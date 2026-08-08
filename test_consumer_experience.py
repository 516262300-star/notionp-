from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import Mock

from consumer_experience import (
    ConsumerExperience,
    consumer_experience_from_values,
    formatted_consumer_experience_rows,
)
from notion_client_wrap import WeeklyReportNotionClient
from page_builder import consumer_experience_database_schema


class ConsumerExperienceTests(unittest.TestCase):
    def test_changes_follow_weekly_comparison_format(self) -> None:
        previous = ConsumerExperience(
            "一店",
            Decimal("2.8"),
            Decimal("4.0"),
            Decimal("1.7"),
            Decimal("4.0"),
            Decimal("2.5"),
            Decimal("3.9"),
        )
        current = ConsumerExperience(
            "一店",
            Decimal("2.8"),
            Decimal("4.1"),
            Decimal("1.6"),
            Decimal("4.0"),
            Decimal("2.5"),
            None,
        )

        row = formatted_consumer_experience_rows([current], {"一店": previous})["一店"]

        self.assertEqual(row["消费者服务体验分"], "2.8")
        self.assertEqual(row["服务态度体验分"], "4 → 4.1 ▲0.1")
        self.assertEqual(row["基础服务体验分"], "1.7 → 1.6 ▼0.1")
        self.assertEqual(row["物流服务体验分"], "—")

    def test_previous_database_value_uses_current_side_of_arrow(self) -> None:
        row = consumer_experience_from_values(
            "二店",
            {
                "消费者服务体验分": "2.5 → 2.7 ▲0.2",
                "服务态度体验分": "4",
                "基础服务体验分": "—",
                "发货服务体验分": "3.8",
                "商品服务体验分": "3.1 → 3 ▼0.1",
                "物流服务体验分": "4.2",
            },
        )

        self.assertEqual(row.overall_score, Decimal("2.7"))
        self.assertEqual(row.product_score, Decimal("3"))
        self.assertIsNone(row.basic_score)

    def test_database_schema_has_six_scores_and_date(self) -> None:
        self.assertEqual(
            list(consumer_experience_database_schema()),
            [
                "店铺",
                "消费者服务体验分",
                "服务态度体验分",
                "基础服务体验分",
                "发货服务体验分",
                "商品服务体验分",
                "物流服务体验分",
                "数据日期",
                "序号",
            ],
        )

    def test_sync_updates_existing_shop_and_creates_missing_shop(self) -> None:
        client = WeeklyReportNotionClient.__new__(WeeklyReportNotionClient)
        client.query_database_all = Mock(  # type: ignore[method-assign]
            return_value=[
                {
                    "id": "page-one",
                    "properties": {
                        "店铺": {"title": [{"plain_text": "一店"}]},
                    },
                }
            ]
        )
        client.client = Mock()
        client._call = Mock()  # type: ignore[method-assign]
        client.configure_consumer_experience_view_order = Mock()  # type: ignore[method-assign]
        rows = {
            shop: {
                "店铺": shop,
                "消费者服务体验分": "2.8",
                "服务态度体验分": "4",
                "基础服务体验分": "1.7",
                "发货服务体验分": "4.1",
                "商品服务体验分": "2.3",
                "物流服务体验分": "3.9",
            }
            for shop in ("一店", "二店")
        }

        client.sync_consumer_experience_rows(
            "database-id", rows, date(2026, 8, 1)
        )

        labels = [call.args[0] for call in client._call.call_args_list]
        self.assertEqual(
            labels,
            [
                "pages.update(consumer_experience_row)",
                "pages.create(consumer_experience_row)",
            ],
        )
        client.configure_consumer_experience_view_order.assert_called_once_with(
            "database-id"
        )

    def test_consumer_view_is_sorted_from_shop_one_to_seven(self) -> None:
        client = WeeklyReportNotionClient.__new__(WeeklyReportNotionClient)
        client._configure_view_order = Mock()  # type: ignore[method-assign]

        client.configure_consumer_experience_view_order("database-id")

        self.assertEqual(
            client._configure_view_order.call_args.kwargs["sorts"],
            [{"property": "序号", "direction": "ascending"}],
        )


if __name__ == "__main__":
    unittest.main()
