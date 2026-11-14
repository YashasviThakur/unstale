"""Scenario checkpoints: 08:00 UTC every morning, plus the scenario's end."""

from __future__ import annotations

from datetime import timedelta

from . import rules


def checkpoints(ds: dict) -> list[str]:
    start, end = rules.parse_ts(ds["start"]), rules.parse_ts(ds["end"])
    day = start.replace(hour=8, minute=0) + timedelta(days=1)
    out = []
    while day < end:
        out.append(day.strftime("%Y-%m-%dT%H:%M:%SZ"))
        day += timedelta(days=1)
    out.append(ds["end"])
    return out
