
from __future__ import annotations

import base64
import hashlib
import sys
import unittest
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

# 签名与密码加密已随登录链路迁入 SDK；算法与旧实现逐字一致，
# 这些用例继续守住「与服务端约定的加密格式」不被无声改动。
from oopz_sdk.auth.api_password_login import (  # noqa: E402
    _build_oopz_sign,
    _encrypt_password_code,
)
from oopz_sdk.auth.api_password_login import (  # noqa: E402
    _load_private_key as load_private_key_from_pem,
)

from tools.credential_tool import jwk_to_pem  # noqa: E402


def _b64url_int(value: int) -> str:
    raw = value.to_bytes(max(1, (value.bit_length() + 7) // 8), "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


class CryptoCompatibilityTest(unittest.TestCase):
    _private_key: rsa.RSAPrivateKey

    @classmethod
    def setUpClass(cls) -> None:
        cls._private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def _pkcs8_pem(self) -> str:
        return self._private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("ascii")

    def test_project_signing_and_pem_loading_round_trip(self) -> None:
        path = "/api/test"
        body = '{"ok":true}'
        oopz_time = "1234567890"
        signature = _build_oopz_sign(
            path=path,
            body=body,
            oopz_time=oopz_time,
            private_key_pem=self._pkcs8_pem(),
        )
        loaded = load_private_key_from_pem(self._pkcs8_pem())
        if not isinstance(loaded, rsa.RSAPrivateKey):
            self.fail("项目 PEM 加载器未返回 RSA 私钥")
        signed_data = hashlib.md5((path + body).encode()).hexdigest() + oopz_time

        loaded.public_key().verify(
            base64.b64decode(signature),
            signed_data.encode(),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )

    def test_password_oaep_encryption_round_trip(self) -> None:
        modulus = _b64url_int(self._private_key.public_key().public_numbers().n)
        encrypted = _encrypt_password_code("test-password", modulus)

        plaintext = self._private_key.decrypt(
            base64.b64decode(encrypted),
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
        self.assertEqual(plaintext, b"test-password")

    def test_jwk_private_numbers_to_pem_round_trip(self) -> None:
        numbers = self._private_key.private_numbers()
        public_numbers = numbers.public_numbers
        jwk = {
            "n": _b64url_int(public_numbers.n),
            "e": _b64url_int(public_numbers.e),
            "d": _b64url_int(numbers.d),
            "p": _b64url_int(numbers.p),
            "q": _b64url_int(numbers.q),
            "dp": _b64url_int(numbers.dmp1),
            "dq": _b64url_int(numbers.dmq1),
            "qi": _b64url_int(numbers.iqmp),
        }

        pem = jwk_to_pem(jwk)

        self.assertIsInstance(pem, str)
        if not isinstance(pem, str):
            return
        loaded = serialization.load_pem_private_key(pem.encode(), password=None)
        if not isinstance(loaded, rsa.RSAPrivateKey):
            self.fail("JWK 转换结果未加载为 RSA 私钥")
        self.assertEqual(loaded.private_numbers(), numbers)


if __name__ == "__main__":
    unittest.main()
