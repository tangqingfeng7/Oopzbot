import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from music.sdk_voice import SdkVoiceController  # noqa: E402
from oopz.sdk_transport import ProjectBrowserVoiceTransport  # noqa: E402


class SdkVoiceControllerTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.voice = Mock()
        self.voice.current_sign = Mock(agora_sign_pid="123")
        self.voice.join = AsyncMock(return_value={"ok": True})
        self.voice.leave = AsyncMock()
        self.voice.play_bytes = AsyncMock(return_value={"ok": True})
        self.voice.play_url = AsyncMock(return_value={"ok": True})
        self.voice.stop = AsyncMock()
        self.voice.pause = AsyncMock(return_value=True)
        self.voice.resume = AsyncMock(return_value=True)
        self.voice.seek = AsyncMock(return_value=True)
        self.voice.set_volume = AsyncMock(return_value=True)
        self.voice.close = AsyncMock()
        self.voice.get_state = AsyncMock(return_value="playing")
        self.controller = SdkVoiceController(self.voice, proxy_value=False)

    async def asyncTearDown(self) -> None:
        if not self.controller._closed:
            await self.controller.destroy()

    async def test_join_delegates_to_sdk_voice(self) -> None:
        await self.controller.join(
            area="area-1",
            channel="voice-1",
            from_area="area-0",
            from_channel="voice-0",
            rtc_uid=123,
        )
        self.voice.join.assert_awaited_once_with(
            area="area-1",
            channel="voice-1",
            from_area="area-0",
            from_channel="voice-0",
            rtc_uid=123,
        )

    async def test_preload_is_reused_by_playback(self) -> None:
        self.controller._fetcher.fetch = Mock(return_value=(b"audio", "audio/mpeg"))
        self.controller.preload_audio("https://example.com/song.mp3")
        await asyncio.gather(*self.controller._preload_tasks.values())

        await self.controller.play_audio("https://example.com/song.mp3")

        self.controller._fetcher.fetch.assert_called_once()
        self.voice.play_bytes.assert_awaited_once_with(b"audio", mime_type="audio/mpeg")
        self.assertTrue(self.controller.is_playing)

    async def test_stream_headers_are_used_for_preload_and_direct_download(self) -> None:
        headers = {
            "User-Agent": "browser",
            "Referer": "https://www.bilibili.com/video/BV1test",
        }
        self.controller._fetcher.fetch = Mock(return_value=(b"audio", "audio/mp4"))

        self.controller.preload_audio("https://cdn.example/preloaded.m4s", headers=headers)
        await asyncio.gather(*self.controller._preload_tasks.values())
        await self.controller.play_audio("https://cdn.example/preloaded.m4s", headers=headers)
        await self.controller.play_audio("https://cdn.example/direct.m4s", headers=headers)

        self.assertEqual(self.controller._fetcher.fetch.call_count, 2)
        for call in self.controller._fetcher.fetch.call_args_list:
            self.assertEqual(call.kwargs["headers"], headers)

    async def test_playback_awaits_async_started_callback(self) -> None:
        self.controller._fetcher.fetch = Mock(return_value=(b"audio", "audio/ogg"))
        callback = AsyncMock()

        await self.controller.play_audio("https://example.com/song.ogg", callback)

        callback.assert_awaited_once_with()

    async def test_netease_remote_audio_uses_browser_without_python_download(self) -> None:
        self.controller._fetcher.fetch = Mock(return_value=(b"audio", "audio/flac"))

        await self.controller.play_audio(
            "http://m703.music.126.net/song.flac",
            prefer_remote=True,
        )

        self.voice.play_url.assert_awaited_once_with(
            "http://m703.music.126.net/song.flac"
        )
        self.controller._fetcher.fetch.assert_not_called()
        self.voice.play_bytes.assert_not_awaited()

    async def test_remote_audio_failure_falls_back_to_safe_download(self) -> None:
        self.voice.play_url.return_value = {"ok": False, "error": "cors"}
        self.controller._fetcher.fetch = Mock(return_value=(b"audio", "audio/flac"))

        await self.controller.play_audio(
            "https://m703.music.126.net/song.flac",
            prefer_remote=True,
        )

        self.voice.play_url.assert_awaited_once()
        self.controller._fetcher.fetch.assert_called_once()
        self.voice.play_bytes.assert_awaited_once_with(
            b"audio", mime_type="audio/flac"
        )

    async def test_non_awaitable_remote_player_falls_back_to_safe_download(self) -> None:
        self.voice.play_url = Mock(return_value={"ok": True})
        self.controller._fetcher.fetch = Mock(return_value=(b"audio", "audio/flac"))

        await self.controller.play_audio(
            "https://m703.music.126.net/song.flac",
            prefer_remote=True,
        )

        self.voice.play_url.assert_called_once()
        self.controller._fetcher.fetch.assert_called_once()
        self.voice.play_bytes.assert_awaited_once_with(
            b"audio", mime_type="audio/flac"
        )

    async def test_non_netease_remote_audio_keeps_safe_download(self) -> None:
        self.controller._fetcher.fetch = Mock(return_value=(b"audio", "audio/mpeg"))

        await self.controller.play_audio(
            "https://example.com/song.mp3",
            prefer_remote=True,
        )

        self.voice.play_url.assert_not_awaited()
        self.controller._fetcher.fetch.assert_called_once()
        self.voice.play_bytes.assert_awaited_once()

    async def test_sdk_play_error_is_not_reported_as_success(self) -> None:
        self.controller._fetcher.fetch = Mock(return_value=(b"audio", "audio/mpeg"))
        self.voice.play_bytes.return_value = {"ok": False, "error": "decode failed"}

        with self.assertRaisesRegex(RuntimeError, "decode failed"):
            await self.controller.play_audio("https://example.com/song.mp3")
        self.assertFalse(self.controller.is_playing)

    async def test_destroy_is_idempotent_and_closes_sdk_backend(self) -> None:
        await self.controller.destroy()
        await self.controller.destroy()

        self.voice.close.assert_awaited_once_with()
        self.assertFalse(self.controller.available)


class PlaybackEndDetectionTest(unittest.IsolatedAsyncioTestCase):
    """一首歌自然播完后要能自己复位播放状态。

    回归背景：SDK 播完不会回调，而 _playing 只有 stop/pause/leave/destroy 会清。
    少了结束轮询，is_playing 会永远停在 True，自动播放监控就不再切下一首，
    只能去 Web 播放器手动点。
    """

    def setUp(self) -> None:
        self.voice = Mock()
        self.voice.play_bytes = AsyncMock(return_value={"ok": True})
        self.voice.stop = AsyncMock()
        self.voice.leave = AsyncMock()
        self.voice.close = AsyncMock()
        self.voice.pause = AsyncMock(return_value=True)
        self.voice.resume = AsyncMock(return_value=True)
        self.voice.get_state = AsyncMock(return_value="playing")
        self.controller = SdkVoiceController(self.voice, proxy_value=False)
        self.controller._fetcher.fetch = Mock(return_value=(b"audio", "audio/mpeg"))
        patcher = patch("music.sdk_voice._PLAY_POLL_INTERVAL", 0.01)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def asyncTearDown(self) -> None:
        if not self.controller._closed:
            await self.controller.destroy()

    async def _play(self) -> None:
        await self.controller.play_audio("https://example.com/song.mp3")

    async def _wait_until(self, predicate, timeout: float = 2.0) -> bool:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if predicate():
                return True
            await asyncio.sleep(0.01)
        return predicate()

    async def test_natural_end_clears_playing(self) -> None:
        await self._play()
        self.assertTrue(self.controller.is_playing, "刚开播时应为播放中")

        self.voice.get_state.return_value = "finished"

        self.assertTrue(
            await self._wait_until(lambda: not self.controller.is_playing),
            "浏览器报告 finished 后必须复位，否则自动播放监控永远不切下一首",
        )

    async def test_end_detected_when_transient_finished_is_missed(self) -> None:
        await self._play()
        self.voice.get_state.return_value = "joined"

        self.assertTrue(
            await self._wait_until(lambda: not self.controller.is_playing),
            "错过 finished 也必须判定为已结束，否则自动播放永远不切下一首",
        )

    async def test_idle_state_also_counts_as_ended(self) -> None:
        await self._play()
        self.voice.get_state.return_value = "idle"

        self.assertTrue(await self._wait_until(lambda: not self.controller.is_playing))

    async def test_end_sets_wake_event_for_auto_play(self) -> None:
        """播完要置位唤醒事件，自动播放监控靠它立刻切下一首而不是干等轮询。"""
        await self._play()
        self.assertFalse(self.controller.playback_ended.is_set(), "开播时应清空")

        self.voice.get_state.return_value = "joined"
        await asyncio.wait_for(self.controller.playback_ended.wait(), timeout=2)

    async def test_new_playback_clears_wake_event(self) -> None:
        await self._play()
        self.voice.get_state.return_value = "joined"
        await asyncio.wait_for(self.controller.playback_ended.wait(), timeout=2)

        self.voice.get_state.return_value = "playing"
        await self._play()
        self.assertFalse(
            self.controller.playback_ended.is_set(),
            "新一首开播必须清位，否则监控会被旧事件反复唤醒",
        )

    async def test_paused_state_is_not_treated_as_ended(self) -> None:
        await self._play()
        self.voice.get_state.return_value = "paused"
        await asyncio.sleep(0.05)

        self.assertTrue(self.controller.is_playing, "暂停不是播完，不能当作结束")

    async def test_still_playing_state_does_not_clear(self) -> None:
        await self._play()
        await asyncio.sleep(0.05)
        self.assertTrue(self.controller.is_playing, "状态仍是 playing 时不能提前判定播完")

    async def test_state_query_failure_does_not_stick_forever(self) -> None:
        await self._play()
        self.voice.get_state.side_effect = RuntimeError("浏览器无响应")

        self.assertTrue(
            await self._wait_until(lambda: not self.controller.is_playing),
            "查不到状态时应按已停止处理，让上层回退到按时长判定，而不是永久卡住",
        )

    async def test_stop_leave_destroy_leave_no_watcher_behind(self) -> None:
        for label, action in (
            ("stop", self.controller.stop_audio),
            ("leave", self.controller.leave),
        ):
            await self._play()
            await action()
            watch = self.controller._playback_watch
            self.assertIsNone(watch, f"{label} 之后不应残留结束轮询任务")

        await self._play()
        await self.controller.destroy()
        self.assertIsNone(self.controller._playback_watch, "destroy 之后不应残留轮询任务")

    async def test_resume_restarts_end_detection(self) -> None:
        await self._play()
        await self.controller.pause_audio()
        self.assertFalse(self.controller.is_playing)

        await self.controller.resume_audio()
        self.assertTrue(self.controller.is_playing)
        self.voice.get_state.return_value = "finished"

        self.assertTrue(
            await self._wait_until(lambda: not self.controller.is_playing),
            "恢复播放后同样要能检测到播完",
        )


class WarmupBeforeJoinTest(unittest.IsolatedAsyncioTestCase):
    """首次进频道要等浏览器预热完成。

    回归背景：预热是后台跑的，启动后很快点歌就会在浏览器没起来时进频道，
    身份绑定赶不上，服务端不把 bot 显示为频道成员——听得到声音看不到人。
    """

    def setUp(self) -> None:
        self.voice = Mock()
        self.voice.join = AsyncMock(return_value={"ok": True})
        self.voice.leave = AsyncMock()
        self.voice.close = AsyncMock()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

        async def _start() -> None:
            self.started.set()
            await self.release.wait()

        self.voice.start = AsyncMock(side_effect=_start)
        self.controller = SdkVoiceController(self.voice, proxy_value=False)

    async def _join(self):
        return await self.controller.join(area="a1", channel="c1")

    async def test_join_waits_for_inflight_warmup(self) -> None:
        warm = asyncio.get_running_loop().create_task(self.controller.warmup())
        await self.started.wait()

        join = asyncio.get_running_loop().create_task(self._join())
        await asyncio.sleep(0.05)
        self.voice.join.assert_not_awaited()

        self.release.set()
        await asyncio.wait_for(join, timeout=2)
        await warm
        self.voice.join.assert_awaited_once()

    async def test_join_does_not_wait_when_no_warmup_scheduled(self) -> None:
        await asyncio.wait_for(self._join(), timeout=1)
        self.voice.join.assert_awaited_once()

    async def test_join_proceeds_after_warmup_finished(self) -> None:
        self.release.set()
        await self.controller.warmup()

        await asyncio.wait_for(self._join(), timeout=1)
        self.voice.join.assert_awaited_once()

    async def test_failed_warmup_does_not_block_join(self) -> None:
        self.voice.start = AsyncMock(side_effect=RuntimeError("浏览器起不来"))
        await self.controller.warmup()

        await asyncio.wait_for(self._join(), timeout=1)
        self.voice.join.assert_awaited_once()

    async def test_join_gives_up_waiting_after_timeout(self) -> None:
        with patch("music.sdk_voice._WARMUP_WAIT_TIMEOUT", 0.05):
            warm = asyncio.get_running_loop().create_task(self.controller.warmup())
            await self.started.wait()

            await asyncio.wait_for(self._join(), timeout=2)

        self.voice.join.assert_awaited_once()
        self.release.set()
        await warm


class SeleniumFallbackTest(unittest.IsolatedAsyncioTestCase):
    async def test_falls_back_when_playwright_initialization_fails(self) -> None:
        transport = ProjectBrowserVoiceTransport(Mock(), proxy_value=False)
        with (
            patch.object(
                transport,
                "_init_playwright_browser",
                AsyncMock(side_effect=RuntimeError("playwright failed")),
            ),
            patch.object(transport, "_init_selenium_browser") as selenium,
            patch(
                "oopz_sdk.transport.voice_browser.BrowserVoiceTransport._shutdown_browser",
                new=AsyncMock(),
            ),
        ):
            await transport._init_browser()

        selenium.assert_called_once_with()
        self.assertTrue(transport._init_done.is_set())

    async def test_does_not_start_selenium_when_playwright_succeeds(self) -> None:
        transport = ProjectBrowserVoiceTransport(Mock(), proxy_value=False)
        with (
            patch.object(transport, "_init_playwright_browser", new=AsyncMock()),
            patch.object(transport, "_init_selenium_browser") as selenium,
        ):
            await transport._init_browser()

        selenium.assert_not_called()


if __name__ == "__main__":
    unittest.main()
