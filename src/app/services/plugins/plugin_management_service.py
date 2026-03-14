from typing import Optional

from domain.plugins.plugin_name import normalize_plugin_name
from app.services.runtime import CommandRuntimeView, plugins_of, sender_of

from .plugin_capability_formatter import format_plugin_status_lines
from .plugin_operation_formatter import (
    format_invalid_plugin_name_message,
    format_plugin_operation_message,
)


class PluginManagementService:
    """处理插件列表、加载和卸载。"""

    def __init__(self, runtime: CommandRuntimeView):
        self._runtime = runtime
        self._sender = sender_of(runtime)
        self._plugins = plugins_of(runtime)

    @staticmethod
    def normalize_plugin_name(raw_name: str) -> Optional[str]:
        """规范化插件名，仅允许字母数字下划线，兼容 .py 后缀。"""
        return normalize_plugin_name(raw_name)

    def show_plugin_list(self, channel: str, area: str) -> None:
        """展示插件状态：已加载与可加载列表。"""
        loaded = self._plugins.list_descriptors()
        discovered = self._plugins.discover()

        loaded_names = {item.name for item in loaded}
        available = [name for name in discovered if name not in loaded_names]

        lines = ["插件状态", "---"]
        lines.append(f"已加载: {len(loaded)} 个")
        if loaded:
            for item in loaded:
                lines.extend(format_plugin_status_lines(item))
        else:
            lines.append("  （无）")

        lines.append("")
        lines.append(f"可加载: {len(available)} 个")
        if available:
            lines.append("  " + ", ".join(available))
        else:
            lines.append("  （无）")

        lines.append("")
        lines.append("用法: /loadplugin <名>  /unloadplugin <名>")
        self._sender.send_message("\n".join(lines), channel=channel, area=area)

    def load(self, raw_name: str, channel: str, area: str) -> None:
        """动态加载插件。"""
        name = self.normalize_plugin_name(raw_name)
        if not name:
            self._sender.send_message(
                format_invalid_plugin_name_message(),
                channel=channel,
                area=area,
            )
            return
        result = self._plugins.load(name, handler=self._runtime.plugin_host)
        self._sender.send_message(
            format_plugin_operation_message(result),
            channel=channel,
            area=area,
        )

    def unload(self, raw_name: str, channel: str, area: str) -> None:
        """动态卸载插件。"""
        name = self.normalize_plugin_name(raw_name)
        if not name:
            self._sender.send_message(
                format_invalid_plugin_name_message(),
                channel=channel,
                area=area,
            )
            return
        result = self._plugins.unload(name, handler=self._runtime.plugin_host)
        self._sender.send_message(
            format_plugin_operation_message(result),
            channel=channel,
            area=area,
        )
