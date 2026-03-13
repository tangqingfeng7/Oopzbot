"""后台服务启动编排。"""

import threading

from config import WEB_PLAYER_CONFIG
from logger_config import setup_logger
from web_player import run_server as run_web_player

from app.lifecycle.context import AppContext

logger = setup_logger("BackgroundServices")


class BackgroundServiceRunner:
    """负责启动命令链路依赖的后台线程与监听器。"""

    def start(self, context: AppContext) -> None:
        self._start_music_services(context)
        self._start_web_player()

    def _start_music_services(self, context: AppContext) -> None:
        music = context.handler.infrastructure.music
        threading.Thread(
            target=music.auto_play_monitor,
            daemon=True,
        ).start()
        music.start_web_command_listener()
        logger.info("自动播放监控已启动。")

    def _start_web_player(self) -> None:
        web_host = WEB_PLAYER_CONFIG.get("host", "0.0.0.0")
        web_port = WEB_PLAYER_CONFIG.get("port", 8080)
        threading.Thread(
            target=run_web_player,
            kwargs={"host": web_host, "port": web_port},
            daemon=True,
        ).start()
        logger.info("Web 播放器已启动: http://%s:%s", web_host, web_port)
        logger.info("WebSocket 客户端启动中...")
