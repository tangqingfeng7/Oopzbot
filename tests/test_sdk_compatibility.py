import os
import sys
import unittest
from pathlib import Path
from typing import cast

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from oopz_sdk.config.settings import OopzConfig  # noqa: E402
from oopz_sdk.exceptions import OopzRateLimitError  # noqa: E402


class RequireEnvReturnsValueTest(unittest.TestCase):
    """环境变量中的凭据应完整进入 SDK 配置。"""

    def setUp(self) -> None:
        self._saved = {
            name: os.environ.get(name)
            for name in (
                "OOPZ_DEVICE_ID",
                "OOPZ_PERSON_UID",
                "OOPZ_JWT_TOKEN",
                "OOPZ_PRIVATE_KEY",
                "OOPZ_LOGIN_METHOD",
                "OOPZ_PATCH_PROBE",
            )
        }
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        for name, value in self._saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def test_returns_value_when_variable_is_set(self) -> None:
        os.environ["OOPZ_PATCH_PROBE"] = "value-1"
        self.assertEqual(OopzConfig._require_env("OOPZ_PATCH_PROBE"), "value-1")

    def test_strips_by_default_but_keeps_whitespace_when_disabled(self) -> None:
        """密码走 strip=False，首尾空白必须原样保留。"""
        os.environ["OOPZ_PATCH_PROBE"] = "  pa ss  "
        self.assertEqual(OopzConfig._require_env("OOPZ_PATCH_PROBE"), "pa ss")
        self.assertEqual(
            OopzConfig._require_env("OOPZ_PATCH_PROBE", strip=False), "  pa ss  "
        )

    def test_still_raises_for_missing_or_blank(self) -> None:
        os.environ.pop("OOPZ_PATCH_PROBE", None)
        with self.assertRaises(ValueError):
            OopzConfig._require_env("OOPZ_PATCH_PROBE")

        os.environ["OOPZ_PATCH_PROBE"] = "   "
        with self.assertRaises(ValueError):
            OopzConfig._require_env("OOPZ_PATCH_PROBE")

    def test_from_env_carries_credentials_through(self) -> None:
        """回归本体：凭据必须真正进入配置，而不是被静默清空。"""
        os.environ.update(
            OOPZ_LOGIN_METHOD="credentials",
            OOPZ_DEVICE_ID="device-abc",
            OOPZ_PERSON_UID="person-xyz",
            OOPZ_JWT_TOKEN="jwt-123",
            OOPZ_PRIVATE_KEY="pem-body",
        )

        config = OopzConfig.from_env()

        self.assertEqual(config.device_id, "device-abc")
        self.assertEqual(config.person_uid, "person-xyz")
        self.assertEqual(config.jwt_token, "jwt-123")
        self.assertEqual(config.private_key, "pem-body")


class RateLimitErrorAcceptsStatusCodeTest(unittest.TestCase):


    def test_explicit_status_code_does_not_conflict(self) -> None:
        error = OopzRateLimitError(
            message="slow down", retry_after=3, status_code=429, payload={"a": 1}
        )
        self.assertEqual(error.status_code, 429)
        self.assertEqual(error.retry_after, 3)
        self.assertEqual(error.payload, {"a": 1})

    def test_defaults_to_429_when_caller_omits_it(self) -> None:
        self.assertEqual(OopzRateLimitError().status_code, 429)

    def test_transport_429_path_raises_the_intended_error(self) -> None:
        import asyncio
        import json
        from unittest.mock import AsyncMock

        from oopz_sdk.auth.signer import Signer
        from oopz_sdk.testing.factories import make_config
        from oopz_sdk.transport.http import HttpResponse, HttpTransport

        body = json.dumps({"message": "slow down"})
        transport = HttpTransport(make_config(), cast("Signer", object()))
        transport.request = AsyncMock(
            return_value=HttpResponse(
                status_code=429, headers={}, content=body.encode(), text=body
            )
        )

        with self.assertRaises(OopzRateLimitError) as ctx:
            asyncio.run(transport.request_json("GET", "/x"))
        self.assertEqual(ctx.exception.status_code, 429)


class ChannelGroupTolerlatesNullChannelsTest(unittest.TestCase):
    def test_explicit_null_becomes_empty_list(self) -> None:
        from oopz_sdk.models.area import ChannelGroupInfo

        group = ChannelGroupInfo.from_api({"id": "g1", "name": "空分组", "channels": None})
        self.assertEqual(group.channels, [])

    def test_missing_key_still_defaults_to_empty_list(self) -> None:
        from oopz_sdk.models.area import ChannelGroupInfo

        self.assertEqual(ChannelGroupInfo.from_api({"id": "g1"}).channels, [])

    def test_real_channels_are_preserved(self) -> None:
        from oopz_sdk.models.area import ChannelGroupInfo

        group = ChannelGroupInfo.from_api(
            {"id": "g1", "channels": [{"id": "c1", "name": "频道一"}]}
        )
        self.assertEqual(len(group.channels), 1)


if __name__ == "__main__":
    unittest.main()
