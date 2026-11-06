# 漏写 `@[名称]` 警告检查 — 改动记录

> 创建日期：2026-11-05
> 目的：分镜画面描述里出现了已登记且已写进该分镜引用字段的名字，却没有用 `@[名称]` 指认时，
> 渲染层只把裸名原样发送、资产图不参与「图N」编号，此前这条漏写是静默的（既有守卫只检查
> 反方向：写了 `@[名称]` 却没绑定）。本次以新增检查模块的方式把它收成 warning，**只提示、不改写**。

## 设计原则

1. **只提示、不修改**：不往 `image_prompt.scene` 补写 `@[名称]`，渲染出口
   （`render_storyboard_image_prompt` / `normalize_video_prompt`）行为一字不变
2. **判定口径三条缺一不可**：名字同时满足「已登记为资产 + 已写进该条目引用字段 + 正文裸写」
   才告警——正文偶发提到一个没进引用字段的名字（背景里一闪而过）不算漏写，不报，避免误报
3. **与既有守卫同形**：产出 `{"key", "params"}` 警告，与 `storyboard_warn_mention_unbound`
   同表、同挂载点、同回执通道（写剧本工具随回执返回，Agent / 用户自行决定补写）
4. **官方指引、模板零改动**：`image_prompt_writing_guide.md` 等官方文件一字未动

## 改动文件清单

| 文件 | 改动类型 | 说明 |
|---|---|---|
| `lib/script/storyboard_plain_name_check.py` | 新增 | 漏写检查主体：`find_plain_asset_mentions(script, catalog, *, unit_ids)` |
| `lib/script/storyboard_mentions.py` | +2 行 | import + `warnings.extend(...)` 挂载，复用已构建的 catalog |
| `lib/i18n/zh/errors.py` | +1 条 | `storyboard_warn_plain_asset_name` 中文文案 |
| `lib/i18n/en/errors.py` | +1 条 | 英文文案 |
| `lib/i18n/vi/errors.py` | +1 条 | 越南文文案 |
| `tests/unit/lib/script/test_storyboard_mentions.py` | +8 用例 | `TestPlainAssetNameWarnings` |

## 判定口径

- `scene` 文本先经 `render_mentions(text, lambda _name: "")` 去掉全部 `@[名称]` 记号，剩下的才是裸写
- 裸名命中 `_declared_names(item)`（引用字段声明名，比对坐标系）且 `catalog.resolve(name)` 非空才报
- 条目内按引用字段声明顺序去重（`sorted` 稳定输出），条目间按剧本顺序
- `unit_ids` 给定时只查这些条目（写工具只对本次改动的条目负责）；参考生视频骨架返回空

## 测试验证

- `uv run python -m pytest tests/unit/lib/script/test_storyboard_mentions.py -q -p no:timeout` → 16 passed
  （新增 8：裸名+已登记+已声明→报、`@[]` 写法→不报、未进引用字段→不报、已登记未声明→不报、
  文本形态、`unit_ids` 限定、参考生视频、i18n 渲染；既有 8 无回归）
- 端到端探针：`storyboard_mention_warnings` → `render_storyboard_mention_warnings` 渲染出
  「分镜 E1S01 的画面描述出现了 黑市，它已登记为资产且已写进该分镜的引用字段，但没有用 @[黑市] 指认：不会编号为图N，将按名字原样发送」

## 上游 rebase 策略

- 官方指引、模板、渲染出口零改动 → 无冲突
- `storyboard_mentions.py` 的挂载只有 2 行（import + `warnings.extend`）→ 冲突面极小
- 新文件与 i18n 条目为纯新增 → 无冲突
- 若上游重构 `storyboard_mention_warnings`，只需把 `warnings.extend(...)` 一行挪到新出口

## 回滚方法

1. 删除 `lib/script/storyboard_plain_name_check.py`
2. 从 `lib/script/storyboard_mentions.py` 删除 import 与 `warnings.extend(...)` 行
3. 从 `lib/i18n/zh|en|vi/errors.py` 删除 `storyboard_warn_plain_asset_name` 条目
4. 从 `tests/unit/lib/script/test_storyboard_mentions.py` 删除 `TestPlainAssetNameWarnings` 类
