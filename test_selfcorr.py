"""test_selfcorr.py — TDD tests for selfcorr.py (03-02 plan).

Task 1 behavior tests:
  - fetch_and_cache_pnl 401 propagates
  - fetch_and_cache_pnl 500 returns None
  - fetch_and_cache_pnl success writes file + updates DB + returns path
  - load_returns produces correct daily returns from cumulative pnls
  - load_returns on 3-year data truncates to last 2 years
  - _pearson([1,2,3],[1,2,3]) == 1.0
  - _pearson([1.0],[1.0]) == 0.0  (insufficient data guard)

Task 2 behavior tests (structural + functional):
  - All 8 public functions present
  - get_selfcorr_limit never hardcodes 0.7
  - proxy_gate returns False on degradation paths
  - backfill_active_pnl prints WARNING when zero reference PnLs after backfill
"""

import json
import math
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db():
    """In-memory SQLite with alphas + checks tables."""
    conn = sqlite3.connect(":memory:")
    conn.execute("""CREATE TABLE alphas (
        alpha_id TEXT PRIMARY KEY, expression TEXT, parent_alpha_id TEXT,
        archetype TEXT, region TEXT, universe TEXT, delay INTEGER,
        decay INTEGER, neutralization TEXT, truncation REAL, settings_json TEXT,
        sharpe REAL, fitness REAL, turnover REAL, returns REAL, drawdown REAL,
        margin REAL, long_count INTEGER, short_count INTEGER,
        self_corr REAL, prod_corr REAL, corr_checked_at TEXT, pnl_path TEXT,
        status TEXT, run_id TEXT, created_at TEXT
    )""")
    conn.execute("""CREATE TABLE checks (
        alpha_id TEXT, name TEXT, result TEXT, value REAL, limit_val REAL,
        checked_at TEXT, PRIMARY KEY (alpha_id, name)
    )""")
    conn.commit()
    return conn


def _make_http_error(status_code: int):
    """Build a requests.HTTPError with a fake response."""
    import requests
    resp = MagicMock()
    resp.status_code = status_code
    err = requests.exceptions.HTTPError(response=resp)
    err.response = resp
    return err


def _write_pnl_json(tmp_dir: str, alpha_id: str, pnls: list, dates: list) -> str:
    path = Path(tmp_dir) / f"{alpha_id}.json"
    path.write_text(json.dumps({"pnls": pnls, "dates": dates}))
    return str(path)


# ---------------------------------------------------------------------------
# Task 1 tests: PnL fetch, caching, and returns conversion
# ---------------------------------------------------------------------------

class TestFetchAndCachePnl(unittest.TestCase):

    def test_401_propagates(self):
        """fetch_and_cache_pnl must re-raise 401 HTTPError (auth expiry)."""
        import selfcorr
        import requests

        client = MagicMock()
        client.get_pnl.side_effect = _make_http_error(401)
        conn = _make_db()

        with self.assertRaises(requests.exceptions.HTTPError):
            selfcorr.fetch_and_cache_pnl(client, "abc", conn)

    def test_500_returns_none(self):
        """fetch_and_cache_pnl must return None on non-401 HTTP errors (graceful degrade D-13)."""
        import selfcorr

        client = MagicMock()
        client.get_pnl.side_effect = _make_http_error(500)
        conn = _make_db()

        result = selfcorr.fetch_and_cache_pnl(client, "abc", conn)
        self.assertIsNone(result)

    def test_success_writes_file_and_updates_db(self):
        """fetch_and_cache_pnl writes JSON to pnl_cache, updates pnl_path, returns path."""
        import selfcorr

        pnls = [0.0, 0.001, 0.003, 0.006]
        dates = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
        client = MagicMock()
        client.get_pnl.return_value = {"pnls": pnls, "dates": dates}

        conn = _make_db()
        conn.execute("INSERT INTO alphas (alpha_id, expression) VALUES (?, ?)",
                     ("abc123", "test_expr"))
        conn.commit()

        with tempfile.TemporaryDirectory() as tmp:
            result = selfcorr.fetch_and_cache_pnl(client, "abc123", conn, pnl_dir=tmp)

        self.assertIsNotNone(result)
        self.assertIn("abc123", result)

        row = conn.execute("SELECT pnl_path FROM alphas WHERE alpha_id='abc123'").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], result)


class TestLoadReturns(unittest.TestCase):

    def test_basic_cumulative_to_daily(self):
        """load_returns converts 4 cumulative values to 3 daily returns."""
        import selfcorr

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            json.dump({
                "pnls": [0.0, 0.001, 0.003, 0.006],
                "dates": ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
            }, f)
            fname = f.name

        try:
            returns = selfcorr.load_returns(fname)
            self.assertEqual(len(returns), 3)
        finally:
            os.unlink(fname)

    def test_truncates_to_last_2_years(self):
        """load_returns on 3-year data keeps only last 2 years."""
        import selfcorr
        from datetime import date, timedelta

        # Build 3 years of daily data (~1095 rows)
        start = date(2021, 1, 4)
        dates = []
        pnls = []
        val = 0.0
        for i in range(1095):
            d = start + timedelta(days=i)
            dates.append(d.strftime("%Y-%m-%d"))
            pnls.append(val)
            val += 0.001

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            json.dump({"pnls": pnls, "dates": dates}, f)
            fname = f.name

        try:
            returns = selfcorr.load_returns(fname)
            # Should be ~730 days filtered then length-1 diffs
            # Exact count depends on calendar; just check it's < total and > 700
            self.assertLess(len(returns), 1094)
            self.assertGreater(len(returns), 700)
        finally:
            os.unlink(fname)


class TestPearson(unittest.TestCase):

    def test_perfect_positive_correlation(self):
        """_pearson([1,2,3],[1,2,3]) == 1.0."""
        from selfcorr import _pearson
        result = _pearson([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])
        self.assertAlmostEqual(result, 1.0, places=9)

    def test_insufficient_data_returns_zero(self):
        """_pearson on single-element lists returns 0.0."""
        from selfcorr import _pearson
        result = _pearson([1.0], [1.0])
        self.assertEqual(result, 0.0)

    def test_perfect_positive_scaled(self):
        """_pearson([1,2,3,4,5],[2,4,6,8,10]) == 1.0."""
        from selfcorr import _pearson
        result = _pearson([1.0, 2.0, 3.0, 4.0, 5.0], [2.0, 4.0, 6.0, 8.0, 10.0])
        self.assertAlmostEqual(result, 1.0, places=9)

    def test_empty_returns_zero(self):
        """_pearson on empty lists returns 0.0."""
        from selfcorr import _pearson
        self.assertEqual(_pearson([], []), 0.0)

    def test_constant_returns_zero(self):
        """_pearson where one series is constant returns 0.0 (zero stddev guard)."""
        from selfcorr import _pearson
        self.assertEqual(_pearson([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]), 0.0)


# ---------------------------------------------------------------------------
# Task 2 tests: Reference set, gate functions, backfill
# ---------------------------------------------------------------------------

class TestStructure(unittest.TestCase):

    def test_all_public_functions_present(self):
        """All 8 required public functions must exist in selfcorr."""
        import selfcorr
        required = [
            "fetch_and_cache_pnl", "load_returns", "max_pearson",
            "get_selfcorr_limit", "get_reference_pnl_paths",
            "backfill_active_pnl", "is_duplicate_by_pnl", "proxy_gate",
        ]
        for fn in required:
            self.assertTrue(hasattr(selfcorr, fn), f"Missing: {fn}")

    def test_no_hardcoded_0_7(self):
        """get_selfcorr_limit must not return a hardcoded 0.7 — must read from DB."""
        import inspect
        import selfcorr
        # Verify the function reads from DB: with empty DB it should return None
        conn = _make_db()
        result = selfcorr.get_selfcorr_limit(conn)
        self.assertIsNone(result, "get_selfcorr_limit should return None when DB has no row, "
                          "not a hardcoded 0.7")
        # Also verify the function body does not contain a literal '0.7' return statement
        fn_src = inspect.getsource(selfcorr.get_selfcorr_limit)
        import re
        # Match "return 0.7" or "return(0.7)" style patterns only (not docstring mentions)
        hardcoded = re.search(r'\breturn\s+0\.7\b', fn_src)
        self.assertIsNone(hardcoded, "get_selfcorr_limit contains a hardcoded 'return 0.7'")

    def test_empty_ref_set_warning_in_backfill(self):
        """backfill_active_pnl source must contain zero reference PnLs warning."""
        import inspect
        import selfcorr
        src = inspect.getsource(selfcorr.backfill_active_pnl)
        self.assertIn("zero reference PnLs", src,
                      "Missing WARNING about zero reference PnLs in backfill_active_pnl")


class TestGetSelfcorrLimit(unittest.TestCase):

    def test_reads_from_db(self):
        """get_selfcorr_limit returns limit_val from checks table."""
        import selfcorr
        conn = _make_db()
        conn.execute(
            "INSERT INTO checks (alpha_id, name, result, value, limit_val) VALUES (?,?,?,?,?)",
            ("xAndqLYJ", "SELF_CORRELATION", "FAIL", 0.89, 0.7)
        )
        conn.commit()
        result = selfcorr.get_selfcorr_limit(conn)
        self.assertAlmostEqual(result, 0.7)

    def test_returns_none_when_no_row(self):
        """get_selfcorr_limit returns None when no SELF_CORRELATION row exists."""
        import selfcorr
        conn = _make_db()
        result = selfcorr.get_selfcorr_limit(conn)
        self.assertIsNone(result)


class TestGetReferencePnlPaths(unittest.TestCase):

    def test_returns_pass_and_active_paths(self):
        """get_reference_pnl_paths returns pnl_path for PASS and ACTIVE alphas only."""
        import selfcorr
        conn = _make_db()
        conn.executemany(
            "INSERT INTO alphas (alpha_id, expression, status, pnl_path) VALUES (?,?,?,?)",
            [
                ("a1", "expr1", "pass", "/cache/a1.json"),
                ("a2", "expr2", "ACTIVE", "/cache/a2.json"),
                ("a3", "expr3", "fail", "/cache/a3.json"),  # excluded
                ("a4", "expr4", "pass", None),               # excluded (no pnl_path)
            ]
        )
        conn.commit()
        paths = selfcorr.get_reference_pnl_paths(conn)
        self.assertIn("/cache/a1.json", paths)
        self.assertIn("/cache/a2.json", paths)
        self.assertNotIn("/cache/a3.json", paths)
        self.assertEqual(len(paths), 2)


class TestProxyGate(unittest.TestCase):

    def test_returns_false_when_no_pnl_path(self):
        """proxy_gate returns False (allow) when parent has no pnl_path (graceful degrade D-13)."""
        import selfcorr
        conn = _make_db()
        conn.execute(
            "INSERT INTO alphas (alpha_id, expression, status, pnl_path) VALUES (?,?,?,?)",
            ("parent1", "expr", "pass", None)
        )
        conn.commit()
        result = selfcorr.proxy_gate("parent1", conn)
        self.assertFalse(result)

    def test_returns_false_when_no_limit(self):
        """proxy_gate returns False when get_selfcorr_limit returns None (graceful degrade)."""
        import selfcorr
        conn = _make_db()
        with tempfile.TemporaryDirectory() as tmp:
            pnl_file = _write_pnl_json(tmp, "parent1",
                                       [0.0, 0.001, 0.003],
                                       ["2024-01-02", "2024-01-03", "2024-01-04"])
            conn.execute(
                "INSERT INTO alphas (alpha_id, expression, status, pnl_path) VALUES (?,?,?,?)",
                ("parent1", "expr", "pass", pnl_file)
            )
            conn.commit()
            result = selfcorr.proxy_gate("parent1", conn)
        self.assertFalse(result)

    def test_returns_false_on_exception(self):
        """proxy_gate returns False on any exception (never blocks grading)."""
        import selfcorr
        result = selfcorr.proxy_gate("nonexistent_id", None)
        self.assertFalse(result)


class TestIsDuplicateByPnl(unittest.TestCase):

    def test_above_limit_is_duplicate(self):
        """is_duplicate_by_pnl returns True when max_pearson >= limit_val."""
        import selfcorr
        from datetime import date, timedelta

        with tempfile.TemporaryDirectory() as tmp:
            base = date(2024, 1, 2)
            # Use 70 dates to exceed the 60-day overlap threshold in _date_overlap_returns
            dates = [(base + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(70)]
            pnls = [float(i) * 0.001 for i in range(70)]

            path_a = _write_pnl_json(tmp, "a", pnls, dates)
            path_b = _write_pnl_json(tmp, "b", pnls, dates)  # identical → corr=1.0

            result = selfcorr.is_duplicate_by_pnl(path_a, [path_b], limit_val=0.7)
            self.assertTrue(result)

    def test_below_limit_not_duplicate(self):
        """is_duplicate_by_pnl returns False when max_pearson < limit_val."""
        import selfcorr
        from datetime import date, timedelta

        with tempfile.TemporaryDirectory() as tmp:
            base = date(2024, 1, 2)
            # Use 70 dates to exceed the 60-day overlap threshold in _date_overlap_returns
            dates = [(base + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(70)]
            pnls_a = [float(i) * 0.001 for i in range(70)]
            pnls_b = [float(70 - i) * 0.001 for i in range(70)]  # anti-correlated

            path_a = _write_pnl_json(tmp, "a", pnls_a, dates)
            path_b = _write_pnl_json(tmp, "b", pnls_b, dates)

            result = selfcorr.is_duplicate_by_pnl(path_a, [path_b], limit_val=0.7)
            self.assertFalse(result)


class TestBackfillActivePnl(unittest.TestCase):

    def test_401_propagates(self):
        """backfill_active_pnl propagates 401 from fetch_and_cache_pnl."""
        import selfcorr
        import requests

        conn = _make_db()
        conn.execute(
            "INSERT INTO alphas (alpha_id, expression, status, pnl_path) VALUES (?,?,?,?)",
            ("active1", "expr", "ACTIVE", None)
        )
        conn.commit()

        client = MagicMock()
        client.get_pnl.side_effect = _make_http_error(401)

        with self.assertRaises(requests.exceptions.HTTPError):
            selfcorr.backfill_active_pnl(client, conn)

    def test_non_401_errors_skipped(self):
        """backfill_active_pnl skips non-401 errors and returns count=0."""
        import selfcorr

        conn = _make_db()
        conn.execute(
            "INSERT INTO alphas (alpha_id, expression, status, pnl_path) VALUES (?,?,?,?)",
            ("active1", "expr", "ACTIVE", None)
        )
        conn.commit()

        client = MagicMock()
        client.get_pnl.side_effect = _make_http_error(503)

        count = selfcorr.backfill_active_pnl(client, conn)
        self.assertEqual(count, 0)

    def test_warning_when_zero_references(self):
        """backfill_active_pnl prints WARNING when no reference PnLs available after backfill."""
        import selfcorr
        import io
        import sys

        conn = _make_db()
        conn.execute(
            "INSERT INTO alphas (alpha_id, expression, status, pnl_path) VALUES (?,?,?,?)",
            ("active1", "expr", "ACTIVE", None)
        )
        conn.commit()

        # Client fails with 500 → graceful degrade → pnl_path stays NULL → 0 references
        client = MagicMock()
        client.get_pnl.side_effect = _make_http_error(500)

        captured = io.StringIO()
        with patch("sys.stdout", captured):
            selfcorr.backfill_active_pnl(client, conn)

        output = captured.getvalue()
        self.assertIn("zero reference PnLs", output)

    def test_success_returns_count(self):
        """backfill_active_pnl returns number of successfully fetched PnL records."""
        import selfcorr

        conn = _make_db()
        conn.executemany(
            "INSERT INTO alphas (alpha_id, expression, status, pnl_path) VALUES (?,?,?,?)",
            [
                ("a1", "expr1", "ACTIVE", None),
                ("a2", "expr2", "ACTIVE", None),
            ]
        )
        conn.commit()

        pnls = [0.0, 0.001, 0.003]
        dates = ["2024-01-02", "2024-01-03", "2024-01-04"]
        client = MagicMock()
        client.get_pnl.return_value = {"pnls": pnls, "dates": dates}

        with tempfile.TemporaryDirectory() as tmp:
            count = selfcorr.backfill_active_pnl(client, conn, pnl_dir=tmp)

        self.assertEqual(count, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
