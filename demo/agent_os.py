"""
Agno Agent OS UI — serves the RevOps workflow in the Agno web interface.

Usage:
    python demo/agent_os.py

Then open: http://localhost:7777
In the UI: select "Revenue Operations Pipeline" → paste leads JSON → run
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv(override=True)

from agno.os.app import AgentOS

from app.workflows.revops_workflow import create_workflow

workflow = create_workflow()

agent_os = AgentOS(
    name="RevOps Multi-Agent System",
    workflows=[workflow],
)

app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(
        "demo.agent_os:app",
        host="localhost",
        port=7777,
        reload=False,
    )
