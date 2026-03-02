"""
Local persistence for Delta Force account selection.
"""

from __future__ import annotations

from typing import Optional

from database import cn_now, get_connection


class DeltaForceStore:
    def get_active_token(self, user_id: str, group: str = "qq_wechat") -> Optional[str]:
        conn = get_connection()
        row = conn.execute(
            "SELECT framework_token FROM delta_force_active_token WHERE user_id=? AND account_group=?",
            (str(user_id), str(group)),
        ).fetchone()
        conn.close()
        if not row:
            return None
        token = row["framework_token"]
        return str(token) if token else None

    def set_active_token(self, user_id: str, token: str, group: str = "qq_wechat") -> None:
        conn = get_connection()
        conn.execute(
            """
            INSERT INTO delta_force_active_token (user_id, account_group, framework_token, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                account_group=excluded.account_group,
                framework_token=excluded.framework_token,
                updated_at=excluded.updated_at
            """,
            (str(user_id), str(group), str(token), cn_now()),
        )
        conn.commit()
        conn.close()

    def clear_active_token(self, user_id: str) -> None:
        conn = get_connection()
        conn.execute("DELETE FROM delta_force_active_token WHERE user_id=?", (str(user_id),))
        conn.commit()
        conn.close()

    def choose_active_token(self, user_id: str, accounts: list[dict], group: str = "qq_wechat") -> Optional[str]:
        current = self.get_active_token(user_id, group)
        valid_tokens: list[str] = []
        for account in accounts:
            if not isinstance(account, dict):
                continue
            token = str(account.get("frameworkToken") or "").strip()
            if not token:
                continue
            if current and current == token:
                self.set_active_token(user_id, current, group)
                return current
            if account.get("isValid"):
                valid_tokens.append(token)

        if not valid_tokens:
            self.clear_active_token(user_id)
            return None

        self.set_active_token(user_id, valid_tokens[0], group)
        return valid_tokens[0]
