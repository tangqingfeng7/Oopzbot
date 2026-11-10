from collections.abc import Iterable


def resolve_role_id(roles: Iterable[tuple[int, str]], role_arg: str) -> int | None:
    candidate = (role_arg or "").strip()
    if not candidate:
        return None

    for role_id, role_name in roles:
        role_name = role_name.strip()
        if str(role_id) == candidate:
            return role_id
        if role_name == candidate:
            return role_id
    return None
