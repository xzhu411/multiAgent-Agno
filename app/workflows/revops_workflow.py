"""
Revenue Operations Workflow — orchestrates 4 Agno agents end-to-end.

Uses Agno's Workflow class with a callable `steps` function for orchestration.
Tracks per-agent latency, token usage, and success/failure status.

Pipeline:
  intake (Python) → classification (Agno Agent) → action (Agno Agent) → review (Agno Agent)
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Union

from agno.run.agent import RunMetrics
from agno.workflow import Workflow
from agno.workflow.types import StepOutput, WorkflowExecutionInput

from app.agents.action_agent import run_action
from app.agents.classification_agent import run_classification
from app.agents.intake_agent import run_intake
from app.agents.review_agent import run_review
from app.models.crm_models import (
    ActionBatch,
    AgentTrace,
    IntakeError,
    LeadBatch,
    OpsReport,
    ScoredBatch,
    WorkflowRun,
)
from app.tools.report_tools import save_report, save_run_log

logger = logging.getLogger(__name__)


def _extract_tokens(metrics: Any) -> tuple[int, int, int]:
    """Safely extract token counts from Agno RunMetrics or None."""
    if metrics is None:
        return 0, 0, 0
    if isinstance(metrics, RunMetrics):
        return (
            metrics.input_tokens or 0,
            metrics.output_tokens or 0,
            metrics.total_tokens or 0,
        )
    return 0, 0, 0


def _run_pipeline(
    workflow: Workflow, execution_input: WorkflowExecutionInput
) -> StepOutput:
    """
    Core pipeline: runs all 4 agents in sequence and returns the final OpsReport.
    Tracks latency and token usage for observability.
    """
    raw_input: Union[str, list] = execution_input.input  # type: ignore[assignment]
    run_id = str(uuid.uuid4())[:8]
    started_at = datetime.now(timezone.utc).isoformat()
    pipeline_start = time.time()
    traces: list[AgentTrace] = []

    # -------------------------------------------------------------------------
    # Step 1: Intake (pure Python — no LLM)
    # -------------------------------------------------------------------------
    t0 = time.time()
    try:
        lead_batch: LeadBatch = run_intake(raw_input)
        traces.append(AgentTrace(
            agent="intake",
            status="ok",
            latency_ms=round((time.time() - t0) * 1000, 1),
            records_in=len(raw_input) if isinstance(raw_input, list) else -1,
            records_out=len(lead_batch.leads),
        ))
        logger.info("[Workflow] Intake: %d leads normalized", len(lead_batch.leads))
    except IntakeError as exc:
        traces.append(AgentTrace(
            agent="intake",
            status="error",
            latency_ms=round((time.time() - t0) * 1000, 1),
            error_message=str(exc),
        ))
        total_ms = round((time.time() - pipeline_start) * 1000, 1)
        _persist_run_log(run_id, started_at, total_ms, "error", traces, output_path=None)
        return StepOutput(content=None, success=False, error=str(exc))

    # -------------------------------------------------------------------------
    # Step 2: Classification (Agno Agent + rule-based tools)
    # -------------------------------------------------------------------------
    t0 = time.time()
    try:
        scored_batch, c_in, c_out, c_tok = run_classification(lead_batch)
        traces.append(AgentTrace(
            agent="classification",
            status="ok",
            latency_ms=round((time.time() - t0) * 1000, 1),
            records_in=len(lead_batch.leads),
            records_out=len(scored_batch.leads),
            input_tokens=c_in,
            output_tokens=c_out,
            total_tokens=c_tok,
        ))
        logger.info("[Workflow] Classification: %d leads scored", len(scored_batch.leads))
    except Exception as exc:
        logger.error("[Workflow] Classification failed: %s", exc)
        traces.append(AgentTrace(
            agent="classification",
            status="error",
            latency_ms=round((time.time() - t0) * 1000, 1),
            error_message=str(exc),
        ))
        total_ms = round((time.time() - pipeline_start) * 1000, 1)
        _persist_run_log(run_id, started_at, total_ms, "error", traces, output_path=None)
        return StepOutput(content=None, success=False, error=str(exc))

    # -------------------------------------------------------------------------
    # Step 3: Action (Agno Agent)
    # -------------------------------------------------------------------------
    t0 = time.time()
    try:
        action_batch, a_in, a_out, a_tok = run_action(scored_batch)
        traces.append(AgentTrace(
            agent="action",
            status="ok",
            latency_ms=round((time.time() - t0) * 1000, 1),
            records_in=len(scored_batch.leads),
            records_out=len(action_batch.items),
            input_tokens=a_in,
            output_tokens=a_out,
            total_tokens=a_tok,
        ))
        logger.info("[Workflow] Action: %d action plans generated", len(action_batch.items))
    except Exception as exc:
        logger.error("[Workflow] Action agent failed: %s", exc)
        traces.append(AgentTrace(
            agent="action",
            status="error",
            latency_ms=round((time.time() - t0) * 1000, 1),
            error_message=str(exc),
        ))
        total_ms = round((time.time() - pipeline_start) * 1000, 1)
        _persist_run_log(run_id, started_at, total_ms, "error", traces, output_path=None)
        return StepOutput(content=None, success=False, error=str(exc))

    # -------------------------------------------------------------------------
    # Step 4: Review (Agno Agent — includes self-correction)
    # -------------------------------------------------------------------------
    t0 = time.time()
    try:
        report, r_in, r_out, r_tok = run_review(action_batch, scored_batch)
        report.run_id = run_id
        traces.append(AgentTrace(
            agent="review",
            status="ok",
            latency_ms=round((time.time() - t0) * 1000, 1),
            records_in=len(action_batch.items),
            records_out=1,
            input_tokens=r_in,
            output_tokens=r_out,
            total_tokens=r_tok,
        ))
        logger.info("[Workflow] Review complete. Run ID: %s", run_id)
    except Exception as exc:
        logger.error("[Workflow] Review agent failed: %s", exc)
        traces.append(AgentTrace(
            agent="review",
            status="error",
            latency_ms=round((time.time() - t0) * 1000, 1),
            error_message=str(exc),
        ))
        total_ms = round((time.time() - pipeline_start) * 1000, 1)
        _persist_run_log(run_id, started_at, total_ms, "error", traces, output_path=None)
        return StepOutput(content=None, success=False, error=str(exc))

    # -------------------------------------------------------------------------
    # Persist outputs
    # -------------------------------------------------------------------------
    md_path = save_report(report)
    total_ms = round((time.time() - pipeline_start) * 1000, 1)
    log_path = _persist_run_log(run_id, started_at, total_ms, "ok", traces, output_path=md_path)

    logger.info(
        "[Workflow] Pipeline complete in %.0fms. Report: %s | Log: %s",
        total_ms, md_path, log_path,
    )

    # Build a markdown string for Agent OS UI display
    from app.tools.report_tools import format_markdown_report
    markdown_output = format_markdown_report(report)

    return StepOutput(content=markdown_output, success=True)


def _persist_run_log(
    run_id: str,
    started_at: str,
    total_ms: float,
    status: str,
    traces: list[AgentTrace],
    output_path: str | None,
) -> str:
    run = WorkflowRun(
        run_id=run_id,
        started_at=started_at,
        total_latency_ms=total_ms,
        status=status,  # type: ignore[arg-type]
        agents=traces,
        output_path=output_path,
    )
    return save_run_log(run)


def create_workflow() -> Workflow:
    """Instantiate the RevOps Agno Workflow."""
    return Workflow(
        id="revenue-operations-pipeline",
        name="Revenue Operations Pipeline",
        description=(
            "Multi-agent RevOps workflow: validates CRM data, scores and classifies leads, "
            "recommends follow-up actions, and produces a prioritized operator dashboard."
        ),
        steps=_run_pipeline,
    )
