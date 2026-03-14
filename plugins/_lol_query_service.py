"""
英雄联盟封号查询
通过 yun.4png.com API 查询 LOL 账号封禁状态（无需密码，按 QQ 号查询）
"""

import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from logger_config import get_logger

logger = get_logger("LolQuery")

_DEFAULT_CONFIG = {
    "enabled": False,
    "api_url": "",
    "token": "",
    "proxy": "",
}


class LolQueryHandler:
    """英雄联盟封号查询处理器"""

    def __init__(self, config: dict | None = None):
        self._config = _DEFAULT_CONFIG.copy()
        if config:
            self._config.update(config)

        self._api_url = self._config.get("api_url", "")
        self._token = self._config.get("token", "")
        proxy = self._config.get("proxy", "")
        # 指定了代理则使用指定的，否则传 None 让 requests 自动读取系统代理
        self._proxies = {"http": proxy, "https": proxy} if proxy else None

    _MAX_RETRIES = 2
    _RETRY_DELAY = 1  # seconds

    def _build_session(self) -> requests.Session:
        """构建带自动重试的 requests Session。"""
        session = requests.Session()
        retry_strategy = Retry(
            total=self._MAX_RETRIES,
            backoff_factor=1,
            status_forcelist=[502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def check_ban(self, qq: str) -> dict:
        """
        查询 QQ 号对应的 LOL 账号封禁状态。
        连接异常时最多重试 _MAX_RETRIES 次。

        Returns:
            {"ok": True, "data": {...}} 或 {"ok": False, "error": "..."}
        """
        last_err = None
        session = self._build_session()
        try:
            for attempt in range(1, self._MAX_RETRIES + 2):  # 1 次正常 + N 次重试
                try:
                    resp = session.get(
                        self._api_url,
                        params={"qq": qq, "token": self._token},
                        proxies=self._proxies,
                        timeout=10,
                    )
                    resp.raise_for_status()
                    data = resp.json()

                    if data.get("code") == 200:
                        return {"ok": True, "data": data}
                    else:
                        return {"ok": False, "error": data.get("msg", "查询失败")}

                except requests.Timeout:
                    logger.warning(f"封号查询超时 (第{attempt}次): qq={qq}")
                    last_err = "查询超时，请稍后再试"
                except (requests.ConnectionError, requests.exceptions.ChunkedEncodingError) as e:
                    logger.warning(f"封号查询连接异常 (第{attempt}次): qq={qq}, {e}")
                    last_err = "连接异常，请稍后再试"
                except Exception as e:
                    logger.error(f"封号查询失败: {e}")
                    return {"ok": False, "error": f"查询异常: {e}"}

                if attempt <= self._MAX_RETRIES:
                    time.sleep(self._RETRY_DELAY)

            logger.error(f"封号查询最终失败 (已重试{self._MAX_RETRIES}次): qq={qq}")
            return {"ok": False, "error": last_err or "查询失败，请稍后再试"}
        finally:
            try:
                session.close()
            except Exception:
                pass

    def query_and_format(self, qq: str) -> str:
        """查询并格式化为可发送的消息文本。"""
        qq = qq.strip()

        if not qq.isdigit():
            return "请输入正确的 QQ 号码（纯数字）\n示例: @bot 查封号 123456789"

        if not self._config.get("enabled", False):
            return "封号查询功能未启用"

        result = self.check_ban(qq)

        if not result["ok"]:
            return f"查询失败: {result['error']}"

        data = result["data"]
        ban_data = data.get("data", {})
        status = ban_data.get("return", "未知")
        msg = data.get("msg", "")

        lines = [f"[search] QQ {qq} 封号查询结果:\n"]

        if status == "封禁":
            lines.append(f"[x] 状态: 已封禁")
            if ban_data.get("banmsg"):
                lines.append(f"[detail] {ban_data['banmsg']}")
            if ban_data.get("rammsg"):
                lines.append(f"[time] {ban_data['rammsg']}")
        elif status == "正常":
            lines.append(f"[ok] 状态: 正常（未封禁）")
        else:
            lines.append(f"状态: {status}")

        if msg:
            lines.append(f"\n[msg] {msg}")

        return "\n".join(lines)
