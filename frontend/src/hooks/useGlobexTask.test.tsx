import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

type MessageHandler = ((event: MessageEvent<string>) => void) | null;
type CloseHandler = ((event: CloseEvent) => void) | null;

class MockWebSocket {
  static instances: MockWebSocket[] = [];
  static readonly OPEN = 1;
  static readonly CLOSED = 3;

  readonly url: string;
  readyState = MockWebSocket.OPEN;
  onmessage: MessageHandler = null;
  onclose: CloseHandler = null;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  close() {
    this.readyState = MockWebSocket.CLOSED;
  }

  send() {}

  emit(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) } as MessageEvent<string>);
  }

  emitRaw(data: string) {
    this.onmessage?.({ data } as MessageEvent<string>);
  }

  disconnect() {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.({ code: 1006 } as CloseEvent);
  }
}

const okJson = (payload: unknown) =>
  Promise.resolve({
    ok: true,
    json: () => Promise.resolve(payload),
  } as Response);

async function loadHook() {
  return import("./useGlobexTask");
}

describe("useGlobexTask", () => {
  beforeEach(() => {
    MockWebSocket.instances = [];
    vi.stubGlobal("WebSocket", MockWebSocket);
    vi.stubGlobal("fetch", vi.fn(() => okJson({ status: "started", thread_id: "thread-1" })));
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  test("starts a task and opens its websocket", async () => {
    const { useGlobexTask } = await loadHook();
    const { result } = renderHook(() => useGlobexTask());

    await act(() => result.current.startTask("find a travel bag", "user-1"));

    expect(fetch).toHaveBeenCalledWith("/api/task", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: "find a travel bag", user_id: "user-1" }),
    });
    expect(result.current.threadId).toBe("thread-1");
    expect(result.current.running).toBe(true);
    expect(MockWebSocket.instances[0].url).toMatch(/\/ws\/thread-1$/);
  });

  test("stores task results and stops running", async () => {
    const { useGlobexTask } = await loadHook();
    const { result } = renderHook(() => useGlobexTask());
    await act(() => result.current.startTask("find a travel bag"));

    act(() => {
      MockWebSocket.instances[0].emit({
        type: "monitor_event",
        event: "task_result",
        message: "任务完成",
        data: { final_answer: "## 推荐清单" },
        timestamp: "2026-07-03T10:00:00Z",
      });
    });

    expect(result.current.events).toHaveLength(1);
    expect(result.current.finalAnswer).toBe("## 推荐清单");
    expect(result.current.running).toBe(false);
  });

  test("reports malformed websocket payloads without crashing", async () => {
    const { useGlobexTask } = await loadHook();
    const { result } = renderHook(() => useGlobexTask());
    await act(() => result.current.startTask("find a travel bag"));

    act(() => MockWebSocket.instances[0].emitRaw("not-json"));

    expect(result.current.error).toBe("收到无法解析的事件");
  });

  test("cancels the active task and closes the socket", async () => {
    const { useGlobexTask } = await loadHook();
    const { result } = renderHook(() => useGlobexTask());
    await act(() => result.current.startTask("find a travel bag"));

    await act(() => result.current.cancelTask());

    expect(fetch).toHaveBeenLastCalledWith("/api/task/thread-1/cancel", {
      method: "POST",
    });
    expect(result.current.running).toBe(false);
    expect(MockWebSocket.instances[0].readyState).toBe(MockWebSocket.CLOSED);
  });

  test("reconnects after an unexpected close while running", async () => {
    vi.useFakeTimers();
    const { useGlobexTask } = await loadHook();
    const { result } = renderHook(() => useGlobexTask());
    await act(() => result.current.startTask("find a travel bag"));

    act(() => MockWebSocket.instances[0].disconnect());
    await act(() => vi.advanceTimersByTimeAsync(500));

    expect(MockWebSocket.instances).toHaveLength(2);
  });

  test("rejects an empty query before calling the API", async () => {
    const { useGlobexTask } = await loadHook();
    const { result } = renderHook(() => useGlobexTask());

    await act(() => result.current.startTask("   "));

    expect(fetch).not.toHaveBeenCalled();
    expect(result.current.error).toBe("请输入选品需求");
  });

  test("closes the socket when unmounted", async () => {
    const { useGlobexTask } = await loadHook();
    const { result, unmount } = renderHook(() => useGlobexTask());
    await act(() => result.current.startTask("find a travel bag"));

    unmount();

    await waitFor(() => {
      expect(MockWebSocket.instances[0].readyState).toBe(MockWebSocket.CLOSED);
    });
  });
});
