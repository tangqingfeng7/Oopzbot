"""SDK 会话与应用发送器、语音控制器的生命周期契约。"""

import asyncio
import sys
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from oopz_sdk.models import Message
from oopz_sdk.testing.factories import make_config

from app.infrastructure.runtime import build_bot_infrastructure
from app.lifecycle import oopz_session
from core.proxy_utils import ProxySettings
from music.voice_browser import ProjectBrowserVoiceTransport


class OopzSessionTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.config = patch.object(
            oopz_session, "build_bot_config",
            AsyncMock(side_effect=lambda *args: (make_config(), ProxySettings(mode="direct"), False)),
        )
        self.config.start()
        self.addCleanup(self.config.stop)
        self.session = await oopz_session.OopzSession.create()
        self.addAsyncCleanup(self.session.stop)

    async def test_runtime_shares_one_sender_and_sdk_instance(self):
        sender = self.session.sender
        infrastructure = build_bot_infrastructure(sender)
        self.assertIs(infrastructure.sender, sender)
        self.assertIs(sender.bot, self.session.bot)
        self.assertIs(sender.bot.messages, self.session.bot.rest.messages)
        self.assertIs(sender.bot.messages.transport, self.session.bot.rest.transport)
        backend = sender.bot.voice.backend
        self.assertIsInstance(backend, ProjectBrowserVoiceTransport)
        assert isinstance(backend, ProjectBrowserVoiceTransport)
        self.assertTrue(backend._voice_html_path().is_file())

    async def test_credentials_update_rebinds_sender_and_voice(self):
        sender = self.session.sender
        old_bot = sender.bot
        voice = Mock(destroy=AsyncMock())
        self.session.voice = voice
        recall = Mock()
        sender.bind_auto_recall_scheduler(recall)

        with patch.object(old_bot, "stop", AsyncMock()) as stop:
            assert sender.rebuild_credentials is not None
            await sender.rebuild_credentials(cast(Any, object()))

        stop.assert_awaited_once()
        self.assertIs(self.session.sender, sender)
        self.assertIs(sender.bot, self.session.bot)
        self.assertIsNot(sender.bot, old_bot)
        self.assertIs(sender._auto_recall_scheduler, recall)
        voice.destroy.assert_awaited_once()
        voice.bind_service.assert_called_once_with(self.session.bot.voice, proxy_value=False)
        await old_bot.stop()

    async def test_failed_rebuild_restores_shared_sender_and_voice(self):
        old_bot = self.session.bot
        voice = Mock(destroy=AsyncMock())
        self.session.voice = voice
        with (
            patch.object(self.session, "_install_bot", side_effect=RuntimeError("invalid credentials")),
            self.assertRaisesRegex(RuntimeError, "invalid credentials"),
        ):
            await self.session.rebuild_credentials(cast(Any, object()))

        self.assertIs(self.session.bot, old_bot)
        self.assertIs(self.session.sender.bot, old_bot)
        voice.bind_service.assert_called_once_with(old_bot.voice, proxy_value=False)

    async def test_stop_cancels_sdk_task_and_clears_readiness(self):
        running = asyncio.Event()
        with patch.object(self.session.bot, "start", AsyncMock(side_effect=running.wait)):
            await self.session.start()
            task = self.session._run_task
            await self.session._handle_sdk_ready(None)
            self.assertTrue(self.session.ready)
            await self.session.stop()

        assert task is not None
        self.assertTrue(task.cancelled())
        self.assertFalse(self.session.ready)

    async def _voice_chat_session(self) -> tuple[oopz_session.OopzSession, AsyncMock]:
        dispatch = AsyncMock()
        session = await oopz_session.OopzSession.create(on_chat_message=dispatch)
        self.addAsyncCleanup(session.stop)
        session._voice_chat_since = (150, "")
        bot_uid = session.bot.config.person_uid
        members = Mock(channel_members={
            "voice": [Mock(uid="user")],
            "empty": [],
            "bot_only": [Mock(uid=bot_uid)],
        })
        with (
            patch.object(session.bot.areas, "get_joined_areas", AsyncMock(return_value=[Mock(area_id="area")])),
            patch.object(session.bot.channels, "get_voice_channel_members", AsyncMock(return_value=members)),
        ):
            await session._load_voice_channels()
        return session, dispatch

    async def test_voice_chat_tracks_all_voice_channels_but_polls_occupied_ones(self):
        session, _dispatch = await self._voice_chat_session()

        self.assertEqual(set(session._voice_chat_history), {"voice", "empty", "bot_only"})
        self.assertEqual(session._voice_chat_active, {"voice"})
        self.assertIn("empty", session.sender.voice_channels)

        bot_uid = session.bot.config.person_uid
        await session._handle_voice_enter(None, Mock(area="area", channel="bot_only", persons=[bot_uid]))
        self.assertEqual(session._voice_chat_active, {"voice"})
        await session._handle_voice_enter(None, Mock(area="area2", channel="new", persons=["user"]))
        self.assertEqual(session._voice_chat_active, {"voice", "new"})
        self.assertEqual(session._voice_chat_history["new"].area, "area2")

        await session._handle_voice_leave(None, Mock(channel="new", active_num=1))
        self.assertEqual(session._voice_chat_active, {"voice", "new"})
        await session._handle_voice_leave(None, Mock(channel="new", active_num=0))
        self.assertEqual(session._voice_chat_active, {"voice"})
        await session._handle_channel_delete(None, Mock(area="area", channel="voice"))
        self.assertEqual(session._voice_chat_active, set())
        self.assertNotIn("voice", session._voice_chat_history)

    async def test_voice_chat_dispatches_messages_after_start_once(self):
        session, dispatch = await self._voice_chat_session()
        history = session._voice_chat_history["voice"]
        old = Message(channel="voice", messageId="1", timestamp="100", person="user", content="/help")
        live = Message(channel="voice", messageId="2", timestamp="200", person="user", area="area", content="/help")
        polled = Message(channel="voice", messageId="3", timestamp="300", person="user", content="/help")
        own = Message(channel="voice", messageId="4", timestamp="400", person=session.bot.config.person_uid)
        with patch.object(
            session.bot.messages,
            "get_channel_messages",
            AsyncMock(side_effect=[[old], [own, polled, live, old], [own, polled, live, old]]),
        ):
            await session._poll_voice_chat("voice", history)
            dispatch.assert_not_awaited()
            await session._handle_sdk_message(live, None)
            await session._poll_voice_chat("voice", history)
            await session._poll_voice_chat("voice", history)
            await session._handle_sdk_message(polled, None)

        messages = [call.args[0] for call in dispatch.await_args_list]
        self.assertEqual([message["messageId"] for message in messages], ["2", "3"])
        self.assertEqual([message["area"] for message in messages], ["area", "area"])

    async def test_sender_uses_v2_for_voice_channels(self):
        session, _dispatch = await self._voice_chat_session()
        with patch.object(session.bot.messages, "send_message", AsyncMock()) as send:
            await session.sender.send_message("hi", area="area", channel="empty", auto_recall=False)
            await session.sender.send_message("hi", area="area", channel="text", auto_recall=False)

        self.assertEqual([call.kwargs["version"] for call in send.await_args_list], ["v2", "v1"])
