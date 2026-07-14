# Globex Agent 系统设计文档

## 1. 项目定位

Globex 是一个跨境电商购物 Agent 后端。用户用自然语言描述购物需求，系统通过 LLM 编排工具调用，最终给出不超过 3 件商品的推荐清单，并附选购理由。

核心能力：

- 意图拆解（Planner）
- 多平台商品检索（ItemSearch）
- 跨平台比价（PriceCompare）
- 关税 / 运费估算（ShippingCalc）
- 子 Agent 并行派发（dispatch_tool）
- 实时事件推送到前端（WebSocket）

## 2. 分层架构

```
┌────────────────────────────────────────────┐
│  API 入口层                                  │
│  FastAPI HTTP + WebSocket 路由              │
│  - 接收用户 query，创建 thread_id           │
│  - WebSocket /ws/{thread_id} 连接前端       │
├────────────────────────────────────────────┤
│  编排层（Agent Loop）                        │
│  app/agent/main.py / 主 LangGraph           │
│  - Think → Act → Observe → Reflect          │
│  - 决定调用工具或 dispatch_tool 派子 Agent   │
├────────────────────────────────────────────┤
│  工具层                                      │
│  app/agent/*_tool.py                        │
│  - item_search / price_compare / shipping_calc│
│  - dispatch_tool（特殊：派生子 Agent）       │
│  - 每个工具独立、可单独测试                  │
├────────────────────────────────────────────┤
│  模型层                                      │
│  app/agent/llm.py                           │
│  - get_llm：主 / 子 Agent 共用              │
│  - get_judge_llm：评测用强模型              │
├────────────────────────────────────────────┤
│  提示词层                                    │
│  app/agent/prompts.py + app/prompt/prompts.yml│
│  - system_prompt / planner_prompt / shopping_summary_prompt│
├────────────────────────────────────────────┤
│  上下文层                                    │
│  app/api/context.py                         │
│  - ContextVar 保存 thread_id / session_dir   │
│  - thread_scope 上下文管理器                 │
├────────────────────────────────────────────┤
│  事件推送层                                  │
│  app/api/connection.py / monitor.py         │
│  - ConnectionManager：管理 WebSocket 连接    │
│  - Monitor：工具开始 / 结束、fork、结果、错误 │
├────────────────────────────────────────────┤
│  基础设施层                                  │
│  app/utils/path_utils.py                    │
│  - 会话目录、上传目录、安全拼路径            │
└────────────────────────────────────────────┘
```

依赖方向：上层可以调下层，下层不依赖上层。

## 3. 关键设计决策

| 决策 | 选择 | 理由 |
|---|---|---|
| 同步 vs 异步 | 全异步 | IO 密集（等 LLM、等搜索 API），asyncio 适合 |
| 状态传递 | ContextVar | 避免把 thread_id / session_dir 层层传参 |
| 会话文件 | 本地文件系统 | 简单、可审计、适合原型；后期可换对象存储 |
| 实时事件 | WebSocket | 双向通信，后续可扩展为前端 also 发消息 |
| 子 Agent | dispatch_tool fork | 并行检索、上下文隔离、调用链深时拆分 |
| 缓存 LLM 实例 | `@lru_cache(maxsize=1)` | 避免重复创建 client |
| 工具输出 | Pydantic BaseModel | 结构化 schema，LLM 按固定格式消费 |

## 4. 数据流

以用户请求 "我想买 500 块以内的帆布包" 为例：

1. 前端 `POST /task {query}`
2. 后端生成 `thread_id`，创建 `session_dir`
3. `run_agent(query, thread_id)` 进入 `thread_scope`
4. `main_agent.ainvoke(...)` 开始 ReAct 循环
5. Agent 调用工具（如 `item_search`）
   - `monitor.report_tool_start(...)`
   - 实际搜索
   - `monitor.report_tool_end(...)`
6. 工具返回观察结果，Agent Reflect
7. 信息足够 → `ShoppingSummary` → 最终答案
8. `monitor.report_task_result(final_answer)`
9. 结果通过 WebSocket 推送到 `/ws/{thread_id}`

## 5. 组件说明

### 5.1 app/agent/llm.py

- `get_llm()`：主 / 子 Agent 共用的大模型，temperature 0.3
- `get_judge_llm()`：评测用强模型，默认 `qwen-max`，temperature 0.0
- 使用 `init_chat_model` + `@lru_cache` 缓存实例

### 5.2 app/api/context.py

- `_thread_id_var` / `_session_dir_var`：ContextVar，请求级隔离
- `set_thread_context()`：入口写入上下文
- `get_thread_id()` / `get_session_dir()`：读取当前上下文
- `thread_scope()`：上下文管理器，离开作用域自动 `reset`

### 5.3 app/utils/path_utils.py

- `PROJECT_ROOT` / `UPLOAD_ROOT` / `OUTPUT_ROOT`
- `ensure_session_dir(thread_id)`：创建 `output/{thread_id}/`
- `ensure_upload_dir(thread_id)`：创建 `uploaded/{thread_id}/`
- `safe_join(base, *parts)`：拼路径后校验前缀，防止 `../` 越权

### 5.4 app/api/connection.py

- `ConnectionManager`：维护 `active: dict[str, WebSocket]`
- `connect()` / `disconnect()`：注册 / 注销连接
- `send_to_thread()`：按 thread_id 推送 JSON 事件
- `disconnect()` 用 `is websocket` 判断对象身份，防止刷新时旧连接误删新连接

### 5.5 app/api/monitor.py

- `Monitor._emit()`：构造事件 payload，通过 ConnectionManager 推送
- `report_tool_start()` / `report_tool_end()`：工具生命周期
- `report_fork()`：派发子 Agent
- `report_task_result()`：任务完成
- `report_error()`：异常上报
- `thread_id is None` 时静默丢弃，兼容离线脚本调用

### 5.6 app/agent/dispatch_tool.py

- `@tool dispatch_tool(demands: str)`：派发同质子 Agent
- 生成 `sub_thread_id`，在 `thread_scope` 内调用 `sub_agent.ainvoke()`
- 保留 `session_dir`，只切换 `thread_id`

### 5.7 app/agent/item_search.py

- `Candidate`：单个商品候选结构
- `ItemSearchOutput`：固定四字段返回结构
- `item_search(...)`：`@tool` 装饰，返回 `ItemSearchOutput`
- `actual_search(...)`：真实搜索占位实现

### 5.8 app/agent/prompts.py

- `_load_prompts()`：从 `prompts.yml` 加载并缓存
- `get_system_prompt()` / `get_planner_prompt()` / `get_shopping_summary_prompt()`

## 6. 边界与异常处理

- **重连身份判断**：`disconnect` 用 `is websocket` 判断，防止刷新时旧连接误删新连接
- **路径越权**：`safe_join` 用 `.resolve()` 后校验前缀
- **上下文还原**：所有 `ContextVar.set()` 必须在 `finally` 里 `reset`
- **无上下文静默丢弃**：monitor 在 `thread_id is None` 时不抛错
- **WebSocket 发送失败**：自动触发 disconnect 清理

## 7. 尚未实现（占位）

- `sub_agent` 实例（`app/agent/dispatch_tool.py`）
- `main_agent` 实例（`app/agent/main.py`）
- `actual_search` 真实搜索逻辑（`app/agent/item_search.py`）
- FastAPI HTTP / WebSocket 路由

## 8. 测试策略

- 单元测试：每个工具独立测，mock LLM / 搜索 API
- 集成测试：一条完整请求从 `/task` 到 WebSocket 事件
- 边界测试：重连、上下文泄漏、路径越权
