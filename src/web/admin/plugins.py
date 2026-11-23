import json
import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from domain.plugins.plugin_name import normalize_plugin_name
from web.admin.shared import _get_plugin_runtime, cfg

router = APIRouter()

# ---------------------------------------------------------------------------
# 插件管理 API
# ---------------------------------------------------------------------------

def _get_plugin_host():
    from web.web_player import get_plugin_host
    return get_plugin_host()


def _descriptor_to_dict(d) -> dict:
    return {
        "name": d.name,
        "description": d.description,
        "version": d.version,
        "author": d.author,
        "builtin": d.builtin,
        "mention_prefixes": list(d.mention_prefixes),
        "slash_commands": list(d.slash_commands),
        "is_public_command": d.is_public_command,
    }


@router.get("/admin/api/plugins")
def admin_plugins_list():
    runtime = _get_plugin_runtime()
    if not runtime:
        return JSONResponse({"ok": False, "error": "插件运行时未初始化"}, status_code=503)
    loaded = [_descriptor_to_dict(d) for d in runtime.list_descriptors()]
    loaded_names = {d["name"] for d in loaded}
    available = [n for n in runtime.discover() if n not in loaded_names]
    return JSONResponse({
        "ok": True,
        "loaded": loaded,
        "plugins": loaded,
        "available": available,
        "loaded_count": len(loaded),
        "available_count": len(available),
        "enabled_plugins": [item["name"] for item in loaded],
    })


def _validate_plugin_name(name: str) -> str | JSONResponse:
    normalized = normalize_plugin_name(name)
    if not normalized:
        return JSONResponse(
            {"ok": False, "error": "插件名不合法，仅支持字母/数字/下划线"},
            status_code=400,
        )
    return normalized


@router.post("/admin/api/plugins/{name}/load")
async def admin_plugin_load(name: str):
    plugin_name = _validate_plugin_name(name)
    if isinstance(plugin_name, JSONResponse):
        return plugin_name
    runtime = _get_plugin_runtime()
    host = _get_plugin_host()
    if not runtime:
        return JSONResponse({"ok": False, "error": "插件运行时未初始化"}, status_code=503)
    result = await runtime.load(plugin_name, handler=host)
    if not result.ok:
        return JSONResponse({"ok": False, "error": result.message, "code": result.code.value})
    return JSONResponse({"ok": True, "message": result.message})


@router.post("/admin/api/plugins/{name}/unload")
async def admin_plugin_unload(name: str):
    plugin_name = _validate_plugin_name(name)
    if isinstance(plugin_name, JSONResponse):
        return plugin_name
    runtime = _get_plugin_runtime()
    host = _get_plugin_host()
    if not runtime:
        return JSONResponse({"ok": False, "error": "插件运行时未初始化"}, status_code=503)
    result = await runtime.unload(plugin_name, handler=host)
    if not result.ok:
        return JSONResponse({"ok": False, "error": result.message, "code": result.code.value})
    return JSONResponse({"ok": True, "message": result.message})


@router.post("/admin/api/plugins/{name}/reload-config")
async def admin_plugin_reload_config(name: str):
    plugin_name = _validate_plugin_name(name)
    if isinstance(plugin_name, JSONResponse):
        return plugin_name
    runtime = _get_plugin_runtime()
    host = _get_plugin_host()
    if not runtime:
        return JSONResponse({"ok": False, "error": "插件运行时未初始化"}, status_code=503)
    result = await runtime.reload_config(plugin_name, handler=host)
    if not result.ok:
        return JSONResponse({"ok": False, "error": result.message, "code": result.code.value})
    return JSONResponse({"ok": True, "message": result.message})


@router.get("/admin/api/plugins/{name}/config")
def admin_plugin_config_get(name: str):
    plugin_name = _validate_plugin_name(name)
    if isinstance(plugin_name, JSONResponse):
        return plugin_name
    from app.infrastructure.plugin_runtime.loader import (
        DEFAULT_PLUGIN_CONFIG_DIR,
        plugin_config_path,
        plugin_config_schema_path,
    )
    config_dir = os.path.join(cfg.PROJECT_ROOT, DEFAULT_PLUGIN_CONFIG_DIR)
    config_path = plugin_config_path(plugin_name, DEFAULT_PLUGIN_CONFIG_DIR)
    config_data = {}
    if os.path.isfile(config_path):
        try:
            with open(config_path, encoding="utf-8") as f:
                config_data = json.load(f)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"读取配置失败: {exc}"})

    schema_path = plugin_config_schema_path(plugin_name, DEFAULT_PLUGIN_CONFIG_DIR)
    schema_data = None
    if os.path.isfile(schema_path):
        try:
            with open(schema_path, encoding="utf-8") as f:
                schema_data = json.load(f)
        except Exception:
            pass

    return JSONResponse({
        "ok": True,
        "name": plugin_name,
        "config": config_data,
        "config_exists": os.path.isfile(config_path),
        "config_path": os.path.relpath(config_path, config_dir),
        "schema": schema_data,
    })


@router.post("/admin/api/plugins/{name}/config")
async def admin_plugin_config_save(name: str, request: Request):
    plugin_name = _validate_plugin_name(name)
    if isinstance(plugin_name, JSONResponse):
        return plugin_name
    import asyncio

    from app.infrastructure.plugin_runtime.loader import (
        DEFAULT_PLUGIN_CONFIG_DIR,
        plugin_config_path,
    )
    from core.config_file_store import replace_text_files_atomically
    from domain.plugins import PluginConfig, PluginConfigValidationError

    config_path = plugin_config_path(plugin_name, DEFAULT_PLUGIN_CONFIG_DIR)

    try:
        body = await request.json()
        config_data = body.get("config", body) if isinstance(body, dict) else body
    except Exception as exc:
        return JSONResponse({"ok": False, "error": f"解析请求体失败: {exc}"}, status_code=400)

    if not isinstance(config_data, dict):
        return JSONResponse({"ok": False, "error": "配置内容必须是 JSON 对象"}, status_code=400)

    runtime = _get_plugin_runtime()
    host = _get_plugin_host()
    loaded_module = runtime.registry.get(plugin_name) if runtime else None
    if loaded_module is not None:
        candidate = PluginConfig.from_mapping(
            plugin_name,
            config_data,
            config_path,
            exists=True,
        )
        try:
            loaded_module.config_spec.apply(candidate)
        except PluginConfigValidationError as exc:
            return JSONResponse(
                {"ok": False, "saved": False, "reloaded": False, "error": f"配置校验失败: {exc}"},
                status_code=400,
            )

    try:
        serialized = json.dumps(config_data, ensure_ascii=False, indent=2) + "\n"
        await asyncio.to_thread(os.makedirs, os.path.dirname(config_path), exist_ok=True)
        await asyncio.to_thread(replace_text_files_atomically, [(config_path, serialized)])
    except Exception as exc:
        return JSONResponse(
            {"ok": False, "saved": False, "reloaded": False, "error": f"写入配置失败: {exc}"},
            status_code=500,
        )

    reload_msg = ""
    reloaded = False
    if runtime and loaded_module is not None:
        result = await runtime.reload_config(plugin_name, handler=host)
        reload_msg = result.message
        reloaded = bool(result.ok)
        if not result.ok:
            return JSONResponse(
                {
                    "ok": False,
                    "saved": True,
                    "reloaded": False,
                    "reload": reload_msg,
                    "error": reload_msg or "配置已保存，但热重载失败",
                },
                status_code=400,
            )

    return JSONResponse({
        "ok": True,
        "saved": True,
        "reloaded": reloaded,
        "message": "配置已保存",
        "reload": reload_msg,
    })

__all__ = ["router"]
