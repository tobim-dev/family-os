# Google und iPhone verbinden

Vorbereitet für **https://fos.lausbuben.cloud** und euren bestehenden Gemeinschaftskalender.
Die Domain bleibt über `FOS_ORIGIN` konfigurierbar. Diese Einrichtung findet auf dem
NAS statt; die lokale Demo verbindet keine echten Konten.

## 1. Anwendung auf dem NAS

Die Schritte für Container, persönliche Konten mit MFA und Reverse Proxy stehen in
[README.md](README.md). Erst beide Konten einrichten und HTTPS testen. Genau einen
Container betreiben. Die folgende Einrichtung startet die Übertragung vorhandener
Familienplanung; ausschließlich echte, gemeinsam geprüfte Planung verwenden.
Die Beispieldatenbank niemals als Produktionsdatenbank übernehmen.

## 2. Google vorbereiten

In der Google Cloud Console ein eigenes Projekt für Family OS anlegen, die
Google Calendar API aktivieren und einen OAuth-Client vom Typ **Webanwendung**
einrichten. Einen privaten Google-Zugang verwenden, der euren Gemeinschaftskalender
bearbeiten darf. Keine Firmenkonten anbinden.

Den Einwilligungsdialog für die private Nutzung konfigurieren; beim ersten Test
Tobis privaten Google-Zugang als Testnutzer eintragen. Autorisierte Weiterleitungs-URI:

```text
https://fos.lausbuben.cloud/api/google/callback
```

Bei anderer Domain entsprechend anpassen. Die Anwendung fordert ausschließlich
`https://www.googleapis.com/auth/calendar.events` an. Google begrenzt diese
Berechtigung nicht auf eine einzelne Kalender-ID. **Die Anwendung selbst verwendet
nur die konfigurierte ID und ihre eigenen Einträge.** Sie liest weder eine
Kalenderliste noch fremde Termine. Wer technisch noch enger isolieren möchte,
kann einen separaten privaten Google-Zugang verwenden, dem nur der
Gemeinschaftskalender zur Bearbeitung freigegeben ist.

Die OAuth-Clientdatei lokal herunterladen und als `/data/google-client.json` im
Container ablegen. Sie enthält ein Geheimnis: nicht in Chat oder Quellcode kopieren.
Für UID 10001 lesbar machen, Dateimodus 600. Bei einem benannten Docker-Volume lässt
sich die Datei beispielsweise so aus dem Projektverzeichnis einspielen:

```sh
docker compose cp google-client.json family-os:/data/google-client.json
docker compose exec --user root family-os chown 10001:10001 /data/google-client.json
docker compose exec --user root family-os chmod 600 /data/google-client.json
```

In den Google-Kalendereinstellungen des Gemeinschaftskalenders unter
„Kalender integrieren“ die **Kalender-ID** kopieren und in `.env` eintragen:

```text
FOS_ORIGIN=https://fos.lausbuben.cloud
FOS_GOOGLE_CALENDAR_ID=die-tatsaechliche-kalender-id
```

Danach `docker compose up -d` ausführen, als Tobi anmelden und unter
**Verbindungen → Mit Google verbinden** die private Anmeldung und Einwilligung
selbst abschließen. Keine Passwörter oder Einmalcodes hier im Chat teilen.
Google-Tokens werden verschlüsselt gespeichert; der Schlüssel liegt auf dem NAS.
Der Rückweg verwendet einen kurzlebigen, einmaligen Verbindungsnachweis.

Im Reverse Proxy für `/api/google/callback` keine URL-Abfrageparameter protokollieren:
Sie enthalten einen kurzlebigen Autorisierungscode. Der Anwendungscontainer
schreibt deshalb keine Zugriffsprotokolle mit URLs.

**Für dauerhaften Betrieb:** Googles externer OAuth-Testmodus lässt Refresh-Tokens
für diesen Kalenderzugriff nach sieben Tagen ablaufen. Vor dem Dauerbetrieb den
Veröffentlichungsstatus und die für euren privaten Anwendungsfall geltenden
Google-Vorgaben prüfen. Quelle: [Google OAuth-Dokumentation](https://developers.google.com/identity/protocols/oauth2).
Die Anwendung zeigt Übertragungsfehler an; ein abgelaufener Zugang lässt sich in
„Verbindungen“ neu autorisieren.

## 3. Ersten echten Kalenderablauf prüfen

1. Einen künftigen Bringtermin als Tobi vorschlagen.
2. Unter Verbindungen den erfolgreichen Abgleich abwarten; in Google muss ein
   „[Vorläufig]“-Eintrag erscheinen.
3. Als Britta bestätigen. Der bestätigte Termin muss in Google erscheinen,
   anschließend verschwindet der vorläufige Eintrag.
4. Persönliche Aufgaben zur Arbeitskalenderpflege prüfen und selbst ausführen.
5. Testweise die Internetverbindung des Containers unterbrechen: Die Planung
   bleibt gespeichert, die Übertragung darf nicht als erfolgreich erscheinen.
6. Verbindung wiederherstellen und den automatischen erneuten Abgleich prüfen.

Änderungen direkt in Google halten die Übertragung des betroffenen Eintrags an.
Tobi kann unter „Abweichung prüfen“ den Google-Stand mit dem Family-OS-Stand
vergleichen. „Family-OS-Stand übertragen“ stellt diesen Stand wieder her. Soll
stattdessen die Änderung aus Google gelten, sie zuerst im Family OS vorschlagen
und gemeinsam bestätigen. Ein zwischenzeitlich erneut geänderter Stand muss neu
geprüft werden. Andere Kalendereinträge werden nicht angefasst.

### Nanny-Termine im Kalender

Nanny-Termine erscheinen im selben Gemeinschaftskalender, sobald sie angefragt sind:
angefragte als „[Vorläufig] Nanny · Lina“ (Status „vorläufig“), bestätigte als
„Nanny · Lina“ bzw. mit dem eingestellten Namen der Nanny. Die Einträge blockieren eure
Zeit nicht. Reine Wünsche bleiben nur im Family OS. Abgesagte oder abgelehnte Termine
werden aus Google entfernt. Änderungen direkt in Google halten auch hier die Übertragung
zur Prüfung an.

## 4. iPhones aktivieren

Auf jedem iPhone mit dem eigenen Konto anmelden, die Anwendung über Safari zum
Home-Bildschirm hinzufügen und von dort starten. In **Verbindungen** auf
„Auf diesem Gerät aktivieren“ tippen und die Gerätefreigabe bestätigen.
Web Push für solche Home-Bildschirm-Anwendungen wird seit iOS 16.4 unterstützt.
Quelle: [Apple/WebKit: Web Push](https://webkit.org/blog/13878/web-push-for-web-apps-on-ios-and-ipados/).

„Testmitteilung senden“ ausprobieren: erst bei geöffneter Anwendung, dann bei
abgeschlossener Anwendung und gesperrtem Bildschirm. Anzeige, Ton und Fokusregeln
hängen von den iPhone-Einstellungen ab. Neue Terminabstimmungen haben in der
Anwendung keine Nachtruhe; sie werden trotzdem nicht zu iOS-Notfallmeldungen.

Die Abmeldung beendet die Anmeldesitzung, nicht die zuvor aktivierte Push-Verbindung.
Auf einem gemeinsam benutzten oder abgegebenen Gerät vorher „Auf diesem Gerät
deaktivieren“ verwenden. Ein Gerät kann nicht stillschweigend einer anderen
Person zugeordnet werden. Bei einem neuen Push-Schlüssel müssen Geräte neu
aktiviert werden; den Schlüssel deshalb zusammen mit der Datenbank sichern.

## Vor der alltäglichen Nutzung noch abzunehmen

Tobi hat den NAS-Betrieb, die Einrichtung beider Konten, die Google-Verbindung und
die Terminzuordnung als funktionierend gemeldet. Das ist keine vollständige Abnahme
aller Fehlerfälle. Noch zu prüfen sind insbesondere Push auf beiden iPhones,
Neustart- und Ausfallverhalten sowie Wiederherstellung aus Sicherung.
