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

# ---------------------------------------------------------------------------
# Theme CSS-variable values for each template (used by base.html)
# ---------------------------------------------------------------------------
_THEME_DEFAULTS = {
    "theme_poster_w": "1200px",
    "theme_poster_p": "40px",
    "theme_shell_radius": "28px",
    "theme_shell_padding": "28px 30px",
    "theme_shell_shadow": "0 24px 70px rgba(0,0,0,.34)",
    "theme_hero_mb": "24px",
    "theme_avatar_size": "104px",
    "theme_avatar_radius": "24px",
    "theme_avatar_border": "1px solid rgba(255,255,255,.14)",
    "theme_title_size": "38px",
    "theme_title_spacing": ".04em",
    "theme_subtitle_size": "18px",
    "theme_name_size": "22px",
    "theme_name_color": "inherit",
    "theme_panel_mt": "18px",
    "theme_panel_p": "18px 20px",
    "theme_panel_radius": "20px",
    "theme_row_gap": "24px",
    "theme_row_p": "8px 0",
    "theme_row_border": "1px solid rgba(255,255,255,.06)",
    "theme_value_weight": "600",
    "theme_value_align": "left",
    "theme_empty_p": "14px 0",
    "theme_record_border": "1px solid rgba(255,255,255,.06)",
    "theme_record_meta_color": "inherit",
    "theme_record_metrics_color": "inherit",
}

THEMES: dict[str, dict[str, str]] = {
    "daily": {
        "theme_bg": "linear-gradient(140deg,#281100,#5d2d06 40%,#8f5721)",
        "theme_text": "#fff7ef",
        "theme_poster_w": "1240px",
        "theme_poster_p": "42px",
        "theme_shell_bg": "rgba(32,14,5,.82)",
        "theme_shell_border": "1px solid rgba(255,214,173,.15)",
        "theme_shell_radius": "30px",
        "theme_shell_padding": "30px",
        "theme_shell_shadow": "0 24px 70px rgba(0,0,0,.35)",
        "theme_hero_mb": "20px",
        "theme_avatar_size": "100px",
        "theme_avatar_bg": "#51290f",
        "theme_avatar_border": "none",
        "theme_title_size": "36px",
        "theme_title_spacing": "normal",
        "theme_subtitle_size": "17px",
        "theme_subtitle_color": "#f0d6bc",
        "theme_name_size": "21px",
        "theme_label_color": "#e9c9a7",
        "theme_panel_mt": "16px",
        "theme_panel_p": "18px",
        "theme_panel_radius": "22px",
        "theme_row_gap": "0px",
        "theme_row_border": "1px solid rgba(255,255,255,.07)",
        "theme_empty_p": "12px 0",
        "theme_record_border": "1px solid rgba(255,255,255,.07)",
    },
    "weekly": {
        "theme_bg": "linear-gradient(135deg,#0c2620,#145145 42%,#2f8977)",
        "theme_text": "#f1fffb",
        "theme_poster_w": "1240px",
        "theme_poster_p": "42px",
        "theme_shell_bg": "rgba(8,29,24,.8)",
        "theme_shell_border": "1px solid rgba(197,255,241,.14)",
        "theme_shell_radius": "30px",
        "theme_shell_padding": "30px",
        "theme_shell_shadow": "0 24px 70px rgba(0,0,0,.34)",
        "theme_hero_mb": "20px",
        "theme_avatar_size": "100px",
        "theme_avatar_bg": "#103e35",
        "theme_avatar_border": "none",
        "theme_title_size": "36px",
        "theme_title_spacing": "normal",
        "theme_subtitle_size": "17px",
        "theme_subtitle_color": "#bfe7de",
        "theme_name_size": "21px",
        "theme_label_color": "#bbe5dc",
        "theme_panel_mt": "16px",
        "theme_panel_p": "18px",
        "theme_panel_radius": "22px",
        "theme_row_gap": "0px",
        "theme_row_border": "1px solid rgba(255,255,255,.07)",
        "theme_empty_p": "12px 0",
        "theme_record_border": "1px solid rgba(255,255,255,.07)",
    },
    "record": {
        "theme_bg": "linear-gradient(140deg,#150d29,#30215d 45%,#536cc5)",
        "theme_text": "#f7f7ff",
        "theme_poster_w": "1240px",
        "theme_poster_p": "42px",
        "theme_shell_bg": "rgba(14,10,32,.8)",
        "theme_shell_border": "1px solid rgba(220,226,255,.13)",
        "theme_shell_radius": "30px",
        "theme_shell_padding": "30px",
        "theme_shell_shadow": "0 24px 70px rgba(0,0,0,.36)",
        "theme_hero_mb": "20px",
        "theme_avatar_size": "96px",
        "theme_avatar_radius": "22px",
        "theme_avatar_bg": "#271d49",
        "theme_avatar_border": "none",
        "theme_title_size": "34px",
        "theme_title_spacing": "normal",
        "theme_subtitle_size": "17px",
        "theme_subtitle_color": "#c6cff9",
        "theme_name_size": "20px",
        "theme_label_color": "#cdd4ff",
        "theme_panel_mt": "16px",
        "theme_panel_p": "18px",
        "theme_panel_radius": "22px",
        "theme_row_gap": "0px",
        "theme_row_border": "1px solid rgba(255,255,255,.07)",
        "theme_empty_p": "12px 0",
        "theme_record_border": "1px solid rgba(255,255,255,.07)",
        "theme_record_meta_color": "#cdd4ff",
        "theme_record_metrics_color": "#eef1ff",
    },
    "money": {
        "theme_bg": "linear-gradient(140deg,#261b0f,#4e3110 46%,#0e1b27)",
        "theme_text": "#f8f3ea",
        "theme_shell_bg": "rgba(15,15,20,.82)",
        "theme_shell_border": "1px solid rgba(244,209,142,.18)",
        "theme_shell_radius": "30px",
        "theme_shell_padding": "30px 32px",
        "theme_shell_shadow": "0 28px 80px rgba(0,0,0,.34)",
        "theme_avatar_bg": "#302010",
        "theme_avatar_border": "1px solid rgba(255,255,255,.12)",
        "theme_subtitle_color": "#d9c09f",
        "theme_name_color": "#fff5de",
        "theme_label_color": "#cbb48f",
        "theme_panel_mt": "18px",
        "theme_row_p": "9px 0",
        "theme_value_weight": "700",
    },
    "info": {
        "theme_bg": "linear-gradient(135deg,#0b1d2b,#18354b 45%,#2a5368)",
        "theme_text": "#eef6fb",
        "theme_shell_bg": "rgba(8,17,24,.78)",
        "theme_shell_border": "1px solid rgba(170,222,255,.16)",
        "theme_avatar_bg": "#102534",
        "theme_subtitle_color": "#a9c8d8",
        "theme_name_color": "#dff2ff",
        "theme_label_color": "#9bbbcf",
    },
    "collection": {
        "theme_bg": "radial-gradient(circle at top right,#274862 0,#132a3b 38%,#08141d 100%)",
        "theme_text": "#eef6fb",
        "theme_shell_bg": "rgba(7,16,24,.82)",
        "theme_shell_border": "1px solid rgba(173,225,255,.16)",
        "theme_shell_radius": "30px",
        "theme_shell_padding": "30px 32px",
        "theme_shell_shadow": "0 28px 80px rgba(0,0,0,.34)",
        "theme_avatar_bg": "#102534",
        "theme_subtitle_color": "#a9c8d8",
        "theme_name_color": "#dff2ff",
        "theme_label_color": "#9bbbcf",
        "theme_panel_mt": "16px",
    },
    "ban_history": {
        "theme_bg": "linear-gradient(145deg,#240e12,#4a161f 44%,#111927)",
        "theme_text": "#f7eef0",
        "theme_shell_bg": "rgba(12,15,22,.84)",
        "theme_shell_border": "1px solid rgba(244,140,157,.18)",
        "theme_shell_radius": "30px",
        "theme_shell_padding": "30px 32px",
        "theme_shell_shadow": "0 28px 80px rgba(0,0,0,.34)",
        "theme_avatar_bg": "#24131a",
        "theme_avatar_border": "1px solid rgba(255,255,255,.12)",
        "theme_subtitle_color": "#e2aab4",
        "theme_name_color": "#fff0f2",
        "theme_label_color": "#d9a6af",
        "theme_panel_mt": "16px",
        "theme_value_align": "right",
    },
    "place_status": {
        "theme_bg": "linear-gradient(145deg,#0f1a22,#1f3a2f 42%,#12283b)",
        "theme_text": "#edf7f5",
        "theme_shell_bg": "rgba(8,16,22,.84)",
        "theme_shell_border": "1px solid rgba(162,231,198,.14)",
        "theme_avatar_bg": "#102534",
        "theme_subtitle_color": "#acd7c6",
        "theme_name_color": "#e8fff6",
        "theme_label_color": "#a7c8be",
        "theme_value_align": "right",
    },
    "red_records": {
        "theme_bg": "radial-gradient(circle at top right,#4f1520 0,#22101a 40%,#0f1724 100%)",
        "theme_text": "#f8eff2",
        "theme_shell_bg": "rgba(12,15,22,.84)",
        "theme_shell_border": "1px solid rgba(230,118,134,.14)",
        "theme_avatar_bg": "#24131a",
        "theme_subtitle_color": "#e4a8b1",
        "theme_name_color": "#fff3f5",
        "theme_label_color": "#d8acb3",
        "theme_value_align": "right",
    },
    "red_collection": {
        "theme_bg": "linear-gradient(145deg,#25090d,#511117 40%,#161928)",
        "theme_text": "#f9eff1",
        "theme_shell_bg": "rgba(14,14,20,.84)",
        "theme_shell_border": "1px solid rgba(249,140,154,.15)",
        "theme_avatar_bg": "#221219",
        "theme_subtitle_color": "#ebb3bc",
        "theme_name_color": "#fff4f6",
        "theme_label_color": "#d9acb3",
        "theme_value_align": "right",
    },
}


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
        base_tpl_path = TEMPLATES_DIR / "base.html"
        if not base_tpl_path.is_file():
            logger.warning("DeltaForceRender: base template not found: %s", base_tpl_path)
            return None
        if template_name not in THEMES:
            logger.warning("DeltaForceRender: unknown theme %r", template_name)
            return None
        try:
            theme_vars = {**_THEME_DEFAULTS, **THEMES[template_name]}
            tpl = Template(base_tpl_path.read_text(encoding="utf-8"))
            html = tpl.safe_substitute(
                title=str(context.get("title") or ""),
                subtitle=str(context.get("subtitle") or ""),
                hero_name=str(context.get("hero_name") or ""),
                hero_image=str(context.get("hero_image") or ""),
                body_html=str(context.get("body_html") or ""),
                **theme_vars,
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
