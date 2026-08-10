from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any, Callable

from notion_client import Client

from aggregator import ReportRow
from consumer_experience import (
    CONSUMER_EXPERIENCE_FIELDS,
    ConsumerExperience,
    consumer_experience_from_values,
)
from network import create_http_client
from page_builder import (
    consumer_experience_database_schema,
    inline_database_schema,
    profit_database_schema,
    text,
)
from profit_model import ProfitRow
from store_overview import StoreOverview, overview_from_cells


NOTION_VERSION = "2022-06-28"
NOTION_VIEW_VERSION = "2026-03-11"
DEFAULT_VIEW_PROPERTY_ORDER = [
    "计划类型",
    "链接主图",
    "总花费",
    "成交额",
    "投产",
    "成交笔数",
    "每笔成交花费",
    "每笔成交金额",
    "商品ID",
    "主图关联",
    "序号",
]
DEFAULT_VIEW_PROPERTY_WIDTHS = {
    "计划类型": 260,
    "链接主图": 180,
    "总花费": 130,
    "成交额": 130,
    "投产": 110,
    "成交笔数": 120,
    "每笔成交花费": 150,
    "每笔成交金额": 150,
    "商品ID": 150,
    "主图关联": 180,
    "序号": 90,
}
PROFIT_VIEW_PROPERTY_ORDER = [
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
]
PROFIT_VIEW_PROPERTY_WIDTHS = {
    "项目": 150,
    "广告成交": 130,
    "广告费": 120,
    "ROI": 100,
    "广告占比": 110,
    "发货净利": 120,
    "毛利-广告": 130,
    "有效销售": 130,
    "发货毛利": 120,
    "序号": 80,
}
CONSUMER_EXPERIENCE_VIEW_PROPERTY_ORDER = [
    "店铺",
    "消费者服务体验分",
    "服务态度体验分",
    "基础服务体验分",
    "发货服务体验分",
    "商品服务体验分",
    "物流服务体验分",
    "数据日期",
    "序号",
]
CONSUMER_EXPERIENCE_VIEW_PROPERTY_WIDTHS = {
    "店铺": 100,
    "消费者服务体验分": 180,
    "服务态度体验分": 170,
    "基础服务体验分": 170,
    "发货服务体验分": 170,
    "商品服务体验分": 170,
    "物流服务体验分": 170,
    "数据日期": 120,
    "序号": 80,
}


class WeeklyReportNotionClient:
    def __init__(self, token: str):
        self.client = Client(
            auth=token,
            notion_version=NOTION_VERSION,
            client=create_http_client(),
        )
        self.view_client = Client(
            auth=token,
            notion_version=NOTION_VIEW_VERSION,
            client=create_http_client(),
        )

    def _call(self, label: str, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                last_error = exc
                logging.warning("Notion API 调用失败：%s，第 %s 次重试", label, attempt)
                time.sleep(0.8 * attempt)
        assert last_error is not None
        raise last_error

    def list_child_blocks(self, block_id: str) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            kwargs: dict[str, Any] = {"block_id": block_id, "page_size": 100}
            if cursor:
                kwargs["start_cursor"] = cursor
            response = self._call(
                "blocks.children.list",
                self.client.blocks.children.list,
                **kwargs,
            )
            blocks.extend(response.get("results", []))
            if not response.get("has_more"):
                return blocks
            cursor = response.get("next_cursor")

    def append_blocks(self, block_id: str, blocks: list[dict[str, Any]]) -> None:
        for start in range(0, len(blocks), 100):
            self._call(
                "blocks.children.append",
                self.client.blocks.children.append,
                block_id=block_id,
                children=blocks[start : start + 100],
            )

    @staticmethod
    def _plain_text(items: list[dict[str, Any]]) -> str:
        return "".join(item.get("plain_text", "") for item in items)

    def _store_overview_rows(self, page_id: str) -> dict[str, tuple[str, list[str]]]:
        overview_heading_seen = False
        for block in self.list_child_blocks(page_id):
            block_type = block.get("type")
            if block_type in {"heading_1", "heading_2", "heading_3"}:
                title = self._plain_text(block.get(block_type, {}).get("rich_text", []))
                if title == "店铺概况汇总":
                    overview_heading_seen = True
                    continue
                if overview_heading_seen:
                    break
            if block_type != "table" or not overview_heading_seen:
                continue
            rows: dict[str, tuple[str, list[str]]] = {}
            for row in self.list_child_blocks(block["id"]):
                if row.get("type") != "table_row":
                    continue
                cells = [
                    self._plain_text(cell)
                    for cell in row.get("table_row", {}).get("cells", [])
                ]
                if cells and cells[0] in {"一店", "二店", "三店", "四店", "五店", "六店", "七店"}:
                    rows[cells[0]] = (row["id"], cells)
            if len(rows) != 7:
                raise RuntimeError(f"店铺概况表应有 7 家店，实际找到 {len(rows)} 家")
            return rows
        raise RuntimeError("周报页面缺少‘店铺概况汇总’表格")

    def read_store_overview(self, page_id: str) -> dict[str, StoreOverview]:
        return {
            shop_name: overview_from_cells(cells)
            for shop_name, (_, cells) in self._store_overview_rows(page_id).items()
        }

    def update_store_overview(self, page_id: str, rows: dict[str, list[str]]) -> None:
        existing = self._store_overview_rows(page_id)
        for shop_name, cells in rows.items():
            if shop_name not in existing:
                raise RuntimeError(f"店铺概况表缺少 {shop_name}")
            row_id = existing[shop_name][0]
            self._call(
                "blocks.update(store_overview)",
                self.client.request,
                path=f"blocks/{row_id}",
                method="PATCH",
                body={"table_row": {"cells": [[text(cell)] for cell in cells]}},
            )

    def create_report_page(self, parent_page_id: str, title: str, children: list[dict[str, Any]]) -> str:
        response = self._call(
            "pages.create",
            self.client.pages.create,
            parent={"type": "page_id", "page_id": parent_page_id},
            icon={"type": "emoji", "emoji": "📋"},
            properties={
                "title": {
                    "title": [
                        {
                            "type": "text",
                            "text": {"content": title},
                            "annotations": {"bold": True},
                        }
                    ]
                }
            },
            children=children,
        )
        return response["id"]

    def create_inline_database(self, parent_page_id: str, title: str, main_image_db_id: str) -> str:
        response = self._call(
            "databases.create",
            self.client.request,
            path="databases",
            method="POST",
            body={
                "parent": {"type": "page_id", "page_id": parent_page_id},
                "is_inline": True,
                "title": [text(title)],
                "properties": inline_database_schema(main_image_db_id),
            },
        )
        database_id = response["id"]
        self.configure_default_view_order(database_id)
        return database_id

    def configure_default_view_order(self, database_id: str) -> None:
        self._configure_view_order(
            database_id,
            DEFAULT_VIEW_PROPERTY_ORDER,
            DEFAULT_VIEW_PROPERTY_WIDTHS,
            sorts=[{"property": "序号", "direction": "ascending"}],
        )

    def create_profit_database(self, parent_page_id: str, title: str) -> str:
        response = self._call(
            "databases.create(profit)",
            self.client.request,
            path="databases",
            method="POST",
            body={
                "parent": {"type": "page_id", "page_id": parent_page_id},
                "is_inline": True,
                "title": [text(title)],
                "properties": profit_database_schema(),
            },
        )
        database_id = response["id"]
        self.configure_profit_view_order(database_id)
        return database_id

    def create_consumer_experience_database(self, parent_page_id: str, title: str) -> str:
        response = self._call(
            "databases.create(consumer_experience)",
            self.client.request,
            path="databases",
            method="POST",
            body={
                "parent": {"type": "page_id", "page_id": parent_page_id},
                "is_inline": True,
                "title": [text(title)],
                "properties": consumer_experience_database_schema(),
            },
        )
        database_id = response["id"]
        self.configure_consumer_experience_view_order(database_id)
        return database_id

    def configure_consumer_experience_view_order(self, database_id: str) -> None:
        self._configure_view_order(
            database_id,
            CONSUMER_EXPERIENCE_VIEW_PROPERTY_ORDER,
            CONSUMER_EXPERIENCE_VIEW_PROPERTY_WIDTHS,
            hidden={"序号"},
            sorts=[{"property": "序号", "direction": "ascending"}],
        )

    def configure_profit_view_order(self, database_id: str) -> None:
        self._configure_view_order(
            database_id,
            PROFIT_VIEW_PROPERTY_ORDER,
            PROFIT_VIEW_PROPERTY_WIDTHS,
            hidden={"序号"},
        )

    def _configure_view_order(
        self,
        database_id: str,
        property_order: list[str],
        property_widths: dict[str, int],
        *,
        hidden: set[str] | None = None,
        sorts: list[dict[str, str]] | None = None,
    ) -> None:
        hidden = hidden or set()
        views = self._call(
            "views.list",
            self.view_client.request,
            path="views",
            method="GET",
            query={"database_id": database_id},
        )
        for view in views.get("results", []):
            view_id = view["id"]
            view_detail = self._call(
                "views.retrieve",
                self.view_client.request,
                path=f"views/{view_id}",
                method="GET",
            )
            configuration = view_detail.get("configuration", {})
            if configuration.get("type") != "table":
                continue
            existing_names = [prop.get("property_name") for prop in configuration.get("properties", [])]
            ordered_names = [name for name in property_order if name in existing_names]
            ordered_names.extend(name for name in existing_names if name not in property_order)
            ordered = [
                {
                    "property_id": name,
                    "visible": name not in hidden,
                    "width": property_widths.get(name, 140),
                }
                for name in ordered_names
            ]
            self._call(
                "views.update",
                self.view_client.request,
                path=f"views/{view_id}",
                method="PATCH",
                body={
                    "configuration": {"type": "table", "properties": ordered},
                    **({"sorts": sorts} if sorts is not None else {}),
                },
            )

    def query_database_all(self, database_id: str, filter_obj: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        pages: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            kwargs: dict[str, Any] = {"page_size": 100}
            if cursor:
                kwargs["start_cursor"] = cursor
            if filter_obj:
                kwargs["filter"] = filter_obj
            response = self._call(
                "databases.query",
                self.client.request,
                path=f"databases/{database_id}/query",
                method="POST",
                body=kwargs,
            )
            pages.extend(response.get("results", []))
            if not response.get("has_more"):
                return pages
            cursor = response.get("next_cursor")

    def find_main_image_page_id(self, main_image_db_id: str, product_id: str) -> str | None:
        response = self._call(
            "databases.query(main_image)",
            self.client.request,
            path=f"databases/{main_image_db_id}/query",
            method="POST",
            body={
                "page_size": 1,
                "filter": {"property": "商品ID", "title": {"equals": product_id}},
            },
        )
        results = response.get("results", [])
        return results[0]["id"] if results else None

    @staticmethod
    def _summary_row_properties(
        row: ReportRow,
        relation_page_id: str | None,
    ) -> dict[str, Any]:
        return {
            "计划类型": {"title": [text(row.plan_type)]},
            "商品ID": {"rich_text": [text(row.product_id or "")] if row.product_id else []},
            "序号": {"number": row.seq},
            "总花费": {"number": row.total_cost},
            "成交额": {"number": row.revenue},
            "投产": {"number": row.roi},
            "成交笔数": {"number": row.orders},
            "每笔成交花费": {"number": row.cost_per_order},
            "每笔成交金额": {"number": row.revenue_per_order},
            "主图关联": {"relation": [{"id": relation_page_id}] if relation_page_id else []},
        }

    def create_summary_row(
        self,
        database_id: str,
        row: ReportRow,
        relation_page_id: str | None = None,
    ) -> None:
        properties = self._summary_row_properties(row, relation_page_id)
        self._call(
            "pages.create(database_row)",
            self.client.pages.create,
            parent={"type": "database_id", "database_id": database_id},
            properties=properties,
        )

    def sync_summary_rows(
        self,
        database_id: str,
        rows: list[tuple[ReportRow, str | None]],
    ) -> None:
        """按计划类型和商品 ID 更新广告汇总行，并归档已不属于本周的旧行。"""
        existing_by_key: dict[tuple[str, str], str] = {}
        stale_page_ids: list[str] = []
        for page in self.query_database_all(database_id):
            key = (
                self._database_property_text(page, "计划类型"),
                self._database_property_text(page, "商品ID"),
            )
            if key in existing_by_key:
                stale_page_ids.append(page["id"])
            else:
                existing_by_key[key] = page["id"]

        active_page_ids: set[str] = set()
        for row, relation_page_id in rows:
            key = (row.plan_type, row.product_id or "")
            properties = self._summary_row_properties(row, relation_page_id)
            page_id = existing_by_key.get(key)
            if page_id:
                self._call(
                    "pages.update(summary_row)",
                    self.client.pages.update,
                    page_id=page_id,
                    properties=properties,
                )
                active_page_ids.add(page_id)
            else:
                response = self._call(
                    "pages.create(summary_row)",
                    self.client.pages.create,
                    parent={"type": "database_id", "database_id": database_id},
                    properties=properties,
                )
                active_page_ids.add(response["id"])

        stale_page_ids.extend(
            page_id for page_id in existing_by_key.values() if page_id not in active_page_ids
        )
        for page_id in stale_page_ids:
            self._call(
                "pages.archive(summary_row)",
                self.client.pages.update,
                page_id=page_id,
                archived=True,
            )

    def create_profit_row(self, database_id: str, row: ProfitRow) -> None:
        properties = self._profit_row_properties(row)
        self._call(
            "pages.create(profit_row)",
            self.client.pages.create,
            parent={"type": "database_id", "database_id": database_id},
            properties=properties,
        )

    @staticmethod
    def _profit_row_properties(row: ProfitRow) -> dict[str, Any]:
        return {
            "项目": {"title": [text(row.project)]},
            "广告成交": {"number": row.ad_revenue},
            "广告费": {"number": row.ad_cost},
            "ROI": {"number": row.roi},
            "广告占比": {"number": row.ad_share},
            "发货净利": {"number": row.shipping_net_profit},
            "毛利-广告": {"number": row.gross_profit_after_ads},
            "有效销售": {"number": row.effective_sales},
            "发货毛利": {"number": row.shipping_gross_profit},
            "序号": {"number": row.seq},
        }

    def sync_profit_rows(self, database_id: str, rows: list[ProfitRow]) -> None:
        existing_pages = self.query_database_all(database_id)
        existing_by_project: dict[str, str] = {}
        for page in existing_pages:
            title_items = page.get("properties", {}).get("项目", {}).get("title", [])
            project = "".join(item.get("plain_text", "") for item in title_items)
            if project and project not in existing_by_project:
                existing_by_project[project] = page["id"]

        for row in rows:
            properties = self._profit_row_properties(row)
            page_id = existing_by_project.get(row.project)
            if page_id:
                self._call(
                    "pages.update(profit_row)",
                    self.client.pages.update,
                    page_id=page_id,
                    properties=properties,
                )
            else:
                self.create_profit_row(database_id, row)

    @staticmethod
    def _database_property_text(page: dict[str, Any], property_name: str) -> str:
        prop = page.get("properties", {}).get(property_name, {})
        items = prop.get("title") or prop.get("rich_text") or []
        return "".join(item.get("plain_text", "") for item in items)

    def read_consumer_experiences(
        self,
        database_id: str,
    ) -> dict[str, ConsumerExperience]:
        result: dict[str, ConsumerExperience] = {}
        for page in self.query_database_all(database_id):
            shop_name = self._database_property_text(page, "店铺")
            if not shop_name:
                continue
            values = {
                property_name: self._database_property_text(page, property_name)
                for property_name in CONSUMER_EXPERIENCE_FIELDS.values()
            }
            result[shop_name] = consumer_experience_from_values(shop_name, values)
        return result

    @staticmethod
    def _consumer_experience_properties(
        shop_name: str,
        values: dict[str, str],
        snapshot_date: date,
        seq: int,
    ) -> dict[str, Any]:
        return {
            "店铺": {"title": [text(shop_name)]},
            **{
                property_name: {"rich_text": [text(values[property_name])]}
                for property_name in CONSUMER_EXPERIENCE_FIELDS.values()
            },
            "数据日期": {"date": {"start": snapshot_date.isoformat()}},
            "序号": {"number": seq},
        }

    def sync_consumer_experience_rows(
        self,
        database_id: str,
        rows: dict[str, dict[str, str]],
        snapshot_date: date,
    ) -> None:
        existing_by_shop = {
            self._database_property_text(page, "店铺"): page["id"]
            for page in self.query_database_all(database_id)
            if self._database_property_text(page, "店铺")
        }
        for seq, (shop_name, values) in enumerate(rows.items(), start=1):
            properties = self._consumer_experience_properties(
                shop_name, values, snapshot_date, seq
            )
            page_id = existing_by_shop.get(shop_name)
            if page_id:
                self._call(
                    "pages.update(consumer_experience_row)",
                    self.client.pages.update,
                    page_id=page_id,
                    properties=properties,
                )
            else:
                self._call(
                    "pages.create(consumer_experience_row)",
                    self.client.pages.create,
                    parent={"type": "database_id", "database_id": database_id},
                    properties=properties,
                )
        self.configure_consumer_experience_view_order(database_id)
