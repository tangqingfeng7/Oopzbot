import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from plugins._delta_force_api import DeltaForceApiClient  # noqa: E402


class _Resp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _Session:
    def __init__(self):
        self.calls = []

    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append(("GET", url, headers, params, timeout))
        if len(self.calls) == 1:
            return _Resp(500, {"message": "server error"})
        return _Resp(200, {"code": 0, "data": {"ok": True}})

    def request(self, method, url, headers=None, data=None, json=None, timeout=None):
        self.calls.append((method, url, headers, data or json, timeout))
        return _Resp(200, {"code": 0})


class DeltaForceApiTests(unittest.TestCase):
    def test_request_fails_over_to_next_base_url(self):
        session = _Session()
        client = DeltaForceApiClient(
            {
                "api_key": "sk-test",
                "client_id": "client-1",
                "base_urls": ["https://one.example", "https://two.example"],
                "request_retries": 1,
            },
            session=session,
        )

        result = client.get_personal_info("tok")

        self.assertEqual(result["code"], 0)
        self.assertEqual(len(session.calls), 2)
        self.assertIn("https://one.example", session.calls[0][1])
        self.assertIn("https://two.example", session.calls[1][1])
        self.assertEqual(
            session.calls[0][2]["Authorization"],
            "Bearer sk-test",
        )


if __name__ == "__main__":
    unittest.main()
