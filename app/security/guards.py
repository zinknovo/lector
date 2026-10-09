"""安全护栏：L3 工具结果注入过滤 + L4 输出脱敏。

威胁模型：工具结果（商品标题/描述、网页搜索正文、货源页面）是外部内容，
可能夹带提示词注入；最终回复可能带出 API Key、数据库地址或本机路径。
两层都是纯正则、零成本，在对应边界同步执行。
"""

from __future__ import annotations

import re

FILTERED_PLACEHOLDER = "[内容已过滤：疑似注入]"
REDACTED_PLACEHOLDER = "[已脱敏]"

# L3：命中即替换为占位符，保留其余正常内容（商品标题、价格不能一起砍掉）
DANGEROUS_PATTERNS: list[str] = [
    r"(?i)ignore\s+(all\s+)?previous\s+instructions?",
    r"(?i)忽略.{0,10}(之前|以上|所有).{0,10}(指令|指示|规则)",
    r"(?i)system\s*prompt",
    r"(?i)you\s+are\s+now",
    r"(?i)扮演.{0,10}角色",
    r"(?i)output\s+(all|every)\s+(user|system)",
    r"(?i)reveal\s+(your|the)\s+(api|secret|key)",
]

# L4：只脱敏“卖家无需知道、且泄露有害”的内容。
# 商品/工具名不下发即是契约的一部分（事件流本来就展示工具名），不做脱敏。
SENSITIVE_PATTERNS: list[str] = [
    r"sk-[A-Za-z0-9]{20,}",
    r"mongodb(?:\+srv)?://[^\s\"'）)]+",
    r"(?:thread_id|session_id)\s*[:=]\s*[\w-]+",
    r"(?:LLM_API_KEY|APIFY_API_TOKEN|DEEPSEEK_API_KEY)\s*[:=]\s*\S+",
    r"/(?:Users|home)/[^\s\"'）)]+",
]

_dangerous = [re.compile(pattern) for pattern in DANGEROUS_PATTERNS]
_sensitive = [re.compile(pattern) for pattern in SENSITIVE_PATTERNS]


def sanitize_tool_output(text: str) -> tuple[bool, str]:
    """过滤工具返回中的疑似注入内容。

    Returns:
        (是否命中过危险模式, 过滤后的文本)；文本始终可用，不会因命中变成空串。
    """
    if not text:
        return False, text
    hit = False
    cleaned = text
    for pattern in _dangerous:
        cleaned, count = pattern.subn(FILTERED_PLACEHOLDER, cleaned)
        if count:
            hit = True
    return hit, cleaned


def audit_output(text: str) -> tuple[bool, str]:
    """审核最终输出：命中敏感模式即脱敏（不阻断回复）。

    Returns:
        (是否安全, 处理后的文本)。
    """
    if not text:
        return True, text
    safe = True
    cleaned = text
    for pattern in _sensitive:
        cleaned, count = pattern.subn(REDACTED_PLACEHOLDER, cleaned)
        if count:
            safe = False
    return safe, cleaned
