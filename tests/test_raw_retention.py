from datetime import datetime,timezone,timedelta
from types import SimpleNamespace as NS
from src.services.raw_retention import eligible
from src.services.raw_retention import compress_verified
import gzip
import pytest


def test_retention_requires_durable_final_success_and_preserves_corrections():
    now=datetime.now(timezone.utc);old=now-timedelta(days=120);cutoff=now-timedelta(days=90)
    state=NS(status='succeeded',last_attempt_at=now);game=NS(status='final',game_time=old)
    payload={'observed_at':old.isoformat(),'payload_hash':'h'}
    assert eligible(payload,state,game,set(),cutoff,True)
    assert not eligible(payload,state,game,{'h'},cutoff,True)
    assert not eligible(payload,state,game,set(),cutoff,False)
    state.status='confirming'
    assert not eligible(payload,state,game,set(),cutoff,True)


def test_lossless_compression_and_path_guards(tmp_path):
    original=b'{"evidence":"'+b'x'*4096+b'"}'
    path=tmp_path/'old.json';path.write_bytes(original)
    result=compress_verified(path,tmp_path)
    assert result['status']=='compressed' and result['bytes_saved']>0
    assert not path.exists()
    assert gzip.open(tmp_path/'old.json.gz','rb').read()==original
    nested=tmp_path/'nested';nested.mkdir()
    with pytest.raises(ValueError):compress_verified(nested/'other.json',tmp_path)
    link=tmp_path/'link.json';link.symlink_to(tmp_path/'old.json.gz')
    with pytest.raises(ValueError):compress_verified(link,tmp_path)
