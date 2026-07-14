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

`web_search` 通过统一接口调用当前模型端的内置搜索，不需要独立搜索供应商或额外密钥。`auto` 当前会为 OpenAI 官方端点绑定 Responses API 的 `web_search` 工具；DeepSeek API 尚未提供可绑定的服务端内置搜索，因此会返回明确的 `unavailable` 状态。趋势研究会降级为数据不足，非同币种汇率不会使用模型猜测。`price_compare`、`exchange_rate` 和 `profit_calculator` 共用动态汇率结果及进程内缓存。

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

开发环境若通过 Java 网关访问，先复制 `frontend/.env.example` 为
`frontend/.env.local`。Vite 只在开发代理进程中读取 `LECTOR_API_KEY`，不会把它
打进浏览器 bundle。

## 本地完整栈

```bash
cp .env.example .env
# 至少设置 LLM_API_KEY；真实 Amazon 搜索还需设置 APIFY_API_TOKEN，并将 USE_MOCK=false
docker compose up --build
```

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
