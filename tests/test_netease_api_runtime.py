import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


class NeteaseApiRuntimeTest(unittest.TestCase):
    def test_resolve_api_dir_uses_repo_root_instead_of_src(self) -> None:
        from app.lifecycle.netease_api_runtime import NeteaseApiRuntime

        api_dir = NeteaseApiRuntime._resolve_api_dir("NeteaseAPI_tmp")

        self.assertEqual(api_dir, REPO_ROOT / "NeteaseAPI_tmp")


if __name__ == "__main__":
    unittest.main()
