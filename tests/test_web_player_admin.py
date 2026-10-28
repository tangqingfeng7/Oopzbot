import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

try:
    from fastapi.testclient import TestClient
    _TESTCLIENT_ERROR = None
except Exception as exc:  # pragma: no cover - 依赖缺失时跳过
    TestClient = None
    _TESTCLIENT_ERROR = exc


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


from domain.plugins.base import (  # noqa: E402
    PluginCommandCapabilities,
    PluginDescriptor,
    PluginMetadata,
)
from domain.plugins.plugin_operation import PluginOperationResult  # noqa: E402


class _FakePlugins:
    def __init__(self):
        self._descriptors = [
            PluginDescriptor(
                metadata=PluginMetadata(name="alpha", description="alpha desc", version="1.0.0"),
                capabilities=PluginCommandCapabilities(
                    mention_prefixes=("alpha",),
                    slash_commands=("alpha",),
                    is_public_command=True,
                ),
                builtin=False,
            )
        ]

    def discover(self):
        return ["alpha"]

    def list_descriptors(self):
        return list(self._descriptors)

    def enabled_plugin_names(self):
        return ["alpha"]

    def get_last_results(self):
        return {}

    @property
    def state_path(self):
        return "data/plugin_runtime_state.json"


class _FakeNeteaseResponse:
    def __init__(self, payload, headers=None, cookies=None):
        self._payload = payload
        self.headers = headers or {}
        self.cookies = cookies or []

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeRedisPipeline:
    """按 RedisPipeline 协议：入队是同步的，只有 execute 异步。"""

    def __init__(self, redis):
        self.redis = redis
        self.keys = []

    def get(self, key):
        self.keys.append(key)
        return self

    async def execute(self):
        return [await self.redis.get(key) for key in self.keys]


class _FakeRedis:
    """按 RedisDataStore 协议：读写异步，pipeline() 本身同步。"""

    def __init__(self):
        self.store = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, *args, **kwargs):
        self.store[key] = value
        return True

    def seed(self, key, value):
        """同步播种，供用例准备初始状态用。"""
        self.store[key] = value
        return self

    async def delete(self, *keys):
        removed = 0
        for key in keys:
            if self.store.pop(key, None) is not None:
                removed += 1
        return removed

    async def lrange(self, key, start, end):
        values = list(self.store.get(key, []))
        if end == -1:
            return values[start:]
        return values[start:end + 1]

    def pipeline(self, transaction=False):
        return _FakeRedisPipeline(self)


class WebPlayerAdminTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        if TestClient is None:
            self.skipTest(f"缺少 TestClient 依赖: {_TESTCLIENT_ERROR}")
        import web.web_player as web_player

        self.module = web_player
        self.module.register_runtime_dependencies(
            music=SimpleNamespace(),
            plugins=_FakePlugins(),
            plugin_host=SimpleNamespace(),
        )
        # 限流器与登录锁定是模块级单例，TestClient 的所有请求又共用 "testclient"
        # 这一个桶；不重置会让用例按执行顺序随机拿 429。
        import web.web_rate_limit as web_rate_limit

        web_rate_limit.reset_all()
        self.client = TestClient(self.module.app, client=("127.0.0.1", 50000))

    def test_plugins_api_requires_login(self) -> None:
        with patch.object(self.module, "_admin_enabled", return_value=True):
            response = self.client.get("/admin/api/plugins")

        self.assertEqual(response.status_code, 401)

    def test_screen_share_heartbeat_rate_limit_is_per_presenter(self) -> None:
        service = SimpleNamespace(heartbeat=AsyncMock(return_value={"ok": True}))
        with patch("screen_share.web.get_screen_share_service", return_value=service):
            for _ in range(30):
                response = self.client.post(
                    "/screen-share/api/presenter/heartbeat",
                    headers={"Cookie": "oopz_screen_presenter=presenter-a"},
                )
                self.assertEqual(response.status_code, 200)
            blocked = self.client.post(
                "/screen-share/api/presenter/heartbeat",
                headers={"Cookie": "oopz_screen_presenter=presenter-a"},
            )
            other_presenter = self.client.post(
                "/screen-share/api/presenter/heartbeat",
                headers={"Cookie": "oopz_screen_presenter=presenter-b"},
            )

        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(other_presenter.status_code, 200)

    def test_screen_share_stop_api_requires_admin_login(self) -> None:
        with patch.object(self.module, "_admin_enabled", return_value=True):
            response = self.client.post(
                "/admin/api/screen-shares/session-abcdefghijkl/stop",
                json={},
            )

        self.assertEqual(response.status_code, 401)

    def test_logged_in_admin_can_stop_one_screen_share(self) -> None:
        session_id = "session-abcdefghijkl"
        session = {
            "id": session_id,
            "status": "active",
            "area": "area-1",
            "channel": "channel-1",
            "presenter_uid": "user-1",
        }
        service = SimpleNamespace(stop_by_id=AsyncMock(return_value=session))
        announce = AsyncMock()
        with (
            patch.object(self.module, "_admin_enabled", return_value=True),
            patch.object(self.module, "_is_admin_authorized", return_value=True),
            patch(
                "web.admin.screen_share.get_screen_share_service",
                return_value=service,
            ),
            patch("web.admin.screen_share.announce_ended", announce),
        ):
            response = self.client.post(
                f"/admin/api/screen-shares/{session_id}/stop",
                json={},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["session_id"], session_id)
        service.stop_by_id.assert_awaited_once_with(session_id, reason="admin_stop")
        announce.assert_awaited_once_with(session)

    def test_plugins_api_returns_inventory_when_logged_in(self) -> None:
        with (
            patch.object(self.module, "_admin_enabled", return_value=True),
            patch.object(self.module, "_is_admin_authorized", return_value=True),
        ):
            response = self.client.get("/admin/api/plugins")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["enabled_plugins"], ["alpha"])
        self.assertEqual(data["plugins"][0]["name"], "alpha")

    def test_plugin_load_rejects_invalid_name(self) -> None:
        with (
            patch.object(self.module, "_admin_enabled", return_value=True),
            patch.object(self.module, "_is_admin_authorized", return_value=True),
        ):
            response = self.client.post("/admin/api/plugins/bad-name/load")

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["ok"])
        self.assertIn("插件名不合法", data["error"])

    def test_plugin_runtime_operations_are_awaited(self) -> None:
        import web.admin.plugins as plugin_routes

        host = SimpleNamespace()
        operations = (
            ("load", "/admin/api/plugins/alpha/load", "已加载 alpha"),
            ("unload", "/admin/api/plugins/alpha/unload", "已卸载 alpha"),
            ("reload_config", "/admin/api/plugins/alpha/reload-config", "配置已重载 alpha"),
        )

        for method_name, path, message in operations:
            with self.subTest(path=path):
                operation = AsyncMock(
                    return_value=PluginOperationResult.success(
                        message,
                        plugin_name="alpha",
                    )
                )
                runtime = SimpleNamespace(**{method_name: operation})
                with (
                    patch.object(self.module, "_admin_enabled", return_value=True),
                    patch.object(self.module, "_is_admin_authorized", return_value=True),
                    patch.object(plugin_routes, "_get_plugin_runtime", return_value=runtime),
                    patch.object(plugin_routes, "_get_plugin_host", return_value=host),
                ):
                    response = self.client.post(path)

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {"ok": True, "message": message})
                operation.assert_awaited_once_with("alpha", handler=host)

    def test_member_endpoint_returns_503_when_sender_missing(self) -> None:
        import web.admin.shared._runtime as runtime

        with (
            patch.object(self.module, "_admin_enabled", return_value=True),
            patch.object(self.module, "_is_admin_authorized", return_value=True),
            patch.object(runtime, "_get_sender", return_value=None),
        ):
            response = self.client.get("/admin/api/members/blocks")

        self.assertEqual(response.status_code, 503)
        data = response.json()
        self.assertFalse(data["ok"])
        self.assertEqual(data["error"], "sender 未初始化")

    def test_player_page_does_not_pin_stale_active_area(self) -> None:
        r = _FakeRedis()
        r.seed("music:web_access_token", "token-1")
        r.seed("music:web_active_area", "old-area")

        with patch.object(self.module, "get_redis", AsyncMock(return_value=r)):
            response = self.client.get("/w/token-1")

        self.assertEqual(response.status_code, 200)
        self.assertIn('window.__OOPZ_AREA__=""', response.text)
        self.assertNotIn("old-area", response.text)

    def test_player_page_can_pin_area_when_query_says_so(self) -> None:
        r = _FakeRedis()
        r.seed("music:web_access_token", "token-1")
        r.seed("music:web_active_area", "old-area")

        with patch.object(self.module, "get_redis", AsyncMock(return_value=r)):
            response = self.client.get("/w/token-1?area=area-2")

        self.assertEqual(response.status_code, 200)
        self.assertIn('window.__OOPZ_AREA__="area-2"', response.text)

    def test_player_cookie_is_not_secure_on_plain_http(self) -> None:
        r = _FakeRedis()
        r.seed("music:web_access_token", "token-1")

        with (
            patch.object(self.module, "get_redis", AsyncMock(return_value=r)),
            patch.object(self.module.cfg, "cookie_secure", return_value=True),
        ):
            response = self.client.get("/w/token-1")

        self.assertEqual(response.status_code, 200)
        self.assertIn("web_token=token-1", response.headers["set-cookie"])
        self.assertNotIn("Secure", response.headers["set-cookie"])

    def test_player_cookie_stays_secure_behind_https_proxy(self) -> None:
        r = _FakeRedis()
        r.seed("music:web_access_token", "token-1")

        with (
            patch.object(self.module, "get_redis", AsyncMock(return_value=r)),
            patch.object(self.module.cfg, "cookie_secure", return_value=True),
        ):
            response = self.client.get("/w/token-1", headers={"x-forwarded-proto": "https"})

        self.assertEqual(response.status_code, 200)
        self.assertIn("web_token=token-1", response.headers["set-cookie"])
        self.assertIn("Secure", response.headers["set-cookie"])

    def _admin_login(self, headers=None):
        """走真实的 /admin/api/login，用于断言后台 Cookie 的 Secure 属性。"""
        r = _FakeRedis()
        with (
            patch.object(self.module, "get_redis", AsyncMock(return_value=r)),
            patch.object(self.module, "_admin_enabled", return_value=True),
            patch.object(self.module.cfg, "admin_password", return_value="pw"),
            patch.object(self.module.cfg, "admin_cookie_secure", return_value=True),
        ):
            return self.client.post(
                "/admin/api/login",
                json={"password": "pw"},
                headers=headers or {},
            )

    def test_admin_cookie_is_not_secure_on_plain_http(self) -> None:
        # 回归：HTTP 部署下若照配置打 Secure，浏览器不回传 Cookie，
        # 表现为登录接口返回 200 但下一个请求就 401（登录后被踢回登录页的死循环）
        response = self._admin_login()

        self.assertEqual(response.status_code, 200)
        self.assertIn(f"{self.module.cfg.admin_cookie_name()}=", response.headers["set-cookie"])
        self.assertNotIn("Secure", response.headers["set-cookie"])

    def test_admin_cookie_stays_secure_behind_https_proxy(self) -> None:
        response = self._admin_login(headers={"x-forwarded-proto": "https"})

        self.assertEqual(response.status_code, 200)
        self.assertIn("Secure", response.headers["set-cookie"])

    def _health(self, *, as_admin: bool):
        r = _FakeRedis()
        with (
            patch.object(self.module, "get_redis", AsyncMock(return_value=r)),
            patch.object(self.module, "_is_admin_authorized", return_value=as_admin),
        ):
            return self.client.get("/health")

    def test_health_is_redacted_for_anonymous_callers(self) -> None:
        body = self._health(as_admin=False).json()

        # 明细里含 Redis/DB/网易云登录态与原始异常文本，不能对匿名调用者暴露
        self.assertEqual(set(body), {"status"})
        self.assertIn(body["status"], {"healthy", "degraded"})

    def test_health_returns_detail_for_logged_in_admin(self) -> None:
        body = self._health(as_admin=True).json()

        self.assertIn("checks", body)
        self.assertIn("uptime_seconds", body)

    def test_health_status_code_is_unaffected_by_redaction(self) -> None:
        # Docker healthcheck 用 urlopen 只看状态码，脱敏不能改变它
        self.assertEqual(
            self._health(as_admin=False).status_code,
            self._health(as_admin=True).status_code,
        )

    def _admin_login_with_password(self, password: str):
        r = _FakeRedis()
        with (
            patch.object(self.module, "get_redis", AsyncMock(return_value=r)),
            patch.object(self.module, "_admin_enabled", return_value=True),
            patch.object(self.module.cfg, "admin_password", return_value="pw"),
            patch.object(self.module.cfg, "admin_login_max_failures", return_value=3),
            patch.object(self.module.cfg, "admin_login_lock_seconds", return_value=300),
        ):
            return self.client.post("/admin/api/login", json={"password": password})

    def test_repeated_login_failures_lock_the_source_out(self) -> None:
        for _ in range(3):
            self.assertEqual(self._admin_login_with_password("wrong").status_code, 401)

        # 锁定后即使密码正确也不放行
        locked = self._admin_login_with_password("pw")
        self.assertEqual(locked.status_code, 429)
        self.assertIn("Retry-After", locked.headers)

    def test_successful_login_clears_failure_counter(self) -> None:
        self.assertEqual(self._admin_login_with_password("wrong").status_code, 401)
        self.assertEqual(self._admin_login_with_password("pw").status_code, 200)

        # 计数已清零，再错两次不应触发锁定（阈值为 3）
        for _ in range(2):
            self.assertEqual(self._admin_login_with_password("wrong").status_code, 401)
        self.assertEqual(self._admin_login_with_password("pw").status_code, 200)

    def test_non_ascii_password_does_not_crash(self) -> None:
        # secrets.compare_digest 对含非 ASCII 的 str 会抛 TypeError（500）
        r = _FakeRedis()
        with (
            patch.object(self.module, "get_redis", AsyncMock(return_value=r)),
            patch.object(self.module, "_admin_enabled", return_value=True),
            patch.object(self.module.cfg, "admin_password", return_value="密码123"),
        ):
            wrong = self.client.post("/admin/api/login", json={"password": "别的"})
            right = self.client.post("/admin/api/login", json={"password": "密码123"})

        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(right.status_code, 200)

    def test_status_without_area_follows_active_area(self) -> None:
        r = _FakeRedis()
        r.seed("music:web_access_token", "token-1")
        r.seed("music:web_active_area", "area-2")
        r.seed(
            self.module._area_key(self.module.KEY_CURRENT, "area-2"),
            json.dumps({"name": "稻香", "duration_ms": 222000}, ensure_ascii=False),
        )

        self.client.cookies.set("web_token", "token-1")
        with patch.object(self.module, "get_redis", AsyncMock(return_value=r)):
            response = self.client.get("/api/status")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["playing"])
        self.assertEqual(data["name"], "稻香")

    def test_status_and_queue_keep_song_platform(self) -> None:
        r = _FakeRedis()
        r.seed("music:web_access_token", "token-1")
        r.seed("music:web_active_area", "area-2")
        r.seed(
            self.module._area_key(self.module.KEY_CURRENT, "area-2"),
            json.dumps(
                {"song_id": "BV1test", "name": "晴天", "platform": "bilibili"},
                ensure_ascii=False,
            ),
        )
        r.seed(
            self.module._area_key(self.module.KEY_QUEUE, "area-2"),
            [
                json.dumps(
                    {"song_id": "2", "name": "稻香", "platform": "qq"},
                    ensure_ascii=False,
                )
            ],
        )

        self.client.cookies.set("web_token", "token-1")
        with patch.object(self.module, "get_redis", AsyncMock(return_value=r)):
            status = self.client.get("/api/status")
            queue = self.client.get("/api/queue")

        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["platform"], "bilibili")
        self.assertEqual(queue.status_code, 200)
        self.assertEqual(queue.json()["queue"][0]["platform"], "qq")

    def test_player_page_protects_cover_requests_and_uses_song_platform(self) -> None:
        r = _FakeRedis().seed("music:web_access_token", "token-1")

        with patch.object(self.module, "get_redis", AsyncMock(return_value=r)):
            response = self.client.get("/w/token-1")

        self.assertEqual(response.status_code, 200)
        self.assertIn('<meta name="referrer" content="no-referrer">', response.text)
        self.assertNotIn('id="btnStop"', response.text)
        self.assertIn("id:'stop'", response.text)
        self.assertIn("label:'停止播放'", response.text)
        self.assertIn("body:JSON.stringify({action:'mode',value:next.id})", response.text)
        self.assertIn("fetchLyric(d.id,platform);", response.text)
        self.assertIn("platform:normalizePlatform(platform)", response.text)

    async def test_public_playback_endpoints_return_exact_409_without_area(self) -> None:
        from core.queue_manager import _InMemoryRedis

        r = _InMemoryRedis()
        await r.set("music:web_access_token", "token-1")
        self.client.cookies.set("web_token", "token-1")
        requests = (
            ("get", "/api/status", None),
            ("get", "/api/queue", None),
            ("get", "/api/debug", None),
            ("post", "/api/add", {"id": "1"}),
            ("post", "/api/control", {"action": "next"}),
            ("post", "/api/queue/action", {"action": "remove", "index": 0}),
        )

        with patch.object(self.module, "get_redis", AsyncMock(return_value=r)):
            for method, url, body in requests:
                with self.subTest(url=url):
                    call = getattr(self.client, method)
                    response = call(url, json=body) if body is not None else call(url)
                    self.assertEqual(response.status_code, 409)
                    self.assertEqual(
                        response.json(),
                        {
                            "ok": False,
                            "code": "playback_area_unavailable",
                            "error": "当前没有可用的播放域",
                        },
                    )

        for global_key in (
            self.module.KEY_QUEUE,
            self.module.KEY_CURRENT,
            self.module.KEY_PLAY_STATE,
            self.module.KEY_PLAY_MODE,
        ):
            self.assertNotIn(global_key, await r.keys())

    def test_admin_playback_endpoints_return_exact_409_without_area(self) -> None:
        import web.admin.shared._area as area_module
        from core.queue_manager import _InMemoryRedis

        r = _InMemoryRedis()
        requests = (
            ("post", "/admin/api/control", {"action": "next"}),
            ("post", "/admin/api/queue/clear", None),
            ("get", "/admin/api/queue", None),
            ("post", "/admin/api/queue/action", {"action": "remove", "index": 0}),
            ("post", "/admin/api/add", {"id": "1"}),
        )
        with (
            patch.object(self.module, "get_redis", AsyncMock(return_value=r)),
            patch.object(self.module, "_admin_enabled", return_value=True),
            patch.object(self.module, "_is_admin_authorized", return_value=True),
            patch.object(area_module.cfg, "OOPZ_CONFIG", {"default_area": ""}),
            patch.object(area_module, "get_active_area", return_value=""),
            patch.object(area_module, "_resolve_area", return_value=""),
        ):
            for method, url, body in requests:
                with self.subTest(url=url):
                    call = getattr(self.client, method)
                    response = call(url, json=body) if body is not None else call(url)
                    self.assertEqual(response.status_code, 409)
                    self.assertEqual(
                        response.json(),
                        {
                            "ok": False,
                            "code": "playback_area_unavailable",
                            "error": "当前没有可用的播放域",
                        },
                    )

    def test_global_volume_does_not_bind_to_active_area(self) -> None:
        r = _FakeRedis()
        r.seed("music:web_access_token", "token-1")
        r.seed("music:web_active_area", "area-2")

        async def fake_control(action, body, redis_client, area=""):
            return {"ok": True, "area": area, "action": action}

        with (
            patch.object(self.module, "get_redis", AsyncMock(return_value=r)),
            patch.object(self.module, "execute_control_action", side_effect=fake_control),
        ):
            self.client.cookies.set("web_token", "token-1")
            response = self.client.post("/api/control", json={"action": "volume", "volume": 50})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["area"], "")

    def test_config_update_writes_config_py(self) -> None:
        import web.web_player_config as cfg

        baseline = copy.deepcopy(cfg.CONFIG_BASELINES["web_player"])
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.py"
            config_path.write_text(
                'WEB_PLAYER_CONFIG = {\n'
                '    "url": "",\n'
                '    "host": "0.0.0.0",\n'
                '}\n',
                encoding="utf-8",
            )
            try:
                with (
                    patch.object(self.module, "_admin_enabled", return_value=True),
                    patch.object(self.module, "_is_admin_authorized", return_value=True),
                    patch.object(cfg, "CONFIG_FILE_PATH", str(config_path)),
                ):
                    response = self.client.post(
                        "/admin/api/config",
                        json={
                            "updates": {"web_player": {"url": "https://example.test"}},
                            "persist": True,
                        },
                    )

                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertTrue(data["ok"])
                self.assertTrue(data["persisted"])
                self.assertEqual(data["config_source"], "config.py")
                self.assertIn('"url": "https://example.test"', config_path.read_text(encoding="utf-8"))
            finally:
                cfg.WEB_PLAYER_CONFIG.clear()
                cfg.WEB_PLAYER_CONFIG.update(copy.deepcopy(baseline))

    def test_oopz_login_payload_falls_back_to_config_account(self) -> None:
        import web.web_player_config as cfg
        from web.admin.config import _parse_oopz_login_payload

        with patch.object(
            cfg,
            "OOPZ_CONFIG",
            {"login_phone": "13800138000", "login_password": "plain-password"},
        ):
            phone, password, timeout = _parse_oopz_login_payload({})

        self.assertEqual(phone, "13800138000")
        self.assertEqual(password, "plain-password")
        self.assertEqual(timeout, 90.0)

    def test_netease_qr_login_returns_qr_image_when_logged_in(self) -> None:
        calls = []

        def fake_get(base_url, path, params=None, **_kwargs):
            calls.append((base_url, path, params or {}))
            if path == "/login/qr/key":
                payload = {"code": 200, "data": {"unikey": "qr-key"}}
                return payload, _FakeNeteaseResponse(payload)
            if path == "/login/qr/create":
                self.assertEqual((params or {}).get("key"), "qr-key")
                self.assertEqual((params or {}).get("qrimg"), "true")
                payload = {
                    "code": 200,
                    "data": {
                        "qrimg": "data:image/png;base64,abc",
                        "qrurl": "orpheus://qr",
                    },
                }
                return payload, _FakeNeteaseResponse(payload)
            raise AssertionError(f"unexpected path: {path}")

        with (
            patch.object(self.module, "_admin_enabled", return_value=True),
            patch.object(self.module, "_is_admin_authorized", return_value=True),
            patch("web.admin.config._netease_api_get", side_effect=fake_get),
        ):
            response = self.client.post(
                "/admin/api/netease/login/qr",
                json={"base_url": "http://localhost:3000/"},
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["key"], "qr-key")
        self.assertEqual(data["qrimg"], "data:image/png;base64,abc")
        self.assertEqual(calls[0][:2], ("http://localhost:3000", "/login/qr/key"))
        self.assertEqual(calls[1][:2], ("http://localhost:3000", "/login/qr/create"))

    def test_netease_qr_check_returns_cookie_and_profile_on_success(self) -> None:
        def fake_get(base_url, path, params=None, **_kwargs):
            self.assertEqual(base_url, "http://localhost:3000")
            self.assertEqual(path, "/login/qr/check")
            self.assertEqual((params or {}).get("key"), "qr-key")
            payload = {
                "code": 200,
                "data": {
                    "code": 803,
                    "message": "授权登录成功",
                    "cookie": "MUSIC_U=abc; __csrf=def",
                },
            }
            return payload, _FakeNeteaseResponse(payload)

        def fake_post(base_url, path, data=None, **kwargs):
            self.assertEqual(base_url, "http://localhost:3000")
            self.assertEqual(path, "/login/status")
            self.assertEqual((kwargs.get("headers") or {}).get("Cookie"), "MUSIC_U=abc; __csrf=def")
            self.assertEqual((data or {}).get("cookie"), "MUSIC_U=abc; __csrf=def")
            payload = {
                "code": 200,
                "data": {"profile": {"userId": 12345, "nickname": "测试账号"}},
            }
            return payload, _FakeNeteaseResponse(payload)

        with (
            patch.object(self.module, "_admin_enabled", return_value=True),
            patch.object(self.module, "_is_admin_authorized", return_value=True),
            patch("web.admin.config._netease_api_get", side_effect=fake_get),
            patch("web.admin.config._netease_account_status", return_value={
                "ok": True,
                "logged_in": True,
                "profile": {"user_id": "12345", "nickname": "测试账号"},
            }),
        ):
            response = self.client.post(
                "/admin/api/netease/login/qr/check",
                json={"base_url": "http://localhost:3000", "key": "qr-key"},
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["cookie"], "MUSIC_U=abc; __csrf=def")
        self.assertEqual(data["profile"]["user_id"], "12345")
        self.assertEqual(data["profile"]["nickname"], "测试账号")

    def test_netease_account_endpoint_returns_current_profile(self) -> None:
        def fake_post(base_url, path, data=None, **kwargs):
            self.assertEqual(base_url, "http://localhost:3000")
            self.assertEqual(path, "/login/status")
            self.assertEqual((kwargs.get("headers") or {}).get("Cookie"), "MUSIC_U=abc")
            self.assertEqual((data or {}).get("cookie"), "MUSIC_U=abc")
            payload = {
                "code": 200,
                "data": {"profile": {"userId": 67890, "nickname": "已保存账号"}},
            }
            return payload, _FakeNeteaseResponse(payload)

        with (
            patch.object(self.module, "_admin_enabled", return_value=True),
            patch.object(self.module, "_is_admin_authorized", return_value=True),
            patch("web.admin.config.cfg.NETEASE_CLOUD", {"base_url": "http://localhost:3000", "cookie": "MUSIC_U=abc"}),
            patch("web.admin.config._netease_account_status", return_value={
                "ok": True,
                "logged_in": True,
                "profile": {"user_id": "67890", "nickname": "已保存账号"},
            }),
        ):
            response = self.client.get("/admin/api/netease/account")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["logged_in"])
        self.assertEqual(data["profile"]["user_id"], "67890")
        self.assertEqual(data["profile"]["nickname"], "已保存账号")

    def test_bilibili_qr_login_returns_qr_image_when_logged_in(self) -> None:
        def fake_get(path, params=None):
            self.assertEqual(path, "/x/passport-login/web/qrcode/generate")
            payload = {
                "code": 0,
                "data": {
                    "qrcode_key": "bili-key",
                    "url": "https://passport.bilibili.com/h5-app/passport/login/scan?qrcode_key=bili-key",
                },
            }
            return payload, _FakeNeteaseResponse(payload)

        with (
            patch.object(self.module, "_admin_enabled", return_value=True),
            patch.object(self.module, "_is_admin_authorized", return_value=True),
            patch("web.admin.config._bilibili_api_get", side_effect=fake_get),
            patch("web.admin.config._make_qr_data_uri", return_value="data:image/png;base64,bili"),
        ):
            response = self.client.post("/admin/api/bilibili/login/qr", json={})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["key"], "bili-key")
        self.assertEqual(data["qrimg"], "data:image/png;base64,bili")

    def test_bilibili_qr_check_returns_cookie_and_profile_on_success(self) -> None:
        def fake_get(path, params=None):
            self.assertEqual(path, "/x/passport-login/web/qrcode/poll")
            self.assertEqual((params or {}).get("qrcode_key"), "bili-key")
            payload = {
                "code": 0,
                "data": {
                    "code": 0,
                    "message": "扫描登录成功",
                    "url": (
                        "https://passport.bilibili.com/crossDomain?"
                        "DedeUserID=100&DedeUserID__ckMd5=md5&SESSDATA=sess&"
                        "bili_jct=csrf&sid=abc"
                    ),
                },
            }
            return payload, _FakeNeteaseResponse(payload)

        with (
            patch.object(self.module, "_admin_enabled", return_value=True),
            patch.object(self.module, "_is_admin_authorized", return_value=True),
            patch("web.admin.config._bilibili_api_get", side_effect=fake_get),
            patch("web.admin.config._bilibili_account_status", return_value={
                "ok": True,
                "logged_in": True,
                "profile": {"user_id": "100", "nickname": "B站测试账号"},
            }),
        ):
            response = self.client.post(
                "/admin/api/bilibili/login/qr/check",
                json={"key": "bili-key"},
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["status"], "success")
        self.assertEqual(
            data["cookie"],
            "SESSDATA=sess; bili_jct=csrf; DedeUserID=100; DedeUserID__ckMd5=md5; sid=abc",
        )
        self.assertEqual(data["profile"]["user_id"], "100")
        self.assertEqual(data["profile"]["nickname"], "B站测试账号")

    def test_bilibili_account_endpoint_returns_current_profile(self) -> None:
        def fake_get(path, headers=None):
            self.assertEqual(path, "/x/web-interface/nav")
            self.assertEqual((headers or {}).get("Cookie"), "SESSDATA=sess")
            payload = {
                "code": 0,
                "message": "0",
                "data": {
                    "isLogin": True,
                    "mid": 24680,
                    "uname": "已保存B站账号",
                    "face": "https://i0.hdslb.com/face.jpg",
                },
            }
            return payload, _FakeNeteaseResponse(payload)

        with (
            patch.object(self.module, "_admin_enabled", return_value=True),
            patch.object(self.module, "_is_admin_authorized", return_value=True),
            patch("web.admin.config.cfg.BILIBILI_MUSIC_CONFIG", {"enabled": True, "cookie": "SESSDATA=sess"}),
            patch("web.admin.config._bilibili_account_status", return_value={
                "ok": True,
                "logged_in": True,
                "profile": {"user_id": "24680", "nickname": "已保存B站账号"},
            }),
        ):
            response = self.client.get("/admin/api/bilibili/account")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["logged_in"])
        self.assertEqual(data["profile"]["user_id"], "24680")
        self.assertEqual(data["profile"]["nickname"], "已保存B站账号")

    def test_admin_html_pages_reference_shared_shell_assets(self) -> None:
        paths = [
            "/admin",
            "/admin/music",
            "/admin/config",
            "/admin/screen-share",
            "/admin/stats",
            "/admin/system",
            "/admin/setup",
        ]

        with patch.object(self.module, "_admin_enabled", return_value=True):
            for path in paths:
                with self.subTest(path=path):
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, 200)
                    self.assertIn('/admin-assets/admin-shell.css', response.text)
                    self.assertIn('/admin-assets/admin-shell.js', response.text)
                    self.assertIn('class="shell-topbar"', response.text)
                    self.assertIn('id="topNav"', response.text)
                    self.assertIn('id="mobileNav"', response.text)
                    self.assertIn('id="topStatus"', response.text)

    def test_screen_share_page_includes_confirmation_modal(self) -> None:
        with patch.object(self.module, "_admin_enabled", return_value=True):
            response = self.client.get("/admin/screen-share")

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="modalDialog"', response.text)
        self.assertIn('id="modalBody"', response.text)
        self.assertIn('id="modalFooter"', response.text)

    def test_setup_diagnostics_api_returns_report_when_logged_in(self) -> None:
        fake_report = {
            "status": "warn",
            "summary": {"pass": 3, "warn": 1, "fail": 0, "info": 1},
            "checks": [{"id": "redis", "level": "pass", "title": "Redis 连接", "summary": "Redis 连接正常"}],
            "wizard_steps": [{"id": "runtime", "status": "done", "title": "打通基础运行时"}],
            "first_run_needed": True,
            "quick_links": [],
        }

        with (
            patch.object(self.module, "_admin_enabled", return_value=True),
            patch.object(self.module, "_is_admin_authorized", return_value=True),
            patch("web.admin.music.SetupDiagnostics") as diagnostics_cls,
        ):
            diagnostics_cls.return_value.build_report = AsyncMock(return_value=fake_report)
            response = self.client.get("/admin/api/setup/diagnostics")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["status"], "warn")
        self.assertEqual(data["summary"]["warn"], 1)
        self.assertEqual(data["checks"][0]["title"], "Redis 连接")

    def test_scheduled_message_templates_api_returns_items_when_logged_in(self) -> None:
        with (
            patch.object(self.module, "_admin_enabled", return_value=True),
            patch.object(self.module, "_is_admin_authorized", return_value=True),
        ):
            response = self.client.get("/admin/api/scheduled-message-templates")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertTrue(len(data["items"]) >= 1)
        self.assertIn("key", data["items"][0])

    def test_scheduled_message_template_apply_creates_task(self) -> None:
        with (
            patch.object(self.module, "_admin_enabled", return_value=True),
            patch.object(self.module, "_is_admin_authorized", return_value=True),
            patch("web.admin.scheduler.ScheduledMessageDB.create", return_value=99) as create_task,
        ):
            response = self.client.post(
                "/admin/api/scheduled-message-templates/morning/apply",
                json={"channel_id": "channel-1", "area_id": "area-1"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], 99)
        create_task.assert_called_once()


if __name__ == "__main__":
    unittest.main()
