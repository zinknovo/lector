"""Multi-currency profit calculation normalized to CNY."""

import time

from langchain_core.tools import tool
from pydantic import BaseModel

from app.api.monitor import monitor
from app.tools.exchange_rate import exchange_rate


class ProfitCalcOutput(BaseModel):
    selling_price_cny: float
    procurement_cost_cny: float
    shipping_cost_cny: float
    platform_fee_cny: float
    total_cost_cny: float
    net_profit_cny: float
    profit_margin_cny: float
    roi_cny: float
    suggested_price_cny: float


async def _rate_to_cny(source_currency: str, target_currency: str = "CNY") -> float:
    result = await exchange_rate.ainvoke(
        {"source_currency": source_currency, "target_currency": target_currency}
    )
    return result.rate


@tool
async def profit_calculator(
    selling_price: float,
    procurement_cost: float,
    shipping_cost: float = 0.0,
    selling_currency: str = "CNY",
    procurement_currency: str = "CNY",
    shipping_currency: str = "CNY",
    platform_fee_rate: float = 0.15,
    target_margin: float = 0.3,
) -> ProfitCalcOutput:
    """Calculate SKU profitability after converting all monetary inputs to CNY."""
    await monitor.report_tool_start("profit_calculator", {"selling_price": selling_price})
    started_at = time.time()
    selling_cny = selling_price * await _rate_to_cny(selling_currency)
    procurement_cny = procurement_cost * await _rate_to_cny(procurement_currency)
    shipping_cny = shipping_cost * await _rate_to_cny(shipping_currency)
    platform_fee_cny = selling_cny * platform_fee_rate
    total_cost_cny = procurement_cny + shipping_cny + platform_fee_cny
    net_profit_cny = selling_cny - total_cost_cny
    margin = net_profit_cny / selling_cny if selling_cny else 0.0
    roi = net_profit_cny / total_cost_cny if total_cost_cny else 0.0
    denominator = 1 - platform_fee_rate - target_margin
    suggested = (procurement_cny + shipping_cny) / denominator if denominator > 0 else 0.0
    await monitor.report_tool_end(
        "profit_calculator", int((time.time() - started_at) * 1000)
    )
    return ProfitCalcOutput(
        selling_price_cny=round(selling_cny, 2),
        procurement_cost_cny=round(procurement_cny, 2),
        shipping_cost_cny=round(shipping_cny, 2),
        platform_fee_cny=round(platform_fee_cny, 2),
        total_cost_cny=round(total_cost_cny, 2),
        net_profit_cny=round(net_profit_cny, 2),
        profit_margin_cny=round(margin, 4),
        roi_cny=round(roi, 4),
        suggested_price_cny=round(suggested, 2),
    )
