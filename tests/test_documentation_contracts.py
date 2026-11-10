import ast
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


class DocumentationContractsTest(unittest.TestCase):
    def test_architecture_lists_every_core_database_table(self) -> None:
        database_source = _read("src/core/database.py")
        architecture = _read("docs/architecture.md")
        tables = set(
            re.findall(
                r"CREATE TABLE IF NOT EXISTS\s+([a-z0-9_]+)",
                database_source,
            )
        )

        self.assertEqual(len(tables), 11)
        missing = sorted(table for table in tables if f"`{table}`" not in architecture)
        self.assertEqual(missing, [])

    def test_architecture_documents_current_module_boundaries(self) -> None:
        architecture = _read("docs/architecture.md")
        required_paths = (
            "message_dispatcher.py",
            "music_platform.py",
            "area_events.py",
            "src/web/admin/",
        )
        for path in required_paths:
            with self.subTest(path=path):
                self.assertIn(path, architecture)

        self.assertNotIn("Admin 后台所有路由（`APIRouter`）", architecture)
        self.assertIn("9 行稳定 facade", architecture)

    def test_architecture_documents_area_scoped_and_global_redis_keys(self) -> None:
        architecture = _read("docs/architecture.md")
        documented_keys = (
            "music:<area>:queue",
            "music:<area>:current",
            "music:<area>:default_channel",
            "music:<area>:play_state",
            "music:<area>:play_mode",
            "music:volume",
            "music:web_commands",
            "music:web_access_token",
            "music:web_active_area",
            "music:web_last_access",
            "music:admin_session:<token>",
        )
        for key in documented_keys:
            with self.subTest(key=key):
                self.assertIn(key, architecture)

    def test_api_and_player_entry_documentation_matches_routes(self) -> None:
        api_reference = _read("docs/api-reference.md")
        commands = _read("docs/commands.md")

        self.assertIn("/client/v1/area/v1/operateLogs", api_reference)
        self.assertIn("DELETE /client/v1/area/v1/quit?area={area}", api_reference)
        self.assertIn("**请求体：** 无。", api_reference)
        self.assertIn("/w/{token}", commands)
        self.assertIn("GET /", commands)
        self.assertIn("HTTP 403", commands)
        self.assertNotIn(
            "访问 `http://<服务器IP>:8080/` 即可打开 Web 播放器",
            commands,
        )

    def test_api_reference_lists_every_service_endpoint(self) -> None:
        api_reference = _read("docs/api-reference.md")
        import oopz_sdk.services

        service_directory = Path(oopz_sdk.services.__file__).parent
        endpoint_paths: set[str] = set()

        source_paths = [*service_directory.glob("*.py"), REPO_ROOT / "src/app/infrastructure/gateways/sender_gateway.py"]
        for source_path in source_paths:
            tree = ast.parse(source_path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                    continue
                value = node.value
                if re.fullmatch(r"/[A-Za-z0-9_./-]+", value) and "/v" in value:
                    endpoint_paths.add(value)

        self.assertGreaterEqual(len(endpoint_paths), 50)
        missing = sorted(path for path in endpoint_paths if path not in api_reference)
        self.assertEqual(missing, [])

    def test_api_reference_uses_current_paths_and_stays_implementation_free(self) -> None:
        api_reference = _read("docs/api-reference.md")

        for current_path in (
            "/general/v3/settings",
            "/uni/advertisement/v1/list",
            "/uni/officialSticker/v2/list",
            "/im/session/v2/sendGimMessage",
            "/im/session/v2/sendImMessage",
        ):
            with self.subTest(current_path=current_path):
                self.assertIn(current_path, api_reference)

        for stale_path in (
            "/general/v2/curTime",
            "/general/v2/settings",
            "/general/v2/switch",
            "/task/v1/bounty/list",
            "/advertisement/v2/list",
            "/discovery/v3/home",
            "/client/v1/sticker/v1/list",
            "/client/v1/roaming/v1/emojis",
        ):
            with self.subTest(stale_path=stale_path):
                self.assertNotIn(stale_path, api_reference)

        for implementation_detail in (
            "SDK",
            "src/oopz",
            "OopzApiMixin",
            "_request_data",
            "SenderGateway",
        ):
            with self.subTest(implementation_detail=implementation_detail):
                self.assertNotIn(implementation_detail, api_reference)

    def test_scaffold_and_environment_documentation_matches_code(self) -> None:
        plugin_development = _read("docs/plugin-development.md")
        configuration = _read("docs/configuration.md")

        self.assertIn("PluginCommandMixin", plugin_development)
        self.assertIn("dispatch_command", plugin_development)
        self.assertNotIn("空实现的 `handle_mention / handle_slash`", plugin_development)

        environment_variables = (
            "OOPZ_DEBUG_WS_EVENTS",
            "BOT_CHROMIUM_EXECUTABLE_PATH",
            "CHROME_BIN",
            "CHROME_PATH",
            "OOPZ_PHONE",
            "OOPZ_PASSWORD",
        )
        for name in environment_variables:
            with self.subTest(name=name):
                self.assertIn(f"`{name}`", configuration)

    def test_member_event_comment_and_contributor_links_stay_current(self) -> None:
        area_events = _read("src/oopz/area_events.py")
        readme = _read("README.md")

        self.assertNotIn("Leaves are not covered by polling", area_events)
        for target in (
            "plugins/README.md",
            "config/plugins/README.md",
            "src/README.md",
        ):
            with self.subTest(target=target):
                self.assertIn(f"]({target})", readme)


if __name__ == "__main__":
    unittest.main()
