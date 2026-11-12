"""
Shared proxy helpers for requests, websocket-client, Playwright, and Selenium.
"""

from __future__ import annotations

import ipaddress
import logging
import os
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

_log = logging.getLogger("ProxyUtils")

_DIRECT_VALUES = {"0", "false", "no", "none", "off", "direct"}

# 本地代理客户端（Clash / mihomo）的默认监听端口与回环地址。
# 集中定义，避免在多个别名里重复写死同一组端口；可被 config.PROXY_ALIAS_CONFIG 覆盖。
_DEFAULT_LOCAL_PROXY_HOST = "127.0.0.1"
_DEFAULT_CLASH_HTTP_PORT = 7890
_DEFAULT_CLASH_SOCKS_PORT = 7891


def _build_proxy_aliases() -> dict[str, str]:
    """构建 clash/mihomo 等别名 → 代理 URL 的映射。

    端口与回环地址默认沿用 Clash 习惯值，可通过 ``config.PROXY_ALIAS_CONFIG``
    覆盖（改了本地代理监听端口时无需改代码）。config 不可用时回退默认值。
    """
    host = _DEFAULT_LOCAL_PROXY_HOST
    http_port = _DEFAULT_CLASH_HTTP_PORT
    socks_port = _DEFAULT_CLASH_SOCKS_PORT
    try:
        from config import PROXY_ALIAS_CONFIG  # type: ignore

        host = str(PROXY_ALIAS_CONFIG.get("host") or host)
        http_port = int(PROXY_ALIAS_CONFIG.get("http_port") or http_port)
        socks_port = int(PROXY_ALIAS_CONFIG.get("socks_port") or socks_port)
    except Exception:
        pass

    http = f"http://{host}:{http_port}"
    socks = f"socks5://{host}:{socks_port}"
    return {
        "clash": http,
        "clash-http": http,
        "clash-mixed": http,
        "clash-socks": socks,
        "mihomo": http,
        "mihomo-socks": socks,
    }


_PROXY_ALIASES = _build_proxy_aliases()

# Clash / mihomo 的 fake-ip 模式会给每个查询到的域名分配一个占位地址，本机 DNS
# 返回的就是这个占位地址，真实解析发生在代理侧。这些段在 ipaddress 里被判为
# private，会让「解析后校验是否公网」的 SSRF 防护把所有域名都误杀。
# 默认取 Clash 出厂 fake-ip 段，可用 config.PROXY_ALIAS_CONFIG["fake_ip_ranges"] 覆盖。
_DEFAULT_FAKE_IP_RANGES = ("198.18.0.0/15", "fdfe:dcba:9876::/64")


def _build_fake_ip_networks() -> tuple:
    """构建 fake-ip 占位段列表；config 不可用或配置非法时回退默认值。"""
    raw = _DEFAULT_FAKE_IP_RANGES
    try:
        from config import PROXY_ALIAS_CONFIG  # type: ignore

        configured = PROXY_ALIAS_CONFIG.get("fake_ip_ranges")
        if configured:
            raw = tuple(configured)
    except Exception:
        pass

    networks = []
    for item in raw:
        try:
            networks.append(ipaddress.ip_network(str(item).strip(), strict=False))
        except ValueError:
            _log.warning("忽略无法解析的 fake-ip 段: %s", item)
    return tuple(networks)


_FAKE_IP_NETWORKS = _build_fake_ip_networks()


def is_fake_ip(ip) -> bool:
    """判断地址是否落在代理的 fake-ip 占位段内。

    占位地址只是 DNS 层的临时映射，不代表真实目标，因此不能据此判断内外网。
    接受 ``ipaddress`` 对象或可解析为地址的字符串；无法解析时返回 False。
    """
    if isinstance(ip, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
        addr = ip
    else:
        try:
            addr = ipaddress.ip_address(str(ip))
        except ValueError:
            return False
    return any(addr in network for network in _FAKE_IP_NETWORKS)


_DEFAULT_PORTS = {
    "http": 80,
    "https": 443,
    "socks4": 1080,
    "socks4a": 1080,
    "socks5": 1080,
    "socks5h": 1080,
}
_SUPPORTED_SCHEMES = set(_DEFAULT_PORTS)
_PROXY_ENV_KEYS = (
    "ALL_PROXY",
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "all_proxy",
    "https_proxy",
    "http_proxy",
)
_NO_PROXY_DEFAULTS = "localhost,127.0.0.1,::1,redis,netease-api"


@dataclass(frozen=True)
class ProxySettings:
    mode: str
    raw: str = ""
    server: str | None = None
    scheme: str | None = None
    host: str | None = None
    port: int | None = None
    username: str | None = None
    password: str | None = None

    @property
    def enabled(self) -> bool:
        return self.mode == "explicit" and bool(self.server)


def _config_proxy_value():
    try:
        from config import OOPZ_CONFIG
    except Exception:
        return ""
    return OOPZ_CONFIG.get("proxy", "")


def _normalize_proxy_value(proxy_value=None):
    value = _config_proxy_value() if proxy_value is None else proxy_value
    if value is False:
        return False
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    value = value.strip()
    if not value:
        return ""
    alias = _PROXY_ALIASES.get(value.lower())
    return alias or value


def _parse_proxy_url(proxy_url: str) -> ProxySettings:
    candidate = proxy_url.strip()
    if "://" not in candidate:
        candidate = f"http://{candidate}"

    parsed = urlparse(candidate)
    scheme = (parsed.scheme or "http").lower()
    if scheme not in _SUPPORTED_SCHEMES:
        raise ValueError(f"unsupported proxy scheme: {scheme}")
    if not parsed.hostname:
        raise ValueError("proxy host is required")

    port = parsed.port or _DEFAULT_PORTS[scheme]
    username = unquote(parsed.username) if parsed.username else None
    password = unquote(parsed.password) if parsed.password else None
    server = f"{scheme}://{parsed.hostname}:{port}"
    if username:
        auth = username
        if password is not None:
            auth = f"{auth}:{password}"
        server = f"{scheme}://{auth}@{parsed.hostname}:{port}"

    return ProxySettings(
        mode="explicit",
        raw=proxy_url,
        server=server,
        scheme=scheme,
        host=parsed.hostname,
        port=port,
        username=username,
        password=password,
    )


def resolve_proxy_settings(proxy_value=None) -> ProxySettings:
    value = _normalize_proxy_value(proxy_value)
    if value is False:
        return ProxySettings(mode="direct", raw="direct")
    if not value:
        return ProxySettings(mode="system")
    if value.lower() in _DIRECT_VALUES:
        return ProxySettings(mode="direct", raw=value)
    return _parse_proxy_url(value)


def resolve_proxy_settings_with_env(proxy_value=None) -> ProxySettings:
    settings = resolve_proxy_settings(proxy_value)
    if settings.mode != "system":
        return settings
    for key in _PROXY_ENV_KEYS:
        value = os.environ.get(key, "").strip()
        if value:
            return resolve_proxy_settings(value)
    return settings


def get_playwright_proxy(proxy_value=None) -> dict | None:
    settings = resolve_proxy_settings_with_env(proxy_value)
    if not settings.enabled:
        return None

    proxy = {"server": f"{settings.scheme}://{settings.host}:{settings.port}"}
    if settings.username:
        proxy["username"] = settings.username
        proxy["password"] = settings.password or ""
    return proxy


def get_selenium_proxy_argument(proxy_value=None) -> str | None:
    settings = resolve_proxy_settings_with_env(proxy_value)
    if not settings.enabled:
        return None
    return f"--proxy-server={settings.server}"


def configure_requests_session(session, proxy_value=None) -> ProxySettings:
    settings = resolve_proxy_settings(proxy_value)
    session.proxies.clear()
    if settings.mode == "direct":
        session.trust_env = False
    elif settings.enabled:
        session.trust_env = False
        session.proxies.update({"http": settings.server, "https": settings.server})
        no_proxy = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
        parts = {s.strip() for s in no_proxy.split(",") if s.strip()}
        for item in _NO_PROXY_DEFAULTS.split(","):
            parts.add(item.strip())
        session.proxies["no_proxy"] = ",".join(sorted(parts))
    else:
        session.trust_env = True
    return settings
