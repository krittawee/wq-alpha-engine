# Phase 3: Smart Iteration - Pattern Map

**Mapped:** 2026-06-09
**Files analyzed:** 7 (4 new + 3 modified)
**Analogs found:** 7 / 7

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `editor.py` | service (hybrid: deterministic classify + LLM mutate) | request-response | `researcher.py` | exact — same hybrid pattern: deterministic DB reads assemble context, LLM layer runs on top |
| `selfcorr.py` | service (pure compute + BRAIN I/O) | request-response + file-I/O | `grade.py` (`_simulate_to_alpha`, 401 propagation, `poll_correlation` Retry-After) | role-match — same BRAIN session usage, same 401/graceful-degrade pattern |
| `fsa.py` | utility (pure compute, no BRAIN) | transform | `researcher.py` (`gather_insights`, `read_catalog` — pure DB reads returning structured data) | role-match — same pattern: read DB, compute, return structured result |
| `hunt.py` | orchestrator / entry point | event-driven autonomous loop | `find_alphas.py` (orchestrator that chains modules) + `cli.py` (single-shot auth, 401 surface) | role-match — same entry-point pattern; extends with a loop |
| `test_phase3.py` | test | — | `test_phase2.py` | exact — same fixture pattern (temp DB copy, module-level patches, no sim/login calls) |
| `grade.py` (modify) | service | request-response | self | — add NEAR to status vocabulary + selfcorr hook points |
| `find_alphas.py` (modify) | orchestrator | request-response | self | — add FSA filter + avoid-list injection into Researcher call |

---

## Pattern Assignments

### `editor.py` (service, hybrid deterministic+LLM)

**Analog:** `researcher.py`

**Module docstring + imports pattern** (`researcher.py` lines 1–16):
```python
"""editor.py — Hybrid Editor for the Alpha Discovery System.

Deterministic tier: reads the checks table, classifies each alpha
PASS/NEAR/FAIL (D-05..D-07), identifies which checks failed and by how much.
LLM tier: given the structured failure context, writes a human-readable
diagnosis and proposes 1-3 validated expression mutations.

No BRAIN API calls. No simulate/login references.
"""

import sqlite3
from typing import Optional

import db
import validate
```

**Deterministic classification core** (pattern from `researcher.py` lines 82–111, adapted to the NEAR algorithm verified in `03-RESEARCH.md` §Code Examples lines 606–638):
```python
HARD_FAIL_CHECKS = frozenset({"MATCHES_COMPETITION", "CONCENTRATED_WEIGHT"})
EPSILON = 0.01  # floor for near-zero limits (LOW_SUB_UNIVERSE_SHARPE edge case)

def classify_from_checks(alpha_id: str, conn: sqlite3.Connection) -> tuple[str, list[str]]:
    """Return ('pass'|'near'|'fail', list_of_failing_check_names).
    Only call for alphas that have completed Phase B (no PENDING rows).
    """
    rows = conn.execute(
        "SELECT name, result, value, limit_val FROM checks WHERE alpha_id=?",
        (alpha_id,)
    ).fetchall()
    resolved = [(n, r, v, l) for n, r, v, l in rows if r != "PENDING"]

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

**DB query pattern** (mirrors `researcher.py` lines 83–111 — parameterized SELECTs, return dicts):
```python
# Read the alpha row + all resolved checks for LLM context assembly
alpha_row = conn.execute(
    "SELECT alpha_id, expression, sharpe, fitness, turnover, status FROM alphas WHERE alpha_id=?",
    (alpha_id,)
).fetchone()
checks_rows = conn.execute(
    "SELECT name, result, value, limit_val FROM checks WHERE alpha_id=? AND result != 'PENDING'",
    (alpha_id,)
).fetchall()
```

**Mutation validation gate** (mirrors `ideator.py` lines 424–431 pattern — validate + dedup before accepting):
```python
valid_mutations = []
for expr in proposed:
    ok, reason = validate.validate(conn, expr)
    if not ok:
        continue  # drop silently (D-03)
    if db.expr_exists(conn, expr) is not None:
        continue  # drop silently (D-03)
    valid_mutations.append(expr)
```

**Error handling pattern** (mirrors `grade.py` lines 79–88 — 401 propagates, other errors degrade):
```python
# 401 always propagates — never catch and retry auth
try:
    llm_response = _call_llm_editor(context)
except requests.exceptions.HTTPError as e:
    if getattr(getattr(e, "response", None), "status_code", None) == 401:
        raise
    return {"status": status, "diagnosis": None, "mutations": []}
```

---

### `selfcorr.py` (service, PnL fetch + Pearson compute)

**Analog:** `grade.py` (BRAIN session usage pattern) + `researcher.py` (pure-function compute)

**Module docstring + imports pattern** (`grade.py` lines 1–32 style):
```python
"""selfcorr.py — Local PnL-based self-correlation pre-filter.

Two-stage filter (D-08):
  (a) proxy_gate: pre-sim check using parent's already-cached PnL.
  (b) precise_filter: post-sim check on candidate's own PnL before
      triggering BRAIN's POST /check.

Uses Python stdlib only (no numpy). Gracefully degrades to None when
PnL is unavailable — never blocks grading (D-13).
"""

import json
import math
import sqlite3
from pathlib import Path
from typing import Optional

import requests
```

**BRAIN API call pattern with 401 propagation and graceful degrade** (mirrors `grade.py` lines 61–88):
```python
def fetch_and_cache_pnl(client, alpha_id: str, conn: sqlite3.Connection,
                         pnl_dir: str = "pnl_cache") -> Optional[str]:
    """Fetch PnL from BRAIN, cache to JSON, update pnl_path. Returns path or None."""
    try:
        pnl_data = client.get_pnl(alpha_id)
    except requests.exceptions.HTTPError as e:
        if getattr(getattr(e, "response", None), "status_code", None) == 401:
            raise  # auth expiry — always propagate (CLAUDE.md constraint)
        return None  # other HTTP error → graceful degrade (D-13)
    except Exception:
        return None  # timeout / malformed → graceful degrade (D-13)
    path = Path(pnl_dir) / f"{alpha_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pnls": pnl_data.get("pnls", []),
                                 "dates": pnl_data.get("dates", [])}))
    conn.execute("UPDATE alphas SET pnl_path=? WHERE alpha_id=?",
                 (str(path), alpha_id))
    conn.commit()
    return str(path)
```

**DB read for reference set** (parameterized SELECT, mirrors `researcher.py` lines 83–111):
```python
def get_reference_pnl_paths(conn: sqlite3.Connection) -> list[str]:
    """Return pnl_path for all PASS alphas + ACTIVE (submitted) alphas with cached PnL."""
    rows = conn.execute(
        "SELECT pnl_path FROM alphas"
        " WHERE pnl_path IS NOT NULL AND status IN ('pass', 'ACTIVE')"
    ).fetchall()
    return [row[0] for row in rows]
```

**Stdlib Pearson (no numpy)** (from `03-RESEARCH.md` §Code Examples lines 667–684):
```python
def _pearson(x: list[float], y: list[float]) -> float:
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

**SELF_CORRELATION limit read from DB** (never hardcode — mirrors `grade.py` lines 204–205 + CLAUDE.md):
```python
def get_selfcorr_limit(conn: sqlite3.Connection) -> Optional[float]:
    """Read SELF_CORRELATION limit_val from checks table. Returns None if unavailable."""
    row = conn.execute(
        "SELECT limit_val FROM checks"
        " WHERE name='SELF_CORRELATION' AND limit_val IS NOT NULL LIMIT 1"
    ).fetchone()
    return row[0] if row else None
```

---

### `fsa.py` (utility, AST subtree mining)

**Analog:** `researcher.py` (pure DB-read + compute, no BRAIN API, returns structured data)

**Module docstring + imports pattern** (`researcher.py` lines 1–16 style):
```python
"""fsa.py — Frequent Subtree Avoidance for the Alpha Discovery System.

Mines common structural motifs (abstract AST subtree shapes) from PASS
alphas in the DB. Returns an avoid-list that:
  - is injected into Researcher + Editor LLM prompts (upstream steer)
  - is applied as a post-generation filter in find_alphas / hunt (hard gate)

Uses Python stdlib ast only. Operates on status='pass' alphas —
never on ACTIVE user-submitted alphas (which may use ternary syntax).
"""

import ast
from collections import Counter
import sqlite3
from typing import Optional
```

**DB read for PASS alphas** (parameterized SELECT, mirrors `researcher.py` lines 127–148):
```python
def mine_frequent_motifs(conn: sqlite3.Connection,
                          threshold: float = 0.5,
                          min_samples: int = 5) -> list[str]:
    """Mine subtree motifs from PASS alphas. Returns motifs in >= threshold fraction.
    Returns [] if fewer than min_samples PASS alphas exist (cold-start guard).
    """
    pass_exprs = conn.execute(
        "SELECT expression FROM alphas WHERE status='pass'"
    ).fetchall()
    if len(pass_exprs) < min_samples:
        return []  # cold-start guard (Claude's discretion — 03-CONTEXT.md)
    ...
```

**AST extraction pattern** (from `03-RESEARCH.md` §Code Examples lines 694–714):
```python
def extract_abstract_subtrees(expr: str) -> list[str]:
    """Extract operator-shape motifs. Returns [] on SyntaxError (ternary safety)."""
    try:
        tree = ast.parse(expr.strip(), mode='eval')
    except SyntaxError:
        return []  # BRAIN ternary (?:) or malformed — skip silently
    shapes = []
    def _visit(node):
        if isinstance(node, ast.Call):
            fname = node.func.id if isinstance(node.func, ast.Name) else '?'
            arg_t = []
            for a in node.args:
                if isinstance(a, ast.Call): arg_t.append('CALL')
                elif isinstance(a, ast.Constant):
                    arg_t.append('NUM' if isinstance(a.value, (int, float)) else 'STR')
                elif isinstance(a, ast.Name): arg_t.append('FIELD')
                elif isinstance(a, ast.BinOp): arg_t.append('BINOP')
                else: arg_t.append('_')
            shapes.append(f"{fname}({','.join(arg_t)})")
            for a in node.args: _visit(a)
    _visit(tree.body)
    return shapes
```

**Filter function** (mirrors `ideator.py` `queueable()` gate pattern — filter a list, return filtered list):
```python
def filter_candidates(candidates: list[dict], avoid_motifs: list[str]) -> list[dict]:
    """Drop candidates whose expression contains any avoid motif. No-op if avoid_motifs empty."""
    if not avoid_motifs:
        return candidates
    avoid_set = set(avoid_motifs)
    return [
        c for c in candidates
        if not (set(extract_abstract_subtrees(c["expression"])) & avoid_set)
    ]
```

---

### `hunt.py` (orchestrator, autonomous loop)

**Analog:** `find_alphas.py` (module structure, imports, orchestrator pattern) + `cli.py` (single-shot auth, 401 surface, argparse CLI)

**Module docstring + imports** (`find_alphas.py` lines 1–25 style):
```python
"""hunt.py — Orchestrator for the /hunt autonomous alpha-discovery command.

Chains: research → generate(FSA) → grade(selfcorr) → editor diagnose/mutate
→ bounded loop → returns best new submittable alpha (D-20).

Budget: configurable max_depth (generations) and max_sims ceiling.
Auth: called ONCE before the loop. A 401 mid-loop stops the run cleanly —
      never re-auth in-loop (CLAUDE.md).
"""

import argparse
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from typing import Optional

import requests

from wq_login import login
import db
import editor
import fsa
import grade
import ideator
import researcher
import selfcorr
```

**Single-shot auth + 401 surface** (mirrors `cli.py` lines 69–112 exactly):
```python
# Single-shot auth — called ONCE before the loop (CLAUDE.md constraint)
client = login()

try:
    result = hunt(client=client, db_path=args.db,
                  max_depth=args.max_depth, max_sims=args.max_sims)
except requests.exceptions.HTTPError as e:
    if getattr(getattr(e, "response", None), "status_code", None) == 401:
        print(
            "[hunt] AUTH EXPIRED — 401 received. "
            "Re-run hunt.py to re-authenticate. Stopping."
        )
        sys.exit(1)
    raise
```

**DB connection pattern** (mirrors `find_alphas.py` lines 391–395 — open once, close in finally):
```python
def hunt(client, db_path: str = "alpha_kb.db",
         max_depth: int = 2, max_sims: int = 30) -> dict:
    conn = db.init_db(db_path)
    try:
        run_id = str(uuid.uuid4())[:8]
        ...
    finally:
        conn.close()
```

**grade_many call pattern** (mirrors `cli.py` lines 96–98 — pass db_path for per-thread connections):
```python
# MUST pass db_path so grade_many workers each open their own SQLite connection
# (single connection cannot be shared across threads — grade.py:279-294)
results = grade.grade_many(
    client, conn, queue, run_id,
    max_workers=3, db_path=db_path
)
```

**Loop stop conditions** (D-16/D-17 — depth OR budget OR dry):
```python
for gen in range(max_depth):
    ...
    if sims_used >= max_sims:
        break
    if not near_ids:
        break  # dry: no NEAR to feed next generation
    if not all_mutations:
        break
```

**Print summary pattern** (mirrors `find_alphas.py` lines 439–447 — human-readable output):
```python
print(f"\n--- /hunt complete ---")
print(f"  run_id:          {run_id}")
print(f"  sims used:       {result['sims_used']} / {max_sims}")
print(f"  best submittable: {result['best_submittable']}")
print(f"  best NEAR:       {len(result['best_near'])} candidates")
```

---

### `test_phase3.py` (test)

**Analog:** `test_phase2.py`

**File-level structure** (`test_phase2.py` lines 1–48):
```python
"""test_phase3.py — Criterion tests for Phase 3: Smart Iteration.

Machine-verifies all 4 ROADMAP Phase 3 success criteria:
Criterion 1: Editor correctly classifies PASS/NEAR/FAIL from checks table.
Criterion 2: Editor proposes mutations with parent_alpha_id lineage; all
             mutations pass validate.validate + db.expr_exists dedup.
Criterion 3: Local self-corr filter correctly computes Pearson + gates duplicates.
Criterion 4: FSA mines motifs from PASS alphas and filters candidates.

CRITICAL: ZERO grade/simulate/login calls.
"""

import os
import shutil
import sys
import tempfile

import db
import editor
import fsa
import selfcorr
```

**Temp DB fixture pattern** (`test_phase2.py` lines 71–82 — copy live DB to tmpdir, patch module constants):
```python
with tempfile.TemporaryDirectory() as tmpdir:
    tmp_db = os.path.join(tmpdir, "test.db")
    shutil.copy("alpha_kb.db", tmp_db)
    conn = db.init_db(tmp_db)
    try:
        # insert deterministic test rows, run assertions
        ...
    finally:
        conn.close()
```

**Assert pattern** (`test_phase2.py` lines 88–101 — descriptive assert messages, stdlib only):
```python
assert result == "near", (
    f"Criterion 1 FAIL: expected 'near', got {result!r} "
    f"for alpha with sharpe within 20% of limit"
)
```

**Test function naming convention** (`test_phase2.py` lines 56, pattern):
```python
def test_criterion_1_near_classification() -> None: ...
def test_criterion_2_mutation_lineage() -> None: ...
def test_criterion_3_pearson_prefilter() -> None: ...
def test_criterion_4_fsa_mining() -> None: ...
```

---

### `grade.py` (modify — add NEAR status + selfcorr hook points)

**Analog:** self (existing `grade.py`)

**Status vocabulary extension** (current status assignment at `grade.py` lines 154 and 209–215):
```python
# Current (lines 154, 209-215):
status = "pass" if is_survivor else "fail"
...
status_final = "pass"

# Phase 3 addition: after Phase B resolves, call editor.classify_from_checks()
# to reclassify IS survivors from "pass" to "near" where appropriate.
# Do NOT call this inline in grade_one — editor.py is the caller's responsibility.
# Instead: add a 'near' value to the status vocabulary by updating the UPDATE
# statement that writes status back:
conn.execute(
    "UPDATE alphas SET self_corr=?, prod_corr=?, corr_checked_at=?, status=? "
    "WHERE alpha_id=?",
    (self_corr, prod_corr, corr_checked_at, status_final, alpha_id),
)
```

**Selfcorr hook locations** (two injection points):

Hook A — pre-sim proxy gate in `grade_one` (after Step 0 dedup check, before Step 2 simulate, `grade.py` lines 107–121):
```python
# [NEW — Phase 3 selfcorr hook A: parent PnL proxy gate]
# If this is a mutation (parent_alpha_id is set), check parent's PnL similarity
# before spending a sim slot. Pass parent_alpha_id and conn to selfcorr.proxy_gate().
# selfcorr.proxy_gate() returns True if locally too-correlated → skip.
# Only when parent_alpha_id is known and parent has pnl_path cached.
```

Hook B — pre-`trigger_correlation_check` precise filter in `grade_one` (after sim but before Phase B, `grade.py` lines 200–202):
```python
# [NEW — Phase 3 selfcorr hook B: precise filter post-sim, pre-POST /check]
# After sim returns PnL (fetch_and_cache_pnl), compare candidate to reference set.
# If locally too-correlated: set status='duplicate', skip trigger_correlation_check().
# This is the whole point of D-08b — avoid the BRAIN API call for obvious dupes.
if is_survivor:
    pnl_path = selfcorr.fetch_and_cache_pnl(client, alpha_id, conn)
    if pnl_path:
        ref_paths = selfcorr.get_reference_pnl_paths(conn)
        limit = selfcorr.get_selfcorr_limit(conn)
        if limit and selfcorr.is_duplicate_by_pnl(pnl_path, ref_paths, limit):
            conn.execute("UPDATE alphas SET status='duplicate' WHERE alpha_id=?", (alpha_id,))
            conn.commit()
            return {... "status": "duplicate", ...}
    trigger_correlation_check(client, alpha_id)
```

---

### `find_alphas.py` (modify — add FSA filter + avoid-list injection)

**Analog:** self (existing `find_alphas.py`)

**FSA import addition** (at existing `find_alphas.py` lines 23–26):
```python
import fsa  # NEW — Phase 3 FSA filter
```

**FSA filter injection in `find_alphas()`** (after `ideator.generate_candidates()` at line 398, before queueable at line 424):
```python
# [NEW — Phase 3 FSA hook]
# Mine motifs from PASS alphas and filter candidates before queueing.
avoid_motifs = fsa.mine_frequent_motifs(conn)
candidates_dict = [{"expression": c["expression"]} for c in candidates]
filtered = fsa.filter_candidates(candidates_dict, avoid_motifs)
# Re-merge: mark dropped candidates as filtered (for transparency in note table)
```

**Avoid-list injection into thesis** (pass avoid_motifs to `researcher.build_thesis` call at line 395 or assemble separately):
```python
# Pass avoid_motifs to the LLM prose step (Researcher + Editor prompts)
# by adding an 'avoid_motifs' key to the thesis dict or as a separate arg.
# This mirrors how 'cited_insights' are passed to the note renderer (find_alphas.py:413).
```

---

## Shared Patterns

### Single-Shot Auth — Never Re-auth In-Loop
**Source:** `cli.py` lines 69–112, `grade.py` lines 79–88 and 286–290
**Apply to:** `hunt.py` (entry point), any new code that touches `client`

```python
# ALWAYS: login() exactly once before any loop
client = login()

# ALWAYS: 401 propagates up and stops the run — never catch-and-retry
except requests.exceptions.HTTPError as e:
    if getattr(getattr(e, "response", None), "status_code", None) == 401:
        raise  # or sys.exit(1) at the CLI layer
```

### Per-Thread SQLite Connections for Concurrent Workers
**Source:** `grade.py` lines 279–294, `db.py` lines 55–70
**Apply to:** `hunt.py` (when calling `grade_many`), any new code spawning threads

```python
# ALWAYS pass db_path to grade_many so workers open independent connections
results = grade.grade_many(client, conn, queue, run_id,
                            max_workers=3, db_path=db_path)

# NEVER share a single sqlite3.Connection across threads.
# db.init_db(path) opens a new WAL-mode connection with busy_timeout=30000.
```

### Parameterized SQL — Never String-Interpolated
**Source:** `db.py` lines 73–108, `researcher.py` lines 83–111, `validate.py` lines 54–75
**Apply to:** all new DB queries in `editor.py`, `selfcorr.py`, `fsa.py`

```python
# ALWAYS: parameterized queries
conn.execute("SELECT ... WHERE alpha_id=?", (alpha_id,))
conn.execute("UPDATE alphas SET pnl_path=? WHERE alpha_id=?", (path, alpha_id))
# NEVER: f"SELECT ... WHERE alpha_id='{alpha_id}'"
```

### Validate Gate Before Any DB Insert
**Source:** `ideator.py` lines 424–431, `grade.py` lines 113–116
**Apply to:** `editor.py` mutation proposals before inserting/queueing

```python
ok, reason = validate.validate(conn, expr)
if not ok:
    continue  # drop invalid mutations silently (D-03)
if db.expr_exists(conn, expr) is not None:
    continue  # drop duplicates silently (D-03)
```

### Graceful Degradation on Non-Auth HTTP Errors
**Source:** `grade.py` lines 79–88, `grade_many` lines 285–292
**Apply to:** `selfcorr.py` PnL fetch, any new BRAIN API call

```python
try:
    data = client.some_api_call(alpha_id)
except requests.exceptions.HTTPError as e:
    if getattr(getattr(e, "response", None), "status_code", None) == 401:
        raise  # propagate auth failure
    return None  # degrade gracefully for all other HTTP errors
except Exception:
    return None  # degrade for timeouts, malformed responses, etc.
```

### DB Connection Lifecycle — Caller Owns, Finally-Close
**Source:** `find_alphas.py` lines 391–435, `grade_many` lines 282–294
**Apply to:** `hunt.py` main orchestrator function

```python
conn = db.init_db(db_path)
try:
    # ... all work ...
finally:
    conn.close()
```

---

## No Analog Found

No Phase 3 file is completely without analog. All new modules have strong role-match or exact analogs in the existing codebase.

| File | Closest Analog Gap | Mitigation |
|------|-------------------|------------|
| `selfcorr.py` (Pearson stdlib math) | No existing float-vector compute in codebase | Use `03-RESEARCH.md` §Code Examples lines 667–684 as the reference implementation |
| `selfcorr.py` (PnL date alignment) | No existing date-series alignment | Align by the `dates` array from the PnL response; skip comparisons with < 60 overlapping days (D-13 graceful degrade) |
| `hunt.py` (autonomous generation loop) | `find_alphas.py` stops before grading; no existing loop | Combine `find_alphas.py` structure with `cli.py` grade call + `grade_many` pattern |

---

## Metadata

**Analog search scope:** `/Users/winter.__.kor/quant/*.py` (flat project, all modules read)
**Files scanned:** `researcher.py`, `grade.py`, `ideator.py`, `find_alphas.py`, `db.py`, `validate.py`, `cli.py`, `test_phase2.py`
**Pattern extraction date:** 2026-06-09
