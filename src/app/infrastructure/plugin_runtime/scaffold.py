"""插件脚手架生成。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from domain.plugins.plugin_name import normalize_plugin_name

from .config_assets import write_plugin_config_assets
from .module_tools import build_plugin_instance


@dataclass(frozen=True)
class PluginScaffoldResult:
    """插件脚手架生成结果。"""

    plugin_name: str
    module_path: Path
    example_path: Path
    schema_path: Path


def create_plugin_scaffold(
    plugin_name: str,
    *,
    project_root: str | Path,
    description: str = "",
    author: str = "",
    mention_prefix: str | None = None,
    slash_command: str | None = None,
    is_public_command: bool = True,
    force: bool = False,
) -> PluginScaffoldResult:
    """创建插件骨架与配置资产。"""
    normalized_name = normalize_plugin_name(plugin_name)
    if not normalized_name:
        raise ValueError(f"非法插件名: {plugin_name}")

    root_path = Path(project_root)
    plugins_dir = root_path / "plugins"
    config_dir = root_path / "config" / "plugins"
    module_path = plugins_dir / f"{normalized_name}.py"

    if module_path.exists() and not force:
        raise FileExistsError(f"插件文件已存在: {module_path}")

    plugins_dir.mkdir(parents=True, exist_ok=True)
    config_dir.mkdir(parents=True, exist_ok=True)

    module_path.write_text(
        _render_plugin_template(
            plugin_name=normalized_name,
            class_name=_build_plugin_class_name(normalized_name),
            description=description or f"{normalized_name} 插件",
            author=author,
            mention_prefix=mention_prefix or normalized_name,
            slash_command=slash_command or f"/{normalized_name}",
            is_public_command=is_public_command,
        ),
        encoding="utf-8",
    )

    plugin = build_plugin_instance(
        normalized_name,
        project_root=str(root_path),
    )
    example_path, schema_path = write_plugin_config_assets(plugin, config_dir)
    return PluginScaffoldResult(
        plugin_name=normalized_name,
        module_path=module_path,
        example_path=example_path,
        schema_path=schema_path,
    )


def _build_plugin_class_name(plugin_name: str) -> str:
    parts = [part.capitalize() for part in plugin_name.split("_") if part]
    if parts and parts[-1] == "Plugin":
        return "".join(parts)
    return "".join(parts) + "Plugin"


def _render_plugin_template(
    *,
    plugin_name: str,
    class_name: str,
    description: str,
    author: str,
    mention_prefix: str,
    slash_command: str,
    is_public_command: bool,
) -> str:
    return f'''"""插件脚手架：{plugin_name}。"""

from __future__ import annotations

from plugin_base import (
    BotModule,
    PluginCommandCapabilities,
    PluginConfig,
    PluginConfigField,
    PluginConfigSpec,
    PluginMetadata,
)


class {class_name}(BotModule):
    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="{plugin_name}",
            description="{description}",
            version="0.1.0",
            author="{author}",
        )

    @property
    def command_capabilities(self) -> PluginCommandCapabilities:
        return PluginCommandCapabilities(
            mention_prefixes=("{mention_prefix}",),
            slash_commands=("{slash_command.lower()}",),
            is_public_command={is_public_command},
        )

    @property
    def config_spec(self) -> PluginConfigSpec:
        return PluginConfigSpec(
            (
                PluginConfigField(
                    "enabled",
                    default=False,
                    description="是否启用插件",
                    example=False,
                ),
            )
        )

    def on_load(self, handler, config: PluginConfig | None = None) -> None:
        self._handler = handler
        self._config = (config or {{}}).copy()

    def handle_mention(self, text, channel, area, user, handler) -> bool:
        return False

    def handle_slash(self, command, subcommand, arg, channel, area, user, handler) -> bool:
        return False
'''
