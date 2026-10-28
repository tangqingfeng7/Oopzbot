import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from app import runtime  # noqa: E402


class RuntimeConfigValidationTest(unittest.TestCase):
    def test_unset_route_environment_preserves_configured_routes(self) -> None:
        config = {"base_url": "https://gateway2.oopz.cn", "ws_url": "wss://custom.example/ws"}
        with (
            mock.patch.object(runtime.runtime_config, "OOPZ_CONFIG", config),
            mock.patch.dict("os.environ", {}, clear=True),
        ):
            runtime.apply_runtime_overrides()
        self.assertEqual(config["base_url"], "https://gateway2.oopz.cn")
        self.assertEqual(config["ws_url"], "wss://custom.example/ws")

    def test_environment_can_select_official_routes_without_changing_credentials(self):
        config = {"jwt_token": "test-token", "ws_url": "wss://ws.oopz.cn"}
        with (
            mock.patch.object(runtime.runtime_config, "OOPZ_CONFIG", config),
            mock.patch.dict("os.environ", {
                "BOT_OOPZ_BASE_URL": " https://gateway1.oopz.cn/ ",
                "BOT_OOPZ_WS_URL": " wss://ws1.oopz.cn ",
            }),
        ):
            runtime.apply_runtime_overrides()
        self.assertEqual(config["base_url"], "https://gateway1.oopz.cn")
        self.assertEqual(config["ws_url"], "wss://ws1.oopz.cn")
        self.assertEqual(config["jwt_token"], "test-token")

    def test_empty_websocket_environment_restores_automatic_pairing(self):
        config = {"ws_url": "wss://ws.oopz.cn"}
        with (
            mock.patch.object(runtime.runtime_config, "OOPZ_CONFIG", config),
            mock.patch.dict("os.environ", {"BOT_OOPZ_WS_URL": ""}),
        ):
            runtime.apply_runtime_overrides()
        self.assertEqual(config["ws_url"], "")

    def test_rejects_removed_proxy_trust_switch(self) -> None:
        config = {
            "trust_proxy_header": False,
            "trusted_proxy_cidrs": ["127.0.0.1/32"],
        }
        with (
            mock.patch.object(runtime.runtime_config, "WEB_PLAYER_CONFIG", config),
            self.assertRaisesRegex(ValueError, "trust_proxy_header 已移除"),
        ):
            runtime.validate_runtime_config()

    def test_accepts_valid_ipv4_and_ipv6_proxy_networks(self) -> None:
        config = {"trusted_proxy_cidrs": ["127.0.0.1/32", "fd00::/8"]}
        with mock.patch.object(runtime.runtime_config, "WEB_PLAYER_CONFIG", config):
            runtime.validate_runtime_config()

    def test_environment_overrides_trusted_proxy_networks(self) -> None:
        config = {}
        with (
            mock.patch.object(runtime.runtime_config, "WEB_PLAYER_CONFIG", config),
            mock.patch.dict(
                "os.environ",
                {"BOT_WEB_TRUSTED_PROXY_CIDRS": "172.30.255.2/32, ::1/128"},
                clear=False,
            ),
        ):
            runtime.apply_runtime_overrides()
        self.assertEqual(
            config["trusted_proxy_cidrs"],
            ["172.30.255.2/32", "::1/128"],
        )

    def test_environment_overrides_redis_network_timeouts(self) -> None:
        config = {}
        with (
            mock.patch.object(runtime.runtime_config, "REDIS_CONFIG", config),
            mock.patch.dict(
                "os.environ",
                {
                    "BOT_REDIS_CONNECT_TIMEOUT": "1.5",
                    "BOT_REDIS_SOCKET_TIMEOUT": "7",
                    "BOT_REDIS_HEALTH_CHECK_INTERVAL": "45",
                },
                clear=False,
            ),
        ):
            runtime.apply_runtime_overrides()

        self.assertEqual(config["socket_connect_timeout"], 1.5)
        self.assertEqual(config["socket_timeout"], 7.0)
        self.assertEqual(config["health_check_interval"], 45)

    def test_rejects_non_positive_redis_timeout(self) -> None:
        config = {"socket_timeout": 0}
        with (
            mock.patch.object(runtime.runtime_config, "REDIS_CONFIG", config),
            self.assertRaisesRegex(ValueError, "socket_timeout 必须是正数"),
        ):
            runtime.validate_runtime_config()

    def test_rejects_non_finite_redis_timeout(self) -> None:
        config = {"socket_timeout": "nan"}
        with (
            mock.patch.object(runtime.runtime_config, "REDIS_CONFIG", config),
            self.assertRaisesRegex(ValueError, "socket_timeout 必须是正数"),
        ):
            runtime.validate_runtime_config()

    def test_rejects_invalid_timeout_environment_value(self) -> None:
        config = {}
        with (
            mock.patch.object(runtime.runtime_config, "REDIS_CONFIG", config),
            mock.patch.dict(
                "os.environ",
                {"BOT_REDIS_CONNECT_TIMEOUT": "not-a-number"},
                clear=False,
            ),
            self.assertRaisesRegex(ValueError, "BOT_REDIS_CONNECT_TIMEOUT 必须是数字"),
        ):
            runtime.apply_runtime_overrides()


class NginxCompatibilityConfigTest(unittest.TestCase):
    def test_http2_syntax_remains_compatible_with_nginx_1_24(self) -> None:
        for relative_path in ("nginx/nginx.conf", "nginx/nginx.docker.conf"):
            with self.subTest(path=relative_path):
                content = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
                self.assertIn("listen 443 ssl http2;", content)
                self.assertNotRegex(content, r"(?m)^\s*http2\s+on\s*;")


class DockerRuntimeConfigTest(unittest.TestCase):
    def test_image_installs_both_chromium_variants_in_shared_path(self) -> None:
        content = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("PLAYWRIGHT_BROWSERS_PATH=/ms-playwright", content)
        self.assertIn("playwright install --with-deps chromium", content)
        self.assertNotIn("--no-shell", content)
        self.assertNotIn("PLAYWRIGHT_CHROMIUM_USE_HEADLESS_SHELL", content)
        self.assertIn('chmod -R a+rX "${PLAYWRIGHT_BROWSERS_PATH}"', content)

    def test_image_gives_bot_dedicated_writable_home_and_xdg_paths(self) -> None:
        content = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("HOME=/home/bot", content)
        self.assertIn("XDG_CACHE_HOME=/home/bot/.cache", content)
        self.assertIn("XDG_CONFIG_HOME=/home/bot/.config", content)
        self.assertIn("XDG_DATA_HOME=/home/bot/.local/share", content)
        self.assertIn("XDG_RUNTIME_DIR=/home/bot/.runtime", content)
        self.assertIn("--home-dir /home/bot --create-home", content)
        self.assertIn("chown -R bot:bot /home/bot", content)
        self.assertNotIn("--home-dir /app", content)
        self.assertNotRegex(content, r"chown\s+-R\s+bot:bot\s+/app(?:\s|$)")

    def test_compose_forwards_configurable_bot_uid_and_gid(self) -> None:
        dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
        compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn("ARG BOT_UID=1000", dockerfile)
        self.assertIn("ARG BOT_GID=1000", dockerfile)
        self.assertIn('groupadd --non-unique --gid "${BOT_GID}" bot', dockerfile)
        self.assertIn('useradd --non-unique --uid "${BOT_UID}"', dockerfile)
        self.assertIn('BOT_UID: "${BOT_UID:-1000}"', compose)
        self.assertIn('BOT_GID: "${BOT_GID:-1000}"', compose)

    def test_compose_preserves_shutdown_and_writable_runtime_contracts(self) -> None:
        compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
        quickstart = (REPO_ROOT / "docs/quickstart.md").read_text(encoding="utf-8")

        self.assertIn("stop_grace_period: 30s", compose)
        self.assertNotIn("./config.py:/app/config.py", compose)
        self.assertNotIn("./private_key.py:/app/private_key.py", compose)
        self.assertIn("./config:/app/config", compose)
        self.assertIn("ln -s /app/config/runtime.py /app/config.py", dockerfile)
        self.assertIn("ln -s /app/config/private_key.py /app/private_key.py", dockerfile)
        self.assertIn("mkdir -p config data logs", quickstart)
        self.assertIn("cp config.example.py config/runtime.py", quickstart)
        self.assertIn("openssl req -x509", quickstart)

    def test_runtime_config_secrets_are_excluded_from_git_and_build_context(self) -> None:
        gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        dockerignore = (REPO_ROOT / ".dockerignore").read_text(
            encoding="utf-8"
        ).splitlines()

        self.assertIn("/config/runtime.py", gitignore)
        self.assertIn("/config/private_key.py", gitignore)
        self.assertIn("config/runtime.py", dockerignore)
        self.assertIn("config/private_key.py", dockerignore)

    def test_compose_forwards_documented_runtime_environment(self) -> None:
        compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

        expected = {
            "BOT_REDIS_PORT",
            "BOT_REDIS_PASSWORD",
            "BOT_REDIS_DB",
            "BOT_NETEASE_BASE_URL",
            "BOT_OOPZ_PROXY",
            "BOT_DISABLE_AUTO_START_NETEASE",
            "BOT_DISABLE_VOICE",
            "BOT_LOG_CONSOLE_LEVEL",
            "BOT_LOG_FILE_LEVEL",
        }
        for variable in expected:
            with self.subTest(variable=variable):
                self.assertIn(f'{variable}: "${{{variable}:-', compose)

        # 空 YAML 值由 Compose 从 shell / .env 解析，区分未设置与显式空字符串。
        for variable in ("BOT_OOPZ_BASE_URL", "BOT_OOPZ_WS_URL"):
            with self.subTest(variable=variable):
                self.assertIn(f"      {variable}:\n", compose)

    def test_docker_ci_runs_real_browsers_and_bind_mount_write(self) -> None:
        workflow = (REPO_ROOT / ".github/workflows/docker-build.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("Verify non-root Chromium runtime", workflow)
        self.assertIn('assert Path.home() == Path("/home/bot")', workflow)
        self.assertIn('probe.write_text(variable, encoding="utf-8")', workflow)
        self.assertIn('(\"default-headless\", {})', workflow)
        self.assertIn('(\"chromium-channel\", {\"channel\": \"chromium\"})', workflow)
        self.assertIn("Verify host bind-mount ownership override", workflow)
        self.assertIn('--build-arg BOT_UID="$host_uid"', workflow)
        self.assertIn("--build-arg BOT_GID=100", workflow)
        self.assertIn('Path("/app/data/.write-test").write_text("data"', workflow)
        self.assertIn('persist_admin_uids(["docker-ci"])', workflow)
        self.assertIn('Path("/app/config.py").is_symlink()', workflow)


if __name__ == "__main__":
    unittest.main()
