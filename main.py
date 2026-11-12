"""程序入口。"""

import asyncio
import os
import sys

if sys.platform == "win32":
    os.system("chcp 65001 >nul 2>&1")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from core.logger_config import enable_file_logging

enable_file_logging()

from app.bootstrap import BotApplication
from app.runtime import apply_runtime_overrides, validate_runtime_config


def main() -> None:
    apply_runtime_overrides()
    validate_runtime_config()
    asyncio.run(BotApplication().run())


if __name__ == "__main__":
    main()
