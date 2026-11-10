from __future__ import annotations

import ipaddress
import math
import socket
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast
from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit
from urllib.request import getproxies, proxy_bypass

import requests
import urllib3
from urllib3 import HTTPConnectionPool, HTTPSConnectionPool, ProxyManager
from urllib3.contrib.socks import SOCKSProxyManager
from urllib3.util import Timeout, make_headers

from core.http_constants import HTTP_TIMEOUT_PROBE, HttpTimeout
from core.logger_config import get_logger
from core.proxy_utils import (
    ProxySettings,
    configure_requests_session,
    is_fake_ip,
    resolve_proxy_settings,
)

logger = get_logger("SafeRemoteFetcher")

_DOWNLOAD_CHUNK = 64 * 1024
_MAX_REDIRECTS = 5
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_DEFAULT_TRUSTED_DOH_URL = "https://cloudflare-dns.com/dns-query"
_ALLOWED_CALLER_HEADERS = frozenset(
    {
        "accept",
        "accept-language",
        "referer",
        "user-agent",
    }
)

try:
    import config as app_config

    proxy_alias_config = getattr(app_config, "PROXY_ALIAS_CONFIG", {})
    if not isinstance(proxy_alias_config, Mapping):
        proxy_alias_config = {}
    _TRUSTED_DOH_URL = str(
        proxy_alias_config.get("trusted_doh_url") or _DEFAULT_TRUSTED_DOH_URL
    ).strip()
except (ImportError, AttributeError):
    _TRUSTED_DOH_URL = _DEFAULT_TRUSTED_DOH_URL


class RemoteFetchError(Exception):
    """远程抓取被安全策略拒绝或下载失败。"""


@dataclass(frozen=True)
class ResolvedTarget:
    """一次 URL 跳转所对应的、已经验证过的目标地址。"""

    scheme: str
    host: str
    port: int
    path_and_query: str
    addresses: tuple[str, ...]


class StreamingResponse(Protocol):
    @property
    def status(self) -> int: ...

    @property
    def headers(self) -> Mapping[str, str]: ...

    def stream(self, amt: int, decode_content: bool = True) -> Iterator[bytes]: ...

    def release_conn(self) -> None: ...


class RemoteTransport(Protocol):
    """可注入传输层，便于对 IP 固定、Host/SNI 和代理行为做确定性测试。"""

    def request(
        self,
        target: ResolvedTarget,
        address: str,
        *,
        headers: Mapping[str, str],
        timeout: Timeout,
        proxy: ProxySettings,
    ) -> StreamingResponse: ...


TrustedDnsResolver = Callable[[str], tuple[str, ...] | None]


# ``IPv6Address.is_global`` 并不代表地址一定可作为安全的公网目标。
# 例如 64:ff9b::/96 同时会被 Python 标记为 global 和 reserved，且可在
# NAT64 环境中嵌入回环、链路本地或内网 IPv4。本地使用的
# 64:ff9b:1::/48 同样不能作为不可信 URL 的安全出站目标。
_NON_PUBLIC_IPV6_NETWORKS = (
    ipaddress.IPv6Network("64:ff9b::/96"),
    ipaddress.IPv6Network("64:ff9b:1::/48"),
)


def _is_public_ip(value: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if (
        not value.is_global
        or value.is_private
        or value.is_loopback
        or value.is_link_local
        or value.is_multicast
        or value.is_reserved
        or value.is_unspecified
    ):
        return False
    if isinstance(value, ipaddress.IPv6Address):
        if value.is_site_local:
            return False
        if any(value in network for network in _NON_PUBLIC_IPV6_NETWORKS):
            return False
    return True


def resolve_via_trusted_dns(
    host: str,
    proxy_value=None,
) -> tuple[str, ...] | None:
    """在 fake-ip 环境中通过固定 DoH 端点获取真实 A/AAAA 地址。

    每次解析都创建不含 Oopz 鉴权、Cookie 或签名头的独立 Session，并沿用
    当前显式/system 代理配置。
    """

    endpoint = urlparse(_TRUSTED_DOH_URL)
    if endpoint.scheme != "https" or not endpoint.hostname:
        logger.error("trusted_doh_url 必须是有效 HTTPS 地址，已拒绝 fake-ip 目标")
        return None

    session = requests.Session()
    try:
        configure_requests_session(session, proxy_value)
        addresses: list[str] = []
        for record_name, record_type in (("A", 1), ("AAAA", 28)):
            response = None
            try:
                response = session.get(
                    _TRUSTED_DOH_URL,
                    params={"name": host, "type": record_name},
                    headers={"Accept": "application/dns-json"},
                    timeout=HTTP_TIMEOUT_PROBE,
                    allow_redirects=False,
                )
                if response.status_code != 200:
                    return None
                payload = response.json()
                if not isinstance(payload, dict) or payload.get("Status") != 0:
                    return None
                answers = payload.get("Answer") or []
                if not isinstance(answers, list):
                    return None
                for answer in answers:
                    if not isinstance(answer, dict) or answer.get("type") != record_type:
                        continue
                    raw = str(answer.get("data") or "").strip()
                    try:
                        addresses.append(str(ipaddress.ip_address(raw)))
                    except ValueError:
                        return None
            except (requests.RequestException, ValueError, TypeError):
                return None
            finally:
                if response is not None:
                    response.close()

        return tuple(dict.fromkeys(addresses)) or None
    finally:
        session.close()


class PublicTargetResolver:
    """把 URL 解析为一组经过 fail-closed 公网校验的地址。"""

    def __init__(self, trusted_dns: TrustedDnsResolver = resolve_via_trusted_dns):
        self._trusted_dns = trusted_dns

    def resolve_url(self, url: str) -> ResolvedTarget:
        parsed = urlsplit((url or "").strip())
        scheme = parsed.scheme.lower()
        if scheme not in {"http", "https"}:
            raise RemoteFetchError(f"不支持的 URL scheme: {scheme or '(空)'}")
        if parsed.username is not None or parsed.password is not None:
            raise RemoteFetchError("远程 URL 不允许包含用户名或密码")
        host = parsed.hostname or ""
        if not host:
            raise RemoteFetchError("URL 缺少主机名")
        try:
            port = parsed.port or (443 if scheme == "https" else 80)
        except ValueError as exc:
            raise RemoteFetchError("URL 端口无效") from exc
        if not 1 <= port <= 65535:
            raise RemoteFetchError("URL 端口超出范围")

        path = parsed.path or "/"
        path_and_query = urlunsplit(("", "", path, parsed.query, ""))
        return ResolvedTarget(
            scheme=scheme,
            host=host,
            port=port,
            path_and_query=path_and_query,
            addresses=self.resolve_host(host, port),
        )

    def resolve_host(self, host: str, port: int = 0) -> tuple[str, ...]:
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            literal = None
        if literal is not None:
            if not _is_public_ip(literal):
                raise RemoteFetchError(f"目标地址不是公网地址，已拒绝: {host}")
            return (str(literal),)

        try:
            infos = socket.getaddrinfo(
                host,
                port or None,
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as exc:
            raise RemoteFetchError(f"无法解析远程主机: {host}") from exc
        if not infos:
            raise RemoteFetchError(f"无法解析远程主机: {host}")

        real_addresses: list[str] = []
        saw_fake_ip = False
        for info in infos:
            try:
                address = ipaddress.ip_address(info[4][0])
            except (ValueError, IndexError, TypeError) as exc:
                raise RemoteFetchError(f"远程主机返回了非法地址: {host}") from exc
            if is_fake_ip(address):
                saw_fake_ip = True
                continue
            if not _is_public_ip(address):
                raise RemoteFetchError(f"目标地址不是公网地址，已拒绝: {host}")
            real_addresses.append(str(address))

        if saw_fake_ip:
            trusted = self._trusted_dns(host)
            if not trusted:
                logger.warning("%s 的 fake-ip 目标无法完成可信 DNS 校验，已拒绝", host)
                raise RemoteFetchError(f"无法安全解析 fake-ip 目标: {host}")
            verified: list[str] = []
            for raw in trusted:
                try:
                    address = ipaddress.ip_address(raw)
                except ValueError as exc:
                    raise RemoteFetchError(f"可信 DNS 返回了非法地址: {host}") from exc
                if not _is_public_ip(address):
                    raise RemoteFetchError(f"可信 DNS 返回非公网地址，已拒绝: {host}")
                verified.append(str(address))
            return tuple(dict.fromkeys(verified))

        addresses = tuple(dict.fromkeys(real_addresses))
        if not addresses:
            raise RemoteFetchError(f"远程主机没有可用公网地址: {host}")
        return addresses


def _timeout(value: HttpTimeout) -> Timeout:
    if isinstance(value, tuple):
        connect, read = value
    else:
        connect = read = float(value or 0)
    if not math.isfinite(float(connect)) or not math.isfinite(float(read)):
        raise RemoteFetchError("下载超时配置无效")
    if float(connect) <= 0 or float(read) <= 0:
        raise RemoteFetchError("下载超时必须大于 0")
    return Timeout(connect=float(connect), read=float(read))


def _format_ip_for_url(address: str) -> str:
    return f"[{address}]" if ":" in address else address


def _host_header(target: ResolvedTarget) -> str:
    default_port = 443 if target.scheme == "https" else 80
    host = f"[{target.host}]" if ":" in target.host else target.host
    return host if target.port == default_port else f"{host}:{target.port}"


class Urllib3PinnedTransport:
    """urllib3 传输实现；每次请求只连接调用方给出的已验证 IP。"""

    def request(
        self,
        target: ResolvedTarget,
        address: str,
        *,
        headers: Mapping[str, str],
        timeout: Timeout,
        proxy: ProxySettings,
    ) -> StreamingResponse:
        if proxy.enabled:
            manager = self._proxy_manager(proxy, target)
            pinned_url = (
                f"{target.scheme}://{_format_ip_for_url(address)}:{target.port}"
                f"{target.path_and_query}"
            )
            return cast(
                StreamingResponse,
                manager.request(
                    "GET",
                    pinned_url,
                    headers=headers,
                    timeout=timeout,
                    preload_content=False,
                    redirect=False,
                    retries=False,
                ),
            )

        if target.scheme == "https":
            pool = HTTPSConnectionPool(
                address,
                port=target.port,
                assert_hostname=target.host,
                server_hostname=target.host,
                cert_reqs="CERT_REQUIRED",
            )
        else:
            pool = HTTPConnectionPool(address, port=target.port)
        return cast(
            StreamingResponse,
            pool.request(
                "GET",
                target.path_and_query,
                headers=headers,
                timeout=timeout,
                preload_content=False,
                redirect=False,
                retries=False,
            ),
        )

    @staticmethod
    def _proxy_manager(proxy: ProxySettings, target: ResolvedTarget) -> Any:
        if not proxy.server or not proxy.scheme:
            raise RemoteFetchError("代理配置缺少地址或协议")
        endpoint = proxy.server
        destination_tls: dict[str, Any] = {}
        if target.scheme == "https":
            destination_tls = {
                "assert_hostname": target.host,
                "server_hostname": target.host,
                "cert_reqs": "CERT_REQUIRED",
            }
        if proxy.scheme in {"socks4", "socks4a", "socks5", "socks5h"}:
            socks_manager = cast(Any, SOCKSProxyManager)
            return socks_manager(
                endpoint,
                username=proxy.username,
                password=proxy.password,
                **destination_tls,
            )
        proxy_headers = None
        if proxy.username:
            proxy_headers = make_headers(
                proxy_basic_auth=f"{proxy.username}:{proxy.password or ''}"
            )
        proxy_manager = cast(Any, ProxyManager)
        return proxy_manager(
            endpoint,
            proxy_headers=proxy_headers,
            **destination_tls,
        )


class SafeRemoteFetcher:
    """下载有限大小的远程内容，并在每次重定向上固定公网目标 IP。"""

    def __init__(
        self,
        *,
        resolver: PublicTargetResolver | None = None,
        transport: RemoteTransport | None = None,
        proxy_value=None,
    ) -> None:
        self._resolver = resolver or PublicTargetResolver(
            trusted_dns=lambda host: resolve_via_trusted_dns(
                host,
                proxy_value=proxy_value,
            )
        )
        self._transport = transport or Urllib3PinnedTransport()
        self._proxy = resolve_proxy_settings(proxy_value)

    def fetch(
        self,
        url: str,
        *,
        max_bytes: int,
        timeout: HttpTimeout,
        headers: Mapping[str, str] | None = None,
    ) -> tuple[bytes, str]:
        if max_bytes <= 0:
            raise RemoteFetchError("下载大小上限必须大于 0")
        safe_headers = self._safe_headers(headers)
        current_url = url

        for redirect_count in range(_MAX_REDIRECTS + 1):
            target = self._resolver.resolve_url(current_url)
            request_headers = {**safe_headers, "Host": _host_header(target)}
            response = self._request_any_address(
                target,
                headers=request_headers,
                timeout=_timeout(timeout),
            )
            try:
                status = int(getattr(response, "status", 0) or 0)
                if status in _REDIRECT_STATUSES:
                    location = str(response.headers.get("Location") or "").strip()
                    if not location:
                        raise RemoteFetchError("远程响应重定向但未提供 Location")
                    if redirect_count >= _MAX_REDIRECTS:
                        raise RemoteFetchError(f"远程下载重定向次数超过上限 {_MAX_REDIRECTS}")
                    current_url = urljoin(current_url, location)
                    continue
                if status < 200 or status >= 300:
                    raise RemoteFetchError(f"远程服务器返回 HTTP {status}")
                declared = response.headers.get("Content-Length")
                if declared is not None:
                    try:
                        if int(declared) > max_bytes:
                            raise RemoteFetchError(
                                f"远程文件过大: 声明 {declared} 字节 > 上限 {max_bytes}"
                            )
                    except ValueError:
                        pass

                chunks: list[bytes] = []
                total = 0
                for chunk in response.stream(_DOWNLOAD_CHUNK, decode_content=True):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > max_bytes:
                        raise RemoteFetchError(f"远程文件超过大小上限 {max_bytes} 字节")
                    chunks.append(bytes(chunk))
                return b"".join(chunks), str(response.headers.get("Content-Type") or "")
            finally:
                response.release_conn()

        raise RemoteFetchError(f"远程下载重定向次数超过上限 {_MAX_REDIRECTS}")

    def _request_any_address(
        self,
        target: ResolvedTarget,
        *,
        headers: Mapping[str, str],
        timeout: Timeout,
    ) -> StreamingResponse:
        errors: list[str] = []
        for address in target.addresses:
            try:
                return self._transport.request(
                    target,
                    address,
                    headers=headers,
                    timeout=timeout,
                    proxy=self._proxy_for(target),
                )
            except (urllib3.exceptions.HTTPError, OSError) as exc:
                errors.append(type(exc).__name__)
        detail = ", ".join(errors) or "没有可用地址"
        raise RemoteFetchError(f"连接远程目标失败: {target.host} ({detail})")

    def _proxy_for(self, target: ResolvedTarget) -> ProxySettings:
        """按目标协议和 NO_PROXY 解析 system 模式，显式代理保持原样。"""
        if self._proxy.mode != "system":
            return self._proxy
        if proxy_bypass(target.host):
            return ProxySettings(mode="direct", raw="no_proxy")
        proxies = getproxies()
        raw = str(proxies.get(target.scheme) or proxies.get("all") or "").strip()
        return (
            resolve_proxy_settings(raw)
            if raw
            else ProxySettings(mode="direct", raw="system:none")
        )

    @staticmethod
    def _safe_headers(headers: Mapping[str, str] | None) -> dict[str, str]:
        result = {
            "Accept": "*/*",
            "User-Agent": "OopzBot-RemoteFetcher/1",
        }
        for name, value in (headers or {}).items():
            if name.lower() in _ALLOWED_CALLER_HEADERS:
                result[name] = str(value)
        return result


__all__ = [
    "PublicTargetResolver",
    "RemoteFetchError",
    "RemoteTransport",
    "ResolvedTarget",
    "SafeRemoteFetcher",
    "Urllib3PinnedTransport",
    "resolve_via_trusted_dns",
]
