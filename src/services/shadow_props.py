"""Fixed, unpromoted research recipes. These never price recommendations."""
import math
import hashlib
from pathlib import Path
from functools import lru_cache

COUNT_STATS = {'fg_made', 'xp_made', 'receptions', 'passing_touchdowns', 'passing_interceptions',
    'rushing_touchdowns', 'receiving_touchdowns', 'hits', 'runs', 'rbis', 'home_runs',
    'strikeouts', 'shots_on_goal', 'goals', 'assists', 'rebounds', 'steals', 'blocks'}


@lru_cache(maxsize=1)
def recipe_digest():
    root = Path(__file__).parent
    return hashlib.sha256(b''.join((root/name).read_bytes() for name in
        ('shadow_props.py', 'player_features.py', 'stat_identity.py'))).hexdigest()


def count_distribution(mean, variance):
    mean = max(0., mean)
    if not math.isfinite(mean) or not math.isfinite(variance) or mean > 500:
        raise ValueError('Outside bounded count research support')
    if variance > mean*(1+1e-6) and mean > 0:
        size = mean*mean/(variance-mean)
        probability = math.exp(-size*math.log1p(mean/size))
        name = 'negative_binomial'
    else:
        size, probability, name = None, math.exp(-mean), 'poisson'
    mass = [probability]
    total = probability
    for k in range(1, 2001):
        if total >= 1-1e-12 and k > mean:
            break
        probability *= mean/k if size is None else (k-1+size)/k*(mean/(size+mean))
        mass.append(probability)
        total += probability
    if total < 1-1e-8 or not math.isfinite(total):
        raise ValueError('Count tail exceeds truncation tolerance')
    return Discrete([p/total for p in mass]), name


class Discrete:
    def __init__(self, mass):
        self.mass = mass

    def pmf(self, k):
        return self.mass[k] if isinstance(k, int) and 0 <= k < len(self.mass) else 0.

    def cdf(self, k):
        return math.fsum(self.mass[:max(0, math.floor(k)+1)])

    def sf(self, k):
        return math.fsum(self.mass[max(0, math.floor(k)+1):])

    def var(self):
        mean = math.fsum(k*p for k, p in enumerate(self.mass))
        return math.fsum((k-mean)**2*p for k, p in enumerate(self.mass))


def probabilities(distribution, line):
    over = float(distribution.sf(math.floor(line)))
    under = float(distribution.cdf(math.ceil(line)-1))
    push = float(distribution.pmf(int(line))) if float(line).is_integer() else 0.
    return pack(over, under, push)


def pack(over, under, push):
    nonpush = over+under
    return {'over_probability': over, 'under_probability': under, 'push_probability': push,
            'model_probability': over/nonpush if nonpush > 1e-12 else None,
            'probability_target': 'over_conditional_on_nonpush'}


def predict(feature, line, baseline_sigma):
    if not feature or not math.isfinite(line) or baseline_sigma <= 0:
        return {}
    baseline = feature['mean']
    mean = .5*baseline+.5*feature['recent_mean']
    usage = feature.get('opportunity')
    if usage:
        mean = .5*baseline+.5*usage['observed_rate']*usage['recent_mean']
    mean = max(baseline-baseline_sigma, min(baseline+baseline_sigma, mean))
    normal = {'mean': mean, 'stddev': baseline_sigma, 'distribution': 'normal',
        'model_probability': .5*math.erfc((line-mean)/(baseline_sigma*math.sqrt(2))), 'push_probability': 0.,
        'probability_target': 'over_conditional_on_nonpush', 'status': 'shadow_only'}
    out = {'opportunity_recent_normal_v1': normal}
    stat = feature['canonical_stat']
    if stat in COUNT_STATS:
        variance = .5*feature['variance']+.5*max(0., mean)
        try:
            distribution, name = count_distribution(mean, variance)
        except ValueError:
            return out
        out['opportunity_count_v1'] = {**probabilities(distribution, line),
            'mean': max(0., mean), 'variance': float(distribution.var()), 'distribution': name, 'status': 'shadow_only'}
    elif stat == 'kicking_points' and all(feature.get('components', {}).get(s) for s in ('fg_made', 'xp_made')):
        components = []
        for stat in ('fg_made', 'xp_made'):
            p = feature['components'][stat]
            mu = .5*p['mean']+.5*p['recent_mean']
            try:
                dist, _ = count_distribution(mu, .5*p['variance']+.5*mu)
            except ValueError:
                return out
            if len(dist.mass) > 201:
                return out
            components.append(dist.mass)
        mass = [0.]*(3*(len(components[0])-1)+len(components[1]))
        for fg, pfg in enumerate(components[0]):
            for xp, pxp in enumerate(components[1]):
                mass[3*fg+xp] += pfg*pxp
        out['compound_kicking_v1'] = {**pack(math.fsum(p for k,p in enumerate(mass) if k>line),
            math.fsum(p for k,p in enumerate(mass) if k<line), math.fsum(p for k,p in enumerate(mass) if k==line)),
            'distribution': '3_field_goals_plus_extra_points', 'status': 'shadow_only',
            'limitation': 'FG/XP independence approximation; not validated'}
    return out
