from collections.abc import Iterable
from typing import Any, Optional


def resolve_role_id(roles: Iterable[dict[str, Any]], role_arg: str) -> Optional[Any]:
    candidate = (role_arg or "").strip()
    if not candidate:
        return None

    for role in roles:
        role_id = role.get("roleID")
        role_name = (role.get("name") or "").strip()
        if role_id is not None and str(role_id) == candidate:
            return role_id
        if role_name == candidate:
            return role_id
    return None
