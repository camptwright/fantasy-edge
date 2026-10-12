"""Read-only frontend source/build verification for Compose and the Mac preview."""
import argparse
import json
from pathlib import Path
import subprocess
import sys


def differences(expected, actual):
    return {kind: sorted(keys) for kind, keys in {
        'missing': expected.keys()-actual.keys(),
        'unexpected': actual.keys()-expected.keys(),
        'changed': {k for k in expected.keys() & actual.keys() if expected[k]!=actual[k]},
    }.items()}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context', default='colima')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    command=['docker','--context',args.context]
    report={'scope':'Source fingerprints and standalone Next artifacts; excludes node_modules, runtime caches, OS, secrets and model qualification. Not a signed attestation.', 'services':{}}
    try:
        local=subprocess.run(['node','scripts/release-provenance.cjs','source'],cwd=root/'dashboard',
                             capture_output=True,text=True,check=True,timeout=30)
        expected=json.loads(local.stdout)['files']
    except (subprocess.SubprocessError, OSError, ValueError, KeyError):
        print(json.dumps({'status':'local_inventory_unavailable'}));return 1
    for name, target in [('dashboard',['compose','exec','-T','dashboard']),
                         ('local-preview',['exec','fantasy-edge-grading-preview'])]:
        try:
            result=subprocess.run(command+target+['node','release-provenance.cjs','verify'],
                cwd=root,capture_output=True,text=True,timeout=30)
            actual=json.loads(result.stdout)
            drift=differences(expected, actual['source'])
            report['services'][name]={
                'status':'matched' if result.returncode==0 and actual['status']=='matched' and not any(drift.values()) else 'drift',
                'source_files_checked':len(expected),'source':drift,
                'build_id':actual['build_id'],'artifacts_checked':actual['artifacts_checked'],
                'artifacts':actual['artifacts']}
        except (subprocess.SubprocessError, OSError, ValueError, KeyError):
            report['services'][name]={'status':'unavailable_or_invalid_manifest'}
    print(json.dumps(report,indent=2))
    return int(any(v['status']!='matched' for v in report['services'].values()))


if __name__=='__main__':
    sys.exit(main())
