"""管理后台路由模块。"""

from fastapi import APIRouter

from . import auth, config, members, music, pages, plugins, scheduler, screen_share


def create_admin_router() -> APIRouter:
    router = APIRouter()
    for module in (pages, auth, config, music, scheduler, members, plugins, screen_share):
        router.include_router(module.router)
    return router


__all__ = ["create_admin_router"]
