"""LOL 插件共享逻辑"""


def extract_keyword_from_mention(text: str, mention_prefixes: tuple[str, ...]) -> str:
    """从 @提及 消息中提取关键词（去掉前缀后 trim）。"""
    for p in mention_prefixes:
        if text.startswith(p):
            return text[len(p) :].strip()
    return text.strip()
