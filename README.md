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

Linux 可直接使用一键启动脚本：

```shell
./start.sh
```

也可以把启动参数放到项目根目录的 `.env`（可先复制 `.env.example`）：

```shell
cp .env.example .env
```

如果希望同时自动下载 Clash 订阅并拉起 mihomo/clash 内核，再启动 Bot，可使用：

```shell
CLASH_SUBSCRIPTION_URL="https://example.com/clash.yaml" CLASH_AUTO_START=1 ./start.sh
```

常用环境变量：

- `CLASH_SUBSCRIPTION_URL`：Clash/Mihomo 订阅地址
- `CLASH_KERNEL_BIN`：内核命令或绝对路径，默认自动查找 `mihomo`、`clash-meta`、`clash`
- `CLASH_MIXED_PORT`：本地 mixed 代理端口，默认 `7890`
- `CLASH_SOCKS_PORT`：本地 socks 代理端口，默认 `7891`
- `CLASH_PROXY` / `BOT_OOPZ_PROXY`：Bot 使用的代理地址；未设置时会默认指向 `http://127.0.0.1:$CLASH_MIXED_PORT`

`start.sh` 会按顺序自动读取项目根目录下的 `.env`、`.env.local`，后者可覆盖前者。
如果订阅内容不是 Clash YAML，而是常见的 base64 通用订阅（`vmess://` / `vless://` / `trojan://` / `ss://`），脚本会先在本地转换成 Mihomo 配置再启动。

### 5. Docker 启动

已提供 `Dockerfile` 与 `docker-compose.yml`，默认会同时启动：

- `bot`：主程序容器
- `redis`：内置 Redis 容器

首次使用前确保项目根目录已有真实的 `config.py` 与 `private_key.py`，然后执行：

```shell
docker compose up -d --build
```

默认会同时拉起 `bot`、`redis`、`netease-api` 三个服务，映射 Web 播放器端口 `8080`，并自动通过环境变量适配容器环境：

- `BOT_REDIS_HOST=redis`
- `BOT_NETEASE_BASE_URL=http://netease-api:3000`

可选环境变量示例见 `docker.env.example`。

说明：

- Docker 默认启用完整能力：Redis、网易云 API、Web 播放器，以及在已配置 `agora_app_id` 时的 Agora 语音推流
- `netease-api` 服务带健康检查，`bot` 会等待其就绪后再启动，避免启动顺序导致音乐功能异常
- 如需改用外部网易云 API，可覆盖 `BOT_NETEASE_BASE_URL`
- 只有在排障时才建议额外设置 `BOT_DISABLE_AUTO_START_NETEASE=1` 或 `BOT_DISABLE_VOICE=1`
- 运行时会挂载 `./config.py`、`./private_key.py`、`./config/`、`./data/`、`./logs/`

---

## 配置要点

| 配置块 | 说明 |
|--------|------|
| **OOPZ_CONFIG** | `person_uid`、`device_id`、`jwt_token`、`default_area`、`default_channel`；语音推流需填写 `agora_app_id` |
| **REDIS_CONFIG** | 队列与播放状态存储，需先启动 Redis |
| **NETEASE_CLOUD** | `base_url`、`cookie`、`auto_start_path`；弱网时可调大 `audio_download_timeout`、`audio_download_retries`，音质可选 `audio_quality: "standard"`（体积小）或 `"exhigh"` |
| **WEB_PLAYER_CONFIG** | Web 播放器监听 `host`/`port`、对外 `url`，以及管理后台（`admin_enabled`/`admin_password`） |
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
| [Web 播放器](docs/web-player.md) | Web 播放器与管理后台说明（功能、配置、HTTP API） |
| [API 参考](docs/api-reference.md) | Oopz 平台 API 端点说明 |

---

## 许可证

MIT
