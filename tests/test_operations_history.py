from src.services.operations_history import alerts,status


def test_alerts_distinguish_process_changes_from_proven_oom():
    warnings=alerts({'process_id':'new','routes':{'/slow':{'p95_ms':2500,'server_errors':1}}},
                    {'stale':True},{'process_id':'old'})
    assert 'api_process_changed_restart_or_deployment' in warnings
    assert 'slow_route:/slow' in warnings and 'server_errors:/slow' in warnings
    assert 'production_capture_overdue_or_unknown' in warnings
    assert not any('oom' in w for w in warnings)


async def test_missing_history_is_not_healthy(db):
    assert (await status(db))['status']=='awaiting_monitor'
