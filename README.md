# Oopz Bot

基于 Oopz 聊天平台的多功能机器人，集成网易云音乐点歌、AI 聊天与画图、LOL 封号查询等能力。通过 WebSocket 实时连接平台，支持频道指令与斜杠命令两种交互方式。

## 功能一览

| 模块 | 说明 |
|------|------|
| 音乐点歌 | 网易云音乐搜索、播放队列、自动切歌、喜欢列表随机播放 |
| AI 聊天 | 接入豆包大模型（火山方舟 OpenAI 兼容接口），@bot 即可对话 |
| AI 画图 | 接入豆包 Seedream 文生图模型 |
| LOL 封号查询 | 输入 QQ 号查询英雄联盟账号封禁状态 |
| LOL 战绩查询 | 查询召唤师近期战绩、段位、胜率等 |
| 脏话自动禁言 | 三层检测：关键词匹配 → 上下文拼接 → AI 智能识别，支持谐音/拆字绕过检测 |
| 管理能力 | 禁言/解禁、禁麦/解麦、撤回消息、每日语录 |
| 关键词回复 | 可配置的自动回复规则 |

## 快速开始

```shell
# 1. 安装依赖
pip install -r requirements.txt

# 2. 获取 Oopz 凭据（自动提取 UID、设备ID、JWT Token、RSA 私钥）
python -m playwright install chromium
python tools/credential_tool.py --save

# 3. 启动 Bot
python main.py
```

> 首次使用需部署网易云音乐 API 并填入 Cookie。若在配置中设置 `auto_start_path`，主程序会自动启动该服务。详见 [快速开始](docs/quickstart.md)。

## 文档

| 文档 | 说明 |
|------|------|
| [快速开始](docs/quickstart.md) | 环境要求、安装依赖、部署音乐 API、启动 Bot |
| [凭据获取工具](docs/credential-tool.md) | 自动提取 RSA 私钥、用户 UID、设备 ID、JWT Token |
| [配置说明](docs/configuration.md) | config.py 各配置项详解 |
| [机器人命令](docs/commands.md) | @bot 中文指令 + / 斜杠命令完整参考 |
| [系统架构](docs/architecture.md) | 架构图、技术栈、项目结构、数据库表结构 |
| [API 参考](docs/api-reference.md) | Oopz 平台全部已知 API 端点文档 |

## 许可证

MIT
