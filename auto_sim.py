"""auto_sim.py — Template-driven alpha batch simulator.

Generates alpha expressions from TEMPLATES (from ga_brain_search.ipynb) and
auto-simulates them via BRAIN, saving passing candidates without any Claude
involvement — zero token cost after startup.

Usage:
    python auto_sim.py                          # 20 random alphas, delay=1, TOP3000
    python auto_sim.py --n 40 --delay 0         # delay-0 run
    python auto_sim.py --n 20 --out results.json
    python auto_sim.py --templates              # list available template names
    python auto_sim.py --template grp_corr      # restrict to one template

TEMPLATES (from ga_brain_search.ipynb):
    seed_alpha, ts_rank_cs, ts_zscore_cs, ts_mean_cs, ts_delta_cs, ts_std_cs,
    bf_rank, bf_zscore, grp_neut_rank, grp_neut_zscore, grp_rank, grp_zscore,
    diff_rank, ratio_rank, corr_cs, diff_delta, tanh_ts, sigmoid_ts,
    grp_diff, grp_corr

ace_lib functions used:
    ace.start_session()                          -> SingleSession
    ace.simulate_multi_alpha(s, list[dict])      -> list[{"alpha_id", "simulate_data"}]
    ace.get_specified_alpha_stats(s, id, data)   -> {"is_stats": DataFrame, ...}
    ace.get_check_submission(s, id)              -> DataFrame of BRAIN checks
    ace.submit_alpha(s, id)                      -> Response
"""

import argparse
import json
import logging
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import ace_lib as ace

# ---------------------------------------------------------------------------
# Hard thresholds — read from BRAIN via /check; these match notebook defaults
# ---------------------------------------------------------------------------
MIN_SHARPE   = 1.25
MIN_FITNESS  = 1.0
MAX_TURNOVER = 0.70

# ---------------------------------------------------------------------------
# Discrete option grids (from ga_brain_search.ipynb)
# ---------------------------------------------------------------------------
DECAY_OPTIONS      = [0, 5, 10, 20, 60]
NEUT_OPTIONS       = ['INDUSTRY', 'SUBINDUSTRY', 'MARKET', 'CROWDING', 'STATISTICAL']
NEUT_OPTIONS_D0    = ['INDUSTRY', 'SUBINDUSTRY', 'MARKET']  # CROWDING/STATISTICAL not available at delay=0
WINDOW_OPTIONS     = [5, 10, 20, 40, 60, 120, 252]
VEC_WRAPPERS   = ['vec_avg', 'vec_sum', 'vec_min', 'vec_max', 'vec_stddev', 'vec_ir']

EXTRA_GROUP_OPTIONS = [
    'market',
    'sector',
    'industry',
    'subindustry',
    'densify(country)',
    'group_cartesian_product(country, subindustry)',
    'group_cartesian_product(country, sector)',
]

# ---------------------------------------------------------------------------
# TEMPLATES — all 21 patterns from ga_brain_search.ipynb cell 9
#
# Placeholder key:
#   {F}  = scalar-compatible field (MATRIX directly, or vec_*(VECTOR))
#   {F2} = second independent scalar field
#   {W}  = lookback window (sampled from WINDOW_OPTIONS)
#   {W2} = second window
#   {G}  = group expression string
# ---------------------------------------------------------------------------
TEMPLATES: list[tuple[str, str]] = [
    ('seed_alpha',      'ts_rank({F}, {W})'),
    ('ts_rank_cs',      'zscore(ts_rank({F}, {W}))'),
    ('ts_zscore_cs',    'rank(ts_zscore({F}, {W}))'),
    ('ts_mean_cs',      'zscore(ts_mean({F}, {W}))'),
    ('ts_delta_cs',     'zscore(ts_delta({F}, {W}))'),
    ('ts_std_cs',       'rank(inverse(ts_std_dev({F}, {W})))'),
    ('bf_rank',         'zscore(ts_rank(ts_backfill({F}, {W}), {W2}))'),
    ('bf_zscore',       'rank(ts_zscore(ts_backfill({F}, {W}), {W2}))'),
    ('grp_neut_rank',   'group_neutralize(zscore(ts_rank({F}, {W})), {G})'),
    ('grp_neut_zscore', 'group_neutralize(rank(ts_zscore({F}, {W})), {G})'),
    ('grp_rank',        'group_rank(ts_rank({F}, {W}), {G})'),
    ('grp_zscore',      'group_zscore(ts_zscore({F}, {W}), {G})'),
    ('diff_rank',       'zscore(subtract(ts_mean({F}, {W}), ts_mean({F2}, {W2})))'),
    ('ratio_rank',      'zscore(divide(ts_mean({F}, {W}), ts_mean({F2}, {W2})))'),
    ('corr_cs',         'zscore(ts_corr({F}, {F2}, {W}))'),
    ('diff_delta',      'zscore(subtract(ts_delta({F}, {W}), ts_delta({F2}, {W2})))'),
    ('tanh_ts',         'tanh(zscore(ts_rank({F}, {W})))'),
    ('sigmoid_ts',      'sigmoid(rank(ts_delta({F}, {W})))'),
    ('grp_diff',        'group_neutralize(zscore(subtract(ts_mean({F}, {W}), ts_mean({F2}, {W2}))), {G})'),
    ('grp_corr',        'group_neutralize(zscore(ts_corr({F}, {F2}, {W})), {G})'),
]

TEMPLATE_MAP: dict[str, str] = {name: pat for name, pat in TEMPLATES}


# ---------------------------------------------------------------------------
# Field pool loading
# ---------------------------------------------------------------------------

def load_field_pools(
    csv_path: str = 'datafields_export.csv',
    region: str = 'USA',
    universe: str = 'TOP3000',
    delay: int = 1,
    accessible_csv: str = 'equity_data_fields.csv',
) -> tuple[list[str], list[str], list[str]]:
    """Load MATRIX / VECTOR / GROUP field IDs, filtered to fields you can actually simulate.

    Problem: datafields_export.csv lists ALL fields in the BRAIN catalog, including
    datasets from subscriptions you don't own. Simulating those returns 403.

    Solution: always cross-reference with equity_data_fields.csv (your accessible
    field list) so only fields in your subscription are used. For delay filtering,
    datafields_export.csv is still used as the source of truth.

    Supports two CSV formats detected by column names:

    Format A — datafields_export.csv:
        columns: id, description, dataset, region, universe, delay, type
        Filters by region/universe/delay, then intersects with accessible_csv.

    Format B — equity_data_fields.csv (or any curated list):
        columns: Field, Description, Type, Alphas
        Used as-is (no delay filter — all fields assumed accessible).

    Returns:
        (matrix_fields, vector_fields, group_fields)
    """
    df = pd.read_csv(csv_path, on_bad_lines='skip', encoding='utf-8-sig')
    df.columns = [c.strip().lstrip('﻿') for c in df.columns]
    cols = set(df.columns)

    if 'delay' not in cols:
        # Format B: no delay column — curated accessible list (equity_data_fields.csv style)
        # Try Field/Type columns; fall back to id/type if Field is missing
        field_col = 'Field' if 'Field' in cols else 'id'
        type_col  = 'Type'  if 'Type'  in cols else 'type'
        matrix = df.loc[df[type_col].str.lower() == 'matrix', field_col].tolist()
        vector = df.loc[df[type_col].str.lower() == 'vector', field_col].tolist()
        group  = df.loc[df[type_col].str.lower() == 'group',  field_col].tolist()
    else:
        # Format A: filter by region/universe/delay first
        mask = (df['region'] == region) & (df['universe'] == universe) & (df['delay'] == delay)
        sub  = df[mask]

        # Then intersect with accessible fields so we never hit 403
        try:
            acc_df = pd.read_csv(accessible_csv, on_bad_lines='skip', encoding='utf-8-sig')
            acc_df.columns = [c.strip() for c in acc_df.columns]
            if 'Field' in acc_df.columns:
                accessible = set(acc_df['Field'].dropna().tolist())
                sub = sub[sub['id'].isin(accessible)]
                print(f'[auto_sim]   (filtered to {len(sub)} accessible fields from {accessible_csv})')
        except FileNotFoundError:
            pass  # no accessible list — use full catalog (may 403 on premium datasets)

        matrix = sub.loc[sub['type'] == 'MATRIX', 'id'].tolist()
        vector = sub.loc[sub['type'] == 'VECTOR', 'id'].tolist()
        group  = sub.loc[sub['type'] == 'GROUP',  'id'].tolist()

    return matrix, vector, group


# ---------------------------------------------------------------------------
# Expression rendering (mirrors ga_brain_search.ipynb cells 11 / functions)
# ---------------------------------------------------------------------------

def make_field_term(field: str, vector_fields: list[str]) -> str:
    """Wrap a VECTOR field in a random vec_* operator; pass MATRIX fields through."""
    if field in vector_fields:
        return f'{random.choice(VEC_WRAPPERS)}({field})'
    return field


def render_template(
    pattern: str,
    matrix_fields: list[str],
    vector_fields: list[str],
    group_options: list[str],
) -> str:
    """Fill {F}/{F2}/{W}/{W2}/{G} placeholders with random choices."""
    all_fields = matrix_fields + vector_fields
    expr = pattern
    if '{F}' in expr:
        expr = expr.replace('{F}', make_field_term(random.choice(all_fields), vector_fields))
    if '{F2}' in expr:
        expr = expr.replace('{F2}', make_field_term(random.choice(all_fields), vector_fields))
    if '{W}' in expr:
        expr = expr.replace('{W}', str(random.choice(WINDOW_OPTIONS)))
    if '{W2}' in expr:
        expr = expr.replace('{W2}', str(random.choice(WINDOW_OPTIONS)))
    if '{G}' in expr:
        expr = expr.replace('{G}', random.choice(group_options))
    return expr


def sample_expressions(
    n: int,
    matrix_fields: list[str],
    vector_fields: list[str],
    group_fields: list[str],
    template_filter: str | None = None,
) -> list[tuple[str, str]]:
    """Sample n unique (template_name, expression) pairs.

    Args:
        n: Number of distinct expressions to generate.
        matrix_fields: MATRIX field IDs.
        vector_fields: VECTOR field IDs.
        group_fields: GROUP field IDs from the catalog.
        template_filter: If set, restrict to this template name only.

    Returns:
        List of (template_name, rendered_expression) tuples.
    """
    group_options = group_fields + EXTRA_GROUP_OPTIONS
    pool = [(nm, pat) for nm, pat in TEMPLATES if template_filter is None or nm == template_filter]
    if not pool:
        raise ValueError(f'Unknown template: {template_filter!r}. Run --templates to list names.')

    seen: set[str] = set()
    results: list[tuple[str, str]] = []
    attempts = 0
    while len(results) < n and attempts < n * 20:
        attempts += 1
        name, pattern = random.choice(pool)
        expr = render_template(pattern, matrix_fields, vector_fields, group_options)
        if expr not in seen:
            seen.add(expr)
            results.append((name, expr))
    return results


# ---------------------------------------------------------------------------
# Sim payload builder
# ---------------------------------------------------------------------------

def build_alpha_config(
    expr: str,
    region: str = 'USA',
    universe: str = 'TOP3000',
    delay: int = 1,
    decay: int | None = None,
    neutralization: str | None = None,
) -> dict:
    """Build a BRAIN simulation payload dict for a REGULAR FASTEXPR alpha.

    Decay and neutralization are sampled randomly if not specified.
    Note: 'regular' here is the API payload key, not the SDK simulate() param.
    """
    neut_pool = NEUT_OPTIONS_D0 if delay == 0 else NEUT_OPTIONS
    return {
        'type': 'REGULAR',
        'settings': {
            'instrumentType': 'EQUITY',
            'region':         region,
            'universe':       universe,
            'delay':          delay,
            'decay':          decay if decay is not None else random.choice(DECAY_OPTIONS),
            'neutralization': neutralization or random.choice(neut_pool),
            'truncation':     0.08,
            'pasteurization': 'ON',
            'testPeriod':     'P1Y6M',
            'unitHandling':   'VERIFY',
            'nanHandling':    'OFF',
            'maxTrade':       'ON',
            'language':       'FASTEXPR',
            'visualization':  False,
        },
        'regular': expr,
    }


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def composite_score(sharpe: float, fitness: float, turnover: float) -> float:
    """Composite fitness: reward Sharpe + fitness, lightly penalise high turnover.

    Returns -100 for any alpha that fails a hard threshold.
    """
    if sharpe < MIN_SHARPE or fitness < MIN_FITNESS or turnover > MAX_TURNOVER:
        return -100.0
    return sharpe + fitness - max(0.0, turnover - 0.3) * 0.5


def _extract_stats(is_stats: pd.DataFrame) -> tuple[float, float, float]:
    """Pull (sharpe, fitness, turnover) from an is_stats DataFrame row."""
    if is_stats is None or is_stats.empty:
        return 0.0, 0.0, 1.0
    row = is_stats.iloc[0]
    sharpe   = float(row.get('sharpe',   0.0) or 0.0)
    fitness  = float(row.get('fitness',  0.0) or 0.0)
    turnover = float(row.get('turnover', 1.0) or 1.0)
    return sharpe, fitness, turnover


# ---------------------------------------------------------------------------
# Core runner
# ---------------------------------------------------------------------------

def run(
    n: int = 20,
    region: str = 'USA',
    universe: str = 'TOP3000',
    delay: int = 1,
    batch_size: int = 3,
    out: str | None = None,
    fields_csv: str = 'datafields_export.csv',
    template_filter: str | None = None,
    seed: int | None = None,
    verbose: bool = False,
) -> list[dict]:
    """Generate, simulate, and filter alphas from the template library.

    Args:
        n: Total number of expressions to simulate.
        region: BRAIN region (e.g. 'USA').
        universe: BRAIN universe (e.g. 'TOP3000').
        delay: Sim delay (0 or 1).
        batch_size: Number of alphas per multi-sim batch (cap ≤ 10).
        out: If set, write passing alphas to this JSON file.
        fields_csv: Path to datafields_export.csv.
        template_filter: Restrict to one template name (None = all templates).
        seed: Optional random seed for reproducibility.

    Returns:
        List of passing alpha dicts with keys:
            alpha_id, template, expression, sharpe, fitness, turnover,
            score, settings, simulated_at.
    """
    if seed is not None:
        random.seed(seed)

    if verbose:
        logging.getLogger('ace').setLevel(logging.DEBUG)

    print(f'[auto_sim] region={region} universe={universe} delay={delay} n={n}')
    print('[auto_sim] Starting session...')
    s = ace.start_session()

    print(f'[auto_sim] Loading fields from {fields_csv}...')
    matrix, vector, group = load_field_pools(fields_csv, region=region, universe=universe, delay=delay)
    print(f'[auto_sim]   MATRIX={len(matrix)}  VECTOR={len(vector)}  GROUP={len(group)}')
    if not matrix and not vector:
        print('[auto_sim] ERROR: No fields found for this region/universe/delay. Check your CSV.')
        return []

    print(f'[auto_sim] Sampling {n} expressions...')
    exprs = sample_expressions(n, matrix, vector, group, template_filter=template_filter)
    configs = [build_alpha_config(expr, region=region, universe=universe, delay=delay) for _, expr in exprs]

    all_results: list[dict] = []
    passing: list[dict] = []
    ts_now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    expr_to_name = {expr: name for name, expr in exprs}

    def _record(alpha_id, expr, sim_data):
        name = expr_to_name.get(expr, '?')
        if not alpha_id:
            print(f'  SIM_FAIL  [{name}] {expr[:70]}')
            return
        stat = ace.get_specified_alpha_stats(s, alpha_id, sim_data)
        sharpe, fitness, turnover = _extract_stats(stat.get('is_stats'))
        score = composite_score(sharpe, fitness, turnover)
        flag  = 'PASS' if score > 0 else 'fail'
        settings = sim_data.get('settings', {})
        print(
            f'  {flag:4s}  sharpe={sharpe:.3f} fit={fitness:.3f} to={turnover:.3f}'
            f'  [{name}] decay={settings.get("decay",0)} neut={settings.get("neutralization","")}'
            f'  {expr[:60]}'
        )
        rec = {
            'alpha_id': alpha_id, 'template': name, 'expression': expr,
            'sharpe': sharpe, 'fitness': fitness, 'turnover': turnover,
            'score': score, 'settings': settings, 'simulated_at': ts_now,
        }
        all_results.append(rec)
        if score > 0:
            passing.append(rec)

    if delay == 0:
        # BRAIN's multi-sim endpoint (list payload) returns 403 at delay=0.
        # Use simulate_alpha_list instead: 3 concurrent single-alpha POSTs.
        print(f'[auto_sim] Simulating {len(configs)} alphas (delay=0: single-alpha mode, 2 concurrent)...')
        stat_results = ace.simulate_alpha_list(s, configs, limit_of_concurrent_simulations=2)
        for stat in stat_results:
            alpha_id = stat.get('alpha_id')
            sim_data = stat.get('simulate_data', {})
            expr = sim_data.get('regular', '')
            _record(alpha_id, expr, sim_data)
    else:
        for batch_i in range(0, len(configs), batch_size):
            batch_configs = configs[batch_i:batch_i + batch_size]
            batch_exprs   = exprs[batch_i:batch_i + batch_size]
            print(f'[auto_sim] Batch {batch_i // batch_size + 1}: simulating {len(batch_configs)} alphas...')
            sim_results = ace.simulate_multi_alpha(s, batch_configs)
            for (_, expr), sim_res in zip(batch_exprs, sim_results):
                _record(sim_res.get('alpha_id'), expr, sim_res.get('simulate_data', {}))

    print(f'\n[auto_sim] {len(passing)}/{len(all_results)} passed '
          f'(sharpe>{MIN_SHARPE}, fitness>{MIN_FITNESS}, turnover<{MAX_TURNOVER})')

    if passing:
        print('\nPassing alphas (sorted by score):')
        for r in sorted(passing, key=lambda x: -x['score']):
            print(f"  [{r['score']:.3f}] {r['expression']}")
            print(f"         alpha_id={r['alpha_id']}  "
                  f"decay={r['settings'].get('decay')}  neut={r['settings'].get('neutralization')}")

    if out:
        with open(out, 'w') as f:
            json.dump(passing, f, indent=2, default=str)
        print(f'\n[auto_sim] Saved {len(passing)} passing alphas → {out}')

    return passing


# ---------------------------------------------------------------------------
# Session diagnostics
# ---------------------------------------------------------------------------

def check_session() -> None:
    """Print session status and fire a minimal hardcoded sim to confirm BRAIN access.

    Use this to diagnose 403 / auth issues before running a full batch.
    Shows the raw HTTP status and BRAIN response body so you can see exactly
    what BRAIN is rejecting and why.
    """
    import ace_lib as ace  # local re-import so the function is self-contained
    brain_api_url = ace.brain_api_url

    print('[check_session] Starting session...')
    s = ace.start_session()

    print('[check_session] Checking session timeout...')
    remaining = ace.check_session_timeout(s)
    if remaining > 0:
        print(f'[check_session] Session LIVE — {remaining}s remaining')
    elif remaining == 0:
        print('[check_session] Session EXPIRED — need fresh login (possibly biometric)')
        return
    else:
        print('[check_session] Session timeout check failed transiently (network blip)')

    # Fire a single minimal sim: ts_rank(close, 10), delay=1, no exotic fields
    test_payload = {
        'type': 'REGULAR',
        'settings': {
            'instrumentType': 'EQUITY',
            'region':         'USA',
            'universe':       'TOP3000',
            'delay':          1,
            'decay':          0,
            'neutralization': 'INDUSTRY',
            'truncation':     0.01,
            'pasteurization': 'ON',
            'testPeriod':     'P0Y0M0D',
            'unitHandling':   'VERIFY',
            'nanHandling':    'OFF',
            'maxTrade':       'OFF',
            'language':       'FASTEXPR',
            'visualization':  False,
        },
        'regular': 'ts_rank(close, 10)',
    }

    print('[check_session] Sending test sim: ts_rank(close, 10) delay=1 ...')
    resp = s.post(brain_api_url + '/simulations', json=test_payload)
    print(f'[check_session] POST /simulations → HTTP {resp.status_code}')

    if resp.status_code in (200, 201, 202):
        loc = resp.headers.get('Location', '(no Location header)')
        print(f'[check_session] OK — sim accepted, progress URL: {loc}')
        print('[check_session] Session and sim access are working correctly.')
    else:
        print(f'[check_session] FAILED — BRAIN response body:')
        try:
            print('  ', resp.json())
        except Exception:
            print('  ', resp.text[:500])
        print()
        if resp.status_code == 403:
            print('[check_session] 403 Forbidden: your session cookie is rejected by BRAIN.')
            print('  Cause A: session expired — re-login via the web console (⚠ LOGIN) to refresh the cookie.')
            print('  Cause B: account suspended or missing subscription for this universe.')
        elif resp.status_code == 401:
            print('[check_session] 401 Unauthorized: session not authenticated.')
            print('  Re-run and complete the biometric (persona) check when prompted.')
        elif resp.status_code == 429:
            print('[check_session] 429 Too Many Requests: BIOMETRICS_THROTTLED or rate limit.')
            print('  Wait 15–30 min before retrying. Do NOT call start_session() again.')


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _list_templates() -> None:
    print('Available templates:')
    for name, pattern in TEMPLATES:
        print(f'  {name:<20} {pattern}')


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Template-driven BRAIN alpha batch simulator.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--n',         type=int,   default=20,                 help='Number of alphas to simulate (default: 20)')
    parser.add_argument('--region',    type=str,   default='USA',              help='BRAIN region (default: USA)')
    parser.add_argument('--universe',  type=str,   default='TOP3000',          help='BRAIN universe (default: TOP3000)')
    parser.add_argument('--delay',     type=int,   default=1, choices=[0, 1],  help='Simulation delay (default: 1)')
    parser.add_argument('--batch',     type=int,   default=3,                  help='Multi-sim batch size, max 3 (BRAIN slot cap)')
    parser.add_argument('--out',       type=str,   default=None,               help='Output JSON file for passing alphas')
    parser.add_argument('--csv',       type=str,   default='datafields_export.csv', help='Path to datafields CSV')
    parser.add_argument('--template',  type=str,   default=None,               help='Restrict to one template name')
    parser.add_argument('--templates', action='store_true',                    help='List available template names and exit')
    parser.add_argument('--seed',      type=int,   default=None,               help='Random seed for reproducibility')
    parser.add_argument('--test',      action='store_true',                    help='Check session and fire a minimal test sim to diagnose 403 errors')
    parser.add_argument('--verbose',   action='store_true',                    help='Enable DEBUG logging to show raw BRAIN error bodies on SIM_FAIL')
    args = parser.parse_args()

    if args.templates:
        _list_templates()
        return

    if args.test:
        check_session()
        return

    run(
        n=args.n,
        region=args.region,
        universe=args.universe,
        delay=args.delay,
        batch_size=min(args.batch, 3),
        out=args.out,
        fields_csv=args.csv,
        template_filter=args.template,
        seed=args.seed,
        verbose=args.verbose,
    )


if __name__ == '__main__':
    main()
