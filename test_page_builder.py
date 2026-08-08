from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from main import single_instance_lock
from page_builder import initial_page_blocks


class WeeklyReportTemplateTests(unittest.TestCase):
    def test_initial_blocks_follow_official_template_order(self) -> None:
        blocks = initial_page_blocks()
        headings = []
        for block in blocks:
            block_type = block["type"]
            if block_type not in {"heading_1", "heading_2"}:
                continue
            headings.append(block[block_type]["rich_text"][0]["text"]["content"])

        self.assertEqual(
            headings,
            [
                "🧭 一、本周结论",
                "⚠️ 二、本周问题清单",
                "🔁 三、上周遗留问题追踪",
                "🗣️ 四、本次周会需要讨论",
                "✅ 五、下周行动清单",
                "店铺概况汇总",
                "畅销榜排名",
                "前十商品（销售情况）",
                "差评概况",
                "消费者体验分情况",
            ],
        )

    def test_template_tables_match_expected_column_counts(self) -> None:
        tables = [block for block in initial_page_blocks() if block["type"] == "table"]
        self.assertEqual([table["table"]["table_width"] for table in tables], [7, 6, 4, 5, 5])
        self.assertEqual(len(tables[0]["table"]["children"]), 3)
        self.assertEqual(len(tables[-1]["table"]["children"]), 8)

    def test_second_generator_is_blocked_while_first_is_running(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lock_path = Path(temp_dir) / "weekly-report.lock"
            with single_instance_lock(lock_path):
                with self.assertRaisesRegex(RuntimeError, "已有一个拼多多周报生成任务"):
                    with single_instance_lock(lock_path):
                        pass


if __name__ == "__main__":
    unittest.main()
