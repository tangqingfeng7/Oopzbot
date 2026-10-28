# Web 播放器说明

Web 播放器是一个独立的歌词与播放控制页面，与 Bot 播放状态通过 Redis 同步，支持歌词滚动、播放队列、喜欢列表、搜索点歌、暂停/切歌/音量等。

---

## 功能概览

| 功能 | 说明 |
|------|------|
| **播放状态** | 当前歌曲、封面、进度条、暂停/播放、与 Bot 实时同步 |
| **歌词** | 自动加载歌词与翻译，高亮当前行；支持**歌词同步**（本地插值 + 手动偏移） |
| **播放队列** | 展示当前 + 待播列表，支持置顶、删除；**防闪烁**（仅数据变化时重绘） |
| **喜欢列表** | 分页浏览网易云喜欢列表；支持**全量搜索**（在全部喜欢中按歌名/歌手/专辑搜索后分页） |
| **搜索点歌** | 关键词搜索歌曲，一键加入队列 |
| **音量** | 滑块调节音量并下发到 Bot；**记忆上次音量**（localStorage 持久化，下次打开恢复） |

---

## 歌词同步

- **本地插值**：进度与歌词高亮按约 150ms 间隔用本地时间插值，避免仅靠 1 秒轮询导致的卡顿与不同步。
- **手动偏移**：点击「同步」可设置歌词整体提前/延后（-1s、-0.5s、+0.5s、+1s、重置），偏移写入 `localStorage`（键 `lyricOffset`），刷新后保留。

---

## 音量记忆

- 调节音量后会写入 `localStorage`（键 `webVolume`）。
- 再次打开或刷新页面时，会优先用本地保存的音量更新界面并下发到 Bot，与上次使用保持一致。

---

## 喜欢列表搜索

- 在「喜欢的音乐」弹层中的搜索框输入关键词，会在**全部喜欢**中搜索（不限于当前页）。
- 后端会拉取全部喜欢歌曲详情，按歌名、歌手、专辑过滤后再分页返回；分页为「搜索结果」的分页。
- 清空搜索框即恢复为普通分页浏览全部喜欢。

---

## 配置

在 `config.py` 的 `WEB_PLAYER_CONFIG` 中设置：

| 配置项 | 说明 |
|--------|------|
| `host` | 监听地址，默认 `0.0.0.0` |
| `port` | 监听端口，默认 `8080` |
| `url` | 对外展示的访问地址，留空则自动检测；使用 Nginx 反代时填写对外域名，如 `https://your-domain.com` |
| `token_ttl_seconds` | Web 随机访问令牌有效期（秒），`0` 表示不过期（不建议） |
| `cookie_max_age_seconds` | 浏览器 cookie 有效期（秒）；未配置时默认与 `token_ttl_seconds` 一致 |
| `cookie_secure` | 仅在 HTTPS 下发送 cookie（使用 Nginx + SSL 时设为 `True`） |
| `send_link_enabled` | 是否在点歌通知中发送播放器链接（默认 `True`） |
| `link_idle_release_seconds` | 播放列表空闲超时后释放随机访问链接（秒，`0` 表示不释放） |
| `admin_enabled` | 是否启用管理后台（访问 `/admin`） |
| `admin_password` | 管理后台登录密码 |
| `admin_session_ttl_seconds` | 后台会话有效期（秒） |
| `admin_cookie_secure` | 后台 cookie 是否仅 HTTPS 发送（使用 Nginx + SSL 时设为 `True`） |
| `trusted_proxy_cidrs` | 允许提供转发头的 TCP 代理网段；默认仅信任 IPv4/IPv6 回环 |

> **注意**：长期配置只认 `config.py`。管理后台(`/admin` -> 配置)保存时会写回 `config.py`，并同步更新当前进程，不需要重启。
> 旧项 `trust_proxy_header` 已移除；配置中仍存在时程序会拒绝启动并给出迁移提示。

---

## Nginx 反向代理

项目分别提供裸机配置 `nginx/nginx.conf` 和 Compose 配置
`nginx/nginx.docker.conf`。两者都通过 Nginx 统一提供 HTTPS (443)，并将
HTTP (80) 自动 301 重定向到 HTTPS。Compose 会固定 Nginx 网络地址并自动
把对应 CIDR 注入 Bot。

### 路由规则

| 路径 | 转发目标 |
|------|----------|
| `/` | Bot Web 播放器 + 管理后台 (`bot:8080`) |
| `/netease-api/` | 网易云音乐 API (`netease-api:3000`) |
| `/admin/api/overview/stream` | SSE 端点，禁用缓冲以保证实时推送 |

### SSL 证书

将证书文件放到 `nginx/ssl/` 目录（已被 `.gitignore` 忽略）：

```
nginx/ssl/cert.pem   # 证书（含完整链）
nginx/ssl/key.pem    # 私钥
```

### 启用 HTTPS 后的配置变更

在 `config.py` 或管理后台中设置：

- `WEB_PLAYER_CONFIG["url"]` = `https://your-domain.com`
- `WEB_PLAYER_CONFIG["cookie_secure"]` = `True`
- `WEB_PLAYER_CONFIG["admin_cookie_secure"]` = `True`

---

## HTTP API

以下为 Web 播放器服务提供的接口，根路径为 `http://<host>:<port>`。

播放器 API 由 `src/web/web_player.py` 提供；Admin 后台 API 由 `src/web/web_player_admin.py`（`APIRouter`）提供；配置管理由 `src/web/web_player_config.py` 集中处理。

### 播放状态

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/status` | 当前播放状态：`playing`、`paused`、歌曲信息、`progress`（秒）、`duration`、`volume` 等 |

无播放时返回 `{"playing": false}`。
说明：`/api/*` 需先通过 Bot 发送的随机链接进入页面（服务端会下发访问 cookie），否则返回 403。

---

### 歌词

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/lyric?id=<song_id>` | 获取指定歌曲的歌词与翻译歌词（LRC），返回 `lyric`、`tlyric` |

---

### 队列

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/queue` | 播放队列，返回 `queue` 数组，每项含 `id`、`name`、`artists`、`cover`、`durationText` |
| POST | `/api/queue/action` | 队列操作。Body: `{"action":"remove"|"top","index":<0-based>}` |

---

### 喜欢列表

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/liked?page=<n>&limit=<n>[&keyword=<kw>]` | 喜欢的音乐。`page`、`limit` 分页；可选 `keyword` 时在**全部喜欢**中搜索后分页返回 |
| POST | `/api/liked/refresh` | 刷新喜欢列表缓存（清空后下次请求重新拉取） |

---

### 搜索与点歌

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/search?keyword=<kw>&limit=<n>` | 搜索歌曲，返回 `results` 数组 |
| POST | `/api/add` | 添加歌曲到队列。Body: `{"id", "name", "artists", "album", "cover", "duration", "durationText"}` |

---

### 播放控制

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/control` | 控制播放。Body: `{"action":"next"|"stop"|"pause"|"resume"}` 或 `{"action":"seek","time":<秒>}` 或 `{"action":"volume","value":<0-100>}` |

---

### 页面

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/w/{token}` | 返回 Web 播放器前端页面（需使用 Bot 发送的随机链接） |
| GET | `/admin` | 管理后台首页（分页面入口） |
| GET | `/admin/music` | 音乐管理页 |
| GET | `/admin/config` | 配置中心页 |
| GET | `/admin/screen-share` | 屏幕共享管理页，可观看或结束指定会话 |
| GET | `/admin/stats` | 统计页 |
| GET | `/admin/activity` | 活跃统计页 |
| GET | `/admin/scheduler` | 定时任务管理页 |
| GET | `/admin/members` | 成员管理页 |
| GET | `/admin/areas` | 域配置管理页 |
| GET | `/admin/plugins` | 插件管理页 |
| GET | `/admin/setup` | 首启向导页 |
| GET | `/admin/system` | 系统页 |

---

## 管理后台 API（`/admin/api/*`）

> 说明：需先通过 `POST /admin/api/login` 登录，接口会使用 HttpOnly cookie 维护会话。

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/admin/api/login` | 登录。Body: `{"password":"..."}` |
| POST | `/admin/api/logout` | 退出登录 |
| GET | `/admin/api/me` | 当前登录状态 |
| GET | `/admin/api/overview` | 运行概览（Redis、队列、播放状态、统计摘要） |
| GET | `/admin/api/statistics?days=7&top_page=1&top_page_size=10` | 统计详情（近 N 天、Top 歌曲〔基于 play_history 聚合〕、最近歌曲） |
| GET | `/admin/api/logs?tail=200` | 读取日志尾部 |
| GET | `/admin/api/config` | 获取后台可编辑配置快照 |
| POST | `/admin/api/config` | 写入 `config.py` 并立即更新当前进程。Body: `{"updates": {...}, "persist": true}` |
| POST | `/admin/api/config/reset` | 从 `config.py` 重新加载配置并立即生效 |
| POST | `/admin/api/control` | 播放控制（同 `/api/control`） |
| POST | `/admin/api/queue/clear` | 清空播放队列 |
| GET | `/admin/api/queue?page=1&page_size=10` | 获取分页队列详情（含索引） |
| POST | `/admin/api/queue/action` | 队列操作（`top/remove`） |
| GET | `/admin/api/player/link` | 获取当前播放器访问链接 |
| POST | `/admin/api/player/link/rotate` | 重置播放器访问链接 |
| GET | `/admin/api/search?keyword=xxx&page=1&page_size=10` | 后台歌曲搜索（分页） |
| POST | `/admin/api/add` | 后台添加歌曲到队列 |
| GET | `/admin/api/system` | 系统信息（Python、Redis、DB、日志大小） |
| POST | `/admin/api/statistics/clear_history` | 清空播放历史记录 |
| POST | `/admin/api/liked/refresh` | 刷新喜欢列表缓存 |
| GET | `/admin/api/scheduled-messages` | 获取所有定时消息 |
| POST | `/admin/api/scheduled-messages` | 创建定时消息。Body: `{"name":"...","cron_hour":8,"cron_minute":0,"weekdays":"0,1,2,3,4,5,6","channel_id":"...","area_id":"...","message_text":"..."}` |
| PUT | `/admin/api/scheduled-messages/{id}` | 更新定时消息 |
| DELETE | `/admin/api/scheduled-messages/{id}` | 删除定时消息 |
| POST | `/admin/api/scheduled-messages/{id}/toggle` | 启用/禁用定时消息 |
| GET | `/admin/api/message-stats/daily?days=14` | 频道每日消息量（折线图数据） |
| GET | `/admin/api/message-stats/ranking?days=7&limit=10&area_id=` | 用户活跃排行（柱状图数据） |
| GET | `/admin/api/message-stats/overview` | 消息统计概览（今日消息数、本周消息数、今日活跃用户） |
| GET | `/admin/api/reminders` | 查看所有待执行提醒 |
| GET | `/admin/api/scheduled-message-templates` | 获取内置定时消息模板列表 |
| POST | `/admin/api/scheduled-message-templates/{template_key}/apply` | 套用模板创建定时消息 |
| GET | `/admin/api/setup/diagnostics` | 首启向导 / 核心依赖体检诊断 |

### 插件管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/admin/api/plugins` | 已加载 / 可加载插件列表 |
| POST | `/admin/api/plugins/{name}/load` | 动态加载插件 |
| POST | `/admin/api/plugins/{name}/unload` | 动态卸载插件 |
| POST | `/admin/api/plugins/{name}/reload-config` | 热重载插件配置 |
| GET | `/admin/api/plugins/{name}/config` | 获取插件配置 |
| POST | `/admin/api/plugins/{name}/config` | 写入插件配置 |

### 频道管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/admin/api/channels?area=` | 获取指定域的频道列表（含分组） |
| POST | `/admin/api/channels/create` | 创建频道 |
| PUT | `/admin/api/channels/{channel_id}` | 修改频道（名称等） |
| DELETE | `/admin/api/channels/{channel_id}` | 删除频道 |
| GET | `/admin/api/channels/{channel_id}/settings` | 获取频道设置（权限、私密等） |
| POST | `/admin/api/channels/{channel_id}/settings` | 编辑频道设置 |
| GET | `/admin/api/channels/{channel_id}/accessible-members` | 私密频道可访问成员 |
| GET | `/admin/api/online-members?area=` | 域在线成员 |
| GET | `/admin/api/voice-channels?area=` | 语音频道在线成员 |
| POST | `/admin/api/voice-channels/dispatch` | 将用户调度（拖拽）到其他语音频道 |

> 语音调度请求体：`{"area": "域ID", "target": "用户UID", "to_channel": "目标语音频道ID", "from_channel": "源语音频道ID(可选)"}`。
> `from_channel` 留空时后端会自动探测用户当前所在语音频道；底层调用 `PUT /client/v1/area/v1/member/v1/dragInto`。
> 在「域管理 → 语音频道监控」中，存在多个语音频道时每位在线成员旁会出现「调度」按钮。

### 域配置 / Bot 管理员

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/admin/api/areas/{area_id}/meta` | 域元信息（频道、身份组等） |
| GET | `/admin/api/area-configs` | 多域独立配置列表 |
| GET | `/admin/api/area-configs/{area_id}` | 获取某域配置 |
| POST | `/admin/api/area-configs/{area_id}` | 写入某域配置 |
| DELETE | `/admin/api/area-configs/{area_id}` | 删除某域配置 |
| GET | `/admin/api/bot-admins` | Bot 管理员（`ADMIN_UIDS`）列表 |
| POST | `/admin/api/bot-admins` | 新增 Bot 管理员 |
| DELETE | `/admin/api/bot-admins/{uid}` | 移除 Bot 管理员 |

### 屏幕共享管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/admin/api/screen-shares` | 列出活动共享、发起者、域/频道和临时观看链接 |
| POST | `/admin/api/screen-shares/{session_id}/stop` | 结束指定共享，使观看链接失效并在原频道通知 |

### 第三方账号登录

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/admin/api/oopz/login` | 用账号密码登录 Oopz 并写回凭据 |
| POST | `/admin/api/netease/login/qr` | 获取网易云登录二维码 |
| POST | `/admin/api/netease/login/qr/check` | 轮询网易云扫码状态 |
| GET | `/admin/api/netease/account` | 查看网易云登录账号 |
| POST | `/admin/api/bilibili/login/qr` | 获取 B 站登录二维码 |
| POST | `/admin/api/bilibili/login/qr/check` | 轮询 B 站扫码状态 |
| GET | `/admin/api/bilibili/account` | 查看 B 站登录账号 |

> 成员管理相关接口（`/admin/api/areas`、`/admin/api/members/*`、`/admin/api/send-message`、`/admin/api/send-announcement` 等）见 [命令文档 - 管理后台 API](commands.md#管理后台-api)。

`/admin/api/config` 当前支持分组：`web_player`、`screen_share`、`auto_recall`、`area_join_notify`、`chat`、`oopz`、`netease`、`redis`、`scheduler`、`reminder`、`music`、`command_cooldown`、`qq_music`、`bilibili_music`、`message_stats`。

---

## 模块说明

| 文件 | 职责 |
|------|------|
| `src/web/web_player.py` | FastAPI 主应用实例、播放器 API 路由（`/api/*`）、共享状态（Redis / Netease 客户端） |
| `src/web/web_player_admin.py` | Admin 路由入口：聚合 `web.admin` 包路由为 `admin_router`，对 `web_player` 与旧调用方保持稳定 facade |
| `src/web/admin/` | Admin 后台路由包：`pages`（页面）/`auth`（登录）/`config`（配置+第三方登录）/`music`（播放、统计、系统）/`screen_share`（活动共享和停止控制）/`scheduler`（定时消息、消息统计、提醒）/`plugins`（插件管理）/`members`（成员、频道、域配置、Bot 管理员、消息）/`shared`（共享工具） |
| `src/screen_share/` | 屏幕共享会话、AccessToken2、页面 API 和模块内 TypeScript 客户端源码 |
| `src/web/web_player_config.py` | 配置常量引用、分组定义、基线值、config.py 写回与热更新 |
| `src/web/assets/` | Web 播放器、Admin 页面以及随仓库发布的屏幕共享编译产物 |

## 相关文档

- [系统架构](architecture.md) — Web 播放器与 Redis、music 模块的协作及 Redis 键、Web 命令格式
- [配置说明](configuration.md) — `WEB_PLAYER_CONFIG` 等配置项
- [屏幕共享](screen-share.md) — 声网配置、权限、会话生命周期和前端构建
