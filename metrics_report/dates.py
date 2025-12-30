from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

_YMD_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_ymd(value: str | None) -> date | None:
    if not value:
        return None
    if not _YMD_RE.match(value):
        return None
    year, month, day = map(int, value.split("-"))
    return date(year, month, day)


def format_ymd(value: date) -> str:
    return value.isoformat()


def add_days(value: date, days: int) -> date:
    return value + timedelta(days=days)


def today_in_tz(timezone: str) -> date:
    tz = ZoneInfo(timezone)
    return datetime.now(tz=tz).date()


def yesterday_ymd(timezone: str) -> str:
    return format_ymd(add_days(today_in_tz(timezone), -1))


def parse_iso_datetime(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def datetime_to_ymd_in_tz(value: datetime, timezone: str) -> str:
    tz = ZoneInfo(timezone)
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo("UTC"))
    return value.astimezone(tz).date().isoformat()


def daterange_inclusive(start: date, end: date) -> list[date]:
    if end < start:
        return []
    days = (end - start).days
    return [start + timedelta(days=i) for i in range(days + 1)]
