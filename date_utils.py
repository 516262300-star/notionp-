from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


try:
    SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
except ZoneInfoNotFoundError:
    # Windows Python may not have an IANA timezone database unless tzdata is installed.
    # Shanghai has no DST in the report period, so UTC+8 is a safe local fallback.
    SHANGHAI_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")


@dataclass(frozen=True)
class WeekPeriod:
    start_date: date
    end_date: date
    start_datetime: datetime
    end_datetime: datetime
    iso_week: int
    iso_year: int
    chinese_week: str
    title: str


def int_to_chinese_week(n: int) -> str:
    """把 ISO 周序号 1~53 转成中文数字。"""
    if not 1 <= n <= 53:
        raise ValueError("周序号必须在 1~53 之间")

    digits = "零一二三四五六七八九"
    if n <= 10:
        return "十" if n == 10 else digits[n]
    if n < 20:
        return "十" + digits[n % 10]
    tens, ones = divmod(n, 10)
    text = digits[tens] + "十"
    return text if ones == 0 else text + digits[ones]


def format_cn_date(value: date) -> str:
    return f"{value.year}年{value.month}月{value.day}日"


def get_last_week_period(now: datetime | None = None) -> WeekPeriod:
    """按 Asia/Shanghai 计算上周一到上周日，ISO 周用 date.isocalendar。"""
    current = now.astimezone(SHANGHAI_TZ) if now else datetime.now(SHANGHAI_TZ)
    this_monday = current.date() - timedelta(days=current.weekday())
    start = this_monday - timedelta(days=7)
    end = start + timedelta(days=6)
    iso = start.isocalendar()
    chinese_week = int_to_chinese_week(iso.week)
    title = (
        f"{start.year}时间：第{chinese_week}周"
        f"{format_cn_date(start)}到{format_cn_date(end)}"
    )
    return WeekPeriod(
        start_date=start,
        end_date=end,
        start_datetime=datetime.combine(start, time.min, SHANGHAI_TZ),
        end_datetime=datetime.combine(end, time.max, SHANGHAI_TZ),
        iso_week=iso.week,
        iso_year=iso.year,
        chinese_week=chinese_week,
        title=title,
    )
