import { useCallback, useEffect, useRef, useState } from "react";

import type { AguiEvent, TaskStartResponse } from "../types";

const MAX_RECONNECT_DELAY_MS = 4_000;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isAguiEvent(value: unknown): value is AguiEvent {
  return (
    isRecord(value) &&
    value.type === "monitor_event" &&
    typeof value.event === "string" &&
    typeof value.message === "string" &&
    isRecord(value.data) &&
    typeof value.timestamp === "string"
  );
}

function isTaskStartResponse(value: unknown): value is TaskStartResponse {
  return (
    isRecord(value) &&
    value.status === "started" &&
    typeof value.thread_id === "string" &&
    value.thread_id.length > 0
  );
}

async function responseError(response: Response): Promise<string> {
  try {
    const payload: unknown = await response.json();
    if (isRecord(payload) && typeof payload.detail === "string") {
      return payload.detail;
    }
  } catch {
    // The status text below is enough when the response is not JSON.
  }
  return response.statusText || `请求失败（${response.status}）`;
}

export function useGlobexTask() {
  const [threadId, setThreadId] = useState<string | null>(null);
  const [events, setEvents] = useState<AguiEvent[]>([]);
  const [finalAnswer, setFinalAnswer] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const mountedRef = useRef(true);
  const runningRef = useRef(false);
  const threadIdRef = useRef<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectAttemptRef = useRef(0);

  const clearConnection = useCallback(() => {
    if (reconnectTimerRef.current !== null) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    const socket = wsRef.current;
    wsRef.current = null;
    if (socket && socket.readyState !== WebSocket.CLOSED) {
      socket.close();
    }
  }, []);

  const finish = useCallback(() => {
    runningRef.current = false;
    setRunning(false);
    clearConnection();
  }, [clearConnection]);

  const connectWs: (threadId: string) => void = useCallback(
    (activeThreadId: string) => {
      if (!mountedRef.current || !runningRef.current) return;

      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const socket = new WebSocket(
        `${protocol}//${window.location.host}/ws/${encodeURIComponent(activeThreadId)}`,
      );
      wsRef.current = socket;

      socket.onopen = () => {
        reconnectAttemptRef.current = 0;
      };
      socket.onmessage = (message) => {
        try {
          const payload: unknown = JSON.parse(message.data);
          if (!isAguiEvent(payload)) return;
          setEvents((previous) => [...previous, payload]);

          if (payload.event === "task_result") {
            const answer = payload.data.final_answer;
            setFinalAnswer(typeof answer === "string" ? answer : "");
            finish();
          } else if (payload.event === "error") {
            setError(payload.message || "任务执行失败");
            finish();
          }
        } catch {
          setError("收到无法解析的事件");
        }
      };
      socket.onclose = () => {
        if (
          wsRef.current !== socket ||
          !mountedRef.current ||
          !runningRef.current
        ) {
          return;
        }
        const delay = Math.min(
          500 * 2 ** reconnectAttemptRef.current,
          MAX_RECONNECT_DELAY_MS,
        );
        reconnectAttemptRef.current += 1;
        reconnectTimerRef.current = setTimeout(
          () => connectWs(activeThreadId),
          delay,
        );
      };
      socket.onerror = () => {
        setError("事件连接暂时不可用，正在重连");
      };
    },
    [finish],
  );

  const startTask = useCallback(
    async (query: string, userId?: string) => {
      const trimmedQuery = query.trim();
      if (!trimmedQuery) {
        setError("请输入购物需求");
        return;
      }

      runningRef.current = false;
      clearConnection();
      setEvents([]);
      setFinalAnswer(null);
      setError(null);
      setThreadId(null);
      threadIdRef.current = null;
      runningRef.current = true;
      setRunning(true);

      try {
        const response = await fetch("/api/task", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query: trimmedQuery, user_id: userId }),
        });
        if (!response.ok) throw new Error(await responseError(response));
        const payload: unknown = await response.json();
        if (!isTaskStartResponse(payload)) {
          throw new Error("任务接口返回格式不正确");
        }
        threadIdRef.current = payload.thread_id;
        setThreadId(payload.thread_id);
        connectWs(payload.thread_id);
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "启动任务失败");
        finish();
      }
    },
    [clearConnection, connectWs, finish],
  );

  const cancelTask = useCallback(async () => {
    const activeThreadId = threadIdRef.current;
    if (!activeThreadId) return;
    try {
      const response = await fetch(`/api/task/${activeThreadId}/cancel`, {
        method: "POST",
      });
      if (!response.ok) throw new Error(await responseError(response));
      finish();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "取消任务失败");
    }
  }, [finish]);

  useEffect(
    () => () => {
      mountedRef.current = false;
      runningRef.current = false;
      clearConnection();
    },
    [clearConnection],
  );

  return {
    threadId,
    events,
    finalAnswer,
    running,
    error,
    startTask,
    cancelTask,
  };
}
