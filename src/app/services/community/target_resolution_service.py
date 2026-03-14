import re
from typing import Optional

from name_resolver import get_resolver


class TargetResolutionService:
    """负责解析用户目标和禁言参数。"""

    def __init__(self, runtime):
        self._runtime = runtime

    def _sender(self):
        """兼容不同运行时对象，取到底层 sender。"""
        sender = getattr(self._runtime, "sender", None)
        if sender is not None:
            return sender
        infrastructure = getattr(self._runtime, "infrastructure", None)
        return getattr(infrastructure, "sender", None)

    def _collect_area_member_uids(self, area: Optional[str]) -> list[str]:
        """拉取当前域成员 UID 列表，供本地匹配用户名称。"""
        if not area:
            return []

        sender = self._sender()
        if sender is None or not hasattr(sender, "get_area_members"):
            return []

        page_size = 100
        max_fetch = 1000
        seen: set[str] = set()
        ordered_uids: list[str] = []

        for start in range(0, max_fetch, page_size):
            data = sender.get_area_members(
                area=area,
                offset_start=start,
                offset_end=start + page_size - 1,
                quiet=True,
            )
            if not isinstance(data, dict) or "error" in data:
                return []

            members = data.get("members", []) or []
            for member in members:
                uid = (member.get("uid") or member.get("id") or "").strip()
                if not uid or uid in seen:
                    continue
                seen.add(uid)
                ordered_uids.append(uid)

            total_count = int(data.get("totalCount") or 0)
            if len(members) < page_size:
                break
            if total_count and len(ordered_uids) >= total_count:
                break

        return ordered_uids

    def _resolve_from_area_members(self, name: str, area: Optional[str]) -> Optional[str]:
        """在当前域内做一次安全的模糊匹配，只接受唯一命中。"""
        if not area:
            return None

        uids = self._collect_area_member_uids(area)
        if not uids:
            return None

        resolver = get_resolver()
        names = resolver.ensure_users(uids) if hasattr(resolver, "ensure_users") else {}
        candidates: list[tuple[str, str]] = []
        keyword = name.lower()

        for uid in uids:
            display_name = (names.get(uid) or resolver.user_cached(uid)).strip()
            candidates.append((uid, display_name))

        if not candidates:
            return None

        exact_matches = [uid for uid, display_name in candidates if display_name and display_name.lower() == keyword]
        if len(exact_matches) == 1:
            return exact_matches[0]

        prefix_matches = [uid for uid, display_name in candidates if display_name and display_name.lower().startswith(keyword)]
        if len(prefix_matches) == 1:
            return prefix_matches[0]

        contains_matches = [uid for uid, display_name in candidates if display_name and keyword in display_name.lower()]
        if len(contains_matches) == 1:
            return contains_matches[0]

        return None

    def resolve_target(self, text: str, area: Optional[str] = None) -> Optional[str]:
        """从 @mention、UID 或用户名中解析目标用户 UID。"""
        text = text.strip()
        if not text:
            return None

        match = re.search(r"\(met\)(\w+)\(met\)", text)
        if match:
            return match.group(1)

        token = text.split()[0]
        if re.fullmatch(r"[a-f0-9]{32}", token):
            return token

        uid = get_resolver().find_uid_by_name(token)
        if uid:
            return uid

        return self._resolve_from_area_members(token, area)

    def parse_mute_args(self, text: str, area: Optional[str] = None) -> tuple[Optional[str], int]:
        """解析禁言/禁麦参数，返回 `(uid, duration)`。"""
        text = text.strip()
        match = re.match(r"\(met\)(\w+)\(met\)\s*(\d+)?", text)
        if match:
            # mention 形式如果没写时长，默认按 10 分钟处理。
            duration = int(match.group(2)) if match.group(2) else 10
            return match.group(1), duration

        parts = text.rsplit(None, 1)
        if len(parts) == 2 and parts[1].isdigit():
            name_part, duration = parts[0], int(parts[1])
        else:
            name_part, duration = text, 10

        uid = self.resolve_target(name_part, area=area)
        return uid, duration
