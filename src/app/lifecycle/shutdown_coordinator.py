from logger_config import setup_logger

from app.lifecycle.context import AppContext
from app.lifecycle.netease_api_runtime import NeteaseApiRuntime

logger = setup_logger("ShutdownCoordinator")


class ShutdownCoordinator:
    """负责关闭应用运行时资源。"""

    def stop(self, context: AppContext | None, netease_runtime: NeteaseApiRuntime) -> None:
        netease_runtime.stop()

        if context:
            try:
                scheduler = context.handler.services.scheduler
                scheduler.scheduled.stop()
                scheduler.reminder.stop()
            except Exception as exc:
                logger.warning("停止定时服务时出现异常: %s", exc)

        if not context or not context.voice:
            return

        try:
            context.voice.destroy()
        except Exception as exc:
            logger.warning("销毁语音客户端时出现异常: %s", exc)
