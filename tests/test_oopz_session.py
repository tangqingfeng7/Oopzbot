"""SDK 会话与应用发送器、语音控制器的生命周期契约。"""

import asyncio
import sys
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

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
