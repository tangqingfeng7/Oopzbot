import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from oopz_sender import OopzSender  # noqa: E402


class OopzSenderPrivateDmTests(unittest.TestCase):
    def test_extract_private_channel_from_nested_id(self):
        payload = {
            "status": True,
            "data": {
                "conversationInfo": {
                    "id": "01KJP5MHQC7TSQ6FDKT8N1DZAX",
                }
            },
        }
        self.assertEqual(
            OopzSender._extract_private_channel(payload),
            "01KJP5MHQC7TSQ6FDKT8N1DZAX",
        )

    def test_extract_private_channel_ignores_lower_hex_uid(self):
        payload = {
            "data": {
                "target": "a8cefa6020c711ef948e22d3a3e3e6e2",
                "session": {
                    "target": "b8cefa6020c711ef948e22d3a3e3e6e2",
                },
            }
        }
        self.assertIsNone(OopzSender._extract_private_channel(payload))


if __name__ == "__main__":
    unittest.main()
