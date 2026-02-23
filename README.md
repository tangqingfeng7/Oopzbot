# Oopz Bot 说明文档

基于 Oopz 聊天平台的多功能机器人：支持网易云音乐点歌与语音频道推流、AI 聊天与画图、LOL 封号/战绩查询、脏话自动禁言等。通过 WebSocket 连接平台，支持 @ 提及与斜杠命令两种交互方式。

---

## 功能一览

| 模块 | 说明 |
|------|------|
| **音乐点歌** | 网易云搜索、播放队列、自动切歌、喜欢列表随机播放；Bot 可加入语音频道并通过 Agora 推流播放 |
| **Web 播放器** | 独立 Web 页面：歌词、队列、喜欢列表、搜索点歌、暂停/切歌/音量，与 Bot 状态同步 |
| **AI 聊天** | 豆包大模型（火山方舟 OpenAI 兼容），@bot 即可对话 |
| **AI 画图** | 豆包 Seedream 文生图 |
| **LOL 封号查询** | 输入 QQ 号查询英雄联盟账号封禁状态 |
| **LOL 战绩查询** | FA8 战绩、段位、胜率等 |
| **脏话自动禁言** | 关键词 → 上下文拼接 → AI 辅助，支持谐音/拆字检测 |
| **管理能力** | 禁言/解禁、禁麦/解麦、移出域(/ban)、域封禁列表(/blocklist)、解除域内封禁(/unblock)、撤回消息、每日语录 |
| **关键词回复** | 可配置的自动回复规则 |

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

---

## 配置要点

| 配置块 | 说明 |
|--------|------|
| **OOPZ_CONFIG** | `person_uid`、`device_id`、`jwt_token`、`default_area`、`default_channel`；语音推流需填写 `agora_app_id` |
| **REDIS_CONFIG** | 队列与播放状态存储，需先启动 Redis |
| **NETEASE_CLOUD** | `base_url`、`cookie`、`auto_start_path`；弱网时可调大 `audio_download_timeout`、`audio_download_retries`，音质可选 `audio_quality: "standard"`（体积小）或 `"exhigh"` |
| **WEB_PLAYER_CONFIG** | Web 播放器监听 `host`/`port`，以及对外展示的 `url`（留空则自动检测） |
| **ADMIN_UIDS** | 可执行管理命令的用户 UID 列表，为空则不限制 |

更多项见 [配置说明](docs/configuration.md)。

---

## 文档索引

| 文档 | 说明 |
|------|------|
| [快速开始](docs/quickstart.md) | 环境、依赖、网易云 API、启动步骤 |
| [凭据获取工具](docs/credential-tool.md) | 自动提取 RSA 私钥、UID、设备 ID、JWT |
| [配置说明](docs/configuration.md) | config.py 各配置项详解 |
| [机器人命令](docs/commands.md) | @ 指令与 / 斜杠命令参考 |
| [系统架构](docs/architecture.md) | 架构、技术栈、项目结构、数据库 |
| [API 参考](docs/api-reference.md) | Oopz 平台 API 端点说明 |

---

## 许可证

MIT
