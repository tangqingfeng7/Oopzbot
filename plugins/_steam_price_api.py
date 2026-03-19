"""Steam 游戏价格查询 API 客户端 (IsThereAnyDeal + Steam Store)。"""

from __future__ import annotations

import re
from typing import Any, Optional

import requests

from logger_config import get_logger

logger = get_logger("SteamPriceApi")

_ITAD_BASE = "https://api.isthereanydeal.com"

_STEAM_SEARCH_URL = "https://store.steampowered.com/api/storesearch/"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36"
)

_HAS_CJK = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\u3040-\u30ff\uac00-\ud7af]")

STEAM_SHOP_ID = 61

# 常用游戏别名 -> Steam appid
# 允许用户用口语化名称精准匹配，key 统一小写
_GAME_ALIASES: dict[str, int] = {
    # --- GTA ---
    "gta5": 271590, "gta 5": 271590, "gta v": 271590,
    "侠盗猎车5": 271590, "侠盗猎车手5": 271590,
    # --- The Forest / Sons of the Forest ---
    "森林": 242760, "theforest": 242760, "the forest": 242760,
    "森林之子": 1326470, "sons of the forest": 1326470,
    # --- Elden Ring ---
    "老头环": 1245620, "艾尔登法环": 1245620, "法环": 1245620,
    "elden ring": 1245620,
    # --- Red Dead Redemption 2 ---
    "大表哥": 1174180, "大表哥2": 1174180, "大镖客": 1174180,
    "荒野大镖客": 1174180, "荒野大镖客2": 1174180, "rdr2": 1174180,
    # --- Cyberpunk 2077 ---
    "2077": 1091500, "赛博朋克": 1091500, "赛博朋克2077": 1091500,
    "cyberpunk": 1091500, "cyberpunk 2077": 1091500,
    # --- PUBG ---
    "吃鸡": 578080, "绝地求生": 578080, "pubg": 578080,
    # --- CS2 / CSGO ---
    "cs2": 730, "csgo": 730, "cs go": 730, "反恐精英": 730,
    # --- Dota 2 ---
    "dota2": 570, "dota 2": 570, "刀塔": 570, "刀塔2": 570,
    # --- Sekiro ---
    "只狼": 814380, "sekiro": 814380,
    # --- Dark Souls ---
    "黑魂": 570940, "黑魂3": 570940, "黑暗之魂3": 570940,
    "黑暗之魂": 570940, "dark souls 3": 570940,
    "黑魂1": 570940, "dark souls remastered": 211420,
    # --- Monster Hunter ---
    "怪猎": 582010, "怪猎世界": 582010, "怪物猎人": 582010,
    "怪物猎人世界": 582010, "mhw": 582010,
    "怪猎崛起": 1446780, "怪物猎人崛起": 1446780, "mhr": 1446780,
    "怪猎荒野": 2246340, "怪物猎人荒野": 2246340,
    # --- The Witcher 3 ---
    "巫师3": 292030, "巫师": 292030, "witcher 3": 292030,
    # --- Civilization ---
    "文明6": 289070, "文明7": 1295660, "civ6": 289070, "civ7": 1295660,
    # --- Terraria ---
    "泰拉瑞亚": 105600, "terraria": 105600,
    # --- Stardew Valley ---
    "星露谷": 413150, "星露谷物语": 413150, "stardew": 413150,
    # --- RimWorld ---
    "环世界": 294100, "rimworld": 294100,
    # --- Don't Starve ---
    "饥荒": 219740, "饥荒联机": 322330,
    "don't starve": 219740, "dst": 322330,
    # --- Baldur's Gate 3 ---
    "博德之门3": 1086940, "博德3": 1086940, "博德之门": 1086940,
    "bg3": 1086940, "baldurs gate 3": 1086940,
    # --- It Takes Two ---
    "双人成行": 1426210, "it takes two": 1426210,
    # --- Palworld ---
    "帕鲁": 1623730, "幻兽帕鲁": 1623730, "palworld": 1623730,
    # --- Black Myth: Wukong ---
    "黑神话": 2358720, "黑神话悟空": 2358720, "黑猴": 2358720,
    "悟空": 2358720, "black myth": 2358720,
    # --- Hollow Knight ---
    "空洞骑士": 367520, "hollow knight": 367520,
    # --- Death Stranding ---
    "死亡搁浅": 1190460, "death stranding": 1190460,
    # --- Ghost of Tsushima ---
    "对马岛": 2215430, "对马岛之魂": 2215430,
    # --- God of War ---
    "战神": 1593500, "战神4": 1593500, "god of war": 1593500,
    "战神5": 2322010, "战神诸神黄昏": 2322010,
    # --- The Last of Us ---
    "美末": 1888930, "最后生还者": 1888930,
    # --- Horizon ---
    "地平线": 1151640, "地平线零之曙光": 1151640,
    "地平线西之绝境": 2420110, "地平线2": 2420110,
    # --- Spider-Man ---
    "蜘蛛侠": 1817070, "漫威蜘蛛侠": 1817070,
    "蜘蛛侠2": 2654170, "漫威蜘蛛侠2": 2654170,
    # --- Detroit ---
    "底特律": 1222140, "底特律变人": 1222140,
    # --- Resident Evil ---
    "生化危机": 2050650, "生化4": 2050650, "生化危机4": 2050650,
    "生化8": 1196590, "生化危机8": 1196590, "生化村庄": 1196590,
    # --- Devil May Cry ---
    "鬼泣5": 601150, "鬼泣": 601150, "dmc5": 601150,
    # --- Persona ---
    "p5r": 1687950, "女神异闻录5": 1687950,
    "p3r": 2161700, "女神异闻录3": 2161700,
    # --- ARK ---
    "方舟": 346110, "ark": 346110,
    # --- Fall Guys ---
    "糖豆人": 1097150, "fall guys": 1097150,
    # --- Rainbow Six ---
    "彩虹六号": 359550, "彩六": 359550, "r6": 359550,
    # --- Human Fall Flat ---
    "人类一败涂地": 477160,
    # --- Overcooked ---
    "胡闹厨房": 448510, "煮糊了": 448510, "胡闹厨房2": 728880,
    # --- Oxygen Not Included ---
    "缺氧": 457140,
    # --- Dyson Sphere Program ---
    "戴森球": 1366540, "戴森球计划": 1366540,
    # --- Hades ---
    "哈迪斯": 1145360, "hades": 1145360,
    "哈迪斯2": 1145350, "hades 2": 1145350,
    # --- Celeste ---
    "蔚蓝": 504230, "celeste": 504230,
    # --- Disco Elysium ---
    "极乐迪斯科": 632470, "disco elysium": 632470,
    # --- Divinity ---
    "神界原罪2": 435150, "dos2": 435150,
    # --- Factorio ---
    "异星工厂": 427520, "factorio": 427520,
    # --- Satisfactory ---
    "幸福工厂": 526870, "satisfactory": 526870,
    # --- Subnautica ---
    "深海迷航": 264710, "subnautica": 264710,
    # --- Valheim ---
    "英灵神殿": 892970, "valheim": 892970,
    # --- Rust ---
    "腐蚀": 252490, "rust": 252490,
    # --- No Man's Sky ---
    "无人深空": 275850,
    # --- Dying Light 2 ---
    "消逝的光芒2": 534380, "dying light 2": 534380,
    # --- Atomic Heart ---
    "原子之心": 668580,
    # --- Lies of P ---
    "匹诺曹": 1627720, "匹诺曹的谎言": 1627720, "lies of p": 1627720,
    # --- Armored Core 6 ---
    "装甲核心6": 1888160, "ac6": 1888160,
    # --- Hogwarts Legacy ---
    "霍格沃茨": 990080, "霍格沃茨之遗": 990080,
    # --- Starfield ---
    "星空": 1716740, "starfield": 1716740,
    # --- Lethal Company ---
    "致命公司": 1966720, "lethal company": 1966720,
    # --- Content Warning ---
    "内容警告": 2881650,
    # --- Left 4 Dead 2 ---
    "求生之路2": 550, "l4d2": 550,
    # --- Dead by Daylight ---
    "黎明杀机": 381210, "dbd": 381210,
    # --- Phasmophobia ---
    "恐鬼症": 739630, "phasmophobia": 739630,
    # --- Manor Lords ---
    "庄园领主": 1363080,
    # --- Cities: Skylines 2 ---
    "城市天际线2": 949230, "天际线2": 949230,
    "城市天际线": 255710, "天际线": 255710,
    # --- Euro Truck Simulator 2 ---
    "欧卡2": 227300, "欧洲卡车模拟2": 227300, "ets2": 227300,
    # --- American Truck Simulator ---
    "美卡": 270880, "美国卡车模拟": 270880,
    # --- Metaphor: ReFantazio ---
    "暗喻幻想": 2679460, "metaphor": 2679460,
}


def _contains_cjk(text: str) -> bool:
    return bool(_HAS_CJK.search(text))


def _resolve_alias(keyword: str) -> Optional[int]:
    """检查关键词是否匹配已知别名，返回 Steam appid 或 None。"""
    normalized = keyword.strip().lower()
    return _GAME_ALIASES.get(normalized)


class SteamPriceApiClient:
    """IsThereAnyDeal API 封装，提供游戏搜索、价格查询和史低查询能力。

    需要在 https://isthereanydeal.com/apps/my/ 注册应用获取免费 API Key。
    """

    def __init__(self, config: dict, session: Optional[requests.Session] = None) -> None:
        self._config = config or {}
        self._api_key = str(self._config.get("api_key") or "").strip()
        self._country = str(self._config.get("country") or "CN").strip().upper()
        self._timeout = max(1, int(self._config.get("request_timeout_sec", 15) or 15))
        self._retries = max(1, int(self._config.get("request_retries", 2) or 2))
        proxy = str(self._config.get("proxy") or "").strip()
        self._proxies: dict[str, str] | None = {"http": proxy, "https": proxy} if proxy else None
        self._session = session or requests.Session()

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    # ------------------------------------------------------------------
    # 通用请求
    # ------------------------------------------------------------------

    def _get(self, url: str, params: Optional[dict[str, Any]] = None) -> Any:
        params = params or {}
        last_error = ""
        for attempt in range(1, self._retries + 1):
            try:
                resp = self._session.get(
                    url, params=params,
                    headers={"User-Agent": _UA},
                    timeout=self._timeout, proxies=self._proxies,
                )
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException as exc:
                last_error = str(exc)
                logger.warning("SteamPriceApi GET %s attempt %d: %s", url, attempt, exc)
            except ValueError as exc:
                return {"_error": f"JSON 解析失败: {exc}"}
        return {"_error": last_error}

    def _post_json(self, url: str, body: Any, params: Optional[dict[str, Any]] = None) -> Any:
        params = params or {}
        last_error = ""
        for attempt in range(1, self._retries + 1):
            try:
                resp = self._session.post(
                    url, json=body, params=params,
                    headers={"User-Agent": _UA, "Content-Type": "application/json"},
                    timeout=self._timeout, proxies=self._proxies,
                )
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException as exc:
                last_error = str(exc)
                logger.warning("SteamPriceApi POST %s attempt %d: %s", url, attempt, exc)
            except ValueError as exc:
                return {"_error": f"JSON 解析失败: {exc}"}
        return {"_error": last_error}

    # ------------------------------------------------------------------
    # Steam Store 搜索 (无需 API Key，支持中文)
    # ------------------------------------------------------------------

    def search_steam(self, keyword: str, limit: int = 5) -> list[dict]:
        """通过 Steam Store API 搜索游戏，返回 [{appid, name}, ...]。"""
        data = self._get(_STEAM_SEARCH_URL, params={
            "term": keyword, "l": "schinese", "cc": "cn",
        })
        if isinstance(data, dict) and data.get("_error"):
            return []
        items = data.get("items") if isinstance(data, dict) else []
        if not isinstance(items, list):
            return []
        results: list[dict] = []
        for item in items[:limit]:
            if not isinstance(item, dict):
                continue
            appid = item.get("id")
            if not appid:
                continue
            price_info = item.get("price") or {}
            results.append({
                "appid": int(appid),
                "name": str(item.get("name") or ""),
                "steam_price_final": (price_info.get("final") or 0) / 100.0 if price_info else None,
                "steam_price_initial": (price_info.get("initial") or 0) / 100.0 if price_info else None,
            })
        return results

    # ------------------------------------------------------------------
    # ITAD: 搜索 / Lookup
    # ------------------------------------------------------------------

    def itad_search(self, title: str, limit: int = 5) -> list[dict]:
        """通过 ITAD 搜索游戏，返回 [{id, title, slug, type}, ...]。"""
        if not self._api_key:
            return []
        data = self._get(f"{_ITAD_BASE}/games/search/v1", params={
            "key": self._api_key, "title": title, "results": limit,
        })
        if isinstance(data, dict) and data.get("_error"):
            return []
        if not isinstance(data, list):
            return []
        return [
            {
                "id": str(item.get("id") or ""),
                "title": str(item.get("title") or ""),
                "slug": str(item.get("slug") or ""),
                "type": str(item.get("type") or "game"),
            }
            for item in data
            if isinstance(item, dict) and item.get("id")
        ][:limit]

    def itad_lookup_by_appid(self, appid: int) -> Optional[dict]:
        """通过 Steam appid 查找 ITAD 游戏条目。"""
        if not self._api_key:
            return None
        data = self._get(f"{_ITAD_BASE}/games/lookup/v1", params={
            "key": self._api_key, "appid": appid,
        })
        if not isinstance(data, dict) or not data.get("found"):
            return None
        game = data.get("game")
        if not isinstance(game, dict) or not game.get("id"):
            return None
        return {
            "id": str(game["id"]),
            "title": str(game.get("title") or ""),
            "slug": str(game.get("slug") or ""),
            "type": str(game.get("type") or "game"),
        }

    def itad_get_steam_appids(self, itad_ids: list[str]) -> dict[str, int]:
        """通过 ITAD game IDs 反查 Steam appid (shop_id=61)。

        响应格式: {itad_id: ["app/12345", "sub/67890"], ...}
        只提取 "app/" 前缀的条目作为 appid。
        """
        if not itad_ids:
            return {}
        data = self._post_json(
            f"{_ITAD_BASE}/lookup/shop/{STEAM_SHOP_ID}/id/v1",
            body=itad_ids[:200],
            params={"key": self._api_key} if self._api_key else {},
        )
        if isinstance(data, dict) and data.get("_error"):
            return {}
        if not isinstance(data, dict):
            return {}
        result: dict[str, int] = {}
        for itad_id, ids in data.items():
            if not isinstance(ids, list):
                continue
            for entry in ids:
                if isinstance(entry, str) and entry.startswith("app/"):
                    try:
                        result[itad_id] = int(entry[4:])
                        break
                    except (TypeError, ValueError):
                        pass
        return result

    # ------------------------------------------------------------------
    # ITAD: 价格概览 (当前最低价 + 历史低价)
    # ------------------------------------------------------------------

    def itad_price_overview(self, game_ids: list[str]) -> dict[str, dict]:
        """批量查询 ITAD 价格概览。"""
        if not self._api_key or not game_ids:
            return {}
        batch_size = 200
        result: dict[str, dict] = {}
        for i in range(0, len(game_ids), batch_size):
            chunk = game_ids[i:i + batch_size]
            data = self._post_json(
                f"{_ITAD_BASE}/games/overview/v2",
                body=chunk,
                params={"key": self._api_key, "country": self._country},
            )
            if isinstance(data, dict) and data.get("_error"):
                logger.warning("SteamPriceApi: overview error: %s", data["_error"])
                continue
            prices = data.get("prices") if isinstance(data, dict) else data
            if not isinstance(prices, list):
                continue
            for entry in prices:
                if not isinstance(entry, dict):
                    continue
                gid = str(entry.get("id") or "")
                if not gid:
                    continue
                result[gid] = self._parse_overview_entry(entry)
        return result

    # ------------------------------------------------------------------
    # ITAD: 全局史低
    # ------------------------------------------------------------------

    def itad_history_low(self, game_ids: list[str]) -> dict[str, dict]:
        """批量查询 ITAD 全网历史最低价。"""
        if not self._api_key or not game_ids:
            return {}
        data = self._post_json(
            f"{_ITAD_BASE}/games/historylow/v1",
            body=game_ids[:200],
            params={"key": self._api_key, "country": self._country},
        )
        if isinstance(data, dict) and data.get("_error"):
            return {}
        if not isinstance(data, list):
            return {}
        result: dict[str, dict] = {}
        for entry in data:
            if not isinstance(entry, dict):
                continue
            gid = str(entry.get("id") or "")
            low = entry.get("low") if isinstance(entry.get("low"), dict) else {}
            if not gid or not low:
                continue
            price_info = low.get("price") or {}
            result[gid] = {
                "price": float(price_info.get("amount") or 0),
                "cut": int(low.get("cut") or 0),
                "shop": str((low.get("shop") or {}).get("name") or ""),
                "timestamp": str(low.get("timestamp") or ""),
            }
        return result

    # ------------------------------------------------------------------
    # 组合查询：搜索 + 价格 (一次调用完成)
    # ------------------------------------------------------------------

    def search_and_price(self, keyword: str) -> Optional[dict]:
        """搜索游戏并返回完整的价格信息。

        中文关键词优先走 Steam Store 搜索（对中文友好），再通过 ITAD lookup 关联。
        英文关键词优先走 ITAD 搜索。
        """
        game_info = self._resolve_game(keyword)
        if not game_info:
            return None

        itad_id = game_info.get("itad_id") or ""
        if not itad_id:
            return game_info

        overview = self.itad_price_overview([itad_id])
        price_data = overview.get(itad_id, {})

        history = self.itad_history_low([itad_id])
        history_data = history.get(itad_id, {})

        if not game_info.get("appid"):
            appids = self.itad_get_steam_appids([itad_id])
            if itad_id in appids:
                game_info["appid"] = appids[itad_id]

        game_info.update({
            "current_price": price_data.get("current_price"),
            "current_cut": price_data.get("current_cut", 0),
            "current_shop": price_data.get("current_shop", ""),
            "regular_price": price_data.get("regular_price"),
            "lowest_price": price_data.get("lowest_price"),
            "lowest_cut": price_data.get("lowest_cut", 0),
            "lowest_shop": price_data.get("lowest_shop", ""),
            "lowest_date": price_data.get("lowest_date", ""),
            "history_low_price": history_data.get("price"),
            "history_low_cut": history_data.get("cut", 0),
            "history_low_shop": history_data.get("shop", ""),
            "history_low_date": history_data.get("timestamp", ""),
            "currency": price_data.get("currency", ""),
        })
        return game_info

    def _resolve_game(self, keyword: str) -> Optional[dict]:
        """解析关键词为游戏信息。

        优先级: 别名精准匹配 -> 中文走 Steam 搜索 -> 英文走 ITAD 搜索 -> Steam 回退
        """
        alias_appid = _resolve_alias(keyword)
        if alias_appid is not None:
            return self._resolve_by_appid(alias_appid)

        if _contains_cjk(keyword):
            return self._resolve_via_steam(keyword)

        itad_results = self.itad_search(keyword, limit=5)
        if itad_results:
            first = itad_results[0]
            return {
                "itad_id": first["id"],
                "title": first["title"],
                "slug": first["slug"],
                "type": first["type"],
                "appid": None,
                "others": itad_results[1:],
            }

        return self._resolve_via_steam(keyword)

    def _resolve_by_appid(self, appid: int) -> Optional[dict]:
        """通过 Steam appid 直接查找 ITAD 信息。"""
        itad_info = self.itad_lookup_by_appid(appid)
        itad_id = itad_info["id"] if itad_info else ""
        title = (itad_info.get("title") or "") if itad_info else ""

        if not title:
            steam_results = self.search_steam(str(appid), limit=1)
            if steam_results:
                title = steam_results[0].get("name") or ""

        return {
            "itad_id": itad_id,
            "title": title or f"App {appid}",
            "slug": itad_info.get("slug", "") if itad_info else "",
            "type": itad_info.get("type", "game") if itad_info else "game",
            "appid": appid,
            "others": [],
        }

    def _resolve_via_steam(self, keyword: str) -> Optional[dict]:
        """通过 Steam Store 搜索再关联 ITAD。"""
        steam_results = self.search_steam(keyword, limit=5)
        if not steam_results:
            return None

        first = steam_results[0]
        appid = first["appid"]

        itad_info = self.itad_lookup_by_appid(appid)
        itad_id = itad_info["id"] if itad_info else ""
        itad_title = itad_info.get("title", "") if itad_info else ""

        title = first["name"]
        if itad_title and itad_title != title:
            title = f"{first['name']} ({itad_title})"

        return {
            "itad_id": itad_id,
            "title": title,
            "slug": itad_info.get("slug", "") if itad_info else "",
            "type": itad_info.get("type", "game") if itad_info else "game",
            "appid": appid,
            "steam_price_final": first.get("steam_price_final"),
            "steam_price_initial": first.get("steam_price_initial"),
            "others": [
                {"title": s["name"], "appid": s["appid"]}
                for s in steam_results[1:]
            ],
        }

    # ------------------------------------------------------------------
    # 内部解析
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_overview_entry(entry: dict) -> dict:
        current = entry.get("current") if isinstance(entry.get("current"), dict) else {}
        lowest = entry.get("lowest") if isinstance(entry.get("lowest"), dict) else {}

        def _extract(block: dict) -> tuple[Optional[float], int, str, str, Optional[float], str]:
            if not block:
                return None, 0, "", "", None, ""
            price_obj = block.get("price") or {}
            regular_obj = block.get("regular") or {}
            amount = price_obj.get("amount")
            regular = regular_obj.get("amount")
            cut = int(block.get("cut") or 0)
            shop = str((block.get("shop") or {}).get("name") or "")
            currency = str(price_obj.get("currency") or "")
            timestamp = str(block.get("timestamp") or "")
            return (
                float(amount) if amount is not None else None,
                cut, shop, currency,
                float(regular) if regular is not None else None,
                timestamp,
            )

        c_price, c_cut, c_shop, c_currency, c_regular, _ = _extract(current)
        l_price, l_cut, l_shop, _, _, l_timestamp = _extract(lowest)

        return {
            "current_price": c_price,
            "current_cut": c_cut,
            "current_shop": c_shop,
            "regular_price": c_regular,
            "lowest_price": l_price,
            "lowest_cut": l_cut,
            "lowest_shop": l_shop,
            "lowest_date": l_timestamp,
            "currency": c_currency,
        }
