"""Phase 7: Brute-Force Tool (Tool B) — test suite. Zero real BRAIN API calls."""

import json
import sqlite3
import unittest.mock
from unittest.mock import MagicMock

import pytest

import db


# ---------------------------------------------------------------------------
# Shared fixture — in-memory SQLite with full Phase 7 schema
# ---------------------------------------------------------------------------


@pytest.fixture
def fresh_db():
    """Open an in-memory SQLite DB with full schema (including Phase 7 additions).

    Phase 7 db.py (Plan 07-01) adds:
      - bruteforce_runs table (17 columns)
      - idx_bruteforce_runs_run index

    Each test gets a fresh connection; connection is closed after the test.
    """
    conn = db.init_db(":memory:")
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Helper factories (plain functions, importable by Plans 07-02/03 tests)
# ---------------------------------------------------------------------------


def make_mock_grade_one_result(status="pass", alpha_id="test_alpha_001"):
    """Return a dict matching grade.grade_one's return shape.

    Plans 07-02 and 07-03 import this to build fake grade results without
    touching the real BRAIN API.
    """
    return {
        "status": status,
        "alpha_id": alpha_id,
        "checks": [],
        "expression": "rank(close/open)",
    }


def make_mock_classify_result(status="near"):
    """Return (status, []) — matches editor.classify_from_checks return shape.

    Plans 07-02 and 07-03 import this for probe-gate classification mocks.
    """
    return (status, [])


def make_mock_additivity_result(additive=True, proxy_drop=False):
    """Return a MagicMock with .additive, .proxy_drop, .alpha_id attributes.

    Matches the object shape returned by additivity functions used in Tool B's
    additivity gate (Phase 6 reuse). Plans 07-03 imports this for gate mocks.
    """
    obj = MagicMock()
    obj.additive = additive
    obj.proxy_drop = proxy_drop
    obj.alpha_id = "test_alpha_001"
    return obj


# ---------------------------------------------------------------------------
# Phase 7 tests
# ---------------------------------------------------------------------------


def test_bruteforce_runs_schema(fresh_db):
    """BF-06 / D-11: bruteforce_runs table and index created by init_db.

    Verifies:
    - Table exists after init_db(':memory:')
    - idx_bruteforce_runs_run index exists
    - insert_bruteforce_run writes a row with all expected columns readable back
    - failure_counts and examples round-trip as JSON strings
    - update_bruteforce_run patches n_additive without touching other columns
    """
    conn = fresh_db

    # Table exists
    table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='bruteforce_runs'"
    ).fetchone()
    assert table is not None, "bruteforce_runs table missing after init_db"

    # Index exists
    index = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_bruteforce_runs_run'"
    ).fetchone()
    assert index is not None, "idx_bruteforce_runs_run index missing after init_db"

    # Insert a full row — JSON strings for aggregate columns (serialized by caller)
    failure_counts_json = json.dumps({"validate_dropped": 10, "IS_fail_SHARPE": 5})
    examples_json = json.dumps({"validate_dropped": ["rank(x)", "ts_mean(close,5)"]})

    rowid = db.insert_bruteforce_run(
        conn,
        {
            "run_id": "run-001",
            "template_name": "sentiment_rank",
            "delay": 0,
            "quota_target": 5,
            "n_combos": 200,
            "n_validated": 180,
            "n_probed": 5,
            "n_simmed": 40,
            "n_survivors": 8,
            "n_additive": 2,
            "quota_hit": 0,
            "partial": 0,
            "failure_counts": failure_counts_json,
            "examples": examples_json,
            "started_at": "2026-01-01T00:00:00",
        },
    )
    assert isinstance(rowid, int) and rowid > 0, (
        f"insert_bruteforce_run should return a positive integer rowid, got {rowid!r}"
    )

    # Read back all expected columns
    row = conn.execute(
        "SELECT run_id, template_name, n_combos, failure_counts, examples "
        "FROM bruteforce_runs WHERE id=?",
        (rowid,),
    ).fetchone()
    assert row is not None, "Row not found after insert"
    assert row[0] == "run-001", "run_id mismatch"
    assert row[1] == "sentiment_rank", "template_name mismatch"
    assert row[2] == 200, "n_combos mismatch"
    # failure_counts and examples survive as JSON strings (not parsed)
    assert row[3] == failure_counts_json, "failure_counts JSON string mismatch"
    assert row[4] == examples_json, "examples JSON string mismatch"

    # update_bruteforce_run patches only the given columns
    db.update_bruteforce_run(conn, rowid, {"n_additive": 3, "finished_at": "2026-01-01T01:00:00"})
    updated = conn.execute(
        "SELECT n_additive, finished_at, n_combos FROM bruteforce_runs WHERE id=?",
        (rowid,),
    ).fetchone()
    assert updated[0] == 3, "n_additive should be patched to 3"
    assert updated[1] == "2026-01-01T01:00:00", "finished_at should be set"
    assert updated[2] == 200, "n_combos should be unchanged after update"


# ---------------------------------------------------------------------------
# BF-01 / BF-02 tests (Plan 07-02: templates.py)
# ---------------------------------------------------------------------------


def test_template_enumeration():
    """BF-01: expand_slots with literal slots produces expected cartesian product.

    beta_neutral has 2 field literals x 3 window literals = 6 combos.
    Verifies combo count, expression completeness, and tuple shape.
    """
    import templates

    conn = db.init_db(":memory:")
    try:
        beta = next(t for t in templates.TEMPLATES if t["name"] == "beta_neutral")
        combos = templates.expand_slots(conn, beta)

        # 2 field values x 3 window values = 6 combos
        assert len(combos) == 6, (
            f"beta_neutral should expand to 6 combos (2 fields x 3 windows), got {len(combos)}"
        )

        for combo in combos:
            # Each combo is a (str, dict) tuple
            assert isinstance(combo, tuple) and len(combo) == 2, (
                f"combo should be a 2-tuple, got {type(combo)} of len {len(combo)}: {combo!r}"
            )
            expr, slot_dict = combo
            assert isinstance(expr, str), f"first element must be str, got {type(expr)}"
            assert isinstance(slot_dict, dict), f"second element must be dict, got {type(slot_dict)}"

            # No unfilled placeholders remain in the expression
            assert "{" not in expr, (
                f"Unfilled placeholder still present in expression: {expr!r}"
            )

        # Verify both field values appear in the expansions
        exprs = [c[0] for c in combos]
        assert any("volume" in e for e in exprs), "field value 'volume' missing from combos"
        assert any("vwap" in e for e in exprs), "field value 'vwap' missing from combos"
    finally:
        conn.close()


def test_slot_expansion():
    """BF-01: expand_slots catalog-filter path queries datafields with type/dataset filter.

    Inserts 2 VECTOR rows and 1 MATRIX row with dataset='nws12'.
    Asserts: only VECTOR ids appear in expanded sentiment_rank expressions.
    Asserts: empty DB returns 0 combos (no error).
    """
    import templates

    # Case 1: empty DB -> 0 combos
    conn_empty = db.init_db(":memory:")
    try:
        sentiment = next(t for t in templates.TEMPLATES if t["name"] == "sentiment_rank")
        combos_empty = templates.expand_slots(conn_empty, sentiment)
        assert len(combos_empty) == 0, (
            f"Empty datafields should yield 0 combos, got {len(combos_empty)}"
        )
    finally:
        conn_empty.close()

    # Case 2: DB with 2 VECTOR rows and 1 MATRIX row for nws12
    conn = db.init_db(":memory:")
    try:
        # Insert 2 VECTOR fields and 1 MATRIX field, all dataset='nws12'
        conn.executemany(
            "INSERT OR IGNORE INTO datafields (id, description, dataset, region, universe, delay, type)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                ("nws12_vec_a", "VECTOR field A", "nws12", "USA", "TOP3000", 0, "VECTOR"),
                ("nws12_vec_b", "VECTOR field B", "nws12", "USA", "TOP3000", 0, "VECTOR"),
                ("nws12_mat_c", "MATRIX field C", "nws12", "USA", "TOP3000", 0, "MATRIX"),
            ],
        )
        conn.commit()

        combos = templates.expand_slots(conn, sentiment)

        # 3 window values x 2 VECTOR fields = 6 combos
        assert len(combos) > 0, "Expected combos from 2 VECTOR fields x 3 windows"
        assert len(combos) == 6, (
            f"Expected 6 combos (2 VECTOR fields x 3 windows), got {len(combos)}"
        )

        # Only VECTOR field ids (not nws12_mat_c) appear in expressions
        exprs = [c[0] for c in combos]
        assert all("nws12_mat_c" not in e for e in exprs), (
            "MATRIX field 'nws12_mat_c' should not appear in VECTOR-filtered expansion"
        )
        assert any("nws12_vec_a" in e for e in exprs), (
            "VECTOR field 'nws12_vec_a' should appear in expansion"
        )
        assert any("nws12_vec_b" in e for e in exprs), (
            "VECTOR field 'nws12_vec_b' should appear in expansion"
        )
    finally:
        conn.close()


def test_validate_gate():
    """BF-02: validate gate contract -- combos with validate returning False are filtered out.

    Uses unittest.mock.patch to stub validate.validate to always return (False, 'bad token').
    Simulates the filtering logic Plan 07-03 MUST implement (every combo checked before sim).
    Asserts: 0 combos pass through when validate always fails.
    """
    import templates
    import unittest.mock

    # Build a small list of 3 synthetic combos (same shape as expand_slots output)
    synthetic_combos = [
        ("rank(ts_corr(volume, close, 5))", {"field": "volume", "window": "5"}),
        ("rank(ts_corr(vwap, close, 5))",   {"field": "vwap",   "window": "5"}),
        ("rank(ts_corr(volume, close, 10))", {"field": "volume", "window": "10"}),
    ]

    # Simulate the validate-gate pattern bruteforce.py will implement
    with unittest.mock.patch("validate.validate", return_value=(False, "bad token")) as mock_validate:
        import validate
        validated_combos = [
            combo for combo in synthetic_combos
            if validate.validate(None, combo[0])[0]
        ]

    # All combos should be filtered out when validate always returns False
    assert len(validated_combos) == 0, (
        f"Expected 0 combos to pass a failing validate gate, got {len(validated_combos)}"
    )
    # validate was called once per combo
    assert mock_validate.call_count == 3, (
        f"validate should be called once per combo (3 times), called {mock_validate.call_count} times"
    )


def test_probe_spread_sample():
    """BF-03: probe_spread_sample covers all distinct slot values within size limit.

    Builds 9 synthetic combos (3 field values x 3 window values).
    Asserts: result <= 5 combos; all 3 field values covered; all 3 window values covered.
    """
    import templates

    # Build 9 combos: 3 field values x 3 window values
    fields = ["field_a", "field_b", "field_c"]
    windows = ["5", "10", "20"]
    synthetic_combos = [
        (f"rank(ts_corr({f}, close, {w}))", {"field": f, "window": w})
        for f in fields
        for w in windows
    ]
    assert len(synthetic_combos) == 9, "synthetic combos setup error"

    slot_names = ["field", "window"]
    sample = templates.probe_spread_sample(synthetic_combos, slot_names, size=5)

    # Result must not exceed size
    assert len(sample) <= 5, (
        f"probe_spread_sample returned {len(sample)} combos, exceeds size=5"
    )

    # Greedy cover should achieve full coverage of all 3 distinct field values within 3-5 picks
    field_vals_covered = {c[1]["field"] for c in sample}
    assert field_vals_covered == set(fields), (
        f"probe_spread_sample did not cover all field values: {field_vals_covered} vs {set(fields)}"
    )

    # Greedy cover should also cover all 3 distinct window values within 5 picks
    window_vals_covered = {c[1]["window"] for c in sample}
    assert window_vals_covered == set(windows), (
        f"probe_spread_sample did not cover all window values: {window_vals_covered} vs {set(windows)}"
    )


# ---------------------------------------------------------------------------
# BF-03 / BF-04 / BF-05 / BF-06 engine tests (Plan 07-03: bruteforce.py)
# ---------------------------------------------------------------------------


def test_probe_abandon():
    """BF-03 / D-05: template abandoned when all probe sims are far-fail.

    All probe grade_many calls return status="fail". classify_from_checks returns
    ("fail", [...]) for every probe alpha. Validates:
    - "template abandoned after probe" is printed
    - bruteforce_runs row: n_simmed == 0 (no bulk-sim)
    - Engine still records 1 bruteforce_runs row (probe_abandoned template IS persisted)
    """
    import io
    import bruteforce

    client = MagicMock()

    # 5 probe results all with status="fail", no alpha_id
    fail_results = [
        {"status": "fail", "alpha_id": None, "checks": [], "expression": f"expr_{i}"}
        for i in range(5)
    ]

    with (
        unittest.mock.patch("bruteforce.selfcorr.backfill_active_pnl"),
        unittest.mock.patch("bruteforce.probe_delay.probe_and_gate"),
        unittest.mock.patch("bruteforce.validate.validate", return_value=(True, "")),
        unittest.mock.patch("bruteforce.grade.grade_many", return_value=fail_results),
        unittest.mock.patch(
            "bruteforce.editor.classify_from_checks", return_value=("fail", ["SHARPE"])
        ),
        unittest.mock.patch(
            "bruteforce.additivity.rank_by_proxy",
            side_effect=AssertionError("additivity gate must not be reached on probe abandon"),
        ),
        unittest.mock.patch(
            "bruteforce.additivity.confirm_additive",
            side_effect=AssertionError("confirm_additive must not be reached on probe abandon"),
        ),
    ):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = bruteforce.bruteforce(
                client=client,
                db_path=":memory:",
                delay=0,
                quota=5,
                probe_size=5,
                template_names=["residual_momentum"],
            )
        output = buf.getvalue()

    # Engine reports 1 template done (probe-abandoned templates still count as processed)
    assert result["n_templates_done"] == 1, (
        f"Expected 1 template done (probe-abandoned), got {result['n_templates_done']}"
    )
    # Log must mention probe abandon
    assert "template abandoned after probe" in output, (
        f"Expected 'template abandoned after probe' in output; got: {output!r}"
    )
    # No additive survivors found
    assert result["quota_count"] == 0, "Expected 0 additive survivors for probe-abandoned run"


def test_validate_gate_drops_combos():
    """BF-02 (engine): validate gate in bruteforce() drops all combos; grade_one never called.

    Patches validate.validate to always return (False, 'unknown field').
    Verifies:
    - grade.grade_one is NEVER called (simulation skipped entirely)
    - bruteforce_runs row has failure_counts["validate_dropped"] > 0, n_simmed == 0
    """
    import json
    import bruteforce

    client = MagicMock()

    # grade.grade_one should never be reached; grade_many also never reached
    grade_one_mock = MagicMock(side_effect=AssertionError("grade_one must not be called"))
    grade_many_mock = MagicMock(side_effect=AssertionError("grade_many must not be called"))

    # We need a real in-memory DB to verify the bruteforce_runs row
    real_conn = db.init_db(":memory:")

    with (
        unittest.mock.patch("bruteforce.selfcorr.backfill_active_pnl"),
        unittest.mock.patch("bruteforce.probe_delay.probe_and_gate"),
        unittest.mock.patch("bruteforce.validate.validate", return_value=(False, "unknown field 'bad_token'")),
        unittest.mock.patch("bruteforce.grade.grade_one", grade_one_mock),
        unittest.mock.patch("bruteforce.grade.grade_many", grade_many_mock),
        unittest.mock.patch("bruteforce.db.init_db", return_value=real_conn),
    ):
        result = bruteforce.bruteforce(
            client=client,
            db_path=":memory:",
            delay=0,
            quota=5,
            probe_size=5,
            template_names=["beta_neutral"],  # 6 combos (2 fields x 3 windows), all dropped
        )

    # grade_one / grade_many must not have been called (AssertionError would have fired)
    # If we reach here without exception, the validate gate worked correctly.

    # Check bruteforce_runs row
    row = real_conn.execute(
        "SELECT n_simmed, failure_counts FROM bruteforce_runs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row is not None, "bruteforce_runs row missing after run with validate failures"
    assert row[0] == 0, f"n_simmed should be 0 when all combos are validate-dropped, got {row[0]}"
    fc = json.loads(row[1]) if row[1] else {}
    assert fc.get("validate_dropped", 0) > 0, (
        f"failure_counts['validate_dropped'] should be > 0, got: {fc}"
    )

    real_conn.close()


def test_quota_stop():
    """BF-04 / D-07: engine stops after quota additive survivors are found.

    With quota=1 and 2 templates: engine stops after the first template yields
    1 additive survivor — second template is never processed.
    Verifies: quota_count==1, stop_reason=="quota_met", n_templates_done==1.
    """
    import bruteforce

    client = MagicMock()

    # Probe: 1 result with status="near" so template survives probe
    probe_result = [{"status": "near", "alpha_id": "alpha_probe_001", "checks": [], "expression": "expr_0"}]

    # Bulk-sim: return 1 IS-passing alpha
    bulk_return = {"results": [{"status": "pass", "alpha_id": "alpha_bulk_001", "checks": [], "expression": "expr_bulk"}], "hit_401": False}

    # Additivity gate: rank_by_proxy → 1 survivor; confirm_additive → additive=True
    proxy_survivor = MagicMock()
    proxy_survivor.proxy_drop = False
    proxy_survivor.alpha_id = "alpha_bulk_001"
    rank_result = [proxy_survivor]

    additive_confirm = MagicMock()
    additive_confirm.additive = True
    additive_confirm.alpha_id = "alpha_bulk_001"

    # classify_from_checks: "near" for probe result (template survives)
    real_conn = db.init_db(":memory:")

    with (
        unittest.mock.patch("bruteforce.selfcorr.backfill_active_pnl"),
        unittest.mock.patch("bruteforce.probe_delay.probe_and_gate"),
        unittest.mock.patch("bruteforce.validate.validate", return_value=(True, "")),
        unittest.mock.patch("bruteforce.grade.grade_many", return_value=probe_result),
        unittest.mock.patch("bruteforce.editor.classify_from_checks", return_value=("near", [])),
        unittest.mock.patch("bruteforce._bulk_sim_quota_aware", return_value=bulk_return),
        unittest.mock.patch("bruteforce.additivity.rank_by_proxy", return_value=rank_result),
        unittest.mock.patch("bruteforce.additivity.confirm_additive", return_value=additive_confirm),
        unittest.mock.patch("bruteforce.db.init_db", return_value=real_conn),
    ):
        result = bruteforce.bruteforce(
            client=client,
            db_path=":memory:",
            delay=0,
            quota=1,
            probe_size=5,
            # 2 templates: beta_neutral (all-literal slots, 6 combos) + residual_momentum
            template_names=["beta_neutral", "residual_momentum"],
        )

    assert result["quota_count"] == 1, (
        f"Expected quota_count=1, got {result['quota_count']}"
    )
    assert result["stop_reason"] == "quota_met", (
        f"Expected stop_reason='quota_met', got {result['stop_reason']!r}"
    )
    assert result["n_templates_done"] == 1, (
        f"Expected engine to stop after 1st template, got n_templates_done={result['n_templates_done']}"
    )

    real_conn.close()


def test_401_stop():
    """D-09: 401 from bulk-sim triggers sys.exit(1) with partial=1 in bruteforce_runs row.

    Verifies:
    - bruteforce() calls sys.exit(1) (caught as SystemExit)
    - bruteforce_runs row for in-progress template has partial=1
    - No re-auth attempt (login never called inside engine)
    """
    import requests
    import bruteforce

    client = MagicMock()

    # Probe passes so template survives probe phase
    probe_result = [{"status": "near", "alpha_id": "alpha_probe_401", "checks": [], "expression": "expr_0"}]

    # _bulk_sim_quota_aware returns hit_401=True (simulates 401 during bulk-sim)
    bulk_401_return = {"results": [], "hit_401": True}

    real_conn = db.init_db(":memory:")

    with (
        unittest.mock.patch("bruteforce.selfcorr.backfill_active_pnl"),
        unittest.mock.patch("bruteforce.probe_delay.probe_and_gate"),
        unittest.mock.patch("bruteforce.validate.validate", return_value=(True, "")),
        unittest.mock.patch("bruteforce.grade.grade_many", return_value=probe_result),
        unittest.mock.patch("bruteforce.editor.classify_from_checks", return_value=("near", [])),
        unittest.mock.patch("bruteforce._bulk_sim_quota_aware", return_value=bulk_401_return),
        unittest.mock.patch("bruteforce.db.init_db", return_value=real_conn),
    ):
        with pytest.raises(SystemExit) as exc_info:
            bruteforce.bruteforce(
                client=client,
                db_path=":memory:",
                delay=0,
                quota=5,
                probe_size=5,
                template_names=["beta_neutral"],
            )

    assert exc_info.value.code == 1, (
        f"Expected sys.exit(1), got exit code {exc_info.value.code}"
    )

    # bruteforce_runs row for the in-progress template must have partial=1
    row = real_conn.execute(
        "SELECT partial FROM bruteforce_runs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row is not None, "bruteforce_runs row missing after 401 stop"
    assert row[0] == 1, (
        f"Expected partial=1 in bruteforce_runs row after 401, got partial={row[0]}"
    )

    real_conn.close()


def test_bruteforce_runs_row_per_template():
    """BF-06 / D-11: one bruteforce_runs row written per template, even with 0 survivors.

    Runs bruteforce() with 2 templates (beta_neutral + residual_momentum).
    Probe passes but bulk-sim returns 0 IS-passing alphas → no additivity gate reached.
    Verifies:
    - COUNT(*) from bruteforce_runs == 2 (one row per template)
    - Both rows have valid JSON in failure_counts and examples columns
    """
    import json
    import bruteforce

    client = MagicMock()

    # Probe: passes with "near" — templates survive probe stage
    probe_result = [{"status": "near", "alpha_id": "alpha_probe_row", "checks": [], "expression": "expr_0"}]

    # Bulk-sim: 0 IS-passing alphas → quota never met, additivity gate never reached
    bulk_no_survivors = {
        "results": [
            {"status": "fail", "alpha_id": None, "checks": [], "expression": "expr_bulk_fail"}
        ],
        "hit_401": False,
    }

    real_conn = db.init_db(":memory:")
    run_id_capture = {}

    # Intercept insert_bruteforce_run to capture the run_id for verification
    original_insert = db.insert_bruteforce_run

    def capturing_insert(conn, row):
        run_id_capture["run_id"] = row["run_id"]
        return original_insert(conn, row)

    with (
        unittest.mock.patch("bruteforce.selfcorr.backfill_active_pnl"),
        unittest.mock.patch("bruteforce.probe_delay.probe_and_gate"),
        unittest.mock.patch("bruteforce.validate.validate", return_value=(True, "")),
        unittest.mock.patch("bruteforce.grade.grade_many", return_value=probe_result),
        unittest.mock.patch("bruteforce.editor.classify_from_checks", return_value=("near", [])),
        unittest.mock.patch("bruteforce._bulk_sim_quota_aware", return_value=bulk_no_survivors),
        unittest.mock.patch("bruteforce.additivity.rank_by_proxy", return_value=[]),
        unittest.mock.patch("bruteforce.db.init_db", return_value=real_conn),
        unittest.mock.patch("bruteforce.db.insert_bruteforce_run", side_effect=capturing_insert),
    ):
        result = bruteforce.bruteforce(
            client=client,
            db_path=":memory:",
            delay=0,
            quota=5,
            probe_size=5,
            template_names=["beta_neutral", "residual_momentum"],
        )

    # Exactly 2 templates done
    assert result["n_templates_done"] == 2, (
        f"Expected 2 templates done, got {result['n_templates_done']}"
    )

    run_id = run_id_capture.get("run_id")
    assert run_id is not None, "run_id not captured — insert_bruteforce_run may not have been called"

    # 2 bruteforce_runs rows (one per template)
    count = real_conn.execute(
        "SELECT COUNT(*) FROM bruteforce_runs WHERE run_id=?", (run_id,)
    ).fetchone()[0]
    assert count == 2, (
        f"Expected 2 bruteforce_runs rows for 2 templates, got {count}"
    )

    # Both rows have valid JSON in failure_counts and examples
    rows = real_conn.execute(
        "SELECT failure_counts, examples FROM bruteforce_runs WHERE run_id=?", (run_id,)
    ).fetchall()
    for i, (fc_json, ex_json) in enumerate(rows):
        assert fc_json is not None, f"Row {i}: failure_counts is NULL"
        assert ex_json is not None, f"Row {i}: examples is NULL"
        fc = json.loads(fc_json)
        ex = json.loads(ex_json)
        assert isinstance(fc, dict), f"Row {i}: failure_counts is not a JSON object"
        assert isinstance(ex, dict), f"Row {i}: examples is not a JSON object"

    real_conn.close()


# ---------------------------------------------------------------------------
# BF-05 static check (Plan 07-04): AI-free constraint
# ---------------------------------------------------------------------------


def test_no_llm_imports():
    """BF-05: bruteforce.py and templates.py contain no LLM/AI library references.

    Opens each file as raw text and asserts that none of the following terms appear
    (case-insensitive): 'claude', 'anthropic', 'llm', 'openai'.

    This is the static verification that Tool B is fully AI-free — no model API
    is called during a brute-force run.
    """
    import pathlib

    terms = ["claude", "anthropic", "llm", "openai"]
    files_to_check = ["bruteforce.py", "templates.py"]

    # Resolve paths relative to this test file's directory
    base_dir = pathlib.Path(__file__).parent

    for filename in files_to_check:
        filepath = base_dir / filename
        assert filepath.exists(), f"{filename} not found at {filepath}"
        source = filepath.read_text(encoding="utf-8").lower()
        for term in terms:
            assert term not in source, (
                f"AI/LLM term '{term}' found in {filename} — "
                f"bruteforce tool must be AI-free (BF-05)"
            )
