import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

type Frame = [number, Record<string, unknown>];

const sse = (runId: string, items: Frame[]) =>
  new Response(
    items
      .map(([seq, event]) => `id: ${runId}:${seq}\ndata: ${JSON.stringify(event)}\n\n`)
      .join(""),
    { headers: { "Content-Type": "text/event-stream" } },
  );

/** 在终态事件之前断开的事件流（模拟网络/服务端提前结束）。 */
const truncatedSse = (runId: string, items: Frame[]) =>
  new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        const encoder = new TextEncoder();
        for (const [seq, event] of items) {
          controller.enqueue(
            encoder.encode(
              `id: ${runId}:${seq}\ndata: ${JSON.stringify(event)}\n\n`,
            ),
          );
        }
        controller.close();
      },
    }),
    { headers: { "Content-Type": "text/event-stream" } },
  );

async function loadHook() {
  return import("./useLectorTask");
}

describe("useLectorTask", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("streams AG-UI events into UI state and finishes", async () => {
    const posted: Array<Record<string, unknown>> = [];
    const accepts: Array<string | null> = [];
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
      posted.push(body);
      accepts.push(new Headers(init?.headers).get("Accept"));
      const runId = String(body.runId);
      return sse(runId, [
        [1, { type: "RUN_STARTED", threadId: body.threadId, runId }],
        [2, { type: "STATE_SNAPSHOT", snapshot: { status: "running" } }],
        [3, { type: "TOOL_CALL_START", toolCallId: "c1", toolCallName: "item_search" }],
        [4, { type: "TOOL_CALL_ARGS", toolCallId: "c1", delta: '{"query":"保温杯"}' }],
        [5, { type: "TOOL_CALL_END", toolCallId: "c1" }],
        [6, {
          type: "CUSTOM",
          name: "activity.upsert",
          value: { kind: "tool", status: "completed", label: "召回候选商品", toolName: "item_search", durationMs: 42 },
        }],
        [7, {
          type: "CUSTOM",
          name: "drift_signal",
          value: { message: "目标偏移提示", kind: "goal_drift" },
        }],
        [8, {
          type: "MESSAGES_SNAPSHOT",
          messages: [
            { id: "u1", role: "user", content: "美国站卖保温杯" },
            { id: "a1", role: "assistant", content: "报告正文" },
          ],
        }],
        [9, { type: "RUN_FINISHED", threadId: body.threadId, runId, outcome: { type: "success" } }],
      ]);
    });
    vi.stubGlobal("fetch", fetchMock);

    const { useLectorTask } = await loadHook();
    const { result } = renderHook(() => useLectorTask());

    await act(async () => {
      await result.current.startTask("美国站卖保温杯", "user-1");
    });

    expect(accepts[0]).toBe("text/event-stream");
    const body = posted[0];
    const messages = body.messages as Array<Record<string, unknown>>;
    expect(messages).toHaveLength(1);
    expect(messages[0].role).toBe("user");
    expect(messages[0].content).toBe("美国站卖保温杯");
    expect((body.forwardedProps as Record<string, unknown>)?.userId).toBe("user-1");

    const names = result.current.events.map((event) => event.event);
    expect(names).toEqual([
      "session_created",
      "tool_start",
      "tool_end",
      "drift_signal",
    ]);
    const toolEnd = result.current.events.find((event) => event.event === "tool_end");
    expect(toolEnd?.data.duration_ms).toBe(42);
    expect(result.current.finalAnswer).toBe("报告正文");
    expect(result.current.running).toBe(false);
    expect(result.current.threadId).toMatch(/[0-9a-f-]{36}/);
    expect(result.current.error).toBeNull();
  });

  test("surfaces RUN_ERROR as error state", async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const runId = String(JSON.parse(String(init?.body)).runId);
      return sse(runId, [
        [1, { type: "RUN_STARTED", threadId: "t", runId }],
        [2, { type: "RUN_ERROR", message: "本轮服务暂时未能完成请求", code: "AGENT_ERROR" }],
      ]);
    });
    vi.stubGlobal("fetch", fetchMock);

    const { useLectorTask } = await loadHook();
    const { result } = renderHook(() => useLectorTask());

    await act(async () => {
      await result.current.startTask("查保温杯");
    });

    expect(result.current.error).toBe("本轮服务暂时未能完成请求");
    expect(result.current.running).toBe(false);
  });

  test("cancel aborts the run and posts to the cancel endpoint", async () => {
    const calls: string[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push(`${init?.method ?? "GET"} ${url}`);
      if (init?.method === "POST" && url === "/ag-ui/run") {
        const runId = String(JSON.parse(String(init.body)).runId);
        const signal = init?.signal;
        return new Response(
          new ReadableStream<Uint8Array>({
            start(controller) {
              controller.enqueue(
                new TextEncoder().encode(
                  `id: ${runId}:1\ndata: ${JSON.stringify({ type: "RUN_STARTED", threadId: "t", runId })}\n\n`,
                ),
              );
              // 保持流打开：等待 abort（模拟真实 fetch 的中断行为）
              signal?.addEventListener("abort", () =>
                controller.error(new DOMException("Aborted", "AbortError")),
              );
            },
          }),
          { headers: { "Content-Type": "text/event-stream" } },
        );
      }
      return new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetchMock);

    const { useLectorTask } = await loadHook();
    const { result } = renderHook(() => useLectorTask());

    let pending: Promise<void> | null = null;
    act(() => {
      pending = result.current.startTask("查保温杯");
    });
    await waitFor(() => expect(result.current.running).toBe(true));

    await act(async () => {
      await result.current.cancelTask();
      await pending;
    });

    expect(calls.some((call) => call.startsWith("POST /ag-ui/runs/") && call.endsWith("/cancel"))).toBe(true);
    expect(result.current.running).toBe(false);
  });

  test("resumes the run from the event cursor after a disconnect", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === "POST") {
        const runId = String(JSON.parse(String(init.body)).runId);
        return truncatedSse(runId, [
          [1, { type: "RUN_STARTED", threadId: "t", runId }],
          [2, { type: "TOOL_CALL_START", toolCallId: "c1", toolCallName: "item_search" }],
          [3, { type: "TOOL_CALL_ARGS", toolCallId: "c1", delta: "{}" }],
          [4, { type: "TOOL_CALL_END", toolCallId: "c1" }],
        ]);
      }
      const runId = url.match(/\/ag-ui\/runs\/([^/]+)\/events/)?.[1] ?? "unknown";
      const after = Number(new URLSearchParams(url.split("?")[1] ?? "").get("after"));
      expect(after).toBe(4); // 从已接收的游标继续
      return sse(runId, [
        [5, { type: "MESSAGES_SNAPSHOT", messages: [{ id: "a1", role: "assistant", content: "恢复后的报告" }] }],
        [6, { type: "RUN_FINISHED", threadId: "t", runId, outcome: { type: "success" } }],
      ]);
    });
    vi.stubGlobal("fetch", fetchMock);

    const { useLectorTask } = await loadHook();
    const { result } = renderHook(() => useLectorTask());

    await act(async () => {
      await result.current.startTask("查保温杯");
    });

    expect(result.current.finalAnswer).toBe("恢复后的报告");
    expect(fetchMock.mock.calls.some((call) => call[1]?.method !== "POST")).toBe(true);
    expect(result.current.error).toBeNull();
  });
});


test("reuses the thread id for follow-ups until the session is reset", async () => {
    const posted: Array<Record<string, unknown>> = [];
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
      posted.push(body);
      const runId = String(body.runId);
      return sse(runId, [
        [1, { type: "RUN_STARTED", threadId: body.threadId, runId }],
        [2, { type: "RUN_FINISHED", threadId: body.threadId, runId, outcome: { type: "success" } }],
      ]);
    });
    vi.stubGlobal("fetch", fetchMock);

    const { useLectorTask } = await loadHook();
    const { result } = renderHook(() => useLectorTask());

    await act(async () => {
      await result.current.startTask("第一个问题");
    });
    await act(async () => {
      await result.current.startTask("继续追问");
    });
    expect(posted[0].threadId).toBe(posted[1].threadId);
    expect(posted[0].runId).not.toBe(posted[1].runId);

    act(() => {
      result.current.resetSession();
    });
    expect(result.current.threadId).toBeNull();

    await act(async () => {
      await result.current.startTask("新会话");
    });
    expect(posted[2].threadId).not.toBe(posted[0].threadId);
  });
