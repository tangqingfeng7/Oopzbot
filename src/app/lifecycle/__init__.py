"""应用生命周期模块导出。"""

from .background_services import BackgroundServiceRunner
from .context import AppContext
from .context_builder import AppContextBuilder
from .netease_api_runtime import NeteaseApiRuntime
from .shutdown_coordinator import ShutdownCoordinator
from .startup_resources import StartupResourceBuilder, StartupResources
from .voice_runtime import VoiceRuntimeBuilder

__all__ = [
    "AppContext",
    "AppContextBuilder",
    "BackgroundServiceRunner",
    "NeteaseApiRuntime",
    "ShutdownCoordinator",
    "StartupResourceBuilder",
    "StartupResources",
    "VoiceRuntimeBuilder",
]
