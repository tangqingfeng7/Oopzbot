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
git clone https://github.com/NeteaseCloudMusicApiEnhanced/api-enhanced.git NeteaseAPI_tmp
cd NeteaseAPI_tmp
npm install
```

默认运行在 `http://localhost:3000`。首次使用需访问该地址扫码登录，将 Cookie 填入 `config.py` 的 `NETEASE_CLOUD.cookie`。

## 3. 配置

推荐使用凭据获取工具自动完成配置，详见 [凭据获取工具](credential-tool.md)。

也可以手动配置，详见 [配置说明](configuration.md)。

若需主程序启动时自动启动网易云 API，在 `config.py` 的 `NETEASE_CLOUD` 中设置 `auto_start_path`（如 `"NeteaseAPI_tmp"`）。

LOL 功能使用插件配置文件：

- `config/plugins/lol_ban.json`
- `config/plugins/lol_fa8.json`

可从同目录下 `*.example.json` 复制后修改，其中 `enabled` 设为 `true` 才会启用对应查询功能。

## 4. 启动

```shell
python main.py
```

- 若已配置 `auto_start_path` 且目录存在，主程序会自动启动网易云 API 并等待就绪
- 否则需先手动启动：`cd NeteaseAPI_tmp && node app.js`，再运行 `python main.py`

启动后 Bot 自动通过 WebSocket 连接 Oopz 平台。

Linux 上也可以使用一键脚本：

```shell
./start.sh
```

脚本会自动读取项目根目录下的 `.env`、`.env.local`。可先复制示例：

```shell
cp .env.example .env
```

如需自动下载 Clash 订阅并启动 mihomo/clash 内核：

```shell
CLASH_SUBSCRIPTION_URL="https://example.com/clash.yaml" CLASH_AUTO_START=1 ./start.sh
```

说明：

- 需系统已安装 `mihomo`、`clash-meta` 或 `clash`，也可通过 `CLASH_KERNEL_BIN` 指定可执行文件
- 脚本会将订阅保存到 `data/clash/subscription.yaml`，并生成运行时配置 `data/clash/config.yaml`
- 默认会将 mixed 端口固定为 `7890`、socks 端口固定为 `7891`
- 如果订阅是 base64 通用订阅（包含 `vmess://` / `vless://` / `trojan://` / `ss://`），脚本会先本地转换为 Mihomo 可读配置

## 5. Docker 部署

项目提供 `docker-compose.yml`，一键启动全部服务，无需手动安装依赖：

```shell
cp config.example.py config.py
cp private_key.example.py private_key.py
# 编辑 config.py 填写必要配置
docker-compose up -d
```

| 服务 | 端口 | 说明 |
|------|------|------|
| nginx | 80 / 443 | 反向代理，统一对外入口（HTTP + HTTPS） |
| bot | 8080（内部） | 主程序 + Web 播放器 |
| netease-api | 3000（内部） | 网易云音乐 API |
| redis | -- | 内部通信，不暴露 |

容器环境自动设置 `BOT_REDIS_HOST=redis` 和 `BOT_NETEASE_BASE_URL=http://netease-api:3000`。更多环境变量覆盖见 [配置说明](configuration.md#环境变量覆盖)。

## 6. 配置 Nginx 反向代理（可选）

如果需要通过域名 + HTTPS 访问 Web 播放器，可配置 Nginx 反向代理。

### 方式一：面板部署（1Panel / 宝塔）

若服务器已有 1Panel 或宝塔面板：

1. 在面板中创建**反向代理**站点，域名填写你的域名，代理地址填 `127.0.0.1:8080`
2. 在站点设置中启用 HTTPS，上传或申请 SSL 证书
3. 在 `config.py`（或管理后台 `/admin` -> 配置）中将 `WEB_PLAYER_CONFIG["url"]` 设为 `https://你的域名`，`cookie_secure` 和 `admin_cookie_secure` 设为 `True`

### 方式二：手动安装 Nginx

```shell
apt install -y nginx

# 复制项目自带的站点配置
cp nginx/nginx.conf /etc/nginx/sites-available/oopzbot
ln -s /etc/nginx/sites-available/oopzbot /etc/nginx/sites-enabled/oopzbot

# 复制 SSL 证书
mkdir -p /etc/nginx/ssl
cp nginx/ssl/cert.pem /etc/nginx/ssl/cert.pem
cp nginx/ssl/key.pem /etc/nginx/ssl/key.pem

# 禁用默认站点、测试并重载
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
```

### 方式三：Docker Compose

`docker-compose up` 时 Nginx 服务会自动启动，需在 `nginx/nginx.conf` 中将 upstream 切换为 Docker 服务名（`bot:8080` / `netease-api:3000`）。

详见 [Web 播放器 - Nginx 反向代理](web-player.md#nginx-反向代理)。
