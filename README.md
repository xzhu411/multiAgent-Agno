# RevOps Multi-Agent Pipeline (Agno)

**Track: Option D — Operators Team (Revenue Operations)**

A multi-agent Revenue Operations workflow built with [Agno](https://github.com/agno-agi/agno). Ingests raw CRM data, scores leads, flags at-risk pipeline opportunities, and produces a prioritized action plan for the sales ops team.

---

## Agent Architecture

```
CRM JSON Input
      │
      ▼
┌─────────────────┐
│  Intake Agent   │  Pure Python — validates & normalizes raw records
│  (no LLM)       │  Handles malformed input, defaults, stage aliases
└────────┬────────┘
         │ List[Lead]
         ▼
┌─────────────────────────────┐
│  Classification Agent       │  Agno Agent (claude)
│  + scoring_tools (Python)   │  Rule-based score + LLM rationale
│                             │  Retries up to 3× on bad LLM output
└────────┬────────────────────┘
         │ List[ScoredLead]
         ▼
┌─────────────────┐
│  Action Agent   │  Agno Agent (claude)
│                 │  2-4 specific actions per lead, tailored to risk level
└────────┬────────┘
         │ List[ActionItem]
         ▼
┌─────────────────────────────┐
│  Review / Manager Agent     │  Agno Agent (claude)
│  + self-correction loop     │  Quality check → optional revision → final report
└─────────────────────────────┘
         │
         ▼
  OpsReport (Markdown + JSON)
  WorkflowRun log (JSON)
```

### What each agent does

| Agent | Type | Role |
|---|---|---|
| **IntakeAgent** | Pure Python | Parses raw JSON, validates required fields, normalizes stages, applies defaults. Fails fast on bad input. |
| **ClassificationAgent** | Agno Agent + rule tools | Scores each lead 0-100 using a weighted formula (deal value, recency, stage, touches). Flags risk patterns. LLM adds human-readable rationale. |
| **ActionAgent** | Agno Agent | Recommends 2-4 concrete, prioritized follow-up actions per lead tailored to risk level and stage. |
| **ReviewAgent** | Agno Agent | Aggregates results, runs quality check (self-correction if needed), computes pipeline stats, writes executive summary. |

### Tools used

| Tool | Where | Purpose |
|---|---|---|
| `compute_score()` | scoring_tools.py | Weighted formula scoring (deterministic) |
| `compute_risk_flags()` | scoring_tools.py | Rule-based risk flag detection |
| `compute_risk_level()` | scoring_tools.py | Risk level from score + flags |
| `format_markdown_report()` | report_tools.py | Renders OpsReport as markdown |
| `save_report()` | report_tools.py | Writes output to disk |
| `save_run_log()` | report_tools.py | Persists observability JSON |

---

## Setup

```bash
# 1. Clone and enter the repo
git clone <repo-url> && cd Ango

# 2. Create virtual environment
python3 -m venv .venv && source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements-dev.txt

# 4. Configure API key
cp .env.example .env
# Edit .env and add your API_KEY
```

---

## Running

```bash
# Run with sample data (10 leads)
python demo/run_demo.py

# Run with custom CRM data
python demo/run_demo.py --input path/to/your_leads.json

# Verbose mode (shows agent logs)
python demo/run_demo.py --verbose
```

**Output:**
- Terminal: Rich-formatted priority table + executive summary
- `output/report_<timestamp>.md` — markdown dashboard
- `output/report_<timestamp>.json` — structured JSON
- `logs/run_<timestamp>.json` — observability log

---

## Testing

```bash
# Run all deterministic tests (no API key needed)
pytest tests/test_models.py -v

# Run integration tests (requires API_KEY)
pytest tests/test_workflow.py -v

# Run all
pytest -v
```

---

## Example Output

```
╭─────────── Pipeline Health ───────────╮
│ Leads: 10  |  Critical: 2  High: 3   │
│ Medium: 3  Low: 2                     │
│ Pipeline: $1,105,500  At-Risk: $855K  │
╰───────────────────────────────────────╯

┌── Prioritized Action List ──────────────────────────────────────────────────────┐
│ #  Risk       Lead / Company           Score  Stage        Deal $      Top Action│
│ 1  ● critical DataHarbor — Enterprise   91   Qualification $310,000  [immediate] │
│ 2  ● critical Acme Corp — Enterprise    82   Negotiation   $185,000  [immediate] │
│ 3  ● high     NovaBuild — Annual        79   Qualification $220,000  [immediate] │
│ ...                                                                              │
└──────────────────────────────────────────────────────────────────────────────────┘
```

See `data/sample_leads.json` for the full demo scenario (10 leads with varied risk profiles).

---

## Observability Log

Each run produces a structured JSON log in `logs/`:

```json
{
  "run_id": "a3f2b1c4",
  "started_at": "2026-04-02T10:00:00Z",
  "total_latency_ms": 4850,
  "status": "ok",
  "agents": [
    {"agent": "intake",         "status": "ok", "latency_ms": 12,   "records_in": 10, "records_out": 10},
    {"agent": "classification", "status": "ok", "latency_ms": 1820, "records_in": 10, "records_out": 10},
    {"agent": "action",         "status": "ok", "latency_ms": 1900, "records_in": 10, "records_out": 10},
    {"agent": "review",         "status": "ok", "latency_ms": 1118, "records_in": 10, "records_out": 1}
  ],
  "output_path": "output/report_20260402_100004.md"
}
```

---

## Failure Handling

Two explicit failure scenarios are handled:

**1. Malformed / invalid input (Intake)**
- If input is not valid JSON → `IntakeError` raised immediately with a clear message
- If individual records are missing required fields → logged as warnings, skipped
- If >50% of records fail validation → `IntakeError` raised (prevents operating on bad data)
- The pipeline returns a failed `StepOutput` with the error message

**2. LLM returns invalid structured output (Classification)**
- If the LLM response doesn't match `ScoredBatch` schema → retry with repair prompt (up to 3×)
- On all retries exhausted → fall back to deterministic scores without LLM rationale (never loses the score)
- Score and risk flags are always computed rule-based; LLM only adds language

---

## Stretch Goals Implemented

- **Self-correction loop**: `ReviewAgent` runs a quality check on action output. If any critical/high-risk lead lacks an immediate action, it sends the batch back to `ActionAgent` for one revision before finalizing.
- **Typed state throughout**: All agent handoffs use Pydantic models (`LeadBatch`, `ScoredBatch`, `ActionBatch`, `OpsReport`). No string parsing between steps.

---

## Tradeoffs and Known Limitations

- **Scoring formula is static**: The weighted scoring formula is hand-tuned for the demo. A production system would calibrate weights from historical win/loss data.
- **No parallelism for LLM calls**: All 3 LLM agents run sequentially. For large batches (50+ leads), the action step could be parallelized by lead segment.
- **No CRM integration**: Input is mocked JSON.
- **Token costs scale with lead count**: Sending all leads in one LLM prompt works for 10-20 leads. Larger batches need chunking.
- **Claude Haiku used by default**: Fast and cost-effective for structured JSON output. Swap model via `ANTHROPIC_MODEL` env var (e.g. `claude-opus-4-5`) or switch to OpenAI by setting `OPENAI_API_KEY` instead.

---

## Build Notes (AI-Assisted Development)

- **AI tool used**: Claude Code — used throughout for generating starter code, boilerplate, and written documentation (most parts of README). It produced the initial working skeleton quickly but required significant iteration and hands-on correction.
- **Where AI accelerated**: Project scaffolding (directory layout, `__init__.py` files), Pydantic model definitions, docstrings, test case scaffolding, and written descriptions. Saved several hours of setup and typing.
- **Where AI fell short / needed correction**: The Agno API details were not reliably known by the AI — parameter names like `output_schema` vs `output_model`, the exact `execution_input` parameter name for Workflow steps, and how `RunMetrics` token fields are accessed all required manual inspection of the Agno source and live debugging to get right.
- **Key bugs caught and fixed personally**: (1) `output_model` → `output_schema` for structured output; (2) `load_dotenv(override=True)` to override empty system env vars; (4) Agent OS was rendering raw `StepOutput` JSON instead of markdown, diagnosed that Agno renders `Agent` responses as markdown but not `Workflow` outputs, and rewrote `agent_os.py` to wrap the pipeline in an Agent tool; (5) integration tests skipping problem.
<!-- - **Design decisions made personally**: Keeping Intake as pure Python with no LLM (scores must be deterministic and auditable); separating scoring logic from LLM rationale (LLM can never corrupt the numeric score); the 50% invalid-record threshold for `IntakeError`; the quality-check trigger condition in ReviewAgent; choosing Claude Haiku over GPT-4o-mini for cost vs. quality in this context.
- **What AI wrote that I verified and kept**: The scoring formula weights (30/30/20/20), the risk flag rules, the Pydantic model structure, most of the agent system prompts, and the test assertions — all reviewed and confirmed to match the intended business logic before keeping. -->

AI generated all the starter code and prose; I directed the architecture, caught bug, made all the product judgment calls, and debugged the full end-to-end pipeline to get it actually running.

---

## Project Structure

```
Ango/
├── README.md
├── requirements.txt
├── requirements-dev.txt
├── .env.example
├── app/
│   ├── models/
│   │   └── crm_models.py        # All Pydantic models
│   ├── tools/
│   │   ├── scoring_tools.py     # Rule-based scoring (pure Python)
│   │   └── report_tools.py      # Markdown/JSON output + log persistence
│   ├── agents/
│   │   ├── intake_agent.py      # Validation + normalization (no LLM)
│   │   ├── classification_agent.py  # Scoring + LLM rationale
│   │   ├── action_agent.py      # Action recommendations
│   │   └── review_agent.py      # Aggregation + self-correction
│   └── workflows/
│       └── revops_workflow.py   # Agno Workflow orchestration + observability
├── data/
│   └── sample_leads.json        # 10 demo leads (varied risk profiles)
├── tests/
│   ├── test_models.py           # Deterministic tests (no API key needed)
│   └── test_workflow.py         # LLM integration tests
└── demo/
    └── run_demo.py              # CLI entrypoint
```
