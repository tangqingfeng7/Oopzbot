import glob
import io
import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler

from core.paths import LOG_FILE
from core.paths import LOGS_DIR as LOG_DIR

LOG_RETENTION_DAYS = 7

_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

def _env_level(env_key: str, default: int) -> int:
    raw = os.environ.get(env_key, "").upper().strip()
    return _LEVEL_MAP.get(raw, default)

_FORMATTER = logging.Formatter(
    fmt="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

_initialized = False
_file_handler: RotatingFileHandler | None = None


def _cleanup_old_logs(log_dir: str) -> None:
    """删除超过 LOG_RETENTION_DAYS 天的日志文件。"""
    if not os.path.isdir(log_dir):
        return
    cutoff = time.time() - LOG_RETENTION_DAYS * 86400
    removed = 0
    for path in glob.glob(os.path.join(log_dir, "*.log*")):
        try:
            if os.path.getmtime(path) < cutoff:
                os.remove(path)
                removed += 1
        except OSError:
            pass
    if removed:
        logging.getLogger("LogCleanup").info(
            f"已清理 {removed} 个超过 {LOG_RETENTION_DAYS} 天的日志文件"
        )


def setup_logger(name: str, level=logging.DEBUG) -> logging.Logger:
    """
    创建并返回一个配置好的 logger。
    首次调用时初始化控制台 handler；文件日志由 bot 入口通过 `enable_file_logging()` 开启。
    """
    global _initialized

    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not _initialized:
        console_level = _env_level("BOT_LOG_CONSOLE_LEVEL", logging.INFO)

        if sys.platform == "win32" and sys.stdout is sys.__stdout__ and sys.stderr is sys.__stderr__:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(console_level)
        console_handler.setFormatter(_FORMATTER)

        root = logging.getLogger()
        root.setLevel(min(root.level or logging.WARNING, console_level))
        root.addHandler(console_handler)

        _attach_sdk_logger(console_handler)
        _initialized = True

    return logger


def enable_file_logging(log_file: str = LOG_FILE) -> logging.Handler:
    """为当前进程开启滚动文件日志；只有 bot 主进程应调用，重复调用返回同一 handler。"""
    global _file_handler

    if _file_handler is not None:
        return _file_handler

    log_dir = os.path.dirname(log_file) or LOG_DIR
    os.makedirs(log_dir, exist_ok=True)
    _cleanup_old_logs(log_dir)

    file_level = _env_level("BOT_LOG_FILE_LEVEL", logging.DEBUG)
    handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setLevel(file_level)
    handler.setFormatter(_FORMATTER)

    root = logging.getLogger()
    root.setLevel(min(root.level or logging.WARNING, file_level))
    root.addHandler(handler)
    _attach_sdk_logger(handler)
    _file_handler = handler
    return handler


def _attach_sdk_logger(*handlers: logging.Handler) -> None:
    sdk_logger = logging.getLogger("oopz_sdk")
    sdk_logger.setLevel(_env_level("BOT_SDK_LOG_LEVEL", logging.INFO))
    existing = set(sdk_logger.handlers)
    for handler in handlers:
        if handler not in existing:
            sdk_logger.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """获取已配置的 logger（简写）"""
    return setup_logger(name)
