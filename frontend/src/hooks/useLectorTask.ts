import type { BaseEvent } from "@ag-ui/core";
import { HttpAgent } from "@ag-ui/client";
import { useCallback, useEffect, useRef, useState } from "react";

import { recoveringFetch } from "../lib/recoveringFetch";
import type { LectorEvent } from "../types";

const RECONNECT_NOTICE = "事件连接中断，正在恢复已保存的进度";

function lastAssistantText(event: BaseEvent): string | null {
  const messages = (event as { messages?: unknown }).messages;
  if (!Array.isArray(messages) || messages.length === 0) return null;
  const last = messages[messages.length - 1] as { content?: unknown; role?: unknown };
  return last?.role === "assistant" && typeof last.content === "string" ? last.content : null;
}

export function useLectorTask() {
  const [threadId, setThreadId] = useState<string | null>(null);
  const [events, setEvents] = useState<LectorEvent[]>([]);
  const [finalAnswer, setFinalAnswer] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const agentRef = useRef<HttpAgent | null>(null);
  const runIdRef = useRef<string | null>(null);
  const threadIdRef = useRef<string | null>(null);
  const noticeRef = useRef<string | null>(null);
  const mountedRef = useRef(true);

  const pushEvent = useCallback(
    (type: string, event: string, message: string, data: Record<string, unknown>) => {
      if (!mountedRef.current) return;
      setEvents((previous) => [
        ...previous,
        { type, event, message, data, timestamp: new Date().toISOString() },
      ]);
    },
    [],
  );

  const handleCustom = useCallback(
    (name: string, value: Record<string, unknown>) => {
      if (name === "activity.upsert") {
        if (value.kind === "tool" && value.status === "completed") {
          const duration = value.durationMs;
          pushEvent("CUSTOM", "tool_end", `${String(value.label ?? value.toolName)} 完成`, {
            tool_name: value.toolName,
            ...(typeof duration === "number" ? { duration_ms: duration } : {}),
          });
        }
        return;
      }
      if (name === "fork") {
        pushEvent("CUSTOM", "fork", "派发子 Agent", {
          demands: value.demands,
          sub_thread_id: value.subThreadId,
        });
        return;
      }
      const message = typeof value.message === "string" && value.message ? value.message : name;
      pushEvent("CUSTOM", name, message, value);
    },
    [pushEvent],
  );

  const handleAguiEvent = useCallback(
    (event: BaseEvent) => {
      switch (event.type) {
        case "RUN_STARTED":
          pushEvent("RUN_STARTED", "session_created", "会话已创建", {});
          break;
        case "TOOL_CALL_START": {
          const name = String((event as { toolCallName?: unknown }).toolCallName ?? "tool");
          pushEvent("TOOL_CALL_START", "tool_start", `正在调用 ${name}`, {
            tool_name: name,
          });
          break;
        }
        case "CUSTOM": {
          const custom = event as { name?: string; value?: unknown };
          const value =
            typeof custom.value === "object" && custom.value !== null
              ? (custom.value as Record<string, unknown>)
              : {};
          handleCustom(String(custom.name ?? "notice"), value);
          break;
        }
        case "MESSAGES_SNAPSHOT": {
          const text = lastAssistantText(event);
          if (text !== null) setFinalAnswer(text);
          break;
        }
        case "RUN_ERROR": {
          const message = String((event as { message?: unknown }).message ?? "任务执行失败");
          setError(message);
          break;
        }
        case "RUN_FINISHED":
          setRunning(false);
          break;
        default:
          break;
      }
    },
    [handleCustom, pushEvent],
  );

  const startTask = useCallback(
    async (query: string, userId = "demo-user") => {
      const trimmed = query.trim();
      if (!trimmed) {
        setError("请输入选品需求");
        return;
      }
      setEvents([]);
      setFinalAnswer(null);
      setError(null);
      noticeRef.current = null;

      // 同一页面会话内的追问沿用同一个 thread：服务端按会话 checkpoint 延续。
      const thread = threadIdRef.current ?? crypto.randomUUID();
      const runId = crypto.randomUUID();
      threadIdRef.current = thread;
      setThreadId(thread);
      runIdRef.current = runId;
      setRunning(true);

      const agent = new HttpAgent({
        url: "/ag-ui/run",
        threadId: thread,
        initialMessages: [{ id: crypto.randomUUID(), role: "user", content: trimmed }],
        fetch: recoveringFetch(globalThis.fetch, {
          runId,
          eventsUrl: `/ag-ui/runs/${runId}/events`,
          onReconnect: () => {
            if (!mountedRef.current) return;
            noticeRef.current = RECONNECT_NOTICE;
            setError(RECONNECT_NOTICE);
          },
          onConnected: () => {
            if (!mountedRef.current) return;
            if (noticeRef.current === RECONNECT_NOTICE) {
              noticeRef.current = null;
              setError(null);
            }
          },
        }),
      });
      agentRef.current = agent;

      try {
        await agent.runAgent(
          { runId, forwardedProps: { userId } },
          { onEvent: ({ event }) => handleAguiEvent(event as BaseEvent) },
        );
      } catch (cause) {
        const aborted = cause instanceof DOMException && cause.name === "AbortError";
        if (!aborted && mountedRef.current) {
          setError(cause instanceof Error ? cause.message : "任务执行失败");
        }
      } finally {
        if (mountedRef.current) setRunning(false);
      }
    },
    [handleAguiEvent],
  );

  const resetSession = useCallback(() => {
    agentRef.current?.abortRun();
    threadIdRef.current = null;
    runIdRef.current = null;
    setThreadId(null);
    setEvents([]);
    setFinalAnswer(null);
    setError(null);
    setRunning(false);
  }, []);

  const cancelTask = useCallback(async () => {
    const runId = runIdRef.current;
    agentRef.current?.abortRun();
    if (runId) {
      await fetch(`/ag-ui/runs/${encodeURIComponent(runId)}/cancel`, {
        method: "POST",
      }).catch(() => undefined);
    }
    setRunning(false);
  }, []);

  useEffect(
    () => () => {
      mountedRef.current = false;
      agentRef.current?.abortRun();
    },
    [],
  );

  return {
    threadId,
    events,
    finalAnswer,
    running,
    error,
    startTask,
    cancelTask,
    resetSession,
  };
}
