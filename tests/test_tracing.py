"""OTLP 追踪：配置解析、span 白名单属性、异常标记与脱敏。"""

import asyncio
import base64

import pytest
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.agent.harness import HarnessMiddleware
from app.observability.tracing import (
    configure_tracing,
    record_usage,
    resolve_otlp,
    span,
)
from tests.test_harness import RecordingFakeModel, _tool_call


@pytest.fixture(scope="module")
def span_exporter():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)  # 测试进程内只设置一次
    yield exporter


@pytest.fixture(autouse=True)
def _clean_spans(span_exporter):
    span_exporter.clear()
    yield
    span_exporter.clear()


class TestConfiguration:
    def test_no_configuration_means_disabled(self, monkeypatch) -> None:
        for name in (
            "OTEL_EXPORTER_OTLP_ENDPOINT",
            "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
            "LANGFUSE_BASE_URL",
            "LANGFUSE_PUBLIC_KEY",
            "LANGFUSE_SECRET_KEY",
        ):
            monkeypatch.delenv(name, raising=False)
        assert resolve_otlp() is None
        assert configure_tracing() is False

    def test_generic_otlp_endpoint_with_headers(self, monkeypatch) -> None:
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
        monkeypatch.setenv(
            "OTEL_EXPORTER_OTLP_TRACES_HEADERS", "x-api-key=abc, x-other=1"
        )
        resolved = resolve_otlp()
        assert resolved is not None
        endpoint, headers = resolved
        assert endpoint == "http://collector:4318"
        assert headers == {"x-api-key": "abc", "x-other": "1"}

    def test_langfuse_derives_otlp_endpoint_and_basic_auth(self, monkeypatch) -> None:
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        monkeypatch.setenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com/")
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
        resolved = resolve_otlp()
        assert resolved is not None
        endpoint, headers = resolved
        assert endpoint == "https://cloud.langfuse.com/api/public/otel/v1/traces"
        token = base64.b64encode(b"pk:sk").decode()
        assert headers == {"Authorization": f"Basic {token}"}


class TestSpans:
    def test_harness_emits_tool_and_model_spans_without_payloads(
        self, span_exporter
    ) -> None:
        secret_payload = "PAYLOAD-MUST-NOT-APPEAR-IN-TRACES"

        from langchain_core.tools import tool

        @tool
        def memo_search(keyword: str) -> str:
            """检索。"""
            return f'{{"items": ["{secret_payload}"]}}'

        model = RecordingFakeModel(
            script=[_tool_call("memo_search", {"keyword": "a"}, "c1"), AIMessage(content="结束")]
        )
        agent = create_agent(
            model=model,
            tools=[memo_search],
            middleware=[HarnessMiddleware(enable_drift=False)],
        )
        asyncio.run(agent.ainvoke({"messages": [HumanMessage(content="查")]}))

        spans = span_exporter.get_finished_spans()
        names = [finished.name for finished in spans]
        assert "tool.call" in names
        assert "llm.call" in names

        tool_span = next(finished for finished in spans if finished.name == "tool.call")
        attributes = dict(tool_span.attributes or {})
        assert attributes["tool.name"] == "memo_search"
        assert attributes["tool.status"] == "success"
        assert isinstance(attributes["tool.duration_ms"], int)

        # 脱敏：任何 span 属性值都不得包含工具返回正文
        for finished in spans:
            for value in (finished.attributes or {}).values():
                assert secret_payload not in str(value)

    def test_span_records_exception_and_reraises(self, span_exporter) -> None:
        with pytest.raises(RuntimeError):
            with span("unit.call", {"k": "v"}):
                raise RuntimeError("boom")

        finished = span_exporter.get_finished_spans()[0]
        assert finished.status.status_code == trace.StatusCode.ERROR
        assert finished.events  # record_exception 至少产生一个事件

    def test_record_usage_uses_available_metadata_only(self, span_exporter) -> None:
        from langchain_core.messages import AIMessage

        with span("llm.call") as handle:
            record_usage(
                handle,
                [
                    AIMessage(
                        content="x",
                        usage_metadata={
                            "input_tokens": 10,
                            "output_tokens": 2,
                            "total_tokens": 12,
                        },
                    )
                ],
            )
        attributes = dict(span_exporter.get_finished_spans()[0].attributes or {})
        assert attributes["llm.input_tokens"] == 10
        assert attributes["llm.total_tokens"] == 12

        span_exporter.clear()
        with span("llm.call") as handle:
            record_usage(handle, [AIMessage(content="x")])
        attributes = dict(span_exporter.get_finished_spans()[0].attributes or {})
        assert "llm.input_tokens" not in attributes  # 缺失不补 0
