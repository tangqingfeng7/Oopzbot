from __future__ import annotations

import asyncio
import base64
import json
import struct
import sys
import unittest
import zlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from app.services.interaction.screen_share_command_service import (  # noqa: E402
    ScreenShareCommandService,
)
from screen_share import web as screen_share_web  # noqa: E402
from screen_share.agora_token import build_rtc_token  # noqa: E402
from screen_share.service import ScreenShareError, ScreenShareService  # noqa: E402
from web.admin import screen_share as admin_screen_share  # noqa: E402

APP_ID = "1" * 32
CERTIFICATE = "2" * 32
CONFIG = {
    "enabled": True,
    "agora_app_id": APP_ID,
    "agora_app_certificate": CERTIFICATE,
    "presenter_link_ttl_seconds": 600,
    "session_max_seconds": 300,
    "rtc_token_ttl_seconds": 300,
    "default_quality": "1080p",
}


def _unpack_u16(data: bytes, offset: int) -> tuple[int, int]:
    return struct.unpack_from("<H", data, offset)[0], offset + 2


def _unpack_u32(data: bytes, offset: int) -> tuple[int, int]:
    return struct.unpack_from("<I", data, offset)[0], offset + 4


def _unpack_string(data: bytes, offset: int) -> tuple[bytes, int]:
    length, offset = _unpack_u16(data, offset)
    return data[offset:offset + length], offset + length


def _decode_rtc_token(token: str) -> dict:
    data = zlib.decompress(base64.b64decode(token[3:]))
    signature, offset = _unpack_string(data, 0)
    app_id, offset = _unpack_string(data, offset)
    issue_ts, offset = _unpack_u32(data, offset)
    token_expire, offset = _unpack_u32(data, offset)
    _salt, offset = _unpack_u32(data, offset)
    service_count, offset = _unpack_u16(data, offset)
    service_type, offset = _unpack_u16(data, offset)
    privilege_count, offset = _unpack_u16(data, offset)
    privileges: dict[int, int] = {}
    for _ in range(privilege_count):
        privilege, offset = _unpack_u16(data, offset)
        expire, offset = _unpack_u32(data, offset)
        privileges[privilege] = expire
    channel, offset = _unpack_string(data, offset)
    uid, offset = _unpack_string(data, offset)
    return {
        "signature": signature,
        "app_id": app_id.decode(),
        "issue_ts": issue_ts,
        "token_expire": token_expire,
        "service_count": service_count,
        "service_type": service_type,
        "privileges": privileges,
        "channel": channel.decode(),
        "uid": uid.decode(),
        "remaining": data[offset:],
    }


class FakeRedis:
    """覆盖屏幕共享使用到的 Redis 原语和三段 Lua 的内存替身。"""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.expires: dict[str, int] = {}
        self.clock = 0

    def advance(self, seconds: int) -> None:
        self.clock += seconds

    def _purge(self, key: str) -> None:
        expires_at = self.expires.get(key)
        if expires_at is not None and expires_at <= self.clock:
            self.data.pop(key, None)
            self.expires.pop(key, None)

    async def get(self, key):
        key = key.decode() if isinstance(key, bytes) else str(key)
        self._purge(key)
        return self.data.get(key)

    async def set(self, key, value, ex=None):
        key = str(key)
        self.data[key] = str(value)
        if ex is not None:
            self.expires[key] = self.clock + int(ex)
        return True

    async def scan(self, cursor=0, match="*", count=100):
        del cursor, count
        prefix = str(match).removesuffix("*")
        for key in list(self.data):
            self._purge(key)
        return 0, [key for key in self.data if key.startswith(prefix)]

    async def eval(self, script, numkeys, *values):
        keys = [str(value) for value in values[:numkeys]]
        args = list(values[numkeys:])
        if "USER_BUSY" in script:
            if keys[0] in self.data:
                return "USER_BUSY"
            sid, payload, ttl = str(args[0]), str(args[1]), int(args[2])
            for key in keys[:3]:
                self.data[key] = sid
                self.expires[key] = self.clock + ttl
            self.data[keys[3]] = payload
            self.expires[keys[3]] = self.clock + ttl
            return "OK"
        if "CLAIMED" in script:
            sid = self.data.get(keys[0])
            payload = self.data.get(keys[1])
            if not sid or not payload:
                return "INVALID"
            session = json.loads(payload)
            if session["status"] != "pending":
                return "CLAIMED"
            auth_hash, now, ttl = str(args[0]), int(args[1]), int(args[2])
            storage_ttl = int(args[3])
            session.update(
                status="claimed",
                claimed_at=now,
                expires_at=now + ttl,
                presenter_auth_hash=auth_hash,
            )
            self.data.pop(keys[0], None)
            self.data[keys[2]] = sid
            self.data[keys[1]] = json.dumps(session)
            for key in keys[1:]:
                self.expires[key] = self.clock + storage_ttl
            return json.dumps(session)
        if "_first_ready" in script:
            sid = self.data.get(keys[2])
            payload = self.data.get(keys[0])
            if not sid or sid != str(args[4]) or not payload:
                return "INVALID"
            session = json.loads(payload)
            if session["presenter_auth_hash"] != str(args[3]):
                return "INVALID"
            if session["status"] == "active":
                session["_first_ready"] = False
                return json.dumps(session)
            if session["status"] != "claimed":
                return "INVALID_STATE"
            viewer_hash, now, ttl = str(args[0]), int(args[1]), int(args[2])
            storage_ttl = int(args[5])
            session.update(
                status="active",
                viewer_token_hash=viewer_hash,
                ready_at=now,
                last_heartbeat=now,
            )
            self.data[keys[0]] = json.dumps(session)
            self.data[keys[1]] = sid
            self.expires[keys[0]] = self.clock + storage_ttl
            self.expires[keys[1]] = self.clock + ttl
            session["_first_ready"] = True
            return json.dumps(session)
        if "heartbeat timestamp" not in script and "last_heartbeat" in script:
            sid = self.data.get(keys[1])
            payload = self.data.get(keys[0])
            if not sid or sid != str(args[1]) or not payload:
                return "INVALID"
            session = json.loads(payload)
            if session["presenter_auth_hash"] != str(args[2]):
                return "INVALID"
            if session["status"] not in {"claimed", "active"}:
                return "INVALID_STATE"
            now = int(args[0])
            ttl = int(session["expires_at"]) - now
            if ttl <= 0:
                return "EXPIRED"
            session["last_heartbeat"] = now
            self.data[keys[0]] = json.dumps(session)
            self.expires[keys[0]] = self.clock + ttl + int(args[3])
            return json.dumps(session)
        if "RECORD_VIEWER_MESSAGE" in script:
            payload = self.data.get(keys[0])
            if not payload:
                return "INVALID"
            session = json.loads(payload)
            if session["status"] != "active":
                return "INVALID"
            ttl = int(session["expires_at"]) - int(args[2])
            if ttl <= 0:
                return "EXPIRED"
            session["viewer_message_id"] = str(args[0])
            session["viewer_message_timestamp"] = str(args[1])
            self.data[keys[0]] = json.dumps(session)
            self.expires[keys[0]] = self.clock + ttl + int(args[3])
            return "OK"
        if "redis.call('del', KEYS[1], KEYS[2]" in script:
            payload = self.data.get(keys[0], "")
            session_id = str(json.loads(payload).get("id") or "") if payload else ""
            for key in (*keys[:5], keys[6]):
                self.data.pop(key, None)
                self.expires.pop(key, None)
            if self.data.get(keys[5]) == session_id:
                self.data.pop(keys[5], None)
                self.expires.pop(keys[5], None)
            return payload
        raise AssertionError("unexpected Lua script")


class AgoraTokenTest(unittest.TestCase):
    def test_publisher_and_viewer_privileges_are_separated(self) -> None:
        publisher = _decode_rtc_token(build_rtc_token(
            app_id=APP_ID,
            app_certificate=CERTIFICATE,
            channel_name="oopz-share-test",
            uid=123,
            expires_in=600,
            publish=True,
            now=1000,
        ))
        viewer = _decode_rtc_token(build_rtc_token(
            app_id=APP_ID,
            app_certificate=CERTIFICATE,
            channel_name="oopz-share-test",
            uid=456,
            expires_in=600,
            publish=False,
            now=1000,
        ))
        self.assertEqual(publisher["privileges"], {1: 600, 2: 600, 3: 600, 4: 600})
        self.assertEqual(viewer["privileges"], {1: 600})
        self.assertEqual(publisher["app_id"], APP_ID)
        self.assertEqual(publisher["channel"], "oopz-share-test")
        self.assertEqual(publisher["uid"], "123")
        self.assertEqual(publisher["remaining"], b"")
        self.assertEqual(len(publisher["signature"]), 32)
        self.assertNotIn(CERTIFICATE.encode(), base64.b64decode(build_rtc_token(
            app_id=APP_ID,
            app_certificate=CERTIFICATE,
            channel_name="safe",
            uid=1,
            expires_in=600,
            publish=True,
            now=1000,
        )[3:]))


class ScreenShareServiceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.redis = FakeRedis()
        self.service = ScreenShareService()
        self.config_patch = patch("screen_share.service._config", return_value=dict(CONFIG))
        self.redis_patch = patch("screen_share.service.get_redis_client", AsyncMock(return_value=self.redis))
        self.degraded_patch = patch("screen_share.service.is_degraded", return_value=False)
        self.config_patch.start()
        self.redis_patch.start()
        self.degraded_patch.start()
        self.addCleanup(self.config_patch.stop)
        self.addCleanup(self.redis_patch.stop)
        self.addCleanup(self.degraded_patch.stop)

    async def _create(self, *, user="u1", area="a1", channel="c1"):
        with patch.object(self.service, "authorize", AsyncMock(return_value=True)):
            return await self.service.create_session(
                sender=Mock(), user=user, area=area, channel=channel,
            )

    async def test_single_claim_viewer_lifecycle_and_fragment_links(self) -> None:
        with patch("screen_share.service.time.time", return_value=1000):
            links = await self._create()
            self.assertIn("/screen-share/p#", links.presenter_url)
            presenter_token = links.presenter_url.split("#", 1)[1]
            credentials, auth = await self.service.claim(presenter_token)
            self.assertEqual(credentials["default_quality"], "1080p")
            with self.assertRaises(ScreenShareError) as second_claim:
                await self.service.claim(presenter_token)
            self.assertEqual(second_claim.exception.code, "invalid_link")

            ready = await self.service.mark_ready(auth)
            self.assertTrue(ready["first_ready"])
            viewer = await self.service.viewer_credentials(
                ready["viewer_token"],
                viewer_instance="viewer-tab-1",
            )
            self.assertEqual(viewer["channel"], credentials["channel"])
            self.assertTrue(
                await self.service.record_viewer_message(
                    ready["session"]["id"],
                    message_id="message-1",
                    timestamp="timestamp-1",
                )
            )
            stopped = await self.service.stop(ready["session"])
            self.assertEqual(stopped["viewer_message_id"], "message-1")
            self.assertEqual(stopped["viewer_message_timestamp"], "timestamp-1")
            with self.assertRaises(ScreenShareError):
                await self.service.viewer_credentials(
                    ready["viewer_token"],
                    viewer_instance="viewer-tab-1",
                )

    async def test_same_channel_allows_multiple_users_but_user_lock_remains_atomic(self) -> None:
        first = await self._create()
        second = await self._create(user="u2", channel="c1")
        self.assertNotEqual(first.session_id, second.session_id)
        with self.assertRaises(ScreenShareError) as user_busy:
            await self._create(user="u1", channel="c2")
        self.assertEqual(user_busy.exception.code, "user_busy")

        await self.redis.set("screen_share:session:unrelated-corrupt", "not-json", ex=300)
        sessions = await self.service.list_by_channel(area="a1", channel="c1")
        self.assertEqual(
            {session["presenter_uid"] for session in sessions},
            {"u1", "u2"},
        )
        await self.service.stop(sessions[0], reason="test_isolated_stop")
        remaining = await self.service.list_by_channel(area="a1", channel="c1")
        self.assertEqual(len(remaining), 1)
        self.assertNotEqual(remaining[0]["presenter_uid"], sessions[0]["presenter_uid"])

    async def test_viewer_uid_is_stable_per_tab_and_distinct_between_tabs(self) -> None:
        with patch("screen_share.service.time.time", return_value=1000):
            links = await self._create()
            _, auth = await self.service.claim(links.presenter_url.split("#", 1)[1])
            ready = await self.service.mark_ready(auth)

        with patch("screen_share.service.time.time", return_value=1000):
            first = await self.service.viewer_credentials(
                ready["viewer_token"],
                viewer_instance="viewer-tab-1",
            )
            renewed = await self.service.viewer_credentials(
                ready["viewer_token"],
                viewer_instance="viewer-tab-1",
            )
            other = await self.service.viewer_credentials(
                ready["viewer_token"],
                viewer_instance="viewer-tab-2",
            )

        self.assertEqual(first["uid"], renewed["uid"])
        self.assertEqual(_decode_rtc_token(renewed["token"])["uid"], str(first["uid"]))
        self.assertNotEqual(first["uid"], other["uid"])

    async def test_viewer_credentials_reject_missing_instance(self) -> None:
        with patch("screen_share.service.time.time", return_value=1000):
            links = await self._create()
            _, auth = await self.service.claim(links.presenter_url.split("#", 1)[1])
            ready = await self.service.mark_ready(auth)
        with self.assertRaises(ScreenShareError) as invalid:
            await self.service.viewer_credentials(
                ready["viewer_token"],
                viewer_instance="",
            )
        self.assertEqual(invalid.exception.code, "invalid_viewer_instance")

    async def test_rtc_token_ttl_never_exceeds_session_and_allows_final_short_renewal(self) -> None:
        config = {**CONFIG, "rtc_token_ttl_seconds": 3600, "session_max_seconds": 300}
        with (
            patch("screen_share.service._config", return_value=config),
            patch("screen_share.service.time.time", return_value=1000),
        ):
            links = await self._create()
            credentials, auth = await self.service.claim(links.presenter_url.split("#", 1)[1])
        self.assertEqual(credentials["expires_in"], 300)

        with (
            patch("screen_share.service._config", return_value=config),
            patch("screen_share.service.time.time", return_value=1241),
        ):
            renewed = await self.service.renew_presenter(auth)
        self.assertEqual(renewed["expires_in"], 59)
        decoded = _decode_rtc_token(renewed["token"])
        self.assertEqual(decoded["token_expire"], 59)
        self.assertEqual(set(decoded["privileges"].values()), {59})

        with (
            patch("screen_share.service._config", return_value=config),
            patch("screen_share.service.time.time", return_value=1300),
            self.assertRaises(ScreenShareError) as expired,
        ):
            await self.service.renew_presenter(auth)
        self.assertEqual(expired.exception.code, "session_expired")

    async def test_max_duration_expiry_remains_visible_to_watchdog(self) -> None:
        with patch("screen_share.service.time.time", return_value=1000):
            links = await self._create()
            _, auth = await self.service.claim(links.presenter_url.split("#", 1)[1])
            ready = await self.service.mark_ready(auth)
        with patch("screen_share.service.time.time", return_value=1290):
            await self.service.heartbeat(auth)
        with (
            patch("screen_share.service.time.time", return_value=1300),
            self.assertLogs("screen_share.service", level="INFO") as captured,
        ):
            expired = await self.service.expire_stale()
        self.assertEqual([item["id"] for item in expired], [ready["session"]["id"]])
        self.assertTrue(any("reason=session_expired" in line for line in captured.output))
        self.assertIsNone(await self.service.get_by_id(ready["session"]["id"]))

    async def test_presenter_link_expires_after_ten_minutes(self) -> None:
        links = await self._create()
        self.redis.advance(601)
        with self.assertRaises(ScreenShareError) as expired:
            await self.service.claim(links.presenter_url.split("#", 1)[1])
        self.assertEqual(expired.exception.code, "invalid_link")

    async def test_heartbeat_allows_short_interruption_then_stops_after_sixty_seconds(self) -> None:
        with patch("screen_share.service.time.time", return_value=1000):
            links = await self._create()
            _, auth = await self.service.claim(links.presenter_url.split("#", 1)[1])
            ready = await self.service.mark_ready(auth)
        with patch("screen_share.service.time.time", return_value=1059):
            self.assertEqual(await self.service.expire_stale(), [])
        with (
            patch("screen_share.service.time.time", return_value=1061),
            self.assertLogs("screen_share.service", level="INFO") as captured,
        ):
            expired = await self.service.expire_stale()
        self.assertEqual([item["id"] for item in expired], [ready["session"]["id"]])
        self.assertTrue(any("reason=heartbeat_timeout" in line for line in captured.output))

    async def test_concurrent_ready_creates_only_one_viewer_link(self) -> None:
        with patch("screen_share.service.time.time", return_value=1000):
            links = await self._create()
            _, auth = await self.service.claim(links.presenter_url.split("#", 1)[1])
            results = await asyncio.gather(
                self.service.mark_ready(auth),
                self.service.mark_ready(auth),
            )
        self.assertEqual(sum(bool(item["first_ready"]) for item in results), 1)
        self.assertEqual(sum(bool(item["viewer_token"]) for item in results), 1)
        self.assertEqual(
            len([key for key in self.redis.data if key.startswith("screen_share:viewer:")]),
            1,
        )

    async def test_admin_active_share_link_is_sanitized_and_expires_with_session(self) -> None:
        with (
            patch("screen_share.service.time.time", return_value=1000),
            patch("web.web_player_config.display_web_base_url", return_value="https://bot.example"),
        ):
            links = await self._create()
            _, auth = await self.service.claim(links.presenter_url.split("#", 1)[1])
            ready = await self.service.mark_ready(auth)
            shares = await self.service.admin_active_shares()
            refreshed = await self.service.admin_active_shares()
        self.assertEqual(len(shares), 1)
        self.assertEqual(shares[0]["viewer_url"], refreshed[0]["viewer_url"])
        self.assertEqual(
            set(shares[0]),
            {"id", "area", "channel", "presenter_uid", "ready_at", "expires_at", "viewer_url"},
        )
        self.assertTrue(shares[0]["viewer_url"].startswith("https://bot.example/screen-share/w#"))
        admin_viewer_token = shares[0]["viewer_url"].split("#", 1)[1]
        self.assertEqual(
            len([key for key in self.redis.data if key.startswith("screen_share:viewer:")]),
            2,
        )
        with patch("screen_share.service.time.time", return_value=1000):
            await self.service.viewer_credentials(
                admin_viewer_token,
                viewer_instance="admin-tab-1",
            )
        await self.service.stop(ready["session"], reason="test_stop")
        self.assertFalse(
            any(key.startswith("screen_share:viewer:") for key in self.redis.data)
        )
        with self.assertRaises(ScreenShareError):
            await self.service.viewer_credentials(
                admin_viewer_token,
                viewer_instance="admin-tab-1",
            )

    async def test_admin_listing_skips_corrupt_session_records(self) -> None:
        with (
            patch("screen_share.service.time.time", return_value=1000),
            patch("web.web_player_config.display_web_base_url", return_value="https://bot.example"),
        ):
            links = await self._create()
            _, auth = await self.service.claim(links.presenter_url.split("#", 1)[1])
            await self.service.mark_ready(auth)
            await self.redis.set("screen_share:session:corrupt", "not-json", ex=300)
            with self.assertLogs("screen_share.service", level="WARNING"):
                shares = await self.service.admin_active_shares()
        self.assertEqual(len(shares), 1)

    async def test_role_permission_is_area_scoped_and_fail_closed(self) -> None:
        sender = SimpleNamespace(
            get_joined_areas=AsyncMock(return_value=[{"id": "denied-area", "owner": "owner"}]),
            get_user_area_detail=AsyncMock(return_value={"list": [{"roleID": "20"}]}),
        )
        registry = Mock()
        registry.get.side_effect = lambda area: SimpleNamespace(
            screen_share_role_ids=(20,) if area == "allowed-area" else (30,),
        )
        with patch("screen_share.service.get_area_registry", return_value=registry):
            self.assertTrue(await self.service.authorize(sender, user="owner", area="denied-area"))
            self.assertTrue(await self.service.authorize(sender, user="member", area="allowed-area"))
            self.assertFalse(await self.service.authorize(sender, user="member", area="denied-area"))
            sender.get_user_area_detail.return_value = {"error": "lookup failed"}
            self.assertFalse(await self.service.authorize(sender, user="member", area="allowed-area"))
            self.assertTrue(await self.service.authorize(sender, user="admin", area="denied-area", is_bot_admin=True))


class ScreenShareCommandTest(unittest.IsolatedAsyncioTestCase):
    async def test_private_message_contains_only_presenter_link(self) -> None:
        sender = SimpleNamespace(
            send_private_message=AsyncMock(return_value={"ok": True}),
            send_message=AsyncMock(return_value={"ok": True}),
        )
        runtime = SimpleNamespace(
            sender=sender,
            services=SimpleNamespace(
                routing=SimpleNamespace(access=SimpleNamespace(is_admin=Mock(return_value=False)))
            ),
        )
        command = ScreenShareCommandService(cast(Any, runtime))
        service = SimpleNamespace(
            create_session=AsyncMock(
                return_value=SimpleNamespace(
                    session_id="session-1",
                    presenter_url="https://example.test/screen-share/p#presenter-secret",
                )
            ),
        )
        with patch(
            "app.services.interaction.screen_share_command_service.get_screen_share_service",
            return_value=service,
        ):
            await command.start("channel", "area", "user")
        private_message = sender.send_private_message.await_args.args[1]
        self.assertIn("发起端专用链接", private_message)
        self.assertIn("/screen-share/p#presenter-secret", private_message)
        public_messages = [call.args[0] for call in sender.send_message.await_args_list]
        self.assertFalse(any("presenter-secret" in message for message in public_messages))

    async def test_private_message_failure_destroys_session(self) -> None:
        sender = SimpleNamespace(
            send_private_message=AsyncMock(return_value={"error": "disabled"}),
            send_message=AsyncMock(return_value={"ok": True}),
        )
        runtime = SimpleNamespace(
            sender=sender,
            services=SimpleNamespace(
                routing=SimpleNamespace(access=SimpleNamespace(is_admin=Mock(return_value=False)))
            )
        )
        command = ScreenShareCommandService(cast(Any, runtime))
        service = SimpleNamespace(
            create_session=AsyncMock(return_value=SimpleNamespace(
                session_id="session-1",
                presenter_url="https://example.test/p#secret",
            )),
            stop_by_id=AsyncMock(return_value={"status": "pending"}),
        )
        with patch(
            "app.services.interaction.screen_share_command_service.get_screen_share_service",
            return_value=service,
        ):
            await command.start("channel", "area", "user")
        service.stop_by_id.assert_awaited_once_with(
            "session-1",
            reason="private_message_failed",
        )
        public_messages = [call.args[0] for call in sender.send_message.await_args_list]
        self.assertFalse(any("secret" in message for message in public_messages))

    async def test_unexpected_backend_error_is_not_exposed_in_channel(self) -> None:
        sender = SimpleNamespace(send_message=AsyncMock(return_value={"ok": True}))
        runtime = SimpleNamespace(
            sender=sender,
            services=SimpleNamespace(
                routing=SimpleNamespace(access=SimpleNamespace(is_admin=Mock(return_value=False)))
            ),
        )
        command = ScreenShareCommandService(cast(Any, runtime))
        service = SimpleNamespace(
            list_by_channel=AsyncMock(side_effect=RuntimeError("redis details")),
        )
        with patch(
            "app.services.interaction.screen_share_command_service.get_screen_share_service",
            return_value=service,
        ):
            await command.stop("channel", "area", "user")
        message = sender.send_message.await_args.args[0]
        self.assertIn("服务暂时不可用", message)
        self.assertNotIn("redis details", message)

    async def test_stop_command_only_stops_presenters_own_share(self) -> None:
        sender = SimpleNamespace(
            send_message=AsyncMock(return_value={"ok": True}),
            recall_message=AsyncMock(return_value={"status": True}),
        )
        runtime = SimpleNamespace(
            sender=sender,
            services=SimpleNamespace(
                routing=SimpleNamespace(access=SimpleNamespace(is_admin=Mock(return_value=False)))
            ),
        )
        own = {
            "id": "own",
            "presenter_uid": "user",
            "status": "active",
            "area": "area",
            "channel": "channel",
            "viewer_message_id": "viewer-message",
            "viewer_message_timestamp": "viewer-timestamp",
        }
        other = {"id": "other", "presenter_uid": "other-user", "status": "active"}
        service = SimpleNamespace(
            list_by_channel=AsyncMock(return_value=[other, own]),
            stop=AsyncMock(return_value=own),
            authorize=AsyncMock(return_value=False),
        )
        command = ScreenShareCommandService(cast(Any, runtime))
        with patch(
            "app.services.interaction.screen_share_command_service.get_screen_share_service",
            return_value=service,
        ), patch(
            "app.services.interaction.screen_share_command_service.presenter_label",
            AsyncMock(return_value="当前用户"),
        ):
            await command.stop("channel", "area", "user")
        service.stop.assert_awaited_once_with(own, reason="command_stop_self")
        service.authorize.assert_not_awaited()
        sender.recall_message.assert_awaited_once_with(
            "viewer-message",
            area="area",
            channel="channel",
            timestamp="viewer-timestamp",
        )
        self.assertEqual(
            sender.send_message.await_args.args[0],
            "当前用户 的屏幕共享已结束",
        )

    async def test_authorized_non_presenter_stops_all_channel_shares(self) -> None:
        sender = SimpleNamespace(send_message=AsyncMock(return_value={"ok": True}))
        runtime = SimpleNamespace(
            sender=sender,
            services=SimpleNamespace(
                routing=SimpleNamespace(access=SimpleNamespace(is_admin=Mock(return_value=True)))
            ),
        )
        sessions = [
            {"id": "one", "presenter_uid": "u1", "status": "active"},
            {"id": "two", "presenter_uid": "u2", "status": "active"},
        ]
        service = SimpleNamespace(
            list_by_channel=AsyncMock(return_value=sessions),
            stop=AsyncMock(side_effect=sessions),
            authorize=AsyncMock(return_value=True),
        )
        command = ScreenShareCommandService(cast(Any, runtime))
        with patch(
            "app.services.interaction.screen_share_command_service.get_screen_share_service",
            return_value=service,
        ):
            await command.stop("channel", "area", "admin")
        self.assertEqual(service.stop.await_count, 2)
        self.assertIn("2 个屏幕共享", sender.send_message.await_args.args[0])


class ScreenShareAssetContractTest(unittest.TestCase):
    def test_certificate_snapshot_is_masked_and_role_ids_are_normalized(self) -> None:
        from core.area_config import AreaConfig
        from web.web_player_config import SCREEN_SHARE_CONFIG, config_snapshot

        with patch.dict(
            SCREEN_SHARE_CONFIG,
            {**CONFIG, "agora_app_certificate": CERTIFICATE},
            clear=True,
        ):
            snapshot = config_snapshot()["screen_share"]
        self.assertEqual(snapshot["agora_app_certificate"], "")
        self.assertTrue(snapshot["agora_app_certificate_configured"])
        cfg = AreaConfig.from_dict(
            "area",
            {"screen_share_role_ids": ["20", 10, "20", 0, "bad"]},
        )
        self.assertEqual(cfg.screen_share_role_ids, (10, 20))

    def test_admin_route_adds_area_channel_and_presenter_names(self) -> None:
        shares = [{
            "area": "area-1",
            "channel": "channel-1",
            "presenter_uid": "user-1",
            "viewer_url": "https://example.test/screen-share/w#token",
        }]
        service = SimpleNamespace(admin_active_shares=AsyncMock(return_value=shares))
        resolver = SimpleNamespace(
            ensure_users=AsyncMock(return_value={"user-1": "小明"}),
            area=Mock(return_value="测试域"),
            channel=Mock(return_value="大厅"),
            user=Mock(return_value="user-1"),
        )

        async def run_route():
            with (
                patch.object(admin_screen_share, "get_screen_share_service", return_value=service),
                patch.object(admin_screen_share, "get_resolver", return_value=resolver),
            ):
                return await admin_screen_share.admin_screen_shares()

        response = asyncio.run(run_route())
        payload = json.loads(bytes(response.body).decode("utf-8"))
        self.assertEqual(payload["shares"][0]["area_name"], "测试域")
        self.assertEqual(payload["shares"][0]["channel_name"], "大厅")
        self.assertEqual(payload["shares"][0]["presenter_name"], "小明")

    def test_admin_route_falls_back_when_user_resolution_fails(self) -> None:
        shares = [{
            "area": "area-1",
            "channel": "channel-1",
            "presenter_uid": "user-1234567890",
            "viewer_url": "https://example.test/screen-share/w#token",
        }]
        service = SimpleNamespace(admin_active_shares=AsyncMock(return_value=shares))
        resolver = SimpleNamespace(
            ensure_users=AsyncMock(side_effect=RuntimeError("gateway unavailable")),
            area=Mock(return_value=""),
            channel=Mock(return_value=""),
            user=Mock(return_value="user…890"),
        )

        async def run_route():
            with (
                patch.object(admin_screen_share, "get_screen_share_service", return_value=service),
                patch.object(admin_screen_share, "get_resolver", return_value=resolver),
            ):
                return await admin_screen_share.admin_screen_shares()

        response = asyncio.run(run_route())
        payload = json.loads(bytes(response.body).decode("utf-8"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["shares"][0]["presenter_name"], "user…890")

    def test_admin_and_viewer_routes_hide_unexpected_backend_errors(self) -> None:
        failing_service = SimpleNamespace(
            admin_active_shares=AsyncMock(side_effect=RuntimeError("redis details")),
            viewer_credentials=AsyncMock(side_effect=RuntimeError("redis details")),
            stop_by_id=AsyncMock(side_effect=RuntimeError("redis details")),
        )
        viewer_request = SimpleNamespace(
            json=AsyncMock(return_value={"token": "viewer", "viewer_instance": "tab"}),
        )

        async def run_routes():
            with (
                patch.object(
                    admin_screen_share,
                    "get_screen_share_service",
                    return_value=failing_service,
                ),
                patch.object(
                    screen_share_web,
                    "get_screen_share_service",
                    return_value=failing_service,
                ),
            ):
                return (
                    await admin_screen_share.admin_screen_shares(),
                    await screen_share_web.viewer_token(cast(Any, viewer_request)),
                    await admin_screen_share.admin_stop_screen_share(
                        "session-abcdefghijkl",
                    ),
                )

        admin_response, viewer_response, stop_response = asyncio.run(run_routes())
        for response in (admin_response, viewer_response, stop_response):
            payload = json.loads(bytes(response.body).decode("utf-8"))
            self.assertEqual(response.status_code, 503)
            self.assertEqual(payload["code"], "screen_share_unavailable")
            self.assertNotIn("redis details", payload["error"])

    def test_admin_can_stop_one_share_and_announce_it(self) -> None:
        session_id = "session-abcdefghijkl"
        session = {
            "id": session_id,
            "status": "active",
            "area": "area-1",
            "channel": "channel-1",
            "presenter_uid": "user-1",
        }
        service = SimpleNamespace(stop_by_id=AsyncMock(return_value=session))
        announce = AsyncMock()

        async def run_route():
            with (
                patch.object(
                    admin_screen_share,
                    "get_screen_share_service",
                    return_value=service,
                ),
                patch.object(admin_screen_share, "announce_ended", announce),
            ):
                return await admin_screen_share.admin_stop_screen_share(session_id)

        response = asyncio.run(run_route())
        payload = json.loads(bytes(response.body).decode("utf-8"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["session_id"], session_id)
        service.stop_by_id.assert_awaited_once_with(session_id, reason="admin_stop")
        announce.assert_awaited_once_with(session)

    def test_admin_stop_returns_not_found_for_ended_share(self) -> None:
        service = SimpleNamespace(stop_by_id=AsyncMock(return_value=None))

        async def run_route():
            with patch.object(
                admin_screen_share,
                "get_screen_share_service",
                return_value=service,
            ):
                return await admin_screen_share.admin_stop_screen_share(
                    "session-abcdefghijkl",
                )

        response = asyncio.run(run_route())
        payload = json.loads(bytes(response.body).decode("utf-8"))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(payload["code"], "session_not_found")

    def test_channel_announcements_include_presenter_name(self) -> None:
        session = {
            "id": "session-1",
            "status": "active",
            "area": "area-1",
            "channel": "channel-1",
            "presenter_uid": "user-1",
            "viewer_message_id": "viewer-message",
            "viewer_message_timestamp": "viewer-timestamp",
        }
        sender = SimpleNamespace(
            send_message=AsyncMock(return_value={
                "status": True,
                "data": {
                    "messageId": "viewer-message",
                    "timestamp": "viewer-timestamp",
                },
            }),
            recall_message=AsyncMock(return_value={"status": True}),
        )
        service = SimpleNamespace(
            mark_ready=AsyncMock(return_value={
                "session": session,
                "first_ready": True,
                "viewer_token": "viewer-token",
            }),
            record_viewer_message=AsyncMock(return_value=True),
        )
        request = SimpleNamespace(cookies={screen_share_web.PRESENTER_COOKIE_NAME: "auth"})

        async def run_announcements():
            with (
                patch.object(screen_share_web, "get_screen_share_service", return_value=service),
                patch.object(screen_share_web, "presenter_label", AsyncMock(return_value="小明")),
                patch("web.web_player.get_sender", return_value=sender),
                patch("web.web_player_config.display_web_base_url", return_value="https://example.test"),
            ):
                response = await screen_share_web.presenter_ready(cast(Any, request))
                await screen_share_web.announce_ended(session)
                return response

        response = asyncio.run(run_announcements())
        self.assertEqual(response.status_code, 200)
        messages = [call.args[0] for call in sender.send_message.await_args_list]
        self.assertEqual(messages[0], "小明 的屏幕共享已开始，点击观看：https://example.test/screen-share/w#viewer-token")
        self.assertEqual(messages[1], "小明 的屏幕共享已结束")
        service.record_viewer_message.assert_awaited_once_with(
            "session-1",
            message_id="viewer-message",
            timestamp="viewer-timestamp",
        )
        for call in sender.send_message.await_args_list:
            self.assertNotIn("styleTags", call.kwargs)
        started, ended = sender.send_message.await_args_list
        self.assertIs(started.kwargs["auto_recall"], False)
        self.assertIsNot(ended.kwargs.get("auto_recall"), False)
        sender.recall_message.assert_awaited_once_with(
            "viewer-message",
            area="area-1",
            channel="channel-1",
            timestamp="viewer-timestamp",
        )

    def test_browser_source_covers_capture_mix_renew_and_stop(self) -> None:
        source = (
            REPO_ROOT / "src" / "screen_share" / "client" / "app.ts"
        ).read_text(encoding="utf-8")
        page = (REPO_ROOT / "src" / "web" / "assets" / "screen-share" / "index.html").read_text(encoding="utf-8")
        style = (REPO_ROOT / "src" / "web" / "assets" / "screen-share" / "style.css").read_text(encoding="utf-8")
        web_source = (REPO_ROOT / "src" / "screen_share" / "web.py").read_text(encoding="utf-8")
        for marker in (
            "createScreenVideoTrack",
            '"auto"',
            "upgradeSelect(qualitySelect)",
            'className = "cs-dropdown"',
            "token-privilege-will-expire",
            "token-privilege-did-expire",
            "Token 续期暂时失败",
            "/screen-share/api/presenter/heartbeat",
            'screenVideo.on("track-ended"',
            "onAutoplayFailed",
            "超过 60 秒仍未恢复时会结束共享",
        ):
            self.assertIn(marker, source)
        self.assertIn('id="frame-rate"', page)
        self.assertIn('value="2k"', page)
        self.assertIn('value="60"', page)
        self.assertIn('value="120"', page)
        self.assertIn('value="144"', page)
        self.assertIn('value="240"', page)
        self.assertIn("return [2560, 1440]", source)
        self.assertIn("[30, 60, 120, 144, 240]", source)
        self.assertIn("frameRate: { max: frameRate }", source)
        self.assertIn("getMediaStreamTrack().getSettings()", source)
        self.assertIn("setEncoderConfiguration(screenEncoder(sourceWidth, sourceHeight))", source)
        self.assertEqual(source.count('mode: "live"'), 2)
        self.assertIn('setClientRole("host")', source)
        self.assertIn('setClientRole("audience")', source)
        self.assertNotIn('mode: "rtc"', source)
        self.assertIn("viewer_instance: viewerInstanceId", source)
        self.assertIn('id="fullscreen"', page)
        self.assertIn('id="viewer-controls"', page)
        self.assertNotIn('history.replaceState({}, "", "/screen-share/w")', source)
        self.assertEqual(page.count('class="quality" hidden'), 2)
        self.assertIn('id="start" class="btn btn-primary primary" type="button" hidden', page)
        self.assertIn('id="control-panel" hidden', page)
        self.assertIn('id="panel-bar" hidden', page)
        self.assertIn('[hidden] { display: none !important; }', style)
        self.assertIn('body[data-mode="viewer"] .app-shell', style)
        self.assertIn('body[data-mode="viewer"] .stage { aspect-ratio: auto;', style)
        self.assertIn("expire_stale(heartbeat_timeout=60)", web_source)
        config_script = (
            REPO_ROOT / "src" / "web" / "assets" / "admin" / "pages" / "config_script.js"
        ).read_text(encoding="utf-8")
        config_page = (
            REPO_ROOT / "src" / "web" / "assets" / "admin" / "pages" / "config_content.html"
        ).read_text(encoding="utf-8")
        admin_share_script = (
            REPO_ROOT / "src" / "web" / "assets" / "admin" / "pages" / "screen-share_script.js"
        ).read_text(encoding="utf-8")
        admin_share_page = (
            REPO_ROOT / "src" / "web" / "assets" / "admin" / "pages" / "screen-share_content.html"
        ).read_text(encoding="utf-8")
        admin_shell = (
            REPO_ROOT / "src" / "web" / "assets" / "admin" / "admin-shell.js"
        ).read_text(encoding="utf-8")
        self.assertIn('AdminShell.upgradeSelect("cfg_screen_share_quality")', config_script)
        self.assertNotIn("当前屏幕共享", config_page)
        self.assertIn('id="screenShareSessions"', admin_share_page)
        self.assertIn("同一文字频道支持多人同时共享", admin_share_page)
        self.assertNotIn("不同文字频道可同时进行共享", admin_share_page)
        self.assertIn('/admin/api/screen-shares', admin_share_script)
        self.assertIn('data-action="stop-screen-share"', admin_share_script)
        self.assertIn('/screen-shares/" + encodeURIComponent(sessionId) + "/stop', admin_share_script)
        self.assertIn('href: "/admin/screen-share"', admin_shell)
        self.assertIn('grid-template-columns: minmax(0, 1fr) 350px', style)
        self.assertIn('/admin-assets/admin-shell.css', page)
        self.assertIn('/screen-share/assets/style.css?v=', page)
        self.assertIn('/screen-share/assets/app.js?v=', page)
        self.assertIn('--accent: #e8b44d', style)
        self.assertIn('body[data-mode="presenter"] .viewer-controls { display: none !important; }', style)
        self.assertIn('microphone=()', web_source)
        self.assertNotIn('id="audio-mode"', page)
        self.assertNotIn("createMicrophoneAudioTrack", source)
        self.assertNotIn("createCustomAudioTrack", source)
        self.assertNotIn("new AudioContext", source)
        self.assertNotIn("createMediaStreamDestination", source)
        self.assertNotIn("麦克风", page + source)
        self.assertNotIn('LIVE', page + source)
        self.assertNotIn('直播', page + source)
        self.assertIn('if (presenterPage) return;', source)
        self.assertNotIn("agora_app_certificate", source)


if __name__ == "__main__":
    unittest.main()
