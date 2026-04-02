"""
All Pydantic models for the RevOps multi-agent workflow.
Typed state objects — no stringly-typed handoffs.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Input models
# ---------------------------------------------------------------------------


class RawLead(BaseModel):
    """Raw CRM record as it arrives from the input source."""

    id: Optional[str] = None
    name: str
    company: str
    stage: str
    deal_value: Optional[float] = None
    days_since_last_activity: Optional[int] = None
    close_date_days_out: Optional[int] = None
    num_touches: Optional[int] = None
    owner: Optional[str] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Normalized lead (post-intake)
# ---------------------------------------------------------------------------


class Lead(BaseModel):
    """Normalized lead after intake validation and enrichment."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str
    company: str
    stage: Literal[
        "Prospecting",
        "Qualification",
        "Proposal",
        "Negotiation",
        "Closed Won",
        "Closed Lost",
    ]
    deal_value: float = Field(ge=0)
    days_since_last_activity: int = Field(ge=0)
    close_date_days_out: int  # negative = overdue
    num_touches: int = Field(ge=0)
    owner: str
    notes: str = ""

    @field_validator("stage", mode="before")
    @classmethod
    def normalize_stage(cls, v: str) -> str:
        mapping = {
            "prospecting": "Prospecting",
            "qualification": "Qualification",
            "proposal": "Proposal",
            "negotiation": "Negotiation",
            "closed won": "Closed Won",
            "closed lost": "Closed Lost",
        }
        return mapping.get(v.lower().strip(), v)


# ---------------------------------------------------------------------------
# Scored lead (post-classification)
# ---------------------------------------------------------------------------

RiskLevel = Literal["low", "medium", "high", "critical"]

RISK_FLAGS = Literal[
    "idle_21_days",
    "idle_30_days",
    "close_date_overdue",
    "close_date_imminent",
    "low_touches",
    "high_value_early_stage",
    "no_recent_activity",
]


class ScoredLead(BaseModel):
    """Lead enriched with priority score and risk classification."""

    lead: Lead
    score: int = Field(ge=0, le=100, description="Priority score 0-100 (higher = more urgent)")
    risk_level: RiskLevel
    risk_flags: List[str] = Field(default_factory=list)
    score_rationale: str = ""

    @field_validator("score", mode="before")
    @classmethod
    def clamp_score(cls, v: Any) -> int:
        return max(0, min(100, int(v)))


# ---------------------------------------------------------------------------
# Action item (post-action agent)
# ---------------------------------------------------------------------------


class RecommendedAction(BaseModel):
    """A single recommended follow-up action."""

    priority: Literal["immediate", "this_week", "this_month"]
    action_type: Literal["call", "email", "meeting", "escalate", "discount", "nurture", "close"]
    description: str
    owner: str


class ActionItem(BaseModel):
    """Scored lead with recommended actions."""

    scored_lead: ScoredLead
    actions: List[RecommendedAction] = Field(min_length=1, max_length=4)
    summary: str = ""


# ---------------------------------------------------------------------------
# Final report
# ---------------------------------------------------------------------------


class PipelineStats(BaseModel):
    total_leads: int
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    total_pipeline_value: float
    at_risk_value: float


class OpsReport(BaseModel):
    """Final output of the RevOps workflow."""

    run_id: str
    generated_at: str
    pipeline_stats: PipelineStats
    ranked_actions: List[ActionItem]  # sorted by score desc
    executive_summary: str
    review_notes: str = ""


# ---------------------------------------------------------------------------
# Observability models
# ---------------------------------------------------------------------------


class AgentTrace(BaseModel):
    """Per-agent execution trace."""

    agent: str
    status: Literal["ok", "error", "skipped"]
    latency_ms: float
    records_in: int = 0
    records_out: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    error_message: Optional[str] = None
    retries: int = 0


class WorkflowRun(BaseModel):
    """Full observability record for one workflow execution."""

    run_id: str
    started_at: str
    total_latency_ms: float
    status: Literal["ok", "error", "partial"]
    agents: List[AgentTrace]
    output_path: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Batch wrappers (for LLM output_model — LLMs can't return bare lists)
# ---------------------------------------------------------------------------


class LeadBatch(BaseModel):
    """Wrapper for a list of normalized leads."""

    leads: List[Lead]
    warnings: List[str] = Field(default_factory=list)


class ScoredBatch(BaseModel):
    """Wrapper for a list of scored leads."""

    leads: List[ScoredLead]


class ActionBatch(BaseModel):
    """Wrapper for a list of action items."""

    items: List[ActionItem]


# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------


class IntakeError(Exception):
    """Raised when intake validation fails beyond recovery."""

    def __init__(self, message: str, field_errors: Optional[Dict[str, str]] = None):
        super().__init__(message)
        self.field_errors = field_errors or {}
