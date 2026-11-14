"""QQ 音乐平台实现。
配置 QQ_MUSIC_CONFIG.base_url 指向该服务地址。
"""

from __future__ import annotations

from core.async_http import ManagedHttpClient
from core.http_constants import HTTP_TIMEOUT_DEFAULT
from core.logger_config import get_logger
from web.web_player_config import QQ_MUSIC_CONFIG

logger = get_logger("QQMusic")

# 专辑封面 CDN 模板，{mid} 为专辑 mid。
_ALBUM_COVER_URL = "https://y.gtimg.cn/music/photo_new/T002R300x300M000{mid}.jpg"


class QQMusic:
    """QQ 音乐平台，实现 MusicPlatform 协议。"""

    name = "qq"
    display_name = "QQ音乐"

    def __init__(self):
        cfg = QQ_MUSIC_CONFIG
        self.enabled = cfg.get("enabled", False)
        self.base_url = str(cfg.get("base_url", "")).rstrip("/")
        self.cookie = cfg.get("cookie", "")
        self._http = ManagedHttpClient()
        if self.enabled and not self.base_url:
            logger.warning("QQ 音乐 API 地址未配置 (QQ_MUSIC_CONFIG.base_url)")

    async def _get(self, path: str, params: dict | None = None) -> dict | None:
        if not self.base_url:
            return None
        try:
            headers = {}
            if self.cookie:
                headers["Cookie"] = self.cookie
            return await self._http.request_json(
                "GET",
                f"{self.base_url}{path}",
                params=params,
                headers=headers,
                timeout=HTTP_TIMEOUT_DEFAULT,
            )
        except Exception as e:
            logger.error("QQ 音乐 API 请求失败: %s", e)
            return None

    async def search(self, keyword: str, limit: int = 1) -> dict | None:
        data = await self._get("/getSearchByKey", params={"key": keyword, "limit": limit, "page": 1})
        if not data:
            return None
        songs = (data.get("response") or data.get("data") or {}).get("song", {}).get("list") or \
                (data.get("data") or {}).get("list") or []
        if not songs:
            data2 = await self._get("/search", params={"key": keyword, "limit": limit, "page": 1})
            if data2:
                songs = (data2.get("data") or {}).get("list") or []
        if not songs:
            return None
        return self._parse_song(songs[0])

    async def search_many(self, keyword: str, limit: int = 10, offset: int = 0) -> list[dict]:
        page = (offset // max(limit, 1)) + 1
        data = await self._get("/getSearchByKey", params={"key": keyword, "limit": limit, "page": page})
        if not data:
            data = await self._get("/search", params={"key": keyword, "limit": limit, "page": page})
        if not data:
            return []
        songs = (data.get("response") or data.get("data") or {}).get("song", {}).get("list") or \
                (data.get("data") or {}).get("list") or []
        return [p for s in songs if (p := self._parse_song(s))]

    async def get_song_url(self, song_id) -> str | None:
        song_id = str(song_id)
        data = await self._get("/song/url", params={"id": song_id})
        if not data:
            data = await self._get("/getMusicPlay", params={"songmid": song_id})
        if not data:
            return None
        play_data = data.get("data") or {}
        url = play_data.get("url") or ((play_data.get("playUrl") or {}).get(song_id) or {}).get("url")
        return url or None

    async def get_song_detail(self, song_id) -> dict | None:
        data = await self._get("/getSongInfo", params={"songmid": str(song_id)})
        if not data or not data.get("data"):
            return None
        return self._parse_song(data["data"])

    async def get_lyric(self, song_id) -> str | None:
        data = await self._get("/getLyric", params={"songmid": str(song_id)})
        if not data:
            return None
        lyric = (data.get("data") or {}).get("lyric") or data.get("lyric") or ""
        return lyric if lyric and "[" in lyric else None

    async def summarize(self, keyword: str) -> dict:
        song = await self.search(keyword)
        if not song:
            return {"code": "error", "message": f"QQ音乐未找到: {keyword}", "data": None}
        mid = song.get("mid") or song.get("id")
        url = await self.get_song_url(mid)
        if not url:
            return {"code": "error", "message": f"QQ音乐无法获取播放链接: {song['name']}", "data": None}
        song["url"] = url
        msg = (
            f"歌曲: {song['name']}\n"
            f"歌手: {song['artists']}\n"
            f"专辑: {song['album']}\n"
            f"时长: {song['durationText']}"
        )
        return {"code": "success", "message": msg, "data": song}

    async def summarize_by_id(self, song_id) -> dict:
        song = await self.get_song_detail(song_id)
        if not song:
            return {"code": "error", "message": f"QQ音乐无法获取歌曲信息: {song_id}", "data": None}
        mid = song.get("mid") or song.get("id")
        url = await self.get_song_url(mid)
        if not url:
            return {"code": "error", "message": f"QQ音乐无法获取播放链接: {song['name']}", "data": None}
        song["url"] = url
        return {"code": "success", "message": "", "data": song}

    async def close(self) -> None:
        await self._http.close()

    def _parse_song(self, song: dict) -> dict | None:
        if not song:
            return None
        song_id = song.get("songmid") or song.get("mid") or song.get("id") or ""
        if not song_id:
            return None
        singers = song.get("singer") or []
        if isinstance(singers, list):
            artists = " / ".join(s.get("name") or "未知" for s in singers) or "未知"
        else:
            artists = str(singers)
        album = song.get("album") or {}
        album_name = album.get("name") or "" if isinstance(album, dict) else str(album)
        duration_s = int(song.get("interval") or song.get("duration") or 0)
        duration_ms = duration_s * 1000
        cover = ""
        if isinstance(album, dict) and album.get("mid"):
            cover = _ALBUM_COVER_URL.format(mid=album["mid"])
        return {
            "id": song_id,
            "mid": song_id,
            "name": song.get("songname") or song.get("name") or "未知歌曲",
            "artists": artists,
            "album": album_name,
            "duration": duration_ms,
            "durationText": f"{duration_s // 60}:{duration_s % 60:02d}",
            "cover": cover,
        }
