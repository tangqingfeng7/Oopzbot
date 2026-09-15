import asyncio
import inspect
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from config import OOPZ_CONFIG
from core.constants import build_mention
from core.logger_config import get_logger
from oopz.sdk_gateway import AsyncOopzGateway
from oopz_sdk.exceptions.auth import AUTH_FAILURE_STATUS_CODES

logger = get_logger("AreaJoinNotifier")


EVENT_SOURCE_OPERATE_LOGS = "operate_logs"
EVENT_SOURCE_MEMBER_SNAPSHOT = "member_snapshot"
EVENT_SOURCE_CHOICES = (EVENT_SOURCE_OPERATE_LOGS, EVENT_SOURCE_MEMBER_SNAPSHOT)
OPERATE_LOG_MEMBER_OP_TYPES = ["AREA_SUBSCRIBE", "AREA_UNSUBSCRIBE"]
# 401 单次不足以判定无权限：连续这么多轮都失败才切换到成员快照。
# 轮询间隔约 5s，5 轮 ≈ 半分钟，足以跨过一次凭据续期或网络抖动。
OPERATE_LOG_AUTH_FAILURE_LIMIT = 5
OPERATE_LOG_PERMISSION_DENIED_KEYWORDS = (
    "暂无进行此操作的权限",
    "没有权限",
    "无权限",
    "权限不足",
    "permission",
    "forbidden",
)
_JOIN_CONTENT = "\u52a0\u5165\u57df"
_LEAVE_CONTENT = "\u9000\u51fa\u57df"


class AreaMemberSnapshotSource(Protocol):
    """成员快照拉取只依赖发送器的这一项能力。"""

    async def get_area_members(
        self,
        area: str,
        offset_start: int,
        offset_end: int,
        quiet: bool = True,
    ) -> dict:
        ...


@dataclass(frozen=True)
class AreaMemberChange:
    action: str
    area: str
    uid: str
    create_time: int
    content: str

    @property
    def key(self) -> tuple[int, str, str, str]:
        return (self.create_time, self.uid, self.action, self.content)


class AreaOperateLogCursor:
    """记录已消费的域管理日志，避免重复触发成员事件。"""

    def __init__(self, max_seen_per_area: int = 200):
        self.max_seen_per_area = max(20, int(max_seen_per_area))
        self._initialized: set[str] = set()
        self._seen: dict[str, set[tuple[int, str, str, str]]] = {}
        self._order: dict[str, list[tuple[int, str, str, str]]] = {}

    def consume(self, area: str, changes: list[AreaMemberChange]) -> list[AreaMemberChange]:
        area = str(area or "").strip()
        ordered = sorted(changes, key=lambda c: (c.create_time, c.uid, c.action))
        if not area:
            return []
        if area not in self._initialized:
            for change in ordered:
                self._mark_seen(area, change.key)
            self._initialized.add(area)
            logger.info("域成员管理日志检测已就绪 area=%s，已跳过 %d 条历史记录", area, len(ordered))
            return []

        fresh: list[AreaMemberChange] = []
        seen = self._seen.setdefault(area, set())
        for change in ordered:
            if change.key in seen:
                continue
            fresh.append(change)
            self._mark_seen(area, change.key)
        return fresh

    def _mark_seen(self, area: str, key: tuple[int, str, str, str]) -> None:
        seen = self._seen.setdefault(area, set())
        order = self._order.setdefault(area, [])
        if key in seen:
            return
        seen.add(key)
        order.append(key)
        while len(order) > self.max_seen_per_area:
            old = order.pop(0)
            seen.discard(old)


_UID_LIKE = re.compile(
    r"^[0-9a-fA-F]{8}([0-9a-fA-F]*|[\.…]+)$|^[0-9a-fA-F]{1,12}[\.…]+$"
)


def _looks_like_uid(name: str) -> bool:
    if not name or len(name) > 32:
        return False
    s = name.strip()
    if not s:
        return False
    return bool(_UID_LIKE.match(s))


async def _resolve_display_name(
    sender: AsyncOopzGateway,
    uid: str,
    cached: str | None = None,
) -> str:
    if cached and not _looks_like_uid(cached):
        return cached
    try:
        detail = await sender.get_person_detail_full(uid)
        if "error" not in detail:
            for key in ("name", "nickname", "displayName", "userName"):
                val = detail.get(key)
                if val and isinstance(val, str) and val.strip():
                    return val.strip()
        detail = await sender.get_person_detail(uid)
        if "error" not in detail:
            for key in ("name", "nickname", "displayName", "userName"):
                val = detail.get(key)
                if val and isinstance(val, str) and val.strip():
                    return val.strip()
    except Exception:
        pass
    return cached or (uid[:8] + "…" if len(uid) > 8 else uid)


from oopz.area_events import parse_member_event as _parse_member_event

_area_channel_cache: dict = {"area": "", "channel": "", "ts": 0.0}
_AREA_CHANNEL_CACHE_TTL = 300.0  # 5 分钟
def _read_area_channel_cache(now: float) -> tuple[str, str] | None:
    if _area_channel_cache["area"] and _area_channel_cache["channel"] \
            and now - _area_channel_cache["ts"] < _AREA_CHANNEL_CACHE_TTL:
        return _area_channel_cache["area"], _area_channel_cache["channel"]
    return None


def _store_area_channel_cache(area: str, channel: str, ts: float) -> None:
    _area_channel_cache.update(area=area, channel=channel, ts=ts)


async def _get_default_area_channel(
    sender: AsyncOopzGateway,
    quiet: bool = False,
) -> tuple[str, str]:
    """获取默认域 ID 和文字频道 ID（与 WS 通知逻辑一致）。quiet=True 时不打域/频道列表日志。"""
    default_area = (OOPZ_CONFIG.get("default_area") or "").strip()
    default_channel = (OOPZ_CONFIG.get("default_channel") or "").strip()
    if default_area and default_channel:
        return default_area, default_channel

    now = time.time()
    cached = _read_area_channel_cache(now)
    if cached is not None and (not default_area or cached[0] == default_area):
        return cached

    if not default_area:
        areas = await sender.get_joined_areas(quiet=quiet)
        if areas:
            default_area = (areas[0].get("id") or "").strip()
    if default_area:
        for g in await sender.get_area_channels(area=default_area, quiet=quiet):
            for ch in (g.get("channels") or []):
                if (ch.get("type") or "").upper() != "VOICE":
                    default_channel = (ch.get("id") or "").strip()
                    if default_channel:
                        _store_area_channel_cache(default_area, default_channel, now)
                        return default_area, default_channel
    if default_area and default_channel:
        _store_area_channel_cache(default_area, default_channel, now)
    return default_area, default_channel


async def _resolve_area_channel(sender: AsyncOopzGateway, area: str) -> str:
    """只在目标域内解析文字频道，禁止回退到其他域的频道。"""
    from core.area_config import get_area_registry

    registry = get_area_registry()
    channel = registry.get(area).default_channel
    if not channel and area == registry.global_default_area:
        channel = registry.global_default_channel
    if channel:
        return channel
    for group in await sender.get_area_channels(area=area, quiet=True):
        for item in group.get("channels") or []:
            if str(item.get("type") or "").upper() != "VOICE":
                channel = str(item.get("id") or "").strip()
                if channel:
                    return channel
    return ""


def _member_uid(m: dict) -> str:
    """从成员项中取出 uid。"""
    if not isinstance(m, dict):
        return ""
    return (m.get("uid") or m.get("id") or m.get("person") or m.get("personId") or "").strip() or ""


def _next_poll_interval(base_interval: int, current_interval: int, rate_limited: bool) -> int:
    """根据是否被限流，计算下一次轮询间隔。"""
    base = max(5, int(base_interval))
    current = max(base, int(current_interval))
    if not rate_limited:
        return base
    return min(max(current * 2, base), 60)


async def fetch_member_uid_snapshot(
    sender: AreaMemberSnapshotSource,
    area: str,
    member_fetch_max: int = 5000,
) -> tuple[set[str] | None, bool, bool]:
    """分页拉取域成员快照。

    返回 ``(uids, rate_limited, truncated)``：
    - uids 为 None 表示本次拉取失败（rate_limited 标记是否为限流）；
    - truncated=True 表示成员数超过 member_fetch_max、快照不完整，
      调用方必须跳过本轮对比，否则窗口外成员会被误判为加入/退出。
    """
    page_size = 100
    uids: set[str] = set()
    start = 0
    while start < member_fetch_max:
        result = await sender.get_area_members(
            area=area,
            offset_start=start,
            offset_end=start + page_size - 1,
            quiet=True,
        )
        if "error" in result:
            err = str(result.get("error") or "")
            is_rl = err.startswith("HTTP 429") or err in ("invalid JSON", "empty response") or "服务异常" in err
            return None, is_rl, False
        members = result.get("members") or []
        for m in members:
            uid = _member_uid(m)
            if uid:
                uids.add(uid)
        if len(members) < page_size:
            return uids, False, False
        try:
            total = int(result.get("userCount") or result.get("total") or 0)
        except (TypeError, ValueError):
            total = 0
        if total and len(uids) >= total:
            return uids, False, False
        start += page_size
    return uids, False, True


def parse_area_operate_log_changes(area: str, payload: dict) -> list[AreaMemberChange]:
    """从域管理日志接口数据中解析成员加入/退出事件。"""
    if not isinstance(payload, dict):
        return []
    logs = payload.get("logs") or []
    if not isinstance(logs, list):
        return []

    changes: list[AreaMemberChange] = []
    for item in logs:
        if not isinstance(item, dict):
            continue
        uid = str(item.get("optUid") or item.get("uid") or item.get("person") or "").strip()
        content = str(item.get("content") or "").strip()
        if not uid or not content:
            continue
        if content == _JOIN_CONTENT:
            action = "join"
        elif content == _LEAVE_CONTENT:
            action = "leave"
        else:
            continue
        try:
            create_time = int(item.get("createTime") or item.get("time") or item.get("timestamp") or 0)
        except (TypeError, ValueError):
            create_time = 0
        changes.append(
            AreaMemberChange(
                action=action,
                area=area,
                uid=uid,
                create_time=create_time,
                content=content,
            )
        )
    return changes


def is_operate_log_permission_denied(error: str) -> bool:
    """判断域管理日志接口失败是否由权限不足导致。"""
    text = str(error or "").strip()
    lower_text = text.lower()
    return any(keyword in text or keyword in lower_text for keyword in OPERATE_LOG_PERMISSION_DENIED_KEYWORDS)


def is_operate_log_auth_failure(error: str) -> bool:
    """判断失败是否为鉴权类（401/428）。

    平台对「本账号读不了该域的管理日志」也回 401，与凭据失效同码，单次响应
    无法区分，因此调用方需要按连续次数判定，不能一次就永久停掉该域。
    """
    text = str(error or "")
    lower_text = text.lower()
    if "authentication failed" in lower_text or "unauthorized" in lower_text:
        return True
    return any(f"HTTP {code}" in text for code in AUTH_FAILURE_STATUS_CODES)


async def fetch_operate_log_changes(
    sender: AsyncOopzGateway,
    area: str,
) -> tuple[list[AreaMemberChange] | None, bool, str]:
    """拉取一页域管理日志并解析成员变更。"""
    result = await sender.get_area_operate_logs(
        area=area,
        offset=0,
        op_types=OPERATE_LOG_MEMBER_OP_TYPES,
    )
    if "error" in result:
        err = str(result.get("error") or "")
        rate_limited = err.startswith("HTTP 429") or "429" in err
        return None, rate_limited, err
    return parse_area_operate_log_changes(area, result), False, ""


def _build_member_mention(uid: str) -> tuple[str, list]:
    """构造 Oopz 的 @ 用户正文片段和 mentionList。"""
    uid = (uid or "").strip()
    if not uid:
        return "", []
    return (
        f" {build_mention(uid)}",
        [{
            "person": uid,
            "isBot": False,
            "botType": "",
            "offset": -1,
        }],
    )


async def _resolve_role_id(
    sender: AsyncOopzGateway,
    uid: str,
    area: str,
    auto_role_id: str,
    auto_role_name: str,
) -> int | None:
    """将配置中的 role_id / role_name 解析为数字 role_id。"""
    if auto_role_id:
        try:
            return int(auto_role_id)
        except (ValueError, TypeError):
            logger.warning("auto_assign_role_id 非法: %s", auto_role_id)
            return None
    if not auto_role_name:
        return None
    try:
        roles = await sender.get_assignable_roles(uid, area=area)
        for r in roles:
            if str(r.get("name") or "").strip() == auto_role_name.strip():
                return int(r.get("roleID") or r.get("id") or 0) or None
    except Exception as e:
        logger.warning("按名称查找身份组失败 (name=%s): %s", auto_role_name, e)
    return None


async def _try_assign_role(
    sender: AsyncOopzGateway,
    uid: str,
    area: str,
    auto_role_id: str,
    auto_role_name: str,
) -> None:
    """为新成员自动分配身份组，失败仅记录日志。"""
    if not auto_role_id and not auto_role_name:
        return
    role_id = await _resolve_role_id(sender, uid, area, auto_role_id, auto_role_name)
    if role_id is None:
        logger.warning("新人身份组分配跳过: 未能解析 role_id (id=%s, name=%s)", auto_role_id, auto_role_name)
        return
    try:
        result = await sender.edit_user_role(uid, role_id, add=True, area=area)
        if "error" in result:
            logger.warning("新人身份组分配失败 uid=%s role=%s: %s", uid, role_id, result["error"])
        else:
            logger.info("新人身份组分配成功 uid=%s role=%s", uid, role_id)
    except Exception as e:
        logger.warning("新人身份组分配异常 uid=%s role=%s: %s", uid, role_id, e)


async def _wait_or_stop(stop_event: asyncio.Event, delay: float) -> bool:
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=max(0.0, delay))
    except asyncio.TimeoutError:
        return False
    return True


async def _run_join_poll_loop(
    sender: AsyncOopzGateway,
    message_template_join: str,
    interval_seconds: int,
    bot_uid: str,
    auto_role_id: str = "",
    auto_role_name: str = "",
    message_template_leave: str = "",
    on_member_change: Callable[[str, str, str], Awaitable[None] | None] | None = None,
    member_fetch_max: int = 5000,
    event_source: str = EVENT_SOURCE_OPERATE_LOGS,
    stop_event: asyncio.Event | None = None,
) -> None:
    """异步轮询域成员事件，所有网络与等待均在应用事件循环内。"""
    from core.area_config import get_area_registry

    last_uids_map: dict[str, set[str]] = {}
    first_run_set: set[str] = set()
    truncated_warned: set[str] = set()
    operate_log_cursor = AreaOperateLogCursor()
    operate_log_disabled_areas: set[str] = set()
    operate_log_auth_failures: dict[str, int] = {}
    source = event_source if event_source in EVENT_SOURCE_CHOICES else EVENT_SOURCE_OPERATE_LOGS
    stop_event = stop_event or asyncio.Event()
    base_interval = max(5 if source == EVENT_SOURCE_MEMBER_SNAPSHOT else 2, int(interval_seconds))
    current_interval = base_interval

    async def notify(action: str, area_id: str, uid: str) -> None:
        if on_member_change is None:
            return
        try:
            result = on_member_change(action, area_id, uid)
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            logger.warning(
                "成员变更回调失败 action=%s area=%s uid=%s: %s",
                action,
                area_id[:8],
                uid[:8],
                exc,
            )

    async def handle_join(area_id: str, channel: str, uid: str, area_cfg) -> None:
        await _try_assign_role(
            sender,
            uid,
            area_id,
            area_cfg.auto_assign_role_id or auto_role_id,
            area_cfg.auto_assign_role_name or auto_role_name,
        )
        await notify("join", area_id, uid)
        if not channel:
            logger.warning("域成员欢迎跳过: 域 %s 未获取到文字频道 uid=%s", area_id[:8], uid[:8])
            return
        try:
            name = await _resolve_display_name(sender, uid)
            join_msg = area_cfg.welcome_message or message_template_join
            mention_text, mention_list = _build_member_mention(uid)
            await sender.send_message(
                f"{mention_text}\n{join_msg.format(name=name, uid=uid)}",
                area=area_id,
                channel=channel,
                auto_recall=False,
                mentionList=mention_list,
            )
        except Exception as exc:
            logger.warning("域成员欢迎发送失败 area=%s uid=%s: %s", area_id[:8], uid[:8], exc)

    async def handle_leave(area_id: str, channel: str, uid: str, area_cfg) -> None:
        try:
            leave_msg = area_cfg.leave_message or message_template_leave
            if leave_msg and channel:
                name = await _resolve_display_name(sender, uid)
                await sender.send_message(
                    leave_msg.format(name=name, uid=uid),
                    area=area_id,
                    channel=channel,
                    auto_recall=False,
                )
        except Exception as exc:
            logger.warning("域成员退出通知发送失败 area=%s uid=%s: %s", area_id[:8], uid[:8], exc)
        await notify("leave", area_id, uid)

    async def handle_operate_log(area_id: str, channel: str, area_cfg) -> bool:
        changes, rate_limited, error = await fetch_operate_log_changes(sender, area_id)
        if changes is None:
            if is_operate_log_permission_denied(error):
                operate_log_disabled_areas.add(area_id)
                operate_log_auth_failures.pop(area_id, None)
                logger.warning("域管理日志无权限，切换成员快照检测 area=%s: %s", area_id[:8], error)
                return await handle_snapshot(area_id, channel, area_cfg)
            if is_operate_log_auth_failure(error):
                # 401 既可能是「本账号读不了该域的管理日志」，也可能是凭据真的失效。
                # 单次无从区分，连续多轮失败才切换成员快照。
                streak = operate_log_auth_failures.get(area_id, 0) + 1
                operate_log_auth_failures[area_id] = streak
                if streak >= OPERATE_LOG_AUTH_FAILURE_LIMIT:
                    operate_log_disabled_areas.add(area_id)
                    operate_log_auth_failures.pop(area_id, None)
                    logger.warning(
                        "域管理日志连续 %d 轮鉴权失败，切换成员快照检测 area=%s: %s",
                        streak,
                        area_id[:8],
                        error,
                    )
                    return await handle_snapshot(area_id, channel, area_cfg)
                else:
                    logger.warning(
                        "域管理日志鉴权失败（第 %d/%d 轮），暂时跳过 area=%s: %s",
                        streak,
                        OPERATE_LOG_AUTH_FAILURE_LIMIT,
                        area_id[:8],
                        error,
                    )
                return False
            logger.warning("域管理日志轮询失败，跳过本轮 area=%s: %s", area_id[:8], error)
            return rate_limited
        operate_log_auth_failures.pop(area_id, None)
        for change in operate_log_cursor.consume(area_id, changes):
            if not change.uid or change.uid == bot_uid:
                continue
            if change.action == "join":
                await handle_join(area_id, channel, change.uid, area_cfg)
            elif change.action == "leave":
                await handle_leave(area_id, channel, change.uid, area_cfg)
        return False

    async def handle_snapshot(area_id: str, channel: str, area_cfg) -> bool:
        current_uids, rate_limited, truncated = await fetch_member_uid_snapshot(
            sender,
            area_id,
            member_fetch_max,
        )
        if current_uids is None:
            return rate_limited
        if truncated:
            if area_id not in truncated_warned:
                truncated_warned.add(area_id)
                logger.warning(
                    "域 %s 成员数量超过 member_fetch_max=%d，暂停该域快照检测",
                    area_id[:8],
                    member_fetch_max,
                )
            return False
        if area_id not in first_run_set:
            last_uids_map[area_id] = current_uids
            first_run_set.add(area_id)
            logger.info("域成员快照检测已就绪 area=%s，现有成员 %d 人", area_id, len(current_uids))
            return False
        previous = last_uids_map.get(area_id, set())
        last_uids_map[area_id] = current_uids
        for uid in current_uids - previous:
            if uid and uid != bot_uid:
                await handle_join(area_id, channel, uid, area_cfg)
        for uid in previous - current_uids:
            if uid and uid != bot_uid:
                await handle_leave(area_id, channel, uid, area_cfg)
        return False

    async def poll_areas() -> list[str]:
        configured = get_area_registry().get_all_area_ids()
        if configured:
            return configured
        area, _channel = await _get_default_area_channel(sender, quiet=True)
        return [area] if area else []

    while not stop_event.is_set():
        try:
            areas = await poll_areas()
            if not areas:
                logger.warning("域成员加入轮询: 未获取到任何域，请配置 AREA_CONFIGS 或 default_area")
                await _wait_or_stop(stop_event, current_interval)
                continue
            registry = get_area_registry()
            any_rate_limited = False
            for area in areas:
                if stop_event.is_set():
                    return
                area_id = area
                if not area_id:
                    continue
                channel = await _resolve_area_channel(sender, area_id)
                area_cfg = registry.get(area_id)
                if source == EVENT_SOURCE_MEMBER_SNAPSHOT or area_id in operate_log_disabled_areas:
                    rate_limited = await handle_snapshot(area_id, channel, area_cfg)
                else:
                    rate_limited = await handle_operate_log(area_id, channel, area_cfg)
                any_rate_limited = any_rate_limited or rate_limited
            if any_rate_limited:
                current_interval = _next_poll_interval(base_interval, current_interval, True)
            elif current_interval != base_interval:
                current_interval = base_interval
                logger.info("域成员加入轮询: 成员接口已恢复，轮询间隔恢复为 %ss", current_interval)
            await _wait_or_stop(stop_event, current_interval)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("域成员加入轮询异常: %s", exc)
            await _wait_or_stop(stop_event, current_interval)


class AreaJoinNotifier:
    """同时承载 WebSocket 回调和可取消的异步成员轮询任务。"""

    def __init__(self, callback, poll_args: tuple, poll_kwargs: dict):
        self._callback = callback
        self._poll_args = poll_args
        self._poll_kwargs = poll_kwargs
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def __call__(self, event: int, data: dict) -> None:
        await self._callback(event, data)

    def start(self, supervisor=None) -> None:
        if self._task is not None and not self._task.done():
            return
        coroutine = _run_join_poll_loop(
            *self._poll_args,
            **self._poll_kwargs,
            stop_event=self._stop_event,
        )
        self._task = (
            supervisor.create(coroutine, name="area-join-poll")
            if supervisor is not None
            else asyncio.create_task(coroutine, name="area-join-poll")
        )

    async def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        task = self._task
        self._task = None
        if task is None:
            return
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=max(0.0, timeout))
        except asyncio.TimeoutError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            logger.warning("服务停止超时: AreaJoinPoll，任务已取消")


def make_ws_handler(
    sender: AsyncOopzGateway,
    message_template_join: str,
    message_template_leave: str,
):
    from core.area_config import get_area_registry

    bot_uid = (OOPZ_CONFIG.get("person_uid") or "").strip()
    channel_cache: dict[str, str] = {}

    async def resolve_channel(area: str) -> str:
        configured = get_area_registry().get(area).default_channel
        if configured:
            return configured
        if area in channel_cache:
            return channel_cache[area]
        channel = await _resolve_area_channel(sender, area)
        if channel:
            channel_cache[area] = channel
        return channel

    async def on_other_event(event: int, data: dict) -> None:
        parsed = _parse_member_event(event, data)
        if not parsed:
            return
        action, area, uid = parsed
        if uid == bot_uid:
            return
        registry = get_area_registry()
        configured = registry.get_all_area_ids()
        if configured and area not in configured:
            return
        channel = await resolve_channel(area)
        if not channel:
            logger.warning("域成员通知跳过: 域 %s 未获取到默认频道", area[:8])
            return
        area_cfg = registry.get(area)
        try:
            name = await _resolve_display_name(sender, uid)
            if action == "join":
                text = (area_cfg.welcome_message or message_template_join).format(name=name, uid=uid)
                mention_text, mention_list = _build_member_mention(uid)
                await sender.send_message(
                    f"{mention_text}\n{text}",
                    area=area,
                    channel=channel,
                    auto_recall=False,
                    mentionList=mention_list,
                )
            else:
                template = area_cfg.leave_message or message_template_leave
                if template:
                    await sender.send_message(
                        template.format(name=name, uid=uid),
                        area=area,
                        channel=channel,
                        auto_recall=False,
                    )
        except Exception as exc:
            logger.warning("域成员通知发送失败: %s", exc)

    return on_other_event


def start_area_join_notifier(
    sender: AsyncOopzGateway | None = None,
    message_template_join: str = "欢迎 {name} 加入域～",
    message_template_leave: str = "{name} 已退出域",
    on_member_change: Callable[[str, str, str], Awaitable[None] | None] | None = None,
    supervisor=None,
) -> AreaJoinNotifier | None:
    try:
        import config as _config
        config = getattr(_config, "AREA_JOIN_NOTIFY", None)
    except Exception:
        config = None

    if not config or not config.get("enabled", False):
        return None

    msg_join = str(config.get("message_template", message_template_join) or message_template_join)
    if "{name}" not in msg_join and "{uid}" not in msg_join:
        msg_join = "欢迎 {name} 加入域～"
    # 显式留空（"" 或 None）= 不在频道发退出提示，但 OneBot group_decrease 仍会推送。
    raw_leave = config.get("message_template_leave", message_template_leave)
    if raw_leave is None or (isinstance(raw_leave, str) and not raw_leave.strip()):
        msg_leave = ""
    else:
        msg_leave = str(raw_leave)
        if "{name}" not in msg_leave and "{uid}" not in msg_leave:
            msg_leave = "{name} 已退出域"

    if sender is None:
        raise ValueError("启用域成员通知时必须注入 AsyncOopzGateway")
    s = sender
    # 加入事件服务端不推送，用轮询检测新成员并发欢迎
    poll_interval = max(5, int(config.get("poll_interval_seconds", 10)))
    bot_uid = (OOPZ_CONFIG.get("person_uid") or "").strip()
    auto_role_id = str(config.get("auto_assign_role_id") or "").strip()
    auto_role_name = str(config.get("auto_assign_role_name") or "").strip()
    try:
        member_fetch_max = max(200, int(config.get("member_fetch_max", 5000)))
    except (TypeError, ValueError):
        member_fetch_max = 5000
    event_source = str(config.get("event_source") or EVENT_SOURCE_OPERATE_LOGS).strip()
    if event_source not in EVENT_SOURCE_CHOICES:
        logger.warning("AREA_JOIN_NOTIFY.event_source=%s 无效，使用 %s", event_source, EVENT_SOURCE_OPERATE_LOGS)
        event_source = EVENT_SOURCE_OPERATE_LOGS
    if auto_role_id or auto_role_name:
        logger.info("新人自动身份组已启用: id=%s, name=%s", auto_role_id or "(无)", auto_role_name or "(无)")
    notifier = AreaJoinNotifier(
        make_ws_handler(s, msg_join, msg_leave),
        (
            s,
            msg_join,
            poll_interval,
            bot_uid,
            auto_role_id,
            auto_role_name,
            msg_leave,
            on_member_change,
        ),
        {"member_fetch_max": member_fetch_max, "event_source": event_source},
    )
    notifier.start(supervisor)
    return notifier
