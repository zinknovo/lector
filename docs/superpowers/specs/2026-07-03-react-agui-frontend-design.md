# React AGUI 前端设计

## 目标与范围

在 `frontend/` 新建可独立运行的 React + TypeScript 应用，消费第 15 章 FastAPI 服务的任务与 AGUI WebSocket 协议，完成“输入购物需求 → 查看执行事件 → 展示最终清单 → 可取消任务”的浏览器闭环。

本次实现教程要求的单页应用，不加入登录、路由、多会话列表、复杂主题、动画系统或生产部署配置。

## 技术栈

- Vite、React、TypeScript、pnpm
- `react-markdown` 安全渲染 Agent 返回的 Markdown
- Vitest、Testing Library、jsdom
- Vite HTTP/WebSocket 代理连接本地 FastAPI `http://127.0.0.1:8000`

## 模块设计

### `useGlobexTask`

Hook 是协议与状态的唯一入口，维护 `threadId`、`events`、`finalAnswer`、`running` 和用户可见错误。`startTask` 校验非空输入后调用 `POST /api/task`，成功后连接 `/ws/{thread_id}`。收到 `monitor_event` 后追加事件；`task_result` 保存最终回答并结束运行；`error` 保存错误并结束运行。

WebSocket 地址根据当前页面协议自动选择 `ws` 或 `wss`。连接异常关闭时，仅在任务仍运行且组件仍挂载时重连，使用有上限的退避延迟；新任务、完成、取消和卸载都会清理旧连接与重连计时器，避免 stale closure 和重复连接。

### `EventStream`

按时间顺序渲染六类教程事件：`session_created`、`fork`、`tool_start`、`tool_end`、`task_result`、`error`。每条记录显示时间、标签与消息；fork 展示 demands，tool_end 展示耗时。未知事件使用原始事件名，不导致页面崩溃。

### `App`

单页由标题、查询输入区、发送/取消按钮、状态提示、事件流和最终清单组成。运行时禁止再次提交；空输入不可发送。最终回答使用 `react-markdown` 渲染，不启用原始 HTML。

## 数据流与错误处理

1. 用户提交查询。
2. Hook 清理上一次任务状态并请求创建任务。
3. HTTP 返回 thread ID 后建立 WebSocket。
4. AGUI 事件驱动事件流和最终清单更新。
5. HTTP 非 2xx、JSON 结构异常、WebSocket 消息格式错误只转成用户可见错误，不抛出到 React 渲染层。
6. 取消请求成功后关闭连接并结束运行；取消失败显示错误并保留当前状态供用户判断。

## 开发代理

Vite 将 `/api` 代理到 `http://127.0.0.1:8000`，将 `/ws` 代理到同一服务并启用 WebSocket。前端启动命令为 `pnpm --dir frontend dev`，后端保持 README 中的 uvicorn 命令。

## 测试与验收

- Hook 测试：启动请求、WebSocket 事件、最终结果、错误、取消和卸载清理。
- 组件测试：事件标签、fork demands、工具耗时、Markdown 安全渲染、按钮状态。
- 静态验证：TypeScript 编译与 Vite 生产构建。
- 浏览器验收：启动前后端后确认页面可加载、输入可提交、事件区与空状态布局正常。

## 自检

规格无待定项和占位符。前后端路径与已实现 FastAPI 协议一致；教程要求全部覆盖，扩展仅限可靠性、安全渲染和自动化测试。
