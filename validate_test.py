"""validate_test.py — Self-contained tests for validate.py.

Uses an in-memory SQLite database seeded with known operators and datafields.
No pytest dependency — run directly: python validate_test.py

Expected output: ALL VALIDATE TESTS PASSED
"""

import sqlite3
import sys

from validate import validate


# ---------------------------------------------------------------------------
# Test database setup
# ---------------------------------------------------------------------------

def make_test_conn() -> sqlite3.Connection:
    """Return an in-memory SQLite connection seeded with test catalog rows."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE operators (
            name TEXT PRIMARY KEY, category TEXT, definition TEXT, signature TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE datafields (
            id TEXT, description TEXT, dataset TEXT, region TEXT,
            universe TEXT, delay INTEGER, type TEXT,
            PRIMARY KEY (id, region, universe, delay, dataset)
        )"""
    )
    # Seed operators
    operators = [
        ("rank",    "cross-sectional", None, None),
        ("add",     "arithmetic",      None, None),
        ("ts_mean", "time-series",     None, None),
    ]
    conn.executemany(
        "INSERT INTO operators (name, category, definition, signature) VALUES (?, ?, ?, ?)",
        operators,
    )
    # Seed datafields — minimal required columns for the PRIMARY KEY constraint
    datafields = [
        ("returns", None, "fundamental", "USA", "TOP3000", 1, "MATRIX"),
        ("close",   None, "price",       "USA", "TOP3000", 1, "MATRIX"),
    ]
    conn.executemany(
        "INSERT INTO datafields (id, description, dataset, region, universe, delay, type) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        datafields,
    )
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def assert_valid(conn: sqlite3.Connection, expr: str, label: str) -> None:
    ok, reason = validate(conn, expr)
    if not ok:
        print(f"FAIL [{label}]: expected valid, got (False, {reason!r})")
        sys.exit(1)


def assert_invalid(
    conn: sqlite3.Connection,
    expr: str,
    label: str,
    reason_contains: str,
) -> None:
    ok, reason = validate(conn, expr)
    if ok:
        print(f"FAIL [{label}]: expected invalid, got (True, '')")
        sys.exit(1)
    if reason_contains.lower() not in reason.lower():
        print(
            f"FAIL [{label}]: reason {reason!r} does not contain {reason_contains!r}"
        )
        sys.exit(1)


# ---------------------------------------------------------------------------
# Test cases — directly mirror the <behavior> block in 01-03-PLAN.md
# ---------------------------------------------------------------------------

def run_tests() -> None:
    conn = make_test_conn()

    # 1. Known operator + known field → valid
    assert_valid(conn, "rank(returns)", "basic valid expression")

    # 2. Unknown operator → invalid with correct reason
    assert_invalid(conn, "bad_op(returns)", "unknown operator", "unknown operator")

    # 3. Unbalanced parentheses → invalid BEFORE any DB query
    assert_invalid(conn, "rank(returns", "unbalanced parens", "unbalanced parentheses")

    # 4. Empty string → invalid
    assert_invalid(conn, "", "empty string", "empty")

    # 5. Whitespace-only → invalid
    assert_invalid(conn, "   ", "whitespace only", "empty")

    # 6. Bare field reference with no function call → valid
    assert_valid(conn, "returns", "bare field reference")

    # 7. Known operator + unknown field → invalid
    assert_invalid(conn, "rank(bad_field)", "unknown field", "unknown data field")

    # 8. Nested multi-operator expression with all tokens present → valid
    assert_valid(
        conn,
        "add(rank(returns), ts_mean(returns, 5))",
        "nested multi-operator valid",
    )

    # 9. Numeric literal inside expression — should not be treated as a field
    #    e.g. "ts_mean(close, 20) - 1"; "5" and "20" are numeric-ish but the
    #    regex r'[A-Za-z_][A-Za-z0-9_]*' only matches identifiers starting with
    #    a letter/underscore, so pure digits are never extracted. Verify no false
    #    rejection from literals in a realistic expression.
    assert_valid(conn, "close / ts_mean(close, 20)", "numeric literal in expression")

    # 10. Keyword tokens (Python keywords in exclusion set) are not checked as fields
    #     e.g. if someone writes "rank(returns) and returns" — "and" must not be
    #     sent to the datafields table.
    assert_valid(conn, "rank(returns) and returns", "keyword exclusion: and")

    print("ALL VALIDATE TESTS PASSED")


if __name__ == "__main__":
    run_tests()
