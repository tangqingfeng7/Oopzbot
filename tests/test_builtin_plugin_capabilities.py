import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


class BuiltinPluginCapabilitiesSmokeTest(unittest.TestCase):
    def test_delta_force_declares_expected_capabilities(self) -> None:
        from plugins.delta_force import DeltaForcePlugin

        plugin = DeltaForcePlugin()
        capabilities = plugin.command_capabilities

        self.assertEqual(capabilities.mention_prefixes, ("三角洲",))
        self.assertEqual(capabilities.slash_commands, ("/df",))
        self.assertTrue(capabilities.is_public_command)

    def test_delta_force_declares_expected_config_spec(self) -> None:
        from plugins.delta_force import DeltaForcePlugin

        plugin = DeltaForcePlugin()
        field_names = [field.name for field in plugin.config_spec.fields]

        self.assertEqual(
            field_names,
            [
                "enabled",
                "api_key",
                "client_id",
                "api_mode",
                "base_urls",
                "request_timeout_sec",
                "request_retries",
                "login_timeout_sec",
                "login_poll_interval_sec",
                "login_success_notice_delay_sec",
                "login_delivery_mode",
                "daily_keyword_push_check_interval_sec",
                "daily_keyword_push_time",
                "place_push_interval_sec",
                "render_timeout_sec",
                "render_width",
                "render_scale",
                "temp_dir",
            ],
        )

    def test_lol_ban_declares_expected_capabilities(self) -> None:
        from plugins.lol_ban import LolBanPlugin

        plugin = LolBanPlugin()
        capabilities = plugin.command_capabilities

        self.assertEqual(capabilities.mention_prefixes, ("查封号", "封号", "lol", "LOL"))
        self.assertEqual(capabilities.slash_commands, ("/lol",))
        self.assertTrue(capabilities.is_public_command)

    def test_lol_ban_declares_expected_config_spec(self) -> None:
        from plugins.lol_ban import LolBanPlugin

        plugin = LolBanPlugin()
        field_names = [field.name for field in plugin.config_spec.fields]

        self.assertEqual(field_names, ["enabled", "api_url", "token", "proxy"])

    def test_lol_fa8_declares_expected_capabilities(self) -> None:
        from plugins.lol_fa8 import LolFa8Plugin

        plugin = LolFa8Plugin()
        capabilities = plugin.command_capabilities

        self.assertEqual(capabilities.mention_prefixes, ("查询战绩", "查战绩", "战绩"))
        self.assertEqual(capabilities.slash_commands, ("/zj",))
        self.assertTrue(capabilities.is_public_command)

    def test_lol_fa8_declares_expected_config_spec(self) -> None:
        from plugins.lol_fa8 import LolFa8Plugin

        plugin = LolFa8Plugin()
        field_names = [field.name for field in plugin.config_spec.fields]

        self.assertEqual(field_names, ["enabled", "username", "password", "default_area"])


if __name__ == "__main__":
    unittest.main()
