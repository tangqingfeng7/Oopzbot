"""退域通知的模板继承、成员快照和昵称降级回归测试。"""

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from core.area_config import AreaConfig, AreaConfigRegistry  # noqa: E402
from services.area_join_notifier import (  # noqa: E402
    _resolve_display_name,
    _run_join_poll_loop,
    make_ws_handler,
)


class LeaveNotificationTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        with patch.object(AreaConfigRegistry, "_load"):
            self.registry = AreaConfigRegistry()
        self.registry.update_config("area-1", {"default_channel": "text-1"})
        self.enterContext(patch("core.area_config.get_area_registry", return_value=self.registry))
        self.resolver = Mock()
        self.resolver.user_cached.return_value = "小明"
        self.enterContext(patch("oopz.name_resolver.get_resolver", return_value=self.resolver))
        self.sender = Mock()
        self.sender.send_message = AsyncMock()
        self.sender.get_person_detail_full = AsyncMock(return_value={"error": "not found"})
        self.sender.get_person_detail = AsyncMock(return_value={"error": "not found"})
        self.sender.get_area_members = AsyncMock(side_effect=[
            {"members": [{"uid": "bot"}, {"uid": "u1"}]},
            {"members": [{"uid": "bot"}]},
            {"members": [{"uid": "bot"}]},
        ])
        self.changed = AsyncMock()

    async def run_poll(self, template="再见 {name}（{uid}）", *, rounds=3, source="member_snapshot"):
        stop = asyncio.Event()
        completed = 0

        async def next_round(event, _seconds):
            nonlocal completed
            completed += 1
            if completed >= rounds:
                event.set()

        with patch("services.area_join_notifier._wait_or_stop", side_effect=next_round):
            await _run_join_poll_loop(
                self.sender, "欢迎 {name}", 5, "bot",
                message_template_leave=template,
                on_member_change=self.changed,
                event_source=source,
                stop_event=stop,
            )

    async def test_snapshot_leave_uses_global_template_and_cached_name_once(self):
        await self.run_poll()
        self.sender.send_message.assert_awaited_once_with(
            "再见 小明（u1）", area="area-1", channel="text-1", auto_recall=False,
        )
        self.sender.get_person_detail_full.assert_not_awaited()
        self.sender.get_person_detail.assert_not_awaited()
        self.changed.assert_awaited_once_with("leave", "area-1", "u1")

    async def test_empty_global_template_suppresses_message_but_keeps_callback(self):
        await self.run_poll(template="")
        self.sender.send_message.assert_not_awaited()
        self.changed.assert_awaited_once_with("leave", "area-1", "u1")

    async def test_area_template_overrides_global(self):
        self.registry.update_config("area-1", {
            "default_channel": "text-1", "leave_message": "{name} 离开了本域",
        })
        await self.run_poll()
        self.assertEqual(self.sender.send_message.await_args.args[0], "小明 离开了本域")

    async def test_failed_snapshot_does_not_report_everyone_leaving(self):
        self.sender.get_area_members.side_effect = [
            {"members": [{"uid": "bot"}, {"uid": "u1"}]},
            {"error": "HTTP 429"},
            {"members": [{"uid": "bot"}, {"uid": "u1"}]},
            {"members": [{"uid": "bot"}]},
        ]
        await self.run_poll(rounds=4)
        self.sender.send_message.assert_awaited_once()
        self.changed.assert_awaited_once_with("leave", "area-1", "u1")

    async def test_incomplete_snapshot_is_not_used_as_leave_baseline(self):
        with patch("services.area_join_notifier.fetch_member_uid_snapshot", AsyncMock(side_effect=[
            ({"bot", "u1"}, False, False),
            ({"bot"}, False, True),
            ({"bot", "u1"}, False, False),
        ])):
            await self.run_poll()
        self.sender.send_message.assert_not_awaited()
        self.changed.assert_not_awaited()

    async def test_send_failure_does_not_lose_member_callback(self):
        self.sender.send_message.side_effect = RuntimeError("send failed")
        await self.run_poll()
        self.changed.assert_awaited_once_with("leave", "area-1", "u1")

    async def test_operate_logs_skip_history_and_repeated_leave(self):
        old = {"optUid": "old-user", "content": "退出域", "createTime": 10}
        fresh = {"optUid": "u1", "content": "退出域", "createTime": 20}
        self.sender.get_area_operate_logs = AsyncMock(side_effect=[
            {"logs": [old]}, {"logs": [fresh, old]}, {"logs": [fresh, old]},
        ])
        await self.run_poll(source="operate_logs")
        self.sender.send_message.assert_awaited_once()
        self.changed.assert_awaited_once_with("leave", "area-1", "u1")

    async def test_ws_leave_obeys_template_and_ignores_voice_leave(self):
        handler = make_ws_handler(self.sender, "欢迎 {name}", "再见 {name}")
        await handler(19, {"body": {"area": "area-1", "person": "u1", "action": "leave"}})
        self.sender.send_message.assert_not_awaited()
        await handler(99, {"body": {"area": "area-1", "person": "u1", "action": "leave"}})
        self.sender.send_message.assert_awaited_once_with(
            "再见 小明", area="area-1", channel="text-1", auto_recall=False,
        )

    async def test_ws_empty_template_sends_no_message(self):
        handler = make_ws_handler(self.sender, "欢迎 {name}", "")
        await handler(99, {"body": {"area": "area-1", "person": "u1", "action": "leave"}})
        self.sender.send_message.assert_not_awaited()

    async def test_name_lookup_tries_basic_profile_after_full_profile_fails(self):
        self.resolver.user_cached.return_value = ""
        self.sender.get_person_detail_full.side_effect = RuntimeError("profile unavailable")
        self.sender.get_person_detail.return_value = {"name": "查询到的昵称"}
        self.assertEqual(await _resolve_display_name(self.sender, "u1"), "查询到的昵称")

    def test_unconfigured_area_does_not_override_global_leave_template(self):
        self.assertEqual(self.registry.get("unconfigured").leave_message, "")
        for value in ({}, {"leave_message": ""}, {"leave_message": None}, {"leave_message": "  "}):
            with self.subTest(value=value):
                cfg = AreaConfig.from_dict("area-1", value)
                self.assertEqual(cfg.leave_message, "")
                self.assertEqual(AreaConfigRegistry.config_to_dict(cfg)["leave_message"], "")


if __name__ == "__main__":
    unittest.main()
