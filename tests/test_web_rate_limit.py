import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from web.web_rate_limit import (  # noqa: E402
    DEFAULT_LIMITER,
    LOGIN_LIMITER,
    SEARCH_LIMITER,
    ClientAddressRequest,
    ClientAddressResolver,
    LoginGuard,
    RateLimiter,
    client_ip,
    limiter_for,
)


def _request(
    host: str = "9.9.9.9",
    real_ip: str | None = None,
    forwarded: str | None = None,
) -> ClientAddressRequest:
    headers = {}
    if real_ip is not None:
        headers["x-real-ip"] = real_ip
    if forwarded is not None:
        headers["x-forwarded-for"] = forwarded
    return cast(
        ClientAddressRequest,
        SimpleNamespace(headers=headers, client=SimpleNamespace(host=host)),
    )


class ClientIpTest(unittest.TestCase):
    def test_uses_x_real_ip_from_trusted_proxy(self) -> None:
        req = _request(host="127.0.0.1", real_ip="1.2.3.4")
        self.assertEqual(client_ip(req, ("127.0.0.1/32",)), "1.2.3.4")

    def test_forwarded_for_strips_trusted_hops_from_right(self) -> None:
        req = _request(
            host="127.0.0.1",
            forwarded="6.6.6.6, 1.2.3.4, 10.0.0.2",
        )
        self.assertEqual(
            client_ip(req, ("127.0.0.1/32", "10.0.0.0/8")),
            "1.2.3.4",
        )

    def test_falls_back_to_peer_address(self) -> None:
        self.assertEqual(client_ip(_request(host="7.7.7.7"), ()), "7.7.7.7")

    def test_untrusted_peer_cannot_forge_headers(self) -> None:
        req = _request(host="7.7.7.7", real_ip="1.2.3.4", forwarded="6.6.6.6")
        self.assertEqual(client_ip(req, ("127.0.0.1/32",)), "7.7.7.7")

    def test_malformed_forwarded_chain_fails_closed_to_peer(self) -> None:
        for forwarded in ("1.2.3.4, not-an-ip", "1.2.3.4,,10.0.0.2"):
            with self.subTest(forwarded=forwarded):
                req = _request(host="127.0.0.1", forwarded=forwarded)
                self.assertEqual(client_ip(req, ("127.0.0.1/32",)), "127.0.0.1")

    def test_missing_client_is_unknown(self) -> None:
        req = cast(ClientAddressRequest, SimpleNamespace(headers={}, client=None))
        self.assertEqual(client_ip(req, ("127.0.0.1/32",)), "unknown")

    def test_ipv6_proxy_network_is_supported(self) -> None:
        req = _request(host="::1", forwarded="2001:4860:4860::8888")
        self.assertEqual(
            client_ip(req, ("::1/128",)),
            "2001:4860:4860::8888",
        )

    def test_invalid_proxy_network_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ClientAddressResolver(("not-a-cidr",))


class RateLimiterTest(unittest.TestCase):
    def test_allows_up_to_max_then_blocks(self) -> None:
        limiter = RateLimiter(max_requests=3, window_seconds=60)
        for _ in range(3):
            self.assertTrue(limiter.is_allowed("a"))
        self.assertFalse(limiter.is_allowed("a"))

    def test_buckets_are_per_key(self) -> None:
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        self.assertTrue(limiter.is_allowed("a"))
        self.assertFalse(limiter.is_allowed("a"))
        self.assertTrue(limiter.is_allowed("b"))

    def test_tracking_is_bounded_even_when_monotonic_does_not_advance(self) -> None:
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        with mock.patch("web.web_rate_limit.time.monotonic", return_value=100.0):
            for index in range(5000):
                limiter.is_allowed(f"source-{index}")
        self.assertLessEqual(len(limiter._hits), limiter._MAX_TRACKED_IPS)


class LimiterRegistryTest(unittest.TestCase):
    def test_login_and_search_have_dedicated_buckets(self) -> None:
        self.assertIs(limiter_for("/admin/api/login"), LOGIN_LIMITER)
        self.assertIs(limiter_for("/api/search"), SEARCH_LIMITER)

    def test_unknown_path_uses_default(self) -> None:
        self.assertIs(limiter_for("/api/status"), DEFAULT_LIMITER)
        self.assertIs(limiter_for("/admin/api/config"), DEFAULT_LIMITER)


class LoginGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.guard = LoginGuard()

    def test_locks_after_max_failures(self) -> None:
        self.assertFalse(self.guard.record_failure("ip", max_failures=3, lock_seconds=300))
        self.assertFalse(self.guard.record_failure("ip", max_failures=3, lock_seconds=300))
        self.assertTrue(self.guard.record_failure("ip", max_failures=3, lock_seconds=300))
        self.assertGreater(self.guard.locked_seconds("ip", 300), 0)

    def test_lock_is_per_key(self) -> None:
        for _ in range(3):
            self.guard.record_failure("ip-a", max_failures=3, lock_seconds=300)
        self.assertGreater(self.guard.locked_seconds("ip-a", 300), 0)
        self.assertEqual(self.guard.locked_seconds("ip-b", 300), 0)

    def test_success_clears_counter(self) -> None:
        self.guard.record_failure("ip", max_failures=3, lock_seconds=300)
        self.guard.record_failure("ip", max_failures=3, lock_seconds=300)
        self.guard.record_success("ip")
        # 计数清零后再失败两次仍不该锁定
        self.assertFalse(self.guard.record_failure("ip", max_failures=3, lock_seconds=300))
        self.assertFalse(self.guard.record_failure("ip", max_failures=3, lock_seconds=300))

    def test_zero_lock_seconds_disables_lockout(self) -> None:
        for _ in range(10):
            self.assertFalse(self.guard.record_failure("ip", max_failures=3, lock_seconds=0))
        self.assertEqual(self.guard.locked_seconds("ip", 0), 0)

    def test_zero_max_failures_disables_lockout(self) -> None:
        for _ in range(10):
            self.assertFalse(self.guard.record_failure("ip", max_failures=0, lock_seconds=300))

    def test_failure_tracking_is_strictly_bounded(self) -> None:
        for index in range(5000):
            self.guard.record_failure(
                f"198.51.100.{index}",
                max_failures=3,
                lock_seconds=300,
            )

        self.assertLessEqual(
            len(self.guard._failures),
            self.guard._MAX_TRACKED_IPS,
        )

    def test_old_failure_count_expires(self) -> None:
        with mock.patch(
            "web.web_rate_limit.time.monotonic",
            side_effect=(100.0, 401.0, 402.0),
        ):
            self.assertFalse(
                self.guard.record_failure("ip", max_failures=2, lock_seconds=300)
            )
            self.assertFalse(
                self.guard.record_failure("ip", max_failures=2, lock_seconds=300)
            )

        self.assertEqual(self.guard.locked_seconds("ip", 300), 0)


if __name__ == "__main__":
    unittest.main()
