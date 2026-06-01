# Goodnight Plugin

一个给 Neo-MoFox 使用的“自然晚安”插件。

它不会生硬地单独插话，而是把“该说晚安了”“这个用户又熬夜了”这类信息注入到 `default_chatter` 的氛围提示里，让 bot 在正常聊天回复中自然地顺带关心大家休息。

## 功能

- 到达设定的晚安时间后，对指定群聊注入“可以自然说晚安”的氛围提醒。
- 晚安时间后，白名单用户在白名单群聊继续发言时，注入“可以顺带劝睡”的氛围提醒。
- 支持劝导次数累计：同一晚同一群同一用户多次熬夜发言时，提醒语气会逐步从温柔变得更认真。
- 支持冷却时间，避免频繁重复提醒。
- 支持提醒过期时间，避免长期污染 `default_chatter` 的上下文。
- 主动晚安和熬夜劝导都不会由插件直接发送消息，而是交给 `default_chatter` 在合适的正常回复中自然表达。

## 工作方式

插件包含两种氛围提醒：

1. **主动晚安提醒**

   到达 `goodnight_time` 后，如果当前时间处于 `goodnight_window_minutes` 窗口内，插件会为 `goodnight_group_whitelist` 中的群聊注入晚安提醒。

2. **熬夜劝导提醒**

   到达 `goodnight_time + nag_delay_minutes` 后，如果 `nag_user_whitelist` 中的用户在 `nag_group_whitelist` 中的群聊发言，插件会注入劝睡提醒。

这些提醒会写入 `default_chatter` 使用的 `actor` reminder，因此 bot 只有在正常决定回复时才会自然提到晚安或劝睡。

## 配置示例

配置文件路径通常为：

```text
config/plugins/goodnight_plugin/config.toml
```

示例：

```toml
[general]
enabled = true
timezone = "Asia/Shanghai"

# 每天开始进入晚安氛围的时间，格式 HH:MM
goodnight_time = "23:30"

# 主动晚安氛围提醒的触发窗口，单位分钟
# 例如 23:30 + 30 分钟内会触发一次当天晚安提醒
goodnight_window_minutes = 30

# 主动晚安提醒注入 default_chatter 后保留多久
goodnight_reminder_ttl_minutes = 30

# 晚安时间后多少分钟开始检测熬夜发言
nag_delay_minutes = 30

# 同一用户同一群两次劝睡提醒之间的最短间隔
nag_cooldown_minutes = 20

# 熬夜劝导提醒注入 default_chatter 后保留多久
nag_reminder_ttl_minutes = 10

# 劝导语气最高等级
max_nag_level = 3

# 定时检查间隔，单位秒
tick_interval_seconds = 60

[groups]
# 允许触发主动晚安氛围提醒的群聊。
# 格式："平台:群号"
goodnight_group_whitelist = ["qq:123456"]

# 允许触发熬夜劝导氛围提醒的群聊。
# 格式："平台:群号"
nag_group_whitelist = ["qq:123456"]

[users]
# 允许被熬夜劝导的用户 ID 白名单
nag_user_whitelist = ["10001", "10002"]

# 禁止被熬夜劝导的用户 ID 黑名单，优先级高于白名单
nag_user_blacklist = []

[prompt]
persona_hint = "符合当前 bot 人设，自然，不要像系统通知。"
goodnight_instruction = "现在已经到晚上休息时间了。请在不打断当前话题的前提下，自然地对群里的大家说晚安，语气要像日常聊天中的顺口关心；可以提醒大家早点休息、别熬太晚，但不要像定时任务、系统通知或公告。"
nag_instruction = "目标用户已经过了设定的晚安时间仍在群里发言。请在正常回复时顺带关心他，明确劝他早点睡觉、不要继续熬夜；语气应贴合当前 bot 人设和聊天上下文，可以带一点熟人式吐槽或担心，但不要生硬点名训话，也不要另起一条像机器人提醒的通知。"
angry_instruction = "如果同一用户今晚已经被多次劝导仍继续熬夜，语气可以逐步变得更认真、更强硬，表现出担心和一点生气，例如催他立刻去睡、别再嘴硬或拖延；但不要辱骂、人身攻击、威胁，也不要破坏 bot 原本人设。"
```

## 群名单说明

### `goodnight_group_whitelist`

用于“主动晚安氛围提醒”。

到晚安时间后，名单内群聊会获得一条临时提示，让 bot 在正常回复时可以自然对大家说晚安。

### `nag_group_whitelist`

用于“熬夜劝导氛围提醒”。

晚安时间之后，只有这些群里的白名单用户发言，才会触发劝睡提醒。

如果希望同一个群既支持晚安，也支持劝睡，需要同时写入两个列表。

## 日志

插件会在关键节点输出日志，方便排查：

```text
已记录主动晚安氛围提醒触发: platform=qq group=123456 ttl_minutes=30
已向 default_chatter 注入主动晚安氛围提醒: bucket=actor name=goodnight_plugin_group_goodnight_hint active_groups=1 shown_groups=qq:123456
已记录熬夜氛围提醒触发: platform=qq group=123456 user=Alice count=1 ttl_minutes=10
已向 default_chatter 注入熬夜氛围提醒: bucket=actor name=goodnight_plugin_sleep_hint active_users=1 shown_users=Alice
```

## 注意事项

- 本插件依赖 `default_chatter` 使用 `actor` reminder。若使用其他 chatter，可能不会感知这些氛围提醒。
- 插件不会保证到点必定发送一条晚安消息；它的目标是“自然”，因此只在 bot 正常回复时顺带表达。
- 如果希望强制到点单独发消息，应使用独立发送模式，而不是当前的氛围提醒模式。

## 许可证

本项目基于 GPL-v3.0 许可证开源，详见 [LICENSE](./LICENSE) 文件。
