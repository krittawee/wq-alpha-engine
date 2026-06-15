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
