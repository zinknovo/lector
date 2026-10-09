# Lector

Lector 是基于 FastAPI、LangGraph 和 LangChain 构建的电商选品 Agent。它保留 ReAct 自由编排能力，通过结构化工具完成：

1. `discover`：发现潜力品类和需求缺口。
2. `filter`：搜索、比价、物流成本估算和候选初筛。
3. `full_chain`：利润计算、供应商风险评估、统一决策和选品报告。

业务指标由工具计算，LLM 只负责工具编排和报告表达。最终 `SelectionDecision` 同时包含综合评分、置信度、利润、物流、供应商风险及缺失数据。

## 数据源

- `MockProductDataSource`：25 条跨品类数据，本地和 CI 默认可用。
- `ApifyAmazonDataSource`：通过 `automation-lab/amazon-scraper` 获取 Amazon 商品。
- `ProductSearchCache`：可选 MongoDB 缓存，默认 TTL 7 天；连接不可用时静默降级。

## 安装

```bash
uv sync
```

复制 `.env.example` 为 `.env`，按需配置：

```dotenv
LLM_API_KEY=
LLM_MODEL_NAME=
LLM_BASE_URL=
APIFY_API_TOKEN=
USE_MOCK=true
MONGODB_URL=
LLM_WEB_SEARCH_BACKEND=auto
```

`web_search` 通过统一接口调用当前模型端的内置搜索，不需要独立搜索供应商或额外密钥。`auto` 会为 OpenAI 官方端点绑定 Responses API 的 `web_search` 工具；DeepSeek 官方端点则复用同一个 Key，仅将搜索请求发送到 DeepSeek 的 Anthropic 兼容 Messages API，普通推理仍走现有 Chat Completions 接口。
趋势研究、`market_price_search`、`price_compare`、`exchange_rate` 和 `profit_calculator` 共用搜索证据及进程内汇率缓存。

启用 OpenAI 内置搜索时，沿用现有 LLM 配置：

```dotenv
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL_NAME=gpt-5
LLM_API_KEY=
LLM_WEB_SEARCH_BACKEND=auto
```

## 品类知识库

`category_insight` 从 MongoDB 的 `category_cards` 集合读取经过审核的结构化卡片。准备好 `data/category_cards.jsonl` 后执行：

```bash
uv run python scripts/build_category_kb.py
```

构建脚本会逐行校验 `CategoryCard`、过滤低置信度数据、归一化品类名，并按 `card_id` 幂等写入 MongoDB。工具层只依赖 `CategoryKnowledgeStore` 接口，后续可以增加新的检索后端而不改工具签名。

## 三阶段 Demo

```bash
uv run python scripts/demo_selection_pipeline.py
```

Demo 使用 Mock 商品完成趋势发现、候选筛选、利润测算、供应商评估、统一决策和最终报告。

## 证据链（每个关键数字的出处）

关键数字在产生它的工具里就以「证据」形式记录：方法（实测 / 提取 / 估算 / 查表 / 缺失）、
来源、置信度与观察时间，写入会话目录 `output/<thread_id>/evidence.jsonl`：

- `procurement_quote` → `procurement_cost_cny`（区分 1688 搜索提取与售价比例估算）
- `market_price_search` → `selling_price_evidence`
- `exchange_rate` → `exchange_rate`；`shipping_calc` → `landed_cost_cny`（按商品）

`selection_decision` 读取证据库：门禁使用的置信度**以库中值为准**（模型转述值仅作对照，
不一致时发 `evidence_mismatch` 事件），并把证据随决策透传到报告；PDF/XLSX 报告附带
「证据与口径」一览（XLSX 为独立「证据」页）。`item_picker` 输出 `excluded` 结构化排除原因。

报告文案另做轻量核验：文本中出现的金额 / 百分比必须能在决策或证据中找到对应，
否则记入 `unverified_numbers` 并发事件（不阻断输出）。

## 运行时守护（Harness）

工具边界与轮次边界的护栏由 LangChain 原生 `AgentMiddleware` 承载（`app/agent/harness.py`）：

- **工具返回后**：L3 注入过滤（命中片段替换为占位符）→ 结果体积治理（结构化裁剪，
  保持 JSON 合法）→ 循环检测（同工具 + 同参数 + 同结果指纹，默认窗口 6、阈值 3）
  → 漂移观察
- **模型调用前**：压缩旧工具结果（决策 / 报告消息受保护，证据类结果放宽阈值），
  并注入上一轮排队的收敛 / 漂移提示
- **会话结束**：最终回复过 L4 输出脱敏（密钥、数据库地址、本机路径）

漂移检测为四类规则信号（默认开启，`LECTOR_DRIFT_DETECT=0` 关闭）：已声明的市场 /
预算约束被违背、连续低重合度查询、连续空检索、工具结果体积异常增大；命中只注入提示
并记事件，不改写本轮回复。

## 业务准确性与评测交付

为了让“选得好不好”更贴近跨境卖家的业务语义，系统在 `selection_decision` 做了证据质量门禁：

- 当采购价置信度过低（疑似估算）时，不会把结果直接升级到 `recommend`（取值来自证据库）
- 当 `market_price_search` 的售价证据质量过低时，不会直接 `recommend`
- 当品类语义不匹配时，会强制降级（至少避免“品类不对但利润看起来不错”的误导）

评测分两层，都是确定性、无外部依赖：

```bash
# 决策门禁 + 证据完整性（用例可携带 evidence 种子与 evidence_fields 断言）
uv run python scripts/run_eval.py --failures-out eval/failures/decisions.yaml

# 品类知识召回评测：Recall@K / MRR / NDCG@K + 门禁（标注集 + 内存索引）
uv run python scripts/run_recall_eval.py

uv run pytest tests/test_eval_harness.py tests/test_recall_eval.py -q
```

## API Server

```bash
uv run uvicorn app.api.server:app --host 0.0.0.0 --port 8000
```

标准 AG-UI 远端接口（前端主链路；POST + SSE，事件带 `id: {run_id}:{seq}` 游标）：

- `POST /ag-ui/run`（RunAgentInput，返回 SSE；支持 `Last-Event-ID` 续传）
- `GET /ag-ui/runs/{run_id}/events?after=N`（断线后按游标重放）
- `GET /ag-ui/runs/{run_id}` / `POST /ag-ui/runs/{run_id}/cancel`

兼容与文件接口：

- `POST /api/task`、`WS /ws/{thread_id}`（旧传输，保留兼容）
- `POST /api/task/{thread_id}/cancel`
- `GET /api/files/{thread_id}/{filename}`
- `POST /api/upload?thread_id=...`

## React Frontend

前端通过官方 `@ag-ui/client` 连接 `POST /ag-ui/run`（SSE），断线时按事件游标恢复，
组件只渲染结构化事件（不从模型文案解析数字）。

```bash
pnpm --dir frontend install
pnpm --dir frontend dev
```

开发环境若通过 Java 网关访问，先复制 `frontend/.env.example` 为
`frontend/.env.local`。Vite 只在开发代理进程中读取 `LECTOR_API_KEY`，不会把它
打进浏览器 bundle。

## 本地完整栈

```bash
cp .env.example .env
# 至少设置 LLM_API_KEY；真实 Amazon 搜索还需设置 APIFY_API_TOKEN，并将 USE_MOCK=false
docker compose up --build
```

成本模型说明：

- 头程/税率分档由 `shipping_calc` 使用：`app/recall/shipping.py` + `app/recall/duty.py`
- 默认表写在 `data/cost_tables.json`
- 可通过 `LECTOR_COST_TABLES_PATH=/path/to/cost_tables.json` 覆盖（例如你们后续扩展到 CA/UK/EU 等目的地时）

服务入口：前端 `http://127.0.0.1:5173`，Java 网关 `http://127.0.0.1:8080`，
内部 Python Agent `http://127.0.0.1:8000`。MongoDB 由 Compose 启动，同时存储
Amazon 搜索缓存和结构化品类知识。默认栈共四个服务：MongoDB、Agent、Gateway、Frontend。

完整部署、严格外部检查和报告导出命令见
[`docs/production-readiness.md`](docs/production-readiness.md)。

## 验证

```bash
uv run pytest
uv run basedpyright app tests scripts
pnpm --dir frontend test -- --run
pnpm --dir frontend build
mvn -f lector-api/pom.xml test
docker compose config --quiet
```
