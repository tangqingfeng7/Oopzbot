"""Oopz-SDK 的本地异步传输扩展。

SDK 0.15.0 原生支持 HTTP 代理，但没有处理项目已有的 system/direct/SOCKS
语义，也没有 WebSocket 收包水位检测。这里仅扩展传输装配，不复制协议逻辑。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path
from typing import Any

import aiohttp
from aiohttp_socks import ProxyConnector

from core.http_constants import HTTP_CONNECT_TIMEOUT
from core.proxy_utils import (
    ProxySettings,
    get_playwright_proxy,
    get_selenium_proxy_argument,
)
from oopz_sdk.config import OopzConfig
from oopz_sdk.exceptions import OopzAuthError, OopzConnectionError
from oopz_sdk.transport.http import HttpTransport
from oopz_sdk.transport.voice_browser import (
    _DEFAULT_BROWSER_ARGS,
    BrowserVoiceTransport,
)
from oopz_sdk.transport.ws import WebSocketTransport

logger = logging.getLogger(__name__)


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

        proxy_url = None
        if self.project_proxy.enabled and not _socks_proxy(self.project_proxy):
            proxy_url = self.project_proxy.server

        try:
            self._ws = await self._session.ws_connect(  # type: ignore[assignment]
                self.config.ws_url,
                proxy=proxy_url,
                heartbeat=None,
                autoping=True,
            )
        except aiohttp.WSServerHandshakeError as exc:
            if exc.status in {401, 428}:
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


class ProjectBrowserVoiceTransport(BrowserVoiceTransport):
    """给 SDK 语音补统一代理，并在 Playwright 失败时回退 Selenium。"""

    def __init__(self, config: OopzConfig, *, proxy_value: object = None):
        super().__init__(config)
        self._proxy_value = proxy_value
        self._selenium_driver = None

    async def _init_browser(self) -> None:
        try:
            await self._init_playwright_browser()
            return
        except Exception as exc:
            # Playwright 缺包、greenlet/动态库损坏或 Chromium 启动失败都可以由
            # Selenium 接管。清理已创建的 Playwright 对象后在同一浏览器线程启动。
            logger.warning("SDK Playwright 语音后端不可用，回退 Selenium: %s", exc)
            self._init_done.clear()
            self._init_error = None
            try:
                await super()._shutdown_browser()
            except Exception:
                logger.debug("清理失败的 Playwright 后端时出现异常", exc_info=True)
        self._init_selenium_browser()
        self._init_done.set()

    async def _init_playwright_browser(self) -> None:
        try:
            from playwright.async_api import async_playwright
        except ModuleNotFoundError as exc:
            self._init_error = (
                "playwright is required for voice browser backend. "
                "Install with: pip install playwright && playwright install chromium"
            )
            self._init_done.set()
            raise exc

        self._playwright = await async_playwright().start()
        launch_kwargs: dict[str, Any] = {
            "headless": self.config.voice_browser_headless,
            "args": list(_DEFAULT_BROWSER_ARGS),
        }
        proxy = get_playwright_proxy(self._proxy_value)
        if proxy:
            launch_kwargs["proxy"] = proxy

        if self.config.voice_browser_executable_path:
            launch_kwargs["executable_path"] = self.config.voice_browser_executable_path
        else:
            launch_kwargs["channel"] = "chromium"

        self._browser = await self._playwright.chromium.launch(**launch_kwargs)
        page = await self._browser.new_page()
        page.set_default_timeout(60_000)
        await page.add_init_script(
            f"window.AGORA_SDK_URL = {self.config.voice_agora_sdk_url!r};"
        )

        import oopz_sdk.transport.voice_browser as voice_browser_module

        html_path = (
            Path(voice_browser_module.__file__).resolve().parent.parent
            / "assets"
            / "voice"
            / "agora_player.html"
        )
        await page.goto(html_path.as_uri())
        warmup = await page.evaluate("() => window.agoraWarmup()")
        if not warmup or not warmup.get("ok"):
            raise RuntimeError(
                f"Agora SDK 预热失败: {(warmup or {}).get('error') or 'empty result'}"
            )
        self._page = page
        self._init_done.set()

    @staticmethod
    def _voice_html_path() -> Path:
        import oopz_sdk.transport.voice_browser as voice_browser_module

        return (
            Path(voice_browser_module.__file__).resolve().parent.parent
            / "assets"
            / "voice"
            / "agora_player.html"
        )

    def _init_selenium_browser(self) -> None:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service as ChromeService

        options = Options()
        options.add_argument("--headless=new")
        for argument in _DEFAULT_BROWSER_ARGS:
            options.add_argument(argument)
        proxy_argument = get_selenium_proxy_argument(self._proxy_value)
        if proxy_argument:
            options.add_argument(proxy_argument)
        if self.config.voice_browser_executable_path:
            options.binary_location = self.config.voice_browser_executable_path

        driver = None
        last_error: BaseException | None = None
        try:
            from webdriver_manager.chrome import ChromeDriverManager

            driver = webdriver.Chrome(
                service=ChromeService(ChromeDriverManager().install()),
                options=options,
            )
        except Exception as exc:
            last_error = exc

        if driver is None:
            try:
                driver = webdriver.Chrome(options=options)
            except Exception as exc:
                last_error = exc

        if driver is None:
            raise RuntimeError(f"Selenium Chromium 启动失败: {last_error}") from last_error

        try:
            driver.set_script_timeout(60)
            driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {
                    "source": (
                        "window.AGORA_SDK_URL = "
                        + repr(str(self.config.voice_agora_sdk_url))
                        + ";"
                    )
                },
            )
            driver.get(self._voice_html_path().as_uri())
            warmup = driver.execute_async_script(
                """
                const done = arguments[arguments.length - 1];
                Promise.resolve(window.agoraWarmup())
                    .then(done)
                    .catch((error) => done({ok: false, error: String(error)}));
                """
            )
            if not warmup or not warmup.get("ok"):
                raise RuntimeError(
                    f"Agora SDK 预热失败: {(warmup or {}).get('error') or 'empty result'}"
                )
        except Exception:
            driver.quit()
            raise
        self._selenium_driver = driver

    async def _run_on_browser(self, method: str, *args: Any) -> Any:
        await self.start()
        driver = self._selenium_driver
        if driver is None:
            return await super()._run_on_browser(method, *args)
        if self._thread_loop is None:
            raise RuntimeError("Selenium 语音浏览器尚未就绪")

        async def invoke() -> Any:
            script = """
                const done = arguments[arguments.length - 1];
                const method = arguments[0];
                const values = Array.prototype.slice.call(arguments, 1, -1);
                try {
                    Promise.resolve(window[method](...values))
                        .then(done)
                        .catch((error) => done({ok: false, error: String(error)}));
                } catch (error) {
                    done({ok: false, error: String(error)});
                }
            """
            return driver.execute_async_script(script, method, *args)

        future = asyncio.run_coroutine_threadsafe(invoke(), self._thread_loop)
        return await asyncio.wrap_future(future)

    async def _shutdown_browser(self) -> None:
        driver = self._selenium_driver
        self._selenium_driver = None
        if driver is not None:
            with contextlib.suppress(Exception):
                driver.quit()
            return
        await super()._shutdown_browser()


def install_project_transports(bot, proxy: ProxySettings, proxy_value: object) -> None:
    """在 OopzBot 启动前替换各 service 共享的传输对象。"""

    transport = ProjectHttpTransport(
        bot.config,
        bot.rest.signer,
        auth_manager=bot.auth,
        proxy=proxy,
    )
    bot.rest.transport = transport
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
