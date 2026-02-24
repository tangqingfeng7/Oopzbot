# Oopz 平台 API 参考

本文档整理了 Bot 中已知并使用的所有 Oopz 平台 API。

## 基础信息

| 项目 | 值 |
|------|-----|
| Gateway API | `https://gateway.oopz.cn` |
| Public API | `https://api.oopz.cn` |
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
sign_data = MD5(url_path + body_json) + timestamp_ms
signature = Base64(RSA_PKCS1v15_SHA256(sign_data, private_key))
```

---

## WebSocket 协议

### 连接

```
URL: wss://ws.oopz.cn
```

### 事件类型

| event | 说明 |
|-------|------|
| `253` | 认证 |
| `254` | 心跳 |
| `1` | 服务端 serverId 确认 |
| `9` | 聊天消息 |

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

收到 `serverId` 后发送首次心跳，之后每 10 秒发送一次。收到心跳响应中 `r=1` 时立即回复心跳。

```json
{
  "time": "毫秒时间戳",
  "body": "{\"person\":\"UID\"}",
  "event": 254
}
```

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

### 发送消息

```
POST /im/session/v1/sendGimMessage
```

**请求体：**

```json
{
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
  "text": "消息文本",
  "attachments": []
}
```

**图片消息 text 格式：** `![IMAGEw{宽}h{高}]({fileKey})`

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
| 本 Bot 默认 | `OopzSender.send_message` 默认使用 `styleTags: ["IMPORTANT"]`，即所有 Bot 发送的消息均为公告样式 |
| 关闭公告样式 | 调用时显式传入 `styleTags=[]` 即可恢复为普通气泡 |
| 正文排版 | 客户端支持 `**粗体**`、`*斜体*` 等 Markdown 式渲染（以实际展示为准） |

### 撤回消息

```
POST /im/session/v1/recallGim?area={area}&channel={channel}&messageId={messageId}&timestamp={timestamp}&target={target}
```

> 参数同时放在 query string 和 JSON body 中。

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
    "owner": "域主UID"
  }
]
```

### 获取域详情

```
GET /area/v2/info?area={area}
```

返回域的详细信息，含角色列表、主页频道等。

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
        "type": "TEXT"
      }
    ]
  }
]
```

`type` 可选值：`TEXT`（文字频道）、`VOICE`（语音频道）

### 进入域

```
POST /client/v1/area/v1/enter?area={area}&recover={recover}
```

进入指定域（进入语音频道前的必要步骤）。`recover` 为 `true`/`false`。

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

---

## 成员 API

### 获取域成员列表

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
      "online": 1,
      "playingState": "正在玩的游戏"
    }
  ]
}
```

### 移出域（踢出用户）

```
POST /area/v3/remove?area={area}&target={uid}
```

**参数：**

| 参数 | 说明 |
|------|------|
| `area` | 域 ID |
| `target` | 被移出用户的 UID |

**请求体（与 query 一致）：**

```json
{
  "area": "域ID",
  "target": "用户UID"
}
```

**说明：** 将指定用户从当前域移出（踢出域），需管理员权限。

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

**参数：** `area`、`target`（要解除封禁的用户 UID）。请求体与 query 一致。

**说明：** 从域封禁列表中移除用户，允许其再次加入该域。可先通过「获取域封禁列表」查看当前封禁用户。

### 搜索域成员

```
POST /area/v3/search/areaSettingMembers
```

**请求体：**

```json
{
  "area": "域ID",
  "name": "搜索关键词",
  "offset": 0,
  "limit": 50
}
```

**响应 data：**

```json
{
  "members": [
    {
      "uid": "用户UID",
      "roleInfos": [{"name": "角色名", "roleID": 1}],
      "enterTime": 1700000000000
    }
  ]
}
```

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
  "disableTextTo": 0,
  "disableVoiceTo": 0,
  "higherUid": ""
}
```

> `disableTextTo` / `disableVoiceTo` 为禁言/禁麦到期时间（毫秒时间戳），`0` 表示未禁言。

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
    "name": "昵称",
    "online": true,
    "introduction": "简介",
    "ipAddress": "IP属地",
    "personType": "类型",
    "playingState": "正在玩",
    "avatar": "头像URL",
    "personVIPEndTime": 0,
    "badges": []
  }
]
```

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

### 获取用户等级信息

```
GET /user_points/v1/level_info
```

**响应 data：**

```json
{
  "currentLevel": 5,
  "nextLevel": 6,
  "nextLevelDistance": 100,
  "currentPoints": 500,
  "totalPoints": 1200,
  "currentExp": 800,
  "totalExp": 2000
}
```

---

## 管理 API

### 禁言用户

```
PATCH /client/v1/area/v1/member/v1/disableText?area={area}&target={uid}&intervalId={intervalId}
```

> 参数同时放在 query string 和 JSON body 中。

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

### 禁麦用户

```
PATCH /client/v1/area/v1/member/v1/disableVoice?area={area}&target={uid}&intervalId={intervalId}
```

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

所有 API 响应遵循统一格式：

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
