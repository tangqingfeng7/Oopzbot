import datetime

from app.services.runtime import CommandRuntimeView, sender_of
from oopz.name_resolver import get_resolver


class MemberService:
    """处理成员列表、资料查询和成员搜索。"""

    def __init__(self, runtime: CommandRuntimeView):
        self._runtime = runtime
        self._sender = sender_of(runtime)

    def _selection_service(self):
        interaction = getattr(self._runtime.services, "interaction", None)
        return getattr(interaction, "selection", None)

    async def show_members(self, channel: str, area: str) -> None:
        """查询域内成员并展示在线状态。"""
        resolver = get_resolver()

        try:
            people = await self._sender.bot.areas.get_all_area_members(area, page_size=100, max_pages=5)
        except Exception as exc:
            await self._sender.send_message(f"查询成员列表失败: {exc}", channel=channel, area=area)
            return
        members = list({person.uid: person for person in people if person.uid}.values())

        await resolver.ensure_users([member.uid for member in members])
        online = [member for member in members if member.online == 1]
        offline = [member for member in members if member.online != 1]

        area_name = resolver.area(area)
        lines = [
            f"{area_name} - 成员列表",
            f"总计 {len(members)} 人 | 在线 {len(online)} 人",
            "---",
        ]

        if online:
            lines.append("在线:")
            show_limit = 50
            for member in online[:show_limit]:
                name = resolver.user(member.uid)
                state = member.playing_state
                suffix = f" ({state})" if state else ""
                lines.append(f"  {name}{suffix}")
            if len(online) > show_limit:
                lines.append(f"  ... 还有 {len(online) - show_limit} 人在线")

        if offline:
            lines.append(f"离线: {len(offline)} 人")

        if len(people) >= 500:
            lines.append("提示: 仅展示前 500 名成员统计")

        await self._sender.send_message("\n".join(lines), channel=channel, area=area)

    async def show_profile(self, channel: str, area: str, user: str) -> None:
        """查询用户详细信息。"""
        try:
            data = await self._sender.bot.person.get_person_info(user)
        except Exception as exc:
            await self._sender.send_message(f"查询个人信息失败: {exc}", channel=channel, area=area)
            return

        lines = [
            f"个人信息 - {data.name or '未知'}",
            "---",
            f"  UID: {user}",
            f"  状态: {'在线' if data.online else '离线'}",
        ]
        for label, value in [
            ("简介", data.introduction),
            ("类型", data.person_type),
            ("头像", data.avatar),
        ]:
            if value:
                lines.append(f"  {label}: {value}")
        if data.badges:
            lines.append(f"  徽章: {len(data.badges)} 个")

        await self._sender.send_message("\n".join(lines), channel=channel, area=area)

    async def show_myinfo(self, channel: str, area: str, user: str) -> None:
        """查询发起指令用户的完整详细资料。"""
        try:
            person = await self._sender.bot.person.get_person_detail_full(user)
        except Exception as exc:
            await self._sender.send_message(f"查询资料失败: {exc}", channel=channel, area=area)
            return

        name = person.name or "未知"
        lines = [f"我的详细资料 - {name}", "---"]

        for label, value in [
            ("UID", person.uid),
            ("简介", person.introduction),
            ("IP属地", person.ip_address),
            ("类型", person.person_type),
        ]:
            if value:
                lines.append(f"  {label}: {value}")

        lines.append(f"  状态: {'在线' if person.online else '离线'}")

        vip_end = person.person_vip_end_time
        if vip_end and vip_end > 0:
            lines.append(
                f"  VIP到期: {datetime.datetime.fromtimestamp(vip_end / 1000).strftime('%Y-%m-%d')}"
            )

        badges = person.badges
        if badges:
            badge_names = [badge.get("name", "") for badge in badges if badge.get("name")]
            lines.append(f"  徽章({len(badges)}): {', '.join(badge_names[:10])}")

        await self._sender.send_message("\n".join(lines), channel=channel, area=area)

    async def _show_whois_by_uid(self, uid: str, channel: str, area: str) -> None:
        """按 UID 展示用户详细资料。"""
        try:
            person = await self._sender.bot.person.get_person_detail_full(uid)
        except Exception as exc:
            await self._sender.send_message(f"查询资料失败: {exc}", channel=channel, area=area)
            return

        name = person.name or uid[:8]
        lines = [f"用户资料 - {name}", "---"]

        for label, value in [
            ("UID", person.uid),
            ("简介", person.introduction),
            ("IP属地", person.ip_address),
            ("类型", person.person_type),
        ]:
            if value:
                lines.append(f"  {label}: {value}")

        lines.append(f"  状态: {'在线' if person.online else '离线'}")
        if person.playing_state:
            lines.append(f"  正在玩: {person.playing_state}")

        vip_end = person.person_vip_end_time
        if vip_end and vip_end > 0:
            lines.append(
                f"  VIP到期: {datetime.datetime.fromtimestamp(vip_end / 1000).strftime('%Y-%m-%d')}"
            )

        badges = person.badges
        if badges:
            badge_names = [badge.get("name", "") for badge in badges if badge.get("name")]
            lines.append(f"  徽章({len(badges)}): {', '.join(badge_names[:10])}")

        if person.avatar:
            lines.append(f"  头像: {person.avatar}")

        await self._sender.send_message("\n".join(lines), channel=channel, area=area)

    async def show_whois(self, target: str, channel: str, area: str, user: str = "") -> None:
        """查看他人完整详细资料。"""
        target_resolution = self._runtime.services.community.target_resolution
        try:
            uid = await target_resolution.resolve_target(target, area=area)
            candidates_raw = await target_resolution.resolve_target_candidates(target, area=area, limit=5) if not uid else []
        except Exception as exc:
            await self._sender.send_message(f"查询成员失败: {exc}", channel=channel, area=area)
            return
        if not uid:
            candidates = candidates_raw if isinstance(candidates_raw, list) else []
            if candidates:
                selection = self._selection_service()
                if selection:
                    selection.store(
                        user=user,
                        channel=channel,
                        area=area,
                        kind="member",
                        query=target,
                        items=candidates,
                    )
                    lines = [f'找到多个匹配 "{target}" 的成员，请发送 `选择 <编号>` 继续:']
                else:
                    lines = [f'找到多个匹配 "{target}" 的成员:']
                for index, candidate in enumerate(candidates, 1):
                    lines.append(f"  {index}. {candidate['name']} ({candidate['uid'][:8]})")
                await self._sender.send_message("\n".join(lines), channel=channel, area=area)
                return
            await self._sender.send_message(f"找不到用户: {target}", channel=channel, area=area)
            return

        await self._show_whois_by_uid(uid, channel, area)

    async def search_members(self, keyword: str, channel: str, area: str, user: str = "") -> None:
        """搜索域内成员。"""
        resolver = get_resolver()
        try:
            members = await self._sender.search_area_members(area=area, keyword=keyword)
        except Exception as exc:
            await self._sender.send_message(f"搜索成员失败: {exc}", channel=channel, area=area)
            return
        if not members:
            await self._sender.send_message(f'未找到匹配 "{keyword}" 的成员', channel=channel, area=area)
            return

        await resolver.ensure_users([member.uid for member in members])
        lines = [f'搜索 "{keyword}" - 找到 {len(members)} 人', "---"]
        selection_items = []
        for member in members[:20]:
            uid = member.uid
            name = resolver.user(uid)
            if uid:
                selection_items.append({"uid": uid, "name": name})
            lines.append(f"  {name}")

        if len(members) > 20:
            lines.append(f"  ... 还有 {len(members) - 20} 人")

        if selection_items:
            selection = self._selection_service()
            if selection:
                selection.store(
                    user=user,
                    channel=channel,
                    area=area,
                    kind="member",
                    query=keyword,
                    items=selection_items,
                )
                lines.append("")
                lines.append("发送 `@bot 选择 <编号>` 或 `/pick <编号>` 查看对应成员资料")

        await self._sender.send_message("\n".join(lines), channel=channel, area=area)

    async def handle_pick(self, index: int, channel: str, area: str, user: str) -> bool:
        """处理成员候选编号选择。"""
        selection_service = self._selection_service()
        if not selection_service:
            return False
        selection, item = selection_service.pick(user, channel, area, index)
        if not selection or selection.kind != "member":
            return False
        if not item:
            await self._sender.send_message(f"编号超出范围，请输入 1-{len(selection.items)}", channel=channel, area=area)
            return True

        uid = item.get("uid", "")
        if not uid:
            await self._sender.send_message("候选结果无效，请重新搜索", channel=channel, area=area)
            return True

        selection_service.clear(user, channel, area)
        await self._show_whois_by_uid(uid, channel, area)
        return True
