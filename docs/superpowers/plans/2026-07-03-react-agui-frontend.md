# React AGUI Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the tutorial React client that starts Globex tasks, consumes AGUI events, cancels work, and renders the final shopping answer.

**Architecture:** A Vite TypeScript app keeps protocol state inside `useGlobexTask`; presentational components receive typed data only. Vite proxies HTTP and WebSocket traffic to the chapter 15 FastAPI server.

**Tech Stack:** React 19, TypeScript, Vite, pnpm, react-markdown, Vitest, Testing Library, jsdom.

---

### Task 1: Frontend project and protocol types

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/index.html`
- Create: `frontend/src/types.ts`

- [ ] Configure Vite, Vitest, TypeScript and `/api` + `/ws` proxies.
- [ ] Define `AguiEvent`, task response and hook state types matching the backend wire format.
- [ ] Install dependencies with `pnpm --dir frontend install`.

### Task 2: Task lifecycle hook

**Files:**
- Create: `frontend/src/hooks/useGlobexTask.test.tsx`
- Create: `frontend/src/hooks/useGlobexTask.ts`
- Create: `frontend/src/test/setup.ts`

- [ ] Write failing tests for task creation, AGUI result/error handling, cancellation and cleanup.
- [ ] Run `pnpm --dir frontend test -- useGlobexTask`; expect missing-module failures.
- [ ] Implement the hook with one active socket, bounded reconnect backoff and safe payload parsing.
- [ ] Re-run the focused tests; expect all pass.

### Task 3: Event stream component

**Files:**
- Create: `frontend/src/components/EventStream.test.tsx`
- Create: `frontend/src/components/EventStream.tsx`

- [ ] Write failing tests for labels, fork demands, tool duration and unknown events.
- [ ] Run focused tests; expect missing-module failures.
- [ ] Implement typed event rendering without unsafe HTML.
- [ ] Re-run focused tests; expect all pass.

### Task 4: Application shell

**Files:**
- Create: `frontend/src/App.test.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/styles.css`

- [ ] Write failing tests for empty-submit prevention, send/cancel states and Markdown output.
- [ ] Run focused tests; expect missing-module failures.
- [ ] Implement the tutorial page and responsive minimal styling.
- [ ] Re-run focused tests; expect all pass.

### Task 5: Documentation and verification

**Files:**
- Modify: `README.md`
- Modify: `.gitignore`

- [ ] Document frontend install/dev/test/build commands and two-terminal startup.
- [ ] Run `pnpm --dir frontend test -- --run`; require zero failures.
- [ ] Run `pnpm --dir frontend build`; require a successful TypeScript/Vite build.
- [ ] Run backend `pytest` and `basedpyright` to detect regressions.
- [ ] Start the frontend locally, inspect it in Chrome, then stop servers and remove temporary outputs.

## Self-review

Every design requirement maps to one task. Hook and component names, event fields and proxy paths are consistent with the FastAPI contract. No implementation placeholders remain.
