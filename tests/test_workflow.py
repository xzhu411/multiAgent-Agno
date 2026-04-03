"""
Integration smoke test for the full workflow.

These tests require ANTHROPIC_API_KEY to be set. They call the real LLM.
Skipped automatically if the key is not available.
"""
from __future__ import annotations

import json
import os

import pytest
from dotenv import load_dotenv

# Load .env BEFORE checking env vars (system env may have empty strings)
load_dotenv(override=True)

# Skip all tests in this module if no API key is set
pytestmark = pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set — skipping LLM integration tests",
)


SAMPLE_LEADS = [
    {
        "id": "t_001",
        "name": "Alpha Corp — Enterprise",
        "company": "Alpha Corp",
        "stage": "Negotiation",
        "deal_value": 90000,
        "days_since_last_activity": 5,
        "close_date_days_out": 8,
        "num_touches": 14,
        "owner": "Sarah Chen",
        "notes": "Close to signing.",
    },
    {
        "id": "t_002",
        "name": "BetaTech — Risk Account",
        "company": "BetaTech",
        "stage": "Proposal",
        "deal_value": 140000,
        "days_since_last_activity": 40,
        "close_date_days_out": -3,
        "num_touches": 2,
        "owner": "Marcus Webb",
        "notes": "Gone dark. Overdue.",
    },
    {
        "id": "t_003",
        "name": "GammaSoft — Small Deal",
        "company": "GammaSoft",
        "stage": "Qualification",
        "deal_value": 8000,
        "days_since_last_activity": 3,
        "close_date_days_out": 45,
        "num_touches": 5,
        "owner": "Jordan Park",
        "notes": "Healthy small deal.",
    },
]


def test_happy_path_full_pipeline():
    """Run the full pipeline with 3 valid leads and verify structure of output."""
    import glob as _glob
    import json as _json
    from app.models.crm_models import OpsReport
    from app.workflows.revops_workflow import create_workflow

    # Snapshot existing output files before running so we can find the new one
    before = set(_glob.glob("output/report_*.json"))

    workflow = create_workflow()
    result = workflow.run(input=SAMPLE_LEADS)

    step_output = result.content
    assert step_output is not None and step_output.success, (
        f"Pipeline failed: {getattr(step_output, 'error', 'unknown')}"
    )

    # Find the newly created report (not one from a previous run)
    after = set(_glob.glob("output/report_*.json"))
    new_files = sorted(after - before)
    assert new_files, "No new output report JSON was created by this run"
    with open(new_files[-1]) as f:
        report = OpsReport(**_json.load(f))
    assert report.run_id
    assert report.pipeline_stats.total_leads == 3
    assert len(report.ranked_actions) == 3
    assert report.executive_summary

    # Verify sort order: scores should be descending
    scores = [item.scored_lead.score for item in report.ranked_actions]
    assert scores == sorted(scores, reverse=True), "Actions not sorted by score desc"

    # Verify risk classification
    risk_levels = {item.scored_lead.lead.id: item.scored_lead.risk_level for item in report.ranked_actions}
    # t_002 (idle 40d, overdue) should be critical or high
    assert risk_levels.get("t_002") in ("critical", "high"), f"Expected t_002 to be critical/high, got {risk_levels.get('t_002')}"

    # Verify each lead has at least one action
    for item in report.ranked_actions:
        assert len(item.actions) >= 1, f"Lead {item.scored_lead.lead.name} has no actions"


def test_pipeline_fails_on_bad_input():
    """Pipeline should raise IntakeError and return failed StepOutput for bad input."""
    from app.models.crm_models import IntakeError
    from app.workflows.revops_workflow import create_workflow

    workflow = create_workflow()
    result = workflow.run(input="this is completely invalid JSON {{{{")

    step_output = result.content
    assert step_output is not None
    assert step_output.success is False
    assert step_output.error is not None
