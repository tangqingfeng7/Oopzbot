import atexit
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import requests

from config import NETEASE_CLOUD
from logger_config import setup_logger

logger = setup_logger("NeteaseApiRuntime")


class NeteaseApiRuntime:
    def __init__(self) -> None:
        self._process: Optional[subprocess.Popen] = None

    @staticmethod
    def _project_root() -> Path:
        return Path(__file__).resolve().parents[3]

    @classmethod
    def _resolve_api_dir(cls, raw_path: str) -> Path:
        return cls._project_root() / raw_path.strip()

    def start(self) -> None:
        path = NETEASE_CLOUD.get("auto_start_path", "")
        if not path or not path.strip():
            return

        api_dir = self._resolve_api_dir(path)
        app_js = api_dir / "app.js"
        if not app_js.is_file():
            logger.info("网易云 API 目录不存在，跳过启动: %s", api_dir)
            return

        node_cmd = self._find_node_binary()
        env = os.environ.copy()
        local_bin = os.path.expanduser("~/.local/bin")
        if local_bin and local_bin not in env.get("PATH", ""):
            env["PATH"] = local_bin + os.pathsep + env.get("PATH", "")

        logger.info("正在启动网易云 API: %s", api_dir)
        try:
            self._process = subprocess.Popen(
                [node_cmd, "app.js"],
                cwd=str(api_dir),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
            )
        except Exception as exc:
            logger.warning("启动网易云 API 失败: %s", exc)
            return

        atexit.register(self.stop)
        self._wait_until_ready()

    def stop(self, timeout: float = 5.0) -> None:
        if not self._process or self._process.poll() is not None:
            return

        self._process.terminate()
        try:
            self._process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._process.kill()
        except Exception as exc:
            logger.warning("停止网易云 API 时出现异常: %s", exc)
        finally:
            logger.info("网易云 API 已停止。")

    def _find_node_binary(self) -> str:
        node_cmd = shutil.which("node")
        if node_cmd:
            return node_cmd

        for candidate in (os.path.expanduser("~/.local/bin/node"), "/usr/bin/node"):
            if candidate and os.path.isfile(candidate):
                return candidate
        return "node"

    def _wait_until_ready(self) -> None:
        base_url = NETEASE_CLOUD.get("base_url", "http://localhost:3000").rstrip("/")
        url = f"{base_url}/"

        for _ in range(30):
            time.sleep(0.5)
            try:
                response = requests.get(url, timeout=2)
            except requests.RequestException:
                continue
            if response.status_code < 500:
                logger.info("网易云 API 已就绪。")
                return

        logger.warning("网易云 API 启动超时，音乐功能可能不可用。")
