"""Calibration evidence and read-only model health for the Sports board.

The evaluator never promotes a prediction merely because an artifact exists.
Only a time-series out-of-fold result with enough observations and a Brier
score no worse than the configured baseline can unlock qualified assessments.
"""

from __future__ import annotations

from dataclasses import dataclass

@dataclass(frozen=True)
class CalibrationState:
    calibrated: bool
    model_version: str | None
    sample_count: int | None
    oof_brier: float | None


def calibration_state(
    sport: str, *, max_oof_brier: float = 0.25, min_samples: int = 100
) -> CalibrationState:
    """Return artifact-backed calibration evidence for one sport.

    Missing, old, or undersized artifacts fail closed.  The evaluation uses
    training's chronological out-of-fold score, not an in-sample accuracy.
    """
    # The ensemble imports native LightGBM/XGBoost bindings.  Keep that
    # optional runtime dependency out of ordinary API/schema imports; model
    # artifacts are the only place this health check needs it.
    from src.algorithms.ensemble import GameOutcomeEnsemble

    try:
        model = GameOutcomeEnsemble.load_latest(sport)
    except FileNotFoundError:
        return CalibrationState(False, None, None, None)

    metrics = getattr(model, "metrics", None)
    if metrics is None or not all(hasattr(metrics, attr) for attr in ("n_samples", "oof_brier")):
        return CalibrationState(False, getattr(model, "version", None), None, None)

    passing = metrics.n_samples >= min_samples and metrics.oof_brier <= max_oof_brier
    return CalibrationState(
        passing,
        getattr(model, "version", None),
        metrics.n_samples,
        metrics.oof_brier,
    )
