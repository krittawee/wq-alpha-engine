---
phase: quick-260613-rvl
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - grade.py
  - test_phase4.py
autonomous: true
requirements:
  - BUG-5-dedup-delay-blind
must_haves:
  truths:
    - "grade_one with delay=0 does NOT skip an expression that exists only at delay=1"
    - "grade_one with delay=N still skips an expression that already exists at delay=N (non-queued)"
    - "grade_one still detects and inherits queued stubs (NULL-delay) regardless of the grading delay"
    - "All existing grade_one callers (find_alphas.py, hunt.py mutation path) continue to work without changes"
  artifacts:
    - path: "grade.py"
      provides: "delay-aware duplicate skip logic at Step-0"
      contains: "active_settings.get"
    - path: "test_phase4.py"
      provides: "three new offline regression tests for the dedup fix"
  key_links:
    - from: "grade.py Step-0 block"
      to: "db.expr_exists"
      via: "delay-blind call preserved for stub detection"
    - from: "grade.py Step-0 block"
      to: "alphas table"
      via: "SELECT status, parent_alpha_id, delay WHERE alpha_id=existing_id"
---

<objective>
Fix the second delay-blind dedup location in grade.py grade_one (line 160 / Step-0 block). The
current code calls db.expr_exists(conn, expression) with no delay argument, then immediately
returns {"status":"duplicate"} if the found row is non-queued — regardless of whether that row
is at a different delay. This caused 4 of 5 delay-0 candidates to be skipped on 2026-06-13
because they already existed at delay-1.

Purpose: Allow grade_one to simulate a (expression, delay) pair that is genuinely new, even if
the same expression was graded at a different delay previously. Queued-stub inheritance must be
preserved without change.

Output: Patched grade.py (Step-0 block only) + three new offline tests appended to test_phase4.py.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/ROADMAP.md
@.planning/STATE.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Patch grade.py Step-0 to compare delays before declaring duplicate</name>
  <files>grade.py</files>
  <action>
Apply Option A from the diagnosis. The change is confined to the Step-0 block (lines 157-172).
Do NOT touch any other part of grade_one.

Compute effective delay before the block:

    effective_delay = active_settings.get("delay", delay)

This is already available from lines 153-155; derive it after active_settings is set and before
Step 0.

Change the Step-0 SELECT at line 163-165 to also fetch the row's delay column:

    row = conn.execute(
        "SELECT status, parent_alpha_id, delay FROM alphas WHERE alpha_id=?",
        (existing_id,)
    ).fetchone()

Update the non-queued branch (line 166-168) to only return "duplicate" when the stored row's
delay matches the effective delay. If the stored delay differs, fall through as if no existing
row was found:

    if row is None or row[0] != "queued":
        stored_delay = row[2] if row is not None else None
        if stored_delay == effective_delay:
            print(f"[grade] skip duplicate: {expression[:40]}")
            return {"expression": expression, "status": "duplicate", "alpha_id": existing_id}
        # Different delay — treat as a genuinely new (expression, delay) pair; fall through
        existing_id = None   # clear so stub_id_to_replace is not set

The call to db.expr_exists at line 160 remains delay-BLIND. This is intentional: stubs have
NULL delay (upsert in editor.py:297-304 never sets delay), so a delay-aware query would never
find them. The delay-blind call finds ANY matching row (stub or not); the delay comparison
only applies when the row is non-queued.

Edge case (queued stub + different-delay non-queued row for same expression): db.expr_exists
uses LIMIT 1 — it returns whichever row the SQLite index returns first. If it returns the
non-queued different-delay row, the new code falls through and grades as novel, which is
acceptable. The orphaned stub will be cleaned up on the next mutation cycle. This is the
simplest correct behavior and does not require a second query for the edge case.

Preserve: the `existing_id = None` assignment means `stub_id_to_replace` stays None, so
grade_one will INSERT a new row rather than replace. This is correct for a genuinely new
(expression, delay) pair.

Do NOT change: the D-03 coercion warn+discard block, the 401 propagation, or any code outside
the Step-0 block.
  </action>
  <verify>
    <automated>cd /Users/winter.__.kor/quant && ./venv/bin/python -c "import grade; print('grade imports OK')"</automated>
  </verify>
  <done>grade.py imports without error; Step-0 block contains the delay comparison logic; the
  db.expr_exists call at the top of Step-0 remains delay-blind.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Add three offline regression tests to test_phase4.py</name>
  <files>test_phase4.py</files>
  <behavior>
    - test (a): grade_one(delay=0, expression=E) where E exists in DB at delay=1 (non-queued)
      must NOT return status='duplicate'; _simulate_to_alpha must be called.
    - test (b): grade_one(delay=1, expression=E) where E exists in DB at delay=1 (non-queued)
      MUST return status='duplicate' (regression guard — don't over-loosen).
    - test (c): grade_one(delay=0, expression=E) where E exists in DB as a queued stub (delay NULL)
      must NOT return status='duplicate'; parent_alpha_id and stub_id_to_replace must be inherited
      (i.e., grade_one proceeds past Step-0 and calls _simulate_to_alpha).
  </behavior>
  <action>
Append three new test functions to the END of test_phase4.py (after the last existing test).
Do not modify any existing test.

All three tests must be fully offline: mock grade._simulate_to_alpha (and any downstream
network/BRAIN calls) using unittest.mock.patch so no HTTP is made.

Use the same mock pattern already established in test_grade_records_brain_actual_settings
(lines 500-590): create an in-memory DB with db.init_db(":memory:"), insert seed rows
directly with db.upsert_alpha, then call grade.grade_one with a MagicMock client, patching
validate.validate to return (True, None), selfcorr helpers, and the simulate path.

The simplest mock surface for all three tests is to patch "grade._simulate_to_alpha" to return
a canned result dict (e.g. {"status": "low_quality", "alpha_id": "FAKE01"}) so grade_one
returns without hitting BRAIN. This avoids mocking the full client.simulate chain.

Test (a) — cross-delay not duplicate:
  - Seed DB: upsert_alpha with expression="rank(close)", delay=1, status="graded", alpha_id="OLD01"
  - Call grade.grade_one(client, conn, "rank(close)", "run1", delay=0)
  - Assert result["status"] != "duplicate"
  - Assert mock_simulate was called (patch target "grade._simulate_to_alpha")

Test (b) — same delay IS duplicate:
  - Seed DB: upsert_alpha with expression="rank(close)", delay=1, status="graded", alpha_id="OLD01"
  - Call grade.grade_one(client, conn, "rank(close)", "run1", delay=1)
  - Assert result["status"] == "duplicate"
  - Assert result["alpha_id"] == "OLD01"

Test (c) — queued stub inherited regardless of delay:
  - Seed DB: upsert_alpha with expression="rank(volume)", status="queued", alpha_id="stub-abc12345",
    parent_alpha_id="PARENT01" (no delay set / delay=None)
  - Call grade.grade_one(client, conn, "rank(volume)", "run1", delay=0)
  - Assert result["status"] != "duplicate"
  - Assert mock_simulate was called
  - Capture what grade_one passed to _simulate_to_alpha; the stub_id_to_replace used internally
    can be verified indirectly by asserting the DB row for "stub-abc12345" is updated (or replaced)
    after the call, OR simply assert the alpha did NOT short-circuit as duplicate and that
    parent_alpha_id in the result equals "PARENT01".

Name the functions:
  test_grade_dedup_cross_delay_not_duplicate
  test_grade_dedup_same_delay_is_duplicate
  test_grade_dedup_queued_stub_inherited

Each must pass in isolation with ./venv/bin/python -m pytest test_phase4.py::test_grade_dedup_cross_delay_not_duplicate -x (etc.).

IMPORTANT: check whether grade._simulate_to_alpha exists as an internal function before
choosing the patch target. If grade_one calls the simulate logic inline (no separate
_simulate_to_alpha function), patch "grade.grade_one" is NOT useful — instead patch
"grade.Brain.simulate" or the client.simulate attribute on the mock client object to raise a
sentinel exception, then assert the exception propagated (proving grade_one reached the
simulate step). The exact patch strategy must match what grade.py actually does at Step 2.
Inspect grade.py lines 189-230 before writing the mock.
  </action>
  <verify>
    <automated>cd /Users/winter.__.kor/quant && ./venv/bin/python -m pytest test_phase4.py::test_grade_dedup_cross_delay_not_duplicate test_phase4.py::test_grade_dedup_same_delay_is_duplicate test_phase4.py::test_grade_dedup_queued_stub_inherited -v 2>&1 | tail -20</automated>
  </verify>
  <done>All three new tests pass. All pre-existing tests in test_phase4.py continue to pass
  (run with ./venv/bin/python -m pytest test_phase4.py -x to confirm no regressions).</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| grade_one → SQLite alphas table | expression and delay values come from internal pipeline; low external exposure |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-rvl-01 | Tampering | grade.py Step-0 delay comparison | mitigate | Compare effective_delay (from active_settings) not raw delay arg, so callers passing a full settings dict are handled correctly |
| T-rvl-02 | Denial of Service | db.expr_exists LIMIT 1 nondeterminism | accept | Edge case (stub + different-delay row) results in a novel sim, not data loss; stub cleanup on next cycle is acceptable |
</threat_model>

<verification>
Full regression run (must stay green):

    cd /Users/winter.__.kor/quant && ./venv/bin/python -m pytest test_phase4.py -x -q

Targeted new tests:

    ./venv/bin/python -m pytest test_phase4.py::test_grade_dedup_cross_delay_not_duplicate test_phase4.py::test_grade_dedup_same_delay_is_duplicate test_phase4.py::test_grade_dedup_queued_stub_inherited -v

Caller compatibility check (no changes needed, but verify no import errors):

    ./venv/bin/python -c "import find_alphas, hunt, grade; print('all callers import OK')"
</verification>

<success_criteria>
- grade.py Step-0 block compares stored delay to effective delay before returning "duplicate"
- db.expr_exists call at line 160 remains delay-blind (stubs have NULL delay)
- Three new offline tests pass: cross-delay not duplicate, same-delay is duplicate, queued stub inherited
- Full test_phase4.py suite passes with no regressions
- find_alphas.py and hunt.py import without error (no signature changes to grade_one)
</success_criteria>

<output>
Create `.planning/quick/260613-rvl-make-grade-py-grade-one-dedup-delay-awar/260613-rvl-SUMMARY.md` when done.
</output>
