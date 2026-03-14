"""插件配置领域模型与配置规范。"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any


class PluginConfig(Mapping[str, Any]):
    """插件配置的只读视图。"""

    __slots__ = ("plugin_name", "values", "path", "exists")

    def __init__(
        self,
        plugin_name: str,
        values: Mapping[str, Any] | None,
        path: str,
        exists: bool,
    ) -> None:
        self.plugin_name = plugin_name
        self.values = dict(values) if values else {}
        self.path = path
        self.exists = exists

    def __getitem__(self, key: str) -> Any:
        return self.values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.values)

    def __len__(self) -> int:
        return len(self.values)

    def __bool__(self) -> bool:
        return bool(self.values)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, PluginConfig):
            return (
                self.plugin_name == other.plugin_name
                and self.path == other.path
                and self.exists == other.exists
                and self.values == other.values
            )
        if isinstance(other, Mapping):
            return self.values == dict(other)
        return False

    def __repr__(self) -> str:
        return (
            "PluginConfig("
            f"plugin_name={self.plugin_name!r}, "
            f"values={self.values!r}, "
            f"path={self.path!r}, "
            f"exists={self.exists!r})"
        )

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    def copy(self) -> dict[str, Any]:
        """返回一个可变字典副本，兼容旧插件写法。"""
        return dict(self.values)

    def to_dict(self) -> dict[str, Any]:
        """显式导出原始配置字典。"""
        return self.copy()

    @classmethod
    def empty(cls, plugin_name: str, path: str) -> "PluginConfig":
        return cls(plugin_name=plugin_name, values={}, path=path, exists=False)

    @classmethod
    def from_mapping(
        cls,
        plugin_name: str,
        values: Mapping[str, Any] | None,
        path: str,
        *,
        exists: bool,
    ) -> "PluginConfig":
        return cls(
            plugin_name=plugin_name,
            values=values,
            path=path,
            exists=exists,
        )


@dataclass(frozen=True)
class PluginConfigField:
    """单个插件配置字段定义。"""

    name: str
    default: Any = None
    required: bool = False
    cast: Callable[[Any], Any] | None = None
    choices: tuple[Any, ...] = ()
    validator: Callable[[Any], bool] | None = None
    description: str = ""
    constraint: str = ""
    example: Any = None


class PluginConfigValidationError(ValueError):
    """插件配置校验失败。"""


class PluginConfigSpec:
    """插件配置规范。"""

    def __init__(self, fields: tuple[PluginConfigField, ...] = ()) -> None:
        self.fields = fields

    def apply(self, config: PluginConfig) -> PluginConfig:
        """执行默认值合并、类型转换和基础校验。"""
        if not self.fields:
            return config

        values = config.copy()
        for field in self.fields:
            if field.name not in values and field.default is not None:
                values[field.name] = _clone_value(field.default)

            if field.name in values and not _is_missing_value(values[field.name]):
                values[field.name] = _apply_cast(field, values[field.name])
                _validate_choices(field, values[field.name])
                _validate_custom(field, values[field.name])

        missing = [
            field.name
            for field in self.fields
            if field.required and _is_missing_value(values.get(field.name))
        ]
        if missing:
            joined = ", ".join(missing)
            raise PluginConfigValidationError(f"缺少必填配置: {joined}")

        return PluginConfig.from_mapping(
            config.plugin_name,
            values,
            config.path,
            exists=config.exists,
        )

    def to_example(self) -> dict[str, Any]:
        """生成示例配置。"""
        example: dict[str, Any] = {}
        for field in self.fields:
            if field.example is not None:
                example[field.name] = _clone_value(field.example)
            elif field.default is not None:
                example[field.name] = _clone_value(field.default)
        return example

    def to_schema(self, plugin_name: str) -> dict[str, Any]:
        """导出配置结构描述。"""
        return {
            "plugin_name": plugin_name,
            "fields": [self._field_to_schema(field) for field in self.fields],
        }

    def _field_to_schema(self, field: PluginConfigField) -> dict[str, Any]:
        item = {
            "name": field.name,
            "type": _infer_field_type(field),
            "required": field.required,
        }
        if field.description:
            item["description"] = field.description
        if field.constraint:
            item["constraint"] = field.constraint
        if field.default is not None:
            item["default"] = _clone_value(field.default)
        if field.example is not None:
            item["example"] = _clone_value(field.example)
        elif field.default is not None:
            item["example"] = _clone_value(field.default)
        if field.choices:
            item["choices"] = list(field.choices)
        return item

    @classmethod
    def empty(cls) -> "PluginConfigSpec":
        return cls(())


def parse_bool(value: Any) -> bool:
    """把常见文本值转换为布尔值。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    raise PluginConfigValidationError(f"无法解析布尔值: {value!r}")


def parse_int(value: Any) -> int:
    """把值转换为整数。"""
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise PluginConfigValidationError(f"无法解析整数值: {value!r}") from exc


def parse_float(value: Any) -> float:
    """把值转换为浮点数。"""
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise PluginConfigValidationError(f"无法解析浮点值: {value!r}") from exc


def parse_string_list(value: Any) -> list[str]:
    """把值转换为字符串列表。"""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [item.strip() for item in text.split(",") if item.strip()]


def validate_range(min_value: int | float, max_value: int | float) -> Callable[[Any], bool]:
    """返回数值范围校验器。"""

    def _validator(value: Any) -> bool:
        return min_value <= value <= max_value

    return _validator


def validate_min(min_value: int | float) -> Callable[[Any], bool]:
    """返回最小值校验器。"""

    def _validator(value: Any) -> bool:
        return value >= min_value

    return _validator


def validate_hhmm(value: Any) -> bool:
    """校验 `HH:MM` 时间格式。"""
    text = str(value).strip()
    parts = text.split(":")
    if len(parts) != 2:
        return False
    hour, minute = parts
    if not hour.isdigit() or not minute.isdigit():
        return False
    hour_num = int(hour)
    minute_num = int(minute)
    return 0 <= hour_num <= 23 and 0 <= minute_num <= 59


def validate_http_url_list(value: Any) -> bool:
    """校验 HTTP/HTTPS URL 列表。"""
    if not isinstance(value, list):
        return False
    return all(
        isinstance(item, str) and item.startswith(("http://", "https://"))
        for item in value
    )


def _apply_cast(field: PluginConfigField, value: Any) -> Any:
    if field.cast is None:
        return value
    try:
        return field.cast(value)
    except PluginConfigValidationError:
        raise
    except Exception as exc:
        raise PluginConfigValidationError(
            f"字段 {field.name} 类型转换失败: {value!r}"
        ) from exc


def _validate_choices(field: PluginConfigField, value: Any) -> None:
    if field.choices and value not in field.choices:
        choices = ", ".join(str(item) for item in field.choices)
        raise PluginConfigValidationError(
            f"字段 {field.name} 不在允许范围内: {value!r}，可选值: {choices}"
        )


def _validate_custom(field: PluginConfigField, value: Any) -> None:
    if field.validator is not None and not field.validator(value):
        raise PluginConfigValidationError(f"字段 {field.name} 校验失败: {value!r}")


def _is_missing_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def _infer_field_type(field: PluginConfigField) -> str:
    if field.cast is parse_bool:
        return "boolean"
    if field.cast is parse_int:
        return "integer"
    if field.cast is parse_float:
        return "number"
    if field.cast is parse_string_list:
        return "string[]"

    sample = field.example if field.example is not None else field.default
    if isinstance(sample, bool):
        return "boolean"
    if isinstance(sample, int):
        return "integer"
    if isinstance(sample, float):
        return "number"
    if isinstance(sample, list):
        return "list"
    return "string"


def _clone_value(value: Any) -> Any:
    if isinstance(value, list):
        return list(value)
    if isinstance(value, dict):
        return dict(value)
    return value
