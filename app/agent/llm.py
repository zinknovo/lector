"""Shared LLM instances for agent loops and judge."""

import os
from functools import lru_cache

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model


@lru_cache(maxsize=8)
def _get_llm_cached(
    model_name: str,
    api_key: str,
    base_url: str,
    temperature: float,
):
    return init_chat_model(
        model_name,
        model_provider="openai",
        api_key=api_key,
        base_url=base_url,
        temperature=temperature,
    )


def get_llm(*, load_env: bool = True):
    """主 / 子 AgentLoop 共用的大模型实例。"""
    if load_env:
        load_dotenv()
    api_key = os.environ.get("LLM_API_KEY")
    if not api_key:
        raise RuntimeError("缺少 LLM_API_KEY 环境变量")
    model_name = os.environ.get("LLM_MODEL_NAME", "deepseek-v4-pro")
    base_url = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com")
    raw_temperature = os.environ.get("LLM_TEMPERATURE", "0.1")
    try:
        temperature = float(raw_temperature)
    except ValueError as exc:
        raise RuntimeError("LLM_TEMPERATURE 必须是数字") from exc
    return _get_llm_cached(
        model_name, api_key, base_url, temperature
    )


@lru_cache(maxsize=1)
def get_judge_llm():
    """评测体系（Rubric judge）专用的强模型。"""
    load_dotenv()
    api_key = os.environ.get("LLM_API_KEY")
    if not api_key:
        raise RuntimeError("缺少 LLM_API_KEY 环境变量")
    return init_chat_model(
        os.environ.get("LLM_JUDGE_MODEL_NAME", "qwen-max"),
        model_provider="openai",
        api_key=api_key,
        base_url=os.environ.get("LLM_BASE_URL", "https://api.deepseek.com"),
        temperature=0.0,
    )
