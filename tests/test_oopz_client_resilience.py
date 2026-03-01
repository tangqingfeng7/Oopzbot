import os
import sys
import unittest
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from oopz_client import OopzClient  # noqa: E402


class _BrokenWs:
    def send(self, _payload):
        raise RuntimeError("socket closed")


class OopzClientResilienceTests(unittest.TestCase):
    @patch("oopz_client.logger.debug")
    def test_send_heartbeat_does_not_raise_when_socket_closed(self, mock_debug):
        client = OopzClient()
        ws = _BrokenWs()

        # 不应抛出异常
        client._send_heartbeat(ws)

        self.assertTrue(mock_debug.called)


if __name__ == "__main__":
    unittest.main()
