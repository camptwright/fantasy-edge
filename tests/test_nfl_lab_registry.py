from src.services.nfl_lab_registry import artifact_version


def test_artifact_version_binds_coefficients_and_training_evidence():
    artifact={'model':{'coef':[1]},'history_hash':'a'}
    assert len(artifact_version(artifact))==64
    assert artifact_version(artifact)==artifact_version(dict(reversed(list(artifact.items()))))
    assert artifact_version(artifact)!=artifact_version({**artifact,'history_hash':'b'})
