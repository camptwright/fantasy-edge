"""Archive reviewed-reference rule pages; observation never grants verification."""
import hashlib
import json
from datetime import datetime,timezone,timedelta
from pathlib import Path
import httpx
from config.settings import get_settings
from src.services.roster_stat_prospective import publish

REGISTRY=Path(__file__).resolve().parents[2]/'config/football_settlement_rules.json'


def directory():return Path(get_settings().raw_archive_dir)/'settlement-source-evidence'


def latest():
    paths=sorted((directory()/'reports').glob('*.json'),reverse=True)
    if not paths:return {'status':'not_observed','serving_enabled':False}
    try:return json.loads(paths[0].read_text())
    except (OSError,ValueError):return {'status':'invalid_report','serving_enabled':False}


async def collect():
    now=datetime.now(timezone.utc);prior=latest()
    if prior.get('observed_at') and timedelta(0)<=now-datetime.fromisoformat(prior['observed_at'])<timedelta(days=1):return prior
    rules=json.loads(REGISTRY.read_text())['rules'];rows=[]
    async with httpx.AsyncClient(timeout=15,follow_redirects=True) as client:
        for source in sorted({r['source'] for r in rules}):
            row={'source':source,'contract_status':'unverified','observed_at':now.isoformat()}
            try:
                response=await client.get(source);response.raise_for_status()
                # Retain exact response bytes as hex so hash can be checked without encoding ambiguity.
                digest=hashlib.sha256(response.content).hexdigest()
                publish(directory()/'sources'/(digest+'.json'),{'source':source,'bytes_hex':response.content.hex(),
                    'sha256':digest,'observed_at':now.isoformat(),'final_url':str(response.url)})
                row.update(status='source_observed_requires_review',sha256=digest,bytes=len(response.content))
            except httpx.HTTPError:row['status']='source_unavailable'
            rows.append(row)
    report={'status':'evidence_only','observed_at':now.isoformat(),'rows':rows,'serving_enabled':False,
        'blockers':['quote_product_and_jurisdiction_not_verified','effective_rules_and_market_clauses_require_review'],
        'note':'A successful HTTP response is not a verified rules contract; login/challenge pages also require review.'}
    publish(directory()/'reports'/(now.strftime('%Y%m%dT%H%M%S.%f')+'.json'),report)
    return report
