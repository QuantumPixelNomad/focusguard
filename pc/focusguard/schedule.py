"""Weekly schedule maths. Days are 0=Monday .. 6=Sunday; times are local 'HH:MM'.

An entry whose end is not after its start runs past midnight into the next day."""
from __future__ import annotations

from datetime import datetime, timedelta


def _minutes(hm: str) -> int:
    h, m = hm.split(":")
    return int(h) * 60 + int(m)


def _at(day: datetime, minutes: int) -> datetime:
    return day.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(minutes=minutes)


def entry_end(entry: dict, now: datetime) -> datetime | None:
    """When the entry's current window ends, or None if it is not running at `now`."""
    if not entry.get("enabled", True) or not entry.get("days"):
        return None
    start, end = _minutes(entry["start"]), _minutes(entry["end"])
    t = now.hour * 60 + now.minute
    today, yesterday = now.weekday(), (now.weekday() - 1) % 7
    if start < end:
        if today in entry["days"] and start <= t < end:
            return _at(now, end)
        return None
    if today in entry["days"] and t >= start:
        return _at(now + timedelta(days=1), end)
    if yesterday in entry["days"] and t < end:
        return _at(now, end)
    return None


def active_until(schedules: list, now: datetime) -> datetime | None:
    """End of the block running at `now`, following back-to-back entries. None if idle."""
    until = None
    probe = now
    for _ in range(16):
        ends = [e for e in (entry_end(s, probe) for s in schedules) if e]
        if not ends:
            break
        latest = max(ends)
        if until is not None and latest <= until:
            break
        until = latest
        probe = latest
    return until


def next_start(schedules: list, now: datetime) -> datetime | None:
    best = None
    for s in schedules:
        if not s.get("enabled", True) or not s.get("days"):
            continue
        start = _minutes(s["start"])
        for offset in range(8):
            day = now + timedelta(days=offset)
            if day.weekday() not in s["days"]:
                continue
            candidate = _at(day, start)
            if candidate > now and (best is None or candidate < best):
                best = candidate
    return best
