"""test_ideator_gates.py — RED phase tests for Task 2: validate gate, dedup, seeds.txt.

Tests validate.validate gate (criterion 2), db.expr_exists dedup (criterion 3),
to_seeds_text serialization (D-02 Path A), and queueable helper.

All tests are written BEFORE any gate-specific behavior is extended (TDD RED gate).
"""

import re

import pytest

import db
import researcher
import validate


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def conn():
    c = db.init_db("alpha_kb.db")
    yield c
    c.close()


@pytest.fixture(scope="module")
def thesis_reversal(conn):
    return researcher.build_thesis(conn, archetype="reversal")


@pytest.fixture(scope="module")
def candidates_reversal(conn, thesis_reversal):
    import ideator
    return ideator.generate_candidates(conn, thesis_reversal)


@pytest.fixture(scope="module")
def all_archetype_candidates(conn):
    """Produce candidates for every archetype."""
    import ideator
    result = {}
    for arch in researcher.ARCHETYPES:
        t = researcher.build_thesis(conn, archetype=arch)
        result[arch] = ideator.generate_candidates(conn, t)
    return result


# ---------------------------------------------------------------------------
# Public API surface
# ---------------------------------------------------------------------------

def test_to_seeds_text_exists():
    import ideator
    assert hasattr(ideator, "to_seeds_text"), "to_seeds_text not found in ideator"
    assert callable(ideator.to_seeds_text)


def test_queueable_exists():
    import ideator
    assert hasattr(ideator, "queueable"), "queueable not found in ideator"
    assert callable(ideator.queueable)


# ---------------------------------------------------------------------------
# Candidate record fields: validation_reason and dedup_alpha_id present
# ---------------------------------------------------------------------------

def test_candidates_have_validation_reason(candidates_reversal):
    for c in candidates_reversal:
        assert "validation_reason" in c, f"Missing validation_reason: {c}"


def test_candidates_have_dedup_alpha_id(candidates_reversal):
    for c in candidates_reversal:
        assert "dedup_alpha_id" in c, f"Missing dedup_alpha_id: {c}"


def test_all_archetypes_have_valid_field(all_archetype_candidates):
    for arch, cs in all_archetype_candidates.items():
        for c in cs:
            assert "valid" in c and isinstance(c["valid"], bool), \
                f"archetype {arch}: invalid 'valid' field: {c}"


# ---------------------------------------------------------------------------
# Criterion 2: validate.validate called and queueable candidates are valid
# ---------------------------------------------------------------------------

def test_queueable_all_pass_validate(conn, all_archetype_candidates):
    """Every queueable candidate passes validate.validate — criterion 2."""
    import ideator
    for arch, cs in all_archetype_candidates.items():
        q = ideator.queueable(cs)
        failures = [c for c in q if not validate.validate(conn, c["expression"])[0]]
        assert not failures, (
            f"archetype {arch!r}: queueable candidates failed validate: "
            f"{[c['expression'] for c in failures]}"
        )


def test_queueable_no_unknown_token_rejections(conn, all_archetype_candidates):
    """Criterion 2: validator rejects ZERO queueable outputs for unknown tokens."""
    import ideator
    for arch, cs in all_archetype_candidates.items():
        q = ideator.queueable(cs)
        for c in q:
            ok, reason = validate.validate(conn, c["expression"])
            assert ok, f"archetype {arch!r}: unknown-token rejection: {reason!r} | {c['expression']}"


def test_valid_field_matches_validate_gate(conn, candidates_reversal):
    """candidate['valid'] is consistent with validate.validate(conn, expr)."""
    for c in candidates_reversal:
        ok, _ = validate.validate(conn, c["expression"])
        assert c["valid"] == ok, (
            f"candidate['valid']={c['valid']} but validate.validate returned {ok}: "
            f"{c['expression']}"
        )


def test_validation_reason_empty_when_valid(candidates_reversal):
    """validation_reason is '' for valid candidates."""
    for c in candidates_reversal:
        if c["valid"]:
            assert c["validation_reason"] == "", \
                f"valid=True but reason={c['validation_reason']!r}: {c['expression']}"


def test_validation_reason_nonempty_when_invalid(conn):
    """validation_reason is non-empty for invalid candidates.

    Inject a fake invalid candidate to test the gate branch.
    We can test this indirectly — construct an expression with an unknown token
    and confirm validate returns (False, non-empty reason).
    """
    bad_expr = "rank(ts_delta(nonexistent_field_xyz_abc, 5))"
    ok, reason = validate.validate(conn, bad_expr)
    assert not ok
    assert reason  # must be non-empty


def test_ideator_calls_validate_validate():
    """Verify ideator.py source references validate.validate (criterion 2 gate)."""
    import pathlib
    src = pathlib.Path("ideator.py").read_text()
    assert "validate.validate" in src, "ideator.py must call validate.validate"


def test_ideator_calls_db_expr_exists():
    """Verify ideator.py source references db.expr_exists (criterion 3 dedup)."""
    import pathlib
    src = pathlib.Path("ideator.py").read_text()
    assert "db.expr_exists" in src, "ideator.py must call db.expr_exists"


# ---------------------------------------------------------------------------
# Criterion 3: db.expr_exists dedup — queueable candidates are novel
# ---------------------------------------------------------------------------

def test_queueable_all_novel(all_archetype_candidates):
    """Every queueable candidate has dedup_alpha_id is None — criterion 3."""
    import ideator
    for arch, cs in all_archetype_candidates.items():
        q = ideator.queueable(cs)
        non_novel = [c for c in q if c["dedup_alpha_id"] is not None]
        assert not non_novel, (
            f"archetype {arch!r}: queueable contains duplicates: "
            f"{[c['expression'] for c in non_novel]}"
        )


def test_dedup_alpha_id_type(all_archetype_candidates):
    """dedup_alpha_id is either None or a non-empty string."""
    for arch, cs in all_archetype_candidates.items():
        for c in cs:
            d = c["dedup_alpha_id"]
            assert d is None or (isinstance(d, str) and d), \
                f"archetype {arch!r}: bad dedup_alpha_id={d!r}"


# ---------------------------------------------------------------------------
# queueable() helper: returns valid+novel subset
# ---------------------------------------------------------------------------

def test_queueable_returns_list(candidates_reversal):
    import ideator
    q = ideator.queueable(candidates_reversal)
    assert isinstance(q, list)


def test_queueable_subset_of_candidates(candidates_reversal):
    import ideator
    q = ideator.queueable(candidates_reversal)
    exprs_all = {c["expression"] for c in candidates_reversal}
    for c in q:
        assert c["expression"] in exprs_all, "queueable returned candidate not in original list"


def test_queueable_excludes_invalid():
    """queueable only includes valid=True candidates."""
    import ideator
    fake = [
        {"expression": "x", "archetype": "reversal", "valid": False, "validation_reason": "err", "dedup_alpha_id": None},
        {"expression": "y", "archetype": "reversal", "valid": True, "validation_reason": "", "dedup_alpha_id": None},
    ]
    q = ideator.queueable(fake)
    assert len(q) == 1 and q[0]["expression"] == "y"


def test_queueable_excludes_duplicates():
    """queueable only includes dedup_alpha_id=None candidates."""
    import ideator
    fake = [
        {"expression": "a", "archetype": "reversal", "valid": True, "validation_reason": "", "dedup_alpha_id": "EXISTINGID"},
        {"expression": "b", "archetype": "reversal", "valid": True, "validation_reason": "", "dedup_alpha_id": None},
    ]
    q = ideator.queueable(fake)
    assert len(q) == 1 and q[0]["expression"] == "b"


# ---------------------------------------------------------------------------
# to_seeds_text: cli.py-parseable seeds format (D-02 Path A)
# ---------------------------------------------------------------------------

def test_to_seeds_text_returns_string(candidates_reversal):
    import ideator
    txt = ideator.to_seeds_text(candidates_reversal)
    assert isinstance(txt, str)


def test_to_seeds_text_line_count_matches_queueable(all_archetype_candidates):
    """Body lines (non-# non-blank) == len(queueable) for every archetype."""
    import ideator
    for arch, cs in all_archetype_candidates.items():
        q = ideator.queueable(cs)
        txt = ideator.to_seeds_text(cs)
        body_lines = [l for l in txt.splitlines() if l.strip() and not l.startswith("#")]
        assert len(body_lines) == len(q), (
            f"archetype {arch!r}: seeds body lines={len(body_lines)}, "
            f"queueable={len(q)}"
        )


def test_to_seeds_text_body_lines_are_queueable_exprs(candidates_reversal):
    """Body lines are exactly the queueable expressions."""
    import ideator
    q = ideator.queueable(candidates_reversal)
    txt = ideator.to_seeds_text(candidates_reversal)
    body_lines = [l.strip() for l in txt.splitlines() if l.strip() and not l.startswith("#")]
    queueable_exprs = [c["expression"] for c in q]
    assert body_lines == queueable_exprs


def test_to_seeds_text_cli_parseable(candidates_reversal):
    """Simulate cli.py parse contract: strip+filter blank+# yields expressions."""
    import ideator
    q = ideator.queueable(candidates_reversal)
    txt = ideator.to_seeds_text(candidates_reversal)
    # cli.py:62-64: expressions = [l.strip() for l in lines if l.strip() and not l.startswith('#')]
    lines = txt.splitlines()
    parsed = [l.strip() for l in lines if l.strip() and not l.startswith("#")]
    assert len(parsed) == len(q), f"cli.py parse yields {len(parsed)}, expected {len(q)}"


def test_to_seeds_text_with_custom_header(candidates_reversal):
    """Custom header line is included and prefixed with '#'."""
    import ideator
    txt = ideator.to_seeds_text(candidates_reversal, header="# custom header")
    lines = txt.splitlines()
    assert any(l.startswith("#") for l in lines), "No comment header found"


def test_to_seeds_text_no_blank_body_lines(candidates_reversal):
    """No blank body lines in seeds text (clean format)."""
    import ideator
    txt = ideator.to_seeds_text(candidates_reversal)
    for l in txt.splitlines():
        if l.startswith("#"):
            continue
        if not l.strip():
            pytest.fail(f"Unexpected blank body line in seeds text")


def test_reversal_has_at_least_one_queueable(conn, candidates_reversal):
    """At least one queueable candidate for reversal archetype."""
    import ideator
    q = ideator.queueable(candidates_reversal)
    assert len(q) >= 1, "No queueable candidates for reversal"
