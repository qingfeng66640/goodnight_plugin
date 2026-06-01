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
            default="对整个群说晚安，简短自然。",
            description="主动晚安要求，默认以氛围提醒形式注入 default_chatter，不会由本插件单独发送群消息。",
        )
        nag_instruction: str = Field(
            default="用户已经过了该睡觉的时间仍在群里发言，请劝他睡觉。",
            description="劝导文案要求，默认以氛围提醒形式注入 default_chatter，不会由本插件单独发送消息。",
        )
        angry_instruction: str = Field(
            default="多次劝导无果时，语气可以更生气、更强硬，但不要辱骂。",
            description="高等级劝导文案要求",
        )

    general: GeneralSection = Field(default_factory=GeneralSection)
    groups: GroupsSection = Field(default_factory=GroupsSection)
    users: UsersSection = Field(default_factory=UsersSection)
    prompt: PromptSection = Field(default_factory=PromptSection)
