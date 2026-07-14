"""Choose a cache-stable boundary based on recent tool calls."""

from collections.abc import Sequence

from langchain_core.messages import BaseMessage


def compute_breakpoint(
    messages: Sequence[BaseMessage], keep_recent: int = 3
) -> int:
    """Return the start of the most recent ``keep_recent`` tool-call window.

    The prefix before this boundary remains byte-for-byte stable for provider
    prompt-cache hits. Returning ``len(messages)`` means tool calls are still
    few enough that the entire history should stay untouched.
    """
    if keep_recent < 0:
        raise ValueError("keep_recent must be non-negative")
    if keep_recent == 0:
        return 0

    tool_call_indices = [
        index
        for index, message in enumerate(messages)
        if message.type == "tool"
    ]
    if len(tool_call_indices) <= keep_recent:
        return len(messages)
    return tool_call_indices[-keep_recent]
