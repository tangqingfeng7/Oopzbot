import json
import re
import threading
import time
from typing import Optional, Tuple, Callable, Set

from config import OOPZ_CONFIG
from oopz_sender import OopzSender
from logger_config import get_logger

logger = get_logger("AreaJoinNotifier")


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


def _resolve_display_name(sender: OopzSender, uid: str, cached: Optional[str] = None) -> str:
    if cached and not _looks_like_uid(cached):
        return cached
    try:
        detail = sender.get_person_detail_full(uid)
        if "error" not in detail:
            for key in ("name", "nickname", "displayName", "userName"):
                val = detail.get(key)
                if val and isinstance(val, str) and val.strip():
                    return val.strip()
        detail = sender.get_person_detail(uid)
        if "error" not in detail:
            for key in ("name", "nickname", "displayName", "userName"):
                val = detail.get(key)
                if val and isinstance(val, str) and val.strip():
                    return val.strip()
    except Exception:
        pass
    return cached or (uid[:8] + "…" if len(uid) > 8 else uid)


EVENT_AREA_MEMBER_ENTER = 10
EVENT_AREA_MEMBER_LEAVE = 11


_area_channel_cache: dict = {"area": "", "channel": "", "ts": 0.0}
_AREA_CHANNEL_CACHE_TTL = 300.0  # 5 分钟


def _get_default_area_channel(sender: OopzSender, quiet: bool = False) -> Tuple[str, str]:
    """获取默认域 ID 和文字频道 ID（与 WS 通知逻辑一致）。quiet=True 时不打域/频道列表日志。"""
    default_area = (OOPZ_CONFIG.get("default_area") or "").strip()
    default_channel = (OOPZ_CONFIG.get("default_channel") or "").strip()
    if default_area and default_channel:
        return default_area, default_channel

    now = time.time()
    if _area_channel_cache["area"] and _area_channel_cache["channel"] \
            and now - _area_channel_cache["ts"] < _AREA_CHANNEL_CACHE_TTL:
        return _area_channel_cache["area"], _area_channel_cache["channel"]

    areas = sender.get_joined_areas(quiet=quiet)
    if areas:
        default_area = (areas[0].get("id") or "").strip()
    if default_area:
        for g in sender.get_area_channels(area=default_area, quiet=quiet):
            for ch in (g.get("channels") or []):
                if (ch.get("type") or "").upper() != "VOICE":
                    default_channel = (ch.get("id") or "").strip()
                    if default_channel:
                        _area_channel_cache.update(area=default_area, channel=default_channel, ts=now)
                        return default_area, default_channel
    if default_area and default_channel:
        _area_channel_cache.update(area=default_area, channel=default_channel, ts=now)
    return default_area, default_channel


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


def _build_member_mention(uid: str) -> Tuple[str, list]:
    """构造 Oopz 的 @ 用户正文片段和 mentionList。"""
    uid = (uid or "").strip()
    if not uid:
        return "", []
    return (
        f" (met){uid}(met)",
        [{
            "person": uid,
            "isBot": False,
            "botType": "",
            "offset": -1,
        }],
    )


def _resolve_role_id(
    sender: OopzSender,
    uid: str,
    area: str,
    auto_role_id: str,
    auto_role_name: str,
) -> Optional[int]:
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
        roles = sender.get_assignable_roles(uid, area=area)
        for r in roles:
            if str(r.get("name") or "").strip() == auto_role_name.strip():
                return int(r.get("roleID") or r.get("id") or 0) or None
    except Exception as e:
        logger.warning("按名称查找身份组失败 (name=%s): %s", auto_role_name, e)
    return None


def _try_assign_role(
    sender: OopzSender,
    uid: str,
    area: str,
    auto_role_id: str,
    auto_role_name: str,
) -> None:
    """为新成员自动分配身份组，失败仅记录日志。"""
    if not auto_role_id and not auto_role_name:
        return
    role_id = _resolve_role_id(sender, uid, area, auto_role_id, auto_role_name)
    if role_id is None:
        logger.warning("新人身份组分配跳过: 未能解析 role_id (id=%s, name=%s)", auto_role_id, auto_role_name)
        return
    try:
        result = sender.edit_user_role(uid, role_id, add=True, area=area)
        if "error" in result:
            logger.warning("新人身份组分配失败 uid=%s role=%s: %s", uid, role_id, result["error"])
        else:
            logger.info("新人身份组分配成功 uid=%s role=%s", uid, role_id)
    except Exception as e:
        logger.warning("新人身份组分配异常 uid=%s role=%s: %s", uid, role_id, e)


def _run_join_poll_loop(
    sender: OopzSender,
    message_template_join: str,
    interval_seconds: int,
    bot_uid: str,
    auto_role_id: str = "",
    auto_role_name: str = "",
) -> None:
    """
    后台轮询域成员列表，发现新加入的成员则发送欢迎消息。
    支持多域：遍历 AreaConfigRegistry 中的所有域，每个域独立维护成员快照。
    首次轮询只记录当前成员，不发送；之后每次对比上次集合，多出来的且非 bot 则发欢迎。
    """
    from area_config import get_area_registry

    last_uids_map: dict[str, Set[str]] = {}
    first_run_set: Set[str] = set()

    current_interval = max(5, int(interval_seconds))

    def _fetch_member_uids(area: str) -> Tuple[Optional[Set[str]], bool]:
        page_size = 100
        max_fetch = 1000
        uids: Set[str] = set()
        for start in range(0, max_fetch, page_size):
            result = sender.get_area_members(
                area=area,
                offset_start=start,
                offset_end=start + page_size - 1,
                quiet=True,
            )
            if "error" in result:
                err = str(result.get("error") or "")
                is_rl = err.startswith("HTTP 429") or err in ("invalid JSON", "empty response") or "服务异常" in err
                return None, is_rl
            members = result.get("members") or []
            for m in members:
                uid = _member_uid(m)
                if uid:
                    uids.add(uid)
            if len(members) < page_size:
                break
        return uids, False

    def _resolve_area_channel(area_id: str) -> Tuple[str, str]:
        registry = get_area_registry()
        ch = registry.get_default_channel(area_id)
        if ch:
            return area_id, ch
        return _get_default_area_channel(sender, quiet=True)

    def _get_poll_areas() -> list[str]:
        registry = get_area_registry()
        area_ids = registry.get_all_area_ids()
        if area_ids:
            return area_ids
        a, _ = _get_default_area_channel(sender, quiet=True)
        return [a] if a else []

    while True:
        try:
            poll_areas = _get_poll_areas()
            if not poll_areas:
                if not last_uids_map:
                    logger.warning("域成员加入轮询: 未获取到任何域，请配置 AREA_CONFIGS 或 default_area")
                time.sleep(current_interval)
                continue

            registry = get_area_registry()
            any_rate_limited = False

            for area in poll_areas:
                area_channel = _resolve_area_channel(area)
                area_id, channel = area_channel
                if not area_id or not channel:
                    continue

                area_cfg = registry.get(area_id)
                current_uids, rate_limited = _fetch_member_uids(area_id)

                if current_uids is None:
                    any_rate_limited = any_rate_limited or rate_limited
                    continue

                is_first = area_id not in first_run_set
                if is_first:
                    last_uids_map[area_id] = current_uids
                    first_run_set.add(area_id)
                else:
                    prev = last_uids_map.get(area_id, set())
                    new_uids = current_uids - prev
                    last_uids_map[area_id] = current_uids
                    for uid in new_uids:
                        if not uid or uid == bot_uid:
                            continue
                        try:
                            name = _resolve_display_name(sender, uid, None)
                            join_msg = area_cfg.welcome_message if area_cfg.welcome_message else message_template_join
                            text = join_msg.format(name=name, uid=uid)
                            mention_text, mention_list = _build_member_mention(uid)
                            sender.send_message(
                                f"{mention_text}\n{text}",
                                area=area_id,
                                channel=channel,
                                auto_recall=False,
                                mentionList=mention_list,
                            )
                        except Exception as e:
                            logger.warning("域成员欢迎发送失败 area=%s uid=%s: %s", area_id[:8], uid[:8], e)
                        a_role_id = area_cfg.auto_assign_role_id or auto_role_id
                        a_role_name = area_cfg.auto_assign_role_name or auto_role_name
                        _try_assign_role(sender, uid, area_id, a_role_id, a_role_name)

            if any_rate_limited:
                next_interval = _next_poll_interval(interval_seconds, current_interval, True)
                if next_interval != current_interval:
                    logger.warning("域成员加入轮询: 检测到限流，轮询间隔调整为 %ss", next_interval)
                current_interval = next_interval
            elif current_interval != max(5, int(interval_seconds)):
                current_interval = max(5, int(interval_seconds))
                logger.info("域成员加入轮询: 成员接口已恢复，轮询间隔恢复为 %ss", current_interval)

            time.sleep(current_interval)
        except Exception as e:
            logger.warning("域成员加入轮询异常: %s", e)
            time.sleep(current_interval)


def _parse_member_event(event: int, data: dict) -> Optional[Tuple[str, str, str]]:
    body_raw = data.get("body")
    if body_raw is None:
        return None
    if isinstance(body_raw, str):
        try:
            body = json.loads(body_raw)
        except json.JSONDecodeError:
            body = {}
    else:
        body = body_raw

    inner = body.get("data")
    if isinstance(inner, str):
        try:
            inner = json.loads(inner)
        except json.JSONDecodeError:
            inner = {}
    if not inner and isinstance(body.get("data"), dict):
        inner = body["data"]
    if not inner:
        inner = body

    def _str_uid(v) -> str:
        if v is None:
            return ""
        if isinstance(v, dict):
            return str(v.get("id") or v.get("uid") or v.get("personId") or v.get("userId") or "").strip()
        return str(v).strip()

    top = data if isinstance(data, dict) else {}
    area = (inner.get("area") or inner.get("areaId") or body.get("area") or body.get("areaId") or top.get("area") or top.get("areaId") or "").strip()
    if not area and isinstance(inner.get("area"), dict):
        area = str(inner["area"].get("id") or inner["area"].get("areaId") or "").strip()
    uid = _str_uid(inner.get("person")) or _str_uid(inner.get("uid")) or _str_uid(inner.get("target")) or inner.get("userId") or _str_uid(body.get("person")) or body.get("uid") or body.get("userId") or _str_uid(top.get("person")) or top.get("uid") or ""
    if not uid:
        persons = body.get("persons") or inner.get("persons") or []
        if isinstance(persons, list) and persons:
            uid = _str_uid(persons[0]) if isinstance(persons[0], dict) else str(persons[0]).strip()
        else:
            uid = ""

    action_raw = (inner.get("action") or inner.get("type") or inner.get("event") or inner.get("actionType") or body.get("action") or body.get("type") or body.get("actionType") or top.get("action") or top.get("type") or "").strip().lower()

    if not area or not uid:
        return None

    channel_id = (inner.get("channel") or inner.get("channelId") or body.get("channel") or body.get("channelId") or top.get("channel") or top.get("channelId") or "")
    if isinstance(channel_id, dict):
        channel_id = str(channel_id.get("id") or channel_id.get("channelId") or "").strip()
    else:
        channel_id = str(channel_id).strip() if channel_id else ""
    if channel_id:
        return None

    active_num = body.get("activeNum") if isinstance(body.get("activeNum"), (int, float)) else None
    if active_num is None:
        active_num = inner.get("activeNum")

    join_keys = ("enter", "join", "add", "member_join", "join_area", "subscribe", "1", "enter_area")
    leave_keys = ("leave", "exit", "remove", "quit", "member_leave", "leave_area", "unsubscribe", "0")
    event_str = str(event).lower() if event is not None else ""
    oopz_join_events = (17, 18, 20, 21, 22)
    if event == 19:
        if active_num is not None and active_num != 0:
            return ("join", area, uid)
        return ("leave", area, uid)
    is_join = (
        event == EVENT_AREA_MEMBER_ENTER
        or event in oopz_join_events
        or event_str in ("10", "17", "18", "20", "21", "22", "enter", "join", "area_member_enter", "member_enter")
        or action_raw in join_keys
    )
    is_leave = (
        event == EVENT_AREA_MEMBER_LEAVE
        or event_str in ("11", "leave", "exit", "area_member_leave", "member_leave")
        or action_raw in leave_keys
    )
    if is_join:
        return ("join", area, uid)
    if is_leave:
        return ("leave", area, uid)

    return None


def make_ws_handler(
    sender: OopzSender,
    message_template_join: str,
    message_template_leave: str,
) -> Callable[[int, dict], None]:
    from area_config import get_area_registry

    bot_uid = (OOPZ_CONFIG.get("person_uid") or "").strip()
    _channel_cache: dict[str, str] = {}

    def _resolve_channel_for_area(area: str) -> str:
        if area in _channel_cache:
            return _channel_cache[area]
        registry = get_area_registry()
        ch = registry.get_default_channel(area)
        if ch:
            _channel_cache[area] = ch
            return ch
        for g in sender.get_area_channels(area=area, quiet=True):
            for c in (g.get("channels") or []):
                if (c.get("type") or "").upper() != "VOICE":
                    ch_id = (c.get("id") or "").strip()
                    if ch_id:
                        _channel_cache[area] = ch_id
                        return ch_id
        return ""

    _IGNORE_EVENTS = (0,)

    def _on_other_event(event: int, data: dict):
        parsed = _parse_member_event(event, data)
        if not parsed:
            if event in _IGNORE_EVENTS:
                return
            return
        action, area, uid = parsed
        if uid == bot_uid:
            return

        registry = get_area_registry()
        configured_areas = registry.get_all_area_ids()
        if configured_areas and area not in configured_areas:
            return

        ch = _resolve_channel_for_area(area)
        if not ch:
            logger.warning("域成员通知跳过: 域 %s 未获取到默认频道", area[:8])
            return

        area_cfg = registry.get(area)
        try:
            name = _resolve_display_name(sender, uid, None)
            if action == "join":
                join_msg = area_cfg.welcome_message or message_template_join
                text = join_msg.format(name=name, uid=uid)
                mention_text, mention_list = _build_member_mention(uid)
                sender.send_message(
                    f"{mention_text}\n{text}",
                    area=area,
                    channel=ch,
                    auto_recall=False,
                    mentionList=mention_list,
                )
            else:
                leave_msg = area_cfg.leave_message or message_template_leave
                text = leave_msg.format(name=name, uid=uid)
                sender.send_message(text, area=area, channel=ch, auto_recall=False)
        except Exception as e:
            logger.warning("域成员通知发送失败: %s", e)

    return _on_other_event


def start_area_join_notifier(
    sender: Optional[OopzSender] = None,
    message_template_join: str = "欢迎 {name} 加入域～",
    message_template_leave: str = "{name} 已退出域",
) -> Optional[Callable[[int, dict], None]]:
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
    msg_leave = str(config.get("message_template_leave", message_template_leave) or message_template_leave)
    if "{name}" not in msg_leave and "{uid}" not in msg_leave:
        msg_leave = "{name} 已退出域"

    s = sender or OopzSender()
    # 加入事件服务端不推送，用轮询检测新成员并发欢迎
    poll_interval = max(5, int(config.get("poll_interval_seconds", 10)))
    bot_uid = (OOPZ_CONFIG.get("person_uid") or "").strip()
    auto_role_id = str(config.get("auto_assign_role_id") or "").strip()
    auto_role_name = str(config.get("auto_assign_role_name") or "").strip()
    if auto_role_id or auto_role_name:
        logger.info("新人自动身份组已启用: id=%s, name=%s", auto_role_id or "(无)", auto_role_name or "(无)")
    poll_thread = threading.Thread(
        target=_run_join_poll_loop,
        args=(s, msg_join, poll_interval, bot_uid, auto_role_id, auto_role_name),
        daemon=True,
        name="AreaJoinPoll",
    )
    poll_thread.start()
    return make_ws_handler(s, msg_join, msg_leave)