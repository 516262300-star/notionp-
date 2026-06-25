from __future__ import annotations

import logging
import traceback
from datetime import datetime

from date_utils import SHANGHAI_TZ
from notion_client_wrap import WeeklyReportNotionClient


def traceback_first_lines(exc: BaseException, max_lines: int = 20) -> list[str]:
    lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
    return "".join(lines).splitlines()[:max_lines]


def send_crash_alert(
    notion: WeeklyReportNotionClient,
    alert_page_id: str,
    notify_user_id: str,
    stage: str,
    exc: BaseException,
) -> None:
    timestamp = datetime.now(SHANGHAI_TZ).strftime("%Y-%m-%d %H:%M:%S")
    exc_type = type(exc).__name__
    exc_msg = str(exc)
    traceback_short = "\n".join(traceback_first_lines(exc))
    logging.error("脚本崩溃：%s: %s", exc_type, exc_msg)
    notion.append_blocks(
        alert_page_id,
        [
            {
                "object": "block",
                "type": "callout",
                "callout": {
                    "icon": {"type": "emoji", "emoji": "⚠️"},
                    "color": "red_background",
                    "rich_text": [
                        {
                            "type": "mention",
                            "mention": {"type": "user", "user": {"id": notify_user_id}},
                        },
                        {
                            "type": "text",
                            "text": {"content": f" 拼多多周报脚本失败 · {timestamp}\n"},
                        },
                        {
                            "type": "text",
                            "text": {
                                "content": (
                                    f"位置：{stage}\n"
                                    f"异常：{exc_type}: {exc_msg}\n\n"
                                    f"{traceback_short}"
                                )
                            },
                        },
                    ],
                },
            }
        ],
    )
