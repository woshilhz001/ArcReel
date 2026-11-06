"""分镜画面描述里「已登记且已写进引用字段、却裸写未用 ``@[名称]``」的漏写检查。

``image_prompt_writing_guide`` 要求画面里出现的已登记资产用 ``@[登记名]`` 指认：生成端按
参考图顺序把它换成「图N」。漏写 ``@[]`` 时渲染层只会把裸名原样发送，资产图不参与指认——
这条漏写在既有 :mod:`lib.script.storyboard_mentions` 守卫里不可见（它只检查写了 ``@[名称]``
却没绑定的反方向），本模块把正方向收成同形的 ``{"key", "params"}`` 警告，供写剧本的工具随
回执返回，由 Agent / 用户决定补写，检查本身不改任何文本。

判定刻意收紧到「名字同时满足：已登记为资产 + 已写进该条目的引用字段 + 正文裸写未用
``@[名称]``」三条缺一不可：正文偶发提到一个没进引用字段的名字（背景里一闪而过）不算漏写，
不报，避免误报。
"""

from __future__ import annotations

from collections.abc import Collection
from typing import Any

from lib.project.asset_types import ASSET_SPECS, asset_name_comparison_key
from lib.references.reference_catalog import ReferenceCatalog
from lib.script.reference_video.text_parser import render_mentions
from lib.script.storyboard_sequence import get_storyboard_items

#: 画面描述里出现了已登记且已写进引用字段的名字，但没有用 ``@[名称]`` 指认，将按裸名发送。
WARN_STORYBOARD_PLAIN_ASSET_NAME = "storyboard_warn_plain_asset_name"

#: 全部引用字段名，与 :mod:`lib.script.storyboard_mentions` 的口径一致（本模块不反向其私有函数，避免循环导入）。
_REFERENCE_LIST_FIELDS: tuple[str, ...] = tuple(
    field for spec in ASSET_SPECS.values() for field in spec.reference_list_fields
)


def _declared_names(item: dict[str, Any]) -> set[str]:
    declared: set[str] = set()
    for field in _REFERENCE_LIST_FIELDS:
        names = item.get(field)
        if not isinstance(names, list):
            continue
        declared.update(asset_name_comparison_key(name) for name in names if isinstance(name, str))
    return declared


def _scene_text(item: dict[str, Any]) -> str | None:
    image_prompt = item.get("image_prompt")
    if isinstance(image_prompt, dict):
        image_prompt = image_prompt.get("scene")
    return image_prompt if isinstance(image_prompt, str) else None


def _plain_text(text: str) -> str:
    """去掉全部 ``@[名称]`` 记号后的正文：这里剩下的名字都是裸写。"""
    return render_mentions(text, lambda _name: "")


def find_plain_asset_mentions(
    script: dict[str, Any],
    catalog: ReferenceCatalog,
    *,
    unit_ids: Collection[str] | None = None,
) -> list[dict[str, Any]]:
    """返回分镜条目画面描述里漏写 ``@[名称]`` 的已登记资产警告，按条目顺序、条目内按引用字段声明顺序。

    ``catalog`` 由调用方构建（与 :mod:`lib.script.storyboard_mentions` 共用同一份，不重复
    解析项目载荷）。``unit_ids`` 给出时只检查这些条目（写工具只对本次改动的条目负责）。没有
    分镜条目的骨架（参考生视频）返回空列表。
    """
    items, id_field, _char_field, _scene_field, _prop_field = get_storyboard_items(script)
    warnings: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        unit_id = str(item.get(id_field) or "")
        if unit_ids is not None and unit_id not in unit_ids:
            continue
        text = _scene_text(item)
        if text is None:
            continue
        plain = _plain_text(text)
        if not plain:
            continue
        for name in sorted(_declared_names(item)):
            entry = catalog.resolve(name)
            if entry is None or name not in plain:
                continue
            warnings.append(
                {"key": WARN_STORYBOARD_PLAIN_ASSET_NAME, "params": {"unit_id": unit_id, "name": entry.name}}
            )
    return warnings


__all__ = [
    "WARN_STORYBOARD_PLAIN_ASSET_NAME",
    "find_plain_asset_mentions",
]
