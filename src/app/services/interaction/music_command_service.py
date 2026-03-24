from typing import Optional

from app.services.runtime import CommandRuntimeView, music_of, sender_of
from music import parse_platform_prefix


class MusicCommandService:
    """处理音乐相关的中文指令和斜杠命令。"""

    def __init__(self, runtime: CommandRuntimeView):
        self._runtime = runtime
        self._sender = sender_of(runtime)
        self._music = music_of(runtime)

    def _interactive_enabled(self) -> bool:
        return getattr(self._music, "supports_interactive_selection", False) is True

    def _play_direct(self, keyword: str, channel: str, area: str, user: str) -> None:
        platform, clean_kw = parse_platform_prefix(keyword)
        if platform:
            self._music.play_song(clean_kw, platform, channel, area, user)
        else:
            self._music.play_netease(clean_kw, channel, area, user)

    @staticmethod
    def _is_confident_match(keyword: str, results: list[dict]) -> bool:
        if not keyword or not results:
            return False
        target = keyword.strip().lower()
        first = results[0]
        first_name = str(first.get("name", "")).strip().lower()
        first_full = f"{first_name} {str(first.get('artists', '')).strip().lower()}".strip()
        if target in {first_name, first_full}:
            return True
        if len(results) == 1:
            return True
        return False

    def _send_song_candidates(
        self,
        keyword: str,
        platform: str,
        channel: str,
        area: str,
        user: str,
        results: list[dict],
    ) -> None:
        items = []
        for song in results[:5]:
            item = dict(song)
            item["platform"] = platform
            items.append(item)
        self._runtime.services.interaction.selection.store(
            user=user,
            channel=channel,
            area=area,
            kind="song",
            query=keyword,
            items=items,
        )
        lines = [f'搜歌 "{keyword}" - 找到 {len(results)} 首候选', "---"]
        for index, song in enumerate(items, 1):
            lines.append(
                f"  {index}. {song.get('name', '未知歌曲')} - {song.get('artists', '未知歌手')}"
                f" [{song.get('durationText', '')}]"
            )
        lines += [
            "",
            "发送 `@bot 选歌 <编号>`、`@bot 选择 <编号>` 或 `/pick <编号>` 继续",
        ]
        self._sender.send_message("\n".join(lines), channel=channel, area=area)

    def _play(self, keyword: str, channel: str, area: str, user: str) -> None:
        """解析平台前缀后调用多平台点歌。"""
        platform, clean_kw = parse_platform_prefix(keyword)
        resolved_platform = platform or "netease"
        if not self._interactive_enabled():
            self._play_direct(keyword, channel, area, user)
            return
        fast_result = None
        fast_search = getattr(self._music, "search_best_candidate", None)
        if callable(fast_search):
            candidate = fast_search(clean_kw, resolved_platform)
            if isinstance(candidate, dict):
                fast_result = candidate
        if fast_result and self._is_confident_match(clean_kw, [fast_result]):
            self._music.play_song_choice(dict(fast_result, platform=resolved_platform), channel, area, user)
            return
        results = self._music.search_candidates(clean_kw, resolved_platform, limit=5)
        if not results:
            self._sender.send_message(f"未找到: {clean_kw}", channel=channel, area=area)
            return
        if self._is_confident_match(clean_kw, results):
            self._music.play_song_choice(dict(results[0], platform=resolved_platform), channel, area, user)
            return
        self._send_song_candidates(clean_kw, resolved_platform, channel, area, user, results)

    def search_candidates(self, keyword: str, channel: str, area: str, user: str) -> None:
        """显式搜歌并返回候选列表。"""
        keyword = (keyword or "").strip()
        if not keyword:
            self._sender.send_message("用法: @bot 搜歌 <关键词>  或  /songsearch <关键词>", channel=channel, area=area)
            return
        platform, clean_kw = parse_platform_prefix(keyword)
        resolved_platform = platform or "netease"
        if not self._interactive_enabled():
            self._play_direct(keyword, channel, area, user)
            return
        results = self._music.search_candidates(clean_kw, resolved_platform, limit=5)
        if not results:
            self._sender.send_message(f"未找到: {clean_kw}", channel=channel, area=area)
            return
        self._send_song_candidates(clean_kw, resolved_platform, channel, area, user, results)

    def handle_pick(self, index: int, channel: str, area: str, user: str) -> bool:
        """处理选歌编号。"""
        selection, item = self._runtime.services.interaction.selection.pick(user, channel, area, index)
        if not selection or selection.kind != "song":
            return False
        if not item:
            self._sender.send_message(f"编号超出范围，请输入 1-{len(selection.items)}", channel=channel, area=area)
            return True
        self._runtime.services.interaction.selection.clear(user, channel, area)
        self._music.play_song_choice(item, channel, area, user)
        return True

    def handle_mention(self, text: str, channel: str, area: str, user: str) -> bool:
        """处理 @bot 中文音乐指令。"""
        for prefix in ("播放", "放", "点播", "来一首", "唱"):
            if text.startswith(prefix):
                keyword = text[len(prefix):].strip()
                if keyword:
                    self._play(keyword, channel, area, user)
                else:
                    self._sender.send_message(
                        "请输入歌名，例如:\n  @bot 播放海阔天空\n  @bot 播放 qq:周杰伦\n  @bot 播放 b站:稻香",
                        channel=channel, area=area,
                    )
                return True

        for prefix in ("搜歌", "搜索歌曲"):
            if text.startswith(prefix):
                self.search_candidates(text[len(prefix):].strip(), channel, area, user)
                return True

        if text in ("停止", "停", "停止播放", "关"):
            self._music.stop_play(channel, area)
            return True

        if text in ("下一首", "切歌", "跳过", "下一个"):
            self._music.play_next(channel, area, user)
            return True

        if text in ("队列", "列表", "播放列表"):
            self._music.show_queue(channel, area)
            return True

        if text in ("随机", "随机播放", "喜欢", "随便来一首"):
            self._music.play_liked(channel, area, user, 1)
            return True

        import re
        match = re.match(r"喜欢列表\s*(\d+)?", text)
        if match:
            page = int(match.group(1)) if match.group(1) else 1
            self._music.show_liked_list(channel, area, page)
            return True

        return False

    def handle_slash(
        self,
        command: str,
        subcommand: Optional[str],
        arg: Optional[str],
        parts: list[str],
        channel: str,
        area: str,
        user: str,
    ) -> bool:
        """处理音乐相关斜杠命令。"""
        if command in ("/bf", "/play"):
            if len(parts) < 2:
                self._sender.send_message(
                    "用法: /bf 歌曲名\n  /bf qq 歌曲名 (QQ音乐)\n  /bf bili 歌曲名 (B站)",
                    channel=channel, area=area,
                )
                return True
            slug = parts[1].lower()
            _SLASH_PLATFORM_MAP = {"qq": "qq", "bili": "bilibili", "bilibili": "bilibili", "netease": "netease", "b站": "bilibili", "网易": "netease"}
            if slug in _SLASH_PLATFORM_MAP and len(parts) > 2:
                platform = _SLASH_PLATFORM_MAP[slug]
                keyword = " ".join(parts[2:])
                self._music.play_song(keyword, platform, channel, area, user)
            else:
                keyword = " ".join(parts[1:])
                self._play(keyword, channel, area, user)
            return True

        if command == "/songsearch":
            keyword = " ".join(parts[1:]).strip()
            if keyword:
                self.search_candidates(keyword, channel, area, user)
            else:
                self._sender.send_message("用法: /songsearch <关键词>", channel=channel, area=area)
            return True

        if command == "/yun" and subcommand == "play":
            if arg:
                if self._interactive_enabled():
                    self._play(arg, channel, area, user)
                else:
                    self._music.play_netease(arg, channel, area, user)
            else:
                self._sender.send_message("用法: /yun play 歌曲名", channel=channel, area=area)
            return True

        if command == "/next":
            self._music.play_next(channel, area, user)
            return True

        if command == "/queue":
            self._music.show_queue(channel, area)
            return True

        if command in ("/st", "/stop"):
            self._music.stop_play(channel, area)
            return True

        if command != "/like":
            return False

        if subcommand == "list":
            page = 1
            if arg:
                try:
                    page = int(arg)
                except ValueError:
                    pass
            self._music.show_liked_list(channel, area, page)
            return True

        if subcommand == "play":
            if arg:
                try:
                    index = int(arg)
                    self._music.play_liked_by_index(index, channel, area, user)
                except ValueError:
                    self._sender.send_message("用法: /like play <编号>", channel=channel, area=area)
            else:
                self._sender.send_message("用法: /like play <编号>\n先用 /like list 查看列表", channel=channel, area=area)
            return True

        count = 1
        if subcommand:
            try:
                count = int(subcommand)
                count = max(1, min(count, 20))
            except ValueError:
                self._sender.send_message(
                    "用法:\n  /like         随机播放1首\n  /like <数量>   随机播放多首\n"
                    "  /like list    查看喜欢列表\n  /like play <编号>  播放指定歌曲",
                    channel=channel,
                    area=area,
                )
                return True

        self._music.play_liked(channel, area, user, count)
        return True
