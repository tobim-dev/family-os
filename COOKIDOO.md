# Cookidoo · erste integrierte Ausbaustufe

## Auf dem NAS verbinden

1. Family-OS-Container in Unraid auf das aktuelle Image aktualisieren. Das bestehende `/data`-Verzeichnis beibehalten.
2. Family OS im Browser neu laden und als Tobi anmelden.
3. **Essen & Einkauf → Cookidoo verbinden** öffnen.
4. E-Mail und Passwort des bestehenden deutschen Cookidoo-Kontos direkt dort eingeben.
5. Die eingelesene Woche und Einkaufsliste mit Cookidoo vergleichen.

Es wird kein zusätzlicher API-Schlüssel benötigt. E-Mail und Passwort werden zur
Anmeldung vom NAS an Cookidoo/Vorwerk übermittelt. Das Passwort wird nicht dauerhaft
abgelegt; Zugangstokens werden mit dem bestehenden `integration.key` verschlüsselt
in der Datenbank gespeichert. Zur Erkennung eines Kontowechsels wird lokal ein Hash
der normalisierten E-Mail gespeichert. Nach Ablauf oder Widerruf des Zugangs
**Zugang erneuern** mit demselben Konto verwenden. Ein anderer Zugang wird abgewiesen,
damit alte Planungsstände nicht still mit einem anderen Konto vermischt werden.

Britta kann nach der Verbindung dieselbe Planung und Einkaufsliste verwenden.
Nur Tobi verbindet oder erneuert den Zugang. Die lokale Demo zeigt Beispieldaten
und lässt keine echten Cookidoo-Schreibvorgänge zu.

## Wochenplanung und Einkauf

- Angezeigt werden immer Samstag bis Freitag, auch über Monatsgrenzen hinweg.
- Vorhandene Einträge aus „Meine Woche“ werden übernommen. Leere Tage lassen sich
  über **Rezept auswählen** ergänzen; belegte Tage werden nicht still ersetzt.
- Die Suche bietet eine maximale Gesamtzeit. Vor dem Einplanen erscheinen die
  Standardportionen und Zutaten. Vegetarische Eignung bitte anhand der Zutaten prüfen:
  Suchbegriffe sind keine garantierte Ernährungskennzeichnung. Eine automatische
  vegetarische und proteinorientierte Menüauswahl ist noch nicht enthalten.
- Ein geplantes Rezept kann gezielt zur Einkaufsliste hinzugefügt werden. Enthaltene
  Rezepte werden nicht erneut hinzugefügt. Mengen bleiben bei den Cookidoo-Standardportionen.
- Vorhandene Zutaten oder gekaufte Artikel lassen sich abhaken; eigene Artikel ergänzen.
- Einzelne Rezeptzutaten lassen sich aus der Liste entfernen. Es gibt keine Funktion,
  die die gesamte bestehende Einkaufsliste leert. Das Entfernen eines Rezepts aus
  einem Tag entfernt dessen Zutaten nicht automatisch aus der Einkaufsliste.
- Eigene Cookidoo-Rezepte werden im Kalender angezeigt, aber in dieser Etappe direkt
  in Cookidoo bearbeitet. Das Gerät erhält seine Daten weiterhin über Cookidoo.

## Abgleich und Fehlerfälle

Der Server liest die zuletzt abgeglichene Essenswoche und die Einkaufsliste etwa
alle zehn Minuten. **Mit Cookidoo abgleichen** lädt sie sofort neu; ein bisher
ungeladener Wochenwechsel löst ebenfalls einen Abruf aus. Eine bereits gespeicherte
Woche zeigt zunächst ihren gespeicherten Stand mit Datum und Uhrzeit.

Vor jedem Schreiben wird der aktuelle Cookidoo-Stand gelesen. Hat er sich seit der
Anzeige geändert, wird die Anfrage abgewiesen und der neue Stand gespeichert.
Nach jedem Schreiben wird erneut gelesen und die gewünschte Änderung sowie der
Erhalt der übrigen Daten geprüft. Eine identische bestätigte Anfrage wird nicht
nochmals ausgeführt. Parallele Aufträge innerhalb dieses Servers werden abgewiesen.

Bei Verbindungsabbruch, unerwartetem Ergebnis oder Neustart während der Übertragung
bleibt ein Prüfhinweis. Weitere Schreibvorgänge sind dann angehalten. **Ich prüfe den
Stand** führt zur ausdrücklichen Bestätigung nach eurer Kontrolle in Cookidoo.
Dabei wird nur neu gelesen, kein alter Schreibauftrag wiederholt oder rückgängig gemacht.

Die inoffizielle Schnittstelle bietet keinen atomaren Vergleich-und-Schreibvorgang.
Änderungen direkt in Cookidoo können sich deshalb trotz Vorprüfung mit einer laufenden
Übertragung überschneiden. Solche Abweichungen werden nach Möglichkeit beim
Zurücklesen erkannt; eine automatische Reparatur oder absolute Verlustfreiheit ist
nicht zugesichert. Während einer Übertragung am besten nicht parallel dieselben
Einträge in Cookidoo bearbeiten. Genau einen Family-OS-Prozess pro Datenbank betreiben.

## Einkauf ohne NAS-Verbindung

**Offline-Kopie speichern** lädt eine eigenständige HTML-Einkaufsliste mit Zeitstempel.
Vor dem Einkauf auf dem Gerät speichern und prüfen, ob sie sich dort öffnen lässt.
Sie enthält die zuletzt vom Server gelesene Einkaufsliste. Die Anwendung selbst
funktioniert damit noch nicht vollständig offline. Änderungen an dieser Kopie werden
nicht zurückübertragen; die Häkchen sind kein dauerhaft synchronisierter Einkaufsstand.
Das Öffnen in der Dateien-App auf einem echten iPhone muss noch praktisch geprüft werden.

## Prüfstand

Die früheren separaten Cookidoo-Proben haben Lesen, einzelne Kalenderänderungen und
gezielte Zutatenänderungen am echten Konto geprüft. Die integrierte Ausbaustufe ist
mit simulierten Cookidoo-Antworten getestet, einschließlich Verbindungsabbruch,
Doppelanfragen, externer Änderung, Erhalt von Häkchen und eigenen Artikeln. Ein erneuter
End-to-End-Test dieser Oberfläche am echten Konto steht nach dem NAS-Update noch aus.
Die Schnittstelle kann sich unabhängig von Family OS ändern; zusätzliche Logins oder
CAPTCHAs werden nicht umgangen.

## Wenn das Verbinden fehlschlägt

Anmeldung und erstes Laden erfolgen in getrennten Anfragen. Eine bestätigte Anmeldung
wird auch dann als erfolgreich bezeichnet, wenn danach die Wochenplanung nicht geladen
werden kann. **Planung erneut laden** wiederholt nur den Abruf. Das Passwortfeld wird
nach erfolgreicher Anmeldung geleert. Einzelne Vorgänge werden nach insgesamt 45 Sekunden
abgebrochen; unklare Schreibvorgänge bleiben dabei zur Prüfung angehalten.

Die Anwendung zeigt eine Diagnosekennung sowie den betroffenen Schritt an und speichert
die letzte Diagnose lokal. So bleibt sie über die Essensansicht abrufbar, auch wenn ein
Reverse Proxy die HTTP-Fehlerantwort ersetzt. Erfolgreiche Vorgänge löschen den alten Hinweis.

Unter **Unraid → Docker → Family-OS-Symbol → Logs** stehen Einträge wie `Cookidoo started`,
`Cookidoo completed` oder `Cookidoo failed`, jeweils mit Diagnosekennung. Fehler nennen
Schritt, feste Fehlerkategorie und gegebenenfalls HTTP-Status des Anbieters. Ausnahme-
texte, Antwortinhalte, URLs und Zugangsdaten werden nicht protokolliert. Normale
Zugriffslogs bleiben ausgeschaltet. Fehlt nach einem erneuten Versuch selbst der
Start-Eintrag, muss als Nächstes geprüft werden, ob die Anfrage diesen Container erreicht.

Ein HTTP 502 ohne diese Diagnose beweist keine falschen Zugangsdaten. Es kann auch der
Reverse Proxy antworten. Seine konkrete Ursache muss anhand des neuen Versuchs geprüft werden.
