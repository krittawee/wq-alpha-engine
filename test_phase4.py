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
