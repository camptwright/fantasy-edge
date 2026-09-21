"""Semantic code fingerprints; immutable legacy forecasts retain their versions."""
import ast
import hashlib
import json
from pathlib import Path
from src.services.serving_calibration import deployment_status
from src.services.serving_distributions import distribution_status


class WithoutDocs(ast.NodeTransformer):
    def visit_Expr(self, node):
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return None
        return self.generic_visit(node)


def semantic_hash(source, functions=None):
    tree = WithoutDocs().visit(ast.parse(source))
    if functions is not None:
        tree.body = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and node.name in functions]
        if {node.name for node in tree.body} != set(functions):
            raise ValueError('versioned serving function missing')
    return hashlib.sha256(ast.dump(tree, include_attributes=False).encode()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def manifest():
    root = Path(__file__).resolve().parents[1]
    files = ('services/elo.py', 'services/totals.py', 'services/projections.py',
             'utils/odds_math.py', 'services/serving_calibration.py',
             'services/probability_calibration.py', 'services/serving_distributions.py',
             'services/stat_identity.py', 'services/result_eligibility.py')
    code = {name: semantic_hash((root/name).read_text()) for name in files}
    code['services/serving_calibration.py'] = semantic_hash((root/'services/serving_calibration.py').read_text(), {'calibrate_home_probability'})
    code['services/probability_calibration.py'] = semantic_hash((root/'services/probability_calibration.py').read_text(), {'transform'})
    # Inline serving calculations live here. New unrelated routes no longer
    # invalidate all forecast cohorts. Edits inside these functions remain
    # conservatively versioned until calculation/presentation are separated.
    code['serving_functions'] = semantic_hash((root/'api/routers/sportsbook.py').read_text(),
                                             {'signal_rows', 'prop_rows'})
    moneyline = deployment_status()
    dist = distribution_status()
    evidence = dist.get('evidence') or {}
    active = {'spread': evidence.get('spread', {}).get('parameters') if dist['spread_enabled'] else None,
              'props': {stat: evidence['player_props'][stat]['parameters'] for stat in dist['player_prop_stats']}}
    model = {'schema': 2, 'code': code,
        'moneyline': {k: moneyline[k] for k in ('enabled', 'slope', 'intercept')},
        'distribution': active}
    policy = {name: semantic_hash((root/name).read_text()) for name in
              ('services/quote_eligibility.py', 'services/injury_evidence.py', 'services/prop_requirements.py',
               'services/prop_validation.py', 'ingest/prop_events.py',
               'services/prospective_review.py', 'services/model_review.py', 'services/forecast_grading.py',
               'services/roster_evidence.py', 'services/forecast_capture.py', 'services/player_features.py')}
    model_version, policy_version = digest(model), digest(policy)
    return {'schema_version': 2, 'model': model, 'policy': policy,
        'model_version': model_version, 'policy_version': policy_version,
        'cohort_version': digest({'model': model_version, 'policy': policy_version})}
