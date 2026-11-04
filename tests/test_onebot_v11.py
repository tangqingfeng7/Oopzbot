
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import sqlite3
import sys
import tempfile
import unittest
import warnings
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

from aiohttp import ClientSession, WSServerHandshakeError, web

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from oopz_sdk.adapters.onebot.v11.adapter import OneBotV11Adapter  # noqa: E402
from oopz_sdk.adapters.onebot.v11.server import (  # noqa: E402
    OneBotV11Server,
    OneBotV11ServerConfig,
)
from oopz_sdk.adapters.onebot.v11.types import (  # noqa: E402
    IdStore,
    make_group_source,
    make_message_source,
    make_user_source,
    parse_group_source,
    parse_message_source,
    parse_user_source,
)
from oopz_sdk.client.bot import OopzBot  # noqa: E402

from core.onebot_migration import (  # noqa: E402
    SDK_BACKUP_SUFFIX,
    migrate_onebot_v11_database,
)


def _listen_port(server: Any) -> int:
    """从 aiohttp 站点拿实际监听端口。

    `_server` 静态类型是 `AbstractServer`，没有 `sockets`；运行时是
    `asyncio.Server`，确有该属性。
    """
    return server.sockets[0].getsockname()[1]


# SDK v0.16.0 的同步 IdStore/MessageStore 在 Python 3.14 会由 sqlite3 报告
# ResourceWarning；项目使用安装版 SDK，因此测试仅屏蔽这一条上游告警。
warnings.filterwarnings("ignore", message="unclosed database.*", category=ResourceWarning)


def _fake_bot() -> SimpleNamespace:
    messages = SimpleNamespace(
        send_message=AsyncMock(
            return_value=SimpleNamespace(message_id="oopz-group-message", timestamp="1770000000000000")
        ),
        send_private_message=AsyncMock(
            return_value=SimpleNamespace(message_id="oopz-private-message", timestamp="1770000000000000")
        ),
        recall_message=AsyncMock(return_value=SimpleNamespace(ok=True, message="")),
        recall_private_message=AsyncMock(return_value=SimpleNamespace(ok=True, message="")),
    )
    person = SimpleNamespace(
        get_self_detail=AsyncMock(return_value=SimpleNamespace(name="机器人", model_dump=lambda: {})),
        get_person_detail_full=AsyncMock(return_value=SimpleNamespace(name="用户", model_dump=lambda: {})),
        get_person_info=AsyncMock(return_value=SimpleNamespace(name="用户")),
        get_friendship=AsyncMock(return_value=[]),
    )
    areas = SimpleNamespace(get_joined_areas=AsyncMock(return_value=[]))
    channels = SimpleNamespace(get_channel_setting_info=AsyncMock(return_value=SimpleNamespace(name="公屏")))
    return SimpleNamespace(messages=messages, person=person, areas=areas, channels=channels)


class _ServerAdapter:
    def __init__(self) -> None:
        self.self_id = 10001
        self.sinks: list = []
        self.calls: list[tuple[str, dict]] = []

    def add_event_sink(self, sink) -> None:
        self.sinks.append(sink)

    def remove_event_sink(self, sink) -> None:
        if sink in self.sinks:
            self.sinks.remove(sink)

    async def call_action(self, action, params=None, *, echo=None):
        params = dict(params or {})
        self.calls.append((str(action), params))
        if action == "missing":
            return {"status": "failed", "retcode": 1404, "data": None, "message": "missing"}
        response = {"status": "ok", "retcode": 0, "data": {"action": action, "params": params}, "message": ""}
        if echo is not None:
            response["echo"] = echo
        return response

    async def call_action_payload(self, payload):
        return await self.call_action(
            payload.get("action"),
            payload.get("params") or {},
            echo=payload.get("echo"),
        )

    async def emit(self, payload: dict) -> None:
        for sink in list(self.sinks):
            result = sink(payload)
            if asyncio.iscoroutine(result):
                await result


class OneBotSdkAdapterTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "onebot.sqlite3"
        self.bot = _fake_bot()
        self.adapter = OneBotV11Adapter(cast("OopzBot", self.bot), "bot-uid", db_path=self.db_path)

    async def asyncTearDown(self) -> None:
        self.temp_dir.cleanup()

    async def test_id_mapping_is_stable(self) -> None:
        first = self.adapter.ids.createId(make_group_source(area="area-1", channel="channel-1"))
        second = self.adapter.ids.createId(make_group_source(area="area-1", channel="channel-1"))
        self.assertEqual(first.number, second.number)
        self.assertEqual(first.source, "group:area-1:channel-1")

    async def test_id_source_round_trips(self) -> None:
        self.assertEqual(parse_user_source(make_user_source("user-1")), "user-1")
        self.assertEqual(parse_group_source(make_group_source(area="area-1", channel="channel-1")), ("area-1", "channel-1"))
        source = make_message_source(area="area-1", channel="channel-1", message_id="message-1")
        self.assertEqual(parse_message_source(source), ("area-1", "channel-1", "", "message-1"))

    async def test_get_status_action(self) -> None:
        response = await self.adapter.call_action("get_status")
        self.assertEqual(response["status"], "ok")
        self.assertEqual(response["data"], {"online": True, "good": True})

    async def test_unknown_action_fails(self) -> None:
        response = await self.adapter.call_action("does_not_exist")
        self.assertEqual(response["retcode"], 1404)

    async def test_payload_preserves_echo(self) -> None:
        response = await self.adapter.call_action_payload({"action": "get_status", "params": {}, "echo": "e-1"})
        self.assertEqual(response["echo"], "e-1")

    async def test_send_group_msg_uses_sdk_messages(self) -> None:
        group_id = self.adapter.ids.createId(make_group_source(area="area-1", channel="channel-1")).number
        response = await self.adapter.call_action("send_group_msg", {"group_id": group_id, "message": "hello"})
        self.assertEqual(response["status"], "ok")
        self.assertIsInstance(response["data"]["message_id"], int)
        self.bot.messages.send_message.assert_awaited_once()
        self.assertEqual(self.bot.messages.send_message.await_args.kwargs["area"], "area-1")
        self.assertEqual(self.bot.messages.send_message.await_args.kwargs["channel"], "channel-1")

    async def test_send_private_msg_resolves_sdk_user(self) -> None:
        user_id = self.adapter.ids.createId(make_user_source("user-1")).number
        response = await self.adapter.call_action("send_private_msg", {"user_id": user_id, "message": "hello"})
        self.assertEqual(response["status"], "ok")
        self.bot.messages.send_private_message.assert_awaited_once()
        self.assertEqual(self.bot.messages.send_private_message.await_args.kwargs["target"], "user-1")

    async def test_delete_msg_uses_saved_mapping(self) -> None:
        group_id = self.adapter.ids.createId(make_group_source(area="area-1", channel="channel-1")).number
        sent = await self.adapter.call_action("send_group_msg", {"group_id": group_id, "message": "hello"})
        message_id = sent["data"]["message_id"]
        deleted = await self.adapter.call_action("delete_msg", {"message_id": message_id})
        self.assertEqual(deleted["status"], "ok")
        self.bot.messages.recall_message.assert_awaited_once()
        self.assertEqual(self.bot.messages.recall_message.await_args.kwargs["message_id"], "oopz-group-message")

    async def test_get_msg_returns_sent_mapping(self) -> None:
        group_id = self.adapter.ids.createId(make_group_source(area="area-1", channel="channel-1")).number
        sent = await self.adapter.call_action("send_group_msg", {"group_id": group_id, "message": "hello"})
        response = await self.adapter.call_action("get_msg", {"message_id": sent["data"]["message_id"]})
        self.assertEqual(response["data"]["message_type"], "group")
        self.assertEqual(response["data"]["group_id"], group_id)

    async def test_supported_actions_include_core_message_actions(self) -> None:
        response = await self.adapter.call_action("get_supported_actions")
        self.assertIn("get_msg", response["data"])
        self.assertIn("send_group_msg", response["data"])



class OneBotMigrationTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "onebot.sqlite3"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _create_legacy(self, *, malformed_messages: bool = False) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "CREATE TABLE onebot_v11_id_map (source TEXT NOT NULL UNIQUE, number INTEGER NOT NULL UNIQUE, created_at INTEGER NOT NULL)"
            )
            connection.execute(
                "INSERT INTO onebot_v11_id_map(source, number, created_at) VALUES ('user:user-1', 12345, 100)"
            )
            raw_column = "" if malformed_messages else ", raw TEXT NOT NULL DEFAULT '{}'"
            connection.execute(
                "CREATE TABLE onebot_v11_messages ("
                "ob_message_id TEXT PRIMARY KEY, oopz_message_id TEXT NOT NULL, detail_type TEXT NOT NULL, "
                "area TEXT NOT NULL DEFAULT '', channel TEXT NOT NULL DEFAULT '', target TEXT NOT NULL DEFAULT '', "
                f"user_id TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL{raw_column})"
            )
            columns = "ob_message_id, oopz_message_id, detail_type, area, channel, target, user_id, created_at"
            values = "'88', 'oopz-88', 'group', 'area-1', 'channel-1', '', 'user-1', 100"
            if not malformed_messages:
                columns += ", raw"
                values += ", '{\"message\": \"hello\"}'"
            connection.execute(f"INSERT INTO onebot_v11_messages({columns}) VALUES ({values})")
            connection.commit()

    async def test_missing_database_is_not_created(self) -> None:
        result = await migrate_onebot_v11_database(self.path)
        self.assertIsNone(result)
        self.assertFalse(self.path.exists())

    async def test_sdk_schema_needs_no_backup(self) -> None:
        IdStore(self.path)
        result = await migrate_onebot_v11_database(self.path)
        self.assertIsNone(result)
        self.assertFalse(Path(str(self.path) + SDK_BACKUP_SUFFIX).exists())

    async def test_legacy_ids_are_migrated_and_backed_up(self) -> None:
        self._create_legacy()
        backup = await migrate_onebot_v11_database(self.path)
        self.assertEqual(backup, Path(str(self.path) + SDK_BACKUP_SUFFIX))
        assert backup is not None
        self.assertTrue(backup.is_file())
        with sqlite3.connect(self.path) as connection:
            row = connection.execute("SELECT string, number, source FROM onebot_v11_id_map").fetchone()
        self.assertEqual(row, ("user:user-1", 12345, "user:user-1"))

    async def test_legacy_messages_are_migrated(self) -> None:
        self._create_legacy()
        await migrate_onebot_v11_database(self.path)
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT ob_message_id, oopz_message_id, raw_json FROM message_map WHERE ob_message_id='88'"
            ).fetchone()
            old_table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='onebot_v11_messages'"
            ).fetchone()
        self.assertEqual(row, ("88", "oopz-88", '{"message": "hello"}'))
        self.assertIsNone(old_table)

    async def test_existing_backup_is_never_overwritten(self) -> None:
        self._create_legacy()
        backup = await migrate_onebot_v11_database(self.path)
        assert backup is not None
        original = backup.read_bytes()
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "CREATE TABLE onebot_v11_messages (ob_message_id TEXT PRIMARY KEY, oopz_message_id TEXT NOT NULL, "
                "detail_type TEXT NOT NULL, area TEXT NOT NULL DEFAULT '', channel TEXT NOT NULL DEFAULT '', "
                "target TEXT NOT NULL DEFAULT '', user_id TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL, "
                "raw TEXT NOT NULL DEFAULT '{}')"
            )
            connection.commit()
        await migrate_onebot_v11_database(self.path)
        self.assertEqual(backup.read_bytes(), original)

    async def test_second_migration_is_noop(self) -> None:
        self._create_legacy()
        await migrate_onebot_v11_database(self.path)
        self.assertIsNone(await migrate_onebot_v11_database(self.path))

    async def test_failed_migration_rolls_back_and_raises(self) -> None:
        self._create_legacy(malformed_messages=True)
        with self.assertRaises(sqlite3.OperationalError):
            await migrate_onebot_v11_database(self.path)
        with sqlite3.connect(self.path) as connection:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(onebot_v11_id_map)")}
            legacy_messages = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='onebot_v11_messages'"
            ).fetchone()
            message_map = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='message_map'"
            ).fetchone()
        self.assertIn("source", columns)
        self.assertNotIn("string", columns)
        self.assertIsNotNone(legacy_messages)
        self.assertIsNone(message_map)


class OneBotServerTest(unittest.IsolatedAsyncioTestCase):
    async def _start_server(self, **overrides):
        adapter = _ServerAdapter()
        values = {
            "host": "127.0.0.1",
            "port": 0,
            "enable_http": True,
            "enable_ws": True,
            "enable_http_post": False,
            "enable_ws_reverse": False,
            "send_connect_event": True,
        }
        values.update(overrides)
        server = OneBotV11Server(adapter, OneBotV11ServerConfig(**values))
        await server.start()
        port = _listen_port(server.site._server) if server.site is not None else 0
        self.addAsyncCleanup(server.stop)
        return adapter, server, f"http://127.0.0.1:{port}"

    async def _start_app(self, handler, path: str = "/"):
        app = web.Application()
        app.router.add_route("*", path, handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = _listen_port(site._server)
        self.addAsyncCleanup(runner.cleanup)
        return f"http://127.0.0.1:{port}{path}"

    async def test_http_auth_distinguishes_missing_and_wrong_token(self) -> None:
        _adapter, _server, base = await self._start_server(access_token="secret")
        async with ClientSession() as session:
            self.assertEqual((await session.get(f"{base}/get_status")).status, 401)
            self.assertEqual(
                (await session.get(f"{base}/get_status", headers={"Authorization": "Bearer wrong"})).status,
                403,
            )
            response = await session.get(f"{base}/get_status", headers={"Authorization": "Bearer secret"})
            self.assertEqual(response.status, 200)

    async def test_http_get_action_passes_query(self) -> None:
        adapter, _server, base = await self._start_server()
        async with ClientSession() as session:
            response = await session.get(f"{base}/echo", params={"name": "value"})
            payload = await response.json()
        self.assertEqual(payload["data"]["params"], {"name": "value"})
        self.assertEqual(adapter.calls[-1], ("echo", {"name": "value"}))

    async def test_http_post_json_action(self) -> None:
        _adapter, _server, base = await self._start_server()
        async with ClientSession() as session:
            response = await session.post(f"{base}/echo", json={"value": 3})
            payload = await response.json()
        self.assertEqual(payload["data"]["params"], {"value": 3})

    async def test_http_post_form_action(self) -> None:
        _adapter, _server, base = await self._start_server()
        async with ClientSession() as session:
            response = await session.post(f"{base}/echo/", data={"value": "3"})
            payload = await response.json()
        self.assertEqual(payload["data"]["params"], {"value": "3"})

    async def test_http_invalid_json_is_400(self) -> None:
        _adapter, _server, base = await self._start_server()
        async with ClientSession() as session:
            response = await session.post(
                f"{base}/echo", data="{", headers={"Content-Type": "application/json"}
            )
        self.assertEqual(response.status, 400)

    async def test_http_unsupported_content_type_is_406(self) -> None:
        _adapter, _server, base = await self._start_server()
        async with ClientSession() as session:
            response = await session.post(f"{base}/echo", data="value", headers={"Content-Type": "text/plain"})
        self.assertEqual(response.status, 406)

    async def test_http_unknown_action_is_404(self) -> None:
        _adapter, _server, base = await self._start_server()
        async with ClientSession() as session:
            response = await session.get(f"{base}/missing")
        self.assertEqual(response.status, 404)

    async def test_forward_api_websocket_executes_action(self) -> None:
        _adapter, _server, base = await self._start_server()
        async with (
            ClientSession() as session,
            session.ws_connect(base.replace("http://", "ws://") + "/api") as socket,
        ):
            await socket.send_json({"action": "get_status", "params": {}, "echo": "ws-1"})
            payload = await socket.receive_json(timeout=1)
        self.assertEqual(payload["echo"], "ws-1")
        self.assertEqual(payload["data"]["action"], "get_status")

    async def test_forward_event_websocket_receives_connect_and_event(self) -> None:
        adapter, _server, base = await self._start_server()
        async with (
            ClientSession() as session,
            session.ws_connect(base.replace("http://", "ws://") + "/event") as socket,
        ):
            connect = await socket.receive_json(timeout=1)
            await adapter.emit({"post_type": "notice", "notice_type": "group_increase"})
            event = await socket.receive_json(timeout=1)
        self.assertEqual(connect["meta_event_type"], "lifecycle")
        self.assertEqual(event["notice_type"], "group_increase")

    async def test_forward_universal_websocket_handles_action_and_event(self) -> None:
        adapter, _server, base = await self._start_server()
        async with (
            ClientSession() as session,
            session.ws_connect(base.replace("http://", "ws://") + "/") as socket,
        ):
            await socket.receive_json(timeout=1)
            await socket.send_json({"action": "echo", "params": {"x": 1}, "echo": 9})
            action = await socket.receive_json(timeout=1)
            await adapter.emit({"post_type": "meta_event", "meta_event_type": "heartbeat"})
            event = await socket.receive_json(timeout=1)
        self.assertEqual(action["echo"], 9)
        self.assertEqual(event["meta_event_type"], "heartbeat")

    async def test_forward_websocket_rejects_bad_token(self) -> None:
        _adapter, _server, base = await self._start_server(access_token="secret")
        async with ClientSession() as session:
            with self.assertRaises(WSServerHandshakeError) as raised:
                await session.ws_connect(base.replace("http://", "ws://") + "/api?access_token=wrong")
        self.assertEqual(raised.exception.status, 403)

    async def test_http_post_reports_event_with_signature(self) -> None:
        received: asyncio.Future = asyncio.get_running_loop().create_future()

        async def receive(request: web.Request):
            body = await request.read()
            received.set_result((body, dict(request.headers)))
            return web.Response(status=204)

        target = await self._start_app(receive, "/events")
        adapter, server, _base = await self._start_server(
            enable_http=False,
            enable_ws=False,
            enable_http_post=True,
            http_post_urls=[target],
            secret="signing-secret",
        )
        event = {"post_type": "notice", "notice_type": "group_increase"}
        await adapter.emit(event)
        body, headers = await asyncio.wait_for(received, timeout=1)
        expected = hmac.new(b"signing-secret", body, hashlib.sha1).hexdigest()
        self.assertEqual(json.loads(body), event)
        self.assertEqual(headers["X-Signature"], f"sha1={expected}")
        await server.stop()

    async def test_http_post_quick_operation_calls_actions(self) -> None:
        async def receive(_request: web.Request):
            return web.json_response({"reply": "pong", "delete": True})

        target = await self._start_app(receive, "/events")
        adapter, _server, _base = await self._start_server(
            enable_http=False,
            enable_ws=False,
            enable_http_post=True,
            http_post_urls=[target],
        )
        await adapter.emit({"post_type": "message", "message_type": "group", "group_id": 7, "message_id": 8})
        self.assertIn(("send_group_msg", {"group_id": 7, "message": "pong", "auto_escape": False}), adapter.calls)
        self.assertIn(("delete_msg", {"message_id": 8}), adapter.calls)

    async def test_reverse_universal_websocket_exchanges_actions_and_events(self) -> None:
        connected = asyncio.Event()
        received: asyncio.Future = asyncio.get_running_loop().create_future()

        async def reverse(request: web.Request):
            socket = web.WebSocketResponse()
            await socket.prepare(request)
            connect = await socket.receive_json(timeout=1)
            await socket.send_json({"action": "echo", "params": {"reverse": True}, "echo": "r-1"})
            action = await socket.receive_json(timeout=1)
            connected.set()
            event = await socket.receive_json(timeout=1)
            if not received.done():
                received.set_result((connect, action, event, dict(request.headers)))
            await socket.close()
            return socket

        http_target = await self._start_app(reverse, "/reverse")
        ws_target = http_target.replace("http://", "ws://")
        adapter, _server, _base = await self._start_server(
            enable_http=False,
            enable_ws=False,
            enable_ws_reverse=True,
            ws_reverse_url=ws_target,
            ws_reverse_reconnect_interval=10,
        )
        await asyncio.wait_for(connected.wait(), timeout=1)
        await adapter.emit({"post_type": "notice", "notice_type": "group_decrease"})
        connect, action, event, headers = await asyncio.wait_for(received, timeout=1)
        self.assertEqual(connect["meta_event_type"], "lifecycle")
        self.assertEqual(action["echo"], "r-1")
        self.assertEqual(event["notice_type"], "group_decrease")
        self.assertEqual(headers["X-Client-Role"], "Universal")

    async def test_reverse_targets_are_deduplicated(self) -> None:
        adapter = _ServerAdapter()
        config = OneBotV11ServerConfig(ws_reverse_url="ws://same", ws_reverse_api_url="ws://same")
        server = OneBotV11Server(adapter, config)
        self.assertEqual(
            server._reverse_targets(),
            [("ws://same", "universal"), ("ws://same", "api")],
        )

    async def test_server_stop_is_idempotent(self) -> None:
        adapter, server, _base = await self._start_server()
        await server.stop()
        await server.stop()
        self.assertEqual(adapter.sinks, [])
