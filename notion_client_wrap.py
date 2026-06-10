from __future__ import annotations

import logging
import time
from typing import Any, Callable

from notion_client import Client

from aggregator import ReportRow
from network import create_http_client
from page_builder import inline_database_schema, text


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
            ordered_names = [name for name in DEFAULT_VIEW_PROPERTY_ORDER if name in existing_names]
            ordered_names.extend(name for name in existing_names if name not in DEFAULT_VIEW_PROPERTY_ORDER)
            ordered = [
                {
                    "property_id": name,
                    "visible": True,
                    "width": DEFAULT_VIEW_PROPERTY_WIDTHS.get(name, 140),
                }
                for name in ordered_names
            ]
            self._call(
                "views.update",
                self.view_client.request,
                path=f"views/{view_id}",
                method="PATCH",
                body={"configuration": {"type": "table", "properties": ordered}},
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

    def create_summary_row(
        self,
        database_id: str,
        row: ReportRow,
        relation_page_id: str | None = None,
    ) -> None:
        properties: dict[str, Any] = {
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
        self._call(
            "pages.create(database_row)",
            self.client.pages.create,
            parent={"type": "database_id", "database_id": database_id},
            properties=properties,
        )
