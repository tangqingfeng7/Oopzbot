# Oopz Bot

基于 Oopz 平台的多功能机器人项目


## 环境要求

- Python 3.10+
- Redis
- Node.js 18+（用于网易云相关能力）
- Playwright 或 Selenium（语音推流 / 浏览器能力）

依赖安装：

```bash
pip install -r requirements.txt
playwright install chromium
```

## 启动方式

先准备配置文件：

```bash
# Windows
copy config.example.py config.py
copy private_key.example.py private_key.py

# Linux / macOS
cp config.example.py config.py
cp private_key.example.py private_key.py
```

然后启动：

```bash
python main.py
```

## 配置说明

常用配置包括：

- `OOPZ_CONFIG`
- `REDIS_CONFIG`
- `NETEASE_CLOUD`
- `WEB_PLAYER_CONFIG`
- `ADMIN_UIDS`
- `config/plugins/*.json`

插件配置会放在 `config/plugins/` 下。推荐保留：

- `*.example.json`
- `*.schema.json`

实际部署时，可把真实配置文件加入忽略规则，避免提交敏感信息。

## 文档索引

- [快速开始](docs/quickstart.md)
- [配置说明](docs/configuration.md)
- [命令说明](docs/commands.md)
- [系统架构](docs/architecture.md)
- [架构演进](docs/architecture-evolution.md)
- [插件开发工作流](docs/plugin-development.md)
- [凭据获取工具](docs/credential-tool.md)
- [Web 播放器](docs/web-player.md)
- [API 参考](docs/api-reference.md)

## 许可证

MIT
