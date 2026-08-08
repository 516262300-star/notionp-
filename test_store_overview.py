from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

from date_utils import period_from_dates
from erp_client import ErpClient
from notion_client_wrap import WeeklyReportNotionClient
from store_overview import (
    StoreOverview,
    current_value_from_cell,
    formatted_overview_rows,
    overview_from_cells,
    saturday_in_period,
)


class StoreOverviewTests(unittest.TestCase):
    def test_full_week_uses_saturday(self) -> None:
        period = period_from_dates(date(2026, 8, 3), date(2026, 8, 9))
        self.assertEqual(saturday_in_period(period), date(2026, 8, 8))

    def test_custom_period_uses_latest_saturday(self) -> None:
        period = period_from_dates(date(2026, 8, 1), date(2026, 8, 7))
        self.assertEqual(saturday_in_period(period), date(2026, 8, 1))

    def test_previous_cell_extracts_current_value(self) -> None:
        self.assertEqual(current_value_from_cell("99.49 → 99.33 ▼0.16"), Decimal("99.33"))
        self.assertEqual(current_value_from_cell("5"), Decimal("5"))
        self.assertIsNone(current_value_from_cell("— → —"))

    def test_zero_rating_is_treated_as_missing(self) -> None:
        row = overview_from_cells(["七店", "5", "2", "0.00", "2.3"])
        self.assertIsNone(row.rating_score)

    def test_changes_follow_notion_format(self) -> None:
        previous = {
            "一店": StoreOverview(
                "一店",
                Decimal("5"),
                Decimal("6"),
                Decimal("99.33"),
                Decimal("2.8"),
            )
        }
        current = [
            StoreOverview(
                "一店",
                Decimal("5.0"),
                Decimal("6"),
                Decimal("99.32"),
                Decimal("2.9"),
            )
        ]
        self.assertEqual(
            formatted_overview_rows(current, previous)["一店"],
            ["一店", "5", "6", "99.33 → 99.32 ▼0.01", "2.8 → 2.9 ▲0.1"],
        )

    def test_rating_delta_keeps_two_decimal_places(self) -> None:
        previous = {
            "三店": StoreOverview(
                "三店", Decimal("5"), Decimal("5"), Decimal("99.83"), Decimal("3.1")
            )
        }
        current = [
            StoreOverview(
                "三店", Decimal("5"), Decimal("5"), Decimal("99.33"), Decimal("3.0")
            )
        ]
        self.assertEqual(
            formatted_overview_rows(current, previous)["三店"][3],
            "99.83 → 99.33 ▼0.50",
        )

    def test_erp_table_parser_selects_requested_date(self) -> None:
        html = """
            <table>
              <tr><th>操作</th><th>日期</th><th>店铺评价分</th></tr>
              <tr><td></td><td>2026-08-01</td><td>99.33</td></tr>
              <tr><td></td><td>2026-08-02</td><td>99.32</td></tr>
            </table>
        """
        self.assertEqual(
            ErpClient._overview_value(html, date(2026, 8, 1), ("店铺评价分",)),
            "99.33",
        )

    def test_notion_update_replaces_existing_table_row(self) -> None:
        client = WeeklyReportNotionClient.__new__(WeeklyReportNotionClient)
        client.client = SimpleNamespace(request=object())
        client._store_overview_rows = Mock(  # type: ignore[method-assign]
            return_value={"一店": ("row-id", ["一店", "—", "—", "—", "—"])}
        )
        client._call = Mock()  # type: ignore[method-assign]
        cells = ["一店", "5", "6", "99.33 → 99.32 ▼0.01", "2.8"]

        client.update_store_overview("page-id", {"一店": cells})

        call = client._call.call_args
        self.assertEqual(call.kwargs["path"], "blocks/row-id")
        self.assertEqual(call.kwargs["method"], "PATCH")
        self.assertEqual(
            [cell[0]["text"]["content"] for cell in call.kwargs["body"]["table_row"]["cells"]],
            cells,
        )


if __name__ == "__main__":
    unittest.main()
