"""verify_delay0.py — Phase 5 / Plan 05-03 empirical delay-0 verification.

Single-process experiment that confirms whether BRAIN actually runs delay-0 when
requested from our code (vs. silently coercing to delay-1).

HUMAN-GATED: this script fires LIVE BRAIN simulations and requires Persona
biometric auth. Run it yourself while present for the auth prompt:

    python verify_delay0.py

CLAUDE.md constraints honored here:
  - login() is called EXACTLY ONCE, at the top. Never re-auth mid-run.
  - A 401 propagates and terminates the script (no try/except swallows it).
  - Sims run sequentially (one at a time) — well under the <=3 concurrency cap.
  - Uses probe_delay.run_probe() only (NOT grade_one/grade_many); run_probe uses
    grade._simulate_to_alpha which does NOT persist anything to alpha_kb.db.

Each probe sim takes ~2 minutes. Test A alone is one sim (~2 min). If Test A is
coerced, Test B + independent bisection adds up to 4 more sims (~8 min).

Outcome is written to:
  .planning/phases/05-delay-0-feasibility-plumbing/05-VERIFICATION.md
The file is rewritten after every sim so partial results survive a 401 interrupt.
"""

import datetime
import json
import sqlite3
import sys
from pathlib import Path

import probe_delay  # provides run_probe / ProbeResult / DelayCoercedError
from wq_login import login

OUT = Path(".planning/phases/05-delay-0-feasibility-plumbing/05-VERIFICATION.md")

# Verbatim 13-key UI delay-0 settings payload captured from the BRAIN web UI
# (05-CONTEXT.md <specifics>, USA/D0/TOP3000). Known-good: the user ran it and it
# returned a real delay-0. Note: NO "maxTrade" key, decay=3, testPeriod="P1Y".
UI_SETTINGS = {
    "nanHandling": "OFF",
    "instrumentType": "EQUITY",
    "delay": 0,
    "universe": "TOP3000",
    "truncation": 0.08,
    "unitHandling": "VERIFY",
    "testPeriod": "P1Y",
    "pasteurization": "ON",
    "region": "USA",
    "language": "FASTEXPR",
    "decay": 3,
    "neutralization": "SUBINDUSTRY",
    "visualization": False,
}


def _flush(lines):
    """Write accumulated report lines to OUT immediately (partial-result safety)."""
    OUT.write_text("\n\n".join(lines))


def _record(lines, header, result):
    """Append one probe round-trip's full diagnostics to the report."""
    verdict = (
        f"COERCED: BRAIN returned delay={result.returned_delay}"
        if result.coerced
        else "PASS: delay=0 confirmed"
    )
    lines.append(header)
    lines.append(f"Settings sent: {json.dumps(result.settings_sent, indent=2)}")
    lines.append(f"Settings returned: {json.dumps(result.returned_settings, indent=2)}")
    lines.append(f"Alpha id: {result.alpha_id}")
    lines.append(f"BRAIN returned delay={result.returned_delay}")
    lines.append(f"Verdict: {verdict}")
    return verdict


def main():
    # --- Section 1: Auth (user triggers biometric ONCE) -------------------------
    print("Starting verify_delay0.py — authenticate with Persona when prompted...")
    client = login()  # ONE call; triggers biometric flow. Never call login() again.
    conn = sqlite3.connect("alpha_kb.db")

    lines = [f"# Delay-0 Verification — {datetime.datetime.now().isoformat()}"]

    try:
        # --- Section 2: Test A — our proven _BASE_SETTINGS with delay flipped to 0 ---
        # No settings_override => run_probe builds {**grade._BASE_SETTINGS, "delay": 0}.
        result_a = probe_delay.run_probe(client, conn, requested_delay=0)
        _record(lines, "## Test A — _BASE_SETTINGS with delay=0", result_a)
        _flush(lines)

        if not result_a.coerced:
            # Test A PASS: the main code path honors delay-0. No fallback needed.
            lines.append("Test B skipped (Test A PASS)")
            lines.append(
                "## Conclusion\n\n"
                "delay-0 IS feasible from code. Our proven _BASE_SETTINGS with "
                "delay=0 returned delay=0 from BRAIN. No settings change required "
                "for probe_delay.py — the default minimal-change path works."
            )
            _flush(lines)
            print("\nTest A PASS: delay=0 confirmed. Test B skipped. See", OUT)
            return

        # --- Section 3: Test B (only reached if Test A coerced) ----------------------
        # Fall back to the known-good UI-verbatim 13-key object.
        lines.append("## Test B — UI-verbatim settings (13 keys, known-good)")
        result_b = probe_delay.run_probe(
            client, conn, requested_delay=0, settings_override=dict(UI_SETTINGS)
        )
        _record(lines, "### Test B baseline — UI verbatim", result_b)
        _flush(lines)

        # Independent bisection: test each of the 3 diffs SEPARATELY from the UI
        # baseline (not stacked), so a single offending key is unambiguous.
        b_diffs = [
            ("Test B1 — UI + maxTrade=ON (our extra key)",
             {**UI_SETTINGS, "maxTrade": "ON"}, "maxTrade"),
            ("Test B2 — UI with decay=15 (our value)",
             {**UI_SETTINGS, "decay": 15}, "decay"),
            ("Test B3 — UI with testPeriod=P1Y6M (our value)",
             {**UI_SETTINGS, "testPeriod": "P1Y6M"}, "testPeriod"),
        ]
        triggers = []
        for header, settings, key in b_diffs:
            res = probe_delay.run_probe(
                client, conn, requested_delay=0, settings_override=settings
            )
            verdict = _record(lines, f"### {header}", res)
            if res.coerced:
                lines.append(f"Trigger identified: {key}")
                triggers.append(key)
            _flush(lines)

        # Only if all three individual diffs pass, test the combination (B4).
        if not triggers:
            res4 = probe_delay.run_probe(
                client, conn, requested_delay=0,
                settings_override={
                    **UI_SETTINGS, "maxTrade": "ON", "decay": 15,
                    "testPeriod": "P1Y6M",
                },
            )
            _record(lines, "### Test B4 — all three diffs applied together", res4)
            if res4.coerced:
                lines.append("Trigger: combination of maxTrade + decay + testPeriod")
                triggers.append("combination(maxTrade,decay,testPeriod)")
            _flush(lines)

        # --- Section 4: Conclusion ---------------------------------------------------
        if triggers:
            conclusion = (
                "## Conclusion\n\n"
                f"Test A (our _BASE_SETTINGS) was COERCED to delay={result_a.returned_delay}. "
                "The UI-verbatim object and independent bisection identified the "
                f"coercion trigger(s): {', '.join(triggers)}. "
                "Recommended action: update probe_delay.py / grade._BASE_SETTINGS so "
                "delay-0 requests drop or adjust the offending key(s), or have "
                "probe_delay.run_probe use the UI-verbatim object for delay-0."
            )
        else:
            conclusion = (
                "## Conclusion\n\n"
                f"Test A was COERCED to delay={result_a.returned_delay}, but every "
                "independent bisection sim (including our values) returned delay=0. "
                "This suggests the coercion was session-transient or expression-driven "
                "rather than settings-driven. Re-run Test A to confirm; if it now "
                "passes, no settings change is needed. Record this in memory."
            )
        lines.append(conclusion)
        _flush(lines)
        print("\nTest A COERCED. Test B + bisection complete. See", OUT)
    finally:
        # --- Section 5: Cleanup ------------------------------------------------------
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
