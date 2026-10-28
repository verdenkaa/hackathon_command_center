"""Stable facts and computed measures shared by analytics and AI context."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.cascade_schemas import CascadeOut
from app.schemas import AnalyticsOut, TaskOut, PredecessorOut, ParticipantOut


class Measure(BaseModel):
    numerator: int
    denominator: int
    percent: float | None
    missing_count: int = 0
    incomplete: bool = False
    unknown_reason: str | None = None


class Progress(BaseModel):
    tasks: Measure
    duration: Measure


class Period(BaseModel):
    start: datetime | None
    deadline: datetime | None
    phase: Literal['no_deadline', 'before_start', 'running', 'overdue', 'unknown_start']
    duration_seconds: int | None
    elapsed_seconds: int | None
    remaining_seconds: int | None
    until_start_seconds: int | None
    overdue_seconds: int | None
    percent: float | None
    unknown_reason: str | None


class PlanSummary(BaseModel):
    incomplete: bool
    status: Literal['completed', 'overdue', 'no_deadline', 'incomplete', 'late', 'on_track']
    finish: datetime | None
    deadline_delta_seconds: int | None
    source: str = 'planning.read.forecast'
    covered_tasks: int
    total_tasks: int
    limitations: list[str]


class Attention(BaseModel):
    code: str
    reason: str
    task_ids: list[int] = Field(default_factory=list)
    incident_id: int | None = None
    user_ids: list[int] = Field(default_factory=list)


class SummaryTask(TaskOut):
    track_name: str | None
    availability: Literal['done', 'active', 'waiting', 'ready']
    waiting_reasons: list[str]
    missing: list[str]


SummaryTask.model_rebuild()


class TrackSummary(BaseModel):
    id: int | None
    name: str
    task_ids: list[int]
    done: int
    total: int
    percent: float | None
    active: int
    waiting: int
    overdue: int
    blocked: int
    incident_ids: list[int]


class IncidentImpact(BaseModel):
    id: int
    number: int
    title: str
    status: str
    level: str
    source_task_id: int | None
    cascade_depth: int
    targets: list[dict[str, str | int]]
    hard_task_ids: list[int]
    potential_task_ids: list[int]
    direct_task_ids: list[int]
    affected_task_ids: list[int]
    track_ids: list[int]
    limitations: list[str]


class Workload(BaseModel):
    id: int
    display_name: str
    traffic_status: str
    incident_ids: list[int]
    task_ids: list[int]
    active_ids: list[int]
    ready_ids: list[int]
    waiting_ids: list[int]
    overlaps: list[list[int]]
    downstream: CascadeOut


class OperationalSummary(BaseModel):
    project_id: int
    generated_at: datetime
    project_state: str
    period: Period
    progress: Progress
    plan: PlanSummary
    tasks: list[SummaryTask]
    tracks: list[TrackSummary]
    incidents: list[IncidentImpact]
    participants: list[Workload]
    attention: list[Attention]
    unassigned_ids: list[int]
    limitations: list[str]
    facts_source: str = 'project, tasks, placements, incident targets and creation events'
    recommendations: list[str] = Field(default_factory=list)


class OperationalAnalytics(AnalyticsOut):
    summary: OperationalSummary


OperationalAnalytics.model_rebuild()
