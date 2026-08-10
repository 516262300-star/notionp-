from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from aggregator import aggregate_pages
from date_utils import WeekPeriod
from erp_client import AdTotal, EffectiveTotal, ErpClient
from page_builder import SHOP_NAMES


@dataclass(frozen=True)
class ProfitRow:
    seq: int
    project: str
    ad_revenue: float | None
    ad_cost: float | None
    roi: float | None
    ad_share: float | None
    shipping_net_profit: float | None
    gross_profit_after_ads: float | None
    effective_sales: float | None
    shipping_gross_profit: float | None


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in {None, 0}:
        return None
    return _rounded(numerator / denominator)


def _period_filter(period: WeekPeriod) -> dict[str, Any]:
    return {
        "and": [
            {"property": "日期", "date": {"on_or_after": period.start_date.isoformat()}},
            {"property": "日期", "date": {"on_or_before": period.end_date.isoformat()}},
        ]
    }


def _pdd_ad_totals(notion: Any, shop_db_ids: list[str], period: WeekPeriod) -> dict[str, AdTotal]:
    result: dict[str, AdTotal] = {}
    for shop_name, database_id in zip(SHOP_NAMES, shop_db_ids, strict=True):
        pages = notion.query_database_all(database_id, _period_filter(period))
        rows = aggregate_pages(pages)
        if rows:
            total = rows[0]
            result[shop_name] = AdTotal(revenue=total.revenue, cost=total.total_cost)
        else:
            result[shop_name] = AdTotal(revenue=0.0, cost=0.0)
        logging.info(
            "%s 盈亏广告汇总：source=%s，广告费=%s，广告成交=%s",
            shop_name,
            len(pages),
            result[shop_name].cost,
            result[shop_name].revenue,
        )
    return result


def _profit_row(
    seq: int,
    name: str,
    ad: AdTotal,
    effective: EffectiveTotal,
    *,
    no_ad_channel: bool = False,
) -> ProfitRow:
    if no_ad_channel:
        after_ads = effective.shipping_net_profit
    elif effective.shipping_gross_profit is None:
        after_ads = None
    else:
        after_ads = effective.shipping_gross_profit - (ad.cost or 0.0)
    return ProfitRow(
        seq=seq,
        project=name,
        ad_revenue=_rounded(ad.revenue),
        ad_cost=_rounded(ad.cost),
        roi=_ratio(ad.revenue, ad.cost),
        ad_share=_ratio(ad.cost, effective.effective_sales),
        shipping_net_profit=_rounded(effective.shipping_net_profit),
        gross_profit_after_ads=_rounded(after_ads),
        effective_sales=_rounded(effective.effective_sales),
        shipping_gross_profit=_rounded(effective.shipping_gross_profit),
    )


def collect_profit_rows(
    notion: Any,
    shop_db_ids: list[str],
    effective_period: WeekPeriod,
    *,
    ad_period: WeekPeriod | None = None,
) -> list[ProfitRow]:
    ad_period = ad_period or effective_period
    # 先校验业务线汇总是否能准确表示所选日期，避免无效区间先产生大量外部查询。
    ErpClient._business_summary_month(effective_period)
    pdd_ads = _pdd_ad_totals(notion, shop_db_ids, ad_period)
    with ErpClient() as erp:
        if not erp.check_login():
            from erp_client import ErpLoginRequired

            raise ErpLoginRequired("系统尚未登录，请先在 .env 填写 ERP_PHONE 和 ERP_PASSWORD")
        effective = erp.fetch_effective_totals(effective_period)
        taobao_ad = erp.fetch_taobao_ad_total(ad_period)
        tmall_ad = erp.fetch_tmall_ad_total(ad_period)

    rows = [
        _profit_row(index, shop_name, pdd_ads[shop_name], effective[shop_name])
        for index, shop_name in enumerate(SHOP_NAMES, start=1)
    ]
    rows.append(_profit_row(8, "淘宝", taobao_ad, effective["淘宝"]))
    rows.append(_profit_row(9, "天猫", tmall_ad, effective["天猫"]))
    rows.append(
        _profit_row(
            10,
            "私域",
            AdTotal(revenue=None, cost=None),
            effective["私域"],
            no_ad_channel=True,
        )
    )

    def sum_present(field: str) -> float | None:
        values = [getattr(row, field) for row in rows if getattr(row, field) is not None]
        return _rounded(sum(values)) if values else None

    total_ad_revenue = sum_present("ad_revenue")
    total_ad_cost = sum_present("ad_cost")
    total_effective_sales = sum_present("effective_sales")
    rows.append(
        ProfitRow(
            seq=11,
            project="总计",
            ad_revenue=total_ad_revenue,
            ad_cost=total_ad_cost,
            roi=_ratio(total_ad_revenue, total_ad_cost),
            ad_share=_ratio(total_ad_cost, total_effective_sales),
            shipping_net_profit=sum_present("shipping_net_profit"),
            gross_profit_after_ads=sum_present("gross_profit_after_ads"),
            effective_sales=total_effective_sales,
            shipping_gross_profit=sum_present("shipping_gross_profit"),
        )
    )
    return rows
