"""Regression tests for debug session bruteforce-delay0-sim-errors.

Two distinct bugs surfaced in the first live /bruteforce run; both made every
residual_momentum probe sim return status="error" and abandon the template:

1. Delay drop: _run_template built probe settings from settings_grid_for_archetype(),
   which inherits delay=1 from grade._BASE_SETTINGS. grade_one gives settings["delay"]
   precedence over the delay= argument, so `--delay 0` was silently dropped.
   Fix: _run_template stamps probe_settings["delay"] = delay before grading.

2. Dict-as-parent_alpha_id: _run_template passed (expr, settings) tuples to grade_many,
   which reads item[1] as parent_alpha_id. The settings dict then bound as a SQL
   parameter — "Error binding parameter 3: type 'dict' is not supported" — so the real
   failure was masked as opaque "error N/A". (A single-threaded grade_one with a plain
   string worked fine, which is what isolated the bug.)
   Fix: _run_template passes plain-string expressions; settings travel via settings_map.

All tests run with zero real BRAIN calls.
"""

import unittest.mock
from unittest.mock import MagicMock

import db


def test_run_template_stamps_requested_delay_into_settings():
    """--delay 0 must propagate into the settings dict passed to grade_many.

    Captures grade.grade_many's call: both the per-expression settings_map dicts
    and the inline (expr, settings) tuples must carry delay=0, NOT the inherited
    _BASE_SETTINGS delay=1. This locks in the fix for the silent-drop bug.
    """
    import bruteforce

    client = MagicMock()
    captured = {}

    def fake_grade_many(client, conn, expressions, run_id, **kwargs):
        # Record what the engine actually sent down to grade.
        captured["settings_map"] = kwargs.get("settings_map")
        captured["delay_kwarg"] = kwargs.get("delay")
        captured["expressions"] = list(expressions)

        def _expr(item):
            return item[0] if isinstance(item, tuple) else item

        # Return a non-surviving probe so the pipeline abandons cleanly (no bulk-sim).
        return [
            {"status": "fail", "alpha_id": None, "checks": [], "expression": _expr(e)}
            for e in expressions
        ]

    real_conn = db.init_db(":memory:")

    with (
        unittest.mock.patch("bruteforce.selfcorr.backfill_active_pnl"),
        unittest.mock.patch("bruteforce.probe_delay.probe_and_gate"),
        unittest.mock.patch("bruteforce.validate.validate", return_value=(True, "")),
        unittest.mock.patch("bruteforce.grade.grade_many", side_effect=fake_grade_many),
        unittest.mock.patch(
            "bruteforce.editor.classify_from_checks", return_value=("fail", ["SHARPE"])
        ),
        unittest.mock.patch("bruteforce.db.init_db", return_value=real_conn),
    ):
        bruteforce.bruteforce(
            client=client,
            db_path=":memory:",
            delay=0,
            quota=1,
            probe_size=5,
            template_names=["residual_momentum"],
        )

    # The delay= kwarg the engine forwards must be the requested 0.
    assert captured["delay_kwarg"] == 0, (
        f"grade_many received delay={captured['delay_kwarg']!r}, expected 0"
    )

    # Every settings dict reaching grade must carry delay=0 (the bug had delay=1).
    settings_map = captured["settings_map"]
    assert settings_map, "settings_map should be provided to grade_many"
    for expr, s in settings_map.items():
        assert s.get("delay") == 0, (
            f"settings_map[{expr!r}]['delay']={s.get('delay')!r}, expected 0 "
            f"(stale _BASE_SETTINGS delay=1 indicates the --delay 0 drop bug)"
        )

    # Probe expressions must be PLAIN STRINGS, not (expr, settings) tuples.
    # grade_many reads a tuple's 2nd element as parent_alpha_id; passing the settings
    # dict there bound a dict as a SQL parameter ("Error binding parameter 3: type
    # 'dict' is not supported") and every probe sim returned status="error". Settings
    # travel via settings_map only. See debug session bruteforce-delay0-sim-errors.
    for e in captured["expressions"]:
        assert isinstance(e, str), (
            f"grade_many received {type(e).__name__} {e!r}; probe expressions must be "
            f"plain strings so settings never reach parent_alpha_id"
        )

    real_conn.close()


def test_grade_one_no_warning_when_settings_delay_matches():
    """grade_one must NOT emit the delay-conflict warning when settings['delay']==delay.

    Before the fix, settings carried delay=1 while delay=0 was requested, firing
    '[grade] WARNING: delay=0 argument ignored ...'. After the fix the caller stamps
    delay=0 into settings, so settings['delay']==delay==0 and no warning fires.

    This drives grade_one far enough to hit (or skip) the warning branch only;
    simulation is mocked so no BRAIN call happens.
    """
    import io
    from contextlib import redirect_stderr

    import grade

    conn = db.init_db(":memory:")
    client = MagicMock()

    settings = {**grade._BASE_SETTINGS, "delay": 0}

    # Make validation fail fast so grade_one returns right after the warning branch,
    # without ever simulating. The warning (if any) is emitted before validation.
    buf = io.StringIO()
    with (
        unittest.mock.patch("grade.validate.validate", return_value=(False, "stop-early")),
        unittest.mock.patch("grade.db.expr_exists", return_value=None),
    ):
        with redirect_stderr(buf):
            result = grade.grade_one(
                client, conn, "rank(close)", "run-x",
                settings=settings, delay=0,
            )

    stderr = buf.getvalue()
    assert "argument ignored" not in stderr, (
        f"Unexpected delay-conflict warning when settings['delay']==delay==0: {stderr!r}"
    )
    assert result["status"] == "invalid", "expected early invalid return (validation stubbed False)"

    conn.close()


def test_grade_many_plain_strings_keep_parent_alpha_id_none():
    """Plain-string expressions must reach grade_one with parent_alpha_id=None.

    Pins the dict-as-parent_alpha_id bug: bruteforce passed (expr, settings) tuples to
    grade_many, which reads item[1] as parent_alpha_id. The settings dict then bound as
    a SQL parameter ("Error binding parameter 3: type 'dict' is not supported") and every
    probe sim errored. With plain strings + settings_map, parent_alpha_id stays None and
    the matched settings dict is forwarded via the settings= kwarg.
    """
    import grade

    conn = db.init_db(":memory:")
    client = MagicMock()
    seen = []

    def fake_grade_one(client, conn, expr, run_id, **kwargs):
        seen.append({"parent_alpha_id": kwargs.get("parent_alpha_id"),
                     "settings": kwargs.get("settings")})
        return {"expression": expr, "status": "fail", "alpha_id": None}

    settings = {**grade._BASE_SETTINGS, "delay": 0}
    exprs = ["rank(close)", "rank(open)"]
    smap = {e: settings for e in exprs}

    with unittest.mock.patch("grade.grade_one", side_effect=fake_grade_one):
        grade.grade_many(client, conn, exprs, "run-x", max_workers=1, settings_map=smap)

    assert seen, "grade_one should have been called"
    for call in seen:
        assert call["parent_alpha_id"] is None, (
            f"parent_alpha_id={call['parent_alpha_id']!r}; a non-None/dict value here is "
            f"the tuple-misread bug that bound a dict into SQL"
        )
        assert call["settings"] is settings, "settings must arrive via settings_map"

    conn.close()
