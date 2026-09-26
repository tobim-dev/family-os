"""Local account provisioning and consistent SQLite backups."""
import argparse
from getpass import getpass
import os
from pathlib import Path
import sqlite3
import shutil
import pyotp
from app import PEOPLE, password_hash, now
from migrations import migrate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['setup-user', 'backup'])
    parser.add_argument('--user', choices=PEOPLE)
    parser.add_argument('--output')
    args = parser.parse_args()
    path = Path(os.getenv('FOS_DB', 'data/family.sqlite'))
    path.parent.mkdir(parents=True, exist_ok=True)
    if args.command == 'backup':
        if not path.exists() or not args.output:
            parser.error('Existing FOS_DB and --output required.')
        output = Path(args.output)
        if output.exists():
            parser.error('Backup destination already exists.')
        output.parent.mkdir(parents=True, exist_ok=True)
        sidecars = output.with_name(output.name + '.keys')
        if sidecars.exists():
            parser.error('Backup key directory already exists.')
        files = [path.parent / name for name in ('integration.key', 'push-private.pem')]
        client_file = os.getenv('FOS_GOOGLE_CLIENT_FILE')
        if client_file:
            files.append(Path(client_file))
        existing = [file for file in files if file.exists()]
        if existing:
            sidecars.mkdir(mode=0o700)
            for file in existing:
                destination = sidecars / ('google-client.json' if client_file and file == Path(client_file) else file.name)
                shutil.copyfile(file, destination)
                os.chmod(destination, 0o600)
        with sqlite3.connect(path) as source, sqlite3.connect(output) as target:
            source.backup(target)
        os.chmod(output, 0o600)
        print('Sicherung erstellt:', output)
        if existing:
            print('Zugehörige Schlüssel ebenfalls sichern:', sidecars)
        return
    if not args.user:
        parser.error('--user required.')
    migrate(path)
    with sqlite3.connect(path) as conn:
        row = conn.execute("SELECT value FROM metadata WHERE key='mode'").fetchone()
        if row and row[0] != 'production':
            raise SystemExit('Keine echten Konten in der Demo-Datenbank anlegen.')
        exists = conn.execute('SELECT id FROM users WHERE id=?', (args.user,)).fetchone()
        if exists and input('Bestehendes Konto zurücksetzen und alle Sitzungen abmelden? Tippe JA: ') != 'JA':
            raise SystemExit('Abgebrochen.')
        password = getpass('Neues Passwort (mindestens 12 Zeichen): ')
        if not 12 <= len(password) <= 128 or password != getpass('Passwort wiederholen: '):
            raise SystemExit('Passwörter stimmen nicht überein oder Länge ungültig.')
        secret = pyotp.random_base32()
        print('Authenticator-App: neues Konto manuell hinzufügen (zeitbasiert / TOTP).')
        print('Kontoname: Family OS / ' + PEOPLE[args.user])
        print('Geheimer Einrichtungsschlüssel (nicht teilen): ' + secret)
        code = getpass('Aktuellen sechsstelligen Code zur Einrichtung bestätigen: ')
        if not pyotp.TOTP(secret).verify(code, valid_window=1):
            raise SystemExit('Code ungültig. Konto wurde nicht verändert.')
        conn.execute("INSERT OR IGNORE INTO metadata VALUES('mode','production')")
        conn.execute('INSERT INTO users(id,password,totp) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET password=excluded.password,totp=excluded.totp,last_step=-1', (args.user,password_hash(password),secret))
        conn.execute('DELETE FROM sessions WHERE user_id=?', (args.user,))
        conn.execute('INSERT INTO audit(actor,action,details,created) VALUES(?,?,?,?)', ('admin','Konto eingerichtet',args.user,now()))
    os.chmod(path, 0o600)
    print('Konto eingerichtet. Einrichtungsschlüssel aus sichtbarem Terminalverlauf entfernen.')


if __name__ == '__main__':
    main()
