"""H3 Ref2VA 六段式产物校验脚本（仅 r2v 模式）。

校验工作流侧组装的 H3 六段式文本：字段顺序、标签悬空/越界、时间戳、<d> 成对、
summary 前缀、retention 标记，以及**台词完整性**（--compare 骨架 / --expect-dialogues，
拦截 LLM 润色删台词）。退出码：0 = 通过；1 = 有 error；2 = 仅用法错误。

用法:
    python check_h3_format.py --text "<六段式文本>" --ref-count <references 数>
    python check_h3_format.py --text "<成品>" --compare "<骨架文件路径>"
    python check_h3_format.py --text "<成品>" --expect-dialogues 5
    python check_h3_format.py <项目名> <集号>   # 校验剧本内含 video_prompt 的条目（r2v 识别）

storyboard（I2VA 三段式）不在本脚本校验范围：storyboard 项目不走本 skill 组装路径。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# --- 常量（与 references/ref-en.txt 硬约束同步，改约束时须同步本文件） ---

# Ref2VA 六段式（顺序固定）
REF_FIELDS = (
    "subject_definitions",
    "summary",
    "retention_analysis",
    "detailed_description",
    "overall_soundscape",
    "non_diegetic_music",
)

# 切镜时间戳：At MM:SS.mmm（两位小数毫秒）
CUT_TIME_RE = re.compile(r"At (\d{2}):(\d{2})\.(\d{3})")

# 任务类型触发词（编辑/修改语义，H3 要求直接描述目标画面）。只做 warning 级提示：
# 过去式/名词形态（如 "changed"、"change of plan"）在画面描述里合法，无法用词形精确区分。
TRIGGER_WORDS_ZH = ("增加", "删除", "去掉", "修改", "替换", "改成", "延长", "续写")
TRIGGER_WORDS_EN = ("remove", "delete", "change", "replace", "extend")

# Ref2VA 的 summary 任务类型前缀
SUMMARY_PREFIX_RE = re.compile(r"^\[[a-z +]+\]")

# 引用标签：<Subject N> / <Picture N> / <Video N> / <Audio N>
LABEL_RE = re.compile(r"<(Subject|Picture|Video|Audio) (\d+)>")

# retention_analysis 关系标记
RETENTION_MARKERS = (
    "fully_preserved",
    "partially_preserved",
    "attribute_transfer",
    "weak_reference",
    "fully_copy",
    "partially_copy",
    "reference",
)

# 台词完整性：<d> 标签计数即台词条数（<d> 与 </d> 必须成对，见 check_prompt）
_DIALOGUE_RE = re.compile(r"<d>")

# @file 引用（atfile 模式，--ref-format atfile）：@文件名.png 等
_ATFILE_RE = re.compile(r"@([^@\s，。：:：]+\.(?:png|jpg|jpeg|webp))")


def _parse_refs_md(path: Path) -> set[str]:
    """从连线清单 refs/*.refs.md 解析参考图文件 basename 集合。

    占位路径（project.json 无 sheet）用名称列降级为 ``<名称>.png``（与
    unit_to_ref2va 的 atfile 降级一致）。
    """
    refs: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\| <Picture \d+> \| ([^|]*) \| [^|]* \| `([^`]*)` \|", line)
        if not m:
            continue
        name = m.group(1).strip()
        p = m.group(2).strip()
        if "/" in p:
            refs.add(p.rsplit("/", 1)[-1])
        elif p and not p.startswith("（"):
            refs.add(p)
        elif name:
            refs.add(f"{name}.png")
    return refs


def _field_order(text: str, fields: tuple[str, ...]) -> list[str]:
    """返回 fields 在 text 中按出现位置排序后的字段名；缺失字段不入列。"""
    hits = [(field, text.find(field)) for field in fields]
    hits = [(f, i) for f, i in hits if i >= 0]
    hits.sort(key=lambda x: x[1])
    return [f for f, _ in hits]


def _cut_times(text: str) -> list[tuple[int, int, int]]:
    """提取全部切镜时间戳为 (MM, SS, mmm) 元组，按出现顺序。"""
    return [(int(m.group(1)), int(m.group(2)), int(m.group(3))) for m in CUT_TIME_RE.finditer(text)]


def _strictly_increasing(times: list[tuple[int, int, int]]) -> bool:
    return all(times[i] < times[i + 1] for i in range(len(times) - 1))


def _subject_definitions_section(text: str) -> str:
    """提取 subject_definitions 段（从 ``subject_definitions:`` 到 ``summary:`` 前）。"""
    start = text.find("subject_definitions:")
    if start < 0:
        return ""
    end = text.find("summary:", start + 1)
    return text[start : end if end >= 0 else len(text)]


def _label_numbers(text: str, tag: str) -> set[int]:
    """提取某类标签（Subject/Picture/Video/Audio）的全部编号。"""
    return {int(m.group(1)) for m in re.finditer(rf"<{tag} (\d+)>", text)}


def _dialogue_count(text: str) -> int:
    """<d> 开标签计数 = 台词条数（check_prompt 已保证成对）。"""
    return len(_DIALOGUE_RE.findall(text))


def check_prompt(
    text: str,
    ref_count: int | None = None,
    compare_text: str | None = None,
    expect_dialogues: int | None = None,
    ref_files: set[str] | None = None,
    asset_names: set[str] | None = None,
) -> tuple[list[str], list[str]]:
    """校验单条 Ref2VA 六段式文本，返回 (errors, warnings)。"""
    errors: list[str] = []
    warnings: list[str] = []

    ordered = _field_order(text, REF_FIELDS)
    if len(ordered) < len(REF_FIELDS):
        missing = [f for f in REF_FIELDS if f not in ordered]
        errors.append(f"字段缺失: {', '.join(missing)}")
    elif ordered != list(REF_FIELDS):
        errors.append(f"字段顺序错误: 实际出现顺序 {ordered}，要求 {list(REF_FIELDS)}")

    if "[Shot 1]" not in text:
        errors.append("缺少 [Shot 1] 标记")
    if re.search(r"\[Shot 1\]\s*At \d{2}:\d{2}\.\d{3}", text):
        errors.append("[Shot 1] 不应带时间戳")

    times = _cut_times(text)
    bad = [t for t in times if t[1] > 59 or t[2] > 999]
    if bad:
        errors.append(f"非法切镜时间戳（MM 或 mmm 越界）: {bad}")
    if len(times) > 1 and not _strictly_increasing(times):
        errors.append("切镜时间戳未严格递增")

    if text.count("<d>") != text.count("</d>"):
        errors.append(f"<d> 标签未成对闭合（<d>={text.count('<d>')}，</d>={text.count('</d>')}）")

    summary_line = ""
    if "summary:" in text:
        after_summary = text.split("summary:")[-1]
        summary_line = next((ln.strip() for ln in after_summary.split("\n") if ln.strip()), "")
    if summary_line and not SUMMARY_PREFIX_RE.match(summary_line):
        errors.append(f"summary 缺少方括号任务类型前缀: {summary_line!r}")
    if "retention_analysis" in text and not any(
        m in text.split("retention_analysis:")[-1].split("detailed_description:")[0] for m in RETENTION_MARKERS
    ):
        # 骨架占位（N/A / (refine...)）不算违约——由直出模板或润色补写后再按标记校验。
        retention_segment = text.split("retention_analysis:")[-1].split("detailed_description:")[0].strip()
        if retention_segment and not (retention_segment.startswith("N/A") or retention_segment.startswith("(refine")):
            errors.append("retention_analysis 未使用任何关系标记")

    # 引用标签对齐：subject_definitions 未定义的标签视为悬空；Picture 编号不得越过参考图数。
    defined_section = _subject_definitions_section(text)
    for tag in ("Subject", "Picture"):
        defined = _label_numbers(defined_section, tag)
        used = _label_numbers(text, tag)
        undefined = used - defined
        if undefined:
            undefined_sorted = sorted(undefined)
            errors.append(f"存在未定义的 <{tag} N> 标签: {undefined_sorted}（subject_definitions 未定义）")
    defined_pics = _label_numbers(defined_section, "Picture")
    if ref_count is not None and defined_pics and max(defined_pics) > ref_count:
        errors.append(f"<Picture N> 最大编号 {max(defined_pics)} 超过参考图数 {ref_count}")

    # 台词完整性：成品台词数不得少于骨架/期望值（防 LLM 润色删台词）
    actual = _dialogue_count(text)
    if compare_text is not None:
        expected = _dialogue_count(compare_text)
        if actual < expected:
            errors.append(
                f"台词被删减: 骨架 {expected} 条 <d>，成品 {actual} 条（逐字保留全部台词，删减=违约；放不下是拆分问题）"
            )
        elif actual > expected:
            warnings.append(f"台词数多于骨架: 骨架 {expected} 条 <d>，成品 {actual} 条（核对是否重复）")
    if expect_dialogues is not None and actual < expect_dialogues:
        errors.append(f"台词不足: 期望 {expect_dialogues} 条 <d>，实际 {actual} 条（逐字保留全部台词，删减=违约）")

    # @file 引用一致性：@xxx.png 必须在连线清单（有图）或项目资产表内（无图标注），否则悬空/错位
    if ref_files:
        used = set(_ATFILE_RE.findall(text))
        known = set(ref_files)
        if asset_names:
            known |= {f"{n}.png" for n in asset_names}
        dangling = used - known
        if dangling:
            errors.append(
                f"@file 引用不在参考图连线清单/资产表内: {sorted(dangling)}"
                "（<Picture N> 与文件对应错位或悬空，按 refs/E1Uxx.refs.md 与 project.json 核对）"
            )

    lowered = text.lower()
    for zh in TRIGGER_WORDS_ZH:
        if zh in text:
            warnings.append(f"命中任务类型触发词（中文）: {zh!r}")
    for en in TRIGGER_WORDS_EN:
        if re.search(rf"\b{en}\b", lowered):
            warnings.append(f"命中任务类型触发词（英文）: {en!r}")

    return errors, warnings


def _video_prompts(episode: dict) -> list[tuple[str, str]]:
    """从剧本提取 (分镜标识, video_prompt) 列表；分镜标识取 id/title/索引。"""
    out: list[tuple[str, str]] = []
    for key in ("segments", "scenes", "shots", "video_units"):
        items = episode.get(key)
        if not isinstance(items, list):
            continue
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            prompt = item.get("video_prompt")
            if not isinstance(prompt, str) or not prompt.strip():
                continue
            label = str(item.get("id") or item.get("title") or f"{key}[{idx}]")
            out.append((label, prompt))
        break
    return out


def _report(errors_all: list[str], warnings_all: list[str]) -> int:
    """打印校验结果并返回退出码。"""
    if errors_all:
        print(f"=== H3 格式校验失败（{len(errors_all)} 条 error）===")
        for line in errors_all:
            print("  ERROR " + line)
        if warnings_all:
            print("--- warning（不阻断）---")
            for line in warnings_all:
                print("  WARN  " + line)
        return 1
    if warnings_all:
        print("=== H3 格式校验通过（含 warning）===")
        for line in warnings_all:
            print("  WARN  " + line)
        return 0
    print("=== H3 格式校验通过（无违约）===")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="H3 Ref2VA 六段式产物校验（仅 r2v）")
    parser.add_argument("project", nargs="?", help="项目名（缺省时从 cwd 推导；与 --text 互斥）")
    parser.add_argument("episode", nargs="?", type=int, help="集号")
    parser.add_argument("--projects-root", default="projects")
    parser.add_argument("--text", help="直接校验的 H3 六段式文本（不走剧本文件）")
    parser.add_argument("--ref-count", type=int, help="参考图数（<Picture N> 编号上限）")
    parser.add_argument("--compare", help="骨架文件路径：成品 <d> 台词数少于骨架即 error（防删台词）")
    parser.add_argument("--expect-dialogues", type=int, help="期望台词条数：成品 <d> 少于该值即 error")
    parser.add_argument(
        "--refs-from",
        help="参考图连线清单路径（refs/E1Uxx.refs.md）：@file 引用文件名必须在该清单内（拦截错位/悬空）",
    )
    parser.add_argument(
        "--assets-from",
        help="project.json 路径：@file 引用名称在资产表内（即使无图标注）也视为合法，不误报",
    )
    args = parser.parse_args(argv)

    if args.text is not None:
        compare_text = None
        if args.compare:
            try:
                compare_text = Path(args.compare).read_text(encoding="utf-8")
            except OSError as exc:
                print(f"骨架读取失败: {args.compare}: {exc}", file=sys.stderr)
                return 2
        ref_files = None
        if args.refs_from:
            try:
                ref_files = _parse_refs_md(Path(args.refs_from))
            except OSError as exc:
                print(f"连线清单读取失败: {args.refs_from}: {exc}", file=sys.stderr)
                return 2
        asset_names: set[str] | None = None
        if args.assets_from:
            try:
                proj = json.loads(Path(args.assets_from).read_text(encoding="utf-8"))
                asset_names = set()
                for bucket in ("characters", "scenes", "props"):
                    assets = proj.get(bucket)
                    if isinstance(assets, dict):
                        asset_names.update(assets.keys())
            except (OSError, json.JSONDecodeError) as exc:
                print(f"project.json 读取失败: {args.assets_from}: {exc}", file=sys.stderr)
                return 2
        errors, warnings = check_prompt(
            args.text,
            ref_count=args.ref_count,
            compare_text=compare_text,
            expect_dialogues=args.expect_dialogues,
            ref_files=ref_files,
            asset_names=asset_names,
        )
        return _report([f"[text] {e}" for e in errors], [f"[text] {w}" for w in warnings])

    project = args.project
    episode = args.episode
    projects_root = Path(args.projects_root)

    if project is None:
        cwd = Path.cwd()
        try:
            if cwd.name == projects_root.name:
                project = cwd.parent.name
            else:
                project = cwd.name
        except Exception:
            parser.error("无法从 cwd 推导项目名，请显式传入")
        episode = episode or 1

    if episode is None:
        parser.error("请传入集号")
    episode_path = projects_root / project / "scripts" / f"episode_{episode}.json"

    if not episode_path.is_file():
        print(f"剧本不存在: {episode_path}", file=sys.stderr)
        return 2
    try:
        data = json.loads(episode_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"剧本读取失败: {exc}", file=sys.stderr)
        return 2

    prompts = _video_prompts(data)
    if not prompts:
        print("未找到任何 video_prompt 字段（reference_video 剧本无该字段，请用 --text 校验 H3 文本）", file=sys.stderr)
        return 2

    errors_all: list[str] = []
    warnings_all: list[str] = []
    for label, prompt in prompts:
        errors, warnings = check_prompt(prompt)
        for e in errors:
            errors_all.append(f"[{label}] {e}")
        for w in warnings:
            warnings_all.append(f"[{label}] {w}")

    return _report(errors_all, warnings_all)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
