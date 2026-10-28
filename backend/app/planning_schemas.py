"""Validated planning commands. All IDs are checked against the URL project."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class PlanningCommand(BaseModel):
    revision: int = Field(ge=0)
    op: Literal['lane_create', 'lane_rename', 'lane_reorder', 'lane_delete', 'place', 'unplace', 'link', 'unlink', 'set_blocker', 'baseline']
    blocking: bool | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)
    lane_id: int | None = None
    target_lane_id: int | None = None
    lane_ids: list[int] = Field(default_factory=list)
    task_id: int | None = None
    source_id: int | None = None
    target_id: int | None = None
    start: datetime | None = None
    estimate_seconds: int | None = Field(default=None, ge=900, le=2147483647)
    pinned: bool | None = None
