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
        self._start_web_player(context)
        self._start_scheduler_services(context)

    def _start_music_services(self, context: AppContext) -> None:
        music = context.handler.infrastructure.music
        threading.Thread(
            target=music.auto_play_monitor,
            daemon=True,
        ).start()
        music.start_web_command_listener()
        logger.info("自动播放监控已启动。")

    def _start_web_player(self, context: AppContext) -> None:
        from web_player import set_sender
        set_sender(context.sender)
        self._warmup_members_cache(context.sender)
        web_host = WEB_PLAYER_CONFIG.get("host", "0.0.0.0")
        web_port = WEB_PLAYER_CONFIG.get("port", 8080)
        threading.Thread(
            target=run_web_player,
            kwargs={"host": web_host, "port": web_port},
            daemon=True,
        ).start()
        logger.info("Web 播放器已启动: http://%s:%s", web_host, web_port)
        logger.info("WebSocket 客户端启动中...")

    def _warmup_members_cache(self, sender) -> None:
        try:
            from config import OOPZ_CONFIG
            area = (OOPZ_CONFIG.get("default_area") or "").strip()
            if not area:
                areas = sender.get_joined_areas(quiet=True)
                if areas:
                    area = (areas[0].get("id") or "").strip()
            if not area:
                return
            result = sender.get_area_members(area=area, quiet=True)
            if "error" not in result:
                count = result.get("fetchedCount", 0)
                logger.info("成员缓存预热完成: %d 人", count)
            else:
                logger.debug("成员缓存预热失败: %s", result.get("error"))
        except Exception:
            pass

    def _start_scheduler_services(self, context: AppContext) -> None:
        try:
            scheduler = context.handler.services.scheduler
            scheduler.scheduled.start()
            scheduler.reminder.start()
        except Exception:
            logger.warning("定时消息/提醒服务启动失败", exc_info=True)
