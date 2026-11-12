from __future__ import annotations

import asyncio
import base64
import functools
import tempfile
from datetime import datetime
from html import escape
from pathlib import Path
from string import Template

import aiohttp

from core.async_http import ManagedHttpClient
from core.logger_config import get_logger
from core.paths import PROJECT_ROOT_PATH
from plugins._shared.browser import HeadlessBrowser

from .service import CHAMPION_EN_TO_CN, _champion_cn, _format_date, _outcome, _won, now_cst

_TEMPLATES_DIR = Path(__file__).with_name("templates")
_BROWSER = HeadlessBrowser()
_HTTP = ManagedHttpClient()
_CHAMPION_KEY_BY_LOWER = {key.lower(): key for key in CHAMPION_EN_TO_CN}
_CHAMPION_KEY_BY_LABEL = {label: key for key, label in CHAMPION_EN_TO_CN.items()}
_DDRAGON_VERSION = "16.22.1"
_RANKS = {
    "iron": "黑铁", "bronze": "黄铜", "silver": "白银", "gold": "黄金",
    "platinum": "铂金", "emerald": "翡翠", "diamond": "钻石", "master": "大师",
    "grandmaster": "宗师", "challenger": "王者",
}
logger = get_logger("FA8Render")


def _text(value) -> str:
    return escape(str(value))


@functools.cache
def load_template(name: str) -> Template:
    return Template((_TEMPLATES_DIR / name).read_text(encoding="utf-8"))


def _champion_key(name: str) -> str:
    return _CHAMPION_KEY_BY_LOWER.get(name.lower()) or _CHAMPION_KEY_BY_LABEL.get(name, "")


def _rank_key(rank: dict) -> str:
    tier = str(rank.get("tier") or "").lower()
    if tier in _RANKS:
        return tier
    label = str(rank.get("tier_label") or "")
    return next((key for key, name in _RANKS.items() if name in label), "unranked")


def _mastery_champions(info: dict) -> list[dict]:
    return sorted(info.get("champion_mastery") or [], key=lambda c: (
        c.get("points") or 0, c.get("level") or 0,
    ), reverse=True)[:5]


def _picture(key: str, images: dict[str, str], css: str, label: str) -> str:
    source = images.get(key)
    if source:
        return f'<img class="{css}" src="{_text(source)}" alt="{_text(label)}">'
    return f'<span class="{css} placeholder" aria-label="{_text(label)}">{_text(label[:1])}</span>'


async def load_card_images(result: dict) -> dict[str, str]:
    """按需缓存英雄头像和段位徽章，将图像嵌入截图 HTML。"""
    detail = result.get("detail_game")
    info = {} if detail is not None else result["info"]
    games = [detail] if detail is not None else (result["games_response"].get("data") or {}).get("games") or []
    champions = {
        _champion_key(str((game.get("player") or {}).get("champion_name")
                          or (game.get("player") or {}).get("champion_title") or ""))
        for game in games[:5]
    }
    champions.update(_champion_key(str(champion.get("name") or "")) for champion in _mastery_champions(info))
    ranks = (info.get("ranked_stats") or {}).get("queues") or []
    tiers = set() if detail is not None else {_rank_key(rank) for rank in ranks} | {"unranked"}
    assets = {
        f"champion:{key}": (
            f"https://ddragon.leagueoflegends.com/cdn/{_DDRAGON_VERSION}/img/champion/{key}.png",
            f"champions/{_DDRAGON_VERSION}/{key}.png",
        ) for key in champions if key
    }
    assets.update({
        f"rank:{tier}": (
            f"https://raw.communitydragon.org/latest/plugins/rcp-fe-lol-shared-components/global/default/{tier}.png",
            f"ranks/{tier}.png",
        ) for tier in tiers
    })
    if "detail_game" in result:
        game = result["detail_game"]
        people = [game.get("player") or {}]
        people.extend(person for team in game.get("teams") or [] for person in team.get("participants") or [])
        for person in people:
            key = _champion_key(str(person.get("champion_name") or ""))
            if key:
                assets[f"champion:{key}"] = (
                    f"https://ddragon.leagueoflegends.com/cdn/{_DDRAGON_VERSION}/img/champion/{key}.png",
                    f"champions/{_DDRAGON_VERSION}/{key}.png",
                )
            for item in person.get("items") or []:
                item_id = int(item.get("id") or 0)
                if item_id:
                    assets[f"item:{item_id}"] = (
                        f"https://game.gtimg.cn/images/lol/act/img/item/{item_id}.png", f"items/{item_id}.png",
                    )
    cache = PROJECT_ROOT_PATH / "data" / "lol_fa8" / "images"

    async def fetch(key: str, url: str, filename: str) -> tuple[str, str]:
        path = cache / filename
        try:
            if path.is_file():
                content = await asyncio.to_thread(path.read_bytes)
            else:
                session = await _HTTP.session()
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10), proxy=_HTTP.request_proxy(url)) as response:
                    response.raise_for_status()
                    content = await response.read()
                path.parent.mkdir(parents=True, exist_ok=True)
                await asyncio.to_thread(path.write_bytes, content)
            return key, "data:image/png;base64," + base64.b64encode(content).decode("ascii")
        except Exception as exc:
            logger.warning("FA8 图片资源暂不可用 [%s]: %s", key, exc)
            return key, ""

    return dict(await asyncio.gather(*(fetch(key, url, name) for key, (url, name) in assets.items())))


def _rank_cards(info: dict, images: dict[str, str]) -> str:
    if info.get("rank_error"):
        return f'<div class="empty">段位读取失败 · {_text(info["rank_error"])}</div>'
    queues = (info.get("ranked_stats") or {}).get("queues") or []
    ranks = {str(rank.get("queueType", "")).upper(): rank for rank in queues}
    cards = []
    for queue, label in (("RANKED_SOLO_5X5", "单双排位"), ("RANKED_FLEX_SR", "灵活排位")):
        rank = ranks.get(queue)
        tier, details, best = "未定级", "暂无排位记录", ""
        if rank:
            tier = " ".join(str(rank[key]) for key in ("tier_label", "rank_label") if rank.get(key)) or "未定级"
            details = f'{rank.get("leaguePoints", 0)} 胜点 · {rank.get("wins", 0)} 胜 {rank.get("losses", 0)} 负'
            highest = " ".join(str(rank[key]) for key in (
                "highest_tier_label", "highest_rank_label",
            ) if rank.get(key))
            if highest:
                best = f'<div class="rank-best">最高 {_text(highest)}</div>'
        cards.append(
            f'<article class="rank-card"><div class="rank-copy"><div class="label">{label}</div>'
            f'<div class="rank-name">{_text(tier)}</div>'
            f'<div class="rank-detail">{_text(details)}</div>{best}</div>'
            f'{_picture("rank:" + _rank_key(rank or {}), images, "rank-emblem", tier)}</article>'
        )
    return "".join(cards)


def _match_rows(games: list[dict], error: str, images: dict[str, str]) -> str:
    if error:
        return f'<div class="empty">战绩读取失败 · {_text(error)}</div>'
    if not games:
        return '<div class="empty">暂无近期战绩</div>'
    rows = []
    for game in games[:5]:
        player = game.get("player") or {}
        won = _won(game)
        state, label = ("win" if won else "loss"), _outcome(won)
        champion = player.get("champion_title") or _champion_cn(player.get("champion_name") or "未知英雄")
        portrait = _picture(
            "champion:" + _champion_key(str(player.get("champion_name") or champion)), images, "champion-portrait", champion,
        )
        kills, deaths, assists = (int(player.get(key) or 0) for key in ("kills", "deaths", "assists"))
        kda = f"{(kills + assists) / deaths:.2f}" if deaths else "完美"
        minutes, seconds = divmod(int(game.get("duration") or 0), 60)
        date = _format_date(game.get("created_at"))
        rows.append(
            f'<article class="match {state}"><div class="outcome">{label}</div>'
            f'<div class="champion">{portrait}<div class="champion-copy"><div class="champion-name">{_text(champion)}</div>'
            f'<div class="match-mode">{_text(game.get("mode") or "未知模式")}</div></div></div>'
            f'<div class="combat"><div class="kda">{kills}<span>/</span>{deaths}<span>/</span>{assists}</div>'
            f'<div class="match-meta">KDA {kda}</div></div>'
            f'<div class="match-time"><div>{minutes:02d}:{seconds:02d}</div>'
            f'<div class="match-meta">{_text(date)}</div></div></article>'
        )
    return "".join(rows)


def _mastery_cards(info: dict, images: dict[str, str]) -> str:
    if info.get("champion_mastery_error"):
        return f'<div class="empty">英雄熟练度读取失败 · {_text(info["champion_mastery_error"])}</div>'
    champions = _mastery_champions(info)
    if not champions:
        return '<div class="empty">暂无英雄熟练度数据</div>'
    return '<div class="mastery-grid">' + "".join(
        f'<article class="mastery"><div class="mastery-top">'
        f'{_picture("champion:" + _champion_key(str(champion.get("name") or "")), images, "mastery-portrait", str(champion.get("name") or "未知英雄"))}'
        f'<div class="mastery-index">{index:02d}</div></div>'
        f'<div class="mastery-name">{_text(champion.get("name") or "未知英雄")}</div>'
        f'<div class="mastery-level">{_text(champion.get("level", 0))} 级成就</div>'
        f'<div class="mastery-points">{int(champion.get("points") or 0):,}</div></article>'
        for index, champion in enumerate(champions, 1)
    ) + "</div>"


def build_card_html(result: dict, *, generated_at: datetime | None = None, images: dict[str, str] | None = None) -> str:
    """将查询数据排版为不依赖外部资源的战绩卡片。"""
    info = result["info"]
    images = images or {}
    summoner = info.get("summoner") or {}
    response = result["games_response"]
    games_error = str(response.get("message") or "FA8 查询失败") if response.get("code") != 0 else ""
    games = [] if games_error else (response.get("data") or {}).get("games") or []
    wins = sum(_won(game) for game in games)
    deaths = sum(int((game.get("player") or {}).get("deaths") or 0) for game in games)
    contributions = sum(
        int((game.get("player") or {}).get("kills") or 0)
        + int((game.get("player") or {}).get("assists") or 0)
        for game in games
    )
    win_rate = f"{wins / len(games):.0%}" if games else "—"
    overall_kda = (f"{contributions / deaths:.2f}" if deaths else "完美") if games else "—"
    record = f'{wins}<span class="record-slash">/</span>{len(games) - wins}' if games else "—"
    trend = "".join(f'<i class="{"win" if _won(game) else "loss"}"></i>' for game in games)
    assets = info.get("player_assets") or {}
    assets_error = f'玩家资产读取失败 · {info["player_assets_error"]}' if info.get("player_assets_error") else ""
    return load_template("match_history.html").substitute(
        game_name=_text(result["game_name"]),
        tag_line=_text(result["tag_line"]),
        server_name=_text(result["server_name"]),
        level=_text(summoner.get("level", "—")),
        last_played=_text(_format_date(summoner.get("lastGameDate") or summoner.get("revisionDate"))),
        heroes=_text(assets.get("heroes", "—")),
        skins=_text(assets.get("skins", "—")),
        assets_error=_text(assets_error),
        sample_label=f"近 {len(games)} 场对局" if games else ("战绩暂不可用" if games_error else "近期对局"),
        win_rate=win_rate,
        record=record,
        overall_kda=overall_kda,
        trend=trend,
        ranks=_rank_cards(info, images),
        matches=_match_rows(games, games_error, images),
        match_count=min(len(games), 5),
        mastery=_mastery_cards(info, images),
        generated_at=(generated_at or now_cst()).strftime("%Y-%m-%d %H:%M"),
    )


async def render_card(result: dict) -> Path:
    """使用无头 Chromium 导出高清 PNG，返回待发送的临时图片。"""
    images = await load_card_images(result)
    if "detail_game" in result:
        from .detail import build_detail_html

        html = await asyncio.to_thread(build_detail_html, result, images=images)
    else:
        html = await asyncio.to_thread(build_card_html, result, images=images)
    render_dir = PROJECT_ROOT_PATH / "data" / "lol_fa8" / "renders"
    render_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix="match_", suffix=".png", dir=render_dir, delete=False) as output:
        path = Path(output.name)
    complete = False
    try:
        async with _BROWSER.page(
            viewport={"width": 1280, "height": 1000}, device_scale_factor=1, locale="zh-CN",
        ) as page:
            await page.set_content(html, wait_until="load")
            await page.evaluate("document.fonts.ready")
            await page.locator("#card").screenshot(path=str(path))
        complete = True
        return path
    finally:
        if not complete:
            path.unlink(missing_ok=True)


async def close() -> None:
    await _BROWSER.close()
    await _HTTP.close()
