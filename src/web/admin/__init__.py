"""管理后台路由模块。"""

from fastapi import APIRouter

from . import auth, config, members, music, pages, plugins, scheduler


def create_admin_router() -> APIRouter:
    router = APIRouter()
    for module in (pages, auth, config, music, scheduler, members, plugins):
        router.include_router(module.router)
    return router


__all__ = ["create_admin_router"]
