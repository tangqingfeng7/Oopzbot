"""
Oopz Bot 配置文件示例
复制此文件为 config.py 并填写真实配置
"""

# Oopz 平台配置
OOPZ_CONFIG = {
    "app_version": "69514",
    "channel": "Web",
    "platform": "windows",
    "web": True,
    "base_url": "https://gateway.oopz.cn",
    "api_url": "https://api.oopz.cn",       # 公共 API（成员、个人信息、语录等）

    # === 以下需要手动填写 ===
    "device_id": "",       # 设备 ID
    "person_uid": "",      # 用户 UID
    "jwt_token": "",       # JWT Token（从 Oopz 客户端获取）

    "default_area": "",    # 默认区域 ID
    "default_channel": "", # 默认频道 ID
    "use_announcement_style": True,  # 发送消息默认是否使用公告样式（styleTags=IMPORTANT）

    # Agora RTC（语音频道推流，仅 Linux/macOS 可用）
    "agora_app_id": "358eebceadb94c2a9fd91ecd7b341602",
    "agora_init_timeout": 1800,  # Playwright 浏览器启动等待秒数，首启或网络慢可调大

    # 代理：不设或 "" = 使用系统代理(HTTP_PROXY/HTTPS_PROXY)；False 或 "direct" = 直连不走代理；或 "http://127.0.0.1:7890"
    "proxy": "",  # 若本机未开代理却设置了环境变量，可设为 False 或 "direct" 避免连 127.0.0.1:7890 被拒
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

# 豆包 AI 配置（火山方舟，OpenAI 兼容接口）
DOUBAO_CONFIG = {
    "enabled": False,
    "base_url": "https://ark.cn-beijing.volces.com/api/v3",
    "api_key": "",                         # 火山方舟 API Key
    "model": "doubao-1-5-pro-32k-250115",
    "system_prompt": "你是 Oopz Bot，一个活泼有趣的聊天机器人。回复简洁友好，不超过100字。",
    "max_tokens": 256,
    "temperature": 0.7,
}

# 豆包图片生成配置（Seedream 文生图）
DOUBAO_IMAGE_CONFIG = {
    "enabled": False,
    "base_url": "https://ark.cn-beijing.volces.com/api/v3",
    "api_key": "",                         # 火山方舟 API Key
    "model": "doubao-seedream-4-5-251128",
    "size": "1920x1920",
    "watermark": False,
}

# LOL 插件配置
# 已迁移到 config/plugins/lol_ban.json 与 config/plugins/lol_fa8.json（见 config/plugins/README.md）

# 脏话自动禁言配置
PROFANITY_CONFIG = {
    "enabled": True,
    "mute_duration": 5,           # 禁言时长（分钟），仅支持: 1, 5, 60, 1440, 4320, 10080
    "recall_message": True,       # 是否自动撤回脏话消息
    "skip_admins": True,          # 管理员是否免检
    "warn_before_mute": False,    # 是否先警告再禁言（False=直接禁言）
    "context_detection": True,    # 上下文检测（拆字发送也能识别）
    "context_window": 30,         # 上下文时间窗口（秒），拼接该窗口内同一用户的连续消息
    "context_max_messages": 10,   # 上下文最多回溯消息条数
    "ai_detection": True,         # AI 辅助检测（关键词未命中时让 AI 判断，需启用豆包 AI）
    "ai_min_length": 2,           # 触发 AI 检测的最短消息长度
    "keywords": [
        # ── 傻逼 系列（谐音 + 变体）──
        "傻逼", "傻比", "傻币", "傻笔", "傻屄", "傻b", "傻鼻", "傻必",
        "煞逼", "煞比", "煞笔", "煞币",
        "沙逼", "沙比", "沙币",
        "杀逼", "杀比", "啥比", "啥逼", "刹比", "刹逼",
        "sb", "shabi",

        # ── 操/草/日 你妈 系列 ──
        "操你妈", "草你妈", "艹你妈", "日你妈", "肏你妈", "干你妈",
        "操你马", "草你马", "艹你马", "日你马",
        "操你麻", "草你麻", "日你麻",
        "操尼玛", "草尼玛", "艹尼玛", "日尼玛",
        "曹你妈", "曹尼玛", "曹你马", "嘈你妈",
        "操你娘", "草你娘", "日你娘",
        "操你大爷", "日你大爷",

        # ── 你妈/妈的 系列 ──
        "你妈逼", "你妈比", "你马逼", "你马比", "尼玛逼", "尼玛比",
        "你麻逼", "你麻比", "你码逼",
        "你妈的", "他妈的", "妈的", "他妈",
        "你麻的", "他麻的", "你马的",
        "你妈了个", "妈了个逼", "妈了个比",
        "我日", "我操", "我草", "我艹", "卧槽",

        # ── 死/诅咒 系列（含谐音: 斯/思/司/四/屎 代 死）──
        "死妈", "死爸", "死爹", "死娘",
        "斯妈", "斯爸", "斯爹", "斯娘",
        "思妈", "司妈", "四妈",
        "你妈死", "妈死了", "爸死了", "爹死了",
        "你妈斯", "你妈思",
        "死全家", "全家死", "全家死光", "全家暴毙", "全家不得好死",
        "斯全家", "全家斯", "思全家", "全家思",
        "一家死光", "全家完蛋",
        "去死", "找死", "该死", "快死", "怎么不去死",
        "去斯", "找斯", "该斯", "快斯",
        "死吧", "死去吧", "赶紧死", "早点死",
        "斯吧", "赶紧斯", "早点斯",
        "断子绝孙", "不得好死", "不得好斯",

        # ── 狗 系列（含谐音: 苟/勾 代 狗）──
        "狗逼", "狗比", "狗b",
        "苟逼", "苟比", "勾逼", "勾比",
        "狗日", "狗日的", "狗娘养的", "狗娘养",
        "狗杂种", "狗东西", "狗玩意",
        "苟日的", "苟杂种", "苟东西",

        # ── 贱/婊/骚 系列 ──
        "贱人", "贱货", "贱逼", "贱比", "贱b", "贱种",
        "婊子", "表子", "绿茶婊",
        "骚货", "骚逼", "骚比", "骚b",
        "下贱", "卑鄙",

        # ── 侮辱智力 ──
        "脑残", "智障", "弱智", "白痴", "低能", "憨逼", "憨比",
        "脑瘫", "神经病", "有病",
        "闹残", "脑惨", "制杖", "若智",
        "mdzz", "nc",

        # ── 废物/人渣/畜生 ──
        "废物", "人渣", "垃圾人", "畜生", "畜牲", "牲口",
        "败类", "杂种", "野种",

        # ── 混蛋/王八 系列 ──
        "混蛋", "浑蛋", "王八蛋", "王八", "龟儿子", "龟孙子", "乌龟",

        # ── 滚 系列 ──
        "滚蛋", "滚犊子", "滚你妈", "滚你马", "滚出去", "爬",

        # ── 谐音/变体 ──
        "尼玛", "你马", "泥马", "你麻痹", "你妈痹", "你码痹",
        "草泥马", "草拟马", "曹泥马",
        "特么", "tm的",
        "屎妈", "屎全家", "屎爸", "屎爹",

        # ── 英文 / 拼音缩写 ──
        "cnm", "nmsl", "wcnm", "rnm", "wdnmd", "nmlgb", "mlgb",
        "dllm", "tmlgb", "qnmd",
        "caonima", "nimabi", "nmsld",
        "fuck", "fck", "f*ck", "shit", "bitch", "stfu",
        "motherfucker", "asshole", "dick",
    ],
}

# Web 播放器配置
WEB_PLAYER_CONFIG = {
    "url": "",       # 留空则自动检测（公网 IPv4 优先）；也可手动填写，如 http://你的公网IP:端口
    "host": "0.0.0.0",  # 监听地址，一般不改
    "port": 8080,    # 若 8080 无法访问（被防火墙/运营商封），可改为 3001 等与 3000 同网段端口
    "token_ttl_seconds": 86400,  # Web 随机访问令牌有效期（秒），0=不过期（不建议）
    "cookie_max_age_seconds": 86400,  # 浏览器 cookie 有效期（秒）；留空则跟 token_ttl_seconds 一致
    "cookie_secure": False,  # True=仅 HTTPS 发送 cookie；纯 http 环境请保持 False
    "link_idle_release_seconds": 1800,  # 播放列表空闲超过该秒数后，释放随机播放器链接（0=不释放）
}

# Bot 消息自动撤回配置
AUTO_RECALL_CONFIG = {
    "enabled": False,
    "delay": 30,                   # 自动撤回延迟（秒）
    "exclude_commands": [          # 不自动撤回的命令类型
        "ai_chat",                 # AI 聊天回复
        "ai_image",                # AI 生成图片
    ],
}

# 域成员加入/退出通知：有人加入或退出当前域时 Bot 在公屏发送消息
# 退出：WebSocket 推送；加入：轮询域成员 API 检测新成员（因服务端不推送加入事件）
AREA_JOIN_NOTIFY = {
    "enabled": False,
    "message_template": "欢迎 {name} 加入域～",  # 加入时消息，占位符: {name} {uid}
    "message_template_leave": "{name} 已退出域",  # 退出时消息
    "poll_interval_seconds": 1,   # 轮询间隔（秒），最小 1；发欢迎后 0.5 秒即下次轮询
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
