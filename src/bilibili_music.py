"""B 站音乐平台实现。

使用 B 站公开搜索 API + 音频流提取。
配置 BILIBILI_MUSIC_CONFIG.cookie 以获取更高音质。
"""

from __future__ import annotations

import re
import requests
from typing import Optional

from logger_config import get_logger

logger = get_logger("BilibiliMusic")

_API_SEARCH = "https://api.bilibili.com/x/web-interface/search/type"
_API_AUDIO_INFO = "https://www.bilibili.com/audio/music-service-c/web/song/info"
_API_AUDIO_URL = "https://www.bilibili.com/audio/music-service-c/web/url"
_API_VIDEO_PLAYURL = "https://api.bilibili.com/x/player/playurl"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
}


_cached_config: dict | None = None


def _load_config() -> dict:
    global _cached_config
    if _cached_config is not None:
        return _cached_config
    try:
        from config import BILIBILI_MUSIC_CONFIG
        _cached_config = BILIBILI_MUSIC_CONFIG
        return _cached_config
    except (ImportError, AttributeError):
        _cached_config = {}
        return _cached_config


class BilibiliMusic:
    """B 站音乐平台，实现 MusicPlatform 协议。"""

    name = "bilibili"
    display_name = "B站"

    def __init__(self):
        cfg = _load_config()
        self.enabled = cfg.get("enabled", False)
        self.cookie = cfg.get("cookie", "")
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)

    def _get(self, url: str, params: dict | None = None) -> Optional[dict]:
        try:
            headers = {"Cookie": self.cookie} if self.cookie else {}
            resp = self._session.get(url, params=params, headers=headers, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error("B 站 API 请求失败 (%s): %s", url, e)
            return None

    def search(self, keyword: str, limit: int = 1) -> Optional[dict]:
        results = self._search_audio(keyword, limit)
        if results:
            return results[0]
        results = self._search_video(keyword, limit)
        if results:
            return results[0]
        return None

    def search_many(self, keyword: str, limit: int = 10, offset: int = 0) -> list[dict]:
        page = (offset // max(limit, 1)) + 1
        results = self._search_audio(keyword, limit, page)
        if not results:
            results = self._search_video(keyword, limit, page)
        return results or []

    def _search_audio(self, keyword: str, limit: int = 10, page: int = 1) -> list[dict]:
        data = self._get(_API_SEARCH, params={
            "search_type": "audio",
            "keyword": keyword,
            "page": page,
            "pagesize": limit,
        })
        if not data or data.get("code") != 0:
            return []
        items = (data.get("data") or {}).get("result") or []
        return [p for item in items if (p := self._parse_audio(item))]

    def _search_video(self, keyword: str, limit: int = 10, page: int = 1) -> list[dict]:
        data = self._get(_API_SEARCH, params={
            "search_type": "video",
            "keyword": keyword + " 音乐",
            "page": page,
            "pagesize": limit,
        })
        if not data or data.get("code") != 0:
            return []
        items = (data.get("data") or {}).get("result") or []
        return [p for item in items if (p := self._parse_video(item))]

    def get_song_url(self, song_id) -> Optional[str]:
        sid = str(song_id)
        if sid.startswith("au"):
            return self._get_audio_url(sid[2:])
        if sid.startswith("BV") or sid.startswith("bv"):
            return self._get_video_audio_url(sid)
        return self._get_audio_url(sid) or self._get_video_audio_url(sid)

    def _get_audio_url(self, au_id: str) -> Optional[str]:
        data = self._get(_API_AUDIO_URL, params={"sid": au_id, "privilege": 2, "quality": 2})
        if not data or data.get("code") != 0:
            return None
        cdns = (data.get("data") or {}).get("cdns") or []
        return cdns[0] if cdns else None

    def _get_video_audio_url(self, bvid: str) -> Optional[str]:
        data = self._get(_API_VIDEO_PLAYURL, params={
            "bvid": bvid,
            "fnval": 16,
            "qn": 64,
        })
        if not data or data.get("code") != 0:
            return None
        dash = (data.get("data") or {}).get("dash") or {}
        audio_list = dash.get("audio") or []
        if audio_list:
            return audio_list[0].get("baseUrl") or audio_list[0].get("base_url")
        return None

    def get_song_detail(self, song_id) -> Optional[dict]:
        sid = str(song_id)
        if sid.startswith("au"):
            sid = sid[2:]
        data = self._get(_API_AUDIO_INFO, params={"sid": sid})
        if data and data.get("code") == 0 and data.get("data"):
            return self._parse_audio_detail(data["data"])
        return None

    def get_lyric(self, song_id) -> Optional[str]:
        sid = str(song_id)
        if sid.startswith("au"):
            sid = sid[2:]
        data = self._get(
            "https://www.bilibili.com/audio/music-service-c/web/song/lyric",
            params={"sid": sid},
        )
        if not data or data.get("code") != 0:
            return None
        lyric = (data.get("data") or {}).get("lrc") or ""
        return lyric if lyric and "[" in lyric else None

    def summarize(self, keyword: str) -> dict:
        song = self.search(keyword)
        if not song:
            return {"code": "error", "message": f"B站未找到: {keyword}", "data": None}
        url = self.get_song_url(song["id"])
        if not url:
            return {"code": "error", "message": f"B站无法获取播放链接: {song['name']}", "data": None}
        song["url"] = url
        msg = (
            f"歌曲: {song['name']}\n"
            f"作者: {song['artists']}\n"
            f"时长: {song['durationText']}"
        )
        return {"code": "success", "message": msg, "data": song}

    def summarize_by_id(self, song_id) -> dict:
        song = self.get_song_detail(song_id)
        if not song:
            return {"code": "error", "message": f"B站无法获取信息: {song_id}", "data": None}
        url = self.get_song_url(song["id"])
        if not url:
            return {"code": "error", "message": f"B站无法获取播放链接: {song['name']}", "data": None}
        song["url"] = url
        return {"code": "success", "message": "", "data": song}

    def _parse_audio(self, item: dict) -> Optional[dict]:
        au_id = item.get("id") or ""
        if not au_id:
            return None
        title = item.get("title") or "未知"
        title = re.sub(r"<[^>]+>", "", title)
        author = item.get("author") or item.get("up_name") or "未知"
        duration_s = int(item.get("duration") or 0)
        cover = item.get("cover") or ""
        return {
            "id": f"au{au_id}",
            "name": title,
            "artists": author,
            "album": "",
            "duration": duration_s * 1000,
            "durationText": f"{duration_s // 60}:{duration_s % 60:02d}",
            "cover": cover,
        }

    def _parse_video(self, item: dict) -> Optional[dict]:
        bvid = item.get("bvid") or ""
        if not bvid:
            return None
        title = item.get("title") or "未知"
        title = re.sub(r"<[^>]+>", "", title)
        author = item.get("author") or item.get("up_name") or "未知"
        duration_str = item.get("duration") or "0:00"
        duration_s = 0
        if isinstance(duration_str, str) and ":" in duration_str:
            parts = duration_str.split(":")
            try:
                duration_s = int(parts[0]) * 60 + int(parts[1])
            except ValueError:
                pass
        elif isinstance(duration_str, (int, float)):
            duration_s = int(duration_str)
        cover = item.get("pic") or ""
        if cover.startswith("//"):
            cover = "https:" + cover
        return {
            "id": bvid,
            "name": title,
            "artists": author,
            "album": "",
            "duration": duration_s * 1000,
            "durationText": f"{duration_s // 60}:{duration_s % 60:02d}",
            "cover": cover,
        }

    def _parse_audio_detail(self, data: dict) -> Optional[dict]:
        au_id = data.get("id") or data.get("sid") or ""
        if not au_id:
            return None
        duration_s = int(data.get("duration") or 0)
        return {
            "id": f"au{au_id}",
            "name": data.get("title") or "未知",
            "artists": data.get("author") or data.get("uname") or "未知",
            "album": "",
            "duration": duration_s * 1000,
            "durationText": f"{duration_s // 60}:{duration_s % 60:02d}",
            "cover": data.get("cover") or "",
        }
