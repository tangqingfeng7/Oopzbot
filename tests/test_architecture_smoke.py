import ast
import py_compile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"


def _parse_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
    return imports


class ArchitectureSmokeTest(unittest.TestCase):
    def test_app_root_only_keeps_composition_entrypoints(self) -> None:
        app_root = SRC_ROOT / "app"
        actual = {path.name for path in app_root.iterdir() if path.is_file()}
        self.assertEqual(actual, {"__init__.py", "bootstrap.py", "runtime.py"})

    def test_infrastructure_root_only_keeps_runtime_entrypoints(self) -> None:
        infra_root = SRC_ROOT / "app" / "infrastructure"
        actual = {path.name for path in infra_root.iterdir() if path.is_file()}
        self.assertEqual(actual, {"__init__.py", "runtime.py"})

    def test_bootstrap_imports_lifecycle_package(self) -> None:
        imports = _parse_imports(SRC_ROOT / "app" / "bootstrap.py")
        self.assertIn("app.lifecycle", imports)
        self.assertNotIn("app.context_builder", imports)
        self.assertNotIn("app.startup_resources", imports)
        self.assertNotIn("app.voice_runtime", imports)

    def test_command_handler_imports_registry_package(self) -> None:
        imports = _parse_imports(SRC_ROOT / "command_handler.py")
        self.assertIn("app.services.registry", imports)
        self.assertNotIn("app.service_registry", imports)

    def test_core_architecture_modules_compile(self) -> None:
        targets = [
            SRC_ROOT / "app" / "__init__.py",
            SRC_ROOT / "app" / "bootstrap.py",
            SRC_ROOT / "app" / "runtime.py",
            SRC_ROOT / "app" / "lifecycle" / "__init__.py",
            SRC_ROOT / "app" / "lifecycle" / "context.py",
            SRC_ROOT / "app" / "services" / "registry" / "__init__.py",
            SRC_ROOT / "app" / "services" / "registry" / "command_service_registry.py",
            SRC_ROOT / "app" / "infrastructure" / "__init__.py",
            SRC_ROOT / "app" / "infrastructure" / "runtime.py",
        ]
        for target in targets:
            with self.subTest(path=target):
                py_compile.compile(str(target), doraise=True)


if __name__ == "__main__":
    unittest.main()
