"""show_results.py — quick view of graded alphas in alpha_kb.db.

Default mode is a pure local DB read: no BRAIN login, no API calls.
With --live it logs in ONCE (single-shot, never re-auth in-loop — CLAUDE.md)
and fills the BOOK_Δ column from BRAIN's Performance Comparison endpoint.

Columns:
    RANK       ranking position (by --sort key, default sharpe desc)
    ALPHA_ID   BRAIN alpha id
    SHARPE     in-sample Sharpe
    DELAY      0 or 1 (BRAIN's actual returned delay, never the requested value)
    STATUS     pass | near | fail | queued
    SELF_CORR  correlation to your own book      (BRAIN POST /check)
    PROD_CORR  correlation to production          (BRAIN POST /check)
    FITNESS    in-sample fitness
    BOOK_Δ     team-score Change (Before - After submission) from BRAIN's
               "Performance Comparison" view. "-" unless --live. This is the
               true additivity number: negative = submitting hurts the book.

Usage:
    python show_results.py
    python show_results.py --status pass
    python show_results.py --delay 0
    python show_results.py --sort self_corr --limit 50
    python show_results.py --live                       # fill BOOK_Δ from BRAIN
    python show_results.py --live --competition IQC2026S2
    python show_results.py --debug-json rKL7xWld        # dump raw BRAIN response
"""

import argparse
import json
import os
import sqlite3
import sys

_SORT_KEYS = {"sharpe", "fitness", "self_corr", "prod_corr"}

API_BASE = "https://api.worldquantbrain.com"
DEFAULT_COMPETITION = "IQC2026S2"


# --------------------------------------------------------------------------
# BRAIN Performance Comparison (Before/After submission) — only used with --live
# --------------------------------------------------------------------------

def _num(v):
    """Coerce a scalar to float, else None (ignores dicts/lists/strings-with-%)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip().rstrip("%").replace(",", "")
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _walk(node, parent_key=""):
    """Yield (parent_key, dict_node) for every dict reachable in the JSON."""
    if isinstance(node, dict):
        yield parent_key, node
        for k, v in node.items():
            yield from _walk(v, k)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item, parent_key)


def extract_score_change(data):
    """Best-effort: find the score node with before/after and return its Change.

    Returns (before, after, change) as floats, or (None, None, None). Prefers a
    node hinted as a 'score' (the Delay-N Score panel) over the per-metric
    Aggregate Data deltas. If the guess is wrong, use --debug-json to see the
    real shape and we tighten this.
    """
    candidates = []
    for pkey, node in _walk(data):
        keys = {k.lower(): k for k in node.keys()}
        bk = next((keys[k] for k in keys if "before" in k), None)
        ak = next((keys[k] for k in keys if "after" in k), None)
        if not (bk and ak):
            continue
        before, after = _num(node[bk]), _num(node[ak])
        if before is None and after is None:
            continue
        ck = next(
            (keys[k] for k in keys if "change" in k or "diff" in k or "delta" in k),
            None,
        )
        if ck is not None and _num(node[ck]) is not None:
            change = _num(node[ck])
        elif before is not None and after is not None:
            change = after - before
        else:
            change = None
        score_hint = ("score" in pkey.lower()) or any("score" in k for k in keys)
        candidates.append((score_hint, before, after, change))

    if not candidates:
        return None, None, None
    candidates.sort(key=lambda c: not c[0])  # score-hinted first
    _, before, after, change = candidates[0]
    return before, after, change


def fetch_before_after(client, alpha_id, competition):
    """GET the raw before-and-after-performance JSON for one alpha."""
    url = (
        f"{API_BASE}/competitions/{competition}"
        f"/alphas/{alpha_id}/before-and-after-performance"
    )
    resp = client._session.get(url)
    resp.raise_for_status()
    return resp.json()


def _fmt_change(change):
    if change is None:
        return f"{'N/A':>7}"
    if abs(change - round(change)) < 1e-9:
        return f"{int(round(change)):+d}".rjust(7)
    return f"{change:+.2f}".rjust(7)


# --------------------------------------------------------------------------

def _fmt(val, width, prec=4):
    if val is None:
        return f"{'N/A':>{width}}"
    return f"{val:>{width}.{prec}f}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Show graded alphas from alpha_kb.db."
    )
    parser.add_argument("--db", default="alpha_kb.db", help="SQLite DB path")
    parser.add_argument("--status", default=None,
                        help="Filter by status (pass|near|fail|queued). Default: all.")
    parser.add_argument("--delay", type=int, default=None, choices=[0, 1],
                        help="Filter by delay (0 or 1). Default: both.")
    parser.add_argument("--sort", default="sharpe", choices=sorted(_SORT_KEYS),
                        help="Sort key (descending, NULLs last). Default: sharpe.")
    parser.add_argument("--limit", type=int, default=30, help="Max rows (default 30).")
    parser.add_argument("--live", action="store_true",
                        help="Log in ONCE and fill BOOK_Δ from BRAIN's Performance "
                             "Comparison endpoint.")
    parser.add_argument("--competition", default=DEFAULT_COMPETITION,
                        help=f"Competition id for --live (default {DEFAULT_COMPETITION}).")
    parser.add_argument("--debug-json", metavar="ALPHA_ID", default=None,
                        help="Fetch one alpha's raw before-and-after JSON and print it "
                             "(needs login). Use this to confirm field names.")
    args = parser.parse_args()

    # --- debug: dump raw response for a single alpha, then exit ---------------
    if args.debug_json:
        from wq_login import login
        client = login()
        try:
            data = fetch_before_after(client, args.debug_json, args.competition)
        except Exception as e:  # noqa: BLE001 — surface anything for diagnosis
            print(f"[show_results] fetch failed for {args.debug_json}: {e}")
            sys.exit(1)
        print(json.dumps(data, indent=2)[:8000])
        b, a, c = extract_score_change(data)
        print(f"\n[parser] before={b} after={a} change={c}")
        return

    if not os.path.exists(args.db):
        print(f"[show_results] no database at '{args.db}'.")
        print("[show_results] run `python sync.py` then grade some alphas first.")
        sys.exit(1)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    where, params = [], []
    if args.status:
        where.append("LOWER(status) = LOWER(?)")
        params.append(args.status)
    if args.delay is not None:
        where.append("delay = ?")
        params.append(args.delay)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    order_sql = f"ORDER BY ({args.sort} IS NULL), {args.sort} DESC"

    rows = conn.execute(
        f"""SELECT alpha_id, sharpe, delay, status, self_corr, prod_corr, fitness
            FROM alphas {where_sql} {order_sql} LIMIT ?""",
        (*params, args.limit),
    ).fetchall()
    conn.close()

    if not rows:
        print(f"[show_results] no alphas matched in '{args.db}'.")
        return

    # --- optional live BOOK_Δ fetch (single-shot login) ----------------------
    book_change = {}  # alpha_id -> change float, or "err"
    if args.live:
        import requests
        from wq_login import login
        print(f"[show_results] --live: logging in once for competition "
              f"{args.competition} ...")
        client = login()
        for r in rows:
            aid = r["alpha_id"]
            try:
                data = fetch_before_after(client, aid, args.competition)
                _, _, change = extract_score_change(data)
                book_change[aid] = change
            except requests.exceptions.HTTPError as e:
                code = getattr(getattr(e, "response", None), "status_code", None)
                if code == 401:
                    print("[show_results] AUTH EXPIRED (401) — stopping. "
                          "Re-run to re-authenticate.")
                    sys.exit(1)
                book_change[aid] = "err"
            except Exception:  # noqa: BLE001
                book_change[aid] = "err"

    header = (
        f"{'RANK':>4}  {'ALPHA_ID':<12}  {'SHARPE':>8}  {'DLY':>3}  "
        f"{'STATUS':<7}  {'SELF_CORR':>9}  {'PROD_CORR':>9}  {'FITNESS':>8}  {'BOOK_Δ':>7}"
    )
    print()
    print(header)
    print("-" * len(header))

    for i, r in enumerate(rows, start=1):
        aid = r["alpha_id"]
        delay = "N/A" if r["delay"] is None else str(r["delay"])
        if not args.live:
            book = f"{'-':>7}"
        elif book_change.get(aid) == "err":
            book = f"{'err':>7}"
        else:
            book = _fmt_change(book_change.get(aid))
        print(
            f"{i:>4}  "
            f"{(aid or ''):<12}  "
            f"{_fmt(r['sharpe'], 8)}  "
            f"{delay:>3}  "
            f"{(r['status'] or ''):<7}  "
            f"{_fmt(r['self_corr'], 9)}  "
            f"{_fmt(r['prod_corr'], 9)}  "
            f"{_fmt(r['fitness'], 8)}  "
            f"{book}"
        )
    print("-" * len(header))
    print(f"{len(rows)} alpha(s) shown (sorted by {args.sort}).")
    if not args.live:
        print("BOOK_Δ shows '-' — pass --live to fill it from BRAIN's Performance "
              "Comparison (Before - After submission team score).")


if __name__ == "__main__":
    main()
