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

**Web 端补充（带 @ 用户）：**

Web 端还可见到 `v2` 包裹格式的频道消息请求：

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

### 私信 API（IM）

以下接口为「私信用户」流程所用，通过 Playwright 抓包自 Web 端（https://web.oopz.cn/）。请求签名与通用规则一致，需携带 Oopz 系列 Header。

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

发送一条私信。与房间消息不同：私信使用 `sendImMessage`（v2），房间消息使用 `sendGimMessage`（v1）；私信请求体为 **`message` 包裹**，正文字段为 **`content`**（与 Web 端 Playwright 抓包一致）。

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

上报该私信会话的已读状态（Playwright 抓包）。

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

> 此接口返回的 `roleList` 可与 `/area/v3/members` 接口的 `role` 字段配合使用，将身份组 ID 映射为名称。旧版 `/area/v2/info` 仍可用但建议使用 v3。

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

**说明：** Web 端抓包中仅要求 `channel`。返回频道当前设置（名称、权限、文字/语音控制、人数上限、密码等），用于编辑前拉取。响应 `data` 的字段与编辑接口请求体一致（含 `secret`、`accessControlEnabled`、`accessibleMembers` 等）。注意：部分字段可能在频道未配置时缺失，使用时应设置默认值。

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
| `accessible` | array | 有访问权限的身份组 |
| `accessibleMembers` | string[] | 有访问权限的成员 UID 列表 |
| `secret` | bool | 频道是否标记为私密 |
| `hasPassword` | bool | 是否启用频道密码 |
| `password` | string | 频道密码（仅 `hasPassword` 为 true 时有效） |

**说明：** 需域内管理员权限。所有字段均为必填（`accessible` 为必填字段，缺少会返回验证错误）。

> **重要：`secret` 与 `accessControlEnabled` 的关系**
>
> 经实测，`secret` 是由平台根据 `accessControlEnabled` 派生的只读字段。当 `accessControlEnabled` 为 `true` 时，平台会强制 `secret` 为 `true`，忽略请求中显式传入的 `secret: false`。因此：
> - 要将频道设为私密：需设置 `accessControlEnabled: true`（`secret` 会自动变为 `true`）
> - 要取消私密：需设置 `accessControlEnabled: false` 并清空 `accessible` / `accessibleMembers`
> - 单独修改 `secret` 而不同步 `accessControlEnabled` 不会生效

### 搜索可添加的私密成员

```
GET /area/v3/search/areaPrivateSettingMembers?area={area}&keyword={keyword}&page={page}
```

**参数：**

| 参数 | 说明 |
|------|------|
| `area` | 域 ID |
| `keyword` | 搜索关键词，可为空 |
| `page` | 页码（如 `1`） |

**说明：** Web 端频道权限页中用于搜索并添加「允许访问的成员」。

---

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

---

## Web 端补充

### 抓包接口索引

#### 通用 / 网关

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `https://gateway.oopz.cn/general/v2/curTime` | 当前时间 |
| GET | `https://gateway.oopz.cn/general/v2/settings` | 通用设置 |
| POST | `https://gateway.oopz.cn/general/v2/switch` | 开关配置 |
| GET | `https://gateway.oopz.cn/health` | 健康检查 |
| GET | `https://gateway.oopz.cn/general/v1/speech` | 语音相关 |

#### 登录 / 用户

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `https://gateway.oopz.cn/client/v1/login/v2/login` | 登录（v2） |
| POST | `https://gateway.oopz.cn/client/v1/login/v1/autoLogin` | 自动登录 |
| GET | `https://gateway.oopz.cn/login/v1/loginCheck` | 登录校验 |
| GET | `https://gateway.oopz.cn/client/v1/person/v2/selfDetail?uid=...` | 当前用户详情 |
| GET | `https://gateway.oopz.cn/client/v1/person/v1/personDetail?uid=...` | 用户详情 |
| POST | `https://gateway.oopz.cn/client/v1/person/v1/personInfos` | 批量用户信息（含在线状态） |
| GET | `https://gateway.oopz.cn/client/v1/person/v1/noviceGuide` | 新手引导 |
| GET | `https://gateway.oopz.cn/person/v1/userNoticeSetting/noticeSetting` | 通知设置 |
| GET | `https://gateway.oopz.cn/person/v1/remarkName/getUserRemarkNames?uid=...` | 备注名 |
| GET | `https://gateway.oopz.cn/person/v1/blockCheck?targetUid=...` | 拉黑检查 |
| GET | `https://gateway.oopz.cn/client/v1/person/v1/privacy/v1/query` | 隐私设置查询 |
| GET | `https://gateway.oopz.cn/client/v1/person/v1/notification/v1/query` | 通知查询 |
| GET | `https://gateway.oopz.cn/client/v1/person/v2/realNameAuth` | 实名认证状态 |
| GET | `https://gateway.oopz.cn/client/v1/list/v1/friendship` | 好友列表 |
| GET | `https://gateway.oopz.cn/client/v1/list/v1/blocked` | 黑名单列表 |
| GET | `https://gateway.oopz.cn/client/v1/friendship/v1/requests` | 好友请求 |
| GET | `https://gateway.oopz.cn/user_points/v1/level_info` | 用户等级 |
| GET | `https://gateway.oopz.cn/diamond/v1/remain` | 钻石余额 |
| GET | `https://gateway.oopz.cn/client/v1/settings/v1/mixer` | 混音器设置 |

#### 会话 / IM

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `https://gateway.oopz.cn/im/session/v1/sessions` | 会话列表 |
| POST | `https://gateway.oopz.cn/im/session/v2/sendGimMessage` | 频道消息（Web 抓包，含 @ 用户） |
| GET | `https://gateway.oopz.cn/im/session/v2/messageBefore?area=...&channel=...&size=50` | 历史消息 |
| GET | `https://gateway.oopz.cn/im/session/v2/topMessages?area=...&channel=...` | 置顶消息 |
| POST | `https://gateway.oopz.cn/im/session/v1/areasUnread` | 区域未读数 |
| POST | `https://gateway.oopz.cn/im/session/v1/areasMentionUnread` | @ 未读 |
| POST | `https://gateway.oopz.cn/im/session/v1/saveReadStatus` | 保存已读状态 |
| POST | `https://gateway.oopz.cn/im/session/v1/gimReactions` | 消息表情反应 |
| POST | `https://gateway.oopz.cn/im/session/v1/gimMessageDetails` | 消息详情 |
| GET | `https://gateway.oopz.cn/im/systemMessage/v1/unreadCount` | 系统消息未读数 |
| GET | `https://gateway.oopz.cn/im/systemMessage/v1/messageList?offsetTime` | 系统消息列表 |

#### 区域 / 频道（权限页相关）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `https://gateway.oopz.cn/client/v1/area/v1/enter?area=...&recover=false` | 进入区域 |
| GET | `https://gateway.oopz.cn/area/v3/info?area=...` | 区域信息 |
| GET | `https://gateway.oopz.cn/area/v3/members?area=...&offsetStart=0&offsetEnd=49` | 区域成员列表 |
| GET | `https://gateway.oopz.cn/client/v1/area/v1/detail/v1/channels?area=...` | 频道列表 |
| POST | `https://gateway.oopz.cn/area/v2/channel/enter` | 进入频道 |
| GET | `https://gateway.oopz.cn/area/v3/channel/setting/info?channel=...` | 频道设置信息 |
| POST | `https://gateway.oopz.cn/area/v3/channel/setting/edit` | 编辑频道设置 |
| GET | `https://gateway.oopz.cn/area/v3/search/areaPrivateSettingMembers?area=...&keyword&page=1` | 搜索私密成员 |
| POST | `https://gateway.oopz.cn/client/v1/area/v1/channel/v1/create` | 创建频道 |
| DELETE | `https://gateway.oopz.cn/client/v1/area/v1/channel/v1/delete?channel=...&area=...` | 删除频道 |
| POST | `https://gateway.oopz.cn/area/v2/getUserAreaNicknames` | 获取区域昵称 |
| POST | `https://gateway.oopz.cn/area/v3/channel/membersByChannels` | 频道在线成员（按频道分组） |
| GET | `https://gateway.oopz.cn/area/v3/userDetail?area=...&target=...` | 区域内用户详情 |
| GET | `https://gateway.oopz.cn/area/v3/role/canGiveList?area=...&target=...` | 可授予身份组列表 |
| POST | `https://gateway.oopz.cn/area/v3/role/editUserRole` | 编辑用户身份组 |
| GET | `https://gateway.oopz.cn/client/v1/area/v1/areaSettings/v1/blocks?area=...` | 域封禁列表 |
| PATCH | `https://gateway.oopz.cn/client/v1/area/v1/unblock?area=...&target=...` | 解除域封禁 |
| POST | `https://gateway.oopz.cn/area/v3/remove?area=...&target=...` | 移出域 |

#### 其他

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `https://gateway.oopz.cn/userSubscribeArea/v1/list` | 已加入域列表 |
| POST | `https://tracking.oopz.cn/events/push` | 埋点事件上报 |
| GET | `https://gateway.oopz.cn/task/v1/bounty/list` | 赏金任务列表 |
| GET | `https://gateway.oopz.cn/advertisement/v2/list` | 广告列表 |
| GET | `https://gateway.oopz.cn/discovery/v3/home?needTop=1&areaCount=20` | 发现页首页 |
| GET | `https://gateway.oopz.cn/shop/v1/preview?previewType=DIAMOND` | 商店预览 |
| GET | `https://gateway.oopz.cn/client/v1/interaction/v1/list` | 互动列表 |
| GET | `https://gateway.oopz.cn/client/v1/sticker/v1/list` | 贴纸列表 |
| GET | `https://gateway.oopz.cn/client/v1/roaming/v1/emojis` | 漫游表情 |
| GET | `https://gateway.oopz.cn/im/systemMessage/v1/unreadCount` | 系统消息未读数 |
| GET | `https://gateway.oopz.cn/diamond/v1/remain` | 钻石余额 |

### Web 端请求头样例

所有抓包接口都需要标准 Oopz 头；下表记录了 Web 端常见值，便于复现：

| Header | 说明 | 示例值 |
|--------|------|--------|
| `content-type` | 固定 | `application/json;charset=utf-8` |
| `origin` | 固定 | `https://web.oopz.cn` |
| `oopz-app-version-number` | 应用版本号 | `73817` |
| `oopz-channel` | 渠道 | `Web` |
| `oopz-device-id` | 设备 ID（UUID） | `b2b0ecba-1838-4df0-a63f-e761b43b97af` |
| `oopz-platform` | 平台 | `windows` |
| `oopz-request-id` | 请求唯一 ID | 每次请求不同 |
| `oopz-sign` | 请求签名 | Base64 长字符串 |
| `oopz-time` | 毫秒时间戳 | `1772429988449` |
| `oopz-web` | 是否 Web | `true` |
| `oopz-person` | 当前用户 UID | 登录后必带 |
| `oopz-signature` | JWT | 登录后必带 |

### 备注

- `client/v1/login/v1/autoLogin` 的 `code` 字段即登录 JWT，后续请求放到 `oopz-signature`。
- `im/session/v2/sendGimMessage` 为 Web 端可见的频道消息包裹格式；本 Bot 当前常用实现仍是 `v1/sendGimMessage`。
- `area/v3/channel/setting/info` 的 Web 抓包查询参数仅包含 `channel`，未见必须传 `area`。
