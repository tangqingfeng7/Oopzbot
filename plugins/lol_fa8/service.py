import asyncio
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie

from yarl import URL

from core.async_http import ManagedHttpClient
from core.constants import USER_AGENT, Msg
from core.logger_config import get_logger

logger = get_logger("FA8")

BASE_URL = "https://fa.3ui.cc"
_API_SIGN_KEY = b"4d3627c36a294272ae24b1069bcd992234349f96a9144bc6b4f2620eda8d70e6"
_CST = timezone(timedelta(hours=8))
_LOGIN_HELP = "请在 https://fa.3ui.cc 完成登录验证，并更新 FA8 插件的 session_cookie"


def _default_config() -> dict:
    from plugins.lol_fa8 import LolFa8Plugin

    return {field.name: field.default for field in LolFa8Plugin().config_spec.fields}


SERVERS = {
    "1": "艾欧尼亚", "2": "比尔吉沃特", "3": "祖安", "4": "诺克萨斯",
    "5": "班德尔城", "6": "德玛西亚", "7": "皮尔特沃夫", "8": "战争学院",
    "9": "弗雷尔卓德", "10": "巨神峰", "11": "雷瑟守备", "12": "无畏先锋",
    "13": "裁决之地", "14": "黑色玫瑰", "15": "暗影岛", "16": "恕瑞玛",
    "17": "钢铁烈阳", "18": "水晶之痕", "19": "均衡教派", "20": "扭曲丛林",
    "21": "教育网专区", "22": "影流", "23": "守望之海", "24": "征服之海",
    "25": "卡拉曼达", "26": "巨龙之巢", "27": "皮城警备", "30": "男爵领域",
    "31": "峡谷之巅",
}

SERVER_NAME_TO_ID = {v: k for k, v in SERVERS.items()}

SERVER_GROUPS: dict[str, list[str]] = {
    "一区": ["3", "7", "10", "19", "21", "22", "23", "30"],
    "二区": ["4", "8", "11", "15", "24", "25"],
    "三区": ["5", "13", "17", "18", "27"],
    "四区": ["2", "9", "20"],
    "五区": ["6", "12", "16", "26"],
}

GROUP_ALIASES: dict[str, str] = {}
_NUM_MAP = {"一区": "1", "二区": "2", "三区": "3", "四区": "4", "五区": "5"}
for _g in SERVER_GROUPS:
    GROUP_ALIASES[_g] = _g
    GROUP_ALIASES[f"联盟{_g}"] = _g
    if _g in _NUM_MAP:
        GROUP_ALIASES[_NUM_MAP[_g]] = _g


_CHAMPION_NAMES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "champion_names.json")

with open(_CHAMPION_NAMES_PATH, encoding="utf-8") as _f:
    CHAMPION_EN_TO_CN: dict[str, str] = json.load(_f)


def _champion_cn(en_key: str) -> str:
    """将英雄英文 ID 转为中文名，未知则返回原样"""
    if not en_key:
        return en_key
    key = en_key.strip()
    if key in CHAMPION_EN_TO_CN:
        return CHAMPION_EN_TO_CN[key]
    # 兼容小写或首字母大写的 key（如 neeko -> Neeko）
    key_alt = key[0].upper() + key[1:].lower() if len(key) > 1 else key.upper()
    return CHAMPION_EN_TO_CN.get(key_alt, en_key)


def now_cst() -> datetime:
    """当前东八区时间。"""
    return datetime.now(_CST)


def _won(game: dict) -> bool:
    return bool((game.get("player") or {}).get("win", game.get("win")))


def _outcome(win: object) -> str:
    return "胜利" if win else "失败"


def _sign_api(action: str, values: list[str], timestamp: str, nonce: str) -> dict[str, str]:
    """按 FA8ApiSign.create 的字段顺序签名。"""
    message = "\n".join([action, *values, timestamp, nonce])
    return {
        "api_timestamp": timestamp,
        "api_nonce": nonce,
        "api_sign": hmac.new(_API_SIGN_KEY, message.encode("utf-8"), hashlib.sha256).hexdigest(),
    }


def _format_date(value) -> str:
    if not value:
        return "未知"
    stamp = float(value)
    if stamp <= 0:
        return "未知"
    if stamp > 100_000_000_000:
        stamp /= 1000
    return datetime.fromtimestamp(stamp, _CST).strftime("%Y-%m-%d %H:%M")


def _area_name(area: str) -> str:
    for group, members in SERVER_GROUPS.items():
        if area in members:
            return f"联盟{group}"
    return SERVERS[area]


class FA8Client:
    """FA8 JSON API 客户端，复用登录会话并按服务器时间签名。"""

    def __init__(self, username: str = "", password: str = "", session_cookie: str = ""):
        self._user = (username or "").strip()
        self._pwd = password or ""
        self._cookie = (session_cookie or "").strip()
        self._http = ManagedHttpClient(headers={
            "User-Agent": USER_AGENT,
            "Origin": BASE_URL,
            "Referer": f"{BASE_URL}/",
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "X-FA8-Client": "desktop",
        })
        self._logged_in = False
        self._lock = asyncio.Lock()
        self._query_lock = asyncio.Lock()
        self._time_lock = asyncio.Lock()
        self._time_offset: float | None = None
        self._login_error = {"code": -1, "message": _LOGIN_HELP}

    async def _request(self, method: str, endpoint: str, data: dict | None = None, cookie: str | None = None) -> dict:
        headers: dict[str, str] = {}
        active_cookie = cookie if cookie is not None else self._cookie
        if active_cookie:
            headers["Cookie"] = active_cookie
        try:
            if active_cookie:
                session = await self._http.session()
                session.cookie_jar.update_cookies(SimpleCookie(active_cookie), response_url=URL(BASE_URL))
            status, result = await self._http.request_payload(
                method, f"{BASE_URL}/api/{endpoint}", data=data, headers=headers,
                timeout=15, raise_for_status=False,
            )
            if not isinstance(result, dict):
                return {"code": -1, "message": "FA8 响应格式错误"}
            if status >= 400 and result.get("code") == 0:
                return {"code": -1, "message": f"FA8 请求失败 (HTTP {status})"}
            return result
        except Exception as exc:
            logger.warning("FA8 请求失败 [%s]: %s", endpoint, exc)
            return {"code": -1, "message": f"FA8 请求异常: {exc}"}

    async def _try_cookie(self, cookie: str) -> bool:
        status = await self._request("GET", "user.php?act=status", cookie=cookie)
        return status.get("code") == 0 and bool((status.get("data") or {}).get("logged_in"))

    async def _jar_sign_cookie(self) -> str:
        """读取登录后 aiohttp cookie jar 中写入的 sign 会话。"""
        try:
            session = await self._http.session()
            for cookie in session.cookie_jar:
                if cookie.key == "sign" and cookie.value:
                    return f"sign={cookie.value}"
        except Exception:
            pass
        return ""

    async def _ensure_login(self) -> bool:
        if self._logged_in:
            return True
        async with self._lock:
            if self._logged_in:
                return True
            # 1) 显式 session_cookie
            if self._cookie and await self._try_cookie(self._cookie):
                self._logged_in = True
                return True
            # 2) 用户名密码登录（登录要求极验时失败，提示更新 Cookie）
            if self._user and self._pwd:
                result = await self._request("POST", "user.php?act=login", {
                    "account": self._user, "password": self._pwd,
                })
                if result.get("code") == 0:
                    jar_cookie = await self._jar_sign_cookie()
                    if jar_cookie:
                        self._cookie = jar_cookie
                    self._logged_in = True
                    return True
                if result.get("data", {}).get("field") == "captcha":
                    result = {**result, "message": _LOGIN_HELP}
                self._login_error = result
            self._login_error = self._login_error or {"code": -1, "message": _LOGIN_HELP}
            return False

    async def _sync_time(self) -> None:
        _status, html = await self._http.request_text("GET", f"{BASE_URL}/", timeout=15)
        match = re.search(r'data-server-time="(\d+)"', html)
        if not match:
            raise ValueError("FA8 页面未提供服务器时间")
        self._time_offset = int(match.group(1)) / 1000 - time.time()

    async def _post_api(self, action: str, fields: dict[str, str], retry: bool = True) -> dict:
        async with self._query_lock:
            return await self._signed_query(action, fields, retry)

    async def _signed_query(self, action: str, fields: dict[str, str], retry: bool) -> dict:
        if not await self._ensure_login():
            return self._login_error
        try:
            retry_login = retry_time = retry
            while True:
                async with self._time_lock:
                    if self._time_offset is None:
                        await self._sync_time()
                timestamp = str(int(time.time() + (self._time_offset or 0)))
                data = {**fields, **_sign_api(
                    action, list(fields.values()), timestamp, secrets.token_hex(16),
                )}
                result = await self._request("POST", f"api.php?act={action}", data)
                detail = result.get("data") or {}
                if detail.get("login_required") or detail.get("expired"):
                    self._logged_in = False
                    if retry_login:
                        retry_login = False
                        if await self._ensure_login():
                            continue
                        return self._login_error
                    return {**result, "message": _LOGIN_HELP}
                if detail.get("sign_expired") and retry_time:
                    retry_time = False
                    async with self._time_lock:
                        await self._sync_time()
                    continue
                return result
        except Exception as exc:
            logger.warning("FA8 签名请求失败 [%s]: %s", action, exc)
            return {"code": -1, "message": f"FA8 请求异常: {exc}"}

    async def find_player(self, game_name: str, tag_line: str) -> dict:
        return await self._post_api("check", {"game_name": game_name, "tag_line": tag_line})

    async def query_summoner(self, puuid: str, region: str) -> dict:
        return await self._post_api("summoner", {"puuid": puuid, "re": region})

    async def query_games(self, puuid: str, region: str, tag: str = "", start: int = 0) -> dict:
        return await self._post_api("matches", {
            "puuid": puuid, "re": region, "start": str(start), "tag": tag,
        })

    async def stop(self) -> None:
        await self._http.close()


class FA8Handler:
    """FA8 战绩查询命令处理器。"""

    def __init__(self, config: dict | None = None):
        self._config = _default_config()
        if config:
            self._config.update(config)
        self._client = FA8Client(
            username=self._config.get("username", ""),
            password=self._config.get("password", ""),
            session_cookie=self._config.get("session_cookie", ""),
        )
        self._query_cache: dict[tuple, tuple[float, dict]] = {}
        self._pending_queries: dict[tuple, asyncio.Task] = {}

    async def close(self) -> None:
        pending = list(self._pending_queries.values())
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        self._query_cache.clear()
        await self._client.stop()

    def _resolve_area(self, text: str) -> tuple[str, list[str]]:
        """解析可选的大区限制，未指定时由站点识别大区。"""
        text = text.strip()
        parts = text.split(None, 1)
        if len(parts) == 2:
            prefix = parts[0]
            if prefix in GROUP_ALIASES:
                return parts[1], SERVER_GROUPS[GROUP_ALIASES[prefix]]
            if prefix in SERVERS:
                return parts[1], [prefix]
            if prefix in SERVER_NAME_TO_ID:
                return parts[1], [SERVER_NAME_TO_ID[prefix]]
        for server_name, server_id in SERVER_NAME_TO_ID.items():
            if text.startswith(server_name):
                name = text[len(server_name):].strip()
                if name:
                    return name, [server_id]
        return text, []

    async def query(self, raw_input: str, *, refresh: bool = False) -> dict | str:
        name, areas = self._resolve_area(raw_input)
        match = re.fullmatch(r"([^#]+?)\s*#\s*([0-9]+)", name)
        if not self._config.get("enabled", False) or not match or not match.group(1).strip():
            return await self._query_uncached(raw_input)
        key = (match.group(1).strip(), match.group(2), tuple(sorted(areas)))
        now = time.monotonic()
        self._query_cache = {key: value for key, value in self._query_cache.items() if value[0] > now}
        cached = self._query_cache.get(key)
        if cached is not None and not refresh:
            return deepcopy(cached[1])
        task = self._pending_queries.get(key)
        if task is None:
            task = asyncio.create_task(self._fetch_query(key, raw_input))
            self._pending_queries[key] = task
        return deepcopy(await asyncio.shield(task))

    async def _fetch_query(self, key: tuple, raw_input: str) -> dict | str:
        try:
            result = await self._query_uncached(raw_input)
            if isinstance(result, dict):
                result["queried_at"] = now_cst().strftime("%Y-%m-%d %H:%M:%S")
                info = result["info"]
                if result["games_response"].get("code") == 0 and not any(
                    info.get(field) for field in ("rank_error", "player_assets_error", "champion_mastery_error")
                ):
                    if len(self._query_cache) >= 128:
                        self._query_cache.pop(next(iter(self._query_cache)))
                    self._query_cache[key] = (time.monotonic() + 45, result)
                else:
                    self._query_cache.pop(key, None)
            else:
                self._query_cache.pop(key, None)
            return result
        finally:
            self._pending_queries.pop(key, None)

    async def _query_uncached(self, raw_input: str) -> dict | str:
        if not self._config.get("enabled", False):
            return "战绩查询功能未启用，请在 config/plugins/lol_fa8/config.json 中配置"
        name, areas = self._resolve_area(raw_input)
        match = re.fullmatch(r"([^#]+?)\s*#\s*([0-9]+)", name)
        if not match or not match.group(1).strip():
            return "请输入召唤师名#数字编号，例如: /zj 艺术就是充钱丶#72269"
        game_name, tag_line = match.group(1).strip(), match.group(2)
        checked = await self._client.find_player(game_name, tag_line)
        if checked.get("code") != 0:
            return f"{Msg.ERR} 查询失败: {checked.get('message', 'FA8 查询失败')}"
        player = checked.get("data") or {}
        if not player.get("exists"):
            return f"{Msg.ERR} 未找到玩家 {game_name}#{tag_line}"
        puuid, region = player.get("puuid"), player.get("re")
        if not puuid or not region:
            return f"{Msg.ERR} FA8 未返回玩家标识或大区"
        response = await self._client.query_summoner(puuid, region)
        if response.get("code") != 0:
            return f"{Msg.ERR} 资料查询失败: {response.get('message', 'FA8 查询失败')}"
        info = response.get("data") or {}
        server_name = (info.get("region") or {}).get("name") or region
        if areas and server_name not in [_area_name(area) for area in areas]:
            expected = "、".join(dict.fromkeys(_area_name(area) for area in areas))
            return f"{Msg.ERR} 该玩家位于{server_name}，与指定大区（{expected}）不符"
        alias = info.get("alias") or {}
        display_name = alias.get("game_name") or player.get("game_name") or game_name
        display_tag = alias.get("tag_line") or player.get("tag_line") or tag_line
        games_response = await self._client.query_games(puuid, region)
        return {
            "server_name": server_name,
            "game_name": display_name,
            "tag_line": display_tag,
            "info": info,
            "games_response": games_response,
        }

    async def query_and_format(self, raw_input: str) -> str:
        result = await self.query(raw_input)
        return result if isinstance(result, str) else self.format_result(result)

    @staticmethod
    def format_result(result: dict) -> str:
        info = result["info"]
        server_name = result["server_name"]
        display_name, display_tag = result["game_name"], result["tag_line"]
        summoner = info.get("summoner") or {}
        lines = [
            f"LOL 战绩查询 - {server_name}", "═══════════════════",
            f"  召唤师: {display_name}#{display_tag}",
            f"  等级: {summoner.get('level', '?')}",
            f"  最近游戏: {_format_date(summoner.get('lastGameDate') or summoner.get('revisionDate'))}",
        ]
        assets = info.get("player_assets")
        if assets:
            lines.append(f"  英雄: {assets.get('heroes', '?')} 个 | 皮肤: {assets.get('skins', '?')} 个")
        elif info.get("player_assets_error"):
            lines.append(f"  玩家资产读取失败: {info['player_assets_error']}")
        lines.extend(["───────────────────", "  段位信息:"])
        if info.get("rank_error"):
            lines.append(f"    段位读取失败: {info['rank_error']}")
        else:
            queues = (info.get("ranked_stats") or {}).get("queues") or []
            ranks = {rank.get("queueType", "").upper(): rank for rank in queues}
            for queue, label in (("RANKED_SOLO_5X5", "单双排位"), ("RANKED_FLEX_SR", "灵活排位")):
                rank = ranks.get(queue)
                if not rank:
                    lines.append(f"    {label}: 未定级 / 无段位")
                    continue
                tier = " ".join(str(rank[key]) for key in ("tier_label", "rank_label") if rank.get(key))
                lines.append(
                    f"    {label}: {tier or '未定级'} "
                    f"({rank.get('wins', 0)}胜{rank.get('losses', 0)}负) 胜点{rank.get('leaguePoints', 0)}"
                )
                best = " ".join(str(rank[key]) for key in (
                    "highest_tier_label", "highest_rank_label",
                ) if rank.get(key))
                if best:
                    lines.append(f"    {label}最高: {best}")
        champions = sorted(info.get("champion_mastery") or [], key=lambda c: (
            c.get("points") or 0, c.get("level") or 0,
        ), reverse=True)
        if champions:
            lines.extend(["───────────────────", "  英雄熟练度 TOP5:"])
            for i, champion in enumerate(champions[:5], 1):
                lines.append(
                    f"    {i}. {champion.get('name', '未知英雄')} - "
                    f"{champion.get('level', 0)}级英雄成就 ({champion.get('points', 0):,})"
                )
        elif info.get("champion_mastery_error"):
            lines.append(f"  英雄熟练度读取失败: {info['champion_mastery_error']}")
        games_response = result["games_response"]
        lines.append("───────────────────")
        if games_response.get("code") != 0:
            lines.append(f"  战绩读取失败: {games_response.get('message', 'FA8 查询失败')}")
        else:
            games = (games_response.get("data") or {}).get("games") or []
            if not games:
                lines.append("  暂无近期战绩")
            else:
                wins = sum(_won(game) for game in games)
                lines.append(f"  近期战绩: {wins}胜 {len(games) - wins}负 (胜率{wins / len(games):.0%})")
                lines.append("  最近对局:")
                for game in games[:5]:
                    participant = game.get("player") or {}
                    outcome = game.get("result") or _outcome(_won(game))
                    champion = participant.get("champion_title") or _champion_cn(
                        participant.get("champion_name") or "未知英雄"
                    )
                    kda = "/".join(str(participant.get(key, 0)) for key in ("kills", "deaths", "assists"))
                    duration = int(game.get("duration") or 0)
                    minutes, seconds = divmod(duration, 60)
                    lines.append(
                        f"    {outcome} {game.get('mode', '')} {champion} {kda} "
                        f"[{minutes}:{seconds:02d}] {_format_date(game.get('created_at'))}"
                    )
        lines.append("═══════════════════")
        return "\n".join(lines)
