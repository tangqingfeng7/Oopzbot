# Oopz-SDK OneBot v11 适配

项目使用 `oopz-sdk` 自带的 OneBot v11 adapter/server，负责协议转换与连接服务。`oopz/sdk_config.py` 直接构造 SDK 配置，`core/onebot_migration.py` 负责旧数据库升级。

默认是关闭的。启用后，Bot 仍然照常连接 Oopz；同时把收到的 Oopz 消息转换成 OneBot v11 事件，给 NoneBot、AstrBot、Hoshino 等支持 OneBot v11 的程序使用。

## 启用方式

在 `config.py` 里加入或修改：

```python
ONEBOT_V11_CONFIG = {
    "enabled": True,
    "host": "127.0.0.1",
    "port": 6700,
    "access_token": "",
    "secret": "",
    "db_path": "data/onebot_v11.sqlite3",

    "enable_http": True,
    "enable_ws": True,

    "enable_http_post": False,
    "http_post_urls": [],
    "http_post_timeout": 0.0,

    "enable_ws_reverse": False,
    "ws_reverse_url": "",
    "ws_reverse_api_url": "",
    "ws_reverse_event_url": "",
    "ws_reverse_reconnect_interval": 3.0,
    "send_connect_event": True,



    "enable_area_scoped_group_ban": False,
    "enable_set_group_kick_as_area_kick": False,
    "enable_set_group_leave_as_area_leave": False,
}
```

然后启动主程序：

```shell
python main.py
```

启动成功后，SDK 会记录 `OneBot v11 server started`。默认监听：

```text
http://127.0.0.1:6700
```

## 连接方式

### HTTP action

OneBot action 直接作为路径调用：

```shell
curl http://127.0.0.1:6700/get_status
```

发送群消息：

```shell
curl -X POST http://127.0.0.1:6700/send_group_msg ^
  -H "Content-Type: application/json" ^
  -d "{\"group_id\":12345678,\"message\":\"hello\"}"
```

如果 `group_id` 还没有映射过，可以直接补 Oopz 上下文：

```json
{
  "group_id": 12345678,
  "oopz_area_id": "OOPZ_AREA_ID",
  "oopz_channel_id": "OOPZ_CHANNEL_ID",
  "message": "hello"
}
```

### 正向 WebSocket

| 路径 | 说明 |
| --- | --- |
| `/api` | 只处理 action 调用 |
| `/event` | 只推送事件 |
| `/` | 同时处理 action 和事件 |

常见程序如果要连正向 WebSocket，可以使用：

```text
ws://127.0.0.1:6700/
```

### HTTP POST 上报

开启：

```python
ONEBOT_V11_CONFIG["enable_http_post"] = True
ONEBOT_V11_CONFIG["http_post_urls"] = [
    "http://127.0.0.1:8081/onebot",
]
```

配置了 `secret` 时，上报请求会带 `X-Signature: sha1=...`。

### 反向 WebSocket

开启：

```python
ONEBOT_V11_CONFIG["enable_ws_reverse"] = True
ONEBOT_V11_CONFIG["ws_reverse_url"] = "ws://127.0.0.1:8081/onebot/v11/ws"
```

如果对端区分 API 和 Event 连接，可以分别配置：

```python
ONEBOT_V11_CONFIG["ws_reverse_api_url"] = "ws://127.0.0.1:8081/api"
ONEBOT_V11_CONFIG["ws_reverse_event_url"] = "ws://127.0.0.1:8081/event"
```

## 鉴权

`access_token` 为空时不鉴权。设置后，HTTP 和 WebSocket 都需要带 token。

HTTP 示例：

```shell
curl http://127.0.0.1:6700/get_status ^
  -H "Authorization: Bearer your-token"
```

也支持 query：

```text
http://127.0.0.1:6700/get_status?access_token=your-token
```

## 映射规则

Oopz 的 ID 多数是字符串，但 OneBot v11 常用数字 ID。SDK 适配器会把这些 ID 存到 SQLite，生成稳定的数字 ID。

| OneBot 字段 | Oopz 来源 |
| --- | --- |
| `self_id` | 当前 Bot 的 Oopz 用户 UID |
| `user_id` | Oopz 用户 UID |
| `group_id` | Oopz 的 `area + channel` |
| `message_id` | Oopz 消息 ID，加上频道上下文 |

默认映射库：

```text
data/onebot_v11.sqlite3
```

不要随便删除这个文件。删掉后数字 ID 会重新生成，外部程序里缓存的 `group_id`、`user_id`、`message_id` 可能失效。首次从旧实现迁移时，会先创建不覆盖的 `<数据库名>.pre-sdk-v0.15.0.bak`，随后在一个事务内迁移 ID 和消息记录；失败会回滚并停止 OneBot 启动。

## 事件格式

### 频道消息

Oopz 频道消息会转成 OneBot v11 的 `group` 消息。

```json
{
  "post_type": "message",
  "message_type": "group",
  "sub_type": "normal",
  "group_id": 12345678,
  "user_id": 87654321,
  "message": [
    {"type": "text", "data": {"text": "hello"}}
  ],
  "raw_message": "hello",
  "extra": {
    "oopz_area_id": "OOPZ_AREA_ID",
    "oopz_channel_id": "OOPZ_CHANNEL_ID",
    "oopz_user_id": "OOPZ_USER_ID",
    "oopz_message_id": "OOPZ_MESSAGE_ID"
  }
}
```

### 私信消息

Oopz 私信消息会转成 OneBot v11 的 `private` 消息。

```json
{
  "post_type": "message",
  "message_type": "private",
  "sub_type": "friend",
  "user_id": 87654321,
  "message": [
    {"type": "text", "data": {"text": "hello"}}
  ],
  "raw_message": "hello",
  "extra": {
    "oopz_user_id": "OOPZ_USER_ID",
    "oopz_target_id": "OOPZ_USER_ID",
    "oopz_message_id": "OOPZ_MESSAGE_ID"
  }
}
```

### 其他事件

SDK 会跳过 Oopz 心跳（`HeartbeatEvent`）和服务端 ID 事件（`ServerIdEvent`）。除消息、撤回和好友请求外，其余 Oopz 事件以 `meta_event_type="oopz"` 推送，事件内容在 `payload` 中。

### 好友请求

Oopz 好友请求会转成 OneBot v11 `request.friend`：

```json
{
  "post_type": "request",
  "request_type": "friend",
  "user_id": 12345678,
  "comment": "nickname",
  "flag": "oopz_friend_request:4455:OOPZ_USER_ID",
  "extra": {
    "oopz_friend_request_id": 4455,
    "oopz_user_id": "OOPZ_USER_ID"
  }
}
```

## 支持的 action

### 基础 action

| Action | 说明 |
| --- | --- |
| `get_supported_actions` | 获取当前支持的 action |
| `.get_supported_actions` | 兼容写法 |
| `get_latest_events` | 获取最近缓存的事件 |
| `get_status` | 获取在线状态 |
| `get_version_info` / `get_version` | 获取版本信息 |
| `can_send_image` | 返回可发送图片 |
| `can_send_record` | 当前返回不可发送语音 record |

### 消息 action

| Action | 说明 |
| --- | --- |
| `send_msg` | 按 `message_type` 分发到群聊或私聊 |
| `send_group_msg` | 发送 Oopz 频道消息 |
| `send_private_msg` | 发送 Oopz 私信 |
| `delete_msg` / `recall_message` | 撤回消息 |
| `get_msg` | 通过消息映射查询消息 |

### 用户和群 action

| Action | 说明 |
| --- | --- |
| `get_login_info` | 获取当前 Bot 信息 |
| `get_stranger_info` | 获取用户信息 |
| `get_friend_list` | 获取 Oopz 好友列表 |
| `set_friend_add_request` | 处理好友请求，可接受或拒绝 |
| `get_group_list` | 获取已加入域下的频道列表 |
| `get_group_info` | 获取频道信息 |
| `get_group_member_info` | 获取域成员信息 |
| `get_group_member_list` | 获取域成员列表 |
| `set_group_name` | 修改 Oopz 频道名 |
| `cleanup_message_mapping` | 清理旧消息映射 |

## 高风险 action

下面这些 action 默认关闭。开启后会映射到 Oopz 域级操作，要确认权限和影响范围后再打开。

| Action | 配置项 | 映射行为 |
| --- | --- | --- |
| `set_group_ban` | `enable_area_scoped_group_ban` | 禁言或解除禁言域成员 |
| `set_group_kick` | `enable_set_group_kick_as_area_kick` | 移出域；`reject_add_request=true` 时封禁 |
| `set_group_leave` | `enable_set_group_leave_as_area_leave` | 离开 `group_id` 对应的 Oopz 域 |

## 消息段支持

发送消息时支持这些 OneBot v11 消息段：

| 消息段 | 处理方式 |
| --- | --- |
| `text` | 普通文本 |
| `at` | 转成 Oopz `mentionList` 和 `(met)uid(met)` |
| `at` `qq=all` | 转成全体提及 |
| `image` | 发送已上传的 Oopz 图片时，`data.file` 填文件键，`data.url` 填同一张图片的 URL |
| `reply` 及其他未识别的数组消息段 | 作为占位文本发送 |

例如，转发一张已上传的图片时，将原图的文件键和 URL 填入 `message` 数组：

```json
[
  {"type": "image", "data": {"file": "OOPZ_FILE_KEY", "url": "https://example.com/image.png"}}
]
```

接收消息时，从 `message` 数组读取提及和图片等结构化内容。`raw_message` 取自 Oopz 消息文本，不进行 CQ 编码。收到的引用消息不会生成 `reply` 段。

字符串 CQ 码也会按同样规则解析，例如：

```text
[CQ:at,qq=123456] hello
```

在 Linux 上发送本地图片时，可使用字符串 `[CQ:image,file=file:///tmp/photo.png]`，路径指向 Bot 所在机器上的文件。

如果请求里传 `auto_escape=true`，字符串里的 CQ 码不会解析，会按普通文本发送。

## 常见问题

### 连接成功但收不到事件

先确认：

- `ONEBOT_V11_CONFIG["enabled"] = True`
- 外部程序连接的是 `ws://127.0.0.1:6700/event` 或 `ws://127.0.0.1:6700/`
- Bot 本身已经成功连接 Oopz
- 如果设置了 `access_token`，外部程序也带了同一个 token

### `send_group_msg` 提示 unknown group_id

说明这个 `group_id` 还没有在映射库里出现过。先调用 `get_group_list` 获取真实 `group_id`，或者在请求里补：

```json
{
  "oopz_area_id": "OOPZ_AREA_ID",
  "oopz_channel_id": "OOPZ_CHANNEL_ID"
}
```

### 端口被占用

修改：

```python
ONEBOT_V11_CONFIG["port"] = 6701
```

然后重启 `python main.py`。

### 外部程序需要公网访问

默认只监听 `127.0.0.1`，只能本机访问。需要外部机器访问时，可以改成：

```python
ONEBOT_V11_CONFIG["host"] = "0.0.0.0"
```

同时建议设置 `access_token`，并通过防火墙或反向代理限制来源。
