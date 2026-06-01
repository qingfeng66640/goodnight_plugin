"""说晚安插件配置。"""

from __future__ import annotations

from typing import ClassVar

from src.app.plugin_system.base import BaseConfig, Field, SectionBase, config_section


class GoodnightConfig(BaseConfig):
    """说晚安插件配置。"""

    config_name: ClassVar[str] = "config"
    config_description: ClassVar[str] = "说晚安插件配置"

    @config_section("general")
    class GeneralSection(SectionBase):
        """通用配置。"""

        enabled: bool = Field(default=True, description="是否启用插件")
        timezone: str = Field(default="Asia/Shanghai", description="时区名称")
        goodnight_time: str = Field(default="23:30", description="每天主动道晚安时间，格式 HH:MM")
        goodnight_window_minutes: int = Field(default=30, description="主动晚安氛围提醒的触发时间窗口，单位分钟")
        goodnight_reminder_ttl_minutes: int = Field(default=30, description="主动晚安氛围提醒注入 default_chatter 的保留时间，单位分钟")
        nag_delay_minutes: int = Field(default=30, description="晚安时间后多少分钟开始劝导")
        nag_cooldown_minutes: int = Field(default=20, description="同一用户同一群氛围提醒冷却时间")
        nag_reminder_ttl_minutes: int = Field(default=10, description="熬夜氛围提醒注入 default_chatter 的保留时间，单位分钟")
        max_nag_level: int = Field(default=3, description="最高劝导等级")
        tick_interval_seconds: int = Field(default=60, description="定时检查间隔，单位秒")

    @config_section("groups")
    class GroupsSection(SectionBase):
        """群聊白名单配置。"""

        goodnight_group_whitelist: list[str] = Field(
            default_factory=list,
            description="允许主动道晚安的群聊白名单。格式为 '平台:群号'，例如 ['qq:123456']；到晚安时间后，插件会对这些群整体说晚安。",
        )
        nag_group_whitelist: list[str] = Field(
            default_factory=list,
            description="允许熬夜劝导的群聊白名单。格式为 '平台:群号'，例如 ['qq:123456']；只有名单内群聊中，白名单用户熬夜发言才会触发劝导。",
        )

    @config_section("users")
    class UsersSection(SectionBase):
        """用户名单配置。"""

        nag_user_whitelist: list[str] = Field(default_factory=list, description="允许劝导的用户白名单")
        nag_user_blacklist: list[str] = Field(default_factory=list, description="禁止劝导的用户黑名单")

    @config_section("prompt")
    class PromptSection(SectionBase):
        """文案提示词配置。"""

        persona_hint: str = Field(
            default="符合当前 bot 人设，自然，不要像系统通知。",
            description="人设提示",
        )
        goodnight_instruction: str = Field(
            default=(
                "现在已经到晚上休息时间了。请在不打断当前话题的前提下，"
                "自然地对群里的大家说晚安，语气要像日常聊天中的顺口关心；"
                "可以提醒大家早点休息、别熬太晚，但不要像定时任务、系统通知或公告。"
            ),
            description="主动晚安要求，默认以氛围提醒形式注入 default_chatter，不会由本插件单独发送群消息。",
        )
        nag_instruction: str = Field(
            default=(
                "目标用户已经过了设定的晚安时间仍在群里发言。请在正常回复时顺带关心他，"
                "明确劝他早点睡觉、不要继续熬夜；语气应贴合当前 bot 人设和聊天上下文，"
                "可以带一点熟人式吐槽或担心，但不要生硬点名训话，也不要另起一条像机器人提醒的通知。"
            ),
            description="劝导文案要求，默认以氛围提醒形式注入 default_chatter，不会由本插件单独发送消息。",
        )
        angry_instruction: str = Field(
            default=(
                "如果同一用户今晚已经被多次劝导仍继续熬夜，语气可以逐步变得更认真、更强硬，"
                "表现出担心和一点生气，例如催他立刻去睡、别再嘴硬或拖延；"
                "但不要辱骂、人身攻击、威胁，也不要破坏 bot 原本人设。"
            ),
            description="高等级劝导文案要求",
        )

    general: GeneralSection = Field(default_factory=GeneralSection)
    groups: GroupsSection = Field(default_factory=GroupsSection)
    users: UsersSection = Field(default_factory=UsersSection)
    prompt: PromptSection = Field(default_factory=PromptSection)
