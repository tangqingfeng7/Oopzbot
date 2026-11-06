"""Oopz 网络连接的代理、权限响应和超时处理。"""

from __future__ import annotations

import asyncio
import logging

import aiohttp
from aiohttp_socks import ProxyConnector
from oopz_sdk.config import OopzConfig
from oopz_sdk.exceptions import (
    AUTH_FAILURE_STATUS_CODES,
    OopzApiError,
    OopzAuthError,
    OopzConnectionError,
)
from oopz_sdk.models import ChannelType, CreateChannelResult, OperationResult
from oopz_sdk.models.event import ChannelCreateEvent, ChannelDeleteEvent, ChannelUpdateEvent
from oopz_sdk.services.channel import Channel
from oopz_sdk.transport.http import HttpResponse, HttpTransport
from oopz_sdk.transport.ws import WebSocketTransport
from oopz_sdk.utils.payload import safe_json

from core.http_constants import HTTP_CONNECT_TIMEOUT
from core.proxy_utils import ProxySettings
from core.ttl_cache import TtlCache
from music.voice_browser import ProjectBrowserVoiceTransport

logger = logging.getLogger(__name__)

CHANNELS_CACHE_TTL = 120.0
channels_response_cache = TtlCache(CHANNELS_CACHE_TTL)


class ProjectChannel(Channel):
    """主动操作与 SDK 频道事件共用缓存失效。"""

    def invalidate_channel_caches(self, area: str) -> None:
        self._get_voice_ids_cache_store().pop(area, None)
        self.cache.invalidate_area_channels(area)
        channels_response_cache.invalidate(area)

    def on_channel_changed(
        self, _ctx, event: ChannelCreateEvent | ChannelUpdateEvent | ChannelDeleteEvent,
    ) -> None:
        if event.area:
            self.invalidate_channel_caches(event.area)


    async def create_channel(
        self, area: str, name: str, group_id: str = "",
        channel_type: ChannelType | str = ChannelType.TEXT,
    ) -> CreateChannelResult:
        result = await super().create_channel(area, name, group_id, channel_type)
        self.invalidate_channel_caches(area)
        return result

    async def delete_channel(self, area: str, channel: str) -> OperationResult:
        result = await super().delete_channel(area, channel)
        if result.ok:
            self.invalidate_channel_caches(area)
        return result


def _socks_proxy(settings: ProxySettings) -> bool:
    return settings.enabled and str(settings.scheme or "").startswith("socks")


def _connector(settings: ProxySettings) -> aiohttp.BaseConnector | None:
    if _socks_proxy(settings):
        assert settings.server is not None
        return ProxyConnector.from_url(settings.server)
    return None


def _trust_env(settings: ProxySettings) -> bool:
    return settings.mode == "system"


class ProjectHttpTransport(HttpTransport):
    """让 SDK REST/上传共享项目的代理模式。"""

    def __init__(self, config: OopzConfig, signer, *, auth_manager, proxy: ProxySettings):
        super().__init__(config, signer, auth_manager=auth_manager)
        self.project_proxy = proxy

    async def request(self, method: str, url_path: str, body=None, **kwargs) -> HttpResponse:
        # 退出域接口只接受 query 参数；SDK 0.16 将 area 放在 JSON body 中。
        if method.upper() == "DELETE" and url_path == "/client/v1/area/v1/quit" and isinstance(body, dict):
            kwargs["params"] = {**body, **(kwargs.get("params") or {})}
            body = None
        response = await super().request(method, url_path, body=body, **kwargs)
        # 域操作日志会用 401 表示缺少管理权限，交由通知服务处理，避免轮询触发重登。
        if (
            method.upper() == "GET"
            and url_path == "/client/v1/area/v1/operateLogs"
            and response.status_code == 401
        ):
            payload = safe_json(response)
            detail = self._error_message(payload, default="HTTP 401")
            raise OopzApiError(
                f"域操作日志请求失败 (HTTP 401): {detail}",
                status_code=401,
                payload=payload,
                response=response,
            )
        return response

    async def _ensure_client_session(self) -> aiohttp.ClientSession:
        if self._client_session is None or self._client_session.closed:
            self._client_session = aiohttp.ClientSession(
                headers=self.headers,
                connector=_connector(self.project_proxy),
                trust_env=_trust_env(self.project_proxy),
            )
        return self._client_session


class ProjectWebSocketTransport(WebSocketTransport):
    """支持 SOCKS/system/direct，并在长时间无收包时主动重连。"""

    def __init__(
        self,
        config: OopzConfig,
        *,
        proxy: ProxySettings,
        stale_timeout: float = 90.0,
    ) -> None:
        super().__init__(config)
        self.project_proxy = proxy
        self.stale_timeout = max(0.0, float(stale_timeout))

    async def connect(self) -> None:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers=self.config.get_headers(),
                connector=_connector(self.project_proxy),
                trust_env=_trust_env(self.project_proxy),
                # 只给建连设上限：aiohttp 默认的 total=5min 会把握手卡死 5 分钟、
                # 拖垮重连退避；而长连接本身不能有 total/sock_read 上限，
                # 否则空闲期（heartbeat 关闭）会被误判为超时断开。
                timeout=aiohttp.ClientTimeout(
                    total=None, sock_connect=HTTP_CONNECT_TIMEOUT, sock_read=None
                ),
            )

        # SDK 0.16 的代理选择器不识别 ws/wss，HTTP 代理须显式传入握手。
        proxy_url = None
        if self.project_proxy.enabled and not _socks_proxy(self.project_proxy):
            proxy_url = self.project_proxy.server
        try:
            self._ws = await self._session.ws_connect(  # type: ignore[assignment]
                self.config.ws_url, proxy=proxy_url, heartbeat=None, autoping=True,
            )
        except aiohttp.WSServerHandshakeError as exc:
            if exc.status in AUTH_FAILURE_STATUS_CODES:
                raise OopzAuthError(
                    f"WebSocket 握手鉴权失败 (HTTP {exc.status}): {exc.message}",
                    status_code=exc.status,
                ) from exc
            raise OopzConnectionError(
                f"WebSocket 握手失败 (HTTP {exc.status}): {exc.message}"
            ) from exc
        except aiohttp.ClientError as exc:
            raise OopzConnectionError(f"WebSocket 连接失败: {exc}") from exc

    async def recv(self) -> str:
        if self.stale_timeout <= 0:
            return await super().recv()
        try:
            return await asyncio.wait_for(
                super().recv(),
                timeout=self.stale_timeout,
            )
        except asyncio.TimeoutError as exc:
            await self.close()
            raise OopzConnectionError(
                f"WebSocket {self.stale_timeout:g} 秒未收到数据，触发重连"
            ) from exc


def install_project_transports(bot, proxy: ProxySettings, proxy_value: object) -> None:
    """在 OopzBot 启动前替换各 service 共享的传输对象。"""

    transport = ProjectHttpTransport(
        bot.config,
        bot.rest.signer,
        auth_manager=bot.auth,
        proxy=proxy,
    )
    bot.rest.transport = transport
    bot.channels = bot.rest.channels = ProjectChannel(
        bot, bot.config, transport, bot.rest.signer, bot.channels.cache,
    )
    for event_name in ("channel.create", "channel.update", "channel.delete"):
        bot.on(event_name)(bot.channels.on_channel_changed)
    for service in (
        bot.messages,
        bot.media,
        bot.areas,
        bot.channels,
        bot.person,
        bot.moderation,
        bot.general,
        bot.voice,
    ):
        service.transport = transport

    bot.ws.transport = ProjectWebSocketTransport(
        bot.config,
        proxy=proxy,
        stale_timeout=90.0,
    )
    bot.voice.backend = ProjectBrowserVoiceTransport(
        bot.config,
        proxy_value=proxy_value,
    )
