"""optimize.py — CLI entrypoint for the /optimize command.

Usage:
    python optimize.py [--db alpha_kb.db] [--max-workers 1]

Mirrors the hunt.py CLI pattern exactly:
  - Single-shot login before the loop (CLAUDE.md constraint: never re-auth in-loop)
  - 401 from BRAIN stops the run immediately with a clear message
  - EditorAuthError (Claude CLI auth) stops with clear guidance
  - Prints summary on completion

BRAIN constraints (per CLAUDE.md):
  - ≤3 concurrent sims via grade_many MAX_CONCURRENT_SIMS
  - Single-shot auth, 401 propagates without retry
  - max_workers default=1 (sequential) to respect per-alpha slot budget
"""

import argparse
import sys

import requests

import editor
import optimizer
from wq_login import login


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Settings optimizer — tune NEAR alphas via archetype heuristics (/optimize)."
    )
    parser.add_argument(
        "--db",
        default="alpha_kb.db",
        help="Path to alpha_kb.db (default: alpha_kb.db)",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=1,
        help="Max concurrent BRAIN sims per variant batch (default: 1; BRAIN cap ≤3)",
    )
    args = parser.parse_args()

    # Single-shot auth — called ONCE before the loop (CLAUDE.md constraint).
    # A 401 inside optimizer.run_optimize() propagates here and exits cleanly.
    # Never re-authenticate inside the loop — risks 429 BIOMETRICS_THROTTLED lockout.
    print("[optimize] logging in...")
    client = login()
    print("[optimize] authenticated")

    try:
        summary = optimizer.run_optimize(
            client=client,
            db_path=args.db,
            max_workers=args.max_workers,
        )
    except editor.EditorAuthError as e:
        # Claude CLI auth failure — NOT a BRAIN session expiry.
        # Do NOT suggest BRAIN re-auth (risks 429 BIOMETRICS_THROTTLED lockout per CLAUDE.md).
        print(f"[optimize] CLAUDE CLI AUTH FAILURE — {e}")
        print("[optimize] Fix: run 'claude login' to re-authenticate the Claude CLI.")
        print("[optimize] This is NOT a BRAIN session expiry — do NOT re-run optimize.py for BRAIN auth.")
        sys.exit(1)
    except requests.exceptions.HTTPError as e:
        if getattr(getattr(e, "response", None), "status_code", None) == 401:
            print(
                "[optimize] BRAIN AUTH EXPIRED — 401 received. "
                "Re-run optimize.py to re-authenticate with BRAIN. Stopping."
            )
            sys.exit(1)
        raise

    # Print completion summary
    print(
        f"[optimize] done — "
        f"NEAR alphas processed: {summary['near_alphas_processed']}, "
        f"variants simulated: {summary['variants_simulated']}, "
        f"variants passed: {summary['variants_passed']}"
    )
