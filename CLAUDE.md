# Family OS – Arbeitshinweise

Selbst gehostete Familienorganisation (Tobi und Britta, Tochter Lina). Läuft als
Docker-Container auf Tobis Unraid-NAS hinter seinem Reverse Proxy
(`fos.lausbuben.cloud`). Sprache für Oberfläche, Doku und Commit-Inhalte: Deutsch;
Code-Bezeichner und Commit-Betreffzeilen dürfen Englisch sein.

## Produktquelle

- `ANFORDERUNGEN.md` ist der verbindliche Soll-Katalog mit stabilen IDs (Z-, B-, N-, E-,
  G-, K-, A-, D-, Q-, V-, T-, O-). Bei jeder fachlichen Änderung den Status der
  betroffenen IDs aktualisieren. Neue Wünsche bekommen neue IDs, bestehende IDs werden
  nie umnummeriert oder gelöscht (siehe Abschnitt 11 dort).
- Offene Punkte (O-xx) nicht stillschweigend entscheiden. Unklare fachliche Regeln
  (z. B. Abrechnung, Rundung) mit Tobi klären statt erfinden.
- `PRUEFSTAND.md` hält fest, was automatisch bzw. manuell geprüft ist. Testzahl und
  neue Prüfungen dort nachziehen.

## Architektur

- `app.py`: FastAPI-App-Factory `create_app()`, Anmeldung (Passwort + TOTP), Betreuung,
  Vorschläge/Freigaben, Klärungspunkte, Aufgaben, gemeinsamer Planungsmodus.
- `integrations.py`: Google-Kalender, Mitteilungen, Web-Push, Hintergrund-Threads.
- `meals.py`: Cookidoo (inoffizielle `cookidoo-api`), Einkaufsliste.
- `meal_suggestions.py`: Wochenvorschläge; harte Regeln lokal, Claude API optional mit minimalen anonymen Daten.
- `recipe_images.py`: Rezeptbilder über den NAS (Host-Allowlist, Cache); Browser lädt nie extern.
- `nanny.py`: Nanny-Termine, WhatsApp-Anfragen (nur vorbereiteter Text), Stunden, Monatsabrechnung.
- `migrations.py`: versioniertes SQLite-Schema (`PRAGMA user_version`).
- `manage.py`: Konten einrichten, Backups. `docker-entrypoint.py`: Unraid-Rechte.
- `static/`: Vanilla-JS-PWA ohne Build-Schritt (`app.js` Kern, `meals.js`, `nanny.js` je Bereich), strikte CSP (keine Inline-Skripte/-Styles,
  keine externen Ressourcen).

## Datenbank-Regeln

- Schemaänderungen **nur** als neuer Eintrag in `migrations.MIGRATIONS` (nächste
  Versionsnummer). Veröffentlichte Migrationen und `BASELINE` nie ändern.
- Die Produktiv-DB auf dem NAS enthält echte Daten: Migrationen müssen verlustfrei sein
  und bekommen einen Test in `tests/test_migrations.py` (Upgrade mit Bestandsdaten).
- Zugriffe über `app.state.db()` (Transaktion mit `BEGIN IMMEDIATE`, Fremdschlüssel an).
- Genau ein Prozess pro Datenbank.

## Qualitätsmaßstab

- Zuverlässigkeit vor Funktionsumfang (Q-01): Fehlschläge nie als Erfolg darstellen,
  bestätigter Plan ändert sich nur durch ausdrückliche Zustimmung (B-11).
- Jede Aufgabe hat eine verantwortliche Person (A-03).
- Keine Arbeitskalender-Anbindung (B-02). Keine CAPTCHA-Umgehung (G-07).
- Neuen Code lesbar schreiben (normale Zeilenlängen). Bestehenden, sehr dichten Code
  beim Anfassen schrittweise entzerren, nicht als Großumbau.

## Prüfen

```sh
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests -v
node --check static/app.js static/meals.js static/sw.js && node --test tests/*.cjs
.venv/bin/python scripts/check_unraid.py
FOS_DEMO=1 FOS_DB=data/demo.sqlite .venv/bin/uvicorn app:create_app --factory --host 127.0.0.1 --port 8765
```

Neue Python-Dateien, die zur Laufzeit gebraucht werden, im `Dockerfile` (`COPY`) ergänzen.

## Git und Auslieferung

- Direkte Pushes auf `main` sind erlaubt (T-08). Jeder Push auf `main` baut und
  veröffentlicht `ghcr.io/tobim-dev/family-os:latest`. Vor dem Push müssen alle Tests
  lokal grün sein. Nach dem Push den GitHub-Actions-Lauf prüfen.
- Tobi installiert Updates auf Unraid bewusst selbst.

## Secrets

Niemals committen: `.env`, `*.key`, `*.pem`, `google-client*.json`, `client_secret*.json`,
SQLite-Dateien, `*.keys/`, Passwörter, TOTP-Schlüssel, Cookidoo-Zugangsdaten, Tokens.
Keine echten personenbezogenen Daten (Adressen, Geburtsdaten) in Code, Tests oder Doku.
