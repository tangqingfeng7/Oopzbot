import asyncio
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


import web.web_player_config as cfg  # noqa: E402
from music.music import (  # noqa: E402
    PLAY_MODE_AUTOPLAY,
    PLAY_MODE_LIST,
    PLAY_MODE_SHUFFLE,
    PLAY_MODE_SINGLE,
    PLAY_MODE_STOP,
    MusicHandler,
)


class MusicModeTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._music_config = dict(cfg.MUSIC_CONFIG)
        self.handler = MusicHandler.__new__(MusicHandler)
        self.queue = AsyncMock()
        self.handler._queue_cache = {"area-1": self.queue}
        self.handler.netease = AsyncMock()
        self.handler._liked_ids_cache = []
        self.handler._voice_channel_id = "voice-1"
        self.handler._voice_channel_area = "area-1"
        # __new__ 跳过了 __init__，补上生产路径依赖的异步锁与缓存
        self.handler._playback_lock = asyncio.Lock()
        self.handler._voice_lock = asyncio.Lock()
        self.handler._active_area_cache = ""
        self.handler._background_area_cache = ("", 0.0)

    def tearDown(self) -> None:
        cfg.MUSIC_CONFIG.clear()
        cfg.MUSIC_CONFIG.update(self._music_config)

    async def test_get_play_mode_defaults_to_list(self) -> None:
        self.queue.get_play_mode.return_value = None

        mode = await self.handler.get_play_mode()

        self.assertEqual(mode, PLAY_MODE_LIST)
        self.queue.set_play_mode.assert_called_once_with(PLAY_MODE_LIST)

    async def test_set_play_mode_rejects_invalid_value(self) -> None:
        with self.assertRaises(ValueError):
            await self.handler.set_play_mode("bad-mode")

    async def test_single_mode_replays_current_song_on_natural_finish(self) -> None:
        self.queue.get_play_mode.return_value = PLAY_MODE_SINGLE
        current_song = {"name": "song", "nested": {"value": 1}}

        next_song, source = await self.handler._dequeue_next_song(
            natural_end=True,
            current_song=current_song,
        )

        self.assertEqual(source, PLAY_MODE_SINGLE)
        self.assertEqual(next_song, current_song)
        self.assertIsNot(next_song, current_song)

    async def test_shuffle_mode_uses_random_pop(self) -> None:
        self.queue.get_play_mode.return_value = PLAY_MODE_SHUFFLE
        self.queue.pop_random.return_value = {"name": "shuffle-song"}

        next_song, source = await self.handler._dequeue_next_song(
            natural_end=False,
            current_song={"name": "current"},
        )

        self.assertEqual(source, "queue")
        assert next_song is not None
        self.assertEqual(next_song["name"], "shuffle-song")
        self.queue.pop_random.assert_called_once_with()
        self.queue.play_next.assert_not_called()

    async def test_stop_mode_stops_after_current_song_finishes(self) -> None:
        self.queue.get_play_mode.return_value = PLAY_MODE_STOP

        next_song, source = await self.handler._dequeue_next_song(
            natural_end=True,
            current_song={"name": "current"},
        )

        self.assertIsNone(next_song)
        self.assertEqual(source, PLAY_MODE_STOP)
        self.queue.clear_queue.assert_awaited_once_with()
        self.queue.play_next.assert_not_called()
        self.handler.netease.get_user_id.assert_not_called()

    async def test_stop_mode_still_allows_manual_next(self) -> None:
        self.queue.get_play_mode.return_value = PLAY_MODE_STOP
        self.queue.play_next.return_value = {"name": "next"}

        next_song, source = await self.handler._dequeue_next_song(
            natural_end=True,
            current_song=None,
        )

        self.assertEqual(next_song, {"name": "next"})
        self.assertEqual(source, "queue")
        self.queue.clear_queue.assert_not_called()
        self.queue.play_next.assert_awaited_once_with()

    async def test_autoplay_mode_falls_back_to_liked_song(self) -> None:
        self.queue.get_play_mode.return_value = PLAY_MODE_AUTOPLAY
        self.queue.play_next.return_value = None
        self.handler.netease.get_user_id.return_value = 100
        self.handler.netease.get_liked_ids.return_value = [1]
        self.handler.netease.summarize_by_id.return_value = {
            "code": "success",
            "data": {
                "id": 1,
                "name": "喜欢歌曲",
                "artists": "测试歌手",
                "album": "测试专辑",
                "url": "https://example.com/song.mp3",
                "cover": "https://example.com/cover.jpg",
                "duration": 120000,
                "durationText": "2:00",
            },
        }

        next_song, source = await self.handler._dequeue_next_song(
            natural_end=True,
            current_song={"channel": "text-1", "area": "area-1", "user": "user-1"},
        )

        self.assertEqual(source, PLAY_MODE_AUTOPLAY)
        assert next_song is not None
        self.assertEqual(next_song["name"], "喜欢歌曲")
        self.assertEqual(next_song["channel"], "text-1")
        self.assertEqual(next_song["area"], "area-1")

    async def test_configured_auto_play_randomizes_after_queue_ends(self) -> None:
        cfg.MUSIC_CONFIG["auto_play_enabled"] = True
        self.queue.get_play_mode.return_value = PLAY_MODE_LIST
        self.queue.play_next.return_value = None
        self.handler.netease.get_user_id.return_value = 100
        self.handler.netease.get_liked_ids.return_value = [1]
        self.handler.netease.summarize_by_id.return_value = {
            "code": "success",
            "data": {
                "id": 1,
                "name": "auto song",
                "artists": "artist",
                "album": "album",
                "url": "https://example.com/song.mp3",
                "cover": "",
                "duration": 120000,
                "durationText": "2:00",
            },
        }

        next_song, source = await self.handler._dequeue_next_song(
            natural_end=True,
            current_song={"channel": "text-1", "area": "area-1", "user": "user-1"},
        )

        self.assertEqual(source, PLAY_MODE_AUTOPLAY)
        assert next_song is not None
        self.assertEqual(next_song["name"], "auto song")
        self.assertEqual(next_song["channel"], "text-1")

    async def test_disabled_auto_play_stops_when_queue_is_empty(self) -> None:
        cfg.MUSIC_CONFIG["auto_play_enabled"] = False
        self.queue.get_play_mode.return_value = PLAY_MODE_LIST
        self.queue.play_next.return_value = None

        next_song, source = await self.handler._dequeue_next_song(
            natural_end=True,
            current_song={"channel": "text-1", "area": "area-1", "user": "user-1"},
        )

        self.assertIsNone(next_song)
        self.assertEqual(source, PLAY_MODE_LIST)
        self.handler.netease.get_user_id.assert_not_called()

    async def test_mark_web_active_area_updates_without_generating_link(self) -> None:
        q = AsyncMock()
        q_client = object()
        q.client = AsyncMock(return_value=q_client)
        self.handler._web_link_released_due_to_idle = True

        with patch("music.music.set_active_area", new=AsyncMock()) as set_active_area:
            await self.handler._mark_web_active_area("area-2", queue=q)

        set_active_area.assert_awaited_once_with("area-2", redis_client=q_client)
        self.assertFalse(self.handler._web_link_released_due_to_idle)

    async def test_get_web_link_marks_active_area_even_when_link_is_empty(self) -> None:
        q = AsyncMock()
        q_client = object()
        q.client = AsyncMock(return_value=q_client)
        self.handler._get_queue = Mock(return_value=q)
        self.handler._web_link_released_due_to_idle = True

        with (
            patch("music.music._web_player_link", new=AsyncMock(return_value="")),
            patch("music.music.set_active_area", new=AsyncMock()) as set_active_area,
        ):
            link = await self.handler._get_web_link(area="area-2")

        self.assertEqual(link, "")
        set_active_area.assert_awaited_once_with("area-2", redis_client=q_client)
        self.assertFalse(self.handler._web_link_released_due_to_idle)

    async def test_song_request_omits_web_link_when_sending_is_disabled(self) -> None:
        self.handler.names = AsyncMock()
        self.handler.names.user.return_value = "测试用户"
        self.handler._get_web_link = AsyncMock(return_value="[打开播放器](https://example.test/player)")
        song = {
            "platform": "netease",
            "name": "测试歌曲",
            "artists": "测试歌手",
            "album": "测试专辑",
            "duration": "3:00",
            "area": "area-1",
            "user": "user-1",
            "attachments": [],
        }

        with patch.dict("music.music.WEB_PLAYER_CONFIG", {"send_link_enabled": False}):
            text = await self.handler._build_song_request_text(song)

        self.assertNotIn("打开播放器", text)
        self.handler._get_web_link.assert_not_called()

    async def test_song_request_includes_web_link_when_sending_is_enabled(self) -> None:
        self.handler.names = AsyncMock()
        self.handler.names.user.return_value = "测试用户"
        self.handler._get_web_link = AsyncMock(return_value="[打开播放器](https://example.test/player)")
        song = {
            "platform": "netease",
            "name": "测试歌曲",
            "artists": "测试歌手",
            "album": "测试专辑",
            "duration": "3:00",
            "area": "area-1",
            "user": "user-1",
            "attachments": [],
        }

        with patch.dict("music.music.WEB_PLAYER_CONFIG", {"send_link_enabled": True}):
            text = await self.handler._build_song_request_text(song)

        self.assertIn("[打开播放器](https://example.test/player)", text)
        self.handler._get_web_link.assert_called_once_with(
            area="area-1",
            mark_active=False,
        )

    async def test_stale_song_request_link_cannot_restore_old_active_area(self) -> None:
        queue = AsyncMock()
        queue_client = object()
        queue.client = AsyncMock(return_value=queue_client)
        self.handler._get_queue = Mock(return_value=queue)
        self.handler._web_link_released_due_to_idle = False
        self.handler.names = AsyncMock()
        self.handler.names.user.return_value = "旧请求用户"
        old_request_ready = asyncio.Event()
        release_old_request = asyncio.Event()
        texts: list[str] = []
        song = {
            "platform": "netease",
            "name": "旧请求歌曲",
            "artists": "歌手",
            "album": "专辑",
            "duration": "3:00",
            "area": "area-A",
            "user": "user-A",
            "attachments": [],
        }

        async def finish_old_request() -> None:
            old_request_ready.set()
            await asyncio.wait_for(release_old_request.wait(), timeout=2)
            texts.append(await self.handler._build_song_request_text(song))

        with (
            patch("music.music._web_player_link", new=AsyncMock(return_value="[player](https://example.test)")),
            patch("music.music.set_active_area", new=AsyncMock()) as set_active_area,
            patch.dict("music.music.WEB_PLAYER_CONFIG", {"send_link_enabled": True}),
        ):
            worker = asyncio.create_task(finish_old_request())
            await asyncio.wait_for(old_request_ready.wait(), timeout=1)
            # 域已切到 B，此时才让旧请求继续；它不能把活跃域改回 A
            await self.handler._mark_web_active_area("area-B", queue=queue)
            release_old_request.set()
            await asyncio.wait_for(worker, timeout=2)

        self.assertEqual(len(texts), 1)
        set_active_area.assert_awaited_once_with("area-B", redis_client=queue_client)

    async def test_stale_now_playing_link_cannot_restore_old_active_area(self) -> None:
        queue = AsyncMock()
        queue_client = object()
        queue.client = AsyncMock(return_value=queue_client)
        self.handler._get_queue = Mock(return_value=queue)
        self.handler._web_link_released_due_to_idle = False
        song = {
            "platform": "netease",
            "name": "旧播放歌曲",
            "artists": "歌手",
            "area": "area-A",
            "attachments": [],
        }

        with (
            patch("music.music._web_player_link", new=AsyncMock(return_value="[player](https://example.test)")),
            patch("music.music.set_active_area", new=AsyncMock()) as set_active_area,
        ):
            await self.handler._mark_web_active_area("area-B", queue=queue)
            text = await self.handler._build_now_playing_text("正在播放", song)

        self.assertIn("[player](https://example.test)", text)
        set_active_area.assert_awaited_once_with("area-B", redis_client=queue_client)

    async def test_netease_cover_upload_uses_small_cdn_thumbnail(self) -> None:
        self.handler.sender = AsyncMock()
        attachment = {"fileKey": "cover-key", "width": 300, "height": 300}
        self.handler.sender.upload_file_from_url.return_value = {
            "code": "success",
            "data": attachment,
        }
        song = {
            "platform": "netease",
            "song_id": "2053320168",
            "cover": "https://p3.music.126.net/cover.png?token=keep",
            "attachments": [],
        }

        with (
            patch("music.music.ImageCache.get_by_source", new=AsyncMock(return_value=None)),
            patch("music.music.ImageCache.save", new=AsyncMock(return_value=7)) as save,
        ):
            attachments, image_cache_id, cache_hit = await self.handler._resolve_song_attachments(song)

        upload_url = self.handler.sender.upload_file_from_url.await_args.args[0]
        self.assertIn("token=keep", upload_url)
        self.assertIn("param=300y300", upload_url)
        self.assertEqual(attachments, [attachment])
        self.assertEqual(image_cache_id, 7)
        self.assertFalse(cache_hit)
        save.assert_awaited_once_with(
            "2053320168",
            "netease",
            song["cover"],
            attachment,
        )

    async def test_cover_prefetch_timeout_cancels_without_sync_retry(self) -> None:
        song = {
            "platform": "netease",
            "song_id": "2053320168",
            "cover": "https://p3.music.126.net/cover.png",
        }
        self.handler._cover_prefetch = {}
        started = asyncio.Event()

        async def never_finishes() -> tuple[list, int | None, bool]:
            started.set()
            await asyncio.Event().wait()
            return ([], None, False)

        task = asyncio.create_task(never_finishes())
        key = self.handler._cover_prefetch_key(song)
        assert key is not None
        self.handler._cover_prefetch[key] = task
        await started.wait()

        with patch.object(MusicHandler, "_COVER_PREFETCH_TIMEOUT", 0.01):
            result = await self.handler._consume_cover_prefetch(song)

        self.assertEqual(result, ([], None, False))
        self.assertTrue(task.cancelled())
        self.assertNotIn(key, self.handler._cover_prefetch)

    async def test_start_playing_uses_explicit_area_queue(self) -> None:
        area_queue = AsyncMock()
        self.handler._get_queue = Mock(return_value=area_queue)

        await self.handler._start_playing(120000, area="area-2")

        self.handler._get_queue.assert_called_once_with("area-2")
        area_queue.set_play_state.assert_called_once()
        self.queue.set_play_state.assert_not_called()

    async def test_play_song_choice_reuses_search_result_without_fetching_detail(self) -> None:
        platform = AsyncMock()
        platform.get_song_url.return_value = "https://example.com/song.mp3"
        platform.summarize_by_id.return_value = {"code": "error", "message": "不应调用", "data": None}
        self.handler.platforms = Mock()
        self.handler.platforms.get.return_value = platform
        self.handler.sender = AsyncMock()
        self.handler.names = AsyncMock()
        self.handler.names.user.return_value = "测试用户"
        self.handler._check_and_enter_voice_channel = AsyncMock(return_value=True)
        self.handler._commit_song_request = AsyncMock(return_value={"message": "ok", "attachments": []})

        await self.handler.play_song_choice(
            {
                "id": 1,
                "name": "稻香",
                "artists": "周杰伦",
                "album": "魔杰座",
                "cover": "https://example.com/cover.jpg",
                "duration": 222000,
                "durationText": "3:42",
                "platform": "netease",
            },
            "channel-1",
            "area-1",
            "user-1",
        )

        platform.get_song_url.assert_called_once_with(
            1,
            expected_duration_ms=222000,
            song_name="稻香",
        )
        platform.summarize_by_id.assert_not_called()
        committed_song = self.handler._commit_song_request.call_args.args[0]
        self.assertEqual(committed_song["url"], "https://example.com/song.mp3")
        self.assertEqual(committed_song["duration"], "3:42")
        self.assertEqual(committed_song["duration_ms"], 222000)

    async def test_check_and_enter_skips_rejoin_when_already_in_same_channel(self) -> None:
        """已在同一语音频道时不能再调用 _do_enter_voice/agora 重连，否则会断流。"""
        self.handler.voice = Mock()
        self.handler.voice.available = True
        self.handler.sender = AsyncMock()
        self.handler.sender.get_voice_channel_for_user.return_value = "voice-1"
        # 服务端确认 bot 仍是该频道成员，这时才允许跳过重连
        self.handler.sender.get_voice_channel_for_user_strict.return_value = "voice-1"
        self.handler._do_enter_voice = AsyncMock()
        self.handler._is_playing = AsyncMock(return_value=True)
        self.handler.names = AsyncMock()

        with patch.dict("music.music.OOPZ_CONFIG", {"person_uid": "bot-uid"}):
            result = await self.handler._check_and_enter_voice_channel(
                user="user-1", channel="text-1", area="area-1",
            )

        self.assertTrue(result)
        self.handler._do_enter_voice.assert_not_called()
        self.handler.sender.send_message.assert_not_called()

    async def test_rejoins_when_server_dropped_the_membership(self) -> None:
        """服务端已不认 bot 是成员时必须重进，否则只有音频没有人。"""
        self.handler.voice = Mock()
        self.handler.voice.available = True
        self.handler.voice.leave = AsyncMock()
        self.handler.sender = AsyncMock()
        self.handler.sender.get_voice_channel_for_user.return_value = "voice-1"
        self.handler.sender.get_voice_channel_for_user_strict.return_value = None
        self.handler._do_enter_voice = AsyncMock(return_value={"status": True})
        self.handler._is_playing = AsyncMock(return_value=True)
        self.handler.names = Mock()
        self.handler.names.channel = Mock(return_value="语音频道")

        with patch.dict("music.music.OOPZ_CONFIG", {"person_uid": "bot-uid"}):
            result = await self.handler._check_and_enter_voice_channel(
                user="user-1", channel="text-1", area="area-1",
            )

        self.assertTrue(result)
        self.handler._do_enter_voice.assert_awaited_once()

    async def test_same_channel_id_in_another_area_is_not_the_same_session(self) -> None:
        self.handler._playback_lock = asyncio.Lock()
        self.handler.voice = Mock()
        self.handler.voice.available = True
        self.handler.sender = AsyncMock()
        self.handler.sender.get_voice_channel_for_user.return_value = "voice-1"
        self.handler._get_queue = Mock(return_value=self.queue)
        self.handler._is_playing = AsyncMock(return_value=True)
        self.handler._do_enter_voice = AsyncMock()
        self.handler.names = AsyncMock()
        self.handler.names.channel.return_value = "旧域语音频道"

        result = await self.handler._check_and_enter_voice_channel(
            user="user-1",
            channel="text-2",
            area="area-2",
        )

        self.assertFalse(result)
        self.handler._get_queue.assert_called_once_with("area-1")
        self.handler._do_enter_voice.assert_not_called()
        self.handler.sender.send_message.assert_called_once()

    async def test_loading_session_rejects_cross_area_switch(self) -> None:
        self.handler._playback_lock = asyncio.Lock()
        self.handler._play_start_time = time.time()
        self.handler._play_duration = 120
        self.handler.voice = Mock()
        self.handler.voice.available = True
        self.handler.voice.is_playing = False
        self.handler.sender = AsyncMock()
        self.handler.sender.get_voice_channel_for_user.return_value = "voice-2"
        self.handler._get_queue = Mock(return_value=self.queue)
        self.queue.get_play_state.return_value = {
            "start_time": self.handler._play_start_time,
            "duration": self.handler._play_duration,
            "loading": True,
        }
        self.handler._do_enter_voice = AsyncMock(return_value={})
        self.handler.names = AsyncMock()
        self.handler.names.channel.return_value = "旧域语音频道"

        result = await self.handler._check_and_enter_voice_channel(
            user="user-2",
            channel="text-2",
            area="area-2",
        )

        self.assertFalse(result)
        self.handler._do_enter_voice.assert_not_called()
        self.handler.sender.send_message.assert_called_once()

    async def test_enter_voice_is_serialized_by_voice_lock(self) -> None:
        """校验到状态提交之间不能让第二次进入插进来。

        序列化点已从 `_playback_lock` 挪到 `_do_enter_voice` 内部的 `_voice_lock`：
        「退旧频道 → 清残留 → join → 提交频道/域/代际」整段必须原子。
        """
        self.handler._voice_lock = asyncio.Lock()
        self.handler._playback_generation = 0
        self.handler._voice_channel_id = None
        self.handler._voice_channel_area = None
        self.handler.voice = AsyncMock()
        self.handler.voice.available = True
        self.handler.names = Mock()
        self.handler._cleanup_stale_voice_membership = AsyncMock()
        self.handler._restore_volume_from_redis = AsyncMock()

        joining = asyncio.Event()
        release_join = asyncio.Event()

        async def slow_join(**_kwargs):
            joining.set()
            await asyncio.wait_for(release_join.wait(), timeout=2)
            return "sign"

        self.handler.voice.join.side_effect = slow_join

        first = asyncio.create_task(self.handler._do_enter_voice("voice-1", "area-1"))
        await asyncio.wait_for(joining.wait(), timeout=1)

        second = asyncio.create_task(self.handler._do_enter_voice("voice-2", "area-2"))
        await asyncio.sleep(0.05)
        # 第一次尚未提交状态，第二次不得进入临界区
        self.assertEqual(self.handler.voice.join.await_count, 1)
        self.assertIsNone(self.handler._voice_channel_id)

        release_join.set()
        self.assertEqual(await asyncio.wait_for(first, 1), {"status": True, "sign": "sign"})
        self.assertEqual(await asyncio.wait_for(second, 1), {"status": True, "sign": "sign"})
        self.assertEqual(self.handler._voice_channel_id, "voice-2")
        # 首次进入 +1，第二次先退旧频道 +1 再进入 +1；退出也要推进代际，
        # 否则 leave 期间旧推流的回调还会把状态写回来
        self.assertEqual(self.handler._playback_generation, 3)

    async def test_enter_voice_leaves_when_only_area_changes(self) -> None:
        """同一个频道 ID 换了域也算换频道，必须先退再进，否则会留在旧域的房间里。"""
        self.handler._voice_lock = asyncio.Lock()
        self.handler._playback_generation = 1
        self.handler._voice_channel_id = "voice-1"
        self.handler._voice_channel_area = "area-1"
        self.handler.voice = AsyncMock()
        self.handler.voice.available = True
        self.handler.voice.join.return_value = "sign-1"
        self.handler.names = Mock()
        self.handler._cleanup_stale_voice_membership = AsyncMock()
        self.handler._restore_volume_from_redis = AsyncMock()

        async def leave_current() -> None:
            self.handler._voice_channel_id = None
            self.handler._voice_channel_area = None

        self.handler._leave_current_voice_channel = AsyncMock(side_effect=leave_current)

        result = await self.handler._do_enter_voice("voice-1", "area-2")

        self.assertEqual(result, {"status": True, "sign": "sign-1"})
        self.handler._leave_current_voice_channel.assert_awaited_once_with()
        self.handler.voice.join.assert_awaited_once_with(
            area="area-2",
            channel="voice-1",
            from_area="area-1",
            from_channel="voice-1",
        )
        self.assertEqual(self.handler._voice_channel_area, "area-2")
        # 换频道必须让播放代际前进，旧代的推流回调才会被判废
        self.assertEqual(self.handler._playback_generation, 2)

    async def test_enter_voice_does_not_commit_state_when_join_fails(self) -> None:
        """加入失败必须原样返回错误且不提交状态，否则后续会以为自己已在频道里。"""
        self.handler._voice_lock = asyncio.Lock()
        self.handler._playback_generation = 1
        self.handler._voice_channel_id = None
        self.handler._voice_channel_area = None
        self.handler.voice = AsyncMock()
        self.handler.voice.available = True
        self.handler.voice.join.side_effect = RuntimeError("agora join failed")
        self.handler.names = Mock()
        self.handler._cleanup_stale_voice_membership = AsyncMock()
        self.handler._restore_volume_from_redis = AsyncMock()

        result = await self.handler._do_enter_voice("voice-2", "area-1")

        self.assertEqual(result, {"error": "agora join failed"})
        self.assertIsNone(self.handler._voice_channel_id)
        self.assertIsNone(self.handler._voice_channel_area)
        self.assertEqual(self.handler._playback_generation, 1)
        self.handler._restore_volume_from_redis.assert_not_awaited()

    async def test_enter_voice_cleans_stale_membership_before_first_join(self) -> None:
        """本地没有频道记录时，服务端可能还留着上次的成员身份，必须先清理。"""
        self.handler._voice_lock = asyncio.Lock()
        self.handler._playback_generation = 0
        self.handler._voice_channel_id = None
        self.handler._voice_channel_area = None
        self.handler.voice = AsyncMock()
        self.handler.voice.available = True
        self.handler.voice.join.return_value = "sign-2"
        self.handler.names = Mock()
        self.handler._cleanup_stale_voice_membership = AsyncMock()
        self.handler._restore_volume_from_redis = AsyncMock()
        self.handler._leave_current_voice_channel = AsyncMock()

        result = await self.handler._do_enter_voice("voice-3", "area-3")

        self.assertEqual(result, {"status": True, "sign": "sign-2"})
        self.handler._cleanup_stale_voice_membership.assert_awaited_once_with("area-3")
        # 本来就不在任何频道，不该触发退出
        self.handler._leave_current_voice_channel.assert_not_awaited()
        self.handler._restore_volume_from_redis.assert_awaited_once()

    async def test_enter_voice_refuses_when_voice_is_unavailable(self) -> None:
        self.handler._voice_lock = asyncio.Lock()
        self.handler.voice = AsyncMock()
        self.handler.voice.available = False

        result = await self.handler._do_enter_voice("voice-2", "area-1")

        self.assertEqual(result, {"error": "voice_unavailable"})
        self.handler.voice.join.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
