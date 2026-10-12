"""Content-addressed fantasy prediction, capture, and evaluator identities.

Old byte-hash cohorts are never aliased to these identities. First adoption is
an explicit new prospective cohort, not retrospective qualification.
"""
import ast
import hashlib
import json
import sys
from importlib.metadata import version as package_version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PREDICTION = {
    'fantasy_decision_models': None,
    'fantasy_simulation': None,
    'fantasy_locks': None,
    'roster_stat_model': {'estimate', 'finite'},
    'fantasy_specialists': {'candidate'},
    'fantasy_specialist_totals': {'ros_research'},
    'fantasy_score_history': {'distributions', 'scoring_hash'},
    'fantasy_component_history': {'distributions'},
    'fantasy_schedule': {'coverage'},
    'player_identity': None,
    'result_eligibility': None,
    'lab_availability': None,
    'injury_evidence': {'game_snapshots', 'for_game'},
}
CAPTURE = {
    'fantasy_prospective': {'candidates', 'capture_forecasts'},
    'fantasy_weekly_evidence': {'candidates'},
    'fantasy_lineup_validation': {'frozen'},
    'roster_stat_prospective': {'publish'},
}
EVALUATOR = {
    'fantasy_result_recovery': None,
    'fantasy_prospective': None,
    'fantasy_lineup_validation': None,
    'fantasy_weekly_evidence': None,
    'fantasy_sleeper_results': None,
    'fantasy_evidence_counts': None,
    'fantasy_score_history': None,
    'fantasy_component_history': None,
    'result_eligibility': None,
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


class WithoutDocs(ast.NodeTransformer):
    def visit_Expr(self, node):
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return None
        return self.generic_visit(node)


def component_tree(source, selected=None):
    tree = WithoutDocs().visit(ast.parse(source))
    if selected is not None:
        definitions = {node.name: node for node in tree.body
                       if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
        required = set(selected)
        if not required <= definitions.keys():
            raise ValueError('Required versioned function missing')
        # Include local helper bodies transitively, not just the entry point.
        while True:
            dependencies = {node.id for name in required for node in ast.walk(definitions[name])
                            if isinstance(node, ast.Name)} & definitions.keys()
            if dependencies <= required:
                break
            required |= dependencies
        tree.body = [node for node in tree.body if not isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) or node.name in required]
    # Imports/constants stay included conservatively. Formatting, comments and
    # docstrings do not change identity; executable constants and helpers do.
    return tree


def semantic_component(source, selected=None):
    return hashlib.sha256(ast.dump(component_tree(source, selected), include_attributes=False).encode()).hexdigest()


def manifest(root=ROOT, runtime=None):
    def components(spec):
        return {name: semantic_component((root / 'src/services' / f'{name}.py').read_text(), selected)
                for name, selected in spec.items()}
    allowed = {'src.services.' + name for name in PREDICTION} | {
        'src.services.fantasy_prospective', 'src.ingest.espn_fantasy_constants'}
    for name, selected in PREDICTION.items():
        tree = component_tree((root / 'src/services' / f'{name}.py').read_text(), selected)
        for node in ast.walk(tree):
            modules = [node.module or ''] if isinstance(node, ast.ImportFrom) else (
                [alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
            for module in modules:
                if module.startswith(('src.services.', 'src.ingest.')) and module not in allowed:
                    raise ValueError(f'Unversioned prediction dependency: {module}')
    runtime = runtime if runtime is not None else {
        'python': f'{sys.version_info.major}.{sys.version_info.minor}',
        **{name: package_version(name) for name in ('numpy', 'scipy', 'sqlalchemy')},
    }
    prediction = {'code': components(PREDICTION), 'runtime': runtime,
        'identity_rules': semantic_component(Path(__file__).read_text()),
        'espn_scoring_constants': semantic_component((root / 'src/ingest/espn_fantasy_constants.py').read_text()),
        'player_crosswalk': digest(json.loads((root / 'config/nfl_player_lab_ids.json').read_text()))}
    capture = {'code': components(CAPTURE)}
    evaluator = {'code': components(EVALUATOR), 'runtime': runtime}
    prediction_version = digest(prediction)
    capture_version = digest(capture)
    body = {'schema_version': 1, 'prediction': prediction, 'capture': capture,
        'evaluator': evaluator, 'prediction_version': prediction_version,
        'capture_version': capture_version, 'evaluator_version': digest(evaluator),
        'cohort_version': digest({'schema': 1, 'prediction': prediction_version, 'capture': capture_version}),
        'legacy_evidence_policy': 'retain_original_versions_no_alias_or_promotion'}
    return {**body, 'manifest_id': digest(body)}


def reference(identity):
    return {key: identity[key] for key in ('schema_version', 'manifest_id', 'prediction_version',
                                         'capture_version', 'evaluator_version', 'cohort_version')}


def archive_identity(root, identity):
    from src.services.roster_stat_prospective import publish
    path = root / 'manifests' / f"{identity['manifest_id']}.json"
    if digest({k: v for k, v in identity.items() if k != 'manifest_id'}) != identity['manifest_id']:
        raise ValueError('Manifest content does not match its identity')
    publish(path, identity)
    if json.loads(path.read_text()) != identity:
        raise ValueError('Existing immutable manifest conflicts with current identity')
    return path
