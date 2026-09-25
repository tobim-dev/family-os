"""Prepare an Unraid bind mount, then permanently drop root before starting.

Regular Docker use runs as UID 10001 already. Unraid explicitly opts into the
short root initialization, with only CHOWN/FOWNER/SETUID/SETGID capabilities.
"""
import os
from pathlib import Path
import sys


def main():
    if len(sys.argv) < 2:
        raise SystemExit('Missing container command.')
    if os.getuid() == 0:
        uid = int(os.environ.get('FOS_UID', '99'))
        gid = int(os.environ.get('FOS_GID', '100'))
        if uid <= 0 or gid <= 0:
            raise SystemExit('FOS_UID and FOS_GID must be non-root IDs.')
        data = Path('/data')
        if data.is_symlink():
            raise SystemExit('/data must not be a symlink.')
        data.mkdir(exist_ok=True)
        os.chown(data, uid, gid)
        os.chmod(data, 0o700)
        # Never recursively change ownership of an arbitrary host mount.
        for name in ('family.sqlite', 'family.sqlite-wal', 'family.sqlite-shm',
                     'family.sqlite-journal', 'integration.key', 'push-private.pem', 'google-client.json'):
            path = data / name
            if path.is_symlink():
                raise SystemExit('Symlinks are not supported for Family OS data files.')
            if path.is_file():
                os.chown(path, uid, gid)
                os.chmod(path, 0o600)
        os.setgroups([])
        os.setgid(gid)
        os.setuid(uid)
    os.umask(0o077)
    os.execvp(sys.argv[1], sys.argv[1:])


if __name__ == '__main__':
    main()
