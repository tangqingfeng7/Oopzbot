from __future__ import annotations

from app.lifecycle.context import AppContext
from core.logger_config import setup_logger
from web import web_player_config as web_cfg
from web.web_player import WebPlayerService

logger = setup_logger("BackgroundServices")


class BackgroundServiceRunner:
    """在应用事件循环内启动和停止后台服务。"""

    def __init__(self) -> None:
        self._web_player: WebPlayerService | None = None
        self._context: AppContext | None = None

    async def start(self, context: AppContext) -> None:
        self._context = context
        await self._start_music_services(context)
        await self._start_web_player(context)
        self._start_scheduler_services(context)

    async def _start_music_services(self, context: AppContext) -> None:
        music = context.handler.infrastructure.music
        await music.start_auto_play_monitor()
        await music.start_web_command_listener()
        logger.info("自动播放监控已启动。")
        # 语音浏览器放到后台预热：冷启动时首次进频道的身份绑定会赶不上，
        # 服务端因此不把 bot 显示为频道成员。预热不能阻塞启动，失败也不致命。
        warmup = getattr(context.voice, "warmup", None)
        if warmup is not None and context.supervisor is not None:
            context.supervisor.create(warmup(), name="voice-browser-warmup")

    async def _start_web_player(self, context: AppContext) -> None:
        from web.web_player import register_runtime_dependencies, set_oopz_client, set_sender

        set_sender(context.sender)
        set_oopz_client(context.client)
        register_runtime_dependencies(
            music=context.handler.infrastructure.music,
            plugins=context.handler.infrastructure.plugins,
            plugin_host=context.handler.plugin_host,
        )
        await self._warmup_members_cache(context.sender)
        web_host = web_cfg.web_host()
        web_port = web_cfg.web_port()
        self._web_player = WebPlayerService(host=web_host, port=web_port)
        await self._web_player.start()
        logger.info("Web 播放器已启动: http://%s:%s", web_host, web_port)

    async def _warmup_members_cache(self, sender) -> None:
        try:
            from core.area_config import get_area_registry

            area_ids = get_area_registry().get_all_area_ids()
            if not area_ids:
                from config import OOPZ_CONFIG

                fallback = str(OOPZ_CONFIG.get("default_area") or "").strip()
                if not fallback:
                    areas = await sender.bot.areas.get_joined_areas()
                    if areas:
                        fallback = areas[0].area_id.strip()
                area_ids = [fallback] if fallback else []
            total = 0
            for area in area_ids:
                if not area:
                    continue
                try:
                    page = await sender.bot.areas.get_area_members(area)
                    total += len(page.members)
                except Exception as exc:
                    logger.debug("成员缓存预热失败 (area=%s): %s", area[:8], exc)
            if total:
                logger.info("成员缓存预热完成: %d 个域, 共 %d 人", len(area_ids), total)
        except Exception:
            logger.debug("成员缓存预热异常", exc_info=True)

    @staticmethod
    def _start_scheduler_services(context: AppContext) -> None:
        scheduler = context.handler.services.scheduler
        scheduler.scheduled.start(context.supervisor)
        scheduler.reminder.start(context.supervisor)

    async def stop_ingress(self, timeout: float = 5.0) -> None:
        web_player = self._web_player
        self._web_player = None
        if web_player is not None:
            try:
                await web_player.stop(timeout=timeout)
            except Exception as exc:
                logger.warning("停止 Web 播放器时出现异常: %s", exc)

    async def stop_producers(self, timeout: float = 5.0) -> None:
        context = self._context
        if context is None:
            return
        services = (
            ("音乐后台服务", context.handler.infrastructure.music.stop),
            ("定时消息", context.handler.services.scheduler.scheduled.stop),
            ("提醒", context.handler.services.scheduler.reminder.stop),
            ("自动撤回", context.handler.services.safety.recall_scheduler.stop),
        )
        for name, stop in services:
            try:
                await stop(timeout=timeout)
            except Exception as exc:
                logger.warning("停止 %s 时出现异常: %s", name, exc)
        notifier = context.notifier_callback
        if notifier is not None:
            try:
                await notifier.stop(timeout=timeout)
            except Exception as exc:
                logger.warning("停止区域通知时出现异常: %s", exc)

    async def stop_plugins(self, timeout: float = 5.0) -> None:
        context = self._context
        if context is None:
            return
        try:
            await context.handler.infrastructure.plugins.stop(timeout=timeout)
        except Exception as exc:
            logger.warning("停止插件时出现异常: %s", exc)

    async def stop(self, timeout: float = 5.0) -> None:
        await self.stop_ingress(timeout=timeout)
        await self.stop_producers(timeout=timeout)
        await self.stop_plugins(timeout=timeout)
