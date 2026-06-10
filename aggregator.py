from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any


AD_TYPE_STABLE = "稳定成本"
AD_TYPE_FULL_SHOP = "全店托管"


@dataclass(frozen=True)
class ReportRow:
    seq: int
    plan_type: str
    product_id: str | None
    total_cost: float | None
    revenue: float | None
    roi: float | None
    orders: float | None
    cost_per_order: float | None
    revenue_per_order: float | None


def plain_text(prop: dict[str, Any] | None) -> str:
    if not prop:
        return ""
    prop_type = prop.get("type")
    values = prop.get(prop_type, [])
    if isinstance(values, list):
        return "".join(item.get("plain_text", "") for item in values).strip()
    if prop_type == "select":
        selected = prop.get("select") or {}
        return (selected.get("name") or "").strip()
    if prop_type == "date":
        value = prop.get("date") or {}
        return (value.get("start") or "").strip()
    if prop_type == "number":
        value = prop.get("number")
        return "" if value is None else str(value)
    return ""


def number_value(prop: dict[str, Any] | None) -> float:
    if not prop or prop.get("number") is None:
        return 0.0
    return float(prop["number"])


def source_record_from_page(page: dict[str, Any]) -> dict[str, Any]:
    props = page.get("properties", {})
    product_id = plain_text(props.get("商品ID")) or plain_text(props.get("广告计划"))
    return {
        "ad_type": plain_text(props.get("广告类型")),
        "product_id": product_id,
        "cost": number_value(props.get("花费")),
        "revenue": number_value(props.get("广告成交金额")),
        "orders": number_value(props.get("成交笔数")),
    }


def _round_or_none(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


def _summarize(seq: int, plan_type: str, rows: list[dict[str, Any]], product_id: str | None = None) -> ReportRow:
    total_cost = sum(row["cost"] for row in rows)
    revenue = sum(row["revenue"] for row in rows)
    orders = sum(row["orders"] for row in rows)
    roi = None if total_cost == 0 else revenue / total_cost
    cost_per_order = None if orders == 0 else total_cost / orders
    revenue_per_order = None if orders == 0 else revenue / orders
    return ReportRow(
        seq=seq,
        plan_type=plan_type,
        product_id=product_id,
        total_cost=_round_or_none(total_cost),
        revenue=_round_or_none(revenue),
        roi=_round_or_none(roi),
        orders=_round_or_none(orders),
        cost_per_order=_round_or_none(cost_per_order),
        revenue_per_order=_round_or_none(revenue_per_order),
    )


def aggregate_pages(pages: list[dict[str, Any]]) -> list[ReportRow]:
    records = [source_record_from_page(page) for page in pages]
    if not records:
        return []

    result: list[ReportRow] = [_summarize(1, "总计", records)]

    full_shop_rows = [row for row in records if row["ad_type"] == AD_TYPE_FULL_SHOP]
    if full_shop_rows:
        result.append(_summarize(2, AD_TYPE_FULL_SHOP, full_shop_rows))

    stable_rows = [row for row in records if row["ad_type"] == AD_TYPE_STABLE]
    if stable_rows:
        result.append(_summarize(3, "稳定成本合计", stable_rows))

    by_product: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in stable_rows:
        if row["product_id"]:
            by_product[row["product_id"]].append(row)

    ranked_products = sorted(
        by_product.items(),
        key=lambda item: sum(row["cost"] for row in item[1]),
        reverse=True,
    )
    for index, (product_id, rows) in enumerate(ranked_products, start=4):
        result.append(_summarize(index, AD_TYPE_STABLE, rows, product_id=product_id))

    return result
