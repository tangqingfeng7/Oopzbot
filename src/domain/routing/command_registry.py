"""
命令注册表 —— 命令定义的单一来源。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommandSpec:
    """一条命令的声明式定义。

    slash:   以 ``/`` 开头的英文别名（slash 通道）。
    mention: ``@bot`` 后的中文/英文别名（mention 通道）。
    admin:   是否仅管理员可用（驱动权限规则）。
    help_topic: 关联的帮助主题 key（驱动 help_catalog 的 ADMIN_ONLY_TOPICS 派生）。
    """

    id: str
    slash: tuple[str, ...] = ()
    mention: tuple[str, ...] = ()
    admin: bool = False
    help_topic: str | None = None


# ---------------------------------------------------------------------------
# 命令清单（单一来源）
#
# 不含「音乐服务」「插件扩展」等自带独立分发的命令——它们不在上述四处分散表内。
# ---------------------------------------------------------------------------

COMMANDS: tuple[CommandSpec, ...] = (
    # --- 插件管理（管理员） ---
    CommandSpec("plugin_load", ("/loadplugin",), ("加载插件", "启用插件", "loadplugin"), admin=True, help_topic="plugin"),
    CommandSpec("plugin_unload", ("/unloadplugin",), ("卸载插件", "禁用插件", "unloadplugin"), admin=True, help_topic="plugin"),
    CommandSpec("plugin_reload", ("/reloadplugin",), ("重载插件", "刷新插件", "reloadplugin"), admin=True, help_topic="plugin"),
    CommandSpec("plugin_list", ("/plugins",), ("插件列表", "扩展列表", "插件"), admin=True, help_topic="plugin"),
    # --- 审核 / 管理（管理员） ---
    CommandSpec("mute", ("/禁言", "/mute"), ("禁言",), admin=True, help_topic="admin"),
    CommandSpec("unmute", ("/解禁", "/unmute"), ("解除禁言", "解禁"), admin=True, help_topic="admin"),
    CommandSpec("mute_mic", ("/禁麦", "/mutemic"), ("禁麦",), admin=True, help_topic="admin"),
    CommandSpec("unmute_mic", ("/解麦", "/unmutemic"), ("解除禁麦", "解麦"), admin=True, help_topic="admin"),
    CommandSpec("remove_from_area", ("/ban",), ("移出域", "踢出", "移出"), admin=True, help_topic="admin"),
    CommandSpec("unblock", ("/unblock",), ("解除域内封禁", "解封"), admin=True, help_topic="admin"),
    CommandSpec("blocklist", ("/blocklist",), ("封禁列表", "封禁名单", "黑名单"), admin=True, help_topic="admin"),
    CommandSpec("autorecall", ("/autorecall",), ("自动撤回",), admin=True, help_topic="admin"),
    CommandSpec("recall", ("/recall",), ("撤回",), admin=True, help_topic="admin"),
    CommandSpec("clear_history", ("/clear",), ("清理历史", "清理记录", "清除历史", "清空历史", "清理数据"), admin=True, help_topic="admin"),
    CommandSpec(
        "schedule",
        ("/schedule",),
        (
            "定时消息列表", "定时消息", "添加定时消息", "新增定时消息",
            "删除定时消息", "移除定时消息", "开启定时消息", "启用定时消息",
            "关闭定时消息", "停用定时消息",
        ),
        admin=True,
        help_topic="schedule",
    ),
    CommandSpec("addrole", ("/addrole",), ("给身份组", "添加身份组", "addrole"), admin=True, help_topic="admin"),
    CommandSpec("removerole", ("/removerole",), ("取消身份组", "移除身份组", "removerole"), admin=True, help_topic="admin"),
    # --- 社区查询（公开） ---
    CommandSpec("members", ("/members", "/online"), ("成员", "在线", "成员列表", "谁在线"), help_topic="query"),
    CommandSpec("profile", ("/me",), ("个人信息", "我是谁", "信息"), help_topic="query"),
    CommandSpec("myinfo", ("/myinfo",), ("我的资料", "我的详细资料", "我的信息"), help_topic="query"),
    CommandSpec("voice", ("/voice",), ("语音", "语音频道", "语音在线", "谁在语音"), help_topic="query"),
    CommandSpec("daily", ("/daily", "/quote"), ("每日一句", "一句", "名言", "语录", "鸡汤"), help_topic="query"),
    CommandSpec("whois", ("/whois",), ("查看", "资料", "查询资料"), help_topic="query"),
    # 这两条是查身份组，本就是公开查询；挂在 admin 主题下会把整个管理主题降级成公开
    CommandSpec("role", ("/role",), ("角色",), help_topic="query"),
    CommandSpec("roles", ("/roles",), ("可分配角色", "分配角色"), help_topic="query"),
    CommandSpec("search", ("/search",), ("搜索成员", "搜索", "找人"), help_topic="query"),
    CommandSpec("enter", ("/enter",), ("进入频道", "进入"), help_topic="query"),
    # --- 提醒 / 统计（公开） ---
    CommandSpec("ranking", ("/ranking", "/活跃", "/活跃排行"), ("活跃排行", "活跃榜", "排行榜"), help_topic="reminder"),
    CommandSpec("chatstats", ("/chatstats", "/频道统计"), ("频道统计", "消息统计"), help_topic="reminder"),
    CommandSpec("topsongs", ("/topsongs", "/点歌排行", "/播放排行"), ("点歌排行", "播放排行", "热歌榜"), help_topic="reminder"),
    CommandSpec("recentsongs", ("/recentsongs", "/最近播放"), ("最近播放", "播放历史"), help_topic="reminder"),
    CommandSpec("remind", ("/remind", "/提醒"), ("提醒",), help_topic="reminder"),
    CommandSpec("delete_reminder", (), ("删除提醒", "取消提醒"), help_topic="reminder"),
    CommandSpec("reminders_list", (), ("我的提醒", "提醒列表"), help_topic="reminder"),
    # --- 音乐候选选择（公开；其余音乐命令由音乐服务独立分发） ---
    CommandSpec("songsearch", ("/songsearch",), ("搜歌", "搜索歌曲"), help_topic="music"),
    CommandSpec("pick", ("/pick",), ("选择", "选歌"), help_topic="music"),
    # 屏幕共享在业务层按域 roleID 授权，不能标成全局 Bot 管理员命令。
    CommandSpec("screen_share", (), ("屏幕共享", "共享屏幕"), help_topic="screen_share"),
    CommandSpec("screen_share_stop", (), ("停止屏幕共享", "结束屏幕共享"), help_topic="screen_share"),
    # --- 系统（公开） ---
    CommandSpec("help", ("/help",), ("帮助", "help", "指令", "命令"), help_topic="overview"),
    CommandSpec("health", ("/health", "/doctor"), ("体检", "系统体检", "健康检查"), help_topic="setup"),
    CommandSpec("setup", ("/setup", "/wizard"), ("首启向导", "向导"), help_topic="setup"),
)


# ---------------------------------------------------------------------------
# 派生视图
# ---------------------------------------------------------------------------

_BY_ID: dict[str, CommandSpec] = {spec.id: spec for spec in COMMANDS}


def spec_of(command_id: str) -> CommandSpec:
    """按 id 取命令定义。"""
    return _BY_ID[command_id]


def slash_of(command_id: str) -> tuple[str, ...]:
    """某命令的 slash 别名元组。"""
    return _BY_ID[command_id].slash


def mention_of(command_id: str) -> tuple[str, ...]:
    """某命令的 mention 别名元组。"""
    return _BY_ID[command_id].mention


def admin_slash_commands() -> frozenset[str]:
    """所有仅管理员可用命令的 slash 别名集合。"""
    return frozenset(alias for spec in COMMANDS if spec.admin for alias in spec.slash)


def admin_mention_prefixes() -> tuple[str, ...]:
    """所有仅管理员可用命令的 mention 别名（按注册顺序）。"""
    return tuple(alias for spec in COMMANDS if spec.admin for alias in spec.mention)


def admin_only_help_topics() -> frozenset[str]:
    """含管理员专属命令的帮助主题集合。

    判定是 fail-closed：主题下**只要有一条** ``admin=True`` 的命令，整个主题就
    不对非管理员展示。早先按「全部命令都是 admin 才算管理主题」归约，一条公开
    命令就能把整个主题降级成公开 —— ``admin`` 主题正是因为混进了公开的
    ``/role`` / ``/roles``，导致非管理员发「帮助 管理」能看到全量管理命令清单。

    代价是主题里少数公开命令会一并被藏起来，所以公开命令应挂到它真正所属的
    主题（如查询类挂 ``query``），而不是靠这里放行。
    """
    by_topic: dict[str, bool] = {}
    for spec in COMMANDS:
        if spec.help_topic is None:
            continue
        by_topic[spec.help_topic] = by_topic.get(spec.help_topic, False) or spec.admin
    return frozenset(topic for topic, has_admin in by_topic.items() if has_admin)
