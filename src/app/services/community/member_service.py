import datetime

from name_resolver import get_resolver
from app.services.runtime import CommandRuntimeView, sender_of


class MemberService:
    """处理成员列表、资料查询和成员搜索。"""

    def __init__(self, runtime: CommandRuntimeView):
        self._runtime = runtime
        self._sender = sender_of(runtime)

    def _selection_service(self):
        interaction = getattr(self._runtime.services, "interaction", None)
        return getattr(interaction, "selection", None)

    def show_members(self, channel: str, area: str) -> None:
        """查询域内成员并展示在线状态。"""
        resolver = get_resolver()

        members = []
        seen_uids: set[str] = set()
        page_size = 100
        max_fetch = 500
        for start in range(0, max_fetch, page_size):
            data = self._sender.get_area_members(
                area=area,
                offset_start=start,
                offset_end=start + page_size - 1,
                quiet=True,
            )
            if "error" in data:
                self._sender.send_message(f"查询成员列表失败: {data['error']}", channel=channel, area=area)
                return
            batch = data.get("members", []) or []
            for member in batch:
                uid = (member.get("uid") or "").strip()
                if not uid or uid in seen_uids:
                    continue
                seen_uids.add(uid)
                members.append(member)
            if len(batch) < page_size:
                break

        online = [member for member in members if member.get("online") == 1]
        offline = [member for member in members if member.get("online") != 1]

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
                name = resolver.user(member.get("uid", ""))
                state = member.get("playingState", "")
                suffix = f" ({state})" if state else ""
                lines.append(f"  {name}{suffix}")
            if len(online) > show_limit:
                lines.append(f"  ... 还有 {len(online) - show_limit} 人在线")

        if offline:
            lines.append(f"离线: {len(offline)} 人")

        if len(members) >= max_fetch:
            lines.append(f"提示: 仅展示前 {max_fetch} 名成员统计")

        self._sender.send_message("\n".join(lines), channel=channel, area=area)

    def show_profile(self, channel: str, area: str, user: str) -> None:
        """查询用户详细信息。"""
        data = self._sender.get_person_detail(uid=user)
        if "error" in data:
            self._sender.send_message(f"查询个人信息失败: {data['error']}", channel=channel, area=area)
            return

        name = data.get("name", "未知")
        lines = [
            f"个人信息 - {name}",
            "---",
            f"  UID: {user}",
        ]

        if "online" in data:
            lines.append(f"  状态: {'在线' if data['online'] else '离线'}")
        if data.get("introduction"):
            lines.append(f"  简介: {data['introduction']}")
        if data.get("ipAddress"):
            lines.append(f"  IP属地: {data['ipAddress']}")
        if data.get("personType"):
            lines.append(f"  类型: {data['personType']}")
        if data.get("playingState"):
            lines.append(f"  正在玩: {data['playingState']}")
        if data.get("avatar"):
            lines.append(f"  头像: {data['avatar']}")

        vip_end = data.get("personVIPEndTime", 0)
        if vip_end and vip_end > 0:
            vip_end_str = datetime.datetime.fromtimestamp(vip_end / 1000).strftime("%Y-%m-%d")
            lines.append(f"  VIP到期: {vip_end_str}")

        badges = data.get("badges", [])
        if badges:
            lines.append(f"  徽章: {len(badges)} 个")

        if len(lines) <= 3:
            lines.append("  （该接口返回信息有限）")

        self._sender.send_message("\n".join(lines), channel=channel, area=area)

    def show_myinfo(self, channel: str, area: str, user: str) -> None:
        """查询发起指令用户的完整详细资料。"""
        data = self._sender.get_person_detail_full(user)
        if "error" in data:
            self._sender.send_message(f"查询资料失败: {data['error']}", channel=channel, area=area)
            return

        person = data.get("person", data)
        name = person.get("name", "未知")
        lines = [f"我的详细资料 - {name}", "---"]

        for label, key in [
            ("UID", "uid"),
            ("简介", "introduction"),
            ("IP属地", "ipAddress"),
            ("类型", "personType"),
            ("性别", "sex"),
        ]:
            value = person.get(key)
            if value:
                lines.append(f"  {label}: {value}")

        if person.get("online") is not None:
            lines.append(f"  状态: {'在线' if person['online'] else '离线'}")

        vip_end = person.get("personVIPEndTime", 0)
        if vip_end and vip_end > 0:
            lines.append(
                f"  VIP到期: {datetime.datetime.fromtimestamp(vip_end / 1000).strftime('%Y-%m-%d')}"
            )

        badges = person.get("badges", [])
        if badges:
            badge_names = [badge.get("name", "") for badge in badges if badge.get("name")]
            lines.append(f"  徽章({len(badges)}): {', '.join(badge_names[:10])}")

        self._sender.send_message("\n".join(lines), channel=channel, area=area)

    def _show_whois_by_uid(self, uid: str, channel: str, area: str) -> None:
        """按 UID 展示用户详细资料。"""
        data = self._sender.get_person_detail_full(uid)
        if "error" in data:
            self._sender.send_message(f"查询资料失败: {data['error']}", channel=channel, area=area)
            return

        person = data.get("person", data)
        name = person.get("name", uid[:8])
        lines = [f"用户资料 - {name}", "---"]

        for label, key in [
            ("UID", "uid"),
            ("简介", "introduction"),
            ("IP属地", "ipAddress"),
            ("类型", "personType"),
            ("性别", "sex"),
        ]:
            value = person.get(key)
            if value:
                lines.append(f"  {label}: {value}")

        if person.get("online") is not None:
            lines.append(f"  状态: {'在线' if person['online'] else '离线'}")
        if person.get("playingState"):
            lines.append(f"  正在玩: {person['playingState']}")

        vip_end = person.get("personVIPEndTime", 0)
        if vip_end and vip_end > 0:
            lines.append(
                f"  VIP到期: {datetime.datetime.fromtimestamp(vip_end / 1000).strftime('%Y-%m-%d')}"
            )

        badges = person.get("badges", [])
        if badges:
            badge_names = [badge.get("name", "") for badge in badges if badge.get("name")]
            lines.append(f"  徽章({len(badges)}): {', '.join(badge_names[:10])}")

        if person.get("avatar"):
            lines.append(f"  头像: {person['avatar']}")

        self._sender.send_message("\n".join(lines), channel=channel, area=area)

    def show_whois(self, target: str, channel: str, area: str, user: str = "") -> None:
        """查看他人完整详细资料。"""
        target_resolution = self._runtime.services.community.target_resolution
        uid = target_resolution.resolve_target(target, area=area)
        if not uid:
            candidates_raw = target_resolution.resolve_target_candidates(target, area=area, limit=5)
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
                self._sender.send_message("\n".join(lines), channel=channel, area=area)
                return
            self._sender.send_message(f"找不到用户: {target}", channel=channel, area=area)
            return

        self._show_whois_by_uid(uid, channel, area)

    def search_members(self, keyword: str, channel: str, area: str, user: str = "") -> None:
        """搜索域内成员。"""
        resolver = get_resolver()
        members = self._sender.search_area_members(area=area, keyword=keyword)
        if not members:
            self._sender.send_message(f'未找到匹配 "{keyword}" 的成员', channel=channel, area=area)
            return

        lines = [f'搜索 "{keyword}" - 找到 {len(members)} 人', "---"]
        selection_items = []
        for member in members[:20]:
            uid = member.get("uid", "")
            name = resolver.user(uid)
            if uid:
                selection_items.append({"uid": uid, "name": name})
            roles_info = member.get("roleInfos", [])
            role_names = [role.get("name", "") for role in roles_info if role.get("name")]
            role_str = f" [{', '.join(role_names)}]" if role_names else ""
            enter_time = member.get("enterTime", 0)
            time_str = ""
            if enter_time:
                time_str = f" 加入于 {datetime.datetime.fromtimestamp(enter_time / 1000).strftime('%Y-%m-%d')}"
            lines.append(f"  {name}{role_str}{time_str}")

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

        self._sender.send_message("\n".join(lines), channel=channel, area=area)

    def handle_pick(self, index: int, channel: str, area: str, user: str) -> bool:
        """处理成员候选编号选择。"""
        selection_service = self._selection_service()
        if not selection_service:
            return False
        selection, item = selection_service.pick(user, channel, area, index)
        if not selection or selection.kind != "member":
            return False
        if not item:
            self._sender.send_message(f"编号超出范围，请输入 1-{len(selection.items)}", channel=channel, area=area)
            return True

        uid = item.get("uid", "")
        if not uid:
            self._sender.send_message("候选结果无效，请重新搜索", channel=channel, area=area)
            return True

        selection_service.clear(user, channel, area)
        self._show_whois_by_uid(uid, channel, area)
        return True
