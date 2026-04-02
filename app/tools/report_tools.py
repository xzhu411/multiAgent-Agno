"""
Report formatting and persistence tools.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import List

from app.models.crm_models import ActionItem, OpsReport, WorkflowRun

_RISK_EMOJI = {
    "critical": "🔴",
    "high": "🟠",
    "medium": "🟡",
    "low": "🟢",
}


def format_markdown_report(report: OpsReport) -> str:
    """Render an OpsReport as a readable markdown string."""
    stats = report.pipeline_stats
    lines: List[str] = []

    lines.append(f"# Revenue Operations Dashboard")
    lines.append(f"**Run ID**: `{report.run_id}`  |  **Generated**: {report.generated_at}")
    lines.append("")
    lines.append("## Executive Summary")
    lines.append(report.executive_summary)
    lines.append("")
    lines.append("## Pipeline Health")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Total leads | {stats.total_leads} |")
    lines.append(f"| 🔴 Critical | {stats.critical_count} |")
    lines.append(f"| 🟠 High risk | {stats.high_count} |")
    lines.append(f"| 🟡 Medium risk | {stats.medium_count} |")
    lines.append(f"| 🟢 Low risk | {stats.low_count} |")
    lines.append(f"| Total pipeline value | ${stats.total_pipeline_value:,.0f} |")
    lines.append(f"| At-risk value | ${stats.at_risk_value:,.0f} |")
    lines.append("")
    lines.append("## Prioritized Action List")
    lines.append("")

    for i, item in enumerate(report.ranked_actions, 1):
        sl = item.scored_lead
        lead = sl.lead
        risk_icon = _RISK_EMOJI.get(sl.risk_level, "⚪")
        lines.append(f"### {i}. {risk_icon} {lead.name} — {lead.company}")
        lines.append(
            f"**Score**: {sl.score}/100 | **Stage**: {lead.stage} | "
            f"**Deal**: ${lead.deal_value:,.0f} | **Owner**: {lead.owner}"
        )
        if sl.risk_flags:
            lines.append(f"**Flags**: {', '.join(sl.risk_flags)}")
        if item.summary:
            lines.append(f"_{item.summary}_")
        lines.append("")
        lines.append("**Recommended Actions:**")
        for action in item.actions:
            lines.append(
                f"- [{action.priority.upper()}] **{action.action_type}** — {action.description} *(owner: {action.owner})*"
            )
        lines.append("")

    if report.review_notes:
        lines.append("## Reviewer Notes")
        lines.append(report.review_notes)

    return "\n".join(lines)


def save_report(report: OpsReport, output_dir: str = "output") -> str:
    """Write markdown report and JSON output to disk. Returns the markdown path."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    md_path = os.path.join(output_dir, f"report_{ts}.md")
    json_path = os.path.join(output_dir, f"report_{ts}.json")

    markdown = format_markdown_report(report)
    with open(md_path, "w") as f:
        f.write(markdown)

    with open(json_path, "w") as f:
        json.dump(report.model_dump(), f, indent=2, default=str)

    return md_path


def save_run_log(run: WorkflowRun, log_dir: str = "logs") -> str:
    """Persist structured observability log. Returns the log file path."""
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(log_dir, f"run_{ts}.json")

    with open(path, "w") as f:
        json.dump(run.model_dump(), f, indent=2, default=str)

    return path
