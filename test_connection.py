from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
from notion_client import Client

from network import create_http_client, proxy_hint


NOTION_VERSION = "2022-06-28"


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"缺少环境变量：{name}")
    return value


def ok(label: str, value: str) -> None:
    print(f"[OK] {label}: {value}")


def fail(label: str, exc: Exception) -> None:
    print(f"[FAIL] {label}: {type(exc).__name__}: {exc}")


def main() -> int:
    load_dotenv()
    client = Client(
        auth=require_env("NOTION_TOKEN"),
        notion_version=NOTION_VERSION,
        client=create_http_client(),
    )
    print(proxy_hint())

    checks: list[tuple[str, str, str]] = [
        ("父页面 PARENT_PAGE_ID", "page", require_env("PARENT_PAGE_ID")),
        ("主图库 MAIN_IMAGE_DB_ID", "database", require_env("MAIN_IMAGE_DB_ID")),
        ("告警页 ALERT_PAGE_ID", "page", require_env("ALERT_PAGE_ID")),
    ]
    for index in range(1, 8):
        checks.append((f"{index}店 SHOP_{index}_DB_ID", "database", require_env(f"SHOP_{index}_DB_ID")))

    failed = 0
    for label, kind, notion_id in checks:
        try:
            if kind == "page":
                page = client.pages.retrieve(page_id=notion_id)
                ok(label, page.get("id", notion_id))
            else:
                database = client.databases.retrieve(database_id=notion_id)
                ok(label, database.get("id", notion_id))
        except Exception as exc:
            failed += 1
            fail(label, exc)

    if failed:
        print(f"\n连接测试未通过：{failed} 项失败。")
        print("如果全部项目都是 ConnectError / WinError 10054，通常是当前网络或 Clash 节点到 Notion API 的 HTTPS 被断开。")
        print("请先在 Clash Verge 切换一个可访问 Notion 的节点，或在 .env 设置 NOTION_PROXY=http://127.0.0.1:7897 后重试。")
        print("如果只有个别页面失败，再检查对应 ID 和 Notion Integration 权限。")
        return 1

    print("\n连接测试通过：所有页面和数据库都能读取。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
