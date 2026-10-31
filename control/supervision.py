"""Bounded health recovery and installation-owned backup retention."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RecoveryPolicy:
    attempts: list[float] = field(default_factory=list)
    grace: float = 90
    delay: float = 90
    limit: int = 3

    @property
    def exhausted(self) -> bool:
        return len(self.attempts) >= self.limit

    def should_restart(self, *, now: float, desired: bool, started: float, healthy: bool, running: bool) -> bool:
        if not desired or healthy or not running or now - started < self.grace or self.exhausted:
            return False
        if self.attempts and now - self.attempts[-1] < self.delay:
            return False
        self.attempts.append(now)
        return True


def retention_candidates(records: list[dict[str, Any]], *, now: float) -> set[str]:
    if not records:
        return set()
    newest = max(records, key=lambda item: item["created"])
    keep = {newest["id"]}
    days: dict[int, dict[str, Any]] = {}
    for record in records:
        age = now - record["created"]
        if age <= 86400:
            keep.add(record["id"])
        elif age <= 8 * 86400:
            day = int(record["created"] // 86400)
            if day not in days or days[day]["created"] < record["created"]:
                days[day] = record
    keep.update(record["id"] for record in sorted(days.values(), key=lambda item: item["created"], reverse=True)[:7])
    return {record["id"] for record in records} - keep
