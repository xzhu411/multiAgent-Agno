# Revenue Operations Multi-Agent Pipeline — 详细说明 / Detailed Explanation

> **Agno Take-Home Exercise · Option D: Operators Team (Revenue Operations)**
> GitHub: https://github.com/xzhu411/multiAgent-Agno

---

## 目录 / Table of Contents

1. [项目概述 / Project Overview](#1-项目概述--project-overview)
2. [系统架构 / System Architecture](#2-系统架构--system-architecture)
3. [文件结构 / File Structure](#3-文件结构--file-structure)
4. [数据模型 / Data Models](#4-数据模型--data-models)
5. [工具层 / Tools Layer](#5-工具层--tools-layer)
6. [Agent 实现详解 / Agent Implementations](#6-agent-实现详解--agent-implementations)
7. [工作流与可观测性 / Workflow & Observability](#7-工作流与可观测性--workflow--observability)
8. [错误处理 / Failure Handling](#8-错误处理--failure-handling)
9. [测试数据 / Sample Data](#9-测试数据--sample-data)
10. [运行方式 / How to Run](#10-运行方式--how-to-run)
11. [关键设计决策 / Key Design Decisions](#11-关键设计决策--key-design-decisions)
12. [Agno 框架概念 / Agno Framework Concepts](#12-agno-框架概念--agno-framework-concepts)

---

## 1. 项目概述 / Project Overview

### 中文

本项目是 Agno Take-Home Exercise Option D 的实现，构建了一个生产级别的多智能体 Revenue Operations（RevOps）流水线系统。

**系统功能：**
- 接收原始 CRM JSON 数据（销售线索/商机）
- 通过 4 个专用 AI Agent 依次处理
- 输出优先级排序的行动清单，供销售运营团队直接执行

**系统价值：** 销售运营团队每天面对大量线索，需要快速判断哪些商机即将流失、哪些需要立即跟进。本系统用 AI 自动完成这一分析，将人工数小时的工作压缩到 90 秒内完成。

### English

This project implements Option D of the Agno Take-Home Exercise — a production-quality multi-agent Revenue Operations pipeline.

**What it does:**
- Ingests raw CRM JSON records (sales leads / pipeline opportunities)
- Runs them through 4 specialized AI agents in sequence
- Produces a prioritized action list that a sales ops team can act on immediately

**Why it matters:** Sales ops teams face dozens of deals daily and need to quickly identify which are at risk, which need immediate follow-up, and which are healthy. This system automates that analysis end-to-end, compressing hours of manual triage into ~90 seconds.

**Core design principles:**
- Deterministic scoring (rule-based Python) — the LLM never does math
- Typed state contracts (Pydantic v2) — every agent handoff is validated
- Graceful degradation — LLM failures fall back to defaults, never crash
- Observability-first — every agent logs latency and token usage
- Multi-provider — supports Anthropic Claude and OpenAI via model factory

---

## 2. 系统架构 / System Architecture

### 中文

系统采用严格的顺序流水线模式（`intake → classification → action → review`），每个 Agent 的输出作为下一个 Agent 的输入，全程无共享可变状态。

### English

The pipeline is strictly sequential. Each agent receives the typed output of the previous agent. There is no shared mutable state between agents.

```
CRM JSON Input  (raw list of dicts)
       │
       ▼
┌─────────────────────┐
│   [1] Intake Agent  │  Pure Python — validates & normalises records
│   (intake_agent.py) │  Input:  raw JSON / list[dict]
└─────────────────────┘  Output: LeadBatch
       │
       ▼
┌──────────────────────────────┐
│  [2] Classification Agent    │  Hybrid — rules compute score, LLM adds rationale
│  (classification_agent.py)   │  Input:  LeadBatch
└──────────────────────────────┘  Output: ScoredBatch  + token counts
       │
       ▼
┌─────────────────────┐
│  [3] Action Agent   │  LLM — recommends 2-4 follow-up actions per lead
│  (action_agent.py)  │  Input:  ScoredBatch
└─────────────────────┘  Output: ActionBatch  + token counts
       │
       ▼
┌──────────────────────────────┐
│  [4] Review / Manager Agent  │  LLM — quality check, executive summary, final report
│  (review_agent.py)           │  Input:  ActionBatch + ScoredBatch
└──────────────────────────────┘  Output: OpsReport  + token counts
       │
       ▼
output/report_<ts>.md   (markdown report)
output/report_<ts>.json (machine-readable)
logs/run_<ts>.json      (observability log)
```

### Agent 职责对比 / Agent Responsibilities

| Agent | 类型 / Type | 核心职责 / Core Responsibility |
|---|---|---|
| Intake | Pure Python | 验证字段、标准化阶段名、填充默认值 |
| Classification | Hybrid (Rules + LLM) | 计算得分+风险标志（规则），添加评分理由（LLM） |
| Action | LLM | 为每条线索生成 2-4 个具体跟进行动 |
| Review | LLM + Self-correction | 质量检查、排序、撰写执行摘要和最终报告 |

---

## 3. 文件结构 / File Structure

```
Ango/
├── app/
│   ├── models/
│   │   └── crm_models.py          # 所有 Pydantic 状态模型 / All typed state models
│   ├── tools/
│   │   ├── scoring_tools.py       # 纯 Python 评分规则 / Pure Python scoring rules
│   │   └── report_tools.py        # 报告生成与持久化 / Report generation & persistence
│   ├── agents/
│   │   ├── _model_factory.py      # LLM 提供商选择 / LLM provider selection
│   │   ├── intake_agent.py        # run_intake() → LeadBatch
│   │   ├── classification_agent.py# run_classification() → (ScoredBatch, tokens)
│   │   ├── action_agent.py        # run_action() → (ActionBatch, tokens)
│   │   └── review_agent.py        # run_review() → (OpsReport, tokens)
│   └── workflows/
│       └── revops_workflow.py     # Agno Workflow 编排 + 可观测性
├── data/
│   └── sample_leads.json          # 10 条模拟 CRM 数据
├── demo/
│   ├── run_demo.py                # CLI 入口（Rich 终端表格）
│   └── agent_os.py                # Agno Agent OS Web UI 入口
├── tests/
│   ├── test_models.py             # 18 个单元测试
│   └── test_workflow.py           # 端到端集成测试
├── .env.example                   # API Key 配置模板
├── requirements.txt
└── requirements-dev.txt
```

---

## 4. 数据模型 / Data Models

### 中文

所有 Agent 之间的数据传递均使用 Pydantic v2 模型，避免了"字符串传一切"的反模式。模型采用嵌套结构：`ScoredLead` 包含 `Lead`，`ActionItem` 包含 `ScoredLead`，依此类推。

### English

Every inter-agent handoff is a Pydantic v2 validated model. This eliminates stringly-typed data and makes each agent's input/output contract explicit and self-documenting.

### 核心模型字段 / Core Model Fields

#### `Lead` — 标准化后的 CRM 记录

```python
class Lead(BaseModel):
    id: str
    name: str
    company: str
    stage: Stage          # enum: Prospecting/Qualification/Proposal/Negotiation/Closed Won/Closed Lost
    deal_value: float     # USD
    days_since_last_activity: int
    close_date_days_out: int   # negative = overdue
    num_touches: int
    owner: str
    notes: str
```

#### `ScoredLead` — 分类后的线索

```python
class ScoredLead(BaseModel):
    lead: Lead
    score: int            # 0-100, 越高优先级越高
    risk_level: Literal["critical", "high", "medium", "low"]
    risk_flags: List[str] # e.g. ["idle_30_days", "close_date_overdue"]
    score_rationale: str  # LLM 生成的 1-2 句解释
```

#### `ActionItem` — 附带行动建议的线索

```python
class Action(BaseModel):
    action_type: Literal["call", "email", "meeting", "escalate", "discount", "nurture", "close"]
    priority: Literal["immediate", "this_week", "this_month"]
    description: str      # 具体的行动描述
    owner: str

class ActionItem(BaseModel):
    scored_lead: ScoredLead
    actions: List[Action]
    summary: str          # 整体推荐策略的一句话总结
```

#### `OpsReport` — 最终报告

```python
class OpsReport(BaseModel):
    run_id: str
    generated_at: str
    pipeline_stats: PipelineStats     # 汇总统计
    ranked_actions: List[ActionItem]  # 按得分降序排列
    executive_summary: str            # 3-5 句执行摘要
    review_notes: str                 # 审阅备注
```

#### `AgentTrace` — 可观测性数据

```python
class AgentTrace(BaseModel):
    agent: str
    status: Literal["ok", "error"]
    latency_ms: float
    records_in: int
    records_out: int
    input_tokens: int     # 实际 LLM token 用量
    output_tokens: int
    total_tokens: int
    error_message: Optional[str]
```

---

## 5. 工具层 / Tools Layer

### 中文

工具层包含纯 Python 的确定性逻辑。这部分代码不调用 LLM，速度快、可单元测试、结果可复现。

### English

The tools layer contains pure Python deterministic logic. No LLM is involved here — fast, unit-testable, and fully reproducible.

### `compute_score(lead: Lead) -> int`

基于 4 个维度的加权评分公式，结果为 0-100 整数：

| 维度 / Dimension | 权重 / Weight | 计算方式 / Calculation |
|---|---|---|
| 交易金额 Deal Value | 30% | 对数归一化，$200k+ 满分。Log scale prevents mega-deals from dominating. |
| 活跃度 Recency | 30% | 线性衰减。0天=100分，60天+=0分。Linear decay, 0 days → 100pts. |
| 阶段进展 Stage Progress | 20% | Negotiation=100, Proposal=75, Qualification=50, Prospecting=25, Closed=0 |
| 接触频次 Engagement | 20% | num_touches 上限 20，每次接触 5 分。Capped at 20 touches × 5pts. |

### `compute_risk_flags(lead: Lead) -> List[str]`

规则引擎，返回命中的风险标志列表：

| 标志 / Flag | 触发条件 / Trigger |
|---|---|
| `idle_30_days` | days_since_last_activity >= 30 |
| `idle_21_days` | days_since_last_activity >= 21 |
| `close_date_overdue` | close_date_days_out < 0 |
| `close_date_imminent` | 0 <= close_date_days_out <= 7 |
| `low_touches` | num_touches < 3 |
| `high_value_early_stage` | deal_value >= 50000 且 stage 为 Prospecting/Qualification |
| `no_recent_activity` | days_since_last_activity >= 14 |

### `compute_risk_level(score, flags) -> str`

```
critical : score < 30  OR  (idle_30_days AND close_date_overdue)
high     : score < 50  OR  idle_30_days  OR  close_date_overdue
medium   : score < 70  OR  idle_21_days  OR  close_date_imminent
low      : 其他 / otherwise
```

---

## 6. Agent 实现详解 / Agent Implementations

### 6.1 Intake Agent

**中文：** 纯 Python，无 LLM。验证并标准化原始输入，是整个流水线的守门人。

**English:** Pure Python — no LLM. Validates and normalises raw input. Acts as the pipeline's gatekeeper.

**关键逻辑：**
- 接受 JSON 字符串、`list[dict]` 或任意 JSON 可序列化输入
- 必填字段：`id, name, company, stage, deal_value, days_since_last_activity`
- 可选字段（有默认值）：`close_date_days_out=0, num_touches=0, owner="Unknown", notes=""`
- 阶段标准化：大小写不敏感匹配到 `Stage` 枚举
- **失败策略：** 无效记录 >50% → 抛出 `IntakeError`；≤50% → 记录警告并跳过

```python
def run_intake(raw_input: Union[str, list]) -> LeadBatch:
    # 解析 → 逐条验证 → 统计失败率 → 返回 LeadBatch 或 raise IntakeError
```

---

### 6.2 Classification Agent

**中文：** 混合 Agent，分两阶段执行。评分计算由规则代码完成，LLM 只负责撰写自然语言解释。这样确保了评分的可复现性，同时保留了 LLM 的语言能力。

**English:** Hybrid agent with two phases. Score computation is handled by deterministic rules; the LLM's only job is writing natural language rationale. This keeps scores reproducible while leveraging the LLM for what it does best.

**阶段一：确定性评分（永不失败）**
```python
def _score_all_deterministically(leads: List[Lead]) -> List[ScoredLead]:
    for lead in leads:
        score = compute_score(lead)
        flags = compute_risk_flags(lead)
        risk_level = compute_risk_level(score, flags)
        # score_rationale="" 占位，等待 LLM 填充
```

**阶段二：LLM 添加评分理由（尽力而为，最多重试 3 次）**
```python
for attempt in range(1, MAX_RETRIES + 1):
    run_output = agent.run(input_text)
    # 提取 token 用量
    m = run_output.metrics
    if m:
        total_in += m.input_tokens or 0
        ...
    # 验证输出结构
    enriched: ScoredBatch = run_output.content
    # 用确定性值覆盖 LLM 可能篡改的数字字段（保险机制）
    for orig, enr in zip(scored, enriched.leads):
        enr.score = orig.score
        enr.risk_level = orig.risk_level
        enr.risk_flags = orig.risk_flags
```

**返回签名：**
```python
def run_classification(batch: LeadBatch) -> Tuple[ScoredBatch, int, int, int]:
    # 返回 (ScoredBatch, input_tokens, output_tokens, total_tokens)
```

---

### 6.3 Action Agent

**中文：** 纯 LLM Agent。根据每条线索的风险等级和销售阶段，生成 2-4 个具体、可执行的跟进行动。

**English:** Pure LLM agent. Generates 2-4 specific, actionable follow-up steps per lead, tailored to risk level and sales stage.

**行动类型规则：**
- `critical / high` → 立即行动（immediate call, escalation, discount offer）
- `medium` → 本周行动（email, meeting scheduling）
- `low` → 标准培育或收单动作（nurture, close）

**结构化输出：** 使用 `output_schema=ActionBatch`，Agno 强制 LLM 返回符合 JSON schema 的结果。

```python
def run_action(batch: ScoredBatch) -> Tuple[ActionBatch, int, int, int]:
```

---

### 6.4 Review / Manager Agent

**中文：** 担任 Revenue Operations 经理角色。负责质量检查、排序和撰写最终报告。包含一个自我修正循环（Stretch Goal）。

**English:** Acts as a Revenue Operations Manager. Responsible for quality checking, ranking, and writing the final report. Includes a self-correction loop (stretch goal).

**自我修正循环：**
```python
passed, reason = _quality_check(action_batch)
# 检查：每个 critical/high 线索至少有一个 "immediate" 优先级的行动
if not passed:
    # 重新调用 Action Agent 修订一次
    revised_batch, r_in, r_out, r_tok = run_action(scored_batch)
    total_in += r_in  # token 计入 review agent 的统计
    ...
```

**确定性覆盖（LLM 之后）：**
```python
# 以下字段始终由代码设置，LLM 无法覆盖
report.run_id = run_id                          # 由 workflow 生成
report.generated_at = generated_at             # UTC 时间戳
report.pipeline_stats = stats                  # 纯 Python 计算
report.ranked_actions = items_sorted           # Python 按 score 降序排列
```

---

## 7. 工作流与可观测性 / Workflow & Observability

### 中文

工作流使用 `agno.Workflow` 类封装，ID 为 `revenue-operations-pipeline`。Agno 框架通过这个 ID 进行 WebSocket 路由，Agent OS 用它来定位正确的工作流实例。

### English

The pipeline is wrapped in `agno.Workflow` with `id="revenue-operations-pipeline"`. Agno uses this ID for WebSocket routing in Agent OS.

### Workflow 结构

```python
def create_workflow() -> Workflow:
    return Workflow(
        id="revenue-operations-pipeline",
        name="Revenue Operations Pipeline",
        steps=_run_pipeline,   # Agno 通过 inspect.signature 检查参数名
    )
```

**重要：** steps 函数的参数名必须精确为 `execution_input`（Agno 内部通过反射注入）：

```python
def _run_pipeline(workflow: Workflow, execution_input: WorkflowExecutionInput) -> StepOutput:
    raw_input = execution_input.input
    ...
```

### Token 追踪 / Token Tracking

每个 LLM Agent 将 token 用量作为返回值的一部分，工作流负责解包并存入 `AgentTrace`：

```python
# Classification
scored_batch, c_in, c_out, c_tok = run_classification(lead_batch)
traces.append(AgentTrace(
    agent="classification", status="ok",
    latency_ms=...,
    input_tokens=c_in, output_tokens=c_out, total_tokens=c_tok,
))

# Action
action_batch, a_in, a_out, a_tok = run_action(scored_batch)

# Review
report, r_in, r_out, r_tok = run_review(action_batch, scored_batch)
```

token 数据来源：`run_output.metrics`（Agno `RunMetrics` 对象），在 Classification 中跨重试次数累加。

### 可观测性日志格式 / Observability Log Format

每次运行在 `logs/` 目录保存一个结构化 JSON：

```json
{
  "run_id": "3879796a",
  "started_at": "2026-04-02T03:33:02+00:00",
  "total_latency_ms": 87432,
  "status": "ok",
  "agents": [
    {
      "agent": "intake",
      "status": "ok",
      "latency_ms": 45,
      "records_in": 10,
      "records_out": 10,
      "input_tokens": 0,
      "output_tokens": 0,
      "total_tokens": 0
    },
    {
      "agent": "classification",
      "status": "ok",
      "latency_ms": 24800,
      "records_in": 10,
      "records_out": 10,
      "input_tokens": 1840,
      "output_tokens": 620,
      "total_tokens": 2460
    },
    {
      "agent": "action",
      "status": "ok",
      "latency_ms": 38100,
      "records_in": 10,
      "records_out": 10,
      "input_tokens": 2240,
      "output_tokens": 980,
      "total_tokens": 3220
    },
    {
      "agent": "review",
      "status": "ok",
      "latency_ms": 24100,
      "records_in": 10,
      "records_out": 1,
      "input_tokens": 3100,
      "output_tokens": 420,
      "total_tokens": 3520
    }
  ],
  "output_path": "output/report_20260402_033302.md"
}
```

---

## 8. 错误处理 / Failure Handling

### 场景一：输入数据无效 / Scenario 1: Invalid Input

**中文：** Intake Agent 逐条验证每条记录。根据失败比例决定是警告继续还是终止整个流水线。

**English:** Intake Agent validates each record individually. The failure threshold determines whether to warn-and-continue or abort the pipeline.

```
无效记录 > 50%  →  raise IntakeError(field_errors={"record_id": "missing field: stage"})
                   Workflow 捕获 → 保存错误日志 → 返回 StepOutput(success=False)
                   下游 Agent 不执行

无效记录 ≤ 50%  →  记录 WARNING 日志，跳过无效记录，继续处理有效记录
```

**测试覆盖：** `test_pipeline_fails_on_bad_input()` 验证垃圾输入时 `StepOutput.success == False`。

---

### 场景二：LLM 返回格式错误 / Scenario 2: Malformed LLM Output

**中文：** Classification Agent 最多重试 3 次，每次将错误信息附加到提示词中，引导 LLM 自我修正。无论如何，评分结果本身不受影响（因为是纯 Python 计算的）。

**English:** Classification Agent retries up to 3 times, appending the error to the prompt each attempt. The numeric scores are never at risk because they were computed before the LLM call.

```python
for attempt in range(1, MAX_RETRIES + 1):
    try:
        run_output = agent.run(input_text)
        enriched = run_output.content
        if not isinstance(enriched, ScoredBatch):
            raise ValueError(...)
        if len(enriched.leads) != len(scored):
            raise ValueError(...)
        return enriched, total_in, total_out, total_tok
    except Exception as exc:
        # 第 1/2 次失败：把错误信息加入下一次提示词
        input_text = f"The previous response had errors: {exc}. Please fix...\n\n{input_text}"

# 所有重试失败后：返回无 rationale 的 ScoredBatch（评分始终有效）
return ScoredBatch(leads=scored), total_in, total_out, total_tok
```

---

### 场景三：自我修正循环 / Scenario 3: Self-Correction Loop (Stretch Goal)

**中文：** Review Agent 在生成最终报告前，会对 Action Agent 的输出做质量检查。如果不通过，会让 Action Agent 重新生成一次。

**English:** Before finalizing the report, the Review Agent runs a quality check on the action plan. If it fails, it re-runs the Action Agent once for revision.

```python
def _quality_check(batch: ActionBatch) -> tuple[bool, str]:
    for item in batch.items:
        if not item.actions:
            return False, f"Lead '{item.scored_lead.lead.name}' has no actions"
        if item.scored_lead.risk_level in ("critical", "high"):
            if not any(a.priority == "immediate" for a in item.actions):
                return False, f"Critical/high lead has no immediate action"
    return True, "ok"
```

---

## 9. 测试数据 / Sample Data

`data/sample_leads.json` 包含 10 条模拟线索，覆盖所有风险等级：

| ID | 公司 / Company | 阶段 / Stage | 金额 / Value | 沉默天数 / Idle | 预期风险 / Expected Risk |
|---|---|---|---|---|---|
| lead_001 | Alpha Corp | Negotiation | $90k | 5d | LOW |
| lead_002 | BetaTech | Proposal | $140k | 40d (overdue) | **CRITICAL** |
| lead_003 | GammaSoft | Qualification | $8k | 3d | MEDIUM |
| lead_004 | Delta Systems | Negotiation | $210k | 2d | LOW |
| lead_005 | EpsilonGroup | Proposal | $65k | 22d | **HIGH** |
| lead_006 | Zeta Analytics | Prospecting | $180k | 45d | **CRITICAL** |
| lead_007 | Eta Robotics | Qualification | $35k | 10d | MEDIUM |
| lead_008 | Theta Health | Closed Won | $120k | 1d | LOW (已关单) |
| lead_009 | Iota Finance | Proposal | $95k | 18d (3d to close) | **HIGH** |
| lead_010 | Kappa Retail | Negotiation | $55k | 7d | MEDIUM |

---

## 10. 运行方式 / How to Run

### 环境准备 / Setup

```bash
git clone https://github.com/xzhu411/multiAgent-Agno.git
cd multiAgent-Agno

python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# 编辑 .env，填入你的 API Key：
# ANTHROPIC_API_KEY=sk-ant-...   （推荐）
# OPENAI_API_KEY=sk-proj-...     （备选）
```

### CLI Demo（Rich 终端输出）

```bash
python demo/run_demo.py                        # 使用默认数据 data/sample_leads.json
python demo/run_demo.py --input my_leads.json  # 自定义 CRM 数据
python demo/run_demo.py --verbose              # 开启 DEBUG 日志
```

终端输出示例：
```
╭─────────────── Pipeline Health ───────────────╮
│ Leads: 10  |  Critical: 2  High: 2  Med: 3  Low: 3  │
│ Pipeline: $1,001,000  |  At-Risk: $385,000           │
╰────────────────────────────────────────────────╯

╭──────────────── Prioritized Action List ────────────────╮
│ # │ Risk     │ Lead / Company      │ Score │ Top Action  │
│ 1 │ ● low    │ Delta Systems       │  92   │ [immediate] close: ... │
│ 2 │ ● low    │ Alpha Corp          │  85   │ [immediate] close: ... │
│ 3 │ ● critical│ BetaTech           │  28   │ [immediate] call: ...  │
│ ...                                                      │
╰──────────────────────────────────────────────────────────╯
```

### Agent OS Web UI

```bash
pip install "uvicorn[standard]" websockets
python demo/agent_os.py
# 浏览器打开 https://os.agno.com/
# 连接到 localhost:7777
# 点击 "Revenue Operations Pipeline" → 提交线索 JSON
```

### 运行测试 / Run Tests

```bash
pip install -r requirements-dev.txt

# 单元测试（无需 API Key）：
pytest tests/test_models.py -v   # 18 个测试，全部通过

# 集成测试（需要 API Key）：
pytest tests/test_workflow.py -v
```

### 验证输出 / Verify Output

```bash
# 检查报告文件
ls output/report_*.md output/report_*.json

# 检查可观测性日志
cat logs/run_*.json | python3 -m json.tool
```

---

## 11. 关键设计决策 / Key Design Decisions

### 决策一：确定性评分 + LLM 语言解释 / Deterministic Scoring + LLM Rationale

**中文：** LLM 的随机性和不可预测性不适合用于数值计算。将评分拆分为两层：规则计算数字，LLM 解释原因。这样既保证了可复现性（单元测试可以精确验证分数），又利用了 LLM 最擅长的自然语言表达。

**English:** LLM non-determinism is unsuitable for numeric computation. Splitting into two layers keeps scores reproducible and unit-testable, while leveraging the LLM for what it does best: natural language.

---

### 决策二：Tuple 返回 Token 计数 / Tuple Return for Token Counts

**中文：** 每个 Agent 将 token 用量作为返回元组的一部分，而不是全局变量或侧信道。这使得 Agent 保持无状态，token 统计在工作流层显式可见。

**English:** Rather than a global accumulator or side-channel, each agent returns token counts as part of its return tuple. This keeps agents stateless and makes token accounting explicit at the workflow level.

```python
# 而非 / Instead of:
global_token_counter += tokens   # 全局状态，难以测试

# 采用 / We use:
return result, input_tokens, output_tokens, total_tokens
```

---

### 决策三：LLM 之后强制覆盖数字字段 / Force-Overwrite Numeric Fields After LLM

**中文：** LLM 即使被明确指示不要修改数字字段，也可能发生幻觉。在 LLM 返回后，立即用确定性计算值覆盖 `score/risk_level/risk_flags`，作为双重保险。

**English:** Even when explicitly instructed not to change numeric values, LLMs can hallucinate. After the LLM enriches rationales, the workflow immediately overwrites `score/risk_level/risk_flags` with deterministic values as a safety net.

---

### 决策四：`execution_input` 参数名 / `execution_input` Parameter Name

**中文：** Agno 框架通过 `inspect.signature()` 反射检查 steps 函数的参数名。参数名必须精确为 `execution_input`，否则 Agno 无法正确注入 `WorkflowExecutionInput` 对象，导致静默失败。

**English:** Agno inspects the steps callable via `inspect.signature()`. The parameter must be named exactly `execution_input` for Agno to inject the `WorkflowExecutionInput` object correctly. Any other name causes a silent failure.

---

### 决策五：显式 Workflow ID / Explicit Workflow ID

**中文：** Agent OS 通过 WebSocket 路由消息时使用 `workflow.id`。如果不显式设置，`id` 为 `None`，WebSocket 连接会返回 404 错误。

**English:** Agent OS routes WebSocket messages using `workflow.id`. Without an explicit ID, it defaults to `None` and WebSocket connections fail with 404.

```python
Workflow(id="revenue-operations-pipeline", ...)  # 必须显式设置 / Must be explicit
```

---

### 决策六：`load_dotenv(override=True)` / `load_dotenv(override=True)`

**中文：** macOS 系统环境变量中可能存在空字符串的 API Key（之前 `export ANTHROPIC_API_KEY=""` 留下的）。`override=True` 确保 `.env` 文件中的值始终覆盖系统环境变量，避免 API Key 为空导致的静默失败。

**English:** macOS may have empty string API key values in the system environment from a previous failed `export`. `override=True` ensures `.env` values always win, preventing silent authentication failures.

---

### 决策七：StepOutput 返回 Markdown 字符串 / StepOutput Returns Markdown String

**中文：** Agent OS 在 Chat UI 中直接渲染 `StepOutput.content`。返回 Markdown 字符串（而非 dict 或 Pydantic 对象）可以在浏览器中呈现格式化的报告，而非原始 JSON。

**English:** Agent OS renders `StepOutput.content` directly in its chat UI. Returning a markdown string (not a dict) gives a formatted, human-readable report in the browser instead of raw JSON.

---

## 12. Agno 框架概念 / Agno Framework Concepts

### 使用的核心 API / Core APIs Used

| API | 用途 / Usage |
|---|---|
| `agno.agent.Agent` | LLM Agent 核心类。配置参数：`name, model, output_schema, instructions, markdown` |
| `agno.workflow.Workflow` | 工作流编排类。接收 `steps` 函数，管理 session 和 Agent OS 注册 |
| `agno.workflow.types.StepOutput` | Steps 函数的返回类型。`content` 字段显示在 Agent OS UI 中 |
| `agno.workflow.types.WorkflowExecutionInput` | 注入到 steps 函数的输入对象。通过 `.input` 属性获取用户传入的数据 |
| `agno.run.agent.RunMetrics` | LLM 调用后的 metrics 对象。包含 `input_tokens, output_tokens, total_tokens` |
| `agno.models.anthropic.Claude` | Anthropic Claude 模型封装。`Claude(id="claude-haiku-4-5-20251001")` |
| `agno.models.openai.OpenAIChat` | OpenAI 模型封装。`OpenAIChat(id="gpt-4o-mini")` |
| `AgentOS` | Web UI 服务器。在 `localhost:7777` 启动，连接 `https://os.agno.com/` 作为前端 |

### `output_schema` vs `output_model` 的区别 / Difference Between `output_schema` and `output_model`

**中文：** 这是一个容易混淆的参数。在 Agno v2.5.x 中：
- `output_schema=ScoredBatch` → 告诉 Agent **输出**应该符合该 Pydantic schema（结构化输出）
- `model=Claude(...)` → 告诉 Agent 使用哪个 **LLM 模型**

`output_model` 是旧版参数名，在新版中已经是 LLM 模型的参数名，使用错误会导致结构化输出失效。

**English:** A common source of confusion in Agno v2.5.x:
- `output_schema=ScoredBatch` → tells the Agent the **output** should conform to this Pydantic schema
- `model=Claude(...)` → tells the Agent which **LLM** to use

Using `output_model` instead of `output_schema` silently breaks structured output.

---

## 项目总结 / Summary

本项目完整实现了 Agno Take-Home Exercise Option D 的所有要求：

| 要求 / Requirement | 状态 / Status |
|---|---|
| 4 个专用 Agent 的流水线 / 4-agent pipeline | ✅ |
| Agno Workflow 编排 / Agno Workflow orchestration | ✅ |
| 结构化 Pydantic 模型 / Structured Pydantic models | ✅ |
| 确定性工具层 / Deterministic tools layer | ✅ |
| 错误处理场景一：无效输入 / Failure: invalid input | ✅ |
| 错误处理场景二：LLM 格式错误 / Failure: malformed LLM output | ✅ |
| 可观测性日志（含 Token 追踪）/ Observability with token tracking | ✅ |
| CLI Demo（Rich 终端）/ CLI demo with Rich | ✅ |
| Agent OS Web UI | ✅ |
| 单元测试 18 个 / 18 unit tests | ✅ |
| Stretch Goal：自我修正循环 / Self-correction loop | ✅ |
| 多 LLM 提供商支持 / Multi-provider LLM support | ✅ |
