"""轻量文本工具：中文二字组 + 英文词的粗粒度切分（模糊匹配共用）。"""

from __future__ import annotations

import re

_CJK_RE = re.compile(r"[一-鿿]")


def bigrams(text: str) -> set[str]:
    """中文按二字组、英文按长度 >= 3 的词切分。"""
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
