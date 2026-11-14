from __future__ import annotations

from app.services.runtime import CommandRuntimeView, sender_of

from .setup_diagnostics import SetupDiagnostics


class SetupService:
    """负责发送系统体检和首启向导消息。"""

    def __init__(self, runtime: CommandRuntimeView):
        self._runtime = runtime
        self._sender = sender_of(runtime)
        # 回退要惰性：runtime 可能是只带 plugins 的精简对象，没有 infrastructure。
        # 这里保留「两边都没有就是 None」的语义，SetupDiagnostics 显式支持插件缺席。
        plugins = getattr(runtime, "plugins", None)
        if plugins is None:
            plugins = getattr(getattr(runtime, "infrastructure", None), "plugins", None)
        self._plugins = plugins

    async def build_report(self) -> dict:
        diagnostics = SetupDiagnostics(sender=self._sender, plugins=self._plugins)
        return await diagnostics.build_report()

    async def show_health_check(self, channel: str, area: str) -> None:
        report = await self.build_report()
        summary = report["summary"]
        level_label = {
            "pass": "正常",
            "warn": "需关注",
            "fail": "存在阻塞项",
        }.get(report["status"], "已生成")
        lines = [
            f"【系统体检】{level_label}",
            f"通过 {summary['pass']} | 警告 {summary['warn']} | 失败 {summary['fail']} | 信息 {summary['info']}",
        ]
        issues = [item for item in report["checks"] if item["level"] in {"fail", "warn"}]
        if issues:
            lines.append("")
            lines.append("当前需要处理:")
            for item in issues[:6]:
                prefix = "失败" if item["level"] == "fail" else "警告"
                lines.append(f"[{prefix}] {item['title']}: {item['summary']}")
        else:
            lines.append("")
            lines.append("当前核心依赖已就绪。")
        lines += [
            "",
            "下一步:",
            "@bot 首启向导  查看分步处理建议",
            "/setup  查看首启向导",
        ]
        await self._sender.send_message("\n".join(lines), channel=channel, area=area)

    def _admin_setup_lines(self, user: str) -> list[str]:
        """未配置管理员时的引导。

        权限判定是 fail-closed 的（见 CommandAccessService.is_admin），空名单下
        所有管理命令都不可用；而后台默认关闭、密码默认为空，也不能靠后台自救。
        所以这里必须回显调用者 UID —— 否则用户拿不到填进 ADMIN_UIDS 的值。
        """
        if self._runtime.services.routing.access.has_configured_admins():
            return []
        lines = [
            "",
            "【尚未配置管理员】当前所有管理命令对任何人都不可用。",
            "请按以下步骤配置：",
        ]
        if user:
            lines.append(f"1. 你的 UID: {user}")
        else:
            lines.append("1. 发送 @bot 个人信息 获取你的 UID")
        lines += [
            "2. 编辑项目根目录 config.py，填入 ADMIN_UIDS = [\"上面的 UID\"]",
            "3. 重启 Bot 生效",
            "",
            "也可以先在 config.py 里设置 WEB_PLAYER_CONFIG 的 admin_enabled=True",
            "与 admin_password，重启后从 /admin 后台管理。",
        ]
        return lines

    async def show_setup_wizard(self, channel: str, area: str, user: str = "") -> None:
        report = await self.build_report()
        lines = ["【首启向导】按顺序完成以下步骤"]
        for index, step in enumerate(report["wizard_steps"], start=1):
            status_text = {
                "done": "已完成",
                "pending": "待处理",
                "blocked": "阻塞",
                "optional": "可选",
            }.get(step["status"], "待处理")
            lines.append(f"{index}. [{status_text}] {step['title']}")
            lines.append(f"   {step['description']}")
            if step.get("summary"):
                lines.append(f"   当前状态: {step['summary']}")
            if step.get("actions"):
                lines.append(f"   建议操作: {step['actions'][0]}")
            if step.get("page"):
                lines.append(f"   后台入口: {step['page']}")
        lines += self._admin_setup_lines(user)
        lines += [
            "",
            "可用命令:",
            "@bot 体检",
            "/health",
        ]
        await self._sender.send_message("\n".join(lines), channel=channel, area=area)
