"""XGBoost + LightGBM stacked ensemble with a logistic meta-learner.

Two gradient-boosted trees rarely make the *same* mistakes - they split
differently, regularise differently, handle missing values differently - so
blending them typically beats either alone. The blending weights are learned
(logistic regression on out-of-fold predictions) rather than hand-picked,
because the right blend shifts by sport and by how much data is available.

Stacking correctly requires the meta-learner to train on OUT-OF-FOLD base
predictions, never in-sample ones: if the meta-learner saw predictions from a
model that was trained on that same row, it would learn to trust that model's
overfitting rather than its actual skill. `TimeSeriesSplit` additionally
enforces that every fold's "test" rows come after its "train" rows in time -
an ordinary k-fold shuffle would let the model train on future games and
predict past ones, which is lookahead bias baked directly into the model
rather than just the backtest.
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import TimeSeriesSplit
from xgboost import XGBClassifier

from config.settings import get_settings
from src.utils.logging import get_logger

log = get_logger(__name__)

DEFAULT_N_SPLITS = 5


@dataclass
class EnsembleMetrics:
    n_samples: int
    n_folds: int
    oof_accuracy: float
    oof_brier: float


class GameOutcomeEnsemble:
    """Predicts P(home team wins) from a feature matrix.

    Sport-agnostic and feature-agnostic by design: `scripts/train_models.py`
    is responsible for building `X` (ELO ratings, Poisson lambdas, rolling
    form, rest days, etc. - whatever features that sport's model uses) and
    ordering rows chronologically. This class only owns the stacking
    mechanics.
    """

    def __init__(self, sport: str, *, n_splits: int = DEFAULT_N_SPLITS):
        self.sport = sport
        self.n_splits = n_splits
        self.xgb = XGBClassifier(
            n_estimators=300,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            eval_metric="logloss",
            n_jobs=2,
        )
        self.lgbm = LGBMClassifier(
            n_estimators=300,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            n_jobs=2,
            verbose=-1,
        )
        self.meta = LogisticRegression()
        self._fitted = False

    def fit(self, X: pd.DataFrame, y: pd.Series) -> EnsembleMetrics:
        """`X`/`y` MUST already be sorted chronologically (oldest first) -
        this class trusts row order for TimeSeriesSplit and does not
        re-sort, since it has no date column to sort by once features are
        numeric-only.
        """
        n = len(X)
        n_splits = min(self.n_splits, max(2, n // 20))
        tscv = TimeSeriesSplit(n_splits=n_splits)

        oof_xgb = np.full(n, np.nan)
        oof_lgbm = np.full(n, np.nan)

        for train_idx, test_idx in tscv.split(X):
            xgb_fold = XGBClassifier(**self.xgb.get_params())
            lgbm_fold = LGBMClassifier(**self.lgbm.get_params())

            xgb_fold.fit(X.iloc[train_idx], y.iloc[train_idx])
            lgbm_fold.fit(X.iloc[train_idx], y.iloc[train_idx])

            oof_xgb[test_idx] = xgb_fold.predict_proba(X.iloc[test_idx])[:, 1]
            oof_lgbm[test_idx] = lgbm_fold.predict_proba(X.iloc[test_idx])[:, 1]

        # Rows in the first fold's training window never get an OOF
        # prediction (TimeSeriesSplit's first split has no held-out rows
        # before it) - drop them rather than impute, so the meta-learner
        # never trains on a fabricated value.
        valid = ~np.isnan(oof_xgb)
        meta_X = np.column_stack([oof_xgb[valid], oof_lgbm[valid]])
        meta_y = y.to_numpy()[valid]
        self.meta.fit(meta_X, meta_y)

        # Final base models are refit on ALL data for use at inference time -
        # the OOF models above existed only to produce leakage-free meta
        # features, not to serve predictions themselves.
        self.xgb.fit(X, y)
        self.lgbm.fit(X, y)
        self._fitted = True

        meta_pred = self.meta.predict_proba(meta_X)[:, 1]
        accuracy = float(np.mean((meta_pred >= 0.5).astype(int) == meta_y))
        brier = float(np.mean((meta_pred - meta_y) ** 2))

        metrics = EnsembleMetrics(
            n_samples=n, n_folds=n_splits, oof_accuracy=accuracy, oof_brier=brier
        )
        log.info("ensemble.fit", sport=self.sport, **metrics.__dict__)
        return metrics

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        if not self._fitted:
            raise RuntimeError("call fit() or load() before predict_proba()")
        xgb_pred = self.xgb.predict_proba(X)[:, 1]
        lgbm_pred = self.lgbm.predict_proba(X)[:, 1]
        meta_X = np.column_stack([xgb_pred, lgbm_pred])
        return self.meta.predict_proba(meta_X)[:, 1]

    # ------------------------------------------------------------ persist ----

    def save(self, version: str | None = None) -> Path:
        """Versioned pickle: `{sport}_ensemble_{version}.pkl`. `version`
        defaults to a UTC timestamp so every training run produces a new
        file rather than clobbering the last one - ValueAgent logs which
        version produced a signal, and a bad retrain can be rolled back by
        pointing at the previous file.

        Pickle is safe here: `model_dir` is a local bind mount
        (`/mnt/data/fantasy-edge/models`) written only by
        `scripts/train_models.py` running on this host, never from a
        network response, user upload, or any other untrusted source. A
        stacked sklearn/XGBoost/LightGBM ensemble isn't cleanly JSON- or
        schema-serialisable, which is the usual reason to avoid pickle in
        the first place.
        """
        settings = get_settings()
        settings.model_dir.mkdir(parents=True, exist_ok=True)
        version = version or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = settings.model_dir / f"{self.sport}_ensemble_{version}.pkl"
        with path.open("wb") as fh:
            pickle.dump(self, fh)
        log.info("ensemble.saved", sport=self.sport, path=str(path))
        return path

    @classmethod
    def load_latest(cls, sport: str) -> "GameOutcomeEnsemble":
        settings = get_settings()
        candidates = sorted(settings.model_dir.glob(f"{sport}_ensemble_*.pkl"))
        if not candidates:
            raise FileNotFoundError(f"no trained ensemble found for sport={sport}")
        with candidates[-1].open("rb") as fh:
            model = pickle.load(fh)
        log.info("ensemble.loaded", sport=sport, path=str(candidates[-1]))
        return model
