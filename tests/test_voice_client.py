import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


from voice_client import VoiceClient


class VoiceClientPlaybackTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = VoiceClient.__new__(VoiceClient)
        self.client._stop_event = threading.Event()
        self.client._playing = False
        self.client._on_play_start_callback = None
        self.client._remote_last_fail = 0
        self.client._temp_audio_path = None
        self.client.get_state = Mock(return_value="finished")

    def test_do_play_prefers_remote_url_before_local_download(self) -> None:
        self.client._download_audio_with_retry = Mock(return_value=(b"abc", "audio/mpeg"))
        self.client._run_on_browser = Mock(return_value={"ok": True, "duration": 1.5})

        self.client._do_play(url="https://example.com/song.mp3")

        self.client._run_on_browser.assert_any_call(
            "agoraPlayAudio",
            "https://example.com/song.mp3",
            timeout=5,
        )
        self.assertFalse(self.client._playing)

    def test_do_play_falls_back_to_local_when_remote_fails(self) -> None:
        self.client._download_audio_with_retry = Mock(return_value=(b"abc", "audio/mpeg"))

        call_count = [0]

        def _run(method, *args, **kwargs):
            if method == "agoraPlayAudio":
                call_count[0] += 1
                if call_count[0] == 1:
                    return {"ok": False, "error": "unsupported"}
                return {"ok": True, "duration": 2}
            raise AssertionError(f"unexpected browser call: {method}")

        self.client._run_on_browser = Mock(side_effect=_run)

        self.client._do_play(url="https://example.com/song.mp3")

        self.client._download_audio_with_retry.assert_called_once()
        play_calls = [c for c in self.client._run_on_browser.call_args_list
                      if c.args[0] == "agoraPlayAudio"]
        self.assertGreaterEqual(len(play_calls), 2)
        self.assertFalse(self.client._playing)

    def test_remote_failure_suppresses_subsequent_attempts(self) -> None:
        """远程失败后，后续播放应跳过远程尝试，直接本地下载。"""
        self.client._download_audio_with_retry = Mock(return_value=(b"data", "audio/mpeg"))
        self.client._run_on_browser = Mock(return_value={"ok": True, "duration": 3})
        import time as _time
        self.client._remote_last_fail = _time.monotonic()

        self.client._do_play(url="https://example.com/song.mp3")

        all_calls = self.client._run_on_browser.call_args_list
        play_urls = [c.args[1] for c in all_calls if c.args[0] == "agoraPlayAudio"]
        remote_calls = [u for u in play_urls if u.startswith("http")]
        self.assertEqual(len(remote_calls), 0, "Should skip remote when recently failed")
        self.client._download_audio_with_retry.assert_called_once()


if __name__ == "__main__":
    unittest.main()
