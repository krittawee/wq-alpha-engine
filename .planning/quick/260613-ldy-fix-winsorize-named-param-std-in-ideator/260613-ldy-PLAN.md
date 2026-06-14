---
phase: quick-260613-ldy
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - validate.py
  - ideator.py
  - grade.py
  - test_phase4.py
autonomous: true
requirements: [BUG-WINSORIZE-NAMED-PARAM, BUG-GRADE-ERROR-SURFACE]
must_haves:
  truths:
    - "winsorize(x, std=4) passes validate.validate without reporting 'std' as unknown data field"
    - "ideator emits winsorize(..., std=N) in every expression containing winsorize"
    - "grade._simulate_to_alpha raises with BRAIN's real error message when sim returns ERROR, not 'transient throttle/queue'"
    - "genuine unknown data fields still fail validation"
    - "genuine throttle case (alpha_id None, no _result ERROR) still retries"
  artifacts:
    - path: validate.py
      provides: "named-arg key exclusion from bare_field_tokens"
      contains: "named_arg_keys"
    - path: ideator.py
      provides: "winsorize with std= named param in all emission sites"
      contains: "std="
    - path: grade.py
      provides: "BRAIN ERROR inspection before retry loop"
      contains: "BRAIN sim ERROR"
    - path: test_phase4.py
      provides: "three new offline test cases"
      contains: "test_validate_winsorize_named_param"
  key_links:
    - from: ideator.py
      to: validate.py
      via: "validate.validate(conn, expr) called on every generated candidate"
      pattern: "validate\\.validate"
    - from: grade.py
      to: "sim._result"
      via: "getattr(sim, '_result', None) inspected after wait()"
      pattern: "_result"
---

<objective>
Fix three interconnected bugs that caused every winsorize-containing expression to fail
BRAIN simulation with "Invalid number of inputs : 2, should be exactly 1 input(s)".

Root cause chain:
1. validate.py treated `std` in `winsorize(x, std=4)` as an unknown data-field token,
   so prior code emitted the positional form `winsorize(x, 4)` as a workaround.
2. BRAIN's operator catalog defines winsorize as `winsorize(x, std=4)` — `std` is a
   NAMED parameter, not a second positional input. BRAIN rejects the positional form.
3. When BRAIN returned status=ERROR, grade.py masked it as "transient throttle/queue"
   and wasted two retry attempts before raising an uninformative message.

This plan fixes all three root causes and adds offline tests for each.

STATE.md note: The old `_SKELETONS` comment "positional arg avoids 'std' being parsed
as a field token" and the decision recording that workaround are REVERSED by this plan.
The executor should NOT edit STATE.md decisions — flag for orchestrator to update the
decision log after execution.

Purpose: Unblock the hunt loop. All winsorize-family archetypes (value_garp, quality)
currently fail at BRAIN sim time; they will pass once the named form is emitted and
validate accepts it.

Output: validate.py, ideator.py, grade.py patched; test_phase4.py extended with 3 tests.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Fix validate.py — exclude named-argument keys from data-field validation</name>
  <files>validate.py, test_phase4.py</files>
  <action>
In validate.py, after the `assigned_vars` extraction (line 63-65) and before the
`bare_field_tokens` set comprehension (line 70-73), add a named-argument key exclusion
step.

Named-argument keys are tokens that appear in the pattern `\b([A-Za-z_]\w*)\s*=(?!=)` —
a word token immediately followed by a single `=` that is NOT `==`. This is distinct from
the existing `assigned_vars` pattern, which anchors on `^` (MULTILINE) to catch
statement-level assignments like `vol = rank(...)`. Named args are the in-paren
`keyword=value` case.

Add after line 65:

    # Named-argument keys (e.g. std=4, dense=false) are not data-field references.
    # Pattern: word token immediately followed by = but NOT ==.
    named_arg_keys: set[str] = set(
        re.findall(r'\b([A-Za-z_]\w*)\s*=(?!=)', expression)
    )

Then update the `bare_field_tokens` set comprehension to also exclude `named_arg_keys`:

    bare_field_tokens: set[str] = {
        t for t in all_tokens
        if t not in operator_tokens
        and t not in _EXCLUSIONS
        and t not in assigned_vars
        and t not in named_arg_keys
    }

Do NOT touch assigned_vars logic. Do NOT touch operator_tokens logic. Do NOT change
anything else in validate.py.

After the validate.py change, append the following test class to test_phase4.py
(do not modify any existing test — add at the bottom of the file):

    class TestValidateNamedArgKeys(unittest.TestCase):
        """FIX-1: validate.py must not flag named-param keys as unknown data fields."""

        def setUp(self):
            import sqlite3
            self.conn = sqlite3.connect(":memory:")
            self.conn.execute(
                "CREATE TABLE operators (name TEXT PRIMARY KEY)"
            )
            self.conn.execute(
                "CREATE TABLE datafields (id TEXT PRIMARY KEY)"
            )
            # Seed the operators and data fields used in winsorize expressions
            for op in ("winsorize", "rank", "divide", "group_neutralize",
                       "ts_decay_linear"):
                self.conn.execute("INSERT INTO operators VALUES (?)", (op,))
            for field in ("close", "bookvalue_ps"):
                self.conn.execute("INSERT INTO datafields VALUES (?)", (field,))
            self.conn.commit()

        def tearDown(self):
            self.conn.close()

        def test_winsorize_named_std_passes(self):
            """winsorize(x, std=4) must validate as True — std is a named param."""
            import validate
            ok, reason = validate.validate(
                self.conn,
                "winsorize(rank(divide(bookvalue_ps, close)), std=4)"
            )
            self.assertTrue(ok, f"Expected valid but got: {reason}")
            self.assertEqual(reason, "")

        def test_std_not_reported_as_unknown_field(self):
            """validate must NOT report 'unknown data field: std'."""
            import validate
            ok, reason = validate.validate(
                self.conn,
                "winsorize(close, std=4)"
            )
            self.assertNotIn("std", reason,
                f"'std' should not appear in rejection reason, got: {reason}")

        def test_genuine_unknown_field_still_fails(self):
            """A genuinely unknown field must still fail validation."""
            import validate
            ok, reason = validate.validate(
                self.conn,
                "winsorize(notafield, std=4)"
            )
            self.assertFalse(ok)
            self.assertIn("notafield", reason)

        def test_dense_named_param_ts_decay_linear(self):
            """ts_decay_linear dense=false must not flag 'dense' or 'false' as fields."""
            import validate
            ok, reason = validate.validate(
                self.conn,
                "ts_decay_linear(close, 5, dense=false)"
            )
            # 'false' is not in _EXCLUSIONS so may be flagged — only assert 'dense' is not
            self.assertNotIn("unknown data field: dense", reason)

Ensure the test file imports `unittest` at the top (it already does — do not add a
duplicate import).
  </action>
  <verify>
    <automated>cd /Users/winter.__.kor/quant && ./venv/bin/python -m pytest test_phase4.py::TestValidateNamedArgKeys -v 2>&1 | tail -20</automated>
  </verify>
  <done>All 4 tests in TestValidateNamedArgKeys pass. validate.validate("winsorize(rank(divide(bookvalue_ps, close)), std=4)") returns (True, "") with a seeded in-memory DB. A genuine unknown field still returns (False, "unknown data field: notafield").</done>
</task>

<task type="auto">
  <name>Task 2: Fix ideator.py — emit winsorize with std= named param everywhere</name>
  <files>ideator.py, test_phase4.py</files>
  <action>
In ideator.py, change every string that emits `winsorize(...)` with a bare positional
numeric argument to use `std=N` instead. There are five emission sites to fix:

SITE 1 — _SKELETONS dict, "value_garp" entry (line 39):
  OLD: "group_neutralize(winsorize(rank(divide(bookvalue_ps, close)), 4), industry)"
  NEW: "group_neutralize(winsorize(rank(divide(bookvalue_ps, close)), std=4), industry)"

SITE 2 — _make_value_garp_variants, subindustry variant (line 144):
  OLD: "group_neutralize(winsorize(rank(divide(bookvalue_ps, close)), 4), subindustry)"
  NEW: "group_neutralize(winsorize(rank(divide(bookvalue_ps, close)), std=4), subindustry)"

SITE 3 — _make_value_garp_variants, EPS ratio variant (line 156):
  OLD: "group_neutralize(winsorize(rank(divide(actual_eps_value_quarterly, close)), 4), industry)"
  NEW: "group_neutralize(winsorize(rank(divide(actual_eps_value_quarterly, close)), std=4), industry)"

SITE 4 — _make_quality_variants, winsorize wrapper (line 180):
  OLD: "group_neutralize(winsorize(rank(divide(operating_income, assets)), 4), industry)"
  NEW: "group_neutralize(winsorize(rank(divide(operating_income, assets)), std=4), industry)"

SITE 5 — _SKELETONS comment (line 38): update the NOTE comment to say:
  "# NOTE: winsorize uses std= named param (BRAIN catalog: winsorize(x, std=4))."
  Remove the old comment on line 32 that says positional arg avoids std being parsed.

Do NOT change any other operators (group_neutralize, ts_decay_linear, etc.). Do NOT
change numeric literals that are positional arguments to other operators.

After the ideator.py changes, append the following test class to test_phase4.py:

    class TestIdeatorWinsorizeNamedParam(unittest.TestCase):
        """FIX-2: ideator must emit winsorize(..., std=N), never winsorize(..., N)."""

        def setUp(self):
            import sqlite3
            import db
            self.conn = sqlite3.connect(":memory:")
            db.init_db(self.conn)
            # Seed minimal catalog so generate_candidates can run
            ops = [
                "winsorize", "rank", "divide", "group_neutralize", "group_zscore",
                "ts_decay_linear", "ts_delta", "ts_delay", "ts_mean", "ts_std_dev",
                "ts_zscore", "ts_corr", "reverse", "abs", "trade_when", "greater",
                "vec_avg", "zscore",
            ]
            fields = [
                "close", "bookvalue_ps", "operating_income", "assets",
                "actual_eps_value_quarterly", "industry", "subindustry", "sector",
                "returns", "volume", "vwap", "adv20", "cap", "cashflow_op",
                "actual_sales_value_annual", "adj_net_income_avg", "debt_lt",
                "nws12_afterhsz_sl", "mdl177_garpanalystmodel_qgp_vfpriceratio",
            ]
            for op in ops:
                self.conn.execute(
                    "INSERT OR IGNORE INTO operators (name) VALUES (?)", (op,)
                )
            for f in fields:
                self.conn.execute(
                    "INSERT OR IGNORE INTO datafields (id) VALUES (?)", (f,)
                )
            self.conn.commit()

        def tearDown(self):
            self.conn.close()

        def _get_winsorize_exprs(self, archetype):
            import researcher
            import ideator
            thesis = {
                "archetype": archetype,
                "source_operators": [
                    "winsorize", "rank", "divide", "group_neutralize", "group_zscore",
                ],
                "source_datafields": [
                    "close", "bookvalue_ps", "operating_income", "assets",
                    "actual_eps_value_quarterly", "industry", "subindustry",
                ],
            }
            candidates = ideator.generate_candidates(self.conn, thesis)
            return [
                c["expression"] for c in candidates
                if "winsorize" in c["expression"]
            ]

        def test_value_garp_winsorize_uses_named_param(self):
            """All value_garp expressions containing winsorize must use std=."""
            winsorize_exprs = self._get_winsorize_exprs("value_garp")
            self.assertTrue(len(winsorize_exprs) > 0,
                "Expected at least one winsorize expression in value_garp")
            for expr in winsorize_exprs:
                self.assertIn("std=", expr,
                    f"winsorize expr missing std=: {expr}")
                # Ensure old positional form is gone: no bare comma-number after the inner expr
                import re
                # Matches winsorize(<something>, <digit>) — the BAD old form
                bad_pattern = re.compile(r'winsorize\([^)]+\),\s*\d+\)')
                self.assertIsNone(bad_pattern.search(expr),
                    f"Old positional winsorize form detected: {expr}")

        def test_quality_winsorize_uses_named_param(self):
            """Quality archetype winsorize wrapper must use std=."""
            winsorize_exprs = self._get_winsorize_exprs("quality")
            for expr in winsorize_exprs:
                self.assertIn("std=", expr,
                    f"winsorize expr missing std=: {expr}")

        def test_winsorize_exprs_pass_validation(self):
            """All emitted winsorize expressions must pass validate.validate."""
            import validate
            for archetype in ("value_garp", "quality"):
                for expr in self._get_winsorize_exprs(archetype):
                    ok, reason = validate.validate(self.conn, expr)
                    self.assertTrue(ok,
                        f"Validation failed for [{archetype}] {expr!r}: {reason}")

After appending, verify the full new test suite runs green.
  </action>
  <verify>
    <automated>cd /Users/winter.__.kor/quant && ./venv/bin/python -m pytest test_phase4.py::TestIdeatorWinsorizeNamedParam -v 2>&1 | tail -20</automated>
  </verify>
  <done>All 3 tests in TestIdeatorWinsorizeNamedParam pass. Every winsorize-containing expression emitted by value_garp and quality archetypes contains "std=" and passes validate.validate. No existing test_phase4.py tests are broken (run full suite to confirm).</done>
</task>

<task type="auto">
  <name>Task 3: Fix grade.py — surface BRAIN sim ERROR instead of mislabeling as throttle</name>
  <files>grade.py, test_phase4.py</files>
  <action>
In grade.py, inside _simulate_to_alpha (lines 63-94), change the handling of the
falsy-alpha_id case (currently line 83) to inspect sim._result before setting last_err
and deciding whether to retry.

Replace the current block:

    if getattr(sim, "alpha_id", None):
        return sim, sim.get_alpha()
    last_err = "wait() returned no alpha_id (transient throttle/queue)"

With:

    if getattr(sim, "alpha_id", None):
        return sim, sim.get_alpha()
    # Inspect _result to distinguish a genuine BRAIN expression ERROR from a
    # transient throttle/queue situation (where _result is absent or has no status).
    _result = getattr(sim, "_result", None)
    if isinstance(_result, dict) and _result.get("status") == "ERROR":
        _msg = _result.get("message", "unknown error")
        raise RuntimeError(
            f"BRAIN sim ERROR (expression rejected): {_msg}"
        )
    last_err = "wait() returned no alpha_id (transient throttle/queue)"

Key behaviors preserved:
- 401 HTTPError still propagates immediately (existing except block unchanged).
- Genuine throttle case (alpha_id=None, _result absent or not ERROR) still sets
  last_err and continues the retry loop with backoff.
- A genuine expression ERROR raises immediately without wasting retry attempts —
  BRAIN will not accept the expression on retry; retrying is wasteful.
- The final raise at line 92 ("simulation failed after N attempts: {last_err}") is
  unchanged — it handles the throttle case.

Do NOT change the `active_settings`, `attempts`, `time.sleep`, or any other part of
_simulate_to_alpha. Do NOT touch grade_one or grade_many.

After the grade.py change, append the following test class to test_phase4.py:

    class TestGradeSurfacesBrainError(unittest.TestCase):
        """FIX-3: _simulate_to_alpha must raise with BRAIN's real error message."""

        def _make_fake_sim(self, alpha_id=None, result=None):
            """Build a minimal fake SimulationResult object."""
            class FakeSim:
                pass
            sim = FakeSim()
            sim.alpha_id = alpha_id
            if result is not None:
                sim._result = result
            # no _result attr when result is None — simulates missing attribute
            return sim

        def test_brain_error_raises_with_real_message(self):
            """When BRAIN returns status=ERROR, RuntimeError must contain the message."""
            import grade
            from unittest.mock import MagicMock, patch

            fake_sim = self._make_fake_sim(
                alpha_id=None,
                result={"status": "ERROR", "message": "Invalid number of inputs : 2, should be exactly 1 input(s)."}
            )

            mock_client = MagicMock()
            mock_client.simulate.return_value = fake_sim
            fake_sim.wait = MagicMock(return_value=None)

            with self.assertRaises(RuntimeError) as ctx:
                grade._simulate_to_alpha(mock_client, "winsorize(close, 4)", attempts=3)

            err_msg = str(ctx.exception)
            self.assertIn("Invalid number of inputs", err_msg,
                f"Expected BRAIN error message in exception, got: {err_msg}")
            self.assertNotIn("transient throttle/queue", err_msg,
                "Must NOT say throttle when BRAIN returned an ERROR status")

        def test_brain_error_does_not_retry(self):
            """A genuine BRAIN ERROR must raise immediately — no retry wasted."""
            import grade
            from unittest.mock import MagicMock

            fake_sim = self._make_fake_sim(
                alpha_id=None,
                result={"status": "ERROR", "message": "bad expression"}
            )

            mock_client = MagicMock()
            mock_client.simulate.return_value = fake_sim
            fake_sim.wait = MagicMock(return_value=None)

            with self.assertRaises(RuntimeError):
                grade._simulate_to_alpha(mock_client, "bad_expr", attempts=3)

            # simulate() should have been called exactly once — no retries
            self.assertEqual(mock_client.simulate.call_count, 1,
                "simulate() was called more than once — ERROR should not retry")

        def test_throttle_still_retries(self):
            """When alpha_id is None and _result has no ERROR status, retries still happen."""
            import grade
            from unittest.mock import MagicMock

            # Fake sim: no alpha_id, no _result at all (pure throttle scenario)
            fake_sim = self._make_fake_sim(alpha_id=None, result=None)
            mock_client = MagicMock()
            mock_client.simulate.return_value = fake_sim
            fake_sim.wait = MagicMock(return_value=None)

            with self.assertRaises(RuntimeError) as ctx:
                grade._simulate_to_alpha(mock_client, "rank(close)", attempts=2)

            # Should have retried (simulate called twice for attempts=2)
            self.assertEqual(mock_client.simulate.call_count, 2,
                "Expected 2 simulate() calls for throttle-retry path")
            self.assertIn("transient throttle/queue", str(ctx.exception))

The test_throttle_still_retries test patches out time.sleep to avoid 5s waits.
Add `@patch('time.sleep')` decorator from unittest.mock to that test method and
add the `mock_sleep` parameter. Import `patch` from unittest.mock at the top of
the test class or inline.

No live BRAIN auth or sim calls are made in any of these tests.
  </action>
  <verify>
    <automated>cd /Users/winter.__.kor/quant && ./venv/bin/python -m pytest test_phase4.py::TestGradeSurfacesBrainError -v 2>&1 | tail -20</automated>
  </verify>
  <done>All 3 tests in TestGradeSurfacesBrainError pass. _simulate_to_alpha raises RuntimeError containing "Invalid number of inputs" (not "transient throttle/queue") when given a BRAIN ERROR result. simulate() is called exactly once for ERROR (no wasted retries). Throttle path (no _result) still retries and surfaces "transient throttle/queue". No live BRAIN calls made.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| BRAIN API response → grade.py | sim._result is a dict from external BRAIN API; must not be trusted blindly — only inspect known keys (status, message) |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-ldy-01 | Tampering | validate.py named_arg_keys regex | accept | Pattern is narrow (word=non-=); cannot be injected via expression strings that reach validate() since expressions are internally composed, not user-supplied at runtime |
| T-ldy-02 | Information Disclosure | grade.py error surface | accept | BRAIN error messages are operational (operator names, counts); no PII or secrets; surfacing them aids debugging |
| T-ldy-03 | Denial of Service | grade.py immediate raise on ERROR | accept | Prevents wasted retry cycles; legitimate throttle path unchanged |
| T-ldy-SC | Tampering | npm/pip/cargo installs | accept | No new package installs in this task; only stdlib (re, unittest.mock) used |
</threat_model>

<verification>
Full regression after all three tasks:

    cd /Users/winter.__.kor/quant && ./venv/bin/python -m pytest test_phase4.py -v 2>&1 | tail -30

All pre-existing tests must remain green. Three new test classes must all pass:
- TestValidateNamedArgKeys (4 tests)
- TestIdeatorWinsorizeNamedParam (3 tests)
- TestGradeSurfacesBrainError (3 tests)

Manual smoke check (optional, offline):

    ./venv/bin/python -c "
    import sqlite3, validate
    conn = sqlite3.connect(':memory:')
    conn.execute('CREATE TABLE operators (name TEXT PRIMARY KEY)')
    conn.execute('CREATE TABLE datafields (id TEXT PRIMARY KEY)')
    for op in ('winsorize','rank','divide','group_neutralize'):
        conn.execute('INSERT INTO operators VALUES (?)', (op,))
    for f in ('close','bookvalue_ps'):
        conn.execute('INSERT INTO datafields VALUES (?)', (f,))
    conn.commit()
    print(validate.validate(conn, 'group_neutralize(winsorize(rank(divide(bookvalue_ps, close)), std=4), industry)'))
    "
Should print: (False, 'unknown data field: industry') — industry is not seeded as a field,
which is correct. With industry seeded it would print (True, '').
</verification>

<success_criteria>
1. validate.validate("winsorize(x, std=4)", ...) returns (True, "") when x and operator
   are seeded — std is never flagged as unknown data field.
2. Every winsorize-containing expression in the ideator's value_garp and quality
   archetypes contains "std=" — no positional bare-integer second argument.
3. grade._simulate_to_alpha raises RuntimeError with BRAIN's real message
   (not "transient throttle/queue") when sim._result indicates status=ERROR, and
   does so without retrying.
4. All pre-existing test_phase4.py tests remain green.
5. No live BRAIN authentication or simulation is required to run any of the new tests.
</success_criteria>

<output>
Create `.planning/quick/260613-ldy-fix-winsorize-named-param-std-in-ideator/260613-ldy-SUMMARY.md` when done.

Note for orchestrator: STATE.md contains a decision recording "winsorize uses positional
numeric arg — std= keyword causes 'std' to be parsed as unknown data-field token by
validate.py". This plan REVERSES that workaround. After execution is confirmed green,
update STATE.md to replace that decision with: "winsorize uses std= named param per
BRAIN catalog definition; validate.py excludes named-arg keys from data-field checks."
</output>
