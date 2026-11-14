"""网易云播放链路的 Cookie 语义回归。

客户端已迁移到 ManagedHttpClient，所有请求统一收敛到 `_http.request_json`，
因此这里在该接缝上做假替身，而不是伪造 aiohttp 的 session/response。
"""

import sys
import types
import unittest
from pathlib import Path
from typing import Any, cast

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


class _FakeHttp:
    """记录 request_json 调用，并按 (method, path) 给出预置响应。"""

    def __init__(self, responder):
        self._responder = responder
        self.calls: list[tuple[str, str, dict, dict]] = []

    async def request_json(self, method, url, params=None, data=None, headers=None, timeout=None):
        payload = dict(data or {}) if method == "POST" else dict(params or {})
        self.calls.append((method, url, payload, dict(headers or {})))
        return self._responder(method, url, payload)

    async def close(self):
        return None

    @property
    def simple_calls(self) -> list[tuple[str, str]]:
        return [(method, url) for method, url, _payload, _headers in self.calls]


class NeteaseCookiePlaybackTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._old_config_module = sys.modules.get("config")
        self._old_netease_module = sys.modules.get("music.netease")
        fake_config = types.ModuleType("config")
        fake_config.__dict__["NETEASE_CLOUD"] = {
            "base_url": "http://netease.example",
            "cookie": "MUSIC_U=abc",
            "audio_quality": "exhigh",
        }
        sys.modules["config"] = fake_config
        sys.modules.pop("music.netease", None)
        import music.netease as netease

        self.module = netease

    def tearDown(self) -> None:
        sys.modules.pop("music.netease", None)
        if self._old_netease_module is not None:
            sys.modules["music.netease"] = self._old_netease_module
        if self._old_config_module is not None:
            sys.modules["config"] = self._old_config_module
        else:
            sys.modules.pop("config", None)

    def _client(self, responder):
        client = cast(Any, self.module.NeteaseCloud.__new__(self.module.NeteaseCloud))
        client.base_url = "http://netease.example"
        client.cookie = "MUSIC_U=abc"
        client.audio_quality = "exhigh"
        client._last_song_url_error = ""
        client._user_id = None
        http = _FakeHttp(responder)
        client._http = http
        return client, http

    async def test_get_song_url_posts_cookie_in_body_before_get(self) -> None:
        def responder(method, url, payload):
            if method == "POST":
                return {
                    "code": 200,
                    "data": [{
                        "id": 1,
                        "url": "https://music.example/full.mp3",
                        "time": 222000,
                        "size": 8_000_000,
                    }],
                }
            return {"code": 500, "data": []}

        client, http = self._client(responder)

        url = await client.get_song_url(1, expected_duration_ms=222000, song_name="稻香")

        self.assertEqual(url, "https://music.example/full.mp3")
        # 带 cookie 的 POST 必须先行且一次命中，不能再退回匿名 GET
        self.assertEqual(len(http.calls), 1)
        method, request_url, data, headers = http.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(request_url, "http://netease.example/song/url/v1")
        self.assertEqual(data["id"], 1)
        self.assertEqual(data["level"], "exhigh")
        self.assertEqual(data["cookie"], "MUSIC_U=abc")
        self.assertEqual(headers["Cookie"], "MUSIC_U=abc")

    async def test_get_user_id_prefers_nested_login_status_profile(self) -> None:
        def responder(method, url, payload):
            if method == "POST":
                return {
                    "data": {
                        "code": 200,
                        "profile": {"userId": 399919346, "nickname": "测试账号"},
                    },
                }
            return {"code": 200, "account": None, "profile": None}

        client, http = self._client(responder)

        user_id = await client.get_user_id()

        self.assertEqual(user_id, 399919346)
        self.assertEqual(len(http.calls), 1)
        method, request_url, data, headers = http.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(request_url, "http://netease.example/login/status")
        self.assertEqual(data["cookie"], "MUSIC_U=abc")
        self.assertIn("timestamp", data)
        self.assertEqual(headers["Cookie"], "MUSIC_U=abc")

    async def test_get_user_id_does_not_fallback_to_another_endpoint(self) -> None:
        def responder(method, url, payload):
            if method == "POST":
                return {"data": {"code": 200, "profile": None}}
            return {
                "code": 200,
                "account": {"id": 123456, "userName": "旧版账号"},
                "profile": None,
            }

        client, http = self._client(responder)

        user_id = await client.get_user_id()

        # 登录态拿不到就得如实返回 None，退到旧接口会拿到别人的账号
        self.assertIsNone(user_id)
        self.assertEqual(http.simple_calls, [("POST", "http://netease.example/login/status")])

    async def test_get_liked_ids_posts_cookie_in_body(self) -> None:
        def responder(method, url, payload):
            if method == "POST":
                return {"code": 200, "ids": [10, 20, 30]}
            return {"code": 200, "ids": []}

        client, http = self._client(responder)

        liked_ids = await client.get_liked_ids(399919346)

        self.assertEqual(liked_ids, [10, 20, 30])
        self.assertEqual(len(http.calls), 1)
        method, request_url, data, headers = http.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(request_url, "http://netease.example/likelist")
        self.assertEqual(data["uid"], 399919346)
        self.assertEqual(data["cookie"], "MUSIC_U=abc")
        self.assertIn("timestamp", data)
        self.assertEqual(headers["Cookie"], "MUSIC_U=abc")

    async def test_get_liked_ids_does_not_fallback_after_failed_post(self) -> None:
        def responder(method, url, payload):
            if method == "POST":
                return {"code": 500}
            return {"code": 200, "ids": [40]}

        client, http = self._client(responder)

        liked_ids = await client.get_liked_ids(123456)

        self.assertEqual(liked_ids, [])
        self.assertEqual(http.simple_calls, [("POST", "http://netease.example/likelist")])

    async def test_cloud_song_placeholder_falls_back_to_authenticated_cloud_lyric(self) -> None:
        cloud_lrc = "[00:01.00]故事的小黄花\n[00:05.00]从出生那年就飘着"

        def responder(method, url, payload):
            if url.endswith("/lyric/new"):
                return {"code": 200, "lrc": {"lyric": "[00:00.00]暂无歌词"}}
            if url.endswith("/login/status"):
                return {"data": {"profile": {"userId": 399919346}}}
            if url.endswith("/cloud/lyric/get"):
                return {"code": 200, "lrc": cloud_lrc}
            return {"code": 404}

        client, http = self._client(responder)

        lyric, tlyric = await client.get_lyrics(555816758)

        self.assertEqual(lyric, cloud_lrc)
        self.assertIsNone(tlyric)
        self.assertEqual(
            http.simple_calls,
            [
                ("GET", "http://netease.example/lyric/new"),
                ("POST", "http://netease.example/login/status"),
                ("POST", "http://netease.example/cloud/lyric/get"),
            ],
        )
        _method, _url, cloud_payload, cloud_headers = http.calls[-1]
        self.assertEqual(cloud_payload["uid"], 399919346)
        self.assertEqual(cloud_payload["sid"], 555816758)
        self.assertEqual(cloud_payload["cookie"], "MUSIC_U=abc")
        self.assertEqual(cloud_headers["Cookie"], "MUSIC_U=abc")

    async def test_regular_lyric_does_not_call_cloud_endpoints(self) -> None:
        normal_lrc = "[00:01.00]一首普通歌曲的歌词"

        def responder(method, url, payload):
            return {
                "code": 200,
                "lrc": {"lyric": normal_lrc},
                "tlyric": {"lyric": "[00:01.00]translated"},
            }

        client, http = self._client(responder)

        lyric, tlyric = await client.get_lyrics(186016)

        self.assertEqual(lyric, normal_lrc)
        self.assertEqual(tlyric, "[00:01.00]translated")
        self.assertEqual(http.simple_calls, [("GET", "http://netease.example/lyric/new")])

    async def test_get_song_url_rejects_free_trial_audio(self) -> None:
        def responder(method, url, payload):
            if method == "POST":
                return {
                    "code": 200,
                    "data": [{
                        "id": 2,
                        "url": "https://music.example/trial.mp3",
                        "time": 30040,
                        "size": 600_000,
                        "freeTrialInfo": {"start": 0, "end": 30},
                    }],
                }
            return {"code": 200, "data": [{"id": 2, "url": None}]}

        client, http = self._client(responder)

        url = await client.get_song_url(2, expected_duration_ms=240000, song_name="会员歌")

        self.assertIsNone(url)
        self.assertIn("试听音频", client.last_song_url_error)
        self.assertGreaterEqual(len(http.calls), 2)

    async def test_get_song_url_rejects_mismatched_response_id(self) -> None:
        """上游 NeteaseCloudMusicApi 偶发的缓存错乱：请求 id=A 返回 id=B 的 URL。
        必须在客户端拦截，否则会播错歌（UI 显示 A、实际播 B）。"""

        def responder(method, url, payload):
            return {
                "code": 200,
                "data": [{
                    "id": 999,  # 错乱：跟请求的 1318235595 不一致
                    "url": "https://music.example/wrong.mp3",
                    "time": 269828,
                    "size": 10_808_214,
                }],
            }

        client, http = self._client(responder)

        url = await client.get_song_url(1318235595, expected_duration_ms=241266, song_name="耳朵")

        self.assertIsNone(url, "id 不匹配时必须丢弃错乱的 URL")
        self.assertIn("错乱", client.last_song_url_error)
        self.assertGreaterEqual(len(http.calls), 2)

    async def test_get_song_url_includes_timestamp_to_bust_cache(self) -> None:
        """请求里必须带 timestamp，破上游本地缓存防止拿到上一次的错乱响应。"""

        def responder(method, url, payload):
            if method == "POST":
                return {
                    "code": 200,
                    "data": [{
                        "id": 100,
                        "url": "https://music.example/ok.mp3",
                        "time": 222000,
                        "size": 8_000_000,
                    }],
                }
            return {"code": 500, "data": []}

        client, http = self._client(responder)
        url = await client.get_song_url(100, expected_duration_ms=222000, song_name="A")

        self.assertEqual(url, "https://music.example/ok.mp3")
        self.assertGreaterEqual(len(http.calls), 1)
        _method, _url, first_params, _headers = http.calls[0]
        self.assertIn("timestamp", first_params, "请求必须带 timestamp 破上游缓存")
        self.assertGreater(int(first_params["timestamp"]), 0)


if __name__ == "__main__":
    unittest.main()
