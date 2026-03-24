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
| `link_idle_release_seconds` | 播放列表空闲超时后释放随机访问链接（秒，`0` 表示不释放） |
| `admin_enabled` | 是否启用管理后台（访问 `/admin`） |
| `admin_password` | 管理后台登录密码 |
| `admin_session_ttl_seconds` | 后台会话有效期（秒） |
| `admin_cookie_secure` | 后台 cookie 是否仅 HTTPS 发送（使用 Nginx + SSL 时设为 `True`） |

> **注意**：管理后台(`/admin` -> 配置)保存的运行时覆盖（`data/admin_runtime_config.json`）优先级高于 `config.py`。如果在后台修改过 URL 等字段，手动编辑 `config.py` 不会生效，需通过后台或直接编辑 JSON 文件修改。

---

## Nginx 反向代理

项目自带 `nginx/nginx.conf`，支持通过 Nginx 反向代理统一对外提供 HTTP (80) 和 HTTPS (443) 访问。

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

播放器 API 由 `web_player.py` 提供；Admin 后台 API 由 `web_player_admin.py`（`APIRouter`）提供；配置管理由 `web_player_config.py` 集中处理。

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
| GET | `/admin/stats` | 统计页 |
| GET | `/admin/activity` | 活跃统计页 |
| GET | `/admin/scheduler` | 定时任务管理页 |
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
| POST | `/admin/api/config` | 更新配置。Body: `{"updates": {...}, "persist": true|false}` |
| POST | `/admin/api/config/reset` | 清理 `data/admin_runtime_config.json` 持久化覆盖 |
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

`/admin/api/config` 当前支持分组：`web_player`、`auto_recall`、`area_join_notify`、`chat`、`profanity`、`oopz`、`netease`、`redis`、`doubao_chat`、`doubao_image`。

---

## 模块说明

| 文件 | 职责 |
|------|------|
| `web_player.py` | FastAPI 主应用实例、播放器 API 路由（`/api/*`）、共享状态（Redis / Netease 客户端） |
| `web_player_admin.py` | Admin 后台路由（`/admin` + `/admin/api/*`），通过 `APIRouter` 挂载 |
| `web_player_config.py` | 配置常量引用、分组定义、基线值、运行时覆盖读写（`admin_runtime_config.json`） |
| `admin_assets/` | Admin 页面 Shell 模板与各页面内容片段 / 脚本 |

## 相关文档

- [系统架构](architecture.md) — Web 播放器与 Redis、music 模块的协作及 Redis 键、Web 命令格式
- [配置说明](configuration.md) — `WEB_PLAYER_CONFIG` 等配置项
