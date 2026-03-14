from typing import Optional

from app.services.runtime import CommandRuntimeView, music_of, sender_of


class MusicCommandService:
    """处理音乐相关的中文指令和斜杠命令。"""

    def __init__(self, runtime: CommandRuntimeView):
        self._runtime = runtime
        self._sender = sender_of(runtime)
        self._music = music_of(runtime)

    def handle_mention(self, text: str, channel: str, area: str, user: str) -> bool:
        """处理 @bot 中文音乐指令。"""
        for prefix in ("播放", "放", "点播", "来一首", "唱"):
            if text.startswith(prefix):
                keyword = text[len(prefix):].strip()
                if keyword:
                    self._music.play_netease(keyword, channel, area, user)
                else:
                    self._sender.send_message("请输入歌名，例如: @bot 播放海阔天空", channel=channel, area=area)
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
            keyword = " ".join(parts[1:]) if len(parts) > 1 else None
            if keyword:
                self._music.play_netease(keyword, channel, area, user)
            else:
                self._sender.send_message("用法: /bf 歌曲名", channel=channel, area=area)
            return True

        if command == "/yun" and subcommand == "play":
            if arg:
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
