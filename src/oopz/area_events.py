from __future__ import annotations

import json

# Authoritative Oopz WS event codes (source: Oopzbot-SDK
# oopz_sdk/config/constants.py, cross-checked against captured ws_capture
# samples). These have confirmed, non-membership meanings and must never be
# read as area member changes — e.g. 19/20 are voice-channel leave/enter,
# 11/12 are channel mute / text-ban, 18 is a channel-setting change. Treating
# them as joins/leaves previously caused false group_increase / group_decrease.
NON_MEMBER_EVENTS = frozenset({
    1, 2, 4, 6, 7, 8, 9, 11, 12, 13, 18, 19, 20,
    25, 26, 27, 28, 32, 52, 56, 57, 249, 253, 254,
})

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
