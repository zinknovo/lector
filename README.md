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
```

## 三阶段 Demo

```bash
uv run python scripts/demo_selection_pipeline.py
```

Demo 使用 Mock 商品完成趋势发现、候选筛选、利润测算、供应商评估、统一决策和最终报告。

## API Server

```bash
uv run uvicorn app.api.server:app --host 0.0.0.0 --port 8000
```

主要接口：

- `POST /api/task`
- `WS /ws/{thread_id}`
- `POST /api/task/{thread_id}/cancel`
- `GET /api/files/{thread_id}/{filename}`
- `POST /api/upload?thread_id=...`

## React Frontend

```bash
pnpm --dir frontend install
pnpm --dir frontend dev
```

## 验证

```bash
uv run pytest
pnpm --dir frontend test -- --run
pnpm --dir frontend build
```
