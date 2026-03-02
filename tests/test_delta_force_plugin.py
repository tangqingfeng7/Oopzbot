import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from plugin_loader import discover_plugins  # noqa: E402
from plugins.delta_force import DeltaForcePlugin  # noqa: E402


class _Sender:
    def __init__(self):
        self.messages = []
        self.images = []

    def send_message(self, text, channel=None, area=None, **kwargs):
        self.messages.append({"text": text, "channel": channel, "area": area, "kwargs": kwargs})

    def upload_and_send_image(self, file_path, text="", channel=None, area=None, **kwargs):
        self.images.append({"file_path": file_path, "text": text, "channel": channel, "area": area, "kwargs": kwargs})


class _Handler:
    def __init__(self):
        self.sender = _Sender()


class _Store:
    def __init__(self, token=None):
        self.token = token

    def get_active_token(self, user_id, group="qq_wechat"):
        return self.token

    def set_active_token(self, user_id, token, group="qq_wechat"):
        self.token = token

    def choose_active_token(self, user_id, accounts, group="qq_wechat"):
        if self.token:
            return self.token
        for item in accounts:
            if item.get("isValid") and item.get("frameworkToken"):
                self.token = item["frameworkToken"]
                return self.token
        return None


class _Api:
    def __init__(self, accounts=None, records=None):
        self.configured = True
        self._accounts = accounts if accounts is not None else []
        self._records = records if records is not None else []

    def get_user_list(self, user):
        return {"code": 0, "data": self._accounts}

    def get_personal_info(self, token):
        return {
            "code": 0,
            "roleInfo": {"uid": "9988", "level": "18", "tdmlevel": "12"},
            "data": {
                "careerData": {"soltotalfght": 9, "tdmtotalfight": 7},
                "userData": {"charac_name": "测试玩家"},
            },
        }

    def get_record(self, token, type_id, page):
        return {"code": 0, "data": self._records}

    def bind_character(self, token):
        return {"code": 0, "success": True}


class _Login:
    def __init__(self):
        self.cancelled = False

    def start_login(self, user, platform, channel, area, handler):
        return f"start {platform}"

    def cancel_all(self):
        self.cancelled = True


class DeltaForcePluginTests(unittest.TestCase):
    def _plugin(self):
        plugin = DeltaForcePlugin()
        plugin.on_load(None, {"api_key": "sk", "client_id": "client"})
        return plugin

    def test_plugin_is_discoverable(self):
        names = discover_plugins("plugins")
        self.assertIn("delta_force", names)

    def test_help_command_returns_help_text(self):
        plugin = self._plugin()
        handler = _Handler()
        plugin.handle_mention("三角洲帮助", "c1", "a1", "u1", handler)
        self.assertIn("三角洲插件命令", handler.sender.messages[-1]["text"])

    def test_info_without_account_prompts_login(self):
        plugin = self._plugin()
        plugin._api = _Api(accounts=[])
        plugin._store = _Store(token=None)
        plugin._renderer = None
        handler = _Handler()

        plugin.handle_mention("三角洲信息", "c1", "a1", "u1", handler)

        self.assertIn("请先登录", handler.sender.messages[-1]["text"])

    def test_slash_record_routes_and_falls_back_to_text(self):
        plugin = self._plugin()
        plugin._api = _Api(
            accounts=[{"frameworkToken": "tok", "isValid": True}],
            records=[{"dtEventTime": "2026-03-01 11:00:00", "EscapeFailReason": 1, "FinalPrice": 12345, "KillCount": 4}],
        )
        plugin._store = _Store(token="tok")
        plugin._renderer = None
        handler = _Handler()

        plugin.handle_slash("/df", "record", "sol 2", "c1", "a1", "u1", handler)

        self.assertIn("烽火地带 第 2 页战绩", handler.sender.messages[-1]["text"])

    def test_on_unload_cancels_login_manager(self):
        plugin = self._plugin()
        login = _Login()
        plugin._login = login

        plugin.on_unload()

        self.assertTrue(login.cancelled)


if __name__ == "__main__":
    unittest.main()
