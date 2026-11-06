"""运行时访问器：延迟导入 ``web.web_player`` 暴露的实例与状态。

这些函数在调用时才导入 ``web.web_player``，避免管理后台模块与播放器主模块之间的
循环引用，是 shared 包内其它子模块的基础依赖。
"""

from __future__ import annotations

import functools
import inspect
from typing import TYPE_CHECKING

from fastapi.responses import JSONResponse

from core.redis_protocol import PlaybackCommandStore, RedisDataStore

if TYPE_CHECKING:
    from app.infrastructure.gateways.sender_gateway import SenderGateway


def require_sender(func):
    """端点守卫装饰器：sender 未就绪时统一返回 503。

    收口各成员/频道/消息端点中重复的「sender 未初始化」检查；装饰后端点体内的
    ``_get_sender()`` 必为非空。须置于 ``@router.*`` 之下（让路由注册到本包装器），
    用 ``functools.wraps`` 保留原签名以便 FastAPI 正确解析路径/查询参数。
    """
    unavailable = {"ok": False, "error": "sender 未初始化"}

    if inspect.iscoroutinefunction(func):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            if not _get_sender():
                return JSONResponse(unavailable, status_code=503)
            return await func(*args, **kwargs)

        return async_wrapper

    @functools.wraps(func)
    def sync_wrapper(*args, **kwargs):
        if not _get_sender():
            return JSONResponse(unavailable, status_code=503)
        return func(*args, **kwargs)

    return sync_wrapper


async def _get_redis() -> RedisDataStore:
    """延迟导入，避免循环引用。"""
    from web.web_player import get_redis
    return await get_redis()


def _get_sender() -> SenderGateway | None:
    from web.web_player import get_sender
    return get_sender()


def _require_sender() -> SenderGateway:
    """返回已初始化的 sender。

    路由装饰器负责把正常的未初始化状态转换为 503；这里保留一次防御性检查，
    为端点函数提供静态可验证的非空契约，也避免未来绕过装饰器直接调用时出现
    难以定位的 ``NoneType`` 属性错误。
    """
    sender = _get_sender()
    if sender is None:
        raise RuntimeError("sender 未初始化；该端点必须由 require_sender 守卫")
    return sender


def _get_oopz_client():
    from web.web_player import get_oopz_client
    return get_oopz_client()


def _get_netease():
    from web.web_player import get_netease
    return get_netease()


def _get_started_at() -> float:
    from web.web_player import started_at
    return started_at


def _admin_enabled() -> bool:
    from web.web_player import _admin_enabled as web_admin_enabled
    return web_admin_enabled()


def _get_liked_ids_cache() -> list:
    from web.web_player import liked_ids_cache
    return liked_ids_cache


def _get_plugin_runtime():
    from web.web_player import get_plugin_runtime
    return get_plugin_runtime()


def _set_liked_ids_cache(value: list) -> None:
    import web.web_player as web_player
    web_player.liked_ids_cache = value


async def _execute_control_action(
    action: str,
    body: dict,
    redis_client: PlaybackCommandStore,
    area: str = "",
) -> dict:
    from web.web_player import execute_control_action
    return await execute_control_action(action, body, redis_client, area=area)


async def _execute_queue_action(
    action: str,
    index,
    redis_client: PlaybackCommandStore,
    area: str,
) -> dict:
    from web.web_player import execute_queue_action
    return await execute_queue_action(action, index, redis_client, area=area)


async def _add_song_to_queue(body: dict, area: str = "") -> dict:
    from web.web_player import add_song_to_queue
    return await add_song_to_queue(body, area=area)


__all__ = [
    "_add_song_to_queue",
    "_admin_enabled",
    "_execute_control_action",
    "_execute_queue_action",
    "_get_liked_ids_cache",
    "_get_netease",
    "_get_oopz_client",
    "_get_plugin_runtime",
    "_get_redis",
    "_get_sender",
    "_get_started_at",
    "_require_sender",
    "_set_liked_ids_cache",
    "require_sender",
]
