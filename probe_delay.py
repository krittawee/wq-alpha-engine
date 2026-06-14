"""probe_delay.py — Delay-0 feasibility probe gate.

Probe-gate contract (D-04):
    Before any delay-0 hunt or brute-force run, the caller fires ONE probe simulation
    via probe_and_gate(). This function:
      - Sends a single simulation at the requested delay (default 0).
      - Reads BRAIN's *returned* delay from the response (BRAIN is the source of truth).
      - If BRAIN confirms the requested delay → returns a ProbeResult (success).
      - If BRAIN coerces to a different delay → raises DelayCoercedError (fail fast).

    The probe reuses the caller's already-authenticated client. It NEVER calls login().
    A 401 from the underlying simulate call propagates unchanged — the caller stops the
    run, consistent with the project's never-re-auth-in-loop rule.

    The probe counts as 1 simulation toward the ≤3 concurrent-sim concurrency cap.

Intentional coupling to grade._simulate_to_alpha:
    probe_delay.py is part of the same project and intentionally imports and calls the
    private function grade._simulate_to_alpha(). This avoids duplicating the retry /
    backoff / 401-propagation logic that function already encapsulates. This is deliberate
    internal coupling (same repo, same developer), not a design error.

    IMPORTANT: simulate() must NEVER be called with the `regular=` keyword — the SDK's
    `regular` param is buggy and silently drops the expression (CLAUDE.md constraint).
    _simulate_to_alpha wraps the correct call pattern; use it, do not call client.simulate()
    directly.

    _simulate_to_alpha does NOT persist any alpha to alpha_kb.db — it is purely a
    simulation/result-fetching call. Probe sims are ephemeral (no DB writes).

conn parameter (reserved):
    Both run_probe() and probe_and_gate() accept a `conn` parameter for future use
    (e.g., recording probe results to alpha_kb.db). In this version, conn is NOT used
    and is accepted only to keep the call signature stable for callers that already pass
    a DB connection.
"""

import sys
from typing import Optional, NamedTuple

import grade


# ---------------------------------------------------------------------------
# Probe expression
# ---------------------------------------------------------------------------

# PROBE_EXPRESSION is a minimal expression using a claimed delay-0 field.
# "rank(vwap)" is expected to work for the default TOP3000 USA configuration,
# but availability depends on the region/universe/operator catalog — it is
# "likely valid" not "guaranteed for all configs."
PROBE_EXPRESSION = "rank(vwap)"


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

class ProbeResult(NamedTuple):
    """Full diagnostic snapshot of one probe simulation round-trip."""
    returned_delay: int   # BRAIN's returned delay (from alpha_dict["settings"]["delay"])
    alpha_id: str         # Alpha ID from BRAIN's response
    requested_delay: int  # What was requested
    coerced: bool         # True if returned_delay != requested_delay
    returned_settings: dict  # Full settings dict from alpha_dict["settings"]
    settings_sent: dict      # Full settings dict that was sent to BRAIN


class DelayCoercedError(RuntimeError):
    """Raised when BRAIN returns a different delay than was requested.

    Carries structured fields so callers can log a precise message without
    parsing the exception string.

    Attributes:
        requested_delay (int): The delay value that was sent in the request.
        returned_delay (int):  The delay value BRAIN actually ran.
        alpha_id (str):        The alpha ID from BRAIN's response.
    """

    def __init__(
        self,
        requested_delay: int,
        returned_delay: int,
        alpha_id: str,
        message: str = "",
    ):
        self.requested_delay = requested_delay
        self.returned_delay = returned_delay
        self.alpha_id = alpha_id
        if not message:
            message = (
                f"BRAIN coerced delay={requested_delay} -> delay={returned_delay} "
                f"(alpha_id={alpha_id}). "
                f"Delay-{requested_delay} is not working on this session. "
                f"Aborting to avoid burning sim slots."
            )
        super().__init__(message)

    def __str__(self) -> str:  # noqa: D105
        return (
            f"DelayCoercedError(requested_delay={self.requested_delay}, "
            f"returned_delay={self.returned_delay}, alpha_id={self.alpha_id!r}): "
            f"{super().__str__()}"
        )


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def run_probe(
    client,
    conn,
    requested_delay: int = 0,
    settings_override: Optional[dict] = None,
) -> ProbeResult:
    """Fire one probe simulation and return a full diagnostic ProbeResult.

    Non-throwing diagnostic helper: always returns a ProbeResult, never raises
    DelayCoercedError. Callers that need fail-fast behavior should use
    probe_and_gate() instead.

    Args:
        client:           Authenticated BRAIN client (pre-authenticated by caller;
                          this function never calls login()).
        conn:             Reserved for future probe-result recording to alpha_kb.db.
                          Not used in this version; accepted to keep the signature stable.
        requested_delay:  The delay value to request (default 0).
        settings_override: If provided, use this dict verbatim as the simulation
                          settings instead of building from _BASE_SETTINGS. This
                          allows Test B callers to pass a UI-verbatim settings object
                          (known-good payload) without bypassing probe_delay.py.

    Returns:
        ProbeResult with full round-trip diagnostic data.

    Raises:
        requests.exceptions.HTTPError (401): Auth expired — propagates unchanged.
        RuntimeError: If _simulate_to_alpha exhausts retries. Propagates unchanged.
    """
    # Build probe settings: use settings_override verbatim if provided,
    # otherwise build a copy of _BASE_SETTINGS with the requested delay.
    # IMPORTANT: never mutate grade._BASE_SETTINGS — always build a new dict.
    if settings_override is not None:
        probe_settings = settings_override
    else:
        probe_settings = {**grade._BASE_SETTINGS, "delay": requested_delay}

    # Fire one simulation. _simulate_to_alpha handles retry/backoff/401.
    # Never pass regular= (SDK buggy param trap — CLAUDE.md constraint).
    _sim, alpha_dict = grade._simulate_to_alpha(
        client, PROBE_EXPRESSION, settings=probe_settings
    )

    # Extract BRAIN's returned delay. BRAIN may omit the key if the value
    # matches the request, so fall back to what was sent.
    returned_settings = alpha_dict.get("settings") or {}
    raw_delay = returned_settings.get("delay")
    if raw_delay is None:
        # Key absent — assume BRAIN honored the request (no coercion signal)
        returned_delay_int = int(probe_settings.get("delay", requested_delay))
    else:
        returned_delay_int = int(raw_delay)

    alpha_id = alpha_dict.get("id", "unknown")

    print(
        f"[probe_delay] Probe result: requested delay={requested_delay} "
        f"BRAIN returned delay={returned_delay_int}",
        file=sys.stderr,
    )

    return ProbeResult(
        returned_delay=returned_delay_int,
        alpha_id=alpha_id,
        requested_delay=requested_delay,
        coerced=(returned_delay_int != requested_delay),
        returned_settings=returned_settings,
        settings_sent=probe_settings,
    )


def probe_and_gate(
    client,
    conn,
    requested_delay: int = 0,
    settings_override: Optional[dict] = None,
) -> ProbeResult:
    """Probe BRAIN for the requested delay and raise if coerced.

    Fires one probe simulation (via run_probe), reads BRAIN's returned delay,
    and either:
      - Returns the ProbeResult if BRAIN honored the requested delay.
      - Raises DelayCoercedError if BRAIN coerced to a different delay.

    This is the gating wrapper used before delay-0 hunt/brute-force runs (D-04).
    Fail-fast on coercion prevents burning sim slots on a session where BRAIN
    won't run the requested delay.

    Args:
        client:           Authenticated BRAIN client (never re-auths internally).
        conn:             Reserved for future use; passed through to run_probe().
        requested_delay:  The delay value to request (default 0).
        settings_override: Passed verbatim to run_probe() (see run_probe docs).

    Returns:
        ProbeResult if BRAIN returned the requested delay.

    Raises:
        DelayCoercedError: If BRAIN returned a delay != requested_delay.
        requests.exceptions.HTTPError (401): Auth expired — propagates unchanged.
        RuntimeError: If simulation fails after retries.
    """
    result = run_probe(client, conn, requested_delay, settings_override)

    if result.coerced:
        raise DelayCoercedError(
            requested_delay=requested_delay,
            returned_delay=result.returned_delay,
            alpha_id=result.alpha_id,
            message=(
                f"BRAIN coerced delay={requested_delay} -> delay={result.returned_delay} "
                f"(alpha_id={result.alpha_id}). "
                f"Delay-{requested_delay} is not working on this session. "
                f"Aborting to avoid burning sim slots."
            ),
        )

    return result
