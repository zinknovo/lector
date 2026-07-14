export type AguiEvent = {
  type: "monitor_event";
  event: string;
  message: string;
  data: Record<string, unknown>;
  timestamp: string;
};

export type TaskStartResponse = {
  status: "started";
  thread_id: string;
};

export type GlobexTaskState = {
  threadId: string | null;
  events: AguiEvent[];
  finalAnswer: string | null;
  running: boolean;
  error: string | null;
};
