"""Small baseline-compatible sigmoid recalibrator with a held-out evaluation.

Fit and select on earlier observations. The final chronological block is
reserved for evaluation. Experimental results never automatically promote.
"""
import math


def transform(probability, slope=1.0, intercept=0.0):
    p = min(max(probability, 1e-6), 1 - 1e-6)
    z = max(-35, min(35, slope * math.log(p / (1 - p)) + intercept))
    return 1 / (1 + math.exp(-z))


def metrics(rows, slope=1.0, intercept=0.0):
    if not rows:
        return None
    pairs = [(transform(p.probability, slope, intercept), p.outcome) for p in rows]
    return {
        "samples": len(pairs),
        "brier": sum((p-y)**2 for p, y in pairs) / len(pairs),
        "log_loss": -sum(y*math.log(p)+(1-y)*math.log1p(-p) for p, y in pairs) / len(pairs),
    }


def experiment(rows, minimum_block=50):
    """Select a bounded correction on the early block, evaluate on the late one.

    Caller supplies one prediction per event in chronological order. This
    experiment is provisional until timestamp/result-availability audit passes.
    No final test outcome participates in selecting the correction.
    """
    split = int(len(rows) * 0.7)
    train, test = rows[:split], rows[split:]
    if min(len(train), len(test)) < minimum_block:
        return {"status": "insufficient_samples", "promotion_eligible": False}
    candidates = [(s, b) for s in (0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0)
                  for b in (-0.5, -0.25, 0.0, 0.25, 0.5)]
    slope, intercept = min(candidates, key=lambda x: metrics(train, *x)["log_loss"])
    baseline = metrics(test)
    candidate = metrics(test, slope, intercept)
    return {
        "status": "experimental_holdout", "fit_samples": len(train),
        "slope": slope, "intercept": intercept,
        "baseline": baseline, "candidate": candidate,
        "improves_both_scores": candidate["brier"] < baseline["brier"]
            and candidate["log_loss"] < baseline["log_loss"],
        "promotion_eligible": False,
        "reason": "Requires independent time-valid replay, uncertainty analysis and prospective validation",
    }
