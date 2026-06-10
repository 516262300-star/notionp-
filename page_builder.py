from __future__ import annotations

from typing import Any


SHOP_NAMES = ["一店", "二店", "三店", "四店", "五店", "六店", "七店"]


def text(content: str, *, bold: bool = False) -> dict[str, Any]:
    rich_text: dict[str, Any] = {"type": "text", "text": {"content": content}}
    if bold:
        rich_text["annotations"] = {"bold": True}
    return rich_text


def heading_2(title: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": [text(title, bold=True)], "is_toggleable": False},
    }


def paragraph(content: str = "") -> dict[str, Any]:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [] if not content else [text(content)]},
    }


def store_overview_callout() -> dict[str, Any]:
    return {
        "object": "block",
        "type": "callout",
        "callout": {
            "icon": {"type": "emoji", "emoji": "📌"},
            "color": "gray_background",
            "rich_text": [
                text("填写格式", bold=True),
                text("：有变化时写“上周值 → 本周值 ▲/▼ 变化值”；持平时直接写本周值，不加箭头；缺数据用“—”。"),
            ],
        },
    }


def _table_cell(content: str, *, bold: bool = False) -> list[dict[str, Any]]:
    return [text(content, bold=bold)] if content else []


def store_overview_table() -> dict[str, Any]:
    header = [
        "店铺",
        "综合体验星级（上周→本周）",
        "成长层级（上周→本周）",
        "店铺评价分排名（上周→本周）",
        "服务体验分（上周→本周）",
    ]
    rows = [
        {
            "object": "block",
            "type": "table_row",
            "table_row": {"cells": [_table_cell(cell, bold=True) for cell in header]},
        }
    ]
    for shop_name in SHOP_NAMES:
        rows.append(
            {
                "object": "block",
                "type": "table_row",
                "table_row": {
                    "cells": [
                        _table_cell(shop_name),
                        _table_cell("— → —"),
                        _table_cell("— → —"),
                        _table_cell("— → —"),
                        _table_cell("— → —"),
                    ]
                },
            }
        )
    return {
        "object": "block",
        "type": "table",
        "table": {
            "table_width": 5,
            "has_column_header": True,
            "has_row_header": False,
            "children": rows,
        },
    }


def initial_page_blocks() -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = [
        heading_2("店铺概况汇总"),
        store_overview_callout(),
        store_overview_table(),
    ]
    for title in [
        "畅销榜排名",
        "前十商品（销售情况）",
        "差评概况",
        "消费者体验分情况",
        "消费者补偿明细",
    ]:
        blocks.append(heading_2(title))
        if title == "消费者补偿明细":
            blocks.extend([paragraph("延迟发货"), paragraph("缺货"), paragraph("虚假发货/虚假轨迹")])

    for title in ["上新建议", "行业分析", "广告情况"]:
        blocks.append(heading_2(title))
    return blocks


def trailing_page_blocks() -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for title in [
        "业务员情况",
        "盈亏情况",
        "图片、视频进展",
        "平台规则变化等",
        "其他问题反馈",
    ]:
        blocks.append(heading_2(title))
        if title == "其他问题反馈":
            blocks.append(paragraph())
    return blocks


def inline_database_schema(main_image_db_id: str) -> dict[str, Any]:
    return {
        "计划类型": {"title": {}},
        "链接主图": {
            "rollup": {
                "relation_property_name": "主图关联",
                "rollup_property_name": "链接主图",
                "function": "show_original",
            }
        },
        "总花费": {"number": {"format": "number"}},
        "成交额": {"number": {"format": "number"}},
        "投产": {"number": {"format": "number"}},
        "成交笔数": {"number": {"format": "number"}},
        "每笔成交花费": {"number": {"format": "number"}},
        "每笔成交金额": {"number": {"format": "number"}},
        "商品ID": {"rich_text": {}},
        "主图关联": {
            "relation": {
                "database_id": main_image_db_id,
                "type": "single_property",
                "single_property": {},
            }
        },
        "序号": {"number": {"format": "number"}},
    }


def warning_paragraph(message: str) -> dict[str, Any]:
    return paragraph(message)
