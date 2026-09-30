"""Plots + heatmaps for Derive 10k mainnet runs."""
import json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

runs = json.load(open("/home/david/derive-cesf-botcamp/backtest/derive_10k_results.json"))
ok = [r for r in runs if "error" not in r]
sh = np.array([r["sharpe"] for r in ok])
rt = np.array([r["ret"] for r in ok])

fig, ax = plt.subplots(2, 2, figsize=(13, 9))

# 1. return distribution
ax[0, 0].hist(rt, bins=60, edgecolor="k", alpha=0.7)
ax[0, 0].axvline(0, color="r", ls="--")
ax[0, 0].axvline(rt.mean(), color="g", label=f"mean {rt.mean():+.2f}%")
ax[0, 0].set_title(f"Return distribution, 10k venue runs (pos {(rt>0).mean():.1%})")
ax[0, 0].set_xlabel("return % / 7d"); ax[0, 0].legend(); ax[0, 0].grid(alpha=0.3)

# 2. sharpe distribution (7-point daily, noisy - stated in title)
ax[0, 1].hist(np.clip(sh, -10, 10), bins=60, edgecolor="k", alpha=0.7)
ax[0, 1].axvline(0.5, color="r", ls="--", label="pass 0.5")
ax[0, 1].set_title(f"Sharpe (7-pt daily, noisy) pass {(sh>0.5).mean():.1%}")
ax[0, 1].set_xlabel("Sharpe"); ax[0, 1].legend(); ax[0, 1].grid(alpha=0.3)

# 3. heatmap thresh x cesf (mean return)
ths = sorted(set(r["thresh"] for r in ok))
css = sorted(set(r["cesf"] for r in ok))
z = np.zeros((len(css), len(ths)))
for i, cs in enumerate(css):
    for j, th in enumerate(ths):
        v = [r["ret"] for r in ok if r["thresh"] == th and r["cesf"] == cs]
        z[i, j] = np.mean(v)
im = ax[1, 0].imshow(z, origin="lower", cmap="RdYlGn", aspect="auto")
ax[1, 0].set_xticks(range(len(ths)), ths)
ax[1, 0].set_yticks(range(len(css)), css)
ax[1, 0].set_xlabel("thresh"); ax[1, 0].set_ylabel("cesf_min")
ax[1, 0].set_title("Mean return % by params (Derive venue tape)")
plt.colorbar(im, ax=ax[1, 0])
for i in range(len(css)):
    for j in range(len(ths)):
        ax[1, 0].text(j, i, f"{z[i,j]:+.2f}", ha="center", va="center",
                       fontsize=7, weight="bold")

# 4. per-symbol bars
syms = ["ETH-PERP", "BTC-PERP", "SOL-PERP", "HYPE-PERP"]
mr = [np.mean([r["ret"] for r in ok if r["symbol"] == s]) for s in syms]
pr = [np.mean([r["ret"] > 0 for r in ok if r["symbol"] == s]) for s in syms]
x = np.arange(len(syms))
ax[1, 1].bar(x, mr, alpha=0.7)
ax[1, 1].set_xticks(x)
ax[1, 1].set_xticklabels([s.replace("-PERP", "") for s in syms])
ax[1, 1].set_title("Mean return % per symbol")
ax[1, 1].grid(alpha=0.3, axis="y")
for i, (m, p) in enumerate(zip(mr, pr)):
    ax[1, 1].text(i, m + 0.005, f"{m:+.2f}%\n{p:.0%}pos", ha="center", fontsize=8)

plt.tight_layout()
plt.savefig("/home/david/derive-cesf-botcamp/backtest/derive_10k_perf.png", dpi=130)
print("saved derive_10k_perf.png")
# adaptation table
adj_runs = [r for r in ok if r["adj"]]
print(f"adjusted runs: {len(adj_runs)}")
ta = np.array([r["ret"] for r in adj_runs])
na = np.array([r["ret"] for r in ok if not r["adj"]])
print(f"adjusted mean {ta.mean():+.3f}% vs unadjusted {na.mean():+.3f}%")
