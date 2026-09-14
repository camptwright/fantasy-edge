"""Replace the Mac preview with the built dashboard, retaining rollback.

Run after `docker compose build dashboard && docker compose up -d dashboard`.
Inspects only the known local preview; never prints its environment secrets.
"""
import json
import subprocess
from datetime import datetime, timezone


def docker(*args):
    result = subprocess.run(['docker', *args], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f'Docker {args[0]} failed (output withheld)')
    return result.stdout


def main():
    name = 'fantasy-edge-grading-preview'
    old = json.loads(docker('inspect', name))[0]
    assert not old['Mounts'], 'Unexpected preview mounts; stop for review'
    assert old['HostConfig']['PortBindings'] == {
        '3000/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '13000'}]}
    assert list(old['NetworkSettings']['Networks']) == ['fantasy-edge_fantasy']
    docker('image', 'inspect', 'fantasy-edge-dashboard')
    api = json.loads(docker('inspect', 'fantasy-edge-api-1'))[0]
    api_token = next((v for v in api['Config']['Env'] if v.startswith('FANTASY_API_TOKEN=') and v.split('=', 1)[1]), None)
    assert api_token, 'API token missing; stop before replacing preview'
    backup = name + '-before-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
    docker('stop', name)
    try:
        docker('rename', name, backup)
    except Exception:
        docker('start', name)
        raise
    created = False
    try:
        args = ['create', '--name', name, '--network', 'fantasy-edge_fantasy',
                '-p', '127.0.0.1:13000:3000', '--memory', '512m',
                '--restart', 'unless-stopped']
        for value in old['Config']['Env']:
            if not value.startswith(('HOSTNAME=', 'FANTASY_LOCAL_ONLY=', 'FANTASY_API_TOKEN=')):
                args += ['-e', value]
        args += ['-e', 'HOSTNAME=0.0.0.0']
        args += ['-e', 'FANTASY_LOCAL_ONLY=true']
        args += ['-e', api_token]
        args.append('fantasy-edge-dashboard')
        docker(*args)
        created = True
        docker('start', name)
        # Retry readiness inside the container; no browser session required.
        docker('exec', name, 'node', '-e',
               "(async()=>{for(let i=0;i<30;i++){try{let r=await fetch('http://127.0.0.1:3000');"
               "if(r.ok)process.exit(0)}catch{}await new Promise(r=>setTimeout(r,1000))}process.exit(1)})()")
    except Exception:
        if created:
            docker('stop', name)
            docker('rename', name, backup + '-failed-replacement')
        docker('rename', backup, name)
        docker('start', name)
        raise
    print(f'Preview updated; stopped rollback container retained: {backup}')


if __name__ == '__main__':
    main()
