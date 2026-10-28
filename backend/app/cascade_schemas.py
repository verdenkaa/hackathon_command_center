from datetime import datetime
from pydantic import BaseModel, Field


class CascadeLevel(BaseModel):
    depth: int
    hard_task_ids: list[int]
    potential_task_ids: list[int]
    new_hard_count: int
    new_potential_count: int
    user_ids: list[int]
    track_ids: list[int]
    start: datetime | None
    end: datetime | None


class DelayScenario(BaseModel):
    delay_seconds: int
    task_ids: list[int]
    finish_shift_seconds: int


class CascadeOut(BaseModel):
    source_ids: list[int] = Field(default_factory=list)
    levels: list[CascadeLevel] = Field(default_factory=list)
    scenarios: list[DelayScenario] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
