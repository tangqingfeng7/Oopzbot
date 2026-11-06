# Oopz 平台 API 参考

本文档整理 Oopz 平台当前可用的 HTTP API 与 WebSocket 协议。Oopz 未公开官方 API 契约，路径、字段和枚举可能随客户端升级变化。


## 基础信息

| 项目 | 值 |
|------|-----|
| Gateway API | `https://gateway.oopz.cn` |
| WebSocket | `wss://ws.oopz.cn` |
| CDN | 通过签名上传接口获取 CDN URL |

## 请求签名

所有 HTTP 请求需携带以下 Oopz 专用头：

| Header | 说明 |
|--------|------|
| `Oopz-Sign` | RSA PKCS1v15 + SHA256 签名，Base64 编码 |
| `Oopz-Request-Id` | 随机 UUID |
| `Oopz-Time` | 毫秒时间戳 |
| `Oopz-App-Version-Number` | 客户端版本号 |
| `Oopz-Channel` | 渠道（`Web`） |
| `Oopz-Device-Id` | 设备 ID |
| `Oopz-Platform` | 平台（`windows`） |
| `Oopz-Web` | 是否 Web 客户端（`true`） |
| `Oopz-Person` | 当前用户 UID |
| `Oopz-Signature` | JWT Token |

**签名流程：**

```
sign_path = url_path + ("?" + urlencode(query) if query else "")
body_json = compact_json(body) if body is not None else method_default_body
sign_data = MD5(sign_path + body_json) + timestamp_ms
signature = Base64(RSA_PKCS1v15_SHA256(sign_data, private_key))
```

无显式 body 时，`method_default_body` 的规则为：`POST` / `PUT` / `PATCH` 使用 `{}`，`GET` / `DELETE` 使用空字符串。Query 参数参与签名，且顺序必须与实际 URL 一致。

---

## WebSocket 协议

### 连接

```
URL: wss://ws.oopz.cn
```

### 事件类型

| event | 说明 |
|-------|------|
| `1` | 服务端 `serverId` 确认 |
| `2` | 收到好友请求 |
| `4` | 好友删除 |
| `6` | 私信撤回 |
| `7` | 私信消息 |
| `8` | 频道消息撤回 |
| `9` | 频道消息 |
| `11` | 频道禁麦 |
| `12` | 频道禁言 |
| `13` | 频道删除 |
| `18` | 频道设置变更 |
| `19` | 用户退出语音频道 |
| `20` | 用户进入语音频道 |
| `21` | 鉴权校验结果；`body.checkRes=false` 表示凭据被拒绝 |
| `25` | 公开频道创建 |
| `26` | 用户信息变更 |
| `27` | 用户登录状态变更 |
| `28` | 域信息变更 |
| `32` | 消息表情反应变更 |
| `52` | 身份组变更 |
| `56` | 私信编辑 |
| `57` | 频道消息编辑 |
| `249` | 客户端发送的域事件订阅帧 |
| `253` | 客户端发送的认证帧 |
| `254` | 心跳帧 |

### 认证（event=253）

连接建立后发送：

```json
{
  "time": "毫秒时间戳",
  "body": "{\"person\":\"UID\",\"deviceId\":\"设备ID\",\"signature\":\"JWT\",\"deviceName\":\"设备ID\",\"platformName\":\"web\",\"reconnect\":0}",
  "event": 253
}
```

### 心跳（event=254）

发送认证帧后应定期发送心跳，建议间隔为 10 秒。

```json
{
  "time": "毫秒时间戳",
  "body": "{\"person\":\"UID\"}",
  "event": 254
}
```

### 订阅域事件（event=249）

```json
{
  "time": "毫秒时间戳",
  "body": "{\"areas\":[\"域ID\"],\"type\":1,\"uid\":\"当前用户UID\"}",
  "event": 249
}
```

> `body` 仍是 JSON 字符串，不是嵌套对象。

### 聊天消息（event=9）

接收格式：

```json
{
  "event": 9,
  "body": "{\"data\":\"{\\\"channel\\\":\\\"频道ID\\\",\\\"area\\\":\\\"域ID\\\",\\\"person\\\":\\\"用户ID\\\",\\\"content\\\":\\\"消息文本\\\",\\\"messageId\\\":\\\"消息ID\\\",\\\"timestamp\\\":\\\"微秒时间戳\\\"}\"}"
}
```

> `body` 是双层 JSON 字符串嵌套：外层 `body.data` 也是 JSON 字符串。

---

## 消息 API

### 发送频道消息（当前默认 v2）

```
POST /im/session/v2/sendGimMessage
```

**请求体：**

```json
{
  "message": {
    "area": "域ID",
    "channel": "频道ID",
    "target": "",
    "clientMessageId": "15位客户端消息ID",
    "timestamp": "微秒时间戳",
    "isMentionAll": false,
    "mentionList": [],
    "styleTags": [],
    "referenceMessageId": null,
    "animated": false,
    "displayName": "",
    "duration": 0,
    "content": "消息文本",
    "attachments": []
  }
}
```

v2 的正文字段为 `content`；需兼容旧版时，可在 `message` 内附带同值的 `text`。

#### v1 兼容格式

```http
POST /im/session/v1/sendGimMessage
```

v1 不使用 `message` 包裹，字段直接放在根级，正文字段为 `text`。新集成应优先使用 v2。

**图片消息正文格式：** `![IMAGEw{宽}h{高}]({fileKey})`

**附件格式（图片）：**

```json
{
  "fileKey": "文件Key",
  "url": "CDN URL",
  "width": 1920,
  "height": 1080,
  "fileSize": 123456,
  "hash": "MD5",
  "animated": false,
  "displayName": "",
  "attachmentType": "IMAGE"
}
```

#### 原生图片消息

```http
POST /rtc/v1/gim/v1/sendImage
POST /rtc/v1/im/v1/sendImage
```

分别用于频道和私信的纯图片消息，客户端按图片比例展示预览。请求体直接包含字段，不使用 `message` 包裹：

| 字段 | 说明 |
|------|------|
| `area` / `channel` / `target` | 频道图片填写域和频道；私信填写会话频道和目标用户 |
| `clientMessageId` / `timestamp` | 客户端消息 ID 和微秒时间戳 |
| `rawImage` | 上述图片附件对象，`hash` 必须填写上传文件字节的 MD5 |
| `displayName` / `animated` | 文件名和是否为动图 |
| `styleTags` | 消息样式数组 |
| `isMentionAll` / `mentionList` | 通常为 `false` 和空数组 |

带文字的图片消息使用文字消息接口，在正文中引用图片附件。

**附件格式（音频）：**

```json
{
  "fileKey": "文件Key",
  "url": "CDN URL",
  "fileSize": 123456,
  "hash": "MD5",
  "animated": false,
  "displayName": "歌名.mp3",
  "attachmentType": "AUDIO",
  "duration": 240
}
```

**公告样式（styleTags）：**

| 说明 | 值 |
|------|-----|
| 请求体字段 | `styleTags`，数组类型 |
| 公告样式 | 传 `["IMPORTANT"]` 时，客户端会将该条消息以「重要/公告」气泡样式展示（与官方公告一致） |
| 强制指定 | 调用时显式传入 `styleTags=["IMPORTANT"]` 或 `styleTags=[]` 会跳过上述配置，直接生效 |
| 正文排版 | 客户端支持 `**粗体**`、`*斜体*` 等 Markdown 式渲染（以实际展示为准） |

**带 @ 用户：**

v2 包裹格式的 @ 用户请求示例：

```
POST /im/session/v2/sendGimMessage
```

```json
{
  "message": {
    "area": "域ID",
    "channel": "频道ID",
    "target": "",
    "clientMessageId": "15位客户端消息ID",
    "timestamp": "微秒时间戳",
    "isMentionAll": false,
    "mentionList": [
      {
        "person": "被@用户UID",
        "isBot": false,
        "botType": "",
        "offset": -1
      }
    ],
    "styleTags": [],
    "referenceMessageId": null,
    "animated": false,
    "displayName": "",
    "duration": 0,
    "content": " (met)被@用户UID(met)",
    "attachments": []
  }
}
```

| 字段 | 说明 |
|------|------|
| `mentionList[].person` | 被 @ 用户 UID |
| `mentionList[].isBot` | 是否机器人 |
| `mentionList[].botType` | 机器人类型（普通用户为空） |
| `mentionList[].offset` | 文本偏移；`-1` 表示不按偏移定位 |
| `content` | @ 文本使用 ` (met){uid}(met)` 格式 |

**Web 端回复消息：**

Web 端发送“回复某条消息”的频道消息时，仍然使用 `v2/sendGimMessage`，引用关系通过 `referenceMessageId` 传递：

```json
{
  "message": {
    "area": "域ID",
    "channel": "频道ID",
    "target": "",
    "clientMessageId": "15位客户端消息ID",
    "timestamp": "微秒时间戳",
    "isMentionAll": false,
    "mentionList": [],
    "styleTags": [],
    "referenceMessageId": "被回复的消息ID",
    "animated": false,
    "displayName": "",
    "duration": 0,
    "content": "回复文本",
    "attachments": []
  }
}
```

> 回复关系在 `sendGimMessage.message.referenceMessageId` 中体现，不是在表情反应接口中单独传引用字段。

### 撤回消息

```
POST /im/session/v1/recallGim
```

> 接口接受 JSON body。Web 客户端还会把同一组字段同时放入 query 和 body；使用该形状时，query 和 body 都必须参与签名。

**请求体：**

```json
{
  "area": "域ID",
  "channel": "频道ID",
  "messageId": "消息ID",
  "timestamp": "微秒时间戳",
  "target": ""
}
```

**成功响应：**

```json
{"status": true, "data": true, "message": "", "error": "", "code": ""}
```

#### 撤回私信

```http
POST /im/session/v1/recallIm
```

```json
{
  "area": "",
  "channel": "私信会话channel",
  "messageId": "消息ID",
  "timestamp": "微秒时间戳",
  "target": "对方UID"
}
```

`recallGim` 用于频道消息，`recallIm` 用于私信消息，两者不可混用。

### 获取频道消息

```
GET /im/session/v2/messageBefore?area={area}&channel={channel}&size={size}
```

**参数：**

| 参数 | 说明 |
|------|------|
| `area` | 域 ID |
| `channel` | 频道 ID |
| `size` | 获取条数（默认 50） |

**响应 data：**

```json
{
  "messages": [
    {
      "messageId": "消息ID",
      "timestamp": "微秒时间戳",
      "person": "发送者UID",
      "content": "消息文本",
      "channel": "频道ID",
      "area": "域ID"
    }
  ]
}
```

#### 置顶/取消置顶频道消息

```http
POST /im/session/v1/messageTop
```

```json
{
  "messageId": "消息ID",
  "type": "TOP 或 CANCEL_TOP",
  "area": "域ID",
  "channel": "频道ID"
}
```

### 消息表情反应

#### 新增 / 取消单条消息表情

```
POST /im/session/v1/gimReaction
```

**请求体：**

```json
{
  "messageId": "消息ID",
  "emoji": "😀",
  "type": "REPLY",
  "channel": "频道ID",
  "area": "域ID",
  "target": "",
  "anchor": ""
}
```

**字段说明：**

| 字段 | 说明 |
|------|------|
| `messageId` | 被反应的消息 ID |
| `emoji` | 表情字符本体。Web 抓包中直接传 Unicode 字符，不是 `:smile:` 这类别名 |
| `type` | `REPLY` 表示新增反应；`WITHDRAWN` 表示取消反应 |
| `channel` | 频道 ID |
| `area` | 域 / 区域 ID |
| `target` | 抓包样本中始终为空字符串 |
| `anchor` | 文本消息通常为空；图片 / 贴纸样本中抓到非空值，如 `a8cefa6020c711ef948e22d3a3e3e6e2` |

**取消表情示例：**

```json
{
  "messageId": "消息ID",
  "emoji": "😀",
  "type": "WITHDRAWN",
  "channel": "频道ID",
  "area": "域ID",
  "target": "",
  "anchor": ""
}
```

**成功响应：**

```json
{
  "status": true,
  "data": true,
  "message": "",
  "error": "",
  "code": ""
}
```

**补充：**

- 文本消息与“回复消息”的表情请求体一致，`anchor` 均为空字符串。
- 图片消息、贴纸 / 动图消息的表情请求体中，`anchor` 可能为非空。
- 频道消息的 `target` 通常为空字符串。

#### 批量查询多条消息的表情反应

```
POST /im/session/v1/gimReactions
```

**请求体：**

```json
[
  {
    "messageId": "消息ID1"
  },
  {
    "messageId": "消息ID2"
  }
]
```

**说明：**

- 用于批量查询多条消息当前的表情反应汇总。
- Web 端会在消息列表加载后批量请求多个 `messageId`。

#### 查询某个表情的反应用户

```
GET /im/session/v2/gimReactionPersons?messageId={messageId}&emoji={emoji}&channel={channel}&page={page}&pageSize={pageSize}
```

**参数：**

| 参数 | 说明 |
|------|------|
| `messageId` | 消息 ID |
| `emoji` | 表情字符，需 URL 编码 |
| `channel` | 频道 ID |
| `page` | 页码，如 `1` |
| `pageSize` | 每页数量，如 `4` |

**成功响应示例：**

```json
{
  "status": true,
  "data": [],
  "message": "",
  "error": "",
  "code": ""
}
```

#### 私信表情反应

私信使用与频道消息分离的 `im*` 接口：

| 用途 | 方法 | 路径 |
|------|------|------|
| 新增/取消私信反应 | POST | `/im/session/v1/imReaction` |
| 批量查询私信反应 | POST | `/im/session/v1/imReactions` |
| 查询私信某表情的反应用户 | GET | `/im/session/v2/imReactionPersons?messageId={messageId}&emoji={emoji}&channel={channel}&page={page}&pageSize={pageSize}` |

`imReaction` 请求体与 `gimReaction` 字段一致，但私信场景的 `area` 为空，`target` 和 `anchor` 都使用对方 UID。`imReactions` 请求体为对象数组，每项仅包含 `messageId`。

> 当前 Web 包的取消反应枚举值为 `WITHDRAWN`。频道和私信使用相同枚举。

### 私信 API（IM）

以下接口用于私信会话。请求签名与通用规则一致，需携带 Oopz 系列 Header。

#### 打开/切换私信会话

进入与指定用户的私信会话（若无则创建会话）。

```
PATCH /client/v1/chat/v1/to?target={目标用户UID}
```

| 参数 | 说明 |
|------|------|
| `target` | 目标用户 UID（如 `a8cefa6020c711ef948e22d3a3e3e6e2`） |

**说明：** 调用成功后，后续拉历史、发消息需使用该会话对应的 `channel`（通常由响应或后续接口返回）。

#### 发送私信消息

发送一条私信。v2 的 `sendImMessage` 与频道消息 `sendGimMessage` 都使用 **`message` 包裹**，正文字段为 **`content`**。v1 为兼容路径，使用根级请求体。

```
POST /im/session/v2/sendImMessage
```

**请求体（Web 端格式，根级为 `message` 对象）：**

```json
{
  "message": {
    "area": "",
    "channel": "私信会话 channel（来自 open_private_session 或会话列表）",
    "target": "目标用户 UID",
    "clientMessageId": "15 位客户端消息 ID",
    "timestamp": "微秒时间戳",
    "isMentionAll": false,
    "mentionList": [],
    "styleTags": [],
    "referenceMessageId": null,
    "animated": false,
    "displayName": "",
    "duration": 0,
    "content": "消息文本",
    "attachments": []
  }
}
```

**字段说明（均在 `message` 内）：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `channel` | string | 是 | 私信会话 channel |
| `target` | string | 是 | 目标用户 UID |
| `clientMessageId` | string | 是 | 客户端消息 ID |
| `timestamp` | string | 是 | 微秒时间戳 |
| `content` | string | 是 | 消息正文；发图片时为 `![IMAGEw{宽}h{高}]({fileKey})` 或与文字拼接 |
| `attachments` | array | 否 | 附件列表，结构同「发送消息」 |
| `area` | string | 否 | 私信留空 `""` |
| `isMentionAll` | boolean | 否 | 默认 `false` |
| `mentionList` | array | 否 | 默认 `[]` |
| `styleTags`、`referenceMessageId`、`animated`、`displayName`、`duration` | - | 否 | 同上 |

**成功响应示例：** `{"status":true,"data":{"messageId":"...","timestamp":"..."},"message":"","error":"","code":""}`

**注意：** `HTTP 200` 不一定代表私信已投递成功。若业务层返回类似 `你已被限制向该用户发送信息`，应视为发送失败，而不是只按 HTTP 状态码判断成功。

**图片消息：** 正文放在 `content`，附件放在 `attachments`，格式同「发送消息」。

#### 获取私信历史消息

拉取与某用户的私信历史。

```
GET /im/session/v2/messageBefore?area&channel={channel}&size={size}
```

| 参数 | 说明 |
|------|------|
| `area` | 私信场景下可为空（query 中保留 `area` 无值即可） |
| `channel` | 私信会话 channel（如 `01KJP5MHQC7TSQ6FDKT8N1DZAX`），从「打开私信会话」或会话列表获得 |
| `size` | 条数，如 `50` |

响应格式与「获取频道消息」中的 `messages` 结构类似（含 `messageId`、`timestamp`、`person`、`content`、`channel` 等）。

#### 保存已读状态

上报该私信会话的已读状态。

```
POST /im/session/v1/saveReadStatus
```

**请求体：**

```json
{
  "area": "",
  "status": [
    {
      "person": "当前用户 UID",
      "channel": "私信会话 channel",
      "messageId": "已读到的最后一条消息 ID"
    }
  ]
}
```

私信场景下 `area` 为空字符串；房间场景下 `area` 为域 ID。

---

**私信流程小结：**

| 步骤 | 方法 | 路径 |
|------|------|------|
| 打开私信会话 | PATCH | `/client/v1/chat/v1/to?target=<uid>` |
| 发送私信 | POST | `/im/session/v2/sendImMessage` |
| 拉取历史 | GET | `/im/session/v2/messageBefore?area&channel=<channel>&size=50` |
| 已读状态 | POST | `/im/session/v1/saveReadStatus` |

---

### 发送语音频道互动

```http
POST /client/v1/interaction/v1/send
```

```json
{
  "area": "域ID",
  "channel": "语音频道ID",
  "interactionStickerIds": ["互动贴纸ID"],
  "target": "目标用户UID"
}
```

该路径用于发送语音频道互动。

---

## 文件上传 API

### 获取签名上传 URL

```
PUT /rtc/v1/cos/v1/signedUploadUrl
```

**请求体：**

```json
{
  "type": "IMAGE",
  "ext": ".webp"
}
```

`type` 可选值：`IMAGE`、`AUDIO`

**响应 data：**

```json
{
  "signedUrl": "带签名的上传URL",
  "file": "文件Key（用于消息附件）",
  "url": "CDN访问URL"
}
```

### 上传文件

```
PUT {signedUrl}
Content-Type: application/octet-stream
Body: 文件二进制内容
```

---

## 域（Area）API

### 获取已加入的域列表

```
GET /userSubscribeArea/v1/list
```

**响应 data：**

```json
[
  {
    "id": "域ID",
    "code": "域邀请码",
    "name": "域名称",
    "avatar": "头像URL",
    "banner": "横幅URL",
    "level": 0,
    "owner": "域主UID",
    "groupID": "默认分组ID",
    "groupName": "默认分组名称",
    "subscript": 0
  }
]
```

> 判断是否真正退域应以这个服务端列表和 Oopz 客户端状态为准。

### 查询邀请详情

```http
GET /invite/v1/codeDetail?code={code}
```

`code` 是 `https://oopz.cn/i/{code}` 中的短码。响应 `data` 字段为：

```json
{
  "status": "INVITE_NORMAL",
  "inviteUid": "邀请者UID",
  "area": "域ID",
  "areaName": "域名称",
  "areaAvatar": "域头像URL",
  "banner": "域横幅URL",
  "channel": "频道ID",
  "channelName": "频道名称",
  "channelType": "频道类型",
  "isAreaInvite": true
}
```

接受邀请前应通过该接口重新校验邀请状态，不应直接信任消息卡片中的展示内容。

### 获取域详情

```
GET /area/v3/info?area={area}
```

返回域的详细信息，含角色列表、主页频道等。

**响应 data：**

```json
{
  "id": "域ID",
  "code": "315084890",
  "name": "域名称",
  "banner": "横幅URL",
  "avatar": "头像URL",
  "desc": "域描述",
  "subscribed": true,
  "privateChannels": ["私密频道ID"],
  "isPublic": false,
  "roleList": [
    {
      "roleID": 10911515,
      "name": "",
      "description": "域的所有者",
      "sort": 99999,
      "isDisplay": true,
      "type": 1
    },
    {
      "roleID": 10911519,
      "name": "全体成员",
      "description": "域的默认身份组",
      "sort": 1,
      "isDisplay": false,
      "type": 2
    }
  ],
  "areaRoleInfos": {
    "maxRole": 10911517,
    "roles": [10911517, 19507623, 10911519],
    "privilegeKeys": ["MANAGE_GROUP", "MANAGE_CHANNEL", "..."],
    "categoryKeys": ["MESSAGE", "AREA", "MEMBER"],
    "isOwner": false
  },
  "homePageChannelId": "主页频道ID"
}
```

**roleList 字段说明：**

| 字段 | 说明 |
|------|------|
| `roleID` | 身份组 ID（与 members 接口中的 `role` 对应） |
| `name` | 身份组名称 |
| `sort` | 排序权重（与 members 接口中的 `roleSort` 对应） |
| `isDisplay` | 是否在成员列表中单独分组显示 |
| `type` | `1` = 域主，`2` = 默认身份组，`3` = 自定义身份组 |

**areaRoleInfos：** 当前用户在域内的权限信息。

> 此接口返回的 `roleList` 可与 `/area/v3/members` 接口的 `role` 字段配合使用，将身份组 ID 映射为名称。`/area/v2/info` 是旧版兼容路径，新集成应使用 v3。

### 修改域名称

```http
PUT /client/v1/area/v1/areaSettings/v1/editAreaName
```

```json
{
  "area": "域ID",
  "name": "新域名称"
}
```

这是需要域管理权限的写操作。

### 获取域频道列表

```
GET /client/v1/area/v1/detail/v1/channels?area={area}
```

**响应 data：**

```json
[
  {
    "id": "分组ID",
    "name": "分组名称",
    "channels": [
      {
        "id": "频道ID",
        "name": "频道名称",
        "type": "TEXT",
        "secret": false
      }
    ]
  }
]
```

| 字段 | 说明 |
|------|------|
| `type` | `TEXT`（文字频道）、`VOICE`（语音频道） |
| `secret` | 是否为私密频道（由 `accessControlEnabled` 派生） |

### 创建频道

```
POST /client/v1/area/v1/channel/v1/create
```

**请求体（通用）：**

```json
{
  "area": "域ID",
  "group": "分组ID",
  "name": "频道名称",
  "type": "TEXT 或 VOICE",
  "secret": false,
  "maxMember": 100
}
```

**请求体（临时语音频道）：**

```json
{
  "area": "域ID",
  "group": "分组ID",
  "name": "频道名称",
  "type": "VOICE",
  "secret": false,
  "maxMember": 人数上限,
  "isTemp": true
}
```

**说明：** 需域内管理员权限。`group` 为频道所在分组 ID（可从「获取域频道列表」响应中的分组 `id` 取得）。可选字段 `vender`、`maxMember`（不传时由服务端默认）。`secret` 控制创建时是否为私密频道。

### 复制频道

```
POST /area/v1/channel/v1/copy
```

**请求体：**

```json
{
  "area": "域ID",
  "channel": "被复制的频道ID",
  "name": "新频道名称"
}
```

### 删除频道

```
DELETE /client/v1/area/v1/channel/v1/delete?area={area}&channel={channel}
```

**参数：**

| 参数 | 说明 |
|------|------|
| `area` | 域 ID |
| `channel` | 要删除的频道 ID |

**说明：** 需域内管理员权限。

### 获取频道设置信息

```
GET /area/v3/channel/setting/info?channel={channel}
```

**参数：**

| 参数 | 说明 |
|------|------|
| `channel` | 频道 ID |

**说明：** query 仅需 `channel`。返回频道名称、类型、权限、文字/语音控制、人数上限和密码等设置。读取响应中的可见身份组字段通常为 `accessibleRoles`，编辑请求中则为 `accessible`。部分未配置字段可能被服务端省略。

### 编辑频道设置（频道权限）

```
POST /area/v3/channel/setting/edit
```

**请求体：**

```json
{
  "area": "域ID",
  "channel": "频道ID",
  "name": "频道名称",
  "textGapSecond": 0,
  "voiceQuality": "质量档位",
  "voiceDelay": "延迟档位",
  "maxMember": 人数上限,
  "voiceControlEnabled": true,
  "textControlEnabled": true,
  "textRoles": [],
  "voiceRoles": [],
  "accessControlEnabled": false,
  "accessible": [],
  "accessibleMembers": [],
  "secret": false,
  "hasPassword": false,
  "password": ""
}
```

**字段说明：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `channel` | string | 频道 ID |
| `area` | string | 域 ID |
| `name` | string | 频道名称 |
| `textGapSecond` | int | 慢速模式间隔（秒），0 为关闭 |
| `voiceQuality` | string | 语音质量：`32k` / `64k` / `128k` |
| `voiceDelay` | string | 语音延迟：`LOW` / `NORMAL` / `HIGH` |
| `maxMember` | int | 人数上限，默认 30000 |
| `voiceControlEnabled` | bool | 是否启用语音发言权限控制 |
| `textControlEnabled` | bool | 是否启用文字发言权限控制 |
| `textRoles` | int[] | 有文字发言权限的角色 ID 列表 |
| `voiceRoles` | int[] | 有语音发言权限的角色 ID 列表 |
| `accessControlEnabled` | bool | 是否启用访问控制（私密频道核心字段） |
| `accessible` | int[] | 有访问权限的身份组 ID；读取响应可能名为 `accessibleRoles` |
| `accessibleMembers` | string[] | 有访问权限的成员 UID 列表 |
| `secret` | bool | 频道是否标记为私密 |
| `hasPassword` | bool | 是否启用频道密码 |
| `password` | string | 频道密码（仅 `hasPassword` 为 true 时有效） |

**说明：** 需域内管理员权限。这是“完整设置对象”接口：应先读取现有设置，覆盖要修改的字段，再发送全量请求体。`accessible` 必须使用编辑接口要求的字段名；不应把读取响应的 `accessibleRoles` 原样发回。

> **重要：`secret` 与 `accessControlEnabled` 的关系**
>
> `secret` 是由平台根据 `accessControlEnabled` 派生的只读字段。当 `accessControlEnabled` 为 `true` 时，平台会强制 `secret` 为 `true`，忽略请求中显式传入的 `secret: false`。因此：
> - 要将频道设为私密：需设置 `accessControlEnabled: true`（`secret` 会自动变为 `true`）
> - 要取消私密：需设置 `accessControlEnabled: false` 并清空 `accessible` / `accessibleMembers`
> - 单独修改 `secret` 而不同步 `accessControlEnabled` 不会生效

### 进入域

```
POST /client/v1/area/v1/enter?area={area}&recover={recover}
```

进入指定域（进入语音频道前的必要步骤）。`recover` 为 `true`/`false`。

请求同时携带 query 和同值 JSON body：

```json
{"area": "域ID", "recover": false}
```

### 退出域

```
DELETE /client/v1/area/v1/quit?area={area}
```

**Query 参数：**

| 参数 | 说明 |
|------|------|
| `area` | 要退出的域 ID |

**请求体：** 无。

**说明：** `area` 必须作为 query 参数发送；不要放入 JSON body。将 `{"area":"域ID"}` 放入 body 时，服务端可能返回成功形状的响应，但账号不会实际退出域。

### 进入频道

```
POST /area/v2/channel/enter
```

**请求体（文字频道）：**

```json
{
  "type": "TEXT",
  "area": "域ID",
  "channel": "频道ID"
}
```

**请求体（语音频道）：**

```json
{
  "type": "VOICE",
  "area": "域ID",
  "channel": "频道ID",
  "fromChannel": "切换前的语音频道ID（首次进入留空）",
  "fromArea": "切换前的域ID（首次进入留空）",
  "password": "",
  "sign": 1,
  "pid": ""
}
```

> 进入语音频道前，需先调用「进入域」接口。`type` 字段必填，否则返回"服务异常"。

**响应 data：**

```json
{
  "voiceQuality": "语音质量",
  "voiceDelay": "语音延迟",
  "roleSort": 0,
  "disableTextTo": 0,
  "disableVoiceTo": 0,
  "supplier": "AGORA_0",
  "supplierSign": "Agora Token（语音频道时返回）",
  "roomId": "房间ID"
}
```

### 退出语音频道

```
DELETE /client/v1/area/v1/member/v1/removeFromChannel?area={area}&channel={channel}&target={uid}
```

**参数：**

| 参数 | 说明 |
|------|------|
| `area` | 域 ID |
| `channel` | 语音频道 ID |
| `target` | 要移出的用户 UID（自己退出填自己的 UID） |

**成功响应：**

```json
{"status": true, "data": true, "message": "", "error": "", "code": ""}
```

> 也可用于管理员将他人移出语音频道。

### 调度成员到语音频道（拖拽）

```
PUT /client/v1/area/v1/member/v1/dragInto
```

**请求体：**

```json
{
  "area": "域ID",
  "channel": "用户当前所在语音频道ID（源）",
  "toChannel": "目标语音频道ID",
  "target": "被调度用户的UID"
}
```

**成功响应：**

```json
{"status": true, "data": true, "message": null, "error": null, "code": "200"}
```

**说明：** 管理员将其他成员从其当前语音频道拖拽（调度）到另一个语音频道，需管理员权限。`channel` 为用户当前所在的语音频道，调用前可用「获取语音频道在线成员」接口探测。

---

## 成员 API

### 获取域管理日志

```http
GET /client/v1/area/v1/operateLogs?area={area}&offset={offset}&opTypes={opTypes}
```

**参数：**

| 参数 | 说明 |
|------|------|
| `area` | 域 ID |
| `offset` | 非负偏移量，首页传 `0` |
| `opTypes` | JSON 数组字符串；域成员通知轮询传 `["AREA_SUBSCRIBE","AREA_UNSUBSCRIBE"]` |

响应 `data.logs` 为日志列表。成员变更记录的常见字段为 `optUid`（部分响应可为 `uid` / `person`）、`content` 和 `createTime`（部分响应可为 `time` / `timestamp`）。`content` 为 `加入域` 或 `退出域` 时表示成员变更。

> 该接口需要有效登录态及相应域权限；无权访问可返回 HTTP 401。

### 获取域成员列表（含在线状态）

```
GET /area/v3/members?area={area}&offsetStart={start}&offsetEnd={end}
```

**参数：**

| 参数 | 说明 |
|------|------|
| `area` | 域 ID |
| `offsetStart` | 起始偏移（默认 0） |
| `offsetEnd` | 结束偏移（默认 49） |

**响应 data：**

```json
{
  "members": [
    {
      "uid": "用户UID",
      "role": 10911515,
      "roleSort": 99999,
      "online": 1,
      "roleStatus": 10911515,
      "playingState": "明明就",
      "displayType": "MUSIC"
    }
  ],
  "roleCount": [
    {"role": 10911515, "count": 1},
    {"role": -1, "count": 14}
  ],
  "totalCount": 17
}
```

**members 字段说明：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `uid` | string | 用户 UID |
| `role` | int | 用户当前最高身份组 ID |
| `roleSort` | int | 身份组排序权重（越大越靠前） |
| `online` | int | 在线状态：`1` = 在线，`0` = 离线 |
| `roleStatus` | int | 在线时等于 `role`；离线时为 `-1` |
| `playingState` | string | 正在做的事情（如歌曲名、游戏名），空串表示无 |
| `displayType` | string | 活动类型：`"MUSIC"` = 听音乐，`""` = 无活动 |

**roleCount 字段说明：**

| 字段 | 说明 |
|------|------|
| `role` | 身份组 ID；`-1` 表示离线 |
| `count` | 该身份组当前在线人数；`role=-1` 时为离线总人数 |

**totalCount：** 域内成员总数。

> Web 端右侧成员面板即通过此接口获取数据，按 `roleSort` 降序排列，在线成员在前、离线成员在后。
> 此接口会被 Web 端定期轮询以刷新在线状态。

### 移出域（踢出用户）

```
POST /area/v3/remove
```

**JSON 请求体：**

```json
{
  "area": "域ID",
  "target": "用户UID"
}
```

**说明：** 将指定用户从当前域移出（踢出域），需管理员权限。`area` / `target` 只放在 JSON body，不在 query 中重复。

### 封禁用户（加入域封禁列表）

```
DELETE /client/v1/area/v1/block?area={area}&target={uid}
```

**参数：** `area`（域 ID）、`target`（要封禁的用户 UID）。无请求体。

**说明：** 将用户加入域封禁列表，同时踢出域。封禁后该用户无法再加入此域，直到解除封禁。

### 获取域封禁列表

```
GET /client/v1/area/v1/areaSettings/v1/blocks?area={area}&name={name}
```

**参数：**

| 参数 | 说明 |
|------|------|
| `area` | 域 ID |
| `name` | 可选，搜索关键词（空则返回全部） |

**说明：** 解除域内封禁前可先调用此接口查看当前封禁用户列表。

### 解除域内封禁（从域封禁列表移除）

```
PATCH /client/v1/area/v1/unblock?area={area}&target={uid}
```

**参数：** `area`、`target`（要解除封禁的用户 UID）。只发送 query，无请求体。

**说明：** 从域封禁列表中移除用户，允许其再次加入该域。可先通过「获取域封禁列表」查看当前封禁用户。

### 获取语音频道在线成员

```
POST /area/v3/channel/membersByChannels
```

**请求体：**

```json
{
  "area": "域ID",
  "channels": ["频道ID1", "频道ID2"]
}
```

**响应 data：**

```json
{
  "channelMembers": {
    "频道ID1": [
      {"uid": "用户UID", "isBot": false}
    ],
    "频道ID2": []
  }
}
```

### 获取用户域内角色/禁言状态

```
GET /area/v3/userDetail?area={area}&target={uid}
```

**响应 data：**

```json
{
  "list": [
    {"roleID": 1, "name": "管理员"}
  ],
  "higherUid": "",
  "now": 1787594400000
}
```

`list`、`higherUid` 和 `now` 为常见字段。如用户正在被限制，响应还可包含 `disableTextTo` / `disableVoiceTo`（禁言/禁麦到期毫秒时间戳）；未设置时服务端可直接省略，不应假定一定返回 `0`。

### 获取可分配角色列表

```
GET /area/v3/role/canGiveList?area={area}&target={uid}
```

**参数：**

| 参数 | 说明 |
|------|------|
| `area` | 域 ID |
| `target` | 目标用户 UID（要为其分配身份组的用户） |

**响应 data：**

```json
{
  "roles": [
    {"roleID": 1, "name": "角色名", "owned": false, "sort": 0}
  ]
}
```

> `owned` 表示目标用户是否已拥有该角色。

### 编辑用户身份组（给/取消身份组）

```
POST /area/v3/role/editUserRole
```

将目标用户在当前域内的身份组**设置为**指定列表（全量覆盖）。给身份组 = 在现有列表上追加；取消身份组 = 从现有列表中移除后提交。

**请求体：**

```json
{
  "area": "域ID",
  "target": "目标用户UID",
  "targetRoleIDs": [3829292, 1234567]
}
```

| 字段 | 说明 |
|------|------|
| `area` | 域 ID |
| `target` | 目标用户 UID |
| `targetRoleIDs` | 该用户在该域下应拥有的身份组 ID 列表（整型数组）。需先通过 `GET /area/v3/userDetail` 获取当前列表，再根据「添加」或「移除」操作增删后传入。 |

**说明：** 与 Web 端行为一致。添加身份组时：先调 `userDetail` 取当前 `list` 的 `roleID` 列表，追加新 `roleID` 后作为 `targetRoleIDs` 提交；取消时则从列表中移除对应 `roleID` 后提交。

### 批量获取用户域内昵称

```http
POST /area/v2/getUserAreaNicknames
```

```json
{
  "area": "域ID",
  "uids": ["用户UID1", "用户UID2"]
}
```

响应 `data.nicknames` 为 `UID -> 域内昵称` 的对象；没有设置域内昵称时可返回空对象。

---

## 用户信息 API

### 获取用户信息（批量）

```
POST /client/v1/person/v1/personInfos
```

**请求体：**

```json
{
  "persons": ["UID1", "UID2"],
  "commonIds": []
}
```

**响应 data：**

```json
[
  {
    "uid": "用户UID",
    "pid": "公开ID（如 824778414）",
    "name": "昵称",
    "status": "ENABLED",
    "personType": "PERSON",
    "personRole": "NORMAL",
    "avatar": "头像URL",
    "online": true,
    "badges": null,
    "avatarFrame": "",
    "avatarFrameAnimation": "",
    "avatarFrameExpireTime": 0,
    "mark": "",
    "markName": "",
    "markExpireTime": 0,
    "introduction": "",
    "userCommonId": "公开ID"
  }
]
```

**字段说明：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `uid` | string | 用户 UID |
| `pid` | string | 公开 ID（数字字符串） |
| `name` | string | 昵称 |
| `status` | string | 账号状态（`ENABLED` / `DISABLED`） |
| `personType` | string | 用户类型（`PERSON`） |
| `personRole` | string | 用户角色（`NORMAL`） |
| `avatar` | string | 头像 URL（带签名） |
| `online` | boolean | 在线状态：`true` / `false` |
| `badges` | array\|null | 徽章列表 |
| `avatarFrame` | string | 头像框 URL |
| `mark` | string | 标记 |
| `markName` | string | 标记名称 |
| `introduction` | string | 个人简介 |
| `userCommonId` | string | 公开 ID（同 `pid`） |

### 获取用户详细资料

```
GET /client/v1/person/v1/personDetail?uid={uid}
```

返回比 `personInfos` 更详细的信息，含 VIP、IP 属地、徽章等。

### 获取自身详细资料

```
GET /client/v1/person/v2/selfDetail?uid={uid}
```

返回当前登录用户的完整资料。

**响应 data：**

```json
{
  "uid": "用户UID",
  "pid": "公开ID",
  "name": "昵称",
  "phone": "167****1220",
  "avatar": "头像URL",
  "banner": "个人主页横幅URL",
  "online": true,
  "introduction": "",
  "stealth": false,
  "status": "ENABLED",
  "personType": "PERSON",
  "personRole": "NORMAL",
  "ipAddress": "IP",
  "defaultAvatar": false,
  "defaultName": false,
  "displayPlayingState": true,
  "playingState": "",
  "playingTime": 0,
  "playingGameImage": "",
  "musicState": "",
  "songState": "",
  "displayType": "",
  "userLevel": 1,
  "likeCount": 0,
  "mutualFollowCount": 0,
  "followCount": 0,
  "fansCount": 0,
  "badges": [],
  "avatarFrame": "",
  "mark": "",
  "greeting": "你已加入Oopz 1 天"
}
```

**关键字段说明：**

| 字段 | 说明 |
|------|------|
| `online` | 是否在线（`true` / `false`） |
| `stealth` | 是否隐身模式 |
| `ipAddress` | IP 归属地 |
| `displayPlayingState` | 是否对外展示正在播放状态 |
| `playingState` | 正在播放/游戏内容 |
| `displayType` | 活动类型（`MUSIC` 等） |
| `userLevel` | 用户等级 |
| `greeting` | 加入平台天数提示 |

### 修改自己的个人简介

```http
PUT /client/v1/person/v1/introduction
```

```json
{"introduction": "新的个人简介"}
```

这是写操作，需要当前用户的有效登录态。

### 好友与好友请求

| 用途 | 方法 | 路径 | 请求数据 |
|------|------|------|------|
| 好友列表 | GET | `/client/v1/list/v1/friendship` | 无 |
| 好友请求列表 | GET | `/client/v1/friendship/v1/requests` | 无 |
| 同意/拒绝好友请求 | POST | `/client/v1/friendship/v1/response` | JSON body |

好友请求响应的 `data.requests` 项包含 `friendRequestId`、`uid`、`createTime`。处理请求的 body：

```json
{
  "agree": true,
  "friendRequestId": 123,
  "target": "对方UID"
}
```

同意/拒绝好友请求是写操作，请求体中的 `friendRequestId` 必须与 `target` 对应。

### 用户备注名

```http
GET /person/v1/remarkName/getUserRemarkNames?uid={uid}
```

响应 `data.userRemarkNames` 为 `[{"uid":"...","remarkName":"..."}]`。

```http
POST /person/v1/remarkName/setUserRemarkName
```

```json
{"remarkUid": "目标UID", "remarkName": "备注名"}
```

设置空字符串可用于清除备注名。

### 获取用户等级信息

```
GET /user_points/v1/level_info
```

**响应 data：**

```json
{
  "currentLevel": 5,
  "currentLevelFullPoints": 500,
  "nextLevel": 6,
  "nextLevelDistance": 100,
  "payPoints": 0,
  "signInPoints": 500,
  "hasNotReceivePrize": false,
  "authState": 0,
  "authDesc": ""
}
```

旧版字段 `currentPoints`、`totalPoints`、`currentExp`、`totalExp` 已不在当前响应中。

---

## 管理 API

### 禁言用户

```
PATCH /client/v1/area/v1/member/v1/disableText?area={area}&target={uid}&intervalId={intervalId}
```

> 只发送 query，无请求体。

**intervalId 映射（禁言）：**

| intervalId | 时长 |
|------------|------|
| `1` | 60 秒 |
| `2` | 5 分钟 |
| `3` | 1 小时 |
| `4` | 1 天 |
| `5` | 3 天 |
| `6` | 7 天 |

**成功响应：**

```json
{"status": true, "data": true, "message": "\"用户名\"已被禁言5分钟", "error": null, "code": "SCC.001.00019"}
```

### 解除禁言

```
PATCH /client/v1/area/v1/member/v1/recoverText?area={area}&target={uid}
```

> 只发送 query，无请求体。

### 禁麦用户

```
PATCH /client/v1/area/v1/member/v1/disableVoice?area={area}&target={uid}&intervalId={intervalId}
```

> 只发送 query，无请求体。

**intervalId 映射（禁麦）：**

| intervalId | 时长 |
|------------|------|
| `7` | 60 秒 |
| `8` | 5 分钟 |
| `9` | 1 小时 |
| `10` | 1 天 |
| `11` | 3 天 |
| `12` | 7 天 |

### 解除禁麦

```
PATCH /client/v1/area/v1/member/v1/recoverVoice?area={area}&target={uid}
```

> 只发送 query，无请求体。

---

## 其他 API

### 每日一句

```
GET /general/v1/speech
```

**响应 data：**

```json
{
  "words": "名言内容",
  "author": "作者"
}
```

---

## 通用响应格式

大多数 Gateway 业务 API 响应遵循以下 envelope（包裹）格式：

```json
{
  "status": true,
  "data": {},
  "message": "",
  "error": "",
  "code": ""
}
```

| 字段 | 说明 |
|------|------|
| `status` | `true` 成功，`false` 失败 |
| `data` | 业务数据 |
| `message` | 成功时的提示信息 |
| `error` | 失败时的错误信息 |
| `code` | 业务状态码 |

不要把该格式当作全局强制契约：例如签名上传 URL 接口和部分登录接口可返回不同结构。

---

## 接口索引

以下路径默认相对于 `https://gateway.oopz.cn`。详细参数与请求体见前文对应章节。

### 消息与会话

| 方法 | 路径 | 用途 |
|------|------|------|
| PATCH | `/client/v1/chat/v1/to` | 打开/切换私信会话 |
| POST | `/im/session/v2/sendGimMessage` | 发送频道消息（首选） |
| POST | `/im/session/v1/sendGimMessage` | 发送频道消息（兼容） |
| POST | `/im/session/v2/sendImMessage` | 发送私信（首选） |
| POST | `/im/session/v1/sendImMessage` | 发送私信（兼容） |
| POST | `/im/session/v1/recallGim` | 撤回频道消息 |
| POST | `/im/session/v1/recallIm` | 撤回私信 |
| GET | `/im/session/v2/messageBefore` | 获取历史消息 |
| POST | `/im/session/v1/messageTop` | 置顶/取消置顶频道消息 |
| POST | `/im/session/v1/gimReaction` | 频道消息表情反应 |
| POST | `/im/session/v1/gimReactions` | 批量查询频道消息反应 |
| GET | `/im/session/v2/gimReactionPersons` | 查询频道消息反应用户 |
| POST | `/im/session/v1/imReaction` | 私信表情反应 |
| POST | `/im/session/v1/imReactions` | 批量查询私信反应 |
| GET | `/im/session/v2/imReactionPersons` | 查询私信反应用户 |
| POST | `/im/session/v1/saveReadStatus` | 保存会话已读状态 |
| POST | `/client/v1/interaction/v1/send` | 发送语音频道互动 |

### 域、频道与成员

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/userSubscribeArea/v1/list` | 已加入域列表 |
| GET | `/invite/v1/codeDetail` | 邀请短码详情 |
| GET | `/area/v3/info` | 域详情 |
| GET | `/area/v3/members` | 域成员列表 |
| GET | `/client/v1/area/v1/detail/v1/channels` | 域频道列表 |
| PUT | `/client/v1/area/v1/areaSettings/v1/editAreaName` | 修改域名称 |
| POST | `/client/v1/area/v1/enter` | 进入域 |
| DELETE | `/client/v1/area/v1/quit` | 退出域 |
| POST | `/client/v1/area/v1/channel/v1/create` | 创建频道 |
| DELETE | `/client/v1/area/v1/channel/v1/delete` | 删除频道 |
| POST | `/area/v1/channel/v1/copy` | 复制频道 |
| GET | `/area/v3/channel/setting/info` | 获取频道设置 |
| POST | `/area/v3/channel/setting/edit` | 编辑频道设置 |
| POST | `/area/v2/channel/enter` | 进入频道 |
| DELETE | `/client/v1/area/v1/member/v1/removeFromChannel` | 退出/移出语音频道 |
| POST | `/area/v3/channel/membersByChannels` | 按频道获取语音成员 |
| PUT | `/client/v1/area/v1/member/v1/dragInto` | 调度成员到语音频道 |
| GET | `/client/v1/area/v1/operateLogs` | 域管理日志 |
| GET | `/area/v3/userDetail` | 用户域内详情 |
| GET | `/area/v3/role/canGiveList` | 可分配身份组 |
| POST | `/area/v3/role/editUserRole` | 编辑用户身份组 |
| POST | `/area/v2/getUserAreaNicknames` | 批量获取域内昵称 |
| POST | `/area/v3/remove` | 将成员移出域 |
| DELETE | `/client/v1/area/v1/block` | 封禁域成员 |
| GET | `/client/v1/area/v1/areaSettings/v1/blocks` | 域封禁列表 |
| PATCH | `/client/v1/area/v1/unblock` | 解除域封禁 |
| PATCH | `/client/v1/area/v1/member/v1/disableText` | 禁言 |
| PATCH | `/client/v1/area/v1/member/v1/recoverText` | 解除禁言 |
| PATCH | `/client/v1/area/v1/member/v1/disableVoice` | 禁麦 |
| PATCH | `/client/v1/area/v1/member/v1/recoverVoice` | 解除禁麦 |

### 用户与好友

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | `/client/v1/person/v1/personInfos` | 批量获取用户信息 |
| GET | `/client/v1/person/v1/personDetail` | 获取用户详细资料 |
| GET | `/client/v1/person/v2/selfDetail` | 获取当前用户详细资料 |
| PUT | `/client/v1/person/v1/introduction` | 修改个人简介 |
| GET | `/client/v1/list/v1/friendship` | 好友列表 |
| GET | `/client/v1/friendship/v1/requests` | 好友请求列表 |
| POST | `/client/v1/friendship/v1/response` | 同意/拒绝好友请求 |
| GET | `/person/v1/remarkName/getUserRemarkNames` | 查询用户备注名 |
| POST | `/person/v1/remarkName/setUserRemarkName` | 设置用户备注名 |
| GET | `/user_points/v1/level_info` | 当前用户等级与积分 |

### 通用与媒体

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/general/v1/speech` | 每日一句 |
| PUT | `/rtc/v1/cos/v1/signedUploadUrl` | 获取对象存储签名上传 URL |

### Web 客户端补充路径

下列路径存在于当前 Web 客户端，但本文档暂未给出完整请求/响应字段：

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/health` | Gateway 健康检查 |
| GET | `/general/v3/settings` | 通用设置 |
| POST | `/im/session/v1/sessions` | 会话列表 |
| POST | `/im/session/v1/areasUnread` | 域未读数 |
| POST | `/im/session/v1/areasMentionUnread` | 域 @ 未读数 |
| GET | `/diamond/v1/remain` | 钻石余额 |
| GET | `/shop/v1/preview` | 商店预览 |
| GET | `/uni/advertisement/v1/list` | 广告列表 |
| GET | `/uni/officialSticker/v2/list` | 官方贴纸列表 |

### Web 请求头样例

| Header | 说明 | 示例值 |
|--------|------|--------|
| `content-type` | JSON 类型 | `application/json;charset=utf-8` |
| `origin` | Web 来源 | `https://web.oopz.cn` |
| `oopz-app-version-number` | 当前客户端版本号 | `<client-version>` |
| `oopz-channel` | 渠道 | `Web` |
| `oopz-device-id` | 设备 ID | `<device-uuid>` |
| `oopz-platform` | 平台 | `windows` |
| `oopz-request-id` | 每次请求唯一的 UUID | `<request-uuid>` |
| `oopz-sign` | 请求签名 | `<base64-signature>` |
| `oopz-time` | 毫秒时间戳 | `<timestamp-ms>` |
| `oopz-web` | 是否 Web | `true` |
| `oopz-person` | 当前用户 UID | `<person-uid>` |
| `oopz-signature` | 登录 JWT | `<jwt>` |

`oopz-app-version-number` 应跟随当前客户端，不应固定为历史版本号。`area/v3/channel/setting/info` 的 query 只需 `channel`，不需要 `area`。
