from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any

_LAUNCH_ARGS = ["--no-sandbox", "--disable-dev-shm-usage"]


class HeadlessBrowser:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._playwright: Any = None
        self._browser: Any = None

    async def _ensure_browser(self) -> Any:
        async with self._lock:
            if self._browser is not None and self._browser.is_connected():
                return self._browser
            from playwright.async_api import async_playwright

            if self._playwright is None:
                self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True, channel="chromium", args=_LAUNCH_ARGS,
            )
            return self._browser

    @contextlib.asynccontextmanager
    async def page(self, **context_options: Any) -> AsyncIterator[Any]:
        browser = await self._ensure_browser()
        context = await browser.new_context(**context_options)
        try:
            yield await context.new_page()
        finally:
            with contextlib.suppress(Exception):
                await context.close()

    async def close(self) -> None:
        async with self._lock:
            browser, playwright = self._browser, self._playwright
            self._browser = self._playwright = None
        if browser is not None:
            with contextlib.suppress(Exception):
                await browser.close()
        if playwright is not None:
            with contextlib.suppress(Exception):
                await playwright.stop()
