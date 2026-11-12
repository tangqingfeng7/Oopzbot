from __future__ import annotations

from .render import _champion_key, _picture, _text, load_template
from .service import _champion_cn, _format_date, _outcome, _won


def _value(player: dict, key: str) -> str:
    value = player.get(key)
    return "—" if value is None else f"{value:,}" if isinstance(value, (int, float)) else str(value)


def format_detail(result: dict) -> str:
    game = result["detail_game"]
    player = game.get("player") or {}
    minutes, seconds = divmod(int(game.get("duration") or 0), 60)
    lines = [
        f"{result['game_name']}#{result['tag_line']} · 第 {result['detail_index']} 场",
        f"{_outcome(_won(game))} · {game.get('mode') or '未知模式'} · {minutes:02d}:{seconds:02d}",
        f"对局时间: {_format_date(game.get('created_at'))}",
        f"英雄: {player.get('champion_title') or _champion_cn(player.get('champion_name') or '未知英雄')}",
        f"KDA: {_value(player, 'kills')}/{_value(player, 'deaths')}/{_value(player, 'assists')}",
        f"伤害: {_value(player, 'damage_dealt')} · 承伤: {_value(player, 'damage_taken')}",
        f"经济: {_value(player, 'gold')} · 补刀: {_value(player, 'cs')} · 视野: {_value(player, 'vision_score')}",
    ]
    for team in game.get("teams") or []:
        lines.append(f"{team.get('label') or '队伍'} · {_outcome(team.get('win'))}")
        for person in team.get("participants") or []:
            name = person.get("display_name") or person.get("game_name") or "未知玩家"
            champion = person.get("champion_title") or _champion_cn(person.get("champion_name") or "未知英雄")
            lines.append(f"  {name} · {champion} · {_value(person, 'kills')}/{_value(person, 'deaths')}/{_value(person, 'assists')}")
    return "\n".join(lines)


def build_detail_html(result: dict, *, images: dict[str, str] | None = None) -> str:
    images = images or {}
    game = result["detail_game"]
    player = game.get("player") or {}
    minutes, seconds = divmod(int(game.get("duration") or 0), 60)
    metrics = "".join(
        f'<div class="stat"><span>{label}</span><strong>{_text(_value(player, key))}</strong></div>'
        for key, label in (("damage_dealt", "对英雄伤害"), ("damage_taken", "承受伤害"),
                           ("gold", "获得经济"), ("cs", "补刀"), ("vision_score", "视野得分"))
    )
    teams = []
    for team in game.get("teams") or []:
        rows = []
        for person in team.get("participants") or []:
            champion = person.get("champion_title") or _champion_cn(person.get("champion_name") or "未知英雄")
            portrait = _picture("champion:" + _champion_key(person.get("champion_name") or ""), images, "portrait", champion)
            equipment = "".join(
                _picture(f"item:{item['id']}", images, "item", f"装备 {item['id']}")
                for item in person.get("items") or [] if item.get("id")
            ) or '<span class="muted">暂无装备数据</span>'
            name = person.get("display_name") or person.get("game_name") or "未知玩家"
            kda = "/".join(_value(person, key) for key in ("kills", "deaths", "assists"))
            current = " current" if person.get("is_current") else ""
            rows.append(
                f'<tr class="{current}"><td><div class="player">{portrait}<div><b>{_text(name)}</b>'
                f'<small>{_text(champion)}{ " · 本人" if current else ""}</small></div></div></td>'
                f'<td>{_text(kda)}</td><td>{_text(_value(person, "damage_dealt"))}</td>'
                f'<td>{_text(_value(person, "damage_taken"))}</td><td>{_text(_value(person, "gold"))}</td>'
                f'<td>{_text(_value(person, "cs"))}</td><td>{_text(_value(person, "vision_score"))}</td>'
                f'<td><div class="equipment">{equipment}</div></td></tr>'
            )
        outcome = _outcome(team.get("win"))
        teams.append(
            f'<section><h2>{_text(team.get("label") or "队伍")} · {outcome}'
            f'<span class="muted">　击杀 {_text(team.get("kills", "—"))}</span></h2>'
            '<table><thead><tr><th>玩家 / 英雄</th><th>K / D / A</th><th>伤害</th><th>承伤</th>'
            '<th>经济</th><th>补刀</th><th>视野</th><th>装备</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></section>'
        )
    return load_template("match_detail.html").substitute(
        player=_text(f"{result['game_name']}#{result['tag_line']}"),
        index=result["detail_index"], outcome=_outcome(_won(game)),
        mode=_text(game.get("mode") or "未知模式"), duration=f"{minutes:02d}:{seconds:02d}",
        date=_text(_format_date(game.get("created_at"))), server=_text(result["server_name"]),
        metrics=metrics, teams="".join(teams) or '<section class="muted">本场暂无双方阵容数据</section>',
        champion=_text(player.get("champion_title") or _champion_cn(player.get("champion_name") or "未知英雄")),
        kda=_text(" / ".join(_value(player, key) for key in ("kills", "deaths", "assists"))),
        queried_at=_text(result.get("queried_at") or "—"),
    )
