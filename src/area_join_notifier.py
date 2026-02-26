"""
域成员加入/退出通知：当用户加入或退出当前域时，Bot 在公屏发送欢迎/再见消息。

- 退出：依赖 WebSocket 推送（event 11 等），有则实时发再见。
- 加入：服务端不推送“加入域”事件，改为轮询域成员 API，发现新成员则发欢迎。
配置 AREA_JOIN_NOTIFY.enabled=True，可选 poll_interval_seconds（默认 1，最小 1）。刚发欢迎后下次轮询仅等 0.5 秒以更快发现连续加入。
"""
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


def _get_default_area_channel(sender: OopzSender, quiet: bool = False) -> Tuple[str, str]:
    """获取默认域 ID 和文字频道 ID（与 WS 通知逻辑一致）。quiet=True 时不打域/频道列表日志。"""
    default_area = (OOPZ_CONFIG.get("default_area") or "").strip()
    default_channel = (OOPZ_CONFIG.get("default_channel") or "").strip()
    if default_area and default_channel:
        return default_area, default_channel
    areas = sender.get_joined_areas(quiet=quiet)
    if areas:
        default_area = (areas[0].get("id") or "").strip()
    if default_area:
        for g in sender.get_area_channels(area=default_area, quiet=quiet):
            for ch in (g.get("channels") or []):
                if (ch.get("type") or "").upper() != "VOICE":
                    default_channel = (ch.get("id") or "").strip()
                    if default_channel:
                        return default_area, default_channel
    return default_area, default_channel


def _member_uid(m: dict) -> str:
    """从成员项中取出 uid。"""
    if not isinstance(m, dict):
        return ""
    return (m.get("uid") or m.get("id") or m.get("person") or m.get("personId") or "").strip() or ""


def _run_join_poll_loop(
    sender: OopzSender,
    message_template_join: str,
    interval_seconds: int,
    bot_uid: str,
) -> None:
    """
    后台轮询域成员列表，发现新加入的成员则发送欢迎消息。
    首次轮询只记录当前成员，不发送；之后每次对比上次集合，多出来的且非 bot 则发欢迎。
    """
    last_uids: Set[str] = set()
    first_run = True
    while True:
        try:
            area, channel = _get_default_area_channel(sender, quiet=True)
            if not area or not channel:
                if first_run:
                    logger.warning("域成员加入轮询: 未获取到默认域/频道，请配置 default_area 与 default_channel")
                time.sleep(interval_seconds)
                continue
            # 拉取前 100 个成员（API offsetEnd 为闭区间）
            result = sender.get_area_members(area=area, offset_start=0, offset_end=99, quiet=True)
            if "error" in result:
                time.sleep(interval_seconds)
                continue
            members = result.get("members") or []
            current_uids = {_member_uid(m) for m in members if _member_uid(m)}
            sent_welcome = False
            if first_run:
                last_uids = current_uids
                first_run = False
            else:
                new_uids = current_uids - last_uids
                last_uids = current_uids
                for uid in new_uids:
                    if not uid or uid == bot_uid:
                        continue
                    try:
                        name = _resolve_display_name(sender, uid, None)
                        text = message_template_join.format(name=name, uid=uid)
                        sender.send_message(text, area=area, channel=channel, auto_recall=False)
                        sent_welcome = True
                    except Exception as e:
                        logger.warning("域成员欢迎发送失败 uid=%s: %s", uid, e)
            # 刚发过欢迎则 0.5 秒后即下次轮询，否则按配置间隔
            time.sleep(0.5 if sent_welcome else interval_seconds)
        except Exception as e:
            logger.warning("域成员加入轮询异常: %s", e)
            time.sleep(interval_seconds)


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
    bot_uid = (OOPZ_CONFIG.get("person_uid") or "").strip()
    default_area = (OOPZ_CONFIG.get("default_area") or "").strip()
    default_channel = (OOPZ_CONFIG.get("default_channel") or "").strip()

    def _ensure_area_channel() -> Tuple[str, str]:
        nonlocal default_area, default_channel
        if default_area and default_channel:
            return default_area, default_channel
        areas = sender.get_joined_areas()
        if areas:
            default_area = (areas[0].get("id") or "").strip()
        if default_area:
            for g in sender.get_area_channels(area=default_area):
                for ch in (g.get("channels") or []):
                    if (ch.get("type") or "").upper() != "VOICE":
                        default_channel = (ch.get("id") or "").strip()
                        if default_channel:
                            return default_area, default_channel
        return default_area, default_channel

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
        a, ch = _ensure_area_channel()
        if not ch:
            logger.warning("域成员通知跳过: 未获取到默认频道，请配置 default_channel 或确保域下有文字频道")
            return
        if a and area != a:
            return
        try:
            name = _resolve_display_name(sender, uid, None)
            if action == "join":
                text = message_template_join.format(name=name, uid=uid)
            else:
                text = message_template_leave.format(name=name, uid=uid)
            sender.send_message(text, area=a, channel=ch, auto_recall=False)
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
    poll_interval = max(1, int(config.get("poll_interval_seconds", 1)))
    bot_uid = (OOPZ_CONFIG.get("person_uid") or "").strip()
    poll_thread = threading.Thread(
        target=_run_join_poll_loop,
        args=(s, msg_join, poll_interval, bot_uid),
        daemon=True,
        name="AreaJoinPoll",
    )
    poll_thread.start()
    return make_ws_handler(s, msg_join, msg_leave)
