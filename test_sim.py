"""
End-to-end smoke test: log in (handling biometrics) and run ONE backtest.
Does NOT submit anything — submission is intentionally left out for now.
"""

from wq_login import login

client = login()

# A simple price-reversion alpha.
EXPR = "close / ts_mean(close, 20) - 1"

print(f"\nSimulating: {EXPR}")
sim = client.simulate(EXPR)
sim.wait(verbose=True)  # blocks until done; only returns the alpha id + status

# The IS stats (sharpe/fitness/turnover/...) live on the full alpha object,
# not the simulation-progress JSON — so fetch the alpha details.
alpha = sim.get_alpha()
stats = alpha["is"]

sharpe = stats["sharpe"]
fitness = stats["fitness"]

print(f"\nSharpe:   {sharpe:.4f}")
print(f"Fitness:  {fitness:.4f}")
print(f"Turnover: {stats.get('turnover', float('nan')):.4f}")
print(f"Returns:  {stats.get('returns', float('nan')):.4f}")

if sharpe > 1.25 and fitness > 1.0:
    print("PASS — alpha meets the example thresholds!")
else:
    print("Below threshold, but the full API chain works end-to-end.")
