"""
Tests for Pydantic models and scoring tools.
No LLM calls — fully deterministic.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.crm_models import (
    ActionItem,
    IntakeError,
    Lead,
    RawLead,
    RecommendedAction,
    ScoredLead,
)
from app.tools.scoring_tools import compute_risk_flags, compute_risk_level, compute_score


# ---------------------------------------------------------------------------
# Lead model validation
# ---------------------------------------------------------------------------


def make_lead(**kwargs) -> Lead:
    defaults = dict(
        id="test_001",
        name="Test Lead",
        company="TestCo",
        stage="Proposal",
        deal_value=50000,
        days_since_last_activity=10,
        close_date_days_out=20,
        num_touches=5,
        owner="Alice",
    )
    defaults.update(kwargs)
    return Lead(**defaults)


def test_lead_valid():
    lead = make_lead()
    assert lead.name == "Test Lead"
    assert lead.stage == "Proposal"


def test_lead_stage_normalization():
    lead = Lead(
        id="x",
        name="N",
        company="C",
        stage="proposal",  # lowercase — should be normalized
        deal_value=1000,
        days_since_last_activity=0,
        close_date_days_out=30,
        num_touches=1,
        owner="Bob",
    )
    assert lead.stage == "Proposal"


def test_lead_invalid_deal_value():
    with pytest.raises(ValidationError):
        make_lead(deal_value=-100)


def test_lead_invalid_stage():
    with pytest.raises(ValidationError):
        make_lead(stage="Unknown Stage XYZ")


def test_scored_lead_score_clamp():
    """ScoredLead clamps score to [0, 100]."""
    lead = make_lead()
    sl = ScoredLead(lead=lead, score=150, risk_level="high", risk_flags=[])
    assert sl.score == 100

    sl2 = ScoredLead(lead=lead, score=-50, risk_level="low", risk_flags=[])
    assert sl2.score == 0


# ---------------------------------------------------------------------------
# Scoring tools
# ---------------------------------------------------------------------------


def test_score_high_value_active_lead():
    lead = make_lead(
        deal_value=150000,
        days_since_last_activity=2,
        stage="Negotiation",
        num_touches=12,
    )
    score = compute_score(lead)
    assert score >= 65, f"Expected high score, got {score}"


def test_score_low_value_idle_lead():
    lead = make_lead(
        deal_value=5000,
        days_since_last_activity=45,
        stage="Prospecting",
        num_touches=0,
    )
    score = compute_score(lead)
    assert score <= 25, f"Expected low score, got {score}"


def test_risk_flags_idle():
    lead = make_lead(days_since_last_activity=35)
    flags = compute_risk_flags(lead)
    assert "idle_30_days" in flags


def test_risk_flags_overdue():
    lead = make_lead(close_date_days_out=-10)
    flags = compute_risk_flags(lead)
    assert "close_date_overdue" in flags


def test_risk_flags_high_value_early_stage():
    lead = make_lead(deal_value=200000, stage="Prospecting")
    flags = compute_risk_flags(lead)
    assert "high_value_early_stage" in flags


def test_risk_level_critical():
    score = 15
    flags = ["idle_30_days", "close_date_overdue"]
    level = compute_risk_level(score, flags)
    assert level == "critical"


def test_risk_level_low():
    score = 80
    flags = []
    level = compute_risk_level(score, flags)
    assert level == "low"


def test_score_bounds():
    """Score must always be in [0, 100]."""
    for deal_value in [0, 1000, 50000, 500000]:
        for idle in [0, 7, 21, 60]:
            for stage in ["Prospecting", "Negotiation"]:
                lead = make_lead(deal_value=deal_value, days_since_last_activity=idle, stage=stage)
                score = compute_score(lead)
                assert 0 <= score <= 100, f"Score {score} out of bounds"


# ---------------------------------------------------------------------------
# Intake validation
# ---------------------------------------------------------------------------


def test_intake_rejects_malformed_json():
    from app.agents.intake_agent import run_intake

    with pytest.raises(IntakeError, match="not valid JSON"):
        run_intake("this is not json at all {{{{")


def test_intake_rejects_empty_list():
    from app.agents.intake_agent import run_intake

    with pytest.raises(IntakeError, match="zero records"):
        run_intake([])


def test_intake_rejects_non_list_json():
    from app.agents.intake_agent import run_intake

    import json
    with pytest.raises(IntakeError, match="must be a list"):
        run_intake(json.dumps({"name": "single record not in a list"}))


def test_intake_partial_bad_records():
    """
    If <50% of records are invalid, intake should succeed with warnings.
    """
    from app.agents.intake_agent import run_intake

    records = [
        {
            "id": "ok_001",
            "name": "Good Lead",
            "company": "GoodCo",
            "stage": "Proposal",
            "deal_value": 10000,
            "days_since_last_activity": 5,
            "close_date_days_out": 20,
            "num_touches": 3,
            "owner": "Alice",
        },
        # Missing required 'name' and 'company'
        {"stage": "Qualification", "deal_value": 5000},
        {
            "id": "ok_002",
            "name": "Another Good Lead",
            "company": "GoodCo2",
            "stage": "Negotiation",
            "deal_value": 20000,
            "days_since_last_activity": 3,
            "close_date_days_out": 10,
            "num_touches": 8,
            "owner": "Bob",
        },
    ]
    batch = run_intake(records)
    # 2 out of 3 are valid → should succeed
    assert len(batch.leads) == 2
    assert len(batch.warnings) >= 1


def test_intake_catastrophic_failure():
    """If >50% of records are invalid, intake raises IntakeError."""
    from app.agents.intake_agent import run_intake

    records = [
        # 3 bad records (missing name+company)
        {"stage": "Proposal", "deal_value": 1000},
        {"stage": "Negotiation"},
        {"stage": "Qualification"},
        # 1 good record
        {
            "name": "Good Lead",
            "company": "GoodCo",
            "stage": "Proposal",
            "deal_value": 10000,
            "days_since_last_activity": 5,
            "close_date_days_out": 20,
            "num_touches": 3,
            "owner": "Alice",
        },
    ]
    with pytest.raises(IntakeError, match="Too many invalid records"):
        run_intake(records)
