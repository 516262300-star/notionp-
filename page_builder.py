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


def heading_1(title: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "heading_1",
        "heading_1": {"rich_text": [text(title, bold=True)], "is_toggleable": False},
    }


def paragraph(content: str = "") -> dict[str, Any]:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [] if not content else [text(content)]},
    }


def bulleted_list_item(label: str, content: str = "") -> dict[str, Any]:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [text(label, bold=True), text(content)],
        },
    }


def callout(
    rich_text: list[dict[str, Any]],
    *,
    icon: str,
    color: str,
) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "callout",
        "callout": {
            "icon": {"type": "emoji", "emoji": icon},
            "color": color,
            "rich_text": rich_text,
        },
    }


def divider() -> dict[str, Any]:
    return {"object": "block", "type": "divider", "divider": {}}


def store_overview_callout() -> dict[str, Any]:
    return callout(
        [
            text("填写格式", bold=True),
            text("：有变化时写“上周值 → 本周值 ▲/▼ 变化值”；持平时直接写本周值，不加箭头；缺数据用“—”。"),
        ],
        icon="📌",
        color="gray_background",
    )


def _table_cell(content: str, *, bold: bool = False) -> list[dict[str, Any]]:
    return [text(content, bold=bold)] if content else []


def simple_table(header: list[str], rows: list[list[str]]) -> dict[str, Any]:
    table_rows = [
        {
            "object": "block",
            "type": "table_row",
            "table_row": {"cells": [_table_cell(cell, bold=True) for cell in header]},
        }
    ]
    for row in rows:
        if len(row) != len(header):
            raise ValueError("表格数据列数必须与表头一致")
        table_rows.append(
            {
                "object": "block",
                "type": "table_row",
                "table_row": {"cells": [_table_cell(cell) for cell in row]},
            }
        )
    return {
        "object": "block",
        "type": "table",
        "table": {
            "table_width": len(header),
            "has_column_header": True,
            "has_row_header": False,
            "children": table_rows,
        },
    }


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
        heading_1("🧭 一、本周结论"),
        bulleted_list_item("整体判断："),
        bulleted_list_item("本周最大变化："),
        bulleted_list_item("本周最大风险："),
        bulleted_list_item("本周最值得复制的动作："),
        bulleted_list_item("本周需要会议讨论的事项："),
        callout(
            [
                text(
                    "你的店铺多（九家），结论里不要逐店列，只写本周最影响大盘的 2~3 家。"
                    "其余店放第六节。"
                )
            ],
            icon="💡",
            color="gray_background",
        ),
        divider(),
        heading_1("⚠️ 二、本周问题清单"),
        simple_table(
            ["问题", "店铺", "类型", "影响", "证据（带数字）", "当前判断", "是否需周会讨论"],
            [["", "", "", "", "", "", ""], ["", "", "", "", "", "", ""]],
        ),
        callout(
            [
                text("你这边固定要盯的两个结构性问题，每周必须出现在清单里\n", bold=True),
                text("① 进店即走", bold=True),
                text("：人均浏览 2.09，写本周值 + 环比 + 本周做了什么动作\n"),
                text("② 低客单价跑量", bold=True),
                text("：客单价 39.7 全团最低、广告占比 23.62% 偏高，写本周值 + 利润是否被挤"),
            ],
            icon="🔴",
            color="red_background",
        ),
        divider(),
        heading_1("🔁 三、上周遗留问题追踪"),
        simple_table(
            ["上周问题 / 待办", "本周状态", "本周结果", "未完成原因", "下一步", "负责人"],
            [["", "", "", "", "", ""]],
        ),
        callout(
            [
                text("状态只能填：", bold=True),
                text("已完成 / 部分完成 / 未开始 / 继续观察", bold=True),
                text("。\n同一条连续两周写「继续观察」的，必须在第四节上会。"),
            ],
            icon="⚠️",
            color="yellow_background",
        ),
        divider(),
        heading_1("🗣️ 四、本次周会需要讨论"),
        simple_table(
            ["议题", "为什么要讨论", "希望会议产出什么结论", "优先级"],
            [["", "", "", "高/中/低"]],
        ),
        divider(),
        heading_1("✅ 五、下周行动清单"),
        simple_table(
            ["动作", "负责人", "截止时间", "预期结果", "状态"],
            [["", "", "", "", "未开始/进行中/已完成"]],
        ),
        heading_2("店铺概况汇总"),
        store_overview_callout(),
        store_overview_table(),
    ]
    for title in ["畅销榜排名", "前十商品（销售情况）", "差评概况", "消费者体验分情况"]:
        blocks.append(heading_2(title))

    return blocks


def post_consumer_experience_blocks() -> list[dict[str, Any]]:
    blocks = [
        heading_2("消费者补偿明细"),
        paragraph("延迟发货"),
        paragraph("缺货"),
        paragraph("虚假发货/虚假轨迹"),
    ]

    for title in ["上新建议", "行业分析", "广告情况"]:
        blocks.append(heading_2(title))
    return blocks


def trailing_page_blocks() -> list[dict[str, Any]]:
    return profit_section_blocks() + post_profit_blocks()


def profit_section_blocks() -> list[dict[str, Any]]:
    return [heading_2("业务员情况"), heading_2("盈亏情况")]


def post_profit_blocks() -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for title in ["图片、视频进展", "平台规则变化等", "其他问题反馈"]:
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


def profit_database_schema() -> dict[str, Any]:
    return {
        "项目": {"title": {}},
        "广告成交": {"number": {"format": "number"}},
        "广告费": {"number": {"format": "number"}},
        "ROI": {"number": {"format": "number"}},
        "广告占比": {"number": {"format": "percent"}},
        "发货净利": {"number": {"format": "number"}},
        "毛利-广告": {"number": {"format": "number"}},
        "有效销售": {"number": {"format": "number"}},
        "发货毛利": {"number": {"format": "number"}},
        "序号": {"number": {"format": "number"}},
    }


def consumer_experience_database_schema() -> dict[str, Any]:
    return {
        "店铺": {"title": {}},
        "消费者服务体验分": {"rich_text": {}},
        "服务态度体验分": {"rich_text": {}},
        "基础服务体验分": {"rich_text": {}},
        "发货服务体验分": {"rich_text": {}},
        "商品服务体验分": {"rich_text": {}},
        "物流服务体验分": {"rich_text": {}},
        "数据日期": {"date": {}},
        "序号": {"number": {"format": "number"}},
    }


def warning_paragraph(message: str) -> dict[str, Any]:
    return paragraph(message)
