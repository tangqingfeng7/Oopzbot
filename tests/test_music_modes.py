import sys
import unittest
from pathlib import Path
from unittest.mock import Mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


from music import (
    MusicHandler,
    PLAY_MODE_AUTOPLAY,
    PLAY_MODE_LIST,
    PLAY_MODE_SHUFFLE,
    PLAY_MODE_SINGLE,
)


class MusicModeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.handler = MusicHandler.__new__(MusicHandler)
        self.handler.queue = Mock()
        self.handler.netease = Mock()
        self.handler._liked_ids_cache = []
        self.handler._voice_channel_id = "voice-1"
        self.handler._voice_channel_area = "area-1"

    def test_get_play_mode_defaults_to_list(self) -> None:
        self.handler.queue.get_play_mode.return_value = None

        mode = self.handler.get_play_mode()

        self.assertEqual(mode, PLAY_MODE_LIST)
        self.handler.queue.set_play_mode.assert_called_once_with(PLAY_MODE_LIST)

    def test_set_play_mode_rejects_invalid_value(self) -> None:
        with self.assertRaises(ValueError):
            self.handler.set_play_mode("bad-mode")

    def test_single_mode_replays_current_song_on_natural_finish(self) -> None:
        self.handler.queue.get_play_mode.return_value = PLAY_MODE_SINGLE
        current_song = {"name": "song", "nested": {"value": 1}}

        next_song, source = self.handler._dequeue_next_song(
            natural_end=True,
            current_song=current_song,
        )

        self.assertEqual(source, PLAY_MODE_SINGLE)
        self.assertEqual(next_song, current_song)
        self.assertIsNot(next_song, current_song)

    def test_shuffle_mode_uses_random_pop(self) -> None:
        self.handler.queue.get_play_mode.return_value = PLAY_MODE_SHUFFLE
        self.handler.queue.pop_random.return_value = {"name": "shuffle-song"}

        next_song, source = self.handler._dequeue_next_song(
            natural_end=False,
            current_song={"name": "current"},
        )

        self.assertEqual(source, "queue")
        self.assertEqual(next_song["name"], "shuffle-song")
        self.handler.queue.pop_random.assert_called_once_with()
        self.handler.queue.play_next.assert_not_called()

    def test_autoplay_mode_falls_back_to_liked_song(self) -> None:
        self.handler.queue.get_play_mode.return_value = PLAY_MODE_AUTOPLAY
        self.handler.queue.play_next.return_value = None
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

        next_song, source = self.handler._dequeue_next_song(
            natural_end=True,
            current_song={"channel": "text-1", "area": "area-1", "user": "user-1"},
        )

        self.assertEqual(source, PLAY_MODE_AUTOPLAY)
        self.assertEqual(next_song["name"], "喜欢歌曲")
        self.assertEqual(next_song["channel"], "text-1")
        self.assertEqual(next_song["area"], "area-1")


if __name__ == "__main__":
    unittest.main()
