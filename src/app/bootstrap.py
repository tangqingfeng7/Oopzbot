from typing import Optional

from logger_config import setup_logger

from config import NETEASE_CLOUD
from app.lifecycle import (
    AppContext,
    AppContextBuilder,
    BackgroundServiceRunner,
    NeteaseApiRuntime,
    ShutdownCoordinator,
    StartupResourceBuilder,
    VoiceRuntimeBuilder,
)

logger = setup_logger("Main")


class BotApplication:
    """负责组装并运行 Bot 应用。"""

    def __init__(self) -> None:
        enable_music = NETEASE_CLOUD.get("enable", True)
        self._netease_runtime = NeteaseApiRuntime() if enable_music else None
        self._background_services = BackgroundServiceRunner()
        self._context_builder = AppContextBuilder()
        self._shutdown = ShutdownCoordinator()
        self._startup_resources = StartupResourceBuilder()
        self._voice_runtime = VoiceRuntimeBuilder() if enable_music else None
        self._context: Optional[AppContext] = None

    def run(self) -> None:
        logger.info("=" * 50)
        logger.info("Oopz Bot 正在启动...")
        logger.info("=" * 50)

        if self._netease_runtime:
            self._netease_runtime.start()
        else:
            logger.info("音乐功能已禁用，跳过启动网易云音乐 API 服务。")
            
        self._context = self._build_context()
        self._background_services.start(self._context, enable_music=self._netease_runtime is not None)

        try:
            self._context.client.start()
        except KeyboardInterrupt:
            logger.info("收到退出信号，正在停止...")
            self._context.client.stop()
        finally:
            self.stop()

        logger.info("Oopz Bot 已停止。")

    def stop(self) -> None:
        self._shutdown.stop(self._context, self._netease_runtime)

    def _build_context(self) -> AppContext:
        resources = self._startup_resources.build()
        voice = self._voice_runtime.build() if self._voice_runtime else None
        return self._context_builder.build(resources.sender, voice=voice)
