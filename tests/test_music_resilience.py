import os
import sys
import time
import unittest
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import music  # noqa: E402
from music import MusicHandler  # noqa: E402


class _DummyRedis:
    def __init__(self):
        self.store = {}

    def set(self, key, value):
        self.store[key] = value

    def get(self, key):
        return self.store.get(key)

    def delete(self, key):
        self.store.pop(key, None)


class _DummyQueue:
    def __init__(self):
        self.redis = _DummyRedis()
        self.current = None
        self.queue_length = 0

    def clear_current(self):
        self.current = None
        return None

    def clear_queue(self):
        return None

    def get_current(self):
        return self.current

    def get_queue_length(self):
        return self.queue_length


class _DummyVoice:
    available = True

    def set_volume(self, vol):
        return True

    def stop_audio(self):
        return None

    def pause_audio(self):
        return True

    def resume_audio(self):
        return True

    def seek_audio(self, _sec):
        return True


class MusicResilienceTests(unittest.TestCase):
    def _handler(self):
        h = MusicHandler.__new__(MusicHandler)
        h.queue = _DummyQueue()
        h.voice = _DummyVoice()
        h._voice_channel_id = None
        h._voice_channel_area = None
        h._play_start_time = 0.0
        h._play_duration = 0.0
        h._playlist_idle_since = 0.0
        h._web_link_released_due_to_idle = False
        h._leave_current_voice_channel = lambda: None
        h.sender = type(
            "S",
            (),
            {
                "__init__": lambda self: setattr(self, "messages", []),
                "send_message": lambda self, text, **kwargs: self.messages.append(
                    {"text": text, **kwargs}
                ),
            },
        )()
        return h

    @patch("music_web_control.logger.debug")
    def test_execute_web_command_invalid_volume_should_not_raise(self, mock_debug):
        h = self._handler()
        h._execute_web_command("volume:not-a-number")
        self.assertTrue(mock_debug.called)

    def test_is_playing_with_invalid_play_state_json_fallbacks_to_time(self):
        h = self._handler()
        h._play_start_time = time.time() - 1
        h._play_duration = 10
        h.queue.redis.set("music:play_state", "{bad-json")
        self.assertTrue(h._is_playing())

    @patch("music.ensure_token", return_value="tok")
    @patch("music._get_web_player_url", return_value="http://127.0.0.1:8080")
    @patch("music.logger.warning")
    def test_web_player_link_invalid_ttl_fallbacks(self, mock_warning, _mock_url, mock_token):
        old_ttl = music.WEB_PLAYER_CONFIG.get("token_ttl_seconds")
        try:
            music.WEB_PLAYER_CONFIG["token_ttl_seconds"] = "bad"
            out = music._web_player_link(redis_client=_DummyRedis())
            self.assertIn("/w/tok", out)
            mock_token.assert_called_once()
            self.assertTrue(mock_warning.called)
        finally:
            music.WEB_PLAYER_CONFIG["token_ttl_seconds"] = old_ttl

    @patch("music_web_control.logger.debug")
    def test_execute_web_command_malformed_notify_should_debug_not_raise(self, mock_debug):
        h = self._handler()
        h._execute_web_command("notify:{bad-json")
        self.assertTrue(mock_debug.called)

    def test_execute_web_command_notify_counts_current_song_in_position(self):
        h = self._handler()
        h._voice_channel_id = "c1"
        h._voice_channel_area = "a1"
        h.queue.current = {"name": "now playing"}

        h._execute_web_command('notify:{"name":"queued","artists":"artist","position":1}')

        self.assertIn("位置: 2", h.sender.messages[-1]["text"])

    @patch("music.clear_token")
    @patch("music.get_token", side_effect=["tok", "tok"])
    @patch("music.logger.info")
    def test_release_web_link_only_once_while_idle(self, mock_info, mock_get_token, mock_clear):
        h = self._handler()
        old_timeout = music.WEB_PLAYER_CONFIG.get("link_idle_release_seconds")
        try:
            music.WEB_PLAYER_CONFIG["link_idle_release_seconds"] = 1
            h._playlist_idle_since = time.time() - 5

            h._release_web_link_if_needed()
            h._release_web_link_if_needed()

            mock_clear.assert_called_once()
            mock_info.assert_called_once()
            self.assertTrue(h._web_link_released_due_to_idle)
            self.assertEqual(1, mock_get_token.call_count)
        finally:
            music.WEB_PLAYER_CONFIG["link_idle_release_seconds"] = old_timeout


if __name__ == "__main__":
    unittest.main()
