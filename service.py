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
_last_goodnight_content: str = ""
_last_sleep_content: str = ""


class GoodnightService(BaseService):
    """说晚安与熬夜劝导服务。"""

    service_name: str = "goodnight_service"
    service_description: str = "主动对群聊说晚安，并对熬夜发言的白名单用户进行分级劝导"
    version: str = "1.0.0"

    async def send_due_goodnights(self) -> None:
        """向 default_chatter 注入到点晚安的群聊氛围提醒。"""

        cfg = self._config()
        if not cfg.general.enabled:
            self.clear_goodnight_reminder()
            self.clear_sleep_reminder()
            return

        sleep_period = self._get_active_sleep_period(cfg)
        if sleep_period is None:
            await self.sync_goodnight_reminder()
            await self.sync_sleep_reminder()
            return

        # 以睡眠时段起点的日期作为当天标识（跨天场景下用 sleep 所在日期）
        today = sleep_period.date().isoformat()
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
        sleep_period = self._get_active_sleep_period(cfg)
        if sleep_period is None:
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
        content = "\n".join(lines)

        global _last_goodnight_content
        if content == _last_goodnight_content:
            return
        _last_goodnight_content = content

        get_system_reminder_store().set(
            _ACTOR_BUCKET,
            _GOODNIGHT_REMINDER_NAME,
            content,
        )
        logger.info(
            "已向 default_chatter 注入主动晚安氛围提醒: "
            f"bucket={_ACTOR_BUCKET} name={_GOODNIGHT_REMINDER_NAME} "
            f"active_groups={len(active_items)} shown_groups={', '.join(groups)}"
        )

    def clear_goodnight_reminder(self) -> None:
        """清除 actor 中的主动晚安氛围提醒。"""

        global _last_goodnight_content
        _last_goodnight_content = ""
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
        content = "\n".join(lines)

        global _last_sleep_content
        if content == _last_sleep_content:
            return
        _last_sleep_content = content

        get_system_reminder_store().set(
            _ACTOR_BUCKET,
            _SLEEP_REMINDER_NAME,
            content,
        )
        users = ", ".join(str(item.get("user_name") or item.get("user_id") or "某用户") for item in active_items[:5])
        logger.info(
            "已向 default_chatter 注入熬夜氛围提醒: "
            f"bucket={_ACTOR_BUCKET} name={_SLEEP_REMINDER_NAME} "
            f"active_users={len(active_items)} shown_users={users}"
        )

    def clear_sleep_reminder(self) -> None:
        """清除 actor 中的熬夜氛围提醒。"""

        global _last_sleep_content
        _last_sleep_content = ""
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

    def _sleep_datetime(self, cfg: GoodnightConfig) -> datetime | None:
        """返回"今天"的睡觉时间。"""

        try:
            hour, minute = cfg.general.sleep_time.split(":", 1)
            now = self._now(cfg)
            return now.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
        except ValueError:
            logger.warning(f"睡觉时间格式无效: {cfg.general.sleep_time}")
            return None

    def _wake_datetime(self, cfg: GoodnightConfig, sleep_dt: datetime) -> datetime:
        """返回 sleep_dt 之后的下一个起床时间。

        若 wake_time 的 HH:MM > sleep_time 的 HH:MM → 同一天；
        若 wake_time 的 HH:MM <= sleep_time 的 HH:MM → 次日（常规跨天场景）。
        """

        try:
            wh, wm = cfg.general.wake_time.split(":", 1)
        except ValueError:
            logger.warning(f"起床时间格式无效: {cfg.general.wake_time}")
            return sleep_dt + timedelta(hours=8)  # 兜底：8 小时后

        wake_same_day = sleep_dt.replace(hour=int(wh), minute=int(wm), second=0, microsecond=0)
        if wake_same_day > sleep_dt:
            return wake_same_day
        return wake_same_day + timedelta(days=1)

    def _get_active_sleep_period(self, cfg: GoodnightConfig) -> datetime | None:
        """如果当前处于睡眠时段内，返回该时段的起点；否则返回 None。

        先检查今天的 sleep→wake 区间，再回退检查昨天的 sleep→wake 区间，
        涵盖跨天延续（如 sleep=23:30, wake=07:00，凌晨 01:00 仍在昨晚的时段内）。
        """

        sleep_dt = self._sleep_datetime(cfg)
        if sleep_dt is None:
            return None
        now = self._now(cfg)
        wake_dt = self._wake_datetime(cfg, sleep_dt)
        if sleep_dt <= now < wake_dt:
            return sleep_dt
        # 昨天的时段可能延续到今天
        yesterday_sleep = sleep_dt - timedelta(days=1)
        yesterday_wake = self._wake_datetime(cfg, yesterday_sleep)
        if yesterday_sleep <= now < yesterday_wake:
            return yesterday_sleep
        return None

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
