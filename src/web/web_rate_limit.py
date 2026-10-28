"""Web 层限流与登录失败锁定。

单进程内存实现：整个进程只跑一个 uvicorn worker，所有计数都在本进程内。
多实例部署时各实例各算各的，需要在反代层另行兜底。

分桶用的客户端 IP 判定也收口在这里。只有 TCP 对端属于明确配置的可信代理
网段时才读取转发头，并从 ``X-Forwarded-For`` 右侧逐个剥离可信代理；
任一地址畸形就回退到真实 TCP 对端，避免攻击者伪造来源绕过限流。
"""

from __future__ import annotations

import ipaddress
import time
from collections import OrderedDict
from collections.abc import Mapping
from functools import lru_cache
from threading import Lock
from typing import Protocol


class ClientPeer(Protocol):
    @property
    def host(self) -> str: ...


class ClientAddressRequest(Protocol):
    """客户端地址解析器依赖的最小请求接口。"""

    @property
    def headers(self) -> Mapping[str, str]: ...

    @property
    def client(self) -> ClientPeer | None: ...


class RateLimiter:
    """基于滑动窗口的简易内存速率限制器。"""

    _MAX_TRACKED_IPS = 2000

    def __init__(self, max_requests: int = 60, window_seconds: int = 60):
        self._max = max(1, int(max_requests))
        self._window = max(1, int(window_seconds))
        self._hits: OrderedDict[str, list[float]] = OrderedDict()
        self._lock = Lock()
        self._last_cleanup = 0.0

    def is_allowed(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self._window
        with self._lock:
            bucket = self._hits.get(key)
            if bucket is None:
                bucket = []
                if len(self._hits) >= self._MAX_TRACKED_IPS:
                    self._hits.popitem(last=False)
                self._hits[key] = bucket
            else:
                self._hits.move_to_end(key)
            bucket[:] = [t for t in bucket if t > cutoff]
            if len(bucket) >= self._max:
                return False
            bucket.append(now)
            if now - self._last_cleanup > self._window:
                self._evict_stale(cutoff)
                self._last_cleanup = now
        return True

    def _evict_stale(self, cutoff: float) -> None:
        stale = [k for k, v in self._hits.items() if not v or v[-1] <= cutoff]
        for k in stale:
            del self._hits[k]

    def reset(self) -> None:
        """清空所有桶。仅供测试使用 —— 限流器是模块级单例，用例间会互相污染。"""
        with self._lock:
            self._hits.clear()
            self._last_cleanup = 0.0


class LoginGuard:
    """后台登录失败锁定：同一 IP 连续失败若干次后，锁定一段固定时长。

    只做 per-IP 固定时长锁定，不做指数退避、不做全站兜底 —— 全站兜底会给出一个
    「打满阈值让管理员登不进」的廉价 DoS 面，收益不抵风险。
    """

    _MAX_TRACKED_IPS = 2000

    def __init__(self) -> None:
        # OrderedDict 按最后一次失败排序，既能让计数按窗口过期，也能 O(1)
        # 淘汰最老来源，避免攻击者用大量不同 IP 把字典无限撑大。
        self._failures: OrderedDict[str, tuple[int, float]] = OrderedDict()
        self._locked_until: OrderedDict[str, float] = OrderedDict()
        self._lock = Lock()

    def locked_seconds(self, key: str, lock_seconds: int) -> int:
        """还需等待多少秒；未锁定返回 0。``lock_seconds`` 为 0 表示关闭锁定。"""
        if lock_seconds <= 0:
            return 0
        with self._lock:
            until = self._locked_until.get(key, 0.0)
            remaining = until - time.monotonic()
            if remaining <= 0:
                self._locked_until.pop(key, None)
                return 0
            return int(remaining) + 1

    def record_failure(self, key: str, max_failures: int, lock_seconds: int) -> bool:
        """记一次失败；返回本次是否触发锁定。"""
        if max_failures <= 0 or lock_seconds <= 0:
            return False
        now = time.monotonic()
        with self._lock:
            self._evict_stale(now, failure_window=lock_seconds)
            count, last_failure = self._failures.get(key, (0, 0.0))
            if last_failure <= now - lock_seconds:
                count = 0
            count += 1
            self._failures[key] = (count, now)
            self._failures.move_to_end(key)

            while len(self._failures) > self._MAX_TRACKED_IPS:
                self._failures.popitem(last=False)

            if count < max_failures:
                return False
            self._failures.pop(key, None)
            self._locked_until[key] = now + lock_seconds
            self._locked_until.move_to_end(key)
            while len(self._locked_until) > self._MAX_TRACKED_IPS:
                self._locked_until.popitem(last=False)
            return True

    def record_success(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)
            self._locked_until.pop(key, None)

    def _evict_stale(self, now: float, failure_window: int) -> None:
        cutoff = now - failure_window
        while self._failures:
            oldest_key = next(iter(self._failures))
            _count, last_failure = self._failures[oldest_key]
            if last_failure > cutoff:
                break
            self._failures.popitem(last=False)
        for k, until in list(self._locked_until.items()):
            if until <= now:
                del self._locked_until[k]

    def reset(self) -> None:
        """清空计数。仅供测试使用。"""
        with self._lock:
            self._failures.clear()
            self._locked_until.clear()


class ClientAddressResolver:
    """只接受来自明确可信代理对端的转发地址。"""

    _MAX_FORWARDED_HOPS = 32

    def __init__(self, trusted_proxy_cidrs: tuple[str, ...] = ()) -> None:
        networks = []
        for raw in trusted_proxy_cidrs:
            try:
                networks.append(ipaddress.ip_network(str(raw).strip(), strict=False))
            except ValueError as exc:
                raise ValueError(f"无效的可信代理网段: {raw}") from exc
        self._trusted_networks = tuple(networks)

    @staticmethod
    def _parse_address(raw: object):
        text = str(raw or "").strip()
        if not text:
            return None
        if text.startswith("[") and "]" in text:
            text = text[1 : text.index("]")]
        if "%" in text:
            text = text.split("%", 1)[0]
        try:
            return ipaddress.ip_address(text)
        except ValueError:
            return None

    def is_trusted(self, address) -> bool:
        parsed = address if isinstance(
            address,
            (ipaddress.IPv4Address, ipaddress.IPv6Address),
        ) else self._parse_address(address)
        return bool(
            parsed is not None
            and any(parsed.version == network.version and parsed in network for network in self._trusted_networks)
        )

    def resolve(self, request: ClientAddressRequest) -> str:
        client = request.client
        peer_raw = client.host if client else ""
        peer = self._parse_address(peer_raw)
        peer_text = str(peer) if peer is not None else (str(peer_raw).strip() or "unknown")
        if peer is None or not self.is_trusted(peer):
            return peer_text

        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            parts = forwarded.split(",")
            if any(not part.strip() for part in parts):
                return peer_text
            raw_hops = [part.strip() for part in parts]
            if len(raw_hops) > self._MAX_FORWARDED_HOPS:
                return peer_text
            hops = [self._parse_address(part) for part in raw_hops]
            if any(hop is None for hop in hops):
                return peer_text
            chain = [*hops, peer]
            while chain and self.is_trusted(chain[-1]):
                chain.pop()
            return str(chain[-1]) if chain else peer_text

        real_ip = self._parse_address(request.headers.get("x-real-ip", ""))
        return str(real_ip) if real_ip is not None else peer_text


@lru_cache(maxsize=64)
def _resolver_for(trusted_proxy_cidrs: tuple[str, ...]) -> ClientAddressResolver:
    return ClientAddressResolver(trusted_proxy_cidrs)


def client_ip(request: ClientAddressRequest, trusted_proxy_cidrs=()) -> str:
    """返回限流和登录锁定共用的规范化客户端地址。"""
    cidrs = tuple(str(item).strip() for item in (trusted_proxy_cidrs or ()) if str(item).strip())
    return _resolver_for(cidrs).resolve(request)


# 路径 → 限流器。未命中的走 DEFAULT_LIMITER。
SEARCH_LIMITER = RateLimiter(max_requests=15, window_seconds=60)
LOGIN_LIMITER = RateLimiter(max_requests=10, window_seconds=60)
DEFAULT_LIMITER = RateLimiter(max_requests=200, window_seconds=60)
SCREEN_SHARE_HEARTBEAT_LIMITER = RateLimiter(max_requests=30, window_seconds=60)
SCREEN_SHARE_HEARTBEAT_IP_LIMITER = RateLimiter(max_requests=1200, window_seconds=60)

PATH_LIMITERS: dict[str, RateLimiter] = {
    "/api/search": SEARCH_LIMITER,
    "/admin/api/login": LOGIN_LIMITER,
    "/screen-share/api/presenter/heartbeat": SCREEN_SHARE_HEARTBEAT_LIMITER,
}

login_guard = LoginGuard()


def limiter_for(path: str) -> RateLimiter:
    return PATH_LIMITERS.get(path, DEFAULT_LIMITER)


def reset_all() -> None:
    """重置全部限流状态。仅供测试使用。"""
    for limiter in {
        *PATH_LIMITERS.values(),
        DEFAULT_LIMITER,
        SCREEN_SHARE_HEARTBEAT_IP_LIMITER,
    }:
        limiter.reset()
    login_guard.reset()


__all__ = [
    "DEFAULT_LIMITER",
    "LOGIN_LIMITER",
    "PATH_LIMITERS",
    "SCREEN_SHARE_HEARTBEAT_IP_LIMITER",
    "SCREEN_SHARE_HEARTBEAT_LIMITER",
    "SEARCH_LIMITER",
    "ClientAddressRequest",
    "ClientAddressResolver",
    "ClientPeer",
    "LoginGuard",
    "RateLimiter",
    "client_ip",
    "limiter_for",
    "login_guard",
    "reset_all",
]
