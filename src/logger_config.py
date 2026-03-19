import glob
import os
import sys
import io
import logging
import time
from logging.handlers import RotatingFileHandler

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(_PROJECT_ROOT, "logs")
LOG_FILE = os.path.join(LOG_DIR, "oopz_bot.log")

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

_initialized = False


def _ensure_log_dir():
    os.makedirs(LOG_DIR, exist_ok=True)


def _cleanup_old_logs():
    """删除超过 LOG_RETENTION_DAYS 天的日志文件。"""
    if not os.path.isdir(LOG_DIR):
        return
    cutoff = time.time() - LOG_RETENTION_DAYS * 86400
    removed = 0
    for path in glob.glob(os.path.join(LOG_DIR, "*.log*")):
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
    首次调用时初始化文件 handler，后续调用复用同一 handler。
    """
    global _initialized

    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not _initialized:
        _ensure_log_dir()
        _cleanup_old_logs()

        formatter = logging.Formatter(
            fmt="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        file_level = _env_level("BOT_LOG_FILE_LEVEL", logging.DEBUG)
        console_level = _env_level("BOT_LOG_CONSOLE_LEVEL", logging.INFO)

        file_handler = RotatingFileHandler(
            LOG_FILE,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(file_level)
        file_handler.setFormatter(formatter)

        if sys.platform == "win32":
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(console_level)
        console_handler.setFormatter(formatter)

        root = logging.getLogger()
        root.setLevel(min(file_level, console_level))
        root.addHandler(file_handler)
        root.addHandler(console_handler)

        _initialized = True

    return logger


def get_logger(name: str) -> logging.Logger:
    """获取已配置的 logger（简写）"""
    return setup_logger(name)