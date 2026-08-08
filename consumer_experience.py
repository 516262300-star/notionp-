from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from store_overview import current_value_from_cell, format_change


@dataclass(frozen=True)
class ConsumerExperience:
    shop_name: str
    overall_score: Decimal | None
    attitude_score: Decimal | None
    basic_score: Decimal | None
    shipping_score: Decimal | None
    product_score: Decimal | None
    logistics_score: Decimal | None


CONSUMER_EXPERIENCE_FIELDS = {
    "overall_score": "消费者服务体验分",
    "attitude_score": "服务态度体验分",
    "basic_score": "基础服务体验分",
    "shipping_score": "发货服务体验分",
    "product_score": "商品服务体验分",
    "logistics_score": "物流服务体验分",
}


def consumer_experience_from_values(
    shop_name: str,
    values: dict[str, str],
) -> ConsumerExperience:
    return ConsumerExperience(
        shop_name=shop_name,
        **{
            field: current_value_from_cell(values.get(property_name, ""))
            for field, property_name in CONSUMER_EXPERIENCE_FIELDS.items()
        },
    )


def formatted_consumer_experience_rows(
    current_rows: Iterable[ConsumerExperience],
    previous_rows: dict[str, ConsumerExperience],
) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for current in current_rows:
        previous = previous_rows.get(current.shop_name)
        values = {"店铺": current.shop_name}
        for field, property_name in CONSUMER_EXPERIENCE_FIELDS.items():
            values[property_name] = format_change(
                getattr(previous, field) if previous else None,
                getattr(current, field),
                decimals=1,
            )
        result[current.shop_name] = values
    return result
