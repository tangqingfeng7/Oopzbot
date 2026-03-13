"""程序入口。"""

import os
import sys

if sys.platform == "win32":
    os.system("chcp 65001 >nul 2>&1")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from app.bootstrap import BotApplication
from app.runtime import apply_runtime_overrides


def main() -> None:
    apply_runtime_overrides()
    BotApplication().run()


if __name__ == "__main__":
    main()
