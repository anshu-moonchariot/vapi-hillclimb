"""Generate iteration curve plot from an optimization run.

Usage:
  conda run -n vapi-takehome python scripts/plot.py --run-id optimize_20260414T083847
"""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()

    run_dir = ROOT / "runs" / args.run_id
    summary = json.loads((run_dir / "optimization_summary.json").read_text())

    baseline = summary["baseline_score"]
    iterations = summary["iteration_log"]

    xs = [0] + [it["t"] for it in iterations]
    ys = [baseline]
    best = baseline
    for it in iterations:
        if it["decision"] == "accepted":
            best = it["best_score_after"]
        ys.append(best)

    try:
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.plot(xs, ys, marker="o", linewidth=2, color="#2563eb", label="Best score so far")
        ax.axhline(baseline, linestyle="--", color="#dc2626", linewidth=1.2, label=f"Baseline ({baseline:.3f})")
        ax.set_xlabel("Iteration")
        ax.set_ylabel("Mean Aggregate Score")
        ax.set_title("Vapi Agent Optimization — Score vs. Iteration")
        ax.set_ylim(max(0, baseline - 0.15), 1.05)
        ax.set_xticks(xs)
        ax.legend()
        ax.grid(True, alpha=0.3)

        out = ROOT / "results" / "iteration_curve.png"
        out.parent.mkdir(exist_ok=True)
        fig.savefig(out, dpi=150, bbox_inches="tight")
        print(f"Plot saved → {out}")
    except ImportError:
        print("matplotlib not available; printing CSV instead:")
        for x, y in zip(xs, ys):
            print(f"  iteration={x}  best_score={y:.4f}")


if __name__ == "__main__":
    main()
