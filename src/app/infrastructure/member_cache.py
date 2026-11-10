"""成员管理操作共用的 SDK 与展示缓存失效。"""

from oopz_sdk import OopzBot

from core.ttl_cache import TtlCache

MEMBERS_RESP_TTL = 10.0
members_response_cache = TtlCache(MEMBERS_RESP_TTL)


def invalidate_members_cache(bot: OopzBot, area: str | None = None) -> None:
    bot.areas.cache.invalidate_area_members_pages(area)
    members_response_cache.invalidate()
