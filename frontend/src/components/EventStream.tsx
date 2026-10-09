import type { LectorEvent } from "../types";

const EVENT_LABEL: Record<string, { icon: string; text: string }> = {
  session_created: { icon: "●", text: "会话已创建" },
  fork: { icon: "↗", text: "派发子 Agent" },
  tool_start: { icon: "▶", text: "工具开始" },
  tool_end: { icon: "✓", text: "工具完成" },
  task_result: { icon: "◆", text: "任务完成" },
  error: { icon: "!", text: "错误" },
  drift_signal: { icon: "≈", text: "漂移提示" },
  loop_detected: { icon: "↻", text: "重复调用提示" },
  injection_filtered: { icon: "⛨", text: "内容过滤" },
  tool_result_capped: { icon: "✂", text: "结果裁剪" },
  report_number_check: { icon: "№", text: "报告数字核验" },
  output_audit: { icon: "⛨", text: "输出脱敏" },
  evidence_mismatch: { icon: "≠", text: "证据口径修正" },
  task_incomplete: { icon: "!", text: "任务未完成" },
};

function textData(event: LectorEvent, key: string): string | null {
  const value = event.data[key];
  return typeof value === "string" && value ? value : null;
}

function numberData(event: LectorEvent, key: string): number | null {
  const value = event.data[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function EventStream({ events }: { events: LectorEvent[] }) {
  if (events.length === 0) {
    return <p className="event-empty">任务启动后，执行事件会显示在这里。</p>;
  }

  return (
    <div className="event-stream" aria-live="polite">
      {events.map((event, index) => {
        const label = EVENT_LABEL[event.event];
        const demands = event.event === "fork" ? textData(event, "demands") : null;
        const duration =
          event.event === "tool_end" ? numberData(event, "duration_ms") : null;

        return (
          <article
            className={`event-row event-${event.event}`}
            key={`${event.timestamp}-${event.event}-${index}`}
          >
            <time dateTime={event.timestamp}>{event.timestamp.slice(11, 19)}</time>
            <span className="event-icon" aria-hidden="true">
              {label?.icon ?? "·"}
            </span>
            <strong>{label?.text ?? event.event}</strong>
            <span className="event-message">{event.message}</span>
            {demands && <code>{demands}</code>}
            {duration !== null && <span className="event-duration">{duration} ms</span>}
          </article>
        );
      })}
    </div>
  );
}
