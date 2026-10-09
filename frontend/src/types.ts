/** 前端渲染用的业务事件；由 AG-UI 事件投影而来（见 useLectorTask）。 */
export type LectorEvent = {
  /** AG-UI 事件类型：RUN_STARTED / TOOL_CALL_START / CUSTOM / ... */
  type: string;
  /** 业务事件名（UI 按此渲染）：session_created / tool_start / tool_end / fork / ... */
  event: string;
  message: string;
  data: Record<string, unknown>;
  timestamp: string;
};

export type LectorTaskState = {
  threadId: string | null;
  events: LectorEvent[];
  finalAnswer: string | null;
  running: boolean;
  error: string | null;
};
