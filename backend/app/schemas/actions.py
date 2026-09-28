from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import (
    ActionPlanEventType,
    ActionPlanPriority,
    ActionPlanStatus,
    ActionTaskStatus,
    SignalType,
)

_TITLE_MAX = 255
_DESCRIPTION_MAX = 4000
_TASK_DESCRIPTION_MAX = 2000
_OWNER_LABEL_MAX = 255
_SUCCESS_METRIC_MAX = 500
_EXPECTED_OUTCOME_MAX = 1000


class ActionPlanCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=_TITLE_MAX)
    description: str = Field(min_length=1, max_length=_DESCRIPTION_MAX)
    priority: ActionPlanPriority = ActionPlanPriority.medium
    owner_label: str | None = Field(default=None, max_length=_OWNER_LABEL_MAX)
    due_at: datetime | None = None
    success_metric: str | None = Field(default=None, max_length=_SUCCESS_METRIC_MAX)
    expected_outcome: str | None = Field(default=None, max_length=_EXPECTED_OUTCOME_MAX)


class ActionPlanFromSignalRequest(BaseModel):
    generate_tasks: bool = True
    max_tasks: int | None = Field(default=None, ge=1, le=100)


class ActionPlanUpdateRequest(BaseModel):
    """Partial update: only fields actually present in the request body are
    applied (see the API handler's `exclude_unset=True`) -- an omitted field
    is left untouched, never reset to its default. `version` is always
    required and must match the plan's current version (optimistic
    concurrency); a stale version is rejected with 409, never silently
    overwritten.
    """

    version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=_TITLE_MAX)
    description: str | None = Field(default=None, min_length=1, max_length=_DESCRIPTION_MAX)
    status: ActionPlanStatus | None = None
    priority: ActionPlanPriority | None = None
    owner_label: str | None = Field(default=None, max_length=_OWNER_LABEL_MAX)
    due_at: datetime | None = None
    success_metric: str | None = Field(default=None, max_length=_SUCCESS_METRIC_MAX)
    expected_outcome: str | None = Field(default=None, max_length=_EXPECTED_OUTCOME_MAX)


class ActionTaskCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=_TITLE_MAX)
    description: str | None = Field(default=None, max_length=_TASK_DESCRIPTION_MAX)
    owner_label: str | None = Field(default=None, max_length=_OWNER_LABEL_MAX)
    due_at: datetime | None = None


class ActionTaskUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=_TITLE_MAX)
    description: str | None = Field(default=None, max_length=_TASK_DESCRIPTION_MAX)
    status: ActionTaskStatus | None = None
    owner_label: str | None = Field(default=None, max_length=_OWNER_LABEL_MAX)
    due_at: datetime | None = None


class ActionTaskReorderRequest(BaseModel):
    task_ids: list[UUID] = Field(min_length=1)


class ActionPlanProgressOut(BaseModel):
    total_tasks: int
    completed_tasks: int
    blocked_tasks: int
    active_tasks: int
    completion_percentage: float
    overdue_task_count: int
    plan_overdue: bool


class ActionTaskResponse(BaseModel):
    id: UUID
    action_plan_id: UUID
    title: str
    description: str | None
    status: ActionTaskStatus
    position: int
    owner_label: str | None
    due_at: datetime | None
    completed_at: datetime | None
    source_recommendation_index: int | None
    created_at: datetime
    updated_at: datetime


class ActionPlanResponse(BaseModel):
    id: UUID
    source_signal_id: UUID | None
    source_job_id: UUID | None
    source_signal_type: SignalType | None
    title: str
    description: str
    status: ActionPlanStatus
    priority: ActionPlanPriority
    owner_label: str | None
    due_at: datetime | None
    success_metric: str | None
    expected_outcome: str | None
    version: int
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    archived_at: datetime | None
    progress: ActionPlanProgressOut


class ActionPlanListResponse(BaseModel):
    plans: list[ActionPlanResponse]
    total: int
    limit: int
    offset: int


class ActionPlanFromSignalResponse(BaseModel):
    plan: ActionPlanResponse
    tasks: list[ActionTaskResponse]


class ActionPlanEventResponse(BaseModel):
    id: UUID
    action_plan_id: UUID
    actor_user_id: UUID | None
    event_type: ActionPlanEventType
    previous_values: dict
    new_values: dict
    created_at: datetime


class ActionPlanEventListResponse(BaseModel):
    events: list[ActionPlanEventResponse]
    total: int
    limit: int
    offset: int
