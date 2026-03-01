import os
import sys
import unittest
import importlib
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)


class _FakeRedis:
    def __init__(self, current=None):
        self.current = current
        self.status = None

    def get(self, key):
        if key != "music:current":
            return None
        return self.current

    def set(self, key, value, ex=None):
        self.status = (key, value, ex)

    def delete(self, key):
        if key == "music:current":
            self.current = None


class AudioServiceTests(unittest.TestCase):
    def test_cleanup_current_clears_uuid_less_sessions(self):
        redis_client = _FakeRedis('{"name":"song"}')
        with patch("redis.Redis", return_value=redis_client):
            audio_service = importlib.import_module("audio_service")
        player = audio_service.AudioPlayer()

        with patch("audio_service.get_redis", return_value=redis_client):
            player._cleanup_current(None)

        self.assertIsNone(redis_client.current)


if __name__ == "__main__":
    unittest.main()
