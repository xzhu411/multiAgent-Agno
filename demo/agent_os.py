"""
Agno Agent OS UI — serves the RevOps pipeline via an Agent (renders markdown).

Usage:
    python demo/agent_os.py

Then open: https://os.agno.com/
Connect to: localhost:7777
Select "Revenue Operations Assistant" → paste leads JSON → run
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv(override=True)

from agno.agent import Agent
from agno.os.app import AgentOS

from app.agents._model_factory import get_model
from app.workflows.revops_workflow import create_workflow

# ── Pipeline tool ────────────────────────────────────────────────────────────
_workflow = create_workflow()


def run_revops_pipeline(crm_json: str) -> str:
    """
    Run the full Revenue Operations pipeline on CRM data.

    Args:
        crm_json: JSON array of lead objects. Each lead must have:
                  id, name, company, stage, deal_value,
                  days_since_last_activity, close_date_days_out,
                  num_touches, owner.

    Returns:
        A markdown-formatted prioritized action report.
    """
    result = _workflow.run(input=crm_json)
    if result and result.content:
        step = result.content          # StepOutput
        if step.success and step.content:
            return step.content        # already a markdown string
        if not step.success:
            return f"**Pipeline error:** {step.error}"
    return "Pipeline produced no output."


# ── Agent (gives Agent OS a chat-style markdown response) ────────────────────
agent = Agent(
    name="Revenue Operations Assistant",
    model=get_model(),
    tools=[run_revops_pipeline],
    markdown=True,
    instructions="""You are a Revenue Operations pipeline assistant.

When the user sends CRM data (a JSON array of lead objects), call the
`run_revops_pipeline` tool immediately with that data and return the
tool result VERBATIM — do not summarize, shorten, or reformat it.

If the user asks a question instead of providing data, answer briefly
and remind them to paste their CRM JSON to run the pipeline.""",
)

# ── Agent OS ──────────────────────────────────────────────────────────────────
agent_os = AgentOS(
    name="RevOps Multi-Agent System",
    agents=[agent],
    workflows=[_workflow],
)

app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(
        "demo.agent_os:app",
        host="localhost",
        port=7777,
        reload=False,
    )
