"""
Oopz Bot 配置文件示例
复制此文件为 config.py 并填写真实配置
管理后台保存配置会写回 config.py，并立即更新当前进程，无需重启
"""

# Oopz 平台配置
OOPZ_CONFIG = {
    "app_version": "69514",
    "channel": "Web",
    "platform": "windows",
    "web": True,
    "base_url": "https://gateway.oopz.cn",
    "ws_url": "wss://ws.oopz.cn",   # 事件推送的 WebSocket 地址，一般不改

    # === 账号密码登录是主要方式 ===
    # 填下面两项后，启动时会先用账号密码刷新登录凭据，并自动写入 device_id/person_uid/jwt_token 和 private_key.py。
    # 也可以留空，在管理后台“OOPZ 与网易云”里临时输入账号密码并点击“登录并获取”。
    "login_phone": "",     # OOPZ 登录手机号 / 账号
    "login_password": "",  # OOPZ 登录密码
    "device_id": "",       # 设备 ID（账号密码登录成功后自动写入）
    "person_uid": "",      # 用户 UID（账号密码登录成功后自动写入）
    "jwt_token": "",       # JWT Token（账号密码登录成功后自动写入）

    "default_area": "",    # 默认区域 ID
    "default_channel": "", # 默认频道 ID
    "use_announcement_style": False,  # 全局默认是否使用公告样式（styleTags=IMPORTANT）；可在 admin 后台 → 域配置 → 公告样式 单独覆盖。bot 不是域主时一般保持 False，否则发公告会被服务端拒

    # Agora RTC（语音频道推流；Playwright 优先，Selenium 可回退）
    "agora_app_id": "358eebceadb94c2a9fd91ecd7b341602",
    "agora_init_timeout": 1800,  # Playwright 浏览器启动等待秒数，首启或网络慢可调大

    # 代理：不设或 "" = 使用系统代理(HTTP_PROXY/HTTPS_PROXY/ALL_PROXY)；False/"direct" = 直连；
    # "clash" = http://127.0.0.1:7890；也可填 "http://127.0.0.1:7890" 或 "socks5://127.0.0.1:7891"
    "proxy": "",  # WebSocket / HTTP / Agora 浏览器侧都会复用这项代理配置

}

# 本地代理客户端别名端口：proxy 填 "clash"/"mihomo" 等别名时使用。
# 改了 Clash/mihomo 的监听端口时，只需在这里调整，无需改动代码。
PROXY_ALIAS_CONFIG = {
    "host": "127.0.0.1",
    "http_port": 7890,   # clash / clash-http / clash-mixed / mihomo
    "socks_port": 7891,  # clash-socks / mihomo-socks
    # Clash / mihomo 开 fake-ip 时，本机 DNS 返回的是占位地址而非真实目标。
    # 远程素材下载遇到这些段会改走下面的可信 DoH 校验真实地址；校验失败则拒绝。
    "fake_ip_ranges": ["198.18.0.0/15", "fdfe:dcba:9876::/64"],
    "trusted_doh_url": "https://cloudflare-dns.com/dns-query",
}

# HTTP 请求头模板
DEFAULT_HEADERS = {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Cache-Control": "no-cache",
    "Content-Type": "application/json;charset=utf-8",
    "Origin": "https://web.oopz.cn",
    "Pragma": "no-cache",
    "Priority": "u=1, i",
    "Sec-Ch-Ua": '"Chromium";v="140", "Not=A?Brand";v="24", "Google Chrome";v="140"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
}

# Redis 配置
REDIS_CONFIG = {
    "host": "127.0.0.1",
    "port": 6379,
    "password": "",
    "db": 0,
    "decode_responses": True,
    "socket_connect_timeout": 3.0,
    "socket_timeout": 5.0,
    "health_check_interval": 30,
}

# 网易云音乐 API 配置
NETEASE_CLOUD = {
    "base_url": "http://localhost:3000",   # 网易云音乐 API 服务地址
    "cookie": "",                          # 可选，登录后的 MUSIC_U Cookie
    "auto_start_path": "NeteaseCloudMusicApi",  # 相对于项目根目录，留空则不自动启动
    # 弱网优化（网络差、播放卡顿时可调大超时与重试，或使用 standard 音质）
    "audio_download_timeout": 120,         # 单次下载读超时(秒)
    "audio_download_retries": 2,           # 失败后重试次数
    "audio_quality": "standard",           # standard=标准(体积小) / exhigh=较高音质
}

# QQ 音乐配置（需部署 QQMusicApi 服务）
QQ_MUSIC_CONFIG = {
    "enabled": False,
    "base_url": "http://localhost:3300",   # QQ 音乐 API 服务地址
    "cookie": "",                          # 可选，登录后的 Cookie
}

# B 站音乐配置
BILIBILI_MUSIC_CONFIG = {
    "enabled": False,
    "cookie": "",  # 可选，B 站 Cookie（获取更高音质需要）
}

# LOL 插件配置
# 已迁移到 config/plugins/lol_ban/config.json 与 config/plugins/lol_fa8/config.json（见 config/plugins/README.md）


# Web 播放器配置
WEB_PLAYER_CONFIG = {
    "url": "",       # 留空则自动检测（公网 IPv4 优先）；使用 Nginx 反代时填写对外地址，如 https://your-domain.com
    "host": "0.0.0.0",  # 监听地址，一般不改
    "port": 8080,    # 内部监听端口；使用 Nginx 反代时无需对外暴露，由 Nginx 统一通过 80/443 转发
    "token_ttl_seconds": 86400,  # Web 随机访问令牌有效期（秒），0=不过期（不建议）
    "cookie_max_age_seconds": 86400,  # 浏览器 cookie 有效期（秒）；留空则跟 token_ttl_seconds 一致
    "cookie_secure": False,  # True=仅 HTTPS 发送 cookie；使用 Nginx + SSL 时应设为 True
    "send_link_enabled": True,  # 点歌通知中是否发送 Web 播放器链接
    "link_idle_release_seconds": 1800,  # 播放列表空闲超过该秒数后，释放随机播放器链接（0=不释放）
    # 管理后台（访问 /admin）
    "admin_enabled": False,  # 是否启用管理后台
    "admin_password": "",    # 后台登录密码（强烈建议设置强密码）
    "admin_session_ttl_seconds": 43200,  # 后台登录会话有效期（秒），0=不过期（不建议）
    "admin_cookie_secure": False,  # 后台 cookie 是否仅 HTTPS 发送；使用 Nginx + SSL 时应设为 True（纯 HTTP 访问时自动降级）
    "admin_login_max_failures": 5,   # 同一 IP 连续登录失败多少次后锁定；0 关闭锁定
    "admin_login_lock_seconds": 300, # 锁定时长（秒）；0 关闭锁定
    # 仅当 TCP 对端属于以下网段时才信任 X-Real-IP / X-Forwarded-For。
    # 裸机 Nginx 默认走回环；Docker Compose 会用环境变量覆盖为容器内 Nginx 的固定地址。
    "trusted_proxy_cidrs": ["127.0.0.1/32", "::1/128"],
}

# 网页屏幕共享
SCREEN_SHARE_CONFIG = {
    "enabled": False,
    "agora_app_id": "",              # 声网项目 App ID（32 位十六进制）
    "agora_app_certificate": "",     # 声网项目 App Certificate；不要提交真实值
    "presenter_link_ttl_seconds": 600,
    "session_max_seconds": 14400,
    "rtc_token_ttl_seconds": 3600,
    "default_quality": "1080p",      # 2k=最高画质；1080p=清晰优先；720p=流畅优先
}

# OneBot v11 旁路服务配置
# 默认关闭。启用后，当前 Oopz Bot 会继续照常运行，同时额外提供 OneBot v11 HTTP / WebSocket 接口。
ONEBOT_V11_CONFIG = {
    "enabled": False,
    "host": "127.0.0.1",
    "port": 6700,
    "access_token": "",
    "secret": "",
    "db_path": "data/onebot_v11.sqlite3",

    # HTTP action: /send_msg、/get_status 等
    "enable_http": True,
    # 正向 WebSocket: /api、/event、/
    "enable_ws": True,

    # HTTP POST 事件上报
    "enable_http_post": False,
    "http_post_urls": [],
    "http_post_timeout": 0.0,

    # 反向 WebSocket
    "enable_ws_reverse": False,
    "ws_reverse_url": "",
    "ws_reverse_api_url": "",
    "ws_reverse_event_url": "",
    "ws_reverse_reconnect_interval": 3.0,
    "send_connect_event": True,

    # OneBot 级心跳元事件（部分框架靠它判活），间隔单位秒
    "heartbeat_enabled": True,
    "heartbeat_interval": 15.0,

    # get_group_member_list 单次返回成员上限（0 表示不限制）
    "member_list_max": 5000,

    # 高风险群管理动作默认关闭；开启后会映射到 Oopz 域级操作
    "enable_area_scoped_group_ban": False,
    "enable_set_group_kick_as_area_kick": False,
    "enable_set_group_leave_as_area_leave": False,
    # set_group_admin 映射为给/取消域身份组；需同时配置 group_admin_role_id
    "enable_set_group_admin_as_area_role": False,
    "group_admin_role_id": 0,
}

# Bot 消息自动撤回配置
AUTO_RECALL_CONFIG = {
    "enabled": False,
    "delay": 30,                   # 自动撤回延迟（秒）
    "max_pending": 1000,           # 最多等待撤回的消息数，防止刷屏时占用过多内存
}

# 域成员加入/退出通知：有人加入或退出当前域时 Bot 在公屏发送消息
# 默认轮询域管理日志接口；如需旧快照方案，可将 event_source 改为 member_snapshot
AREA_JOIN_NOTIFY = {
    "enabled": False,
    "event_source": "operate_logs",  # 成员事件来源：operate_logs=管理日志轮询；member_snapshot=成员列表快照对比
    "message_template": "欢迎 {name} 加入域～\n请阅读频道规则，祝你玩得开心！",  # 加入时消息，占位符: {name} {uid}；支持多行
    "message_template_leave": "{name} 已退出域",  # 退出时消息；留空("")则不在频道发提示，但 OneBot group_decrease 仍推送
    "poll_interval_seconds": 2,   # 轮询间隔（秒），最小 2；遇到 429 会自动退避并临时放慢
    "auto_assign_role_id": "",    # 新人自动分配的身份组 ID，留空则不分配
    "auto_assign_role_name": "",  # 或用身份组名称匹配（优先使用 role_id）
    "member_fetch_max": 5000,     # 单次成员快照翻页上限；超过该人数的域会暂停加入/退出检测并告警
}

# 聊天自动回复配置
CHAT_CONFIG = {
    "enabled": True,
    "keyword_replies": {
        "你好": "你好呀！我是 Oopz Bot ~",
        "帮助": "输入 /help 查看可用命令",
        "ping": "pong!",
    },
}

# 定时消息调度配置
SCHEDULER_CONFIG = {
    "enabled": True,
    "check_interval_seconds": 30,  # 检查间隔（秒），最小 10
}

# 用户提醒配置
REMINDER_CONFIG = {
    "enabled": True,
    "max_per_user": 5,             # 每用户最大待执行提醒数
    "max_delay_hours": 72,         # 最大提醒延迟（小时）
    "check_interval_seconds": 15,  # 检查间隔（秒），最小 5
}

# 消息统计配置
MESSAGE_STATS_CONFIG = {
    "enabled": True,
}

# 音乐播放配置
MUSIC_CONFIG = {
    "auto_play_enabled": True,          # 队列播完是否自动随机播放喜欢列表
    "default_volume": 50,               # 默认音量 (0-100)
}

# 命令冷却配置
COMMAND_COOLDOWN_CONFIG = {
    "enabled": False,
    "default_seconds": 3,              # 默认命令冷却时间（秒）
    "exempt_admins": True,             # 管理员是否免冷却
}

# 多域配置（可选）
# 为每个域配置独立的参数，不配或留空则所有域共享全局配置
# 键为域 ID，值为该域的个性化配置
AREA_CONFIGS = {
    # "域ID": {
    #     "name": "域名称（仅供日志显示）",
    #     "default_channel": "该域默认发送频道 ID",
    #     "welcome_message": "欢迎 {name} 加入～",      # 占位符: {name} {uid}
    #     "leave_message": "{name} 已退出域",
    #     "auto_assign_role_id": "",                      # 新人自动分配的身份组 ID
    #     "auto_assign_role_name": "",                    # 或用身份组名称匹配
    #     "admin_uids": [],                               # 该域独立管理员，空则继承全局 ADMIN_UIDS
    #     "plugins_enabled": [],                          # 空=全部启用
    #     "plugins_disabled": [],                         # 禁用的插件名列表
    # },
}

# Bot 管理员列表（只有这些用户可以执行指令，其他用户无权限）
# 填入用户 UID，留空则不做权限限制（所有人可用）
ADMIN_UIDS = [
    # "用户UID",
]

# 名称映射表（手动配置 ID → 显示名称）
# Bot 运行时会自动发现新 ID 并记录到 names.json，你可以在里面补充名称
NAME_MAP = {
    "users": {
        # "用户UID": "昵称",
    },
    "channels": {
        # "频道ID": "频道名称",
    },
    "areas": {
        # "区域ID": "区域名称",
    },
}
