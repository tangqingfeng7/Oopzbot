from __future__ import annotations

import json
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

    def upsert_place_push_subscription(
        self,
        user_id: str,
        channel_id: str,
        area_id: str,
        last_snapshot: Optional[list[dict]] = None,
    ) -> None:
        snapshot_text = "[]"
        if isinstance(last_snapshot, list):
            snapshot_text = json.dumps(last_snapshot, ensure_ascii=False)
        conn = get_connection()
        conn.execute(
            """
            INSERT INTO delta_force_place_push (user_id, channel_id, area_id, last_snapshot, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, channel_id, area_id) DO UPDATE SET
                last_snapshot=excluded.last_snapshot,
                updated_at=excluded.updated_at
            """,
            (str(user_id), str(channel_id), str(area_id), snapshot_text, cn_now()),
        )
        conn.commit()
        conn.close()

    def remove_place_push_subscription(self, user_id: str, channel_id: str, area_id: str) -> None:
        conn = get_connection()
        conn.execute(
            "DELETE FROM delta_force_place_push WHERE user_id=? AND channel_id=? AND area_id=?",
            (str(user_id), str(channel_id), str(area_id)),
        )
        conn.commit()
        conn.close()

    def has_place_push_subscription(self, user_id: str, channel_id: str, area_id: str) -> bool:
        conn = get_connection()
        row = conn.execute(
            "SELECT 1 FROM delta_force_place_push WHERE user_id=? AND channel_id=? AND area_id=?",
            (str(user_id), str(channel_id), str(area_id)),
        ).fetchone()
        conn.close()
        return bool(row)

    def any_place_push_subscriptions(self) -> bool:
        conn = get_connection()
        row = conn.execute("SELECT 1 FROM delta_force_place_push LIMIT 1").fetchone()
        conn.close()
        return bool(row)

    def list_place_push_subscriptions(self) -> list[dict]:
        conn = get_connection()
        rows = conn.execute(
            "SELECT user_id, channel_id, area_id, last_snapshot, updated_at FROM delta_force_place_push"
        ).fetchall()
        conn.close()
        results: list[dict] = []
        for row in rows:
            item = dict(row)
            try:
                item["last_snapshot"] = json.loads(item.get("last_snapshot") or "[]")
            except Exception:
                item["last_snapshot"] = []
            results.append(item)
        return results

    def update_place_push_snapshot(
        self,
        user_id: str,
        channel_id: str,
        area_id: str,
        snapshot: Optional[list[dict]],
    ) -> None:
        if not self.has_place_push_subscription(user_id, channel_id, area_id):
            return
        snapshot_text = "[]"
        if isinstance(snapshot, list):
            snapshot_text = json.dumps(snapshot, ensure_ascii=False)
        conn = get_connection()
        conn.execute(
            """
            UPDATE delta_force_place_push
            SET last_snapshot=?, updated_at=?
            WHERE user_id=? AND channel_id=? AND area_id=?
            """,
            (snapshot_text, cn_now(), str(user_id), str(channel_id), str(area_id)),
        )
        conn.commit()
        conn.close()

    def upsert_daily_keyword_push_subscription(self, channel_id: str, area_id: str, last_push_date: str = "") -> None:
        conn = get_connection()
        conn.execute(
            """
            INSERT INTO delta_force_daily_keyword_push (channel_id, area_id, last_push_date, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(channel_id, area_id) DO UPDATE SET
                last_push_date=excluded.last_push_date,
                updated_at=excluded.updated_at
            """,
            (str(channel_id), str(area_id), str(last_push_date or ""), cn_now()),
        )
        conn.commit()
        conn.close()

    def remove_daily_keyword_push_subscription(self, channel_id: str, area_id: str) -> None:
        conn = get_connection()
        conn.execute(
            "DELETE FROM delta_force_daily_keyword_push WHERE channel_id=? AND area_id=?",
            (str(channel_id), str(area_id)),
        )
        conn.commit()
        conn.close()

    def has_daily_keyword_push_subscription(self, channel_id: str, area_id: str) -> bool:
        conn = get_connection()
        row = conn.execute(
            "SELECT 1 FROM delta_force_daily_keyword_push WHERE channel_id=? AND area_id=?",
            (str(channel_id), str(area_id)),
        ).fetchone()
        conn.close()
        return bool(row)

    def any_daily_keyword_push_subscriptions(self) -> bool:
        conn = get_connection()
        row = conn.execute("SELECT 1 FROM delta_force_daily_keyword_push LIMIT 1").fetchone()
        conn.close()
        return bool(row)

    def list_daily_keyword_push_subscriptions(self) -> list[dict]:
        conn = get_connection()
        rows = conn.execute(
            "SELECT channel_id, area_id, last_push_date, updated_at FROM delta_force_daily_keyword_push"
        ).fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def mark_daily_keyword_pushed(self, channel_id: str, area_id: str, push_date: str) -> None:
        if not self.has_daily_keyword_push_subscription(channel_id, area_id):
            return
        conn = get_connection()
        conn.execute(
            """
            UPDATE delta_force_daily_keyword_push
            SET last_push_date=?, updated_at=?
            WHERE channel_id=? AND area_id=?
            """,
            (str(push_date), cn_now(), str(channel_id), str(area_id)),
        )
        conn.commit()
        conn.close()
