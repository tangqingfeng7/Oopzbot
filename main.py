"""
Oopz Bot 入口
"""

import os
import sys
import subprocess
import time
import atexit
import shutil

if sys.platform == "win32":
    os.system("chcp 65001 >nul 2>&1")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

import threading
import requests

from logger_config import setup_logger
from database import init_database
from oopz_sender import OopzSender
from oopz_client import OopzClient
from command_handler import CommandHandler
from voice_client import VoiceClient
from web_player import run_server as run_web_player
from area_join_notifier import start_area_join_notifier

logger = setup_logger("Main")

_netease_proc = None


def _terminate_netease_proc(timeout: float = 5.0):
    """终止网易云 API 子进程（若仍在运行）。"""
    global _netease_proc
    if not _netease_proc or _netease_proc.poll() is not None:
        return
    _netease_proc.terminate()
    try:
        _netease_proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _netease_proc.kill()
    except Exception as e:
        logger.warning("停止网易云 API 子进程时出现异常: %s", e)
    finally:
        logger.info("网易云 API 已停止")


def _start_netease_api():
    """启动网易云 API 子进程，若已配置且目录存在"""
    global _netease_proc
    try:
        from config import NETEASE_CLOUD
        path = NETEASE_CLOUD.get("auto_start_path", "")
    except Exception as e:
        logger.warning("读取 NETEASE_CLOUD 配置失败，跳过自动启动: %s", e)
        return
    if not path or not path.strip():
        return

    root = os.path.dirname(os.path.abspath(__file__))
    api_dir = os.path.join(root, path.strip())
    app_js = os.path.join(api_dir, "app.js")
    if not os.path.isfile(app_js):
        logger.info(f"网易云 API 目录不存在 ({api_dir})，跳过自动启动")
        return

    # 查找 node：优先 PATH，再试 ~/.local/bin（常见用户安装位置）
    node_cmd = shutil.which("node")
    if not node_cmd:
        for candidate in (os.path.expanduser("~/.local/bin/node"), "/usr/bin/node"):
            if candidate and os.path.isfile(candidate):
                node_cmd = candidate
                break
    if not node_cmd:
        node_cmd = "node"
    env = os.environ.copy()
    local_bin = os.path.expanduser("~/.local/bin")
    if local_bin and local_bin not in env.get("PATH", ""):
        env["PATH"] = local_bin + os.pathsep + env.get("PATH", "")

    logger.info(f"正在启动网易云 API: {api_dir}")
    try:
        _netease_proc = subprocess.Popen(
            [node_cmd, "app.js"],
            cwd=api_dir,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
        )
    except Exception as e:
        logger.warning(f"启动网易云 API 失败: {e}")
        return

    def _cleanup():
        _terminate_netease_proc(timeout=5)

    atexit.register(_cleanup)

    base_url = NETEASE_CLOUD.get("base_url", "http://localhost:3000").rstrip("/")
    url = f"{base_url}/"
    for i in range(30):
        time.sleep(0.5)
        try:
            r = requests.get(url, timeout=2)
            if r.status_code < 500:
                logger.info("网易云 API 已就绪")
                return
        except requests.RequestException:
            pass
    logger.warning("网易云 API 启动超时，音乐功能可能不可用")


def main():
    logger.info("=" * 50)
    logger.info("Oopz Bot 正在启动...")
    logger.info("=" * 50)

    _start_netease_api()
    init_database()

    sender = OopzSender()
    sender.populate_names()

    # 域成员加入/退出通知（WebSocket 实时推送）
    _notifier_ws = start_area_join_notifier(sender=sender)

    # 初始化 Agora 语音频道客户端（Playwright + Agora Web SDK）
    from config import OOPZ_CONFIG
    agora_app_id = OOPZ_CONFIG.get("agora_app_id", "")
    voice = None
    if agora_app_id:
        init_timeout = OOPZ_CONFIG.get("agora_init_timeout", 60)
        voice = VoiceClient(agora_app_id, oopz_uid=OOPZ_CONFIG.get("person_uid", ""), init_timeout=init_timeout)
        if voice.available:
            logger.info("Agora 语音频道已启用（浏览器模式）")
            atexit.register(voice.destroy)
        else:
            logger.warning("Agora 语音频道初始化失败，音乐推流功能不可用")
            voice = None

    handler = CommandHandler(sender, voice_client=voice)

    threading.Thread(target=handler.music.auto_play_monitor, daemon=True).start()
    handler.music.start_web_command_listener()
    logger.info("自动播放监控已启动")

    from config import WEB_PLAYER_CONFIG
    web_host = WEB_PLAYER_CONFIG.get("host", "0.0.0.0")
    web_port = WEB_PLAYER_CONFIG.get("port", 8080)
    threading.Thread(target=run_web_player, kwargs={"host": web_host, "port": web_port}, daemon=True).start()
    logger.info("Web 歌词播放器已启动: http://%s:%s (IPv4)", web_host, web_port)

    client = OopzClient(
        on_chat_message=handler.handle,
        on_other_event=_notifier_ws,
    )
    logger.info("WebSocket 客户端启动中...")

    try:
        client.start()
    except KeyboardInterrupt:
        logger.info("收到退出信号，正在关闭...")
        client.stop()
    finally:
        _terminate_netease_proc(timeout=5)

    logger.info("Oopz Bot 已停止")


if __name__ == "__main__":
    main()
