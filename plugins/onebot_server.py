import asyncio
import json
import threading
import time
import uuid

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from plugin_base import (
    BotModule,
    PluginCommandCapabilities,
    PluginConfig,
    PluginConfigField,
    PluginConfigSpec,
    PluginMetadata,
)
from oopz_sender import OopzSender
from command_handler import CommandHandler
from logger_config import get_logger
from config import OOPZ_CONFIG

logger = get_logger("OneBotServer")

app = FastAPI(title="OneBot V12 Server")
connected_clients: list[WebSocket] = []
uvicorn_loop: asyncio.AbstractEventLoop = None

@app.on_event("startup")
async def on_startup():
    global uvicorn_loop
    uvicorn_loop = asyncio.get_running_loop()

class OnebotGateway:
    sender: OopzSender
    bot_uid: str
    access_token: str

    def __init__(self):
        self.sender = None
        self.bot_uid = ""
        self.access_token = ""

    def connect_sender(self, sender, bot_uid):
        self.sender = sender
        self.bot_uid = bot_uid

gateway = OnebotGateway()

@app.websocket("/")
async def websocket_endpoint(websocket: WebSocket):
    if gateway.access_token:
        token = websocket.query_params.get("access_token")
        if not token:
            auth_header = websocket.headers.get("authorization")
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header[7:]

        if token != gateway.access_token:
            await websocket.close(code=1008, reason="Unauthorized")
            return

    await websocket.accept()
    connected_clients.append(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                frame = json.loads(data)
                await handle_action(websocket, frame)
            except json.JSONDecodeError:
                pass
            except Exception as e:
                logger.error(f"OneBot action error: {e}")
    except WebSocketDisconnect:
        connected_clients.remove(websocket)

async def handle_action(websocket: WebSocket, frame: dict):
    action = frame.get("action")
    params = frame.get("params", {})
    echo = frame.get("echo")

    if action == "send_message":
        channel_id = params.get("channel_id")
        guild_id = params.get("guild_id", "")
        message = params.get("message", [])

        text_content = ""
        attachments = []
        if isinstance(message, str):
            text_content = message
        elif isinstance(message, list):
            for seg in message:
                message_type = seg.get("type")
                data = seg.get("data", {})
                if message_type == "text":
                    text_content += data.get("text", "")
                elif message_type == "image":
                    file_id = data.get("file_id", "")
                    if file_id:
                        att = json.loads(file_id)
                        text_content += f"![IMAGEw{att['width']}h{att['height']}]({att['fileKey']})"
                        attachments.append(att)
                elif message_type == "mention":
                    text_content += f"(met){data.get('user_id', '')}(met)"

        if gateway.sender and channel_id:
            try:
                result = await asyncio.to_thread(
                    gateway.sender.send_message,
                    text=text_content,
                    area=guild_id,
                    channel=channel_id,
                    attachments=attachments
                )

                resp = {
                    "status": "ok",
                    "retcode": 0,
                    "data": {
                        "message_id": str(uuid.uuid4())
                    },
                    "message": ""
                }
                if echo:
                    resp["echo"] = echo
                await websocket.send_json(resp)
            except Exception as e:
                logger.error(f"发送消息失败: {e}")
                error_resp = {
                    "status": "failed",
                    "retcode": 10000,
                    "data": None,
                    "message": str(e)
                }
                if echo:
                    error_resp["echo"] = echo
                await websocket.send_json(error_resp)

    elif action == "upload_file":
        upload_type = params.get("type")
        url = params.get("url")

        if gateway.sender:
            try:
                result = await asyncio.to_thread(gateway.sender.upload_file_from_url, url)
                if result["code"] == "error":
                    raise Exception(result["message"])
                data = json.dumps(result["data"])

                resp = {
                    "status": "ok",
                    "retcode": 0,
                    "data": {
                        "file_id": data
                    },
                    "message": ""
                }
                if echo:
                    resp["echo"] = echo
                await websocket.send_json(resp)
            except Exception as e:
                logger.error(f"上传文件失败: {e}")
                error_resp = {
                    "status": "failed",
                    "retcode": 10000,
                    "data": None,
                    "message": str(e)
                }
                if echo:
                    error_resp["echo"] = echo
                await websocket.send_json(error_resp)

class OnebotServerPlugin(BotModule):
    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="onebot_server",
            description="OneBot v12 协议适配器",
            version="1.0.0",
            author="",
        )

    @property
    def command_capabilities(self) -> PluginCommandCapabilities:
        return PluginCommandCapabilities(
            mention_prefixes=(),
            slash_commands=(),
            is_public_command=True,
        )

    @property
    def config_spec(self) -> PluginConfigSpec:
        return PluginConfigSpec(
            (
                PluginConfigField(
                    "enabled",
                    default=False,
                    cast=bool,
                    description="是否启用插件",
                    example=False,
                ),
                PluginConfigField(
                    "host",
                    default="0.0.0.0",
                    cast=str,
                    description="绑定的 Host",
                    example="0.0.0.0",
                ),
                PluginConfigField(
                    "port",
                    default=8081,
                    cast=int,
                    description="绑定的端口",
                    example=8081,
                ),
                PluginConfigField(
                    "access_token",
                    default="",
                    cast=str,
                    description="访问令牌，留空则不验证",
                    example="your_secret_token",
                ),
            )
        )

    def __init__(self):
        self._original_handle_message = None
        self._server_thread = None

    def on_load(self, handler, config: PluginConfig | None = None) -> None:
        self._handler = handler
        self._config = config or PluginConfig("onebot_server")

        if not self._config.get("enabled", False):
            logger.info("OneBot Server 插件未启用")
            return

        bot_uid = OOPZ_CONFIG.get("person_uid", "")
        gateway.connect_sender(handler.sender.raw, bot_uid)
        gateway.access_token = self._config.get("access_token", "")

        self._original_handle_message = CommandHandler.handle_message

        def handle_message_wrapper(handler_self, msg_data: dict):
            self._broadcast_to_onebot(msg_data)

        CommandHandler.handle_message = handle_message_wrapper

        host = self._config.get("host", "0.0.0.0")
        port = int(self._config.get("port", 8081))

        self._server_thread = threading.Thread(
            target=lambda: uvicorn.run(app, host=host, port=port, log_level="warning"),
            daemon=True
        )
        self._server_thread.start()
        logger.info(f"OneBot V12 Server 运行在 ws://{host}:{port}/")

    def _broadcast_to_onebot(self, msg_data: dict):
        if not connected_clients:
            return

        ob12_event = {
            "id": str(uuid.uuid4()),
            "time": time.time(),
            "type": "message",
            "detail_type": "channel",
            "sub_type": "",
            "message_id": msg_data.get("messageId", ""),
            "message": [
                {
                    "type": "text",
                    "data": {
                        "text": msg_data.get("content", "")
                    }
                }
            ],
            "alt_message": msg_data.get("content", ""),
            "guild_id": msg_data.get("area", ""),
            "channel_id": msg_data.get("channel", ""),
            "user_id": msg_data.get("person", "")
        }

        if uvicorn_loop and uvicorn_loop.is_running():
            for client in connected_clients:
                asyncio.run_coroutine_threadsafe(client.send_json(ob12_event), uvicorn_loop)

    def on_unload(self) -> None:
        if self._original_handle_message:
            CommandHandler.handle_message = self._original_handle_message

    def handle_mention(self, text, channel, area, user, handler) -> bool:
        return False

    def handle_slash(self, command, subcommand, arg, channel, area, user, handler) -> bool:
        return False
