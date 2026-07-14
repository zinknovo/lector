# Globex Agent

Minimal uv-based Python environment for practicing agents with DeepSeek's
OpenAI-compatible chat API.

## Setup

```bash
uv sync
```

The placeholder DeepSeek settings are in `.env` and mirrored in `.env.example`.

## Smoke Test

```bash
uv run python -m app.agent.main "用一句话介绍 agent"
```

## API Server

```bash
uv run uvicorn app.api.server:app --host 0.0.0.0 --port 8000
```

The chapter 15 backend exposes:

- `POST /api/task` — start an AgentLoop task.
- `WS /ws/{thread_id}` — subscribe to replayable AGUI events.
- `POST /api/task/{thread_id}/cancel` — cancel a running task.
- `GET /api/files/{thread_id}/{filename}` — download a session artifact.
- `POST /api/upload?thread_id=...` — upload a reference image (10 MiB maximum).

## React Frontend

Install and start the chapter 16 AGUI client:

```bash
pnpm --dir frontend install
pnpm --dir frontend dev
```

Run the API server in a second terminal. Open `http://localhost:5173`; Vite proxies
`/api` and `/ws` to `http://127.0.0.1:8000`.

Frontend checks:

```bash
pnpm --dir frontend test -- --run
pnpm --dir frontend build
```

## Tests

```bash
uv run pytest
```
