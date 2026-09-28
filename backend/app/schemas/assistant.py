from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import AssistantMessageRole, AssistantScopeType, SourceType

_QUESTION_MAX_CHARS = 4000


class CreateAssistantSessionRequest(BaseModel):
    scope_type: AssistantScopeType
    # Required iff scope_type == "source"; ignored otherwise.
    source_type: SourceType | None = None
    # Required iff scope_type == "job"; ignored otherwise. Ownership is
    # verified server-side at creation time -- see AssistantService.
    job_id: UUID | None = None


class AssistantCitation(BaseModel):
    """A citation is only ever built server-side from evidence a tool
    actually retrieved during the turn that produced it -- never trusted
    verbatim from the LLM's own output. See app/services/assistant/agent.py
    for the hydration/validation step."""

    job_id: UUID
    #: A SourceRecord id for comment/issue/post citations, or a web evidence
    #: id such as ``content.word_count`` for a web page analysis -- so a
    #: string, not a UUID.
    record_id: str
    record_type: str | None = None
    excerpt: str | None = None
    #: Grounding fields, all from persisted evidence metadata (never from the
    #: model). Optional so pre-grounding citations stay valid.
    source_type: str | None = None
    source_key: str | None = None
    label: str | None = None
    url: str | None = None
    path: str | None = None
    line: int | None = None


class ToolCallTrace(BaseModel):
    tool: str
    status: Literal["success", "error", "cached"]
    arguments: dict[str, Any]
    result_summary: str


class AssistantMessageOut(BaseModel):
    id: UUID
    role: AssistantMessageRole
    content: str
    citations: list[AssistantCitation]
    tool_calls: list[ToolCallTrace]
    created_at: datetime

    model_config = {"from_attributes": True}


class AssistantSessionOut(BaseModel):
    id: UUID
    title: str | None
    scope_type: AssistantScopeType
    source_type: SourceType | None
    job_id: UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AssistantSessionListResponse(BaseModel):
    sessions: list[AssistantSessionOut]
    total: int
    limit: int
    offset: int


class AssistantSessionWithMessagesResponse(AssistantSessionOut):
    messages: list[AssistantMessageOut]


class AssistantTurnContext(BaseModel):
    """What the user had on screen when they asked.

    Sent per MESSAGE rather than stored on the session, because it changes
    every time the user navigates while the conversation does not. A session
    scoped to one analysis can be asked about its Relationships page and then
    its Trends page without becoming a different conversation.

    Untrusted by construction. It can point at a section of an analysis the
    session may already read; it can never widen that scope, and it is never
    read as a measurement -- see app/services/assistant/page_context.py.
    """

    #: One of page_context.PAGE_SECTIONS. Anything else is ignored.
    page: str = Field(max_length=64)
    entity_type: str | None = Field(default=None, max_length=64)
    entity_label: str | None = Field(default=None, max_length=200)
    #: A handful of already-rendered figures, flat. Bounded again server-side.
    facts: dict[str, Any] = Field(default_factory=dict)


class SendAssistantMessageRequest(BaseModel):
    question: str = Field(min_length=1, max_length=_QUESTION_MAX_CHARS)
    #: Optional. Its absence is the ordinary case -- the Assistant page
    #: reached directly has no page context to send.
    context: AssistantTurnContext | None = None


class SendAssistantMessageResponse(BaseModel):
    status: Literal["ok", "unavailable", "error"]
    reason: str | None = None
    message: AssistantMessageOut | None = None
