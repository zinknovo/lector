"""小模型抽取：从原始资料生成 CategoryCard 字段。"""

import json

from app.agent.llm import get_judge_llm
from app.recall.category_norm import normalize_category

EXTRACT_PROMPT = """你是 Globex 品类知识库的卡片抽取器。

输入：关于「{category}」的原始资料（评论、销量榜、商品聚合等）。
输出：按约定格式写 CategoryCard 字段。

summary 格式约定（依 card_type）：
- bestseller: 「{{category}}: {{组件1}} / {{组件2}} / {{组件3}}」
- attribute: 如「材质: 尼龙 60% / 帆布 25% / 牛津布 15%」
- price_range: 如「便宜款 60—150 / 中档 150—400 / 高端 400+ 常见品牌联名」

还需输出：
- raw_evidence: 1-3 条原文摘录，每条不超过 80 字；爆款卡可用「name | price | reason」格式
- confidence: 0-1，根据资料量和表述确定性自评

只输出 JSON，不要解释。"""


async def extract_card(category: str, raw_text: str, card_type: str) -> dict:
    category = normalize_category(category)
    llm = get_judge_llm()
    resp = await llm.ainvoke(
        [
            ("system", EXTRACT_PROMPT.format(category=category)),
            ("user", f"card_type={card_type}\n\n资料：\n{raw_text}"),
        ]
    )
    return json.loads(resp.content)
