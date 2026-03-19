"""Oopz 平台 API Mixin — 域/成员/频道/语音/审核等查询与操作。"""

from __future__ import annotations

import copy
import json
import re
import time
from typing import TYPE_CHECKING, Optional

from config import OOPZ_CONFIG
from logger_config import get_logger

if TYPE_CHECKING:
    import requests as _requests_type

logger = get_logger("OopzApi")


class OopzApiMixin:

    # ---- 域成员查询 ----

    def _get_area_members_cache_store(self) -> dict:
        store = getattr(self, "_area_members_cache", None)
        if not isinstance(store, dict):
            store = {}
            self._area_members_cache = store
        return store

    def _get_cached_area_members(
        self,
        cache_key: tuple[str, int, int],
        *,
        max_age: float,
    ) -> Optional[dict]:
        store = self._get_area_members_cache_store()
        cached = store.get(cache_key)
        if not isinstance(cached, dict):
            return None
        ts = cached.get("ts")
        data = cached.get("data")
        if not isinstance(ts, (int, float)) or not isinstance(data, dict):
            return None
        if time.time() - float(ts) > max_age:
            return None
        return copy.deepcopy(data)

    def _set_cached_area_members(self, cache_key: tuple[str, int, int], data: dict) -> None:
        store = self._get_area_members_cache_store()
        store[cache_key] = {"ts": time.time(), "data": copy.deepcopy(data)}

    def get_area_members(self, area: Optional[str] = None, offset_start: int = 0, offset_end: int = 49, quiet: bool = False) -> dict:
        """
        获取域内成员列表及在线状态。

        API: GET /area/v3/members?area={area}&offsetStart={start}&offsetEnd={end}

        Args:
            quiet: 为 True 时不向控制台打成功日志（用于轮询等后台调用）。

        Returns:
            {"members": [...], "userCount": int, "onlineCount": int, ...}
            或 {"error": "..."} 表示失败
        """
        area = area or OOPZ_CONFIG["default_area"]
        url_path = "/area/v3/members"
        params = {"area": area, "offsetStart": str(offset_start), "offsetEnd": str(offset_end)}
        max_attempts = 3
        cache_key = (str(area), int(offset_start), int(offset_end))
        cache_ttl = float(getattr(self, "_area_members_cache_ttl", 2.0))
        stale_ttl = float(getattr(self, "_area_members_stale_ttl", 300.0))

        if quiet:
            cached = self._get_cached_area_members(cache_key, max_age=cache_ttl)
            if cached is not None:
                return cached

        try:
            resp = None
            for attempt in range(1, max_attempts + 1):
                resp = self._get(url_path, params=params)
                if resp.status_code != 429:
                    break

                retry_after = 0
                try:
                    retry_after = int(resp.headers.get("Retry-After", "0") or "0")
                except Exception:
                    retry_after = 0
                wait_seconds = retry_after if retry_after > 0 else min(attempt, 3)

                if attempt >= max_attempts:
                    stale_cached = self._get_cached_area_members(cache_key, max_age=stale_ttl)
                    if stale_cached is not None:
                        stale_cached["stale"] = True
                        stale_cached["rateLimited"] = True
                        logger.warning(
                            "获取域成员被限流，返回 %.1fs 内缓存数据 (area=%s, offset=%s-%s)",
                            stale_ttl,
                            area,
                            offset_start,
                            offset_end,
                        )
                        return stale_cached
                    logger.warning(
                        "获取域成员被限流: HTTP 429 (area=%s, offset=%s-%s, 已重试%d次)",
                        area,
                        offset_start,
                        offset_end,
                        max_attempts - 1,
                    )
                    return {"error": "HTTP 429"}

                logger.warning(
                    "获取域成员被限流: HTTP 429 (area=%s, offset=%s-%s), %.1fs 后重试 (%d/%d)",
                    area,
                    offset_start,
                    offset_end,
                    float(wait_seconds),
                    attempt,
                    max_attempts - 1,
                )
                time.sleep(wait_seconds)

            if resp is None:
                return {"error": "未获得响应"}

            if resp.status_code != 200:
                logger.debug(f"获取域成员失败: HTTP {resp.status_code}")
                stale = self._get_cached_area_members(cache_key, max_age=stale_ttl)
                if stale is not None:
                    stale["stale"] = True
                    return stale
                return {"error": f"HTTP {resp.status_code}"}

            if not resp.content:
                logger.debug("获取域成员失败: HTTP 200 但响应体为空")
                stale = self._get_cached_area_members(cache_key, max_age=stale_ttl)
                if stale is not None:
                    stale["stale"] = True
                    return stale
                return {"error": "empty response"}

            try:
                result = resp.json()
            except ValueError:
                content_encoding = (resp.headers.get("Content-Encoding") or "").lower()
                if content_encoding in ("br", "zstd") or (
                    resp.content and resp.content[:4] != b'{"st'
                ):
                    logger.debug(
                        "获取域成员失败: 响应体可能未被正确解压 "
                        "(Content-Encoding=%s, len=%d)。"
                        "请确保已安装 brotli 和 zstandard 包: "
                        "pip install brotli zstandard",
                        content_encoding or "未知",
                        len(resp.content),
                    )
                else:
                    logger.debug(
                        "获取域成员失败: 响应非合法 JSON (len=%d, status=%d, preview=%r)",
                        len(resp.content),
                        resp.status_code,
                        resp.content[:200],
                    )
                stale = self._get_cached_area_members(cache_key, max_age=stale_ttl)
                if stale is not None:
                    stale["stale"] = True
                    return stale
                return {"error": "invalid JSON"}
            if not result.get("status"):
                msg = result.get("message") or result.get("error") or "未知错误"
                logger.debug(f"获取域成员失败: {msg}")
                stale = self._get_cached_area_members(cache_key, max_age=stale_ttl)
                if stale is not None:
                    stale["stale"] = True
                    return stale
                return {"error": msg}

            data = result.get("data", {})
            members = data.get("members", [])
            online = sum(1 for m in members if m.get("online") == 1)
            fetched = len(members)
            api_total = data.get("totalCount") or data.get("userCount")
            try:
                total = int(api_total) if api_total is not None else fetched
            except Exception:
                total = fetched

            role_count = data.get("roleCount", [])
            online_from_api = sum(
                rc.get("count", 0) for rc in role_count if rc.get("role", 0) != -1
            ) if role_count else online

            if not quiet:
                logger.info(f"获取域成员成功: 本页 {fetched} 人, 在线 {online_from_api} 人, 域总人数 {total}")
            data["onlineCount"] = online_from_api or online
            data["totalCount"] = total
            data["userCount"] = total
            data["fetchedCount"] = fetched
            self._set_cached_area_members(cache_key, data)
            return data
        except Exception as e:
            logger.error(f"获取域成员异常: {e}")
            stale = self._get_cached_area_members(cache_key, max_age=stale_ttl)
            if stale is not None:
                stale["stale"] = True
                return stale
            return {"error": str(e)}

    # ---- 频道列表 ----

    def get_area_channels(self, area: Optional[str] = None, quiet: bool = False) -> list:
        """
        获取域内完整频道列表（含分组）。

        API: GET /client/v1/area/v1/detail/v1/channels?area={area}

        Args:
            quiet: 为 True 时不打成功日志（用于轮询等后台调用）。

        Returns:
            频道分组列表，每组含 channels 子列表。失败时返回空列表。
        """
        area = area or OOPZ_CONFIG["default_area"]
        url_path = "/client/v1/area/v1/detail/v1/channels"
        params = {"area": area}

        try:
            resp = self._get(url_path, params=params)
            if resp.status_code != 200:
                logger.error(f"获取频道列表失败: HTTP {resp.status_code}")
                return []
            result = resp.json()
            if not result.get("status"):
                logger.error(f"获取频道列表失败: {result.get('message') or result.get('error')}")
                return []
            groups = result.get("data") or []
            if not quiet:
                total = sum(len(g.get("channels") or []) for g in groups)
                logger.info(f"获取频道列表: {total} 个频道, {len(groups)} 个分组")
            return groups
        except Exception as e:
            logger.error(f"获取频道列表异常: {e}")
            return []

    def get_channel_setting_info(self, channel: str) -> dict:
        """
        获取频道设置详情（名称、访问权限等）。

        API: GET /area/v3/channel/setting/info?channel={channel}
        """
        channel = str(channel or "").strip()
        if not channel:
            return {"error": "缺少 channel"}

        url_path = "/area/v3/channel/setting/info"
        params = {"channel": channel}
        try:
            resp = self._get(url_path, params=params)
            if resp.status_code != 200:
                logger.error(f"获取频道设置失败: HTTP {resp.status_code}")
                return {"error": f"HTTP {resp.status_code}"}
            result = resp.json()
            if not result.get("status"):
                msg = result.get("message") or result.get("error") or "未知错误"
                logger.error(f"获取频道设置失败: {msg}")
                return {"error": msg}
            data = result.get("data", {})
            if not isinstance(data, dict):
                return {"error": "频道设置响应格式异常"}
            return data
        except Exception as e:
            logger.error(f"获取频道设置异常: {e}")
            return {"error": str(e)}

    def _pick_channel_group(
        self,
        area: str,
        preferred_channel: Optional[str] = None,
        preferred_group_name: Optional[str] = None,
    ) -> Optional[str]:
        """优先按分组名匹配，否则选当前频道所在分组，再回退到第一个可用分组。"""
        groups = self.get_area_channels(area=area, quiet=True) or []
        preferred_channel = str(preferred_channel or "").strip()
        preferred_group_name = str(preferred_group_name or "").strip().lower()

        fallback = None
        for group in groups:
            group_id = str(group.get("id") or "").strip()
            if not group_id:
                continue
            group_name = str(group.get("name") or "").strip().lower()
            if not fallback:
                fallback = group_id
            if preferred_group_name and group_name == preferred_group_name:
                return group_id
            channels = group.get("channels") or []
            if preferred_channel and any(str(ch.get("id") or "") == preferred_channel for ch in channels):
                return group_id
        if preferred_group_name:
            return None
        return fallback

    def create_restricted_text_channel(
        self,
        target_uid: str,
        area: Optional[str] = None,
        preferred_channel: Optional[str] = None,
        name: Optional[str] = None,
    ) -> dict:
        """
        创建仅指定成员可见的文字频道。

        先创建频道，再通过 setting/edit 开启访问权限并写入 accessibleMembers。
        """
        area = area or OOPZ_CONFIG["default_area"]
        target_uid = str(target_uid or "").strip()
        if not target_uid:
            return {"error": "缺少 target_uid"}

        group_id = self._pick_channel_group(area, preferred_channel=preferred_channel)
        if not group_id:
            return {"error": "未找到可用频道分组"}

        default_name = f"登录-{target_uid[-4:]}-{time.strftime('%H%M%S')}"
        channel_name = (name or default_name).strip() or "登录"
        url_path = "/client/v1/area/v1/channel/v1/create"
        body = {
            "area": area,
            "group": group_id,
            "name": channel_name,
            "type": "TEXT",
            "secret": True,
        }

        try:
            resp = self._post(url_path, body)
        except Exception as e:
            logger.error(f"创建受限频道异常: {e}")
            return {"error": str(e)}

        raw = resp.text or ""
        logger.info(f"创建受限频道 POST {url_path} -> HTTP {resp.status_code}, body: {raw[:300]}")
        if resp.status_code != 200:
            return {"error": f"HTTP {resp.status_code}" + (f" | {raw[:200]}" if raw else "")}

        try:
            result = resp.json()
        except Exception:
            return {"error": f"响应非 JSON: {raw[:200]}"}

        if not result.get("status"):
            msg = result.get("message") or result.get("error") or "创建频道失败"
            return {"error": str(msg)}

        data = result.get("data", {})
        channel_id = self._extract_channel_id(data) or self._extract_channel_id(result)
        if not channel_id:
            return {"error": "创建频道成功，但未能提取频道 ID"}

        setting = self.get_channel_setting_info(channel_id)
        if isinstance(setting, dict) and "error" in setting:
            logger.warning("获取新频道设置失败，改用默认值: %s", setting["error"])
            setting = {}

        edit_body = {
            "channel": channel_id,
            "name": str(setting.get("name") or channel_name),
            "textGapSecond": int(setting.get("textGapSecond", 0) or 0),
            "area": area,
            "voiceQuality": str(setting.get("voiceQuality") or "64k"),
            "voiceDelay": str(setting.get("voiceDelay") or "LOW"),
            "maxMember": int(setting.get("maxMember", 30000) or 30000),
            "voiceControlEnabled": bool(setting.get("voiceControlEnabled", False)),
            "textControlEnabled": bool(setting.get("textControlEnabled", False)),
            "textRoles": list(setting.get("textRoles") or []),
            "voiceRoles": list(setting.get("voiceRoles") or []),
            "accessControlEnabled": True,
            "accessible": [],
            "accessibleMembers": [
                uid for uid in dict.fromkeys([
                    str(target_uid),
                    str(OOPZ_CONFIG.get("person_uid") or ""),
                ]) if uid
            ],
            "secret": bool(setting.get("secret", True)),
            "hasPassword": bool(setting.get("hasPassword", False)),
            "password": str(setting.get("password") or ""),
        }

        edit_path = "/area/v3/channel/setting/edit"
        try:
            edit_resp = self._post(edit_path, edit_body)
        except Exception as e:
            logger.error(f"设置受限频道权限异常: {e}")
            self.delete_channel(channel_id, area=area)
            return {"error": str(e)}

        edit_raw = edit_resp.text or ""
        logger.info(f"设置受限频道权限 POST {edit_path} -> HTTP {edit_resp.status_code}, body: {edit_raw[:300]}")
        if edit_resp.status_code != 200:
            self.delete_channel(channel_id, area=area)
            return {"error": f"HTTP {edit_resp.status_code}" + (f" | {edit_raw[:200]}" if edit_raw else "")}

        try:
            edit_result = edit_resp.json()
        except Exception:
            self.delete_channel(channel_id, area=area)
            return {"error": f"权限设置响应非 JSON: {edit_raw[:200]}"}

        if not edit_result.get("status"):
            self.delete_channel(channel_id, area=area)
            msg = edit_result.get("message") or edit_result.get("error") or "权限设置失败"
            return {"error": str(msg)}

        logger.info("创建受限频道成功: channel=%s target=%s", channel_id[:24], target_uid[:12])
        return {
            "status": True,
            "channel": channel_id,
            "group": group_id,
            "name": edit_body["name"],
        }

    def delete_channel(self, channel: str, area: Optional[str] = None) -> dict:
        """
        删除频道。

        API: DELETE /client/v1/area/v1/channel/v1/delete?area={area}&channel={channel}
        """
        area = area or OOPZ_CONFIG["default_area"]
        channel = str(channel or "").strip()
        if not channel:
            return {"error": "缺少 channel"}

        url_path = "/client/v1/area/v1/channel/v1/delete"
        query = f"?channel={channel}&area={area}"
        full_path = url_path + query

        try:
            headers = {**self.session.headers, **self.signer.oopz_headers(full_path, "")}
            url = OOPZ_CONFIG["base_url"] + full_path
            resp = self.session.delete(url, headers=headers)
        except Exception as e:
            logger.error(f"删除频道异常: {e}")
            return {"error": str(e)}

        raw = resp.text or ""
        logger.info(f"删除频道 DELETE {full_path} -> HTTP {resp.status_code}, body: {raw[:300]}")
        if resp.status_code != 200:
            return {"error": f"HTTP {resp.status_code}" + (f" | {raw[:200]}" if raw else "")}

        try:
            result = resp.json()
        except Exception:
            return {"error": f"响应非 JSON: {raw[:200]}"}

        if result.get("status") is True:
            return {"status": True, "message": result.get("message") or "已删除频道"}

        err = result.get("message") or result.get("error") or str(result)
        logger.error(f"删除频道失败: {err}")
        return {"error": err}

    # ---- 已加入的域列表 ----

    def get_joined_areas(self, quiet: bool = False) -> list:
        """
        获取当前用户已加入（订阅）的域列表。

        API: GET /userSubscribeArea/v1/list

        Args:
            quiet: 为 True 时不打成功日志（用于轮询等后台调用）。

        Returns:
            域信息列表，每个元素包含 id / code / name / avatar / owner 等字段。
            失败时返回空列表。
        """
        url_path = "/userSubscribeArea/v1/list"
        try:
            resp = self._get(url_path)
            if resp.status_code != 200:
                logger.error(f"获取已加入域列表失败: HTTP {resp.status_code}")
                return []
            result = resp.json()
            if not result.get("status"):
                logger.error(f"获取已加入域列表失败: {result.get('message') or result.get('error')}")
                return []
            areas = result.get("data", [])
            if not quiet:
                logger.info(f"获取已加入域列表: {len(areas)} 个域")
                for a in areas:
                    logger.info(f"  域: {a.get('name')} (ID={a.get('id')}, code={a.get('code')})")
            return areas
        except Exception as e:
            logger.error(f"获取已加入域列表异常: {e}")
            return []

    # ---- 域详情（含频道） ----

    def get_area_info(self, area: Optional[str] = None) -> dict:
        """
        获取域详细信息（含角色列表、主页频道 ID/名称等）。

        API: GET /area/v3/info?area={area}

        Returns:
            域信息字典，或 {"error": "..."} 表示失败。
        """
        area = area or OOPZ_CONFIG["default_area"]
        url_path = "/area/v3/info"
        params = {"area": area}
        try:
            resp = self._get(url_path, params=params)
            if resp.status_code != 200:
                logger.error(f"获取域详情失败: HTTP {resp.status_code}")
                return {"error": f"HTTP {resp.status_code}"}
            result = resp.json()
            if not result.get("status"):
                return {"error": result.get("message") or result.get("error") or "未知错误"}
            return result.get("data", {})
        except Exception as e:
            logger.error(f"获取域详情异常: {e}")
            return {"error": str(e)}

    # ---- 启动时自动填充域/频道名称 ----

    def populate_names(self):
        """
        从 API 获取已加入的域列表及各域频道列表，
        自动填充 NameResolver 中的域名称和频道名称。
        """
        from name_resolver import get_resolver
        resolver = get_resolver()

        areas = self.get_joined_areas()
        for a in areas:
            area_id = a.get("id", "")
            area_name = a.get("name", "")
            if area_id and area_name:
                resolver.set_area(area_id, area_name)

            groups = self.get_area_channels(area_id) or []
            for group in groups:
                for ch in (group.get("channels") or []):
                    ch_id = ch.get("id", "")
                    ch_name = ch.get("name", "")
                    if ch_id and ch_name:
                        resolver.set_channel(ch_id, ch_name)

        stats = resolver.get_stats()
        logger.info(
            f"名称自动填充完成: "
            f"{stats['areas_named']} 个域, "
            f"{stats['channels_named']} 个频道"
        )

    # ---- 批量获取用户信息 ----

    def get_person_infos_batch(self, uids: list[str]) -> dict[str, dict]:
        """
        批量获取用户基本信息（昵称、头像、在线状态等）。

        API: POST /client/v1/person/v1/personInfos

        Args:
            uids: 用户 UID 列表

        Returns:
            {uid: {name, avatar, online, pid, ...}, ...}
        """
        if not uids:
            return {}
        url_path = "/client/v1/person/v1/personInfos"
        result_map: dict[str, dict] = {}
        batch_size = 30
        for i in range(0, len(uids), batch_size):
            batch = uids[i : i + batch_size]
            body = {"persons": batch, "commonIds": []}
            try:
                resp = self._post(url_path, body)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                if not data.get("status"):
                    continue
                for person in data.get("data", []):
                    uid = person.get("uid", "")
                    if uid:
                        result_map[uid] = person
            except Exception as e:
                logger.debug(f"批量获取用户信息部分失败: {e}")
        return result_map

    # ---- 个人详细信息 ----

    def get_person_detail(self, uid: Optional[str] = None) -> dict:
        """
        通过 personInfos 接口获取用户信息（可查询任意用户）。

        Args:
            uid: 用户 UID（默认取当前 Bot 自身的 UID）

        Returns:
            包含用户信息的字典，或 {"error": "..."} 表示失败
        """
        uid = uid or OOPZ_CONFIG["person_uid"]
        url_path = "/client/v1/person/v1/personInfos"
        body = {"persons": [uid], "commonIds": []}

        try:
            resp = self._post(url_path, body)
            if resp.status_code != 200:
                logger.error(f"获取个人信息失败: HTTP {resp.status_code}")
                return {"error": f"HTTP {resp.status_code}"}

            result = resp.json()
            if not result.get("status"):
                msg = result.get("message") or result.get("error") or "未知错误"
                logger.error(f"获取个人信息失败: {msg}")
                return {"error": msg}

            data_list = result.get("data", [])
            if not data_list:
                return {"error": "未找到该用户"}

            person = data_list[0]
            logger.info(f"获取个人信息成功: {person.get('name', '未知')}")
            return person
        except Exception as e:
            logger.error(f"获取个人信息异常: {e}")
            return {"error": str(e)}

    # ---- 他人详细资料 ----

    def get_person_detail_full(self, uid: str) -> dict:
        """
        获取他人完整详细资料（比 personInfos 更详细，含 VIP、IP 属地等）。

        API: GET /client/v1/person/v1/personDetail?uid={uid}
        """
        url_path = "/client/v1/person/v1/personDetail"
        params = {"uid": uid}
        try:
            resp = self._get(url_path, params=params)
            if resp.status_code != 200:
                return {"error": f"HTTP {resp.status_code}"}
            result = resp.json()
            if not result.get("status"):
                return {"error": result.get("message") or "未知错误"}
            return result.get("data", {})
        except Exception as e:
            logger.error(f"获取他人详细资料异常: {e}")
            return {"error": str(e)}

    # ---- 自身详细资料 ----

    def get_self_detail(self) -> dict:
        """
        获取当前登录用户的完整详细资料。

        API: GET /client/v1/person/v2/selfDetail?uid={uid}
        """
        uid = OOPZ_CONFIG["person_uid"]
        url_path = "/client/v1/person/v2/selfDetail"
        params = {"uid": uid}
        try:
            resp = self._get(url_path, params=params)
            if resp.status_code != 200:
                return {"error": f"HTTP {resp.status_code}"}
            result = resp.json()
            if not result.get("status"):
                return {"error": result.get("message") or "未知错误"}
            return result.get("data", {})
        except Exception as e:
            logger.error(f"获取自身详细资料异常: {e}")
            return {"error": str(e)}

    # ---- 用户等级信息 ----

    def get_level_info(self) -> dict:
        """
        获取当前用户等级、积分信息。

        API: GET /user_points/v1/level_info

        Returns:
            {"currentLevel": int, "nextLevel": int, "nextLevelDistance": int, ...}
        """
        url_path = "/user_points/v1/level_info"
        try:
            resp = self._get(url_path)
            if resp.status_code != 200:
                return {"error": f"HTTP {resp.status_code}"}
            result = resp.json()
            if not result.get("status"):
                return {"error": result.get("message") or "未知错误"}
            return result.get("data", {})
        except Exception as e:
            logger.error(f"获取等级信息异常: {e}")
            return {"error": str(e)}

    # ---- 用户在域内的角色 / 禁言状态 ----

    def get_user_area_detail(self, target: str, area: Optional[str] = None) -> dict:
        """
        获取指定用户在域内的角色列表和禁言/禁麦状态。

        API: GET /area/v3/userDetail?area={area}&target={uid}

        Returns:
            {"list": [{"roleID":..., "name":...}], "disableTextTo":..., "disableVoiceTo":..., "higherUid":...}
        """
        area = area or OOPZ_CONFIG["default_area"]
        url_path = "/area/v3/userDetail"
        params = {"area": area, "target": target}
        try:
            resp = self._get(url_path, params=params)
            if resp.status_code != 200:
                return {"error": f"HTTP {resp.status_code}"}
            result = resp.json()
            if not result.get("status"):
                return {"error": result.get("message") or "未知错误"}
            return result.get("data", {})
        except Exception as e:
            logger.error(f"获取用户域内详情异常: {e}")
            return {"error": str(e)}

    # ---- 可分配的角色列表 ----

    def get_assignable_roles(self, target: str, area: Optional[str] = None) -> list:
        """
        获取当前用户可以分配给目标用户的角色列表。

        API: GET /area/v3/role/canGiveList?area={area}&target={uid}

        Returns:
            [{"roleID": int, "name": str, "owned": bool, "sort": int}, ...]
        """
        area = area or OOPZ_CONFIG["default_area"]
        url_path = "/area/v3/role/canGiveList"
        params = {"area": area, "target": target}
        try:
            resp = self._get(url_path, params=params)
            if resp.status_code != 200:
                logger.error(f"获取可分配角色失败: HTTP {resp.status_code}")
                return []
            result = resp.json()
            if not result.get("status"):
                return []
            data = result.get("data")
            if not isinstance(data, dict):
                return []
            return data.get("roles", [])
        except Exception as e:
            logger.error(f"获取可分配角色异常: {e}")
            return []

    # ---- 给/取消身份组 ----

    def edit_user_role(
        self,
        target_uid: str,
        role_id: int,
        add: bool,
        area: Optional[str] = None,
    ) -> dict:
        """
        给目标用户添加或取消指定身份组。

        真实 API（与 Web 端一致）:
        POST /area/v3/role/editUserRole
        Body: {"area": area, "target": target_uid, "targetRoleIDs": [id1, id2, ...]}
        语义：将目标用户在该域内的身份组设置为 targetRoleIDs 列表（全量覆盖）。

        Args:
            target_uid: 目标用户 UID
            role_id: 身份组 ID（来自 canGiveList 或 userDetail.list）
            add: True=给身份组，False=取消身份组
            area: 域 ID，默认取配置

        Returns:
            {"status": True, "message": "..."} 或 {"error": "..."}
        """
        area = area or OOPZ_CONFIG["default_area"]
        detail = self.get_user_area_detail(target_uid, area=area)
        if "error" in detail:
            return {"error": detail["error"]}
        current_list = detail.get("list") or []
        current_ids = [int(r["roleID"]) for r in current_list if r.get("roleID") is not None]
        role_id = int(role_id)
        if add:
            if role_id not in current_ids:
                current_ids.append(role_id)
        else:
            current_ids = [x for x in current_ids if x != role_id]
        url_path = "/area/v3/role/editUserRole"
        body = {"area": area, "target": target_uid, "targetRoleIDs": current_ids}
        try:
            resp = self._post(url_path, body)
            raw = resp.text or ""
            logger.info(f"editUserRole POST {url_path} add={add} -> {resp.status_code}, body: {raw[:200]}")
            if resp.status_code != 200:
                return {"error": f"HTTP {resp.status_code}" + (f" | {raw[:150]}" if raw else "")}
            result = resp.json()
            if result.get("status") is True:
                return {"status": True, "message": result.get("message") or ("已给身份组" if add else "已取消身份组")}
            return {"error": result.get("message") or result.get("error") or str(result)}
        except Exception as e:
            logger.error(f"editUserRole 异常: {e}")
            return {"error": str(e)}

    # ---- 搜索域成员 ----

    def search_area_members(self, area: Optional[str] = None, keyword: str = "") -> list:
        """
        搜索域内成员（含角色信息、加入时间）。

        API: POST /area/v3/search/areaSettingMembers

        Returns:
            [{"uid": str, "roleInfos": [...], "enterTime": int}, ...]
        """
        area = area or OOPZ_CONFIG["default_area"]
        url_path = "/area/v3/search/areaSettingMembers"
        body = {"area": area, "name": keyword, "offset": 0, "limit": 50}
        try:
            resp = self._post(url_path, body)
            if resp.status_code != 200:
                logger.error(f"搜索域成员失败: HTTP {resp.status_code}")
                return []
            result = resp.json()
            if not result.get("status"):
                return []
            return result.get("data", {}).get("members", [])
        except Exception as e:
            logger.error(f"搜索域成员异常: {e}")
            return []

    # ---- 各语音频道在线成员 ----

    def get_voice_channel_members(self, area: Optional[str] = None) -> dict:
        """
        获取域内各语音频道的在线成员列表。

        API: POST /area/v3/channel/membersByChannels

        Returns:
            {"channelId1": [uid1, uid2, ...], "channelId2": [...], ...}
        """
        area = area or OOPZ_CONFIG["default_area"]
        groups = self.get_area_channels(area)
        voice_ids = []
        for g in groups:
            for ch in g.get("channels", []):
                if ch.get("type") == "VOICE":
                    voice_ids.append(ch["id"])
        if not voice_ids:
            return {}

        url_path = "/area/v3/channel/membersByChannels"
        body = {"area": area, "channels": voice_ids}
        try:
            resp = self._post(url_path, body)
            if resp.status_code != 200:
                logger.error(f"获取语音频道成员失败: HTTP {resp.status_code}")
                return {}
            result = resp.json()
            if not result.get("status"):
                return {}
            return result.get("data", {}).get("channelMembers", {})
        except Exception as e:
            logger.error(f"获取语音频道成员异常: {e}")
            return {}

    def get_voice_channel_for_user(self, user_uid: str, area: Optional[str] = None) -> Optional[str]:
        """
        获取用户当前所在的语音频道 ID。
        若用户不在任何语音频道，返回 None。
        """
        members = self.get_voice_channel_members(area=area)
        for ch_id, ch_members in members.items():
            if not ch_members:
                continue
            for m in ch_members:
                uid = m.get("uid", m.get("id", "")) if isinstance(m, dict) else str(m)
                if uid == user_uid:
                    return ch_id
        return None

    # ---- 进入域 / 进入频道 ----

    def enter_area(self, area: Optional[str] = None, recover: bool = False) -> dict:
        """
        进入指定域（前置步骤，进入语音频道前需先进入域）。

        API: POST /client/v1/area/v1/enter?area={area}&recover={recover}
        """
        area = area or OOPZ_CONFIG["default_area"]
        url_path = f"/client/v1/area/v1/enter?area={area}&recover={str(recover).lower()}"
        body = {"area": area, "recover": recover}
        try:
            resp = self._post(url_path, body)
            if resp.status_code != 200:
                return {"error": f"HTTP {resp.status_code}"}
            result = resp.json()
            if not result.get("status"):
                return {"error": result.get("message") or result.get("error") or "未知错误"}
            return result.get("data", {})
        except Exception as e:
            logger.error(f"进入域异常: {e}")
            return {"error": str(e)}

    def enter_channel(self, channel: Optional[str] = None, area: Optional[str] = None,
                      channel_type: str = "TEXT", from_channel: str = "",
                      from_area: str = "", pid: str = "") -> dict:
        """
        进入指定频道（获取频道配置、语音参数、禁言状态等）。

        API: POST /area/v2/channel/enter

        Args:
            channel:      频道 ID
            area:         域 ID
            channel_type: 频道类型，"TEXT" 或 "VOICE"
            from_channel: 切换语音频道时，来源频道 ID
            from_area:    切换语音频道时，来源域 ID
            pid:          语音频道 Agora uid，服务端据此生成 Token

        Returns:
            {"voiceQuality": str, "voiceDelay": str, "disableTextTo": ..., "roleSort": int, ...}
        """
        area = area or OOPZ_CONFIG["default_area"]
        channel = channel or OOPZ_CONFIG["default_channel"]
        url_path = "/area/v2/channel/enter"

        body: dict = {"type": channel_type, "area": area, "channel": channel}
        if channel_type == "VOICE":
            body.update({
                "fromChannel": from_channel,
                "fromArea": from_area,
                "password": "",
                "sign": 1,
                "pid": pid,
            })

        try:
            resp = self._post(url_path, body)
            if resp.status_code != 200:
                return {"error": f"HTTP {resp.status_code}"}
            result = resp.json()
            if not result.get("status"):
                return {"error": result.get("message") or "未知错误"}
            return result.get("data", {})
        except Exception as e:
            logger.error(f"进入频道异常: {e}")
            return {"error": str(e)}

    def leave_voice_channel(self, channel: str, area: Optional[str] = None,
                            target: Optional[str] = None) -> dict:
        """
        退出语音频道。

        API: DELETE /client/v1/area/v1/member/v1/removeFromChannel
             ?area={area}&channel={channel}&target={uid}

        Args:
            channel: 语音频道 ID
            area:    域 ID（默认取配置）
            target:  要移出的用户 UID（默认为 Bot 自身）
        """
        area = area or OOPZ_CONFIG["default_area"]
        target = target or OOPZ_CONFIG["person_uid"]
        url_path = "/client/v1/area/v1/member/v1/removeFromChannel"
        query = f"?area={area}&channel={channel}&target={target}"
        full_path = url_path + query

        try:
            body_str = ""
            headers = {**self.session.headers, **self.signer.oopz_headers(full_path, body_str)}
            url = OOPZ_CONFIG["base_url"] + full_path
            resp = self.session.delete(url, headers=headers)
        except Exception as e:
            logger.error(f"退出语音频道异常: {e}")
            return {"error": str(e)}

        raw = resp.text or ""
        logger.info(f"退出语音频道 DELETE {full_path} -> HTTP {resp.status_code}")

        if resp.status_code != 200:
            return {"error": f"HTTP {resp.status_code}" + (f" | {raw[:200]}" if raw else "")}

        try:
            result = resp.json()
        except Exception:
            return {"error": f"响应非 JSON: {raw[:200]}"}

        if result.get("status") is True:
            logger.info("已退出语音频道")
            return {"status": True, "message": "已退出语音频道"}

        err = result.get("message") or result.get("error") or str(result)
        logger.error(f"退出语音频道失败: {err}")
        return {"error": err}

    # ---- 每日一句 ----

    def get_daily_speech(self) -> dict:
        """
        获取开屏每日一句（名言）。

        Returns:
            {"words": "文本内容", "author": "作者"}
            或 {"error": "..."} 表示失败
        """
        url_path = "/general/v1/speech"

        try:
            resp = self._get(url_path)
            if resp.status_code != 200:
                logger.error(f"获取每日一句失败: HTTP {resp.status_code}")
                return {"error": f"HTTP {resp.status_code}"}

            result = resp.json()
            if not result.get("status"):
                msg = result.get("message") or result.get("error") or "未知错误"
                logger.error(f"获取每日一句失败: {msg}")
                return {"error": msg}

            data = result["data"]
            logger.info(f"每日一句: {data.get('words', '')[:30]}...")
            return data
        except Exception as e:
            logger.error(f"获取每日一句异常: {e}")
            return {"error": str(e)}

    # ---- 获取频道消息 ----

    def get_channel_messages(
        self,
        area: Optional[str] = None,
        channel: Optional[str] = None,
        size: int = 50,
    ) -> list:
        """
        获取频道最近的消息列表（含 messageId / timestamp / person / content 等）。

        API: GET /im/session/v2/messageBefore?area={area}&channel={channel}&size={size}

        Returns:
            消息列表（按时间倒序，最新在前），失败时返回空列表。
        """
        area = area or OOPZ_CONFIG["default_area"]
        channel = channel or OOPZ_CONFIG["default_channel"]
        url_path = "/im/session/v2/messageBefore"
        params = {"area": area, "channel": channel, "size": str(size)}

        try:
            resp = self._get(url_path, params=params)
            if resp.status_code != 200:
                logger.error(f"获取频道消息失败: HTTP {resp.status_code}")
                return []
            result = resp.json()
            if not result.get("status"):
                logger.error(f"获取频道消息失败: {result.get('message') or result.get('error')}")
                return []
            raw_list = result.get("data", {}).get("messages", [])
            messages = []
            for m in raw_list:
                mid = m.get("messageId") or m.get("id")
                if mid is not None:
                    m = {**m, "messageId": str(mid)}
                messages.append(m)
            logger.info(f"获取频道消息: {len(messages)} 条 (area={area[:8]}… channel={channel[:8]}…)")
            return messages
        except Exception as e:
            logger.error(f"获取频道消息异常: {e}")
            return []

    def find_message_timestamp(
        self,
        message_id: str,
        area: Optional[str] = None,
        channel: Optional[str] = None,
    ) -> Optional[str]:
        """
        从频道最近消息中查找指定 messageId 的 timestamp。
        找不到则返回 None。
        """
        messages = self.get_channel_messages(area=area, channel=channel)
        for msg in messages:
            if msg.get("messageId") == message_id:
                return msg.get("timestamp")
        return None

    # ---- 禁言 / 禁麦 ----
    #
    # 禁言时长 intervalId 映射:
    #   禁言(text): 1=60秒, 2=5分钟, 3=1小时, 4=1天, 5=3天, 6=7天
    #   禁麦(voice): 7=60秒, 8=5分钟, 9=1小时, 10=1天, 11=3天, 12=7天

    _TEXT_INTERVALS = {1: "60秒", 2: "5分钟", 3: "1小时", 4: "1天", 5: "3天", 6: "7天"}
    _VOICE_INTERVALS = {7: "60秒", 8: "5分钟", 9: "1小时", 10: "1天", 11: "3天", 12: "7天"}

    @staticmethod
    def _minutes_to_interval_id(minutes: int, voice: bool = False) -> str:
        """将分钟数映射到最接近的 intervalId。"""
        thresholds = [(1, 7), (5, 8), (60, 9), (1440, 10), (4320, 11), (10080, 12)] if voice \
            else [(1, 1), (5, 2), (60, 3), (1440, 4), (4320, 5), (10080, 6)]
        for limit, iid in thresholds:
            if minutes <= limit:
                return str(iid)
        return str(thresholds[-1][1])

    def mute_user(
        self,
        uid: str,
        area: Optional[str] = None,
        channel: Optional[str] = None,
        duration: int = 10,
    ) -> dict:
        """
        禁言用户（PATCH disableText）。

        Args:
            uid:      目标用户 UID
            area:     区域 ID
            duration: 禁言时长（分钟），自动映射到最近的 intervalId
        """
        area = area or OOPZ_CONFIG["default_area"]
        interval_id = self._minutes_to_interval_id(duration, voice=False)
        url_path = "/client/v1/area/v1/member/v1/disableText"
        query = f"?area={area}&target={uid}&intervalId={interval_id}"
        body = {"area": area, "target": uid, "intervalId": interval_id}
        return self._manage_patch("禁言", url_path, query, body)

    def unmute_user(
        self,
        uid: str,
        area: Optional[str] = None,
        channel: Optional[str] = None,
    ) -> dict:
        """解除禁言（PATCH recoverText）。"""
        area = area or OOPZ_CONFIG["default_area"]
        url_path = "/client/v1/area/v1/member/v1/recoverText"
        query = f"?area={area}&target={uid}"
        body = {"area": area, "target": uid}
        return self._manage_patch("解除禁言", url_path, query, body)

    def mute_mic(
        self,
        uid: str,
        area: Optional[str] = None,
        channel: Optional[str] = None,
        duration: int = 10,
    ) -> dict:
        """禁麦用户（PATCH disableVoice）。"""
        area = area or OOPZ_CONFIG["default_area"]
        interval_id = self._minutes_to_interval_id(duration, voice=True)
        url_path = "/client/v1/area/v1/member/v1/disableVoice"
        query = f"?area={area}&target={uid}&intervalId={interval_id}"
        body = {"area": area, "target": uid, "intervalId": interval_id}
        return self._manage_patch("禁麦", url_path, query, body)

    def unmute_mic(
        self,
        uid: str,
        area: Optional[str] = None,
        channel: Optional[str] = None,
    ) -> dict:
        """解除禁麦（PATCH recoverVoice）。"""
        area = area or OOPZ_CONFIG["default_area"]
        url_path = "/client/v1/area/v1/member/v1/recoverVoice"
        query = f"?area={area}&target={uid}"
        body = {"area": area, "target": uid}
        return self._manage_patch("解除禁麦", url_path, query, body)

    def remove_from_area(
        self,
        uid: str,
        area: Optional[str] = None,
    ) -> dict:
        """
        将用户移出当前域（踢出域）。

        API: POST /area/v3/remove?area={area}&target={uid}

        Args:
            uid:  目标用户 UID
            area: 域 ID（默认取配置）
        """
        area = area or OOPZ_CONFIG["default_area"]
        url_path = "/area/v3/remove"
        query = f"?area={area}&target={uid}"
        full_path = url_path + query
        body = {"area": area, "target": uid}

        try:
            self._throttle()
            body_str = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
            headers = {**self.session.headers, **self.signer.oopz_headers(full_path, body_str)}
            url = OOPZ_CONFIG["base_url"] + full_path
            resp = self.session.post(url, headers=headers, data=body_str.encode("utf-8"))
        except Exception as e:
            logger.error(f"移出域请求异常: {e}")
            return {"error": str(e)}

        raw = resp.text or ""
        logger.info(f"移出域 POST {full_path} -> HTTP {resp.status_code}, body: {raw[:300]}")

        if resp.status_code != 200:
            return {"error": f"HTTP {resp.status_code}" + (f" | {raw[:200]}" if raw else "")}

        try:
            result = resp.json()
        except Exception:
            return {"error": f"响应非 JSON: {raw[:200]}"}

        if result.get("status") is True:
            logger.info("移出域成功")
            return {"status": True, "message": "已移出域"}

        err = result.get("message") or result.get("error") or str(result)
        logger.error(f"移出域失败: {err}")
        return {"error": err}

    def get_area_blocks(self, area: Optional[str] = None, name: str = "") -> dict:
        """
        获取域内封禁列表。

        API: GET /client/v1/area/v1/areaSettings/v1/blocks?area={area}&name={name}

        Returns:
            {"blocks": [{"uid": "...", ...}, ...]} 或 {"error": "..."}
        """
        area = area or OOPZ_CONFIG["default_area"]
        url_path = "/client/v1/area/v1/areaSettings/v1/blocks"
        params = {"area": area, "name": name}

        try:
            resp = self._get(url_path, params=params)
            if resp.status_code != 200:
                logger.debug(f"获取域封禁列表失败: HTTP {resp.status_code}")
                return {"error": f"HTTP {resp.status_code}"}

            result = resp.json()
            if not result.get("status"):
                msg = result.get("message") or result.get("error") or "未知错误"
                logger.debug(f"获取域封禁列表失败: {msg}")
                return {"error": msg}

            data = result.get("data", {})
            blocks = data if isinstance(data, list) else data.get("blocks", data.get("list", []))
            if not isinstance(blocks, list):
                blocks = []
            logger.info(f"获取域封禁列表: {len(blocks)} 人")
            return {"blocks": blocks}
        except Exception as e:
            logger.error(f"获取域封禁列表异常: {e}")
            return {"error": str(e)}

    def unblock_user_in_area(
        self,
        uid: str,
        area: Optional[str] = None,
    ) -> dict:
        """
        解除域内封禁（从域封禁列表移除）。

        API: PATCH /client/v1/area/v1/unblock?area={area}&target={uid}
        """
        area = area or OOPZ_CONFIG["default_area"]
        url_path = "/client/v1/area/v1/unblock"
        query = f"?area={area}&target={uid}"
        body = {"area": area, "target": uid}
        return self._manage_patch("解除域内封禁", url_path, query, body)

    def _manage_patch(self, action: str, url_path: str, query: str, body: dict) -> dict:
        """通用 PATCH 管理操作（禁言/禁麦等），参数同时放 query string 和 body。"""
        full_path = url_path + query
        try:
            self._throttle()
            body_str = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
            headers = {**self.session.headers, **self.signer.oopz_headers(full_path, body_str)}
            url = OOPZ_CONFIG["base_url"] + full_path
            resp = self.session.patch(url, headers=headers, data=body_str.encode("utf-8"))
        except Exception as e:
            logger.error(f"{action}请求异常: {e}")
            return {"error": str(e)}

        raw = resp.text or ""
        logger.info(f"{action} PATCH {full_path} -> HTTP {resp.status_code}, body: {raw[:300]}")

        if resp.status_code != 200:
            err = f"HTTP {resp.status_code}" + (f" | {raw[:200]}" if raw else "")
            return {"error": err}

        try:
            result = resp.json()
        except Exception:
            return {"error": f"响应非 JSON: {raw[:200]}"}

        if result.get("status") is True:
            msg = result.get("message") or f"{action}成功"
            logger.info(f"{action}成功: {msg}")
            return {"status": True, "message": msg}

        err = result.get("message") or result.get("error") or str(result)
        logger.error(f"{action}失败: {err}")
        return {"error": err}

    # ---- 撤回消息 ----

    def recall_message(
        self,
        message_id: str,
        area: Optional[str] = None,
        channel: Optional[str] = None,
        timestamp: Optional[str] = None,
        target: str = "",
    ) -> dict:
        """
        撤回指定消息（需要管理员权限）。

        API: POST /im/session/v1/recallGim
        参数同时放在 query string 和 JSON body 中。

        Args:
            message_id: 消息 ID
            area:       区域 ID（默认取配置）
            channel:    频道 ID（默认取配置）
            timestamp:  消息原始时间戳（微秒），为空则用当前时间
            target:     目标用户 UID（撤回他人消息时填写，默认空）
        """
        area = area or OOPZ_CONFIG["default_area"]
        channel = channel or OOPZ_CONFIG["default_channel"]
        timestamp = timestamp or self.signer.timestamp_us()
        message_id = str(message_id).strip() if message_id is not None else ""

        url_path = "/im/session/v1/recallGim"
        query = (
            f"?area={area}&channel={channel}"
            f"&messageId={message_id}&timestamp={timestamp}&target={target}"
        )
        full_path = url_path + query

        body = {
            "area": area,
            "channel": channel,
            "messageId": message_id,
            "timestamp": timestamp,
            "target": target,
        }

        try:
            body_str = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
            headers = {**self.session.headers, **self.signer.oopz_headers(full_path, body_str)}
            url = OOPZ_CONFIG["base_url"] + full_path
            resp = self.session.post(url, headers=headers, data=body_str.encode("utf-8"))
        except Exception as e:
            logger.error(f"撤回请求异常: {e}")
            return {"error": str(e)}

        raw_text = resp.text or ""
        logger.info(f"撤回 POST {full_path} → HTTP {resp.status_code}, body: {raw_text[:300]}")

        if resp.status_code != 200:
            err = f"HTTP {resp.status_code}" + (f" | {raw_text[:200]}" if raw_text else "")
            logger.error(f"撤回消息失败: {err}")
            return {"error": err}

        try:
            result = resp.json()
        except Exception:
            logger.error(f"撤回响应非 JSON: {raw_text[:200]}")
            return {"error": f"响应非 JSON: {raw_text[:200]}"}

        if result.get("status") is True or result.get("code") in (0, "0", "success", 200):
            logger.info(f"撤回消息成功: {message_id}")
            return {"status": True, "message": "撤回成功"}

        err = result.get("message") or result.get("error") or str(result)
        logger.error(f"撤回消息失败: {err}")
        return {"error": err}
