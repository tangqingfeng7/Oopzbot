"""Oopz API 响应解析的语义回归。

旧实现 `oopz.responses` 返回结果对象（ok/error/data），迁移到 SDK 后改成
`HttpTransport.request_json` 直接抛 `OopzApiError`。这里按新契约重写，
守住的仍是同一批上游怪异行为：非 200、空 body、非 JSON、status 为假、
以及 status 被序列化成字符串 "false" 时不能误判成功。
"""

import json
import sys
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from oopz_sdk.auth.signer import Signer  # noqa: E402
from oopz_sdk.exceptions import OopzApiError, OopzRateLimitError  # noqa: E402
from oopz_sdk.testing.factories import make_config  # noqa: E402
from oopz_sdk.transport.http import HttpResponse, HttpTransport  # noqa: E402
from oopz_sdk.utils.payload import coerce_bool  # noqa: E402


def _response(status_code: int = 200, payload=None, *, text: str | None = None) -> HttpResponse:
    if text is None:
        text = "" if payload is None else json.dumps(payload)
    return HttpResponse(
        status_code=status_code,
        headers={},
        content=text.encode("utf-8"),
        text=text,
    )


class _StubSigner:
    def sign(self, *args, **kwargs):
        return {}


class RequestJsonSemanticsTest(unittest.IsolatedAsyncioTestCase):
    def _transport(self, response: HttpResponse) -> HttpTransport:
        transport = HttpTransport(make_config(), cast("Signer", _StubSigner()))
        transport.request = AsyncMock(return_value=response)
        return transport

    async def _expect_api_error(self, response: HttpResponse) -> OopzApiError:
        transport = self._transport(response)
        with self.assertRaises(OopzApiError) as ctx:
            await transport.request_json("GET", "/x")
        return ctx.exception

    async def test_non_200_carries_status_code(self) -> None:
        error = await self._expect_api_error(_response(404))
        self.assertEqual(error.status_code, 404)
        self.assertIn("404", str(error))

    async def test_empty_body_is_not_valid_json(self) -> None:
        error = await self._expect_api_error(_response(200, text=""))
        self.assertIn("not valid JSON", str(error))
        self.assertEqual(error.status_code, 200)

    async def test_invalid_json_is_reported_as_such(self) -> None:
        error = await self._expect_api_error(_response(200, text="<html>"))
        self.assertIn("not valid JSON", str(error))

    async def test_non_dict_payload_is_rejected(self) -> None:
        error = await self._expect_api_error(_response(200, text=json.dumps([1, 2, 3])))
        self.assertIn("not valid dict", str(error))

    async def test_status_false_combines_message_and_error(self) -> None:
        # 两者都在且不同，服务端往往一个是概要一个是细节，都要保留
        error = await self._expect_api_error(
            _response(200, {"status": False, "message": "msg", "error": "err"})
        )
        self.assertEqual(str(error), "msg: err")
        self.assertEqual(error.payload, {"status": False, "message": "msg", "error": "err"})

    async def test_status_false_falls_back_to_error_then_default(self) -> None:
        only_error = await self._expect_api_error(_response(200, {"status": False, "error": "err"}))
        self.assertEqual(str(only_error), "err")

        bare = await self._expect_api_error(_response(200, {"status": False}))
        self.assertEqual(str(bare), "Oopz API request failed")

    async def test_missing_status_is_a_failure(self) -> None:
        # status 缺失时必须 fail-closed，不能因为 HTTP 200 就当成功
        error = await self._expect_api_error(_response(200, {"code": 0}))
        self.assertIn("failed", str(error))

    async def test_string_false_status_is_not_success(self) -> None:
        """服务端会把布尔序列化成字符串，bool("false") 为真是经典陷阱。"""
        for literal in ("false", "0", "no", "off", ""):
            with self.subTest(status=literal):
                await self._expect_api_error(_response(200, {"status": literal}))

    async def test_truthy_status_variants_succeed(self) -> None:
        for literal in (True, "true", "1", "yes", "on", 1):
            with self.subTest(status=literal):
                transport = self._transport(_response(200, {"status": literal, "data": {"a": 1}}))
                result = await transport.request_json("GET", "/x")
                self.assertEqual(result["data"], {"a": 1})

    async def test_rate_limit_raises_dedicated_error(self) -> None:
        transport = self._transport(_response(429, {"message": "slow down"}))
        with self.assertRaises(OopzRateLimitError) as ctx:
            await transport.request_json("GET", "/x")
        self.assertEqual(ctx.exception.status_code, 429)



class RequestDataSemanticsTest(unittest.IsolatedAsyncioTestCase):
    def _transport(self, response: HttpResponse) -> HttpTransport:
        transport = HttpTransport(make_config(), cast("Signer", _StubSigner()))
        transport.request = AsyncMock(return_value=response)
        return transport

    async def test_success_extracts_data_field(self) -> None:
        transport = self._transport(_response(200, {"status": True, "data": {"a": 1}}))
        self.assertEqual(await transport.request_data("GET", "/x"), {"a": 1})

    async def test_missing_data_field_is_an_error(self) -> None:
        # 旧实现会静默给默认值，新契约要求显式报错，避免把空结果当成正常返回
        transport = self._transport(_response(200, {"status": True}))
        with self.assertRaises(OopzApiError) as ctx:
            await transport.request_data("GET", "/x")
        self.assertIn("does not contain 'data'", str(ctx.exception))

    async def test_falsy_data_is_preserved(self) -> None:
        transport = self._transport(_response(200, {"status": True, "data": []}))
        self.assertEqual(await transport.request_data("GET", "/x"), [])


class CoerceBoolTest(unittest.TestCase):
    def test_string_literals_are_interpreted_strictly(self) -> None:
        for literal in ("true", "TRUE", "1", "yes", "y", "on"):
            self.assertTrue(coerce_bool(literal), f"{literal!r} 应为真")
        for literal in ("false", "FALSE", "0", "no", "n", "off", ""):
            self.assertFalse(coerce_bool(literal), f"{literal!r} 应为假")

    def test_unknown_values_fall_back_to_default(self) -> None:
        self.assertFalse(coerce_bool("maybe", default=False))
        self.assertTrue(coerce_bool("maybe", default=True))
        self.assertFalse(coerce_bool(None, default=False))
        self.assertTrue(coerce_bool(None, default=True))

    def test_numbers_follow_zero_is_false(self) -> None:
        self.assertFalse(coerce_bool(0))
        self.assertTrue(coerce_bool(1))
        self.assertTrue(coerce_bool(2.5))


if __name__ == "__main__":
    unittest.main()
