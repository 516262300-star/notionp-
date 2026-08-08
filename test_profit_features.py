from __future__ import annotations

import unittest
from datetime import date

import httpx

from date_utils import period_from_dates
from erp_client import AdTotal, EffectiveTotal, ErpClient, TMALL_AD_URL
from page_builder import profit_database_schema
from profit_model import _profit_row


class ProfitFeatureTests(unittest.TestCase):
    def test_custom_period_title_does_not_claim_iso_week(self) -> None:
        period = period_from_dates(date(2026, 8, 1), date(2026, 8, 7))
        self.assertEqual(period.title, "2026时间：2026年8月1日到2026年8月7日")

    def test_full_monday_to_sunday_keeps_week_title(self) -> None:
        period = period_from_dates(date(2026, 8, 3), date(2026, 8, 9))
        self.assertIn("第三十二周", period.title)

    def test_cross_year_iso_week_uses_iso_year(self) -> None:
        period = period_from_dates(date(2025, 12, 29), date(2026, 1, 4))
        self.assertTrue(period.title.startswith("2026时间：第一周"))

    def test_profit_formulas_match_template_rules(self) -> None:
        row = _profit_row(
            1,
            "一店",
            AdTotal(revenue=540154, cost=136445),
            EffectiveTotal(
                effective_sales=440268,
                shipping_gross_profit=150908,
                shipping_net_profit=16897,
            ),
        )
        self.assertEqual(row.roi, 3.96)
        self.assertEqual(row.ad_share, 0.31)
        self.assertEqual(row.gross_profit_after_ads, 14463)

    def test_private_channel_uses_shipping_net_profit(self) -> None:
        row = _profit_row(
            10,
            "私域",
            AdTotal(revenue=None, cost=None),
            EffectiveTotal(38725, 10713, 7700),
            no_ad_channel=True,
        )
        self.assertIsNone(row.ad_cost)
        self.assertEqual(row.gross_profit_after_ads, 7700)

    def test_effective_summary_parser_matches_store_aliases(self) -> None:
        headers = ["操作", "项目", "有效销售", "发货毛利", "发货净利"]
        rows = [
            ["-", "1店【利德仕官方旗舰店】", "100", "40", "10"],
            ["-", "3店【珂琪艺旗舰店】", "80", "30", "5"],
            ["-", "淘宝项目", "50", "20", "3"],
            ["-", "私域总计", "25", "12", "8"],
        ]
        parsed = ErpClient._effective_from_summary([(headers, rows)])
        self.assertEqual(parsed["一店"].effective_sales, 100)
        self.assertEqual(parsed["天猫"].shipping_gross_profit, 30)
        self.assertEqual(parsed["淘宝"].shipping_net_profit, 3)
        self.assertEqual(parsed["私域"].shipping_net_profit, 8)

    def test_effective_detail_rows_map_stores_and_private_channel(self) -> None:
        rows = [
            {
                "业务线": "拼多多项目",
                "店铺": "1店：利德仕官方旗舰店",
                "单源": "拼多多",
                "有效销售": "100.50",
                "发货毛利": "30",
                "发货净利": "8",
            },
            {
                "业务线": "拼多多项目",
                "店铺": "1",
                "单源": "微信",
                "有效销售": "20",
                "发货毛利": "7",
                "发货净利": "5",
            },
            {
                "业务线": "天猫项目",
                "店铺": "3店：珂琪艺旗舰店",
                "单源": "天猫",
                "有效销售": "80",
                "发货毛利": "20",
                "发货净利": "2",
            },
        ]
        parsed = ErpClient._effective_from_json_rows(rows)
        self.assertEqual(parsed["一店"].effective_sales, 100.5)
        self.assertEqual(parsed["私域"].shipping_net_profit, 5)
        self.assertEqual(parsed["天猫"].shipping_gross_profit, 20)
        self.assertEqual(parsed["二店"].effective_sales, 0)

    def test_effective_detail_period_splits_on_month_boundaries(self) -> None:
        period = period_from_dates(date(2026, 7, 30), date(2026, 8, 2))
        self.assertEqual(
            ErpClient._month_segments(period),
            [(date(2026, 7, 30), date(2026, 7, 31)), (date(2026, 8, 1), date(2026, 8, 2))],
        )

    def test_ad_page_rows_are_summed_within_selected_period(self) -> None:
        response = httpx.Response(
            200,
            request=httpx.Request("GET", "https://example.test/ad"),
            text="""
                <table>
                  <tr><th>广告计划</th><th>花费</th><th>广告成交金额</th><th>日期</th></tr>
                  <tr><td>A</td><td>10.25</td><td>35.50</td><td>2026-08-01</td></tr>
                  <tr><td>B</td><td>4.75</td><td>9.50</td><td>2026-08-07</td></tr>
                  <tr><td>C</td><td>99</td><td>99</td><td>2026-08-08</td></tr>
                </table>
            """,
        )
        period = period_from_dates(date(2026, 8, 1), date(2026, 8, 7))
        cost, revenue, found = ErpClient._ad_values_from_response(response, period)
        self.assertTrue(found)
        self.assertEqual(cost, 15)
        self.assertEqual(revenue, 45)

    def test_tmall_profit_source_is_store_103(self) -> None:
        self.assertIn("store=103", TMALL_AD_URL)

    def test_profit_database_columns_match_template(self) -> None:
        self.assertEqual(
            list(profit_database_schema()),
            [
                "项目",
                "广告成交",
                "广告费",
                "ROI",
                "广告占比",
                "发货净利",
                "毛利-广告",
                "有效销售",
                "发货毛利",
                "序号",
            ],
        )


if __name__ == "__main__":
    unittest.main()
