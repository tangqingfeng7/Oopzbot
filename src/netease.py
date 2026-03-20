import time
import threading
import requests
from typing import Optional

from config import NETEASE_CLOUD
from logger_config import get_logger

logger = get_logger("Netease")


class _SearchCache:
    """简单的线程安全短期搜索缓存，避免重复搜索同一关键词反复请求外部 API。"""

    def __init__(self, max_size: int = 128, ttl: int = 300):
        self._data: dict[str, tuple[float, object]] = {}
        self._max_size = max_size
        self._ttl = ttl
        self._lock = threading.Lock()

    def get(self, key: str):
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            ts, val = entry
            if time.time() - ts > self._ttl:
                self._data.pop(key, None)
                return None
            return val

    def put(self, key: str, val):
        with self._lock:
            if len(self._data) >= self._max_size:
                oldest_key = min(self._data, key=lambda k: self._data[k][0])
                self._data.pop(oldest_key, None)
            self._data[key] = (time.time(), val)


class NeteaseCloud:
    """网易云音乐搜索与获取"""

    name = "netease"
    display_name = "网易云"

    def __init__(self):
        self.base_url = NETEASE_CLOUD.get("base_url", "").rstrip("/")
        self.cookie = NETEASE_CLOUD.get("cookie", "")
        self._search_cache = _SearchCache()
        self._session = requests.Session()
        if not self.base_url:
            logger.warning("网易云 API 地址未配置 (NETEASE_CLOUD.base_url)")

    def _get(self, path: str, params: Optional[dict] = None) -> Optional[dict]:
        """发起 GET 请求（复用连接池）"""
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
            logger.error(f"网易云 API 请求失败: {e}")
            return None

    def search(self, keyword: str, limit: int = 1) -> Optional[dict]:
        """
        搜索歌曲

        返回格式::
            {
                "id": 歌曲ID,
                "name": "歌名",
                "artists": "歌手",
                "album": "专辑",
                "duration": 毫秒,
                "cover": "封面URL"
            }
        """
        cache_key = f"s:{keyword}:{limit}"
        cached = self._search_cache.get(cache_key)
        if cached is not None:
            return cached

        data = self._get("/cloudsearch", params={"keywords": keyword, "limit": limit, "type": 1})
        if not data or data.get("code") != 200:
            return None

        songs = data.get("result", {}).get("songs", [])
        if not songs:
            return None

        result = self._parse_song(songs[0])
        if result:
            self._search_cache.put(cache_key, result)
        return result

    def search_many(self, keyword: str, limit: int = 10, offset: int = 0) -> list[dict]:
        """搜索歌曲，返回多条结果列表"""
        data = self._get("/cloudsearch", params={
            "keywords": keyword,
            "limit": limit,
            "offset": max(0, int(offset or 0)),
            "type": 1,
        })
        if not data or data.get("code") != 200:
            return []

        songs = data.get("result", {}).get("songs", [])
        results = []
        for song in songs:
            parsed = self._parse_song(song)
            if parsed:
                results.append(parsed)
        return results

    def get_song_url(self, song_id: int) -> Optional[str]:
        """获取歌曲播放 URL。level 可选 standard(体积小/弱网友好) 或 exhigh(音质更好)。"""
        level = NETEASE_CLOUD.get("audio_quality", "standard")
        data = self._get("/song/url/v1", params={"id": song_id, "level": level})
        if not data or data.get("code") != 200:
            return None

        urls = data.get("data", [])
        if urls and urls[0].get("url"):
            return urls[0]["url"]
        return None

    def get_user_id(self) -> Optional[int]:
        """获取当前登录用户的 ID"""
        data = self._get("/user/account")
        if not data or data.get("code") != 200:
            return None
        profile = data.get("profile")
        return profile.get("userId") if profile else None

    def get_liked_ids(self, uid: int) -> list:
        """获取用户喜欢的歌曲 ID 列表"""
        data = self._get("/likelist", params={"uid": uid})
        if not data or data.get("code") != 200:
            return []
        return data.get("ids", [])

    def get_song_detail(self, song_id: int) -> Optional[dict]:
        """通过歌曲 ID 获取歌曲详细信息"""
        data = self._get("/song/detail", params={"ids": str(song_id)})
        if not data or data.get("code") != 200:
            return None

        songs = data.get("songs", [])
        if not songs:
            return None

        return self._parse_song(songs[0])

    def get_song_details_batch(self, song_ids: list) -> list:
        """批量获取歌曲详细信息（一次最多传 50 个 ID）"""
        if not song_ids:
            return []
        ids_str = ",".join(str(sid) for sid in song_ids)
        data = self._get("/song/detail", params={"ids": ids_str})
        if not data or data.get("code") != 200:
            return []

        results = []
        for song in data.get("songs", []):
            try:
                parsed = self._parse_song(song)
                if parsed:
                    results.append(parsed)
            except Exception as e:
                logger.warning(f"解析歌曲失败 (id={song.get('id')}): {e}")
        return results

    def summarize_by_id(self, song_id: int) -> dict:
        """通过歌曲 ID 获取完整信息（详情 + URL）"""
        song_info = self.get_song_detail(song_id)
        if not song_info:
            return {"code": "error", "message": f"无法获取歌曲信息: {song_id}", "data": None}

        url = self.get_song_url(song_id)
        if not url:
            return {"code": "error", "message": f"无法获取播放链接: {song_info['name']}", "data": None}

        song_info["url"] = url
        return {"code": "success", "message": "", "data": song_info}

    def summarize(self, keyword: str) -> dict:
        """
        搜索并汇总歌曲信息（搜索 + 获取 URL），
        返回统一格式供 music.py 调用。
        """
        song_info = self.search(keyword)
        if not song_info:
            return {"code": "error", "message": f"未找到: {keyword}", "data": None}

        url = self.get_song_url(song_info["id"])
        if not url:
            return {"code": "error", "message": f"无法获取播放链接: {song_info['name']}", "data": None}

        song_info["url"] = url

        msg = (
            f"歌曲: {song_info['name']}\n"
            f"歌手: {song_info['artists']}\n"
            f"专辑: {song_info['album']}\n"
            f"时长: {song_info['durationText']}"
        )
        return {"code": "success", "message": msg, "data": song_info}

    def get_lyrics(self, song_id: int) -> tuple[Optional[str], Optional[str]]:
        """获取歌曲 LRC 歌词和翻译歌词，一次请求同时返回 (lyric, tlyric)。"""
        data = self._get("/lyric/new", params={"id": song_id})
        if not data or data.get("code") != 200:
            return None, None
        lrc_text = (data.get("lrc") or {}).get("lyric", "")
        tlrc_text = (data.get("tlyric") or {}).get("lyric", "")
        lyric = lrc_text if lrc_text and "[" in lrc_text else None
        tlyric = tlrc_text if tlrc_text and "[" in tlrc_text else None
        return lyric, tlyric

    def get_lyric(self, song_id: int) -> Optional[str]:
        """获取歌曲 LRC 歌词文本，无歌词返回 None。"""
        lyric, _ = self.get_lyrics(song_id)
        return lyric

    def get_tlyric(self, song_id: int) -> Optional[str]:
        """获取歌曲翻译歌词，无翻译返回 None。"""
        _, tlyric = self.get_lyrics(song_id)
        return tlyric

    def _parse_song(self, song: dict) -> Optional[dict]:
        """从 API 返回的原始歌曲数据中提取标准化字段，防御所有 None 值"""
        if not song or not song.get("id"):
            return None
        ar = song.get("ar") or []
        artists = " / ".join(a.get("name") or "未知" for a in ar) or "未知"
        album = song.get("al") or {}
        duration_ms = song.get("dt") or 0
        return {
            "id": song["id"],
            "name": song.get("name") or "未知歌曲",
            "artists": artists,
            "album": album.get("name") or "",
            "duration": duration_ms,
            "durationText": self._format_duration(duration_ms),
            "cover": album.get("picUrl") or "",
        }

    @staticmethod
    def _format_duration(ms: int) -> str:
        s = (ms or 0) // 1000
        return f"{s // 60}:{s % 60:02d}"