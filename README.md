# Zuhause · Family OS

[![Tests und Container](https://github.com/tobim-dev/family-os/actions/workflows/build.yml/badge.svg)](https://github.com/tobim-dev/family-os/actions/workflows/build.yml)

**Installation auf Unraid:** [Anwendung über die XML-Vorlage installieren](UNRAID.md).
Fertiges Image: `ghcr.io/tobim-dev/family-os:latest`.

**Produktanforderungen:** [Vollständiger Anforderungskatalog](ANFORDERUNGEN.md) ·
[Abgleich: bisher dokumentiert und ergänzt](ANFORDERUNGSABGLEICH.md).
Der Katalog enthält auch die noch nicht implementierten Anforderungen aus dem Interview.


Betreuung planen, Änderungen gemeinsam bestätigen, Klärungspunkte zuordnen,
Aufgaben nachhalten und den Gemeinschaftskalender verbinden. Dazu kommen
Cookidoo-Essensplanung und eine gemeinsame Einkaufsliste.

## Lokal ausprobieren

Die vorbereitete Vorschau läuft auf diesem Mac unter **http://127.0.0.1:8765**.
Wenn sie beendet wurde, `Demo-starten.command` im Finder doppelklicken.
Das Fenster bleibt während der Nutzung geöffnet; Ctrl+C beendet den Server.
Wenn der Port bereits belegt ist, die vorhandene Vorschau verwenden.

Die Demo verwendet eine getrennte Datenbank im Arbeitsordner, ausschließlich
Beispieldaten und eine vereinfachte Personenwahl. Sie ist nur lokal erreichbar.
**Sie verbindet weder Google-Kalender noch Cookidoo und sendet keine externen Nachrichten.**
Die neuen Bereiche „Mitteilungen“ und „Verbindungen“ sind lokal ausprobierbar. Unter
„Verbindungen“ legt „Mitteilung ausprobieren“ einen persönlichen Testeintrag an.
Änderungen werden gespeichert und überleben einen Neustart. Die Personenwahl
ist ausschließlich eine Demo-Funktion; im Regelbetrieb sind Passwort und TOTP nötig.

### Durchgängiger Testablauf

1. Als Tobi öffnen und einen Bring- oder Abholtermin anklicken.
2. Eine andere Person oder ein anderes Zeitfenster vorschlagen, Grund und Frist angeben.
3. Prüfen: Der bisherige Plan bleibt gültig, „Änderung offen“ ist sichtbar.
4. Über die Profil-Schaltfläche abmelden und als Britta öffnen.
5. Den Vorschlag prüfen und bestätigen. Erst jetzt ändert sich der gültige Plan.
6. Unter Aufgaben erscheinen die notwendigen Anpassungen der Arbeitskalender.
   Jede Person kann ausschließlich ihre eigenen Aufgaben als erledigt bestätigen.

Ein neuer Monat lässt sich in der Monatsplanung vorbereiten. Standard ist eine
gleichmäßige Verteilung von fünf Wegen pro Person in einer vollständigen Woche.
Alle Zuordnungen bleiben vorläufig, bis die andere Person die konkrete Fassung
bestätigt. Die vorgegebenen Zeitblöcke entsprechen Tobis Angaben; Brittas Zeiten
sind noch gemeinsam zu prüfen. Feiertage, Krippenschließtage und Nanny-Ausnahmen
sind in diesem ersten Monatsentwurf noch nicht berücksichtigt.

Vorschläge lassen sich ablehnen oder durch ihren Ersteller zurückziehen und neu
erstellen. Jede neue Fassung braucht neue Zustimmung. Offene Klärungspunkte
haben immer die eröffnende Person als Verantwortliche. Ein Terminwechsel kann
direkt aus dem Klärungspunkt gestartet werden; mit gemeinsamer Bestätigung wird
der verknüpfte Punkt abgeschlossen. Ein reines Gesprächsergebnis verändert keine
Termine.

## Gemeinsam auf der Couch planen

In Übersicht oder Monatsplanung **Gemeinsam planen** auswählen und ausdrücklich
„Wir planen zusammen · Modus starten“ anklicken. Damit erklärt ihr, dass ihr
zusammen plant. Es ist keine zweite Anmeldung und keine einzelne Freigabe nötig.
Neue Zuordnungen werden mit **Verbindlich zuordnen** direkt gespeichert.
Der grüne Hinweis zeigt den aktiven Modus und seine Ablaufzeit.

Der Modus gilt nur für diese Anmeldung (einschließlich ihrer Browser-Tabs), endet
nach zwei Stunden oder über **Planung beenden** und wird beim Abmelden widerrufen.
Andere Anmeldungen behalten die gegenseitige Freigabe. Ein abgelaufener Modus
führt beim Speichern zu einer klaren Meldung; es erfolgt keine stille Umwandlung.
Bestehende Vorschläge werden beim Einschalten nicht automatisch übernommen.
Monatsentwürfe können nach einer gemeinsamen Prüfung gesammelt bestätigt werden,
auch wenn die angemeldete Person sie selbst erstellt hat.

Arbeitskalender-Aufgaben, Änderungsverlauf, Versionsprüfung und Google-Abgleich
bleiben aktiv. Die Historie nennt die bedienende Person und kennzeichnet direkte
Zuordnungen als gemeinsame Planung. Die andere Person erhält beim Start eine
Mitteilung über den eingeschalteten Modus.

## Was implementiert ist

- Übersicht der nächsten Betreuungstage und Monatsplanung.
- Verantwortliche Personen und persönliche Zeitfenster je Termin.
- Versionierte, gegenseitige Bestätigung, einschließlich Monats-Sammelprüfung.
- Schutz vor doppelten oder veralteten Entscheidungen; Änderungen sind atomar.
- Klärungspunkte mit Verantwortung, Frist und dokumentiertem Abschluss.
- Automatisch erzeugte, persönliche Aufgaben zur Arbeitskalenderpflege.
- Dauerhafte SQLite-Datenbank und Änderungshistorie.
- Passwort-Anmeldung plus zeitbasierter zweiter Faktor im Regelbetrieb.
- Abgelaufene Sitzungen, Code-Wiederverwendung und zu viele Login-Versuche werden abgefangen.
- Mobile Darstellung, Tastaturbedienung und lokale Demo.

## Neu in dieser Etappe

- Google-OAuth mit einmaligem, sitzungsgebundenem Rückweg und PKCE.
- Verschlüsselte lokale Google-Tokens, automatische Zugangserneuerung.
- Dauerhafte Übertragungsaufträge mit Wiederholung und getrenntem Erfolgsstatus.
- Vorläufige Google-Einträge getrennt von bereits bestätigter Planung.
- Erkennung externer Änderungen; ausdrückliche Prüfung vor erneutem Übertragen.
- Persönlicher Mitteilungseingang; Lesen erteilt keine Freigabe.
- Web-Push mit Gerätefreigabe, Wiederholung und Behandlung abgelaufener Geräte.
- Tagesübersicht um 19 Uhr, Wochenübersicht sonntags um 19 Uhr.
- Einmal täglich ab 9 Uhr Erinnerungen an fällige Aufgaben und überschrittene Fristen.

## Noch nicht implementiert

Nanny-Verwaltung, automatische Menüvorschläge, automatisch verfügbare
Offline-Einkaufslisten mit späterem Abgleich sowie Spracherkennung folgen später.
Die erste Cookidoo-Anbindung ist integriert; siehe [COOKIDOO.md](COOKIDOO.md).
Es gibt keinen Zugriff auf Arbeitskalender. Google und Push benötigen die Einrichtung
nach [VERBINDUNGEN.md](VERBINDUNGEN.md). Google-Verbindung und Terminzuordnung wurden
vom Nutzer bestätigt; vollständige Integrations- und iPhone-Push-Abnahme stehen noch aus.

Diese Etappe ist ein überprüfbarer Entwicklungsstand, noch kein vollständig
abgenommenes öffentliches Familiensystem. Brittas Rückmeldung ist zurückgestellt.

## Unraid / Docker vorbereiten

Das Paket enthält Dockerfile, Compose-Konfiguration und eine Unraid-Vorlage.
GitHub Actions testet und baut das Image einschließlich eines Container-Starttests
mit den Unraid-Datenrechten. Tobi hat die Anwendung bereits auf dem NAS eingerichtet.

Den vollständigen Ordner auf das NAS kopieren und darin arbeiten:

```sh
cp .env.example .env
```

In `.env` die tatsächliche HTTPS-Adresse eintragen, ohne abschließenden Slash:

```text
FOS_ORIGIN=https://fos.lausbuben.cloud
```

Dann Image bauen und beide Konten im lokalen NAS-Terminal einrichten:

```sh
docker compose build
docker compose run --rm family-os python manage.py setup-user --user tobi
docker compose run --rm family-os python manage.py setup-user --user britta
docker compose up -d
```

Die Einrichtung fragt das Passwort verdeckt ab und zeigt einen TOTP-Schlüssel zur
manuellen Einrichtung in einer Authenticator-App. Ein gültiger Code muss bestätigt
werden, bevor das Konto gespeichert wird. Passwörter und Einrichtungsschlüssel
nicht in Chat, Quellcode oder `.env` kopieren. Es gibt keine Standardpasswörter.
Ein verlorener zweiter Faktor kann nur über denselben lokalen Einrichtungsbefehl
zurückgesetzt werden; dabei werden bestehende Sitzungen des Kontos abgemeldet.

Der HTTP-Port ist standardmäßig nur an **127.0.0.1:8765 des NAS** gebunden.
Den vorhandenen Reverse Proxy davor konfigurieren. Wenn dieser selbst in Docker
läuft, einen gemeinsamen privaten Docker-Netzwerkzugang verwenden und intern
auf `family-os:8000` zeigen; dabei die Netzwerkdefinition passend ergänzen.
Die Domain muss mit `FOS_ORIGIN` übereinstimmen. Öffentliche Verbindungen benötigen
HTTPS, da die regulären Sitzungscookies ausschließlich über HTTPS verwendet werden.
Unraid-Verwaltung und Datenbank erhalten keine öffentlichen Ports.

Der Container läuft ohne Root-Rechte, ohne zusätzliche Linux-Capabilities und
mit schreibgeschütztem Anwendungsverzeichnis. Die Daten liegen im benannten
Volume `family-data` unter `/data`. Dieses Volume beim Aktualisieren erhalten.
`docker compose down -v` würde die Daten löschen und ist kein Update-Befehl.

Für eine manuelle Unraid-Containerdefinition: Port 8000 intern, FOS_ORIGIN setzen,
FOS_DEMO=0, FOS_DB=/data/family.sqlite und ein dauerhaftes `/data`-Volume verwenden.
Bei einem Host-Verzeichnis muss Benutzer-ID 10001 dort schreiben können.

## Daten und Wiederherstellung

Die Datenbank enthält private Planungsdaten, Passwort-Hashes und TOTP-Geheimnisse.
Sie ist nicht durch die Anwendung verschlüsselt. NAS-Zugriffsrechte und eine
geschützte Sicherung sind deshalb Bestandteil des Betriebs. Es werden keine
externen Schriften, Analyse-Dienste oder KI-Dienste geladen.

Eine konsistente manuelle Sicherung ist möglich:

```sh
docker compose exec family-os python manage.py backup --output /data/backups/family-2026-09-24.sqlite
```

Jeder Sicherung einen neuen Dateinamen geben. Zusätzlich zur Datenbank wird, sofern
vorhanden, ein gleichnamiger Ordner mit Endung `.keys` angelegt: Verschlüsselungsschlüssel,
Push-Schlüssel und Google-Zugangsdatei. **Datenbank und Schlüsselordner gemeinsam** auf ein
separates geschütztes Ziel kopieren. Ohne `integration.key` sind gesicherte Google-Tokens
nicht lesbar. Dasselbe gilt für Cookidoo-Tokens. Die Anwendung erzeugt bei vorhandenen Tokens keinen Ersatzschlüssel. Der Befehl verwendet die SQLite-Backup-API,
damit auch bei laufender Anwendung ein konsistenter Stand entsteht. Es ist noch
kein automatischer Sicherungsplan eingerichtet.

Wiederherstellung: Anwendung stoppen, aktuelle Datenbank gesondert sichern, die
gewählte Sicherung als `/data/family.sqlite` und Dateien aus `.keys` unter ihren
Originalnamen nach `/data` zurücklegen. Dateirechte für UID 10001
prüfen und wieder starten. Google-Kalender-ID und öffentliche Adresse aus der bisherigen
Konfiguration beibehalten; die Kalender-ID wird gegen stillen Wechsel geschützt. Sicherungen enthalten auch Sitzungen. Nach einer
Wiederherstellung alle Sitzungen aus der Tabelle `sessions` löschen oder beide
Konten über `setup-user` neu einrichten, bevor der öffentliche Zugriff wieder
aktiviert wird. Den Ablauf zuerst in einer getrennten Testinstallation prüfen.

Die Datenbank hat eine Schema-Version (`PRAGMA user_version`). Neue Versionen passen sie
beim Start an und legen vorher eine Kopie unter `backups/` im Datenverzeichnis ab.
Details zu Rollback und Grenzen stehen in [UNRAID.md](UNRAID.md).

## Lokale Entwicklung und Prüfungen

Python 3.12 verwenden. Abhängigkeiten sind auf konkrete Versionen festgelegt.

```sh
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests -v
FOS_DEMO=1 FOS_DB=data/demo.sqlite .venv/bin/uvicorn app:create_app --factory --host 127.0.0.1 --port 8765
```

Die automatisierten Tests verwenden ausschließlich temporäre Datenbanken. Sie
prüfen unter anderem: gegenseitige Freigabe, Erhalt der bisherigen Zuordnung,
veraltete und parallele Entscheidungen, vollständigen Rollback einer fehlerhaften
Sammelbestätigung, persönliche Aufgaben, MFA, Code-Wiederverwendung und Limits.

Die Browserprüfung umfasst Vorschlag als Tobi → Bestätigung als Britta → richtige
Zuordnung und Folgeaufgabe → ausdrücklicher Aufgabenabschluss. Mobile und
Desktop-Ansichten werden separat geprüft. Echte iPhone-Push- und NAS-Tests folgen
erst mit den entsprechenden Integrationen.

## Betriebsgrenzen dieser Etappe

Genau einen Anwendungsprozess und einen Container pro Datenbank betreiben.
Kalenderabgleich läuft etwa alle 20 Sekunden, externe Änderungen werden bei
bestehenden Einträgen ungefähr alle 15 Minuten geprüft. Push hat einen eigenen
Hintergrundlauf alle 5 Sekunden, damit langsame Google-Antworten ihn nicht aufhalten.
Zusammenfassungen werden bei einem Neustart zwischen 19 und 21 Uhr nachgeholt;
später werden keine alten Abendübersichten nachgesendet. Push-Aufträge älter als
24 Stunden oder bereits gelesene Mitteilungen werden nicht weiter versucht.

Die Anwendung umgeht keine Fokus-/Nicht-stören-Einstellung des iPhones.
„Vom Push-Dienst angenommen“ bedeutet keine garantierte Anzeige oder Lesebestätigung.
Eine zeitkritische Betreuungsklärung bleibt bis zur ausdrücklichen Zustimmung offen.

Die Anwendung importiert keine fremden Google-Termine. Änderungen an eigenen
Einträgen werden als Konflikt gezeigt, nicht automatisch in Familienentscheidungen
umgewandelt. Ein Wechsel des Zielkalenders erfordert eine kontrollierte Migration.
Eine manuell speicherbare Einkaufskopie ist vorhanden. Automatischer Offline-Abgleich
und ein automatischer Sicherungsplan folgen später.
