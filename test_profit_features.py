from __future__ import annotations

import argparse
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import Mock, patch

import httpx

from aggregator import ReportRow
from date_utils import SHANGHAI_TZ, get_profit_period_for_report, period_from_dates
from erp_client import AdTotal, EffectiveTotal, ErpClient, ErpParseError, TMALL_AD_URL
from main import _report_week_from_title, find_existing_report_page, find_previous_report_page, period_from_args
from notion_client_wrap import WeeklyReportNotionClient
from page_builder import profit_database_schema
from profit_model import _profit_row


class ProfitFeatureTests(unittest.TestCase):
    def test_summary_sync_updates_current_rows_and_archives_old_week_rows(self) -> None:
        notion = WeeklyReportNotionClient.__new__(WeeklyReportNotionClient)
        notion.client = Mock()
        notion.query_database_all = Mock(
            return_value=[
                {
                    "id": "total-row",
                    "properties": {
                        "计划类型": {"title": [{"plain_text": "总计"}]},
                        "商品ID": {"rich_text": []},
                    },
                },
                {
                    "id": "old-product-row",
                    "properties": {
                        "计划类型": {"title": [{"plain_text": "稳定成本"}]},
                        "商品ID": {"rich_text": [{"plain_text": "OLD"}]},
                    },
                },
            ]
        )
        notion._call = Mock()
        total = ReportRow(1, "总计", None, 100, 200, 2, 10, 10, 20)

        notion.sync_summary_rows("shop-db", [(total, None)])

        update_calls = notion._call.call_args_list
        self.assertEqual(update_calls[0].args[0], "pages.update(summary_row)")
        self.assertEqual(update_calls[0].kwargs["page_id"], "total-row")
        self.assertEqual(update_calls[1].args[0], "pages.archive(summary_row)")
        self.assertEqual(update_calls[1].kwargs, {"page_id": "old-product-row", "archived": True})

    def test_full_report_without_dates_uses_last_full_week(self) -> None:
        args = argparse.Namespace(
            start_date=None,
            end_date=None,
            overview_only=False,
            consumer_only=False,
        )
        period = period_from_args(args, datetime(2026, 8, 10, 9, 0, tzinfo=SHANGHAI_TZ))
        self.assertEqual(period.start_date, date(2026, 8, 3))
        self.assertEqual(period.end_date, date(2026, 8, 9))
        self.assertEqual(period.title, "周报｜拼多多｜2026-W32｜金博敏")

    def test_weekly_report_uses_month_to_date_profit_period(self) -> None:
        report_period = period_from_dates(date(2026, 8, 3), date(2026, 8, 9))
        profit_period = get_profit_period_for_report(
            report_period,
            datetime(2026, 8, 10, 9, 0, tzinfo=SHANGHAI_TZ),
        )
        self.assertEqual(profit_period.start_date, date(2026, 8, 1))
        self.assertEqual(profit_period.end_date, date(2026, 8, 9))

    def test_week_across_month_start_uses_current_month_profit_period(self) -> None:
        report_period = period_from_dates(date(2026, 8, 31), date(2026, 9, 6))
        profit_period = get_profit_period_for_report(
            report_period,
            datetime(2026, 9, 7, 9, 0, tzinfo=SHANGHAI_TZ),
        )
        self.assertEqual(profit_period.start_date, date(2026, 9, 1))
        self.assertEqual(profit_period.end_date, date(2026, 9, 6))

    def test_overview_only_without_dates_keeps_last_full_week(self) -> None:
        args = argparse.Namespace(
            start_date=None,
            end_date=None,
            overview_only=True,
            consumer_only=False,
        )
        period = period_from_args(args, datetime(2026, 8, 8, 9, 0, tzinfo=SHANGHAI_TZ))
        self.assertEqual(period.start_date, date(2026, 7, 27))
        self.assertEqual(period.end_date, date(2026, 8, 2))

    def test_custom_period_title_uses_end_date_iso_week(self) -> None:
        period = period_from_dates(date(2026, 8, 1), date(2026, 8, 7))
        self.assertEqual(period.title, "周报｜拼多多｜2026-W32｜金博敏")
        self.assertEqual(period.iso_week, 32)

    def test_full_monday_to_sunday_uses_standard_title(self) -> None:
        period = period_from_dates(date(2026, 8, 3), date(2026, 8, 9))
        self.assertEqual(period.title, "周报｜拼多多｜2026-W32｜金博敏")

    def test_cross_year_iso_week_uses_iso_year(self) -> None:
        period = period_from_dates(date(2025, 12, 29), date(2026, 1, 4))
        self.assertEqual(period.title, "周报｜拼多多｜2026-W01｜金博敏")

    def test_report_week_parser_accepts_only_standard_title(self) -> None:
        self.assertEqual(_report_week_from_title("周报｜拼多多｜2026-W32｜金博敏"), (2026, 32))
        self.assertIsNone(_report_week_from_title("周报｜拼多多｜2026-W54｜金博敏"))

    def test_existing_report_matches_standard_week_title(self) -> None:
        notion = Mock()
        notion.list_child_blocks.return_value = [
            {
                "id": "w32-page",
                "type": "child_page",
                "child_page": {"title": "周报｜拼多多｜2026-W32｜金博敏"},
            }
        ]
        period = period_from_dates(date(2026, 8, 1), date(2026, 8, 7))
        self.assertEqual(find_existing_report_page(notion, "parent", period), "w32-page")

    def test_previous_report_uses_prior_iso_week(self) -> None:
        notion = Mock()
        notion.list_child_blocks.return_value = [
            {
                "id": "w31-page",
                "type": "child_page",
                "child_page": {"title": "周报｜拼多多｜2026-W31｜金博敏"},
            }
        ]
        period = period_from_dates(date(2026, 8, 3), date(2026, 8, 9))
        self.assertEqual(find_previous_report_page(notion, "parent", period), "w31-page")

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

    def test_business_summary_rejects_partial_month_period(self) -> None:
        today = datetime.now(SHANGHAI_TZ).date()
        if today.day > 2:
            period = period_from_dates(today.replace(day=1), today - timedelta(days=2))
        else:
            previous_month_end = today - timedelta(days=1)
            period = period_from_dates(previous_month_end.replace(day=2), previous_month_end)
        with self.assertRaises(ErpParseError):
            ErpClient._business_summary_month(period)

    def test_business_summary_accepts_previous_day_operational_cutoff(self) -> None:
        today = datetime.now(SHANGHAI_TZ).date()
        if today.day == 1:
            self.skipTest("每月 1 日没有同月的上一日")
        period = period_from_dates(today.replace(day=1), today - timedelta(days=1))
        self.assertEqual(
            ErpClient._business_summary_month(period),
            today.strftime("%Y-%m"),
        )

    def test_business_summary_maps_pdd_tmall_taobao_and_private(self) -> None:
        today = datetime.now(SHANGHAI_TZ).date()
        period = period_from_dates(today.replace(day=1), today)
        summary_html = """
            <table>
              <tr><th>操作</th><th>项目</th><th>有效销售</th><th>毛利</th><th>净利</th>
                  <th>均毛利率</th><th>均净利率</th><th>新客</th><th>老客</th><th>代码</th>
                  <th>发货毛利</th><th>发货净利</th></tr>
              <tr><td></td><td>淘宝项目</td><td>70</td><td>20</td><td>3</td><td></td><td></td>
                  <td></td><td></td><td>9</td><td>18</td><td>2</td></tr>
            </table>
        """
        pdd_rows = "".join(
            f"<tr><td></td><td>{index}店【{name}】</td><td>{index * 100}</td>"
            f"<td>0</td><td>0</td><td></td><td></td><td></td><td></td><td>3</td>"
            f"<td>{index * 20}</td><td>{index * 5}</td></tr>"
            for index, name in enumerate(
                [
                    "利德仕官方旗舰店",
                    "LEEDIS官方旗舰店",
                    "利德仕旗舰店",
                    "珂琪艺官方旗舰店",
                    "固家恒五金旗舰店",
                    "梵居匠五金旗舰店",
                    "适家旗舰店",
                ],
                start=1,
            )
        )
        pdd_html = f"<table>{pdd_rows}<tr><td></td><td>私域总计</td><td>80</td><td>30</td><td>9</td></tr></table>"
        tmall_html = """
            <table><tr><td></td><td>3店【珂琪艺旗舰店】</td><td>50</td><td>0</td><td>0</td>
            <td></td><td></td><td></td><td></td><td>2</td><td>12</td><td>-1</td></tr></table>
        """

        def response_for(url: str, **kwargs: object) -> httpx.Response:
            params = kwargs.get("params", {})
            html = summary_html
            if "blinedetail" in url:
                html = pdd_html if isinstance(params, dict) and params.get("bl") == "3" else tmall_html
            return httpx.Response(200, request=httpx.Request("GET", url), text=html)

        with ErpClient() as client, patch.object(client, "_get_authenticated", side_effect=response_for):
            parsed = client._effective_from_business_line_summary(period)
        self.assertEqual(parsed["一店"].effective_sales, 100)
        self.assertEqual(parsed["七店"].shipping_net_profit, 35)
        self.assertEqual(parsed["淘宝"].shipping_gross_profit, 18)
        self.assertEqual(parsed["天猫"].shipping_net_profit, -1)
        self.assertEqual(parsed["私域"].shipping_gross_profit, 30)

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
