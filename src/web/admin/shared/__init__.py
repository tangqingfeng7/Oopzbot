"""管理后台共享依赖和辅助函数。

历史上这些工具集中在单个 ``web/admin/shared.py``（1100+ 行）；现按主题拆分为
子模块（运行时访问器 / OOPZ 热更新 / 域上下文 / 调试工具 / 网易云 / B 站 /
页面渲染 / 会话令牌 / 概览快照），这里把它们重新聚合到包命名空间，并保留被各
路由模块依赖的领域聚合符号（如 ``cfg``、``Statistics``、``RequestsException``
等）。标准库 / ``typing`` / ``fastapi`` 等通用依赖不再经此转发，由各消费方直接导入。
"""
# pyright: reportMissingModuleSource=false

from __future__ import annotations

import web.web_player_config as cfg
from app.services.interaction.setup_diagnostics import SetupDiagnostics
from core.database import (
    DB_PATH,
    MessageStatsDB,
    ReminderDB,
    ScheduledMessageDB,
    SongCache,
    Statistics,
    db_connection,
)
from core.http_constants import HTTP_TIMEOUT_DEFAULT
from core.logger_config import get_logger
from core.queue_manager import (
    KEY_CURRENT,
    KEY_PLAY_STATE,
    KEY_QUEUE,
    _area_key,
    get_redis_client,
)
from core.ttl_cache import TtlCache
from oopz.name_resolver import get_resolver
from services.scheduler_templates import get_scheduled_template, list_scheduled_templates
from web.web_link_token import (
    clear_token,
    ensure_token,
    get_active_area,
    get_token,
    set_token,
)

from ._area import (
    _MEMBERS_RESP_TTL,
    _get_music_area,
    _invalidate_members_cache,
    _members_resp_cache,
    _music_area_context,
    _playback_area_unavailable_payload,
    _require_music_area,
    _resolve_area,
    _resolve_area_async,
    _resolved_area_cache,
)
from ._bilibili import (
    _BILIBILI_API_BASE,
    _BILIBILI_COOKIE_NAMES,
    _BILIBILI_LOGIN_BASE,
    _BILIBILI_NAV_PATH,
    _BILIBILI_QR_GENERATE_PATH,
    _BILIBILI_QR_POLL_PATH,
    _bilibili_account_api_get,
    _bilibili_account_status,
    _bilibili_api_get,
    _bilibili_cookie_from_poll,
    _bilibili_login_message,
    _bilibili_qr_code,
    _bilibili_response_data,
    _extract_bilibili_profile,
    _make_qr_data_uri,
)
from ._debug import (
    _cookie_debug_summary,
    _cookie_pairs_from_header,
    _cookie_pairs_from_response,
    _debug_profile_text,
    _mask_debug_token,
)
from ._netease import (
    _cookie_from_response,
    _netease_account_status,
    _netease_api_get,
    _netease_api_post,
    _netease_login_message,
    _netease_qr_code,
    _netease_response_data,
    _netease_timestamp_params,
    _normalize_netease_base_url,
)
from ._oopz import (
    _OOPZ_RUNTIME_FIELDS,
    _apply_oopz_config_updates,
    _oopz_login_lock,
    _oopz_runtime_updates,
    _refresh_oopz_runtime,
)
from ._pages import (
    _ADMIN_PAGES,
    _ADMIN_SHELL_TEMPLATE,
    _load_admin_template,
    _render_admin_page,
    _render_topbar_actions,
)
from ._requests import read_json_body
from ._runtime import (
    _add_song_to_queue,
    _admin_enabled,
    _execute_control_action,
    _execute_queue_action,
    _get_liked_ids_cache,
    _get_netease,
    _get_oopz_client,
    _get_plugin_runtime,
    _get_redis,
    _get_sender,
    _get_started_at,
    _require_sender,
    _set_liked_ids_cache,
    require_sender,
)
from ._session import _clear_admin_session_token, _set_admin_session_token
from ._snapshots import (
    _current_song_snapshot,
    _overview_payload,
    _queue_snapshot,
    _tail_file,
    _top_songs_from_play_history,
)

try:
    import requests

    RequestsException = requests.RequestException
except Exception:
    requests = None  # type: ignore[assignment]
    RequestsException = RuntimeError

try:
    import qrcode  # type: ignore[reportMissingModuleSource]
except Exception:
    qrcode = None  # type: ignore[assignment]

logger = get_logger("WebPlayerAdmin")

# 共享包的公共面保持显式，新增依赖时由评审决定是否对路由层公开。
__all__ = [
    "DB_PATH",
    "HTTP_TIMEOUT_DEFAULT",
    "KEY_CURRENT",
    "KEY_PLAY_STATE",
    "KEY_QUEUE",
    "_ADMIN_PAGES",
    "_ADMIN_SHELL_TEMPLATE",
    "_BILIBILI_API_BASE",
    "_BILIBILI_COOKIE_NAMES",
    "_BILIBILI_LOGIN_BASE",
    "_BILIBILI_NAV_PATH",
    "_BILIBILI_QR_GENERATE_PATH",
    "_BILIBILI_QR_POLL_PATH",
    "_MEMBERS_RESP_TTL",
    "_OOPZ_RUNTIME_FIELDS",
    "MessageStatsDB",
    "ReminderDB",
    "RequestsException",
    "ScheduledMessageDB",
    "SetupDiagnostics",
    "SongCache",
    "Statistics",
    "TtlCache",
    "_add_song_to_queue",
    "_admin_enabled",
    "_apply_oopz_config_updates",
    "_area_key",
    "_bilibili_account_api_get",
    "_bilibili_account_status",
    "_bilibili_api_get",
    "_bilibili_cookie_from_poll",
    "_bilibili_login_message",
    "_bilibili_qr_code",
    "_bilibili_response_data",
    "_clear_admin_session_token",
    "_cookie_debug_summary",
    "_cookie_from_response",
    "_cookie_pairs_from_header",
    "_cookie_pairs_from_response",
    "_current_song_snapshot",
    "_debug_profile_text",
    "_execute_control_action",
    "_execute_queue_action",
    "_extract_bilibili_profile",
    "_get_liked_ids_cache",
    "_get_music_area",
    "_get_netease",
    "_get_oopz_client",
    "_get_plugin_runtime",
    "_get_redis",
    "_get_sender",
    "_get_started_at",
    "_invalidate_members_cache",
    "_load_admin_template",
    "_make_qr_data_uri",
    "_mask_debug_token",
    "_members_resp_cache",
    "_music_area_context",
    "_netease_account_status",
    "_netease_api_get",
    "_netease_api_post",
    "_netease_login_message",
    "_netease_qr_code",
    "_netease_response_data",
    "_netease_timestamp_params",
    "_normalize_netease_base_url",
    "_oopz_login_lock",
    "_oopz_runtime_updates",
    "_overview_payload",
    "_playback_area_unavailable_payload",
    "_queue_snapshot",
    "_refresh_oopz_runtime",
    "_render_admin_page",
    "_render_topbar_actions",
    "_require_music_area",
    "_require_sender",
    "_resolve_area",
    "_resolve_area_async",
    "_resolved_area_cache",
    "_set_admin_session_token",
    "_set_liked_ids_cache",
    "_tail_file",
    "_top_songs_from_play_history",
    "cfg",
    "clear_token",
    "db_connection",
    "ensure_token",
    "get_active_area",
    "get_logger",
    "get_redis_client",
    "get_resolver",
    "get_scheduled_template",
    "get_token",
    "list_scheduled_templates",
    "logger",
    "qrcode",
    "read_json_body",
    "requests",
    "require_sender",
    "set_token",
]
