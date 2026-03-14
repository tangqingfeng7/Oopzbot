from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from plugin_base import BotModule

from .loader import discover_plugins
from .module_tools import build_plugin_instance


def build_plugin_config_example(module: BotModule) -> dict:
    """基于插件配置规范生成示例配置。"""
    return module.config_spec.to_example()


def build_plugin_config_schema(module: BotModule) -> dict:
    """基于插件配置规范生成结构描述。"""
    return module.config_spec.to_schema(module.metadata.name)


def write_plugin_config_assets(module: BotModule, output_dir: str | Path) -> tuple[Path, Path]:
    """把示例配置和结构描述写入目标目录。"""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    plugin_name = module.metadata.name
    example_path = output_path / f"{plugin_name}.example.json"
    schema_path = output_path / f"{plugin_name}.schema.json"

    example_path.write_text(
        json.dumps(build_plugin_config_example(module), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    schema_path.write_text(
        json.dumps(build_plugin_config_schema(module), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return example_path, schema_path


def export_plugin_config_assets(
    plugin_names: Iterable[str] | None = None,
    *,
    output_dir: str | Path = "config/plugins",
    plugins_dir: str = "plugins",
) -> list[tuple[str, Path, Path]]:
    """按插件名批量导出配置资产。"""
    names = list(dict.fromkeys(plugin_names or discover_plugins(plugins_dir)))
    exported: list[tuple[str, Path, Path]] = []
    for plugin_name in names:
        plugin = build_plugin_instance(plugin_name, plugins_dir)
        example_path, schema_path = write_plugin_config_assets(plugin, output_dir)
        exported.append((plugin_name, example_path, schema_path))
    return exported
