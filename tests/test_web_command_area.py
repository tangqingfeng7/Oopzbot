
import asyncio
import json
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from core.redis_keys import decode_web_command, encode_web_command  # noqa: E402
from core.redis_protocol import RedisPipeline  # noqa: E402
from domain.playback import (  # noqa: E402
    AreaId,
    AreaWebCommand,
    GlobalWebCommand,
    PlaybackSessionSnapshot,
    WebCommandDecodeError,
)


class EncodeDecodeTest(unittest.TestCase):
    def test_roundtrip(self) -> None:
        command = AreaWebCommand(AreaId("A1"), "next", {})
        self.assertEqual(decode_web_command(encode_web_command(command)), command)

    def test_empty_area_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            AreaWebCommand(AreaId(""), "next", {})

    def test_notify_json_can_contain_old_separator(self) -> None:
        command = AreaWebCommand(
            AreaId("A1"),
            "notify",
            {"name": "a|b", "artists": "c", "position": 1},
        )
        self.assertEqual(decode_web_command(encode_web_command(command)), command)

    def test_all_legacy_payloads_are_invalid(self) -> None:
        for raw in ("next", "A1|next"):
            with self.subTest(raw=raw), self.assertRaises(WebCommandDecodeError):
                decode_web_command(raw)

    def test_area_is_stripped(self) -> None:
        command = AreaWebCommand(AreaId("  A1  "), "stop", {})
        self.assertEqual(command.area.value, "A1")

    def test_validated_command_payload_is_immutable(self) -> None:
        command = GlobalWebCommand("volume", {"value": 20})
        with self.assertRaises(TypeError):
            command.payload["value"] = 30  # type: ignore[index]

    def test_unknown_fields_and_versions_are_rejected(self) -> None:
        base = {
            "version": 1,
            "scope": "global",
            "action": "volume",
            "payload": {"value": 20},
        }
        for patch in ({"version": 2}, {"version": True}, {"extra": True}):
            payload = {**base, **patch}
            with self.subTest(patch=patch), self.assertRaises(WebCommandDecodeError):
                decode_web_command(json.dumps(payload))

    def test_duplicate_fields_and_nonstandard_numbers_are_rejected(self) -> None:
        invalid = (
            '{"version":1,"scope":"global","action":"volume",'
            '"action":"volume","payload":{"value":20}}',
            '{"version":1,"scope":"global","action":"volume",'
            '"payload":{"value":20,"value":30}}',
            '{"version":1,"scope":"global","action":"volume",'
            '"payload":{"value":NaN}}',
        )
        for raw in invalid:
            with self.subTest(raw=raw), self.assertRaises(WebCommandDecodeError):
                decode_web_command(raw)

    def test_payload_fields_and_volume_bounds_are_strict(self) -> None:
        invalid = (
            {
                "version": 1,
                "scope": "area",
                "area": "A1",
                "action": "next",
                "payload": {"unexpected": True},
            },
            {
                "version": 1,
                "scope": "global",
                "action": "volume",
                "payload": {"value": 101},
            },
            {
                "version": 1,
                "scope": "global",
                "action": "volume",
                "payload": {"value": True},
            },
            {
                "version": 1,
                "scope": "global",
                "action": "volume",
                "payload": {"value": "20"},
            },
            {
                "version": 1,
                "scope": "area",
                "area": 123,
                "action": "next",
                "payload": {},
            },
            {
                "version": 1,
                "scope": "area",
                "area": "A1",
                "action": "seek",
                "payload": {"time": "10"},
            },
            {
                "version": 1,
                "scope": "area",
                "area": "A1",
                "action": "notify",
                "payload": {"name": None, "artists": "artist", "position": 1},
            },
        )
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(WebCommandDecodeError):
                decode_web_command(json.dumps(payload))


class CommandAreaGateTest(unittest.TestCase):
    def _handler(self, current_area) -> Any:
        from music.music import MusicHandler

        handler = MusicHandler.__new__(MusicHandler)  # 跳过 __init__ 的重量级构造
        handler._voice_channel_area = current_area
        handler._voice_channel_id = None
        handler._playback_generation = 0
        return handler

    def test_command_from_another_area_is_skipped(self) -> None:
        handler = self._handler("area-A")
        command = AreaWebCommand(AreaId("area-B"), "next", {})
        self.assertFalse(handler._web_command_applies_here(command))

    def test_command_from_the_playing_area_runs(self) -> None:
        handler = self._handler("area-A")
        command = AreaWebCommand(AreaId("area-A"), "next", {})
        self.assertTrue(handler._web_command_applies_here(command))

    def test_global_scope_only_allows_validated_volume(self) -> None:
        handler = self._handler("area-A")
        self.assertTrue(
            handler._web_command_applies_here(GlobalWebCommand("volume", {"value": 20}))
        )

    def test_no_current_area_rejects_area_command(self) -> None:
        handler = self._handler(None)
        command = AreaWebCommand(AreaId("area-B"), "next", {})
        self.assertFalse(handler._web_command_applies_here(command))


class ConsumeWebCommandTest(unittest.IsolatedAsyncioTestCase):
    """走监听线程真正调用的那一层，光测判定函数抓不到「校验被删掉」。"""

    def _handler(self, current_area) -> Any:
        from music.music import MusicHandler

        handler = MusicHandler.__new__(MusicHandler)
        handler._voice_channel_area = current_area
        handler._voice_channel_id = None
        handler._playback_generation = 0
        handler._playback_lock = asyncio.Lock()
        handler._get_queue = mock.Mock(return_value=mock.sentinel.queue)
        handler._execute_web_command = mock.AsyncMock()
        handler._execute_web_command.return_value = True
        return handler

    async def test_command_from_another_area_is_not_executed(self) -> None:
        handler = self._handler("area-A")

        command = AreaWebCommand(AreaId("area-B"), "next", {})
        self.assertFalse(await handler._consume_web_command(encode_web_command(command)))
        handler._execute_web_command.assert_not_called()

    async def test_command_from_the_playing_area_is_executed(self) -> None:
        handler = self._handler("area-A")

        command = AreaWebCommand(AreaId("area-A"), "next", {})
        self.assertTrue(await handler._consume_web_command(encode_web_command(command)))
        handler._execute_web_command.assert_called_once_with(
            command,
            queue=mock.sentinel.queue,
        )

    async def test_global_volume_is_executed_anywhere(self) -> None:
        handler = self._handler("area-A")
        command = GlobalWebCommand("volume", {"value": 20})

        self.assertTrue(await handler._consume_web_command(encode_web_command(command)))
        handler._execute_web_command.assert_called_once_with(command, queue=None)

    async def test_bytes_payload_is_decoded(self) -> None:
        handler = self._handler("area-A")
        command = AreaWebCommand(AreaId("area-A"), "stop", {})

        self.assertTrue(await handler._consume_web_command(encode_web_command(command).encode()))
        handler._execute_web_command.assert_called_once_with(
            command,
            queue=mock.sentinel.queue,
        )

    async def test_legacy_payload_is_dropped(self) -> None:
        handler = self._handler("area-A")

        self.assertFalse(await handler._consume_web_command("area-A|next"))
        handler._execute_web_command.assert_not_called()

    async def test_area_command_is_dropped_without_current_area(self) -> None:
        handler = self._handler(None)

        command = AreaWebCommand(AreaId("area-B"), "stop", {})
        self.assertFalse(await handler._consume_web_command(encode_web_command(command)))
        handler._execute_web_command.assert_not_called()

    async def test_area_switch_cannot_redirect_an_inflight_command(self) -> None:
        handler = self._handler("area-A")
        handler._playback_generation = 1
        queue_a = object()
        queue_b = object()
        handler._get_queue.side_effect = lambda area: {
            "area-A": queue_a,
            "area-B": queue_b,
        }[area]
        switch_attempted = asyncio.Event()
        release_command = asyncio.Event()
        executed = []

        async def execute(command, queue=None):
            # 命令执行期间发起域切换：在途命令的目标队列必须仍是快照时解析的那个
            await asyncio.wait_for(switch_attempted.wait(), 1)
            executed.append(queue)
            release_command.set()
            return True

        handler._execute_web_command.side_effect = execute

        async def switch_area():
            switch_attempted.set()
            async with handler._playback_lock:
                handler._voice_channel_area = "area-B"
                handler._playback_generation += 1

        command_task = asyncio.create_task(
            handler._consume_web_command(
                encode_web_command(AreaWebCommand(AreaId("area-A"), "stop", {}))
            )
        )
        switch_task = asyncio.create_task(switch_area())
        await asyncio.wait_for(release_command.wait(), 1)
        await asyncio.wait_for(command_task, 1)
        await asyncio.wait_for(switch_task, 1)

        # 契约是「队列在持锁的快照里定死」，而不是执行期间 _voice_channel_area 不变：
        # 生产实现只在锁内捕获快照并解析队列，随后释放锁再执行命令。
        self.assertEqual(executed, [queue_a], "域切换不得把在途命令改投到新域队列")
        self.assertEqual(handler._voice_channel_area, "area-B")

    async def test_stale_stream_task_cannot_play_in_new_area(self) -> None:
        from music.music import MusicHandler

        handler = MusicHandler.__new__(MusicHandler)
        handler._playback_lock = asyncio.Lock()
        handler._voice_channel_area = "area-B"
        handler._voice_channel_id = "voice-B"
        handler._playback_generation = 2
        handler._get_queue = mock.Mock()
        handler.voice = mock.Mock(available=True)

        await handler._stream_to_voice_channel(
            "https://example.com/song.mp3",
            "song",
            PlaybackSessionSnapshot(AreaId("area-A"), "voice-A", 1),
            "song-id",
        )

        handler._get_queue.assert_not_called()
        handler.voice.play_audio.assert_not_called()

    async def test_stale_stream_task_cannot_override_new_song_in_same_area(self) -> None:
        from music.music import MusicHandler

        handler = MusicHandler.__new__(MusicHandler)
        handler._playback_lock = asyncio.Lock()
        handler._voice_channel_area = "area-A"
        handler._voice_channel_id = "voice-A"
        handler._playback_generation = 2
        handler._get_queue = mock.Mock()
        handler.voice = mock.Mock(available=True)

        await handler._stream_to_voice_channel(
            "https://example.com/old-song.mp3",
            "old-song",
            PlaybackSessionSnapshot(AreaId("area-A"), "voice-A", 1),
            "old-song-id",
        )

        handler._get_queue.assert_not_called()
        handler.voice.play_audio.assert_not_called()


class ProducerCarriesAreaTest(unittest.IsolatedAsyncioTestCase):
    """execute_control_action 早就收了 area，只是没带进命令载荷。"""

    class _Recorder:
        def __init__(self):
            self.pushed: list[str | bytes] = []
            self.values: dict[str, object] = {}

        async def rpush(self, key: str, *values: object) -> int:
            for value in values:
                if not isinstance(value, (str, bytes)):
                    raise TypeError("测试命令队列仅接受文本载荷")
                self.pushed.append(value)
            return len(self.pushed)

        async def delete(self, *keys: str) -> int:
            return len(keys)

        async def set(
            self,
            key: str,
            value: object,
            ex: int | None = None,
            px: int | None = None,
            **kwargs: object,
        ) -> None:
            self.values[key] = value
            return None

        def pipeline(self, transaction: bool = False) -> RedisPipeline:
            raise AssertionError("该测试路径不应创建 pipeline")

    async def test_track_scoped_actions_tag_the_area(self) -> None:
        """作用在某个域正在播的那首歌上的命令必须带域。"""
        from web.web_player import execute_control_action

        for action, body in (
            ("next", {}),
            ("stop", {}),
            ("pause", {}),
            ("resume", {}),
            ("seek", {"time": 12}),
        ):
            with self.subTest(action=action):
                r = self._Recorder()
                with mock.patch("web.web_player._area_key", side_effect=lambda base, area: base):
                    await execute_control_action(action, body, r, area="area-A")

                self.assertTrue(r.pushed, f"{action} 应写入一条命令")
                command = decode_web_command(r.pushed[-1])
                self.assertIsInstance(command, AreaWebCommand)
                assert isinstance(command, AreaWebCommand)
                self.assertEqual(command.area.value, "area-A")
                if action == "seek":
                    self.assertEqual(command.payload, {"time": 12.0})

    async def test_volume_is_not_area_scoped(self) -> None:
        """音量作用于全局唯一的 Agora 输出设备，带域会让写入生效但命令被丢弃，
        于是 /api/status 读到的值和实际在响的音量长期背离。"""
        from web.web_player import execute_control_action

        r = self._Recorder()
        with mock.patch("web.web_player._area_key", side_effect=lambda base, area: base):
            await execute_control_action("volume", {"value": 50}, r, area="area-A")

        command = decode_web_command(r.pushed[-1])
        self.assertEqual(command, GlobalWebCommand("volume", {"value": 50}))

    async def test_stop_after_current_is_a_persisted_play_mode(self) -> None:
        from web.web_player import execute_control_action

        r = self._Recorder()
        result = await execute_control_action(
            "mode",
            {"value": "stop"},
            r,
            area="area-A",
        )

        self.assertEqual(result, {"ok": True, "mode": "stop"})
        self.assertIn("stop", r.values.values())
        self.assertEqual(r.pushed, [])

    async def test_track_control_without_area_is_rejected(self) -> None:
        from web.web_player import execute_control_action

        for action, body in (
            ("next", {}),
            ("clear", {}),
            ("stop", {}),
            ("pause", {}),
            ("resume", {}),
            ("seek", {"time": 12}),
            ("mode", {"value": "loop"}),
        ):
            with self.subTest(action=action):
                r = self._Recorder()
                result = await execute_control_action(action, body, r, area="")

                self.assertFalse(result["ok"])
                self.assertEqual(r.pushed, [])


if __name__ == "__main__":
    unittest.main()
