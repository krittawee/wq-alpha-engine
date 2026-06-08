"""TDD tests for researcher.py — Task 2: deterministic archetype selection + thesis assembly.

RED phase: select_archetype and build_thesis already exist (in researcher.py from Task 1),
but these tests verify their correctness guarantees in detail.
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

VALID_LABELS = {
    "reversal", "momentum", "value_garp", "quality",
    "growth", "low_volatility", "liquidity_volume", "sentiment_event",
}


def test_select_archetype_exists():
    """select_archetype function must exist in researcher module."""
    import researcher
    assert hasattr(researcher, "select_archetype"), "select_archetype not found"


def test_build_thesis_exists():
    """build_thesis function must exist in researcher module."""
    import researcher
    assert hasattr(researcher, "build_thesis"), "build_thesis not found"


def test_select_archetype_returns_valid_label():
    """select_archetype must return one of the 8 taxonomy labels."""
    import researcher
    import db
    conn = db.init_db("alpha_kb.db")
    try:
        label = researcher.select_archetype(conn)
        assert label in VALID_LABELS, f"Got invalid label: {label!r}"
    finally:
        conn.close()


def test_select_archetype_deterministic():
    """Same DB state must yield the same archetype on repeated calls."""
    import researcher
    import db
    conn = db.init_db("alpha_kb.db")
    try:
        label1 = researcher.select_archetype(conn)
        label2 = researcher.select_archetype(conn)
        assert label1 == label2, f"Non-deterministic: {label1!r} != {label2!r}"
    finally:
        conn.close()


def test_build_thesis_returns_dict():
    """build_thesis must return a dict."""
    import researcher
    import db
    conn = db.init_db("alpha_kb.db")
    try:
        thesis = researcher.build_thesis(conn)
        assert isinstance(thesis, dict), f"Expected dict, got {type(thesis)}"
    finally:
        conn.close()


def test_build_thesis_archetype_valid():
    """build_thesis dict must have archetype in the 8-label taxonomy."""
    import researcher
    import db
    conn = db.init_db("alpha_kb.db")
    try:
        thesis = researcher.build_thesis(conn)
        assert "archetype" in thesis, "Missing 'archetype' key"
        assert thesis["archetype"] in VALID_LABELS, f"Invalid archetype: {thesis['archetype']!r}"
    finally:
        conn.close()


def test_build_thesis_source_operators_subset_of_catalog():
    """source_operators must be a subset of operators.name in the live catalog."""
    import researcher
    import db
    conn = db.init_db("alpha_kb.db")
    try:
        thesis = researcher.build_thesis(conn)
        live_ops = {row[0] for row in conn.execute("SELECT name FROM operators")}
        source_ops = set(thesis.get("source_operators", []))
        unknown = source_ops - live_ops
        assert not unknown, f"source_operators not subset of catalog: {unknown}"
        assert len(source_ops) > 0, "source_operators is empty"
    finally:
        conn.close()


def test_build_thesis_source_datafields_subset_of_synced_slice():
    """source_datafields must be a subset of datafields.id for USA/TOP3000/delay=1."""
    import researcher
    import db
    conn = db.init_db("alpha_kb.db")
    try:
        thesis = researcher.build_thesis(conn)
        live_fields = {
            row[0] for row in conn.execute(
                "SELECT id FROM datafields WHERE region='USA' AND universe='TOP3000' AND delay=1"
            )
        }
        source_fields = set(thesis.get("source_datafields", []))
        unknown = source_fields - live_fields
        assert not unknown, f"source_datafields not subset of catalog: {unknown}"
        assert len(source_fields) > 0, "source_datafields is empty"
    finally:
        conn.close()


def test_build_thesis_has_cited_insights():
    """build_thesis must include >=1 cited_insight string."""
    import researcher
    import db
    conn = db.init_db("alpha_kb.db")
    try:
        thesis = researcher.build_thesis(conn)
        insights = thesis.get("cited_insights", [])
        assert isinstance(insights, list), f"cited_insights must be list, got {type(insights)}"
        assert len(insights) >= 1, f"Expected >=1 cited insight, got {len(insights)}"
    finally:
        conn.close()


def test_build_thesis_has_region_universe_delay():
    """build_thesis must include region='USA', universe='TOP3000', delay=1."""
    import researcher
    import db
    conn = db.init_db("alpha_kb.db")
    try:
        thesis = researcher.build_thesis(conn)
        assert thesis.get("region") == "USA", f"Wrong region: {thesis.get('region')}"
        assert thesis.get("universe") == "TOP3000", f"Wrong universe: {thesis.get('universe')}"
        assert thesis.get("delay") == 1, f"Wrong delay: {thesis.get('delay')}"
    finally:
        conn.close()


def test_build_thesis_has_cited_alpha_ids():
    """build_thesis must include cited_alpha_ids (may be empty if DB is empty)."""
    import researcher
    import db
    conn = db.init_db("alpha_kb.db")
    try:
        thesis = researcher.build_thesis(conn)
        assert "cited_alpha_ids" in thesis, "Missing 'cited_alpha_ids' key"
        assert isinstance(thesis["cited_alpha_ids"], list), "cited_alpha_ids must be list"
    finally:
        conn.close()


def test_build_thesis_with_explicit_archetype():
    """build_thesis(conn, archetype='quality') must use the given archetype."""
    import researcher
    import db
    conn = db.init_db("alpha_kb.db")
    try:
        thesis = researcher.build_thesis(conn, archetype="quality")
        assert thesis["archetype"] == "quality", f"Expected quality, got {thesis['archetype']}"
    finally:
        conn.close()


def test_build_thesis_invalid_archetype_raises():
    """build_thesis with invalid archetype must raise ValueError."""
    import researcher
    import db
    conn = db.init_db("alpha_kb.db")
    try:
        with pytest.raises(ValueError):
            researcher.build_thesis(conn, archetype="invalid_archetype")
    finally:
        conn.close()


def test_no_grade_simulate_login_in_source():
    """researcher.py must not reference grade., simulate(, or login(."""
    researcher_path = os.path.join(os.path.dirname(__file__), "researcher.py")
    assert os.path.exists(researcher_path), "researcher.py not found"
    with open(researcher_path) as f:
        content = f.read()
    non_comment_lines = [
        line for line in content.splitlines()
        if not line.strip().startswith("#")
    ]
    non_comment = "\n".join(non_comment_lines)
    import re
    grade_count = len(re.findall(r'grade\.', non_comment))
    sim_count = len(re.findall(r'simulate\(', non_comment))
    login_count = len(re.findall(r'login\(', non_comment))
    assert grade_count == 0, f"researcher.py has {grade_count} grade.* reference(s)"
    assert sim_count == 0, f"researcher.py has {sim_count} simulate( reference(s)"
    assert login_count == 0, f"researcher.py has {login_count} login( reference(s)"
