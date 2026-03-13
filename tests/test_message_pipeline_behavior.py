import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


class MessageContextTest(unittest.TestCase):
    def test_message_context_normalizes_message_payload(self) -> None:
        from app.services.routing.command_message_service import MessageContext

        ctx = MessageContext.from_message(
            {
                "content": "  /help  ",
                "channel": "channel-1",
                "area": "area-1",
                "person": "user-1",
                "messageId": "msg-1",
                "timestamp": "ts-1",
            }
        )

        self.assertEqual(ctx.content, "/help")
        self.assertEqual(ctx.channel, "channel-1")
        self.assertEqual(ctx.area, "area-1")
        self.assertEqual(ctx.user, "user-1")
        self.assertEqual(ctx.message_id, "msg-1")
        self.assertEqual(ctx.timestamp, "ts-1")
        self.assertTrue(ctx.is_slash_command())
        self.assertFalse(ctx.is_mention_command("(met)bot(met)"))

    def test_message_context_extracts_mention_text(self) -> None:
        from app.services.routing.command_message_service import MessageContext

        ctx = MessageContext.from_message(
            {
                "content": "(met)bot(met) 帮助",
                "channel": "channel-1",
                "area": "area-1",
                "person": "user-1",
                "messageId": "msg-1",
            }
        )

        self.assertTrue(ctx.is_mention_command("(met)bot(met)"))
        self.assertTrue(ctx.is_command("(met)bot(met)"))
        self.assertEqual(ctx.mention_text("(met)bot(met)"), "帮助")


class CommandMessageServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sender = Mock()
        self.chat = Mock()
        self.access = Mock()
        self.profanity = Mock()
        self.command = Mock()
        self.handler = SimpleNamespace(
            infrastructure=SimpleNamespace(sender=self.sender, chat=self.chat),
            services=SimpleNamespace(
                routing=SimpleNamespace(access=self.access, command=self.command),
                safety=SimpleNamespace(profanity=self.profanity),
            ),
            _recent_messages=[],
        )

    def _build_service(self):
        from app.services.routing.command_message_service import CommandMessageService

        return CommandMessageService(self.handler, bot_uid="bot-uid", bot_mention="(met)bot(met)")

    def test_remember_message_appends_and_limits_recent_messages(self) -> None:
        from app.services.routing.command_message_service import MessageContext

        service = self._build_service()
        for index in range(55):
            ctx = MessageContext(
                raw={},
                content=f"message-{index}",
                channel="channel",
                area="area",
                user="user",
                message_id=f"id-{index}",
                timestamp=f"ts-{index}",
            )
            service.remember_message(ctx)

        self.assertEqual(len(self.handler._recent_messages), 50)
        self.assertEqual(self.handler._recent_messages[0]["messageId"], "id-5")
        self.assertEqual(self.handler._recent_messages[-1]["messageId"], "id-54")

    def test_handle_profanity_short_circuits_on_direct_keyword_match(self) -> None:
        from app.services.routing.command_message_service import MessageContext
        import app.services.routing.command_message_service as module

        service = self._build_service()
        ctx = MessageContext(
            raw={},
            content="坏词",
            channel="channel",
            area="area",
            user="user-1",
            message_id="msg-1",
            timestamp="ts-1",
        )
        self.profanity.check_profanity.return_value = "坏词"

        with patch.object(module, "PROFANITY_CONFIG", {"enabled": True, "skip_admins": False}):
            result = service.handle_profanity(ctx)

        self.assertTrue(result)
        self.profanity.handle_profanity.assert_called_once_with(
            "user-1",
            "channel",
            "area",
            "坏词",
            [{"message_id": "msg-1", "channel": "channel", "area": "area", "timestamp": "ts-1"}],
        )

    def test_handle_profanity_can_use_ai_context_detection(self) -> None:
        from app.services.routing.command_message_service import MessageContext
        import app.services.routing.command_message_service as module

        service = self._build_service()
        ctx = MessageContext(
            raw={},
            content="第一句",
            channel="channel",
            area="area",
            user="user-1",
            message_id="msg-1",
            timestamp="ts-1",
        )
        self.profanity.check_profanity.return_value = None
        self.profanity.check_context_profanity.return_value = None
        self.profanity.clean_text.return_value = "第一句"
        self.profanity.get_user_buffer.return_value = [
            {"content": "第一句"},
            {"content": "第二句"},
        ]
        self.chat.check_profanity.side_effect = [None, "拼接违规"]

        config = {
            "enabled": True,
            "skip_admins": False,
            "context_detection": True,
            "ai_detection": True,
            "ai_min_length": 2,
        }
        with patch.object(module, "PROFANITY_CONFIG", config):
            result = service.handle_profanity(ctx)

        self.assertTrue(result)
        self.profanity.push_user_buffer.assert_called_once_with(
            "user-1",
            "第一句",
            "msg-1",
            "channel",
            "area",
            "ts-1",
        )
        self.profanity.handle_profanity.assert_called_once_with(
            "user-1",
            "channel",
            "area",
            "AI:拼接违规",
            list(self.profanity.get_user_buffer.return_value),
        )

    def test_reject_unauthorized_command_sends_denial_message(self) -> None:
        from app.services.routing.command_message_service import MessageContext

        service = self._build_service()
        ctx = MessageContext(
            raw={},
            content="/ban user",
            channel="channel",
            area="area",
            user="user-1",
            message_id="msg-1",
            timestamp="ts-1",
        )
        self.access.is_admin.return_value = False
        self.access.is_public_command.return_value = False

        result = service.reject_unauthorized_command(ctx)

        self.assertTrue(result)
        self.sender.send_message.assert_called_once()
        self.assertIn("无权限", self.sender.send_message.call_args.args[0])


class CommandRouterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.mention = Mock()
        self.slash = Mock()
        self.chat = Mock()
        self.recall_scheduler = Mock()
        self.handler = SimpleNamespace(
            services=SimpleNamespace(
                routing=SimpleNamespace(mention=self.mention, slash=self.slash),
                interaction=SimpleNamespace(chat=self.chat),
                safety=SimpleNamespace(recall_scheduler=self.recall_scheduler),
            )
        )

    def _build_router(self):
        from app.services.routing.command_router import CommandRouter

        return CommandRouter(self.handler, bot_mention="(met)bot(met)")

    def test_route_mention_dispatches_and_schedules_recall(self) -> None:
        from app.services.routing.command_message_service import MessageContext

        router = self._build_router()
        ctx = MessageContext(
            raw={},
            content="(met)bot(met) 帮助",
            channel="channel",
            area="area",
            user="user-1",
            message_id="msg-1",
            timestamp="ts-1",
        )

        router.route(ctx)

        self.mention.dispatch.assert_called_once_with("帮助", "channel", "area", "user-1")
        self.recall_scheduler.schedule_user_message_recall.assert_called_once_with(
            "msg-1",
            "channel",
            "area",
            "ts-1",
        )

    def test_route_slash_dispatches_and_schedules_recall(self) -> None:
        from app.services.routing.command_message_service import MessageContext

        router = self._build_router()
        ctx = MessageContext(
            raw={},
            content="/help",
            channel="channel",
            area="area",
            user="user-1",
            message_id="msg-1",
            timestamp="ts-1",
        )

        router.route(ctx)

        self.slash.dispatch.assert_called_once_with("/help", "channel", "area", "user-1")
        self.recall_scheduler.schedule_user_message_recall.assert_called_once_with(
            "msg-1",
            "channel",
            "area",
            "ts-1",
        )

    def test_route_plain_chat_delegates_to_chat_service(self) -> None:
        from app.services.routing.command_message_service import MessageContext

        router = self._build_router()
        ctx = MessageContext(
            raw={},
            content="普通聊天",
            channel="channel",
            area="area",
            user="user-1",
            message_id="msg-1",
            timestamp="ts-1",
        )

        router.route(ctx)

        self.chat.handle_plain_chat.assert_called_once_with("普通聊天", "channel", "area")
        self.recall_scheduler.schedule_user_message_recall.assert_not_called()


if __name__ == "__main__":
    unittest.main()
