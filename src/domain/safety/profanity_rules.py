from collections.abc import Sequence
from typing import Optional


DEFAULT_MUTE_THRESHOLDS = (1, 5, 60, 1440, 4320, 10080)


def match_keyword(text: str, keywords: Sequence[str]) -> Optional[str]:
    lowered = text.lower()
    for keyword in keywords:
        if keyword in lowered:
            return keyword
    return None


def match_context_keyword(
    messages: Sequence[str],
    keywords: Sequence[str],
) -> Optional[tuple[str, int]]:
    if len(messages) < 2:
        return None

    for start in range(len(messages) - 2, -1, -1):
        keyword = match_keyword("".join(messages[start:]), keywords)
        if keyword:
            return keyword, start
    return None


def actual_mute_duration(
    minutes: int,
    thresholds: Sequence[int] = DEFAULT_MUTE_THRESHOLDS,
) -> int:
    for limit in thresholds:
        if minutes <= limit:
            return limit
    return thresholds[-1] if thresholds else minutes


def format_duration(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} 分钟"
    if minutes < 1440:
        return f"{minutes // 60} 小时"
    return f"{minutes // 1440} 天"
