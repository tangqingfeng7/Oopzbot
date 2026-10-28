
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def _load_deploy() -> Any:
    """deploy.py 在仓库根目录、不是包的一部分，按路径加载。

    标成 Any：类型检查器推不出动态加载模块的属性，而测试要 patch 其中的常量。
    """
    spec = importlib.util.spec_from_file_location("deploy_script", REPO_ROOT / "deploy.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


deploy: Any = _load_deploy()


class CredentialDetectionTest(unittest.TestCase):
    """凭据判断错了会导致「没配也去启动」或「配了却不启动」。"""

    def test_phone_and_password_is_enough(self) -> None:
        self.assertTrue(
            deploy.has_usable_credentials(
                {"login_phone": "138", "login_password": "pw", "device_id": "",
                 "person_uid": "", "jwt_token": ""}
            )
        )

    def test_full_token_triple_is_enough(self) -> None:
        self.assertTrue(
            deploy.has_usable_credentials(
                {"login_phone": "", "login_password": "", "device_id": "d",
                 "person_uid": "p", "jwt_token": "t"}
            )
        )

    def test_partial_token_triple_is_not_enough(self) -> None:
        self.assertFalse(
            deploy.has_usable_credentials(
                {"login_phone": "", "login_password": "", "device_id": "d",
                 "person_uid": "p", "jwt_token": ""}
            ),
            "缺一项就连不上，不能当作已配置",
        )

    def test_phone_without_password_is_not_enough(self) -> None:
        self.assertFalse(
            deploy.has_usable_credentials(
                {"login_phone": "138", "login_password": "", "device_id": "",
                 "person_uid": "", "jwt_token": ""}
            )
        )

    def test_empty_config_is_not_enough(self) -> None:
        self.assertFalse(
            deploy.has_usable_credentials(
                dict.fromkeys(
                    ["login_phone", "login_password", "device_id", "person_uid", "jwt_token"], ""
                )
            )
        )


class NeteaseDirTest(unittest.TestCase):
    """回归背景：目录名写死成 NeteaseCloudMusicApi 会把用户改过名的
    （比如 NeteaseAPI_tmp）已装环境误报成「没装」。
    """

    def test_follows_configured_path(self) -> None:
        with patch.object(deploy, "config_value", return_value="NeteaseAPI_tmp"):
            self.assertEqual(deploy.netease_dir(), deploy.ROOT / "NeteaseAPI_tmp")

    def test_falls_back_to_default_when_unset(self) -> None:
        with patch.object(deploy, "config_value", return_value=""):
            self.assertEqual(
                deploy.netease_dir(), deploy.ROOT / deploy.NETEASE_DEFAULT_DIR
            )

    def test_absolute_path_is_kept(self) -> None:
        with patch.object(deploy, "config_value", return_value="/opt/ncm"):
            self.assertEqual(deploy.netease_dir(), Path("/opt/ncm"))


class NeteaseInstallTest(unittest.TestCase):
    """生产安装不能执行依赖 devDependencies 的上游 prepare 脚本。"""

    def test_source_install_skips_development_lifecycle_scripts(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "NeteaseCloudMusicApi"

            def fake_run_ok(cmd: list[str], **kwargs: Any) -> bool:
                if cmd[:2] == ["git", "clone"]:
                    target.mkdir()
                    (target / "app.js").write_text("", encoding="utf-8")
                return True

            with (
                patch.object(deploy, "IS_WINDOWS", False),
                patch.object(deploy, "run_ok", side_effect=fake_run_ok) as run_ok,
            ):
                self.assertTrue(deploy.install_netease_from_source(target))

            npm_call = run_ok.call_args_list[1]
            self.assertEqual(
                npm_call.args[0],
                ["npm", "install", "--omit=dev", "--ignore-scripts"],
            )
            self.assertEqual(npm_call.kwargs["cwd"], target)

    def test_docker_fallback_is_restartable_and_waits_until_ready(self) -> None:
        with (
            patch.object(deploy.shutil, "which", return_value="/usr/bin/docker"),
            patch.object(deploy, "quiet_ok", return_value=True),
            patch.object(deploy, "run_ok", return_value=True) as run_ok,
            patch.object(deploy, "wait_for_port", return_value=True) as wait_for_port,
        ):
            self.assertTrue(deploy.start_netease_container())

        docker_run = run_ok.call_args.args[0]
        self.assertIn("--restart", docker_run)
        self.assertIn("unless-stopped", docker_run)
        wait_for_port.assert_called_once_with("127.0.0.1", 3000, 20)


class ConfigWriteTest(unittest.TestCase):
    """写凭据不能破坏 config.py：它是会被 import 的 Python 源码。"""

    def test_writes_values_without_breaking_the_file(self) -> None:
        from oopz.credentials import _replace_config_value

        original = (
            "OOPZ_CONFIG = {\n"
            '    "login_phone": "",     # 账号\n'
            '    "login_password": "",  # 密码\n'
            '    "base_url": "https://gateway.oopz.cn",\n'
            "}\n"
        )
        content, ok_phone = _replace_config_value(original, "login_phone", "13800000000")
        content, ok_pw = _replace_config_value(content, "login_password", "secret")

        self.assertTrue(ok_phone and ok_pw)
        self.assertIn('"login_phone": "13800000000"', content)
        self.assertIn('"login_password": "secret"', content)
        self.assertIn("# 账号", content, "注释要保留，用户还得看着它改配置")
        self.assertIn('"base_url": "https://gateway.oopz.cn"', content, "别的字段不能动")

        namespace: dict = {}
        exec(compile(content, "config.py", "exec"), namespace)
        self.assertEqual(namespace["OOPZ_CONFIG"]["login_phone"], "13800000000")


class SectionAwareConfigWriteTest(unittest.TestCase):
    """api_key / cookie 这类键名多个配置块里都有，写错块是静默的。"""

    SAMPLE = (
        'OOPZ_CONFIG = {\n    "proxy": "",\n}\n\n'
        'NETEASE_CLOUD = {\n    "cookie": "",   # 网易云\n}\n\n'
        'WEB_PLAYER_CONFIG = {\n'
        '    "enabled": False,\n'
        '    "url": "",\n'
        '    "cookie_secure": False,\n'
        '    "admin_cookie_secure": False,\n'
        '}\n\n'
        'SCREEN_SHARE_CONFIG = {\n'
        '    "enabled": False,\n'
        '    "agora_app_id": "",\n'
        '    "agora_app_certificate": "",\n'
        '}\n\n'
        'ONEBOT_V11_CONFIG = {\n    "enabled": False,\n}\n\n'
        'ADMIN_UIDS = [\n    # "用户UID",\n]\n'
    )

    def test_writes_into_the_right_section(self) -> None:
        content, ok = deploy.set_config_field(self.SAMPLE, "WEB_PLAYER_CONFIG", "enabled", True)

        self.assertTrue(ok)
        self.assertIn('WEB_PLAYER_CONFIG = {\n    "enabled": True,', content)
        self.assertIn('ONEBOT_V11_CONFIG = {\n    "enabled": False,', content)

    def test_cookie_goes_to_netease_not_elsewhere(self) -> None:
        content, ok = deploy.set_config_field(self.SAMPLE, "NETEASE_CLOUD", "cookie", "MUSIC_U=x")

        self.assertTrue(ok)
        self.assertIn('"cookie": "MUSIC_U=x",   # 网易云', content, "注释要留着")

    def test_boolean_field_is_written_without_quotes(self) -> None:
        content, ok = deploy.set_config_field(self.SAMPLE, "WEB_PLAYER_CONFIG", "enabled", True)

        self.assertTrue(ok)
        self.assertIn('"enabled": True', content)
        self.assertNotIn('"enabled": "True"', content, "布尔值加引号会变成真值字符串")

    def test_unknown_section_is_a_no_op(self) -> None:
        content, ok = deploy.set_config_field(self.SAMPLE, "NO_SUCH_CONFIG", "api_key", "x")

        self.assertFalse(ok)
        self.assertEqual(content, self.SAMPLE, "找不到配置块时不能乱改")

    def test_admin_uids_list_is_rewritten(self) -> None:
        content, ok = deploy.set_admin_uids(self.SAMPLE, ["uid-1", "uid-2"])

        self.assertTrue(ok)
        namespace: dict = {}
        exec(compile(content, "config.py", "exec"), namespace)
        self.assertEqual(namespace["ADMIN_UIDS"], ["uid-1", "uid-2"])

    def test_result_is_still_valid_python(self) -> None:
        content = self.SAMPLE
        for section, key, value in (
            ("WEB_PLAYER_CONFIG", "enabled", True),
            ("NETEASE_CLOUD", "cookie", 'has "quotes" inside'),
            ("OOPZ_CONFIG", "proxy", "http://127.0.0.1:7890"),
        ):
            content, ok = deploy.set_config_field(content, section, key, value)
            self.assertTrue(ok, f"{section}.{key} 未写入")

        namespace: dict = {}
        exec(compile(content, "config.py", "exec"), namespace)
        self.assertTrue(namespace["WEB_PLAYER_CONFIG"]["enabled"])
        self.assertEqual(namespace["NETEASE_CLOUD"]["cookie"], 'has "quotes" inside')
        self.assertEqual(namespace["OOPZ_CONFIG"]["proxy"], "http://127.0.0.1:7890")


class ScreenShareDeployTest(unittest.TestCase):
    CONFIG = SectionAwareConfigWriteTest.SAMPLE

    def test_first_run_writes_complete_screen_share_config(self) -> None:
        app_id = "a" * 32
        certificate = "b" * 32
        with (
            patch.object(
                deploy,
                "ask",
                side_effect=[app_id, "https://bot.example.com/"],
            ),
            patch.object(deploy, "ask_secret", return_value=certificate),
        ):
            content, enabled = deploy.configure_screen_share(self.CONFIG)

        self.assertTrue(enabled)
        namespace: dict = {}
        exec(compile(content, "config.py", "exec"), namespace)
        self.assertTrue(namespace["SCREEN_SHARE_CONFIG"]["enabled"])
        self.assertEqual(namespace["SCREEN_SHARE_CONFIG"]["agora_app_id"], app_id)
        self.assertEqual(
            namespace["SCREEN_SHARE_CONFIG"]["agora_app_certificate"],
            certificate,
        )
        self.assertEqual(namespace["WEB_PLAYER_CONFIG"]["url"], "https://bot.example.com")
        self.assertTrue(namespace["WEB_PLAYER_CONFIG"]["cookie_secure"])
        self.assertTrue(namespace["WEB_PLAYER_CONFIG"]["admin_cookie_secure"])

    def test_invalid_credentials_do_not_write_partial_config(self) -> None:
        with (
            patch.object(
                deploy,
                "ask",
                side_effect=["bad-app-id", "http://public.example.com"],
            ),
            patch.object(deploy, "ask_secret", return_value="bad-certificate"),
            patch.object(deploy, "warn"),
        ):
            content, enabled = deploy.configure_screen_share(self.CONFIG)

        self.assertFalse(enabled)
        self.assertEqual(content, self.CONFIG)

    def test_public_url_requires_https_but_allows_localhost(self) -> None:
        self.assertTrue(deploy.valid_screen_share_url("https://bot.example.com"))
        self.assertTrue(deploy.valid_screen_share_url("http://localhost:8080"))
        self.assertTrue(deploy.valid_screen_share_url("http://127.0.0.1:8080"))
        self.assertFalse(deploy.valid_screen_share_url("http://bot.example.com"))
        self.assertFalse(deploy.valid_screen_share_url("not-a-url"))

    def test_committed_assets_do_not_require_node(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            asset_dir = Path(tmp)
            for name in deploy.SCREEN_SHARE_REQUIRED_ASSETS:
                (asset_dir / name).write_text("asset", encoding="utf-8")
            with (
                patch.object(deploy, "SCREEN_SHARE_ASSET_DIR", asset_dir),
                patch.object(deploy, "run_ok") as run_ok,
                patch.object(deploy, "say"),
            ):
                deploy.setup_screen_share_assets(install=True)
            run_ok.assert_not_called()

    def test_missing_assets_use_module_local_client_as_recovery_only(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            asset_dir = base / "assets"
            client_dir = base / "client"
            asset_dir.mkdir()
            client_dir.mkdir()

            def fake_run_ok(command: list[str], **kwargs: Any) -> bool:
                self.assertEqual(kwargs.get("cwd"), client_dir)
                if command[-1] == "build":
                    for name in deploy.SCREEN_SHARE_REQUIRED_ASSETS:
                        (asset_dir / name).write_text("asset", encoding="utf-8")
                return True

            with (
                patch.object(deploy, "SCREEN_SHARE_ASSET_DIR", asset_dir),
                patch.object(deploy, "SCREEN_SHARE_CLIENT_DIR", client_dir),
                patch.object(deploy.shutil, "which", return_value="/usr/bin/npm"),
                patch.object(deploy, "run_ok", side_effect=fake_run_ok) as run_ok,
                patch.object(deploy, "say"),
                patch.object(deploy, "warn"),
            ):
                deploy.setup_screen_share_assets(install=True)

            self.assertEqual(
                [call.args[0] for call in run_ok.call_args_list],
                [
                    ["npm", "ci"],
                    ["npm", "run", "typecheck"],
                    ["npm", "run", "build"],
                ],
            )

    def test_readiness_checks_redis_https_credentials_and_assets(self) -> None:
        import tempfile

        content = self.CONFIG
        for section, key, value in (
            ("SCREEN_SHARE_CONFIG", "enabled", True),
            ("SCREEN_SHARE_CONFIG", "agora_app_id", "a" * 32),
            ("SCREEN_SHARE_CONFIG", "agora_app_certificate", "b" * 32),
            ("WEB_PLAYER_CONFIG", "url", "https://bot.example.com"),
        ):
            content, ok = deploy.set_config_field(content, section, key, value)
            self.assertTrue(ok)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            asset_dir = root / "assets"
            asset_dir.mkdir()
            (root / "config.py").write_text(content, encoding="utf-8")
            for name in deploy.SCREEN_SHARE_REQUIRED_ASSETS:
                (asset_dir / name).write_text("asset", encoding="utf-8")
            with (
                patch.object(deploy, "ROOT", root),
                patch.object(deploy, "SCREEN_SHARE_ASSET_DIR", asset_dir),
                patch.object(deploy, "redis_alive", return_value=True),
            ):
                enabled, ready, reasons = deploy.screen_share_readiness()

        self.assertTrue(enabled)
        self.assertTrue(ready)
        self.assertEqual(reasons, [])

    def test_docker_release_uses_compiled_assets_without_node_modules(self) -> None:
        dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
        dockerignore = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8")
        self.assertIn("/app/src/web/assets/screen-share/app.js", dockerfile)
        self.assertNotIn("npm install", dockerfile)
        self.assertIn("node_modules/", dockerignore)


class EnvFileTest(unittest.TestCase):
    """start.sh 的 .env 能力并进来之后不能丢。"""

    def setUp(self) -> None:
        import tempfile

        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self._orig_root = deploy.ROOT
        deploy.ROOT = self.tmp
        self.addCleanup(setattr, deploy, "ROOT", self._orig_root)

    def _write_env(self, text: str) -> None:
        (self.tmp / ".env").write_text(text, encoding="utf-8")

    def test_reads_plain_pairs(self) -> None:
        self._write_env('CLASH_MIXED_PORT=7899\nCLASH_KERNEL_BIN="mihomo"\n')
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("CLASH_MIXED_PORT", None)
            os.environ.pop("CLASH_KERNEL_BIN", None)
            deploy.load_env_files()
            self.assertEqual(os.environ["CLASH_MIXED_PORT"], "7899")
            self.assertEqual(os.environ["CLASH_KERNEL_BIN"], "mihomo", "引号要去掉")

    def test_existing_env_wins(self) -> None:
        """命令行上临时指定的值不该被 .env 盖掉，文档里就是这么用的。"""
        self._write_env("CLASH_AUTO_START=0\n")
        with patch.dict("os.environ", {"CLASH_AUTO_START": "1"}):
            deploy.load_env_files()
            import os

            self.assertEqual(os.environ["CLASH_AUTO_START"], "1")

    def test_comments_and_blank_lines_are_ignored(self) -> None:
        self._write_env("# 注释\n\nFOO_BAR=1\n")
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("FOO_BAR", None)
            deploy.load_env_files()
            self.assertEqual(os.environ["FOO_BAR"], "1")

    def test_missing_file_is_fine(self) -> None:
        deploy.load_env_files()  # 不该抛异常


class ClashFlagTest(unittest.TestCase):
    def test_flag_accepts_common_truthy_spellings(self) -> None:
        for value in ("1", "true", "TRUE", "yes", "on"):
            with patch.dict("os.environ", {"X": value}):
                self.assertTrue(deploy.env_flag("X"), value)

    def test_flag_rejects_others(self) -> None:
        for value in ("0", "false", "no", ""):
            with patch.dict("os.environ", {"X": value}):
                self.assertFalse(deploy.env_flag("X"), value)

    def test_kernel_lookup_prefers_configured_binary(self) -> None:
        with (
            patch.dict("os.environ", {"CLASH_KERNEL_BIN": "my-clash"}),
            patch.object(deploy.shutil, "which", side_effect=lambda n: f"/usr/bin/{n}"),
        ):
            self.assertEqual(deploy.find_clash_kernel(), "/usr/bin/my-clash")

    def test_kernel_lookup_falls_back_to_known_names(self) -> None:
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(
                deploy.shutil, "which",
                side_effect=lambda n: "/usr/bin/mihomo" if n == "mihomo" else None,
            ),
        ):
            self.assertEqual(deploy.find_clash_kernel(), "/usr/bin/mihomo")

    def test_kernel_missing_returns_none(self) -> None:
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(deploy.shutil, "which", return_value=None),
        ):
            self.assertIsNone(deploy.find_clash_kernel())


class StartShRemovedTest(unittest.TestCase):
    def test_start_sh_is_gone_and_unreferenced(self) -> None:
        self.assertFalse((REPO_ROOT / "start.sh").exists())
        for name in ("README.md", "docs/quickstart.md"):
            self.assertNotIn(
                "start.sh",
                (REPO_ROOT / name).read_text(encoding="utf-8"),
                f"{name} still points at the removed script",
            )


class DeadUpstreamTest(unittest.TestCase):
    """上游 git 仓库已因版权清空，不能再靠 clone 装网易云 API。"""

    def test_does_not_clone_the_dead_repo(self) -> None:
        source = (REPO_ROOT / "deploy.py").read_text(encoding="utf-8")

        self.assertNotIn(
            "Binaryify/NeteaseCloudMusicApi.git",
            source,
            "该仓库已清空，clone 下来只有一个 README，装不出可用的服务",
        )

    def test_uses_the_fork_the_docs_use(self) -> None:
        """脚本装的必须和文档教用户装的是同一个，否则两条路会跑偏。"""
        docs = (REPO_ROOT / "docs" / "quickstart.md").read_text(encoding="utf-8")

        self.assertIn("api-enhanced", deploy.NETEASE_REPO)
        self.assertIn("api-enhanced", docs)


if __name__ == "__main__":
    unittest.main()
