# Action 强化层 — 改动记录

> 创建日期：2026-11-05
> 最后更新：2026-11-05（追加 camera_motion 运镜选择指引）
> 目的：在不改动官方 `action_writing_guide.md` / `ambiance_audio_writing_guide.md` / `camera_motion` 原行的前提下，
> 以附加 partial 的方式强化 `video_prompt.action` 与 `video_prompt.camera_motion` 的写作质量。

## 设计原则

1. **官方默认不变**：静态 / 低缓分镜仍按官方基调写；camera_motion 原行（`按画面内容自行选择。`）一字不动
2. **Action 分层触发**：
   - **高强度分支**（打斗 / 冲撞 / 追逐 / 奔跑 / 激烈情绪爆发）→ 节拍拆解、景别匹配、强物理动词
   - **低强度丰富化分支**（慢节奏但有画面潜力：拉抽屉、点灯、翻纸、注水、擦拭）→ 微动多层、质感感官锚定、环境同框、景别匹配
3. **camera_motion 通用选择**：每个分镜主动选最匹配叙事功能的运镜值，Static 非默认回退；相邻分镜运镜应有变化
4. **Ambiance_Audio 只配合**：与 Action 节拍同步，不独立强化
5. **不偏离原著**：只细化已定稿事件，不新增情节 / 人物 / 物件

## 改动文件清单

| 文件 | 改动类型 | 说明 |
|---|---|---|
| `lib/prompts/prompt_templates/templates/partials/shared/action_reinforce.md` | 新增 | Action 强化层主体（官方指引之上叠加） |
| `lib/prompts/prompt_templates/templates/partials/shared/camera_motion_writing_guide.md` | 新增 | camera_motion 运镜选择决策指引（通用，不限场景类型） |
| `lib/prompts/prompt_templates/templates/text/drama_prompt_authoring.md` | +2 行 | 引用 action_reinforce + camera_motion_writing_guide |
| `lib/prompts/prompt_templates/templates/text/narration_prompt_authoring.md` | +2 行 | 同上 |
| `lib/prompts/prompt_templates/templates/text/ad_storyboard_prompt_authoring.md` | +2 行 | 同上 |
| `lib/prompts/prompt_templates/templates/text/ad_storyboard_script.md` | +2 行 | 同上 |
| `lib/prompts/prompt_templates/templates/text/ad_reference_video_prompt_authoring.md` | +2 行 | 同上 |
| `lib/prompts/prompt_templates/templates/text/ad_reference_video_script.md` | +2 行 | 同上 |
| `agent_runtime_profile/CLAUDE.drama.md` | +2 行 bullet | Agent 编辑剧本时同口径（Action + camera_motion） |

## 触发条件（LLM 自行判断）

模板引擎不支持场景条件 `{% if %}`，由 LLM 在 prompt_authoring 时按分镜内容自行判断：

**Action 强化层**：
- 分镜核心事件为打斗 / 冲撞 / 追逐 / 奔跑 / 激烈情绪爆发 → 启用**高强度分支**
- 分镜为慢节奏 / 细微动作但有画面潜力（拉抽屉、点灯、翻书、注水、擦物）→ 启用**低强度丰富化分支**
- 纯静态对话 / 无动作事件 → 不启用，按官方基调写

**camera_motion 运镜选择**（通用，每个分镜都适用）：
- 按叙事功能选值：推进 / 拉出 / 跟拍 / 环绕 / 横向平移 / 垂直升降 / 摇晃 / 固定机位
- 时长匹配：5s 单次运动、8s+ 可跟拍/环绕/拉出、12s+ 可节奏变化
- 相邻分镜变化：连续 3 个以上不应全同一运镜
- 硬约束：只从 schema 14 枚举值选、一个分镜一个值、运镜不写进 action

## 测试验证

- `uv run python -m pytest tests/unit/lib/prompts/ -q -p no:timeout` → 348 passed
- 枚举罗列守卫（`test_no_enum_listing` / `test_drama_no_enum_dump_in_prompt`）→ 通过
- 渲染顺序验证：action_guide → action_reinforce → camera_motion_writing_guide → ambiance → 创作目标
- 官方 `action_writing_guide.md`、`ambiance_audio_writing_guide.md`、camera_motion 原行均未改动

## 上游 rebase 策略

- 官方指引文件零改动 → 无冲突
- camera_motion 原行（`按画面内容自行选择。`）一字不动 → 无冲突
- 6 个模板各 +2 行（action_reinforce + camera_motion_writing_guide）→ rebase 时冲突面 = 6 个文件各 2 行上下文
- 新 partial 文件为纯新增 → 无冲突
- 若上游模板重构（如改行号/结构），只需重新插入 2 行引用

## 回滚方法

1. 删除 `lib/prompts/prompt_templates/templates/partials/shared/action_reinforce.md`
2. 删除 `lib/prompts/prompt_templates/templates/partials/shared/camera_motion_writing_guide.md`
3. 从 6 个模板中删除 `{{ partial("shared/action_reinforce") }}` 和 `{{ partial("shared/camera_motion_writing_guide") }}` 行
4. 从 `agent_runtime_profile/CLAUDE.drama.md` 删除对应 2 条 bullet
