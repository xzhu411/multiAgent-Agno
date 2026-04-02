"""
Revenue Operations Pipeline — Demo Entrypoint

Usage:
    python demo/run_demo.py                       # uses data/sample_leads.json
    python demo/run_demo.py --input my_leads.json # custom input file
    python demo/run_demo.py --help

Outputs:
    - Rich terminal table with ranked leads and actions
    - output/report_<timestamp>.md
    - output/report_<timestamp>.json
    - logs/run_<timestamp>.json
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys

# Ensure repo root is on the path regardless of where script is invoked from
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv(override=True)

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from app.models.crm_models import OpsReport
from app.workflows.revops_workflow import create_workflow

console = Console()

_RISK_COLOR = {
    "critical": "bold red",
    "high": "bold yellow",
    "medium": "yellow",
    "low": "green",
}

_RISK_ICON = {
    "critical": "[red]●[/red]",
    "high": "[yellow]●[/yellow]",
    "medium": "[bold yellow]○[/bold yellow]",
    "low": "[green]○[/green]",
}


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(name)-30s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )


def _print_report(report: OpsReport) -> None:
    """Render the report as a Rich table in the terminal."""
    stats = report.pipeline_stats

    # Pipeline stats panel
    stats_text = (
        f"[bold]Leads:[/bold] {stats.total_leads}  |  "
        f"[red]Critical: {stats.critical_count}[/red]  "
        f"[yellow]High: {stats.high_count}[/yellow]  "
        f"[bold yellow]Med: {stats.medium_count}[/bold yellow]  "
        f"[green]Low: {stats.low_count}[/green]\n"
        f"[bold]Pipeline:[/bold] ${stats.total_pipeline_value:,.0f}  |  "
        f"[red]At-Risk: ${stats.at_risk_value:,.0f}[/red]"
    )
    console.print(Panel(stats_text, title="[bold blue]Pipeline Health[/bold blue]", expand=False))
    console.print()

    # Executive summary
    console.print(Panel(report.executive_summary, title="[bold]Executive Summary[/bold]", expand=False))
    console.print()

    # Actions table
    table = Table(
        title="[bold]Prioritized Action List[/bold]",
        box=box.ROUNDED,
        show_lines=True,
        expand=True,
    )
    table.add_column("#", style="dim", width=3)
    table.add_column("Risk", width=9)
    table.add_column("Lead / Company", min_width=22)
    table.add_column("Score", width=7)
    table.add_column("Stage", width=14)
    table.add_column("Deal $", width=12)
    table.add_column("Idle (d)", width=9)
    table.add_column("Top Action", min_width=35)

    for i, item in enumerate(report.ranked_actions, 1):
        sl = item.scored_lead
        lead = sl.lead
        color = _RISK_COLOR.get(sl.risk_level, "white")
        icon = _RISK_ICON.get(sl.risk_level, "○")
        top_action = item.actions[0] if item.actions else None
        action_str = (
            f"[{top_action.priority}] {top_action.action_type}: {top_action.description[:45]}"
            if top_action
            else "—"
        )

        table.add_row(
            str(i),
            f"{icon} {sl.risk_level}",
            f"[{color}]{lead.name[:30]}[/{color}]\n[dim]{lead.company}[/dim]",
            f"[bold]{sl.score}[/bold]",
            lead.stage,
            f"${lead.deal_value:,.0f}",
            str(lead.days_since_last_activity),
            action_str,
        )

    console.print(table)

    if report.review_notes:
        console.print()
        console.print(Panel(report.review_notes, title="[bold]Reviewer Notes[/bold]", expand=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the RevOps multi-agent pipeline.")
    parser.add_argument(
        "--input",
        default="data/sample_leads.json",
        help="Path to CRM leads JSON file (default: data/sample_leads.json)",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    _configure_logging(args.verbose)

    # Check API key
    if not os.getenv("OPENAI_API_KEY") and not os.getenv("ANTHROPIC_API_KEY"):
        console.print("[bold red]Error:[/bold red] No API key set. Add OPENAI_API_KEY or ANTHROPIC_API_KEY to your .env file.")
        sys.exit(1)

    # Load input
    if not os.path.exists(args.input):
        console.print(f"[bold red]Error:[/bold red] Input file not found: {args.input}")
        sys.exit(1)

    with open(args.input) as f:
        raw_leads = json.load(f)

    console.print()
    console.rule("[bold blue]Revenue Operations Pipeline[/bold blue]")
    console.print(f"[dim]Input: {args.input} ({len(raw_leads)} records)[/dim]")
    console.print()

    with console.status("[bold green]Running pipeline...[/bold green]", spinner="dots"):
        workflow = create_workflow()
        wf_output = workflow.run(input=raw_leads)

    # workflow.run() returns WorkflowRunOutput; the StepOutput is in .content
    step_output = wf_output.content
    if step_output is None or not step_output.success:
        error_msg = getattr(step_output, "error", None) or "Unknown error"
        console.print(f"\n[bold red]Pipeline failed:[/bold red] {error_msg}")
        sys.exit(1)

    # Read the report from the latest JSON output file
    import glob as _glob
    json_files = sorted(_glob.glob("output/report_*.json"))
    if not json_files:
        console.print("[bold red]Error:[/bold red] No output report found.")
        sys.exit(1)
    with open(json_files[-1]) as f:
        report = OpsReport(**json.load(f))

    console.print()
    _print_report(report)
    console.print()
    console.rule("[bold green]Done[/bold green]")
    console.print(f"[dim]Report saved to output/  |  Log saved to logs/[/dim]")


if __name__ == "__main__":
    main()
