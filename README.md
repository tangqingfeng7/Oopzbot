# Oopz Bot 说明文档

基于 Oopz 聊天平台的多功能机器人：支持网易云音乐点歌与语音频道推流、AI 聊天与画图、LOL 封号/战绩查询、三角洲行动账号与战绩查询、脏话自动禁言等。通过 WebSocket 连接平台，支持 @ 提及与斜杠命令两种交互方式。

---

## 环境要求

- **Python** 3.10+
- **Redis**（队列与播放状态）
- **Node.js** 18+（用于网易云音乐 API）
- **语音频道推流**：Playwright + Chromium，或 Selenium + Chrome/Edge（Windows 上若遇 greenlet 错误会自动用 Selenium，见 [配置说明](docs/configuration.md#agora-语音频道-agora_app_id)）

---

## 快速开始

### 1. 安装依赖

```shell
pip install -r requirements.txt
# 语音频道推流：推荐执行 playwright install chromium；若仅用 Selenium 回退则需本机安装 Chrome 或 Edge
playwright install chromium
```

### 2. 配置文件

```shell
# Windows
copy config.example.py config.py
copy private_key.example.py private_key.py

# Linux / macOS
cp config.example.py config.py
cp private_key.example.py private_key.py
```

推荐使用 [凭据获取工具](docs/credential-tool.md) 自动填充 Oopz 凭据与 RSA 私钥。

### 3. 网易云音乐 API

- 将网易云 API 项目放在项目根目录下（如 `NeteaseCloudMusicApi`），在 `config.py` 的 `NETEASE_CLOUD.base_url` 中填写服务地址（默认 `http://localhost:3000`）。
- 在 `NETEASE_CLOUD.cookie` 中填入登录后的 Cookie（可选，用于喜欢列表等）。
- 若设置 `auto_start_path` 为上述目录名，主程序启动时会自动启动该 API 并等待就绪。

### 4. 启动 Bot

```shell
python main.py
```

启动后会自动连接 Oopz WebSocket；若配置了 Agora，Bot 可加入语音频道并推流播放音乐。Web 歌词播放器默认在配置的端口（如 3001）提供页面。

### 5. Docker 启动

已提供 `Dockerfile` 与 `docker-compose.yml`，默认会同时启动：

- `bot`：主程序容器
- `redis`：内置 Redis 容器

首次使用前确保项目根目录已有真实的 `config.py` 与 `private_key.py`，然后执行：

```shell
docker compose up -d --build
```

如需同时启用网易云 API 容器，使用 `music` profile：

```shell
docker compose --profile music up -d --build
```

默认会映射 Web 播放器端口 `8080`，并自动通过环境变量适配容器环境：

- `BOT_REDIS_HOST=redis`
- `BOT_NETEASE_BASE_URL=http://netease-api:3000`
- `BOT_DISABLE_AUTO_START_NETEASE=1`
- `BOT_DISABLE_VOICE=1`

可选环境变量示例见 `docker.env.example`。

说明：

- Docker 默认关闭“自动启动网易云 API 子进程”，如需使用外部网易云 API，可额外设置 `BOT_NETEASE_BASE_URL`
- 若使用 `--profile music`，会额外构建并启动本地 `NeteaseAPI_tmp` 目录中的网易云 API 服务
- Docker 默认关闭 Agora 语音推流；如需启用，请移除 `BOT_DISABLE_VOICE`，并自行提供浏览器运行环境
- 运行时会挂载 `./config.py`、`./private_key.py`、`./config/`、`./data/`、`./logs/`

---

## 配置要点

| 配置块 | 说明 |
|--------|------|
| **OOPZ_CONFIG** | `person_uid`、`device_id`、`jwt_token`、`default_area`、`default_channel`；语音推流需填写 `agora_app_id` |
| **REDIS_CONFIG** | 队列与播放状态存储，需先启动 Redis |
| **NETEASE_CLOUD** | `base_url`、`cookie`、`auto_start_path`；弱网时可调大 `audio_download_timeout`、`audio_download_retries`，音质可选 `audio_quality: "standard"`（体积小）或 `"exhigh"` |
| **WEB_PLAYER_CONFIG** | Web 播放器监听 `host`/`port`，以及对外展示的 `url`（留空则自动检测） |
| **插件配置（JSON）** | 插件配置位于 `config/plugins/*.json`，当前包含 `lol_ban`、`lol_fa8` 与 `delta_force`（字段说明见 [配置说明](docs/configuration.md)） |
| **ADMIN_UIDS** | 可执行管理命令的用户 UID 列表，为空则不限制 |

Bot 发送的所有消息默认使用**公告样式**（`styleTags: ["IMPORTANT"]`）。更多项见 [配置说明](docs/configuration.md)。

---

## 插件系统

- 插件位于 `plugins/`，启动时自动加载。
- 插件配置位于 `config/plugins/<插件名>.json`，例如 `lol_ban`、`lol_fa8` 与 `delta_force`。
- `delta_force` 插件支持三角洲行动二维码登录、账号切换、角色绑定、信息、藏品/资产、货币、封号记录、日报、周报和战绩查询。
- 三角洲登录支持通过配置选择二维码投递方式：私信，或创建仅登录用户可见的临时频道；若所选方式失败，插件会回退到当前频道提示。
- 管理命令（仅管理员）：
  - `@bot 插件列表` / `/plugins`
  - `@bot 加载插件 <名>` / `/loadplugin <名>`
  - `@bot 卸载插件 <名>` / `/unloadplugin <名>`
- 提示：卸载时只填写插件名（如 `lol_ban`），不要带版本号文本。

---

## 文档索引

| 文档 | 说明 |
|------|------|
| [快速开始](docs/quickstart.md) | 环境、依赖、网易云 API、启动步骤 |
| [凭据获取工具](docs/credential-tool.md) | 自动提取 RSA 私钥、UID、设备 ID、JWT |
| [配置说明](docs/configuration.md) | config.py 各配置项详解 |
| [机器人命令](docs/commands.md) | @ 指令与 / 斜杠命令参考 |
| [系统架构](docs/architecture.md) | 架构、技术栈、项目结构、数据库 |
| [Web 播放器](docs/web-player.md) | Web 播放器功能说明与 HTTP API（歌词同步、音量记忆、喜欢列表全量搜索等） |
| [API 参考](docs/api-reference.md) | Oopz 平台 API 端点说明 |

---

## 许可证

MIT
