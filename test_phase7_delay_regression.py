"""Regression test for debug session bruteforce-delay0-sim-errors.

Root cause: bruteforce._run_template built probe settings from
settings_grid_for_archetype(), which inherits delay=1 from grade._BASE_SETTINGS.
grade_one gives settings["delay"] precedence over the delay= argument, so a
`--delay 0` run was silently dropped — every sim ran at delay=1, and the
residual_momentum template's sims came back as errors (template abandoned).

Fix: _run_template now stamps the run's requested delay into probe_settings
(probe_settings["delay"] = delay) before passing it to grade_many / bulk-sim.

This test verifies, with zero real BRAIN calls, that the settings dict reaching
grade carries the requested delay (0), and that no delay-conflict warning fires.
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
        captured["inline_settings"] = [
            item[1] for item in expressions if isinstance(item, tuple) and len(item) > 1
        ]
        # Return a non-surviving probe so the pipeline abandons cleanly (no bulk-sim).
        return [
            {"status": "fail", "alpha_id": None, "checks": [], "expression": e[0]}
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

    for s in captured["inline_settings"]:
        assert s.get("delay") == 0, (
            f"inline tuple settings delay={s.get('delay')!r}, expected 0"
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
