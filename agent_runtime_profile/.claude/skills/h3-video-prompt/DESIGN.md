# h3-video-prompt 设计文档（精简版）

## 目标

ArcReel 负责「小说 → 剧集 → 剧本 → 资产（角色/场景/道具 sheet 图）→ step1 单元拆分
（unit + 时长 + 台词）」。本 skill 在**工作流侧**把 reference_video 剧集的 unit 组装为
MiniMax H3 Ref2VA 六段式提示词（`references/ref-en.txt` 为权威格式），并产出
**参考图连线清单**，供用户把提示词复制进自建 ComfyUI + MiniMax 工作流、按编号加载参考图。

- 纯新增文件，不改 ArcReel 源码；H3 文本不进剧本字段（Pydantic 拒绝 / 书写语法解析器拆坏）。
- storyboard（I2VA）项目不适用本工具：脚本 fail-loud 拒绝，需按 `references/base-en.txt`
  在工作流侧手动组装。

## 数据源（单源：step1_reference_units.json，零硬编码）

| 信息 | 所在位置 | 组装角色 |
|---|---|---|
| unit 结构（unit_id / duration_seconds / references / shots / source_text） | `drafts/episode_{N}/step1_reference_units.json` | 唯一真相：unit 拆分 / 时长 / `references[]`（`<Picture N>` 前部编号）/ 书写层 `shots`（画面 + `{台词}` + `@[名称]`） |
| 资产描述 / sheet 图路径 / 风格 | `project.json`（description + character_sheet / scene_sheet / prop_sheet + style） | subject_definitions 特征 + 连线清单文件路径 + 直出风格句 |
| 原文（人名线索） | `source/` 目录 | refs / characters.md 的原文线索 |

**不读取** `step1_normalized_script.json` 与 `scripts/episode_{N}.json`（旧版路径，新版不产出）；剧本仅用于 storyboard 模式检测（顶层 `scenes[]` 存在则 fail-loud）。

unit 数量、id 命名全部运行时读取，工具内无 id 字面量。

## 组装规则

- **参考图集合** = `references[]`（原序）∪ 台词说话人（有 sheet）∪ shots `@[名称]` 引用
  （有 sheet）∪ 画面文本提及的资产名（有 sheet）；`--max-refs 8` 上限，超出按优先级
  （references > 说话人 > `@[名称]` > 画面提及）截断并 warning（列出被截断资产）。
  `<Picture N>` 编号 = 该集合顺序；无 sheet 的资产不建 subject（防悬空标签），由文字描述
  兜底（refs md 标注 + characters.md 画像）。
- **参考图引用显示**：`--ref-format atfile`（默认）→ `@文件名.png`（basename，ComfyUI
  常用，无图降级 `@<名称>.png`）；`picture` → `<Picture N>`（H3 官方格式）。`detailed_description`
  一律用 `<Subject N>` 文本标签、不嵌 `@file`（避免工作流把引用解析成角色发声）。
- 台词/旁白：从 `shots[].text` 的 `{台词}` 块逐字提取进 `<d>[语言]`——语言标签读
  project.json `source_language`（`--language` 可覆盖）；`名字：{台词}` 绑 `<Subject N> (Sx)`，
  裸 `{台词}` 给裸 `(Sx)`（不猜说话人，避免张冠李戴）；`旁白/画外音：` 前缀用官方
  voiceover 措辞 + 嘴唇闭合声明；**逐字保留原始语言**（中文/日语/英语均可）；**全保留不
  裁剪**，量超时长容量自动拆分（shot 级贪心，不切断台词）或 warning。
- detailed_description：镜头画面用 `shots[].text`（剔除 `@[名称]` 与 `{台词}` 机器语法）；
  **运镜/构图不写入**——直出由视频模型自主，润色由 LLM 按 ref-en.txt 编排。
- `summary` / `retention_analysis` / `overall_soundscape` / `non_diegetic_music`：
  直出路径用模板（见下），润色路径由 LLM 补写。

## 两条产出路径（token 分层）

1. **中文直出（`--raw`）**：脚本确定性组装，零 LLM 调用——summary / retention 用模板、
   detailed_description 保持中文正文（MiniMax H3 实际可吃中文），产出即 ComfyUI 可用。
2. **标准 ref-en.txt 骨架（`--std`）**：subject/summary/retention/声音段英文模板，画面内容
   中文 + `(refine: translate to English)` 占位——需要英语成品时按 refine-prompt.txt
   **只润色画面内容**（输入裁剪到 refs 提炼、按 unit 小批、`check_h3_format --compare` 拦
   截删台词），省 token。

两版共用同一参考图集合与 `refs/*.refs.md` 连线清单；脚本**默认双版本**（`--no-raw`/`--no-std` 可关）。

## 骨架/成品独立存档 + 连线清单

- 骨架落盘 `h3_prompts/episode_{N}/skeleton/E1Uxx[.pN].txt`（只读留档）；成品写主目录
  `h3_prompts/episode_{N}/E1Uxx[.pN].txt`，永不覆盖骨架；`diff` 对比润色前后。
- 同批产出：
  - `refs/E1Uxx.refs.md` — **ComfyUI 连线清单**：`<Picture N>` 编号 ↔ 名称/类型 ↔ 文件路径
    ↔ 主体提示（路径取 project.json 的 sheet 字段、提示取 description 全文），用户照单把
    图加载进工作流参考图槽位；
  - `refs/E1Uxx[.pN].md` — 声音绑定（说话人 → `<Subject N>` / 无图）+ 无参考图说话人（含原文线索），绑定引用 `.refs.md`；
  - `characters.md` — 全剧有台词但无参考图的说话人总表（跨 unit 去重、疑似关联标注）。
- 两份各自可跑 `check_h3_format --text` 校验（骨架应零违约、成品须零违约）。

## 运镜构图（自动生成，不写死）

组装工具不重造运镜、不接 LLM API：镜头画面只给「内容」（step1 书写层清洗后的中文描述），
运镜/构图/景别一律不写入——直出路径由视频模型自主发挥，润色路径由 LLM 按 ref-en.txt 的
摄像机规则自主编排（详见 refine-prompt.txt）。

## 触发条件

仅当用户声明「本项目 video_prompt 用 H3 格式」或「自建 ComfyUI minimax 工作流需要 H3
格式 prompt」时启用；未声明不读本 skill，ArcReel 行为与现状一致。
