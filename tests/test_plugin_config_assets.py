import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
CONFIG_ROOT = REPO_ROOT / "config" / "plugins"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


class PluginConfigAssetsTest(unittest.TestCase):
    maxDiff = None

    def _load_json(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def _assert_assets_match(self, plugin, plugin_name: str) -> None:
        from app.infrastructure.plugin_runtime import (
            build_plugin_config_example,
            build_plugin_config_schema,
        )

        example = build_plugin_config_example(plugin)
        schema = build_plugin_config_schema(plugin)

        self.assertEqual(
            example,
            self._load_json(CONFIG_ROOT / f"{plugin_name}.example.json"),
        )
        self.assertEqual(
            schema,
            self._load_json(CONFIG_ROOT / f"{plugin_name}.schema.json"),
        )

    def test_delta_force_assets_match_config_spec(self) -> None:
        from plugins.delta_force import DeltaForcePlugin

        self._assert_assets_match(DeltaForcePlugin(), "delta_force")

    def test_lol_ban_assets_match_config_spec(self) -> None:
        from plugins.lol_ban import LolBanPlugin

        self._assert_assets_match(LolBanPlugin(), "lol_ban")

    def test_lol_fa8_assets_match_config_spec(self) -> None:
        from plugins.lol_fa8 import LolFa8Plugin

        self._assert_assets_match(LolFa8Plugin(), "lol_fa8")

    def test_write_plugin_config_assets_writes_example_and_schema(self) -> None:
        from app.infrastructure.plugin_runtime import (
            build_plugin_config_example,
            build_plugin_config_schema,
            write_plugin_config_assets,
        )
        from plugins.lol_ban import LolBanPlugin

        plugin = LolBanPlugin()
        with tempfile.TemporaryDirectory() as temp_dir:
            example_path, schema_path = write_plugin_config_assets(plugin, temp_dir)

            self.assertTrue(example_path.is_file())
            self.assertTrue(schema_path.is_file())
            self.assertEqual(
                self._load_json(example_path),
                build_plugin_config_example(plugin),
            )
            self.assertEqual(
                self._load_json(schema_path),
                build_plugin_config_schema(plugin),
            )

    def test_export_plugin_config_assets_exports_selected_plugins(self) -> None:
        from app.infrastructure.plugin_runtime import export_plugin_config_assets

        with tempfile.TemporaryDirectory() as temp_dir:
            exported = export_plugin_config_assets(
                ["lol_ban"],
                output_dir=temp_dir,
            )

            self.assertEqual(len(exported), 1)
            plugin_name, example_path, schema_path = exported[0]
            self.assertEqual(plugin_name, "lol_ban")
            self.assertTrue(example_path.is_file())
            self.assertTrue(schema_path.is_file())
            self.assertEqual(example_path.name, "lol_ban.example.json")
            self.assertEqual(schema_path.name, "lol_ban.schema.json")

    def test_export_tool_cli_exports_selected_plugin(self) -> None:
        tool_path = REPO_ROOT / "tools" / "export_plugin_config_assets.py"
        with tempfile.TemporaryDirectory() as temp_dir:
            result = subprocess.run(
                [
                    sys.executable,
                    str(tool_path),
                    "lol_fa8",
                    "--output-dir",
                    temp_dir,
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("[ok] lol_fa8", result.stdout)
            self.assertTrue((Path(temp_dir) / "lol_fa8.example.json").is_file())
            self.assertTrue((Path(temp_dir) / "lol_fa8.schema.json").is_file())


if __name__ == "__main__":
    unittest.main()
