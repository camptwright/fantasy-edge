from src.services import model_health


def test_calibration_requires_passing_out_of_fold_evidence(monkeypatch):
    class Model:
        version = "test"
        class metrics:
            n_samples = 120
            oof_brier = 0.20

    class Ensemble:
        @staticmethod
        def load_latest(_sport):
            return Model()

    import sys
    import types

    monkeypatch.setitem(sys.modules, "src.algorithms.ensemble", types.SimpleNamespace(GameOutcomeEnsemble=Ensemble))
    state = model_health.calibration_state("wnba")
    assert state.calibrated is True
    assert state.oof_brier == 0.20


def test_calibration_fails_closed_without_evidence(monkeypatch):
    class Model:
        version = "old"
        metrics = None

    class Ensemble:
        @staticmethod
        def load_latest(_sport):
            return Model()

    import sys
    import types

    monkeypatch.setitem(sys.modules, "src.algorithms.ensemble", types.SimpleNamespace(GameOutcomeEnsemble=Ensemble))
    assert model_health.calibration_state("wnba").calibrated is False
