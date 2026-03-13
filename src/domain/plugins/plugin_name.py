import re
from typing import Optional


PLUGIN_NAME_PATTERN = re.compile(r"[A-Za-z0-9_]+")


def normalize_plugin_name(raw_name: str) -> Optional[str]:
    name = (raw_name or "").strip()
    if name.endswith(".py"):
        name = name[:-3]
    if not PLUGIN_NAME_PATTERN.fullmatch(name):
        return None
    return name
