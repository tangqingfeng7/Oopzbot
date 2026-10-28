from __future__ import annotations

from dataclasses import dataclass, replace
from difflib import get_close_matches

from domain.routing.command_registry import admin_only_help_topics


@dataclass(frozen=True)
class HelpTopic:
    key: str
    title: str
    description: str
    aliases: tuple[str, ...]
    lines: tuple[str, ...]
    # 总览菜单（overview）用到的短标签与一句话简介；overview 自身留空。
    menu_label: str = ""
    menu_blurb: str = ""


# 主题级管理员分类由命令注册表派生（某主题全员 admin 才算管理员主题）。
ADMIN_ONLY_TOPICS = admin_only_help_topics()

HELP_TOPICS: dict[str, HelpTopic] = {
    # overview 的菜单正文由下方 _build_overview_lines() 从各主题派生后注入。
    "overview": HelpTopic(
        key="overview",
        title="总览",
        description="按场景浏览常用功能入口。",
        aliases=("总览", "首页", "帮助", "help", "命令", "指令"),
        lines=(),
    ),
    "music": HelpTopic(
        key="music",
        title="音乐",
        description="点歌、队列、喜欢列表和选歌。",
        aliases=("音乐", "点歌", "播放", "搜歌", "选歌"),
        menu_label="音乐",
        menu_blurb="点歌、队列、喜欢列表",
        lines=(
            "@bot 播放<歌名>  直接点歌",
            "@bot 搜歌<关键词>  返回候选歌曲，支持选择",
            "@bot 选歌 <编号>  播放最近一次搜歌结果",
            "@bot 停止 / 下一首 / 队列",
            "@bot 随机 / 喜欢列表 [页码]",
            "/bf <歌名>  /bf qq <歌名>  /bf bili <歌名>",
            "/songsearch <关键词>  搜歌候选",
            "/pick <编号>  选择最近一次候选结果",
            "/like  /like list  /like play <编号>",
        ),
    ),
    "query": HelpTopic(
        key="query",
        title="查询",
        description="资料、成员、搜索和语音状态。",
        aliases=("查询", "资料", "成员", "搜索", "语音"),
        menu_label="查询",
        menu_blurb="成员、资料、语音、身份组",
        lines=(
            "@bot 个人信息 / 我的资料",
            "@bot 查看 <用户名>  查看用户资料",
            "@bot 搜索 <关键词>  搜索成员并生成候选",
            "@bot 选择 <编号>  查看最近一次成员搜索/歧义解析结果",
            "@bot 成员 / 语音 / 每日一句",
            "@bot 角色 <用户> / 可分配角色 <用户>",
            "/me  /myinfo  /whois <用户>",
            "/role <用户>  /roles <用户>",
            "/search <关键词>  /pick <编号>",
            "/members  /voice  /daily",
        ),
    ),
    "reminder": HelpTopic(
        key="reminder",
        title="提醒与统计",
        description="个人提醒、活跃排行和播放统计。",
        aliases=("提醒", "统计", "排行", "活跃"),
        menu_label="提醒",
        menu_blurb="提醒、排行、统计",
        lines=(
            "@bot 提醒 30分钟后 <内容>",
            "@bot 我的提醒 / 删除提醒 <ID>",
            "@bot 活跃排行 / 频道统计 / 点歌排行 / 最近播放",
            "/remind <时间> <内容>",
            "/remind list  /remind del <ID>",
            "/ranking  /chatstats  /topsongs  /recentsongs",
        ),
    ),
    "schedule": HelpTopic(
        key="schedule",
        title="定时消息",
        description="管理员定时消息与频道推送。",
        aliases=("定时", "定时消息", "schedule"),
        menu_label="定时",
        menu_blurb="定时消息与提醒管理",
        lines=(
            "@bot 定时消息列表",
            "@bot 添加定时消息 HH:MM <内容>",
            "@bot 添加定时消息 HH:MM [1,2,3,4,5] <内容>",
            "@bot 删除定时消息 <ID>",
            "@bot 开启定时消息 <ID> / 关闭定时消息 <ID>",
            "后台支持模板一键创建: /admin/scheduler",
            "/schedule list|add|del|on|off",
        ),
    ),
    "admin": HelpTopic(
        key="admin",
        title="管理",
        description="成员管理、撤回和频道控制。",
        aliases=("管理", "禁言", "撤回", "角色", "后台"),
        menu_label="管理",
        menu_blurb="禁言、撤回、清理、身份组变更",
        lines=(
            "@bot 禁言 <用户> [分钟] / 解禁 <用户>",
            "@bot 禁麦 <用户> / 解麦 <用户>",
            "@bot 移出域 <用户> / 解封 <用户> / 封禁列表",
            "@bot 给身份组 <用户> <身份组> / 取消身份组 <用户> <身份组>",
            "@bot 自动撤回 / 撤回",
            "@bot 清理历史  (播放历史 + 日志文件 + 消息记录)",
            "/mute  /unmute  /mutemic  /unmutemic",
            "/ban  /unblock  /blocklist",
            "/addrole  /removerole  /autorecall  /recall",
        ),
    ),
    "plugin": HelpTopic(
        key="plugin",
        title="插件",
        description="插件查看、装卸和扩展命令。",
        aliases=("插件", "扩展", "plug", "plugin"),
        menu_label="插件",
        menu_blurb="插件命令与管理",
        lines=(
            "@bot 插件列表",
            "@bot 加载插件 <名> / 卸载插件 <名> / 重载插件 <名>",
            "/plugins  /loadplugin <名>",
            "/unloadplugin <名>  /reloadplugin <名>",
            "提示: 已加载插件的扩展命令会出现在帮助末尾",
        ),
    ),
    "setup": HelpTopic(
        key="setup",
        title="系统",
        description="系统体检、首启向导和后台排查入口。",
        aliases=("系统", "体检", "向导", "首启", "健康检查"),
        menu_label="系统",
        menu_blurb="系统体检与首启向导",
        lines=(
            "@bot 体检  查看当前核心依赖状态",
            "@bot 首启向导  查看分步配置建议",
            "/health  查看系统体检摘要",
            "/setup  查看首启向导",
            "后台入口: /admin/setup",
        ),
    ),
    "screen_share": HelpTopic(
        key="screen_share",
        title="屏幕共享",
        description="通过临时网页链接发起和观看屏幕共享。",
        aliases=("屏幕共享", "共享屏幕", "投屏"),
        menu_label="共享",
        menu_blurb="网页屏幕共享",
        lines=(
            "@bot 屏幕共享  私信获取单次发起链接",
            "@bot 停止屏幕共享  停止当前频道共享",
            "发起权限由后台域配置中的身份组控制",
            "推流成功后 Bot 会在原频道发送观看链接",
        ),
    ),
}


# 总览菜单展示顺序（单一来源）；列出的主题必须存在于 HELP_TOPICS。
MENU_ORDER: tuple[str, ...] = (
    "music", "query", "reminder", "screen_share", "admin", "schedule", "plugin", "setup",
)


def _display_width(text: str) -> int:
    """按终端显示宽度计长：非 ASCII（中文等全角）记 2，ASCII 记 1。"""
    return sum(2 if ord(ch) > 0x7F else 1 for ch in text)


def _overview_lines_for_keys(keys: tuple[str, ...]) -> tuple[str, ...]:
    """从各主题的 menu_label/menu_blurb 派生总览菜单，标签按显示宽度对齐。"""
    label_width = max(_display_width(HELP_TOPICS[key].menu_label) for key in keys)
    lines = ["帮助主题:"]
    for key in keys:
        topic = HELP_TOPICS[key]
        pad = " " * (label_width - _display_width(topic.menu_label))
        lines.append(f"  帮助 {topic.menu_label}{pad}  {topic.menu_blurb}")
    return tuple(lines)


def _build_overview_lines() -> tuple[str, ...]:
    return _overview_lines_for_keys(MENU_ORDER)


def overview_lines(is_admin: bool) -> tuple[str, ...]:
    """总览菜单；非管理员不展示管理员专属主题。

    过滤依据是 ADMIN_ONLY_TOPICS（从命令注册表派生），不是行文本字面量 ——
    菜单标签的对齐空格是按显示宽度动态生成的，按整行字面量匹配来过滤会在
    任何人改动 menu_label 字宽时静默失效。
    """
    if is_admin:
        return HELP_TOPICS["overview"].lines
    keys = tuple(key for key in MENU_ORDER if key not in ADMIN_ONLY_TOPICS)
    return _overview_lines_for_keys(keys)


HELP_TOPICS["overview"] = replace(HELP_TOPICS["overview"], lines=_build_overview_lines())


COMMAND_SUGGESTIONS: tuple[tuple[str, str], ...] = (
    ("帮助", "@bot 帮助"),
    ("播放", "@bot 播放<歌名>"),
    ("搜歌", "@bot 搜歌<关键词>"),
    ("选歌", "@bot 选歌 <编号>"),
    ("查看", "@bot 查看 <用户名>"),
    ("搜索", "@bot 搜索 <关键词>"),
    ("选择", "@bot 选择 <编号>"),
    ("提醒", "@bot 提醒 30分钟后 <内容>"),
    ("定时消息", "@bot 定时消息列表"),
    ("插件列表", "@bot 插件列表"),
    ("体检", "@bot 体检"),
    ("首启向导", "@bot 首启向导"),
    ("屏幕共享", "@bot 屏幕共享"),
    ("禁言", "@bot 禁言 <用户> [分钟]"),
    ("/help", "/help [主题]"),
    ("/health", "/health"),
    ("/setup", "/setup"),
    ("/bf", "/bf <歌名>"),
    ("/songsearch", "/songsearch <关键词>"),
    ("/pick", "/pick <编号>"),
    ("/search", "/search <关键词>"),
    ("/remind", "/remind <时间> <内容>"),
    ("/schedule", "/schedule list"),
    ("/plugins", "/plugins"),
)


def topic_keys() -> tuple[str, ...]:
    return tuple(HELP_TOPICS.keys())


def resolve_help_topic(raw_topic: str) -> str | None:
    text = (raw_topic or "").strip().lower()
    if not text:
        return "overview"
    for key, topic in HELP_TOPICS.items():
        values = {key.lower(), topic.title.lower(), *(alias.lower() for alias in topic.aliases)}
        if text in values:
            return key
    return None


def suggest_help_topics(raw_topic: str, limit: int = 3) -> list[str]:
    text = (raw_topic or "").strip().lower()
    if not text:
        return []
    names: dict[str, str] = {}
    for key, topic in HELP_TOPICS.items():
        names[key.lower()] = topic.title
        names[topic.title.lower()] = topic.title
        for alias in topic.aliases:
            names[alias.lower()] = topic.title
    matches = get_close_matches(text, list(names.keys()), n=limit, cutoff=0.45)
    ordered: list[str] = []
    for match in matches:
        title = names[match]
        if title not in ordered:
            ordered.append(title)
    return ordered


def suggest_command_usages(raw_text: str, limit: int = 3) -> list[str]:
    text = (raw_text or "").strip()
    if not text:
        return []
    token = text.split()[0]
    variants = [text.lower(), token.lower()]
    score_map: dict[str, str] = {}
    for key, usage in COMMAND_SUGGESTIONS:
        score_map[key.lower()] = usage
    candidates: list[str] = []
    for variant in variants:
        candidates.extend(get_close_matches(variant, list(score_map.keys()), n=limit, cutoff=0.45))
    ordered: list[str] = []
    for candidate in candidates:
        usage = score_map[candidate]
        if usage not in ordered:
            ordered.append(usage)
        if len(ordered) >= limit:
            break
    return ordered
