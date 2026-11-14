from __future__ import annotations

import inspect
import json
import os
import sys
from typing import Any

from core.logger_config import get_logger
from domain.plugins.plugin_config import PluginConfig, PluginConfigValidationError
from domain.plugins.plugin_operation import PluginOperationCode, PluginOperationResult

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


def plugin_config_path(plugin_name: str, config_dir: str = DEFAULT_PLUGIN_CONFIG_DIR) -> str:
    return os.path.join(_PROJECT_ROOT, config_dir, plugin_name, "config.json")


def plugin_config_schema_path(plugin_name: str, config_dir: str = DEFAULT_PLUGIN_CONFIG_DIR) -> str:
    return os.path.join(_PROJECT_ROOT, config_dir, plugin_name, "schema.json")


def load_plugin_config(
    plugin_name: str,
    config_dir: str = DEFAULT_PLUGIN_CONFIG_DIR,
) -> PluginConfig:
    """读取插件配置文件并返回显式配置对象。"""
    path = plugin_config_path(plugin_name, config_dir)
    if not os.path.isfile(path):
        return PluginConfig.empty(plugin_name, path)

    try:
        with open(path, encoding="utf-8") as file:
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


def _validate_async_plugin(plugin_class: type) -> str | None:
    """同步插件会阻塞主事件循环，因此在实例化前明确拒绝。"""
    required = (
        "handle_mention", "handle_slash", "handle_message",
        "on_load", "on_config_reload", "on_disable", "on_unload",
    )
    invalid = [name for name in required if not inspect.iscoroutinefunction(getattr(plugin_class, name, None))]
    if invalid:
        return "插件仅支持 async def，以下方法仍为同步实现: " + ", ".join(invalid)
    return None


async def load_plugin(
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
    except ImportError as exc:
        logger.warning("PluginLoader: 模块 spec 无效 %s: %s", plugin_name, exc)
        return PluginOperationResult.failure(
            f"无法创建模块 spec: {plugin_name}",
            plugin_name=plugin_name,
            code=PluginOperationCode.INVALID_SPEC,
        )
    except FileNotFoundError:
        return PluginOperationResult.failure(
            f"插件不存在: {plugin_name}",
            plugin_name=plugin_name,
            code=PluginOperationCode.NOT_FOUND,
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

    async_error = _validate_async_plugin(plugin_class)
    if async_error:
        sys.modules.pop(module_name, None)
        return PluginOperationResult.failure(
            async_error,
            plugin_name=plugin_name,
            code=PluginOperationCode.INVALID_MODULE,
        )

    try:
        instance = plugin_class()
        config = instance.config_spec.apply(load_plugin_config(plugin_name))
        if not await registry.register(instance, builtin=False):
            sys.modules.pop(module_name, None)
            return PluginOperationResult.failure(
                f"注册失败: {plugin_name}",
                plugin_name=plugin_name,
                code=PluginOperationCode.REGISTER_FAILED,
            )
        if handler:
            try:
                await instance.on_load(handler, config)
            except PluginConfigValidationError as exc:
                logger.warning("PluginLoader: %s 配置校验失败: %s", plugin_name, exc)
                await registry.unregister(plugin_name)
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
                await registry.unregister(plugin_name)
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


async def reload_plugin_config(
    registry: PluginRegistry,
    plugin_name: str,
    handler: Any = None,
) -> PluginOperationResult:
    """重新读取插件配置并通知插件实例，不重新加载代码。"""
    module = registry.get(plugin_name)
    if not module:
        return PluginOperationResult.failure(
            f"插件未加载: {plugin_name}",
            plugin_name=plugin_name,
            code=PluginOperationCode.NOT_LOADED,
        )

    try:
        config = module.config_spec.apply(load_plugin_config(plugin_name))
    except PluginConfigValidationError as exc:
        return PluginOperationResult.failure(
            f"配置校验失败: {exc}",
            plugin_name=plugin_name,
            code=PluginOperationCode.INVALID_CONFIG,
        )
    except Exception as exc:
        logger.exception("PluginLoader: %s 读取配置失败", plugin_name)
        return PluginOperationResult.failure(
            f"读取配置失败: {exc!s}",
            plugin_name=plugin_name,
            code=PluginOperationCode.LOAD_FAILED,
        )

    try:
        await module.on_config_reload(handler, config)
    except PluginConfigValidationError as exc:
        return PluginOperationResult.failure(
            f"热重载配置校验失败: {exc}",
            plugin_name=plugin_name,
            code=PluginOperationCode.INVALID_CONFIG,
        )
    except Exception as exc:
        logger.exception("PluginLoader: %s on_config_reload 异常", plugin_name)
        return PluginOperationResult.failure(
            f"热重载失败: {exc!s}",
            plugin_name=plugin_name,
            code=PluginOperationCode.ON_LOAD_FAILED,
        )

    logger.info("插件配置已热重载: %s", plugin_name)
    return PluginOperationResult.success(
        f"已重载配置: {plugin_name}",
        plugin_name=plugin_name,
    )


async def unload_plugin(
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

    try:
        await module.on_disable()
    except Exception as exc:
        logger.warning("PluginLoader: %s on_disable 异常: %s", plugin_name, exc)
        return PluginOperationResult.failure(
            f"卸载失败: {exc}",
            plugin_name=plugin_name,
            code=PluginOperationCode.UNLOAD_FAILED,
        )

    private_modules = tuple(getattr(module, "private_modules", ()) or ())
    await registry.unregister(plugin_name, handler)
    sys.modules.pop(f"plugins.{plugin_name}", None)
    for mod_name in private_modules:
        if isinstance(mod_name, str) and mod_name:
            sys.modules.pop(mod_name, None)

    return PluginOperationResult.success(
        f"已卸载: {plugin_name}",
        plugin_name=plugin_name,
    )


async def load_plugins_dir(
    registry: PluginRegistry,
    plugins_dir: str = "plugins",
    handler: Any = None,
) -> list[str]:
    """扫描目录并加载所有可用插件。"""
    loaded: list[str] = []
    for name in discover_plugins(plugins_dir):
        result = await load_plugin(registry, name, plugins_dir, handler)
        if result.ok:
            loaded.append(name)
        else:
            logger.debug("PluginLoader: 跳过 %s: %s", name, result.message)
    return loaded
