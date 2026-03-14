"""插件运维结果模型。"""

from dataclasses import dataclass
from enum import StrEnum


class PluginOperationCode(StrEnum):
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
    LOAD_FAILED = "load_failed"


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
