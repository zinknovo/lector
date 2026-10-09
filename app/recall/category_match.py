"""品类一致性：判断候选文本是否属于目标品类（规则版，先不引入向量）。

用于召回层过滤"硬凑的相近品"（如目标「保温杯」混入「茶杯」）：目标品类先经
别名表展开/替换，再与候选文本做二字组与英文词的重合度比较。

两条保守约定：

- 别名命中即视为一致（U 型枕 → 颈枕、马克杯 → 咖啡杯）；
- 目标与候选分属不同文字体系（中文 vs 拉丁）且没有共享 token 时，**判为无法判定，
  保留候选**——规则版只处理有把握的部分，宁可少滤不可误伤。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.recall.category_norm import CATEGORY_ALIASES, normalize_category

DEFAULT_MIN_OVERLAP = 0.3

_CJK_RE = re.compile(r"[一-鿿]")


@dataclass(frozen=True)
class CategoryMatch:
    ok: bool
    overlap: float
    reason: str


def _has_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text))


def _expand_aliases(text: str) -> str:
    """把文本里出现的别名短语替换为标准品类名（子串替换，大小写不敏感）。"""
    result = text.strip().lower()
    for alias, standard in CATEGORY_ALIASES.items():
        if alias and alias in result:
            result = result.replace(alias, standard)
    return result


def _tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for chunk in re.findall(r"[一-鿿]+|[a-z0-9]+", text.lower()):
        if _CJK_RE.match(chunk):
            if len(chunk) >= 2:
                tokens.update(chunk[i : i + 2] for i in range(len(chunk) - 1))
            else:
                tokens.add(chunk)
        elif len(chunk) >= 3:
            tokens.add(chunk)
    return tokens


def match_category(
    target: str, text: str, *, min_overlap: float = DEFAULT_MIN_OVERLAP
) -> CategoryMatch:
    """判断候选文本是否与目标品类一致；无法判定时保守保留。"""
    if not target.strip() or not text.strip():
        return CategoryMatch(ok=True, overlap=1.0, reason="缺少品类或候选文本，跳过过滤")

    normalized_target = _expand_aliases(normalize_category(target))
    normalized_text = _expand_aliases(text)
    target_tokens = _tokens(normalized_target)
    text_tokens = _tokens(normalized_text)
    if not target_tokens:
        return CategoryMatch(ok=True, overlap=1.0, reason="目标品类无法拆词，跳过过滤")

    overlap = len(target_tokens & text_tokens) / len(target_tokens)
    if overlap >= min_overlap:
        return CategoryMatch(ok=True, overlap=round(overlap, 3), reason="品类一致")

    if _has_cjk(normalized_target) != _has_cjk(normalized_text):
        return CategoryMatch(
            ok=True,
            overlap=round(overlap, 3),
            reason="目标与候选文字体系不同，规则无法判定，保留候选",
        )
    return CategoryMatch(
        ok=False, overlap=round(overlap, 3), reason="品类不一致：与目标品类无共同关键词"
    )
