from __future__ import annotations

import os
from pathlib import Path
from string import Template
from typing import Optional

from logger_config import get_logger

from ._delta_force_assets import TEMPLATES_DIR

logger = get_logger("DeltaForceRender")
_PLAYWRIGHT_RENDER_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
]


class DeltaForceRenderer:
    def __init__(self, config: dict) -> None:
        self._config = config or {}
        self._width = max(720, int(self._config.get("render_width", 1365) or 1365))
        self._timeout_ms = max(5000, int(float(self._config.get("render_timeout_sec", 30) or 30) * 1000))
        self._temp_dir = Path(str(self._config.get("temp_dir") or "data/delta_force"))
        self._render_dir = self._temp_dir / "renders"
        self._render_dir.mkdir(parents=True, exist_ok=True)

    @property
    def render_dir(self) -> Path:
        return self._render_dir

    def render_to_image(self, template_name: str, context: dict) -> Optional[str]:
        template_path = TEMPLATES_DIR / f"{template_name}.html"
        if not template_path.is_file():
            logger.warning("DeltaForceRender: template not found: %s", template_path)
            return None
        try:
            tpl = Template(template_path.read_text(encoding="utf-8"))
            html = tpl.safe_substitute(
                title=str(context.get("title") or ""),
                subtitle=str(context.get("subtitle") or ""),
                hero_name=str(context.get("hero_name") or ""),
                hero_image=str(context.get("hero_image") or ""),
                body_html=str(context.get("body_html") or ""),
            )
        except Exception as exc:
            logger.warning("DeltaForceRender: failed to build html: %s", exc)
            return None

        base_name = f"{template_name}_{os.getpid()}_{id(context)}"
        html_path = self._render_dir / f"{base_name}.html"
        png_path = self._render_dir / f"{base_name}.png"

        try:
            html_path.write_text(html, encoding="utf-8")
        except OSError as exc:
            logger.warning("DeltaForceRender: failed to write html: %s", exc)
            return None

        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            logger.warning("DeltaForceRender: playwright unavailable: %s", exc)
            self.safe_cleanup(html_path)
            return None

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True, channel="chromium", args=_PLAYWRIGHT_RENDER_ARGS)
                page = browser.new_page(viewport={"width": self._width, "height": 2200})
                page.goto(html_path.resolve().as_uri(), wait_until="networkidle", timeout=self._timeout_ms)
                page.locator("#poster").screenshot(path=str(png_path))
                browser.close()
        except Exception as exc:
            logger.warning("DeltaForceRender: screenshot failed: %s", exc)
            self.safe_cleanup(html_path)
            self.safe_cleanup(png_path)
            return None

        self.safe_cleanup(html_path)
        return str(png_path)

    @staticmethod
    def safe_cleanup(path: os.PathLike | str | None) -> None:
        if not path:
            return
        try:
            Path(path).unlink(missing_ok=True)
        except Exception:
            return
