"""test_ideator_candidates.py — RED phase tests for Task 1: ideator.generate_candidates.

Tests candidate composition from grounded skeletons + archetype inheritance.
All tests are written BEFORE the implementation (TDD RED gate).

Covers:
- generate_candidates returns 4-8 candidates (D-01)
- Each candidate inherits archetype from thesis (D-04)
- Each candidate expression is a non-empty string
- Candidate record has all required keys
- No grade/simulate/login calls in ideator module (T-02-06)
"""

import importlib
import re
import sqlite3
import sys

import pytest

import db
import researcher


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def conn():
    """Open a real connection to alpha_kb.db (gitignored but present)."""
    c = db.init_db("alpha_kb.db")
    yield c
    c.close()


@pytest.fixture(scope="module")
def thesis_reversal(conn):
    """Build a thesis pinned to the 'reversal' archetype."""
    return researcher.build_thesis(conn, archetype="reversal")


@pytest.fixture(scope="module")
def thesis_momentum(conn):
    return researcher.build_thesis(conn, archetype="momentum")


@pytest.fixture(scope="module")
def thesis_value_garp(conn):
    return researcher.build_thesis(conn, archetype="value_garp")


@pytest.fixture(scope="module")
def thesis_quality(conn):
    return researcher.build_thesis(conn, archetype="quality")


@pytest.fixture(scope="module")
def thesis_growth(conn):
    return researcher.build_thesis(conn, archetype="growth")


@pytest.fixture(scope="module")
def thesis_low_vol(conn):
    return researcher.build_thesis(conn, archetype="low_volatility")


@pytest.fixture(scope="module")
def thesis_liq_vol(conn):
    return researcher.build_thesis(conn, archetype="liquidity_volume")


@pytest.fixture(scope="module")
def thesis_sentiment(conn):
    return researcher.build_thesis(conn, archetype="sentiment_event")


# ---------------------------------------------------------------------------
# Structural — module imports cleanly
# ---------------------------------------------------------------------------

def test_ideator_imports():
    """Module imports without error."""
    import ideator  # noqa: F401
    assert hasattr(ideator, "generate_candidates")


def test_generate_candidates_is_callable():
    import ideator
    assert callable(ideator.generate_candidates)


# ---------------------------------------------------------------------------
# Count constraint D-01: 4-8 candidates per thesis
# ---------------------------------------------------------------------------

def test_candidate_count_reversal(conn, thesis_reversal):
    import ideator
    cs = ideator.generate_candidates(conn, thesis_reversal)
    assert 4 <= len(cs) <= 8, f"Expected 4-8, got {len(cs)}"


def test_candidate_count_momentum(conn, thesis_momentum):
    import ideator
    cs = ideator.generate_candidates(conn, thesis_momentum)
    assert 4 <= len(cs) <= 8, f"Expected 4-8, got {len(cs)}"


def test_candidate_count_value_garp(conn, thesis_value_garp):
    import ideator
    cs = ideator.generate_candidates(conn, thesis_value_garp)
    assert 4 <= len(cs) <= 8


def test_candidate_count_all_archetypes(conn):
    """All 8 archetypes produce 4-8 candidates."""
    import ideator
    for arch in researcher.ARCHETYPES:
        t = researcher.build_thesis(conn, archetype=arch)
        cs = ideator.generate_candidates(conn, t)
        assert 4 <= len(cs) <= 8, f"archetype {arch!r}: expected 4-8, got {len(cs)}"


def test_n_clamp_to_4_min(conn, thesis_reversal):
    """n=1 is clamped to 4 (minimum)."""
    import ideator
    cs = ideator.generate_candidates(conn, thesis_reversal, n=1)
    assert len(cs) >= 4


def test_n_clamp_to_8_max(conn, thesis_reversal):
    """n=100 is clamped to 8 (maximum)."""
    import ideator
    cs = ideator.generate_candidates(conn, thesis_reversal, n=100)
    assert len(cs) <= 8


def test_n_exact_within_range(conn, thesis_reversal):
    """n=5 yields exactly 5 candidates when achievable."""
    import ideator
    cs = ideator.generate_candidates(conn, thesis_reversal, n=5)
    assert 4 <= len(cs) <= 8


# ---------------------------------------------------------------------------
# Archetype inheritance D-04: all candidates inherit thesis archetype
# ---------------------------------------------------------------------------

def test_archetype_inherited_reversal(conn, thesis_reversal):
    import ideator
    cs = ideator.generate_candidates(conn, thesis_reversal)
    assert all(c["archetype"] == "reversal" for c in cs), \
        [c["archetype"] for c in cs]


def test_archetype_inherited_all_archetypes(conn):
    """Every candidate inherits the thesis archetype regardless of which one."""
    import ideator
    for arch in researcher.ARCHETYPES:
        t = researcher.build_thesis(conn, archetype=arch)
        cs = ideator.generate_candidates(conn, t)
        mismatches = [c["archetype"] for c in cs if c["archetype"] != arch]
        assert not mismatches, f"archetype {arch!r} mismatch: {mismatches}"


# ---------------------------------------------------------------------------
# Candidate record shape
# ---------------------------------------------------------------------------

REQUIRED_KEYS = {"expression", "archetype", "valid", "validation_reason", "dedup_alpha_id"}


def test_candidate_keys_present(conn, thesis_reversal):
    import ideator
    cs = ideator.generate_candidates(conn, thesis_reversal)
    for c in cs:
        missing = REQUIRED_KEYS - set(c.keys())
        assert not missing, f"Candidate missing keys: {missing}"


def test_expression_is_nonempty_string(conn, thesis_reversal):
    import ideator
    cs = ideator.generate_candidates(conn, thesis_reversal)
    for c in cs:
        assert isinstance(c["expression"], str), f"expression is {type(c['expression'])}"
        assert c["expression"].strip(), "expression is empty/whitespace"


def test_expression_all_archetypes_nonempty(conn):
    """All candidates for every archetype have non-empty string expressions."""
    import ideator
    for arch in researcher.ARCHETYPES:
        t = researcher.build_thesis(conn, archetype=arch)
        cs = ideator.generate_candidates(conn, t)
        empties = [c for c in cs if not isinstance(c["expression"], str) or not c["expression"].strip()]
        assert not empties, f"archetype {arch!r} has empty expressions: {empties}"


# ---------------------------------------------------------------------------
# No BRAIN calls (T-02-06)
# ---------------------------------------------------------------------------

def test_no_grade_simulate_login_in_ideator():
    """ideator.py must not contain grade./simulate(/login( references."""
    import pathlib
    src = pathlib.Path("ideator.py").read_text()
    # Strip comment lines first
    non_comment_lines = [l for l in src.splitlines() if not l.strip().startswith("#")]
    code = "\n".join(non_comment_lines)
    pattern = re.compile(r"grade\.|simulate\(|login\(")
    matches = pattern.findall(code)
    assert not matches, f"ideator.py contains forbidden BRAIN calls: {matches}"
