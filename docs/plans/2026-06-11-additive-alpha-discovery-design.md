# Design — Additive, Decorrelated, Delay-Aware Alpha Discovery

**Date:** 2026-06-11
**Status:** Design agreed (not yet implemented — build later as a new GSD milestone)
**Context:** Follows v1.0 (Phases 1–4). Reframes the system's goal after two lessons this
session: (1) BRAIN silently coerces delay-0→delay-1 (recording bug now fixed); (2) a
"submittable" alpha (`1Ygw09oz`) would have *dropped* the team score by 112 because it
was too correlated to the existing book — passing the checks ≠ improving the portfolio.

---

## North star

**Additivity is the objective; passing the checks is the constraint.**

A "good" alpha is one that *adds to the team competition score* — i.e. is decorrelated
enough from the existing book to pull its weight — while still passing BRAIN's checks.
Every tool optimizes additivity subject to staying submittable.

Delay-0 is the primary diversification lever: the team is heavily delay-1, so delay-0
alphas are structurally decorrelated from the book almost by construction (and carry a
higher quality bar).

---

## Two standalone tools (one shared BRAIN session, run one at a time)

Decoupled so either runs alone — critical because the AI has usage limits but BRAIN+time
do not. When the AI is unavailable, the brute-force tool still runs.

### Tool A — LLM hunt (= evolved `/hunt`)
- research → ideate → grade → mutate (existing loop).
- AI-driven, **sim-light** (a few smart candidates).
- Changes: add `--delay`; replace "best by Sharpe" selection with the **additivity gate**.

### Tool B — Brute-force (NEW, e.g. `/bruteforce`)
- template → local validate → probe-sim → bulk-sim → gate.
- **AI-free** (combinatorial generation), **sim-heavy** — the long pole on BRAIN time.
- Built **in-repo** (decision: option 1), reusing existing auth/db/grade/validate.
- Borrows ACE's (`JediNakDev/wq-alpha-sim`) four template *shapes* (sentiment, fundamental,
  residual, beta) as inspiration — NOT its runtime (its `relogin.py` + auto-submit are
  lockout / score-tanking risks; auto-submit stays OFF, nothing submits without the gate).
- Absorbs `/optimize`'s settings-variant logic (settings = just more variables to enumerate).

### Why not run them simultaneously (yet)
The LLM steps never touch BRAIN (researcher/ideator/editor take `conn`, not `client`);
only `grade.py` (simulate, correlation) and `sync.py` touch the session. So both tools are
just *producers* of candidate expressions. The only shared scarce resource is the **one
BRAIN session capped at ≤3 concurrent sims** (a second login = biometric throttle lockout).
Because brute-force saturates those 3 slots for hours anyway, true simultaneity buys little.
Start: run one tool at a time, sharing the cached session. Later (optional): a single
sim-queue/session-owner both producers feed, for real overlap.

---

## Shared components (mostly already exist)

| Component | Status | Role |
|---|---|---|
| `wq_login.py` | exists | One cached BRAIN session; single-shot auth, never re-auth in loop |
| `db.py` / `alpha_kb.db` | exists | One store (gitignored) |
| `validate.py` | exists | Local validity pre-filter (free; kills junk combos before sims) |
| `grade.py` | exists (settings recording fixed) | The only BRAIN-sim + correlation primitives |
| `selfcorr.py` | exists | Local PnL correlation proxy (cheap "how correlated to my book?") |
| **Additivity gate** | **NEW** | The keystone. Filter (yes/no) in discovery; score (maximize) in refinement. Nothing submits without it. Uses local PnL proxy to rank, confirms finalists with the real BRAIN correlation check (+ optionally competition before/after API). |

---

## Candidate flow (any source)

```
generate (LLM or brute-force)
  → local validate            (free, all combos)
  → [brute-force only] probe-sim a small sample  (cheap; drop dead template shapes)
  → bulk-sim survivors        (BRAIN, ≤3 concurrent, one session)
  → IS-check filter           (from sim results)
  → rank by local PnL correlation proxy   (free)
  → confirm finalists with real BRAIN correlation check   (additivity gate)
  → collect the additive ones
Stop when: quota of 5 additive delay-0 alphas met, OR ~4h session expires
           (a 401 stops cleanly — natural budget ceiling), OR dry (no new candidates).
Output: a quota/shortlist of additive delay-0 candidates for the user to submit.
```

Memory: collect **survivors + structured failure-reasons**, NOT every raw combo (avoids DB
landfill). Distill into insights for future LLM template design — but keep an explicit
diversity/avoidance pressure (FSA) so a learn-from-winners loop doesn't converge and
re-create the correlation problem. (Learning loop = deliberate phase 2, not day one.)

---

## Command consolidation

| Command | Fate |
|---|---|
| `/hunt` | Tool A. Keep, evolve (`--delay`, additivity gate) |
| `/find-alphas` | **Fold into `/hunt --research-only`** — it's /hunt's front half (AI-only, no BRAIN) |
| `/bruteforce` | **NEW** — Tool B |
| `/iterate` | Keep + **grow a "decorrelate this submittable alpha" mode** (additivity as objective). Two modes: make-it-pass, make-it-more-additive |
| `/optimize` | **Demote to library** — `optimizer.py` reused inside Tool B |
| `/decay` | Unchanged — book monitoring, orthogonal |

The "improve an already-submittable alpha" use case = `/iterate`'s new decorrelate mode:
seed a passing alpha, generate variants (neutralization swap is the big lever; also settings,
small mutations, or delay-0), keep the most-additive variant that *still passes*. Honest
caveat: decorrelating usually costs Sharpe, so it's a **constrained** search — sometimes the
original is already the best tradeoff.

---

## Build order (when implementing, via a new GSD milestone)

0. **Delay-0 feasibility (step zero):** run one delay-0 sim from code, confirm BRAIN echoes
   `delay=0`. The UI works, so if code still gets delay-1 it's a send-bug to fix. Gate the
   whole delay-0 effort on this.
1. **Additivity gate** — the keystone everything else depends on.
2. **Tool B brute-force engine** — in-repo, ACE template shapes, reuse optimizer/validate/selfcorr.
3. **Evolve `/hunt`** (`--delay`, gate) and **fold `/find-alphas`** into it.
4. **`/iterate` decorrelate mode.**
5. *(later, optional)* shared sim-queue for true simultaneity; learning/memory loop.
