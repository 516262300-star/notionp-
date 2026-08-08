from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Iterable

from date_utils import WeekPeriod


@dataclass(frozen=True)
class StoreOverview:
    shop_name: str
    experience_star: Decimal | None
    growth_level: Decimal | None
    rating_score: Decimal | None
    service_score: Decimal | None


def saturday_in_period(period: WeekPeriod) -> date:
    """返回所选周期中最靠后的周六。"""
    days_since_saturday = (period.end_date.weekday() - 5) % 7
    target = period.end_date - timedelta(days=days_since_saturday)
    if target < period.start_date:
        raise ValueError("所选日期区间不包含周六，无法生成店铺概况")
    return target


def decimal_value(value: str, *, zero_is_missing: bool = False) -> Decimal | None:
    text = re.sub(r"\s+", "", value or "")
    if text in {"", "-", "--", "—", "None", "null"}:
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", text)
    if cleaned in {"", "-", ".", "-."}:
        return None
    try:
        result = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"无法识别数值：{value}") from exc
    if zero_is_missing and result == 0:
        return None
    return result


def current_value_from_cell(value: str, *, zero_is_missing: bool = False) -> Decimal | None:
    """从“上周 → 本周 ▲/▼变化值”或单值单元格中提取本周值。"""
    text = (value or "").strip()
    if "→" in text:
        text = text.split("→", 1)[1]
    text = re.split(r"[▲▼]", text, maxsplit=1)[0]
    return decimal_value(text, zero_is_missing=zero_is_missing)


def overview_from_cells(cells: list[str]) -> StoreOverview:
    if len(cells) < 5:
        raise ValueError(f"店铺概况行字段不足：{cells}")
    return StoreOverview(
        shop_name=cells[0].strip(),
        experience_star=current_value_from_cell(cells[1]),
        growth_level=current_value_from_cell(cells[2]),
        rating_score=current_value_from_cell(cells[3], zero_is_missing=True),
        service_score=current_value_from_cell(cells[4]),
    )


def _format_decimal(value: Decimal, decimals: int, *, fixed: bool = False) -> str:
    quantizer = Decimal(1).scaleb(-decimals)
    text = f"{value.quantize(quantizer):f}"
    if decimals and not fixed:
        text = text.rstrip("0").rstrip(".")
    return text


def format_change(
    previous: Decimal | None,
    current: Decimal | None,
    *,
    decimals: int,
    fixed: bool = False,
) -> str:
    if current is None:
        return "—"
    current_text = _format_decimal(current, decimals, fixed=fixed)
    if previous is None or previous == current:
        return current_text
    delta = current - previous
    arrow = "▲" if delta > 0 else "▼"
    return (
        f"{_format_decimal(previous, decimals, fixed=fixed)} → {current_text} "
        f"{arrow}{_format_decimal(abs(delta), decimals, fixed=fixed)}"
    )


def formatted_overview_rows(
    current_rows: Iterable[StoreOverview],
    previous_rows: dict[str, StoreOverview],
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for current in current_rows:
        previous = previous_rows.get(current.shop_name)
        result[current.shop_name] = [
            current.shop_name,
            format_change(
                previous.experience_star if previous else None,
                current.experience_star,
                decimals=1,
            ),
            format_change(
                previous.growth_level if previous else None,
                current.growth_level,
                decimals=0,
            ),
            format_change(
                previous.rating_score if previous else None,
                current.rating_score,
                decimals=2,
                fixed=True,
            ),
            format_change(
                previous.service_score if previous else None,
                current.service_score,
                decimals=1,
            ),
        ]
    return result
