"""
Classification Agent — scores leads and flags risk using rule-based tools + LLM rationale.

The deterministic scoring (score, risk flags, risk level) runs via pure Python tools.
The LLM adds a human-readable score_rationale per lead — keeping the LLM responsible for
language, not math.

Failure handling: if the LLM returns malformed output, we fall back to rule-based defaults
and retry up to MAX_RETRIES times before giving up on rationale (never on the score itself).
"""
from __future__ import annotations

import json
import logging
from typing import List, Tuple

from agno.agent import Agent

from app.agents._model_factory import get_model
from app.models.crm_models import Lead, LeadBatch, ScoredBatch, ScoredLead
from app.tools.scoring_tools import compute_risk_flags, compute_risk_level, compute_score

logger = logging.getLogger(__name__)

MAX_RETRIES = 3


def _build_rationale_agent() -> Agent:
    """Create the Agno agent that generates score rationales."""
    return Agent(
        name="ClassificationAgent",
        model=get_model(),
        output_schema=ScoredBatch,
        instructions=(
            "You are a Revenue Operations analyst. You will receive a JSON list of pre-scored leads. "
            "Each lead already has a numeric `score`, `risk_level`, and `risk_flags` computed by rules. "
            "Your ONLY job is to add a concise `score_rationale` (1-2 sentences) for each lead explaining "
            "WHY it was scored that way, in plain language an AE would understand. "
            "Do NOT change any numeric values. Return the full ScoredBatch JSON with all leads."
        ),
        markdown=False,
    )


def _score_all_deterministically(leads: List[Lead]) -> List[ScoredLead]:
    """Apply rule-based scoring to all leads — always succeeds."""
    results: List[ScoredLead] = []
    for lead in leads:
        score = compute_score(lead)
        flags = compute_risk_flags(lead)
        risk_level = compute_risk_level(score, flags)
        results.append(
            ScoredLead(
                lead=lead,
                score=score,
                risk_level=risk_level,
                risk_flags=flags,
                score_rationale="",
            )
        )
    return results


def run_classification(batch: LeadBatch) -> Tuple[ScoredBatch, int, int, int]:
    """
    Score and classify all leads.

    Returns:
        (ScoredBatch, input_tokens, output_tokens, total_tokens)

    1. Deterministic scoring via pure Python tools (always runs, never fails).
    2. LLM adds rationale — retried up to MAX_RETRIES on failure, then skipped gracefully.
       Token counts are accumulated across retry attempts.
    """
    leads = batch.leads
    scored = _score_all_deterministically(leads)

    payload = {
        "leads": [
            {
                "lead": sl.lead.model_dump(),
                "score": sl.score,
                "risk_level": sl.risk_level,
                "risk_flags": sl.risk_flags,
                "score_rationale": "",
            }
            for sl in scored
        ]
    }
    input_text = json.dumps(payload, indent=2)
    agent = _build_rationale_agent()

    total_in = total_out = total_tok = 0
    last_error: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            run_output = agent.run(input_text)

            # Accumulate tokens across attempts
            m = run_output.metrics
            if m:
                total_in += m.input_tokens or 0
                total_out += m.output_tokens or 0
                total_tok += m.total_tokens or 0

            enriched: ScoredBatch = run_output.content  # type: ignore[assignment]

            if not isinstance(enriched, ScoredBatch):
                raise ValueError(f"Expected ScoredBatch, got {type(enriched).__name__}")

            if len(enriched.leads) != len(scored):
                raise ValueError(
                    f"LLM returned {len(enriched.leads)} leads, expected {len(scored)}"
                )

            for orig, enr in zip(scored, enriched.leads):
                enr.score = orig.score
                enr.risk_level = orig.risk_level
                enr.risk_flags = orig.risk_flags

            logger.info("[Classification] Rationale enrichment succeeded (attempt %d)", attempt)
            return enriched, total_in, total_out, total_tok

        except Exception as exc:
            last_error = exc
            logger.warning(
                "[Classification] Rationale attempt %d/%d failed: %s",
                attempt, MAX_RETRIES, exc,
            )
            if attempt < MAX_RETRIES:
                input_text = (
                    f"The previous response had errors: {exc}. "
                    f"Please fix and return valid ScoredBatch JSON.\n\n{input_text}"
                )

    logger.error(
        "[Classification] All %d rationale attempts failed (%s). "
        "Returning scores without rationale.",
        MAX_RETRIES, last_error,
    )
    return ScoredBatch(leads=scored), total_in, total_out, total_tok
