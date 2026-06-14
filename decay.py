"""decay.py — /decay CLI entrypoint for the Decay Monitor.

Mirrors the hunt.py __main__ pattern exactly:
  - Single-shot login via wq_login.login() (CLAUDE.md: never re-auth in-loop)
  - Calls decay_monitor.run_decay() which re-checks PASS+ACTIVE alphas
  - 401 from BRAIN propagates and exits cleanly (sys.exit(1))

Usage:
    python decay.py [--db alpha_kb.db] [--threshold 0.15]
"""

import argparse
import sys

import requests

from wq_login import login
import decay_monitor

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Decay monitor (/decay).")
    parser.add_argument(
        "--db",
        default="alpha_kb.db",
        help="Path to alpha_kb.db (default: alpha_kb.db)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=decay_monitor.DEFAULT_DECAY_THRESHOLD,
        help="Degradation threshold fraction (default: 0.15 = 15%%)",
    )
    args = parser.parse_args()

    # Single-shot auth — called ONCE before the decay loop (CLAUDE.md constraint).
    # A 401 inside run_decay() propagates here and exits cleanly (never re-auth in-loop).
    print("[decay] logging in...")
    client = login()
    print("[decay] authenticated")

    try:
        result = decay_monitor.run_decay(
            client=client,
            db_path=args.db,
            threshold_pct=args.threshold,
        )
    except requests.exceptions.HTTPError as e:
        if getattr(getattr(e, "response", None), "status_code", None) == 401:
            print("BRAIN AUTH EXPIRED — 401. Re-run to re-authenticate.")
            sys.exit(1)
        raise
