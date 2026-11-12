import threading
import time
from collections import OrderedDict
from typing import Generic, TypeVar
from urllib.parse import urlparse

from config import NETEASE_CLOUD
from core.async_http import ManagedHttpClient
from core.http_constants import HTTP_TIMEOUT_DEFAULT
from core.logger_config import get_logger

logger = get_logger("Netease")

_CacheValue = TypeVar("_CacheValue")


def _safe_params(params: dict | None) -> dict:
    safe = dict(params or {})
    for key in ("cookie", "Cookie"):
        if key in safe:
            safe[key] = "<redacted>"
    return safe


def _mask_audio_url(url: object) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    try:
        parsed = urlparse(text)
        tail = parsed.path.rsplit("/", 1)[-1] if parsed.path else ""
        suffix = "?..." if parsed.query else ""
        return f"{parsed.scheme}://{parsed.netloc}/.../{tail}{suffix}"
    except Exception:
        no_query = text.split("?", 1)[0]
        return no_query[:120] + ("..." if len(no_query) > 120 else "")


def _compact_trial_value(value):
    if not isinstance(value, dict):
        return value
    keys = (
        "start",
        "end",
        "type",
        "resConsumable",
        "userConsumable",
        "listenType",
        "cannotListenReason",
        "playReason",
        "freeLimitTagType",
    )
    return {key: value.get(key) for key in keys if key in value}


def _song_url_debug_summary(item: object) -> dict:
    if not isinstance(item, dict):
        return {"type": type(item).__name__}
    return {
        "id": item.get("id"),
        "code": item.get("code"),
        "level": item.get("level"),
        "encodeType": item.get("encodeType"),
        "type": item.get("type"),
        "br": item.get("br"),
        "size": item.get("size"),
        "time": item.get("time"),
        "fee": item.get("fee"),
        "payed": item.get("payed"),
        "flag": item.get("flag"),
        "urlSource": item.get("urlSource"),
        "rightSource": item.get("rightSource"),
        "freeTrialInfo": _compact_trial_value(item.get("freeTrialInfo")),
        "freeTrialPrivilege": _compact_trial_value(item.get("freeTrialPrivilege")),
        "freeTimeTrialPrivilege": _compact_trial_value(item.get("freeTimeTrialPrivilege")),
        "url": _mask_audio_url(item.get("url")),
    }


def _looks_like_trial_audio(item: object, expected_duration_ms: int = 0) -> bool:
    if not isinstance(item, dict):
        return False
    if item.get("freeTrialInfo"):
        return True
    try:
        duration_ms = int(item.get("time") or 0)
    except (TypeError, ValueError):
        duration_ms = 0
    try:
        size = int(item.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    try:
        expected_ms = int(expected_duration_ms or 0)
    except (TypeError, ValueError):
        expected_ms = 0
    return expected_ms > 90_000 and 0 < duration_ms <= 65_000 and 0 < size < 2_000_000


def _trial_audio_message(song_name: str = "") -> str:
    label = f"《{song_name}》" if song_name else "该歌曲"
    return f"{label}只返回了 30 秒左右的试听音频，可能需要会员、单曲购买或受版权限制"


class _SearchCache(Generic[_CacheValue]):
    """线程安全的 LRU + TTL 搜索缓存，基于 OrderedDict 实现 O(1) 淘汰。"""

    def __init__(self, max_size: int = 128, ttl: int = 300):
        self._data: OrderedDict[str, tuple[float, _CacheValue]] = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl
        self._lock = threading.Lock()

    def get(self, key: str) -> _CacheValue | None:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            ts, val = entry
            if time.time() - ts > self._ttl:
                self._data.pop(key, None)
                return None
            self._data.move_to_end(key)
            return val

    def put(self, key: str, val: _CacheValue) -> None:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
            elif len(self._data) >= self._max_size:
                self._data.popitem(last=False)
            self._data[key] = (time.time(), val)


class NeteaseCloud:
    """网易云音乐搜索与获取"""

    name = "netease"
    display_name = "网易云"

    def __init__(self):
        self.base_url = NETEASE_CLOUD.get("base_url", "").rstrip("/")
        self.cookie = NETEASE_CLOUD.get("cookie", "")
        self._search_cache: _SearchCache[dict] = _SearchCache()
        self._http = ManagedHttpClient()
        self._last_song_url_error = ""
        self._user_id: int | None = None
        if not self.base_url:
            logger.warning("网易云 API 地址未配置 (NETEASE_CLOUD.base_url)")

    @property
    def last_song_url_error(self) -> str:
        return self._last_song_url_error

    async def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        include_cookie_param: bool = False,
    ) -> dict | None:
        """发起网易云 API 请求；需要登录态的接口用 POST body 携带 cookie。"""
        if not self.base_url:
            return None
        try:
            request_params = dict(params or {})
            headers = {}
            if self.cookie:
                headers["Cookie"] = self.cookie
            if include_cookie_param and self.cookie:
                request_params["cookie"] = self.cookie
            logger.debug(
                "网易云 API 请求: method=%s path=%s params=%s cookie_configured=%s cookie_in_body=%s",
                method.upper(),
                path,
                _safe_params(request_params),
                bool(str(self.cookie or "").strip()),
                include_cookie_param and bool(str(self.cookie or "").strip()),
            )
            return await self._http.request_json(
                method.upper(),
                f"{self.base_url}{path}",
                params=request_params if method.upper() != "POST" else None,
                data=request_params if method.upper() == "POST" else None,
                headers=headers,
                timeout=HTTP_TIMEOUT_DEFAULT,
            )
        except Exception as e:
            logger.error(f"网易云 API 请求失败: {e}")
            return None

    async def _get(self, path: str, params: dict | None = None) -> dict | None:
        """发起 GET 请求（复用连接池）"""
        return await self._request("GET", path, params=params)

    async def _post_with_cookie(self, path: str, params: dict | None = None) -> dict | None:
        """发起带 cookie body 的 POST 请求，供需要会员/登录态的接口使用。"""
        return await self._request("POST", path, params=params, include_cookie_param=True)

    async def search(self, keyword: str, limit: int = 1) -> dict | None:
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
            return dict(cached)

        data = await self._get("/cloudsearch", params={"keywords": keyword, "limit": limit, "type": 1})
        if not data or data.get("code") != 200:
            return None

        songs = data.get("result", {}).get("songs", [])
        if not songs:
            return None

        result = self._parse_song(songs[0])
        if result:
            self._search_cache.put(cache_key, dict(result))
        return result

    async def search_many(self, keyword: str, limit: int = 10, offset: int = 0) -> list[dict]:
        """搜索歌曲，返回多条结果列表"""
        data = await self._get("/cloudsearch", params={
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

    async def get_song_url(self, song_id: int, expected_duration_ms: int = 0, song_name: str = "") -> str | None:
        """获取歌曲播放 URL。level 可选 standard(体积小/弱网友好) 或 exhigh(音质更好)。

        实测 NeteaseCloudMusicApi 本地服务存在缓存错乱 bug：
        请求 id=A 有时会返回上一次 id=B 的 URL（响应里的 id 字段会暴露这一点）。
        因此这里：
        1. 给每次请求加 `timestamp` 破上游缓存；
        2. 拿到响应后校验 `first["id"]` 必须等于 `song_id`，
           否则丢弃这次响应（避免播错歌：UI 显示的是 A，实际推流是 B）。
        """
        level = NETEASE_CLOUD.get("audio_quality", "standard")
        self._last_song_url_error = ""
        logger.debug(
            "网易云获取播放链接开始: song_id=%s level=%s expected_duration_ms=%s cookie_configured=%s",
            song_id,
            level,
            expected_duration_ms or 0,
            bool(str(self.cookie or "").strip()),
        )
        try:
            song_id_int = int(song_id)
        except (TypeError, ValueError):
            song_id_int = None
        requests_to_try = (
            ("/song/url/v1", {"id": song_id, "level": level}),
            ("/song/url", {"id": song_id}),
        )
        for path, params in requests_to_try:
            attempts = [("POST", True), ("GET", False)] if self.cookie else [("GET", False)]
            for method, include_cookie_param in attempts:
                # timestamp 破 NeteaseCloudMusicApi 的本地缓存，避免拿到上一首的 URL
                req_params = dict(params)
                req_params["timestamp"] = int(time.time() * 1000)
                data = (
                    await self._post_with_cookie(path, params=req_params)
                    if method == "POST"
                    else await self._get(path, params=req_params)
                )
                if not data or data.get("code") != 200:
                    logger.debug(
                        "网易云播放链接接口未成功: song_id=%s method=%s path=%s code=%s message=%s",
                        song_id,
                        method,
                        path,
                        data.get("code") if isinstance(data, dict) else None,
                        data.get("message") if isinstance(data, dict) else None,
                    )
                    continue
                urls = data.get("data", [])
                if not urls:
                    logger.debug(
                        "网易云播放链接接口 data 为空: song_id=%s method=%s path=%s",
                        song_id,
                        method,
                        path,
                    )
                    continue
                first = urls[0]
                summary = _song_url_debug_summary(first)
                logger.debug(
                    "网易云播放链接响应: song_id=%s method=%s path=%s summary=%s",
                    song_id,
                    method,
                    path,
                    summary,
                )
                if isinstance(first, dict) and first.get("url"):
                    # 防御 NeteaseCloudMusicApi 缓存错乱：响应 id 必须跟请求 id 匹配
                    resp_id = first.get("id")
                    try:
                        resp_id_int = int(resp_id) if resp_id is not None else None
                    except (TypeError, ValueError):
                        resp_id_int = None
                    if (
                        song_id_int is not None
                        and resp_id_int is not None
                        and resp_id_int != song_id_int
                    ):
                        logger.warning(
                            "网易云播放链接 id 不匹配（疑似上游缓存错乱）: "
                            "请求 song_id=%s 但响应 id=%s, 已丢弃此响应 path=%s method=%s",
                            song_id,
                            resp_id,
                            path,
                            method,
                        )
                        self._last_song_url_error = "上游返回了错乱的 URL"
                        continue
                    if _looks_like_trial_audio(first, expected_duration_ms=expected_duration_ms):
                        self._last_song_url_error = _trial_audio_message(song_name)
                        logger.warning(
                            "网易云返回疑似试听音频: song_id=%s method=%s path=%s summary=%s",
                            song_id,
                            method,
                            path,
                            summary,
                        )
                        continue
                    return first["url"]
                logger.debug(
                    "网易云播放链接为空: song_id=%s method=%s path=%s summary=%s",
                    song_id,
                    method,
                    path,
                    summary,
                )
                if include_cookie_param:
                    logger.debug("网易云 POST cookie body 未拿到可用播放链接，继续尝试 GET 兼容路径")
        if self._last_song_url_error:
            logger.warning(
                "网易云播放链接被拒绝: song_id=%s level=%s reason=%s",
                song_id,
                level,
                self._last_song_url_error,
            )
        else:
            self._last_song_url_error = "无法获取播放链接"
            logger.warning("网易云未获取到播放链接: song_id=%s level=%s", song_id, level)
        return None

    async def get_account_profile(self) -> dict[str, str] | None:
        """通过项目约定的认证接口获取当前登录账号。"""
        if not self.cookie:
            logger.debug("网易云账号身份查询跳过: 未配置 Cookie")
            return None
        data = await self._post_with_cookie(
            "/login/status",
            params={"timestamp": int(time.time() * 1000)},
        )
        response_data = data.get("data") if isinstance(data, dict) else None
        raw_profile = response_data.get("profile") if isinstance(response_data, dict) else None
        if not isinstance(raw_profile, dict) or not raw_profile.get("userId"):
            logger.debug("网易云账号接口未返回可用身份: path=/login/status")
            return None
        logger.debug("网易云账号身份解析成功: path=/login/status")
        return {
            "user_id": str(raw_profile["userId"]),
            "nickname": str(raw_profile.get("nickname") or ""),
            "avatar_url": str(raw_profile.get("avatarUrl") or ""),
        }

    async def get_user_id(self) -> int | None:
        """获取当前登录用户的 ID；Cookie 只在构造时读取，成功结果可整个实例复用。"""
        if self._user_id is not None:
            return self._user_id
        profile = await self.get_account_profile()
        if not profile:
            return None
        self._user_id = int(profile["user_id"])
        return self._user_id

    async def get_liked_ids(self, uid: int) -> list:
        """获取用户喜欢的歌曲 ID 列表"""
        if not self.cookie:
            logger.debug("网易云喜欢列表查询跳过: 未配置 Cookie")
            return []
        data = await self._post_with_cookie(
            "/likelist",
            params={"uid": uid, "timestamp": int(time.time() * 1000)},
        )
        if not isinstance(data, dict) or data.get("code") != 200:
            logger.debug("网易云喜欢列表接口未成功: path=/likelist")
            return []
        ids = data.get("ids")
        if not isinstance(ids, list):
            logger.debug("网易云喜欢列表响应缺少 ids: path=/likelist")
            return []
        return ids

    async def get_song_detail(self, song_id: int) -> dict | None:
        """通过歌曲 ID 获取歌曲详细信息"""
        data = await self._get("/song/detail", params={"ids": str(song_id)})
        if not data or data.get("code") != 200:
            return None

        songs = data.get("songs", [])
        if not songs:
            return None

        return self._parse_song(songs[0])

    async def get_song_details_batch(self, song_ids: list) -> list:
        """批量获取歌曲详细信息（一次最多传 50 个 ID）"""
        if not song_ids:
            return []
        ids_str = ",".join(str(sid) for sid in song_ids)
        data = await self._get("/song/detail", params={"ids": ids_str})
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

    async def get_all_liked_song_details(self, uid: int, max_songs: int = 5000,
                                   batch_size: int = 50) -> list[dict]:
        """拉取登录用户"我喜欢的音乐"全部歌曲详情，用于本地匹配。

        - 单次详情接口最多 50 个 ID，按 batch_size 分批
        - 用 max_songs 兜底，防止用户喜欢列表异常大把启动拖死
        - 任一批次失败不影响其它批次（容错）
        """
        ids = await self.get_liked_ids(uid)
        if not ids:
            return []
        total = len(ids)
        if max_songs > 0 and total > max_songs:
            logger.warning(
                "喜欢列表共 %d 首，超过上限 %d，仅加载前 %d 首到本地索引",
                total, max_songs, max_songs,
            )
            ids = ids[:max_songs]

        out: list[dict] = []
        for i in range(0, len(ids), batch_size):
            chunk = ids[i:i + batch_size]
            try:
                details = await self.get_song_details_batch(chunk)
            except Exception as e:
                logger.debug(f"喜欢列表详情拉取批次失败 (offset={i}): {e}")
                continue
            if details:
                out.extend(details)
        if len(out) < len(ids):
            logger.debug(
                "喜欢列表详情接口返回不全: 请求 %d, 实际 %d", len(ids), len(out),
            )
        return out

    async def summarize_by_id(self, song_id: int) -> dict:
        """通过歌曲 ID 获取完整信息（详情 + URL）"""
        song_info = await self.get_song_detail(song_id)
        if not song_info:
            return {"code": "error", "message": f"无法获取歌曲信息: {song_id}", "data": None}

        url = await self.get_song_url(
            song_id,
            expected_duration_ms=song_info.get("duration", 0) or 0,
            song_name=song_info.get("name", ""),
        )
        if not url:
            detail = self.last_song_url_error or f"无法获取播放链接: {song_info['name']}"
            return {"code": "error", "message": detail, "data": None}

        song_info["url"] = url
        return {"code": "success", "message": "", "data": song_info}

    async def summarize(self, keyword: str) -> dict:
        """
        搜索并汇总歌曲信息（搜索 + 获取 URL），
        返回统一格式供 music.py 调用。
        """
        song_info = await self.search(keyword)
        if not song_info:
            return {"code": "error", "message": f"未找到: {keyword}", "data": None}

        url = await self.get_song_url(
            song_info["id"],
            expected_duration_ms=song_info.get("duration", 0) or 0,
            song_name=song_info.get("name", ""),
        )
        if not url:
            detail = self.last_song_url_error or f"无法获取播放链接: {song_info['name']}"
            return {"code": "error", "message": detail, "data": None}

        song_info["url"] = url

        msg = (
            f"歌曲: {song_info['name']}\n"
            f"歌手: {song_info['artists']}\n"
            f"专辑: {song_info['album']}\n"
            f"时长: {song_info['durationText']}"
        )
        return {"code": "success", "message": msg, "data": song_info}

    async def get_lyrics(self, song_id: int) -> tuple[str | None, str | None]:
        """获取歌曲 LRC 歌词和翻译歌词。
        """
        data = await self._get("/lyric/new", params={"id": song_id})
        if not data or data.get("code") != 200:
            return None, None
        lrc_text = (data.get("lrc") or {}).get("lyric", "")
        tlrc_text = (data.get("tlyric") or {}).get("lyric", "")
        lyric = lrc_text if lrc_text and "[" in lrc_text else None
        tlyric = tlrc_text if tlrc_text and "[" in tlrc_text else None

        if not self._is_placeholder_lyric(lyric):
            return lyric, tlyric

        cloud_lyric = await self.get_cloud_lyric(song_id)
        if cloud_lyric:
            return cloud_lyric, tlyric
        return lyric, tlyric

    @staticmethod
    def _is_placeholder_lyric(lyric: str | None) -> bool:
        """识别网易云无歌词时返回的带时间戳占位文本。"""
        if not lyric:
            return True
        text = lyric
        while "[" in text and "]" in text:
            start = text.find("[")
            end = text.find("]", start)
            if end < 0:
                break
            text = text[:start] + text[end + 1:]
        normalized = "".join(text.split())
        return normalized in {"", "暂无歌词", "纯音乐，请欣赏", "纯音乐,请欣赏"}

    async def get_cloud_lyric(self, song_id: int) -> str | None:
        """获取当前登录账号的云盘歌词。"""
        if not self.cookie:
            return None
        uid = await self.get_user_id()
        if uid is None:
            return None
        data = await self._post_with_cookie(
            "/cloud/lyric/get",
            params={"uid": uid, "sid": song_id},
        )
        if not isinstance(data, dict) or data.get("code") != 200:
            return None
        raw_lrc = data.get("lrc")
        if isinstance(raw_lrc, dict):
            raw_lrc = raw_lrc.get("lyric")
        if not isinstance(raw_lrc, str) or "[" not in raw_lrc:
            return None
        return None if self._is_placeholder_lyric(raw_lrc) else raw_lrc

    async def get_lyric(self, song_id: int) -> str | None:
        """获取歌曲 LRC 歌词文本，无歌词返回 None。"""
        lyric, _ = await self.get_lyrics(song_id)
        return lyric

    async def get_tlyric(self, song_id: int) -> str | None:
        """获取歌曲翻译歌词，无翻译返回 None。"""
        _, tlyric = await self.get_lyrics(song_id)
        return tlyric

    async def close(self) -> None:
        await self._http.close()

    def _parse_song(self, song: dict) -> dict | None:
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
