"""OTLP 追踪（教程 16-3 最小版）：默认关闭、只记录结构化字段、导出失败不阻断。

配置二选一（全部留空 = 关闭，OpenTelemetry 保持 no-op）：

- ``OTEL_EXPORTER_OTLP_ENDPOINT``（或 ``OTEL_EXPORTER_OTLP_TRACES_ENDPOINT``），
  可选 ``OTEL_EXPORTER_OTLP_TRACES_HEADERS``（``k=v`` 逗号分隔）；
- Langfuse 三项：``LANGFUSE_BASE_URL`` + ``LANGFUSE_PUBLIC_KEY`` + ``LANGFUSE_SECRET_KEY``
  （自动派生 OTLP 地址与 Basic 认证头）。

span 只带白名单字段（工具名、耗时、状态、usage、thread/run id），
不记录 prompt、工具结果或报告正文（对齐 L4 的脱敏口径）。
"""

from __future__ import annotations

import base64
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Span, Status, StatusCode

_configured = False
_TRACER_NAME = "lector.agent"


def _parse_headers(raw: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    for pair in raw.split(","):
        key, separator, value = pair.partition("=")
        if separator and key.strip():
            headers[key.strip()] = value.strip()
    return headers


def resolve_otlp() -> tuple[str, dict[str, str]] | None:
    """按环境变量解析 OTLP 端点与认证头；未配置时返回 None。"""
    endpoint = os.environ.get(
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", ""
    ).strip() or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    headers_raw = (
        os.environ.get("OTEL_EXPORTER_OTLP_TRACES_HEADERS", "").strip()
        or os.environ.get("OTEL_EXPORTER_OTLP_HEADERS", "").strip()
    )
    if endpoint:
        return endpoint, _parse_headers(headers_raw)

    base_url = os.environ.get("LANGFUSE_BASE_URL", "").strip().rstrip("/")
    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY", "").strip()
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY", "").strip()
    if base_url and public_key and secret_key:
        token = base64.b64encode(
            f"{public_key}:{secret_key}".encode("utf-8")
        ).decode("ascii")
        return (
            f"{base_url}/api/public/otel/v1/traces",
            {"Authorization": f"Basic {token}"},
        )
    return None


def configure_tracing() -> bool:
    """按环境配置一次 OTLP 导出；返回是否启用。重复调用幂等。"""
    global _configured
    if _configured:
        return True
    resolved = resolve_otlp()
    if resolved is None:
        return False
    endpoint, headers = resolved
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(
            resource=Resource.create({"service.name": "lector-agent"})
        )
        provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(endpoint=endpoint, headers=headers or None)
            )
        )
        trace.set_tracer_provider(provider)
        _configured = True
        return True
    except Exception:  # noqa: BLE001 —— 观测失败不阻断业务
        return False


def tracer() -> trace.Tracer:
    return trace.get_tracer(_TRACER_NAME)


@contextmanager
def span(name: str, attributes: dict[str, Any] | None = None) -> Iterator[Span]:
    """创建一个 span；异常时记录并标记错误状态后继续抛出。"""
    with tracer().start_as_current_span(name) as current:
        for key, value in (attributes or {}).items():
            if value is not None:
                current.set_attribute(key, value)
        try:
            yield current
        except Exception as exc:
            current.record_exception(exc)
            current.set_status(Status(StatusCode.ERROR))
            raise


def record_usage(current: Span, messages: list[Any]) -> None:
    """从模型返回消息里取 usage（拿不到就什么都不记，不补 0）。"""
    for message in reversed(messages):
        usage = getattr(message, "usage_metadata", None)
        if not isinstance(usage, dict):
            continue
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        if isinstance(input_tokens, int):
            current.set_attribute("llm.input_tokens", input_tokens)
        if isinstance(output_tokens, int):
            current.set_attribute("llm.output_tokens", output_tokens)
        total = usage.get("total_tokens")
        if isinstance(total, int):
            current.set_attribute("llm.total_tokens", total)
        return
