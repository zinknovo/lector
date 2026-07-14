# Lector 数据源抽象层设计

> 阶段：Python Agent 层（FastAPI + LangGraph）  
> 目标：为上层工具提供统一、无感知的数据来源抽象。

## 背景

Lector 电商选品 Agent 需要同时支持：

1. 本地/CI 快速验证：无需外部依赖即可跑通工具链。
2. 真实平台抓取：通过 Apify Amazon Scraper 获取实时商品数据。

因此需要引入一层数据抽象：`Product` 统一模型 + `ProductDataSource` 抽象接口 + 多实现 + 工厂函数。

## 范围

- 仅新增 `app/data/` 目录及相关配置、脚本、测试。
- 不改动现有 `app/agent/`、`app/tools/`、`app/api/` 等业务逻辑。
- 本次先实现 Mock 数据源和 Apify Amazon 数据源。

## 设计

### 1. 目录结构

```
app/data/
├── __init__.py          # 导出 Product、ProductDataSource、get_data_source
├── models.py            # Product Pydantic 模型
├── base.py              # ProductDataSource ABC
├── mock_source.py       # MockProductDataSource
├── apify_source.py      # ApifyAmazonDataSource
└── factory.py           # get_data_source() 工厂
```

### 2. Product 模型

使用 Pydantic BaseModel，字段如下：

| 字段 | 类型 | 说明 |
|------|------|------|
| `product_id` | `str` | 平台内唯一 ID |
| `title` | `str` | 商品标题 |
| `category` | `str` | 品类名称（统一小写下划线） |
| `price` | `Decimal` | 当前售价 |
| `original_price` | `Decimal \| None` | 原价/划线价 |
| `rating` | `float \| None` | 评分，范围 0-5 |
| `review_count` | `int \| None` | 评论数 |
| `sales_volume` | `int \| None` | 月销量/销量估算 |
| `bsr` | `int \| None` | Best Sellers Rank |
| `platform` | `str` | 来源平台，如 `amazon`、`mock` |
| `url` | `str` | 商品详情 URL |
| `image_url` | `str \| None` | 主图 URL |
| `shipping_cost` | `Decimal \| None` | 运费 |
| `seller` | `str \| None` | 卖家名称 |
| `availability` | `str \| None` | 库存状态 |
| `attributes` | `dict[str, Any]` | 扩展属性（颜色、尺寸等） |
| `scraped_at` | `datetime` | 抓取时间，UTC |

说明：

- `sales_volume` 和 `bsr` 都保留，根据平台数据填充可用字段。
- 价格使用 `Decimal` 避免浮点误差。
- `scraped_at` 默认 `datetime.now(timezone.utc)`。

### 3. 抽象接口

```python
class ProductDataSource(ABC):
    @abstractmethod
    async def search(self, query: str, **filters) -> list[Product]: ...

    @abstractmethod
    async def get_by_id(self, product_id: str) -> Product | None: ...
```

- `search` 统一接收 `query` 字符串和过滤参数。
- 过滤参数由具体实现解释，但 Mock 和 Apify 至少支持：`category`、`price_min`、`price_max`、`rating_min`。

### 4. MockProductDataSource

- 内置 25 条跨品类示例数据（家居、电子、户外、厨房、办公）。
- 无外部依赖。
- 支持过滤：
  - `category`: 精确匹配（小写）。
  - `price_min` / `price_max`: 价格区间（含端点）。
  - `rating_min`: 最低评分。
- 支持对 `title` 和 `category` 的模糊文本匹配。

### 5. ApifyAmazonDataSource

- 依赖 `apify-client`。
- 从环境变量读取 `APIFY_API_TOKEN`。
- 默认 Actor ID：`junglee/amazon-scraper`，可通过 `APIFY_AMAZON_ACTOR_ID` 覆盖。
- 调用 `client.actor(...).call(run_input={...})`，将结果映射为 `Product` 列表。
- 失败时抛出自定义 `DataSourceError`，保留原始异常信息。
- `search` 透传 `query` 给 Actor，返回后做轻量过滤（price/rating 等）。

### 6. 配置与工厂

新增环境变量：

```bash
APIFY_API_TOKEN=
USE_MOCK=true
APIFY_AMAZON_ACTOR_ID=junglee/amazon-scraper  # 可选
```

工厂函数 `get_data_source()` 回退逻辑：

| USE_MOCK | APIFY_API_TOKEN | 结果 |
|----------|-----------------|------|
| `true` | 任意 | Mock |
| `false` | 存在 | ApifyAmazon |
| `false` | 缺失 | Mock + warning |
| 未设置 | 存在 | ApifyAmazon |
| 未设置 | 缺失 | Mock |

### 7. 可运行脚本

`scripts/test_data_source.py`：

```bash
uv run python scripts/test_data_source.py --source mock --query "kitchen"
uv run python scripts/test_data_source.py --source apify --query "wireless earbuds"
```

### 8. 测试

新增 `tests/test_data_source.py`：

- Mock 搜索与过滤。
- `get_by_id` 命中与缺失。
- 工厂函数：各种 `USE_MOCK` / `APIFY_API_TOKEN` 组合。
- 确保不破坏现有测试。

## 风险与后续

- Apify Actor 输出字段可能变化，映射函数需保持容错。
- 后续如需接入 Shopee/TikTok，可新增 `ApifyShopeeDataSource` 等实现，沿用同一接口。
