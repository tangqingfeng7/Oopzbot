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

                ┌──────────────┐
                │  oopz_sender │  RSA 签名 · 消息发送 · 文件上传
                └──────┬───────┘
                       │
                  ┌────┴────┐
                  ▼         ▼
             Oopz API   Oopz CDN
                            │
                       database (SQLite)

  ┌──────────────┐     Redis      ┌──────────────┐
  │  web_player  │◄──────────────►│    music     │
  │  (FastAPI)   │  web_commands  │              │
  │  :8080       │  play_state    │ voice_client │
  └──────┬───────┘  volume        └──────┬───────┘
         │                               │
    浏览器 (Web UI)                Agora RTC (语音频道)
         │                               │
    player.html                  agora_player.html
    搜索/点歌/控制               Playwright 无头浏览器
    暂停/进度/音量               音频推流/暂停/跳转/音量
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
| 语音推流 | Agora Web SDK（Playwright 无头浏览器） |

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
│   ├── oopz_sender.py           # 消息发送（RSA 签名、文件上传、用户管理，默认公告样式）
│   ├── area_join_notifier.py    # 域成员加入/退出通知（轮询域成员 API 检测加入 + WebSocket 退出事件）
│   ├── command_handler.py       # 命令路由（@bot 指令 + / 命令 + 权限校验 + 脏话自动禁言）
│   ├── music.py                 # 音乐核心（搜索、队列、播放、封面缓存、自动切歌、Web 控制）
│   ├── netease.py               # 网易云音乐 API 封装（搜索、歌词、翻译歌词）
│   ├── queue_manager.py         # Redis 播放队列管理
│   ├── web_player.py            # Web 播放器 FastAPI 服务（状态/歌词/队列/搜索/控制 API）
│   ├── player.html              # Web 播放器前端（歌词同步、播放控制、搜索点歌）
│   ├── agora_player.html        # Agora RTC 浏览器端（推流/暂停/跳转/音量控制）
│   ├── voice_client.py          # Agora 语音客户端（Playwright 无头浏览器控制）
│   ├── chat.py                  # AI 聊天 + 图片生成 + 关键词回复 + AI 脏话审核
│   ├── database.py              # SQLite 数据层（图片缓存、歌曲缓存、播放历史、统计）
│   ├── name_resolver.py         # ID → 名称解析（用户/频道/区域，自动发现 + 持久化）
│   └── logger_config.py         # 日志配置（轮转文件 + 控制台，UTF-8）
│
├── plugins/                     # 插件目录
│   ├── lol_ban.py               # LOL 封号查询插件入口
│   ├── lol_fa8.py               # LOL 战绩查询插件入口
│   ├── _lol_query_service.py    # 封号查询实现（插件私有）
│   └── _lol_fa8_service.py      # 战绩查询实现（插件私有）
│
├── tools/                       # 独立工具
│   ├── credential_tool.py       # 凭据获取工具（RSA 私钥、UID、设备 ID、JWT Token）
│   └── audio_service.py         # 音频播放服务（ffplay + FastAPI）
│
├── data/                        # 运行时数据（自动生成）
│   ├── names.json               # ID → 名称缓存
│   └── oopz_cache.db            # SQLite 数据库文件
│
├── docs/                        # 文档目录
└── logs/                        # 日志文件
```

## 数据库表结构

| 表名 | 用途 | 关键字段 |
|------|------|----------|
| `image_cache` | 封面图片缓存 | source_id, oopz_url, use_count |
| `song_cache` | 歌曲信息缓存 | song_id, song_name, artist, play_count |
| `play_history` | 播放历史记录 | song_cache_id, channel_id, user_id, played_at |
| `statistics` | 每日统计汇总 | date, total_plays, unique_songs, cache_hits |

## Web 播放器

### 架构总览

Web 播放器通过 FastAPI 提供 HTTP API，前端 `player.html` 通过轮询获取状态、歌词、队列，通过 POST 请求发送控制命令。

```
浏览器 (player.html)
  │  轮询 GET /api/status, /api/queue, /api/lyric
  │  控制 POST /api/control, /api/queue/action
  │  搜索 GET /api/search → POST /api/add
  ▼
web_player.py (FastAPI :8080)
  │  读取 Redis: music:current, music:queue, music:play_state, music:volume
  │  写入 Redis: music:web_commands (RPUSH)
  ▼
music.py (BLPOP 独立线程，实时消费命令)
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
