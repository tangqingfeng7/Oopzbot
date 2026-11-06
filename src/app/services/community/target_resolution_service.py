import re

from core.constants import MENTION_PATTERN, UID_PATTERN
from oopz.name_resolver import get_resolver


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

    async def _collect_area_member_uids(self, area: str | None) -> list[str]:
        """拉取当前域成员 UID 列表，供本地匹配用户名称。"""
        if not area:
            return []

        sender = self._sender()
        if sender is None:
            raise RuntimeError("成员查询服务未初始化")
        members = await sender.bot.areas.get_all_area_members(area, page_size=100, max_pages=10)
        return list(dict.fromkeys(member.uid.strip() for member in members if member.uid.strip()))

    async def _resolve_from_area_members(self, name: str, area: str | None) -> str | None:
        """在当前域内做一次安全的模糊匹配，只接受唯一命中。"""
        candidates = await self.resolve_target_candidates(name, area=area, limit=10)
        if len(candidates) == 1:
            return candidates[0]["uid"]
        return None

    async def resolve_target_candidates(self, name: str, area: str | None = None, limit: int = 5) -> list[dict]:
        """在当前域内返回候选用户列表，用于交互式选择。"""
        if not area:
            return []

        uids = await self._collect_area_member_uids(area)
        if not uids:
            return []

        resolver = get_resolver()
        names = await resolver.ensure_users(uids) if hasattr(resolver, "ensure_users") else {}
        candidates: list[tuple[str, str]] = []
        keyword = name.lower()

        for uid in uids:
            display_name = (names.get(uid) or resolver.user_cached(uid)).strip()
            candidates.append((uid, display_name))

        if not candidates:
            return []

        exact_matches = [
            {"uid": uid, "name": display_name}
            for uid, display_name in candidates
            if display_name and display_name.lower() == keyword
        ]
        if exact_matches:
            return exact_matches[:limit]

        prefix_matches = [
            {"uid": uid, "name": display_name}
            for uid, display_name in candidates
            if display_name and display_name.lower().startswith(keyword)
        ]
        if prefix_matches:
            return prefix_matches[:limit]

        contains_matches = [
            {"uid": uid, "name": display_name}
            for uid, display_name in candidates
            if display_name and keyword in display_name.lower()
        ]
        return contains_matches[:limit]

    async def resolve_target(self, text: str, area: str | None = None) -> str | None:
        """从 @mention、UID 或用户名中解析目标用户 UID。"""
        text = text.strip()
        if not text:
            return None

        match = re.search(MENTION_PATTERN, text)
        if match:
            return match.group(1)

        token = text.split()[0]
        if re.fullmatch(UID_PATTERN, token):
            return token

        uid = get_resolver().find_uid_by_name(token)
        if uid:
            return uid

        return await self._resolve_from_area_members(token, area)

    async def parse_mute_args(self, text: str, area: str | None = None) -> tuple[str | None, int]:
        """解析禁言/禁麦参数，返回 `(uid, duration)`。"""
        text = text.strip()
        match = re.match(MENTION_PATTERN + r"\s*(\d+)?", text)
        if match:
            # mention 形式如果没写时长，默认按 10 分钟处理。
            duration = int(match.group(2)) if match.group(2) else 10
            return match.group(1), duration

        parts = text.rsplit(None, 1)
        if len(parts) == 2 and parts[1].isdigit():
            name_part, duration = parts[0], int(parts[1])
        else:
            name_part, duration = text, 10

        uid = await self.resolve_target(name_part, area=area)
        return uid, duration
