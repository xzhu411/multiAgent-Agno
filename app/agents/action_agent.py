"""
Action Agent — recommends concrete follow-up actions for each scored lead.

Each lead gets 2-4 prioritized actions tailored to its risk level, stage, and deal size.
The agent is instructed to be specific and operational, not generic.
"""
from __future__ import annotations

import json
import logging
from typing import Tuple

from agno.agent import Agent

from app.agents._model_factory import get_model
from app.models.crm_models import ActionBatch, ScoredBatch

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a Revenue Operations specialist helping sales reps prioritize their pipeline.

For each scored lead provided, recommend 2-4 specific follow-up actions.

Guidelines:
- CRITICAL / HIGH risk leads: recommend immediate actions (calls, escalations, discounts)
- MEDIUM risk leads: recommend this-week actions (emails, meetings)
- LOW risk leads: recommend standard nurture or close actions
- Tailor the action owner to the lead's `owner` field when appropriate
- Be specific: "Send ROI case study email" is better than "follow up"
- action_type must be one of: call, email, meeting, escalate, discount, nurture, close
- priority must be one of: immediate, this_week, this_month

Return a valid ActionBatch JSON with one ActionItem per input lead.
Include a 1-sentence `summary` per item explaining the overall recommended approach.
"""


def run_action(batch: ScoredBatch) -> Tuple[ActionBatch, int, int, int]:
    """Generate recommended actions for all scored leads.

    Returns:
        (ActionBatch, input_tokens, output_tokens, total_tokens)
    """
    payload = {"leads": [sl.model_dump() for sl in batch.leads]}
    input_text = json.dumps(payload, indent=2)

    agent = Agent(
        name="ActionAgent",
        model=get_model(),
        output_schema=ActionBatch,
        instructions=_SYSTEM_PROMPT,
        markdown=False,
    )

    run_output = agent.run(input_text)
    result = run_output.content

    if not isinstance(result, ActionBatch):
        raise ValueError(
            f"ActionAgent returned unexpected type: {type(result).__name__}. "
            "Check that your API key is set and has available credits."
        )

    m = run_output.metrics
    in_tok = (m.input_tokens or 0) if m else 0
    out_tok = (m.output_tokens or 0) if m else 0
    tot_tok = (m.total_tokens or 0) if m else 0

    logger.info("[Action] Generated actions for %d leads", len(result.items))
    return result, in_tok, out_tok, tot_tok
