import os
import sys
import unittest
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from command_handler import CommandHandler  # noqa: E402


class DummySender:
    def __init__(self):
        self.messages = []

    def send_message(self, text, channel=None, area=None, **kwargs):
        self.messages.append(
            {
                "text": text,
                "channel": channel,
                "area": area,
                "kwargs": kwargs,
            }
        )


class DummyRegistry:
    def __init__(self, loaded=None):
        self.loaded = loaded or []

    def try_dispatch_slash(self, *args, **kwargs):
        return False

    def list_all(self):
        return list(self.loaded)


class PluginCommandTests(unittest.TestCase):
    def _handler(self):
        h = CommandHandler.__new__(CommandHandler)
        h.sender = DummySender()
        h._plugin_registry = DummyRegistry(
            loaded=[
                {
                    "name": "lol_ban",
                    "description": "LOL 封禁查询",
                    "version": "1.0.0",
                    "author": "",
                    "builtin": False,
                }
            ]
        )
        h._is_admin = lambda user: True
        return h

    def test_dispatch_plugins_command_routes_to_plugin_list(self):
        h = self._handler()
        called = {"ok": False}

        def fake_list(channel, area):
            called["ok"] = True
            h.sender.send_message("plugin list called", channel=channel, area=area)

        h._cmd_plugin_list = fake_list
        h._dispatch_command("/plugins", "c1", "a1", "u1")
        self.assertTrue(called["ok"])
        self.assertIn("plugin list called", h.sender.messages[-1]["text"])

    @patch("command_handler.discover_plugins", return_value=["lol_ban", "lol_fa8"])
    def test_cmd_plugin_list_includes_loaded_and_available(self, _mock_discover):
        h = self._handler()
        h._cmd_plugin_list("c1", "a1")
        text = h.sender.messages[-1]["text"]
        self.assertIn("已加载: 1", text)
        self.assertIn("lol_ban", text)
        self.assertIn("可加载: 1", text)
        self.assertIn("lol_fa8", text)

    @patch("command_handler.load_plugin", return_value=(True, "已加载: demo"))
    def test_cmd_plugin_load_valid_and_invalid_name(self, mock_load):
        h = self._handler()

        h._cmd_plugin_load("bad/name", "c1", "a1")
        self.assertIn("插件名不合法", h.sender.messages[-1]["text"])
        mock_load.assert_not_called()

        h._cmd_plugin_load("demo.py", "c1", "a1")
        self.assertIn("[ok]", h.sender.messages[-1]["text"])
        mock_load.assert_called_once()

    @patch("command_handler.unload_plugin", return_value=(False, "插件未加载: demo"))
    def test_cmd_plugin_unload_returns_error_message(self, mock_unload):
        h = self._handler()
        h._cmd_plugin_unload("demo", "c1", "a1")
        self.assertIn("[x]", h.sender.messages[-1]["text"])
        self.assertIn("插件未加载", h.sender.messages[-1]["text"])
        mock_unload.assert_called_once()


if __name__ == "__main__":
    unittest.main()
