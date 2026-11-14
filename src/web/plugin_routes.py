"""插件路由与后台导航的注册入口。"""

from collections.abc import Callable
from dataclasses import asdict, dataclass

from fastapi import APIRouter, FastAPI


@dataclass(frozen=True)
class AdminNavItem:
    key: str
    href: str
    label: str


_admin_nav: dict[object, AdminNavItem] = {}


def admin_navigation() -> list[dict[str, str]]:
    return [asdict(item) for item in tuple(_admin_nav.values())]


def register_web(
    app: FastAPI,
    router: APIRouter,
    *,
    admin_nav: AdminNavItem | None = None,
) -> Callable[[], None]:
    routes = tuple(router.routes)
    app.router.routes.extend(routes)
    app.openapi_schema = None
    registration = object()
    if admin_nav is not None:
        _admin_nav[registration] = admin_nav

    def unregister() -> None:
        registered = {id(route) for route in routes}
        app.router.routes[:] = [route for route in app.router.routes if id(route) not in registered]
        app.openapi_schema = None
        _admin_nav.pop(registration, None)

    return unregister
