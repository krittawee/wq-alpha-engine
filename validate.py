"""validate.py — Local expression validator against the synced SQLite catalog.

Checks operators and data-fields before any simulation slot is spent.
No BRAIN API call is made — purely local against the sqlite3 connection.

Public API:
    validate(conn, expression) -> tuple[bool, str]
"""

import re
import sqlite3
from typing import Optional


# Python keywords and reserved names that should not be treated as data-field tokens
_EXCLUSIONS: frozenset = frozenset({
    "if", "else", "elif", "and", "or", "not", "in", "is",
    "True", "False", "None", "for", "while", "return",
    "lambda", "def", "class", "import", "from", "as",
})


def validate(conn: sqlite3.Connection, expression: str) -> tuple[bool, str]:
    """Return (True, '') if expression is locally valid, else (False, reason).

    Checks performed (in order — fail fast):
    1. Empty expression check.
    2. Bracket balance check.
    3. Operator token validation against operators table.
    4. Data-field token validation against datafields table.

    No BRAIN API call is made. The operators table may be empty if the catalog
    has not been synced yet — in that case all operator tokens will fail (correct
    behaviour: sync must run before grade).

    SQL queries use parameterized statements only — never string-interpolated SQL.
    """
    # Step 1 — Empty check
    if not expression.strip():
        return False, "empty expression"

    # Step 2 — Bracket balance
    if expression.count("(") != expression.count(")"):
        return False, "unbalanced parentheses"

    # Step 3 — Operator token detection
    # All tokens that appear immediately before "(" are treated as function calls.
    operator_tokens: set[str] = set(
        re.findall(r'([A-Za-z_][A-Za-z0-9_]*)\s*\(', expression)
    )

    # Step 4 — Validate each operator token against the operators table
    for token in operator_tokens:
        row = conn.execute(
            "SELECT 1 FROM operators WHERE name=? LIMIT 1", (token,)
        ).fetchone()
        if row is None:
            return False, f"unknown operator: {token}"

    # Step 5 — Data-field token detection
    # Extract variable names from assignment statements (e.g. "vol = rank(...);\n")
    # so that user-defined variable names are not mistaken for datafield references.
    assigned_vars: set[str] = set(
        re.findall(r'^([A-Za-z_][A-Za-z0-9_]*)\s*=', expression, re.MULTILINE)
    )

    # All word tokens that are NOT function-call tokens, NOT excluded keywords,
    # and NOT user-defined variable names are treated as data-field references.
    all_tokens: list[str] = re.findall(r'[A-Za-z_][A-Za-z0-9_]*', expression)
    bare_field_tokens: set[str] = {
        t for t in all_tokens
        if t not in operator_tokens and t not in _EXCLUSIONS and t not in assigned_vars
    }

    # Step 6 — Validate each bare field token against the datafields table
    for token in bare_field_tokens:
        row = conn.execute(
            "SELECT 1 FROM datafields WHERE id=? LIMIT 1", (token,)
        ).fetchone()
        if row is None:
            return False, f"unknown data field: {token}"

    # Step 7 — All checks passed
    return True, ""
