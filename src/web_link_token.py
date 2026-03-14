"""
Web 播放器访问令牌管理

优先读写 Redis；当 Redis 不可用时回退到进程内存，确保同进程线程间一致。
"""

import secrets
import threading

from logger_config import get_logger

logger = get_logger("WebLinkToken")

KEY_WEB_ACCESS_TOKEN = "music:web_access_token"

_lock = threading.Lock()
_memory_token: str = ""


def _normalize_ttl(ttl_seconds=None) -> int:
    """标准化 TTL 秒数。<=0 表示不设置过期。"""
    try:
        ttl = int(ttl_seconds or 0)
    except (TypeError, ValueError):
        return 0
    return ttl if ttl > 0 else 0


def get_token(redis_client=None) -> str:
    """读取当前访问令牌。"""
    global _memory_token
    token = ""
    redis_read_ok = False
    if redis_client is not None:
        try:
            raw = redis_client.get(KEY_WEB_ACCESS_TOKEN)
            redis_read_ok = True
            if isinstance(raw, bytes):
                token = raw.decode("utf-8", errors="ignore")
            elif isinstance(raw, str):
                token = raw
        except Exception as e:
            logger.debug(f"Redis 读取 Web 令牌失败，使用内存回退: {e}")
    if token:
        with _lock:
            _memory_token = token
        return token
    if redis_client is not None and redis_read_ok:
        with _lock:
            _memory_token = ""
        return ""
    with _lock:
        return _memory_token


def set_token(token: str, redis_client=None, ttl_seconds=None):
    """设置访问令牌。"""
    global _memory_token
    with _lock:
        _memory_token = token or ""
    if redis_client is not None:
        ttl = _normalize_ttl(ttl_seconds)
        try:
            if ttl > 0:
                try:
                    redis_client.set(KEY_WEB_ACCESS_TOKEN, _memory_token, ex=ttl)
                except TypeError:
                    # 兼容少数不支持 ex 参数的客户端
                    redis_client.set(KEY_WEB_ACCESS_TOKEN, _memory_token)
                    if hasattr(redis_client, "expire"):
                        redis_client.expire(KEY_WEB_ACCESS_TOKEN, ttl)
            else:
                redis_client.set(KEY_WEB_ACCESS_TOKEN, _memory_token)
        except Exception as e:
            logger.debug(f"Redis 写入 Web 令牌失败，已仅写内存: {e}")


def ensure_token(redis_client=None, ttl_seconds=None) -> str:
    """确保存在可用令牌，不存在则生成。"""
    ttl = _normalize_ttl(ttl_seconds)
    token = get_token(redis_client=redis_client)
    if token:
        # 有效令牌存在时，按需刷新 Redis 过期时间（滑动续期）
        if redis_client is not None and ttl > 0:
            set_token(token, redis_client=redis_client, ttl_seconds=ttl)
        return token
    token = secrets.token_urlsafe(18)
    set_token(token, redis_client=redis_client, ttl_seconds=ttl)
    return token


def clear_token(redis_client=None):
    """清理访问令牌。"""
    global _memory_token
    with _lock:
        _memory_token = ""
    if redis_client is not None:
        try:
            redis_client.delete(KEY_WEB_ACCESS_TOKEN)
        except Exception as e:
            logger.debug(f"Redis 清理 Web 令牌失败: {e}")
