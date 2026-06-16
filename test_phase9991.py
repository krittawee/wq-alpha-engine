"""Offline tests for Phase 999.1 — hunt→bruteforce template bridge.

Covers SPEC acceptance criteria R1–R6 except the live human-verify checkpoint.
Zero BRAIN: no login, no sim, no submit. The LLM generator and the bruteforce
runner are injected/mocked; additivity and validation are mocked where needed.
"""

import json
import unittest.mock
from unittest.mock import MagicMock

import db
import handoff


# ---------------------------------------------------------------------------
# R3 — registry table + linkage + round-trip
# ---------------------------------------------------------------------------

def test_generated_templates_table_and_linkage_created():
    conn = db.init_db(":memory:")
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "generated_templates" in tables
    cols = {r[1] for r in conn.execute("PRAGMA table_info(bruteforce_runs)").fetchall()}
    assert "generated_template_id" in cols, "bruteforce_runs must link to generated_templates"
    conn.close()


def test_insert_generated_template_roundtrips_expression_and_slots():
    conn = db.init_db(":memory:")
    slots = {"fast": [3, 5], "slow": [20, 40]}
    rowid = db.insert_generated_template(conn, {
        "template_name": "gen_mom",
        "expression": "rank(ts_mean(close, {fast}) / ts_mean(close, {slow}) - 1)",
        "slots_json": json.dumps(slots, sort_keys=True),
        "settings_archetype": "momentum",
        "source_run_id": "handoff-x",
        "source_thesis_json": "{}",
        "prompt_version": "999.1-v1",
        "llm_model": "mock",
        "validation_status": "accepted",
        "n_combos": 4,
        "n_validated": 4,
        "failure_reason": "",
        "created_at": "2026-06-16T00:00:00Z",
    })
    row = conn.execute(
        "SELECT expression, slots_json FROM generated_templates WHERE id=?", (rowid,)
    ).fetchone()
    assert row[0] == "rank(ts_mean(close, {fast}) / ts_mean(close, {slow}) - 1)"
    assert json.loads(row[1]) == slots
    conn.close()


# ---------------------------------------------------------------------------
# R2 — validate_generated_template gate (schema / zero-combos / zero-valid / ok)
# ---------------------------------------------------------------------------

def test_validate_rejects_bad_schema_without_expanding():
    conn = db.init_db(":memory:")
    with unittest.mock.patch("handoff.templates.expand_slots") as expand:
        res = handoff.validate_generated_template(conn, {"name": "x"})  # missing keys
        assert res["ok"] is False
        assert "missing keys" in res["reason"]
        expand.assert_not_called()  # no expansion (and thus no sim) on schema failure
    conn.close()


def test_validate_rejects_zero_combos():
    conn = db.init_db(":memory:")
    tmpl = {"name": "t", "expression": "rank({field})", "slots": {"field": {}},
            "settings_archetype": "reversal"}
    with unittest.mock.patch("handoff.templates.expand_slots", return_value=[]):
        res = handoff.validate_generated_template(conn, tmpl)
        assert res["ok"] is False and res["n_combos"] == 0
        assert "zero combos" in res["reason"]
    conn.close()


def test_validate_rejects_when_no_combo_passes_validate():
    conn = db.init_db(":memory:")
    tmpl = {"name": "t", "expression": "rank(bogus_field)", "slots": {"w": [1]},
            "settings_archetype": "reversal"}
    combos = [("rank(bogus_field)", {"w": 1})]
    with (
        unittest.mock.patch("handoff.templates.expand_slots", return_value=combos),
        unittest.mock.patch("handoff.validate.validate", return_value=(False, "unknown field bogus_field")),
    ):
        res = handoff.validate_generated_template(conn, tmpl)
        assert res["ok"] is False and res["n_validated"] == 0
        assert "unknown field" in res["reason"]
    conn.close()


def test_validate_accepts_valid_template():
    conn = db.init_db(":memory:")
    tmpl = {"name": "t", "expression": "rank(close)", "slots": {"w": [1, 2]},
            "settings_archetype": "reversal"}
    combos = [("rank(close)", {"w": 1}), ("rank(close)", {"w": 2})]
    with (
        unittest.mock.patch("handoff.templates.expand_slots", return_value=combos),
        unittest.mock.patch("handoff.validate.validate", return_value=(True, "")),
    ):
        res = handoff.validate_generated_template(conn, tmpl)
        assert res["ok"] is True and res["n_validated"] == 2
    conn.close()


# ---------------------------------------------------------------------------
# R4/R5/R6 — bounded handoff loop
# ---------------------------------------------------------------------------

_TMPL = {"name": "gen", "expression": "rank(close)", "slots": {"w": [1]},
         "settings_archetype": "reversal"}


def _gen(*_args, **_kwargs):
    return dict(_TMPL)


def _run_loop(runner, validation_ok=True, max_sims=100, max_templates=3):
    """Drive run_bruteforce_handoff with mocked validation + injected runner."""
    val = {"ok": validation_ok, "n_combos": 1, "n_validated": 1 if validation_ok else 0,
           "reason": "" if validation_ok else "rejected"}
    with (
        unittest.mock.patch("handoff.validate_generated_template", return_value=val),
        unittest.mock.patch("handoff.ideator.build_additivity_hint", return_value=""),
    ):
        return handoff.run_bruteforce_handoff(
            client=MagicMock(),
            db_path=":memory:",
            max_sims=max_sims,
            max_templates=max_templates,
            delay=0,
            thesis={"archetype": "reversal"},
            template_generator=_gen,
            bruteforce_runner=runner,
        )


def test_loop_stops_at_max_templates():
    runner = MagicMock(return_value={"sims_used": 1, "additive_ids": []})
    res = _run_loop(runner, max_sims=100, max_templates=3)
    assert res["templates_attempted"] == 3
    assert res["best_submittable"] is None
    assert res["stop_reason"] == "template_cap"
    assert res["auto_submitted"] is False


def test_loop_stops_at_max_sims():
    runner = MagicMock(return_value={"sims_used": 50, "additive_ids": []})
    res = _run_loop(runner, max_sims=10, max_templates=99)
    assert res["sims_used"] >= 10
    assert res["best_submittable"] is None
    assert res["stop_reason"] == "sim_budget"


def test_loop_stops_at_first_additive():
    runner = MagicMock(return_value={"sims_used": 2, "additive_ids": ["aXbYcZ1q"]})
    res = _run_loop(runner, max_sims=100, max_templates=99)
    assert res["best_submittable"] == "aXbYcZ1q"
    assert res["stop_reason"] == "success"
    assert res["templates_attempted"] == 1  # stopped immediately
    assert runner.call_count == 1


def test_loop_retries_then_stops_on_rejected_templates():
    runner = MagicMock(return_value={"sims_used": 1, "additive_ids": []})
    res = _run_loop(runner, validation_ok=False, max_sims=100, max_templates=2)
    assert res["templates_accepted"] == 0
    assert res["rejected_templates"] == 2
    runner.assert_not_called()  # nothing sweeps when every template is rejected


# ---------------------------------------------------------------------------
# R6 + threat model — no auto-submit, no in-loop login (static guarantees)
# ---------------------------------------------------------------------------

def test_handoff_result_never_auto_submits():
    runner = MagicMock(return_value={"sims_used": 1, "additive_ids": ["zz9PqRsT"]})
    res = _run_loop(runner)
    assert res["auto_submitted"] is False


def test_handoff_source_has_no_login_or_submit():
    src = open("handoff.py").read()
    assert "login(" not in src, "handoff must never authenticate (single-shot auth rule)"
    assert ".submit(" not in src and "submit_alpha" not in src, "handoff must never submit"


# ---------------------------------------------------------------------------
# R4 — hunt CLI exposes the flag and a thin branch
# ---------------------------------------------------------------------------

def test_hunt_cli_wires_bruteforce_handoff():
    src = open("hunt.py").read()
    assert "--bruteforce-handoff" in src
    assert "run_bruteforce_handoff" in src or "handoff" in src


# ---------------------------------------------------------------------------
# VECTOR-field type safety (live-run finding: gen produced ts_mean on a raw
# VECTOR field → all sims errored). Guard at validate + type-aware generator.
# ---------------------------------------------------------------------------

def _seed_catalog(conn):
    for op in ("rank", "ts_mean", "vec_avg"):
        conn.execute("INSERT INTO operators(name) VALUES(?)", (op,))
    conn.execute("INSERT INTO datafields(id, type) VALUES('vecfld', 'VECTOR')")
    conn.execute("INSERT INTO datafields(id, type) VALUES('close', 'MATRIX')")
    conn.commit()


def test_validate_rejects_vector_field_without_reduction():
    import validate
    conn = db.init_db(":memory:")
    _seed_catalog(conn)
    ok, reason = validate.validate(conn, "rank(ts_mean(vecfld, 5))")
    assert ok is False and "VECTOR" in reason
    conn.close()


def test_validate_accepts_vector_field_with_vec_avg():
    import validate
    conn = db.init_db(":memory:")
    _seed_catalog(conn)
    ok, reason = validate.validate(conn, "rank(ts_mean(vec_avg(vecfld), 5))")
    assert ok is True, reason
    conn.close()


def test_generate_template_wraps_vector_field():
    import ideator
    conn = db.init_db(":memory:")
    _seed_catalog(conn)
    t = ideator.generate_template(
        conn, {"archetype": "sentiment_event", "source_datafields": ["vecfld"]})
    assert "vec_avg({field})" in t["expression"], t["expression"]
    conn.close()


def test_generate_template_direct_for_non_vector():
    import ideator
    conn = db.init_db(":memory:")
    _seed_catalog(conn)
    t = ideator.generate_template(
        conn, {"archetype": "momentum", "source_datafields": ["close"]})
    assert "vec_avg" not in t["expression"]
    conn.close()
