"""
Delta Force MVP plugin for Oopz Bot.
"""

from __future__ import annotations

import re
from typing import Optional

from logger_config import get_logger
from plugin_base import BotModule, PluginMetadata

from ._delta_force_api import DeltaForceApiClient, describe_common_failure
from ._delta_force_assets import normalize_mode
from ._delta_force_formatters import (
    build_daily_context,
    build_help_text,
    build_info_context,
    build_record_context,
    build_uid_text,
    build_weekly_context,
    daily_fallback_text,
    format_accounts,
    info_fallback_text,
    record_fallback_text,
    today_yyyymmdd,
    weekly_fallback_text,
)
from ._delta_force_login import DeltaForceLoginManager
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

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="delta_force",
            description="三角洲行动账号与战绩查询",
            version="0.1.0",
            author="OpenAI",
        )

    @property
    def mention_prefixes(self) -> tuple[str, ...]:
        return ("三角洲",)

    @property
    def slash_commands(self) -> tuple[str, ...]:
        return ("/df",)

    @property
    def private_modules(self) -> tuple[str, ...]:
        return (
            "plugins._delta_force_api",
            "plugins._delta_force_assets",
            "plugins._delta_force_formatters",
            "plugins._delta_force_login",
            "plugins._delta_force_render",
            "plugins._delta_force_store",
        )

    def on_load(self, handler, config=None) -> None:
        self._config = (config or {}).copy()
        self._api = DeltaForceApiClient(self._config)
        self._renderer = DeltaForceRenderer(self._config)
        self._login = DeltaForceLoginManager(self._config, self._api, self._store)

    def on_unload(self) -> None:
        if self._login:
            self._login.cancel_all()

    def handle_mention(self, text, channel, area, user, handler) -> bool:
        command = text[len("三角洲"):].strip() if text.startswith("三角洲") else text.strip()
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
