import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  useGlobexTask: vi.fn(),
  startTask: vi.fn(),
  cancelTask: vi.fn(),
}));

vi.mock("./hooks/useGlobexTask", () => ({ useGlobexTask: mocks.useGlobexTask }));

async function loadApp() {
  return import("./App");
}

describe("App", () => {
  beforeEach(() => {
    mocks.startTask.mockReset();
    mocks.cancelTask.mockReset();
    mocks.useGlobexTask.mockReturnValue({
      threadId: null,
      events: [],
      finalAnswer: null,
      running: false,
      error: null,
      startTask: mocks.startTask,
      cancelTask: mocks.cancelTask,
    });
  });

  afterEach(() => cleanup());

  test("prevents empty submissions and sends the entered query", async () => {
    const { default: App } = await loadApp();
    const user = userEvent.setup();
    render(<App />);
    const send = screen.getByRole("button", { name: "发送" });

    expect(send).toBeDisabled();
    await user.type(screen.getByLabelText("购物需求"), "旅行收纳三件套");
    expect(send).toBeEnabled();
    await user.click(send);

    expect(mocks.startTask).toHaveBeenCalledWith("旅行收纳三件套", "demo-user");
  });

  test("shows cancel while a task is running", async () => {
    mocks.useGlobexTask.mockReturnValue({
      threadId: "thread-1",
      events: [],
      finalAnswer: null,
      running: true,
      error: null,
      startTask: mocks.startTask,
      cancelTask: mocks.cancelTask,
    });
    const { default: App } = await loadApp();
    const user = userEvent.setup();
    render(<App />);

    expect(screen.getByRole("button", { name: "取消任务" })).toBeInTheDocument();
    expect(screen.getByLabelText("购物需求")).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "取消任务" }));

    expect(mocks.cancelTask).toHaveBeenCalledOnce();
  });

  test("renders markdown without enabling raw HTML", async () => {
    mocks.useGlobexTask.mockReturnValue({
      threadId: "thread-1",
      events: [],
      finalAnswer: "<script>alert('x')</script>\n\n## 推荐清单",
      running: false,
      error: null,
      startTask: mocks.startTask,
      cancelTask: mocks.cancelTask,
    });
    const { default: App } = await loadApp();
    const { container } = render(<App />);

    expect(screen.getByRole("heading", { name: "推荐清单" })).toBeInTheDocument();
    expect(container.querySelector("script")).toBeNull();
  });

  test("shows task errors", async () => {
    mocks.useGlobexTask.mockReturnValue({
      threadId: null,
      events: [],
      finalAnswer: null,
      running: false,
      error: "后端不可用",
      startTask: mocks.startTask,
      cancelTask: mocks.cancelTask,
    });
    const { default: App } = await loadApp();
    render(<App />);

    expect(screen.getByRole("alert")).toHaveTextContent("后端不可用");
  });
});
