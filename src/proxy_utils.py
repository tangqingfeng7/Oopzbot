"""
Shared proxy helpers for requests, websocket-client, Playwright, and Selenium.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional
from urllib.parse import unquote, urlparse

_log = logging.getLogger("ProxyUtils")

_DIRECT_VALUES = {"0", "false", "no", "none", "off", "direct"}
_PROXY_ALIASES = {
    "clash": "http://127.0.0.1:7890",
    "clash-http": "http://127.0.0.1:7890",
    "clash-mixed": "http://127.0.0.1:7890",
    "clash-socks": "socks5://127.0.0.1:7891",
    "mihomo": "http://127.0.0.1:7890",
    "mihomo-socks": "socks5://127.0.0.1:7891",
}
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
    server: Optional[str] = None
    scheme: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    password: Optional[str] = None

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


def get_websocket_proxy_kwargs(proxy_value=None) -> dict:
    settings = resolve_proxy_settings_with_env(proxy_value)
    if not settings.enabled:
        return {}

    proxy_type = "http" if settings.scheme in {"http", "https"} else settings.scheme
    kwargs = {
        "http_proxy_host": settings.host,
        "http_proxy_port": settings.port,
        "proxy_type": proxy_type,
        "http_proxy_timeout": 10,
    }
    if settings.username:
        kwargs["http_proxy_auth"] = (settings.username, settings.password or "")
    return kwargs


def get_playwright_proxy(proxy_value=None) -> Optional[dict]:
    settings = resolve_proxy_settings_with_env(proxy_value)
    if not settings.enabled:
        return None

    proxy = {"server": f"{settings.scheme}://{settings.host}:{settings.port}"}
    if settings.username:
        proxy["username"] = settings.username
        proxy["password"] = settings.password or ""
    return proxy


def get_selenium_proxy_argument(proxy_value=None) -> Optional[str]:
    settings = resolve_proxy_settings_with_env(proxy_value)
    if not settings.enabled:
        return None
    return f"--proxy-server={settings.server}"


def apply_process_proxy_env(env: dict, proxy_value=None) -> dict:
    settings = resolve_proxy_settings(proxy_value)
    updated = dict(env)
    if settings.mode == "direct":
        for key in _PROXY_ENV_KEYS:
            updated.pop(key, None)
    elif settings.enabled:
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
            updated[key] = settings.server
        for key in ("http_proxy", "https_proxy", "all_proxy"):
            updated[key] = settings.server
        _ensure_no_proxy(updated)
    return updated


def _ensure_no_proxy(env: dict) -> None:
    """Populate NO_PROXY / no_proxy so internal services bypass the proxy."""
    existing = env.get("NO_PROXY") or env.get("no_proxy") or ""
    parts = {s.strip() for s in existing.split(",") if s.strip()}
    for item in _NO_PROXY_DEFAULTS.split(","):
        parts.add(item.strip())
    merged = ",".join(sorted(parts))
    env["NO_PROXY"] = merged
    env["no_proxy"] = merged


# ---------------------------------------------------------------------------
# Plugin helper: resolve a plugin-level proxy config value to a requests
# proxies dict, with full support for aliases ("clash"), "direct", socks, etc.
# ---------------------------------------------------------------------------

def resolve_requests_proxies(proxy_value: str | None) -> dict[str, str] | None:
    """Resolve a raw proxy config string into a ``requests``-compatible proxies
    dict.  Returns ``None`` when the caller should use default behaviour
    (system env / no proxy), or an empty dict for explicit direct connection.

    Supports the same aliases and schemes as the core proxy system (e.g.
    ``"clash"``, ``"direct"``, ``"socks5://host:port"``).
    """
    if not proxy_value or not isinstance(proxy_value, str) or not proxy_value.strip():
        return None

    value = proxy_value.strip()
    if value.lower() in _DIRECT_VALUES:
        return {}

    normalized = _PROXY_ALIASES.get(value.lower(), value)
    try:
        settings = _parse_proxy_url(normalized)
    except ValueError:
        _log.warning("Invalid plugin proxy value %r, ignoring", proxy_value)
        return None
    return {"http": settings.server, "https": settings.server}


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


def log_proxy_summary(label: str, proxy_value=None) -> ProxySettings:
    """Resolve and log proxy settings once at startup for a named component."""
    settings = resolve_proxy_settings_with_env(proxy_value)
    if settings.mode == "direct":
        _log.info("[%s] proxy: direct (disabled)", label)
    elif settings.enabled:
        display = settings.server or ""
        if settings.username:
            display = f"{settings.scheme}://***@{settings.host}:{settings.port}"
        _log.info("[%s] proxy: %s", label, display)
    else:
        _log.debug("[%s] proxy: system (env / none)", label)
    return settings
