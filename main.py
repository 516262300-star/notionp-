from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from aggregator import aggregate_pages
from alert import send_crash_alert
from date_utils import SHANGHAI_TZ, WeekPeriod, format_cn_date, get_last_week_period
from notion_client_wrap import WeeklyReportNotionClient
from page_builder import SHOP_NAMES, initial_page_blocks, trailing_page_blocks, warning_paragraph


@dataclass(frozen=True)
class Config:
    notion_token: str
    parent_page_id: str
    main_image_db_id: str
    shop_db_ids: list[str]
    notify_user_id: str
    alert_page_id: str

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv()
        required = [
            "NOTION_TOKEN",
            "PARENT_PAGE_ID",
            "MAIN_IMAGE_DB_ID",
            "NOTIFY_USER_ID",
            "ALERT_PAGE_ID",
            *[f"SHOP_{i}_DB_ID" for i in range(1, 8)],
        ]
        missing = [key for key in required if not os.getenv(key)]
        if missing:
            raise RuntimeError(f".env 缺少必要变量：{', '.join(missing)}")
        return cls(
            notion_token=os.environ["NOTION_TOKEN"],
            parent_page_id=os.environ["PARENT_PAGE_ID"],
            main_image_db_id=os.environ["MAIN_IMAGE_DB_ID"],
            shop_db_ids=[os.environ[f"SHOP_{i}_DB_ID"] for i in range(1, 8)],
            notify_user_id=os.environ["NOTIFY_USER_ID"],
            alert_page_id=os.environ["ALERT_PAGE_ID"],
        )


class Stage:
    value = "初始化"


def setup_logging() -> None:
    log_dir = Path(__file__).resolve().parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / f"weekly_report_{datetime.now(SHANGHAI_TZ).strftime('%Y%m%d')}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(log_file, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
    )


def weekly_date_filter(period: WeekPeriod) -> dict:
    return {
        "and": [
            {"property": "日期", "date": {"on_or_after": period.start_date.isoformat()}},
            {"property": "日期", "date": {"on_or_before": period.end_date.isoformat()}},
        ]
    }


def find_existing_report_page(
    notion: WeeklyReportNotionClient,
    parent_page_id: str,
    period: WeekPeriod,
) -> str | None:
    Stage.value = "检查重复周报"
    week_text = f"第{period.chinese_week}周"
    start_text = format_cn_date(period.start_date)
    end_text = format_cn_date(period.end_date)
    for block in notion.list_child_blocks(parent_page_id):
        if block.get("type") != "child_page":
            continue
        title = block.get("child_page", {}).get("title", "")
        if "测试" in title:
            continue
        if week_text in title and start_text in title and end_text in title:
            return block["id"]
    return None


def existing_inline_databases(notion: WeeklyReportNotionClient, page_id: str) -> dict[str, str]:
    Stage.value = "检查广告情况内嵌数据库"
    databases: dict[str, str] = {}
    for block in notion.list_child_blocks(page_id):
        if block.get("type") == "child_database":
            title = block.get("child_database", {}).get("title", "")
            databases[title] = block["id"]
    return databases


def normalize_existing_inline_database_views(
    notion: WeeklyReportNotionClient,
    inline_databases: dict[str, str],
) -> None:
    for shop_name in SHOP_NAMES:
        database_id = inline_databases.get(shop_name)
        if database_id:
            Stage.value = f"{shop_name} 调整视图列顺序"
            notion.configure_default_view_order(database_id)


def existing_heading_titles(notion: WeeklyReportNotionClient, page_id: str) -> set[str]:
    Stage.value = "检查周报板块"
    titles: set[str] = set()
    for block in notion.list_child_blocks(page_id):
        block_type = block.get("type")
        if block_type not in {"heading_1", "heading_2", "heading_3"}:
            continue
        rich_text = block.get(block_type, {}).get("rich_text", [])
        title = "".join(item.get("plain_text", "") for item in rich_text)
        if title:
            titles.add(title)
    return titles


def create_report_skeleton(notion: WeeklyReportNotionClient, config: Config, period: WeekPeriod) -> str:
    Stage.value = "创建周报页面"
    page_id = notion.create_report_page(config.parent_page_id, period.title, initial_page_blocks())
    logging.info("已创建周报页面：%s", page_id)
    return page_id


def create_shop_database_and_rows(
    notion: WeeklyReportNotionClient,
    config: Config,
    period: WeekPeriod,
    page_id: str,
    shop_index: int,
) -> tuple[int, int, list[str]]:
    shop_name = SHOP_NAMES[shop_index]
    shop_db_id = config.shop_db_ids[shop_index]
    warnings: list[str] = []

    # 每个店铺独立查询、独立建表；某个店没有数据也会留下空 schema，便于人工补看。
    Stage.value = f"{shop_name} 查询源数据库"
    pages = notion.query_database_all(shop_db_id, weekly_date_filter(period))
    logging.info("%s 源记录数：%s", shop_name, len(pages))

    Stage.value = f"{shop_name} 创建内嵌数据库"
    inline_db_id = notion.create_inline_database(page_id, shop_name, config.main_image_db_id)

    if not pages:
        warnings.append(f"{shop_name}上周无广告数据")
        logging.info("%s 生成行数：0", shop_name)
        notion.configure_default_view_order(inline_db_id)
        return len(pages), 0, warnings

    rows = aggregate_pages(pages)
    Stage.value = f"{shop_name} 写入汇总行"
    # Notion 表格默认把新建行放在上方，因此倒序写入后，界面里会按序号 1、2、3... 显示。
    for row in reversed(rows):
        relation_page_id = None
        if row.product_id:
            # 只有稳定成本商品行需要主图；找不到时写入当周周报，不触发崩溃告警。
            relation_page_id = notion.find_main_image_page_id(config.main_image_db_id, row.product_id)
            if relation_page_id is None:
                warnings.append(
                    f"⚠️ 缺主图：商品ID {row.product_id}（{shop_name}）"
                    "未在广告链接主图中找到，补录后下周自动显示"
                )
        notion.create_summary_row(inline_db_id, row, relation_page_id)

    # Notion may reinitialize the default view shortly after database creation.
    # Apply the column order once more after rows exist so the visible table sticks.
    Stage.value = f"{shop_name} 调整视图列顺序"
    notion.configure_default_view_order(inline_db_id)

    logging.info("%s 生成行数：%s", shop_name, len(rows))
    return len(pages), len(rows), warnings


def append_feedback(notion: WeeklyReportNotionClient, page_id: str, warnings: list[str]) -> None:
    if warnings:
        Stage.value = "写入其他问题反馈"
        notion.append_blocks(page_id, [warning_paragraph(message) for message in warnings])


def generate_report() -> None:
    setup_logging()
    config = Config.from_env()
    notion = WeeklyReportNotionClient(config.notion_token)
    period = get_last_week_period()
    logging.info(
        "周报周期：%s 到 %s，ISO 年=%s，ISO 周=%s",
        period.start_date,
        period.end_date,
        period.iso_year,
        period.iso_week,
    )

    try:
        page_id = find_existing_report_page(notion, config.parent_page_id, period)
        if page_id:
            logging.info("检测到重复周报，不重新创建页面：%s", page_id)
            existing_databases = existing_inline_databases(notion, page_id)
            normalize_existing_inline_database_views(notion, existing_databases)
            heading_titles = existing_heading_titles(notion, page_id)
            missing_shop_indexes = [
                index for index, shop_name in enumerate(SHOP_NAMES) if shop_name not in existing_databases
            ]
        else:
            page_id = create_report_skeleton(notion, config, period)
            heading_titles = set()
            missing_shop_indexes = list(range(7))

        warnings: list[str] = []
        total_source_records = 0
        if missing_shop_indexes:
            for shop_index in missing_shop_indexes:
                source_count, _, shop_warnings = create_shop_database_and_rows(
                    notion, config, period, page_id, shop_index
                )
                total_source_records += source_count
                warnings.extend(shop_warnings)
        else:
            logging.info("7 个内嵌数据库已齐全，无需补建")

        if not page_id:
            raise RuntimeError("未能获得周报页面 ID")

        if total_source_records == 0 and len(missing_shop_indexes) == 7:
            warnings.append("上周全店无广告数据")

        if "其他问题反馈" not in heading_titles:
            Stage.value = "追加后续周报板块"
            notion.append_blocks(page_id, trailing_page_blocks())

        append_feedback(notion, page_id, warnings)
        logging.info("周报生成完成：%s", page_id)
    except Exception as exc:
        try:
            send_crash_alert(notion, config.alert_page_id, config.notify_user_id, Stage.value, exc)
        except Exception:
            logging.critical("CRITICAL: notion unreachable", exc_info=True)
        raise


if __name__ == "__main__":
    try:
        generate_report()
    except Exception:
        sys.exit(1)
