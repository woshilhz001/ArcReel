"""把 reference_video 剧集（新版 step1 数据）的 unit 组装为 H3 Ref2VA 六段式文本。

数据源**单源**：``drafts/episode_{N}/step1_reference_units.json``（零硬编码、只消费
ArcReel 自动分析产物，见 `DESIGN.md`）：

- ``unit_id`` / ``duration_seconds`` / ``references`` / ``source_text``：unit 拆分、时长、
  参考图（``references[]`` 顺序即 ``<Picture N>`` 前部编号）
- ``shots[].text``：书写层——画面文本 + 内嵌台词语法（``名字：{台词}`` 或裸 ``{台词}``），
  含 ``@[名称]`` 引用；脚本解析台词进 ``<d>[Chinese]``、剔除 ``@[]``/``{}`` 机器语法

不读取 ``step1_normalized_script.json`` / ``scripts/episode_{N}.json``（旧版路径，新版
不产出）；剧本仅用于 storyboard 模式检测（顶层 ``scenes[]`` 存在则 fail-loud）。

参考图集合 = ``references``（原序）∪ 台词说话人（有 sheet）∪ shots ``@[名称]`` 引用
（有 sheet）；``--max-refs`` 上限，超出按优先级截断并 warning。

用法:
    python unit_to_ref2va.py <项目名> <集号> [unit_id]
        [--language Chinese] [--out <目录>] [--repo-root <ArcReel 根>]
        [--raw] [--max-refs <张>] [--max-unit-duration <秒>] [--speech-rate <字/秒>] [--no-split]

- unit_id：省略 = 转换该集全部 unit
- --language：台词 ``<d>[语言]`` 的语言标签，默认 ``Chinese``
- --out：输出目录，骨架/直出落盘为 ``<out>/episode_{N}/skeleton/<unit_id>.txt``
  （骨架独立目录；润色成品写主目录 ``<out>/episode_{N}/<unit_id>.txt``，不覆盖骨架）；
  同批产出 ``<out>/episode_{N}/refs/<unit_id>.md``（声音绑定 + 无参考图说话人）、
  ``<out>/episode_{N}/refs/<unit_id>.refs.md``（ComfyUI 参考图连线清单：<Picture N> 编号 ↔
  资产名称/类型 ↔ 文件路径 ↔ 主体提示，照单加载参考图）与
  ``<out>/episode_{N}/characters.md``（全剧有台词但无参考图的说话人总表）
- --raw：直出模式——summary/retention 模板化、detailed_description 保持中文，产出即
  ComfyUI 可用成品（零 LLM，MiniMax H3 可吃中文）；不传 = 骨架（占位待润色）
- --max-refs：每 unit 参考图数量上限（默认 8）；参考图集合 = references（原序）∪ 说话人
  ∪ ``@[名称]`` 引用，按优先级截断
- --repo-root：ArcReel 仓库根（含 ``lib/``），缺省从脚本位置自动上溯
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# project.json 资产 sheet 图路径字段（按 ref type 映射）
_SHEET_FIELD = {"character": "character_sheet", "scene": "scene_sheet", "prop": "prop_sheet"}

# 书写层机器语法：@[名称] 引用、{台词} 块
_SCRIPT_REF_RE = re.compile(r"@\[([^\]]+)\]")
_DIALOG_RE = re.compile(r"\{([^}]*)\}")
_SPEAKER_REF_RE = re.compile(r"^@\[([^\]]+)\]")
_SPEAKER_RAW_RE = re.compile(r"^([^：:]{1,20})[：:]$")


def _find_repo_root(script_path: Path) -> Path | None:
    """从脚本位置上溯找含 lib/ 的 ArcReel 仓库根。"""
    for parent in script_path.parents:
        if (parent / "lib").is_dir():
            return parent
    return None


def _project_root(repo_root: Path, project: str) -> Path | None:
    """在根 projects/ 与 deploy/projects/ 下探测项目目录（通用：不写死部署位置）。"""
    for base in (repo_root / "projects", repo_root / "deploy" / "projects"):
        if (base / project).is_dir():
            return base / project
    return None


def _load_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _asset_description(project: dict | None, ref_type: str, name: str) -> str:
    """从 project.json 的 characters/scenes/props 取资产描述摘要（≤80 字符）。"""
    if not project:
        return ""
    bucket = {"character": "characters", "scene": "scenes", "prop": "props"}.get(ref_type)
    if not bucket:
        return ""
    assets = project.get(bucket)
    if not isinstance(assets, dict):
        return ""
    meta = assets.get(name)
    if not isinstance(meta, dict):
        return ""
    desc = meta.get("description")
    if not isinstance(desc, str) or not desc.strip():
        return ""
    desc = desc.strip().replace("\n", " ")
    return desc if len(desc) <= 80 else desc[:77] + "..."


def _asset_sheet_path(
    project: dict | None,
    ref_type: str,
    name: str,
    assets_root: Path | None = None,
) -> str:
    """取资产 sheet 图路径（characters/xx.png 等）：project.json 字段优先，无则目录探测回退。

    目录探测：``assets_root/<bucket>/<name>.png``（图已生成但 project.json 未登记时仍可连线）。
    查不到返回空串。
    """
    if project:
        bucket = {"character": "characters", "scene": "scenes", "prop": "props"}.get(ref_type)
        if bucket:
            assets = project.get(bucket)
            if isinstance(assets, dict):
                meta = assets.get(name)
                if isinstance(meta, dict):
                    field = _SHEET_FIELD.get(ref_type)
                    if field:
                        path = meta.get(field)
                        if isinstance(path, str) and path.strip():
                            return path.strip()
    if assets_root is not None:
        bucket = {"character": "characters", "scene": "scenes", "prop": "props"}.get(ref_type)
        if bucket:
            for ext in (".png", ".jpg", ".jpeg", ".webp"):
                cand = assets_root / bucket / f"{name}{ext}"
                if cand.is_file():
                    return f"{bucket}/{name}{ext}"
    return ""


def _asset_full_description(project: dict | None, ref_type: str, name: str) -> str:
    """project.json 资产完整描述（压平换行，供直出 subject 特征/连线清单主体提示）。"""
    if not project:
        return ""
    bucket = {"character": "characters", "scene": "scenes", "prop": "props"}.get(ref_type)
    if not bucket:
        return ""
    assets = project.get(bucket)
    if not isinstance(assets, dict):
        return ""
    meta = assets.get(name)
    if not isinstance(meta, dict):
        return ""
    desc = meta.get("description")
    if not isinstance(desc, str) or not desc.strip():
        return ""
    return desc.strip().replace("\n", " ").replace("\r", " ")


def _has_sheet(project: dict | None, ref_type: str, name: str, assets_root: Path | None = None) -> bool:
    """资产有 sheet 图：project.json 登记或 assets 目录存在同名图。"""
    return bool(_asset_sheet_path(project, ref_type, name, assets_root))


def _ref_type_for_name(project: dict | None, name: str) -> str | None:
    """按名字查 project.json 找到资产类型（character/scene/prop）；找不到返回 None。"""
    if not project:
        return None
    for t, bucket in (("character", "characters"), ("scene", "scenes"), ("prop", "props")):
        assets = project.get(bucket)
        if isinstance(assets, dict) and name in assets:
            return t
    return None


def _source_raw(source_dir: Path) -> str:
    """拼接 source/ 下全部文本为原文（\x00 分隔，供人名线索上下文提取）。"""
    parts: list[str] = []
    if source_dir.is_dir():
        for path in sorted(source_dir.glob("*.txt")):
            try:
                parts.append(path.read_text(encoding="utf-8"))
            except OSError:
                continue
    return "\x00".join(parts)


def _find_source_context(source_raw: str, name: str, radius: int = 40) -> str:
    """在源文中找名字首次出现，返回前后 radius 字的上下文片段；找不到返回空串。"""
    if not name:
        return ""
    idx = source_raw.find(name)
    if idx < 0:
        return ""
    start = max(0, idx - radius)
    end = min(len(source_raw), idx + len(name) + radius)
    return source_raw[start:end].replace("\x00", " ")


def _clean_script_syntax(text: str) -> str:
    """清洗书写层机器语法：@[名称] → 名称、剔除 {台词} 块；其余原文保持。"""
    if not text:
        return ""
    text = _SCRIPT_REF_RE.sub(r"\1", text)
    text = _DIALOG_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


_ATFILE_MARK_RE = re.compile(r"@[^@\s，。：:：]+\.(?:png|jpg|jpeg|webp)")


def _annotate_assets(text: str, asset_names: list[str]) -> str:
    """画面文本中的资产名 → @名称.png（ComfyUI 自动转 <Subject N> 用）。

    - 按名称长度降序替换（避免「宁家族长」/「宁家族长书房」子串误替换）
    - 已存在的 @xxx.png 标记保护，不被二次替换
    """
    if not text or not asset_names:
        return text
    protected: dict[str, str] = {}

    def _protect(m: re.Match) -> str:
        key = f"\x00{m.group(0)}\x00"
        protected[key] = m.group(0)
        return key

    out = _ATFILE_MARK_RE.sub(_protect, text)
    for name in sorted(asset_names, key=len, reverse=True):
        if name:
            out = out.replace(name, f"@{name}.png")
    for key, val in protected.items():
        out = out.replace(key, val)
    return out


def _appearing_assets(unit: dict, project: dict | None, references: list) -> list[str]:
    """出场资产名 = references 名 ∪ 画面文本提及的 project.json 资产名（有图无图都算，标注用）。"""
    names = [str(r.get("name")) for r in references if isinstance(r, dict)]
    full_text = " ".join(str(s.get("text") or "") for s in unit.get("shots") or [])
    if isinstance(project, dict):
        for bucket in ("characters", "scenes", "props"):
            assets = project.get(bucket)
            if isinstance(assets, dict):
                for name in assets:
                    if name and name in full_text and name not in names:
                        names.append(name)
    return names


def _parse_shot(text: str) -> tuple[str, list[tuple[str | None, str]]]:
    """解析单个 shot 文本：{台词} 块提取为 (说话人, 逐字台词)，其余为画面文本。

    - ``名字：{台词}`` / ``@[名字]：{台词}`` → (名字, 台词)；裸 ``{台词}`` → (None, 台词)
      （说话人不猜，避免张冠李戴）
    - 画面文本剔除 @[名称] 与 {台词} 块；台词块的尾部文本并入画面
    """
    dialogues: list[tuple[str | None, str]] = []
    visual: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        m = _DIALOG_RE.search(line)
        if m is None:
            visual.append(_clean_script_syntax(line))
            continue
        spoken = m.group(1).strip()
        prefix = line[: m.start()].strip()
        speaker = None
        if prefix:
            mr = _SPEAKER_REF_RE.match(prefix)
            if mr:
                speaker = mr.group(1)
            else:
                mw = _SPEAKER_RAW_RE.match(prefix)
                if mw:
                    speaker = mw.group(1)
        if spoken:
            dialogues.append((speaker, spoken))
        tail = line[m.end() :].strip()
        if tail:
            visual.append(_clean_script_syntax(tail))
    return " ".join(visual), dialogues


def _shot_speech_seconds(shot: dict, speech_rate: float) -> float:
    """单个 shot 台词所需秒数（台词字数 ÷ 语速）。"""
    _, dial = _parse_shot(str(shot.get("text") or ""))
    return sum(len(t) for _, t in dial) / speech_rate if speech_rate > 0 else 0.0


def _split_shots(
    shots: list[dict],
    speech_rate: float,
    max_duration: int,
    total_duration: int,
) -> list[tuple[list[dict], int]]:
    """按台词秒数贪心切段：每段台词 ≤ max_duration，不切断台词/镜头。

    返回 [(shots 子集, 建议时长秒)]：台词段取台词秒数（≥1），无台词段按 shot 数比例
    分原时长。单 shot 台词仍超上限时保留并 warning（不切台词，需调上限）。
    """
    if not shots:
        return [(shots, int(total_duration or 0))]
    n = len(shots)
    parts: list[tuple[list[dict], float]] = []
    cur: list[dict] = []
    cur_secs = 0.0
    for s in shots:
        secs = _shot_speech_seconds(s, speech_rate)
        if cur and cur_secs + secs > max_duration:
            parts.append((cur, cur_secs))
            cur = [s]
            cur_secs = secs
        else:
            cur.append(s)
            cur_secs += secs
        if secs > max_duration:
            print(
                f"warning: 单个 shot 台词需 {secs:.0f}s 超上限 {max_duration}s，"
                "单 shot 不可再拆（不切断台词）；请调大 --max-unit-duration",
                file=sys.stderr,
            )
    if cur:
        parts.append((cur, cur_secs))
    out: list[tuple[list[dict], int]] = []
    for shots_sub, secs in parts:
        if secs > 0:
            out.append((shots_sub, max(1, round(secs))))
        else:
            frac = len(shots_sub) / n
            out.append((shots_sub, max(1, round((total_duration or 0) * frac))))
    return out


def _collect_refs(
    unit: dict,
    project: dict | None,
    max_refs: int,
    quiet: bool = False,
    assets_root: Path | None = None,
) -> list[dict]:
    """扩展参考图集合：references（原序）∪ 台词说话人（有 sheet）∪ shots @[名称] 引用（有 sheet）。

    优先级：references > 台词说话人 > @[名称] 引用；桶内按出现顺序、去重。超 max_refs
    截断并 warning（quiet=True 静默，供全剧预计算）。返回 [{type, name}, ...]。
    """
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def _add(t: str, name: str) -> None:
        key = (t, name)
        if key in seen:
            return
        seen.add(key)
        out.append({"type": t, "name": name})

    # 1. references 原序（显式声明）
    for r in unit.get("references") or []:
        t = str(r.get("type")) if isinstance(r, dict) else ""
        name = str(r.get("name")) if isinstance(r, dict) else str(r)
        if t in _SHEET_FIELD and name.strip():
            _add(t, name.strip())
        elif t not in _SHEET_FIELD and name.strip():
            # type 缺失/未知：按名字反查 bucket
            rt = _ref_type_for_name(project, name.strip())
            if rt:
                _add(rt, name.strip())

    # 2. 台词说话人（有 sheet）
    speakers: list[str] = []
    seen_sp: set[str] = set()
    for s in unit.get("shots") or []:
        _, dial = _parse_shot(str(s.get("text") or ""))
        for sp, _t in dial:
            if sp and sp.strip() and sp.strip() not in seen_sp:
                seen_sp.add(sp.strip())
                speakers.append(sp.strip())
    for sp in speakers:
        if _has_sheet(project, "character", sp, assets_root):
            _add("character", sp)

    # 3. shots @[名称] 引用（有 sheet，剩余）
    for s in unit.get("shots") or []:
        for m in _SCRIPT_REF_RE.finditer(str(s.get("text") or "")):
            name = m.group(1).strip()
            rt = _ref_type_for_name(project, name)
            if rt and _has_sheet(project, rt, name, assets_root):
                _add(rt, name)

    # 4. 画面文本提及的资产名（裸名，有 sheet，最低优先级）——出场资产都能连线
    full_text = " ".join(str(s.get("text") or "") for s in unit.get("shots") or [])
    for t, bucket in (("character", "characters"), ("scene", "scenes"), ("prop", "props")):
        assets = project.get(bucket) if isinstance(project, dict) else None
        if not isinstance(assets, dict):
            continue
        for name in assets:
            if name and name in full_text and _has_sheet(project, t, name, assets_root):
                _add(t, name)

    if max_refs > 0 and len(out) > max_refs:
        if not quiet:
            print(
                f"warning: 参考图数 {len(out)} 超上限 {max_refs}，按优先级截断为 {max_refs} 张"
                f"（被截断: {', '.join(str(r.get('name')) for r in out[max_refs:])}）",
                file=sys.stderr,
            )
        return out[:max_refs]
    return out


def _unit_refs_index(
    uid: str,
    references: list,
    project: dict | None = None,
    assets_root: Path | None = None,
) -> str:
    """unit 级参考图连线清单（ComfyUI 用）：<Picture N> 编号 ↔ 资产 ↔ 文件路径 ↔ 主体提示。

    文件路径取 project.json 的 character_sheet / scene_sheet / prop_sheet；主体提示取
    description 全文。查不到时降级为占位说明（warning 不静默）。
    """
    rows: list[str] = []
    for i, ref in enumerate(references, start=1):
        rtype = str(ref.get("type")) if isinstance(ref, dict) else "asset"
        rname = str(ref.get("name")) if isinstance(ref, dict) else str(ref)
        path = _asset_sheet_path(project, rtype, rname, assets_root)
        desc = _asset_full_description(project, rtype, rname)
        if not path:
            print(
                f"warning: {uid} <Picture {i}> {rname}（{rtype}）project.json 无 sheet 路径，"
                "连线时按名称在 assets 目录取图",
                file=sys.stderr,
            )
        if not desc:
            print(
                f"warning: {uid} <Picture {i}> {rname}（{rtype}）project.json 无 description，主体提示缺失",
                file=sys.stderr,
            )
        path_s = path or "（project.json 无 sheet 路径，按名称在 assets 目录取）"
        desc_s = desc or "（project.json 无 description，按名称/原文定位）"
        desc_s = desc_s.replace("|", "｜")
        rows.append(f"| <Picture {i}> | {rname} | {rtype} | `{path_s}` | {desc_s} |")
    lines = [
        f"# {uid} 参考图连线清单（ComfyUI）",
        "",
        "按 <Picture N> 编号顺序把下列文件加载进工作流参考图槽位；编号与 H3 文本中的",
        "<Picture N> 一一对应（subject_definitions 里 `<Subject N> is ... in <Picture N>` 同源）。",
        "文件路径取自 project.json 的 character_sheet / scene_sheet / prop_sheet。",
        "",
        "| <Picture N> | 名称 | 类型 | 文件路径 | 主体提示 |",
        "|---|---|---|---|---|",
        *rows,
        "",
    ]
    return "\n".join(lines)


def _unit_speakers(shots: list[dict]) -> list[str]:
    """该 unit/段全部有名字的说话人（按出现顺序去重）。"""
    out: list[str] = []
    seen: set[str] = set()
    for s in shots:
        _, dial = _parse_shot(str(s.get("text") or ""))
        for sp, _t in dial:
            if sp and sp.strip() and sp.strip() not in seen:
                seen.add(sp.strip())
                out.append(sp.strip())
    return out


def _unit_refs_md(
    uid: str,
    references: list,
    shots: list[dict],
    subject_of: dict[str, int],
    source_raw: str,
    index_ref: str,
) -> str:
    """unit 参考绑定：声音绑定（说话人 → <Subject N> / 无图）+ 无参考图说话人（含原文线索）。

    index_ref 给定（如 ``E1U01.refs.md``）时参考图绑定引用 ComfyUI 连线清单文件。
    """
    ref_names = {str(r.get("name")) for r in references}
    sound_lines: list[str] = []
    for sid, sp in enumerate(_unit_speakers(shots), start=1):
        if sp in subject_of:
            sound_lines.append(f"  (S{sid}) {sp} → <Subject {subject_of[sp]}>（本 unit 有参考图）")
        elif sp in ref_names:
            sound_lines.append(f"  (S{sid}) {sp} → 有参考图（其他 unit），本 unit 未引用；音色可跨 unit 复用")
        else:
            sound_lines.append(f"  (S{sid}) {sp} → 无参考图，音色由润色生成")
    # 无名字的台词条数
    unnamed = 0
    for s in shots:
        _, dial = _parse_shot(str(s.get("text") or ""))
        unnamed += sum(1 for sp, _t in dial if not sp)
    if unnamed:
        sound_lines.append(f"  （{unnamed} 条无说话人标注的台词，按 (Sx) 独立编号、不猜说话人）")
    extras: list[str] = []
    for sp in _unit_speakers(shots):
        if sp not in ref_names:
            ctx = _find_source_context(source_raw, sp)
            ctx_s = f"线索: {ctx}" if ctx else "线索: 原文未直接出现该名（由润色补）"
            extras.append(f"  - {sp} {ctx_s}")
    blocks = [
        f"# {uid} 参考绑定",
        "",
        "参考图绑定:",
        f"  见 {index_ref}（ComfyUI 连线清单：<Picture N> ↔ 文件路径 ↔ 主体提示）",
        "",
        "声音绑定:",
        *sound_lines,
        "",
        "无参考图说话人:",
        *(extras or ["  （无）"]),
        "",
    ]
    return "\n".join(blocks)


def _characters_md(
    units: list[dict],
    project: dict | None,
    source_raw: str,
    max_refs: int,
    assets_root: Path | None = None,
) -> str:
    """全剧有台词但无参考图的说话人总表：跨 unit 去重、合并出场范围与原文线索。

    完整画像（身份/外观/音色/性格）由润色 LLM 按线索与项目风格生成，每人独立不重复。
    """
    # 全剧最终参考图名集合
    final_names: set[str] = set()
    for u in units:
        for r in _collect_refs(u, project, max_refs, quiet=True, assets_root=assets_root):
            final_names.add(str(r.get("name")))
    acc: dict[str, dict] = {}
    for u in units:
        uid = str(u.get("unit_id"))
        for sp in _unit_speakers(u.get("shots") or []):
            if sp not in final_names:
                info = acc.setdefault(sp, {"units": set(), "speech": 0})
                info["units"].add(uid)
                info["speech"] += 1
    if not acc:
        return "# 无参考图说话人总表\n\n（本集全部说话人都有参考图）\n"
    char_bucket = project.get("characters") if isinstance(project, dict) else None
    lines = [
        "# 无参考图说话人总表",
        "",
        "（画像由润色 LLM 生成：身份/外观/音色/性格，基于线索与项目风格，",
        "跨 unit 去重、每人独立不重复）",
        "",
    ]
    for name, info in sorted(acc.items()):
        related = sorted(
            rn
            for rn in final_names
            if rn in name
            or name in rn
            or (len(rn) >= 2 and len(name) >= 2 and rn[:2] == name[:2])
            or (rn[-1:] == name[-1:] and len(name) >= 2)
        )
        rel_s = f"- 疑似与参考图人物相关: {related}（勿自动合并，润色时定夺）" if related else ""
        ctx = _find_source_context(source_raw, name)
        ctx_s = f"线索: {ctx}" if ctx else "线索: 原文未直接出现该名（由润色补）"
        desc = ""
        if isinstance(char_bucket, dict):
            meta = char_bucket.get(name)
            if isinstance(meta, dict) and isinstance(meta.get("description"), str) and meta["description"].strip():
                desc = f"- project description: {meta['description'].strip()}"
        lines += [
            f"## {name}",
            f"- 出场 unit: {sorted(info['units'])}",
            f"- 台词数: {info['speech']}",
            f"- {ctx_s}",
            *([desc] if desc else []),
            *([rel_s] if rel_s else []),
            "- 画像: （由润色 LLM 生成）",
            "",
        ]
    return "\n".join(lines)


def _ref_display(
    ref: dict,
    project: dict | None,
    assets_root: Path | None,
    ref_format: str,
    index: int,
) -> str:
    """参考图引用的显示形式：atfile 模式 @文件名.png（basename），picture 模式 <Picture N>。

    atfile 无图路径时降级为 ``@<名称>.png``（按名称约定文件名，用户自行放图）。
    """
    if ref_format != "atfile":
        return f"<Picture {index}>"
    rtype = str(ref.get("type")) if isinstance(ref, dict) else "asset"
    name = str(ref.get("name")) if isinstance(ref, dict) else str(ref)
    path = _asset_sheet_path(project, rtype, name, assets_root)
    if path:
        return f"@{Path(path).name}"
    return f"@{name}.png"


def _subject_lines(
    references: list,
    project: dict | None,
    raw: bool,
    assets_root: Path | None = None,
    ref_format: str = "atfile",
) -> tuple[dict[str, int], list[str]]:
    """subject_definitions 行 + 说话人→<Subject N> 映射。直出用完整 description，骨架 80 字截断。"""
    subject_of: dict[str, int] = {}
    subject_lines: list[str] = []
    for i, ref in enumerate(references, start=1):
        rtype = str(ref.get("type")) if isinstance(ref, dict) else "asset"
        name = str(ref.get("name")) if isinstance(ref, dict) else str(ref)
        subject_of[name] = i
        desc = _asset_full_description(project, rtype, name) if raw else _asset_description(project, rtype, name)
        feature = f", featuring {desc}" if desc else ""
        ref_disp = _ref_display(ref, project, assets_root, ref_format, i)
        subject_lines.append(f"<Subject {i}> is {name} in {ref_disp}{feature}.")
    return subject_of, subject_lines


# 语言代码 → <d> 语言标签（source_language → English 名）
_LANG_LABELS = {
    "zh": "Chinese",
    "ja": "Japanese",
    "en": "English",
    "ko": "Korean",
    "fr": "French",
    "de": "German",
    "ru": "Russian",
    "es": "Spanish",
    "ar": "Arabic",
    "hi": "Hindi",
    "th": "Thai",
    "vi": "Vietnamese",
    "pt": "Portuguese",
    "it": "Italian",
    "id": "Indonesian",
}

# 旁白/画外音前缀（说话人名为这些 → 官方 voiceover 措辞）
_VOICEOVER_NAMES = ("旁白", "画外音", "旁白者", "voiceover", "narrator")


def _lang_label(code: str | None) -> str | None:
    """语言代码 → <d>[Language] 标签（zh → Chinese 等）；未知返回 None。"""
    if not code:
        return None
    c = str(code).strip().lower()
    if c in _LANG_LABELS:
        return _LANG_LABELS[c]
    return None


def _dialogue_lines(
    shots: list[dict],
    language: str,
    subject_of: dict[str, int],
) -> tuple[list[str], dict[str, int]]:
    """逐 shot 解析台词 → H3 台词行；返回 (按 shot 归属的台词行, 说话人→Sx 映射)。

    对白：有名字说话人绑定 <Subject N>（在 references 中）或裸 (Sx)；无名字（None）每句
    独立新 ID（不猜说话人）。旁白/画外音（说话人为 旁白/画外音/…）：用官方 voiceover
    措辞 + 嘴唇闭合声明。台词/旁白内容逐字保留原语言（<d>[Language] 内）。返回的列表与
    shots 一一对应。
    """
    speaker_ids: dict[str, int] = {}
    next_id = 1
    per_shot: list[list[str]] = []
    for s in shots:
        _, dial = _parse_shot(str(s.get("text") or ""))
        lines: list[str] = []
        for sp, spoken in dial:
            if sp and sp.strip():
                key = sp.strip()
                if key not in speaker_ids:
                    speaker_ids[key] = next_id
                    next_id += 1
                sid = speaker_ids[key]
            else:
                sid = next_id
                next_id += 1
            subj = subject_of.get(sp.strip()) if sp else None
            who = f"<Subject {subj}> (S{sid})" if subj else f"(S{sid})"
            if sp and sp.strip().lower() in _VOICEOVER_NAMES:
                # 官方 voiceover 措辞：嘴唇闭合（base-en.txt 规范）
                lines.append(
                    f"{who} says in an off-screen voiceover, <d>[{language}] {spoken}</d>, with lips remaining closed."
                )
            else:
                lines.append(f"{who} says: <d>[{language}] {spoken}</d>")
        per_shot.append(lines)
    return per_shot, speaker_ids


def _unit_ref2va(
    unit: dict,
    language: str,
    project: dict | None,
    references: list,
    shots: list[dict],
    duration: int | None,
    raw: bool = False,
    std: bool = False,
    assets_root: Path | None = None,
    ref_format: str = "atfile",
) -> str:
    """把单个 unit（或拆分后的一段 shots）组装为六段式文本。

    数据源：step1 unit 的 shots（书写层，画面 + 内嵌 {台词}）+ references（扩展后，顺序
    即 <Picture N> 编号）+ project.json（资产描述/风格）。运镜/构图不写入（直出由视频模型
    自主，润色由 LLM 按 ref-en.txt 编排）。台词逐字全保留，量超时长容量由调用方拆分。
    参考图引用显示：atfile 模式 @文件名.png / picture 模式 <Picture N>（--ref-format）。

    raw=True：中文直出成品（风格行/声音段中文模板，零 LLM）。
    std=True：标准 ref-en.txt 骨架——subject/summary/retention/声音段英文模板，画面内容
    中文 + ``(refine: translate to English)`` 占位，供 LLM 只润色画面内容（省 token）。
    两者都 False：纯骨架（占位待整体润色，旧路径）。
    """
    unit_id = str(unit.get("unit_id") or "?")
    duration = int(duration if duration is not None else (unit.get("duration_seconds") or 0))
    subject_of, subject_block = _subject_lines(references, project, raw, assets_root, ref_format)
    per_shot_dialogue, speaker_ids = _dialogue_lines(shots, language, subject_of)

    # 画面文本（清洗 @[] 与 {台词} 块，出场资产标注 @名称.png 供 ComfyUI 关联）
    shot_texts: list[str] = []
    for s in shots:
        visual, _ = _parse_shot(str(s.get("text") or ""))
        if visual:
            shot_texts.append(visual)
    appearing = _appearing_assets(unit, project, references)
    shot_texts = [_annotate_assets(t, appearing) for t in shot_texts]
    n_frames = len(shot_texts)

    # 镜头：画面文本 + 该 shot 台词（台词天然归属本镜）
    shot_lines: list[str] = []
    for idx in range(1, n_frames + 1):
        header = f"[Shot {idx}]"
        if idx > 1 and n_frames > 1 and duration > 0:
            seconds = duration * (idx - 1) / n_frames
            mm, ss = divmod(int(seconds * 1000) // 1000, 60)
            header = f"[Shot {idx}] At {mm:02d}:{ss:02d}.{int(seconds * 1000) % 1000:03d}"
        body = shot_texts[idx - 1]
        if std:
            # 标准版：画面内容标记待英译（只润画面，台词/模板不动）
            body += " (refine: translate to English)"
        dialog_lines = per_shot_dialogue[idx - 1]
        if dialog_lines:
            body = (body + " " + " ".join(dialog_lines)) if body else " ".join(dialog_lines)
        shot_lines.append(f"{header} {body}")
    if not shot_lines:
        shot_lines.append("[Shot 1] （画面内容缺失，请补充）" if raw else "[Shot 1] (refine: shot description)")

    detail_blocks: list[str] = []
    style_s = ""
    if isinstance(project, dict):
        st = project.get("style")
        style_s = str(st).strip() if isinstance(st, str) else ""
    if raw:
        detail_blocks.append(f"风格：{style_s}。" if style_s else f"The target video uses a {unit_id} style.")
    elif std:
        detail_blocks.append(
            f"The target video uses a {style_s} style." if style_s else f"The target video uses a {unit_id} style."
        )
    else:
        detail_blocks.append(f"The target video uses a {unit_id} style. (refine: set style)")
    detail_blocks.extend(shot_lines)

    names = "、".join(str(r.get("name")) for r in references) if references else "(no references)"
    appears = ", ".join(f"[Shot {i}]" for i in range(1, len(shot_lines) + 1)) or "[Shot 1]"
    if raw:
        retention_block = [
            f"<Subject {n}> (appears in {appears}): fully_preserved - 外观与特征由 "
            f"{_ref_display(references[n - 1], project, assets_root, ref_format, n)} 参考图承担。"
            for n in range(1, len(references) + 1)
        ] or ["(no references)"]
        subject_block = subject_block or ["(no references)"]
        summary_block = f"[reference generation] The target video shows {names}."
        soundscape_block = "环境音与动作音按场景自然呈现。"
        music_block = "配乐按氛围自然生成。"
    elif std:
        retention_block = [
            f"<Subject {n}> (appears in {appears}): fully_preserved - appearance and features "
            f"carried by {_ref_display(references[n - 1], project, assets_root, ref_format, n)}."
            for n in range(1, len(references) + 1)
        ] or ["(no references)"]
        subject_block = subject_block or ["(no references)"]
        summary_block = f"[reference generation] The target video shows {names}."
        soundscape_block = "Ambient and action sounds follow the scene naturally."
        music_block = "Background score generated to fit the mood."
    else:
        retention_block = [
            f"<Subject {n}> (appears in {appears}): fully_preserved - (refine)." for n in range(1, len(references) + 1)
        ] or ["(refine)"]
        subject_block = subject_block or ["(refine: define subjects from references)"]
        summary_block = f"[reference generation] The target video shows {names}. (working draft - refine)"
        soundscape_block = "N/A"
        music_block = "N/A"

    blocks = [
        "subject_definitions:",
        *subject_block,
        "",
        "summary:",
        summary_block,
        "",
        "retention_analysis:",
        *retention_block,
        "",
        "detailed_description:",
        *detail_blocks,
        "",
        "overall_soundscape:",
        soundscape_block,
        "",
        "non_diegetic_music:",
        music_block,
    ]
    return "\n".join(blocks)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="把 reference_video 剧集 unit（新版 step1 数据）组装为 H3 Ref2VA 六段式"
    )
    parser.add_argument("project", help="项目名")
    parser.add_argument("episode", type=int, help="集号")
    parser.add_argument("unit_id", nargs="?", help="目标 unit_id（省略=该集全部 unit）")
    parser.add_argument(
        "--language",
        default=None,
        help="台词 <d>[语言] 标签（如 Chinese/Japanese/English）；缺省读 project.json 的 source_language",
    )
    parser.add_argument("--repo-root", help="ArcReel 仓库根（含 lib/），缺省自动上溯")
    parser.add_argument("--out", help="输出目录（骨架落盘 skeleton/、refs/ 同批产出），不传走 stdout")
    parser.add_argument(
        "--max-unit-duration",
        type=int,
        default=15,
        help="拆分时每段台词容量上限（秒），默认 15（按你的视频 backend/ComfyUI 上限调）",
    )
    parser.add_argument(
        "--speech-rate",
        type=float,
        default=4.0,
        help="台词语速（字/秒），默认 4，用于估算台词所需秒数",
    )
    parser.add_argument(
        "--no-split",
        action="store_true",
        help="关闭自动拆分：台词超容量时仍输出单文件（仅 warning，台词全保留）",
    )
    parser.add_argument(
        "--no-raw",
        action="store_true",
        help="不生成中文直出版（默认生成）：summary/retention 模板化、detailed_description 中文，"
        "零 LLM，MiniMax H3 可吃中文，直接粘贴 ComfyUI",
    )
    parser.add_argument(
        "--no-std",
        action="store_true",
        help="不生成标准 ref-en.txt 骨架版（默认生成）：英文模板 + 中文画面 + (refine: translate to English) 占位，"
        "供 agent 自动润色为英文官方版（Step 3.5）",
    )
    parser.add_argument(
        "--max-refs",
        type=int,
        default=8,
        help="每 unit 参考图数量上限（默认 8，按 ComfyUI 工作流参考图槽位数调）；"
        "超出按优先级截断（references > 说话人 > @[名称] 引用）",
    )
    parser.add_argument(
        "--ref-format",
        choices=("atfile", "picture"),
        default="atfile",
        help="参考图引用显示：atfile（默认，@文件名.png，ComfyUI 常用）或 picture（<Picture N>，H3 官方）",
    )
    args = parser.parse_args(argv)
    gen_raw = not args.no_raw
    gen_std = not args.no_std

    script_path = Path(__file__).resolve()
    repo_root = Path(args.repo_root).resolve() if args.repo_root else _find_repo_root(script_path)
    if repo_root is None:
        print("找不到 ArcReel 仓库根（含 lib/），请用 --repo-root 指定", file=sys.stderr)
        return 2
    proj_root = _project_root(repo_root, args.project)
    if proj_root is None:
        print(f"项目目录不存在: {args.project}（projects/ 与 deploy/projects/ 均探测）", file=sys.stderr)
        return 2
    drafts_dir = proj_root / "drafts" / f"episode_{args.episode}"

    step1 = _load_json(drafts_dir / "step1_reference_units.json")
    if not step1:
        print(f"缺少 step1_reference_units.json: {drafts_dir / 'step1_reference_units.json'}", file=sys.stderr)
        return 2
    units = step1.get("units")
    if not isinstance(units, list) or not units:
        print(f"step1 中没有 units: {drafts_dir / 'step1_reference_units.json'}", file=sys.stderr)
        return 2

    # storyboard 项目检测（剧本顶层 scenes[] 存在则非 reference_video）：fail-loud
    script_data = _load_json(proj_root / "scripts" / f"episode_{args.episode}.json")
    if isinstance(script_data, dict) and isinstance(script_data.get("scenes"), list) and script_data.get("scenes"):
        print(
            "错误: 剧本是 storyboard 模式（scenes[]），本工具仅支持 reference_video 模式"
            "（新版 step1_reference_units.json）；storyboard 的 I2VA 三段式请按 "
            "references/base-en.txt 在工作流侧手动组装",
            file=sys.stderr,
        )
        return 2

    project = _load_json(proj_root / "project.json") or {}
    language = args.language or _lang_label(project.get("source_language")) or "Chinese"
    source_raw = _source_raw(proj_root / "source")

    # 预计算每 unit 扩展后的最终参考图集合
    final_refs_by_unit: dict[str, list[dict]] = {}
    for u in units:
        uid = str(u.get("unit_id"))
        final_refs_by_unit[uid] = _collect_refs(u, project, args.max_refs, assets_root=proj_root)

    if args.unit_id:
        targets = [u for u in units if str(u.get("unit_id")) == args.unit_id]
        if not targets:
            print(f"step1 中未找到 unit_id={args.unit_id}（unit 数: {len(units)}）", file=sys.stderr)
            return 2
    else:
        targets = units

    out_dir = Path(args.out) / f"episode_{args.episode}" / "skeleton" if args.out else None
    refs_dir = Path(args.out) / f"episode_{args.episode}" / "refs" if args.out else None
    episode_dir = Path(args.out) / f"episode_{args.episode}" if args.out else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        refs_dir.mkdir(parents=True, exist_ok=True)

    def _gen_texts(p_shots: list[dict], p_dur: int | None) -> list[tuple[str, str]]:
        """产出版本列表 [(文件名后缀, 文本)]：raw → ('', 中文直出)；std → ('.en', 标准骨架)。"""
        out: list[tuple[str, str]] = []
        if gen_raw:
            out.append(
                (
                    "",
                    _unit_ref2va(
                        u,
                        language,
                        project,
                        refs,
                        p_shots,
                        p_dur,
                        raw=True,
                        assets_root=proj_root,
                        ref_format=args.ref_format,
                    ),
                )
            )
        if gen_std:
            out.append(
                (
                    ".en",
                    _unit_ref2va(
                        u,
                        language,
                        project,
                        refs,
                        p_shots,
                        p_dur,
                        std=True,
                        assets_root=proj_root,
                        ref_format=args.ref_format,
                    ),
                )
            )
        return out

    def _emit(part_uid: str, texts: list[tuple[str, str]], ref_md: str) -> None:
        if out_dir:
            for suffix, text in texts:
                (out_dir / f"{part_uid}{suffix}.txt").write_text(text, encoding="utf-8")
            (refs_dir / f"{part_uid}.md").write_text(ref_md, encoding="utf-8")
            if gen_raw or gen_std:
                # 成品/骨架均同步写主目录交付位（skeleton/ 仍留档）
                for suffix, text in texts:
                    (episode_dir / f"{part_uid}{suffix}.txt").write_text(text, encoding="utf-8")
        else:
            if len(targets) > 1 or "." in part_uid:
                print(f"# === {part_uid} ===")
            for suffix, text in texts:
                print(text)
                print()

    for u in targets:
        uid = str(u.get("unit_id"))
        duration = int(u.get("duration_seconds") or 0) or None
        refs = final_refs_by_unit.get(uid) or []
        subject_of = {str(r.get("name")): i for i, r in enumerate(refs, start=1)}
        shots = [s for s in u.get("shots") or [] if isinstance(s, dict)]
        if out_dir:
            (refs_dir / f"{uid}.refs.md").write_text(_unit_refs_index(uid, refs, project, proj_root), encoding="utf-8")
        total_speech = sum(_shot_speech_seconds(s, args.speech_rate) for s in shots)
        if (not args.no_split) and shots and total_speech > args.max_unit_duration:
            parts = _split_shots(shots, args.speech_rate, args.max_unit_duration, duration or 0)
            print(
                f"拆分: {uid} 台词需 {total_speech:.0f}s 超上限 {args.max_unit_duration}s"
                f" → {len(parts)} 段（台词全保留）",
                file=sys.stderr,
            )
            for pi, (p_shots, p_dur) in enumerate(parts, start=1):
                part_uid = f"{uid}.p{pi}"
                texts = _gen_texts(p_shots, p_dur)
                ref_md = _unit_refs_md(part_uid, refs, p_shots, subject_of, source_raw, f"{uid}.refs.md")
                _emit(part_uid, texts, ref_md)
        else:
            texts = _gen_texts(shots, duration)
            ref_md = _unit_refs_md(uid, refs, shots, subject_of, source_raw, f"{uid}.refs.md")
            _emit(uid, texts, ref_md)
    if out_dir:
        (episode_dir / "characters.md").write_text(
            _characters_md(units, project, source_raw, args.max_refs, proj_root), encoding="utf-8"
        )
        print(f"已写入骨架 + refs + characters.md 到 {episode_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
