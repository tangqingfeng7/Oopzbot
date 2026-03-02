import os
import sys
import unittest
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import oopz_sender  # noqa: E402


class _FakeResponse:
    def __init__(self, status_code, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}

    def json(self):
        return self._payload


class OopzSenderResilienceTests(unittest.TestCase):
    def test_get_area_members_uses_fresh_cache_when_quiet(self):
        sender = oopz_sender.OopzSender.__new__(oopz_sender.OopzSender)
        sender._area_members_cache = {
            ("a1", 0, 49): {
                "ts": oopz_sender.time.time(),
                "data": {"members": [{"uid": "u1"}], "userCount": 1, "onlineCount": 1, "fetchedCount": 1},
            }
        }
        sender._get = lambda *args, **kwargs: self.fail("should not request network when cache is fresh")

        data = sender.get_area_members(area="a1", quiet=True)

        self.assertEqual(data["userCount"], 1)
        self.assertEqual(data["members"][0]["uid"], "u1")

    @patch("oopz_sender.time.sleep")
    def test_get_area_members_retries_after_429_then_succeeds(self, mock_sleep):
        sender = oopz_sender.OopzSender.__new__(oopz_sender.OopzSender)
        responses = iter(
            [
                _FakeResponse(429),
                _FakeResponse(
                    200,
                    payload={
                        "status": True,
                        "data": {
                            "members": [{"uid": "u1", "online": 1}, {"uid": "u2", "online": 0}],
                            "userCount": 2,
                        },
                    },
                ),
            ]
        )
        sender._get = lambda *args, **kwargs: next(responses)

        data = sender.get_area_members(area="a1", quiet=True)

        self.assertEqual(data["userCount"], 2)
        self.assertEqual(data["onlineCount"], 1)
        mock_sleep.assert_called_once_with(1)

    @patch("oopz_sender.time.sleep")
    def test_get_area_members_returns_429_after_retry_exhausted(self, mock_sleep):
        sender = oopz_sender.OopzSender.__new__(oopz_sender.OopzSender)
        sender._get = lambda *args, **kwargs: _FakeResponse(429)

        data = sender.get_area_members(area="a1", quiet=True)

        self.assertEqual(data, {"error": "HTTP 429"})
        self.assertEqual(mock_sleep.call_count, 2)

    @patch("oopz_sender.time.sleep")
    def test_get_area_members_returns_stale_cache_when_429_persists(self, mock_sleep):
        sender = oopz_sender.OopzSender.__new__(oopz_sender.OopzSender)
        sender._area_members_cache = {
            ("a1", 0, 49): {
                "ts": oopz_sender.time.time() - 5,
                "data": {"members": [{"uid": "u1"}], "userCount": 1, "onlineCount": 1, "fetchedCount": 1},
            }
        }
        sender._get = lambda *args, **kwargs: _FakeResponse(429)

        data = sender.get_area_members(area="a1", quiet=True)

        self.assertEqual(data["userCount"], 1)
        self.assertTrue(data["stale"])
        self.assertTrue(data["rateLimited"])
        self.assertEqual(mock_sleep.call_count, 2)


if __name__ == "__main__":
    unittest.main()
