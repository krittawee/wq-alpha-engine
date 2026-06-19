"""helpful_functions.py — Minimal stubs for ace_lib dependencies.

These utilities were originally in a separate package. This file provides
the minimum implementations needed by ace_lib.py.
"""

import json
from pathlib import Path
import pandas as pd


def expand_dict_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Expand columns whose values are dicts into separate flattened columns."""
    if df.empty:
        return df
    result = df.copy()
    for col in list(result.columns):
        sample = result[col].dropna()
        if sample.empty:
            continue
        first = sample.iloc[0]
        if isinstance(first, dict):
            expanded = result[col].apply(lambda x: x if isinstance(x, dict) else {})
            expanded_df = pd.json_normalize(expanded.tolist())
            expanded_df.columns = [f'{col}.{c}' for c in expanded_df.columns]
            expanded_df.index = result.index
            result = pd.concat([result.drop(columns=[col]), expanded_df], axis=1)
    return result


def save_pnl(pnl: pd.DataFrame, alpha_id: str, region: str) -> None:
    """Save PnL DataFrame to pnl_cache/<alpha_id>.csv."""
    out_dir = Path('pnl_cache')
    out_dir.mkdir(exist_ok=True)
    if pnl is not None and not pnl.empty:
        pnl.to_csv(out_dir / f'{alpha_id}.csv')


def save_simulation_result(result: dict) -> None:
    """Save raw simulation result JSON to pnl_cache/<alpha_id>.json."""
    alpha_id = result.get('id', 'unknown')
    out_dir = Path('pnl_cache')
    out_dir.mkdir(exist_ok=True)
    with open(out_dir / f'{alpha_id}.json', 'w') as f:
        json.dump(result, f, indent=2)


def save_yearly_stats(stats: pd.DataFrame, alpha_id: str, region: str) -> None:
    """Save yearly stats DataFrame to pnl_cache/<alpha_id>_yearly.csv."""
    out_dir = Path('pnl_cache')
    out_dir.mkdir(exist_ok=True)
    if stats is not None and not stats.empty:
        stats.to_csv(out_dir / f'{alpha_id}_yearly.csv', index=False)
