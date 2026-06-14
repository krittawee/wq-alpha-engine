---
phase: quick-260613-kpu
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - db.py
  - ideator.py
  - hunt.py
  - selfcorr.py
  - test_phase4.py
autonomous: true
requirements: [BUG-DELAY-DEDUP, BUG-SELFCORR-PNL]

must_haves:
  truths:
    - "A delay-0 candidate whose expression already exists in the DB under delay=1 is NOT dropped as a duplicate"
    - "A delay-0 candidate whose expression already exists under delay=0 IS dropped as a duplicate"
    - "fetch_and_cache_pnl correctly reads BRAIN's {schema, records} response and writes non-empty pnls/dates to the cache file"
    - "load_returns and the rest of selfcorr are untouched (on-disk cache format unchanged)"
    - "All existing expr_exists callers that pass no delay (editor.py, grade.py, hunt._is_passable) continue to work without modification"
  artifacts:
    - path: "db.py"
      provides: "delay-aware expr_exists(conn, expression, delay=None)"
      contains: "WHERE expression=? AND delay=?"
    - path: "ideator.py"
      provides: "generate_candidates threads delay into db.expr_exists"
      contains: "db.expr_exists(conn, expr, delay=delay)"
    - path: "hunt.py"
      provides: "Gen 0 call passes delay into generate_candidates"
      contains: "ideator.generate_candidates(conn, thesis, delay=delay)"
    - path: "selfcorr.py"
      provides: "PnL parser reads schema+records format"
      contains: "records"
    - path: "test_phase4.py"
      provides: "regression tests for both bugs"
  key_links:
    - from: "hunt.py Gen 0 path"
      to: "ideator.generate_candidates"
      via: "delay= kwarg"
    - from: "ideator.generate_candidates"
      to: "db.expr_exists"
      via: "delay= kwarg"
    - from: "selfcorr.fetch_and_cache_pnl"
      to: "pnl_cache JSON file"
      via: "schema+records parser writing {pnls, dates}"
---

<objective>
Fix two confirmed bugs that together cause delay-0 /hunt runs to produce 0 candidates
and 0 usable PnL data.

Bug 1: db.expr_exists matches on expression text only, ignoring delay. A delay-0 run
generates the same expressions already stored for delay-1, so every candidate is
dropped as a duplicate before any simulation runs.

Bug 2: selfcorr.fetch_and_cache_pnl expects pnl_data["pnls"] / pnl_data["dates"] but
BRAIN returns pnl_data["schema"] / pnl_data["records"]. Every cached PnL file is
written empty, breaking local self-correlation computation.

Purpose: Unblock delay-0 alpha discovery and restore PnL-based self-correlation checks.
Output: Patched db.py, ideator.py, hunt.py, selfcorr.py; regression tests in test_phase4.py.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@/Users/winter.__.kor/quant/.planning/PROJECT.md
@/Users/winter.__.kor/quant/.planning/ROADMAP.md
@/Users/winter.__.kor/quant/.planning/STATE.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Delay-aware novelty dedup</name>
  <files>db.py, ideator.py, hunt.py</files>
  <action>
Make db.expr_exists delay-aware with full backward compatibility.

In db.py, update `expr_exists` signature to:
  def expr_exists(conn, expression: str, delay: Optional[int] = None) -> Optional[str]:

When delay is None (current behavior preserved): query `WHERE expression=? LIMIT 1`.
When delay is an int: query `WHERE expression=? AND delay=? LIMIT 1`.

Update the docstring to note the delay param and that alphas.delay holds BRAIN's ACTUAL
returned delay (set by the 2026-06-11 recording fix), so matching on it is correct.

In ideator.py, update `generate_candidates` signature to accept `delay: Optional[int] = None`
(new kwarg, default None preserves all existing callers). Thread it into the dedup call at
line 425: change `db.expr_exists(conn, expr)` to `db.expr_exists(conn, expr, delay=delay)`.
Update the Returns docstring to note that dedup_alpha_id is now keyed on (expression, delay).

In hunt.py, update the Gen 0 call at line 202:
  candidates = ideator.generate_candidates(conn, thesis)
to:
  candidates = ideator.generate_candidates(conn, thesis, delay=delay)

The variable `delay` is already in scope at that point (passed into the hunt function and
threaded to grade_many / build_thesis).

Do NOT change the mutation path in hunt.py (lines 300-325): mutations are pre-inserted
as status='queued' by editor.diagnose_and_mutate and use _is_passable() instead of
generate_candidates, so they do not go through this dedup path. Leave _is_passable and
its db.expr_exists call at line 97 unchanged (no delay kwarg — correct, because
editor-produced mutations are delay-agnostic stubs).

Do NOT change the callers in editor.py (line 272), grade.py (line 149), or find_alphas.py
(line 408). Those callers do not pass delay, so they continue to use expression-only dedup.
This is acceptable: editor.py drops mutations it pre-inserted (already handled by
_is_passable upstream); grade.py uses the same dedup logic as before for its own checks;
find_alphas.py has no delay-specific dedup requirement today.
  </action>
  <verify>
    <automated>cd /Users/winter.__.kor/quant && ./venv/bin/python -c "
import sqlite3, db
conn = db.init_db(':memory:')
# Manually insert a delay-1 row
conn.execute(\"INSERT INTO alphas (alpha_id, expression, delay) VALUES ('A1', 'rank(returns)', 1)\")
conn.commit()
# Same expression, delay=0 must NOT match
result = db.expr_exists(conn, 'rank(returns)', delay=0)
assert result is None, f'Expected None for delay=0, got {result}'
# Same expression, delay=1 MUST match
result = db.expr_exists(conn, 'rank(returns)', delay=1)
assert result == 'A1', f'Expected A1, got {result}'
# No delay arg must still match (backward compat)
result = db.expr_exists(conn, 'rank(returns)')
assert result == 'A1', f'Expected A1 (no-delay), got {result}'
print('Task 1 inline checks: PASS')
"
    </automated>
  </verify>
  <done>
db.expr_exists accepts an optional delay int; with delay=0 it does not match a delay=1
row for the same expression; with no delay arg the behavior is identical to before.
ideator.generate_candidates accepts delay= and threads it to db.expr_exists.
hunt.py Gen 0 passes delay= to generate_candidates.
Inline verification prints "Task 1 inline checks: PASS".
  </done>
</task>

<task type="auto">
  <name>Task 2: selfcorr PnL parser for schema+records format</name>
  <files>selfcorr.py</files>
  <action>
Fix `fetch_and_cache_pnl` in selfcorr.py to parse BRAIN's actual PnL response format.

BRAIN's get_pnl returns:
  {
    "schema": { ... "properties": { "col1": {...}, "col2": {...} } OR "name": [col1, col2, ...] },
    "records": [[date_val, pnl_val], [date_val, pnl_val], ...]
  }

The exact schema shape varies, so do NOT assume column order — map by name. The two
column names to look for are "date" and "pnl". The schema structure seen in BRAIN
responses is typically one of:
  - schema["properties"] being a dict keyed by column name (JSON-Schema style)
  - schema as a list of strings (column name list)
  - schema["name"] being a list of column names

Write a private helper `_parse_pnl_response(pnl_data: dict) -> tuple[list, list]` that:
1. Extracts the column name list from pnl_data["schema"]. Try these in order:
   a. If schema is a list → use it directly
   b. If schema has key "name" and it is a list → use schema["name"]
   c. If schema has key "properties" and it is a dict → use list(schema["properties"].keys())
   d. Fallback: assume first column is date, second is pnl (index 0/1)
2. Finds the index of "date" and "pnl" in the column name list (case-insensitive search).
   If either is not found, fall back to index 0 for date and index 1 for pnl.
3. Reads pnl_data.get("records", []) and extracts [row[date_idx], ...] and [row[pnl_idx], ...].
4. Returns (dates_list, pnls_list). Returns ([], []) on any parsing exception.

Replace lines 205-206 in fetch_and_cache_pnl:
  OLD:  pnls = pnl_data.get("pnls", [])
        dates = pnl_data.get("dates", [])
  NEW:  dates, pnls = _parse_pnl_response(pnl_data)

Keep the log line at 208-209 (it already prints len(pnls)/len(dates) — useful to confirm
the fix works in the next live hunt). The write at line 213 (`{"pnls": pnls, "dates": dates}`)
and everything in load_returns remain unchanged — the on-disk cache format is NOT altered.
  </action>
  <verify>
    <automated>cd /Users/winter.__.kor/quant && ./venv/bin/python -c "
import selfcorr
# Test schema+records format (the actual BRAIN format)
sample = {
    'schema': {'name': ['date', 'pnl']},
    'records': [['2024-01-01', 0.001], ['2024-01-02', -0.002], ['2024-01-03', 0.003]]
}
dates, pnls = selfcorr._parse_pnl_response(sample)
assert len(dates) == 3, f'Expected 3 dates, got {len(dates)}'
assert len(pnls) == 3, f'Expected 3 pnls, got {len(pnls)}'
assert pnls[0] == 0.001, f'Expected 0.001, got {pnls[0]}'
# Test graceful degrade on empty records
empty = {'schema': {'name': ['date', 'pnl']}, 'records': []}
d2, p2 = selfcorr._parse_pnl_response(empty)
assert d2 == [] and p2 == [], f'Expected [], got {d2}, {p2}'
# Test old format still degrades gracefully (returns empty, not crash)
old_fmt = {'pnls': [0.1], 'dates': ['2024-01-01']}
d3, p3 = selfcorr._parse_pnl_response(old_fmt)
# old_fmt has no 'schema' key, records key → should return [], []
assert isinstance(d3, list) and isinstance(p3, list)
print('Task 2 inline checks: PASS')
"
    </automated>
  </verify>
  <done>
_parse_pnl_response correctly extracts dates and pnls from schema+records format.
fetch_and_cache_pnl uses it. Inline verification prints "Task 2 inline checks: PASS".
load_returns and on-disk cache format are unchanged.
  </done>
</task>

<task type="auto">
  <name>Task 3: Regression tests in test_phase4.py</name>
  <files>test_phase4.py</files>
  <action>
Add three regression tests to test_phase4.py. Append them after the existing test
functions — do not remove or modify any existing tests.

--- TEST A: expr_exists delay discrimination ---
def test_expr_exists_delay_aware():
    """db.expr_exists with delay= only matches rows with the same (expression, delay)."""
    conn = db.init_db(':memory:')
    conn.execute("INSERT INTO alphas (alpha_id, expression, delay) VALUES ('A1', 'rank(returns)', 1)")
    conn.commit()
    # delay=0 must NOT match the delay-1 row
    assert db.expr_exists(conn, 'rank(returns)', delay=0) is None
    # delay=1 MUST match
    assert db.expr_exists(conn, 'rank(returns)', delay=1) == 'A1'
    # no delay arg (backward compat) MUST match
    assert db.expr_exists(conn, 'rank(returns)') == 'A1'

--- TEST B: queueable lets delay-0 candidate through when only delay-1 row exists ---
This requires mocking ideator.generate_candidates or calling it with a real in-memory DB
that has delay-1 rows. Use the simplest approach: build a candidate list manually and
call ideator.queueable, verifying the dedup_alpha_id logic directly.

def test_queueable_delay0_passes_when_only_delay1_exists():
    """A candidate with dedup_alpha_id=None passes queueable even if a delay-1 row exists.

    This verifies the full chain: after the fix, generate_candidates sets
    dedup_alpha_id=None for a delay-0 candidate when only a delay-1 row exists.
    """
    conn = db.init_db(':memory:')
    conn.execute("INSERT INTO alphas (alpha_id, expression, delay) VALUES ('A1', 'rank(returns)', 1)")
    conn.commit()

    # Simulate what generate_candidates now does: dedup against delay=0
    expr = 'rank(returns)'
    dedup_id = db.expr_exists(conn, expr, delay=0)  # must be None
    candidate = {
        'expression': expr,
        'archetype': 'momentum',
        'valid': True,
        'validation_reason': '',
        'dedup_alpha_id': dedup_id,
    }
    result = ideator.queueable([candidate])
    assert len(result) == 1, f'Expected 1 queueable candidate, got {len(result)}'
    assert result[0]['expression'] == expr

--- TEST C: fetch_and_cache_pnl parses schema+records correctly ---
Use a MagicMock client that returns a schema+records fixture. Use a tmp_path for the
cache dir and an in-memory sqlite DB.

def test_fetch_and_cache_pnl_schema_records(tmp_path):
    """fetch_and_cache_pnl correctly parses BRAIN's {schema, records} response."""
    import sqlite3
    from unittest.mock import MagicMock

    conn = db.init_db(':memory:')
    # Insert a row so the UPDATE in fetch_and_cache_pnl has something to match
    conn.execute("INSERT INTO alphas (alpha_id, expression) VALUES ('ALPHA1', 'rank(returns)')")
    conn.commit()

    mock_client = MagicMock()
    mock_client.get_pnl.return_value = {
        'schema': {'name': ['date', 'pnl']},
        'records': [
            ['2024-01-02', 0.001],
            ['2024-01-03', -0.002],
            ['2024-01-04', 0.003],
        ]
    }

    cache_dir = str(tmp_path / 'pnl_cache')
    path = selfcorr.fetch_and_cache_pnl(mock_client, 'ALPHA1', conn, pnl_dir=cache_dir)
    assert path is not None, 'Expected a cache path, got None'

    import json, pathlib
    cached = json.loads(pathlib.Path(path).read_text())
    assert len(cached['pnls']) == 3, f"Expected 3 pnls, got {len(cached['pnls'])}"
    assert len(cached['dates']) == 3, f"Expected 3 dates, got {len(cached['dates'])}"
    assert cached['pnls'][0] == 0.001

For imports at top of the test: db, ideator, and selfcorr are already imported in
test_phase4.py. Confirm with a quick grep before appending — add any missing imports.
  </action>
  <verify>
    <automated>cd /Users/winter.__.kor/quant && ./venv/bin/python -m pytest test_phase4.py::test_expr_exists_delay_aware test_phase4.py::test_queueable_delay0_passes_when_only_delay1_exists test_phase4.py::test_fetch_and_cache_pnl_schema_records -v 2>&1 | tail -20</automated>
  </verify>
  <done>
All three new tests pass. No existing test_phase4.py tests are broken
(run ./venv/bin/python -m pytest test_phase4.py -x -q to confirm full suite).
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| BRAIN API response → parser | pnl_data shape is untrusted; column names or record structure could differ |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-kpu-01 | Tampering | _parse_pnl_response column index fallback | accept | Fallback to index 0/1 only when schema is unparseable; returns [], [] on exception — graceful degrade per D-13 |
| T-kpu-02 | Denial of Service | db.expr_exists with delay= | accept | Query uses existing idx_alphas_expr index; adding AND delay=? to a narrow eq-scan is negligible cost |
</threat_model>

<verification>
Full offline verification — no live BRAIN API calls:

1. Task 1 inline check: ./venv/bin/python -c "..." prints "Task 1 inline checks: PASS"
2. Task 2 inline check: ./venv/bin/python -c "..." prints "Task 2 inline checks: PASS"
3. Regression suite: ./venv/bin/python -m pytest test_phase4.py -x -q — all tests pass
4. Backward-compat smoke: grep callers in editor.py / grade.py / find_alphas.py / hunt._is_passable
   still call db.expr_exists without delay arg — confirm no TypeError at import time:
   ./venv/bin/python -c "import db, editor, grade, find_alphas, ideator, selfcorr; print('imports OK')"
</verification>

<success_criteria>
- db.expr_exists(conn, expr, delay=0) returns None when only a delay=1 row exists for that expression
- db.expr_exists(conn, expr) (no delay) behaves identically to today for all existing callers
- ideator.generate_candidates(conn, thesis, delay=0) sets dedup_alpha_id=None for expressions
  present only under delay=1 — those candidates flow through queueable and into /hunt
- selfcorr.fetch_and_cache_pnl writes non-empty pnls/dates when BRAIN returns schema+records
- All three regression tests pass; no existing test_phase4.py tests broken
</success_criteria>

<output>
Create `.planning/quick/260613-kpu-fix-delay-blind-novelty-dedup-and-selfco/260613-kpu-SUMMARY.md` when done.
</output>
