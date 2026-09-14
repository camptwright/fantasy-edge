"""Frozen prospective MLB count-only experiment; never used by serving routes."""
import math
from functools import lru_cache
from pathlib import Path
from src.services.model_version import semantic_hash, digest
from src.services.shadow_props import count_distribution, probabilities

RECIPE = 'mlb_count_only_v1'
MARKETS = frozenset({'rbis', 'hits', 'runs', 'home_runs', 'strikeouts'})


@lru_cache(maxsize=1)
def recipe_version():
    root = Path(__file__).parent
    return digest({name: semantic_hash((root/name).read_text()) for name in
                   ('count_only_shadow.py', 'shadow_props.py', 'player_features.py', 'stat_identity.py')})


def predict(feature, line, sport):
    if sport != 'mlb' or not feature or feature.get('canonical_stat') not in MARKETS:
        return {}
    try:
        mean, variance = feature['mean'], feature['variance']
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                   for v in (mean, variance, line)) or mean < 0 or variance < 0 or feature.get('games', 0) < 4:
            return {}
        distribution, name = count_distribution(mean, .5*variance+.5*mean)
        result = probabilities(distribution, line)
    except (TypeError, ValueError, KeyError):
        return {}
    if result['model_probability'] is None:
        return {}
    return {RECIPE: {**result, 'recipe_version': recipe_version(), 'status': 'shadow_only',
        'distribution': name, 'mean': mean, 'variance': distribution.var(),
        'comparison_baseline': 'retained_baseline', 'primary_market': 'rbis',
        'analysis_role': 'primary' if feature['canonical_stat'] == 'rbis' else 'exploratory',
        'protocol': 'first-capture-utc-day-30d-plus-7d-grading-v1',
        'mean_shift': False, 'automatic_deployment': False}}
