"""启动期凭据刷新策略。
"""

import sys
import time
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import oopz.sdk_config as sdk_config  # noqa: E402
from oopz_sdk.auth.manager import DEFAULT_REFRESH_THRESHOLD_SECONDS  # noqa: E402


def _jwt(exp: float | None) -> str:
    import base64
    import json

    def b64(obj) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    payload = {"exp": exp} if exp is not None else {"sub": "u1"}
    return f"{b64({'alg': 'RS256'})}.{b64(payload)}.sig"


class _Config:
    """只实现被判定逻辑用到的那部分 OopzConfig 接口。"""

    def __init__(self, *, jwt_token: str, has_creds: bool = True):
        self.jwt_token = jwt_token
        self._has_creds = has_creds

    def has_credentials(self) -> bool:
        return self._has_creds


class StartupLoginDecisionTest(unittest.TestCase):
    def test_fresh_token_does_not_trigger_relogin(self) -> None:
        config = _Config(jwt_token=_jwt(time.time() + 30 * 86400))
        self.assertFalse(sdk_config._startup_login_needed(cast("Any", config)))

    def test_token_inside_refresh_window_triggers_relogin(self) -> None:
        config = _Config(jwt_token=_jwt(time.time() + DEFAULT_REFRESH_THRESHOLD_SECONDS / 2))
        self.assertTrue(sdk_config._startup_login_needed(cast("Any", config)))

    def test_expired_token_triggers_relogin(self) -> None:
        config = _Config(jwt_token=_jwt(time.time() - 3600))
        self.assertTrue(sdk_config._startup_login_needed(cast("Any", config)))

    def test_missing_credentials_trigger_relogin(self) -> None:
        config = _Config(jwt_token=_jwt(time.time() + 30 * 86400), has_creds=False)
        self.assertTrue(sdk_config._startup_login_needed(cast("Any", config)))

    def test_token_without_exp_falls_back_to_relogin(self) -> None:
        """没有 exp 就无从判断新鲜度，保守重登而不是赌它还有效。"""
        config = _Config(jwt_token=_jwt(None))
        self.assertTrue(sdk_config._startup_login_needed(cast("Any", config)))

    def test_threshold_matches_the_sdk_runtime_refresh_window(self) -> None:
        """启动期与运行期用同一个阈值，避免两条路径对「临期」的判断打架。"""
        just_outside = _Config(jwt_token=_jwt(time.time() + DEFAULT_REFRESH_THRESHOLD_SECONDS + 60))
        just_inside = _Config(jwt_token=_jwt(time.time() + DEFAULT_REFRESH_THRESHOLD_SECONDS - 60))

        self.assertFalse(sdk_config._startup_login_needed(cast("Any", just_outside)))
        self.assertTrue(sdk_config._startup_login_needed(cast("Any", just_inside)))


class StartupLoginIntegrationTest(unittest.IsolatedAsyncioTestCase):
    """凭据新鲜时，启动不得发起登录，也不得改写凭据文件。"""

    async def test_sdk_builder_keeps_automatic_route_pairing(self):
        with (
            patch.dict(sdk_config.OOPZ_CONFIG, {
                "base_url": "https://gateway1.oopz.cn", "ws_url": "",
            }),
            patch.object(sdk_config, "_login_account", return_value=("", "")),
            patch.object(sdk_config, "_load_private_key", return_value="test-key"),
            patch.object(sdk_config, "_onebot_v11_config", AsyncMock(return_value=None)),
            patch.object(sdk_config.OopzConfig, "ensure_credentials"),
        ):
            config, _proxy, _raw_proxy = await sdk_config.build_sdk_config()
        self.assertEqual(config.ws_url, "wss://ws1.oopz.cn")

    async def test_fresh_credentials_skip_login_and_persist(self) -> None:
        login = AsyncMock()
        persist = AsyncMock()

        with (
            patch.object(sdk_config, "login_with_password", login),
            patch.object(sdk_config, "_persist_credentials", persist),
            patch.object(sdk_config, "_startup_login_needed", return_value=False),
            patch.object(sdk_config, "_login_account", return_value=("13800138000", "pw")),
            patch.object(sdk_config, "_load_private_key", return_value="pem"),
            patch.object(sdk_config, "_onebot_v11_config", AsyncMock(return_value=None)),
            # 不能依赖运行环境的 config.py 里有真实凭据：CI 与容器用的都是
            # config.example.py，那里的凭据是空的，会在收尾校验处直接抛错。
            patch.object(sdk_config.OopzConfig, "ensure_credentials", create=True),
        ):
            config, _proxy, _proxy_value = await sdk_config.build_sdk_config()

        login.assert_not_awaited()
        persist.assert_not_awaited()
        # 即便跳过登录，续期回调仍要装上，运行期失效时才能自愈
        self.assertIsNotNone(config._auth_relogin)

    async def test_stale_credentials_relogin_and_persist(self) -> None:
        credentials = object()
        login = AsyncMock(return_value=credentials)
        persist = AsyncMock()

        with (
            patch.object(sdk_config, "login_with_password", login),
            patch.object(sdk_config, "_persist_credentials", persist),
            patch.object(sdk_config, "_startup_login_needed", return_value=True),
            patch.object(sdk_config, "_login_account", return_value=("13800138000", "pw")),
            patch.object(sdk_config, "_load_private_key", return_value="pem"),
            patch.object(sdk_config, "_onebot_v11_config", AsyncMock(return_value=None)),
            patch.object(sdk_config.OopzConfig, "_apply_login_credentials", create=True),
            patch.object(sdk_config.OopzConfig, "ensure_credentials", create=True),
        ):
            await sdk_config.build_sdk_config()

        login.assert_awaited_once()
        persist.assert_awaited_once_with(credentials)

    async def test_login_failure_still_lets_existing_credentials_start(self) -> None:
        """刷新失败不应直接拒绝启动——已有凭据可能仍然有效。"""
        login = AsyncMock(side_effect=RuntimeError("network down"))

        with (
            patch.object(sdk_config, "login_with_password", login),
            patch.object(sdk_config, "_persist_credentials", AsyncMock()),
            patch.object(sdk_config, "_startup_login_needed", return_value=True),
            patch.object(sdk_config, "_login_account", return_value=("13800138000", "pw")),
            patch.object(sdk_config, "_load_private_key", return_value="pem"),
            patch.object(sdk_config, "_onebot_v11_config", AsyncMock(return_value=None)),
            patch.object(sdk_config.OopzConfig, "ensure_credentials", create=True),
        ):
            config, _proxy, _proxy_value = await sdk_config.build_sdk_config()

        login.assert_awaited_once()
        self.assertIsNotNone(config._auth_relogin)

    async def test_relogin_callback_is_installed_without_account(self) -> None:
        """没配账号密码时不该装续期回调，否则运行期会拿空账号去登录。"""
        with (
            patch.object(sdk_config, "_login_account", return_value=("", "")),
            patch.object(sdk_config, "_load_private_key", return_value="pem"),
            patch.object(sdk_config, "_onebot_v11_config", AsyncMock(return_value=None)),
            patch.object(sdk_config.OopzConfig, "ensure_credentials", create=True),
        ):
            config, _proxy, _proxy_value = await sdk_config.build_sdk_config()

        self.assertIsNone(getattr(config, "_auth_relogin", None))


if __name__ == "__main__":
    unittest.main()
