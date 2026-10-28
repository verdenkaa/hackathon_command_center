"""Versioned provider contracts. No free-form provider metadata is persisted."""
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True, strict=True)


Evidence = Annotated[str, Field(min_length=1, max_length=2000)]
ObjectId = Annotated[int, Field(ge=1)]


class Related(StrictModel):
    task_ids: list[ObjectId] = Field(default_factory=list, max_length=100)
    track_ids: list[ObjectId] = Field(default_factory=list, max_length=100)
    user_ids: list[ObjectId] = Field(default_factory=list, max_length=100)
    incident_ids: list[ObjectId] = Field(default_factory=list, max_length=100)


class Advice(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    situation: str = Field(min_length=1, max_length=3000)
    grounds: list[Evidence] = Field(min_length=1, max_length=20)
    consequence: str = Field(min_length=1, max_length=2000)
    action: str = Field(min_length=1, max_length=3000)
    limitations: list[Evidence] = Field(min_length=1, max_length=20)
    related: Related
    significance: Literal['info', 'warning', 'critical']
    freshness: Literal['current', 'uncertain']


class AnalysisReply(StrictModel):
    result: Literal['recommendations', 'no_new_recommendations']
    recommendations: list[Advice] = Field(max_length=20)

    @model_validator(mode='after')
    def consistent(self) -> 'AnalysisReply':
        if bool(self.recommendations) != (self.result == 'recommendations'):
            raise ValueError('Результат не соответствует списку рекомендаций')
        return self


class QuestionReply(StrictModel):
    answer: str = Field(min_length=1, max_length=12000)
    grounds: list[Evidence] = Field(min_length=1, max_length=30)
    limitations: list[Evidence] = Field(min_length=1, max_length=30)
    related: Related


class AdvisorRequest(StrictModel):
    kind: Literal['analysis', 'question'] = 'analysis'
    question: str = Field(default='', max_length=5000)

    @model_validator(mode='after')
    def has_question(self) -> 'AdvisorRequest':
        if self.kind == 'question' and not self.question:
            raise ValueError('Введите вопрос')
        if self.kind == 'analysis' and self.question:
            raise ValueError('Для вопроса используйте отдельный сценарий')
        return self


class Decision(StrictModel):
    status: Literal['unreviewed', 'accepted', 'rejected', 'deferred']
    comment: str = Field(default='', max_length=2000)


class ProviderPatch(StrictModel):
    model: str | None = Field(default=None, min_length=1, max_length=120, pattern=r'^[a-zA-Z0-9.\-/]+$')
    rpm: int | None = Field(default=None, ge=1, le=10000)
    rpd: int | None = Field(default=None, ge=1, le=1000000)
    tpm: int | None = Field(default=None, ge=100, le=10000000)
    max_attempts: int | None = Field(default=None, ge=1, le=5)
    max_input_tokens: int | None = Field(default=None, ge=100, le=1000000)


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    kind: str
    trigger: str
    state: str
    question: str
    answer: dict | None
    error_code: str | None
    attempts: int
    created_at: datetime
    snapshot_at: datetime | None
    snapshot_version: str | None
    finished_at: datetime | None
    next_attempt_at: datetime

