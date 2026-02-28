# 快速开始

## 环境要求

- Python 3.10+
- Redis 服务器
- Node.js 18+（运行网易云音乐 API 服务）
- **语音频道推流**：Playwright + Chromium，或 Selenium + Chrome/Edge（见下方说明）

## 1. 安装 Python 依赖

```shell
pip install -r requirements.txt
```

**语音频道推流（Agora）二选一即可：**

- **推荐**：`playwright install chromium`（安装 Playwright 自带的 Chromium）
- **若 Windows 出现 greenlet DLL 错误**：程序会自动改用 Selenium，需本机已安装 [Chrome](https://www.google.com/chrome/) 或 Edge；驱动由 `webdriver-manager` 或 Selenium 自动管理。详见 [配置说明 - Agora 语音频道](configuration.md#agora-语音频道-agora_app_id)。

## 2. 部署网易云音乐 API

```shell
# 在项目根目录下克隆
git clone https://gitlab.com/Binaryify/NeteaseCloudMusicApi.git
cd NeteaseCloudMusicApi
npm install
```

默认运行在 `http://localhost:3000`。首次使用需访问该地址扫码登录，将 Cookie 填入 `config.py` 的 `NETEASE_CLOUD.cookie`。

## 3. 配置

推荐使用凭据获取工具自动完成配置，详见 [凭据获取工具](credential-tool.md)。

也可以手动配置，详见 [配置说明](configuration.md)。

若需主程序启动时自动启动网易云 API，在 `config.py` 的 `NETEASE_CLOUD` 中设置 `auto_start_path`（如 `"NeteaseCloudMusicApi"`）。

LOL 功能使用插件配置文件：

- `config/plugins/lol_ban.json`
- `config/plugins/lol_fa8.json`

可从同目录下 `*.example.json` 复制后修改，其中 `enabled` 设为 `true` 才会启用对应查询功能。

## 4. 启动

```shell
python main.py
```

- 若已配置 `auto_start_path` 且目录存在，主程序会自动启动网易云 API 并等待就绪
- 否则需先手动启动：`cd NeteaseCloudMusicApi && node app.js`，再运行 `python main.py`

启动后 Bot 自动通过 WebSocket 连接 Oopz 平台。
