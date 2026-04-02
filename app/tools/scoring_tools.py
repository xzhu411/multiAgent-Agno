"""
Deterministic, rule-based scoring tools for lead classification.
Pure Python — fast, testable, no LLM required.
"""
from __future__ import annotations

from typing import List

from app.models.crm_models import Lead, RiskLevel

# Stage progression weights (higher = further along)
_STAGE_WEIGHTS = {
    "Prospecting": 10,
    "Qualification": 25,
    "Proposal": 55,
    "Negotiation": 80,
    "Closed Won": 100,
    "Closed Lost": 0,
}

# Deal value thresholds
_HIGH_VALUE = 100_000
_MEDIUM_VALUE = 25_000


def compute_score(lead: Lead) -> int:
    """
    Compute a 0-100 priority score for a lead.

    Weights:
    - Deal value (30%): normalized to high/medium/low bands
    - Recency of activity (30%): fewer idle days = higher score
    - Stage progress (20%): further = higher score
    - Engagement / touches (20%): more touches = higher score
    """
    # Deal value component (0-30)
    if lead.deal_value >= _HIGH_VALUE:
        value_score = 30
    elif lead.deal_value >= _MEDIUM_VALUE:
        value_score = 20
    elif lead.deal_value > 0:
        value_score = 10
    else:
        value_score = 0

    # Recency component (0-30): 0 idle days = 30, 60+ days = 0
    idle = lead.days_since_last_activity
    if idle <= 3:
        recency_score = 30
    elif idle <= 14:
        recency_score = 22
    elif idle <= 21:
        recency_score = 15
    elif idle <= 30:
        recency_score = 8
    else:
        recency_score = 0

    # Stage component (0-20)
    stage_weight = _STAGE_WEIGHTS.get(lead.stage, 0)
    stage_score = int(stage_weight * 0.20)

    # Engagement component (0-20): touches
    touches = lead.num_touches
    if touches >= 10:
        engagement_score = 20
    elif touches >= 5:
        engagement_score = 15
    elif touches >= 2:
        engagement_score = 8
    else:
        engagement_score = 2

    raw = value_score + recency_score + stage_score + engagement_score
    return max(0, min(100, raw))


def compute_risk_flags(lead: Lead) -> List[str]:
    """Return a list of risk flag strings for the lead."""
    flags: List[str] = []

    if lead.days_since_last_activity >= 30:
        flags.append("idle_30_days")
    elif lead.days_since_last_activity >= 21:
        flags.append("idle_21_days")

    if lead.close_date_days_out < 0:
        flags.append("close_date_overdue")
    elif lead.close_date_days_out <= 7:
        flags.append("close_date_imminent")

    if lead.num_touches <= 1:
        flags.append("low_touches")

    if lead.deal_value >= _HIGH_VALUE and lead.stage in ("Prospecting", "Qualification"):
        flags.append("high_value_early_stage")

    if lead.days_since_last_activity >= 14 and lead.num_touches == 0:
        flags.append("no_recent_activity")

    return flags


def compute_risk_level(score: int, flags: List[str]) -> RiskLevel:
    """Derive risk level from score and flags."""
    critical_flags = {"idle_30_days", "close_date_overdue", "high_value_early_stage"}
    has_critical = bool(set(flags) & critical_flags)

    if score < 20 or (has_critical and score < 50):
        return "critical"
    elif score < 40 or has_critical:
        return "high"
    elif score < 65:
        return "medium"
    else:
        return "low"
