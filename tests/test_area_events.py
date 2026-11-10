import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from oopz.area_events import parse_member_event  # noqa: E402


def _raw(event: int, body: dict) -> dict:
    return {"event": event, "body": json.dumps(body)}


class AreaEventsTest(unittest.TestCase):
    def test_voice_leave_event_is_not_member_change(self) -> None:
        # event 19 = 退出语音频道 (SDK 权威)。历史上 channel 空 + activeNum 0 会被误判为域退出。
        raw = _raw(19, {"area": "area-1", "channel": "", "persons": ["u1"], "activeNum": 0, "sound": ""})
        self.assertIsNone(parse_member_event(19, raw))

    def test_voice_enter_event_is_not_member_change(self) -> None:
        # event 20 = 进入语音频道。
        raw = _raw(20, {"area": "area-1", "channel": "c1", "persons": ["u1"], "activeNum": 3, "sort": 1})
        self.assertIsNone(parse_member_event(20, raw))

    def test_channel_update_event_is_not_member_change(self) -> None:
        # event 18 = 频道设置改变。
        raw = _raw(18, {"area": "area-1", "channel": "c1", "name": "x"})
        self.assertIsNone(parse_member_event(18, raw))

    def test_voice_ban_event_is_not_member_change(self) -> None:
        # event 11 = 频道禁麦，曾与旧的 EVENT_AREA_MEMBER_LEAVE=11 冲突。
        raw = _raw(11, {"area": "area-1", "person": "u1", "disableTo": "0"})
        self.assertIsNone(parse_member_event(11, raw))

    def test_reaction_event_is_not_member_change(self) -> None:
        # event 32 = 消息 reaction。
        raw = _raw(32, {"area": "area-1", "person": "u1", "emoji": "x"})
        self.assertIsNone(parse_member_event(32, raw))

    def test_numeric_code_alone_is_not_a_join(self) -> None:
        # WS join heuristic removed: a bare event code without an explicit action
        # is no longer guessed as a join (joins come from member-list polling).
        raw = _raw(17, {"area": "area-1", "person": "u1"})
        self.assertIsNone(parse_member_event(17, raw))

    def test_explicit_join_action_is_classified(self) -> None:
        raw = _raw(99, {"area": "area-1", "person": "u1", "action": "join"})
        self.assertEqual(parse_member_event(99, raw), ("join", "area-1", "u1"))

    def test_explicit_leave_action_is_classified(self) -> None:
        raw = _raw(99, {"area": "area-1", "person": "u1", "action": "leave"})
        self.assertEqual(parse_member_event(99, raw), ("leave", "area-1", "u1"))

    def test_channel_scoped_event_is_ignored(self) -> None:
        raw = _raw(99, {"area": "area-1", "channel": "c1", "person": "u1", "action": "join"})
        self.assertIsNone(parse_member_event(99, raw))

    def test_nested_member_payload_accepts_dict_and_json(self) -> None:
        member = {"area": "area-1", "person": "u1", "action": "leave"}
        for inner in (member, json.dumps(member)):
            with self.subTest(inner=inner):
                raw = _raw(99, {"data": inner})
                self.assertEqual(parse_member_event(99, raw), ("leave", "area-1", "u1"))

    def test_system_events_do_not_trigger_member_notifications(self) -> None:
        for event in (21, 249, 253, 254):
            with self.subTest(event=event):
                raw = _raw(event, {"area": "area-1", "person": "u1", "action": "join"})
                self.assertIsNone(parse_member_event(event, raw))
