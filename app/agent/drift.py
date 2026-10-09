"""漂移检测：长选品任务中，行为逐渐偏离需求时给出纠正提示。

四类规则信号（本地计算、零成本、默认开启）：

- ``constraint_drop`` 已声明的市场/预算约束在后续工具参数里被违背
- ``goal_drift``      最近几次查询与原始需求的关键词重合度过低
- ``empty_streak``    连续多次检索类工具返回空结果
- ``cost_runaway``    最近三次工具结果体积明显高于此前均值

规则命中只返回一条提示（由调用方注入下一轮输入）并发事件，
不改写本轮回复；同类信号每会话最多触发一次。按会话隔离，
一轮选品意图结束后调用 :meth:`DriftDetector.reset`。
"""

from __future__ import annotations

import json
import re
from collections import deque
from dataclasses import dataclass
from typing import Any, Mapping

_MARKET_US_PATTERN = re.compile(r"美国站|美国|亚马逊|amazon|\bUS\b|美元|USD", re.I)
_BUDGET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"预算[^\d]{0,4}(\d+(?:\.\d+)?)"),
    re.compile(r"不超过[^\d]{0,4}(\d+(?:\.\d+)?)"),
    re.compile(r"(\d+(?:\.\d+)?)\s*(?:元|块)(?:以内|以下)?"),
)
_BUDGET_ARG_KEYS = ("price_max_major", "price_max", "max_price", "budget")
_DESTINATION_ARG_KEYS = ("destination", "ship_to", "target_market")
_MARKET_DEFAULT_VALUES = {"US", "USA", "UNITED STATES", "美国"}

_QUERY_ARG_KEYS = (
    "query",
    "queries",
    "product_query",
    "normalized_query",
    "keyword",
    "keywords",
    "demands",
    "title",
    "category",
)
_SEARCH_TOOLS = {
    "item_search",
    "product_scraper",
    "market_price_search",
    "web_search",
    "market_trend_research",
    "procurement_quote",
}
_EMPTY_LIST_KEYS = (
    "results",
    "items",
    "candidates",
    "picks",
    "evidence",
    "hits",
    "cards",
    "products",
)
_GOAL_STOPWORDS = {
    "帮我",
    "请",
    "想",
    "要",
    "找",
    "一个",
    "一款",
    "的",
    "了",
    "吗",
    "吧",
    "以及",
    "并且",
    "然后",
    "一下",
    "可以",
}


@dataclass(frozen=True)
class DriftSignal:
    """一次命中的漂移信号；``hint`` 可直接注入下一轮输入。"""

    kind: str
    detail: str
    hint: str


def _bigrams(text: str) -> set[str]:
    """中文按二字组、英文按词切分，用于粗略的语义重合度。"""
    tokens: set[str] = set()
    for chunk in re.findall(r"[一-鿿]+|[a-z0-9]+", text.lower()):
        if re.match(r"[一-鿿]", chunk):
            if len(chunk) >= 2:
                tokens.update(chunk[i : i + 2] for i in range(len(chunk) - 1))
            else:
                tokens.add(chunk)
        elif len(chunk) >= 3:
            tokens.add(chunk)
    return {token for token in tokens if token not in _GOAL_STOPWORDS}


def _overlap(goal_tokens: set[str], text: str) -> float:
    if not goal_tokens:
        return 1.0
    candidate = _bigrams(text)
    if not candidate:
        return 0.0
    return len(goal_tokens & candidate) / len(goal_tokens)


def _extract_budget(goal: str) -> float | None:
    for pattern in _BUDGET_PATTERNS:
        match = pattern.search(goal)
        if match:
            try:
                return float(match.group(1))
            except (TypeError, ValueError):
                continue
    return None


def _query_text(arguments: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for key in _QUERY_ARG_KEYS:
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value)
        elif isinstance(value, (list, tuple)):
            parts.extend(str(item) for item in value if isinstance(item, str))
    return " ".join(parts)


def _is_empty_result(tool_name: str, text: str) -> bool:
    """检索类工具返回空集合（而非报错）时视为一次空结果。"""
    if tool_name not in _SEARCH_TOOLS:
        return False
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return False
    if not isinstance(data, dict):
        return False
    if data.get("source") == "unavailable":
        return True
    if data.get("status") == "unavailable":
        return True
    for key in _EMPTY_LIST_KEYS:
        value = data.get(key)
        if isinstance(value, list):
            return len(value) == 0
    return False


class DriftDetector:
    """按会话累计行为信号；规则命中返回提示，不做强制终止。"""

    def __init__(
        self,
        *,
        goal_overlap_threshold: float = 0.2,
        goal_lookback: int = 3,
        empty_threshold: int = 3,
        cost_multiplier: float = 2.0,
        min_cost_chars: int = 2000,
    ) -> None:
        self._overlap_threshold = goal_overlap_threshold
        self._lookback = goal_lookback
        self._empty_threshold = empty_threshold
        self._cost_multiplier = cost_multiplier
        self._min_cost_chars = min_cost_chars

        self._goals: dict[str, str] = {}
        self._goal_tokens: dict[str, set[str]] = {}
        self._market_us: dict[str, bool] = {}
        self._budget: dict[str, float | None] = {}
        self._recent_overlaps: dict[str, deque[float]] = {}
        self._empty_counts: dict[str, int] = {}
        self._result_sizes: dict[str, deque[int]] = {}
        self._fired: dict[str, set[str]] = {}

    def start_turn(self, session_id: str, goal: str) -> None:
        """登记本轮选品目标；只在该目标尚未登记时写入。"""
        if session_id in self._goals:
            return
        self._goals[session_id] = goal
        self._goal_tokens[session_id] = _bigrams(goal)
        self._market_us[session_id] = bool(_MARKET_US_PATTERN.search(goal))
        self._budget[session_id] = _extract_budget(goal)
        self._recent_overlaps[session_id] = deque(maxlen=self._lookback)
        self._empty_counts[session_id] = 0
        self._result_sizes[session_id] = deque(maxlen=2 * self._lookback)
        self._fired[session_id] = set()

    def reset(self, session_id: str) -> None:
        for store in (
            self._goals,
            self._goal_tokens,
            self._market_us,
            self._budget,
            self._recent_overlaps,
            self._empty_counts,
            self._result_sizes,
            self._fired,
        ):
            store.pop(session_id, None)

    # -- 信号规则 ---------------------------------------------------------

    def _constraint_signals(
        self, session_id: str, tool_name: str, arguments: Mapping[str, Any]
    ) -> list[DriftSignal]:
        signals: list[DriftSignal] = []
        if self._market_us.get(session_id):
            for key in _DESTINATION_ARG_KEYS:
                value = arguments.get(key)
                if not isinstance(value, str) or not value.strip():
                    continue
                if value.strip().upper() not in _MARKET_DEFAULT_VALUES:
                    signals.append(
                        DriftSignal(
                            kind="constraint_drop",
                            detail=f"本次需求声明美国市场，但 {tool_name}.{key}={value}",
                            hint=(
                                f"[漂移提示] 买家本次需求是美国站，但 {tool_name} 使用了 "
                                f"{key}={value}。请用美国（US）口径重新核对相关数字；"
                                "若确有原因改用其他口径，请明确说明来源。"
                            ),
                        )
                    )
                    return signals
        budget = self._budget.get(session_id)
        if budget is not None:
            for key in _BUDGET_ARG_KEYS:
                value = arguments.get(key)
                if isinstance(value, (int, float)) and value > budget * 1.05:
                    signals.append(
                        DriftSignal(
                            kind="constraint_drop",
                            detail=f"预算 {budget:g}，但 {tool_name}.{key}={value}",
                            hint=(
                                f"[漂移提示] 买家预算约 {budget:g}，但 {tool_name} 使用了 "
                                f"{key}={value}。请回到预算约束，或说明为何放宽。"
                            ),
                        )
                    )
                    return signals
        return signals

    def _goal_signal(
        self, session_id: str, arguments: Mapping[str, Any]
    ) -> DriftSignal | None:
        text = _query_text(arguments)
        if not text:
            return None
        overlaps = self._recent_overlaps[session_id]
        overlaps.append(_overlap(self._goal_tokens[session_id], text))
        if len(overlaps) < self._lookback:
            return None
        if all(value < self._overlap_threshold for value in overlaps):
            goal = self._goals[session_id]
            return DriftSignal(
                kind="goal_drift",
                detail=f"最近 {self._lookback} 次查询与原始需求重合度低于阈值",
                hint=(
                    "[漂移提示] 最近几次查询与买家原始需求（"
                    f"{goal[:60]}）的重合度很低。请回到本次需求重新组织查询；"
                    "如果这是买家新增的需求，请以其最新说明为准并继续核对证据。"
                ),
            )
        return None

    def _empty_signal(self, session_id: str, tool_name: str, text: str) -> DriftSignal | None:
        if _is_empty_result(tool_name, text):
            self._empty_counts[session_id] += 1
        elif tool_name in _SEARCH_TOOLS:
            self._empty_counts[session_id] = 0
        if (
            tool_name in _SEARCH_TOOLS
            and self._empty_counts[session_id] >= self._empty_threshold
        ):
            return DriftSignal(
                kind="empty_streak",
                detail=f"连续 {self._empty_counts[session_id]} 次检索为空",
                hint=(
                    "连续多次检索没有返回结果。请不要继续用相近查询重试："
                    "更换关键词或品类，或基于已有证据给出结论并明确说清缺口。"
                ),
            )
        return None

    def _cost_signal(self, session_id: str, text: str) -> DriftSignal | None:
        sizes = self._result_sizes[session_id]
        sizes.append(len(text))
        if len(sizes) < 3 * 2:
            return None
        recent = list(sizes)[-3:]
        history = list(sizes)[:-3]
        if not history:
            return None
        recent_mean = sum(recent) / len(recent)
        history_mean = sum(history) / len(history)
        if recent_mean < self._min_cost_chars or recent_mean <= history_mean * self._cost_multiplier:
            return None
        return DriftSignal(
            kind="cost_runaway",
            detail=f"近 3 次工具结果均 {recent_mean:.0f} 字符，约为此前均值的 {recent_mean / max(history_mean, 1):.1f} 倍",
            hint=(
                "工具结果体积持续增大。请收窄查询范围（减少条数、限定字段），"
                "需要回查细节时再按条目查询，避免把整批明细反复带入上下文。"
            ),
        )

    # -- 入口 -------------------------------------------------------------

    def observe(
        self,
        *,
        session_id: str,
        tool_name: str,
        arguments: Mapping[str, Any],
        result_text: str,
    ) -> list[DriftSignal]:
        """记录一次工具调用，返回本次新命中的信号（同类每会话最多一次）。"""
        if session_id not in self._goals:
            return []
        fired = self._fired[session_id]

        candidates = [
            *self._constraint_signals(session_id, tool_name, arguments),
            self._goal_signal(session_id, arguments),
            self._empty_signal(session_id, tool_name, result_text),
            self._cost_signal(session_id, result_text),
        ]
        signals = [
            signal
            for signal in candidates
            if signal is not None and signal.kind not in fired
        ]
        for signal in signals:
            fired.add(signal.kind)
        return signals
