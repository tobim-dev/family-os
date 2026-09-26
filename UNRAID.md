# Installation als Unraid-Anwendung

Das Image wird von GitHub Actions getestet, gebaut und unter
`ghcr.io/tobim-dev/family-os:latest` veröffentlicht. Zielplattform: **linux/amd64**,
passend zum Intel-NAS. `latest` folgt erfolgreichen Builds von `main`. Jeder Build
hat zusätzlich einen unveränderlich benannten `sha-<vollständige Commit-ID>`-Tag;
Versions-Tags wie `v0.2.0` erzeugen gleichnamige Image-Tags.

## Vorlage installieren

Die XML ist eine eigene Docker-Vorlage. Sie erscheint nach dem Import unter
**Docker → Add Container**, nicht automatisch im öffentlichen Community-Apps-Katalog.
Eine Veröffentlichung im öffentlichen Katalog ist nicht Bestandteil dieser Einrichtung.

Im Unraid-Terminal die Vorlage herunterladen:

```sh
mkdir -p /boot/config/plugins/dockerMan/templates-user
curl --fail --location https://raw.githubusercontent.com/tobim-dev/family-os/main/unraid/family-os.xml \
  --output /boot/config/plugins/dockerMan/templates-user/my-family-os.xml
```

Dann **Docker → Add Container → Vorlage family-os** auswählen und installieren.

- Daten: `/mnt/user/appdata/family-os` → `/data` im Container.
- Port: standardmäßig `8765` auf dem NAS → `8000` im Container.
- HTTPS-Adresse: `https://fos.lausbuben.cloud`, jederzeit konfigurierbar.
- Google-Kalender-ID zunächst leer lassen, bis Google eingerichtet wird.
- Demo-Modus bleibt **0**. Die lokale Demo gehört nicht auf den öffentlichen Server.

Der HTTP-Port ist in dieser Unraid-Vorlage im LAN erreichbar und ausschließlich
als Ziel für deinen Reverse Proxy gedacht. Keine direkte Routerfreigabe dafür
anlegen. Der WebUI-Link öffnet die HTTPS-Adresse; bei anderer Domain auch diesen
Link in den erweiterten Vorlageneinstellungen anpassen.

Die Vorlage initialisiert nur den zugehörigen Datenordner kurz als root und
startet die Anwendung anschließend dauerhaft als **UID 99 / GID 100**
(Unraid nobody/users). Es gibt keinen privilegierten Containerbetrieb. Die nötigen
Initialisierungsrechte sind einzeln begrenzt. Bestehende App-Dateien werden beim
Start der konfigurierten UID zugeordnet; andere Unterordner werden nicht rekursiv
verändert. Für diesen Container einen eigenen Datenordner verwenden.

## Konten und Reverse Proxy

Nach dem Start im Unraid-Terminal die beiden Konten einrichten:

```sh
docker exec -it --user 99:100 family-os python manage.py setup-user --user tobi
docker exec -it --user 99:100 family-os python manage.py setup-user --user britta
```

Jeweils ein eigenes Passwort setzen und den ausgegebenen Schlüssel in einer
Authenticator-App aufnehmen. Die Einrichtung prüft einen aktuellen Code.
Es gibt keine Standardpasswörter. Bei angepasster UID/GID die Befehle entsprechend ändern.

Den vorhandenen Reverse Proxy auf `http://NAS-IP:8765` konfigurieren, HTTPS für
die Domain bereitstellen und anschließend den WebUI-Link öffnen. Für die Anwendung
muss die Adresse exakt mit `FOS_ORIGIN` übereinstimmen. Google- und iPhone-Einrichtung:
[VERBINDUNGEN.md](VERBINDUNGEN.md). Bei manueller Dateiablage gehören die Dateien im
Host-Appdata-Ordner UID 99 / GID 100, nicht UID 10001 aus dem Compose-Beispiel.

## Image-Zugriff

GitHub legt neue GHCR-Pakete zunächst privat an, unabhängig von der Sichtbarkeit
des Git-Repositories. Für Installation ohne Registry-Anmeldung muss das Paket
`family-os` unter GitHub → Packages → Package settings öffentlich sein.
Falls das Paket privat bleiben soll, Unraid vorher mit einem separaten GitHub-Token
mit `read:packages` bei `ghcr.io` anmelden. Tokens niemals in die XML oder ins
Repository eintragen. Die Vorlage enthält keine Zugangsdaten.

## Updates und Rückkehr zum vorherigen Stand

Unraid kann nach einem erfolgreichen Build ein Image-Update erkennen. Updates
bewusst über die Docker-Seite installieren; eine automatische Installation auf
dem NAS ist nicht eingerichtet. Datenordner beibehalten. Vor Updates eine Sicherung:

```sh
docker exec --user 99:100 family-os python manage.py backup --output /data/backups/family-vor-update.sqlite
```

Für jede Sicherung einen neuen Namen verwenden. Datenbank und zugehörigen
`.keys`-Ordner auf ein separates geschütztes Ziel kopieren.

Ein älterer Image-Tag lässt sich im Repository-Feld der Vorlage fest einstellen.

**Datenbankschema:** Die Datenbank trägt eine Schema-Version. Ein neues Image passt
sie beim Start automatisch an. Vorher legt es unter `/data/backups/` eine Kopie mit dem
Namen `pre-migration-v<alt>-v<neu>-<Zeitpunkt>.sqlite` an. Schlägt eine Anpassung fehl,
wird sie vollständig zurückgenommen und der Container startet nicht. Ein älteres Image
verweigert den Start mit einer neueren Datenbank, statt sie falsch zu verwenden.
Für einen Rollback deshalb das ältere Image **und** die passende `pre-migration`-Kopie
als `/data/family.sqlite` einsetzen. Danach vorgenommene Änderungen fehlen dann.
Automatische `pre-migration`-Kopien ersetzen nicht die Sicherung auf ein separates Ziel.

**Tägliche Sicherung:** Unter `/data/backups/auto/` liegen die letzten 14 Tagesstände
(Datenbank und `keys`). Einstellbar über „Sicherungen aufbewahren“ und „Sicherungsordner“
(erweiterte Ansicht der Vorlage). Wiederherstellung wie oben beschrieben: Datenbank aus dem
Tagesordner als `/data/family.sqlite`, Dateien aus `keys` nach `/data`.

## Was die Pipeline prüft

Alle Python-Tests, JavaScript-Syntax und XML-Einstellungen. Danach ein echter
Docker-Build und Start im Produktionsmodus: geschützter API-Zugriff, beschreibbarer
Datenordner, unprivilegierter Anwendungsprozess und Datenerhalt nach Neustart.
Beide Startvarianten werden geprüft: regulärer Docker-Betrieb und Unraid-Initialisierung.
Pull Requests veröffentlichen keine Images; Zugangsdaten sind für die Tests unnötig.
Das tatsächlich veröffentlichte Image durchläuft ebenfalls den Container-Test.

Die Pipeline ersetzt nicht den Test eures Reverse Proxys, des Gemeinschaftskalenders
und der Push-Zustellung auf euren iPhones.
