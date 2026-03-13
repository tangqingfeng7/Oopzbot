"""插件加载器。"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from domain.plugins.plugin_config import PluginConfig, PluginConfigValidationError
from domain.plugins.plugin_operation import PluginOperationCode, PluginOperationResult
from logger_config import get_logger

from .module_tools import (
    PROJECT_ROOT,
    discover_plugin_names,
    ensure_src_on_path,
    find_plugin_class,
    load_plugin_module,
    plugin_file_path,
)
from .registry import PluginRegistry

DEFAULT_PLUGIN_CONFIG_DIR = "config/plugins"

logger = get_logger("PluginLoader")
_PROJECT_ROOT = PROJECT_ROOT
_SRC_DIR = os.path.join(_PROJECT_ROOT, "src")


def _plugin_config_path(plugin_name: str, config_dir: str) -> str:
    return os.path.join(_PROJECT_ROOT, config_dir, f"{plugin_name}.json")


def load_plugin_config(
    plugin_name: str,
    config_dir: str = DEFAULT_PLUGIN_CONFIG_DIR,
) -> PluginConfig:
    """读取插件配置文件并返回显式配置对象。"""
    path = _plugin_config_path(plugin_name, config_dir)
    if not os.path.isfile(path):
        return PluginConfig.empty(plugin_name, path)

    try:
        with open(path, "r", encoding="utf-8") as file:
            raw = json.load(file)
    except Exception as exc:
        logger.warning("PluginLoader: 读取配置 %s 失败: %s", path, exc)
        return PluginConfig.empty(plugin_name, path)

    if not isinstance(raw, dict):
        logger.warning("PluginLoader: 配置文件不是对象结构: %s", path)
        return PluginConfig.empty(plugin_name, path)

    return PluginConfig.from_mapping(
        plugin_name,
        raw,
        path,
        exists=True,
    )


def get_plugin_config(
    plugin_name: str,
    config_dir: str = DEFAULT_PLUGIN_CONFIG_DIR,
) -> PluginConfig:
    """运行时按插件名重新读取配置。"""
    return load_plugin_config(plugin_name, config_dir)


def discover_plugins(plugins_dir: str) -> list[str]:
    """扫描目录中可加载的插件名。"""
    return discover_plugin_names(plugins_dir, _PROJECT_ROOT)


def load_plugin(
    registry: PluginRegistry,
    plugin_name: str,
    plugins_dir: str = "plugins",
    handler: Any = None,
) -> PluginOperationResult:
    """加载单个插件并注册到注册表。"""
    ensure_src_on_path(_PROJECT_ROOT)
    filepath = plugin_file_path(plugin_name, plugins_dir, _PROJECT_ROOT)
    if not os.path.isfile(filepath):
        return PluginOperationResult.failure(
            f"插件不存在: {plugin_name}",
            plugin_name=plugin_name,
            code=PluginOperationCode.NOT_FOUND,
        )

    if registry.get(plugin_name):
        return PluginOperationResult.failure(
            f"插件已加载: {plugin_name}",
            plugin_name=plugin_name,
            code=PluginOperationCode.ALREADY_LOADED,
        )

    try:
        module, module_name = load_plugin_module(plugin_name, plugins_dir, _PROJECT_ROOT)
    except ImportError:
        return PluginOperationResult.failure(
            f"无法创建模块 spec: {plugin_name}",
            plugin_name=plugin_name,
            code=PluginOperationCode.INVALID_SPEC,
        )
    except Exception as exc:
        logger.exception("PluginLoader: 加载 %s 失败", plugin_name)
        return PluginOperationResult.failure(
            f"加载失败: {exc!s}",
            plugin_name=plugin_name,
            code=PluginOperationCode.LOAD_FAILED,
        )

    plugin_class = find_plugin_class(module)
    if not plugin_class:
        sys.modules.pop(module_name, None)
        return PluginOperationResult.failure(
            f"插件未定义 BotModule 子类: {plugin_name}",
            plugin_name=plugin_name,
            code=PluginOperationCode.INVALID_MODULE,
        )

    try:
        instance = plugin_class()
        config = instance.config_spec.apply(load_plugin_config(plugin_name))
        if not registry.register(instance, builtin=False):
            sys.modules.pop(module_name, None)
            return PluginOperationResult.failure(
                f"注册失败: {plugin_name}",
                plugin_name=plugin_name,
                code=PluginOperationCode.REGISTER_FAILED,
            )
        if handler:
            try:
                instance.on_load(handler, config)
            except PluginConfigValidationError as exc:
                logger.warning("PluginLoader: %s 配置校验失败: %s", plugin_name, exc)
                registry.unregister(plugin_name)
                sys.modules.pop(module_name, None)
                for mod_name in tuple(getattr(instance, "private_modules", ()) or ()):
                    if isinstance(mod_name, str) and mod_name:
                        sys.modules.pop(mod_name, None)
                return PluginOperationResult.failure(
                    f"插件配置无效: {exc}",
                    plugin_name=plugin_name,
                    code=PluginOperationCode.INVALID_CONFIG,
                )
            except Exception as exc:
                logger.exception("PluginLoader: %s on_load 异常", plugin_name)
                registry.unregister(plugin_name)
                sys.modules.pop(module_name, None)
                for mod_name in tuple(getattr(instance, "private_modules", ()) or ()):
                    if isinstance(mod_name, str) and mod_name:
                        sys.modules.pop(mod_name, None)
                return PluginOperationResult.failure(
                    f"on_load 失败: {exc!s}",
                    plugin_name=plugin_name,
                    code=PluginOperationCode.ON_LOAD_FAILED,
                )

        return PluginOperationResult.success(
            f"已加载: {plugin_name}",
            plugin_name=plugin_name,
        )
    except PluginConfigValidationError as exc:
        logger.warning("PluginLoader: %s 配置校验失败: %s", plugin_name, exc)
        sys.modules.pop(module_name, None)
        return PluginOperationResult.failure(
            f"插件配置无效: {exc}",
            plugin_name=plugin_name,
            code=PluginOperationCode.INVALID_CONFIG,
        )
    except Exception as exc:
        logger.exception("PluginLoader: 实例化 %s 失败", plugin_name)
        sys.modules.pop(module_name, None)
        return PluginOperationResult.failure(
            f"实例化失败: {exc!s}",
            plugin_name=plugin_name,
            code=PluginOperationCode.INSTANTIATION_FAILED,
        )


def unload_plugin(
    registry: PluginRegistry,
    plugin_name: str,
    handler: Any = None,
) -> PluginOperationResult:
    """卸载插件，仅允许卸载非内置插件。"""
    if registry.is_builtin(plugin_name):
        return PluginOperationResult.failure(
            f"内置模块不可卸载: {plugin_name}",
            plugin_name=plugin_name,
            code=PluginOperationCode.BUILTIN_FORBIDDEN,
        )

    module = registry.get(plugin_name)
    if not module:
        return PluginOperationResult.failure(
            f"插件未加载: {plugin_name}",
            plugin_name=plugin_name,
            code=PluginOperationCode.NOT_LOADED,
        )

    private_modules = tuple(getattr(module, "private_modules", ()) or ())
    registry.unregister(plugin_name, handler)
    sys.modules.pop(f"plugins.{plugin_name}", None)
    for mod_name in private_modules:
        if isinstance(mod_name, str) and mod_name:
            sys.modules.pop(mod_name, None)

    return PluginOperationResult.success(
        f"已卸载: {plugin_name}",
        plugin_name=plugin_name,
    )


def load_plugins_dir(
    registry: PluginRegistry,
    plugins_dir: str = "plugins",
    handler: Any = None,
) -> list[str]:
    """扫描目录并加载所有可用插件。"""
    loaded: list[str] = []
    for name in discover_plugins(plugins_dir):
        result = load_plugin(registry, name, plugins_dir, handler)
        if result.ok:
            loaded.append(name)
        else:
            logger.debug("PluginLoader: 跳过 %s: %s", name, result.message)
    return loaded
