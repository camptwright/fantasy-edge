"""Small read-only API artifact; never load full history in request handling."""
import json
from pathlib import Path
from config.settings import get_settings


def settlement_lookup(book, product, sport):
    """Never merge standard sportsbook and Prop Builder participation policies."""
    root = Path(__file__).resolve().parents[2]
    rules = json.loads((root/'config/football_settlement_rules.json').read_text())
    matches = [r for r in rules['rules'] if r['book'] == book and r['product'] == product
               and sport in r['sports']]
    if len(matches) != 1:
        return {'ready': False, 'blockers': ['unknown_or_ambiguous_product_rules']}
    return {'ready': False, 'rule': matches[0], 'blockers': matches[0]['unresolved']}


def status():
    root = Path(__file__).resolve().parents[2]
    rules = json.loads((root/'config/football_settlement_rules.json').read_text())
    directory = Path(get_settings().raw_archive_dir)/'period-research-status'
    files = sorted(directory.glob('*.json'), reverse=True)
    result = {'status': 'not_built', 'seasons': [], 'metrics': [], 'serving_enabled': False}
    if files:
        try:
            if files[0].stat().st_size > 1_000_000:
                raise ValueError('oversized status artifact')
            loaded = json.loads(files[0].read_text())
            if loaded.get('schema_version') != 1:
                raise ValueError('unsupported status schema')
            result = {k: v for k, v in loaded.items() if not k.endswith('_archive')}
        except (ValueError, OSError):
            result['status'] = 'invalid_artifact'
    college = sorted((Path(get_settings().raw_archive_dir)/'ncaaf-period-history-status').glob('*.json'), reverse=True)
    if college:
        try:
            if college[0].stat().st_size > 1_000_000:
                raise ValueError('oversized college report')
            report = json.loads(college[0].read_text())
            result['ncaaf_history'] = {'games': report['games'],
                'timeline_passes': sum(not r.get('timeline_blockers') and 'error_type' not in r for r in report['reports']),
                'fully_validated_games': sum(not r.get('timeline_blockers') and not r.get('unresolved_plays')
                    and not r.get('mismatched_or_missing') and 'error_type' not in r for r in report['reports'])}
        except (ValueError, OSError, KeyError, TypeError):
            result['ncaaf_history'] = {'status': 'invalid_artifact'}
    # Research artifacts cannot authorize a serving promotion.
    return {**result, 'settlement_rules': rules, 'serving_enabled': False}
