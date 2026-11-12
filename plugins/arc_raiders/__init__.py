from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from core.async_http import ManagedHttpClient
from core.logger_config import get_logger
from domain.plugins.base import (
    BotModule,
    PluginCommandCapabilities,
    PluginConfig,
    PluginConfigField,
    PluginConfigSpec,
    PluginMetadata,
    parse_int,
    validate_min,
)
from plugins._shared.browser import HeadlessBrowser
from plugins._shared.command_mixin import PluginCommandMixin

logger = get_logger("ArcRaidersPlugin")

RARITY_ZH = {
    "Common": "普通",
    "Uncommon": "不常见",
    "Rare": "稀有",
    "Epic": "史诗",
    "Legendary": "传说",
}

TYPE_ZH = {
    "Recyclable": "可回收物",
    "Trinket": "小饰品",
    "Topside Material": "上层材料",
    "SMG": "冲锋枪",
    "Shotgun": "霰弹枪",
    "Key": "钥匙",
    "Quick Use": "快速使用",
    "Assault Rifle": "突击步枪",
    "Modification": "改装件",
    "Ammunition": "弹药",
    "Shield": "护盾",
    "Battle Rifle": "战斗步枪",
    "LMG": "轻机枪",
    "Pistol": "手枪",
    "Nature": "自然物品",
    "Basic Material": "基础材料",
    "Augment": "强化件",
}

MAP_ZH = {
    "stella-montis": "星辰山",
    "riven-tides": "裂潮",
    "dam-battleground": "大坝战场",
    "blue-gate": "蓝门",
    "the-spaceport": "太空港",
    "buried-city": "掩埋废城",
}


class ArcRaidersPlugin(PluginCommandMixin, BotModule):
    command_error_prefix = "Arc 查询出错"
    command_log_name = "ArcRaidersPlugin"

    def __init__(self) -> None:
        self._handler = None
        self._config: dict[str, Any] = {}
        self._http = ManagedHttpClient()
        self._browser = HeadlessBrowser()
        self._index_cache: list[dict[str, Any]] = []
        self._index_expire_at = 0.0

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="arc_raiders",
            description="Arc Raiders物品查询与掉率",
            version="0.2.0",
            author="OpenAI",
        )

    @property
    def command_capabilities(self) -> PluginCommandCapabilities:
        return PluginCommandCapabilities(
            mention_prefixes=("arc", "ARC", "arc查询", "arc物品"),
            slash_commands=("/arc", "/arcevent"),
            is_public_command=True,
        )

    @property
    def private_modules(self) -> tuple[str, ...]:
        return ()

    @property
    def config_spec(self) -> PluginConfigSpec:
        return PluginConfigSpec(
            (
                PluginConfigField("enabled", default=False, description="是否启用插件", example=False),
                PluginConfigField(
                    "index_url",
                    default="https://arctracker.io/generated/client/items/items-index.zh-CN.json",
                    description="物品索引JSON地址",
                ),
                PluginConfigField(
                    "stats_api_base",
                    default="https://arctracker.io/api/stats/items",
                    description="掉率API基础地址",
                ),
                PluginConfigField(
                    "item_page_base",
                    default="https://arctracker.io/items",
                    description="物品详情页地址(英文页，用于提取场景)",
                ),
                PluginConfigField(
                    "zh_item_page_base",
                    default="https://arctracker.io/zh-CN/items",
                    description="中文详情页地址（用于截图）",
                ),
                PluginConfigField(
                    "zh_map_events_url",
                    default="https://arctracker.io/zh-CN/map-events",
                    description="中文地图事件页地址（用于/arcevent截图）",
                ),
                PluginConfigField(
                    "cache_ttl_sec",
                    default=600,
                    cast=parse_int,
                    validator=validate_min(60),
                    description="物品索引缓存秒数",
                    constraint=">= 60",
                ),
                PluginConfigField(
                    "request_timeout_sec",
                    default=12,
                    cast=parse_int,
                    validator=validate_min(3),
                    description="请求超时秒数",
                    constraint=">= 3",
                ),
                PluginConfigField(
                    "max_candidates",
                    default=6,
                    cast=parse_int,
                    validator=validate_min(1),
                    description="模糊匹配最大候选数量",
                    constraint=">= 1",
                ),
                PluginConfigField(
                    "image_mode",
                    default=True,
                    description="是否优先返回图片截图",
                    example=True,
                ),
                PluginConfigField(
                    "render_timeout_sec",
                    default=20,
                    cast=parse_int,
                    validator=validate_min(5),
                    description="截图渲染超时秒数",
                    constraint=">= 5",
                ),
                PluginConfigField(
                    "temp_dir",
                    default="data/arc_raiders",
                    description="截图临时目录",
                ),
            )
        )

    async def on_load(self, handler, config: PluginConfig | None = None) -> None:
        self._handler = handler
        self._config = (config or {}).copy()

    async def on_unload(self) -> None:
        await self._http.close()
        await self._browser.close()

    async def handle_slash(self, command, subcommand, arg, channel, area, user, handler) -> bool:
        if (command or "").strip().lower() == "/arcevent":
            if not self._config.get("enabled", False):
                await self._send(
                    handler,
                    "arc_raiders 插件当前未启用，请在 config/plugins/arc_raiders/config.json 中设置 enabled=true 后重载插件配置。",
                    channel,
                    area,
                )
                return True
            await self._send(handler, "正在查询地图事件截图，请稍候...", channel, area)
            img = await self._render_card_from_url(str(self._config.get("zh_map_events_url") or "https://arctracker.io/zh-CN/map-events"))
            if not img:
                await self._send(handler, "地图事件截图失败，请稍后重试。", channel, area)
                return True
            try:
                await handler.sender.upload_and_send_image(img, channel=channel, area=area)
            except Exception:
                await self._send(handler, "地图事件截图失败，请稍后重试。", channel, area)
            finally:
                with contextlib.suppress(Exception):
                    Path(img).unlink(missing_ok=True)
            return True
        return await super().handle_slash(command, subcommand, arg, channel, area, user, handler)

    async def dispatch_command(self, command_text: str, channel: str, area: str, user: str, handler) -> None:
        if not self._config.get("enabled", False):
            await self._send(
                handler,
                "arc_raiders 插件当前未启用，请在 config/plugins/arc_raiders/config.json 中设置 enabled=true 后重载插件配置。",
                channel,
                area,
            )
            return

        q = (command_text or "").strip()
        force_text_mode = False
        if q.endswith(" 1"):
            q = q[:-2].strip()
            force_text_mode = True
        elif q == "1":
            await self._send(handler, "用法: /arc <物品名> 或 /arc <物品名> 1（文字模式）", channel, area)
            return

        if not q or q.lower() in {"help", "帮助"}:
            await self._send(handler, "用法: @bot arc <物品名> 或 /arc <物品名>", channel, area)
            return

        try:
            items = await self._load_items()
        except Exception as exc:
            logger.warning("ArcRaiders: load index failed: %s", exc)
            await self._send(handler, "Arc物品索引加载失败，请稍后重试。", channel, area)
            return

        matches = self._search_items(items, q)
        if not matches:
            await self._send(handler, f"未找到与“{q}”相关的物品。", channel, area)
            return

        max_candidates = int(self._config.get("max_candidates", 6) or 6)
        if len(matches) > 1:
            lines = [f"找到 {len(matches)} 个候选，请输入更精确名称："]
            for idx, item in enumerate(matches[:max_candidates], start=1):
                item_type_zh = self._to_type_zh(str(item.get("type") or "?"))
                rarity_zh = self._to_rarity_zh(str(item.get("rarity") or "?"))
                lines.append(f"{idx}. {item.get('name','?')} ({item_type_zh} / {rarity_zh})")
            await self._send(handler, "\n".join(lines), channel, area)
            return

        item = matches[0]
        item_id = str(item.get("id") or "").strip()
        if not item_id:
            await self._send(handler, "命中物品缺少ID，暂时无法查询。", channel, area)
            return

        image_mode = bool(self._config.get("image_mode", True)) and not force_text_mode
        if image_mode:
            await self._send(handler, "正在使用直观截图模式查询，查询时间可能较长，请耐心等待", channel, area)
            if await self._send_item_image(handler, item_id, channel, area):
                return
        stats, locations = await asyncio.gather(
            self._fetch_drop_stats(item_id),
            self._fetch_locations(item_id),
        )
        if image_mode and await self._send_fallback_card_image(handler, item, stats, locations, channel, area):
            return
        await self._send(handler, self._format_result(item, stats, locations), channel, area)

    async def _send_item_image(self, handler, item_id: str, channel: str, area: str) -> bool:
        png_path = await self._render_item_page_image(item_id)
        if not png_path:
            return False
        try:
            await handler.sender.upload_and_send_image(png_path, channel=channel, area=area)
            return True
        except Exception as exc:
            logger.warning("ArcRaiders: upload image failed: %s", exc)
            return False
        finally:
            with contextlib.suppress(Exception):
                Path(png_path).unlink(missing_ok=True)

    async def _render_item_page_image(self, item_id: str) -> str | None:
        base = str(self._config.get("zh_item_page_base") or "https://arctracker.io/zh-CN/items").rstrip("/")
        return await self._render_card_from_url(f"{base}/{item_id}", f"item_{item_id}")

    async def _render_card_from_url(self, url: str, file_prefix: str = "page") -> str | None:
        timeout_ms = int(self._config.get("render_timeout_sec", 20)) * 1000
        render_dir = Path(str(self._config.get("temp_dir") or "data/arc_raiders")) / "renders"
        await asyncio.to_thread(render_dir.mkdir, parents=True, exist_ok=True)
        out_path = render_dir / f"{file_prefix}_{os.getpid()}_{int(time.time()*1000)}.png"

        try:
            async with self._browser.page(viewport={"width": 1365, "height": 2400}, locale="zh-CN") as page:
                await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                with contextlib.suppress(Exception):
                    await page.wait_for_load_state("networkidle", timeout=min(8000, timeout_ms // 2))
                await page.wait_for_timeout(1800)
                card = page.locator('[data-slot="card"]')
                if await card.count() == 0:
                    raise RuntimeError("card element not found")
                await card.first.screenshot(path=str(out_path))
        except Exception as exc:
            logger.warning("ArcRaiders: render screenshot failed: %s", exc)
            with contextlib.suppress(Exception):
                out_path.unlink(missing_ok=True)
            return None

        return str(out_path)

    async def _send_fallback_card_image(
        self,
        handler,
        item: dict[str, Any],
        stats: dict[str, Any] | None,
        locations: list[str],
        channel: str,
        area: str,
    ) -> bool:
        img_path = await asyncio.to_thread(self._render_text_card, item, stats, locations)
        if not img_path:
            return False
        try:
            await handler.sender.upload_and_send_image(img_path, channel=channel, area=area)
            return True
        except Exception as exc:
            logger.warning("ArcRaiders: upload fallback image failed: %s", exc)
            return False
        finally:
            with contextlib.suppress(Exception):
                Path(img_path).unlink(missing_ok=True)

    def _render_text_card(
        self,
        item: dict[str, Any],
        stats: dict[str, Any] | None,
        locations: list[str],
    ) -> str | None:
        try:
            temp_root = Path(str(self._config.get("temp_dir") or "data/arc_raiders"))
            render_dir = temp_root / "renders"
            render_dir.mkdir(parents=True, exist_ok=True)
            out_path = render_dir / f"card_{item.get('id','item')}_{os.getpid()}_{int(time.time()*1000)}.png"

            width = 1200
            height = 860
            img = Image.new("RGB", (width, height), (14, 23, 31))
            draw = ImageDraw.Draw(img)
            font = ImageFont.load_default()

            y = 40
            item_type_zh = self._to_type_zh(str(item.get("type") or "未知"))
            rarity_zh = self._to_rarity_zh(str(item.get("rarity") or "未知"))
            lines = [
                "ARC Raiders 物品查询",
                f"名称: {item.get('name') or '未知'}",
                f"ID: {item.get('id') or ''}",
                f"类型/稀有度: {item_type_zh} / {rarity_zh}",
                f"场景: {'、'.join(locations) if locations else '暂无'}",
            ]
            if stats:
                lines.extend(self._stats_lines(stats))

            lines.append(f"详情页: https://arctracker.io/zh-CN/items/{item.get('id') or ''}")

            for idx, line in enumerate(lines):
                color = (242, 248, 255) if idx == 0 else (218, 230, 242)
                draw.text((40, y), line, fill=color, font=font)
                y += 36

            img.save(out_path, format="PNG")
            return str(out_path)
        except Exception as exc:
            logger.warning("ArcRaiders: render text card failed: %s", exc)
            return None

    async def _load_items(self) -> list[dict[str, Any]]:
        now = time.time()
        if self._index_cache and now < self._index_expire_at:
            return self._index_cache

        index_url = str(self._config.get("index_url") or "").strip()
        timeout = int(self._config.get("request_timeout_sec", 12))

        payload = None
        if index_url.startswith("http://") or index_url.startswith("https://"):
            _status, payload = await self._http.request_payload(
                "GET",
                index_url,
                timeout=timeout,
            )
        else:
            path = Path(index_url)
            if not path.is_absolute():
                path = Path.cwd() / path
            payload = json.loads(await asyncio.to_thread(path.read_text, encoding="utf-8"))

        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            raise ValueError("invalid items index format")

        self._index_cache = [it for it in items if isinstance(it, dict)]
        ttl = int(self._config.get("cache_ttl_sec", 600))
        self._index_expire_at = now + ttl
        return self._index_cache

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"\s+", "", (text or "").strip().lower())

    def _search_items(self, items: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
        q = self._normalize(query)
        scored: list[tuple[int, dict[str, Any]]] = []

        for item in items:
            name = str(item.get("name") or "")
            name_search = str(item.get("nameSearch") or "")
            item_id = str(item.get("id") or "")
            n1 = self._normalize(name)
            n2 = self._normalize(name_search)
            n3 = self._normalize(item_id)

            score = -1
            if q == n1 or q == n2 or q == n3:
                score = 100
            elif q and (q in n1 or q in n2):
                score = 80
            elif q and q in n3:
                score = 70

            if score >= 0:
                scored.append((score, item))

        scored.sort(key=lambda x: (-x[0], len(str(x[1].get("name") or ""))))
        if not scored:
            return []

        best = scored[0][0]
        if best == 100:
            return [it for score, it in scored if score == 100][:1]
        return [it for _, it in scored]

    async def _fetch_drop_stats(self, item_id: str) -> dict[str, Any] | None:
        try:
            base = str(self._config.get("stats_api_base") or "").rstrip("/")
            timeout = int(self._config.get("request_timeout_sec", 12))
            status, data = await self._http.request_payload(
                "GET",
                f"{base}/{item_id}",
                timeout=timeout,
                raise_for_status=False,
            )
            if status != 200:
                return None
            return data if isinstance(data, dict) else None
        except Exception as exc:
            logger.debug("ArcRaiders: stats fetch failed: %s", exc)
            return None

    async def _fetch_locations(self, item_id: str) -> list[str]:
        try:
            base = str(self._config.get("item_page_base") or "").rstrip("/")
            timeout = int(self._config.get("request_timeout_sec", 12))
            _status, html = await self._http.request_text(
                "GET",
                f"{base}/{item_id}",
                timeout=timeout,
            )
            marker = "Can be found in</h3>"
            i = html.find(marker)
            if i < 0:
                return []
            block = html[i:i + 1200]
            found = re.findall(r"<span[^>]*>([^<]+)</span>", block)
            cleaned = []
            for name in found:
                v = re.sub(r"\s+", " ", name).strip()
                if v and v not in cleaned:
                    cleaned.append(v)
            return cleaned[:12]
        except Exception as exc:
            logger.debug("ArcRaiders: location parse failed: %s", exc)
            return []

    def _format_result(self, item: dict[str, Any], stats: dict[str, Any] | None, locations: list[str]) -> str:
        name = item.get("name") or "未知"
        item_id = item.get("id") or ""
        rarity = self._to_rarity_zh(str(item.get("rarity") or "未知"))
        item_type = self._to_type_zh(str(item.get("type") or "未知"))
        lines = [
            f"[{name}]",
            f"ID: {item_id}",
            f"类型/稀有度: {item_type} / {rarity}",
        ]

        if locations:
            lines.append("使用/产出场景: " + "、".join(locations))

        if stats:
            lines.extend(self._stats_lines(stats))
        else:
            lines.append("掉率: 暂无统计数据")

        lines.append(f"详情页: https://arctracker.io/zh-CN/items/{item_id}")
        return "\n".join(lines)

    def _stats_lines(self, stats: dict[str, Any]) -> list[str]:
        raw_overall = stats.get("overall")
        overall = raw_overall if isinstance(raw_overall, dict) else {}
        rate = overall.get("averageDropRate")
        sample = overall.get("totalSampleSize")
        conf = overall.get("confidence")
        lines: list[str] = []
        if isinstance(rate, (int, float)):
            lines.append(f"整体掉率: {rate * 100:.2f}%")
        if isinstance(sample, int):
            lines.append(f"样本量: {sample}")
        if conf:
            lines.append(f"可靠度: {conf}")
        lines.extend(self._format_all_map_rates(stats))
        return lines

    @staticmethod
    def _to_type_zh(value: str) -> str:
        return TYPE_ZH.get(value, value)

    @staticmethod
    def _to_rarity_zh(value: str) -> str:
        return RARITY_ZH.get(value, value)

    def _format_all_map_rates(self, stats: dict[str, Any]) -> list[str]:
        by_map = stats.get("byMap") if isinstance(stats.get("byMap"), list) else []
        if not by_map:
            return []

        entries = [m for m in by_map if isinstance(m, dict)]
        rate_by_id: dict[str, float] = {}
        for m in entries:
            mid = str(m.get("mapId") or "").strip()
            if not mid:
                continue
            rate_by_id[mid] = float(m.get("dropRate") or 0) * 100

        lines: list[str] = ["各地图掉率:"]
        ordered_ids = list(MAP_ZH.keys())
        for mid in ordered_ids:
            if mid in rate_by_id:
                lines.append(f"- {MAP_ZH[mid]}: {rate_by_id[mid]:.2f}%")

        # 补充未知映射但接口返回的其他地图，避免丢信息
        for mid, val in sorted(rate_by_id.items(), key=lambda x: x[1], reverse=True):
            if mid in MAP_ZH:
                continue
            lines.append(f"- {mid.replace('-', ' ')}: {val:.2f}%")
        return lines
