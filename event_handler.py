"""说晚安插件事件处理器。"""

from __future__ import annotations

from typing import Any, cast

from src.app.plugin_system.api.service_api import get_service
from src.app.plugin_system.base import BaseEventHandler
from src.core.components.types import EventType
from src.core.models.message import Message
from src.kernel.event import EventDecision

from .service import GoodnightService


class GoodnightEventHandler(BaseEventHandler):
    """监听群消息并触发熬夜劝导。"""

    handler_name = "goodnight_event_handler"
    handler_description = "监听白名单群聊中白名单用户的熬夜发言并进行劝导"
    weight = 0
    intercept_message = False
    init_subscribe = [EventType.ON_MESSAGE_RECEIVED]

    async def execute(self, event_name: str, params: dict[str, Any]) -> tuple[EventDecision, dict[str, Any]]:
        """处理消息接收事件。"""

        if event_name != EventType.ON_MESSAGE_RECEIVED:
            return EventDecision.PASS, params

        message = cast(Message | None, params.get("message"))
        if message is None:
            return EventDecision.PASS, params

        service = get_service("goodnight_plugin:service:goodnight_service")
        if isinstance(service, GoodnightService):
            await service.maybe_nag_user(message)

        return EventDecision.SUCCESS, params
