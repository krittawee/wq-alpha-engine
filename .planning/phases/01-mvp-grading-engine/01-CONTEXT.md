# Phase 1: MVP Grading Engine - Context

**Gathered:** 2026-06-07
**Status:** Ready for planning
**Source:** Synthesized from verified design doc (`docs/plans/2026-06-07-alpha-system-design.md`)

<domain>
## Phase Boundary

Phase 1 delivers a **runnable grading engine with NO LLM in the loop**: it builds a
grounded knowledge base, validates expressions locally, grades a hand-seeded list of
FastExpr expressions against BRAIN's *real* checks, and persists everything to SQLite.

In scope (ENG-01..ENG-07):
1. Sync BRAIN operators, data-fields, settings options → SQLite catalog.
2. Sync the user's existing/submitted alphas → SQLite (self-correlation memory).
3. Local validator: reject expressions with unknown operators/fields or malformed
   syntax BEFORE any simulation.
4. Grade by simulating → read `is.checks` IS results, reading each check's `limit`
   (never hardcode 1.25/0.7).
5. For IS survivors, resolve SELF/PROD_CORRELATION via `POST /alphas/{id}/check`
   (poll → read from `is.checks`); persist values.
6. Persist every graded alpha + a normalized per-check record; dedupe by expression.
7. Run end-to-end over a seed list, concurrency ≤3 on one shared session, never
   re-auth in loop.

Out of scope for Phase 1: any LLM agent (Researcher/Ideator/Editor → Phase 2-3),
local PnL self-corr (Phase 3 — Phase 1 uses the server `POST /check`), Frequent
Subtree Avoidance (Phase 3), Settings Optimizer / decay monitor / Obsidian prose
(Phase 4), and automated submission (permanently manual).
</domain>

<decisions>
## Implementation Decisions (LOCKED — from the verified design)

### Storage
- Single SQLite file `alpha_kb.db` (Python stdlib `sqlite3`). Schema below is locked.
- Add `alpha_kb.db` to `.gitignore` (local data, not committed).

### Grounding (catalog) — all hand-written; the SDK lacks these endpoints
- Operators: `GET /operators`.
- Data-fields: `GET /data-fields?dataset.id=…&region=…&delay=…&universe=…` (PAGINATED — must page through results).
- Settings options: from BRAIN's region/universe metadata.
- Never hardcode operator/field lists — always source from the API.

### Login / session
- Reuse `wq_login.py` as-is (biometric-aware). Log in ONCE per run; reuse the hot
  `BrainClient._session` for every call. **Never re-authenticate inside the loop** —
  a 401 must surface and STOP the run (429 BIOMETRICS_THROTTLED lockout risk).

### Simulation
- Reuse the `autobrain-sim` chain proven in `test_sim.py`: `client.simulate(expr)` →
  `sim.wait()` → `sim.get_alpha()`.
- **Always call `simulate(expr)` with the DEFAULT `regular` param** — the SDK's
  `regular` handling is buggy and silently drops the expression otherwise.
- `sim.wait()` returns only progress JSON; the stats + `is.checks` come from
  `get_alpha()`.

### Grading = two phases, BRAIN is source of truth
- Phase A: simulate → `get_alpha()` → iterate `alpha["is"]["checks"]` array. Each
  check is `{name, result: PASS|FAIL|WARNING, limit, value}`. Read `result` and
  `limit` dynamically; treat any `result == FAIL` as blocking. The check list is
  NON-EXHAUSTIVE — iterate whatever BRAIN returns (e.g. LOW_SHARPE, LOW_FITNESS,
  LOW/HIGH_TURNOVER, CONCENTRATED_WEIGHT, LOW_SUB_UNIVERSE_SHARPE,
  MATCHES_COMPETITION, units). SELF_CORRELATION / PROD_CORRELATION are PENDING here.
- Phase B (IS survivors only): `POST /alphas/{id}/check` (hand-written) → poll
  `GET /alphas/{id}` until SELF_CORRELATION / PROD_CORRELATION leave PENDING → read
  their `value` from `is.checks`. This is a second async op (~minutes). Self-corr
  threshold configurable (default 0.7, region-scoped).

### Concurrency
- Cap concurrent simulations at ≤3 on the one shared session (BRAIN slot cap +
  throttle). Sequential is acceptable for Phase 1; if a pool is used, bound it ≤3.

### Fixed settings (Phase 1)
- Use the default BASE_SETTINGS: region USA, universe TOP3000, delay 1, decay 15,
  neutralization SUBINDUSTRY, truncation 0.08, testPeriod P1Y6M. Settings are stored
  per-alpha (the optimizer that varies them is Phase 4).

### Claude's Discretion
- Module decomposition (e.g. `db.py`, `sync.py`, `validate.py`, `grade.py`, CLI
  entrypoint), polling intervals/backoff, CLI argument shape, seed-list file format,
  and how the validator parses arity (a pragmatic check is fine — full FastExpr
  parsing is not required).
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design (authoritative)
- `docs/plans/2026-06-07-alpha-system-design.md` — full design: SQLite schema,
  hand-written endpoints table, submittability two-phase flow, known gotchas.

### Existing code to reuse / generalize
- `wq_login.py` — biometric-aware login; returns a ready `BrainClient`. Reuse as-is.
- `test_sim.py` — proven simulate→wait→get_alpha chain. Generalize to a list +
  `is.checks` reading (replace its hardcoded `sharpe>1.25 and fitness>1.0`).
- `venv/lib/python3.14/site-packages/brain_client.py` — the SDK surface: only
  `authenticate/simulate/get_alpha/get_pnl/get_recordset/login`; HTTP Basic auth via
  `session.auth`. No operators/data-fields/check/submit — those are hand-written.
</canonical_refs>

<specifics>
## Specific Artifacts

### SQLite schema (locked — copy into the implementation)
```sql
CREATE TABLE alphas (
  alpha_id TEXT PRIMARY KEY, expression TEXT NOT NULL, parent_alpha_id TEXT,
  archetype TEXT, region TEXT, universe TEXT, delay INTEGER,
  decay INTEGER, neutralization TEXT, truncation REAL, settings_json TEXT,
  sharpe REAL, fitness REAL, turnover REAL, returns REAL, drawdown REAL, margin REAL,
  long_count INTEGER, short_count INTEGER,
  self_corr REAL, prod_corr REAL, corr_checked_at TEXT, pnl_path TEXT,
  status TEXT, run_id TEXT, created_at TEXT
);
CREATE TABLE checks (
  alpha_id TEXT, name TEXT, result TEXT, value REAL, limit_val REAL, checked_at TEXT,
  PRIMARY KEY (alpha_id, name)
);
CREATE TABLE operators  (name TEXT PRIMARY KEY, category TEXT, definition TEXT, signature TEXT);
CREATE TABLE datafields (id TEXT, description TEXT, dataset TEXT, region TEXT,
                         universe TEXT, delay INTEGER, type TEXT,
                         PRIMARY KEY (id, region, universe, delay, dataset));
CREATE TABLE runs (run_id TEXT PRIMARY KEY, thesis TEXT, started_at TEXT,
                   iterations INTEGER, num_pass INTEGER, notes TEXT);
CREATE INDEX idx_alphas_expr ON alphas(expression);
CREATE INDEX idx_alphas_arch ON alphas(archetype, status);
```

### Hand-written endpoints (SDK lacks these)
| Purpose | Endpoint |
|---------|----------|
| Resolve SELF/PROD_CORRELATION | `POST /alphas/{id}/check` then poll `GET /alphas/{id}` |
| Operators catalog | `GET /operators` |
| Data-fields catalog | `GET /data-fields?dataset.id=…&region=…&delay=…&universe=…` (paginated) |

Base URL: `https://api.worldquantbrain.com` (from `brain_client.BASE_URL`). Use the
authenticated `client._session` for hand-written calls so they ride the same auth.

### Acceptance (phase success)
A `grade.py`-style entrypoint takes a seed list of expressions and produces, for
each: validation result, IS check verdicts (read from `is.checks`), and — for IS
survivors — self/prod correlation, all persisted to `alpha_kb.db`. No hardcoded
thresholds; concurrency ≤3; no in-loop re-auth.
</specifics>

<deferred>
## Deferred Ideas

- LLM Researcher / Ideator / Editor → Phase 2-3
- Local PnL-based self-correlation pre-filter → Phase 3 (Phase 1 uses server `POST /check`)
- Frequent Subtree Avoidance → Phase 3
- Settings Optimizer, decay monitor, Obsidian prose layer → Phase 4
- Automated submission → permanently out of scope (manual/human-gated)
</deferred>

---

*Phase: 01-mvp-grading-engine*
*Context synthesized: 2026-06-07 from the verified design doc (skipped discuss-phase — design already complete)*
