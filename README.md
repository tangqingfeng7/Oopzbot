# Oopz Bot

基于 [Oopz](https://web.oopz.cn) 平台的多功能聊天机器人，通过 WebSocket 与平台保持连接，支持音乐点播、AI 聊天、插件扩展、Web 播放器、管理后台等能力。

## 功能特性

- **音乐点播** — 网易云搜索 / 播放 / 队列 / 随机播放 / 喜欢列表，支持 Agora 语音频道推流
- **AI 聊天 & 图片生成** — 接入豆包 AI（火山方舟），支持智能对话与 Seedream 文生图
- **Web 播放器** — FastAPI 提供 HTTP API，浏览器端控制播放、歌词、队列
- **安全管控** — 脏话检测（关键词 + AI 辅助）、自动禁言、消息撤回
- **社区管理** — 成员管理、角色、禁言、封禁、踢出、域成员加入 / 退出通知
- **插件系统** — 可扩展插件架构，已有三角洲行动、LOL 封号查询、LOL 战绩查询等插件
- **管理后台** — Web 管理面板，支持系统监控、音乐控制、配置管理

## 环境要求

| 依赖 | 说明 |
|------|------|
| Python 3.10+ | 主程序运行环境 |
| Redis | 播放队列、状态存储、Web 命令通道 |
| Playwright | 语音推流浏览器自动化（Selenium 可作为回退） |
| Node.js 18+ | 仅当本地启动网易云 API 服务时需要（Docker 部署无需手动安装） |

## 快速开始

### 安装依赖

```bash
pip install -r requirements.txt
playwright install chromium
```

### 准备配置

```bash
# Windows
copy config.example.py config.py
copy private_key.example.py private_key.py

# Linux / macOS
cp config.example.py config.py
cp private_key.example.py private_key.py
```

编辑 `config.py`，填写 `OOPZ_CONFIG` 中的 `device_id`、`person_uid`、`jwt_token` 等必填项。可使用凭据获取工具辅助：

```bash
python tools/credential_tool.py
```

### 启动

```bash
python main.py
```

Bot 启动时会自动连接 Redis、启动网易云 API（若已配置 `auto_start_path`）、启动 Web 播放器。

### Docker 部署

项目提供 `docker-compose.yml`，一键启动 Redis、Bot、网易云 API 三个服务：

```bash
# 1. 准备配置文件
copy config.example.py config.py
copy private_key.example.py private_key.py
# 编辑 config.py 填写必要配置

# 2. 克隆网易云 API
git clone https://github.com/NeteaseCloudMusicApiEnhanced/api-enhanced.git NeteaseAPI_tmp

# 3. 启动
docker-compose up -d
```

| 服务 | 端口 | 说明 |
|------|------|------|
| bot | 8080 | 主程序 + Web 播放器 |
| netease-api | 3000 | 网易云音乐 API |
| redis | — | 内部通信，不暴露 |

## 配置说明

### 主要配置项（`config.py`）

| 配置 | 说明 |
|------|------|
| `OOPZ_CONFIG` | 平台连接、JWT、设备 ID、区域、频道、Agora 等 |
| `REDIS_CONFIG` | Redis 连接参数 |
| `NETEASE_CLOUD` | 网易云 API 地址、Cookie、音质、自动启动路径 |
| `DOUBAO_CONFIG` | 豆包 AI 聊天（火山方舟） |
| `DOUBAO_IMAGE_CONFIG` | 豆包 Seedream 文生图 |
| `PROFANITY_CONFIG` | 脏话检测、禁言规则 |
| `WEB_PLAYER_CONFIG` | Web 播放器、管理后台 |
| `AUTO_RECALL_CONFIG` | Bot 消息自动撤回 |
| `AREA_JOIN_NOTIFY` | 域成员加入 / 退出通知 |
| `CHAT_CONFIG` | 关键词自动回复 |
| `ADMIN_UIDS` | 管理员 UID 列表 |

### 环境变量覆盖

Docker 环境下可通过环境变量覆盖部分配置，无需修改 `config.py`：

| 环境变量 | 对应配置 |
|----------|----------|
| `BOT_REDIS_HOST` / `BOT_REDIS_PORT` / `BOT_REDIS_PASSWORD` / `BOT_REDIS_DB` | Redis 连接 |
| `BOT_NETEASE_BASE_URL` | 网易云 API 地址 |
| `BOT_WEB_HOST` / `BOT_WEB_PORT` | Web 播放器监听 |
| `BOT_OOPZ_PROXY` | Oopz 代理地址 |
| `BOT_DISABLE_VOICE` | 禁用语音推流 |
| `BOT_DISABLE_AUTO_START_NETEASE` | 禁用自动启动网易云 API |

### 插件配置

插件配置位于 `config/plugins/` 目录，每个插件提供 `*.example.json`（示例）和 `*.schema.json`（结构定义），复制示例文件并修改即可。


## 文档索引

- [快速开始](docs/quickstart.md)
- [配置说明](docs/configuration.md)
- [命令说明](docs/commands.md)
- [系统架构](docs/architecture.md)
- [插件开发工作流](docs/plugin-development.md)
- [凭据获取工具](docs/credential-tool.md)
- [Web 播放器](docs/web-player.md)
- [API 参考](docs/api-reference.md)

## 许可证

MIT
