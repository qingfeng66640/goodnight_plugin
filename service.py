"""说晚安插件服务。"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.app.plugin_system.api import storage_api
from src.app.plugin_system.api.log_api import get_logger
from src.app.plugin_system.base import BaseService
from src.core.models.message import Message
from src.core.prompt import get_system_reminder_store

from .config import GoodnightConfig

logger = get_logger("goodnight_plugin.service")

_STORE_NAME = "goodnight_plugin"
_DAILY_KEY = "daily_goodnight_state"
_NAG_KEY = "nag_state"
_LOCK = asyncio.Lock()
_ACTOR_BUCKET = "actor"
_SLEEP_REMINDER_NAME = "goodnight_plugin_sleep_hint"
_GOODNIGHT_REMINDER_NAME = "goodnight_plugin_group_goodnight_hint"

_GOODNIGHT_SYNC_INTERVAL = 60
_SLEEP_SYNC_INTERVAL = 60
_last_goodnight_sync_at: float = 0
_last_sleep_sync_at: float = 0


class GoodnightService(BaseService):
    """说晚安与熬夜劝导服务。"""

    service_name: str = "goodnight_service"
    service_description: str = "主动对群聊说晚安，并对熬夜发言的白名单用户进行分级劝导"
    version: str = "1.0.0"

    async def send_due_goodnights(self) -> None:
        """向 default_chatter 注入到点晚安的群聊氛围提醒。"""

        cfg = self._config()
        if not cfg.general.enabled or not self._in_goodnight_window(cfg):
            return

        today = self._now(cfg).date().isoformat()
        now_ts = time.time()
        async with _LOCK:
            state = await self._load_dict(_DAILY_KEY)

        changed = False
        for target in cfg.groups.goodnight_group_whitelist:
            parsed = self._parse_group_target(target)
            if parsed is None:
                continue
            platform, group_id = parsed
            key = self._group_day_key(today, platform, group_id)
            if state.get(key):
                continue
            state[key] = {
                "created_at": now_ts,
                "expires_at": now_ts + max(1, int(cfg.general.goodnight_reminder_ttl_minutes)) * 60,
                "platform": platform,
                "group_id": group_id,
            }
            changed = True
            logger.info(
                "已记录主动晚安氛围提醒触发: "
                f"platform={platform} group={group_id} ttl_minutes={cfg.general.goodnight_reminder_ttl_minutes}"
            )

        if changed:
            async with _LOCK:
                await storage_api.save_json(_STORE_NAME, _DAILY_KEY, state)
            await self.sync_goodnight_reminder()

    async def maybe_nag_user(self, message: Message) -> None:
        """在用户熬夜发言时向 default_chatter 注入氛围提醒。"""

        cfg = self._config()
        if not cfg.general.enabled:
            return
        if message.chat_type != "group":
            return
        group_id = self._message_group_id(message)
        if not group_id or not self._group_allowed(cfg.groups.nag_group_whitelist, message.platform, group_id):
            return
        if not self._user_allowed(cfg, message.sender_id):
            return
        if not self._after_nag_start(cfg):
            return

        now_ts = time.time()
        today = self._now(cfg).date().isoformat()
        key = f"{today}:{message.platform}:group:{group_id}:user:{message.sender_id}"
        async with _LOCK:
            state = await self._load_dict(_NAG_KEY)
            item = state.get(key, {})
            last_nag_at = float(item.get("last_nag_at", 0) or 0)
            cooldown = max(0, int(cfg.general.nag_cooldown_minutes)) * 60
            if now_ts - last_nag_at < cooldown:
                return
            nag_count = int(item.get("nag_count", 0) or 0) + 1
            item["nag_count"] = nag_count
            item["last_nag_at"] = now_ts
            item["expires_at"] = now_ts + max(1, int(cfg.general.nag_reminder_ttl_minutes)) * 60
            item.setdefault("first_late_message_at", now_ts)
            item["platform"] = message.platform
            item["group_id"] = group_id
            item["stream_id"] = message.stream_id
            item["user_id"] = message.sender_id
            item["user_name"] = message.sender_cardname or message.sender_name or message.sender_id
            state[key] = item
            await storage_api.save_json(_STORE_NAME, _NAG_KEY, state)

        logger.info(
            "已记录熬夜氛围提醒触发: "
            f"platform={message.platform} group={group_id} user={item['user_name']} "
            f"count={nag_count} ttl_minutes={cfg.general.nag_reminder_ttl_minutes}"
        )
        await self.sync_sleep_reminder()

    async def sync_goodnight_reminder(self) -> None:
        """把当前有效的主动晚安提醒同步到 actor system reminder。"""

        cfg = self._config()
        if not cfg.general.enabled:
            self.clear_goodnight_reminder()
            return

        global _last_goodnight_sync_at
        now_ts = time.time()
        if now_ts - _last_goodnight_sync_at < _GOODNIGHT_SYNC_INTERVAL:
            return
        _last_goodnight_sync_at = now_ts

        async with _LOCK:
            state = await self._load_dict(_DAILY_KEY)
            active_items = [item for item in state.values() if float(item.get("expires_at", 0) or 0) > now_ts]

        if not active_items:
            self.clear_goodnight_reminder()
            return

        active_items.sort(key=lambda item: float(item.get("created_at", 0) or 0), reverse=True)
        groups = [f"{item.get('platform')}:{item.get('group_id')}" for item in active_items[:5]]
        lines = [
            "当前已经到晚安时间。若你本轮刚好要回复下列群聊，请把对大家说晚安作为自然的顺带关心融入回复里。",
            "不要为了晚安单独打断话题；如果语境适合，用符合人设的方式简短收束，提醒大家早点休息。",
            f"基础要求：{cfg.prompt.goodnight_instruction}",
            "适用群聊：",
        ]
        lines.extend(f"- {group}" for group in groups)

        get_system_reminder_store().set(
            _ACTOR_BUCKET,
            _GOODNIGHT_REMINDER_NAME,
            "\n".join(lines),
        )
        logger.info(
            "已向 default_chatter 注入主动晚安氛围提醒: "
            f"bucket={_ACTOR_BUCKET} name={_GOODNIGHT_REMINDER_NAME} "
            f"active_groups={len(active_items)} shown_groups={', '.join(groups)}"
        )

    def clear_goodnight_reminder(self) -> None:
        """清除 actor 中的主动晚安氛围提醒。"""

        removed = get_system_reminder_store().delete(_ACTOR_BUCKET, _GOODNIGHT_REMINDER_NAME)
        if removed:
            logger.info(
                "已清理 default_chatter 主动晚安氛围提醒: "
                f"bucket={_ACTOR_BUCKET} name={_GOODNIGHT_REMINDER_NAME}"
            )

    async def sync_sleep_reminder(self) -> None:
        """把当前有效的熬夜提醒同步到 actor system reminder。"""

        cfg = self._config()
        if not cfg.general.enabled:
            self.clear_sleep_reminder()
            return

        global _last_sleep_sync_at
        now_ts = time.time()
        if now_ts - _last_sleep_sync_at < _SLEEP_SYNC_INTERVAL:
            return
        _last_sleep_sync_at = now_ts

        async with _LOCK:
            state = await self._load_dict(_NAG_KEY)
            active_items = [item for item in state.values() if float(item.get("expires_at", 0) or 0) > now_ts]

        if not active_items:
            self.clear_sleep_reminder()
            return

        active_items.sort(key=lambda item: float(item.get("last_nag_at", 0) or 0), reverse=True)
        lines = [
            "当前处于晚安后的深夜时段。若你本轮正常回复下列用户，请把劝睡作为自然的顺带关心融入回复里，而不是另起一条生硬通知。",
            "不要强行打断正在进行的话题；如果语境适合，可以简短提醒早点睡。",
            f"基础要求：{cfg.prompt.nag_instruction}",
            f"升级要求：{cfg.prompt.angry_instruction}",
            "需要关注的用户：",
        ]
        for item in active_items[:5]:
            name = str(item.get("user_name") or item.get("user_id") or "某用户")
            nag_count = int(item.get("nag_count", 1) or 1)
            tone = "温柔一点"
            if nag_count == 2:
                tone = "稍微认真一点"
            elif nag_count >= 3:
                tone = "可以更强硬一点，但不要辱骂"
            lines.append(f"- {name}：今晚第 {nag_count} 次熬夜发言，语气建议：{tone}")

        get_system_reminder_store().set(
            _ACTOR_BUCKET,
            _SLEEP_REMINDER_NAME,
            "\n".join(lines),
        )
        users = ", ".join(str(item.get("user_name") or item.get("user_id") or "某用户") for item in active_items[:5])
        logger.info(
            "已向 default_chatter 注入熬夜氛围提醒: "
            f"bucket={_ACTOR_BUCKET} name={_SLEEP_REMINDER_NAME} "
            f"active_users={len(active_items)} shown_users={users}"
        )

    def clear_sleep_reminder(self) -> None:
        """清除 actor 中的熬夜氛围提醒。"""

        removed = get_system_reminder_store().delete(_ACTOR_BUCKET, _SLEEP_REMINDER_NAME)
        if removed:
            logger.info(
                "已清理 default_chatter 熬夜氛围提醒: "
                f"bucket={_ACTOR_BUCKET} name={_SLEEP_REMINDER_NAME}"
            )

    async def cleanup_old_state(self) -> None:
        """清理旧的每日状态并刷新氛围提醒。"""

        cfg = self._config()
        today = self._now(cfg).date()
        now_ts = time.time()
        keep_days = {(today - timedelta(days=offset)).isoformat() for offset in range(2)}
        async with _LOCK:
            daily = await self._load_dict(_DAILY_KEY)
            nag = await self._load_dict(_NAG_KEY)
            daily = {
                key: value
                for key, value in daily.items()
                if key.split(":", 1)[0] in keep_days and float(value.get("expires_at", 0) or 0) > now_ts
            }
            nag = {
                key: value
                for key, value in nag.items()
                if key.split(":", 1)[0] in keep_days and float(value.get("expires_at", 0) or 0) > now_ts
            }
            await storage_api.save_json(_STORE_NAME, _DAILY_KEY, daily)
            await storage_api.save_json(_STORE_NAME, _NAG_KEY, nag)

        await self.sync_goodnight_reminder()
        await self.sync_sleep_reminder()


    async def _load_dict(self, key: str) -> dict[str, Any]:
        """读取字典状态。"""

        data = await storage_api.load_json(_STORE_NAME, key)
        return data if isinstance(data, dict) else {}

    def _parse_group_target(self, target: str) -> tuple[str, str] | None:
        """解析 '平台:群号' 形式的群目标。"""

        value = target.strip()
        if not value:
            return None
        if ":" not in value:
            logger.warning(f"群目标格式无效: {target}")
            return None
        platform, group_id = value.split(":", 1)
        platform = platform.strip()
        group_id = group_id.strip()
        if not platform or not group_id:
            logger.warning(f"群目标格式无效: {target}")
            return None
        return platform, group_id

    def _config(self) -> GoodnightConfig:
        """获取插件配置。"""

        if isinstance(self.plugin.config, GoodnightConfig):
            return self.plugin.config
        return GoodnightConfig()

    def _now(self, cfg: GoodnightConfig) -> datetime:
        """获取配置时区下的当前时间。"""

        try:
            return datetime.now(ZoneInfo(cfg.general.timezone))
        except ZoneInfoNotFoundError:
            return datetime.now()

    def _goodnight_datetime(self, cfg: GoodnightConfig) -> datetime | None:
        """获取今天的晚安时间。"""

        try:
            hour, minute = cfg.general.goodnight_time.split(":", 1)
            now = self._now(cfg)
            return now.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
        except ValueError:
            logger.warning(f"晚安时间格式无效: {cfg.general.goodnight_time}")
            return None

    def _in_goodnight_window(self, cfg: GoodnightConfig) -> bool:
        """判断当前是否处于主动晚安窗口。"""

        start = self._goodnight_datetime(cfg)
        if start is None:
            return False
        end = start + timedelta(minutes=max(1, int(cfg.general.goodnight_window_minutes)))
        now = self._now(cfg)
        return start <= now <= end

    def _after_nag_start(self, cfg: GoodnightConfig) -> bool:
        """判断当前是否已到劝导开始时间。"""

        start = self._goodnight_datetime(cfg)
        if start is None:
            return False
        nag_start = start + timedelta(minutes=max(0, int(cfg.general.nag_delay_minutes)))
        return self._now(cfg) >= nag_start

    def _group_day_key(self, day: str, platform: str, group_id: str) -> str:
        """构造群每日状态键。"""

        return f"{day}:{platform}:group:{group_id}"

    def _group_allowed(self, targets: list[str], platform: str, group_id: str) -> bool:
        """判断群聊是否在白名单中。"""

        return any(parsed == (platform, group_id) for parsed in (self._parse_group_target(target) for target in targets))

    def _user_allowed(self, cfg: GoodnightConfig, user_id: str) -> bool:
        """判断用户是否允许被劝导。"""

        if user_id in cfg.users.nag_user_blacklist:
            return False
        return user_id in cfg.users.nag_user_whitelist

    def _message_group_id(self, message: Message) -> str:
        """从消息中提取群号。"""

        group_id = message.extra.get("group_id") or message.extra.get("target_group_id")
        if group_id:
            return str(group_id)
        raw_data = message.raw_data
        if isinstance(raw_data, dict):
            raw_group_id = raw_data.get("group_id")
            if raw_group_id:
                return str(raw_group_id)
        return ""
