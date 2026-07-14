import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import type { AguiEvent } from "../types";

const event = (
  name: string,
  data: Record<string, unknown> = {},
): AguiEvent => ({
  type: "monitor_event",
  event: name,
  message: `${name} message`,
  data,
  timestamp: "2026-07-03T10:20:30Z",
});

async function loadComponent() {
  return import("./EventStream");
}

describe("EventStream", () => {
  test("shows tutorial labels and event messages", async () => {
    const { EventStream } = await loadComponent();

    render(
      <EventStream
        events={[event("session_created"), event("tool_start"), event("task_result")]}
      />,
    );

    expect(screen.getByText("会话已创建")).toBeInTheDocument();
    expect(screen.getByText("工具开始")).toBeInTheDocument();
    expect(screen.getByText("任务完成")).toBeInTheDocument();
    expect(screen.getByText("tool_start message")).toBeInTheDocument();
  });

  test("shows fork demands", async () => {
    const { EventStream } = await loadComponent();
    render(<EventStream events={[event("fork", { demands: "search amazon" })]} />);

    expect(screen.getByText("search amazon")).toBeInTheDocument();
  });

  test("shows tool duration", async () => {
    const { EventStream } = await loadComponent();
    render(<EventStream events={[event("tool_end", { duration_ms: 125 })]} />);

    expect(screen.getByText("125 ms")).toBeInTheDocument();
  });

  test("falls back to the raw name for unknown events", async () => {
    const { EventStream } = await loadComponent();
    render(<EventStream events={[event("custom_event")]} />);

    expect(screen.getByText("custom_event")).toBeInTheDocument();
  });
});
