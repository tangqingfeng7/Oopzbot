"""登录与凭据落盘的语义。

旧的 `oopz.oopz_password_login` 是个大门面，把「配置文件事务写入」「内置登录物料」
「API 密码登录」揉在一起。迁移后拆成三处：本项目的 `oopz/credentials.py` 负责落盘，
SDK 的 `auth/_builtin_login_bundle` 提供物料，`auth/api_password_login` 负责登录。
用例按新归属重写，落盘那几条（符号链接、失败回滚、共享事务锁）语义完全保留。
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from oopz_sdk.auth import _builtin_login_bundle as bundle  # noqa: E402
from oopz_sdk.auth import api_password_login as api_login_module  # noqa: E402
from oopz_sdk.exceptions import OopzPasswordLoginError  # noqa: E402

import core.config_file_store as config_file_store  # noqa: E402
import oopz.credentials as credentials_module  # noqa: E402
import web.web_player_config as web_config  # noqa: E402

PRIVATE_KEY_PEM = "-----BEGIN PRIVATE KEY-----\nunit-test-key\n-----END PRIVATE KEY-----"

_CREDENTIALS = {
    "app_version": "70000",
    "device_id": "device-new",
    "person_uid": "person-new",
    "jwt_token": "jwt-new",
    "private_key_pem": PRIVATE_KEY_PEM,
}


class _Response:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class ConfigRewriteTest(unittest.TestCase):
    def test_replace_config_value_updates_only_requested_field(self) -> None:
        content = 'OOPZ_CONFIG = {"device_id": "old-device", "jwt_token": "old-token"}'

        updated, replaced = credentials_module._replace_config_value(
            content, "jwt_token", "new-token"
        )

        self.assertTrue(replaced)
        self.assertIn('"device_id": "old-device"', updated)
        self.assertIn('"jwt_token": "new-token"', updated)

    def test_blank_values_are_not_written_back(self) -> None:
        """登录结果缺字段时不能把配置里已有的值清空。"""
        content = 'OOPZ_CONFIG = {"jwt_token": "old-token"}'

        for empty in (None, ""):
            with self.subTest(value=empty):
                updated, replaced = credentials_module._replace_config_value(
                    content, "jwt_token", empty
                )
                self.assertFalse(replaced)
                self.assertEqual(updated, content)

    def test_missing_credential_field_is_reported(self) -> None:
        with (
            patch.object(credentials_module, "_read_config_template", return_value="X = 1\n"),
            self.assertRaises(OopzPasswordLoginError),
        ):
            credentials_module._updated_config_content(_CREDENTIALS)


class CredentialPersistenceTest(unittest.TestCase):
    """凭据要一次性原子写入 config.py 与 private_key.py。"""

    @contextmanager
    def _workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config.py"
            private_key_path = root / "private_key.py"
            with (
                patch.object(credentials_module, "CONFIG_PATH", str(config_path)),
                patch.object(credentials_module, "PRIVATE_KEY_PATH", str(private_key_path)),
            ):
                yield root, config_path, private_key_path

    @staticmethod
    def _config_text() -> str:
        return (
            "OOPZ_CONFIG = {\n"
            '    "app_version": "old",\n'
            '    "device_id": "old",\n'
            '    "person_uid": "old",\n'
            '    "jwt_token": "old",\n'
            "}\n"
        )

    def test_save_credentials_preserves_symlinks(self) -> None:
        """用户常把 config.py 软链到别处，写入不能把链接替换成普通文件。"""
        with self._workspace() as (root, config_path, private_key_path):
            config_target = root / "runtime.py"
            private_key_target = root / "private-key-runtime.py"
            config_target.write_text(self._config_text(), encoding="utf-8")
            private_key_target.write_text("old-private-key", encoding="utf-8")
            config_path.symlink_to(config_target)
            private_key_path.symlink_to(private_key_target)

            with patch.object(credentials_module, "_apply_runtime"):
                saved = credentials_module.save_credentials(_CREDENTIALS)

            self.assertEqual(saved, ["config.py", "private_key.py"])
            self.assertTrue(config_path.is_symlink())
            self.assertTrue(private_key_path.is_symlink())
            config_text = config_path.read_text(encoding="utf-8")
            for field, value in (
                ("app_version", "70000"),
                ("device_id", "device-new"),
                ("person_uid", "person-new"),
                ("jwt_token", "jwt-new"),
            ):
                self.assertIn(f'"{field}": "{value}"', config_text)
            self.assertIn("PRIVATE_KEY_PEM", private_key_path.read_text(encoding="utf-8"))

    def test_second_replace_failure_rolls_back_both_files(self) -> None:
        """第二个文件提交失败时，第一个也必须回滚，否则凭据会半新半旧。"""
        original_config = self._config_text()
        original_private_key = "old-private-key\n"

        with self._workspace() as (root, config_path, private_key_path):
            config_path.write_text(original_config, encoding="utf-8")
            private_key_path.write_text(original_private_key, encoding="utf-8")
            real_replace = config_file_store.os.replace
            failed = False

            def fail_second_commit(source, destination):
                nonlocal failed
                if (
                    not failed
                    and Path(source).suffix == ".tmp"
                    and Path(destination).resolve() == private_key_path.resolve()
                ):
                    failed = True
                    raise OSError("injected private-key replace failure")
                return real_replace(source, destination)

            with (
                patch.object(credentials_module, "_apply_runtime") as apply_runtime,
                patch.object(config_file_store.os, "replace", side_effect=fail_second_commit),
                self.assertRaisesRegex(OSError, "injected private-key"),
            ):
                credentials_module.save_credentials(_CREDENTIALS)

            self.assertTrue(failed)
            self.assertEqual(config_path.read_text(encoding="utf-8"), original_config)
            self.assertEqual(private_key_path.read_text(encoding="utf-8"), original_private_key)
            self.assertEqual(list(root.glob(".*.tmp")), [])
            self.assertEqual(list(root.glob(".*.bak")), [])
            # 落盘失败就不该把新凭据推到运行时，否则内存与磁盘会不一致
            apply_runtime.assert_not_called()

    def test_missing_private_key_is_rejected_before_touching_files(self) -> None:
        with self._workspace() as (_root, config_path, _private_key_path):
            config_path.write_text(self._config_text(), encoding="utf-8")

            with self.assertRaises(OopzPasswordLoginError):
                credentials_module.save_credentials(
                    {key: value for key, value in _CREDENTIALS.items() if key != "private_key_pem"}
                )

            self.assertEqual(config_path.read_text(encoding="utf-8"), self._config_text())

    def test_web_and_oopz_writers_share_one_transaction_lock(self) -> None:
        """两个写入方各写 config.py 的不同片段，必须串行，否则会互相覆盖。"""
        with self._workspace() as (_root, config_path, private_key_path):
            config_path.write_text("ADMIN_UIDS = []\n" + self._config_text(), encoding="utf-8")
            private_key_path.write_text("old-private-key", encoding="utf-8")

            barrier = threading.Barrier(2)
            errors: list[BaseException] = []
            real_lock = config_file_store.config_file_write_lock

            @contextmanager
            def synchronized_lock():
                # 先各自到齐再抢锁，确保真的构成并发
                barrier.wait(timeout=2)
                with real_lock():
                    yield

            def save_oopz() -> None:
                try:
                    credentials_module.save_credentials(_CREDENTIALS)
                except BaseException as exc:
                    errors.append(exc)

            def save_admins() -> None:
                try:
                    web_config.persist_admin_uids(["shared-lock-admin"], path=str(config_path))
                except BaseException as exc:
                    errors.append(exc)

            with (
                patch.object(credentials_module, "_apply_runtime"),
                patch.object(credentials_module, "config_file_write_lock", synchronized_lock),
                patch.object(web_config, "config_file_write_lock", synchronized_lock),
            ):
                threads = [
                    threading.Thread(target=save_oopz),
                    threading.Thread(target=save_admins),
                ]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=3)

            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertEqual(errors, [])
            updated = config_path.read_text(encoding="utf-8")
            self.assertIn("shared-lock-admin", updated)
            self.assertIn('"jwt_token": "jwt-new"', updated)


class BuiltinLoginBundleTest(unittest.TestCase):
    def test_bundle_restores_expected_material_shapes(self) -> None:
        self.assertIn("BEGIN PRIVATE KEY", bundle.get_client_signing_key())
        self.assertIn("END PRIVATE KEY", bundle.get_client_signing_key())
        self.assertGreater(len(bundle.get_client_password_modulus()), 100)

    def test_tampered_bundle_does_not_silently_yield_garbage(self) -> None:
        """物料被改动必须直接失败，拿到半截密钥去签名只会得到难查的 401。"""
        parts = list(bundle._CLIENT_SIGNING_KEY_DATA)
        parts[0] = "A" + parts[0][1:]

        # 具体异常类型由解码/解压路径决定，这里只要求「不能安静返回垃圾」
        with self.assertRaises((ValueError, TypeError, OSError, Exception)) as ctx:
            bundle._restore(parts)
        self.assertIsNotNone(ctx.exception)


class ApiPasswordLoginTest(unittest.TestCase):
    def test_body_carries_encrypted_password_only(self) -> None:
        with patch.object(api_login_module, "_encrypt_password_code", return_value="encrypted-code"):
            body = api_login_module._build_password_login_body(
                phone="13800138000",
                password="plain-password",
                device_id="device-1",
                public_n="public-modulus",
            )

        payload = json.loads(body)
        self.assertEqual(payload["loginType"], "PASSWORD")
        self.assertEqual(payload["phone"], "13800138000")
        self.assertEqual(payload["deviceId"], "device-1")
        self.assertEqual(payload["code"], "encrypted-code")
        # 明文密码绝不能出现在请求体里
        self.assertNotIn("plain-password", body)

    def test_headers_contain_oopz_signing_fields(self) -> None:
        with patch.object(api_login_module, "_build_oopz_sign", return_value="signed-value"):
            headers = api_login_module._build_headers(
                device_id="device-1",
                body="{}",
                private_key_pem=PRIVATE_KEY_PEM,
            )

        self.assertEqual(headers["Oopz-Sign"], "signed-value")
        self.assertEqual(headers["Oopz-Device-Id"], "device-1")
        self.assertEqual(headers["Oopz-App-Version-Number"], api_login_module.APP_VERSION_NUMBER)
        self.assertIn("Oopz-Time", headers)
        self.assertIn("Oopz-Request-Id", headers)

    def test_time_and_request_id_change_between_calls(self) -> None:
        """两者用于防重放，写死会让服务端拒绝第二次登录。"""
        with patch.object(api_login_module, "_build_oopz_sign", return_value="signed"):
            first = api_login_module._build_headers(
                device_id="d", body="{}", private_key_pem=PRIVATE_KEY_PEM
            )
            time.sleep(0.002)
            second = api_login_module._build_headers(
                device_id="d", body="{}", private_key_pem=PRIVATE_KEY_PEM
            )

        self.assertNotEqual(first["Oopz-Request-Id"], second["Oopz-Request-Id"])
        self.assertNotEqual(first["Oopz-Time"], second["Oopz-Time"])

    def _patched_login(self, response):
        return (
            patch.object(api_login_module, "get_client_signing_key", return_value=PRIVATE_KEY_PEM),
            patch.object(
                api_login_module, "get_client_password_modulus", return_value="public-modulus"
            ),
            patch.object(api_login_module, "_encrypt_password_code", return_value="encrypted-code"),
            patch.object(api_login_module, "_build_oopz_sign", return_value="signed-value"),
            patch("oopz_sdk.auth.api_password_login.requests.post", return_value=response),
        )

    def test_successful_login_returns_credentials(self) -> None:
        response = _Response(200, {"status": True, "data": {"uid": "person-1", "signature": "jwt-1"}})
        signing, modulus, encrypt, sign, post = self._patched_login(response)

        with signing, modulus, encrypt, sign, post as post_mock:
            credentials = api_login_module.login_with_api_password(
                "13800138000", "plain-password", device_id="device-1", timeout=3
            )

        self.assertEqual(credentials.person_uid, "person-1")
        self.assertEqual(credentials.device_id, "device-1")
        self.assertEqual(credentials.jwt_token, "jwt-1")

        sent_body = post_mock.call_args.kwargs["data"]
        if isinstance(sent_body, bytes):
            sent_body = sent_body.decode("utf-8")
        self.assertIn('"loginType":"PASSWORD"', sent_body)
        self.assertNotIn("plain-password", sent_body)
        self.assertEqual(post_mock.call_args.kwargs["headers"]["Oopz-Sign"], "signed-value")
        self.assertEqual(post_mock.call_args.kwargs["timeout"], 3)

    def test_failure_reports_the_server_message(self) -> None:
        response = _Response(200, {"status": False, "data": {"msg": "密码错误"}})
        signing, modulus, encrypt, sign, post = self._patched_login(response)

        with signing, modulus, encrypt, sign, post, self.assertRaises(OopzPasswordLoginError) as ctx:
            api_login_module.login_with_api_password("13800138000", "bad-password")

        self.assertIn("密码错误", str(ctx.exception))

    def test_empty_account_is_rejected_before_any_request(self) -> None:
        with patch("oopz_sdk.auth.api_password_login.requests.post") as post:
            for phone, password in (("", "pw"), ("13800138000", "")):
                with (
                    self.subTest(phone=phone, password=password),
                    self.assertRaises(OopzPasswordLoginError),
                ):
                    api_login_module.login_with_api_password(phone, password)
        post.assert_not_called()


class PasswordLoginEntryPointTest(unittest.IsolatedAsyncioTestCase):
    async def test_login_with_password_is_api_only(self) -> None:
        """统一入口不再自动回退浏览器登录。

        浏览器路径会触发验证码/风控人工交互，不适合无人值守，还会把
        「密码错误」和「可重试的瞬时故障」混成一类。回退已被去掉，
        这里守住它不被重新引入。
        """
        from oopz_sdk.auth import password_login as module

        with (
            patch.object(
                module,
                "login_with_playwright_password",
                side_effect=AssertionError("统一入口不应触发浏览器登录"),
            ),
            patch.object(
                api_login_module,
                "login_with_api_password",
                side_effect=OopzPasswordLoginError("密码错误"),
            ),self.assertRaises(OopzPasswordLoginError)
        ):
            await module.login_with_password("13800138000", "bad-password")


class AuthFailureStatusTest(unittest.TestCase):
    def test_401_and_428_are_the_auth_failure_signals(self) -> None:
        """428 是 Oopz 独有的「凭据需刷新」，漏掉它会导致长跑后静默掉线。"""
        from oopz_sdk.exceptions.auth import AUTH_FAILURE_STATUS_CODES

        self.assertIn(401, AUTH_FAILURE_STATUS_CODES)
        self.assertIn(428, AUTH_FAILURE_STATUS_CODES)


if __name__ == "__main__":
    unittest.main()
