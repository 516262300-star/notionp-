from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv

from aggregator import aggregate_pages
from alert import send_crash_alert
from consumer_experience import (
    ConsumerExperience,
    formatted_consumer_experience_rows,
)
from date_utils import SHANGHAI_TZ, WeekPeriod, format_cn_date, get_last_week_period, period_from_dates
from erp_client import ErpClient, ErpError
from notion_client_wrap import WeeklyReportNotionClient
from page_builder import (
    SHOP_NAMES,
    heading_2,
    initial_page_blocks,
    post_consumer_experience_blocks,
    post_profit_blocks,
    profit_section_blocks,
    warning_paragraph,
)
from profit_model import ProfitRow, collect_profit_rows
from store_overview import StoreOverview, formatted_overview_rows, saturday_in_period


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
    log_file = log_dir / f"weekly_report_{datetime.now(SHANGHAI_TZ).strftime('%Y%m%d_%H%M%S')}.log"
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
    start_text = format_cn_date(period.start_date)
    end_text = format_cn_date(period.end_date)
    for block in notion.list_child_blocks(parent_page_id):
        if block.get("type") != "child_page":
            continue
        title = block.get("child_page", {}).get("title", "")
        if "测试" in title:
            continue
        if start_text in title and end_text in title:
            return block["id"]
    return None


def _report_dates_from_title(title: str) -> tuple[date, date] | None:
    matches = re.findall(r"(20\d{2})年(\d{1,2})月(\d{1,2})日", title)
    if len(matches) < 2:
        return None
    try:
        start = date(*(int(part) for part in matches[-2]))
        end = date(*(int(part) for part in matches[-1]))
    except ValueError:
        return None
    return start, end


def find_previous_report_page(
    notion: WeeklyReportNotionClient,
    parent_page_id: str,
    period: WeekPeriod,
) -> str | None:
    candidates: list[tuple[date, str]] = []
    for block in notion.list_child_blocks(parent_page_id):
        if block.get("type") != "child_page":
            continue
        title = block.get("child_page", {}).get("title", "")
        if "测试" in title:
            continue
        report_dates = _report_dates_from_title(title)
        if report_dates and report_dates[1] < period.start_date:
            candidates.append((report_dates[1], block["id"]))
    return max(candidates, default=(None, None), key=lambda item: item[0])[1]


def _consumer_experience_database_id(databases: dict[str, str]) -> str | None:
    return next(
        (
            database_id
            for title, database_id in databases.items()
            if title.startswith("消费者体验分明细")
        ),
        None,
    )


def collect_store_metric_rows(
    notion: WeeklyReportNotionClient,
    config: Config,
    period: WeekPeriod,
) -> tuple[
    date,
    list[StoreOverview],
    dict[str, list[str]],
    list[ConsumerExperience],
    dict[str, dict[str, str]],
]:
    Stage.value = "获取店铺概况和消费者体验分"
    snapshot_date = saturday_in_period(period)
    with ErpClient() as erp:
        current_overviews, current_experiences = erp.fetch_pdd_store_metrics(snapshot_date)

    previous_page_id = find_previous_report_page(notion, config.parent_page_id, period)
    previous_overviews: dict[str, StoreOverview] = {}
    previous_experiences: dict[str, ConsumerExperience] = {}
    if previous_page_id:
        Stage.value = "读取上一期店铺概况"
        previous_overviews = notion.read_store_overview(previous_page_id)
        logging.info("上一期店铺概况来源页面：%s", previous_page_id)
        previous_databases = existing_inline_databases(notion, previous_page_id)
        previous_experience_db_id = _consumer_experience_database_id(previous_databases)
        if previous_experience_db_id:
            Stage.value = "读取上一期消费者体验分"
            previous_experiences = notion.read_consumer_experiences(
                previous_experience_db_id
            )
            logging.info("上一期消费者体验分来源数据库：%s", previous_experience_db_id)
        else:
            logging.warning("上一期周报没有消费者体验分数据库，本期将只填写本周值")
    else:
        logging.warning("没有找到上一期周报，店铺概况将只填写本期值")
        logging.warning("没有找到上一期周报，消费者体验分将只填写本期值")
    return (
        snapshot_date,
        current_overviews,
        formatted_overview_rows(current_overviews, previous_overviews),
        current_experiences,
        formatted_consumer_experience_rows(
            current_experiences, previous_experiences
        ),
    )


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


def consumer_experience_database_title(snapshot_date: date) -> str:
    return f"消费者体验分明细 {snapshot_date.month}.{snapshot_date.day}"


def sync_consumer_experience_database(
    notion: WeeklyReportNotionClient,
    page_id: str,
    snapshot_date: date,
    rows: dict[str, dict[str, str]],
    existing_databases: dict[str, str],
    *,
    page_created_now: bool,
) -> str:
    database_id = _consumer_experience_database_id(existing_databases)
    if database_id is None:
        if not page_created_now:
            notion.append_blocks(page_id, [heading_2("消费者体验分情况（自动生成）")])
        database_id = notion.create_consumer_experience_database(
            page_id, consumer_experience_database_title(snapshot_date)
        )
    Stage.value = "写入消费者体验分情况"
    notion.sync_consumer_experience_rows(database_id, rows, snapshot_date)
    logging.info(
        "消费者体验分情况写入完成：页面=%s，数据日期=%s，数据库=%s",
        page_id,
        snapshot_date,
        database_id,
    )
    return database_id


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
        warnings.append(f"{shop_name}所选周期无广告数据")
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


def profit_database_title(period: WeekPeriod) -> str:
    return (
        f"盈亏明细 {period.start_date.month}.{period.start_date.day}"
        f"-{period.end_date.month}.{period.end_date.day}"
    )


def create_profit_database_and_rows(
    notion: WeeklyReportNotionClient,
    page_id: str,
    period: WeekPeriod,
    rows: list[ProfitRow],
) -> str:
    title = profit_database_title(period)
    Stage.value = "创建盈亏情况数据库"
    database_id = notion.create_profit_database(page_id, title)
    Stage.value = "写入盈亏情况"
    # 新库倒序写入，让 Notion 默认视图中一店到总计从上到下显示。
    notion.sync_profit_rows(database_id, list(reversed(rows)))
    notion.configure_profit_view_order(database_id)
    logging.info("盈亏情况生成完成：%s 行", len(rows))
    return database_id


def generate_report(
    period: WeekPeriod | None = None,
    *,
    dry_run: bool = False,
    overview_only: bool = False,
    consumer_only: bool = False,
) -> None:
    setup_logging()
    config = Config.from_env()
    notion = WeeklyReportNotionClient(config.notion_token)
    period = period or get_last_week_period()
    logging.info(
        "周报周期：%s 到 %s，ISO 年=%s，ISO 周=%s",
        period.start_date,
        period.end_date,
        period.iso_year,
        period.iso_week,
    )

    try:
        snapshot_date, _, overview_rows, _, consumer_rows = collect_store_metric_rows(
            notion, config, period
        )
        if (overview_only or consumer_only) and dry_run:
            payload: dict[str, object] = {"snapshot_date": snapshot_date.isoformat()}
            if overview_only:
                payload["store_overview"] = list(overview_rows.values())
            payload["consumer_experience"] = list(consumer_rows.values())
            print(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    indent=2,
                )
            )
            logging.info("店铺指标 dry-run 完成，未写入 Notion")
            return

        if overview_only or consumer_only:
            page_id = find_existing_report_page(notion, config.parent_page_id, period)
            page_created_now = page_id is None
            if page_id is None:
                page_id = create_report_skeleton(notion, config, period)
            if overview_only:
                Stage.value = "写入店铺概况"
                notion.update_store_overview(page_id, overview_rows)
                logging.info(
                    "店铺概况写入完成：页面=%s，数据日期=%s", page_id, snapshot_date
                )
            existing_databases = existing_inline_databases(notion, page_id)
            sync_consumer_experience_database(
                notion,
                page_id,
                snapshot_date,
                consumer_rows,
                existing_databases,
                page_created_now=page_created_now,
            )
            return

        Stage.value = "汇总盈亏数据"
        profit_rows = collect_profit_rows(notion, config.shop_db_ids, period)
        if dry_run:
            print(
                json.dumps(
                    {
                        "snapshot_date": snapshot_date.isoformat(),
                        "store_overview": list(overview_rows.values()),
                        "consumer_experience": list(consumer_rows.values()),
                        "profit": [row.__dict__ for row in profit_rows],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            logging.info("盈亏数据 dry-run 完成，未写入 Notion")
            return

        page_id = find_existing_report_page(notion, config.parent_page_id, period)
        if page_id:
            logging.info("检测到重复周报，不重新创建页面：%s", page_id)
            created_page = False
            existing_databases = existing_inline_databases(notion, page_id)
            normalize_existing_inline_database_views(notion, existing_databases)
            heading_titles = existing_heading_titles(notion, page_id)
            missing_shop_indexes = [
                index for index, shop_name in enumerate(SHOP_NAMES) if shop_name not in existing_databases
            ]
        else:
            page_id = create_report_skeleton(notion, config, period)
            created_page = True
            existing_databases = {}
            heading_titles = set()
            missing_shop_indexes = list(range(7))

        Stage.value = "写入店铺概况"
        notion.update_store_overview(page_id, overview_rows)
        logging.info("店铺概况写入完成：数据日期=%s", snapshot_date)

        consumer_database_id = sync_consumer_experience_database(
            notion,
            page_id,
            snapshot_date,
            consumer_rows,
            existing_databases,
            page_created_now=created_page,
        )
        existing_databases[consumer_experience_database_title(snapshot_date)] = (
            consumer_database_id
        )

        if created_page or "广告情况" not in heading_titles:
            Stage.value = "追加消费者体验分后续板块"
            notion.append_blocks(page_id, post_consumer_experience_blocks())

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
            warnings.append("所选周期全店无广告数据")

        profit_title = profit_database_title(period)
        if profit_title in existing_databases:
            Stage.value = "更新盈亏情况数据"
            notion.sync_profit_rows(existing_databases[profit_title], profit_rows)
            notion.configure_profit_view_order(existing_databases[profit_title])
            logging.info("盈亏情况数据库已存在，已按最新口径更新：%s", profit_title)
        else:
            Stage.value = "追加盈亏情况板块"
            if created_page or "盈亏情况" not in heading_titles:
                notion.append_blocks(page_id, profit_section_blocks())
            else:
                # 兼容旧版已生成页面：旧页面的盈亏标题后已有其他板块，无法移动旧块，
                # 因此在页面尾部补一个明确的自动生成标题，避免数据库脱离标题。
                notion.append_blocks(page_id, [heading_2("盈亏情况（自动生成）")])
            create_profit_database_and_rows(notion, page_id, period, profit_rows)

        if created_page or "其他问题反馈" not in heading_titles:
            Stage.value = "追加后续周报板块"
            notion.append_blocks(page_id, post_profit_blocks())

        append_feedback(notion, page_id, warnings)
        logging.info("周报生成完成：%s", page_id)
    except ErpError as exc:
        # 登录、网页口径与输入日期类错误是可操作提示，不写入崩溃告警页。
        logging.error("无法生成周报：%s: %s", type(exc).__name__, exc)
        raise
    except Exception as exc:
        try:
            send_crash_alert(notion, config.alert_page_id, config.notify_user_id, Stage.value, exc)
        except Exception:
            logging.critical("CRITICAL: notion unreachable", exc_info=True)
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成拼多多周报和盈亏数据库")
    parser.add_argument("--start-date", help="开始日期，格式 YYYY-MM-DD")
    parser.add_argument("--end-date", help="结束日期，格式 YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true", help="只汇总并打印数据，不写入 Notion")
    parser.add_argument(
        "--overview-only",
        action="store_true",
        help="只获取上周六店铺概况和消费者体验分并回填 Notion，不生成广告和盈亏数据",
    )
    parser.add_argument(
        "--consumer-only",
        action="store_true",
        help="只获取上周六消费者体验分并回填 Notion",
    )
    args = parser.parse_args()
    if args.overview_only and args.consumer_only:
        parser.error("--overview-only 和 --consumer-only 不能同时使用")
    if bool(args.start_date) != bool(args.end_date):
        parser.error("--start-date 和 --end-date 必须同时提供")
    return args


def period_from_args(args: argparse.Namespace) -> WeekPeriod:
    if not args.start_date:
        return get_last_week_period()
    try:
        start = date.fromisoformat(args.start_date)
        end = date.fromisoformat(args.end_date)
    except ValueError as exc:
        raise SystemExit(f"日期格式错误：{exc}") from exc
    return period_from_dates(start, end)


if __name__ == "__main__":
    try:
        cli_args = parse_args()
        generate_report(
            period_from_args(cli_args),
            dry_run=cli_args.dry_run,
            overview_only=cli_args.overview_only,
            consumer_only=cli_args.consumer_only,
        )
    except Exception:
        sys.exit(1)
