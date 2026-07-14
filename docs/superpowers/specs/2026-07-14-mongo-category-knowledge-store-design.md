# Mongo 品类知识库改造设计

日期：2026-07-14

## 背景

Lector 当前使用 Tower 生成品类卡片向量，再由 OpenSearch 进行 BM25 与 KNN 混合召回。这个链路适合大规模、非结构化语义检索，但当前品类知识是经过整理的 `CategoryCard`，字段稳定、类别可归一化，继续维护 Tower、模型缓存和 OpenSearch 会显著增加本地磁盘占用、部署服务数和运维复杂度。

本次改造把品类知识检索迁移到现有 MongoDB，并保留存储接口，使未来确有语义召回需求时可以增加新的后端，而不改动工具层调用方式。

## 目标

- 使用 MongoDB 存储和检索 `CategoryCard`。
- `category_insight` 不再依赖 Tower、向量模型或 OpenSearch。
- 默认 Compose 删除 OpenSearch 和 Tower，只保留 MongoDB、Agent、Gateway、Frontend。
- 删除不再使用的依赖、配置、健康检查、脚本、文档和测试。
- 保留清晰的 `CategoryKnowledgeStore` 接口，隔离工具与存储实现。
- 保持 `category_insight` 的公开工具名称和返回结构兼容。

## 非目标

- 本次不合并 Agent、Gateway 和 Frontend 镜像，也不删除 Java Gateway 或前端。
- 本次不实现模糊匹配、向量检索、MongoDB Atlas Search 或新的 embedding provider。
- 不迁移商品搜索缓存；`product_search_cache` 继续按现有方式工作。
- 不修改 Agent、Server、Middleware 等框架代码。

## 方案比较

### 方案 A：MongoDB 结构化精确检索（采用）

按归一化后的 `category` 和可选 `card_type` 查询，依据置信度和更新时间排序。它复用已有 MongoDB，部署最轻，且符合当前卡片是人工或离线整理的结构化知识这一事实。

### 方案 B：MongoDB Atlas Search / Vector Search

可以保留混合或语义召回，但引入托管平台、索引配置和 embedding 依赖。当前没有足够数据量和召回质量证据证明这些成本必要，因此暂不采用。

### 方案 C：把 OpenSearch/Tower 改成可选 Compose Profile

可保留现有能力，但镜像、代码、依赖和维护面仍然存在，不能达到简化默认架构的主要目标，因此不采用。

## 架构

### 存储接口

在 `app/recall` 中定义异步 `CategoryKnowledgeStore` 协议，至少提供：

```python
async def search(
    category: str,
    *,
    card_types: set[CategoryCardType] | None = None,
    limit: int = 8,
) -> list[CategoryCard]: ...

async def upsert_many(self, cards: list[CategoryCard]) -> int: ...
```

工具只依赖该接口。Mongo 实现通过惰性工厂创建，模块导入时不连接数据库；测试可以替换工厂或直接注入 store。

### Mongo 实现

`MongoCategoryKnowledgeStore` 复用 `MONGODB_URL`，默认数据库为连接串中的数据库名，缺省时使用 `lector`，默认集合为 `category_cards`。继续使用项目已有的同步 PyMongo，通过 `asyncio.to_thread` 执行数据库操作，避免阻塞异步工具事件循环，不增加新的 Mongo 驱动。

每条文档使用 `CategoryCard` 的字段：

- `card_id`：唯一业务键。
- `category`：写入前执行 `normalize_category()`。
- `card_type`：`bestseller`、`attribute` 或 `price_range`。
- `summary`、`raw_evidence`、`last_updated`、`confidence`：保持现有模型含义。

启动或首次使用时幂等创建：

- `card_id` 唯一索引。
- `(category, card_type, confidence)` 复合索引，其中 `confidence` 降序。

查询规则固定为：

1. 归一化输入类别。
2. 精确匹配 `category`。
3. 如指定则过滤 `card_type`。
4. 过滤 `confidence >= 0.5`。
5. 按 `confidence` 降序、`last_updated` 降序、`card_id` 升序排序。
6. 应用 `limit`。

MVP 不做未命中时的语义回退。别名继续由现有 `category_norm` 负责，避免把数据库不可解释的模糊匹配隐藏在工具内部。

### 数据写入

保留 `scripts/build_category_kb.py` 这个入口以减少使用方式变化，但将其改造成 Mongo 导入器：

1. 逐行读取 JSONL。
2. 用 `CategoryCard` 校验并执行现有 admission 规则。
3. 归一化类别。
4. 按 `card_id` 批量 upsert 到 Mongo。
5. 输出读取、接受、拒绝和写入数量。

不再生成 embedding，也不再创建 OpenSearch 索引。删除只服务于旧链路的 `setup_pipeline.py` 和 `setup_pipeline.sh`。

### 工具调用链

`category_insight` 保持原工具签名和 monitor 打点。内部调用 `_recall_cards()`，后者从惰性 store 工厂取得 `CategoryKnowledgeStore` 并执行查询，再沿用现有卡片解析和输出聚合逻辑。

没有匹配卡片属于正常结果，返回现有的空洞察/低置信度结果。Mongo 配置错误、连接失败或查询异常属于基础设施故障：记录 monitor error 并抛出明确异常，不伪装成“该品类没有知识”。

## 删除和配置变更

- 从 `compose.yaml` 删除 `opensearch`、`tower` 服务、相关健康依赖、环境变量和 volume。
- 从 `pyproject.toml` 和 `uv.lock` 删除 `opensearch-py`；保留 `faiss-cpu`，因为其他 recall 模块仍在使用。
- 从 `.env.example` 删除 Tower/OpenSearch/旧品类索引配置；Mongo 继续使用 `MONGODB_URL`。
- 删除 `services/tower`、OpenSearch/Tower 专用 integration、readiness 分支和 recall 配置文件。
- 更新外部服务 smoke 脚本、README 和生产准备文档，使默认服务清单与实际 Compose 一致。
- demo 不再设置 Tower 环境变量。

## 测试策略

按 TDD 顺序实现：

1. 为 Mongo store 写失败测试，覆盖类别归一化、类型过滤、置信度阈值、排序、limit、批量 upsert 和索引幂等性。
2. 为 `category_insight` 写 store 注入测试，覆盖正常召回、空结果和基础设施错误。
3. 改写 builder 测试，覆盖 JSONL 校验、admission、归一化和 upsert 统计。
4. 更新 readiness、外部服务 smoke 和配置测试，确认 Tower/OpenSearch 不再出现。
5. 每个小步运行相关测试；完成后运行全量 `uv run pytest`、类型检查和 demo。
6. 验证 `docker compose config` 中只剩 MongoDB、Agent、Gateway、Frontend，并启动默认栈做健康检查。

测试不依赖真实公网服务；Mongo 单元测试使用可控的 fake collection/store。最终集成验证使用本机 Compose MongoDB。

## 验收标准

- `category_insight` 能从 Mongo `category_cards` 返回与现有结构兼容的结果。
- `scripts/build_category_kb.py` 能把合法 JSONL 幂等导入 Mongo。
- 默认 Compose 不再拉取或启动 OpenSearch、Tower 和 embedding 模型。
- 代码、环境示例、健康检查和文档中不存在失效的 Tower/OpenSearch 运行路径。
- 全量测试、类型检查、demo 和 Compose 健康检查通过。
- 用户已有 `.idea` 文件和其他无关工作区改动不被提交或修改。
