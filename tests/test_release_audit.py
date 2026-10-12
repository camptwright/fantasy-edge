from scripts.release_audit import source_files, differences, dependency_drift


def test_preview_release_audit_never_targets_production():
    from scripts.release_audit import targets
    assert targets(True) == (['-f', 'docker-compose.workspace.yml'], ('workspace-api', 'workspace-observer'))
    assert targets(False) == ([], ('api', 'worker', 'evaluation', 'beat'))


def test_remote_probe_is_valid_standalone_python():
    from scripts.release_audit import remote_probe
    probe=remote_probe()
    compile(probe, '<remote-release-audit>', 'exec')
    assert '\n    sys.exit(main())' not in probe


def test_source_inventory_ignores_secrets_caches_and_symlinks(tmp_path):
    (tmp_path/'src').mkdir()
    (tmp_path/'src'/'app.py').write_text('pass')
    (tmp_path/'src'/'.env').write_text('secret')
    (tmp_path/'src'/'__pycache__').mkdir()
    (tmp_path/'src'/'__pycache__'/'hidden.py').write_text('ignored')
    (tmp_path/'src'/'linked.py').symlink_to(tmp_path/'src'/'app.py')
    (tmp_path/'.env').write_text('secret')
    assert list(source_files(tmp_path)) == ['src/app.py']


def test_drift_detects_missing_changed_and_unexpected_files():
    assert differences({'a':'old','b':'same','c':'missing'}, {'a':'new','b':'same','d':'extra'}) == {
        'missing':['c'],'changed':['a'],'unexpected':['d']}


def test_dependency_lock_checks_missing_versions_and_normalizes_names(tmp_path):
    (tmp_path/'requirements-runtime.lock').write_text('# runtime\ncurl_cffi==1.0\nSQLAlchemy==2.0\nhttpx==0.28\n')
    assert dependency_drift(tmp_path,{'curl-cffi':'1.0','sqlalchemy':'1.9'}) == [
        {'package':'SQLAlchemy','expected':'2.0','installed':'1.9'},
        {'package':'httpx','expected':'0.28','installed':None}]
