"""音乐平台统一协议与注册表。"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class MusicPlatform(Protocol):
    """所有音乐平台必须实现的接口。"""

    @property
    def name(self) -> str:
        """平台标识符，如 "netease" / "qq" / "bilibili"。"""
        ...

    @property
    def display_name(self) -> str:
        """平台显示名，如 "网易云" / "QQ音乐" / "B站"。"""
        ...

    async def search(self, keyword: str, limit: int = 1) -> dict | None:
        """搜索单首歌曲，返回标准化歌曲 dict 或 None。"""
        ...

    async def search_many(self, keyword: str, limit: int = 10, offset: int = 0) -> list[dict]:
        """搜索多首歌曲，返回标准化歌曲 dict 列表。"""
        ...

    async def get_song_url(self, song_id) -> str | None:
        """获取歌曲播放 URL。"""
        ...

    async def get_song_detail(self, song_id) -> dict | None:
        """获取歌曲详情。"""
        ...

    async def get_lyric(self, song_id) -> str | None:
        """获取 LRC 歌词，无歌词返回 None。"""
        ...

    async def summarize(self, keyword: str) -> dict:
        """搜索并汇总：返回 {"code": "success"|"error", "message": str, "data": dict|None}。"""
        ...

    async def summarize_by_id(self, song_id) -> dict:
        """按 ID 获取详情 + URL：返回同 summarize 格式。"""
        ...


class PlatformRegistry:
    """音乐平台注册表，按 name 索引。"""

    def __init__(self) -> None:
        self._platforms: dict[str, MusicPlatform] = {}

    def register(self, platform: MusicPlatform) -> None:
        self._platforms[platform.name] = platform

    def unregister(self, name: str) -> MusicPlatform | None:
        return self._platforms.pop(name, None)

    def get(self, name: str) -> MusicPlatform | None:
        return self._platforms.get(name)

    def get_default(self) -> MusicPlatform | None:
        return self._platforms.get("netease")

    @property
    def available(self) -> dict[str, MusicPlatform]:
        return dict(self._platforms)

    def display_name(self, platform_name: str) -> str:
        p = self._platforms.get(platform_name)
        return p.display_name if p else platform_name

    async def close(self) -> None:
        for platform in self._platforms.values():
            closer = getattr(platform, "close", None)
            if closer is not None:
                await closer()
