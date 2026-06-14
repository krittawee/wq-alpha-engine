# Phase 3: Smart Iteration - Research

**Researched:** 2026-06-09
**Domain:** Python: Editor (classify/diagnose/mutate), local self-corr pre-filter, Frequent Subtree Avoidance, autonomous loop, `/hunt` command
**Confidence:** HIGH (codebase verified) / MEDIUM (BRAIN PnL schema)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**D-01 Hybrid Editor.** Deterministic code classifies PASS/NEAR/FAIL + identifies failing check. LLM writes diagnosis and proposes mutations.

**D-02 1-3 mutations per NEAR and per FAIL alpha.** Both statuses produce mutations. Each mutation records `parent_alpha_id`.

**D-03 Mutations are validated, invalids dropped.** Every LLM-proposed mutation passes `validate.py` AND `db.expr_exists` dedup before persistence. Invalid or duplicate mutations are silently dropped.

**D-04 Editor auto-queues mutations into grading.** Loop MUST respect ≤3 concurrent sims and single-shot auth — never re-auth in-loop. Reuse `grade_many`'s existing concurrency cap.

**D-05 NEAR margin = within 20% of limit.** A failing numeric check counts toward NEAR only if its `value` is within 20% of its `limit`.

**D-06 Any structural/hard fail → FAIL.** Non-numeric / boolean checks (MATCHES_COMPETITION; optionally CONCENTRATED_WEIGHT by convention) that fail force FAIL regardless.

**D-07 NEAR fail-count cap = at most 2.** NEAR requires ≤2 failing numeric checks, all within 20% margin, and no hard/structural fail.

**D-08 Two-stage filter.** (a) Pre-sim parent-PnL proxy gate; (b) post-sim/pre-BRAIN-check precise filter.

**D-09 Reference set = submitted alphas + all PASS alphas in DB.**

**D-10 Method = Pearson on daily PnL**, calibrated against BRAIN's stored `self_corr` values.

**D-11 Cutoff derived from BRAIN's SELF_CORRELATION limit** read from `checks` table — never hardcode 0.7.

**D-12 PnL fetch = backfill submitted once + lazy-cache passers.**

**D-13 Graceful degradation.** If PnL unavailable, skip local filter for that item and fall back to BRAIN's POST /check.

**D-14 AST subtree mining.** Parse PASS alpha FastExpr into expression tree, abstract fields/numbers, enumerate subtree shapes.

**D-15 Filter + LLM steer (both).** Post-generation structural filter drops/deprioritizes Ideator candidates with frequent motifs. Mined avoid-list injected into Researcher + Editor prompts.

**D-16 Stop on depth OR budget OR dry.** Loop does NOT early-stop on first success — spends budget hunting stronger alpha.

**D-17 Budget = configurable ceiling; default = 2 generations, ~30 sims/run.** User can raise it.

**D-18 TWO commands.** `/hunt` (chained, autonomous) and `/iterate` (standalone Editor, manual).

**D-19 Each filter lands where its trigger already is.** Self-corr integrates into `grade.py`. FSA into generation path + prompts.

**D-20 Hunt return value = best NEW submittable alpha** (or best NEAR candidates if none found).

### Claude's Discretion

- FSA "frequent" threshold (e.g. ≥X% of passers) and cold-start min-sample guard.
- Exact PnL caching mechanics (storage format under `pnl_path`, alignment, date-window).
- Internal module structure (`editor.py`, `selfcorr.py`, `fsa.py`), LLM prompt wording.
- FastExpr parser implementation details.
- Ranking metric for D-20 best-alpha selection (Sharpe/fitness — Claude's choice).

### Deferred Ideas (OUT OF SCOPE)

- Settings Optimizer / parameter tuning, decay monitor, Obsidian prose/Archetypes layer → Phase 4 (OPT-01..03).
- Richer FSA (cross-archetype motif analysis, weighted novelty scoring).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ITR-01 | Editor classifies each alpha PASS/NEAR/FAIL from BRAIN's checks and diagnoses which check failed and why | D-05..D-07 classification logic verified against live DB; check taxonomy confirmed (numeric vs boolean). See §Architecture Patterns §Pitfalls. |
| ITR-02 | Editor proposes expression mutations for next loop with `parent_alpha_id` lineage | Mutation flow uses existing `validate.py` + `db.expr_exists` gates; `parent_alpha_id` column already in schema. See §Standard Stack. |
| ITR-03 | System computes local PnL-based self-correlation pre-filter against user's alphas without triggering BRAIN API | PnL endpoint confirmed (`GET /alphas/{id}/recordsets/pnl` via `client.get_pnl()`). Response shape: `{"pnls": [...], "dates": [...]}`. Pearson on daily diffs, stdlib-only, no numpy needed. See §PnL Endpoint Research. |
| ITR-04 | FSA mines common motifs from passing alphas and steers Ideator toward structural novelty | Python `ast` module parses all generated (non-ternary) FastExpr. Abstract subtree enumeration confirmed working. See §FSA Research. |
</phase_requirements>

---

## Summary

Phase 3 adds three capabilities to the existing flat-Python pipeline: an **Editor** (classify → diagnose → mutate), a **local self-correlation pre-filter** (avoid duplicate BRAIN API calls), and **Frequent Subtree Avoidance** (structural diversity). These connect into a new `/hunt` autonomous command and a `/iterate` manual command.

All research is grounded in actual code inspection of the Phase 1/2 modules and live DB queries. The most important unknowns (PnL endpoint schema, self-correlation method) are resolved below with appropriate confidence levels.

**Primary recommendation:** Build three new flat Python modules — `editor.py`, `selfcorr.py`, `fsa.py` — following the exact hybrid pattern of `researcher.py`. Wire them into `grade.py` (selfcorr filter), `find_alphas.py`/generation path (FSA), and two new Claude Code commands (`/hunt`, `/iterate`). Use Python stdlib throughout — no new pip dependencies required.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| NEAR/FAIL/PASS classification | `grade.py` (post-Phase-B) + `editor.py` | — | Classification is a read of already-stored `checks` rows; deterministic code owns it |
| LLM diagnosis + mutation proposal | `editor.py` (LLM subagent prompt) | — | Mirrors `researcher.py` pattern |
| Mutation validation + dedup | `validate.py` + `db.expr_exists` | `editor.py` calls these | Reuse existing Phase 1 gates, never bypass |
| PnL fetch + caching | `selfcorr.py` | `grade.py` hooks it | Isolated module; grade.py calls it pre-POST /check |
| Local Pearson pre-filter | `selfcorr.py` | — | Pure compute; needs access to cached PnL vectors |
| FSA subtree mining | `fsa.py` | — | Pure compute on PASS alphas in DB |
| FSA filter (generation path) | `fsa.py` called from `find_alphas.py` / `/hunt` | Researcher/Editor prompts inject avoid-list | Filter is pre-queueing; prompt injection is at LLM call time |
| Autonomous loop control | `/hunt` command (Claude Code) | `grade.py` (grade_many) | Loop logic in the command; sim execution reuses grade_many |
| Status vocabulary extension (NEAR) | `grade.py` | `editor.py` reclassifies post-grading | Grade sets initial pass/fail; editor reclassifies to NEAR |

---

## Standard Stack

### Core (all already in venv — no new installs)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `requests` | 2.34.2 | BRAIN API calls (PnL fetch) | Already the only HTTP client in project |
| `sqlite3` | stdlib | DB reads for classification, FSA mining | Already used everywhere |
| `ast` | stdlib | FastExpr expression parsing for FSA | Works on all generated (non-ternary) expressions — verified |
| `math` | stdlib | Pearson correlation computation | No numpy needed; pure float arithmetic |
| `json` | stdlib | PnL vector caching to disk | Already used; sufficient for list-of-float storage |
| `concurrent.futures` | stdlib | Reused via `grade_many` | Never write new sim orchestration |
| `pytest` | 9.0.3 | Phase 3 criterion tests | Already in venv |

[VERIFIED: codebase] — all packages confirmed in `/Users/winter.__.kor/quant/venv/bin/pip list`

### Supporting (new files, zero new installs)

| Module | Purpose | Where to Create |
|--------|---------|-----------------|
| `editor.py` | Hybrid: deterministic classify/diagnose + LLM mutation proposal | `/Users/winter.__.kor/quant/editor.py` |
| `selfcorr.py` | PnL fetch, caching, daily-returns conversion, Pearson compute, pre-filter gate | `/Users/winter.__.kor/quant/selfcorr.py` |
| `fsa.py` | AST subtree mining, frequency counting, avoid-list generation + post-generation filter | `/Users/winter.__.kor/quant/fsa.py` |
| `hunt.py` | Orchestrator for `/hunt` command — chains research→generate→grade→editor→loop | `/Users/winter.__.kor/quant/hunt.py` |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| stdlib `ast` for FSA | Custom recursive-descent parser | ast is proven on all generated expressions; ternary expressions never appear in the PASS alpha pool (verified in DB — only ACTIVE/user-submitted alphas use ternary). Stdlib first. |
| stdlib Pearson (pure Python) | numpy `corrcoef` | numpy not in venv; installing it adds ~20MB and a new dep for a 20-line function. Stdlib Pearson is correct and fast enough for ≤500 daily points × ≤50 reference alphas. |
| JSON file for PnL cache | SQLite BLOB column | JSON files keep `pnl_path` as a filesystem path (already in schema); no schema migration needed. |

**Installation:** No new packages required. All Phase 3 code runs in the existing venv.

---

## Package Legitimacy Audit

No new pip packages are required for Phase 3. All capabilities are implemented using the stdlib or packages already installed in the venv.

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

---

## BRAIN PnL Endpoint Research

### Endpoint Confirmed

`GET /alphas/{id}/recordsets/pnl` — already wrapped in the vendored SDK as `client.get_pnl(alpha_id)` (brain_client.py:176-187). [VERIFIED: codebase — `/Users/winter.__.kor/quant/venv/lib/python3.14/site-packages/brain_client.py:176`]

Implementation: `_poll_recordset(alpha_id, "pnl", poll_interval)` → polls `GET /alphas/{alpha_id}/recordsets/pnl` with `Retry-After` pattern until no `Retry-After` header, then returns `r.json()`.

### Response Schema [ASSUMED — confirmed by community implementations, not official docs]

```json
{
  "pnls": [0.0, 0.001234, 0.003456, ...],
  "dates": ["2022-01-03", "2022-01-04", "2022-01-05", ...]
}
```

- `pnls`: cumulative PnL series (float, one value per trading day)
- `dates`: ISO date strings aligned 1:1 with `pnls`
- Date range: matches `testPeriod` simulation setting (`P1Y6M` = ~18 months for newly simulated alphas)

**Source:** xiegengcai/world-quant-brain community implementation — DeepWiki analysis confirmed `pnls` and `dates` keys. [ASSUMED — not confirmed from official BRAIN API docs]

### Daily Returns Conversion [MEDIUM confidence — community-verified pattern]

The community converts cumulative PnL to daily returns as:
```
returns[i] = pnls[i] - pnls[i-1]   (forward-fill NaN before diff)
```

This matches the design doc's "convert to returns, corrwith().max()" description. [CITED: docs/plans/2026-06-07-alpha-system-design.md]

### SELF_CORRELATION Method [MEDIUM confidence — community-sourced, not official docs]

- **Method:** max Pearson correlation on daily PnL returns against all same-region user-submitted alphas
- **Window:** 2-year rolling window (filter to most recent 2 years before computing) [ASSUMED — community sources consistently cite 2 years; BRAIN's own check value agrees with this approach when calibrated]
- **Direction:** `max()` of pairwise correlations (not average), capturing worst-case duplicate

**Calibration approach (D-10):** The one resolved `SELF_CORRELATION` check in the DB shows `alpha_id=xAndqLYJ, self_corr=0.8939, limit=0.7, result=FAIL`. After downloading PnL for this alpha and its comparators, compute local Pearson and compare to 0.8939. If local ≈ BRAIN (within ±0.05), the method is validated. If off, adjust the window.

### Live DB Evidence for SELF_CORRELATION Limit

```
DB query confirms: checks.name='SELF_CORRELATION', limit_val=0.7 (consistent across all resolved records)
```
[VERIFIED: DB query on alpha_kb.db]

The `limit_val=0.7` is read from `checks.limit_val` at runtime (never hardcoded), consistent with CLAUDE.md constraint. [VERIFIED: grade.py:200-204 — `poll_correlation` reads values from `is.checks` array]

### Throttle / 401 Landmines

- PnL fetch uses the same `client._session` as sims — same auth token, same 401-propagation behavior
- `Retry-After` pattern is already handled by `brain_client._poll_recordset`
- No separate rate-limit for recordsets endpoint documented; treat it like a fast read (seconds, not minutes)
- **Do NOT call `get_pnl()` inside the ≤3-concurrent sim pool** — PnL fetches are I/O-bound sequentials; issue them one at a time in the backfill step or immediately after each sim completes before the next batch

---

## Check Classification Research

### Verified from Live DB (`alpha_kb.db` — 50 graded expressions)

[VERIFIED: DB queries on alpha_kb.db]

| Check Name | Type | Direction | Typical Limit | Has value/limit_val |
|------------|------|-----------|---------------|---------------------|
| `LOW_SHARPE` | NUMERIC | value ≥ limit to PASS | 1.25 (delay=1) | Always |
| `LOW_FITNESS` | NUMERIC | value ≥ limit to PASS | 1.0 | Always |
| `LOW_TURNOVER` | NUMERIC | value ≥ limit to PASS | 0.01 | Always |
| `HIGH_TURNOVER` | NUMERIC | value ≤ limit to PASS | 0.7 | Always |
| `LOW_SUB_UNIVERSE_SHARPE` | NUMERIC | value ≥ limit to PASS | Variable (−0.5 to 0.75 seen) | Always |
| `CONCENTRATED_WEIGHT` | NUMERIC-but-HARD | value ≤ limit to PASS | 0.1 | Sometimes |
| `SELF_CORRELATION` | NUMERIC | value ≤ limit to PASS | 0.7 | When resolved |
| `MATCHES_COMPETITION` | BOOLEAN/STRUCTURAL | PASS/FAIL only | — | Never |

**CONCENTRATED_WEIGHT:** Has numeric value/limit_val in DB, but CONTEXT.md D-06 classifies it as a "structural/hard fail" because fixing it requires expression-level changes (not just parameter tuning). Treat as hard fail per D-06. [VERIFIED: 03-CONTEXT.md D-06]

**MATCHES_COMPETITION:** No value or limit_val. Pure boolean. Always FAIL → hard fail per D-06. [VERIFIED: DB query]

### NEAR Classification Algorithm

For each IS survivor alpha with any `result='FAIL'` in `checks` table:

```python
def classify_alpha(alpha_id, conn):
    """Returns 'pass', 'near', or 'fail' based on checks table."""
    checks = conn.execute(
        "SELECT name, result, value, limit_val FROM checks WHERE alpha_id=?",
        (alpha_id,)
    ).fetchall()

    HARD_FAIL_CHECKS = {"MATCHES_COMPETITION", "CONCENTRATED_WEIGHT"}

    # Hard/structural fails are immediate FAIL (D-06)
    for name, result, val, lim in checks:
        if result == "FAIL" and name in HARD_FAIL_CHECKS:
            return "fail", [name]

    # Collect numeric fails and measure gap
    numeric_fails = []
    for name, result, val, lim in checks:
        if result == "FAIL" and val is not None and lim is not None:
            # gap = abs(val - lim) / max(abs(lim), EPSILON)
            # For LOW_ checks: value should be >= limit (fail when value < limit)
            # For HIGH_/CONCENTRATED: value should be <= limit (fail when value > limit)
            EPSILON = 0.01  # floor for near-zero limits (LOW_SUB_UNIVERSE_SHARPE edge case)
            gap = abs(val - lim) / max(abs(lim), EPSILON)
            numeric_fails.append((name, gap))

    if not numeric_fails:
        return "pass", []

    # NEAR: <= 2 numeric fails, all within 20% (D-05, D-07)
    all_within_margin = all(gap <= 0.20 for _, gap in numeric_fails)
    if len(numeric_fails) <= 2 and all_within_margin:
        return "near", [n for n, _ in numeric_fails]

    return "fail", [n for n, _ in numeric_fails]
```

**Edge case — LOW_SUB_UNIVERSE_SHARPE with limit near zero:** The `EPSILON=0.01` floor prevents division-by-zero and wild percentages when `limit_val` is 0.0 or very small. [VERIFIED: DB shows limit_val=0.0 case exists]

**Important: NEAR is only applied post-Phase-B** (after SELF_CORRELATION resolves). An IS survivor with SELF_CORRELATION FAIL could be NEAR if it's within 20% — but in practice, correlation failures are structural (the expression is too similar to an existing alpha). Treat SELF_CORRELATION FAIL as a FAIL category for mutation purposes: the mutation must diverge the expression, not just nudge parameters.

---

## Architecture Patterns

### System Architecture Diagram

```
/hunt command
     │
     ├─► researcher.build_thesis()          (existing)
     │        │ avoid-list from fsa.mine()
     ├─► ideator.generate_candidates()      (existing)
     │        │ fsa.filter_candidates() drops/deprioritizes frequent motifs
     ├─► grade.grade_many()                 (existing, extended)
     │        │ selfcorr.proxy_gate() BEFORE each sim (parent PnL check)
     │        │ selfcorr.precise_filter() AFTER sim, BEFORE POST /check
     │        │ grade sets status pass/fail (NEAR reclassified by editor)
     │
     ├─► editor.classify_and_diagnose()     (new)
     │        │ reads checks table → PASS/NEAR/FAIL per alpha
     │        │ LLM subagent writes diagnosis + proposes 1-3 mutations
     │        │ mutations validated via validate.py + db.expr_exists
     │
     └─► LOOP (D-16/D-17)
              │ mutations → grade_many → editor → repeat
              │ stop: depth cap | budget cap | no new NEAR produced
              └─► return best NEW submittable alpha (D-20)
```

### Recommended Project Structure (new files only)

```
quant/
├── editor.py          # Editor: classify/diagnose (deterministic) + LLM mutation proposal
├── selfcorr.py        # PnL fetch/cache + Pearson pre-filter (no numpy)
├── fsa.py             # AST subtree mining + frequency + filter + avoid-list
├── hunt.py            # /hunt orchestrator: autonomous loop + result reporting
└── test_phase3.py     # Phase 3 criterion tests (no sim/login calls)
```

Existing files extended:
- `grade.py` — add NEAR to status vocabulary; add selfcorr hook points
- `db.py` — possibly add `upsert_pnl()` helper (writes pnl_path); schema already has column
- `find_alphas.py` — add FSA filter + avoid-list injection into Researcher prompt

### Pattern 1: Hybrid Editor (mirrors researcher.py)

```python
# editor.py — deterministic + LLM hybrid
# Source: 03-CONTEXT.md D-01 + researcher.py pattern (verified codebase)

def classify_alpha(alpha_id: str, conn) -> tuple[str, list[str]]:
    """Deterministic: reads checks table, returns ('pass'|'near'|'fail', [failing_checks])."""
    ...

def diagnose_and_mutate(alpha_id: str, conn, client_session) -> dict:
    """Hybrid: deterministic context assembly + LLM subagent for diagnosis + mutations."""
    status, failing = classify_alpha(alpha_id, conn)
    alpha_row = conn.execute("SELECT * FROM alphas WHERE alpha_id=?", (alpha_id,)).fetchone()
    checks_rows = conn.execute("SELECT * FROM checks WHERE alpha_id=?", (alpha_id,)).fetchall()
    # Build structured context for LLM (expression + checks + diagnosis request)
    context = _build_editor_context(alpha_row, checks_rows, failing, status)
    # LLM call (Claude subagent in /iterate or /hunt context)
    # Returns: {"diagnosis": str, "mutations": [expr1, expr2, ...]}
    llm_response = _call_llm_editor(context)
    # Gate each mutation through validate + dedup (D-03)
    valid_mutations = [
        m for m in llm_response["mutations"]
        if validate.validate(conn, m)[0] and db.expr_exists(conn, m) is None
    ]
    return {"status": status, "diagnosis": llm_response["diagnosis"], "mutations": valid_mutations}
```

### Pattern 2: PnL Cache and Pearson Pre-filter (selfcorr.py)

```python
# selfcorr.py — stdlib only, no numpy
# Source: brain_client.py get_pnl() + community PnL conversion pattern [ASSUMED schema]

PNL_CACHE_DIR = Path("pnl_cache")  # or configurable; pnl_path stores full path

def fetch_and_cache(client, alpha_id: str, conn) -> Optional[str]:
    """Fetch PnL from BRAIN, cache as JSON, update pnl_path in DB. Returns path or None."""
    try:
        pnl_data = client.get_pnl(alpha_id)       # GET /alphas/{id}/recordsets/pnl
    except requests.HTTPError as e:
        if e.response.status_code == 401: raise   # propagate auth expiry
        return None                                # other errors → graceful degrade (D-13)
    path = PNL_CACHE_DIR / f"{alpha_id}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(pnl_data))
    conn.execute("UPDATE alphas SET pnl_path=? WHERE alpha_id=?", (str(path), alpha_id))
    conn.commit()
    return str(path)

def load_returns(pnl_path: str) -> list[float]:
    """Load cached PnL and convert to daily returns. Returns list of floats."""
    data = json.loads(Path(pnl_path).read_text())
    pnls = data["pnls"]
    # Forward-fill Nones, then diff: returns[i] = pnls[i] - pnls[i-1]
    # Filter to last 2 years [ASSUMED date-window based on community sources]
    return _pnls_to_daily_returns(pnls, data.get("dates", []))

def max_pearson(candidate_returns: list[float], reference_paths: list[str]) -> float:
    """Max Pearson correlation of candidate against all reference alphas."""
    max_corr = 0.0
    for path in reference_paths:
        ref_returns = load_returns(path)
        corr = _pearson(candidate_returns, ref_returns)
        if corr > max_corr:
            max_corr = corr
    return max_corr

def is_duplicate(candidate_returns, reference_paths, limit_val: float, margin: float = 0.0) -> bool:
    """True if max correlation >= limit_val - margin."""
    return max_pearson(candidate_returns, reference_paths) >= (limit_val - margin)
```

### Pattern 3: AST-based FSA (fsa.py)

```python
# fsa.py — Python stdlib ast, no external parser
# Source: verified working on all generated (non-ternary) FastExpr in DB

import ast
from collections import Counter

def extract_subtrees(expr: str) -> list[str]:
    """Parse FastExpr via Python ast, return list of abstract shape strings."""
    try:
        tree = ast.parse(expr.strip(), mode='eval')
    except SyntaxError:
        return []  # ternary / non-parseable → silently skip (D-13 graceful degrade)
    shapes = []
    def visit(node):
        if isinstance(node, ast.Call):
            func = node.func.id if isinstance(node.func, ast.Name) else '?'
            arg_types = [_arg_type(a) for a in node.args]
            shapes.append(f"{func}({','.join(arg_types)})")
            for a in node.args: visit(a)
    visit(tree.body)
    return shapes

def _arg_type(node) -> str:
    if isinstance(node, ast.Call): return 'CALL'
    if isinstance(node, ast.Constant):
        return 'NUM' if isinstance(node.value, (int, float)) else 'STR'
    if isinstance(node, ast.Name): return 'FIELD'
    if isinstance(node, ast.BinOp): return 'BINOP'
    return '_'

def mine_frequent_motifs(conn, threshold: float = 0.5, min_samples: int = 5) -> list[str]:
    """Mine subtree motifs from PASS alphas. Returns motifs appearing in >= threshold fraction."""
    pass_exprs = conn.execute(
        "SELECT expression FROM alphas WHERE status='pass'"
    ).fetchall()
    if len(pass_exprs) < min_samples:
        return []  # cold-start guard (Claude's discretion per 03-CONTEXT.md)
    counter: Counter = Counter()
    total = len(pass_exprs)
    for (expr,) in pass_exprs:
        for motif in set(extract_subtrees(expr)):  # set: count each motif once per alpha
            counter[motif] += 1
    return [motif for motif, cnt in counter.items() if cnt / total >= threshold]

def filter_candidates(candidates: list[dict], avoid_motifs: list[str]) -> list[dict]:
    """Drop candidates whose expression contains any motif in avoid_motifs."""
    if not avoid_motifs:
        return candidates
    avoid_set = set(avoid_motifs)
    result = []
    for c in candidates:
        motifs = set(extract_subtrees(c["expression"]))
        if not (motifs & avoid_set):
            result.append(c)
    return result
```

### Pattern 4: Autonomous Loop (/hunt)

```python
# hunt.py — /hunt orchestrator
# Implements D-16/D-17/D-20: bounded loop, no early-stop, configurable budget
# Source: 03-CONTEXT.md D-16..D-20 + grade.grade_many() pattern

def hunt(db_path, client, max_depth=2, max_sims=30):
    """Research → generate(FSA) → grade(selfcorr) → editor → bounded loop."""
    conn = db.init_db(db_path)
    avoid_motifs = fsa.mine_frequent_motifs(conn)
    run_id = uuid.uuid4().hex[:8]
    sims_used = 0
    best_submittable = None
    best_near = []

    # Gen 0: Researcher → Ideator → grade
    thesis = researcher.build_thesis(conn)
    candidates = ideator.generate_candidates(conn, thesis)
    candidates = fsa.filter_candidates(candidates, avoid_motifs)
    queue = [c["expression"] for c in ideator.queueable(candidates)]
    # Apply parent proxy gate before grading (selfcorr.proxy_gate)
    # Then grade_many (includes selfcorr precise filter pre-POST /check)
    results = grade.grade_many(client, conn, queue, run_id,
                               max_workers=3, db_path=db_path)
    sims_used += len(queue)

    for gen in range(max_depth):
        # Reclassify all graded alphas
        graded_ids = [r["alpha_id"] for r in results if r.get("alpha_id")]
        editor_results = [editor.classify_and_diagnose(aid, conn, ...) for aid in graded_ids]
        near_ids = [e["alpha_id"] for e in editor_results if e["status"] == "near"]
        submittable = [e for e in editor_results if e["status"] == "pass"]

        # Track best (D-20)
        if submittable:
            best_submittable = _rank_best(submittable, conn)
        best_near.extend(near_ids)

        # Stop conditions (D-16)
        if sims_used >= max_sims: break
        if not near_ids: break          # dry: no NEAR to mutate

        # Collect mutations from NEAR (and FAIL) editors
        all_mutations = []
        for res in editor_results:
            if res["status"] in ("near", "fail"):
                all_mutations.extend(res["mutations"])
        if not all_mutations: break

        # Dedup + FSA filter mutations
        all_mutations = [m for m in all_mutations if db.expr_exists(conn, m) is None]
        all_mutations = fsa.filter_candidates(
            [{"expression": m} for m in all_mutations], avoid_motifs
        )
        queue_next = [m["expression"] for m in all_mutations[:max_sims - sims_used]]
        if not queue_next: break

        results = grade.grade_many(client, conn, queue_next, run_id,
                                   max_workers=3, db_path=db_path)
        sims_used += len(queue_next)

    return {"best_submittable": best_submittable, "best_near": best_near, "sims_used": sims_used}
```

### Anti-Patterns to Avoid

- **Calling `login()` inside the loop:** `wq_login.login()` is called ONCE before the loop. A 401 inside `grade_many` propagates and stops the run. Never catch and retry a 401. [VERIFIED: CLAUDE.md + grade.py]
- **Exceeding max_workers=3:** `grade_many` already enforces `min(max_workers, MAX_CONCURRENT_SIMS)`. Do not bypass this. [VERIFIED: grade.py:37,266]
- **Hardcoding the SELF_CORRELATION limit:** Always read `limit_val` from `checks` table. Current DB shows 0.7 but this is region/account-specific. [VERIFIED: CLAUDE.md + DB query]
- **Running ast.parse on ACTIVE (user-submitted) alphas for FSA:** 6 of 16 ACTIVE alphas use BRAIN's ternary syntax (`?:`) which Python's ast cannot parse. FSA operates only on `status='pass'` alphas — none of which have ternary. [VERIFIED: DB query]
- **Storing PnL as numpy arrays:** venv has no numpy. Store as JSON (list of floats). [VERIFIED: venv pip list]
- **Sharing one SQLite connection across threads:** `grade_many` with `max_workers>1` already opens per-thread connections via `db_path`. `selfcorr.py` hooks must receive the worker's local connection, not the main-thread connection. [VERIFIED: grade.py:281-294]
- **Calling POST /check for locally-filtered duplicates:** The whole point of D-08b is to skip the BRAIN API call. After `selfcorr.precise_filter()` marks an alpha as duplicate, set `status='duplicate'` directly in DB and skip `trigger_correlation_check()`. [VERIFIED: 03-CONTEXT.md D-08, D-13]

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Expression tokenization | Custom string parser for FSA | Python `stdlib ast` | Verified working on all generated FastExpr (non-ternary); handles operator/field/numeric distinction cleanly |
| BRAIN API polling | Custom polling loop with fixed sleep | `client.get_pnl()` in brain_client.py (already has Retry-After loop) | SDK already handles Retry-After for recordsets |
| Concurrent simulation | New ThreadPoolExecutor wrapper | `grade.grade_many(max_workers=3)` | Already concurrency-capped, thread-safe DB connections, 401-propagation correct |
| Mutation validation | Regex/heuristic syntax check | `validate.py:validate(conn, expr)` | Phase 1 gate checks actual catalog; never bypass |
| Duplicate detection | Expression similarity hashing | `db.expr_exists(conn, expr)` | Exact string match on indexed column; fast |

**Key insight:** Phase 3's value is in the LOGIC (classify, diagnose, mutate, correlate, mine) — not in new infrastructure. All infrastructure reuse is mandatory.

---

## Common Pitfalls

### Pitfall 1: LOW_SUB_UNIVERSE_SHARPE Gap Percentage with Near-Zero Limit

**What goes wrong:** `abs(value - limit) / abs(limit)` blows up to thousands of percent when `limit_val` is near zero (seen in DB: `limit_val=0.0` case exists). All such FAILs get classified as FAIL regardless of actual proximity.

**Why it happens:** `LOW_SUB_UNIVERSE_SHARPE` limits are alpha-specific and can be 0.0 or slightly negative. [VERIFIED: DB query — `limit_val=-0.50, 0.00, 0.75` all seen]

**How to avoid:** Use `max(abs(limit_val), EPSILON)` with `EPSILON=0.01` as denominator floor. An alpha with value=-0.48 and limit=0.0 should be FAIL (it's nowhere near the limit from the correct direction), and the floor achieves this correctly.

**Warning signs:** If NEAR count seems implausibly high, check for near-zero-limit cases being misclassified.

### Pitfall 2: SELF_CORRELATION Check Status at Classification Time

**What goes wrong:** Most alphas that hit Phase B have `SELF_CORRELATION` in `PENDING` state in the checks table (verified: 49 of 50 SELF_CORRELATION rows show PENDING). Classifying these as PASS/NEAR/FAIL before Phase B completes gives wrong results.

**Why it happens:** `grade_one` stores the IS checks array immediately after simulation; `SELF_CORRELATION` and `PROD_CORRELATION` are PENDING at that point. Only after `poll_correlation()` do they resolve.

**How to avoid:** The Editor must ONLY classify alphas that have completed Phase B (i.e., `is_survivor=True` AND `SELF_CORRELATION` is no longer PENDING in the checks table). Check: `WHERE result != 'PENDING'` before classifying SELF_CORRELATION. [VERIFIED: grade.py:196-226 — Phase B only runs for IS survivors]

### Pitfall 3: ternary expressions in FSA Mining

**What goes wrong:** `ast.parse()` raises `SyntaxError` on BRAIN's `?:` ternary syntax. If FSA runs on ACTIVE (user-submitted) alphas, 6/16 will fail.

**Why it happens:** BRAIN uses a non-Python ternary syntax; Python's ast only handles standard Python.

**How to avoid:** FSA mines only from `status='pass'` alphas in `alphas` table. All system-generated (Ideator-produced) PASS alphas use standard Python-parseable FastExpr — verified in DB (0 ternary expressions in the `pass` status set). Wrap `ast.parse` in `try/except SyntaxError: return []` for safety. [VERIFIED: DB query]

### Pitfall 4: PnL Vector Length Mismatch

**What goes wrong:** Two PnL vectors from different test periods have different lengths; Pearson correlation uses `min(len(x), len(y))` but the date alignment matters — a 2024 alpha and a 2022 alpha may have non-overlapping date ranges.

**Why it happens:** `testPeriod=P1Y6M` means each alpha has an 18-month PnL window starting at different calendar dates.

**How to avoid:** Align by date before Pearson. Use the `dates` array to find the overlap period. If overlap is less than N trading days (say 60), skip that comparison (graceful degradation per D-13).

**Warning signs:** Pearson returning unexpectedly high or low values for obviously different alpha expressions is a signal of misaligned dates.

### Pitfall 5: Editor LLM Proposing Expressions with Unknown Tokens

**What goes wrong:** The LLM mutation step proposes a valid-looking expression using an operator or field not in the catalog (e.g., `ts_regression` if it's been removed, or a fantasy field like `implied_vol`).

**Why it happens:** LLM has training knowledge of BRAIN expressions but no live catalog access.

**How to avoid:** `validate.py:validate(conn, expr)` is the mandatory gate (D-03 LOCKED). Apply it to every proposed mutation before adding to queue. This is the Phase 1 pattern used by Ideator and must not be bypassed. [VERIFIED: 03-CONTEXT.md D-03, ideator.py:424-431]

### Pitfall 6: Re-auth Trap in `/hunt` Loop

**What goes wrong:** A 401 mid-loop causes the code to call `login()` again → `429 BIOMETRICS_THROTTLED` (15-30 min lockout).

**Why it happens:** Session token expires (~4 hours). In a long `/hunt` run this can happen.

**How to avoid:** ANY 401 must propagate to the top-level and stop the run cleanly. The `_grade_isolated` worker already does `if status_code == 401: raise`. The `/hunt` command must NOT catch `requests.HTTPError` with status 401. Let it surface with a human-readable message. [VERIFIED: grade.py:286-290, CLAUDE.md]

---

## Code Examples

### NEAR Classification (deterministic)

```python
# Source: verified against live DB checks structure
HARD_FAIL_CHECKS = frozenset({"MATCHES_COMPETITION", "CONCENTRATED_WEIGHT"})
EPSILON = 0.01  # floor for near-zero limits (LOW_SUB_UNIVERSE_SHARPE edge case)

def classify_from_checks(alpha_id: str, conn) -> tuple[str, list[str]]:
    """Return ('pass'|'near'|'fail', list_of_failing_check_names)."""
    rows = conn.execute(
        "SELECT name, result, value, limit_val FROM checks WHERE alpha_id=?",
        (alpha_id,)
    ).fetchall()

    # Ignore PENDING rows (Phase B not yet complete)
    resolved = [(n, r, v, l) for n, r, v, l in rows if r != "PENDING"]

    # Hard/structural fails
    for name, result, val, lim in resolved:
        if result == "FAIL" and name in HARD_FAIL_CHECKS:
            return "fail", [name]

    numeric_fails = []
    for name, result, val, lim in resolved:
        if result == "FAIL" and val is not None and lim is not None:
            gap = abs(val - lim) / max(abs(lim), EPSILON)
            numeric_fails.append((name, gap))

    if not numeric_fails:
        return "pass", []

    if len(numeric_fails) <= 2 and all(gap <= 0.20 for _, gap in numeric_fails):
        return "near", [n for n, _ in numeric_fails]

    return "fail", [n for n, _ in numeric_fails]
```

### PnL Fetch with Graceful Degradation

```python
# Source: brain_client.py get_pnl() + 03-CONTEXT.md D-13
def fetch_and_cache_pnl(client, alpha_id: str, conn, pnl_dir: str = "pnl_cache") -> Optional[str]:
    """Fetch PnL, cache to JSON, update pnl_path in DB. Returns path or None."""
    import json, requests
    from pathlib import Path
    try:
        pnl_data = client.get_pnl(alpha_id)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 401:
            raise  # auth expiry: always propagate
        return None  # other error: graceful degrade (D-13)
    except Exception:
        return None  # any other error (timeout, malformed): graceful degrade
    path = Path(pnl_dir) / f"{alpha_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pnls": pnl_data.get("pnls", []), "dates": pnl_data.get("dates", [])}))
    conn.execute("UPDATE alphas SET pnl_path=? WHERE alpha_id=?", (str(path), alpha_id))
    conn.commit()
    return str(path)
```

### Pearson (stdlib, no numpy)

```python
# Source: verified correct with Python stdlib math module
import math

def pearson(x: list[float], y: list[float]) -> float:
    """Pearson correlation of two float lists. Returns 0.0 if insufficient data."""
    n = min(len(x), len(y))
    if n < 2:
        return 0.0
    x, y = x[:n], y[:n]
    mx = sum(x) / n
    my = sum(y) / n
    num = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    sx = math.sqrt(sum((xi - mx) ** 2 for xi in x))
    sy = math.sqrt(sum((yi - my) ** 2 for yi in y))
    if sx == 0.0 or sy == 0.0:
        return 0.0
    return num / (sx * sy)
```

### FSA Abstract Subtree Extraction

```python
# Source: verified on all 8 archetype skeletons + generated pass alpha in DB
import ast
from collections import Counter

def extract_abstract_subtrees(expr: str) -> list[str]:
    """Extract operator-shape motifs from a FastExpr string. Returns [] on parse error."""
    try:
        tree = ast.parse(expr.strip(), mode='eval')
    except SyntaxError:
        return []
    shapes = []
    def _visit(node):
        if isinstance(node, ast.Call):
            fname = node.func.id if isinstance(node.func, ast.Name) else '?'
            arg_t = []
            for a in node.args:
                if isinstance(a, ast.Call): arg_t.append('CALL')
                elif isinstance(a, ast.Constant): arg_t.append('NUM' if isinstance(a.value, (int, float)) else 'STR')
                elif isinstance(a, ast.Name): arg_t.append('FIELD')
                elif isinstance(a, ast.BinOp): arg_t.append('BINOP')
                else: arg_t.append('_')
            shapes.append(f"{fname}({','.join(arg_t)})")
            for a in node.args: _visit(a)
    _visit(tree.body)
    return shapes
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Hardcode check thresholds (sharpe>1.25) | Read `limit` from `is.checks` array | Phase 1 | Correct submittability detection |
| No lineage tracking | `parent_alpha_id` FK in alphas table | Phase 1 schema | Enables traceable mutation trees |
| Human manually checks correlation | Local PnL Pearson pre-filter | Phase 3 (now) | Skips BRAIN API call for obvious duplicates |
| No structural diversity control | FSA motif mining + avoid-list | Phase 3 (now) | Prevents rediscovering same structural family |

**Deprecated/outdated:**
- `pnl_path = None` in `grade_one`: Phase 3 must write actual paths after PnL download (currently always None — verified in grade.py:179).
- Manual classification of check results: Phase 3 automates this with `classify_from_checks()`.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | PnL response schema is `{"pnls": [...], "dates": [...]}` | §PnL Endpoint Research | selfcorr.py must adapt key names; not a blocker, just a code change |
| A2 | Self-correlation uses 2-year rolling window for Pearson | §PnL Endpoint Research | Local pre-filter may have different cutoff than BRAIN's; calibration step (D-10) detects this |
| A3 | `SELF_CORRELATION` method is max Pearson on daily diffs | §PnL Endpoint Research | If BRAIN uses a different metric, local filter gives wrong results; D-13 graceful degrade handles this (falls back to POST /check) |
| A4 | CONCENTRATED_WEIGHT should be treated as a hard fail (D-06) | §Check Classification | If treated as numeric NEAR, a NEAR alpha with concentrated weight would get mutations that can't fix it |

**A1 mitigation:** The first PnL fetch should print/log the actual response keys so the implementer can adjust if the schema differs.

**If this table is empty:** All other claims in this research were verified against the codebase or DB.

---

## Open Questions (RESOLVED)

1. RESOLVED: **PnL date alignment between candidate and reference alphas**
   - What we know: PnL has a `dates` array; each alpha has a different test period start date depending on when it was simulated
   - What's unclear: the exact overlap behavior when a newly simulated alpha's `testPeriod=P1Y6M` overlaps differently with a 3-year-old submitted alpha's PnL window
   - Recommendation: Align by date, use only the overlapping window. If overlap < 60 trading days, skip that comparison (D-13 graceful degrade). Implement date alignment in `selfcorr.py:load_returns()` using the `dates` array.

2. RESOLVED: **SELF_CORRELATION calibration: is the DB-observed limit_val=0.7 stable across regions?**
   - What we know: All 1 resolved `SELF_CORRELATION` check in DB shows `limit_val=0.7`; design doc says "default 0.7; reference impls use 0.6" [CITED: docs/plans/2026-06-07-alpha-system-design.md]
   - What's unclear: Whether limit changes for non-USA regions or over time
   - Recommendation: Always read `limit_val` from `checks` table at runtime (already the plan, D-11). The first `/hunt` run will naturally populate more resolved values.

3. RESOLVED: **How to handle PnL for ACTIVE (user-submitted) alphas that haven't been re-simulated?**
   - What we know: The 16 ACTIVE alphas have `pnl_path=None`; `self_corr=None` (not in our DB yet)
   - What's unclear: Can `client.get_pnl(alpha_id)` be called for any alpha_id (including old user-submitted ones) without simulating again?
   - Recommendation: Yes — `GET /alphas/{id}/recordsets/pnl` should work for any alpha_id that exists in BRAIN's system (the user has 16 submitted alphas with known IDs). The D-12 backfill step calls `client.get_pnl()` for each ACTIVE alpha_id from DB. If it returns 404 or other error, skip that alpha (D-13 graceful degrade).

4. RESOLVED: **FSA threshold value (Claude's discretion)**
   - Recommendation: Start with `threshold=0.5` (motif appears in ≥50% of PASS alphas) and `min_samples=5`. With 1 PASS alpha currently in DB, cold-start guard returns empty list (no filtering until 5+ PASS alphas). This is the correct behavior — don't filter when data is sparse.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python venv | All code | ✓ | Python 3.14 | — |
| `requests` | PnL fetch | ✓ | 2.34.2 | — |
| `pytest` | test_phase3.py | ✓ | 9.0.3 | — |
| `autobrain-sim` (brain_client) | `client.get_pnl()` | ✓ | 1.0.0 | — |
| `numpy` / `pandas` | Pearson, PnL processing | ✗ | — | stdlib `math` + pure-Python Pearson (verified working) |
| `alpha_kb.db` with synced catalog | `validate.py` + FSA | ✓ | 429 rows in alphas | — |

[VERIFIED: venv pip list query]

**Missing dependencies with no fallback:** None — all Phase 3 functionality is achievable with stdlib.

**Missing dependencies with fallback:**
- `numpy`/`pandas`: not in venv. Pure Python Pearson implemented and verified. JSON for PnL storage. No install needed.

---

## Security Domain

No new authentication, session management, or user-facing input handling. The primary security concern is the same as Phase 1/2:

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V5 Input Validation | yes — LLM mutation output | `validate.py` gate on every proposed mutation (already enforced D-03) |
| V2 Authentication | no new auth | Single-shot `wq_login.login()` unchanged |
| V6 Cryptography | no | — |

No new SQL queries beyond parameterized SELECT/UPDATE already used in project. LLM-proposed expressions pass through `validate()` before any SQL insert.

---

## Sources

### Primary (HIGH confidence)

- [VERIFIED: codebase] `grade.py`, `db.py`, `ideator.py`, `researcher.py`, `validate.py`, `find_alphas.py`, `brain_client.py` — direct code inspection
- [VERIFIED: DB query] `alpha_kb.db` queries — live check names, value/limit distributions, NEAR classification examples, ACTIVE/pass/fail status counts
- [VERIFIED: codebase] `03-CONTEXT.md` — locked decisions D-01..D-20, canonical references
- [CITED: docs/plans/2026-06-07-alpha-system-design.md] — system design, PnL endpoint description, SELF_CORRELATION threshold discussion

### Secondary (MEDIUM confidence)

- Community implementations (xiegengcai/world-quant-brain, krocellx/WorldQuant-Alpha-Research via DeepWiki summaries) — confirmed PnL-to-returns conversion pattern, 2-year window for self-correlation

### Tertiary (LOW / ASSUMED)

- A1: PnL response schema `{"pnls": [...], "dates": [...]}` — community-sourced, not from official BRAIN API docs
- A2-A3: 2-year window + max Pearson method — community-sourced, calibration step will verify

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all packages verified in venv; all module signatures read from source
- Architecture: HIGH — all patterns directly derived from existing Phase 1/2 code; no novel infrastructure
- BRAIN PnL endpoint: MEDIUM — SDK wrapper confirmed; response schema assumed from community sources
- SELF_CORRELATION method: MEDIUM — community-sourced; calibration step designed to verify at runtime
- Pitfalls: HIGH — all derived from actual DB data and code inspection

**Research date:** 2026-06-09
**Valid until:** 2026-07-09 (30 days — BRAIN API stable; library versions locked in venv)
