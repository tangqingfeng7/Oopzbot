"""
Oopz WebSocket 客户端
负责与 Oopz 平台的实时通信：连接、认证、心跳、消息接收、自动重连
"""

import json
import time
import threading
from typing import Callable, Optional, Any

import websocket

from config import OOPZ_CONFIG, DEFAULT_HEADERS
from logger_config import get_logger
from name_resolver import get_resolver

logger = get_logger("OopzClient")

OOPZ_WS_URL = "wss://ws.oopz.cn"

# Oopz WebSocket 事件类型
EVENT_SERVER_ID = 1
EVENT_CHAT_MESSAGE = 9
EVENT_AUTH = 253
EVENT_HEARTBEAT = 254


class OopzClient:
    """
    Oopz WebSocket 客户端，支持自动重连。

    用法::

        client = OopzClient(on_chat_message=my_handler)
        client.start()          # 阻塞运行
        # 或
        client.start_async()    # 后台线程运行
    """

    def __init__(
        self,
        on_chat_message: Optional[Callable[[dict], None]] = None,
        on_other_event: Optional[Callable[[int, dict], None]] = None,
        reconnect_interval: float = 5.0,
        heartbeat_interval: float = 10.0,
    ):
        self.on_chat_message = on_chat_message
        self.on_other_event = on_other_event
        self.reconnect_interval = reconnect_interval
        self.heartbeat_interval = heartbeat_interval

        self._person_id = OOPZ_CONFIG["person_uid"]
        self._device_id = OOPZ_CONFIG["device_id"]
        self._jwt_token = OOPZ_CONFIG["jwt_token"]

        self._ws: Optional[websocket.WebSocketApp] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def start(self):
        """阻塞运行（带自动重连）"""
        self._running = True
        while self._running:
            try:
                self._connect_and_run()
            except Exception as e:
                logger.error(f"WebSocket 异常: {e}")

            if self._running:
                logger.info(f"{self.reconnect_interval}s 后重连...")
                time.sleep(self.reconnect_interval)

    def start_async(self):
        """在后台线程中运行"""
        self._thread = threading.Thread(target=self.start, daemon=True)
        self._thread.start()
        return self._thread

    def stop(self):
        """停止客户端"""
        self._running = False
        if self._ws:
            self._ws.close()

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    def _connect_and_run(self):
        """建立一次 WebSocket 连接并持续运行直到断开"""
        ws_headers = {
            "User-Agent": DEFAULT_HEADERS["User-Agent"],
            "Origin": DEFAULT_HEADERS["Origin"],
            "Cache-Control": DEFAULT_HEADERS["Cache-Control"],
            "Accept-Language": DEFAULT_HEADERS["Accept-Language"],
            "Accept-Encoding": DEFAULT_HEADERS["Accept-Encoding"],
        }

        self._ws = websocket.WebSocketApp(
            OOPZ_WS_URL,
            header=ws_headers,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )

        logger.info(f"正在连接 {OOPZ_WS_URL} ...")
        self._ws.run_forever(ping_interval=0, ping_timeout=None)

    # -- WebSocket 回调 --

    def _on_open(self, ws):
        logger.info("WebSocket 连接已建立")
        self._send_auth(ws)
        threading.Thread(target=self._heartbeat_loop, args=(ws,), daemon=True).start()

    def _on_message(self, ws, message: str):
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            logger.warning(f"无法解析消息: {message[:200]}")
            return

        event = data.get("event")

        # 心跳响应
        if event == EVENT_HEARTBEAT:
            body = json.loads(data.get("body", "{}"))
            if body.get("r") == 1:
                self._send_heartbeat(ws)
            return

        # 服务端 serverId 确认
        if event == EVENT_SERVER_ID:
            self._send_heartbeat(ws)
            logger.info("收到 serverId，已发送首次心跳")
            return

        # 聊天消息
        if event == EVENT_CHAT_MESSAGE:
            self._handle_chat(data)
            return

        # 其他事件（如域成员加入/退出等）交给外部处理
        if self.on_other_event:
            try:
                self.on_other_event(event, data)
            except Exception as e:
                logger.debug("on_other_event 处理异常: %s", e)

    def _on_error(self, ws, error):
        logger.error(f"WebSocket 错误: {error}")

    def _on_close(self, ws, code, reason):
        logger.warning(f"连接关闭 (code={code}, reason={reason})")

    # -- 认证 --

    def _send_auth(self, ws):
        auth_body = {
            "person": self._person_id,
            "deviceId": self._device_id,
            "signature": self._jwt_token,
            "deviceName": self._device_id,
            "platformName": "web",
            "reconnect": 0,
        }
        payload = {
            "time": str(int(time.time() * 1000)),
            "body": json.dumps(auth_body),
            "event": EVENT_AUTH,
        }
        ws.send(json.dumps(payload))
        logger.info("已发送认证信息")

    # -- 心跳 --

    def _send_heartbeat(self, ws):
        payload = {
            "time": str(int(time.time() * 1000)),
            "body": json.dumps({"person": self._person_id}),
            "event": EVENT_HEARTBEAT,
        }
        try:
            ws.send(json.dumps(payload))
        except Exception:
            pass

    def _heartbeat_loop(self, ws):
        """定时心跳线程"""
        while self._running:
            time.sleep(self.heartbeat_interval)
            if ws.sock and ws.sock.connected:
                self._send_heartbeat(ws)
            else:
                break

    # -- 聊天消息处理 --

    def _handle_chat(self, data: dict):
        try:
            body = json.loads(data["body"])
            msg_data = json.loads(body["data"])

            # 忽略自己发的消息
            if msg_data.get("person") == self._person_id:
                return

            # 通过名称解析器获取友好名称
            resolver = get_resolver()
            person_id = msg_data.get("person", "")
            channel_id = msg_data.get("channel", "")
            area_id = msg_data.get("area", "")

            # 注册新发现的 ID（自动保存到 names.json）
            if area_id:
                resolver.register_id("areas", area_id)
            if channel_id:
                resolver.register_id("channels", channel_id)
            if person_id:
                resolver.register_id("users", person_id)

            user_display = resolver.user(person_id)
            area_display = resolver.area(area_id)
            channel_display = resolver.channel(channel_id)

            logger.info(
                f"[聊天] 域={area_display} 频道={channel_display} "
                f"用户={user_display} "
                f"内容={msg_data.get('content', '')[:100]}"
            )

            if self.on_chat_message:
                self.on_chat_message(msg_data)

        except Exception as e:
            logger.error(f"解析聊天消息失败: {e}")
