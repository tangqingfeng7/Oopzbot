# 快速开始

## 最快的方式：一键部署

装好 Python 3.10+ 之后，Windows 双击 `deploy.bat`，Linux / macOS 执行：

```shell
chmod +x deploy.sh
./deploy.sh
```

脚本会建虚拟环境、装依赖和浏览器、生成配置、检查屏幕共享网页产物，并检查安装 Redis 与网易云音乐 API，
再问一次 Oopz 账号密码就启动。首次部署可选填写声网 App ID、不回显的 App Certificate 和对外 HTTPS 地址；留空则不启用屏幕共享。装不上的组件会降级而不是中断（详见
[README 的一键部署说明](../README.md#一键部署推荐)）。

想自己控制每一步，或者只想装其中一部分，就按下面的手动流程来。

## 环境要求（手动部署）

- Python 3.10+
- Redis 服务器（可选：连不上会自动退到内存队列，但屏幕共享会因权限状态不可靠而停用）
- Node.js 18+（仅用于运行网易云音乐 API；屏幕共享正式部署使用已编译产物，不需要 Node.js）
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
git clone https://github.com/NeteaseCloudMusicApiEnhanced/api-enhanced.git NeteaseCloudMusicApi
cd NeteaseCloudMusicApi
npm install
```

默认运行在 `http://localhost:3000`。首次使用需访问该地址扫码登录，将 Cookie 填入 `config.py` 的 `NETEASE_CLOUD.cookie`。

## 3. 配置

账号密码登录是主要登录方式。推荐先在 `config.py` 的 `OOPZ_CONFIG` 里填写 `login_phone` 和 `login_password`，Bot 启动时会自动刷新 Oopz 凭据，并写入 `device_id`、`person_uid`、`jwt_token` 和 `private_key.py`。

也可以先启动 Bot，再进管理后台的配置页，在“OOPZ 与网易云”里填写 Oopz 账号和密码并点击“登录并获取”。后台会优先调用 Oopz 登录接口直接获取凭据，失败时再回退到浏览器登录方式，并自动写入 `config.py` 和 `private_key.py`。

如果后台登录不可用，也可以使用命令行凭据工具从网页端抓取，详见 [凭据获取工具](credential-tool.md)。

也可以手动配置，详见 [配置说明](configuration.md)。

若需主程序启动时自动启动网易云 API，在 `config.py` 的 `NETEASE_CLOUD` 中设置 `auto_start_path`（如 `"NeteaseCloudMusicApi"`）。

LOL 功能使用插件配置文件：

- `config/plugins/lol_ban/config.json`
- `config/plugins/lol_fa8/config.json`

可从对应插件目录下的 `example.json` 复制为 `config.json` 后修改，其中 `enabled` 设为 `true` 才会启用对应查询功能。

## 4. 启动

```shell
python main.py
```

- 若已配置 `auto_start_path` 且目录存在，主程序会自动启动网易云 API 并等待就绪
- 否则需先手动启动：`cd NeteaseCloudMusicApi && node app.js`，再运行 `python main.py`

启动后 Bot 自动通过 WebSocket 连接 Oopz 平台。

如果需要给 NoneBot、AstrBot、Hoshino 等外部程序提供 OneBot v11 接口，可在 `config.py` 中启用 `ONEBOT_V11_CONFIG["enabled"] = True`，默认地址为 `http://127.0.0.1:6700`。详见 [OneBot v11 旁路适配](onebot-v11.md)。

### 需要走代理时

一键脚本会读取项目根目录下的 `.env`、`.env.local`；已设好的环境变量优先，文件只补空缺。可先复制示例：

```shell
cp .env.example .env
```

如需自动下载 Clash 订阅并启动 mihomo/clash 内核（Bot 退出时会一并停掉内核）：

```shell
CLASH_SUBSCRIPTION_URL="https://example.com/clash.yaml" CLASH_AUTO_START=1 ./deploy.sh
```

说明：

- 需系统已安装 `mihomo`、`clash-meta` 或 `clash`，也可通过 `CLASH_KERNEL_BIN` 指定可执行文件
- 脚本会将订阅保存到 `data/clash/subscription.yaml`，并生成运行时配置 `data/clash/config.yaml`
- 默认会将 mixed 端口固定为 `7890`、socks 端口固定为 `7891`
- 如果订阅是 base64 通用订阅（包含 `vmess://` / `vless://` / `trojan://` / `ss://`），脚本会先本地转换为 Mihomo 可读配置

## 5. Docker 部署

项目提供 `docker-compose.yml` 统一启动全部服务。首次启动前需准备运行时
配置目录和 TLS 证书：

```shell
cp docker.env.example .env
mkdir -p config data logs
cp config.example.py config/runtime.py
cp private_key.example.py config/private_key.py
mkdir -p nginx/ssl
# 生产环境请把正式完整证书链和私钥分别放到以下两个路径。
# 若文件尚不存在，下面会生成仅供本机测试的自签名证书；浏览器会提示不受信任。
if [ ! -s nginx/ssl/cert.pem ] || [ ! -s nginx/ssl/key.pem ]; then
  openssl req -x509 -newkey rsa:2048 -nodes -days 30 \
    -subj "/CN=localhost" \
    -keyout nginx/ssl/key.pem -out nginx/ssl/cert.pem
fi
chmod 600 nginx/ssl/key.pem
chmod u+rw config/runtime.py config/private_key.py
chmod u+rwx config data logs
# 编辑 config/runtime.py 填写必要配置
docker compose up -d --build
```

Docker 镜像默认以 `1000:1000` 的非 root 用户运行 Bot，与大多数 Linux
桌面用户的 UID/GID 一致，以便写入 `config/`、`data/` 和 `logs/`
bind mount（绑定挂载）。如果 `id -u` 或 `id -g` 不是 `1000`，请把
`.env` 中的 `BOT_UID` / `BOT_GID` 改为负责这些文件的**非 root**账号
实际输出，再执行
`docker compose build bot && docker compose up -d`。
如果当前 shell 是 root，不要把这两个值设为 `0`；保留 `1000:1000`
（或选择另一个非 root 身份），并把上述挂载路径 `chown` 给该数字身份。

上述 `mkdir` / `chmod` 必须在首次启动 Compose 前执行，否则 Docker 可能以
root 身份创建不可写的 `logs/` 绑定目录。如果这些目录已被旧部署创建为
root 所有，请执行 `sudo chown -R 1000:1000 config data logs`；如果 `.env`
选择了其他非 root `BOT_UID` / `BOT_GID`，相应替换两个数字。
Docker 部署把 `config/runtime.py` 与 `config/private_key.py` 分别链接为容器内
的 `/app/config.py`、`/app/private_key.py`。账号密码刷新和管理后台会安全
写回它们，因此 Compose 有意以可写目录方式挂载；请继续按敏感文件管理，
不要提交到 Git。已有 Docker 部署可先把根目录的 `config.py` 和
`private_key.py` 复制到这两个新路径再升级。

镜像已在共享的 `PLAYWRIGHT_BROWSERS_PATH` 中安装 Chromium 和 Chromium
Headless Shell，容器内的非 root Bot 可直接使用语音频道推流，无需再手工
执行 `playwright install`。屏幕共享的 TypeScript 编译产物也会随镜像复制，Docker 构建会校验其完整性，镜像内不安装 Node.js。

| 服务 | 端口 | 说明 |
|------|------|------|
| nginx | 80 / 443 | 反向代理，HTTP 301 重定向到 HTTPS |
| bot | 8080（内部） | 主程序 + Web 播放器 |
| netease-api | 3000（内部） | 网易云音乐 API |
| redis | -- | 内部通信，不暴露 |

容器环境默认设置 `BOT_REDIS_HOST=redis` 和
`BOT_NETEASE_BASE_URL=http://netease-api:3000`，可在 `.env` 中覆盖 Redis、
网易云、Oopz 代理、功能开关和日志级别。Compose 内部 Web 监听固定为
`0.0.0.0:8080`，以匹配健康检查与 Nginx 上游。更多环境变量见
[配置说明](configuration.md#环境变量覆盖)。Bot 的停止宽限期为 30 秒，
足以覆盖应用的 20 秒关停预算并为容器调度和退出留出余量。

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
ln -sf /etc/nginx/sites-available/oopzbot /etc/nginx/sites-enabled/oopzbot

# 复制 SSL 证书并设置权限
mkdir -p /etc/nginx/ssl
cp nginx/ssl/cert.pem /etc/nginx/ssl/cert.pem
cp nginx/ssl/key.pem /etc/nginx/ssl/key.pem
chmod 600 /etc/nginx/ssl/key.pem

# 禁用默认站点、测试并重载
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
```

### 方式三：Docker Compose

`docker compose up` 时 Nginx 会自动挂载 `nginx/nginx.docker.conf`，无需手工
切换 upstream。默认固定网络和容器 IP 可通过 `docker.env.example` 中的
`BOT_*_SUBNET` / `BOT_*_IP` 覆盖；Nginx 的可信代理 CIDR 会同步注入 Bot。

详见 [Web 播放器 - Nginx 反向代理](web-player.md#nginx-反向代理)。
