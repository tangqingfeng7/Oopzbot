from fastapi import APIRouter

from . import (
    _area_configs,
    _area_invites,
    _area_membership,
    _articles,
    _bot_admins,
    _channels,
    _members,
    _messaging,
)

_SUBMODULES = (
    _members,
    _bot_admins,
    _channels,
    _articles,
    _messaging,
    _area_configs,
    _area_invites,
    _area_membership,
)

router = APIRouter()
for _module in _SUBMODULES:
    router.include_router(_module.router)

__all__ = ["router"]
