"""
插件加载器：从 plugins 目录发现、加载、卸载扩展

- 发现：扫描目录下 .py，排除 _ 开头
- 加载：import 模块，查找 BotModule 子类并实例化，加载 config/plugins/<name>.json 后注入 on_load
- 卸载：从注册表移除并调用 on_unload（仅允许非内置模块）
"""

import os
import sys
import json
import importlib.util
from typing import Any, Optional

# 插件配置目录（项目根下）
DEFAULT_PLUGIN_CONFIG_DIR = "config/plugins"

from logger_config import get_logger
from plugin_base import BotModule
from plugin_registry import PluginRegistry

logger = get_logger("PluginLoader")

# 项目根目录（src 的上一级）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC_DIR = os.path.join(_PROJECT_ROOT, "src")


def _ensure_src_on_path() -> None:
    if _SRC_DIR not in sys.path:
        sys.path.insert(0, _SRC_DIR)


def load_plugin_config(
    plugin_name: str,
    config_dir: str = DEFAULT_PLUGIN_CONFIG_DIR,
) -> dict:
    """
    读取插件配置文件。路径: <项目根>/config/plugins/<plugin_name>.json
    文件不存在或非合法 JSON 时返回 {}，不抛异常。
    """
    path = os.path.join(_PROJECT_ROOT, config_dir, f"{plugin_name}.json")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            out = json.load(f)
            return out if isinstance(out, dict) else {}
    except Exception as e:
        logger.warning("PluginLoader: 读取配置 %s 失败: %s", path, e)
        return {}


def get_plugin_config(
    plugin_name: str,
    config_dir: str = DEFAULT_PLUGIN_CONFIG_DIR,
) -> dict:
    """
    运行时按插件名读取配置（每次从磁盘读取，便于热更新）。
    插件内可调用此函数重载配置。
    """
    return load_plugin_config(plugin_name, config_dir)


def _find_module_class(module) -> Optional[type]:
    """在模块中查找 BotModule 的子类（排除 BotModule 自身）。"""
    for attr_name in dir(module):
        try:
            obj = getattr(module, attr_name)
            if (
                isinstance(obj, type)
                and issubclass(obj, BotModule)
                and obj is not BotModule
            ):
                return obj
        except (TypeError, AttributeError):
            continue
    return None


def discover_plugins(plugins_dir: str) -> list[str]:
    """发现目录下可加载的插件名（.py 文件名去掉后缀，排除 _ 开头）。"""
    path = os.path.join(_PROJECT_ROOT, plugins_dir)
    if not os.path.isdir(path):
        return []
    names = []
    for name in sorted(os.listdir(path)):
        if name.startswith("_") or not name.endswith(".py"):
            continue
        if os.path.isfile(os.path.join(path, name)):
            names.append(name[:-3])
    return names


def load_plugin(
    registry: PluginRegistry,
    plugin_name: str,
    plugins_dir: str = "plugins",
    handler: Any = None,
) -> tuple[bool, str]:
    """
    加载单个插件并注册。
    返回 (成功, 消息)。
    """
    _ensure_src_on_path()
    path = os.path.join(_PROJECT_ROOT, plugins_dir)
    filepath = os.path.join(path, f"{plugin_name}.py")
    if not os.path.isfile(filepath):
        return False, f"插件不存在: {plugin_name}"

    if registry.get(plugin_name):
        return False, f"插件已加载: {plugin_name}"

    try:
        spec = importlib.util.spec_from_file_location(
            f"plugins.{plugin_name}",
            filepath,
        )
        if not spec or not spec.loader:
            return False, f"无法创建模块 spec: {plugin_name}"
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
    except Exception as e:
        logger.exception("PluginLoader: 加载 %s 失败", plugin_name)
        return False, f"加载失败: {e!s}"

    cls = _find_module_class(mod)
    if not cls:
        # 若未找到 BotModule 子类，移除已注入的模块，避免残留
        sys.modules.pop(spec.name, None)
        return False, f"插件未定义 BotModule 子类: {plugin_name}"

    try:
        instance = cls()
        if not registry.register(instance, builtin=False):
            sys.modules.pop(spec.name, None)
            return False, f"注册失败: {plugin_name}"
        config = load_plugin_config(plugin_name)
        if handler:
            try:
                instance.on_load(handler, config)
            except Exception as e:
                logger.exception("PluginLoader: %s on_load 异常", plugin_name)
                registry.unregister(plugin_name)
                # on_load 失败时清理已加载模块，避免后续重载命中脏缓存
                sys.modules.pop(spec.name, None)
                for mod_name in tuple(getattr(instance, "private_modules", ()) or ()):
                    if isinstance(mod_name, str) and mod_name:
                        sys.modules.pop(mod_name, None)
                return False, f"on_load 失败: {e!s}"
        return True, f"已加载: {plugin_name}"
    except Exception as e:
        logger.exception("PluginLoader: 实例化 %s 失败", plugin_name)
        sys.modules.pop(spec.name, None)
        return False, f"实例化失败: {e!s}"


def unload_plugin(
    registry: PluginRegistry,
    plugin_name: str,
    handler: Any = None,
) -> tuple[bool, str]:
    """
    卸载插件（仅允许非内置）。
    返回 (成功, 消息)。
    """
    if registry.is_builtin(plugin_name):
        return False, f"内置模块不可卸载: {plugin_name}"
    module = registry.get(plugin_name)
    if not module:
        return False, f"插件未加载: {plugin_name}"
    private_modules = tuple(getattr(module, "private_modules", ()) or ())
    registry.unregister(plugin_name, handler)
    # 从 sys.modules 移除，便于下次「加载插件」时重新 import
    spec_name = f"plugins.{plugin_name}"
    sys.modules.pop(spec_name, None)
    # 精确清理该插件声明的私有模块缓存，避免误删其它插件
    for mod_name in private_modules:
        if isinstance(mod_name, str) and mod_name:
            sys.modules.pop(mod_name, None)
    return True, f"已卸载: {plugin_name}"


def load_plugins_dir(
    registry: PluginRegistry,
    plugins_dir: str = "plugins",
    handler: Any = None,
) -> list[str]:
    """
    扫描目录并加载所有可加载插件。
    返回成功加载的插件名列表。
    """
    names = discover_plugins(plugins_dir)
    loaded = []
    for name in names:
        ok, msg = load_plugin(registry, name, plugins_dir, handler)
        if ok:
            loaded.append(name)
        else:
            logger.debug("PluginLoader: 跳过 %s: %s", name, msg)
    return loaded
