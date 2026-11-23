from __future__ import annotations

from oopz_sdk.config.constants import EVENT_AUTH_RESULT, EVENT_SUBSCRIBE_AREA_EVENTS
from oopz_sdk.events.parser import EventParser

# SDK 已识别的消息、频道、语音和系统事件不代表域成员加入或退出。
NON_MEMBER_EVENTS = frozenset(EventParser.EVENT_SPECS) | {
    EVENT_AUTH_RESULT, EVENT_SUBSCRIBE_AREA_EVENTS,
}

_JOIN_KEYS = ("enter", "join", "add", "member_join", "join_area", "subscribe", "1", "enter_area")
_LEAVE_KEYS = ("leave", "exit", "remove", "quit", "member_leave", "leave_area", "unsubscribe", "0")


def parse_member_event(event: int, data: dict) -> tuple[str, str, str] | None:
    """Classify a raw Oopz event as an area member change.

    Returns ``("join"|"leave", area, uid)`` for area-level member changes, or
    ``None`` when the event is not a recognizable member enter/leave (including
    channel-scoped events, which are ignored here).
    """
    try:
        event_int: int | None = int(event)
    except (TypeError, ValueError):
        event_int = None
    if event_int is not None and event_int in NON_MEMBER_EVENTS:
        return None

    body_raw = data.get("body")
    if body_raw is None:
        return None
    body = EventParser.safe_json_parse(body_raw)
    inner = EventParser.safe_json_parse(body.get("data")) or body

    def _extract_id(value, *dict_keys: str) -> str:
        if value is None or isinstance(value, bool):
            return ""
        if isinstance(value, dict):
            for key in dict_keys:
                nested = value.get(key)
                if nested is not None and not isinstance(nested, (bool, dict, list)):
                    text = str(nested).strip()
                    if text:
                        return text
            return ""
        if isinstance(value, (list, tuple, set)):
            return ""
        return str(value).strip()

    def _first_id(candidates, *dict_keys: str) -> str:
        for candidate in candidates:
            extracted = _extract_id(candidate, *dict_keys)
            if extracted:
                return extracted
        return ""

    def _first_action(candidates) -> str:
        for candidate in candidates:
            if candidate is None or isinstance(candidate, (bool, dict, list, tuple, set)):
                continue
            text = str(candidate).strip().lower()
            if text:
                return text
        return ""

    top = data if isinstance(data, dict) else {}
    area = _first_id(
        (
            inner.get("area"),
            inner.get("areaId"),
            body.get("area"),
            body.get("areaId"),
            top.get("area"),
            top.get("areaId"),
        ),
        "id",
        "areaId",
    )
    uid = _first_id(
        (
            inner.get("person"),
            inner.get("uid"),
            inner.get("target"),
            inner.get("userId"),
            body.get("person"),
            body.get("uid"),
            body.get("userId"),
            top.get("person"),
            top.get("uid"),
        ),
        "id",
        "uid",
        "personId",
        "userId",
    )
    if not uid:
        persons = body.get("persons") or inner.get("persons") or []
        if isinstance(persons, list) and persons:
            uid = _extract_id(persons[0], "id", "uid", "personId", "userId")

    action_raw = _first_action(
        (
            inner.get("action"),
            inner.get("type"),
            inner.get("event"),
            inner.get("actionType"),
            body.get("action"),
            body.get("type"),
            body.get("actionType"),
            top.get("action"),
            top.get("type"),
        )
    )

    if not area or not uid:
        return None

    channel_id = _first_id(
        (
            inner.get("channel"),
            inner.get("channelId"),
            body.get("channel"),
            body.get("channelId"),
            top.get("channel"),
            top.get("channelId"),
        ),
        "id",
        "channelId",
    )
    if channel_id:
        return None

    event_str = str(event).lower() if event is not None else ""
    # Oopz has no reliable WS event code for area membership changes, so we never
    # *guess* membership from numeric event codes. Both joins and leaves are
    # covered by area_join_notifier polling (operate logs by default, member-list
    # snapshots when configured). Explicit WS actions remain useful as low-latency
    # supplemental signals.
    is_join = (
        event_str in ("enter", "join", "area_member_enter", "member_enter")
        or action_raw in _JOIN_KEYS
    )
    is_leave = (
        event_str in ("leave", "exit", "area_member_leave", "member_leave")
        or action_raw in _LEAVE_KEYS
    )
    if is_join:
        return ("join", area, uid)
    if is_leave:
        return ("leave", area, uid)

    return None
