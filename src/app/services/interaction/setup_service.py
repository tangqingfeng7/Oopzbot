from __future__ import annotations

from app.services.runtime import CommandRuntimeView, sender_of

from .setup_diagnostics import SetupDiagnostics


class SetupService:
    """负责发送系统体检和首启向导消息。"""

    def __init__(self, runtime: CommandRuntimeView):
        self._runtime = runtime
        self._sender = sender_of(runtime)
        self._plugins = getattr(runtime, "plugins", getattr(runtime.infrastructure, "plugins", None))

    def build_report(self) -> dict:
        diagnostics = SetupDiagnostics(sender=self._sender, plugins=self._plugins)
        return diagnostics.build_report()

    def show_health_check(self, channel: str, area: str) -> None:
        report = self.build_report()
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
            "/setup  查看后台首启步骤",
            "后台页面: /admin/setup",
        ]
        self._sender.send_message("\n".join(lines), channel=channel, area=area)

    def show_setup_wizard(self, channel: str, area: str) -> None:
        report = self.build_report()
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
        lines += [
            "",
            "可用命令:",
            "@bot 体检",
            "/health",
        ]
        self._sender.send_message("\n".join(lines), channel=channel, area=area)
