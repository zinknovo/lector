# Lector 本地部署与外部能力验收

## 1. 配置边界

复制示例配置并填写真实密钥：

```bash
cp .env.example .env
```

- `.env` 已被 Git 和 Docker build context 排除，不要把密钥写入示例文件。
- `USE_MOCK=true` 只验证本地工具链；真实 Amazon 验收需设置
  `APIFY_API_TOKEN` 并改为 `USE_MOCK=false`。
- `LLM_WEB_SEARCH_BACKEND=auto` 使用模型服务端内置搜索接口，不引入 Tavily 等
  独立 Provider。当前后端不支持内置搜索时，检查会明确返回 `skipped` 或 `fail`，
  不会伪造结果。
- `LECTOR_API_KEY` 是 Java 网关与反向代理之间的共享密钥。Compose 未设置时仅使用
`local-dev-only` 作为本机默认值。Compose 的所有端口只绑定 `127.0.0.1`；它是
本机开发拓扑，不得原样部署到共享环境。共享环境必须替换密钥，并在前端之前增加
真实的用户/会话认证，不能把前端反向代理注入的共享 key 当成终端用户认证。
容器化前端自身启用 HTTP Basic Auth，账号由 `FRONTEND_USERNAME` 和
`FRONTEND_PASSWORD` 配置；本机默认密码仅用于零配置演示，共享环境必须替换。

仓库当前不包含任何真实 Apify token。`APIFY_API_TOKEN` 为空或仍是示例值时，
严格检查显示 `skipped`；这不代表 Apify 已联通。

## 2. 启动完整本地栈

```bash
docker compose up --build
```

| 服务 | 地址 | 用途 |
| --- | --- | --- |
| Frontend | `http://127.0.0.1:5173` | Nginx 静态站点及 API/WS 反向代理 |
| Gateway | `http://127.0.0.1:8080` | API Key、限流、Prometheus、REST/WS 转发 |
| Agent | `http://127.0.0.1:8000` | 内部 FastAPI + LangGraph 服务 |
| Query Tower | `http://127.0.0.1:8001` | BGE-M3 1024 维归一化向量 |
| OpenSearch | `http://127.0.0.1:9200` | 品类知识库混合检索 |
| MongoDB | `mongodb://127.0.0.1:27017/lector` | Amazon 搜索结果缓存 |

OpenSearch 的安全插件仅在这个仅绑定回环地址的本地 Compose 配置中关闭。Query Tower 首次启动需要
下载 `BAAI/bge-m3`，健康检查会等模型加载完成。

只启动基础依赖：

```bash
docker compose up -d mongodb opensearch tower
```

停止并清理本次本地数据卷：

```bash
docker compose down -v
```

## 3. 品类知识库

准备经过审核的 `data/category_cards.jsonl` 后执行：

```bash
uv run python scripts/setup_pipeline.py
uv run python scripts/build_category_kb.py
```

构建脚本会校验卡片、过滤低置信度记录、调用 Query Tower，并写入 OpenSearch。
仓库不附带伪造的生产品类卡；没有真实卡片时不要把空索引当成检索验收通过。

## 4. 严格外部检查

检查所有已配置能力：

```bash
uv run python scripts/smoke_external_services.py --services configured
```

指定能力：

```bash
uv run python scripts/smoke_external_services.py \
  --services apify,mongodb,llm,web_search,opensearch,tower
```

状态语义：

- `pass`：真实调用成功，并校验了响应结构。
- `fail`：能力已配置但调用失败；命令退出码非零。
- `skipped`：缺少配置或后端明确不支持；不是成功验收。

Apify 检查直接实例化 `ApifyAmazonDataSource`，不会回退到 Mock。MongoDB 会执行
ping 和缓存往返；Tower 会校验恰好 1024 个有限浮点数。

## 5. 报告导出

准备一个符合 `ShoppingSummaryOutput` schema 的 JSON 后可导出 PDF 和 XLSX：

```bash
uv run python scripts/export_selection_report.py \
  output/selection.json --output-dir output --basename selection-report
```

XLSX 保留数值单元格，并对来自外部数据、以公式触发字符开头的文本做转义。

## 6. 单独启动 Java 网关

先启动 Python Agent，再运行：

```bash
export LECTOR_API_KEY='replace-me'
mvn -f lector-api/pom.xml spring-boot:run
```

除 `/actuator/health` 外，请求必须携带 `X-API-Key`。限流参数由
`LECTOR_RATE_CAPACITY` 和 `LECTOR_RATE_REFILL_PER_MINUTE` 控制；Prometheus 指标位于
`/actuator/prometheus`，同样受 API Key 保护。

## 7. 验收矩阵

```bash
uv run pytest
uv run basedpyright app tests scripts services
uv run pytest services/tower/tests/test_app.py
pnpm --dir frontend test -- --run
pnpm --dir frontend build
mvn -f lector-api/pom.xml test
docker compose config --quiet
uv run python scripts/demo_selection_pipeline.py
uv run python scripts/smoke_external_services.py --services configured
```

前八项必须退出 0。最后一项按上述状态语义判断；任何 `skipped` 的外部能力仍需补齐
真实凭据或兼容后端后重新验收。
