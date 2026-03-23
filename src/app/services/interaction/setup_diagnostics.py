from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import requests

import config as runtime_config
import web_player_config as web_cfg
from database import DB_PATH
from queue_manager import get_redis_client


class SetupDiagnostics:
    """汇总系统体检与首启向导所需的诊断信息。"""

    _WEAK_PASSWORDS = {
        "123456",
        "12345678",
        "admin",
        "admin123",
        "password",
        "qwerty",
    }

    def __init__(self, *, sender=None, plugins=None):
        self._sender = sender
        self._plugins = plugins
        self._session = requests.Session()

    def build_report(self) -> dict[str, Any]:
        checks = [
            self._check_runtime_storage(),
            self._check_admin_password(),
            self._check_web_player(),
            self._check_redis(),
            self._check_database(),
            self._check_oopz_config(),
            self._check_joined_areas(),
            self._check_default_area_channel(),
            self._check_netease_api(),
            self._check_netease_cookie(),
            self._check_ai_chat(),
            self._check_ai_image(),
            self._check_plugins(),
        ]
        summary = self._summarize(checks)
        wizard_steps = self._build_wizard_steps(checks)
        overall = "fail" if summary["fail"] else ("warn" if summary["warn"] else "pass")
        return {
            "status": overall,
            "ok": overall != "fail",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "summary": summary,
            "checks": checks,
            "wizard_steps": wizard_steps,
            "first_run_needed": any(
                step["required"] and step["status"] in {"blocked", "pending"}
                for step in wizard_steps
            ),
            "quick_links": [
                {"label": "配置中心", "href": "/admin/config"},
                {"label": "系统页", "href": "/admin/system"},
                {"label": "插件页", "href": "/admin/plugins"},
                {"label": "域管理", "href": "/admin/areas"},
            ],
        }

    def _make_check(
        self,
        *,
        check_id: str,
        group: str,
        title: str,
        level: str,
        summary: str,
        detail: str = "",
        action: str = "",
        page: str = "",
        blocking: bool = False,
        current: str = "",
    ) -> dict[str, Any]:
        return {
            "id": check_id,
            "group": group,
            "title": title,
            "level": level,
            "summary": summary,
            "detail": detail or summary,
            "action": action,
            "page": page,
            "blocking": blocking,
            "current": current,
        }

    def _probe_http(self, url: str) -> tuple[bool, str]:
        if not url:
            return False, "未配置地址"
        try:
            response = self._session.get(url, timeout=3, allow_redirects=True)
            if response.status_code < 500:
                return True, f"HTTP {response.status_code}"
            return False, f"HTTP {response.status_code}"
        except Exception as exc:
            return False, str(exc)

    def _summarize(self, checks: list[dict[str, Any]]) -> dict[str, int]:
        summary = {"pass": 0, "warn": 0, "fail": 0, "info": 0, "total": len(checks)}
        for item in checks:
            level = item.get("level", "info")
            if level not in summary:
                continue
            summary[level] += 1
        return summary

    def _truncate(self, text: str, limit: int = 56) -> str:
        text = str(text or "").strip()
        if len(text) <= limit:
            return text
        return text[: limit - 3] + "..."

    def _mask(self, text: str, keep: int = 4) -> str:
        text = str(text or "").strip()
        if not text:
            return ""
        if len(text) <= keep * 2:
            return "*" * len(text)
        return text[:keep] + "*" * (len(text) - keep * 2) + text[-keep:]

    def _check_runtime_storage(self) -> dict[str, Any]:
        data_dir = os.path.join(web_cfg.PROJECT_ROOT, "data")
        target_dir = data_dir if os.path.isdir(data_dir) else os.path.dirname(data_dir) or web_cfg.PROJECT_ROOT
        writable = os.access(target_dir, os.W_OK)
        if writable:
            return self._make_check(
                check_id="runtime_storage",
                group="runtime",
                title="运行时存储",
                level="pass",
                summary="运行时目录可写",
                detail=f"配置覆盖、插件状态等数据将写入: {target_dir}",
                page="/admin/system",
                current=target_dir,
            )
        return self._make_check(
            check_id="runtime_storage",
            group="runtime",
            title="运行时存储",
            level="fail",
            summary="运行时目录不可写",
            detail=f"当前目录无写权限: {target_dir}",
            action="检查项目目录和 data 目录权限",
            page="/admin/system",
            blocking=True,
            current=target_dir,
        )

    def _check_admin_password(self) -> dict[str, Any]:
        enabled = web_cfg.admin_enabled()
        password = web_cfg.admin_password()
        if not enabled:
            return self._make_check(
                check_id="admin_password",
                group="security",
                title="后台安全",
                level="warn",
                summary="管理后台未启用",
                detail="后台处于关闭状态，首启阶段建议保留管理后台，方便完成配置与体检。",
                action="在配置中心开启管理后台",
                page="/admin/config",
            )
        if not password:
            return self._make_check(
                check_id="admin_password",
                group="security",
                title="后台安全",
                level="fail",
                summary="后台密码未配置",
                detail="当前无法安全登录后台，建议立即设置强密码。",
                action="前往配置中心设置 admin_password",
                page="/admin/config",
                blocking=True,
            )
        if len(password) < 8 or password.lower() in self._WEAK_PASSWORDS:
            return self._make_check(
                check_id="admin_password",
                group="security",
                title="后台安全",
                level="warn",
                summary="后台密码强度偏弱",
                detail="已配置后台密码，但强度不足，建议改成至少 8 位且包含字母数字。",
                action="在配置中心更新后台密码",
                page="/admin/config",
            )
        return self._make_check(
            check_id="admin_password",
            group="security",
            title="后台安全",
            level="pass",
            summary="后台密码已配置",
            detail="管理后台已启用，且密码强度满足基础要求。",
            page="/admin/config",
        )

    def _check_web_player(self) -> dict[str, Any]:
        base_url = web_cfg.display_web_base_url()
        return self._make_check(
            check_id="web_player",
            group="runtime",
            title="Web 后台与播放器",
            level="pass",
            summary="已生成 Web 入口地址",
            detail=f"当前展示地址: {base_url}",
            page="/admin/system",
            current=base_url,
        )

    def _check_redis(self) -> dict[str, Any]:
        try:
            client = get_redis_client()
            client.ping()
            dbsize = int(client.dbsize() or 0)
            return self._make_check(
                check_id="redis",
                group="runtime",
                title="Redis 连接",
                level="pass",
                summary="Redis 连接正常",
                detail=f"{runtime_config.REDIS_CONFIG.get('host', '127.0.0.1')}:{runtime_config.REDIS_CONFIG.get('port', 6379)} | dbsize={dbsize}",
                page="/admin/system",
            )
        except Exception as exc:
            return self._make_check(
                check_id="redis",
                group="runtime",
                title="Redis 连接",
                level="fail",
                summary="Redis 无法连接",
                detail=f"连接失败: {exc}",
                action="检查 Redis 地址、密码和服务状态",
                page="/admin/config",
                blocking=True,
            )

    def _check_database(self) -> dict[str, Any]:
        if os.path.exists(DB_PATH):
            size = os.path.getsize(DB_PATH)
            return self._make_check(
                check_id="database",
                group="runtime",
                title="数据库",
                level="pass",
                summary="数据库文件存在",
                detail=f"{DB_PATH} | {size} 字节",
                page="/admin/system",
                current=DB_PATH,
            )
        return self._make_check(
            check_id="database",
            group="runtime",
            title="数据库",
            level="warn",
            summary="数据库文件尚未生成",
            detail="数据库通常会在运行过程中自动创建；如果长期不存在，说明初始化链路可能没有跑通。",
            action="先启动机器人并执行一次常用命令，再复查系统页",
            page="/admin/system",
            current=DB_PATH,
        )

    def _check_oopz_config(self) -> dict[str, Any]:
        oopz = getattr(runtime_config, "OOPZ_CONFIG", {})
        person_uid = str(oopz.get("person_uid", "") or "").strip()
        jwt_token = str(oopz.get("jwt_token", "") or "").strip()
        base_url = str(oopz.get("base_url", "") or "").strip()
        api_url = str(oopz.get("api_url", "") or "").strip()
        if person_uid and jwt_token and base_url and api_url:
            return self._make_check(
                check_id="oopz_config",
                group="oopz",
                title="OOPZ 登录配置",
                level="pass",
                summary="OOPZ 基础配置完整",
                detail=f"UID: {self._mask(person_uid, keep=4)} | 网关: {self._truncate(base_url)}",
                page="/admin/config",
            )
        missing = []
        if not person_uid:
            missing.append("person_uid")
        if not jwt_token:
            missing.append("jwt_token")
        if not base_url:
            missing.append("base_url")
        if not api_url:
            missing.append("api_url")
        return self._make_check(
            check_id="oopz_config",
            group="oopz",
            title="OOPZ 登录配置",
            level="fail",
            summary="OOPZ 基础配置不完整",
            detail=f"缺失项: {', '.join(missing)}",
            action="补齐 config.py 中的 OOPZ_CONFIG",
            page="/admin/config",
            blocking=True,
        )

    def _check_joined_areas(self) -> dict[str, Any]:
        if self._sender is None:
            return self._make_check(
                check_id="joined_areas",
                group="oopz",
                title="域连接状态",
                level="info",
                summary="未注入发送器，跳过在线校验",
                detail="当前环境只能检查配置完整性，无法直接校验已加入域列表。",
                page="/admin/areas",
            )
        try:
            areas = self._sender.get_joined_areas(quiet=True) or []
            if areas:
                first = areas[0]
                name = first.get("name") or first.get("id") or "未知域"
                return self._make_check(
                    check_id="joined_areas",
                    group="oopz",
                    title="域连接状态",
                    level="pass",
                    summary=f"已读取到 {len(areas)} 个域",
                    detail=f"首个域: {name}",
                    page="/admin/areas",
                )
            return self._make_check(
                check_id="joined_areas",
                group="oopz",
                title="域连接状态",
                level="warn",
                summary="未读取到已加入域",
                detail="配置存在，但当前没有拿到域列表；可能是登录态失效，或机器人尚未正常加入域。",
                action="检查 OOPZ 登录态并确认机器人已加入目标域",
                page="/admin/areas",
            )
        except Exception as exc:
            return self._make_check(
                check_id="joined_areas",
                group="oopz",
                title="域连接状态",
                level="warn",
                summary="域列表读取失败",
                detail=f"读取失败: {exc}",
                action="检查登录态、网络代理和 OOPZ 网关连通性",
                page="/admin/system",
            )

    def _check_default_area_channel(self) -> dict[str, Any]:
        oopz = getattr(runtime_config, "OOPZ_CONFIG", {})
        area_id = str(oopz.get("default_area", "") or "").strip()
        channel_id = str(oopz.get("default_channel", "") or "").strip()
        if area_id and channel_id:
            return self._make_check(
                check_id="default_area_channel",
                group="oopz",
                title="默认域与频道",
                level="pass",
                summary="默认域和频道已配置",
                detail=f"area={self._mask(area_id, keep=4)} | channel={self._mask(channel_id, keep=4)}",
                page="/admin/config",
            )
        if area_id and not channel_id:
            return self._make_check(
                check_id="default_area_channel",
                group="oopz",
                title="默认域与频道",
                level="warn",
                summary="默认频道未配置",
                detail="已经配置默认域，但默认频道为空，部分推送和默认发言入口会缺少目标频道。",
                action="在配置中心填写 default_channel",
                page="/admin/config",
            )
        return self._make_check(
            check_id="default_area_channel",
            group="oopz",
            title="默认域与频道",
            level="warn",
            summary="默认域与频道未配置",
            detail="建议在首启阶段先确定一个默认域和默认频道，减少命令与后台操作的上下文歧义。",
            action="在配置中心填写 default_area 和 default_channel",
            page="/admin/config",
        )

    def _check_netease_api(self) -> dict[str, Any]:
        netease = getattr(runtime_config, "NETEASE_CLOUD", {})
        base_url = str(netease.get("base_url", "") or "").rstrip("/")
        if not base_url:
            return self._make_check(
                check_id="netease_api",
                group="music",
                title="网易云 API",
                level="warn",
                summary="网易云 API 地址未配置",
                detail="音乐搜索和播放依赖网易云 API，未配置时音乐体验会明显受限。",
                action="配置 NETEASE_CLOUD.base_url",
                page="/admin/config",
            )
        ok, detail = self._probe_http(base_url + "/")
        if ok:
            return self._make_check(
                check_id="netease_api",
                group="music",
                title="网易云 API",
                level="pass",
                summary="网易云 API 可访问",
                detail=f"{base_url} | {detail}",
                page="/admin/config",
                current=base_url,
            )
        return self._make_check(
            check_id="netease_api",
            group="music",
            title="网易云 API",
            level="warn",
            summary="网易云 API 连通性异常",
            detail=f"{base_url} | {detail}",
            action="检查本地 API 服务是否启动，或确认 base_url 是否正确",
            page="/admin/system",
            current=base_url,
        )

    def _check_netease_cookie(self) -> dict[str, Any]:
        cookie = str(getattr(runtime_config, "NETEASE_CLOUD", {}).get("cookie", "") or "").strip()
        if cookie:
            return self._make_check(
                check_id="netease_cookie",
                group="music",
                title="网易云 Cookie",
                level="pass",
                summary="网易云 Cookie 已配置",
                detail="喜欢列表、部分登录态接口可正常工作。",
                page="/admin/config",
            )
        return self._make_check(
            check_id="netease_cookie",
            group="music",
            title="网易云 Cookie",
            level="warn",
            summary="网易云 Cookie 未配置",
            detail="基础搜歌可以继续使用，但喜欢列表、账号态接口和部分资源能力会受限。",
            action="在配置中心补充 NETEASE_CLOUD.cookie",
            page="/admin/config",
        )

    def _check_ai_chat(self) -> dict[str, Any]:
        ai = getattr(runtime_config, "DOUBAO_CONFIG", {})
        enabled = bool(ai.get("enabled", False))
        base_url = str(ai.get("base_url", "") or "").strip()
        api_key = str(ai.get("api_key", "") or "").strip()
        model = str(ai.get("model", "") or "").strip()
        if not enabled:
            return self._make_check(
                check_id="ai_chat",
                group="ai",
                title="AI 聊天",
                level="info",
                summary="AI 聊天当前关闭",
                detail="如果你不需要聊天兜底，可以保持关闭；否则建议补齐模型配置。",
                action="需要时在配置中心开启豆包聊天",
                page="/admin/config",
            )
        if base_url and api_key and model:
            return self._make_check(
                check_id="ai_chat",
                group="ai",
                title="AI 聊天",
                level="pass",
                summary="AI 聊天配置完整",
                detail=f"模型: {model}",
                page="/admin/config",
            )
        missing = []
        if not base_url:
            missing.append("base_url")
        if not api_key:
            missing.append("api_key")
        if not model:
            missing.append("model")
        return self._make_check(
            check_id="ai_chat",
            group="ai",
            title="AI 聊天",
            level="warn",
            summary="AI 聊天已开启但配置不完整",
            detail=f"缺失项: {', '.join(missing)}",
            action="补齐 doubao_chat 配置，或先关闭该功能",
            page="/admin/config",
        )

    def _check_ai_image(self) -> dict[str, Any]:
        image = getattr(runtime_config, "DOUBAO_IMAGE_CONFIG", {})
        enabled = bool(image.get("enabled", False))
        base_url = str(image.get("base_url", "") or "").strip()
        api_key = str(image.get("api_key", "") or "").strip()
        model = str(image.get("model", "") or "").strip()
        if not enabled:
            return self._make_check(
                check_id="ai_image",
                group="ai",
                title="AI 绘图",
                level="info",
                summary="AI 绘图当前关闭",
                detail="如果不需要文生图，可以保持关闭。",
                action="需要时在配置中心开启豆包文生图",
                page="/admin/config",
            )
        if base_url and api_key and model:
            return self._make_check(
                check_id="ai_image",
                group="ai",
                title="AI 绘图",
                level="pass",
                summary="AI 绘图配置完整",
                detail=f"模型: {model}",
                page="/admin/config",
            )
        missing = []
        if not base_url:
            missing.append("base_url")
        if not api_key:
            missing.append("api_key")
        if not model:
            missing.append("model")
        return self._make_check(
            check_id="ai_image",
            group="ai",
            title="AI 绘图",
            level="warn",
            summary="AI 绘图已开启但配置不完整",
            detail=f"缺失项: {', '.join(missing)}",
            action="补齐 doubao_image 配置，或先关闭该功能",
            page="/admin/config",
        )

    def _check_plugins(self) -> dict[str, Any]:
        if self._plugins is None:
            return self._make_check(
                check_id="plugins",
                group="plugins",
                title="插件运行时",
                level="info",
                summary="当前未注入插件运行时",
                detail="无法在本上下文统计已发现和已加载插件数量。",
                page="/admin/plugins",
            )
        try:
            discovered = self._plugins.discover()
            loaded = self._plugins.list_descriptors()
            return self._make_check(
                check_id="plugins",
                group="plugins",
                title="插件运行时",
                level="pass",
                summary=f"已发现 {len(discovered)} 个插件，已加载 {len(loaded)} 个",
                detail=f"状态文件: {getattr(self._plugins, 'state_path', '未提供')}",
                page="/admin/plugins",
            )
        except Exception as exc:
            return self._make_check(
                check_id="plugins",
                group="plugins",
                title="插件运行时",
                level="warn",
                summary="插件状态读取失败",
                detail=f"读取失败: {exc}",
                action="前往插件页检查装载状态和配置文件",
                page="/admin/plugins",
            )

    def _build_wizard_steps(self, checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_id = {item["id"]: item for item in checks}
        templates = [
            {
                "id": "security",
                "title": "设置后台安全与持久化",
                "required": True,
                "page": "/admin/config",
                "description": "先确保后台密码可用、运行时目录可写，后续配置才能稳定保存。",
                "check_ids": ["runtime_storage", "admin_password"],
            },
            {
                "id": "oopz",
                "title": "确认 OOPZ 登录态与入域状态",
                "required": True,
                "page": "/admin/areas",
                "description": "确认机器人可以读取域列表，否则后面的默认域、成员和频道能力都不可靠。",
                "check_ids": ["oopz_config", "joined_areas"],
            },
            {
                "id": "default_context",
                "title": "设置默认域和默认频道",
                "required": True,
                "page": "/admin/config",
                "description": "先定义默认上下文，减少命令执行时的歧义和后台操作的选域成本。",
                "check_ids": ["default_area_channel"],
            },
            {
                "id": "runtime",
                "title": "打通基础运行时",
                "required": True,
                "page": "/admin/system",
                "description": "Redis 与数据库是消息、队列和状态管理的基础依赖。",
                "check_ids": ["redis", "database", "web_player"],
            },
            {
                "id": "music",
                "title": "补齐音乐能力",
                "required": False,
                "page": "/admin/config",
                "description": "如果要使用点歌、喜欢列表和播放器，建议先完成网易云相关配置。",
                "check_ids": ["netease_api", "netease_cookie"],
            },
            {
                "id": "ai",
                "title": "按需开启 AI 能力",
                "required": False,
                "page": "/admin/config",
                "description": "AI 聊天和绘图不是首启硬依赖，但建议在准备好密钥后一次配齐。",
                "check_ids": ["ai_chat", "ai_image"],
            },
            {
                "id": "plugins",
                "title": "检查插件装载状态",
                "required": False,
                "page": "/admin/plugins",
                "description": "插件不是硬依赖，但可以在首启阶段确认扩展能力是否按预期加载。",
                "check_ids": ["plugins"],
            },
        ]
        steps: list[dict[str, Any]] = []
        for template in templates:
            related = [by_id[item_id] for item_id in template["check_ids"] if item_id in by_id]
            levels = {item["level"] for item in related}
            if "fail" in levels:
                status = "blocked"
            elif "warn" in levels:
                status = "pending"
            elif any(level == "pass" for level in levels):
                status = "done"
            else:
                status = "optional"
            actions = [item["action"] for item in related if item.get("action")]
            highlights = [item["summary"] for item in related if item["level"] in {"fail", "warn"}]
            if not highlights:
                highlights = [item["summary"] for item in related[:1]]
            steps.append(
                {
                    "id": template["id"],
                    "title": template["title"],
                    "required": template["required"],
                    "page": template["page"],
                    "description": template["description"],
                    "status": status,
                    "summary": "；".join(highlights) if highlights else "当前无需处理",
                    "actions": actions,
                    "checks": related,
                }
            )
        return steps
