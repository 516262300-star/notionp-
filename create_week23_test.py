from __future__ import annotations

from datetime import datetime

from date_utils import SHANGHAI_TZ, format_cn_date, get_last_week_period
from main import Config, append_feedback, create_shop_database_and_rows, setup_logging
from notion_client_wrap import WeeklyReportNotionClient
from page_builder import initial_page_blocks, trailing_page_blocks


def main() -> None:
    setup_logging()
    config = Config.from_env()
    notion = WeeklyReportNotionClient(config.notion_token)
    period = get_last_week_period(datetime(2026, 6, 8, 10, 0, tzinfo=SHANGHAI_TZ))
    title = (
        f"{period.start_date.year}时间：第{period.chinese_week}周"
        f"{format_cn_date(period.start_date)}到{format_cn_date(period.end_date)}（测试版）"
    )

    page_id = notion.create_report_page(config.parent_page_id, title, initial_page_blocks())
    print(f"TEST_PAGE_ID={page_id}")

    warnings: list[str] = []
    total_source_records = 0
    for shop_index in range(7):
        source_count, row_count, shop_warnings = create_shop_database_and_rows(
            notion, config, period, page_id, shop_index
        )
        total_source_records += source_count
        warnings.extend(shop_warnings)
        print(f"SHOP_{shop_index + 1}: source={source_count}, rows={row_count}")

    if total_source_records == 0:
        warnings.append("上周全店无广告数据")

    notion.append_blocks(page_id, trailing_page_blocks())
    append_feedback(notion, page_id, warnings)
    print(f"DONE={page_id}")


if __name__ == "__main__":
    main()
