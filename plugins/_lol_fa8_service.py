"""
英雄联盟战绩查询 (FA8)
通过 fa.3ui.cc API 自动登录并查询召唤师战绩
"""

import hashlib
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from logger_config import get_logger

logger = get_logger("FA8")

BASE_URL = "https://fa.3ui.cc"

_DEFAULT_CONFIG = {
    "enabled": False,
    "username": "",
    "password": "",
    "default_area": "1",
}

SERVERS = {
    "1": "艾欧尼亚", "2": "比尔吉沃特", "3": "祖安", "4": "诺克萨斯",
    "5": "班德尔城", "6": "德玛西亚", "7": "皮尔特沃夫", "8": "战争学院",
    "9": "弗雷尔卓德", "10": "巨神峰", "11": "雷瑟守备", "12": "无畏先锋",
    "13": "裁决之地", "14": "黑色玫瑰", "15": "暗影岛", "16": "恕瑞玛",
    "17": "钢铁烈阳", "18": "水晶之痕", "19": "均衡教派", "20": "扭曲丛林",
    "21": "教育网专区", "22": "影流", "23": "守望之海", "24": "征服之海",
    "25": "卡拉曼达", "26": "巨龙之巢", "27": "皮城警备", "30": "男爵领域",
    "31": "峡谷之巅",
}

SERVER_NAME_TO_ID = {v: k for k, v in SERVERS.items()}

SERVER_GROUPS: dict[str, list[str]] = {
    "一区": ["3", "7", "10", "19", "21", "22", "23", "30"],
    "二区": ["4", "8", "11", "15", "24", "25"],
    "三区": ["5", "13", "17", "18", "27"],
    "四区": ["2", "9", "20"],
    "五区": ["6", "12", "16", "26"],
}

GROUP_ALIASES: dict[str, str] = {}
_NUM_MAP = {"一区": "1", "二区": "2", "三区": "3", "四区": "4", "五区": "5"}
for _g in SERVER_GROUPS:
    GROUP_ALIASES[_g] = _g
    GROUP_ALIASES[f"联盟{_g}"] = _g
    if _g in _NUM_MAP:
        GROUP_ALIASES[_NUM_MAP[_g]] = _g


def _md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _ts() -> int:
    return int(time.time() * 1000)


_RE_MASTERY = re.compile(
    r'alt="([^"]+)".*?'
    r'class="font-medium text-white mr-2">([^<]+)</span>.*?'
    r'text-gray-400">(\d+级英雄成就)</span>.*?'
    r'熟练度：(\d+)',
    re.DOTALL,
)
_RE_CARD_SPLIT = re.compile(r'class="match-card\s+')
_RE_CHAMP = re.compile(r'champion/(\w+)\.png')
_RE_KDA = re.compile(r'font-bold text-white">(\d+/\d+/\d+)<')
_RE_SCORE = re.compile(r'评分\s*([\d.]+)')
_RE_MODE = re.compile(r'text-xs">([^<]+)</span>\s*<span[^>]*>时长([\d:]+)')
_RE_DATE = re.compile(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})')
_RE_HERO = re.compile(r"英雄:\s*(\d+)\s*个")
_RE_SKIN = re.compile(r"皮肤:\s*(\d+)\s*个")

# 英雄英文 ID（API/图片路径用）→ 中文名，用于最近对局展示
CHAMPION_EN_TO_CN = {
    "Aatrox": "亚托克斯", "Ahri": "阿狸", "Akali": "阿卡丽", "Akshan": "阿克尚",
    "Alistar": "阿利斯塔", "Amumu": "阿木木", "Anivia": "艾尼维亚", "Annie": "安妮",
    "Aphelios": "厄斐琉斯", "Ashe": "艾希", "AurelionSol": "奥瑞利安·索尔", "Azir": "阿兹尔",
    "Bard": "巴德", "Belveth": "卑尔维斯", "Blitzcrank": "布里茨", "Brand": "布兰德",
    "Braum": "布隆", "Caitlyn": "凯特琳", "Camille": "卡蜜尔", "Cassiopeia": "卡西奥佩娅",
    "Chogath": "科加斯", "Corki": "库奇", "Darius": "德莱厄斯", "Diana": "黛安娜",
    "DrMundo": "蒙多", "Draven": "德莱文", "Ekko": "艾克", "Elise": "伊莉丝",
    "Evelynn": "伊芙琳", "Ezreal": "伊泽瑞尔", "Fiddlesticks": "费德提克", "Fiora": "菲奥娜",
    "Fizz": "菲兹", "Galio": "加里奥", "Gangplank": "普朗克", "Garen": "盖伦",
    "Gnar": "纳尔", "Gragas": "古拉加斯", "Graves": "格雷福斯", "Gwen": "格温",
    "Hecarim": "赫卡里姆", "Heimerdinger": "黑默丁格", "Illaoi": "俄洛伊", "Irelia": "艾瑞莉娅",
    "Ivern": "艾翁", "Janna": "迦娜", "JarvanIV": "嘉文四世", "Jax": "贾克斯",
    "Jayce": "杰斯", "Jhin": "烬", "Jinx": "金克丝", "Kaisa": "卡莎",
    "Kalista": "卡莉丝塔", "Karma": "卡尔玛", "Karthus": "卡尔萨斯", "Kassadin": "卡萨丁",
    "Katarina": "卡特琳娜", "Kayle": "凯尔", "Kayn": "凯隐", "Kennen": "凯南",
    "Khazix": "卡兹克", "Kindred": "千珏", "Kled": "克烈", "KogMaw": "克格莫",
    "Leblanc": "乐芙兰", "LeeSin": "李青", "Leona": "蕾欧娜", "Lillia": "莉莉娅",
    "Lissandra": "丽桑卓", "Lucian": "卢锡安", "Lulu": "璐璐", "Lux": "拉克丝",
    "Malphite": "墨菲特", "Malzahar": "马尔扎哈", "Maokai": "茂凯", "MasterYi": "易",
    "MissFortune": "厄运小姐", "Mordekaiser": "莫德凯撒", "Morgana": "莫甘娜", "Nami": "娜美",
    "Nasus": "内瑟斯", "Nautilus": "诺提勒斯", "Neeko": "妮蔻", "Nidalee": "奈德丽",
    "Nocturne": "梦魇", "Nunu": "努努", "Olaf": "奥拉夫", "Orianna": "奥莉安娜",
    "Ornn": "奥恩", "Pantheon": "潘森", "Poppy": "波比", "Pyke": "派克",
    "Qiyana": "奇亚娜", "Quinn": "奎因", "Rakan": "洛", "Rammus": "拉莫斯",
    "RekSai": "雷克塞", "Rell": "芮尔", "Renata": "烈娜塔", "Renekton": "雷克顿",
    "Rengar": "雷恩加尔", "Riven": "锐雯", "Rumble": "兰博", "Ryze": "瑞兹",
    "Samira": "萨弥拉", "Sejuani": "瑟庄妮", "Senna": "赛娜", "Seraphine": "萨勒芬妮",
    "Sett": "瑟提", "Shaco": "萨科", "Shen": "慎", "Shyvana": "希瓦娜",
    "Singed": "辛吉德", "Sion": "赛恩", "Sivir": "希维尔", "Skarner": "斯卡纳",
    "Sona": "娑娜", "Soraka": "索拉卡", "Swain": "斯维因", "Sylas": "塞拉斯",
    "Syndra": "辛德拉", "TahmKench": "塔姆", "Taliyah": "塔莉垭", "Talon": "泰隆",
    "Taric": "塔里克", "Teemo": "提莫", "Thresh": "锤石", "Tristana": "崔丝塔娜",
    "Trundle": "特朗德尔", "Tryndamere": "泰达米尔", "TwistedFate": "崔斯特", "Twitch": "图奇",
    "Udyr": "乌迪尔", "Urgot": "厄加特", "Varus": "韦鲁斯", "Vayne": "薇恩",
    "Veigar": "维迦", "Velkoz": "维克兹", "Vex": "薇古丝", "Vi": "蔚",
    "Viego": "佛耶戈", "Viktor": "维克托", "Vladimir": "弗拉基米尔", "Volibear": "沃利贝尔",
    "Warwick": "沃里克", "Xayah": "霞", "Xerath": "泽拉斯", "XinZhao": "赵信",
    "Yasuo": "亚索", "Yone": "永恩", "Yorick": "约里克", "Yuumi": "悠米",
    "Zac": "扎克", "Zed": "劫", "Zeri": "泽丽", "Ziggs": "吉格斯",
    "Zilean": "基兰", "Zoe": "佐伊", "Zyra": "婕拉",
}


def _champion_cn(en_key: str) -> str:
    """将英雄英文 ID 转为中文名，未知则返回原样"""
    if not en_key:
        return en_key
    key = en_key.strip()
    if key in CHAMPION_EN_TO_CN:
        return CHAMPION_EN_TO_CN[key]
    # 兼容小写或首字母大写的 key（如 neeko -> Neeko）
    key_alt = key[0].upper() + key[1:].lower() if len(key) > 1 else key.upper()
    return CHAMPION_EN_TO_CN.get(key_alt, en_key)


def _parse_mastery(html: str) -> list[dict]:
    """从 mastery HTML 中解析英雄熟练度列表"""
    results = []
    for m in _RE_MASTERY.finditer(html):
        results.append({
            "name": m.group(2),
            "level": m.group(3),
            "points": int(m.group(4)),
        })
    return results


def _parse_match_cards(html: str) -> list[dict]:
    """从战绩 HTML 中解析对局列表（分段解析避免回溯）"""
    results = []
    cards = _RE_CARD_SPLIT.split(html)
    for card in cards[1:]:
        try:
            win_lose = "胜利" if card.startswith("win") else "失败"
            champ_m = _RE_CHAMP.search(card)
            kda_m = _RE_KDA.search(card)
            if not (champ_m and kda_m):
                continue
            score_m = _RE_SCORE.search(card)
            mode_m = _RE_MODE.search(card)
            date_m = _RE_DATE.search(card)
            results.append({
                "result": win_lose,
                "champion": champ_m.group(1),
                "kda": kda_m.group(1),
                "score": score_m.group(1) if score_m else "",
                "mode": mode_m.group(1) if mode_m else "",
                "duration": mode_m.group(2) if mode_m else "",
                "date": date_m.group(1) if date_m else "",
            })
        except Exception:
            continue
    return results


class FA8Client:
    """FA8 API 客户端，自动管理登录态，后台线程每 5 秒检查并保活"""

    _KEEPALIVE_INTERVAL = 5  # 秒

    def __init__(self, username: str = "", password: str = ""):
        self._user = (username or "").strip()
        self._pwd = (password or "").strip()
        self._session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=10, pool_maxsize=10,
        )
        self._session.mount("https://", adapter)
        self._session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/140.0.0.0 Safari/537.36"
            ),
            "Origin": BASE_URL,
            "Referer": f"{BASE_URL}/",
            "Connection": "keep-alive",
        })
        self._pool = ThreadPoolExecutor(max_workers=10, thread_name_prefix="FA8")
        self._logged_in = False
        self._lock = threading.Lock()
        self._keepalive_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._start_keepalive()

    # ------------------------------------------------------------------
    # 登录保活
    # ------------------------------------------------------------------

    def _start_keepalive(self):
        """启动后台保活线程"""
        if not self._user or not self._pwd:
            return
        if self._keepalive_thread and self._keepalive_thread.is_alive():
            return
        self._stop_event.clear()
        self._keepalive_thread = threading.Thread(
            target=self._keepalive_loop, daemon=True, name="FA8-keepalive",
        )
        self._keepalive_thread.start()
        logger.info("FA8 保活线程已启动 (间隔 %ds)", self._KEEPALIVE_INTERVAL)

    def _keepalive_loop(self):
        """后台循环：检查登录状态，失效则自动重新登录"""
        while not self._stop_event.is_set():
            try:
                self._check_and_login()
            except Exception as e:
                logger.debug(f"FA8 保活检查异常: {e}")
            self._stop_event.wait(self._KEEPALIVE_INTERVAL)

    def _check_and_login(self):
        """检查 Cookie 是否有效，无效则重新登录"""
        with self._lock:
            cookies = {c.name: c.value for c in self._session.cookies}
            if cookies.get("name") and cookies.get("sign"):
                self._logged_in = True
                return
            self._logged_in = False
            self._do_login()

    def _do_login(self) -> bool:
        """执行登录请求（调用方需持有 _lock）"""
        try:
            ts = _ts()
            resp = self._session.post(
                f"{BASE_URL}/api/api.php?act=login",
                data={"user": self._user, "pwd": self._pwd, "time": ts},
                timeout=15,
            )
            data = resp.json()
            if data.get("code") == 0:
                self._logged_in = True
                logger.info("FA8 登录成功")
                return True
            logger.warning(f"FA8 登录失败: {data.get('msg', '未知错误')}")
            return False
        except Exception as e:
            logger.error(f"FA8 登录异常: {e}")
            return False

    def _ensure_login(self) -> bool:
        if self._logged_in:
            return True
        with self._lock:
            if self._logged_in:
                return True
            if not self._user or not self._pwd:
                logger.error("FA8 账号或密码未配置")
                return False
            return self._do_login()

    def _post_api(self, endpoint: str, data: dict, retry: bool = True) -> dict:
        """发送 API 请求，自动处理登录"""
        if not self._ensure_login():
            return {"code": -1, "msg": "登录失败，请检查 FA8 账号配置"}
        try:
            resp = self._session.post(
                f"{BASE_URL}/api/{endpoint}",
                data=data,
                timeout=10,
            )
            result = resp.json()
            msg = str(result.get("msg", ""))
            is_auth_error = result.get("code") != 0 and "登录" in msg
            if is_auth_error and retry:
                self._logged_in = False
                return self._post_api(endpoint, data, retry=False)
            return result
        except Exception as e:
            logger.error(f"FA8 API 请求失败 [{endpoint}]: {e}")
            return {"code": -1, "msg": f"请求异常: {e}"}

    def query_summoner(self, name: str, area: str) -> dict:
        """查询召唤师基本信息"""
        ts = _ts()
        sign = _md5(f"{name}{ts}{area}{ts}#6352")
        return self._post_api("tyapi.php?act=cxinfo", {
            "name": name, "area": area, "sign": sign, "time": ts,
        })

    def query_games(self, puuid: str, area: str, tag: str = "all", page: str = "0") -> dict:
        """查询历史战绩"""
        ts = _ts()
        sign = _md5(f"{puuid}{ts}{area}{ts}{tag}{page}#6662")
        return self._post_api("tyapi.php?act=cxgame", {
            "puuid": puuid, "area": area, "page": page,
            "sign": sign, "tag": tag, "time": ts,
        })

    def query_current_game(self, puuid: str, area: str) -> dict:
        """查询当前对局"""
        ts = _ts()
        sign = _md5(f"{puuid}{ts}{area}{ts}#6362")
        return self._post_api("tyapi.php?act=nowcx", {
            "puuid": puuid, "area": area, "sign": sign, "time": ts,
        })

    def stop(self):
        """停止保活线程并释放网络/线程池资源。"""
        self._stop_event.set()
        if self._keepalive_thread and self._keepalive_thread.is_alive():
            self._keepalive_thread.join(timeout=2)
        try:
            self._pool.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        try:
            self._session.close()
        except Exception:
            pass


class FA8Handler:
    """FA8 战绩查询命令处理器"""

    def __init__(self, config: dict | None = None):
        self._config = _DEFAULT_CONFIG.copy()
        if config:
            self._config.update(config)
        self._client = FA8Client(
            username=self._config.get("username", ""),
            password=self._config.get("password", ""),
        )

    def close(self):
        """释放内部客户端资源（插件卸载时调用）。"""
        try:
            self._client.stop()
        except Exception:
            pass

    def _resolve_area(self, text: str) -> tuple[str, list[str]]:
        """
        从输入文本中解析大区和召唤师名。
        返回 (召唤师名, 大区ID列表)。
        支持格式:
          - "召唤师名#编号"              → 使用默认大区
          - "大区名 召唤师名#编号"       → 指定大区
          - "一区 召唤师名#编号"         → 搜索整个区组
          - "联盟一区 召唤师名#编号"     → 搜索整个区组
        """
        text = text.strip()
        default_area = self._config.get("default_area", "1")

        parts = text.split(None, 1)
        if len(parts) == 2:
            prefix = parts[0]
            if prefix in GROUP_ALIASES:
                return parts[1], SERVER_GROUPS[GROUP_ALIASES[prefix]]
            if prefix in SERVERS:
                return parts[1], [prefix]
            if prefix in SERVER_NAME_TO_ID:
                return parts[1], [SERVER_NAME_TO_ID[prefix]]

        for server_name, server_id in SERVER_NAME_TO_ID.items():
            if text.startswith(server_name):
                name = text[len(server_name):].strip()
                if name:
                    return name, [server_id]

        return text, [default_area]

    def _search_summoner(self, name: str, areas: list[str]) -> tuple[str, dict] | None:
        """在多个大区中并行搜索召唤师，返回 (area_id, info) 或 None"""
        if len(areas) == 1:
            info = self._client.query_summoner(name, areas[0])
            if info.get("code") == 0:
                return areas[0], info
            return None

        pool = self._client._pool
        futures = {
            pool.submit(self._client.query_summoner, name, a): a
            for a in areas
        }
        try:
            for fut in as_completed(futures):
                try:
                    info = fut.result()
                    if info.get("code") == 0:
                        return futures[fut], info
                except Exception:
                    pass
        finally:
            for fut in futures:
                fut.cancel()
        return None

    def query_and_format(self, raw_input: str) -> str:
        """查询召唤师战绩并格式化为消息文本"""
        if not self._config.get("enabled", False):
            return "战绩查询功能未启用，请在 config/plugins/lol_fa8.json 中配置"

        name, areas = self._resolve_area(raw_input)
        if not name:
            return (
                "请输入召唤师名称\n"
                "格式: @bot 战绩 召唤师名#编号\n"
                "示例: @bot 战绩 召唤师名#编号\n"
                "指定大区: @bot 战绩 班德尔城 召唤师名#编号\n"
                "按区搜索: @bot 战绩 3 召唤师名#编号 (1-5对应联盟一~五区)"
            )

        is_group = len(areas) > 1
        group_label = ""
        if is_group:
            for alias, g in GROUP_ALIASES.items():
                if SERVER_GROUPS[g] == areas and not alias.startswith("联盟"):
                    group_label = f"联盟{alias}"
                    break

        result = self._search_summoner(name, areas)
        if result is None:
            if is_group:
                return f"[x] 在{group_label}所有服务器中均未找到该玩家"
            msg_area = SERVERS.get(areas[0], f"大区{areas[0]}")
            return f"[x] 在{msg_area}未找到该玩家"

        area, info = result
        msg = info.get("msg", "")
        if "登录" in str(msg):
            return f"[x] 查询失败: FA8 登录态异常，请联系管理员检查配置"

        puuid = info.get("puuid", "")
        server_name = SERVERS.get(area, f"大区{area}")

        lines = [
            f"LOL 战绩查询 - {server_name}",
            "═══════════════════",
            f"  召唤师: {name}",
            f"  等级: {info.get('level', '?')}",
            f"  最近游戏: {info.get('lastGameDate', '未知')}",
        ]

        hero_count = ""
        skin_count = ""
        skin_html = info.get("skin", "")
        hero_m = _RE_HERO.search(skin_html)
        skin_m = _RE_SKIN.search(skin_html)
        if hero_m:
            hero_count = hero_m.group(1)
        if skin_m:
            skin_count = skin_m.group(1)
        if hero_count or skin_count:
            lines.append(f"  英雄: {hero_count} 个 | 皮肤: {skin_count} 个")

        lines.append("───────────────────")
        lines.append("  段位信息:")

        # 将 FA8 返回的段位字段做一次“清洗”，把 "无"、"?"、"未定级" 等情况统一成“未定级 / 无段位”
        def _normalize_rank_text(text: str) -> str | None:
            if not text:
                return None
            t = str(text).strip()
            if t in ("无", "?", "-", "未定级", "未排位"):
                return None
            return t

        ds_dj_raw = info.get("dsdj", "")
        ds_dj = _normalize_rank_text(ds_dj_raw)
        if ds_dj:
            lines.append(f"    单双排位: {ds_dj} ({info.get('dssf', '')}) 胜点{info.get('dssd', 0)}")
        else:
            lines.append("    单双排位: 未定级 / 无段位")

        lh_dj_raw = info.get("lhdj", "")
        lh_dj = _normalize_rank_text(lh_dj_raw)
        if lh_dj:
            lines.append(f"    灵活排位: {lh_dj} ({info.get('lhsf', '')}) 胜点{info.get('lhsd', 0)}")
        else:
            lines.append("    灵活排位: 未定级 / 无段位")

        rank = info.get("rank", {})
        ds_best_raw = rank.get("dszgdw", "")
        ds_best = _normalize_rank_text(ds_best_raw)
        if ds_best:
            lines.append(f"    单双排位最高: {ds_best}")

        lh_best_raw = rank.get("lhzgdw", "")
        lh_best = _normalize_rank_text(lh_best_raw)
        if lh_best:
            lines.append(f"    灵活排位最高: {lh_best}")

        mastery_html = info.get("mastery", "")
        champions = _parse_mastery(mastery_html)
        if champions:
            lines.append("───────────────────")
            lines.append("  英雄熟练度 TOP5:")
            for i, c in enumerate(champions[:5], 1):
                lines.append(f"    {i}. {c['name']} - {c['level']} ({c['points']:,})")

        if puuid:
            pool = self._client._pool
            games_fut = pool.submit(self._client.query_games, puuid, area)
            current_fut = pool.submit(self._client.query_current_game, puuid, area)
            games = games_fut.result()
            current = current_fut.result()

            if games.get("code") == 0:
                win = games.get("win", 0)
                lose = games.get("lose", 0)
                sl = games.get("sl", 0)
                lines.append("───────────────────")
                lines.append(f"  近期战绩: {win}胜 {lose}负 (胜率{sl}%)")

                zj_html = games.get("zj", "")
                matches = _parse_match_cards(zj_html)
                if matches:
                    lines.append("  最近对局:")
                    for m in matches[:5]:
                        icon = "赢" if m["result"] == "胜利" else "输"
                        champ_cn = _champion_cn(m["champion"])

                        mode = m.get("mode") or ""
                        if mode:
                            mode = mode.replace("单排/双排", "单双排位")
                        score = m.get("score") or ""
                        duration = m.get("duration") or ""
                        date = m.get("date") or ""

                        mode_part = f"{mode} " if mode else ""
                        score_part = f" 评分{score}" if score else ""
                        duration_part = f" [{duration}]" if duration else ""
                        date_part = f" {date}" if date else ""

                        lines.append(
                            f"    {icon} {mode_part}{champ_cn} "
                            f"{m['kda']}{score_part}"
                            f"{duration_part}{date_part}"
                        )

            if current.get("code") == 0:
                lines.append("───────────────────")
                lines.append("  ★ 当前正在游戏中!")
                if current.get("mode"):
                    lines.append(f"    模式: {current['mode']}")

        lines.append("═══════════════════")
        return "\n".join(lines)

