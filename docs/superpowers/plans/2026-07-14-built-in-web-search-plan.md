# Built-in Model Web Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Replace Tavily with a model-capability interface and an OpenAI Responses built-in web-search adapter.

**Architecture:** Keep `WebSearchOutput` stable. Route the tool through `BuiltInWebSearchBackend`; the OpenAI adapter extracts URL citations, while unsupported model endpoints return explicit unavailable status.

**Tech Stack:** Python, OpenAI SDK, LangChain tools, Pydantic, pytest.

## Tasks

1. RED: replace Tavily tests with backend-interface, OpenAI Responses request and citation-mapping tests.
2. GREEN: implement backend protocol, OpenAI adapter, unavailable adapter and factory.
3. Remove Tavily environment/docs references and document `LLM_WEB_SEARCH_BACKEND`.
4. Run focused tests, full backend/frontend/build/Demo verification, merge and push.

## Constraints

- Reuse existing LLM credentials.
- Do not add another provider SDK or API key.
- Do not claim DeepSeek supports a server-side search tool.
- Preserve structured unavailable behavior.
