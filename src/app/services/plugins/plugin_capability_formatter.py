from collections.abc import Mapping

from plugin_base import PluginDescriptor


def _read_value(item: Mapping[str, object] | PluginDescriptor, key: str, default: object = "") -> object:
    if isinstance(item, PluginDescriptor):
        return getattr(item, key, default)
    return item.get(key, default)


def format_plugin_command_summary(
    item: Mapping[str, object] | PluginDescriptor,
    *,
    mention_limit: int = 5,
    slash_limit: int = 5,
    empty_text: str = "（无命令声明）",
) -> str:
    """把插件能力字段格式化成统一展示文本。"""
    mentions = [
        prefix
        for prefix in (_read_value(item, "mention_prefixes", ()) or ())
        if isinstance(prefix, str) and prefix
    ]
    slashes = [
        command
        for command in (_read_value(item, "slash_commands", ()) or ())
        if isinstance(command, str) and command
    ]

    parts: list[str] = []
    if mentions:
        parts.append("@bot " + " / ".join(mentions[:mention_limit]))
    if slashes:
        parts.append(" / ".join(slashes[:slash_limit]))

    return "  |  ".join(parts) if parts else empty_text


def format_plugin_status_lines(item: Mapping[str, object] | PluginDescriptor) -> list[str]:
    """把插件状态和能力整理成统一的多行展示格式。"""
    tag = "内置" if _read_value(item, "builtin", False) else "扩展"
    description = str(_read_value(item, "description", "") or "").strip()
    suffix = f" - {description}" if description else ""
    lines = [f"  {_read_value(item, 'name', '')} [{tag}]{suffix}"]

    summary = format_plugin_command_summary(item)
    if summary != "（无命令声明）":
        lines.append(f"    命令: {summary}")

    return lines
