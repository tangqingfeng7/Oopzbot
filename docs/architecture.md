# 系统架构

## 架构图

```
                    Oopz 平台
                       │
                  WebSocket 连接
                       │
                       ▼
                 ┌─────────────┐
                 │ oopz_client │  心跳保活 · 自动重连 · 事件分发
                 └──────┬──────┘
                        │
                        ▼
                ┌───────────────┐
                │command_handler│  指令路由 · 权限校验 · 脏话检测
                └─┬──┬──┬──┬───┘
                  │  │  │  │
        ┌─────────┘  │  │  └──────────┐
        ▼            ▼  ▼             ▼
   ┌─────────┐  ┌──────────┐  ┌────────────┐
   │ music   │  │  chat    │  │  plugins   │
   │         │  │          │  │            │
   │ 搜索/队列│  │ AI聊天   │  │ 扩展命令   │
   │ 播放/缓存│  │ AI画图   │  └────────────┘
   └────┬────┘  │ AI审核   │
        │       └────┬─────┘
  ┌─────┴─────┐      │
  ▼           ▼      └──► 豆包 AI API
netease    queue_manager
(API)       (Redis)
  │
  ▼
NeteaseCloud API (:3000)

         ┌─────────────────────────────────┐
         │          oopz_sender            │
         │  OopzSender(UploadMixin,        │
         │             OopzApiMixin)       │
         │  RSA 签名 · 消息发送 · 上传 · API │
         └──────────────┬──────────────────┘
                        │
                   ┌────┴────┐
                   ▼         ▼
              Oopz API   Oopz CDN
                             │
                        database (SQLite)

  ┌──────────────────────┐   Redis    ┌──────────────────────┐
  │    web_player        │◄─────────►│  music               │
  │  ├ web_player_admin  │ web_cmd   │  └ music_playback    │
  │  └ web_player_config │ play_st   │                      │
  │    (FastAPI :8080)   │ volume    │  voice_client        │
  └──────────┬───────────┘           └──────────┬───────────┘
             │                                  │
        浏览器 (Web UI)                   Agora RTC (语音频道)
             │                                  │
        player.html                    agora_player.html
        搜索/点歌/控制                 浏览器自动化（Playwright/Selenium）
        暂停/进度/音量                 音频推流/暂停/跳转/音量
```

## 技术栈

| 类别 | 技术 |
|------|------|
| 运行时 | Python 3.10+ |
| WebSocket | websocket-client |
| Web 服务 | FastAPI + Uvicorn（Web 播放器 :8080） |
| 队列 | Redis（播放队列 + 播放状态 + Web 命令通道） |
| 数据库 | SQLite（缓存、统计） |
| 加密签名 | cryptography（RSA PKCS1v15 + SHA256） |
| AI 接口 | 豆包（火山方舟，OpenAI 兼容） |
| 音乐 API | NeteaseCloudMusicApi（Node.js） |
| 语音推流 | Agora Web SDK（Playwright 优先，Selenium 回退） |

## 项目结构

```
├── main.py                      # 入口：初始化数据库、启动 Bot
├── config.py                    # 集中配置（平台、Redis、AI、音乐等）
├── config.example.py            # 配置示例
├── private_key.py               # RSA 私钥（PEM 格式）
├── private_key.example.py       # 私钥示例
├── requirements.txt             # Python 依赖
│
├── src/                         # 核心源码模块
│   ├── oopz_client.py           # WebSocket 客户端（心跳、重连、事件分发）
│   ├── oopz_sender.py           # 消息发送核心（RSA 签名、HTTP 请求、继承 UploadMixin + OopzApiMixin）
│   ├── oopz_upload.py           # UploadMixin：文件/图片/音频上传
│   ├── oopz_api.py              # OopzApiMixin：Oopz 平台 API 交互（成员/频道/角色/禁言等）
│   ├── area_join_notifier.py    # 域成员加入/退出通知（轮询域成员 API 检测加入 + WebSocket 退出事件）
│   ├── command_handler.py       # 命令路由（@bot 指令 + / 命令 + 权限校验 + 脏话自动禁言）
│   ├── music.py                 # 音乐核心（搜索、队列、封面缓存、Web 控制，继承 PlaybackMixin）
│   ├── music_playback.py        # PlaybackMixin：播放执行、推流、IP 检测、Web 播放器链接
│   ├── music_web_control.py     # Web 控制命令消费与分发
│   ├── netease.py               # 网易云音乐 API 封装（搜索、歌词、翻译歌词）
│   ├── queue_manager.py         # Redis 播放队列管理
│   ├── web_player.py            # Web 播放器 FastAPI 主应用（播放器 API 路由、共享状态）
│   ├── web_player_admin.py      # Admin 后台路由（/admin + /admin/api，使用 APIRouter）
│   ├── web_player_config.py     # Web 播放器 / Admin 配置常量、分组定义、运行时覆盖管理
│   ├── web_link_token.py        # Web 播放器随机访问链接/令牌管理
│   ├── player.html              # Web 播放器前端（歌词同步、播放控制、搜索点歌）
│   ├── agora_player.html        # Agora RTC 浏览器端（推流/暂停/跳转/音量控制）
│   ├── voice_client.py          # Agora 语音客户端（Playwright/Selenium 浏览器控制）
│   ├── chat.py                  # AI 聊天 + 图片生成 + 关键词回复 + AI 脏话审核
│   ├── database.py              # SQLite 数据层（图片缓存、歌曲缓存、播放历史、统计、db_connection 上下文管理器）
│   ├── name_resolver.py         # ID → 名称解析（用户/频道/区域，自动发现 + 持久化）
│   ├── plugin_loader.py         # 插件发现/加载/卸载
│   ├── plugin_registry.py       # 插件注册表与命令能力汇总
│   ├── plugin_base.py           # 插件基类
│   ├── logger_config.py         # 日志配置（轮转文件 + 控制台，UTF-8）
│   └── admin_assets/            # Admin 后台前端资源
│       ├── admin-shell-template.html  # Admin 页面公共 Shell 模板
│       └── pages/               # 各页面内容片段 + 脚本
│           ├── dashboard_content.html / dashboard_script.js
│           ├── music_content.html     / music_script.js
│           ├── config_content.html    / config_script.js
│           ├── stats_content.html     / stats_script.js
│           └── system_content.html    / system_script.js
│
├── plugins/                     # 插件目录
│   ├── delta_force.py           # 三角洲插件入口
│   ├── _delta_force_api.py      # 三角洲 API 封装
│   ├── _delta_force_assets.py   # 三角洲静态资源辅助
│   ├── _delta_force_login.py    # 三角洲登录流程
│   ├── _delta_force_store.py    # 三角洲本地状态存储
│   ├── _delta_force_render.py   # 三角洲海报渲染（单 base.html + CSS 变量主题映射）
│   ├── _delta_force_formatters.py # 三角洲文案格式化
│   ├── _delta_force_daily_push.py # 三角洲每日密码推送
│   ├── _delta_force_place_push.py # 三角洲特勤处推送
│   ├── _lol_common.py           # LOL 插件公共逻辑（关键词提取）
│   ├── lol_ban.py               # LOL 封号查询插件入口
│   ├── lol_fa8.py               # LOL 战绩查询插件入口
│   ├── _lol_query_service.py    # 封号查询实现（插件私有）
│   ├── _lol_fa8_service.py      # 战绩查询实现（插件私有）
│   ├── champion_names.json      # 英雄名英→中映射数据
│   ├── delta_force_assets/      # 三角洲静态资源
│   │   └── templates/base.html  # 三角洲海报统一模板（CSS 变量主题）
│   └── README.md                # 插件说明
│
├── tools/                       # 独立工具
│   ├── credential_tool.py       # 凭据获取工具（RSA 私钥、UID、设备 ID、JWT Token）
│   └── audio_service.py         # 音频播放服务（ffplay + FastAPI）
│
├── data/                        # 运行时数据（自动生成）
│   ├── names.json               # ID → 名称缓存
│   ├── admin_runtime_config.json # Admin 运行时配置覆盖
│   └── oopz_cache.db            # SQLite 数据库文件
│
├── docs/                        # 文档目录
└── logs/                        # 日志文件
```

## 模块拆分设计

### OopzSender 模块拆分

`oopz_sender.py` 通过 Mixin 模式拆分为三个模块：

| 模块 | 职责 |
|------|------|
| `oopz_sender.py` | 核心发送器，RSA 签名、HTTP 请求基础设施（`_request` 统一方法）、消息发送 |
| `oopz_upload.py` | `UploadMixin`：文件上传、图片上传、音频上传、图片信息获取 |
| `oopz_api.py` | `OopzApiMixin`：所有 Oopz 平台 API 交互（成员管理、频道操作、角色分配等） |

`OopzSender` 继承 `UploadMixin` 和 `OopzApiMixin`，外部调用方式不变。

### Music 模块拆分

| 模块 | 职责 |
|------|------|
| `music.py` | 音乐核心调度：搜索、队列管理、封面缓存、Web 控制消费 |
| `music_playback.py` | `PlaybackMixin`：播放执行（推流/自动切歌/预加载）、IP 检测、Web 播放器链接生成 |

`MusicHandler` 继承 `PlaybackMixin`。

### Web Player 模块拆分

| 模块 | 职责 |
|------|------|
| `web_player.py` | FastAPI 主应用实例、播放器 API 路由、共享状态（Redis/Netease 客户端） |
| `web_player_admin.py` | Admin 后台所有路由（`APIRouter`），包括登录、概览、统计、配置、队列管理等 |
| `web_player_config.py` | 配置常量（`WEB_PLAYER_CONFIG` 引用）、分组定义、基线值、运行时覆盖读写 |

`web_player.py` 通过 `app.include_router(admin_router)` 挂载 Admin 路由。

## 数据库表结构

| 表名 | 用途 | 关键字段 |
|------|------|----------|
| `image_cache` | 封面图片缓存 | source_id, oopz_url, use_count |
| `song_cache` | 歌曲信息缓存 | song_id, song_name, artist, play_count |
| `play_history` | 播放历史记录 | song_cache_id, channel_id, user_id, played_at |
| `statistics` | 每日统计汇总 | date, total_plays, unique_songs, cache_hits |

## Web 播放器

### 架构总览

Web 播放器通过 FastAPI 提供 HTTP API，前端 `player.html` 通过轮询获取状态、歌词、队列，通过 POST 请求发送控制命令。Admin 后台路由由 `web_player_admin.py` 通过 `APIRouter` 提供，配置管理由 `web_player_config.py` 集中处理。

```
浏览器 (player.html / admin 页面)
  │  轮询 GET /api/status, /api/queue, /api/lyric
  │  控制 POST /api/control, /api/queue/action
  │  搜索 GET /api/search → POST /api/add
  │  管理 /admin/api/* (登录/概览/统计/配置/队列)
  ▼
web_player.py ──► web_player_admin.py (APIRouter)
(FastAPI :8080)    └── web_player_config.py (配置管理)
  │  读取 Redis: music:current, music:queue, music:play_state, music:volume
  │  写入 Redis: music:web_commands (RPUSH)
  ▼
music.py + music_playback.py (BLPOP 独立线程，实时消费命令)
  │  调用 voice_client 方法
  ▼
voice_client.py → agora_player.html (Playwright 无头浏览器)
  │  Agora Web SDK: 推流/暂停/跳转/音量
  ▼
Agora RTC (语音频道)
```

### Redis 键约定

| 键 | 类型 | 说明 |
|----|------|------|
| `music:current` | String (JSON) | 当前播放歌曲信息（song_id, name, artist, cover, duration_ms 等） |
| `music:queue` | List (JSON[]) | 播放队列，每个元素为歌曲 JSON |
| `music:play_state` | String (JSON) | 播放状态（start_time, duration, paused, pause_elapsed） |
| `music:volume` | String | 当前音量 0-100 |
| `music:web_commands` | List | Web 控制命令队列，由 BLPOP 实时消费 |

### Web 控制命令

命令通过 `RPUSH` 写入 `music:web_commands`，`music.py` 的独立监听线程通过 `BLPOP` 实时取出执行（延迟 < 100ms）。

| 命令 | 说明 |
|------|------|
| `next` | 切下一首 |
| `stop` | 停止播放并清空队列 |
| `pause` | 暂停 |
| `resume` | 恢复播放 |
| `seek:<秒数>` | 跳转到指定位置 |
| `volume:<0-100>` | 设置音量 |
| `notify:<json>` | Web 点歌后在频道发送通知消息 |

### Web API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/status` | 当前播放状态（歌曲信息、进度、暂停、音量） |
| GET | `/api/queue` | 播放队列 |
| GET | `/api/lyric?id=<song_id>` | 歌词 + 翻译歌词 |
| GET | `/api/search?keyword=<kw>&limit=<n>` | 搜索歌曲 |
| GET | `/api/liked?page=<n>&limit=<n>[&keyword=<kw>]` | 喜欢的音乐（分页）；带 `keyword` 时在全部喜欢中搜索后分页 |
| POST | `/api/add` | 添加歌曲到队列（同时发送频道通知） |
| POST | `/api/control` | 播放控制（action: next/stop/pause/resume/seek/volume） |
| POST | `/api/queue/action` | 队列操作（action: remove/top, index） |
| POST | `/api/liked/refresh` | 刷新喜欢列表缓存 |
