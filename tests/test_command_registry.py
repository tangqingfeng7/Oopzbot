
import sys
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


# --- 迁移前的原始硬编码值（golden snapshot） ---

_LEGACY_ADMIN_ONLY_COMMANDS = frozenset(
    {
        "/plugins",
        "/loadplugin",
        "/unloadplugin",
        "/reloadplugin",
        "/禁言",
        "/mute",
        "/解禁",
        "/unmute",
        "/禁麦",
        "/mutemic",
        "/解麦",
        "/unmutemic",
        "/ban",
        "/unblock",
        "/blocklist",
        "/autorecall",
        "/recall",
        "/clear",
        "/schedule",
        "/addrole",
        "/removerole",
    }
)

_LEGACY_ADMIN_ONLY_MENTION_PREFIXES = (
    "加载插件", "启用插件", "loadplugin",
    "卸载插件", "禁用插件", "unloadplugin",
    "重载插件", "刷新插件", "reloadplugin",
    "插件列表", "扩展列表", "插件",
    "禁言", "解除禁言", "解禁",
    "禁麦", "解除禁麦", "解麦",
    "移出域", "踢出", "移出",
    "解除域内封禁", "解封",
    "封禁列表", "封禁名单", "黑名单",
    "自动撤回", "撤回",
    "清理历史", "清理记录", "清除历史", "清空历史", "清理数据",
    "定时消息列表", "定时消息",
    "添加定时消息", "新增定时消息", "删除定时消息", "移除定时消息",
    "开启定时消息", "启用定时消息", "关闭定时消息", "停用定时消息",
    "给身份组", "添加身份组", "addrole",
    "取消身份组", "移除身份组", "removerole",
)


class CommandRegistryDerivationTest(unittest.TestCase):
    def test_admin_slash_commands_match_legacy(self) -> None:
        from domain.routing.public_command_rules import ADMIN_ONLY_COMMANDS

        self.assertEqual(set(ADMIN_ONLY_COMMANDS), set(_LEGACY_ADMIN_ONLY_COMMANDS))

    def test_admin_mention_prefixes_match_legacy(self) -> None:
        from domain.routing.public_command_rules import ADMIN_ONLY_MENTION_PREFIXES

        # 消费方使用 any(startswith(...))，顺序无关，故比较集合。
        self.assertEqual(
            set(ADMIN_ONLY_MENTION_PREFIXES), set(_LEGACY_ADMIN_ONLY_MENTION_PREFIXES)
        )

    def test_no_mention_prefix_lost_to_dedup(self) -> None:
        # 注册表内 mention 别名应无重复（否则会掩盖映射错误）。
        from domain.routing.command_registry import COMMANDS

        seen: dict[str, str] = {}
        for spec in COMMANDS:
            for alias in spec.mention:
                self.assertNotIn(
                    alias, seen, f"mention 别名 {alias!r} 同时属于 {seen.get(alias)} 与 {spec.id}"
                )
                seen[alias] = spec.id

    def test_no_slash_alias_duplicated(self) -> None:
        from domain.routing.command_registry import COMMANDS

        seen: dict[str, str] = {}
        for spec in COMMANDS:
            for alias in spec.slash:
                self.assertNotIn(
                    alias, seen, f"slash 别名 {alias!r} 同时属于 {seen.get(alias)} 与 {spec.id}"
                )
                seen[alias] = spec.id


class SlashRouterAliasGoldenTest(unittest.TestCase):
    """锁定 slash 路由各规则组的别名集合（迁移前 golden），确保 派生零变更。"""

    def _router(self):
        from unittest.mock import Mock

        from app.services.routing.slash_command_router import SlashCommandRouter

        return SlashCommandRouter(Mock())

    @staticmethod
    def _aliases(rules) -> set[str]:
        collected: set[str] = set()
        for rule in rules:
            collected.update(rule[0])
        return collected

    def test_admin_rules_aliases(self) -> None:
        router = self._router()
        self.assertEqual(
            self._aliases(router._admin_rules("c", "a")),
            {"/plugins", "/loadplugin", "/unloadplugin", "/reloadplugin"},
        )

    def test_exact_rules_aliases(self) -> None:
        router = self._router()
        self.assertEqual(
            self._aliases(router._exact_rules("c", "a", "u", "")),
            {
                "/members", "/online", "/me", "/myinfo", "/voice",
                "/daily", "/quote", "/health", "/doctor", "/setup", "/wizard",
                "/禁言", "/mute", "/解禁", "/unmute", "/禁麦", "/mutemic",
                "/解麦", "/unmutemic", "/ban", "/unblock", "/blocklist",
                "/autorecall", "/recall", "/ranking", "/活跃", "/活跃排行",
                "/chatstats", "/频道统计", "/topsongs", "/点歌排行", "/播放排行",
                "/recentsongs", "/最近播放",
            },
        )

    def test_arg_rules_aliases(self) -> None:
        router = self._router()
        self.assertEqual(
            self._aliases(router._arg_rules("c", "a", "u")),
            {"/whois", "/role", "/roles", "/search", "/help", "/enter", "/songsearch", "/pick"},
        )

    def test_pair_rules_aliases(self) -> None:
        router = self._router()
        self.assertEqual(
            self._aliases(router._pair_rules("c", "a")),
            {"/addrole", "/removerole"},
        )

    def test_inline_command_aliases(self) -> None:
        from domain.routing.command_registry import slash_of

        self.assertEqual(set(slash_of("clear_history")), {"/clear"})
        self.assertEqual(set(slash_of("remind")), {"/remind", "/提醒"})
        self.assertEqual(set(slash_of("schedule")), {"/schedule"})


class MentionRouterAliasGoldenTest(unittest.TestCase):
    """锁定 mention 路由各规则组的别名集合（迁移前 golden），确保 派生零变更。"""

    def _router(self):
        from unittest.mock import Mock

        from app.services.routing.mention_command_router import MentionCommandRouter

        return MentionCommandRouter(Mock())

    @staticmethod
    def _aliases(rules) -> set[str]:
        collected: set[str] = set()
        for rule in rules:
            collected.update(rule[0])
        return collected

    def test_exact_rules_aliases(self) -> None:
        router = self._router()
        self.assertEqual(
            self._aliases(router._exact_rules("c", "a", "u")),
            {
                "成员", "在线", "成员列表", "谁在线",
                "个人信息", "我是谁", "信息",
                "我的资料", "我的详细资料", "我的信息",
                "语音", "语音频道", "语音在线", "谁在语音",
                "每日一句", "一句", "名言", "语录", "鸡汤",
                "体检", "系统体检", "健康检查",
                "首启向导", "向导",
                "清理历史", "清理记录", "清除历史", "清空历史", "清理数据",
                "封禁列表", "封禁名单", "黑名单",
                "插件列表", "扩展列表", "插件",
                "帮助", "help", "指令", "命令",
                "活跃排行", "活跃榜", "排行榜",
                "频道统计", "消息统计",
                "点歌排行", "播放排行", "热歌榜",
                "最近播放", "播放历史",
                "定时消息列表", "定时消息",
                "我的提醒", "提醒列表",
                "屏幕共享", "共享屏幕",
                "停止屏幕共享", "结束屏幕共享",
            },
        )

    def test_arg_rules_aliases(self) -> None:
        router = self._router()
        self.assertEqual(
            self._aliases(router._arg_rules("c", "a", "u")),
            {
                "查看", "资料", "查询资料",
                "角色",
                "可分配角色", "分配角色",
                "搜索成员", "搜索", "找人",
                "帮助", "help",
                "进入频道", "进入",
                "加载插件", "启用插件", "loadplugin",
                "卸载插件", "禁用插件", "unloadplugin",
                "重载插件", "刷新插件", "reloadplugin",
            },
        )

    def test_pair_rules_aliases(self) -> None:
        router = self._router()
        self.assertEqual(
            self._aliases(router._pair_rules("c", "a")),
            {"给身份组", "添加身份组", "addrole", "取消身份组", "移除身份组", "removerole"},
        )

    def test_raw_rules_aliases(self) -> None:
        router = self._router()
        self.assertEqual(
            self._aliases(router._raw_rules("c", "a", "u")),
            {
                "禁言", "解除禁言", "解禁", "禁麦", "解除禁麦", "解麦",
                "移出域", "踢出", "移出", "解除域内封禁", "解封",
                "自动撤回", "撤回", "提醒", "删除提醒", "取消提醒",
                "添加定时消息", "新增定时消息", "删除定时消息", "移除定时消息",
                "开启定时消息", "启用定时消息", "关闭定时消息", "停用定时消息",
                "选择", "选歌", "搜歌", "搜索歌曲",
            },
        )

    def test_schedule_literal_groups_stay_in_sync_with_registry(self) -> None:
        # 定时消息别名仍保留字面量；用此测试防止其与注册表静默背离。
        from domain.routing.command_registry import mention_of

        literal_schedule = {
            "定时消息列表", "定时消息",
            "添加定时消息", "新增定时消息",
            "删除定时消息", "移除定时消息",
            "开启定时消息", "启用定时消息",
            "关闭定时消息", "停用定时消息",
        }
        self.assertEqual(literal_schedule, set(mention_of("schedule")))

    def test_help_arg_subset_within_registry(self) -> None:
        from domain.routing.command_registry import mention_of

        self.assertTrue({"帮助", "help"}.issubset(set(mention_of("help"))))


class HelpCatalogDerivationTest(unittest.TestCase):
    """锁定 help_catalog 的主题级管理员分类派生，确保零行为变更且不与注册表背离。"""

    # 主题级 admin 判定改为 fail-closed（主题内任一命令 admin=True 即受限）后的期望值。
    # 早先是 AND 归约 + /role /roles 挂在 admin 主题下，导致 admin 主题被降级成公开，
    # 非管理员发「帮助 管理」能看到全量管理命令清单。
    _EXPECTED_ADMIN_ONLY_TOPICS = frozenset({"plugin", "schedule", "admin"})

    def test_admin_only_topics_are_fail_closed(self) -> None:
        from app.services.interaction.help_catalog import ADMIN_ONLY_TOPICS

        self.assertEqual(set(ADMIN_ONLY_TOPICS), set(self._EXPECTED_ADMIN_ONLY_TOPICS))

    def test_admin_topic_is_restricted(self) -> None:
        # 回归守卫：管理主题必须受限，且不能再被任何公开命令降级
        from app.services.interaction.help_catalog import ADMIN_ONLY_TOPICS

        self.assertIn("admin", ADMIN_ONLY_TOPICS)

    def test_every_registry_topic_has_catalog_entry(self) -> None:
        # 注册表引用的每个 help_topic 都必须在 HELP_TOPICS 中存在，杜绝悬挂引用。
        from app.services.interaction.help_catalog import HELP_TOPICS
        from domain.routing.command_registry import COMMANDS

        referenced = {spec.help_topic for spec in COMMANDS if spec.help_topic is not None}
        dangling = referenced - set(HELP_TOPICS)
        self.assertEqual(dangling, set(), f"注册表引用了不存在的帮助主题: {sorted(dangling)}")

    def test_admin_only_topics_consistent_with_independent_rule(self) -> None:
        # 独立重算「主题内任一命令为 admin 即算管理员主题」，防止派生逻辑回退成 fail-open。
        from app.services.interaction.help_catalog import ADMIN_ONLY_TOPICS
        from domain.routing.command_registry import COMMANDS

        expected = {spec.help_topic for spec in COMMANDS if spec.admin and spec.help_topic}
        self.assertEqual(set(ADMIN_ONLY_TOPICS), expected)

    def test_non_admin_overview_hides_restricted_topics(self) -> None:
        # 过滤必须基于 ADMIN_ONLY_TOPICS 而非行文本字面量
        from app.services.interaction.help_catalog import (
            ADMIN_ONLY_TOPICS,
            HELP_TOPICS,
            overview_lines,
        )

        public = "\n".join(overview_lines(is_admin=False))
        admin = "\n".join(overview_lines(is_admin=True))
        for key in ADMIN_ONLY_TOPICS:
            label = HELP_TOPICS[key].menu_label
            self.assertNotIn(f"帮助 {label}", public, f"非管理员总览泄漏了受限主题 {key}")
            self.assertIn(f"帮助 {label}", admin)

    def test_public_query_help_contains_role_queries_only(self) -> None:
        from app.services.interaction.help_catalog import HELP_TOPICS

        query = "\n".join(HELP_TOPICS["query"].lines)
        admin = "\n".join(HELP_TOPICS["admin"].lines)
        self.assertIn("/role <用户>", query)
        self.assertIn("/roles <用户>", query)
        self.assertIn("@bot 角色 <用户>", query)
        self.assertNotIn("/role <用户>", admin)
        self.assertNotIn("可分配角色 <用户>", admin)
        self.assertIn("/addrole", admin)
        self.assertIn("/removerole", admin)


class OverviewMenuDerivationTest(unittest.TestCase):
    """锁定 overview 总览菜单的派生，确保派生输出与迁移前逐字一致且不与主题表背离。"""

    # 迁移前 overview.lines 的原始硬编码值（golden snapshot）。
    _LEGACY_OVERVIEW_LINES = (
        "帮助主题:",
        "  帮助 音乐  点歌、队列、喜欢列表",
        "  帮助 查询  成员、资料、语音、身份组",
        "  帮助 提醒  提醒、排行、统计",
        "  帮助 共享  网页屏幕共享",
        "  帮助 管理  禁言、撤回、清理、身份组变更",
        "  帮助 定时  定时消息与提醒管理",
        "  帮助 插件  插件命令与管理",
        "  帮助 系统  系统体检与首启向导",
    )

    def test_overview_lines_match_legacy(self) -> None:
        from app.services.interaction.help_catalog import HELP_TOPICS

        self.assertEqual(HELP_TOPICS["overview"].lines, self._LEGACY_OVERVIEW_LINES)

    def test_menu_order_covers_all_non_overview_topics(self) -> None:
        # 菜单顺序正好覆盖除 overview 外的全部主题，新增/删除主题会强制更新菜单。
        from app.services.interaction.help_catalog import HELP_TOPICS, MENU_ORDER

        non_overview = set(HELP_TOPICS) - {"overview"}
        self.assertEqual(set(MENU_ORDER), non_overview)
        self.assertEqual(len(MENU_ORDER), len(non_overview), "MENU_ORDER 含重复主题")

    def test_menu_topics_carry_label_and_blurb(self) -> None:
        from app.services.interaction.help_catalog import HELP_TOPICS, MENU_ORDER

        for key in MENU_ORDER:
            topic = HELP_TOPICS[key]
            self.assertTrue(topic.menu_label, f"主题 {key} 缺少 menu_label")
            self.assertTrue(topic.menu_blurb, f"主题 {key} 缺少 menu_blurb")


class CommandSuggestionsConsistencyTest(unittest.TestCase):
    """守卫 COMMAND_SUGGESTIONS 的触发词不与命令体系背离（2d）。"""

    # 非注册表来源的合法触发词（音乐命令由音乐服务独立分发，不在注册表内）。
    _NON_REGISTRY_TRIGGERS = frozenset({"播放", "/bf"})

    def test_every_suggestion_trigger_is_known(self) -> None:
        from app.services.interaction.help_catalog import COMMAND_SUGGESTIONS
        from domain.routing.command_registry import COMMANDS

        registry_aliases = {
            alias for spec in COMMANDS for alias in (*spec.slash, *spec.mention)
        }
        known = registry_aliases | self._NON_REGISTRY_TRIGGERS
        unknown = {trigger for trigger, _ in COMMAND_SUGGESTIONS if trigger not in known}
        self.assertEqual(
            unknown, set(), f"建议触发词未对应任何命令别名(疑似改名/删除漂移): {sorted(unknown)}"
        )


class MentionAdminGateGuardTest(unittest.IsolatedAsyncioTestCase):
    """守卫：注册表里每条 admin=True 的 mention 别名，非管理员都进不了内置动作。

    slash 侧本就有 `if is_admin` 的第二层门，mention 侧早先完全没有，
    全靠第一层闸门的前缀匹配 —— 插件用公开前缀盖过内置管理命令时就会漏。
    """

    def _build_router(self, *, is_admin: bool) -> tuple[Any, Any]:
        from unittest.mock import AsyncMock, Mock

        from app.services.routing.mention_command_router import MentionCommandRouter

        runtime = AsyncMock()
        runtime.plugins.try_dispatch_mention.return_value = False
        runtime.services.interaction.music.handle_mention.return_value = False
        # CommandAccessService 是全同步服务，不能用 AsyncMock 的子桩
        runtime.services.routing.access.is_admin = Mock(return_value=is_admin)
        runtime.services.routing.access.is_public_command = Mock(return_value=not is_admin)
        router = MentionCommandRouter(runtime)
        router._actions = AsyncMock()  # 内置动作整体替身：命中即可见，且不会真的执行
        return router, runtime

    async def test_every_admin_mention_alias_is_blocked_for_non_admin(self) -> None:
        from domain.routing.command_registry import admin_mention_prefixes

        aliases = admin_mention_prefixes()
        self.assertTrue(aliases, "注册表里应当存在 admin mention 别名")

        for alias in aliases:
            for text in (alias, f"{alias} 目标"):
                with self.subTest(text=text):
                    router, runtime = self._build_router(is_admin=False)

                    handled_as_special_case = await router.dispatch(text, "c", "a", "u")

                    self.assertFalse(handled_as_special_case)
                    self.assertEqual(
                        router._actions.mock_calls, [], f"管理命令 {text!r} 在非管理员身份下被执行"
                    )
                    runtime.sender.send_message.assert_called_once()
                    self.assertIn("无权限", runtime.sender.send_message.call_args.args[0])

    async def test_admin_still_reaches_builtin_actions(self) -> None:
        from domain.routing.command_registry import admin_mention_prefixes

        alias = sorted(admin_mention_prefixes())[0]
        router, runtime = self._build_router(is_admin=True)

        await router.dispatch(f"{alias} 目标", "c", "a", "u")

        # 管理员不该收到拒绝消息
        for call in runtime.sender.send_message.call_args_list:
            self.assertNotIn("无权限", call.args[0] if call.args else "")

    async def test_public_mention_is_untouched_by_the_gate(self) -> None:
        router, runtime = self._build_router(is_admin=False)

        await router.dispatch("帮助", "c", "a", "u")

        for call in runtime.sender.send_message.call_args_list:
            self.assertNotIn("无权限", call.args[0] if call.args else "")


class SlashAdminGateGuardTest(unittest.IsolatedAsyncioTestCase):
    """插件未处理命令后，所有内置管理员 slash 都必须再次校验身份。"""

    def _build_router(self, *, is_admin: bool) -> tuple[Any, Any]:
        from unittest.mock import AsyncMock, Mock

        from app.services.routing.slash_command_router import SlashCommandRouter

        runtime = AsyncMock()
        runtime.plugins.try_dispatch_slash.return_value = False
        runtime.services.interaction.music.handle_slash.return_value = False
        # CommandAccessService 是全同步服务，不能用 AsyncMock 的子桩
        runtime.services.routing.access.is_admin = Mock(return_value=is_admin)
        runtime.services.routing.access.is_public_command = Mock(return_value=not is_admin)
        router = SlashCommandRouter(runtime)
        router._actions = AsyncMock()
        return router, runtime

    async def test_every_admin_slash_alias_is_blocked_for_non_admin(self) -> None:
        from domain.routing.command_registry import admin_slash_commands

        aliases = admin_slash_commands()
        self.assertTrue(aliases, "注册表里应当存在 admin slash 别名")

        for alias in aliases:
            with self.subTest(alias=alias):
                router, runtime = self._build_router(is_admin=False)

                await router.dispatch(f"{alias} 目标", "c", "a", "u")

                self.assertEqual(
                    router._actions.mock_calls,
                    [],
                    f"管理命令 {alias!r} 在非管理员身份下被执行",
                )
                runtime.sender.send_message.assert_called_once()
                self.assertIn("无权限", runtime.sender.send_message.call_args.args[0])

    async def test_public_plugin_collision_cannot_fall_through_to_builtin(self) -> None:
        router, runtime = self._build_router(is_admin=False)

        await router.dispatch("/ban 目标", "c", "a", "u")

        runtime.plugins.try_dispatch_slash.assert_called_once()
        router._actions.moderation.remove_from_area.assert_not_called()

    async def test_public_slash_is_untouched_by_the_gate(self) -> None:
        router, runtime = self._build_router(is_admin=False)

        await router.dispatch("/members", "c", "a", "u")

        router._actions.community.show_members.assert_called_once_with("c", "a")
        for call in runtime.sender.send_message.call_args_list:
            self.assertNotIn("无权限", call.args[0] if call.args else "")


class SlashRouterIdentityIsolationTest(unittest.IsolatedAsyncioTestCase):
    """守卫：slash 路由不得把调用者身份挂在实例字段上。

    router 在 registry 里是单例，而 MessageDispatcher 有 4 个 worker 按
    area:channel 分片并行，实例字段会被后到的其他频道消息覆盖 —— /whois
    /search /pick 会以别人的身份执行，/help 更是直接架空 show_help 里
    按 user 判定的管理员门。
    """

    def _router(self):
        from unittest.mock import AsyncMock, Mock

        from app.services.routing.slash_command_router import SlashCommandRouter

        runtime = AsyncMock()
        runtime.plugins.try_dispatch_slash.return_value = False
        runtime.services.interaction.music.handle_slash.return_value = False
        # CommandAccessService 是全同步服务
        runtime.services.routing.access.is_admin = Mock(return_value=False)
        runtime.services.routing.access.is_public_command = Mock(return_value=True)
        router = SlashCommandRouter(runtime)
        # 内置动作会被 await，替身必须是异步的
        actions = AsyncMock()
        router._actions = actions
        return router, actions

    async def test_dispatch_hands_the_caller_identity_to_the_action(self) -> None:
        """端到端：走真实 dispatch，断言动作收到的是这次调用的 user。

        这是修复的实际接线点。只测 _arg_rules 的闭包绑定抓不到它 —— 把
        dispatch 里的实参换成空串、换成 channel、或者改回实例字段中转，
        闭包用例全都照过。
        """
        router, actions = self._router()

        await router.dispatch("/whois 张三", "chan-A", "area-1", "user-A")

        actions.community.show_whois.assert_called_once_with(
            "张三", "chan-A", "area-1", "user-A"
        )

    async def test_a_concurrent_dispatch_does_not_pollute_this_one(self) -> None:
        """另一个 worker 在本次分发中途插入时，本次仍须按自己的身份执行。

        真实竞态是 4 个 worker 并行跑同一个 router 单例；单线程等价复现是可重入 ——
        让 music 分发钩子（排在 _arg_rules 之前，正是那个窗口）再进一次 dispatch，
        相当于另一线程抢先写完了共享状态。

        顺序调用两次是抓不到的：实例字段中转在不交错时表现完全正常。
        """
        router, actions = self._router()
        reentered = []

        async def _interleave(*_args, **_kwargs):
            if not reentered:
                reentered.append(True)
                await router.dispatch("/whois 乙", "chan-B", "area-2", "user-B")
            return False

        router._services.interaction.music.handle_slash.side_effect = _interleave

        await router.dispatch("/whois 甲", "chan-A", "area-1", "user-A")

        self.assertTrue(reentered, "夹层调用没被触发，用例失去意义")
        self.assertIn(
            ("甲", "chan-A", "area-1", "user-A"),
            [c.args for c in actions.community.show_whois.call_args_list],
            "本次分发被另一次调用的身份污染了",
        )

    async def test_help_topic_gate_receives_the_dispatching_user(self) -> None:
        """/help <主题> 是主题级 fail-closed 的判定入口，喂进去的 user 必须干净。"""
        router, actions = self._router()

        await router.dispatch("/help 管理", "chan-B", "area-1", "plain-uid")

        actions.interaction.show_help.assert_called_once_with(
            "chan-B", "area-1", "plain-uid", "管理"
        )

    def test_arg_rules_bind_the_user_passed_in(self) -> None:
        router, actions = self._router()

        rules_a = router._arg_rules("chan-A", "area-1", "user-A")
        rules_b = router._arg_rules("chan-B", "area-1", "user-B")

        # 先建好 A 的规则，再建 B 的（模拟另一个 worker 插进来），
        # 之后才求值 A —— 闭包必须仍然绑着 user-A
        whois_a = next(cb for aliases, cb, _ in rules_a if "/whois" in aliases)
        whois_b = next(cb for aliases, cb, _ in rules_b if "/whois" in aliases)
        whois_b("someone")
        actions.reset_mock()
        whois_a("zhangsan")

        actions.community.show_whois.assert_called_once_with(
            "zhangsan", "chan-A", "area-1", "user-A"
        )

    def test_help_topic_gate_gets_the_real_caller(self) -> None:
        # /help <主题> 是 P0-3 主题级 fail-closed 的判定入口，喂进去的 user 必须干净
        router, actions = self._router()

        rules_admin = router._arg_rules("chan-A", "area-1", "admin-uid")
        rules_plain = router._arg_rules("chan-B", "area-1", "plain-uid")
        help_admin = next(cb for aliases, cb, _ in rules_admin if "/help" in aliases)
        help_plain = next(cb for aliases, cb, _ in rules_plain if "/help" in aliases)

        help_admin("管理")
        actions.reset_mock()
        help_plain("管理")

        actions.interaction.show_help.assert_called_once_with(
            "chan-B", "area-1", "plain-uid", "管理"
        )


if __name__ == "__main__":
    unittest.main()
