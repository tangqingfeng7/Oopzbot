"""B 站音乐平台实现。

使用 B 站公开搜索 API + 音频流提取。
配置 BILIBILI_MUSIC_CONFIG.cookie 以获取更高音质。
"""

from __future__ import annotations

import re
from http.cookies import SimpleCookie
from urllib.parse import quote

from core.async_http import ManagedHttpClient
from core.constants import USER_AGENT
from core.http_constants import HTTP_TIMEOUT_DEFAULT
from core.logger_config import get_logger
from web.web_player_config import BILIBILI_MUSIC_CONFIG

logger = get_logger("BilibiliMusic")

_API_SEARCH = "https://api.bilibili.com/x/web-interface/search/type"
_API_AUDIO_INFO = "https://www.bilibili.com/audio/music-service-c/web/song/info"
_API_AUDIO_URL = "https://www.bilibili.com/audio/music-service-c/web/url"
_API_VIDEO_VIEW = "https://api.bilibili.com/x/web-interface/view"
_API_VIDEO_PLAYURL = "https://api.bilibili.com/x/player/playurl"
_BILIBILI_HOME = "https://www.bilibili.com/"

_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "User-Agent": USER_AGENT,
    "Referer": _BILIBILI_HOME,
}



def _cookie_dict(raw: str) -> dict[str, str]:
    """把后台配置里的 Cookie 字符串解析为 Session Cookie。"""
    text = (raw or "").strip()
    if not text:
        return {}
    try:
        parsed = SimpleCookie()
        parsed.load(text)
        return {name: morsel.value for name, morsel in parsed.items() if morsel.value}
    except Exception:
        pairs: dict[str, str] = {}
        for item in text.split(";"):
            if "=" not in item:
                continue
            name, value = item.split("=", 1)
            name = name.strip()
            value = value.strip()
            if name and value:
                pairs[name] = value
        return pairs


def _cookie_debug_summary(raw: str) -> str:
    """生成不含 Cookie 值的调试摘要。"""
    names = sorted(_cookie_dict(raw).keys())
    return f"configured={bool(names)} names={','.join(names) or '-'}"


def _bilibili_referer_for_video(bvid: str) -> str:
    return f"https://www.bilibili.com/video/{bvid}"


class BilibiliMusic:
    """B 站音乐平台，实现 MusicPlatform 协议。"""

    name = "bilibili"
    display_name = "B站"

    def __init__(self):
        cfg = BILIBILI_MUSIC_CONFIG
        self.enabled = cfg.get("enabled", False)
        self.cookie = cfg.get("cookie", "")
        self.last_song_url_error = ""
        self._cookie_pairs = _cookie_dict(self.cookie)
        self._http = ManagedHttpClient(headers=_HEADERS)
        logger.debug("B 站音乐平台初始化: enabled=%s %s", self.enabled, _cookie_debug_summary(self.cookie))

    async def _prime_session(self) -> None:
        """刷新 B 站首页 Cookie，降低公开接口偶发 412 的概率。"""
        try:
            session = await self._http.session()
            async with session.get(
                _BILIBILI_HOME,
                cookies=self._cookie_pairs,
                proxy=self._http.request_proxy(_BILIBILI_HOME),
                timeout=HTTP_TIMEOUT_DEFAULT,
            ) as resp:
                await resp.read()
            logger.debug(
                "B 站首页 Cookie 预热完成: status=%s cookies=%s",
                getattr(resp, "status", "-"),
                ",".join(sorted(cookie.key for cookie in session.cookie_jar)) or "-",
            )
        except Exception as e:
            logger.debug("B 站首页 Cookie 预热失败: %s", e)

    async def _get(self, url: str, params: dict | None = None, referer: str | None = None) -> dict | None:
        request_headers = {}
        if referer:
            request_headers["Referer"] = referer
        try:
            session = await self._http.session()

            async def request_once():
                return await session.get(
                    url,
                    params=params,
                    headers=request_headers,
                    cookies=self._cookie_pairs,
                    proxy=self._http.request_proxy(url),
                    timeout=HTTP_TIMEOUT_DEFAULT,
                )

            resp = await request_once()
            if resp.status == 412:
                resp.release()
                logger.debug("B 站 API 返回 412，刷新首页 Cookie 后重试: url=%s params=%s", url, params or {})
                await self._prime_session()
                resp = await request_once()
            async with resp:
                resp.raise_for_status()
                data = await resp.json(content_type=None)
            if isinstance(data, dict):
                code = data.get("code")
                if code not in (None, 0):
                    logger.debug(
                        "B 站 API 返回业务错误: url=%s code=%s message=%s",
                        url,
                        code,
                        data.get("message") or data.get("msg"),
                    )
                return data
            logger.error("B 站 API 返回格式异常 (%s): %s", url, type(data).__name__)
            return None
        except Exception as e:
            logger.error("B 站 API 请求失败 (%s): %s", url, e)
            return None

    def _set_last_error(self, message: str) -> None:
        self.last_song_url_error = message

    def get_stream_headers(self, song_id) -> dict[str, str]:
        """B 站 CDN 音频直链需要的防盗链请求头。"""
        sid = str(song_id or "").strip()
        if sid.lower().startswith("bv"):
            referer = _bilibili_referer_for_video(sid)
        elif sid.lower().startswith("au"):
            referer = f"https://www.bilibili.com/audio/{sid}"
        else:
            referer = _BILIBILI_HOME
        return {
            "User-Agent": USER_AGENT,
            "Referer": referer,
        }

    async def search(self, keyword: str, limit: int = 1) -> dict | None:
        results = await self._search_audio(keyword, limit)
        if results:
            return results[0]
        results = await self._search_video(keyword, limit)
        if results:
            return results[0]
        return None

    async def search_many(self, keyword: str, limit: int = 10, offset: int = 0) -> list[dict]:
        page = (offset // max(limit, 1)) + 1
        results = await self._search_audio(keyword, limit, page)
        if not results:
            results = await self._search_video(keyword, limit, page)
        return results or []

    async def _search_audio(self, keyword: str, limit: int = 10, page: int = 1) -> list[dict]:
        data = await self._get(_API_SEARCH, params={
            "search_type": "audio",
            "keyword": keyword,
            "page": page,
            "pagesize": limit,
        }, referer=f"https://search.bilibili.com/all?keyword={quote(keyword)}")
        if not data or data.get("code") != 0:
            return []
        items = (data.get("data") or {}).get("result") or []
        return [p for item in items if (p := self._parse_audio(item))]

    async def _search_video(self, keyword: str, limit: int = 10, page: int = 1) -> list[dict]:
        data = await self._get(_API_SEARCH, params={
            "search_type": "video",
            "keyword": keyword + " 音乐",
            "page": page,
            "pagesize": limit,
        }, referer=f"https://search.bilibili.com/all?keyword={quote(keyword)}")
        if not data or data.get("code") != 0:
            return []
        items = (data.get("data") or {}).get("result") or []
        return [p for item in items if (p := self._parse_video(item))]

    async def get_song_url(self, song_id) -> str | None:
        self.last_song_url_error = ""
        sid = str(song_id)
        if sid.startswith("au"):
            url = await self._get_audio_url(sid[2:])
            if not url and not self.last_song_url_error:
                self._set_last_error(f"B站无法获取音频链接: {sid}")
            return url
        if sid.startswith("BV") or sid.startswith("bv"):
            url = await self._get_video_audio_url(sid)
            if not url and not self.last_song_url_error:
                self._set_last_error(f"B站无法获取视频音频流: {sid}")
            return url
        return await self._get_audio_url(sid) or await self._get_video_audio_url(sid)

    async def _get_audio_url(self, au_id: str) -> str | None:
        data = await self._get(
            _API_AUDIO_URL,
            params={"sid": au_id, "privilege": 2, "quality": 2},
            referer=f"https://www.bilibili.com/audio/au{au_id}",
        )
        if not data:
            self._set_last_error(f"B站音频链接请求失败: au{au_id}")
            return None
        if data.get("code") != 0:
            self._set_last_error(
                f"B站音频链接接口返回错误: code={data.get('code')} message={data.get('message') or data.get('msg') or ''}"
            )
            return None
        cdns = (data.get("data") or {}).get("cdns") or []
        if not cdns:
            self._set_last_error(f"B站音频链接为空: au{au_id}")
            return None
        return cdns[0] if cdns else None

    async def _get_video_cid(self, bvid: str) -> str | None:
        data = await self._get(
            _API_VIDEO_VIEW,
            params={"bvid": bvid},
            referer=_bilibili_referer_for_video(bvid),
        )
        if not data or data.get("code") != 0:
            logger.debug("B 站视频 cid 获取失败: bvid=%s", bvid)
            self._set_last_error(f"B站视频 cid 获取失败: {bvid}")
            return None
        video = data.get("data") or {}
        cid = video.get("cid")
        pages = video.get("pages") or []
        if not cid and pages:
            first = pages[0] if isinstance(pages[0], dict) else {}
            cid = first.get("cid")
        if not cid:
            logger.debug("B 站视频详情缺少 cid: bvid=%s", bvid)
            self._set_last_error(f"B站视频详情缺少 cid: {bvid}")
            return None
        return str(cid)

    async def _get_video_audio_url(self, bvid: str) -> str | None:
        cid = await self._get_video_cid(bvid)
        if not cid:
            return None
        data = await self._get(_API_VIDEO_PLAYURL, params={
            "bvid": bvid,
            "cid": cid,
            "fnval": 16,
            "qn": 64,
            "fourk": 1,
        }, referer=_bilibili_referer_for_video(bvid))
        if not data:
            self._set_last_error(f"B站视频播放链接请求失败: {bvid}")
            return None
        if data.get("code") != 0:
            logger.debug("B 站视频播放链接接口失败: bvid=%s cid=%s", bvid, cid)
            self._set_last_error(
                f"B站视频播放链接接口返回错误: code={data.get('code')} message={data.get('message') or data.get('msg') or ''}"
            )
            return None
        dash = (data.get("data") or {}).get("dash") or {}
        audio_list = dash.get("audio") or []
        if audio_list:
            audio_list = sorted(audio_list, key=lambda item: int(item.get("bandwidth") or 0), reverse=True)
            logger.debug("B 站视频音频链接获取成功: bvid=%s cid=%s audio_count=%s", bvid, cid, len(audio_list))
            return audio_list[0].get("baseUrl") or audio_list[0].get("base_url")
        durl = (data.get("data") or {}).get("durl") or []
        if durl:
            logger.debug("B 站视频播放链接回退到 durl: bvid=%s cid=%s", bvid, cid)
            return durl[0].get("url")
        logger.debug("B 站视频播放链接响应中没有 dash.audio/durl: bvid=%s cid=%s", bvid, cid)
        self._set_last_error(f"B站视频播放链接没有音频流: {bvid}")
        return None

    async def get_song_detail(self, song_id) -> dict | None:
        sid = str(song_id)
        if sid.startswith("BV") or sid.startswith("bv"):
            return await self._get_video_detail(sid)
        if sid.startswith("au"):
            sid = sid[2:]
        data = await self._get(_API_AUDIO_INFO, params={"sid": sid})
        if data and data.get("code") == 0 and data.get("data"):
            return self._parse_audio_detail(data["data"])
        return None

    async def _get_video_detail(self, bvid: str) -> dict | None:
        data = await self._get(
            _API_VIDEO_VIEW,
            params={"bvid": bvid},
            referer=_bilibili_referer_for_video(bvid),
        )
        if not data or data.get("code") != 0 or not data.get("data"):
            return None
        video = data["data"]
        owner = video.get("owner") if isinstance(video.get("owner"), dict) else {}
        duration_s = int(video.get("duration") or 0)
        cover = video.get("pic") or ""
        if cover.startswith("//"):
            cover = "https:" + cover
        return {
            "id": video.get("bvid") or bvid,
            "name": video.get("title") or "未知",
            "artists": owner.get("name") or video.get("author") or "未知",
            "album": "",
            "duration": duration_s * 1000,
            "durationText": f"{duration_s // 60}:{duration_s % 60:02d}",
            "cover": cover,
        }

    async def get_lyric(self, song_id) -> str | None:
        sid = str(song_id)
        if sid.startswith("au"):
            sid = sid[2:]
        data = await self._get(
            "https://www.bilibili.com/audio/music-service-c/web/song/lyric",
            params={"sid": sid},
            referer=f"https://www.bilibili.com/audio/au{sid}",
        )
        if not data or data.get("code") != 0:
            return None
        lyric = (data.get("data") or {}).get("lrc") or ""
        return lyric if lyric and "[" in lyric else None

    async def summarize(self, keyword: str) -> dict:
        song = await self.search(keyword)
        if not song:
            return {"code": "error", "message": f"B站未找到: {keyword}", "data": None}
        url = await self.get_song_url(song["id"])
        if not url:
            return {"code": "error", "message": f"B站无法获取播放链接: {song['name']}", "data": None}
        song["url"] = url
        msg = (
            f"歌曲: {song['name']}\n"
            f"作者: {song['artists']}\n"
            f"时长: {song['durationText']}"
        )
        return {"code": "success", "message": msg, "data": song}

    async def summarize_by_id(self, song_id) -> dict:
        song = await self.get_song_detail(song_id)
        if not song:
            return {"code": "error", "message": f"B站无法获取信息: {song_id}", "data": None}
        url = await self.get_song_url(song["id"])
        if not url:
            return {"code": "error", "message": f"B站无法获取播放链接: {song['name']}", "data": None}
        song["url"] = url
        return {"code": "success", "message": "", "data": song}

    async def close(self) -> None:
        await self._http.close()

    def _parse_audio(self, item: dict) -> dict | None:
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

    def _parse_video(self, item: dict) -> dict | None:
        bvid = item.get("bvid") or ""
        if not bvid:
            return None
        title = item.get("title") or "未知"
        title = re.sub(r"<[^>]+>", "", title)
        author = item.get("author") or item.get("up_name") or "未知"
        duration_str = item.get("duration") or "0:00"
        duration_s = 0
        if isinstance(duration_str, str) and ":" in duration_str:
            try:
                # 兼容 MM:SS 与 H:MM:SS，逐段按 60 进制累加。
                seconds = 0
                for part in duration_str.split(":"):
                    seconds = seconds * 60 + int(part)
                duration_s = seconds
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

    def _parse_audio_detail(self, data: dict) -> dict | None:
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
