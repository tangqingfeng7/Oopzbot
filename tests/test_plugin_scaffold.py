import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


class PluginScaffoldTest(unittest.TestCase):
    def test_create_plugin_scaffold_creates_module_and_assets(self) -> None:
        from app.infrastructure.plugin_runtime import create_plugin_scaffold

        with tempfile.TemporaryDirectory() as temp_dir:
            result = create_plugin_scaffold(
                "demo_plugin",
                project_root=temp_dir,
                description="示例插件",
                author="tester",
                mention_prefix="示例",
                slash_command="/demo",
            )

            self.assertEqual(result.plugin_name, "demo_plugin")
            self.assertTrue(result.module_path.is_file())
            self.assertTrue(result.example_path.is_file())
            self.assertTrue(result.schema_path.is_file())

            module_text = result.module_path.read_text(encoding="utf-8")
            self.assertIn("class DemoPlugin(BotModule):", module_text)
            self.assertIn('name="demo_plugin"', module_text)
            self.assertIn('description="示例插件"', module_text)
            self.assertIn('author="tester"', module_text)
            self.assertIn('mention_prefixes=("示例",)', module_text)
            self.assertIn('slash_commands=("/demo",)', module_text)

            example = json.loads(result.example_path.read_text(encoding="utf-8"))
            schema = json.loads(result.schema_path.read_text(encoding="utf-8"))
            self.assertEqual(example, {"enabled": False})
            self.assertEqual(schema["plugin_name"], "demo_plugin")
            self.assertEqual(schema["fields"][0]["name"], "enabled")

    def test_create_plugin_scaffold_rejects_existing_file_without_force(self) -> None:
        from app.infrastructure.plugin_runtime import create_plugin_scaffold

        with tempfile.TemporaryDirectory() as temp_dir:
            plugins_dir = Path(temp_dir) / "plugins"
            plugins_dir.mkdir(parents=True, exist_ok=True)
            (plugins_dir / "demo.py").write_text("# existing\n", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                create_plugin_scaffold("demo", project_root=temp_dir)

    def test_create_plugin_scaffold_force_overwrites_module(self) -> None:
        from app.infrastructure.plugin_runtime import create_plugin_scaffold

        with tempfile.TemporaryDirectory() as temp_dir:
            plugins_dir = Path(temp_dir) / "plugins"
            plugins_dir.mkdir(parents=True, exist_ok=True)
            module_path = plugins_dir / "demo.py"
            module_path.write_text("# existing\n", encoding="utf-8")

            result = create_plugin_scaffold(
                "demo",
                project_root=temp_dir,
                force=True,
            )
            self.assertTrue(result.module_path.is_file())
            self.assertNotEqual(result.module_path.read_text(encoding="utf-8"), "# existing\n")

    def test_create_plugin_scaffold_cli_generates_files(self) -> None:
        tool_path = REPO_ROOT / "tools" / "create_plugin_scaffold.py"
        with tempfile.TemporaryDirectory() as temp_dir:
            env = dict(os.environ)
            env["PYTHONPATH"] = f"{SRC_ROOT};{REPO_ROOT}"
            result = subprocess.run(
                [
                    sys.executable,
                    str(tool_path),
                    "scaffold_cli_demo",
                    "--project-root",
                    temp_dir,
                    "--description",
                    "脚手架 CLI 示例",
                    "--author",
                    "tester",
                    "--mention-prefix",
                    "脚手架",
                    "--slash-command",
                    "/scaffold",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=env,
                check=False,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("[ok] scaffold_cli_demo", result.stdout)
            self.assertTrue((Path(temp_dir) / "plugins" / "scaffold_cli_demo.py").is_file())
            self.assertTrue((Path(temp_dir) / "config" / "plugins" / "scaffold_cli_demo.example.json").is_file())
            self.assertTrue((Path(temp_dir) / "config" / "plugins" / "scaffold_cli_demo.schema.json").is_file())


if __name__ == "__main__":
    unittest.main()
