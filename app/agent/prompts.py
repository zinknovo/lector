"""Prompt loaders cached from prompts.yml."""

from functools import lru_cache
from pathlib import Path
from typing import cast

import yaml


@lru_cache(maxsize=1)
def _load_prompts() -> dict[str, object]:
    cfg_path = Path(__file__).parent.parent / "prompt" / "prompts.yml"
    with cfg_path.open("r", encoding="utf-8") as f:
        data = cast(object, yaml.safe_load(f))
    if not isinstance(data, dict):
        raise ValueError("prompts.yml must contain a YAML mapping")
    return cast(dict[str, object], data)


def get_system_prompt(long_term_preferences: str = "") -> str:
    """主 / 子 AgentLoop 共用的 system prompt（带长期偏好注入位）。"""
    template = cast(str, _load_prompts()["system_prompt"])
    return template.format(
        long_term_preferences=long_term_preferences or "（暂无沉淀偏好）"
    )


def get_planner_prompt() -> str:
    return cast(str, _load_prompts()["planner_prompt"])


def get_shopping_summary_prompt() -> str:
    return cast(str, _load_prompts()["shopping_summary_prompt"])
