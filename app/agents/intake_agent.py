"""
Intake Agent — validates and normalizes raw CRM input.

No LLM involved: intake is purely rule-based Python for speed and reliability.
Handles two failure scenarios:
  1. Catastrophic: >50% of records are unrecoverable → raises IntakeError
  2. Partial: individual record failures are logged as warnings, skipped
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Union

from pydantic import ValidationError

from app.models.crm_models import IntakeError, Lead, LeadBatch, RawLead

logger = logging.getLogger(__name__)

_REQUIRED_FIELDS = {"name", "company", "stage"}
_STAGE_ALIASES = {
    "prospect": "Prospecting",
    "prospecting": "Prospecting",
    "qualify": "Qualification",
    "qualification": "Qualification",
    "proposal": "Proposal",
    "negotiation": "Negotiation",
    "closed won": "Closed Won",
    "won": "Closed Won",
    "closed lost": "Closed Lost",
    "lost": "Closed Lost",
}

_VALID_STAGES = {
    "Prospecting", "Qualification", "Proposal",
    "Negotiation", "Closed Won", "Closed Lost",
}


def _normalize_raw(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Apply defaults and light normalization before Pydantic validation."""
    out = dict(raw)

    # Normalize stage aliases
    stage = str(out.get("stage", "")).strip().lower()
    out["stage"] = _STAGE_ALIASES.get(stage, out.get("stage", "Prospecting"))

    # Defaults
    out.setdefault("deal_value", 0.0)
    out.setdefault("days_since_last_activity", 0)
    out.setdefault("close_date_days_out", 30)
    out.setdefault("num_touches", 0)
    out.setdefault("owner", "Unassigned")
    out.setdefault("notes", "")

    return out


def run_intake(raw_input: Union[str, List[Dict[str, Any]]]) -> LeadBatch:
    """
    Parse and validate raw CRM input.

    Args:
        raw_input: JSON string or list of raw lead dicts.

    Returns:
        LeadBatch with validated leads and any warnings.

    Raises:
        IntakeError: if >50% of records are invalid or input is completely malformed.
    """
    # --- Parse input ---
    if isinstance(raw_input, str):
        try:
            records = json.loads(raw_input)
        except json.JSONDecodeError as exc:
            raise IntakeError(f"Input is not valid JSON: {exc}") from exc
        if not isinstance(records, list):
            raise IntakeError("Input JSON must be a list of lead records.")
    elif isinstance(raw_input, list):
        records = raw_input
    else:
        raise IntakeError(f"Unsupported input type: {type(raw_input).__name__}")

    if not records:
        raise IntakeError("Input contains zero records.")

    leads: List[Lead] = []
    warnings: List[str] = []
    errors: List[str] = []

    for idx, record in enumerate(records):
        if not isinstance(record, dict):
            errors.append(f"Record #{idx}: not a dict (got {type(record).__name__})")
            continue

        # Check required fields
        missing = _REQUIRED_FIELDS - set(record.keys())
        if missing:
            errors.append(f"Record #{idx} ({record.get('name', '?')}): missing required fields {missing}")
            continue

        # Check stage is valid or aliasable
        stage = str(record.get("stage", "")).strip().lower()
        resolved_stage = _STAGE_ALIASES.get(stage, record.get("stage", ""))
        if resolved_stage not in _VALID_STAGES:
            warnings.append(
                f"Record #{idx} ({record.get('name', '?')}): unknown stage '{record['stage']}', defaulting to 'Prospecting'"
            )
            record = dict(record)
            record["stage"] = "Prospecting"

        normalized = _normalize_raw(record)

        try:
            raw_lead = RawLead(**normalized)
            lead = Lead(
                id=raw_lead.id or f"lead_{idx:03d}",
                name=raw_lead.name,
                company=raw_lead.company,
                stage=raw_lead.stage,  # type: ignore[arg-type]
                deal_value=raw_lead.deal_value or 0.0,
                days_since_last_activity=raw_lead.days_since_last_activity or 0,
                close_date_days_out=raw_lead.close_date_days_out if raw_lead.close_date_days_out is not None else 30,
                num_touches=raw_lead.num_touches or 0,
                owner=raw_lead.owner or "Unassigned",
                notes=raw_lead.notes or "",
            )
            leads.append(lead)
        except (ValidationError, TypeError) as exc:
            errors.append(f"Record #{idx} ({record.get('name', '?')}): validation error — {exc}")
            continue

    total = len(records)
    error_rate = len(errors) / total if total > 0 else 1.0

    for w in warnings:
        logger.warning("[Intake] %s", w)
    for e in errors:
        logger.error("[Intake] %s", e)

    if error_rate > 0.5:
        raise IntakeError(
            f"Too many invalid records: {len(errors)}/{total} failed validation. "
            "Aborting to prevent operating on bad data.",
            field_errors={f"error_{i}": e for i, e in enumerate(errors)},
        )

    return LeadBatch(leads=leads, warnings=warnings + errors)
