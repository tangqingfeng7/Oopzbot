import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from domain.playback import AreaId, PlaybackSessionSnapshot  # noqa: E402
from music.music import MusicHandler  # noqa: E402


class _FakeResponse:
    """模拟 aiohttp 响应：既能被 async with 使用，也支持 release/raise_for_status。"""

    def __init__(self, status: int, payload: dict):
        self.status = status
        self._payload = payload
        self.released = False

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")

    def release(self):
        self.released = True

    async def json(self, content_type=None):
        return self._payload

    async def read(self):
        return b""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeRequestContext:
    """aiohttp 的 session.get() 既可 await 也可 async with，这里同时实现两种协议。"""

    def __init__(self, response: _FakeResponse):
        self._response = response

    def __await__(self):
        async def _resolve():
            return self._response

        return _resolve().__await__()

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *exc):
        return False


class BilibiliMusicTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        import music.bilibili_music as bilibili_music

        self.module = bilibili_music
        config_patch = patch.dict(
            bilibili_music.BILIBILI_MUSIC_CONFIG,
            {"enabled": True, "cookie": "SESSDATA=sess; bili_jct=csrf"},
        )
        config_patch.start()
        self.addCleanup(config_patch.stop)

    async def test_video_playurl_uses_cid_from_view(self) -> None:
        bili = self.module.BilibiliMusic()
        calls = []

        async def fake_get(url, params=None, referer=None):
            calls.append((url, params or {}, referer))
            if url == self.module._API_VIDEO_VIEW:
                return {
                    "code": 0,
                    "data": {
                        "pages": [{"cid": 998877}],
                    },
                }
            if url == self.module._API_VIDEO_PLAYURL:
                self.assertEqual((params or {}).get("bvid"), "BV1test")
                self.assertEqual((params or {}).get("cid"), "998877")
                return {
                    "code": 0,
                    "data": {
                        "dash": {
                            "audio": [
                                {"baseUrl": "https://low.example/audio.m4s", "bandwidth": 64000},
                                {"baseUrl": "https://high.example/audio.m4s", "bandwidth": 128000},
                            ],
                        },
                    },
                }
            return {"code": -1}

        bili._get = fake_get

        url = await bili._get_video_audio_url("BV1test")

        self.assertEqual(url, "https://high.example/audio.m4s")
        self.assertEqual(calls[0][0], self.module._API_VIDEO_VIEW)
        self.assertEqual(calls[1][0], self.module._API_VIDEO_PLAYURL)

    def test_stream_headers_use_matching_bilibili_page(self) -> None:
        bili = self.module.BilibiliMusic()

        video_headers = bili.get_stream_headers("BV1test")
        audio_headers = bili.get_stream_headers("au123")

        self.assertEqual(video_headers["Referer"], "https://www.bilibili.com/video/BV1test")
        self.assertEqual(audio_headers["Referer"], "https://www.bilibili.com/audio/au123")
        self.assertEqual(video_headers["User-Agent"], self.module.USER_AGENT)

    async def test_stream_headers_reach_voice_download(self) -> None:
        bili = self.module.BilibiliMusic()
        handler = MusicHandler.__new__(MusicHandler)
        handler._playback_lock = asyncio.Lock()
        handler._voice_channel_area = "area-A"
        handler._voice_channel_id = "voice-A"
        handler._playback_generation = 1
        handler._play_start_time = 0
        handler._play_duration = 120

        queue = Mock()
        queue.clear_current = AsyncMock()
        queue.clear_play_state = AsyncMock()
        handler._get_queue = Mock(return_value=queue)

        voice = Mock(available=True)
        voice.play_audio = AsyncMock(return_value={"ok": True})
        handler.voice = voice
        handler.platforms = Mock()
        handler.platforms.get.return_value = bili

        await handler._stream_to_voice_channel(
            "https://cdn.example/audio.m4s",
            "song",
            PlaybackSessionSnapshot(AreaId("area-A"), "voice-A", 1),
            "BV1test",
            "bilibili",
        )

        headers = voice.play_audio.await_args.kwargs["headers"]
        self.assertEqual(headers["Referer"], "https://www.bilibili.com/video/BV1test")
        self.assertEqual(headers["User-Agent"], self.module.USER_AGENT)

    async def test_get_retries_once_after_412(self) -> None:
        bili = self.module.BilibiliMusic()
        target_url = "https://api.bilibili.com/x/web-interface/search/type"
        bilibili_home = self.module._BILIBILI_HOME
        calls = []

        class FakeCookieJar:
            def __init__(self):
                self._keys = []

            def seed(self, key):
                self._keys.append(SimpleNamespace(key=key))

            def __iter__(self):
                return iter(self._keys)

        class FakeSession:
            def __init__(self):
                self.cookie_jar = FakeCookieJar()
                self.target_calls = 0
                self.first_response = None

            def get(self, url, **kwargs):
                calls.append(url)
                if url == bilibili_home:
                    self.cookie_jar.seed("buvid3")
                    return _FakeRequestContext(_FakeResponse(200, {"ok": True}))
                self.target_calls += 1
                if self.target_calls == 1:
                    self.first_response = _FakeResponse(412, {"code": -412})
                    return _FakeRequestContext(self.first_response)
                return _FakeRequestContext(_FakeResponse(200, {"code": 0, "data": {"result": []}}))

        fake_session = FakeSession()
        bili._http.session = AsyncMock(return_value=fake_session)
        bili._http.request_proxy = lambda url: None

        data = await bili._get(target_url, params={"keyword": "测试"})

        self.assertIsNotNone(data)
        assert data is not None
        self.assertEqual(data["code"], 0)
        # 412 必须触发一次首页预热再重试，且失败的响应要被显式释放，避免连接泄漏
        self.assertEqual(calls, [target_url, bilibili_home, target_url])
        first_response = fake_session.first_response
        assert first_response is not None
        self.assertTrue(first_response.released)
        self.assertEqual([cookie.key for cookie in fake_session.cookie_jar], ["buvid3"])


if __name__ == "__main__":
    unittest.main()
