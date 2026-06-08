"""TDD tests for researcher.py — Task 1: catalog reads + past-alpha insight queries.

RED phase: these tests must FAIL before researcher.py exists.
"""

import pytest
import sys
import os

# Ensure we can import from the project root
sys.path.insert(0, os.path.dirname(__file__))


def test_researcher_importable():
    """researcher.py must be importable without error."""
    import researcher  # noqa: F401


def test_read_catalog_exists():
    """read_catalog function must exist in researcher module."""
    import researcher
    assert hasattr(researcher, "read_catalog"), "read_catalog not found in researcher"


def test_gather_insights_exists():
    """gather_insights function must exist in researcher module."""
    import researcher
    assert hasattr(researcher, "gather_insights"), "gather_insights not found in researcher"


def test_read_catalog_operator_count():
    """read_catalog must return >=60 operators from live alpha_kb.db."""
    import researcher
    import db
    conn = db.init_db("alpha_kb.db")
    try:
        ops, fields = researcher.read_catalog(conn)
        assert len(ops) >= 60, f"Expected >=60 operators, got {len(ops)}"
    finally:
        conn.close()


def test_read_catalog_field_count():
    """read_catalog must return >=5000 USA/TOP3000/delay=1 datafields."""
    import researcher
    import db
    conn = db.init_db("alpha_kb.db")
    try:
        ops, fields = researcher.read_catalog(conn)
        assert len(fields) >= 5000, f"Expected >=5000 datafields, got {len(fields)}"
    finally:
        conn.close()


def test_read_catalog_operator_keys():
    """Each operator row must have name, category, definition keys."""
    import researcher
    import db
    conn = db.init_db("alpha_kb.db")
    try:
        ops, fields = researcher.read_catalog(conn)
        assert len(ops) > 0
        sample = ops[0]
        assert "name" in sample, f"Missing 'name' key: {sample}"
        assert "category" in sample, f"Missing 'category' key: {sample}"
        assert "definition" in sample, f"Missing 'definition' key: {sample}"
    finally:
        conn.close()


def test_read_catalog_field_keys():
    """Each datafield row must have id, description, dataset, type keys."""
    import researcher
    import db
    conn = db.init_db("alpha_kb.db")
    try:
        ops, fields = researcher.read_catalog(conn)
        assert len(fields) > 0
        sample = fields[0]
        assert "id" in sample, f"Missing 'id' key: {sample}"
        assert "description" in sample, f"Missing 'description' key: {sample}"
        assert "dataset" in sample, f"Missing 'dataset' key: {sample}"
        assert "type" in sample, f"Missing 'type' key: {sample}"
    finally:
        conn.close()


def test_gather_insights_returns_list():
    """gather_insights must return a list of >=1 insight dicts."""
    import researcher
    import db
    conn = db.init_db("alpha_kb.db")
    try:
        insights = researcher.gather_insights(conn)
        assert isinstance(insights, list), f"Expected list, got {type(insights)}"
        assert len(insights) >= 1, "Expected >=1 insight"
    finally:
        conn.close()


def test_gather_insights_structure():
    """Each insight must be a dict with 'text' and 'cited_alpha_ids' keys."""
    import researcher
    import db
    conn = db.init_db("alpha_kb.db")
    try:
        insights = researcher.gather_insights(conn)
        for ins in insights:
            assert isinstance(ins, dict), f"Insight must be a dict, got {type(ins)}"
            assert "text" in ins, f"Missing 'text' key in insight: {ins}"
            assert "cited_alpha_ids" in ins, f"Missing 'cited_alpha_ids' key in insight: {ins}"
            assert isinstance(ins["cited_alpha_ids"], list), \
                f"cited_alpha_ids must be a list: {ins}"
    finally:
        conn.close()


def test_gather_insights_no_null_column_citations():
    """Insights must NOT cite archetype, self_corr, or prod_corr (NULL in DB)."""
    import researcher
    import db
    conn = db.init_db("alpha_kb.db")
    try:
        insights = researcher.gather_insights(conn)
        for ins in insights:
            text = ins.get("text", "").lower()
            assert "self_corr" not in text, f"Insight cites NULL column self_corr: {text}"
            assert "prod_corr" not in text, f"Insight cites NULL column prod_corr: {text}"
    finally:
        conn.close()


def test_gather_insights_59_pool():
    """At least one insight must reference the 59-alpha clean pool count."""
    import researcher
    import db
    conn = db.init_db("alpha_kb.db")
    try:
        insights = researcher.gather_insights(conn)
        # At least one insight should mention a numeric count derived from the clean pool query
        texts = [ins.get("text", "") for ins in insights]
        combined = " ".join(texts).lower()
        # Should contain reference to pool / unsubmitted / sharpe
        has_pool_ref = any(
            kw in combined
            for kw in ["clean pool", "unsubmitted", "sharpe", "pool"]
        )
        assert has_pool_ref, f"No clean-pool insight found in: {texts}"
    finally:
        conn.close()


def test_no_brain_calls_in_source():
    """researcher.py must not contain grade., simulate(, or login( references."""
    researcher_path = os.path.join(os.path.dirname(__file__), "researcher.py")
    if not os.path.exists(researcher_path):
        pytest.skip("researcher.py not created yet (RED phase)")
    with open(researcher_path) as f:
        content = f.read()
    # Strip comment lines before checking
    non_comment_lines = [
        line for line in content.splitlines()
        if not line.strip().startswith("#")
    ]
    non_comment = "\n".join(non_comment_lines)
    import re
    assert not re.search(r'grade\.', non_comment), "researcher.py references grade.*"
    assert not re.search(r'simulate\(', non_comment), "researcher.py calls simulate("
    assert not re.search(r'login\(', non_comment), "researcher.py calls login("
