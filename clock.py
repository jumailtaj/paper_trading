"""Small time helpers. All timestamps in this project are naive datetimes in IST."""
from datetime import datetime, time
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def now_ist() -> datetime:
    return datetime.now(IST).replace(tzinfo=None)


def to_ist_naive(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        dt = dt.astimezone(IST).replace(tzinfo=None)
    return dt


def parse_hhmm(text: str) -> time:
    hh, mm = text.strip().split(":")
    return time(int(hh), int(mm))


def parse_window(text: str):
    """'09:30-14:30' -> (time(9,30), time(14,30))"""
    start, end = text.split("-")
    s, e = parse_hhmm(start), parse_hhmm(end)
    if s >= e:
        raise ValueError(f"Invalid window '{text}': start must be before end")
    return s, e
