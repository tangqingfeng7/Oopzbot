PUBLIC_MENTION_PREFIXES = (
    "每日一句",
    "一句",
    "名言",
    "语录",
    "鸡汤",
    "画",
    "画一个",
    "画一张",
    "生成图片",
    "生成",
    "画图",
    "帮助",
    "help",
    "指令",
    "命令",
    "体检",
    "系统体检",
    "健康检查",
    "首启向导",
    "向导",
    "个人信息",
    "我是谁",
    "信息",
    "我的资料",
    "我的详细资料",
    "我的信息",
)

PUBLIC_COMMANDS = (
    "/daily",
    "/quote",
    "/help",
    "/health",
    "/setup",
    "/me",
    "/myinfo",
)


def is_public_mention_text(text: str) -> bool:
    return any(text.startswith(prefix) for prefix in PUBLIC_MENTION_PREFIXES)


def is_public_slash_command(command: str) -> bool:
    return command.lower() in PUBLIC_COMMANDS
