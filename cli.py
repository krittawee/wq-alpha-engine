"""cli.py — Main entrypoint for the Grounded Alpha Discovery grading pipeline.

Usage:
    python cli.py seeds.txt
    python cli.py seeds.txt --sync
    python cli.py seeds.txt --sync --workers 3
    python cli.py seeds.txt --db custom.db

Authentication: called exactly once per run. A 401 mid-run prints a
clear error and exits non-zero — never re-authenticates in-loop (lockout risk).
"""

import argparse
import sys
import uuid
from datetime import datetime

import requests

from wq_login import login
import db
import sync
import grade


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Grade alpha expressions against BRAIN's IS checks"
    )
    parser.add_argument(
        "seed_file",
        type=str,
        help="Path to text file with one FastExpr expression per line",
    )
    parser.add_argument(
        "--db",
        default="alpha_kb.db",
        help="SQLite database path (default: alpha_kb.db)",
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Refresh catalog from BRAIN before grading",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        choices=[1, 2, 3],
        help="Concurrent simulation slots (max 3, default 1)",
    )
    args = parser.parse_args()

    # Step 1 — Read seed file; filter blank lines and # comments
    try:
        with open(args.seed_file) as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"[cli] ERROR: seed file not found: {args.seed_file}")
        sys.exit(1)

    expressions = [
        l.strip() for l in lines if l.strip() and not l.startswith("#")
    ]
    if not expressions:
        print(f"[cli] No expressions found in {args.seed_file}")
        sys.exit(1)

    # Step 2 — Single-shot authentication (called exactly once per run).
    # Never call the login function inside the grading loop — 429 BIOMETRICS_THROTTLED lockout risk.
    print("[cli] logging in...")
    client = login()
    print("[cli] authenticated")

    # Step 3 — Init DB
    conn = db.init_db(args.db)
    print(f"[cli] db: {args.db}")

    # Step 4 — Optional catalog sync (refreshes operators + data-fields + existing alphas)
    if args.sync:
        print("[cli] syncing catalog...")
        sync.sync_all(client, conn)

    # Step 5 — Generate run_id for this batch
    run_id = str(uuid.uuid4())[:8]
    print(
        f"[cli] grading {len(expressions)} expressions "
        f"(run {run_id}, workers={args.workers})"
    )

    # Step 6 — Grade (with 401 surfacing)
    # A 401 mid-run means the session expired. Print a clear message and exit(1).
    # Never attempt to re-authenticate inside this block.
    results = []
    try:
        results = grade.grade_many(
            client, conn, expressions, run_id,
            max_workers=args.workers, db_path=args.db,
        )
    except requests.exceptions.HTTPError as e:
        if "401" in str(e) or (
            hasattr(e, "response")
            and e.response is not None
            and e.response.status_code == 401
        ):
            print(
                "[cli] AUTH EXPIRED — a 401 was returned. "
                "Re-run cli.py to re-authenticate. Stopping."
            )
            sys.exit(1)
        else:
            raise

    # Step 7 — Print ranked output table (sorted by sharpe descending, None last)
    results_sorted = sorted(
        results,
        key=lambda r: (r.get("sharpe") is None, -(r.get("sharpe") or 0)),
    )

    print()
    print(
        f"{'RANK':>4}  "
        f"{'EXPRESSION':<40}  "
        f"{'STATUS':<10}  "
        f"{'SHARPE':>8}  "
        f"{'FITNESS':>8}  "
        f"{'SELF_CORR':>9}  "
        f"{'PROD_CORR':>9}"
    )
    print("-" * 100)

    for i, r in enumerate(results_sorted, start=1):
        expr_display = (r.get("expression") or "")[:40]
        status_display = (r.get("status") or "").ljust(10)
        sharpe_val = r.get("sharpe")
        fitness_val = r.get("fitness")
        self_corr_val = r.get("self_corr")
        prod_corr_val = r.get("prod_corr")

        sharpe_str = f"{sharpe_val:>8.4f}" if sharpe_val is not None else f"{'N/A':>8}"
        fitness_str = f"{fitness_val:>8.4f}" if fitness_val is not None else f"{'N/A':>8}"
        self_corr_str = f"{self_corr_val:>9.4f}" if self_corr_val is not None else f"{'N/A':>9}"
        prod_corr_str = f"{prod_corr_val:>9.4f}" if prod_corr_val is not None else f"{'N/A':>9}"

        print(
            f"{i:>4}  "
            f"{expr_display:<40}  "
            f"{status_display}  "
            f"{sharpe_str}  "
            f"{fitness_str}  "
            f"{self_corr_str}  "
            f"{prod_corr_str}"
        )

    print("-" * 100)

    # Step 8 — Close connection
    conn.close()
    print("[cli] done")


if __name__ == "__main__":
    main()
