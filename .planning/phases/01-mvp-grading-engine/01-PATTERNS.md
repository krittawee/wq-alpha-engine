# Phase 1: MVP Grading Engine - Pattern Map

**Mapped:** 2026-06-07
**Files analyzed:** 6 new modules
**Analogs found:** 5 / 6

---

## File Classification

| New File | Role | Data Flow | Closest Analog | Match Quality |
|----------|------|-----------|----------------|---------------|
| `db.py` | data layer | CRUD | `brain_client.py` (session/state init pattern) | partial |
| `sync.py` | API client | request-response (paginated) | `wq_login.py` (raw `client._session` hand-written calls) | role-match |
| `validate.py` | utility / validator | transform | `test_sim.py` (expression is the unit of work) | partial |
| `grade.py` | orchestration | batch + request-response | `test_sim.py` (simulate→wait→get_alpha chain) | exact |
| `cli.py` | CLI entrypoint | batch | `test_sim.py` (top-level script flow) | role-match |
| `seeds.txt` / `seeds.py` | config / data | — | none | no analog |

---

## Pattern Assignments

### `db.py` (data layer, CRUD)

**Analog:** `brain_client.py` lines 40-60 (session/state initialization pattern)

**Core pattern — module-level init and connection helper:**
```python
# brain_client.py lines 40-44 — init, store state, expose for callers
self._session = requests.Session()
self._authenticated = False

if email and password:
    self._session.auth = (email, password)
```
Mirror this in `db.py`: open connection once, store as module-level or passed object, never re-open inside loops.

**Imports pattern** (copy from `brain_client.py` lines 1-12):
```python
import sqlite3
from pathlib import Path
from typing import Optional
```

**Schema to copy verbatim** (from `01-CONTEXT.md` Specific Artifacts section — locked):
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

**Key db.py functions to implement:**
- `init_db(path="alpha_kb.db") -> sqlite3.Connection` — create tables if not exist, return connection
- `upsert_alpha(conn, alpha_dict)` — INSERT OR REPLACE into `alphas`
- `upsert_checks(conn, alpha_id, checks_list)` — bulk insert into `checks`
- `upsert_operators(conn, rows)` — bulk insert into `operators`
- `upsert_datafields(conn, rows)` — bulk insert into `datafields`
- `expr_exists(conn, expression) -> Optional[str]` — return alpha_id if duplicate (uses `idx_alphas_expr`)

---

### `sync.py` (API client, request-response + paginated)

**Analog:** `wq_login.py` — the hand-written `client._session` pattern for raw HTTP calls against `BASE_URL`

**Critical pattern — hand-written calls ride the existing auth session** (`wq_login.py` lines 24-38):
```python
from brain_client import BrainClient, BASE_URL

# After login(), use client._session for ALL hand-written calls.
# This is the ONLY way to make calls that aren't in the SDK surface.
sess = client._session

r = sess.post(f"{BASE_URL}/authentication")   # example of the pattern
```
Apply identically for sync.py's catalog calls:
```python
# Operators
r = client._session.get(f"{BASE_URL}/operators")
r.raise_for_status()
operators = r.json()   # inspect actual shape; likely {"results": [...], "count": N}

# Data-fields (PAGINATED — must loop offset/limit or cursor)
params = {"dataset.id": dataset_id, "region": region, "delay": delay, "universe": universe, "limit": 100, "offset": 0}
while True:
    r = client._session.get(f"{BASE_URL}/data-fields", params=params)
    r.raise_for_status()
    page = r.json()
    rows = page.get("results", [])
    if not rows:
        break
    # upsert rows into db
    params["offset"] += len(rows)
```

**Error/auth pattern** (`wq_login.py` lines 79-88 and 71-74):
```python
# A 401 must surface and STOP the run — never retry auth inside a loop
if r.status_code == 429 or data.get("detail") == "BIOMETRICS_THROTTLED":
    raise SystemExit("BRAIN rate-limited ...")

if fin.status_code >= 400:
    print("[finalize] WARNING: ...")
```
Mirror: if `client._session.get(...)` returns 401, let `raise_for_status()` propagate — do NOT catch and re-auth.

**Imports pattern** (mirror `wq_login.py` lines 21-24):
```python
from wq_login import login
from brain_client import BASE_URL
import db   # local module
```

**Existing alphas sync** — `GET /alphas` (paginated, same pattern as data-fields above). Store each alpha_id + expression into `alphas` table with status from BRAIN's response.

---

### `validate.py` (utility/validator, transform)

**Analog:** `test_sim.py` — the expression is the unit of work; validate replaces the simulate call as the first gate

**Role:** Reject expressions with unknown operators/fields or malformed syntax BEFORE any simulation is submitted. A pragmatic check is sufficient — full FastExpr AST parsing is NOT required.

**Core validation steps to implement:**
1. Bracket balance check (count `(` vs `)`)
2. Tokenize expression on word boundaries; extract tokens that look like function calls (`word(`)
3. Check each function token against `operators` table in db
4. Check each bare data token against `datafields` table
5. Return `(is_valid: bool, reason: str)`

**Pattern — query db inline, return typed result** (no analog; design from scratch using stdlib):
```python
def validate(conn: sqlite3.Connection, expression: str) -> tuple[bool, str]:
    """Return (True, '') if valid, else (False, reason)."""
    if expression.count("(") != expression.count(")"):
        return False, "unbalanced parentheses"
    # ... operator/field checks against conn
    return True, ""
```

**What NOT to do:** Do not call `client.simulate()` here. Validation is purely local against the synced catalog.

---

### `grade.py` (orchestration, batch + request-response)

**Analog:** `test_sim.py` — the entire simulate→wait→get_alpha chain is the core pattern to generalize

**Simulate chain** (`test_sim.py` lines 8-19 — copy and generalize):
```python
from wq_login import login

client = login()

# For each expression (generalize from single EXPR):
sim = client.simulate(EXPR)      # always pass expression as first positional arg
sim.wait(verbose=True)           # blocks; returns only progress JSON + alpha_id
alpha = sim.get_alpha()          # IS stats + is.checks live HERE, not in wait()
stats = alpha["is"]
```

**CRITICAL simulate() call convention** (`brain_client.py` lines 107-150 — VERIFIED 2026-06-07):
```python
# Signature: simulate(expression, settings=None, alpha_type="REGULAR", regular="close")
# The body does (lines 142-150):
#   payload["regular"] = expression if regular == "close" else regular
#   if regular == "close": payload["regular"] = expression
# => With the DEFAULT regular="close", your `expression` IS what gets submitted. CORRECT.
# => Pass ANY other regular value and the SDK submits THAT value and SILENTLY DROPS
#    your `expression`. That is the trap.
sim = client.simulate(expr)              # correct — let regular default to "close"
# sim = client.simulate(expr, regular="anything")  # WRONG — submits "anything", drops expr
```

**IS checks reading pattern** — generalize `test_sim.py` lines 22-31; replace hardcoded thresholds with dynamic loop:
```python
alpha = sim.get_alpha()
is_data = alpha["is"]

# stats for db storage
sharpe   = is_data.get("sharpe")
fitness  = is_data.get("fitness")
turnover = is_data.get("turnover")
returns  = is_data.get("returns")

# Iterate checks dynamically — BRAIN is source of truth; never hardcode limits
checks = is_data.get("checks", [])   # list of {name, result, limit, value}
passed = True
for check in checks:
    name   = check["name"]
    result = check["result"]     # "PASS" | "FAIL" | "WARNING" | "PENDING"
    limit  = check.get("limit")  # dynamic — read from BRAIN, never hardcode
    value  = check.get("value")
    if result == "FAIL":
        passed = False
    # upsert into checks table
```

**Phase B — SELF/PROD_CORRELATION via hand-written POST + poll** (no SDK equivalent; use `client._session`):
```python
from brain_client import BASE_URL
import time

def trigger_correlation_check(client, alpha_id: str):
    r = client._session.post(f"{BASE_URL}/alphas/{alpha_id}/check")
    r.raise_for_status()

def poll_correlation(client, alpha_id: str, timeout: int = 300, interval: int = 15):
    """Poll GET /alphas/{id} until SELF_CORRELATION + PROD_CORRELATION leave PENDING."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client._session.get(f"{BASE_URL}/alphas/{alpha_id}")
        r.raise_for_status()
        alpha = r.json()
        checks = alpha["is"].get("checks", [])
        corr_checks = {c["name"]: c for c in checks
                       if c["name"] in ("SELF_CORRELATION", "PROD_CORRELATION")}
        pending = [n for n, c in corr_checks.items() if c["result"] == "PENDING"]
        if not pending:
            return corr_checks   # resolved
        time.sleep(interval)
    raise TimeoutError(f"Correlation check timed out for {alpha_id}")
```

**Concurrency cap** — sequential is acceptable for Phase 1; if threading is added, bound pool ≤ 3:
```python
from concurrent.futures import ThreadPoolExecutor
with ThreadPoolExecutor(max_workers=3) as pool:
    futures = [pool.submit(grade_one, client, expr) for expr in expressions]
```

**401 must surface and stop** — mirror the `wq_login.py` principle: never catch HTTPError 401 inside the loop. Let `raise_for_status()` propagate.

**Imports pattern:**
```python
import time
import sqlite3
from wq_login import login
from brain_client import BASE_URL
import db
import validate
```

---

### `cli.py` (CLI entrypoint, batch)

**Analog:** `test_sim.py` lines 1-8 (top-level script flow: import login, call login, run work)

**Pattern to mirror** (`test_sim.py` lines 1-8):
```python
from wq_login import login

client = login()   # one auth per run; reuse client for all work below
```

**Extend with argparse:**
```python
import argparse

def main():
    parser = argparse.ArgumentParser(description="Grade alpha expressions against BRAIN")
    parser.add_argument("seed_file", help="Path to file with one expression per line")
    parser.add_argument("--db", default="alpha_kb.db", help="SQLite database path")
    parser.add_argument("--sync", action="store_true", help="Refresh catalog before grading")
    args = parser.parse_args()

    client = login()        # single auth; no re-auth in loop
    conn = db.init_db(args.db)
    if args.sync:
        import sync
        sync.sync_all(client, conn)
    # load expressions from args.seed_file, call grade.run(client, conn, expressions)
```

**Never re-authenticate inside the loop** — `login()` is called exactly once at the top of `main()`.

---

### `seeds.txt` (config/data)

**No analog.** Simple newline-delimited text file, one FastExpr expression per line. Lines starting with `#` are comments. The CLI reads this with:
```python
expressions = [line.strip() for line in open(seed_file) if line.strip() and not line.startswith("#")]
```

---

## Shared Patterns

### Auth / Session — apply to ALL modules making API calls

**Source:** `wq_login.py` lines 27-38 and 63-72

The single shared `requests.Session` inside `client._session` carries all auth cookies/headers. Every module receives `client` (a `BrainClient`) from `login()` and uses `client._session` for hand-written calls.

```python
# wq_login.py lines 35-38 — session is set up inside BrainClient.__init__
client = BrainClient(email=email, password=password)
sess = client._session   # this is the requests.Session to reuse everywhere

# wq_login.py lines 71-72 — 401 convention: surface, do NOT retry
if fin.status_code >= 400:
    print("[finalize] WARNING: ...")
# grade.py / sync.py must let raise_for_status() propagate 401 — no catch + re-login
```

Apply to: `sync.py`, `grade.py`

### Hand-written endpoint call pattern — apply to `sync.py` and `grade.py`

**Source:** `wq_login.py` line 38; `brain_client.py` line 16

```python
from brain_client import BASE_URL   # "https://api.worldquantbrain.com"

# All hand-written calls:
r = client._session.get(f"{BASE_URL}/operators")
r.raise_for_status()
data = r.json()

r = client._session.post(f"{BASE_URL}/alphas/{alpha_id}/check")
r.raise_for_status()
```

The SDK's `BrainClient` covers only: `authenticate`, `simulate`, `get_alpha`, `get_pnl`, `get_recordset`. Everything else (`/operators`, `/data-fields`, `/alphas/{id}/check`) is hand-written using this pattern.

### Retry-After polling — apply to `grade.py` Phase B correlation poll

**Source:** `brain_client.py` lines 203-212 (`_poll_recordset`) and lines 234-246 (`SimulationResult.wait`)

```python
# brain_client.py lines 234-246 — canonical Retry-After polling loop
while True:
    response = self._session.get(self.progress_url)
    retry_after = float(response.headers.get("Retry-After", 0))
    if retry_after == 0:
        response.raise_for_status()
        self._result = response.json()
        self.alpha_id = self._result.get("alpha")
        return self._result
    sleep(retry_after)
```

Mirror this pattern in `poll_correlation()`: check `Retry-After` header first; if absent, `raise_for_status()` and return.

### Default simulation settings — apply to `grade.py`

**Source:** `brain_client.py` lines 123-138

```python
# brain_client.py lines 123-138 — default settings that grade.py must pass unchanged
default_settings = {
    "instrumentType": "EQUITY",
    "region": "USA",
    "universe": "TOP3000",
    "delay": 1,
    "decay": 15,
    "neutralization": "SUBINDUSTRY",
    "truncation": 0.08,
    "maxTrade": "ON",
    "pasteurization": "ON",
    "testPeriod": "P1Y6M",
    "unitHandling": "VERIFY",
    "nanHandling": "OFF",
    "language": "FASTEXPR",
    "visualization": False,
}
```

`grade.py` calls `client.simulate(expr)` with no `settings=` override in Phase 1 — the SDK default above matches `BASE_SETTINGS` from the design. Store these values per-alpha in `settings_json` column.

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `seeds.txt` | config/data | — | No seed/expression list files exist in this repo |
| `validate.py` (local expression validator) | utility | transform | No local validation logic exists; closest is test_sim.py's single-expression usage but it just calls the API, not a pre-flight validator |

---

## Metadata

**Analog search scope:** `/Users/winter.__.kor/quant/` (wq_login.py, test_sim.py, venv/lib/python3.14/site-packages/brain_client.py)
**Files scanned:** 3 analog files
**Pattern extraction date:** 2026-06-07
