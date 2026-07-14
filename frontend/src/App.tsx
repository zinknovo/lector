import { FormEvent, useState } from "react";
import ReactMarkdown from "react-markdown";

import { EventStream } from "./components/EventStream";
import { useGlobexTask } from "./hooks/useGlobexTask";

export default function App() {
  const {
    threadId,
    events,
    finalAnswer,
    running,
    error,
    startTask,
    cancelTask,
  } = useGlobexTask();
  const [query, setQuery] = useState("");

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!query.trim() || running) return;
    void startTask(query, "demo-user");
  };

  return (
    <main className="app-shell">
      <header className="hero">
        <p className="eyebrow">AGENTIC COMMERCE</p>
        <h1>Globex 跨境购物 Agent</h1>
        <p className="hero-copy">
          描述预算、材质和风格偏好，实时查看 Agent 的检索、分派与筛选过程。
        </p>
      </header>

      <form className="query-panel" onSubmit={submit}>
        <label htmlFor="shopping-query">购物需求</label>
        <textarea
          id="shopping-query"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="例如：想买便宜又抗造的旅行三件套，预算 300，不要塑料，偏好小众设计"
          disabled={running}
          rows={4}
        />
        <div className="query-actions">
          <span className="thread-status">
            {threadId ? `会话 ${threadId.slice(0, 8)}` : "等待新任务"}
          </span>
          {running ? (
            <button className="button button-danger" type="button" onClick={() => void cancelTask()}>
              取消任务
            </button>
          ) : (
            <button className="button button-primary" type="submit" disabled={!query.trim()}>
              发送
            </button>
          )}
        </div>
      </form>

      {error && <p className="error-banner" role="alert">{error}</p>}

      <section className="panel" aria-labelledby="event-heading">
        <div className="section-heading">
          <div>
            <p className="section-kicker">LIVE TRACE</p>
            <h2 id="event-heading">执行过程</h2>
          </div>
          {running && <span className="running-indicator">运行中</span>}
        </div>
        <EventStream events={events} />
      </section>

      {finalAnswer && (
        <article className="panel final-answer">
          <div className="section-heading">
            <div>
              <p className="section-kicker">RESULT</p>
              <h2>购物清单</h2>
            </div>
          </div>
          <div className="markdown-body">
            <ReactMarkdown>{finalAnswer}</ReactMarkdown>
          </div>
        </article>
      )}
    </main>
  );
}
