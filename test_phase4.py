"""test_phase4.py — Full test suite for Phase 4: Optimization & Polish.

Covers all 12 requirement cases from the 04-RESEARCH.md validation architecture table.

OPT-01 (Settings Optimizer): 4 tests
OPT-02 (Decay Monitor): 4 tests
OPT-03 (Obsidian Prose Layer): 4 tests

Design principles:
- All tests use in-memory SQLite via db.init_db(':memory:') — zero disk writes.
- Zero BRAIN API calls in any test — grade_many and BRAIN client are mocked with MagicMock.
- Modules not yet implemented (optimizer, decay_monitor, obsidian) are loaded with
  pytest.importorskip so the test FILE is always importable (no syntax errors) even
  before the feature modules exist. Missing modules cause the test to SKIP, not ERROR.
- Inline fixtures — no conftest.py (matches test_phase3.py pattern exactly).
- OPT-03 tests use tmp_path (built-in pytest fixture) for vault root.

CRITICAL: ZERO grade/simulate/login calls.
"""

import sys
import unittest
import unittest.mock
import pytest
import sqlite3

import db


# ---------------------------------------------------------------------------
# Shared fixture — in-memory SQLite with Phase 4 schema
# ---------------------------------------------------------------------------


@pytest.fixture
def conn():
    """Open an in-memory SQLite DB with full schema (including Phase 4 additions).

    The Phase 4 db.py (Plan 01) must add:
      - checks_history table (CREATE TABLE IF NOT EXISTS)
      - note_path column on alphas (ALTER TABLE ... ADD COLUMN)

    This fixture verifies that init_db(':memory:') creates a DB ready for
    all Phase 4 tests. Each test gets a fresh connection.
    """
    c = db.init_db(":memory:")
    yield c
    c.close()


# ---------------------------------------------------------------------------
# OPT-01: Settings Optimizer tests
# ---------------------------------------------------------------------------


def test_build_variants_cap(conn):
    """OPT-01: build_variants returns ≤4 settings dicts for a NEAR alpha.

    Requirement: The optimizer must build at most 4 candidate settings variants
    per NEAR alpha (RESEARCH.md D-02 cap). Having too many variants wastes BRAIN
    sim slots (BRAIN cap ≤3 concurrent; time, not money, is the bottleneck).
    """
    optimizer = pytest.importorskip("optimizer")

    # Insert a NEAR alpha with archetype so build_variants can use heuristic table
    conn.execute(
        "INSERT OR REPLACE INTO alphas(alpha_id, expression, archetype, decay, "
        "neutralization, truncation, status) VALUES(?,?,?,?,?,?,?)",
        ("NEAR_01", "ts_rank(close,5)", "reversal", 10, "SUBINDUSTRY", 0.08, "near"),
    )
    conn.commit()

    alpha_row = {
        "alpha_id": "NEAR_01",
        "expression": "ts_rank(close,5)",
        "archetype": "reversal",
        "decay": 10,
        "neutralization": "SUBINDUSTRY",
        "truncation": 0.08,
        "status": "near",
    }

    result = optimizer.build_variants(alpha_row, conn)

    assert isinstance(result, list), (
        f"build_variants must return a list; got {type(result).__name__!r}"
    )
    assert len(result) <= 4, (
        f"OPT-01 FAIL: build_variants returned {len(result)} variants; "
        f"expected ≤4 (D-02 cap)"
    )


def test_build_variants_no_self(conn):
    """OPT-01: build_variants never includes the alpha's current (decay, neutralization, truncation).

    Requirement: Re-simulating the exact same settings as the NEAR alpha is a
    wasted sim slot. The optimizer must exclude the current combo (RESEARCH.md D-02).
    """
    optimizer = pytest.importorskip("optimizer")

    # Alpha with specific current settings
    current_decay = 10
    current_neutralization = "SUBINDUSTRY"
    current_truncation = 0.08

    alpha_row = {
        "alpha_id": "NEAR_02",
        "expression": "ts_rank(close,5)",
        "archetype": "reversal",
        "decay": current_decay,
        "neutralization": current_neutralization,
        "truncation": current_truncation,
        "status": "near",
    }

    result = optimizer.build_variants(alpha_row, conn)

    current_combo = (current_decay, current_neutralization, current_truncation)
    for variant in result:
        variant_combo = (
            variant.get("decay"),
            variant.get("neutralization"),
            variant.get("truncation"),
        )
        assert variant_combo != current_combo, (
            f"OPT-01 FAIL: build_variants included current settings combo "
            f"{current_combo!r} in variants — this wastes a sim slot"
        )


def test_optimizer_calls_grade_many(conn):
    """OPT-01: run_optimize calls grade_many (mocked), confirming the optimization loop runs.

    Requirement: The optimizer must call grade.grade_many to simulate variants.
    This test mocks grade_many to return [] (no sims) and verifies the mock was
    called — confirming the orchestration wiring exists even if no NEAR alphas
    are currently in the DB.

    Note: The test inserts a NEAR alpha so run_optimize has something to process.
    """
    from unittest.mock import patch, MagicMock

    optimizer = pytest.importorskip("optimizer")

    # Insert a NEAR alpha so the optimizer has something to process
    conn.execute(
        "INSERT OR REPLACE INTO alphas(alpha_id, expression, archetype, decay, "
        "neutralization, truncation, status) VALUES(?,?,?,?,?,?,?)",
        ("NEAR_OPT_01", "ts_rank(close,5)", "reversal", 10, "SUBINDUSTRY", 0.08, "near"),
    )
    conn.commit()

    mock_client = MagicMock()
    mock_grade_many = MagicMock(return_value=[])

    with patch("grade.grade_many", mock_grade_many):
        optimizer.run_optimize(client=mock_client, conn=conn, db_path=":memory:")

    assert mock_grade_many.called, (
        "OPT-01 FAIL: grade_many was never called by run_optimize — "
        "variant simulation loop not wired"
    )


def test_variant_lineage(conn):
    """OPT-01: variants are recorded with parent_alpha_id = NEAR alpha's id.

    Requirement: RESEARCH.md Pattern 2 — each variant's DB row must link back
    to the NEAR alpha via parent_alpha_id. This is the lineage chain that lets
    the user trace which NEAR alpha each variant came from.

    Strategy: Insert a NEAR alpha, mock grade_many to return a passing result,
    run the optimizer, then assert grade_many was called with parent_map
    containing the NEAR alpha's id (or assert the returned result includes
    parent_alpha_id).
    """
    from unittest.mock import patch, MagicMock

    optimizer = pytest.importorskip("optimizer")

    near_alpha_id = "NEAR_LIN_01"

    # Insert a NEAR alpha
    conn.execute(
        "INSERT OR REPLACE INTO alphas(alpha_id, expression, archetype, decay, "
        "neutralization, truncation, status) VALUES(?,?,?,?,?,?,?)",
        (near_alpha_id, "ts_rank(close,5)", "reversal", 10, "SUBINDUSTRY", 0.08, "near"),
    )
    conn.commit()

    # Mock grade_many to capture its arguments
    captured_calls = []

    def mock_grade_many_capture(*args, **kwargs):
        captured_calls.append(kwargs)
        return []

    mock_client = MagicMock()

    with patch("grade.grade_many", side_effect=mock_grade_many_capture):
        optimizer.run_optimize(client=mock_client, conn=conn, db_path=":memory:")

    # Verify that grade_many was called with parent linkage to the NEAR alpha
    assert len(captured_calls) > 0, (
        "OPT-01 FAIL: grade_many was not called — no variants submitted"
    )
    # The call must include parent_map or parent_alpha_id linking to near_alpha_id
    any_linked = any(
        (kwargs.get("parent_map") and near_alpha_id in str(kwargs.get("parent_map", {})))
        or kwargs.get("parent_alpha_id") == near_alpha_id
        for kwargs in captured_calls
    )
    assert any_linked, (
        f"OPT-01 FAIL: grade_many never called with parent_map containing "
        f"near_alpha_id={near_alpha_id!r}. Variants must record lineage to NEAR alpha. "
        f"Captured calls: {captured_calls!r}"
    )


# ---------------------------------------------------------------------------
# OPT-02: Decay Monitor tests
# ---------------------------------------------------------------------------


def test_decay_no_data(conn):
    """OPT-02: detect_decay returns status='no_data' when <2 checks_history rows exist.

    Requirement: RESEARCH.md Pattern 4 — "A fresh check with no prior history is
    'no data', not 'degraded'. Needs ≥2 history rows per alpha before flagging anything."
    Anti-pattern: marking 'no_data' as 'degraded' (RESEARCH.md anti-pattern section).
    """
    decay_monitor = pytest.importorskip("decay_monitor")

    # No checks_history rows inserted — alpha has never been re-checked
    result = decay_monitor.detect_decay(conn, "ALPHA_NO_DATA_01")

    assert isinstance(result, dict), (
        f"detect_decay must return a dict; got {type(result).__name__!r}"
    )
    assert result.get("status") == "no_data", (
        f"OPT-02 FAIL: detect_decay with no history rows returned "
        f"status={result.get('status')!r}; expected 'no_data'. "
        f"Anti-pattern: cannot flag decay with <2 data points."
    )


def test_decay_degraded(conn):
    """OPT-02: detect_decay returns status='degraded' when Sharpe drops > threshold.

    Requirement: RESEARCH.md Pattern 4 — degradation = key metric drops beyond
    configurable %. Test: old_val=1.2, new_val=0.8 → drop=33% > threshold=15%.
    """
    decay_monitor = pytest.importorskip("decay_monitor")

    alpha_id = "ALPHA_DEG_01"

    # Insert 2 checks_history rows for LOW_SHARPE — older first, newer second
    # (checked_at ordering determines which is "new" vs "old")
    conn.execute(
        "INSERT INTO checks_history "
        "(alpha_id, name, result, value, limit_val, checked_at, run_tag) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (alpha_id, "LOW_SHARPE", "FAIL", 1.2, 1.25, "2026-06-01T10:00:00", "run_1"),
    )
    conn.execute(
        "INSERT INTO checks_history "
        "(alpha_id, name, result, value, limit_val, checked_at, run_tag) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (alpha_id, "LOW_SHARPE", "FAIL", 0.8, 1.25, "2026-06-11T10:00:00", "run_2"),
    )
    conn.commit()

    result = decay_monitor.detect_decay(conn, alpha_id, threshold_pct=0.15)

    assert result.get("status") == "degraded", (
        f"OPT-02 FAIL: detect_decay with old_val=1.2, new_val=0.8 (drop=33%) and "
        f"threshold=15% returned status={result.get('status')!r}; expected 'degraded'. "
        f"Full result: {result!r}"
    )


def test_decay_stable(conn):
    """OPT-02: detect_decay returns status='stable' when Sharpe drop < threshold.

    Requirement: RESEARCH.md Pattern 4 — test: old_val=1.3, new_val=1.2 → drop=7.7%
    < threshold=15%. Must return 'stable', not 'degraded'.
    """
    decay_monitor = pytest.importorskip("decay_monitor")

    alpha_id = "ALPHA_STABLE_01"

    # old_val=1.3, new_val=1.2 → drop = (1.3 - 1.2) / 1.3 = 7.69% < 15%
    conn.execute(
        "INSERT INTO checks_history "
        "(alpha_id, name, result, value, limit_val, checked_at, run_tag) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (alpha_id, "LOW_SHARPE", "FAIL", 1.3, 1.25, "2026-06-01T10:00:00", "run_1"),
    )
    conn.execute(
        "INSERT INTO checks_history "
        "(alpha_id, name, result, value, limit_val, checked_at, run_tag) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (alpha_id, "LOW_SHARPE", "FAIL", 1.2, 1.25, "2026-06-11T10:00:00", "run_2"),
    )
    conn.commit()

    result = decay_monitor.detect_decay(conn, alpha_id, threshold_pct=0.15)

    assert result.get("status") == "stable", (
        f"OPT-02 FAIL: detect_decay with old_val=1.3, new_val=1.2 (drop=7.7%) and "
        f"threshold=15% returned status={result.get('status')!r}; expected 'stable'. "
        f"Full result: {result!r}"
    )


def test_history_append_only(conn):
    """OPT-02: append_checks_history never overwrites — two calls = two rows.

    Requirement: RESEARCH.md anti-pattern — 'Writing checks_history rows via
    upsert_checks is wrong'. The append helper must use plain INSERT (not INSERT OR
    REPLACE) so each call adds a new row. Calling twice for the same alpha_id must
    produce COUNT(*) == 2, not 1.

    This test verifies the checks_history table exists and is append-only.
    """
    alpha_id = "ALPHA_HIST_01"
    checks_list = [
        {"name": "LOW_SHARPE", "result": "FAIL", "value": 1.22, "limit": 1.25},
    ]

    # Call append_checks_history twice
    db.append_checks_history(conn, alpha_id, checks_list, run_tag="run_1")
    db.append_checks_history(conn, alpha_id, checks_list, run_tag="run_2")

    count = conn.execute(
        "SELECT COUNT(*) FROM checks_history WHERE alpha_id=?",
        (alpha_id,),
    ).fetchone()[0]

    assert count == 2, (
        f"OPT-02 FAIL: append_checks_history must be append-only; "
        f"expected COUNT=2 after two inserts, got {count}. "
        f"Ensure checks_history uses INSERT (not INSERT OR REPLACE)."
    )


# ---------------------------------------------------------------------------
# OPT-03: Obsidian Prose Layer tests
# ---------------------------------------------------------------------------


def test_archetype_notes_count(tmp_path, conn):
    """OPT-03: regen_archetype_notes creates exactly one file per archetype.

    Requirement: RESEARCH.md Pattern 7 — one note per archetype in
    alpha-kb/Archetypes/, regenerated from DB each run (D-10).
    Must create len(researcher.ARCHETYPES) files (currently 8 archetypes).
    """
    obsidian = pytest.importorskip("obsidian")
    researcher = pytest.importorskip("researcher")

    written_paths = obsidian.regen_archetype_notes(conn, tmp_path)

    expected_count = len(researcher.ARCHETYPES)
    assert len(written_paths) == expected_count, (
        f"OPT-03 FAIL: regen_archetype_notes returned {len(written_paths)} paths; "
        f"expected {expected_count} (one per archetype in researcher.ARCHETYPES)"
    )
    for p in written_paths:
        from pathlib import Path
        assert Path(p).exists(), (
            f"OPT-03 FAIL: regen_archetype_notes returned path {p!r} "
            f"but the file does not exist on disk"
        )


def test_failure_notes_families(tmp_path, conn):
    """OPT-03: regen_failure_notes creates one file per distinct failure family.

    Requirement: RESEARCH.md Pattern 5 — group by primary failing check name
    (CONCENTRATED_WEIGHT > HIGH_TURNOVER > ... > LOW_SHARPE priority order).
    With 3 fail alphas each having a different primary check, must create 3 notes.
    """
    obsidian = pytest.importorskip("obsidian")

    # Insert 3 fail alphas with distinct primary failure checks
    test_alphas = [
        ("FAIL_LS_01", "ts_rank(close,5)", "LOW_SHARPE"),
        ("FAIL_SUS_01", "rank(volume)", "LOW_SUB_UNIVERSE_SHARPE"),
        ("FAIL_CW_01", "rank(close/open)", "CONCENTRATED_WEIGHT"),
    ]
    for alpha_id, expression, check_name in test_alphas:
        conn.execute(
            "INSERT OR REPLACE INTO alphas(alpha_id, expression, status) VALUES(?,?,?)",
            (alpha_id, expression, "fail"),
        )
        conn.execute(
            "INSERT OR REPLACE INTO checks(alpha_id, name, result, value, limit_val, checked_at) "
            "VALUES(?,?,?,?,?,?)",
            (alpha_id, check_name, "FAIL", None, None, "2026-06-11T00:00:00"),
        )
    conn.commit()

    written_paths = obsidian.regen_failure_notes(conn, tmp_path)

    assert len(written_paths) == 3, (
        f"OPT-03 FAIL: regen_failure_notes returned {len(written_paths)} paths; "
        f"expected 3 (one per distinct failure family). "
        f"Inserted families: LOW_SHARPE, LOW_SUB_UNIVERSE_SHARPE, CONCENTRATED_WEIGHT"
    )
    # Each file must exist
    from pathlib import Path
    for p in written_paths:
        assert Path(p).exists(), (
            f"OPT-03 FAIL: regen_failure_notes returned path {p!r} "
            f"but the file does not exist on disk"
        )


def test_note_path_written(tmp_path, conn):
    """OPT-03: regen_archetype_notes populates alphas.note_path for matching alphas.

    Requirement: RESEARCH.md D-09 — two-way linking: notes embed [[alpha_id]]
    wikilinks AND alphas.note_path stores the path for DB→note navigation.

    Test: insert an alpha with archetype='reversal', call regen_archetype_notes,
    then verify alphas.note_path is not NULL for that alpha.
    """
    obsidian = pytest.importorskip("obsidian")

    # Insert a 'reversal' archetype alpha
    conn.execute(
        "INSERT OR REPLACE INTO alphas(alpha_id, expression, archetype, status) "
        "VALUES(?,?,?,?)",
        ("REVERSAL_NP_01", "ts_rank(close,5)", "reversal", "near"),
    )
    conn.commit()

    obsidian.regen_archetype_notes(conn, tmp_path)

    row = conn.execute(
        "SELECT note_path FROM alphas WHERE alpha_id=?",
        ("REVERSAL_NP_01",),
    ).fetchone()

    assert row is not None, (
        "OPT-03 FAIL: alpha REVERSAL_NP_01 not found in DB after regen"
    )
    assert row[0] is not None, (
        "OPT-03 FAIL: alphas.note_path is NULL after regen_archetype_notes — "
        "two-way link (DB→note) not written. Must UPDATE alphas SET note_path=... "
        "for all alphas belonging to each regenerated archetype note."
    )


def test_wikilinks_in_notes(tmp_path, conn):
    """OPT-03: generated notes contain [[alpha_id]] wikilinks.

    Requirement: RESEARCH.md D-09 — note body must contain [[alpha_id]] wikilinks
    for the note→alpha half of the two-way link. Pattern 7 example includes
    '[[{id}]]' in both Archetype and Failure note templates.
    """
    obsidian = pytest.importorskip("obsidian")

    # Insert a fail alpha so regen_failure_notes has a family to write
    conn.execute(
        "INSERT OR REPLACE INTO alphas(alpha_id, expression, status) VALUES(?,?,?)",
        ("FAIL_WL_01", "ts_rank(volume,5)", "fail"),
    )
    conn.execute(
        "INSERT OR REPLACE INTO checks(alpha_id, name, result, value, limit_val, checked_at) "
        "VALUES(?,?,?,?,?,?)",
        ("FAIL_WL_01", "LOW_SHARPE", "FAIL", 1.1, 1.25, "2026-06-11T00:00:00"),
    )
    conn.commit()

    written_paths = obsidian.regen_failure_notes(conn, tmp_path)
    assert len(written_paths) >= 1, (
        "OPT-03 FAIL: regen_failure_notes returned no paths — "
        "cannot check wikilinks in an empty result"
    )

    # Read the first generated note and verify [[...]] wikilinks are present
    from pathlib import Path
    note_content = Path(written_paths[0]).read_text(encoding="utf-8")

    assert "[[" in note_content, (
        f"OPT-03 FAIL: note at {written_paths[0]!r} does not contain '[[' — "
        f"wikilinks missing from note body. D-09 requires [[alpha_id]] wikilinks "
        f"in note content for note→alpha navigation in Obsidian."
    )


# ---------------------------------------------------------------------------
# GRADE-SETTINGS-FIDELITY: BRAIN returned settings trump requested settings
# ---------------------------------------------------------------------------


def test_grade_records_brain_actual_settings():
    """BRAIN is the source of truth for simulation settings.

    After Plan 05-01 changes, coerced alphas are DISCARDED (not persisted).
    This test uses a no-coercion scenario: requested delay=1 and BRAIN also
    returns delay=1. The test still asserts DB row shows delay=1 from BRAIN's
    response, while avoiding the new discard logic that fires on mismatch.

    Red-green contract: verifies that when delays match, grade_one correctly
    persists the alpha row with BRAIN's returned settings value.
    """
    import json
    from unittest.mock import MagicMock, patch

    import db
    import grade

    conn = db.init_db(":memory:")

    # Build mock BRAIN response: alpha dict with "settings" carrying delay=1
    # REQUEST delay=1 and BRAIN returns delay=1 — no coercion, alpha is persisted.
    mock_alpha_dict = {
        "id": "TEST_BRAIN_ACTUAL",
        "is": {
            "sharpe": 1.5,
            "fitness": 1.2,
            "checks": [{"result": "PASS", "name": "SHARPE"}],
        },
        "settings": {
            "delay": 1,              # BRAIN returns delay=1 (matches request)
            "region": "USA",
            "universe": "TOP3000",
            "decay": 15,
            "neutralization": "SUBINDUSTRY",
            "truncation": 0.08,
        },
    }

    mock_sim = MagicMock()
    mock_sim.wait.return_value = None
    mock_sim.alpha_id = "TEST_BRAIN_ACTUAL"
    mock_sim.get_alpha.return_value = mock_alpha_dict

    mock_client = MagicMock()
    mock_client.simulate.return_value = mock_sim

    # Patch validate so the test expression passes local validation, selfcorr helpers
    # so we don't hit real PnL / correlation logic, and Phase B correlation checks
    # so the test doesn't block on the 300-second poll_correlation timeout.
    with patch("validate.validate", return_value=(True, None)), \
         patch("selfcorr.proxy_gate", return_value=False), \
         patch("selfcorr.fetch_and_cache_pnl", return_value=None), \
         patch("grade.trigger_correlation_check", return_value=None), \
         patch("grade.poll_correlation", return_value={}):
        grade.grade_one(
            mock_client,
            conn,
            "close / open",
            run_id="test-run",
            delay=1,                 # REQUEST: delay=1 (matches BRAIN response)
        )

    row = conn.execute(
        "SELECT delay, settings_json FROM alphas WHERE alpha_id=?",
        ("TEST_BRAIN_ACTUAL",),
    ).fetchone()

    assert row is not None, (
        "grade_one did not insert a row for TEST_BRAIN_ACTUAL — check for early return"
    )

    col_delay = row[0]
    sj_delay = json.loads(row[1])["delay"] if row[1] else None

    assert col_delay == 1, (
        f"GRADE-SETTINGS-FIDELITY FAIL: delay column is {col_delay!r}; "
        f"expected 1 (BRAIN's returned value). grade_one must persist BRAIN's "
        f"returned settings, not the requested settings."
    )
    assert sj_delay == 1, (
        f"GRADE-SETTINGS-FIDELITY FAIL: settings_json['delay'] is {sj_delay!r}; "
        f"expected 1 (BRAIN's returned value). settings_json must reflect what "
        f"BRAIN actually ran."
    )

    conn.close()


# ---------------------------------------------------------------------------
# DELAY COERCION WARN+DISCARD (Plan 05-01 D-03 regression tests)
# ---------------------------------------------------------------------------


def test_grade_coercion_warning():
    """D-03: When BRAIN returns a different delay than requested, grade_one must
    print a COERCION WARNING to stderr and return WITHOUT persisting the alpha.

    Scenario: grade_one called with delay=0; mock BRAIN response carries
    settings.delay=1 (coercion). Verifies stderr warning and no DB row.
    """
    import contextlib
    import io
    from unittest.mock import MagicMock, patch

    import db
    import grade

    conn = db.init_db(":memory:")

    mock_alpha_dict = {
        "id": "TEST_COERCE_WARN",
        "is": {
            "sharpe": 1.5,
            "fitness": 1.2,
            "checks": [{"result": "PASS", "name": "SHARPE"}],
        },
        "settings": {
            "delay": 1,              # BRAIN coerced: returns delay=1
            "region": "USA",
            "universe": "TOP3000",
            "decay": 15,
            "neutralization": "SUBINDUSTRY",
            "truncation": 0.08,
        },
    }

    mock_sim = MagicMock()
    mock_sim.wait.return_value = None
    mock_sim.alpha_id = "TEST_COERCE_WARN"
    mock_sim.get_alpha.return_value = mock_alpha_dict

    mock_client = MagicMock()
    mock_client.simulate.return_value = mock_sim

    stderr_buf = io.StringIO()
    with patch("validate.validate", return_value=(True, None)), \
         patch("selfcorr.proxy_gate", return_value=False), \
         patch("selfcorr.fetch_and_cache_pnl", return_value=None), \
         patch("grade.trigger_correlation_check", return_value=None), \
         patch("grade.poll_correlation", return_value={}), \
         contextlib.redirect_stderr(stderr_buf):
        result = grade.grade_one(
            mock_client,
            conn,
            "rank(vwap)",
            run_id="test-coerce",
            delay=0,                 # REQUEST: delay=0
        )

    stderr_output = stderr_buf.getvalue()
    assert "COERCION WARNING" in stderr_output, (
        f"Expected 'COERCION WARNING' in stderr; got: {stderr_output!r}"
    )
    assert "TEST_COERCE_WARN" in stderr_output, (
        f"Expected alpha_id 'TEST_COERCE_WARN' in stderr warning; got: {stderr_output!r}"
    )

    row = conn.execute(
        "SELECT alpha_id FROM alphas WHERE alpha_id=?",
        ("TEST_COERCE_WARN",),
    ).fetchone()
    assert row is None, (
        "grade_one persisted a coerced alpha — it must be discarded (no DB row written)"
    )

    assert result.get("status") == "coerced", (
        f"Expected result['status'] == 'coerced'; got {result.get('status')!r}"
    )

    conn.close()


def test_grade_no_coercion_when_delay_matches():
    """D-03: When BRAIN returns the same delay as requested, no COERCION WARNING
    is emitted and the alpha IS persisted to the DB.

    Scenario: grade_one called with delay=0; mock BRAIN response carries
    settings.delay=0 (no coercion). Verifies no warning and DB row written.
    """
    import contextlib
    import io
    from unittest.mock import MagicMock, patch

    import db
    import grade

    conn = db.init_db(":memory:")

    mock_alpha_dict = {
        "id": "TEST_NO_COERCE",
        "is": {
            "sharpe": 1.5,
            "fitness": 1.2,
            "checks": [{"result": "PASS", "name": "SHARPE"}],
        },
        "settings": {
            "delay": 0,              # BRAIN returns delay=0 — matches request
            "region": "USA",
            "universe": "TOP3000",
            "decay": 15,
            "neutralization": "SUBINDUSTRY",
            "truncation": 0.08,
        },
    }

    mock_sim = MagicMock()
    mock_sim.wait.return_value = None
    mock_sim.alpha_id = "TEST_NO_COERCE"
    mock_sim.get_alpha.return_value = mock_alpha_dict

    mock_client = MagicMock()
    mock_client.simulate.return_value = mock_sim

    stderr_buf = io.StringIO()
    with patch("validate.validate", return_value=(True, None)), \
         patch("selfcorr.proxy_gate", return_value=False), \
         patch("selfcorr.fetch_and_cache_pnl", return_value=None), \
         patch("grade.trigger_correlation_check", return_value=None), \
         patch("grade.poll_correlation", return_value={}), \
         contextlib.redirect_stderr(stderr_buf):
        result = grade.grade_one(
            mock_client,
            conn,
            "rank(vwap)",
            run_id="test-no-coerce",
            delay=0,                 # REQUEST: delay=0
        )

    stderr_output = stderr_buf.getvalue()
    assert "COERCION WARNING" not in stderr_output, (
        f"Unexpected COERCION WARNING in stderr when delays match; got: {stderr_output!r}"
    )

    row = conn.execute(
        "SELECT alpha_id FROM alphas WHERE alpha_id=?",
        ("TEST_NO_COERCE",),
    ).fetchone()
    assert row is not None, (
        "grade_one did not persist alpha when delays match — it should be written to DB"
    )

    conn.close()


def test_grade_many_forwards_delay():
    """grade_many must forward delay= to every grade_one call.

    Calls grade_many with delay=0 and two expressions.
    Patches grade.grade_one to capture call arguments.
    Asserts every call received delay=0 as a keyword argument.
    """
    from unittest.mock import MagicMock, patch, call

    import db
    import grade

    conn = db.init_db(":memory:")
    mock_client = MagicMock()

    fake_result = {"expression": "x", "status": "pass", "alpha_id": "fake"}

    with patch.object(grade, "grade_one", return_value=fake_result) as mock_grade_one:
        grade.grade_many(
            mock_client,
            conn,
            ["rank(vwap)", "rank(volume)"],
            run_id="r1",
            delay=0,
        )

    assert mock_grade_one.call_count == 2, (
        f"Expected 2 grade_one calls; got {mock_grade_one.call_count}"
    )
    for c in mock_grade_one.call_args_list:
        assert c.kwargs.get("delay") == 0, (
            f"grade_one call did not receive delay=0; call args: {c}"
        )

    conn.close()


def test_grade_coercion_with_none_returned_delay():
    """D-03 None-safe normalization: when BRAIN omits the delay key entirely from
    settings (returns None from .get("delay")), the normalization must NOT raise
    TypeError and must fall back to the requested delay.

    When the fallback makes requested == resolved (both are the requested value),
    no coercion fires and the alpha IS persisted.

    This exercises the branch: resolved_delay_raw is None → resolved_delay_int = requested_delay_int
    """
    import contextlib
    import io
    from unittest.mock import MagicMock, patch

    import db
    import grade

    conn = db.init_db(":memory:")

    # BRAIN returns settings={} — no "delay" key (resolved_delay_raw is None)
    mock_alpha_dict = {
        "id": "TEST_NONE_DELAY",
        "is": {
            "sharpe": 1.5,
            "fitness": 1.2,
            "checks": [{"result": "PASS", "name": "SHARPE"}],
        },
        "settings": {},              # delay key absent
    }

    mock_sim = MagicMock()
    mock_sim.wait.return_value = None
    mock_sim.alpha_id = "TEST_NONE_DELAY"
    mock_sim.get_alpha.return_value = mock_alpha_dict

    mock_client = MagicMock()
    mock_client.simulate.return_value = mock_sim

    stderr_buf = io.StringIO()
    # Should not raise TypeError even though BRAIN returned no delay
    try:
        with patch("validate.validate", return_value=(True, None)), \
             patch("selfcorr.proxy_gate", return_value=False), \
             patch("selfcorr.fetch_and_cache_pnl", return_value=None), \
             patch("grade.trigger_correlation_check", return_value=None), \
             patch("grade.poll_correlation", return_value={}), \
             contextlib.redirect_stderr(stderr_buf):
            result = grade.grade_one(
                mock_client,
                conn,
                "rank(vwap)",
                run_id="test-none-delay",
                delay=0,             # REQUEST: delay=0
            )
    except TypeError as e:
        raise AssertionError(
            f"None-safe normalization failed — TypeError raised: {e}. "
            f"int(None) must not be called when resolved_delay_raw is None."
        ) from e

    # When None falls back to requested_delay_int=0, resolved==requested → no coercion.
    # The alpha IS persisted.
    row = conn.execute(
        "SELECT alpha_id FROM alphas WHERE alpha_id=?",
        ("TEST_NONE_DELAY",),
    ).fetchone()
    assert row is not None, (
        "grade_one should persist the alpha when BRAIN omits the delay key (None fallback = no coercion)"
    )

    # No coercion warning should appear
    stderr_output = stderr_buf.getvalue()
    assert "COERCION WARNING" not in stderr_output, (
        f"Unexpected COERCION WARNING when delay key is absent from BRAIN response; got: {stderr_output!r}"
    )

    conn.close()


# ---------------------------------------------------------------------------
# BUG-DELAY-DEDUP: delay-aware novelty dedup regression tests
# ---------------------------------------------------------------------------


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
    conn.close()


def test_queueable_delay0_passes_when_only_delay1_exists():
    """A candidate with dedup_alpha_id=None passes queueable even if a delay-1 row exists.

    This verifies the full chain: after the fix, generate_candidates sets
    dedup_alpha_id=None for a delay-0 candidate when only a delay-1 row exists.
    """
    import ideator

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
    conn.close()


# ---------------------------------------------------------------------------
# BUG-SELFCORR-PNL: schema+records PnL parser regression test
# ---------------------------------------------------------------------------


def test_fetch_and_cache_pnl_schema_records(tmp_path):
    """fetch_and_cache_pnl correctly parses BRAIN's {schema, records} response."""
    import json
    import pathlib
    import selfcorr
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

    cached = json.loads(pathlib.Path(path).read_text())
    assert len(cached['pnls']) == 3, f"Expected 3 pnls, got {len(cached['pnls'])}"
    assert len(cached['dates']) == 3, f"Expected 3 dates, got {len(cached['dates'])}"
    assert cached['pnls'][0] == 0.001
    conn.close()


# ---------------------------------------------------------------------------
# FIX-1: validate.py named-arg key exclusion from bare_field_tokens
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# FIX-2: ideator.py must emit winsorize(..., std=N) named param everywhere
# ---------------------------------------------------------------------------


class TestIdeatorWinsorizeNamedParam(unittest.TestCase):
    """FIX-2: ideator must emit winsorize(..., std=N), never winsorize(..., N)."""

    def setUp(self):
        import db
        self.conn = db.init_db(":memory:")
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


# ---------------------------------------------------------------------------
# FIX-3: grade.py must surface BRAIN sim ERROR instead of mislabeling as throttle
# ---------------------------------------------------------------------------


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

    @unittest.mock.patch('time.sleep')
    def test_throttle_still_retries(self, mock_sleep):
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


# ---------------------------------------------------------------------------
# Entry point — mirrors test_phase3.py pattern
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    """Run all tests directly (no pytest required for smoke check)."""
    import sys
    import tempfile
    from pathlib import Path

    tests = [
        # OPT-01
        ("test_build_variants_cap",          None),
        ("test_build_variants_no_self",       None),
        ("test_optimizer_calls_grade_many",   None),
        ("test_variant_lineage",              None),
        # OPT-02
        ("test_decay_no_data",               None),
        ("test_decay_degraded",              None),
        ("test_decay_stable",                None),
        ("test_history_append_only",         None),
        # OPT-03
        ("test_archetype_notes_count",       "tmp_path"),
        ("test_failure_notes_families",      "tmp_path"),
        ("test_note_path_written",           "tmp_path"),
        ("test_wikilinks_in_notes",          "tmp_path"),
    ]

    passed = 0
    failed = 0
    skipped = 0
    errors = []

    for test_name, fixture_type in tests:
        test_fn = globals()[test_name]
        try:
            c = db.init_db(":memory:")
            if fixture_type == "tmp_path":
                with tempfile.TemporaryDirectory() as tmpdir:
                    test_fn(Path(tmpdir), c)
            else:
                test_fn(c)
            c.close()
            print(f"  PASS: {test_name}")
            passed += 1
        except SystemExit:
            # pytest.importorskip raises SystemExit when module missing
            print(f"  SKIP: {test_name} (module not yet implemented)")
            skipped += 1
        except Exception as exc:
            print(f"  FAIL: {test_name}: {exc}")
            failed += 1
            errors.append((test_name, str(exc)))

    print(f"\n{passed} passed, {skipped} skipped, {failed} failed")
    if errors:
        sys.exit(1)
