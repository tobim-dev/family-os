"""Start the exact image without external services and test durable Unraid data.

Runs in GitHub Actions with its Docker daemon; creates/removes only uniquely
named test containers and volumes. No real family data or credentials are used.
"""
import json
import subprocess
import sys
import time
import uuid


def docker(*args, check=True):
    return subprocess.run(['docker', *args], check=check, text=True, capture_output=True)


def check_image(image, unraid):
    name = 'fos-ci-' + uuid.uuid4().hex[:12]
    volume = name + '-data'
    uid = '99' if unraid else '10001'
    try:
        docker('volume', 'create', volume)
        args = ['run', '--detach', '--name', name, '--read-only', '--tmpfs', '/tmp:rw,noexec,nosuid,size=64m',
                '--cap-drop=ALL', '--security-opt=no-new-privileges:true',
                '--mount', f'type=volume,source={volume},target=/data',
                '--env', 'FOS_ORIGIN=https://family.test', '--env', 'FOS_DEMO=0',
                # No 1.6 GB model download in CI; the libraries are checked below.
                '--env', 'FOS_SPEECH_MODEL=off']
        if unraid:
            args += ['--user', '0:0', '--env', 'FOS_UID=99', '--env', 'FOS_GID=100']
            for cap in ('CHOWN', 'FOWNER', 'SETUID', 'SETGID'):
                args += ['--cap-add=' + cap]
        docker(*args, image)
        for _ in range(40):
            probe = docker('exec', '--user', uid, name, 'python', '-c',
                           'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8000/health",timeout=2)', check=False)
            if probe.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError('Container did not become ready.')
        code = '''
import json, os, pathlib, urllib.request, urllib.error
p=pathlib.Path('/data')
assert (p/'family.sqlite').exists()
assert (p/'integration.key').exists()
assert (p/'push-private.pem').exists()
uid_line=next(line for line in pathlib.Path('/proc/1/status').read_text().splitlines() if line.startswith('Uid:'))
assert uid_line.split()[1:]==[str(os.getuid())]*4, uid_line
try:
 urllib.request.urlopen('http://127.0.0.1:8000/api/state?month=2027-03')
 raise AssertionError('Anonymous access allowed')
except urllib.error.HTTPError as e:
 assert e.code==401
(p/'persistence-check').write_text('preserved')
print(json.dumps({'uid':os.getuid(),'mfa_required':True,'data_writable':True}))
'''
        print(docker('exec', '--user', uid, name, 'python', '-c', code).stdout.strip())
        # Speech libraries import and the bundled VAD model runs on the read-only image.
        docker('exec', '--user', uid, name, 'python', '-c',
               'import ctranslate2, av; from faster_whisper.vad import get_vad_model; get_vad_model()')
        docker('restart', name)
        docker('exec', '--user', uid, name, 'python', '-c', "from pathlib import Path; assert Path('/data/persistence-check').read_text() == 'preserved'")
        print('Container smoke test passed:', 'Unraid initialization' if unraid else 'unprivileged default')
    except Exception:
        print(docker('logs', name, check=False).stdout)
        print(docker('logs', name, check=False).stderr, file=sys.stderr)
        raise
    finally:
        docker('rm', '--force', name, check=False)
        docker('volume', 'rm', volume, check=False)


if __name__ == '__main__':
    check_image(sys.argv[1], False)
    check_image(sys.argv[1], True)
