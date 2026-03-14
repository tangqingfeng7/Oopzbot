from typing import Optional

from logger_config import setup_logger

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
        self._netease_runtime = NeteaseApiRuntime()
        self._background_services = BackgroundServiceRunner()
        self._context_builder = AppContextBuilder()
        self._shutdown = ShutdownCoordinator()
        self._startup_resources = StartupResourceBuilder()
        self._voice_runtime = VoiceRuntimeBuilder()
        self._context: Optional[AppContext] = None

    def run(self) -> None:
        logger.info("=" * 50)
        logger.info("Oopz Bot 正在启动...")
        logger.info("=" * 50)

        self._netease_runtime.start()
        self._context = self._build_context()
        self._background_services.start(self._context)

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
        voice = self._voice_runtime.build()
        return self._context_builder.build(resources.sender, voice=voice)
