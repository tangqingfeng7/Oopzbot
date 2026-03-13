"""插件领域模型与规则。"""

from .plugin_config import (
    PluginConfig,
    PluginConfigField,
    PluginConfigSpec,
    PluginConfigValidationError,
    parse_bool,
    parse_float,
    parse_int,
    parse_string_list,
    validate_hhmm,
    validate_http_url_list,
    validate_min,
    validate_range,
)
from .plugin_name import normalize_plugin_name
from .plugin_operation import PluginOperationCode, PluginOperationResult

__all__ = [
    "PluginConfig",
    "PluginConfigField",
    "PluginConfigSpec",
    "PluginConfigValidationError",
    "parse_bool",
    "parse_float",
    "parse_int",
    "parse_string_list",
    "validate_hhmm",
    "validate_http_url_list",
    "validate_min",
    "validate_range",
    "normalize_plugin_name",
    "PluginOperationCode",
    "PluginOperationResult",
]
