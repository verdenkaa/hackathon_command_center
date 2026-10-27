"""Pydantic-схемы (DTO) API."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import ProjectState, Role


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: Role
    project_id: int | None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    login: str
    display_name: str
    telegram_username: str | None
    active: bool
    avatar: str | None
    created_at: datetime


class MeOut(UserOut):
    roles: list[RoleOut] = Field(default_factory=list)


class LoginRequest(BaseModel):
    login: str
    password: str


class UserCreate(BaseModel):
    login: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    telegram_username: str | None = Field(default=None, max_length=128)


class UserPatch(BaseModel):
    login: str | None = Field(default=None, min_length=1, max_length=128)
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    telegram_username: str | None = Field(default=None, max_length=128)


class PasswordReset(BaseModel):
    new_password: str = Field(min_length=1, max_length=255)


class RoleAssign(BaseModel):
    user_id: int
    role: Role
    project_id: int | None = None


class IpRuleCreate(BaseModel):
    ip: str = Field(min_length=1, max_length=64)


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    deadline_msk: datetime | None
    state: ProjectState
    created_at: datetime


class AuditEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int | None
    actor_id: int | None
    action: str
    entity_type: str | None
    entity_id: str | None
    data: dict
    created_at: datetime


class LoginEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    login: str
    ip: str | None
    user_id: int | None
    success: bool
    reason: str | None
    created_at: datetime


class AuditEdit(BaseModel):
    """Правка текстового поля журнала администратором."""
    field: Literal["action", "entity_type", "entity_id"] | str
    new_value: str


class AuditRevisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    audit_entry_id: int
    field: str
    old_value: str | None
    new_value: str | None
    edited_by: int | None
    edited_at: datetime


# ---------- Kanban, задачи, таймеры ----------


class ColumnOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    key: str
    title: str
    position: int
    auto_start_timer: bool = False
    auto_stop_timer: bool = False


class ColumnCreate(BaseModel):
    title: str = Field(min_length=1, max_length=128)
    auto_start_timer: bool = False
    auto_stop_timer: bool = False


class ColumnPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=128)
    auto_start_timer: bool | None = None
    auto_stop_timer: bool | None = None


class ModuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None


class ModulePatch(BaseModel):
    name: str | None = None
    description: str | None = None


class ModuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    traffic_status: str
    created_at: datetime


class AssigneeIn(BaseModel):
    user_id: int
    is_primary: bool = False


class AssigneesSet(BaseModel):
    assignees: list[AssigneeIn] = Field(default_factory=list)


class AssigneeOut(BaseModel):
    user_id: int
    login: str
    display_name: str
    is_primary: bool


class ChecklistItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    text: str
    done: bool
    position: int


class TimerOut(BaseModel):
    state: str
    accumulated_seconds: int
    elapsed_seconds: int
    total_seconds: int


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    module_id: int | None = None
    priority: str = "medium"
    estimate_seconds: int | None = Field(default=None, ge=0)
    deadline: datetime | None = None
    tags: list[str] = Field(default_factory=list)
    column_key: str = "backlog"
    parent_id: int | None = None


class TaskPatch(BaseModel):
    title: str | None = None
    description: str | None = None
    module_id: int | None = None
    priority: str | None = None
    estimate_seconds: int | None = Field(default=None, ge=0)
    deadline: datetime | None = None
    tags: list[str] | None = None
    version: int


class TaskMove(BaseModel):
    column_key: str
    version: int


class TaskOut(BaseModel):
    id: int
    project_id: int
    column_id: int
    column_key: str
    module_id: int | None
    parent_id: int | None
    title: str
    description: str | None
    priority: str
    estimate_seconds: int | None
    deadline: datetime | None
    tags: list[str]
    version: int
    created_at: datetime
    updated_at: datetime
    assignees: list[AssigneeOut] = Field(default_factory=list)
    predecessors: list[PredecessorOut] = Field(default_factory=list)
    checklist: list[ChecklistItemOut] = Field(default_factory=list)
    timer: TimerOut | None = None


class DependencyCreate(BaseModel):
    predecessor_id: int
    link_type: str = "blocked_by"


class PredecessorOut(BaseModel):
    task_id: int
    link_type: str


class ChecklistCreate(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class ChecklistPatch(BaseModel):
    text: str | None = None
    done: bool | None = None


class TimeAdjustment(BaseModel):
    accumulated_seconds: int = Field(ge=0)


class DeadlinePatch(BaseModel):
    deadline_msk: datetime


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    deadline_msk: datetime | None = None


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class AnalyticsOut(BaseModel):
    kpi: dict
    participants: list[ParticipantOut] = Field(default_factory=list)
    modules: list[dict] = Field(default_factory=list)
    burn_down: list[dict] = Field(default_factory=list)
    time_by_user: list[dict] = Field(default_factory=list)
    active_incidents: list[dict] = Field(default_factory=list)
    risks: list[dict] = Field(default_factory=list)


class DashboardOut(BaseModel):
    project: ProjectOut
    deadline_seconds_left: int | None
    total_tasks: int
    completed_tasks: int
    in_progress_tasks: int
    overdue_tasks: int
    active_timers: int
    active_participants: int
    progress_percent: float
    estimate_seconds: int
    actual_seconds: int
    calendar_seconds: int
    risks: list[dict] = Field(default_factory=list)


# ---------- Инциденты и уведомления ----------


class IncidentTargetIn(BaseModel):
    target_type: str
    target_id: int


class IncidentCreate(BaseModel):
    level: str
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    impact: str | None = None
    urgency: str | None = None
    owner_id: int | None = None
    targets: list[IncidentTargetIn] = Field(default_factory=list)


class IncidentTargetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    target_type: str
    target_id: int


class IncidentEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    incident_id: int
    actor_id: int | None
    event_type: str
    data: dict
    created_at: datetime


class IncidentOut(BaseModel):
    id: int
    project_id: int
    level: str
    status: str
    title: str
    description: str | None
    impact: str | None
    urgency: str | None
    author_id: int
    owner_id: int | None
    resolution: str | None
    created_at: datetime
    confirmed_at: datetime | None
    resolved_at: datetime | None
    age_seconds: int
    targets: list[IncidentTargetOut] = Field(default_factory=list)
    events: list[IncidentEventOut] = Field(default_factory=list)


class ConfirmRed(BaseModel):
    confirm: bool = True
    comment: str | None = None


class ResolveIncident(BaseModel):
    resolution: str = Field(min_length=1)


class CommentIncident(BaseModel):
    text: str = Field(min_length=1)


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int | None
    user_id: int | None
    type: str
    payload: dict
    read_at: datetime | None
    created_at: datetime


class ParticipantOut(BaseModel):
    id: int
    login: str
    display_name: str
    telegram_username: str | None
    traffic_status: str
    active_tasks: int
    active_timer_seconds: int


# ---------- Документы ----------


class DocumentCreate(BaseModel):
    path: str = Field(min_length=1, max_length=512)
    content: str = ""


class DocumentSave(BaseModel):
    content: str
    base_checksum: str


class DocumentOut(BaseModel):
    id: int
    path: str
    author_id: int | None
    checksum: str
    trashed: bool
    created_at: datetime
    updated_at: datetime
    locked_by: int | None = None
    editors: list[int] = Field(default_factory=list)


class DocumentContent(BaseModel):
    content: str


# ---------- ИИ-советник ----------


class AiSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    enabled: bool
    priority_provider: str
    prompt: str
    interval_minutes: int
    triggers: dict


class AiSettingsPatch(BaseModel):
    enabled: bool | None = None
    priority_provider: str | None = None
    prompt: str | None = None
    interval_minutes: int | None = Field(default=None, ge=5, le=1440)
    triggers: dict | None = None


class AiRunRequest(BaseModel):
    trigger: str = "manual"


class AiRecommendationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    provider: str
    trigger: str
    summary: str
    content: str
    excluded: bool
    created_at: datetime
