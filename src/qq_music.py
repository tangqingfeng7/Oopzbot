"""QQ 音乐平台实现。
配置 QQ_MUSIC_CONFIG.base_url 指向该服务地址。
"""

from __future__ import annotations

import requests
from typing import Optional

from logger_config import get_logger

logger = get_logger("QQMusic")


_cached_config: dict | None = None


def _load_config() -> dict:
    global _cached_config
    if _cached_config is not None:
        return _cached_config
    try:
        from config import QQ_MUSIC_CONFIG
        _cached_config = QQ_MUSIC_CONFIG
        return _cached_config
    except (ImportError, AttributeError):
        _cached_config = {}
        return _cached_config


class QQMusic:
    """QQ 音乐平台，实现 MusicPlatform 协议。"""

    name = "qq"
    display_name = "QQ音乐"

    def __init__(self):
        cfg = _load_config()
        self.enabled = cfg.get("enabled", False)
        self.base_url = str(cfg.get("base_url", "")).rstrip("/")
        self.cookie = cfg.get("cookie", "")
        self._session = requests.Session()
        if self.enabled and not self.base_url:
            logger.warning("QQ 音乐 API 地址未配置 (QQ_MUSIC_CONFIG.base_url)")

    def _get(self, path: str, params: dict | None = None) -> Optional[dict]:
        if not self.base_url:
            return None
        try:
            headers = {}
            if self.cookie:
                headers["Cookie"] = self.cookie
            resp = self._session.get(
                f"{self.base_url}{path}",
                params=params,
                headers=headers,
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error("QQ 音乐 API 请求失败: %s", e)
            return None

    def search(self, keyword: str, limit: int = 1) -> Optional[dict]:
        data = self._get("/getSearchByKey", params={"key": keyword, "limit": limit, "page": 1})
        if not data:
            return None
        songs = (data.get("response") or data.get("data") or {}).get("song", {}).get("list") or \
                (data.get("data") or {}).get("list") or []
        if not songs:
            data2 = self._get("/search", params={"key": keyword, "limit": limit, "page": 1})
            if data2:
                songs = (data2.get("data") or {}).get("list") or []
        if not songs:
            return None
        return self._parse_song(songs[0])

    def search_many(self, keyword: str, limit: int = 10, offset: int = 0) -> list[dict]:
        page = (offset // max(limit, 1)) + 1
        data = self._get("/getSearchByKey", params={"key": keyword, "limit": limit, "page": page})
        if not data:
            data = self._get("/search", params={"key": keyword, "limit": limit, "page": page})
        if not data:
            return []
        songs = (data.get("response") or data.get("data") or {}).get("song", {}).get("list") or \
                (data.get("data") or {}).get("list") or []
        return [p for s in songs if (p := self._parse_song(s))]

    def get_song_url(self, song_id) -> Optional[str]:
        song_id = str(song_id)
        data = self._get("/song/url", params={"id": song_id})
        if not data:
            data = self._get("/getMusicPlay", params={"songmid": song_id})
        if not data:
            return None
        url = (data.get("data") or {}).get("url") or ""
        if not url:
            play_data = data.get("data") or {}
            for key in ("sizeflac", "size320", "size128"):
                if play_data.get(key):
                    url = play_data.get("url", "")
                    break
        return url if url else None

    def get_song_detail(self, song_id) -> Optional[dict]:
        data = self._get("/getSongInfo", params={"songmid": str(song_id)})
        if not data or not data.get("data"):
            return None
        return self._parse_song(data["data"])

    def get_lyric(self, song_id) -> Optional[str]:
        data = self._get("/getLyric", params={"songmid": str(song_id)})
        if not data:
            return None
        lyric = (data.get("data") or {}).get("lyric") or data.get("lyric") or ""
        return lyric if lyric and "[" in lyric else None

    def summarize(self, keyword: str) -> dict:
        song = self.search(keyword)
        if not song:
            return {"code": "error", "message": f"QQ音乐未找到: {keyword}", "data": None}
        mid = song.get("mid") or song.get("id")
        url = self.get_song_url(mid)
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

    def summarize_by_id(self, song_id) -> dict:
        song = self.get_song_detail(song_id)
        if not song:
            return {"code": "error", "message": f"QQ音乐无法获取歌曲信息: {song_id}", "data": None}
        mid = song.get("mid") or song.get("id")
        url = self.get_song_url(mid)
        if not url:
            return {"code": "error", "message": f"QQ音乐无法获取播放链接: {song['name']}", "data": None}
        song["url"] = url
        return {"code": "success", "message": "", "data": song}

    def _parse_song(self, song: dict) -> Optional[dict]:
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
            cover = f"https://y.gtimg.cn/music/photo_new/T002R300x300M000{album['mid']}.jpg"
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
