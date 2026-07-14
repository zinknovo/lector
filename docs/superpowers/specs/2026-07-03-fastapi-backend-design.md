# FastAPI 后端闭环设计

## 目标

把第 15 章定义的后端协议落实到现有 Globex 项目：启动任务、订阅 AGUI 事件、取消任务、下载产物和上传参考图片。前端、鉴权、分布式任务和限流不在本次范围。

## 架构

- `app/api/server.py` 提供 FastAPI HTTP/WebSocket 路由，并持有进程内任务注册表。
- `app/api/connection.py` 管理每个线程的当前连接与有界事件缓存。monitor 上报的事件先缓存，再投递给在线连接，WebSocket 重连时按序补发。
- `app/api/monitor.py` 继续作为 AgentLoop 与传输层之间的唯一事件接口。
- `app/utils/path_utils.py` 统一验证线程 ID、文件名和目录边界。

## 接口行为

### 创建任务

`POST /api/task` 接收非空 `query`、可选 `thread_id` 和 `user_id`。未提供线程 ID 时生成 UUID。相同线程存在活跃任务时取消旧任务并注册新任务。旧任务结束时仅在注册表仍指向自身时清理，避免删除替换后的任务。

### WebSocket

`WS /ws/{thread_id}` 验证线程 ID，接受连接，先补发缓存事件，再发送 `session_created`。客户端发送 `ping` 时回复 `pong`。同一线程的新连接替换旧连接；旧连接断开不得移除新连接。

### 取消任务

`POST /api/task/{thread_id}/cancel` 仅取消仍运行的任务；不存在或已结束返回 404。

### 文件下载

`GET /api/files/{thread_id}/{filename}` 只允许读取该线程输出目录内的普通文件。路径穿越、目录和不存在文件均不返回内容。

### 文件上传

`POST /api/upload` 要求合法线程 ID、非空安全文件名，并仅接受 PNG/JPEG/WebP/GIF。按块读取，最大 10 MiB；超过限制或写入失败时删除部分文件。响应返回相对项目根目录的 POSIX 路径。

## 错误与事件

- AgentLoop 取消上报 `cancelled`；未处理异常上报 `internal_error`。
- 任务完成后的注册表清理由任务身份保护。
- 连接发送失败只移除对应旧连接，不影响重连后的连接。
- 事件缓存按线程限制为最近 200 条，避免无界内存增长。

## 测试

- 单元测试覆盖连接替换、事件缓存和发送失败清理。
- API 测试覆盖创建、替换、取消、WebSocket 心跳与补发。
- 文件测试覆盖正常上传下载、非法类型、超限、路径穿越和目录下载。
- 全量运行 pytest 与 basedpyright。

## 自检

本文无待定项；后端范围与第 15 章一致，前端明确留到第 16 章；所有安全和重连增强均有对应测试。
