
from __future__ import annotations

import importlib
import logging
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from core import logger_config  # noqa: E402


class SdkLoggingBridgeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sdk_logger = logging.getLogger("oopz_sdk")
        self._propagate = self.sdk_logger.propagate
        self._level = self.sdk_logger.level
        self.addCleanup(setattr, self.sdk_logger, "propagate", self._propagate)
        self.addCleanup(self.sdk_logger.setLevel, self._level)

    def setUpHandlers(self) -> logging.Handler:
        handler = logging.Handler()
        self.addCleanup(self.sdk_logger.removeHandler, handler)
        return handler

    def test_sdk_logs_reach_project_handler(self) -> None:
        handler = self.setUpHandlers()

        logger_config._attach_sdk_logger(handler)

        self.assertIn(handler, self.sdk_logger.handlers, "SDK 日志要能进项目 handler")

    def test_survives_sdk_being_imported_afterwards(self) -> None:
        handler = self.setUpHandlers()
        logger_config._attach_sdk_logger(handler)

        self.sdk_logger.propagate = False  # 模拟 SDK 在此之后被导入

        self.assertIn(
            handler,
            self.sdk_logger.handlers,
            "SDK 后导入把 propagate 改回 False 时，日志仍必须送得出去",
        )

    def test_does_not_attach_same_handler_twice(self) -> None:
        handler = self.setUpHandlers()

        logger_config._attach_sdk_logger(handler)
        logger_config._attach_sdk_logger(handler)

        self.assertEqual(
            self.sdk_logger.handlers.count(handler), 1, "重复初始化不该产生重复日志"
        )

    def test_level_defaults_to_info(self) -> None:
        import os

        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("BOT_SDK_LOG_LEVEL", None)
            logger_config._attach_sdk_logger()

        self.assertEqual(self.sdk_logger.level, logging.INFO, "默认不该打开 DEBUG 淹没日志")

    def test_level_can_be_raised_by_env(self) -> None:
        with patch.dict("os.environ", {"BOT_SDK_LOG_LEVEL": "DEBUG"}):
            logger_config._attach_sdk_logger()

        self.assertEqual(self.sdk_logger.level, logging.DEBUG)

    def test_sdk_import_really_cuts_propagation(self) -> None:
        """确认这个桥接不是多余的：SDK 导入后 propagate 确实是 False。"""
        module = importlib.import_module("oopz_sdk")
        source = Path(module.__file__ or "").read_text(encoding="utf-8")

        self.assertIn(
            "_logger.propagate = False",
            source,
            "上游若不再切断传播，这个桥接就可以撤掉",
        )


class FileLoggingTest(unittest.TestCase):
    def test_get_logger_does_not_write_bot_log_file(self) -> None:
        logger_config.get_logger("FileLoggingTest")

        file_handlers = [
            handler
            for handler in logging.getLogger().handlers
            if isinstance(handler, logging.FileHandler)
        ]
        self.assertEqual(file_handlers, [], "测试和工具进程不该写入 bot 的日志文件")

    def test_enable_file_logging_attaches_once(self) -> None:
        import tempfile

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        log_file = str(Path(directory.name) / "bot.log")
        root = logging.getLogger()
        sdk_logger = logging.getLogger("oopz_sdk")
        self.addCleanup(setattr, logger_config, "_file_handler", None)
        self.addCleanup(root.setLevel, root.level)

        handler = logger_config.enable_file_logging(log_file)
        self.addCleanup(handler.close)
        self.addCleanup(sdk_logger.removeHandler, handler)
        self.addCleanup(root.removeHandler, handler)

        self.assertIs(logger_config.enable_file_logging(log_file), handler)
        self.assertEqual(root.handlers.count(handler), 1)
        self.assertIn(handler, sdk_logger.handlers)
        logging.getLogger("FileLoggingTest").warning("写入文件")
        handler.flush()
        self.assertIn("写入文件", Path(log_file).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
