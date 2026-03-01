import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import web_link_token as wlt  # noqa: E402


class FakeRedis:
    def __init__(self):
        self.kv = {}
        self.expires = {}

    def get(self, key):
        return self.kv.get(key)

    def set(self, key, value, ex=None):
        self.kv[key] = value
        if ex is not None:
            self.expires[key] = ex

    def expire(self, key, ttl):
        self.expires[key] = ttl

    def delete(self, key):
        self.kv.pop(key, None)
        self.expires.pop(key, None)


class WebLinkTokenTests(unittest.TestCase):
    def setUp(self):
        wlt.clear_token()

    def test_set_token_with_ttl_writes_expire(self):
        r = FakeRedis()
        wlt.set_token("abc", redis_client=r, ttl_seconds=120)
        self.assertEqual("abc", r.get(wlt.KEY_WEB_ACCESS_TOKEN))
        self.assertEqual(120, r.expires.get(wlt.KEY_WEB_ACCESS_TOKEN))

    def test_ensure_token_reuses_and_refreshes_ttl(self):
        r = FakeRedis()
        first = wlt.ensure_token(redis_client=r, ttl_seconds=60)
        second = wlt.ensure_token(redis_client=r, ttl_seconds=180)
        self.assertEqual(first, second)
        self.assertEqual(180, r.expires.get(wlt.KEY_WEB_ACCESS_TOKEN))

    def test_clear_token_deletes_memory_and_redis(self):
        r = FakeRedis()
        tok = wlt.ensure_token(redis_client=r, ttl_seconds=30)
        self.assertTrue(tok)
        self.assertTrue(wlt.get_token(redis_client=r))
        wlt.clear_token(redis_client=r)
        self.assertEqual("", wlt.get_token(redis_client=r))
        self.assertIsNone(r.get(wlt.KEY_WEB_ACCESS_TOKEN))

    def test_get_token_does_not_revive_expired_redis_token_from_memory(self):
        r = FakeRedis()
        first = wlt.ensure_token(redis_client=r, ttl_seconds=30)
        r.delete(wlt.KEY_WEB_ACCESS_TOKEN)

        self.assertEqual("", wlt.get_token(redis_client=r))

        second = wlt.ensure_token(redis_client=r, ttl_seconds=30)
        self.assertTrue(second)
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
