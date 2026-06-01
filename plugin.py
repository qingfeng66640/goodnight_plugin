"""说晚安插件入口。"""

from __future__ import annotations

import asyncio
from typing import cast

from src.app.plugin_system.api.log_api import get_logger
from src.app.plugin_system.api.service_api import get_service
from src.app.plugin_system.base import BasePlugin, register_plugin
from src.kernel.concurrency import get_task_manager

from .config import GoodnightConfig
from .event_handler import GoodnightEventHandler
from .service import GoodnightService

logger = get_logger("goodnight_plugin")


@register_plugin
class GoodnightPlugin(BasePlugin):
    """说晚安插件。"""

    plugin_name: str = "goodnight_plugin"
    plugin_description: str = "在合适时间对群聊说晚安，并劝导白名单用户早点睡觉"
    plugin_version: str = "1.0.0"

    configs = [GoodnightConfig]
    dependent_components: list[str] = []

    def __init__(self, config: GoodnightConfig | None = None) -> None:
        """初始化插件实例。"""

        super().__init__(config)
        self._schedule_ids: list[str] = []
        self._register_task_id: str | None = None

    def get_components(self) -> list[type]:
        """返回插件组件类。"""

        return [GoodnightService, GoodnightEventHandler]

    async def on_plugin_loaded(self) -> None:
        """插件加载后注册定时任务。"""

        task = get_task_manager().create_task(
            self._register_schedule_when_ready(),
            name="goodnight_plugin_register_schedule",
            daemon=True,
        )
        self._register_task_id = task.task_id

    async def on_plugin_unloaded(self) -> None:
        """插件卸载时移除定时任务。"""

        from src.kernel.scheduler import get_unified_scheduler

        scheduler = get_unified_scheduler()
        for schedule_id in list(self._schedule_ids):
            try:
                await scheduler.remove_schedule(schedule_id)
            except Exception:
                pass
        self._schedule_ids.clear()

        service = get_service("goodnight_plugin:service:goodnight_service")
        if isinstance(service, GoodnightService):
            cast(GoodnightService, service).clear_goodnight_reminder()
            cast(GoodnightService, service).clear_sleep_reminder()

        if self._register_task_id:
            try:
                get_task_manager().cancel_task(self._register_task_id)
            except Exception:
                pass
            self._register_task_id = None

    async def _register_schedule_when_ready(self) -> None:
        """等待 scheduler 就绪后注册周期任务。"""

        from src.kernel.scheduler import TriggerType, get_unified_scheduler

        scheduler = get_unified_scheduler()
        cfg = self.config if isinstance(self.config, GoodnightConfig) else GoodnightConfig()
        interval = max(10, int(cfg.general.tick_interval_seconds))

        for _attempt in range(600):
            try:
                goodnight_id = await scheduler.create_schedule(
                    callback=self._goodnight_tick,
                    trigger_type=TriggerType.TIME,
                    trigger_config={"interval_seconds": interval},
                    is_recurring=True,
                    task_name="goodnight_plugin_goodnight_tick",
                    force_overwrite=True,
                )
                cleanup_id = await scheduler.create_schedule(
                    callback=self._cleanup_tick,
                    trigger_type=TriggerType.TIME,
                    trigger_config={"interval_seconds": 3600},
                    is_recurring=True,
                    task_name="goodnight_plugin_cleanup_tick",
                    force_overwrite=True,
                )
                self._schedule_ids = [goodnight_id, cleanup_id]
                logger.info(f"goodnight_plugin 定时任务已注册: {self._schedule_ids}")
                return
            except RuntimeError:
                await asyncio.sleep(0.5)
            except Exception as exc:
                logger.warning(f"注册 goodnight_plugin 定时任务失败: {exc}")
                await asyncio.sleep(2.0)

        logger.warning("等待 scheduler 就绪超时，goodnight_plugin 定时任务未注册")

    async def _goodnight_tick(self) -> None:
        """周期检查主动群晚安。"""

        service = get_service("goodnight_plugin:service:goodnight_service")
        if isinstance(service, GoodnightService):
            await service.send_due_goodnights()

    async def _cleanup_tick(self) -> None:
        """周期清理旧状态。"""

        service = get_service("goodnight_plugin:service:goodnight_service")
        if isinstance(service, GoodnightService):
            await cast(GoodnightService, service).cleanup_old_state()
