from datetime import datetime,timezone,timedelta
from types import SimpleNamespace as NS
from uuid import uuid4
from src.services.prop_price_comparisons import compare


def rows():
    g=NS(id=uuid4(),sport='nfl');p=uuid4();now=datetime.now(timezone.utc)
    return [(NS(id=uuid4(),game_id=g.id,player_id=p,stat_type='passing_yards',line=250.5,
        source=source,over_price_american=over,under_price_american=-110,observed_at=now),g)
        for source,over in [('parlay_pinnacle',-110),('parlay_draftkings',110)]]


def test_exact_sharp_soft_and_never_actionable():
    out=compare(rows())
    assert len(out)==2 and out[0]['fair_probability']==.5
    assert abs(out[0]['ev_percent']-5)<1e-8 and not out[0]['actionable']


def test_contract_and_timing_isolation():
    for field,value in [('game_id',uuid4()),('player_id',uuid4()),('stat_type','rushing_yards'),('line',251.5)]:
        r=rows();setattr(r[1][0],field,value);assert not compare(r)
    r=rows();r[0][0].observed_at-=timedelta(minutes=6);assert not compare(r)
    r=rows()
    for q,g in r:q.line=250
    assert not compare(r)


def test_one_vote_per_brand_and_two_sided_reference():
    r=rows();r.append((NS(**{**vars(r[0][0]),'source':'theodds_pinnacle','id':uuid4()}),r[0][1]))
    assert compare(r)[0]['reference_books']==['pinnacle']
    r=rows();r[0][0].under_price_american=None;assert not compare(r)
