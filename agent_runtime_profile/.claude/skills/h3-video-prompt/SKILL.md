---
name: h3-video-prompt
description: 把 ArcReel **reference_video** 模式剧集的单元（unit + 台词 + 参考图）组装为 MiniMax H3 Ref2VA 六段式提示词（subject_definitions / summary / retention_analysis / detailed_description / overall_soundscape / non_diegetic_music），并产出参考图连线清单（<Picture N> ↔ 文件路径 ↔ 主体提示），供复制进自建 ComfyUI + MiniMax 工作流、按编号加载参考图。storyboard 项目不适用（fail-loud）。H3 文本是工作流侧转换产物，不进剧本字段（见「结构边界」）。触发条件：用户声明本项目 video_prompt 用 H3 格式（或自建 ComfyUI minimax 工作流需要 H3 格式 prompt）。不改 ArcReel 源码。未声明时不触发。
user-invocable: false
---

# h3-video-prompt

把 MiniMax H3 的 Ref2VA 六段式约束（`references/ref-en.txt`，移植自
`MiniMax-AI/MiniMax-H3/.claude/skills/h3-prompt-writing/`）应用到 ArcReel 剧本数据上，
在**工作流侧**组装出 H3 格式提示词，供自建 ComfyUI + MiniMax 工作流消费。

本 skill 的承诺边界：**转换脚本 + 校验工具**。H3 六段式是自由文本，ArcReel 剧本里没有
字段能合法存放它（见「结构边界」）；它从剧本结构化字段取材、在工作流侧组装。
设计要点见同目录 `DESIGN.md`。

## 结构边界

**禁止**把 H3 文本写进：

| 位置 | 后果 |
|---|---|
| `scripts/episode_N.json` 的 `video_prompt` 字段 | 该字段是结构化 Pydantic 对象，写入触发校验拒绝 |
| `video_units[].shots[].text` | 机器解析的书写语法（`镜头N：`/`@[名称]`/`{}`），H3 文本会被拆坏 |
| step1 隔离草稿 `content` | 草稿只装扁平书写层产物，修改须走锁流程 |

**正确路径**：从 `drafts/episode_{N}/step1_reference_units.json` 单源组装六段式——
unit 拆分 / 时长 / `references[]` / 书写层 `shots`；台词从 `shots[].text` 的 `{台词}` 块
逐字提取进 `<d>[语言]`（`名字：{台词}` 绑 `<Subject N>`，裸 `{台词}` 给 `(Sx)` 不猜
说话人）；参考图集合 = `references[]` ∪ 台词说话人（有 sheet）∪ `@[名称]` 引用（有
sheet），`<Picture N>` 编号 = 该集合顺序；画面文本剔除 `@[]`/`{}` 机器语法，运镜/构图
不写入。可用 `scripts/unit_to_ref2va.py` 产出。storyboard 项目不适用（脚本 fail-loud
拒绝；I2VA 按 `references/base-en.txt` 在工作流侧手动组装）。

## 触发条件

仅当用户声明「本项目 video_prompt 用 H3 格式」（或其 ComfyUI minimax 工作流需要 H3 格式
prompt）时启用。未声明时不读本 skill、不做转换，ArcReel 行为与现状完全一致。

## 工作流

### Step 1: 读 step1_reference_units.json，定位目标 unit

读取 `drafts/episode_{N}/step1_reference_units.json`（每个 unit 含 `shots` /
`references[]` / `duration_seconds` / `source_text` 原文锚）。`shots[].text` 是书写层：
画面文本 + 内嵌台词语法（`名字：{台词}` 或裸 `{台词}`）+ `@[名称]` 引用。

### Step 2: 读 ref-en.txt 格式权威

`generation_mode=reference_video` → **Ref2VA 六段式**，读 `references/ref-en.txt`。
硬性记法原样保持：字段名与顺序、`[Shot N]` 时间戳两位小数毫秒且严格递增、摄像机运动三要素、
`(S1)` 稳定 ID + `<d>[Language]` 逐字台词、正文英语 / 台词保留原语言。

### Step 3: 组装（默认直出，零 LLM）

```bash
python .claude/skills/h3-video-prompt/scripts/unit_to_ref2va.py {项目名} {集号} [unit_id] \
  --out h3_prompts
```

- 省略 unit_id = 该集全部 unit；**默认双版本产出**（`--no-raw`/`--no-std` 可关）：
  - `--raw` → `E1Uxx[.pN].txt` 中文直出成品（summary/retention 模板化、detailed_description
    中文，零 LLM，MiniMax H3 可吃中文，直接粘贴 ComfyUI）
  - `--std` → `E1Uxx[.pN].en.txt` 标准 ref-en.txt 骨架（subject/summary/retention/声音段
    英文模板，画面内容中文 + `(refine: translate to English)` 占位）——需要英语成品时按
    `references/refine-prompt.txt` **只润色画面内容**（省 token）
  - 两版都用 `@文件名.png` 参考图索引 + 同一份 `refs/E1Uxx.refs.md` 连线清单
  - **直出同时写主目录**（交付位）+ `skeleton/`（留档），主目录即最新；骨架模式只写 `skeleton/`
- 同批产出 `refs/E1Uxx.refs.md`（**ComfyUI 连线清单**：`<Picture N>` ↔ 名称/类型 ↔
  文件路径 ↔ 主体提示）、`refs/E1Uxx[.pN].md`（声音绑定 + 无参考图出场人物）与
  `characters.md`（全剧无参考图人物总表）。
- 台词超容量自动拆分（`--max-unit-duration 15` / `--speech-rate 4` / `--no-split` 可调），
  产出 `E1Uxx.pN`；**数据源 = step1_reference_units.json 单源**：时长 = `duration_seconds`、
  画面 = `shots[].text`（剔除 `@[名称]` 与 `{台词}` 机器语法）、台词 = `{台词}` 块逐字进
  `<d>[语言]`（语言标签读 project.json `source_language`，`--language` 可覆盖；
  `名字：{台词}` 绑 `<Subject N>`，裸 `{台词}` 给裸 `(Sx)` 不猜说话人；`旁白/画外音：`
  用官方 voiceover 措辞 + 嘴唇闭合声明）；
  **参考图集合 = `references[]`（原序）∪ 台词说话人（有 sheet）∪ shots `@[名称]` 引用
  （有 sheet）∪ 画面文本提及的资产名（有 sheet）**；`--max-refs 8` 上限，超出按优先级截断
  并 warning；**参考图引用显示 = `@文件名.png`**（`--ref-format atfile` 默认；`picture`
  切回 `<Picture N>` H3 官方格式）；**运镜/构图不写入**——直出由视频模型自主，润色由
  LLM 按 ref-en.txt 编排。

### Step 3.5: 自动润色英文版（生成 H3 格式指令的默认动作）

用户说「生成 H3 格式」即视为要英语官方版：Step 3 产出双版本后，**agent 立即按
`references/refine-prompt.txt` 润色 `E1Uxx[.pN].en.txt`**（无需用户再发「润色」指令）：

- 只润两处：`detailed_description` 画面内容英译（含运镜编排）+ `subject_definitions` 的
  featuring 特征英译；**台词/旁白（`<d>` 内）逐字保留原始语言**（中文/日语/英语均可，
  语言标签按实际）；summary/retention/声音段脚本模板不动
- 润色成品写回主目录 `E1Uxx[.pN].en.txt`（不覆盖 `skeleton/`），交付 = **中文直出 +
  英文官方版**两版
- 润色后跑校验：`check_h3_format --text "<成品>" --ref-count … --refs-from … --compare "…/skeleton/E1Uxx.en.txt"`

### Step 4: 校验

```bash
python .claude/skills/h3-video-prompt/scripts/check_h3_format.py --text "<六段式文本>" \
  --ref-count <references 数> --refs-from h3_prompts/episode_{N}/refs/E1Uxx.refs.md
```

`--ref-count` 取该 unit 参考图数：`grep -c '^| <Picture' h3_prompts/episode_{N}/refs/E1Uxx.refs.md`
（连线清单的图行数，避免手填与参考图集合结果不一致）；`--refs-from` 校验 `@file` 引用
文件名都在连线清单内（拦截错位/悬空）。
退出码 0 通过；1 有 error（字段缺失/顺序、标签悬空或越界、`<d>` 不成对、时间戳非法、
@file 错位）；2 仅用法错误。error 全清才交付。

### Step 5: 交付

`--raw` 直出已把成品写入主目录 `h3_prompts/episode_{N}/E1Uxx[.pN].txt`（交付位，与
`skeleton/` 留档同内容）；骨架模式需把润色成品写入主目录（不覆盖 `skeleton/`）。
交付时说明：按 `refs/E1Uxx.refs.md` 的连线清单在 ComfyUI 里把 `<Picture N>` 编号对应的图
文件加载进参考图槽位（`@文件名.png` 引用与清单一一对应，主体提示帮助确认加载的图）。

## 可选：LLM 润色为英语成品（需要更高质量时才做）

直出即可用；若用户要求英语正文或更精细的运镜/音景，按 `references/refine-prompt.txt`
把骨架润色为英语成品——输入已裁剪到 `refs/` 提炼文件（几 KB），**按 unit 小批进行**，
润色后必须跑校验并带 `--compare` 骨架（拦截删台词）：

```bash
python .claude/skills/h3-video-prompt/scripts/check_h3_format.py --text "<成品>" \
  --ref-count <references 数> --compare "h3_prompts/episode_{N}/skeleton/E1Uxx[.pN].txt"
```

## 边界

- 只产出/校验 H3 文本；不改 ArcReel 源码、不改剧本/草稿文件（组装与校验均为只读）。
- 部署环境（Docker `/app/...`）需重新同步 `agent_runtime_profile/.claude/skills/` 后修订才生效。
