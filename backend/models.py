"""Typed inputs and outputs shared by the Campus Customs agent team."""

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentRole(str, Enum):
    BOSS = "boss"
    INVENTORY = "inventory"
    ACCOUNTING = "accounting"
    FACILITIES = "facilities"
    CUSTOMER_SERVICE = "customer_service"


class DatabaseFact(BaseModel):
    table: str
    record_id: int | str | None = None
    field: str
    value: Any


class ApprovalRequest(BaseModel):
    kind: Literal["payment", "purchase_order", "discount"]
    reference_table: str | None = None
    reference_id: int | None = None
    amount: float | None = Field(default=None, ge=0)
    amount_basis: Literal[
        "recorded_database_amount", "vendor_quote_required", "not_available"
    ] = "not_available"
    reason: str
    requires_human_approval: Literal[True] = True


class DraftMessage(BaseModel):
    recipient: str
    subject: str
    body: str
    delivery_status: Literal["draft"] = "draft"


class AgentWorkReport(BaseModel):
    summary: str
    facts: list[DatabaseFact] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    approval_requests: list[ApprovalRequest] = Field(default_factory=list)
    draft_messages: list[DraftMessage] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)


class TicketRunResult(BaseModel):
    run_id: str
    ticket_id: int
    status: Literal[
        "analysis_complete", "human_approval_required", "needs_human_review"
    ]
    model: Literal["gpt-6-luna"]
    agent_steps: int
    report: AgentWorkReport
