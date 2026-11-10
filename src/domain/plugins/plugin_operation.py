from dataclasses import dataclass
from enum import Enum


class PluginOperationCode(str, Enum):
    """插件运维操作结果码。"""

    SUCCESS = "success"
    NOT_FOUND = "not_found"
    ALREADY_LOADED = "already_loaded"
    INVALID_SPEC = "invalid_spec"
    INVALID_MODULE = "invalid_module"
    REGISTER_FAILED = "register_failed"
    INVALID_CONFIG = "invalid_config"
    ON_LOAD_FAILED = "on_load_failed"
    INSTANTIATION_FAILED = "instantiation_failed"
    BUILTIN_FORBIDDEN = "builtin_forbidden"
    NOT_LOADED = "not_loaded"
    UNLOAD_FAILED = "unload_failed"
    LOAD_FAILED = "load_failed"

    def __str__(self) -> str:
        """保持 Python 3.10 下与字符串枚举一致的序列化语义。"""

        return self.value


@dataclass(frozen=True)
class PluginOperationResult:
    """插件运维操作结果。"""

    ok: bool
    message: str
    code: PluginOperationCode
    plugin_name: str = ""

    @classmethod
    def success(
        cls,
        message: str,
        plugin_name: str = "",
        code: PluginOperationCode = PluginOperationCode.SUCCESS,
    ) -> "PluginOperationResult":
        return cls(ok=True, message=message, code=code, plugin_name=plugin_name)

    @classmethod
    def failure(
        cls,
        message: str,
        plugin_name: str = "",
        code: PluginOperationCode = PluginOperationCode.LOAD_FAILED,
    ) -> "PluginOperationResult":
        return cls(ok=False, message=message, code=code, plugin_name=plugin_name)
