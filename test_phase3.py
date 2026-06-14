"""test_phase3.py — Criterion tests for Phase 3: Smart Iteration.

Machine-verifies all 4 ROADMAP Phase 3 success criteria:
Criterion 1: Editor correctly classifies PASS/NEAR/FAIL from checks table AND
             persists diagnosis to alphas.diagnosis after diagnose_and_mutate.
Criterion 2: Editor proposes mutations with parent_alpha_id lineage; mutation
             stubs pre-inserted at status=queued with parent_alpha_id set at
             insert time (confirmed by DB query — no post-hoc update).
Criterion 3: Local PnL-based self-corr pre-filter correctly identifies
             near-identical PnL series above the cutoff (max_pearson);
             load_returns returns daily differences; get_selfcorr_limit reads
             from DB (not hardcoded).
Criterion 4: FSA mines motifs from PASS alphas; filter_candidates drops
             candidates with known-frequent motifs; diversity metric available
             and measurable before/after diversity change.

CRITICAL: ZERO grade/simulate/login calls.
"""

import json
import math
import os
import sys
import tempfile
import unittest.mock as mock

import db


def _make_test_db(tmpdir: str) -> str:
    """Return path to a fresh hermetic test DB.

    WR-12: always start from a clean db.init_db() — never copy the live
    alpha_kb.db. Copying the live DB makes tests depend on production data
    (384+ live rows), causing non-deterministic results as the live DB grows.
    Each test seeds only the rows it needs.
    """
    tmp_db = os.path.join(tmpdir, "test.db")
    # tmp_db doesn't exist yet; db.init_db will create and initialise it.
    return tmp_db


# ---------------------------------------------------------------------------
# Criterion 1: classify_from_checks — NEAR/FAIL/PASS deterministic logic
# ---------------------------------------------------------------------------


def test_criterion_1_near_classification() -> None:
    """Verify that classify_from_checks covers all NEAR/FAIL/PASS cases (Case A-F)
    and that diagnose_and_mutate persists diagnosis to alphas.diagnosis (Case A).

    Case A: LOW_SHARPE value=1.22, limit=1.25 → gap=0.024 → NEAR
    Case B: MATCHES_COMPETITION FAIL → hard FAIL regardless
    Case C: LOW_SHARPE value=1.0, limit=1.25 → gap=0.20 → boundary check
    Case D: all checks result='PENDING' → PASS (Pitfall 2)
    Case E: LOW_SUB_UNIVERSE_SHARPE value=0.0, limit=0.0 → EPSILON floor applied
    Case F: 3 numeric fails each within 20% → FAIL (D-07 cap exceeded)
    """
    import editor

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_db = _make_test_db(tmpdir)
        conn = db.init_db(tmp_db)
        try:
            # ---------- Case A: NEAR (single numeric fail, gap=2.4% < 20%) ----------
            conn.execute(
                "INSERT OR IGNORE INTO alphas(alpha_id, expression, status) VALUES(?,?,?)",
                ("TEST_NEAR_A", "ts_rank(close,5)", "fail"),
            )
            conn.execute(
                "INSERT OR REPLACE INTO checks VALUES(?,?,?,?,?,?)",
                ("TEST_NEAR_A", "LOW_SHARPE", "FAIL", 1.22, 1.25, "2026-01-01"),
            )
            conn.commit()

            status_a, fails_a = editor.classify_from_checks("TEST_NEAR_A", conn)
            assert status_a == "near", (
                f"Case A FAIL: expected 'near', got {status_a!r} "
                f"for alpha with LOW_SHARPE within 20% of limit"
            )
            assert "LOW_SHARPE" in fails_a, (
                f"Case A FAIL: expected 'LOW_SHARPE' in fails, got {fails_a!r}"
            )

            # ---------- Case B: hard FAIL (MATCHES_COMPETITION) ----------
            conn.execute(
                "INSERT OR IGNORE INTO alphas(alpha_id, expression, status) VALUES(?,?,?)",
                ("TEST_HARD_B", "rank(close)", "fail"),
            )
            conn.execute(
                "INSERT OR REPLACE INTO checks VALUES(?,?,?,?,?,?)",
                ("TEST_HARD_B", "MATCHES_COMPETITION", "FAIL", None, None, "2026-01-01"),
            )
            conn.commit()

            status_b, fails_b = editor.classify_from_checks("TEST_HARD_B", conn)
            assert status_b == "fail", (
                f"Case B FAIL: expected 'fail' for MATCHES_COMPETITION, got {status_b!r}"
            )
            assert "MATCHES_COMPETITION" in fails_b, (
                f"Case B FAIL: expected MATCHES_COMPETITION in fails, got {fails_b!r}"
            )

            # ---------- Case C: boundary check — gap exactly 20% ----------
            # gap = abs(1.0 - 1.25) / max(abs(1.25), 0.01) = 0.25/1.25 = 0.20
            # D-07 says "within 20%" means gap <= 0.20, so 0.20 is a NEAR boundary
            conn.execute(
                "INSERT OR IGNORE INTO alphas(alpha_id, expression, status) VALUES(?,?,?)",
                ("TEST_BNDRY_C", "rank(close)", "fail"),
            )
            conn.execute(
                "INSERT OR REPLACE INTO checks VALUES(?,?,?,?,?,?)",
                ("TEST_BNDRY_C", "LOW_SHARPE", "FAIL", 1.0, 1.25, "2026-01-01"),
            )
            conn.commit()

            status_c, fails_c = editor.classify_from_checks("TEST_BNDRY_C", conn)
            # gap = 0.20 which satisfies gap <= 0.20 → NEAR (single fail, at-boundary)
            assert status_c == "near", (
                f"Case C FAIL: expected 'near' at exactly 20% gap boundary, got {status_c!r}"
            )

            # ---------- Case D: all PENDING → PASS (Pitfall 2) ----------
            conn.execute(
                "INSERT OR IGNORE INTO alphas(alpha_id, expression, status) VALUES(?,?,?)",
                ("TEST_PEND_D", "rank(close)", "grading"),
            )
            conn.execute(
                "INSERT OR REPLACE INTO checks VALUES(?,?,?,?,?,?)",
                ("TEST_PEND_D", "SELF_CORRELATION", "PENDING", None, None, "2026-01-01"),
            )
            conn.execute(
                "INSERT OR REPLACE INTO checks VALUES(?,?,?,?,?,?)",
                ("TEST_PEND_D", "PROD_CORRELATION", "PENDING", None, None, "2026-01-01"),
            )
            conn.commit()

            status_d, fails_d = editor.classify_from_checks("TEST_PEND_D", conn)
            assert status_d == "pass", (
                f"Case D FAIL: expected 'pass' for all-PENDING, got {status_d!r}"
            )
            assert fails_d == [], (
                f"Case D FAIL: expected empty fails for all-PENDING, got {fails_d!r}"
            )

            # ---------- Case E: EPSILON floor (LOW_SUB_UNIVERSE_SHARPE 0.0/0.0) ----------
            # Without EPSILON floor: gap = abs(0.0 - 0.0) / max(abs(0.0), 0) → division by zero
            # With EPSILON=0.01: gap = abs(0.0 - 0.0) / max(0.0, 0.01) = 0.0 / 0.01 = 0.0 → NEAR
            # The EPSILON floor prevents a ZeroDivisionError (Pitfall 1)
            conn.execute(
                "INSERT OR IGNORE INTO alphas(alpha_id, expression, status) VALUES(?,?,?)",
                ("TEST_EPS_E", "rank(close)", "fail"),
            )
            conn.execute(
                "INSERT OR REPLACE INTO checks VALUES(?,?,?,?,?,?)",
                ("TEST_EPS_E", "LOW_SUB_UNIVERSE_SHARPE", "FAIL", 0.0, 0.0, "2026-01-01"),
            )
            conn.commit()

            # Must not raise ZeroDivisionError — EPSILON floor guards this
            try:
                status_e, fails_e = editor.classify_from_checks("TEST_EPS_E", conn)
                # With value=0.0, limit=0.0: gap=0.0 → near (not a blocker)
                # The key assertion is that NO ZeroDivisionError occurred
                assert isinstance(status_e, str), (
                    f"Case E FAIL: classify_from_checks returned non-string status {status_e!r}"
                )
            except ZeroDivisionError:
                raise AssertionError(
                    "Case E FAIL: classify_from_checks raised ZeroDivisionError "
                    "for LOW_SUB_UNIVERSE_SHARPE with 0.0/0.0 — EPSILON floor missing"
                )

            # ---------- Case F: 3 numeric fails (D-07 cap exceeded → FAIL) ----------
            conn.execute(
                "INSERT OR IGNORE INTO alphas(alpha_id, expression, status) VALUES(?,?,?)",
                ("TEST_CAP_F", "rank(close)", "fail"),
            )
            for name, val, lim in [
                ("LOW_SHARPE", 1.22, 1.25),
                ("LOW_FITNESS", 0.97, 1.0),
                ("NEGATIVE_MARGIN", 0.97, 1.0),
            ]:
                conn.execute(
                    "INSERT OR REPLACE INTO checks VALUES(?,?,?,?,?,?)",
                    ("TEST_CAP_F", name, "FAIL", val, lim, "2026-01-01"),
                )
            conn.commit()

            status_f, fails_f = editor.classify_from_checks("TEST_CAP_F", conn)
            assert status_f == "fail", (
                f"Case F FAIL: expected 'fail' for 3 numeric fails (D-07 cap), got {status_f!r}"
            )

            # ---------- WARNING 2 / ROADMAP criterion 1: diagnosis persistence ----------
            # Mock _call_llm_editor to return a fixed diagnosis for Case A (NEAR alpha)
            # Verify alphas.diagnosis IS NOT NULL and != "" after diagnose_and_mutate
            fixed_llm_response = {
                "diagnosis": "Alpha has low Sharpe ratio due to high turnover diluting returns.",
                "mutations": [],  # No mutations to avoid operator/field validation complexity
            }
            with mock.patch("editor._call_llm_editor", return_value=fixed_llm_response):
                result_a = editor.diagnose_and_mutate("TEST_NEAR_A", conn)

            # Verify diagnosis was persisted to DB
            row = conn.execute(
                "SELECT diagnosis FROM alphas WHERE alpha_id=?",
                ("TEST_NEAR_A",),
            ).fetchone()
            assert row is not None, "Criterion 1 FAIL: TEST_NEAR_A alpha not found in DB"
            assert row[0] is not None and row[0] != "", (
                f"Criterion 1 FAIL (WARNING 2): diagnosis not persisted to DB; "
                f"got {row[0]!r}. diagnose_and_mutate must UPDATE alphas.diagnosis."
            )
            assert row[0] == fixed_llm_response["diagnosis"], (
                f"Criterion 1 FAIL: wrong diagnosis in DB; "
                f"expected {fixed_llm_response['diagnosis']!r}, got {row[0]!r}"
            )

        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Criterion 1 (supplementary): additional classification cases
# ---------------------------------------------------------------------------


def test_criterion_1_hard_fail_matches_competition() -> None:
    """MATCHES_COMPETITION must always be a hard FAIL regardless of numeric checks."""
    import editor

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_db = _make_test_db(tmpdir)
        conn = db.init_db(tmp_db)
        try:
            conn.execute(
                "INSERT OR IGNORE INTO alphas(alpha_id, expression, status) VALUES(?,?,?)",
                ("TEST_HARD_01", "rank(close)", "fail"),
            )
            conn.execute(
                "INSERT OR REPLACE INTO checks VALUES(?,?,?,?,?,?)",
                ("TEST_HARD_01", "MATCHES_COMPETITION", "FAIL", None, None, "2026-01-01"),
            )
            conn.commit()

            status, fails = editor.classify_from_checks("TEST_HARD_01", conn)
            assert status == "fail", (
                f"Criterion 1 FAIL: expected 'fail' for MATCHES_COMPETITION, got {status!r}"
            )
            assert "MATCHES_COMPETITION" in fails, (
                f"Criterion 1 FAIL: expected MATCHES_COMPETITION in fails, got {fails!r}"
            )
        finally:
            conn.close()


def test_criterion_1_pending_returns_pass() -> None:
    """When only PENDING checks exist (Phase B incomplete), return ('pass', [])."""
    import editor

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_db = _make_test_db(tmpdir)
        conn = db.init_db(tmp_db)
        try:
            conn.execute(
                "INSERT OR IGNORE INTO alphas(alpha_id, expression, status) VALUES(?,?,?)",
                ("TEST_PEND_01", "rank(close)", "grading"),
            )
            conn.execute(
                "INSERT OR REPLACE INTO checks VALUES(?,?,?,?,?,?)",
                ("TEST_PEND_01", "SELF_CORRELATION", "PENDING", None, None, "2026-01-01"),
            )
            conn.execute(
                "INSERT OR REPLACE INTO checks VALUES(?,?,?,?,?,?)",
                ("TEST_PEND_01", "PROD_CORRELATION", "PENDING", None, None, "2026-01-01"),
            )
            conn.commit()

            status, fails = editor.classify_from_checks("TEST_PEND_01", conn)
            assert status == "pass", (
                f"Criterion 1 FAIL: expected 'pass' for all-PENDING, got {status!r}"
            )
            assert fails == [], (
                f"Criterion 1 FAIL: expected empty fails for all-PENDING, got {fails!r}"
            )
        finally:
            conn.close()


def test_criterion_1_too_many_fails() -> None:
    """3 numeric fails even if all within 20% margin → 'fail' (D-07 cap = 2)."""
    import editor

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_db = _make_test_db(tmpdir)
        conn = db.init_db(tmp_db)
        try:
            conn.execute(
                "INSERT OR IGNORE INTO alphas(alpha_id, expression, status) VALUES(?,?,?)",
                ("TEST_CAP_01", "rank(close)", "fail"),
            )
            # All 3 within 5% of limit (< 20% each), but cap says <=2 -> FAIL
            for name, val, lim in [
                ("LOW_SHARPE", 1.22, 1.25),
                ("LOW_FITNESS", 0.97, 1.0),
                ("NEGATIVE_MARGIN", 0.97, 1.0),
            ]:
                conn.execute(
                    "INSERT OR REPLACE INTO checks VALUES(?,?,?,?,?,?)",
                    ("TEST_CAP_01", name, "FAIL", val, lim, "2026-01-01"),
                )
            conn.commit()

            status, fails = editor.classify_from_checks("TEST_CAP_01", conn)
            assert status == "fail", (
                f"Criterion 1 FAIL: expected 'fail' for 3 numeric fails (D-07 cap), got {status!r}"
            )
        finally:
            conn.close()


def test_criterion_1_concentrated_weight_hard_fail() -> None:
    """CONCENTRATED_WEIGHT is a hard fail (D-06) regardless of numeric checks."""
    import editor

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_db = _make_test_db(tmpdir)
        conn = db.init_db(tmp_db)
        try:
            conn.execute(
                "INSERT OR IGNORE INTO alphas(alpha_id, expression, status) VALUES(?,?,?)",
                ("TEST_CONC_01", "rank(close)", "fail"),
            )
            conn.execute(
                "INSERT OR REPLACE INTO checks VALUES(?,?,?,?,?,?)",
                ("TEST_CONC_01", "CONCENTRATED_WEIGHT", "FAIL", None, None, "2026-01-01"),
            )
            conn.commit()

            status, fails = editor.classify_from_checks("TEST_CONC_01", conn)
            assert status == "fail", (
                f"Criterion 1 FAIL: expected 'fail' for CONCENTRATED_WEIGHT, got {status!r}"
            )
            assert "CONCENTRATED_WEIGHT" in fails, (
                f"Criterion 1 FAIL: expected CONCENTRATED_WEIGHT in fails, got {fails!r}"
            )
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Criterion 2: diagnose_and_mutate — mutation lineage (parent_alpha_id pre-set)
# ---------------------------------------------------------------------------


def test_criterion_2_mutation_lineage() -> None:
    """Verify mutation stubs are pre-inserted with parent_alpha_id set at insert time.

    ROADMAP criterion 2: NEAR/FAIL alphas produce at least one mutation with
    parent_alpha_id set at insert time (status=queued). No post-hoc UPDATE needed.

    Strategy: mock _call_llm_editor to return a known valid expression + an invalid
    one. Check the DB directly for inserted mutation stub with parent_alpha_id set.
    """
    import editor

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_db = _make_test_db(tmpdir)
        conn = db.init_db(tmp_db)
        try:
            # Insert a NEAR alpha (LOW_SHARPE within 20%)
            conn.execute(
                "INSERT OR IGNORE INTO alphas(alpha_id, expression, status) VALUES(?,?,?)",
                ("TEST_MUT_SRC", "ts_rank(close,5)", "fail"),
            )
            conn.execute(
                "INSERT OR REPLACE INTO checks VALUES(?,?,?,?,?,?)",
                ("TEST_MUT_SRC", "LOW_SHARPE", "FAIL", 1.22, 1.25, "2026-01-01"),
            )
            conn.commit()

            # Verify parent_alpha_id column exists in schema
            cols = [row[1] for row in conn.execute("PRAGMA table_info(alphas)").fetchall()]
            assert "parent_alpha_id" in cols, (
                "Criterion 2 FAIL: parent_alpha_id column missing from alphas schema"
            )

            # Insert a known valid operator and field into the temp DB catalog
            # so that validate.validate can confirm the mutation expression
            conn.execute(
                "INSERT OR REPLACE INTO operators(name, category) VALUES(?,?)",
                ("ts_mean", "time_series"),
            )
            conn.execute(
                "INSERT OR REPLACE INTO datafields(id, description, dataset, region, universe, delay, type) "
                "VALUES(?,?,?,?,?,?,?)",
                ("close", "close price", "price", "USA", "TOP3000", 1, "MATRIX"),
            )
            conn.commit()

            # Mock _call_llm_editor: return one valid expression + one invalid
            fixed_llm_response = {
                "diagnosis": "Sharpe is marginally below threshold; reduce lookback window.",
                "mutations": [
                    "ts_mean(close,10)",                   # valid: known op + known field
                    "invalid_expr_____UNKNOWN_OP(close,5)",  # invalid: UNKNOWN_OP not in catalog
                ],
            }

            with mock.patch("editor._call_llm_editor", return_value=fixed_llm_response):
                result = editor.diagnose_and_mutate("TEST_MUT_SRC", conn)

            # Verify returned dict structure
            assert "mutations" in result, (
                "Criterion 2 FAIL: result dict missing 'mutations' key"
            )
            assert isinstance(result["mutations"], list), (
                f"Criterion 2 FAIL: mutations is not a list: {result['mutations']!r}"
            )

            # Valid mutation should appear; invalid should be dropped
            assert "ts_mean(close,10)" in result["mutations"], (
                f"Criterion 2 FAIL: valid mutation 'ts_mean(close,10)' not in result: "
                f"{result['mutations']!r}"
            )
            assert not any("UNKNOWN_OP" in m for m in result["mutations"]), (
                f"Criterion 2 FAIL: invalid mutation with UNKNOWN_OP not dropped: "
                f"{result['mutations']!r}"
            )

            # DB check: inserted stub must have parent_alpha_id=TEST_MUT_SRC and status=queued
            stub_rows = conn.execute(
                "SELECT alpha_id, parent_alpha_id, status FROM alphas "
                "WHERE parent_alpha_id=? AND status='queued'",
                ("TEST_MUT_SRC",),
            ).fetchall()
            assert len(stub_rows) >= 1, (
                "Criterion 2 FAIL: no mutation stub found in DB with parent_alpha_id='TEST_MUT_SRC' "
                "and status='queued'. Stub must be pre-inserted before diagnose_and_mutate returns."
            )

            # Confirm parent_alpha_id is set at insert time (not NULL)
            for stub_id, parent_id, stub_status in stub_rows:
                assert parent_id == "TEST_MUT_SRC", (
                    f"Criterion 2 FAIL: stub {stub_id!r} has parent_alpha_id={parent_id!r}, "
                    f"expected 'TEST_MUT_SRC'"
                )
                assert stub_status == "queued", (
                    f"Criterion 2 FAIL: stub {stub_id!r} has status={stub_status!r}, "
                    f"expected 'queued'"
                )

        finally:
            conn.close()


def test_criterion_2_diagnose_and_mutate_structure() -> None:
    """Verify diagnose_and_mutate exists and has correct signature/structure in editor module."""
    import editor
    import inspect

    src = inspect.getsource(editor)

    # Verify the key contract elements are present in source
    assert "def classify_from_checks" in src, "classify_from_checks missing from editor.py"
    assert "def diagnose_and_mutate" in src, "diagnose_and_mutate missing from editor.py"
    assert "parent_alpha_id" in src, "parent_alpha_id lineage missing from editor.py"
    assert "validate.validate" in src, "mutation gate missing from editor.py"
    assert "expr_exists" in src, "dedup gate missing from editor.py"
    assert "401" in src, "401 propagation missing from editor.py"
    assert "diagnosis" in src, "diagnosis column write missing from editor.py"
    assert "queued" in src, "pre-insert status=queued missing from editor.py"
    assert "UPDATE alphas SET diagnosis" in src, "diagnosis UPDATE missing from editor.py"


# ---------------------------------------------------------------------------
# Criterion 3: selfcorr — local PnL-based pre-filter (no BRAIN API calls)
# ---------------------------------------------------------------------------


def test_criterion_3_pearson_prefilter() -> None:
    """Verify local PnL self-corr filter correctly identifies near-identical PnL series.

    ROADMAP criterion 3: Local PnL-based self-corr pre-filter eliminates
    known-duplicate candidates without BRAIN API call.

    Tests:
    - max_pearson(identical, [identical]) returns value close to 1.0
    - max_pearson(orthogonal, [identical]) returns value < 0.5
    - get_selfcorr_limit reads limit from DB (not hardcoded)
    - load_returns: returns daily differences (list of floats, len = pnls-1)
    - No requests.Session usage in the computations (pure compute)
    """
    import selfcorr

    with tempfile.TemporaryDirectory() as tmpdir:
        # Build synthetic PnL files
        # Series A: cumulative PnL [1.0, 1.1, 1.2, 1.3, ...] for 100 days
        dates_a = [f"2024-{(i // 28 + 1):02d}-{(i % 28 + 1):02d}" for i in range(100)]
        pnls_a = [1.0 + i * 0.01 for i in range(100)]

        # Identical series B (perfect correlation = 1.0)
        pnls_b = list(pnls_a)

        # Orthogonal series C: alternating +0.01/-0.01 (near-zero correlation with A)
        pnls_c = [1.0]
        for i in range(99):
            pnls_c.append(pnls_c[-1] + (0.01 if i % 2 == 0 else -0.01))

        path_a = os.path.join(tmpdir, "alpha_a.json")
        path_b = os.path.join(tmpdir, "alpha_b.json")
        path_c = os.path.join(tmpdir, "alpha_c.json")

        with open(path_a, "w") as f:
            json.dump({"pnls": pnls_a, "dates": dates_a}, f)
        with open(path_b, "w") as f:
            json.dump({"pnls": pnls_b, "dates": dates_a}, f)
        with open(path_c, "w") as f:
            json.dump({"pnls": pnls_c, "dates": dates_a}, f)

        # Test max_pearson: identical series should be ~1.0
        corr_identical = selfcorr.max_pearson(path_a, [path_b])
        assert corr_identical > 0.99, (
            f"Criterion 3 FAIL: max_pearson(identical, [identical]) = {corr_identical:.4f}; "
            f"expected > 0.99 (near-identical PnL series should be detected)"
        )

        # Test max_pearson: orthogonal series should be well below 0.5
        corr_orthogonal = selfcorr.max_pearson(path_c, [path_a])
        assert corr_orthogonal < 0.5, (
            f"Criterion 3 FAIL: max_pearson(orthogonal, [identical]) = {corr_orthogonal:.4f}; "
            f"expected < 0.5 (orthogonal PnL should not be flagged as duplicate)"
        )

        # Test load_returns: must return daily differences (list of floats, len = n-1)
        returns_a = selfcorr.load_returns(path_a)
        assert isinstance(returns_a, list), (
            f"Criterion 3 FAIL: load_returns returned {type(returns_a).__name__}, expected list"
        )
        assert len(returns_a) == len(pnls_a) - 1, (
            f"Criterion 3 FAIL: load_returns length={len(returns_a)}, "
            f"expected {len(pnls_a) - 1} (daily differences = pnls-1)"
        )
        # Each element should be a float (daily return = pnls[i] - pnls[i-1])
        for i, r in enumerate(returns_a[:5]):
            assert isinstance(r, float), (
                f"Criterion 3 FAIL: load_returns[{i}] is {type(r).__name__}, expected float"
            )
        # Daily returns from linearly increasing series should all be ~0.01
        assert all(abs(r - 0.01) < 1e-9 for r in returns_a), (
            f"Criterion 3 FAIL: expected all daily returns ~0.01 for linear series, "
            f"got {returns_a[:5]!r}"
        )

    # Test get_selfcorr_limit reads from DB (not hardcoded 0.7)
    with tempfile.TemporaryDirectory() as tmpdir2:
        tmp_db = os.path.join(tmpdir2, "test.db")
        conn = db.init_db(tmp_db)
        try:
            # No SELF_CORRELATION row → should return None (not hardcoded 0.7)
            limit_none = selfcorr.get_selfcorr_limit(conn)
            assert limit_none is None, (
                f"Criterion 3 FAIL: get_selfcorr_limit returned {limit_none!r} "
                f"with no DB row; expected None (not hardcoded)"
            )

            # Insert SELF_CORRELATION check with limit_val=0.7
            conn.execute(
                "INSERT OR REPLACE INTO checks VALUES(?,?,?,?,?,?)",
                ("SOME_ALPHA", "SELF_CORRELATION", "FAIL", 0.75, 0.7, "2026-01-01"),
            )
            conn.commit()

            limit_val = selfcorr.get_selfcorr_limit(conn)
            assert limit_val == 0.7, (
                f"Criterion 3 FAIL: get_selfcorr_limit returned {limit_val!r}; "
                f"expected 0.7 (read from DB, not hardcoded)"
            )
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Criterion 4: FSA mining — motifs, cold-start guard, diversity metric
# ---------------------------------------------------------------------------


def test_criterion_4_fsa_mining() -> None:
    """Verify FSA mines motifs, cold-start guard, filter_candidates, and diversity metric.

    ROADMAP criterion 4: FSA mines motifs from passing alphas; Ideator prompt excludes
    them; diversity metric available.

    Tests:
    - mine_frequent_motifs returns [] below min_samples (cold-start guard)
    - mine_frequent_motifs finds "ts_rank(FIELD,NUM)" from 6 identical ts_rank exprs
    - filter_candidates drops expressions with known-frequent motifs; keeps different ones
    - diversity_metric before/after comparison shows measurable diversity change
    """
    import fsa

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_db = _make_test_db(tmpdir)
        conn = db.init_db(tmp_db)
        try:
            # Cold-start and motif-count assertions require exact control over the
            # PASS-alpha population; a copied live DB already satisfies min_samples.
            conn.execute("DELETE FROM alphas")
            conn.commit()
            # ---------- Cold-start guard: only 4 PASS alphas → mine returns [] ----------
            for i in range(4):
                conn.execute(
                    "INSERT OR IGNORE INTO alphas(alpha_id, expression, status) VALUES(?,?,?)",
                    (f"COLD_{i}", "ts_rank(close,5)", "pass"),
                )
            conn.commit()

            motifs_cold = fsa.mine_frequent_motifs(conn, threshold=0.5, min_samples=5)
            assert motifs_cold == [], (
                f"Criterion 4 FAIL: mine_frequent_motifs with 4 PASS alphas (< min_samples=5) "
                f"returned {motifs_cold!r}; expected [] (cold-start guard)"
            )

            # ---------- 6 PASS alphas using ts_rank → motif should be found ----------
            for i in range(4, 6):
                conn.execute(
                    "INSERT OR IGNORE INTO alphas(alpha_id, expression, status) VALUES(?,?,?)",
                    (f"COLD_{i}", "ts_rank(close,5)", "pass"),
                )
            conn.commit()

            motifs = fsa.mine_frequent_motifs(conn, threshold=0.5, min_samples=5)
            assert "ts_rank(FIELD,NUM)" in motifs, (
                f"Criterion 4 FAIL: mine_frequent_motifs returned {motifs!r}; "
                f"expected 'ts_rank(FIELD,NUM)' (appears in 6/6 = 100% of PASS alphas)"
            )

            # ---------- filter_candidates: drops ts_rank, keeps rank(close) ----------
            candidates = [
                {"expression": "ts_rank(close,5)"},   # contains ts_rank(FIELD,NUM) → DROP
                {"expression": "rank(close)"},         # contains rank(FIELD) → KEEP
            ]
            kept = fsa.filter_candidates(candidates, avoid_motifs=motifs)

            kept_exprs = [c["expression"] for c in kept]
            assert "ts_rank(close,5)" not in kept_exprs, (
                f"Criterion 4 FAIL: ts_rank(close,5) not filtered out; kept={kept_exprs!r}"
            )
            assert "rank(close)" in kept_exprs, (
                f"Criterion 4 FAIL: rank(close) incorrectly filtered out; kept={kept_exprs!r}"
            )

            # ---------- Diversity metric before/after (WARNING 3 / ROADMAP criterion 4) ----------
            # Before: 6 PASS alphas all using ts_rank → top_motif_share near 1.0
            snapshot_before = fsa.diversity_metric(conn)
            assert "top_motif_share" in snapshot_before, (
                f"Criterion 4 FAIL: diversity_metric missing 'top_motif_share' key; "
                f"got {snapshot_before.keys()!r}"
            )
            assert "pass_alpha_count" in snapshot_before, (
                f"Criterion 4 FAIL: diversity_metric missing 'pass_alpha_count' key"
            )
            assert "unique_motifs" in snapshot_before, (
                f"Criterion 4 FAIL: diversity_metric missing 'unique_motifs' key"
            )
            assert snapshot_before["pass_alpha_count"] == 6, (
                f"Criterion 4 FAIL: pass_alpha_count before={snapshot_before['pass_alpha_count']}, "
                f"expected 6"
            )

            # Insert 4 more PASS alphas with rank(close) (different structural motif)
            for i in range(4):
                conn.execute(
                    "INSERT OR IGNORE INTO alphas(alpha_id, expression, status) VALUES(?,?,?)",
                    (f"RANK_{i}", "rank(close)", "pass"),
                )
            conn.commit()

            snapshot_after = fsa.diversity_metric(conn)
            assert snapshot_after["pass_alpha_count"] == 10, (
                f"Criterion 4 FAIL: pass_alpha_count after={snapshot_after['pass_alpha_count']}, "
                f"expected 10"
            )
            # Top-motif concentration should drop after adding structurally diverse alphas
            assert snapshot_before["top_motif_share"] > snapshot_after["top_motif_share"], (
                f"Criterion 4 FAIL: top_motif_share did not decrease after adding diverse alphas; "
                f"before={snapshot_before['top_motif_share']:.3f}, "
                f"after={snapshot_after['top_motif_share']:.3f}"
            )

            # ---------- Empty DB: diversity_metric returns zero-count dict ----------
            with tempfile.TemporaryDirectory() as tmpdir2:
                fresh_db = os.path.join(tmpdir2, "fresh.db")
                fresh_conn = db.init_db(fresh_db)
                try:
                    empty_metric = fsa.diversity_metric(fresh_conn)
                    assert empty_metric["pass_alpha_count"] == 0, (
                        f"Criterion 4 FAIL: diversity_metric on fresh DB returned "
                        f"pass_alpha_count={empty_metric['pass_alpha_count']}, expected 0"
                    )
                finally:
                    fresh_conn.close()

        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Criterion 3 (supplementary): db.py — diagnosis column
# ---------------------------------------------------------------------------


def test_criterion_3_db_diagnosis_column() -> None:
    """Verify db.py adds diagnosis TEXT column and upsert_alpha can write to it."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_db = os.path.join(tmpdir, "test.db")
        conn = db.init_db(tmp_db)
        try:
            cols = [row[1] for row in conn.execute("PRAGMA table_info(alphas)").fetchall()]
            assert "diagnosis" in cols, (
                f"Criterion 3 FAIL: diagnosis column missing from alphas table; columns: {cols}"
            )

            # Verify upsert_alpha can write diagnosis
            db.upsert_alpha(conn, {
                "alpha_id": "TEST_DIAG_01",
                "expression": "ts_rank(close,5)",
                "status": "pass",
                "diagnosis": "test diagnosis string",
            })
            row = conn.execute(
                "SELECT diagnosis FROM alphas WHERE alpha_id=?", ("TEST_DIAG_01",)
            ).fetchone()
            assert row is not None, "Criterion 3 FAIL: inserted alpha not found"
            assert row[0] == "test diagnosis string", (
                f"Criterion 3 FAIL: expected 'test diagnosis string', got {row[0]!r}"
            )
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------


def test_editor_module_constants() -> None:
    """Verify HARD_FAIL_CHECKS and EPSILON are present with correct values."""
    import editor

    assert hasattr(editor, "HARD_FAIL_CHECKS"), "HARD_FAIL_CHECKS constant missing"
    assert hasattr(editor, "EPSILON"), "EPSILON constant missing"
    assert "MATCHES_COMPETITION" in editor.HARD_FAIL_CHECKS
    assert "CONCENTRATED_WEIGHT" in editor.HARD_FAIL_CHECKS
    assert editor.EPSILON == 0.01, f"Expected EPSILON=0.01, got {editor.EPSILON}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    tests = [
        test_criterion_1_near_classification,
        test_criterion_1_hard_fail_matches_competition,
        test_criterion_1_pending_returns_pass,
        test_criterion_1_too_many_fails,
        test_criterion_1_concentrated_weight_hard_fail,
        test_criterion_2_mutation_lineage,
        test_criterion_2_diagnose_and_mutate_structure,
        test_criterion_3_pearson_prefilter,
        test_criterion_4_fsa_mining,
        test_criterion_3_db_diagnosis_column,
        test_editor_module_constants,
    ]
    passed = 0
    failed = 0
    errors = []
    for test_fn in tests:
        try:
            test_fn()
            print(f"  PASS: {test_fn.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL: {test_fn.__name__}: {exc}")
            failed += 1
            errors.append((test_fn.__name__, str(exc)))

    print(f"\n{passed} passed, {failed} failed")
    if errors:
        sys.exit(1)
