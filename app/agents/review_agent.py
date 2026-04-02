"""
Review / Manager Agent — aggregates, quality-checks, and produces the final OpsReport.

Stretch goal: self-correction loop. If the quality check fails, the ReviewAgent sends
the ActionBatch back to the ActionAgent for one revision before finalizing.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import List, Tuple

from agno.agent import Agent

from app.agents._model_factory import get_model
from app.agents.action_agent import run_action
from app.models.crm_models import ActionBatch, ActionItem, OpsReport, PipelineStats, ScoredBatch

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a Revenue Operations Manager reviewing a prioritized action plan prepared by your team.

You will receive a JSON list of ActionItems, each with a scored lead and recommended actions.

Your tasks:
1. Write a concise `executive_summary` (3-5 sentences) highlighting the pipeline health, top risks, and key priorities for the team today.
2. Add brief `review_notes` (1-3 bullets) flagging anything the team should be aware of (e.g. unusually large at-risk deals, accounts with no owner, etc.).
3. Rank the `ranked_actions` list by descending priority score (score is already computed; use it).
4. Compute `pipeline_stats` from the data.

Return a valid OpsReport JSON. Use the run_id and generated_at values provided in the input.
"""


def _compute_pipeline_stats(items: List[ActionItem], run_id: str) -> PipelineStats:
    """Compute pipeline stats from action items (deterministic, used as fallback)."""
    total_value = 0.0
    at_risk_value = 0.0
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}

    for item in items:
        sl = item.scored_lead
        lead = sl.lead
        total_value += lead.deal_value
        counts[sl.risk_level] = counts.get(sl.risk_level, 0) + 1
        if sl.risk_level in ("critical", "high"):
            at_risk_value += lead.deal_value

    return PipelineStats(
        total_leads=len(items),
        critical_count=counts["critical"],
        high_count=counts["high"],
        medium_count=counts["medium"],
        low_count=counts["low"],
        total_pipeline_value=total_value,
        at_risk_value=at_risk_value,
    )


def _quality_check(batch: ActionBatch) -> tuple[bool, str]:
    """
    Basic quality check on action output before finalizing.
    Returns (passed, reason).
    """
    for item in batch.items:
        if not item.actions:
            return False, f"Lead '{item.scored_lead.lead.name}' has no actions"
        if item.scored_lead.risk_level in ("critical", "high"):
            has_immediate = any(a.priority == "immediate" for a in item.actions)
            if not has_immediate:
                return False, (
                    f"Critical/high lead '{item.scored_lead.lead.name}' "
                    "has no immediate action"
                )
    return True, "ok"


def run_review(action_batch: ActionBatch, scored_batch: ScoredBatch) -> Tuple[OpsReport, int, int, int]:
    """
    Review and finalize the action plan.

    Includes a self-correction loop: if quality check fails, sends back to
    ActionAgent for one revision before finalizing.

    Returns:
        (OpsReport, input_tokens, output_tokens, total_tokens)
    """
    run_id = str(uuid.uuid4())[:8]
    generated_at = datetime.now(timezone.utc).isoformat()
    total_in = total_out = total_tok = 0

    # --- Self-correction loop (stretch goal) ---
    passed, reason = _quality_check(action_batch)
    if not passed:
        logger.warning("[Review] Quality check failed: %s — requesting revision", reason)
        revised_batch, r_in, r_out, r_tok = run_action(scored_batch)
        total_in += r_in; total_out += r_out; total_tok += r_tok
        passed_again, reason2 = _quality_check(revised_batch)
        if passed_again:
            action_batch = revised_batch
            logger.info("[Review] Revision passed quality check.")
        else:
            logger.warning("[Review] Revision still failed (%s). Using original output.", reason2)

    # Sort by score descending (deterministic, no LLM needed)
    items_sorted = sorted(
        action_batch.items,
        key=lambda x: x.scored_lead.score,
        reverse=True,
    )

    stats = _compute_pipeline_stats(items_sorted, run_id)

    # Build input for LLM to generate summaries
    payload = {
        "run_id": run_id,
        "generated_at": generated_at,
        "pipeline_stats": stats.model_dump(),
        "items": [item.model_dump() for item in items_sorted],
    }
    input_text = json.dumps(payload, indent=2)

    agent = Agent(
        name="ReviewAgent",
        model=get_model(),
        output_schema=OpsReport,
        instructions=_SYSTEM_PROMPT,
        markdown=False,
    )

    run_output = agent.run(input_text)
    report: OpsReport = run_output.content  # type: ignore[assignment]

    if not isinstance(report, OpsReport):
        raise ValueError(f"ReviewAgent returned unexpected type: {type(report).__name__}")

    m = run_output.metrics
    if m:
        total_in += m.input_tokens or 0
        total_out += m.output_tokens or 0
        total_tok += m.total_tokens or 0

    # Ensure our deterministic fields are not overwritten by the LLM
    report.run_id = run_id
    report.generated_at = generated_at
    report.pipeline_stats = stats
    report.ranked_actions = items_sorted

    logger.info("[Review] Report finalized: %d leads, run_id=%s", len(items_sorted), run_id)
    return report, total_in, total_out, total_tok
