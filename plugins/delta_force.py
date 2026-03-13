"""
Delta Force MVP plugin for Oopz Bot.
"""

from __future__ import annotations

import re
from typing import Optional

from logger_config import get_logger
from plugin_base import (
    BotModule,
    PluginCommandCapabilities,
    PluginConfigField,
    PluginConfigSpec,
    PluginMetadata,
    parse_float,
    parse_int,
    parse_string_list,
    validate_hhmm,
    validate_http_url_list,
    validate_min,
    validate_range,
)

from ._delta_force_api import DeltaForceApiClient, describe_common_failure
from ._delta_force_assets import normalize_mode
from ._delta_force_formatters import (
    ban_history_fallback_text,
    build_daily_context,
    build_ban_history_context,
    build_collection_context,
    build_help_text,
    build_info_context,
    build_money_context,
    build_place_status_context,
    build_record_context,
    build_red_collection_context,
    build_red_record_context,
    build_uid_text,
    build_weekly_context,
    collection_fallback_text,
    daily_fallback_text,
    format_daily_keyword_text,
    format_accounts,
    format_object_search_text,
    format_price_history_text,
    format_solution_detail_text,
    format_solution_list_text,
    info_fallback_text,
    money_fallback_text,
    place_status_fallback_text,
    record_fallback_text,
    red_collection_fallback_text,
    red_record_fallback_text,
    today_yyyymmdd,
    weekly_fallback_text,
)
from ._delta_force_daily_push import DeltaForceDailyKeywordPushManager
from ._delta_force_login import DeltaForceLoginManager
from ._delta_force_place_push import DeltaForcePlacePushManager
from ._delta_force_render import DeltaForceRenderer
from ._delta_force_store import DeltaForceStore

logger = get_logger("DeltaForcePlugin")


class DeltaForcePlugin(BotModule):
    def __init__(self) -> None:
        self._config: dict = {}
        self._api: Optional[DeltaForceApiClient] = None
        self._store = DeltaForceStore()
        self._renderer: Optional[DeltaForceRenderer] = None
        self._login: Optional[DeltaForceLoginManager] = None
        self._daily_push: Optional[DeltaForceDailyKeywordPushManager] = None
        self._push: Optional[DeltaForcePlacePushManager] = None
        self._handler = None

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="delta_force",
            description="三角洲行动账号与战绩查询",
            version="0.1.0",
            author="OpenAI",
        )

    @property
    def command_capabilities(self) -> PluginCommandCapabilities:
        return PluginCommandCapabilities(
            mention_prefixes=("三角洲",),
            slash_commands=("/df",),
            is_public_command=True,
        )

    @property
    def private_modules(self) -> tuple[str, ...]:
        return (
            "plugins._delta_force_api",
            "plugins._delta_force_assets",
            "plugins._delta_force_daily_push",
            "plugins._delta_force_formatters",
            "plugins._delta_force_login",
            "plugins._delta_force_place_push",
            "plugins._delta_force_render",
            "plugins._delta_force_store",
        )

    @property
    def config_spec(self) -> PluginConfigSpec:
        return PluginConfigSpec(
            (
                PluginConfigField("enabled", default=False, example=True),
                PluginConfigField("api_key", default="", description="Delta Force API 密钥"),
                PluginConfigField("client_id", default="", description="Delta Force 客户端标识"),
                PluginConfigField(
                    "api_mode",
                    default="auto",
                    choices=("auto", "eo", "esa"),
                    description="API 路由模式",
                    constraint="auto | eo | esa",
                ),
                PluginConfigField(
                    "base_urls",
                    default=[
                        "https://df-api-eo.shallow.ink",
                        "https://df-api-esa.shallow.ink",
                        "https://df-api.shallow.ink",
                    ],
                    cast=parse_string_list,
                    validator=validate_http_url_list,
                    description="API 基础地址列表",
                    constraint="http_url_list",
                ),
                PluginConfigField(
                    "request_timeout_sec",
                    default=30,
                    cast=parse_int,
                    validator=validate_min(1),
                    description="API 请求超时秒数",
                    constraint=">= 1",
                ),
                PluginConfigField(
                    "request_retries",
                    default=3,
                    cast=parse_int,
                    validator=validate_range(1, 10),
                    description="API 请求重试次数",
                    constraint="1 - 10",
                ),
                PluginConfigField(
                    "login_timeout_sec",
                    default=180,
                    cast=parse_int,
                    validator=validate_min(10),
                    description="扫码登录总超时秒数",
                    constraint=">= 10",
                ),
                PluginConfigField(
                    "login_poll_interval_sec",
                    default=1,
                    cast=parse_int,
                    validator=validate_min(1),
                    description="扫码登录轮询间隔秒数",
                    constraint=">= 1",
                ),
                PluginConfigField(
                    "login_success_notice_delay_sec",
                    default=10,
                    cast=parse_int,
                    validator=validate_min(0),
                    description="登录成功提示延迟秒数",
                    constraint=">= 0",
                ),
                PluginConfigField(
                    "login_delivery_mode",
                    default="private_message",
                    choices=("private_message", "temp_channel"),
                    description="二维码投递方式",
                    constraint="private_message | temp_channel",
                ),
                PluginConfigField(
                    "daily_keyword_push_check_interval_sec",
                    default=60,
                    cast=parse_int,
                    validator=validate_min(30),
                    description="每日口令推送检查间隔秒数",
                    constraint=">= 30",
                ),
                PluginConfigField(
                    "daily_keyword_push_time",
                    default="08:00",
                    validator=validate_hhmm,
                    description="每日口令推送时间",
                    constraint="HH:MM",
                ),
                PluginConfigField(
                    "place_push_interval_sec",
                    default=60,
                    cast=parse_int,
                    validator=validate_min(15),
                    description="特勤处推送检查间隔秒数",
                    constraint=">= 15",
                ),
                PluginConfigField(
                    "render_timeout_sec",
                    default=30,
                    cast=parse_float,
                    validator=validate_min(1),
                    description="渲染超时秒数",
                    constraint=">= 1",
                ),
                PluginConfigField(
                    "render_width",
                    default=1365,
                    cast=parse_int,
                    validator=validate_min(720),
                    description="渲染宽度",
                    constraint=">= 720",
                ),
                PluginConfigField(
                    "render_scale",
                    default=1.0,
                    cast=parse_float,
                    validator=validate_range(0.1, 4.0),
                    description="渲染缩放比例",
                    constraint="0.1 - 4.0",
                ),
                PluginConfigField("temp_dir", default="data/delta_force", description="临时文件目录"),
            )
        )

    def on_load(self, handler, config=None) -> None:
        self._handler = handler
        self._config = (config or {}).copy()
        self._api = DeltaForceApiClient(self._config)
        self._renderer = DeltaForceRenderer(self._config)
        self._login = DeltaForceLoginManager(self._config, self._api, self._store)
        self._daily_push = DeltaForceDailyKeywordPushManager(self._config, self._api, self._store)
        self._push = DeltaForcePlacePushManager(self._config, self._api, self._store)
        if self._daily_push and handler:
            try:
                if self._store.any_daily_keyword_push_subscriptions():
                    self._daily_push.ensure_started(handler)
            except Exception as exc:
                logger.warning("DeltaForcePlugin: daily keyword push preload skipped: %s", exc)
        if self._push and handler:
            try:
                if self._store.any_place_push_subscriptions():
                    self._push.ensure_started(handler)
            except Exception as exc:
                logger.warning("DeltaForcePlugin: place push preload skipped: %s", exc)

    def on_unload(self) -> None:
        if self._login:
            self._login.cancel_all()
        if self._daily_push:
            self._daily_push.stop()
        if self._push:
            self._push.stop()

    def handle_mention(self, text, channel, area, user, handler) -> bool:
        mention_prefix = self.command_capabilities.mention_prefixes[0]
        command = text[len(mention_prefix):].strip() if text.startswith(mention_prefix) else text.strip()
        if not command:
            self._send_text(handler, build_help_text(), channel, area)
            return True
        self._dispatch(command, channel, area, user, handler)
        return True

    def handle_slash(self, command, subcommand, arg, channel, area, user, handler) -> bool:
        if (command or "").strip().lower() != "/df":
            return False
        parts = []
        if subcommand:
            parts.append(subcommand)
        if arg:
            parts.append(arg)
        self._dispatch(" ".join(parts).strip(), channel, area, user, handler, slash=True)
        return True

    def _dispatch(self, command_text: str, channel: str, area: str, user: str, handler, slash: bool = False) -> None:
        try:
            self._dispatch_inner(command_text, channel, area, user, handler, slash=slash)
        except Exception as exc:
            logger.exception("DeltaForcePlugin: command failed: %s", command_text)
            self._send_text(handler, f"三角洲命令执行失败: {exc}", channel, area)

    def _dispatch_inner(self, command_text: str, channel: str, area: str, user: str, handler, slash: bool = False) -> None:
        command_text = command_text.strip()
        lower = command_text.lower()

        if not command_text or lower in {"help", "帮助"}:
            self._send_text(handler, build_help_text(), channel, area)
            return

        if lower.startswith("登录") or lower.startswith("login"):
            platform = self._parse_login_platform(command_text)
            if not self._ensure_api_config(handler, channel, area):
                return
            message = self._login.start_login(user, platform, channel, area, handler) if self._login else "登录模块未初始化"
            self._send_text(handler, message, channel, area)
            return

        if lower in {"角色绑定", "bind-character"}:
            if not self._ensure_api_config(handler, channel, area):
                return
            token = self._ensure_active_token(user, handler, channel, area)
            if not token:
                return
            payload = self._api.bind_character(token)
            err = self._api_error(payload)
            self._send_text(handler, err or "角色绑定请求已提交，请回到游戏确认是否生效。", channel, area)
            return

        if lower in {"账号", "accounts"}:
            self._send_accounts(user, handler, channel, area)
            return

        if lower.startswith("账号切换") or lower.startswith("switch"):
            self._switch_account(command_text, user, handler, channel, area)
            return

        if lower in {"信息", "info"}:
            self._send_info(user, handler, channel, area)
            return

        if lower in {"uid"}:
            self._send_uid(user, handler, channel, area)
            return

        if lower in {"每日密码", "今日密码", "daily-keyword", "password"}:
            self._send_daily_keyword(handler, channel, area)
            return

        if lower in {"开启每日密码推送"} or lower.startswith("daily-keyword-push on"):
            self._toggle_daily_keyword_push(True, handler, channel, area)
            return

        if lower in {"关闭每日密码推送"} or lower.startswith("daily-keyword-push off"):
            self._toggle_daily_keyword_push(False, handler, channel, area)
            return

        if lower in {"特勤处状态", "placestatus", "place-status"}:
            self._send_place_status(user, handler, channel, area)
            return

        if lower in {"开启特勤处推送", "开启制造推送"} or lower.startswith("place-push on"):
            self._toggle_place_push(True, user, handler, channel, area)
            return

        if lower in {"关闭特勤处推送", "关闭制造推送"} or lower.startswith("place-push off"):
            self._toggle_place_push(False, user, handler, channel, area)
            return

        if lower.startswith("藏品") or lower.startswith("资产") or lower.startswith("collection") or lower.startswith("assets"):
            self._send_collection(command_text, user, handler, channel, area)
            return

        if lower.startswith("物品搜索") or lower.startswith("物品查询") or lower.startswith("物品 ") or lower.startswith("object-search"):
            self._send_object_search(command_text, handler, channel, area)
            return

        if lower.startswith("价格历史") or lower.startswith("历史价格") or lower.startswith("price-history"):
            self._send_price_history(command_text, handler, channel, area)
            return

        if lower in {"货币", "money", "余额", "balance"}:
            self._send_money(user, handler, channel, area)
            return

        if lower in {"封号记录", "违规记录", "违规历史", "封号历史", "ban-history", "banhistory"}:
            self._send_ban_history(user, handler, channel, area)
            return

        if lower.startswith("大红收藏") or lower.startswith("大红藏品") or lower.startswith("大红海报") or lower.startswith("藏品海报") or lower.startswith("red-collection"):
            self._send_red_collection(command_text, user, handler, channel, area)
            return

        if lower.startswith("出红记录") or lower.startswith("大红记录") or lower.startswith("藏品记录") or lower.startswith("red-records"):
            self._send_red_records(user, handler, channel, area)
            return

        if lower.startswith("社区改枪码") or lower.startswith("改枪码列表") or lower.startswith("改枪方案列表") or lower.startswith("solution-list"):
            self._send_solution_list(command_text, user, handler, channel, area)
            return

        if lower.startswith("改枪码详情") or lower.startswith("改枪方案详情") or lower.startswith("solution-detail"):
            self._send_solution_detail(command_text, user, handler, channel, area)
            return

        if lower.startswith("日报") or lower.startswith("daily"):
            self._send_daily(command_text, user, handler, channel, area)
            return

        if lower.startswith("周报") or lower.startswith("weekly"):
            self._send_weekly(command_text, user, handler, channel, area)
            return

        if lower.startswith("战绩") or lower.startswith("record"):
            self._send_record(command_text, user, handler, channel, area)
            return

        self._send_text(handler, "未知三角洲命令，发送“@bot 三角洲帮助”查看用法。", channel, area)

    def _ensure_api_config(self, handler, channel: str, area: str) -> bool:
        if not self._api or not self._api.configured:
            self._send_text(handler, "三角洲插件未配置 api_key 或 client_id。", channel, area)
            return False
        return True

    def _api_error(self, payload: Optional[dict]) -> Optional[str]:
        if not isinstance(payload, dict):
            return "后端接口返回格式错误。"
        common = describe_common_failure(payload)
        if common:
            return common
        code = payload.get("code")
        success = payload.get("success")
        if code not in (None, 0, "0") and success not in (None, True):
            return str(payload.get("message") or payload.get("msg") or "接口调用失败")
        return None

    def _ensure_active_token(self, user: str, handler, channel: str, area: str) -> Optional[str]:
        if not self._ensure_api_config(handler, channel, area):
            return None
        active = self._store.get_active_token(user)
        if active:
            return active
        payload = self._api.get_user_list(user)
        err = self._api_error(payload)
        if err:
            self._send_text(handler, err, channel, area)
            return None
        accounts = payload.get("data") if isinstance(payload.get("data"), list) else []
        token = self._store.choose_active_token(user, accounts)
        if not token:
            self._send_text(handler, "当前没有有效账号，请先登录（执行三角洲登录）。", channel, area)
            return None
        return token

    def _send_accounts(self, user: str, handler, channel: str, area: str) -> None:
        if not self._ensure_api_config(handler, channel, area):
            return
        payload = self._api.get_user_list(user)
        err = self._api_error(payload)
        if err:
            self._send_text(handler, err, channel, area)
            return
        accounts = payload.get("data") if isinstance(payload.get("data"), list) else []
        active = self._store.choose_active_token(user, accounts)
        self._send_text(handler, format_accounts(accounts, active), channel, area)

    def _switch_account(self, command_text: str, user: str, handler, channel: str, area: str) -> None:
        if not self._ensure_api_config(handler, channel, area):
            return
        match = re.search(r"(\d+)$", command_text.strip())
        if not match:
            self._send_text(handler, "用法: @bot 三角洲账号切换 <序号> 或 /df switch <序号>", channel, area)
            return
        index = int(match.group(1))
        payload = self._api.get_user_list(user)
        err = self._api_error(payload)
        if err:
            self._send_text(handler, err, channel, area)
            return
        accounts = payload.get("data") if isinstance(payload.get("data"), list) else []
        if index < 1 or index > len(accounts):
            self._send_text(handler, "账号序号超出范围。", channel, area)
            return
        target = accounts[index - 1]
        token = str(target.get("frameworkToken") or "").strip()
        if not token:
            self._send_text(handler, "目标账号没有可用 token。", channel, area)
            return
        self._store.set_active_token(user, token)
        self._send_text(handler, f"已切换到账号 {index}。", channel, area)

    def _send_info(self, user: str, handler, channel: str, area: str) -> None:
        token = self._ensure_active_token(user, handler, channel, area)
        if not token:
            return
        payload = self._api.get_personal_info(token)
        err = self._api_error(payload)
        if err:
            self._send_text(handler, err, channel, area)
            return
        context = build_info_context(user, payload)
        self._send_poster_or_text(handler, "info", context, info_fallback_text(payload), channel, area)

    def _send_uid(self, user: str, handler, channel: str, area: str) -> None:
        token = self._ensure_active_token(user, handler, channel, area)
        if not token:
            return
        payload = self._api.get_personal_info(token)
        err = self._api_error(payload)
        if err:
            self._send_text(handler, err, channel, area)
            return
        self._send_text(handler, build_uid_text(payload), channel, area)

    def _send_daily_keyword(self, handler, channel: str, area: str) -> None:
        payload = self._api.get_daily_keyword()
        err = self._api_error(payload)
        if err:
            self._send_text(handler, err, channel, area)
            return
        self._send_text(handler, format_daily_keyword_text(payload), channel, area)

    def _toggle_daily_keyword_push(self, enabled: bool, handler, channel: str, area: str) -> None:
        if not self._ensure_api_config(handler, channel, area):
            return
        if not self._daily_push:
            self._send_text(handler, "每日密码推送模块未初始化。", channel, area)
            return
        if not enabled:
            if not self._daily_push.is_subscribed(channel, area):
                self._send_text(handler, "当前频道尚未开启每日密码推送。", channel, area)
                return
            self._daily_push.unsubscribe(channel, area)
            try:
                if not self._store.any_daily_keyword_push_subscriptions():
                    self._daily_push.stop()
            except Exception:
                pass
            self._send_text(handler, "已关闭当前频道的每日密码定时推送。", channel, area)
            return
        self._daily_push.subscribe(channel, area)
        self._daily_push.ensure_started(self._handler or handler)
        self._send_text(handler, "已开启当前频道的每日密码定时推送。", channel, area)

    def _send_object_search(self, command_text: str, handler, channel: str, area: str) -> None:
        query = self._tail_after_first_token(command_text)
        if not query:
            self._send_text(handler, "用法: @bot 三角洲物品 <关键词或ID> 或 /df object-search <关键词或ID>", channel, area)
            return
        if "," in query or "，" in query:
            parts = [part.strip() for part in re.split(r"[,，]", query) if part.strip()]
            query = parts[0] if parts else query
        if query.isdigit():
            payload = self._api.search_object(ids=query)
        else:
            payload = self._api.search_object(name=query)
        err = self._api_error(payload)
        if err:
            self._send_text(handler, err, channel, area)
            return
        self._send_text(handler, format_object_search_text(payload, query), channel, area)

    def _send_price_history(self, command_text: str, handler, channel: str, area: str) -> None:
        query = self._tail_after_first_token(command_text)
        if not query:
            self._send_text(handler, "用法: @bot 三角洲价格历史 <关键词或ID> 或 /df price-history <关键词或ID>", channel, area)
            return
        if "," in query or "，" in query:
            parts = [part.strip() for part in re.split(r"[,，]", query) if part.strip()]
            query = parts[0] if parts else query
        search_payload = self._api.search_object(ids=query) if query.isdigit() else self._api.search_object(name=query)
        err = self._api_error(search_payload)
        if err:
            self._send_text(handler, err, channel, area)
            return
        items = search_payload.get("data", {}).get("keywords") if isinstance(search_payload.get("data"), dict) else []
        items = items if isinstance(items, list) else []
        if not items and not query.isdigit():
            self._send_text(handler, f"未找到与“{query}”相关的物品。", channel, area)
            return
        first = items[0] if items and isinstance(items[0], dict) else {}
        object_id = str(first.get("objectID") or query).strip()
        history_payload = self._api.get_price_history_v2(object_id)
        history_err = self._api_error(history_payload)
        if history_err:
            history_payload = self._api.get_price_history_v1(object_id)
            history_err = self._api_error(history_payload)
            if history_err:
                self._send_text(handler, history_err, channel, area)
                return
        self._send_text(handler, format_price_history_text(search_payload, history_payload, query), channel, area)

    def _send_place_status(self, user: str, handler, channel: str, area: str) -> None:
        token = self._ensure_active_token(user, handler, channel, area)
        if not token:
            return
        payload = self._api.get_place_status(token)
        err = self._api_error(payload)
        if err:
            self._send_text(handler, err, channel, area)
            return
        personal_info = self._api.get_personal_info(token)
        if self._api_error(personal_info):
            personal_info = {}
        context = build_place_status_context(user, personal_info, payload)
        self._send_poster_or_text(handler, "place_status", context, place_status_fallback_text(payload), channel, area)

    def _toggle_place_push(self, enabled: bool, user: str, handler, channel: str, area: str) -> None:
        if not self._ensure_api_config(handler, channel, area):
            return
        if not self._push:
            self._send_text(handler, "特勤处推送模块未初始化。", channel, area)
            return
        if not enabled:
            if not self._push.is_subscribed(user, channel, area):
                self._send_text(handler, "当前频道尚未开启特勤处制造完成推送。", channel, area)
                return
            self._push.unsubscribe(user, channel, area)
            try:
                if not self._store.any_place_push_subscriptions():
                    self._push.stop()
            except Exception:
                pass
            self._send_text(handler, "已关闭当前频道的特勤处制造完成推送。", channel, area)
            return

        token = self._ensure_active_token(user, handler, channel, area)
        if not token:
            return
        payload = self._api.get_place_status(token)
        err = self._api_error(payload)
        if err:
            self._send_text(handler, f"开启失败：{err}", channel, area)
            return
        snapshot = self._push.extract_active_tasks(payload)
        self._push.subscribe(user, channel, area, snapshot)
        self._push.ensure_started(self._handler or handler)
        self._send_text(handler, "已开启当前频道的特勤处制造完成推送。", channel, area)

    def _send_collection(self, command_text: str, user: str, handler, channel: str, area: str) -> None:
        token = self._ensure_active_token(user, handler, channel, area)
        if not token:
            return
        type_filter = self._tail_after_first_token(command_text)
        collection_payload = self._api.get_collection(token)
        err = self._api_error(collection_payload)
        if err:
            self._send_text(handler, err, channel, area)
            return
        collection_map_payload = self._api.get_collection_map()
        map_err = self._api_error(collection_map_payload)
        if map_err:
            self._send_text(handler, f"获取藏品基础信息失败：{map_err}", channel, area)
            return
        personal_info = self._api.get_personal_info(token)
        if self._api_error(personal_info):
            personal_info = {}
        context = build_collection_context(user, personal_info, collection_payload, collection_map_payload, type_filter)
        self._send_poster_or_text(
            handler,
            "collection",
            context,
            collection_fallback_text(collection_payload, collection_map_payload, type_filter),
            channel,
            area,
        )

    def _send_money(self, user: str, handler, channel: str, area: str) -> None:
        token = self._ensure_active_token(user, handler, channel, area)
        if not token:
            return
        payload = self._api.get_money(token)
        err = self._api_error(payload)
        if err:
            self._send_text(handler, err, channel, area)
            return
        personal_info = self._api.get_personal_info(token)
        if self._api_error(personal_info):
            personal_info = {}
        context = build_money_context(user, personal_info, payload)
        self._send_poster_or_text(handler, "money", context, money_fallback_text(payload), channel, area)

    def _send_ban_history(self, user: str, handler, channel: str, area: str) -> None:
        token = self._ensure_active_token(user, handler, channel, area)
        if not token:
            return
        payload = self._api.get_ban_history(token)
        err = self._api_error(payload)
        if err:
            self._send_text(handler, err, channel, area)
            return
        personal_info = self._api.get_personal_info(token)
        if self._api_error(personal_info):
            personal_info = {}
        context = build_ban_history_context(user, personal_info, payload)
        self._send_poster_or_text(handler, "ban_history", context, ban_history_fallback_text(payload), channel, area)

    def _send_red_collection(self, command_text: str, user: str, handler, channel: str, area: str) -> None:
        token = self._ensure_active_token(user, handler, channel, area)
        if not token:
            return
        season_id = self._parse_red_season(command_text)
        season_display = f"S{season_id}赛季" if season_id != "all" else "所有赛季"
        personal_info = self._api.get_personal_info(token)
        if self._api_error(personal_info):
            personal_info = {}
        personal_data = self._api.get_personal_data(token, "", season_id)
        err = self._api_error(personal_data)
        if err:
            self._send_text(handler, err, channel, area)
            return
        title_payload = self._api.get_title(token)
        if self._api_error(title_payload):
            title_payload = {}
        object_list = self._api.get_object_list("props", "collection")
        if self._api_error(object_list):
            object_list = {}
        object_ids = self._extract_red_object_ids(personal_data)
        search_payload = self._api.search_object(ids=",".join(object_ids)) if object_ids else {}
        if self._api_error(search_payload):
            search_payload = {}
        context = build_red_collection_context(
            user,
            personal_info,
            personal_data,
            title_payload,
            object_list,
            search_payload,
            season_display,
        )
        self._send_poster_or_text(
            handler,
            "red_collection",
            context,
            red_collection_fallback_text(personal_data, title_payload, object_list, search_payload, season_display),
            channel,
            area,
        )

    def _send_red_records(self, user: str, handler, channel: str, area: str) -> None:
        token = self._ensure_active_token(user, handler, channel, area)
        if not token:
            return
        red_list = self._api.get_red_list(token)
        err = self._api_error(red_list)
        if err:
            self._send_text(handler, err, channel, area)
            return
        personal_info = self._api.get_personal_info(token)
        if self._api_error(personal_info):
            personal_info = {}
        object_ids = self._extract_red_record_object_ids(red_list)
        search_payload = self._api.search_object(ids=",".join(object_ids)) if object_ids else {}
        if self._api_error(search_payload):
            search_payload = {}
        context = build_red_record_context(user, personal_info, red_list, search_payload)
        self._send_poster_or_text(
            handler,
            "red_records",
            context,
            red_record_fallback_text(red_list, search_payload),
            channel,
            area,
        )

    def _send_solution_list(self, command_text: str, user: str, handler, channel: str, area: str) -> None:
        token = self._ensure_active_token(user, handler, channel, area)
        if not token:
            return
        weapon_name, price_range = self._parse_solution_list_args(command_text)
        payload = self._api.get_solution_list(
            token,
            user,
            weapon_name,
            price_range,
            client_id=getattr(self._api, "client_id", "") or None,
        )
        err = self._api_error(payload)
        if err:
            self._send_text(handler, err, channel, area)
            return
        self._send_text(handler, format_solution_list_text(payload, weapon_name, price_range), channel, area)

    def _send_solution_detail(self, command_text: str, user: str, handler, channel: str, area: str) -> None:
        token = self._ensure_active_token(user, handler, channel, area)
        if not token:
            return
        match = re.search(r"(\d+)\s*$", command_text.strip())
        if not match:
            self._send_text(handler, "用法: @bot 三角洲改枪码详情 <ID> 或 /df solution-detail <ID>", channel, area)
            return
        payload = self._api.get_solution_detail(
            token,
            user,
            match.group(1),
            client_id=getattr(self._api, "client_id", "") or None,
        )
        err = self._api_error(payload)
        if err:
            self._send_text(handler, err, channel, area)
            return
        self._send_text(handler, format_solution_detail_text(payload), channel, area)

    def _send_daily(self, command_text: str, user: str, handler, channel: str, area: str) -> None:
        token = self._ensure_active_token(user, handler, channel, area)
        if not token:
            return
        mode = self._parse_mode_from_args(command_text, leading=("日报", "daily"))
        date_text = today_yyyymmdd()
        daily_payload = self._api.get_daily_record(token, "" if mode == "all" else mode, date_text)
        err = self._api_error(daily_payload)
        if err:
            self._send_text(handler, err, channel, area)
            return
        personal_info = self._api.get_personal_info(token)
        if self._api_error(personal_info):
            personal_info = {}
        context = build_daily_context(user, personal_info, daily_payload, "" if mode == "all" else mode, date_text)
        self._send_poster_or_text(
            handler,
            "daily",
            context,
            daily_fallback_text(daily_payload, "" if mode == "all" else mode),
            channel,
            area,
        )

    def _send_weekly(self, command_text: str, user: str, handler, channel: str, area: str) -> None:
        token = self._ensure_active_token(user, handler, channel, area)
        if not token:
            return
        mode = self._parse_mode_from_args(command_text, leading=("周报", "weekly"))
        date_text = self._parse_date(command_text) or today_yyyymmdd()
        show_extra = "详细" in command_text or "detail" in command_text.lower()
        weekly_payload = self._api.get_weekly_record(token, "" if mode == "all" else mode, date_text, show_extra=show_extra)
        err = self._api_error(weekly_payload)
        if err:
            self._send_text(handler, err, channel, area)
            return
        personal_info = self._api.get_personal_info(token)
        if self._api_error(personal_info):
            personal_info = {}
        context = build_weekly_context(user, personal_info, weekly_payload, "" if mode == "all" else mode, date_text)
        self._send_poster_or_text(
            handler,
            "weekly",
            context,
            weekly_fallback_text(weekly_payload, "" if mode == "all" else mode),
            channel,
            area,
        )

    def _send_record(self, command_text: str, user: str, handler, channel: str, area: str) -> None:
        token = self._ensure_active_token(user, handler, channel, area)
        if not token:
            return
        mode = self._parse_mode_from_args(command_text, leading=("战绩", "record")) or "all"
        page = self._parse_page(command_text)
        personal_info = self._api.get_personal_info(token)
        if self._api_error(personal_info):
            personal_info = {}
        modes = ["sol", "mp"] if mode == "all" else [mode]
        sent_any = False
        for current_mode in modes:
            type_id = 4 if current_mode == "sol" else 5
            payload = self._api.get_record(token, type_id, page)
            err = self._api_error(payload)
            if err:
                if mode == "all":
                    self._send_text(handler, f"{current_mode.upper()} 查询失败: {err}", channel, area)
                    continue
                self._send_text(handler, err, channel, area)
                return
            records = payload.get("data") if isinstance(payload.get("data"), list) else []
            if not records:
                if mode != "all":
                    self._send_text(handler, record_fallback_text([], current_mode, page), channel, area)
                    return
                continue
            context = build_record_context(user, personal_info, records, current_mode, page)
            fallback = record_fallback_text(records, current_mode, page)
            self._send_poster_or_text(handler, "record", context, fallback, channel, area)
            sent_any = True
        if not sent_any:
            self._send_text(handler, "没有更多战绩记录。", channel, area)

    def _send_poster_or_text(self, handler, template_name: str, context: dict, fallback: str, channel: str, area: str) -> None:
        if self._renderer:
            image_path = self._renderer.render_to_image(template_name, context)
            if image_path:
                try:
                    handler.sender.upload_and_send_image(image_path, channel=channel, area=area)
                    self._renderer.safe_cleanup(image_path)
                    return
                except Exception as exc:
                    logger.warning("DeltaForcePlugin: upload poster failed: %s", exc)
                    self._renderer.safe_cleanup(image_path)
        self._send_text(handler, fallback, channel, area)

    @staticmethod
    def _send_text(handler, text: str, channel: str, area: str) -> None:
        handler.sender.send_message(text, channel=channel, area=area)

    @staticmethod
    def _parse_login_platform(command_text: str) -> str:
        lower = command_text.lower()
        if "微信" in command_text or "wechat" in lower:
            return "wechat"
        return "qq"

    @staticmethod
    def _parse_mode_from_args(command_text: str, leading: tuple[str, str]) -> str:
        text = command_text.strip()
        for prefix in leading:
            if text.lower().startswith(prefix.lower()):
                text = text[len(prefix):].strip()
                break
        for part in text.split():
            mode = normalize_mode(part)
            if mode:
                return mode
        return "all"

    @staticmethod
    def _parse_page(command_text: str) -> int:
        match = re.search(r"(\d+)\s*$", command_text.strip())
        if not match:
            return 1
        return max(1, int(match.group(1)))

    @staticmethod
    def _parse_date(command_text: str) -> str:
        match = re.search(r"\b(\d{8})\b", command_text)
        return match.group(1) if match else ""

    @staticmethod
    def _tail_after_first_token(command_text: str) -> str:
        parts = command_text.strip().split(maxsplit=1)
        if len(parts) < 2:
            return ""
        return parts[1].strip()

    @staticmethod
    def _parse_red_season(command_text: str) -> str:
        match = re.search(r"\b(\d+)\b", command_text)
        if not match:
            return "all"
        return match.group(1)

    @staticmethod
    def _extract_red_object_ids(personal_data: dict) -> list[str]:
        data = personal_data.get("data") if isinstance(personal_data.get("data"), dict) else {}
        sol = data.get("sol") if isinstance(data.get("sol"), dict) else {}
        sol_data = sol.get("data") if isinstance(sol.get("data"), dict) else {}
        inner = sol_data.get("data") if isinstance(sol_data.get("data"), dict) else {}
        detail = inner.get("solDetail") if isinstance(inner.get("solDetail"), dict) else {}
        red_items = detail.get("redCollectionDetail") if isinstance(detail.get("redCollectionDetail"), list) else []
        ids: list[str] = []
        for item in red_items:
            if not isinstance(item, dict):
                continue
            object_id = str(item.get("objectID") or "").strip()
            if object_id:
                ids.append(object_id)
        return sorted(set(ids))

    @staticmethod
    def _extract_red_record_object_ids(red_list: dict) -> list[str]:
        data = red_list.get("data") if isinstance(red_list.get("data"), dict) else {}
        records = data.get("records") if isinstance(data.get("records"), dict) else {}
        entries = records.get("list") if isinstance(records.get("list"), list) else []
        ids: list[str] = []
        for item in entries:
            if not isinstance(item, dict):
                continue
            object_id = str(item.get("itemId") or "").strip()
            if object_id:
                ids.append(object_id)
        return sorted(set(ids))

    @staticmethod
    def _parse_solution_list_args(command_text: str) -> tuple[str, str]:
        raw = command_text.strip()
        for prefix in ("社区改枪码", "改枪码列表", "改枪方案列表", "solution-list"):
            if raw.lower().startswith(prefix.lower()):
                raw = raw[len(prefix):].strip()
                break
        if not raw:
            return "", ""
        weapon_name = ""
        price_range = ""
        for part in raw.split():
            if re.fullmatch(r"\d+,\d+", part):
                price_range = part
            elif not weapon_name:
                weapon_name = part
        return weapon_name, price_range
