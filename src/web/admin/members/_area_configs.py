"""域独立配置（area_configs）的增删查改与持久化。"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from web.admin.shared import (
    cfg,
    read_json_body,
)

router = APIRouter()


@router.get("/admin/api/area-configs")
def admin_area_configs_list():
    """返回所有域的独立配置。"""
    from core.area_config import get_area_registry
    reg = get_area_registry()
    configs = reg.export_all()
    return JSONResponse({"ok": True, "configs": configs})


@router.get("/admin/api/area-configs/{area_id}")
def admin_area_config_get(area_id: str):
    from core.area_config import AreaConfigRegistry, get_area_registry
    reg = get_area_registry()
    if not reg.is_configured(area_id):
        return JSONResponse({"ok": True, "configured": False, "config": {}})
    c = reg.get(area_id)
    return JSONResponse({"ok": True, "configured": True, "config": AreaConfigRegistry.config_to_dict(c)})


@router.post("/admin/api/area-configs/{area_id}")
async def admin_area_config_save(area_id: str, request: Request):
    """创建或更新域配置并持久化。"""
    body = await read_json_body(request)
    area_id = area_id.strip()
    if not area_id:
        return JSONResponse({"ok": False, "error": "area_id 不能为空"}, status_code=400)

    from core.area_config import AreaConfigRegistry, get_area_registry
    reg = get_area_registry()
    updated = reg.update_config(area_id, body)
    normalized = AreaConfigRegistry.config_to_dict(updated)

    saved = cfg.read_area_overrides()
    saved[area_id] = normalized
    cfg.write_area_overrides(saved)

    return JSONResponse({"ok": True, "config": AreaConfigRegistry.config_to_dict(reg.get(area_id))})


@router.delete("/admin/api/area-configs/{area_id}")
def admin_area_config_delete(area_id: str):
    """删除域的独立配置。"""
    area_id = area_id.strip()
    from core.area_config import get_area_registry
    reg = get_area_registry()
    removed = reg.remove_config(area_id)

    saved = cfg.read_area_overrides()
    saved.pop(area_id, None)
    cfg.write_area_overrides(saved)

    return JSONResponse({"ok": True, "removed": removed})
