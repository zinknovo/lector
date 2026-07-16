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
        <p className="eyebrow">LECTOR</p>
        <h1>Lector 电商选品 Agent</h1>
        <p className="hero-copy">
          描述目标市场与品类；默认中国货源卖海外站，实时查看发现、筛选与决策全链路。
        </p>
      </header>

      <form className="query-panel" onSubmit={submit}>
        <label htmlFor="shopping-query">选品需求</label>
        <textarea
          id="shopping-query"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="例如：美国站卖紫砂保温杯，中国货源，目标毛利 30%，给出 Top 候选与建议"
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
              <h2>选品报告</h2>
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
