"""项目 Agora 播放页面的浏览器运行后端。"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any

from oopz_sdk.config import OopzConfig
from oopz_sdk.transport.voice_browser import _DEFAULT_BROWSER_ARGS, BrowserVoiceTransport

from core.logger_config import get_logger
from core.proxy_utils import get_playwright_proxy, get_selenium_proxy_argument

logger = get_logger("VoiceBrowser")


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

        html_path = self._voice_html_path()
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
        return Path(__file__).resolve().parents[1] / "oopz" / "assets" / "voice" / "agora_player.html"

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
