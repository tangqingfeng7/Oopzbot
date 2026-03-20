import signal
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

    def _install_signal_handlers(self) -> None:
        def _graceful_stop(signum, _frame):
            name = signal.Signals(signum).name
            logger.info("收到 %s，正在停止...", name)
            if self._context:
                self._context.client.stop()

        signal.signal(signal.SIGTERM, _graceful_stop)
        signal.signal(signal.SIGINT, _graceful_stop)

    def run(self) -> None:
        logger.info("=" * 50)
        logger.info("Oopz Bot 正在启动...")
        logger.info("=" * 50)

        self._install_signal_handlers()
        self._netease_runtime.start()
        self._context = self._build_context()
        self._background_services.start(self._context)

        try:
            self._context.client.start()
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

        logger.info("Oopz Bot 已停止。")

    def stop(self) -> None:
        self._shutdown.stop(self._context, self._netease_runtime)

    def _build_context(self) -> AppContext:
        resources = self._startup_resources.build()
        voice = self._voice_runtime.build()
        return self._context_builder.build(resources.sender, voice=voice)
