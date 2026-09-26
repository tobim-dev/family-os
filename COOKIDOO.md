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
  die die gesamte bestehende Einkaufsliste leert (siehe aber den geführten Wochenwechsel unten). Das Entfernen eines Rezepts aus
  einem Tag entfernt dessen Zutaten nicht automatisch aus der Einkaufsliste.
- Eigene Cookidoo-Rezepte werden im Kalender angezeigt, aber in dieser Etappe direkt
  in Cookidoo bearbeitet. Das Gerät erhält seine Daten weiterhin über Cookidoo.

## Wochenwechsel der Einkaufsliste

**Einkaufsliste für diese Woche vorbereiten** (unter „Rezepte für den Einkauf“) zeigt zuerst
eine Vorschau für die angezeigte Woche (Samstag bis Freitag):

- **Alte Rezepte entfernen:** alle Rezepte auf der Liste, die in dieser Woche nicht geplant sind.
  Abgehakte Zutaten werden genannt und mit entfernt. Häkchen weg = Rezept bleibt auf der Liste.
- **Neu hinzufügen:** geplante Rezepte, deren Zutaten noch fehlen (Standardportionen).
- **Bleibt:** Rezepte, die schon auf der Liste stehen und in dieser Woche geplant sind.
- **Nicht automatisch:** eigene Cookidoo-Rezepte; bitte direkt in Cookidoo bearbeiten.
- Eigene Artikel werden nie angefasst.

Erst **Wochenwechsel starten** ändert Cookidoo: zuerst entfernen, dann hinzufügen, jedes Rezept
als eigener, geprüfter Schritt mit aktueller Revision. Beim ersten Fehler hält der Wechsel an und
nennt die bereits erledigten Schritte; nach der Prüfung zeigt dieselbe Schaltfläche den Rest.
Danach folgt der Hinweis, die Vorräte durchzugehen und Vorhandenes abzuhaken.

Cookidoo entfernt Zutaten nur pro Rezept, nicht einzeln. Zutaten, die ein verbleibendes Rezept
ebenfalls braucht, bleiben erhalten; ihre Mengenangabe darf Cookidoo dabei neu berechnen.

## Erinnerungen

Bei verbundenem Cookidoo erhält Tobi donnerstags ab 9 Uhr die Aufgabe **Essen planen**
für die kommende Woche (fällig Freitag 12 Uhr), sofern noch nicht alle sieben Abende
geplant sind. Freitags ab 9 Uhr folgt **Einkaufsliste vorbereiten** (fällig 17 Uhr).
Beide Aufgaben schließen sich selbst, sobald die Woche voll geplant bzw. die Einkaufsliste
zur Woche passt; dafür muss die Woche in Family OS einmal geladen sein. Eine erledigte
Aufgabe wird nicht erneut angelegt.

## Wochenvorschläge

„Woche vorschlagen“ sucht in Cookidoo nach vegetarischen, eiweißreichen Gerichten (plus optionale
Wünsche als Suchbegriffe) und prüft die Kandidaten auf dem NAS: keine Fleisch-/Fischzutat, Kochzeit
(Vorgabe Mo–Fr 45, Sa/So 90 Minuten), keine Wiederholung der letzten vier Wochen, Eiweiß pro Portion.
Rezeptdetails werden 30 Tage zwischengespeichert.

Mit einem Claude-API-Schlüssel (`FOS_ANTHROPIC_API_KEY`, in Unraid maskiert) wählt Claude aus diesen
Kandidaten eine abwechslungsreiche Woche. Gesendet werden ausschließlich Wochentag und Zeitgrenze sowie
je Kandidat eine anonyme Nummer, Rezeptname, Minuten, Eiweiß und Zutatennamen. Keine Namen, Datumsangaben,
Cookidoo-IDs, Verläufe oder Wünsche. „Gesendete Daten“ zeigt den genauen Inhalt. Die Antwort wird lokal
geprüft; ungültige Auswahl wird verworfen und vom NAS ergänzt. Ohne Schlüssel, bei Fehlern oder nach dem
Monatslimit (`FOS_CLAUDE_MONTHLY_CALLS`, Vorgabe 40) entsteht ein lokaler Vorschlag. Modell über
`FOS_CLAUDE_MODEL` (Vorgabe `claude-haiku-4-5-20251001`).

Vorschläge ändern Cookidoo nicht. „Übernehmen“ bzw. „Alle übernehmen“ nutzt den abgesicherten Weg
mit Revisionsprüfung je Rezept und hält bei einer Abweichung an.

## Rezeptbilder

Wochenplan, Suchtreffer und Rezeptdetails zeigen die Vorschaubilder aus Cookidoo.
Der Browser lädt sie ausschließlich vom NAS (`/api/meals/image/<Rezept-ID>`), nie direkt
von Cookidoo; die strikte Inhaltsrichtlinie der Seite bleibt unverändert. Der NAS holt
jedes Bild einmal vom Cookidoo-Bildserver (`assets.tmecosys.com`, nur HTTPS), prüft
Bildtyp und Größe (höchstens 2 MB) und speichert es unter `/data/recipe-images/`
(höchstens 400 Dateien, älteste werden entfernt). Der Ordner muss nicht gesichert werden.
Fehlt ein Bild oder schlägt der Abruf fehl, erscheint eine neutrale Kachel; ein neuer
Versuch folgt frühestens nach einer Stunde. Bild-Adressen beeinflussen nicht die Revision,
mit der Schreibvorgänge gegen parallele Änderungen geschützt werden. Die Demo lädt keine Bilder.

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

Wer Family OS einmal mit Verbindung öffnet, hat auf diesem Gerät automatisch eine Lesekopie
der Einkaufsliste und der aktiven Gutschein-PDFs (höchstens alle fünf Minuten aktualisiert).
Ohne Verbindung, wenn das NAS nicht antwortet oder nach fünf Sekunden ohne Antwort öffnet sich
**Einkauf offline** mit dem Stand der Liste. Dort lässt sich nichts ändern; abgehakt wird in der
Cookidoo-App. Beim Abmelden wird die Kopie gelöscht. iOS kann den Speicher einer Website
bei längerer Nichtnutzung leeren; als Home-Bildschirm-App ist das seltener. Einmal mit Verbindung
öffnen stellt die Kopie wieder her.

### Als Datei

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

## Mehrfach vorkommende Einkaufskennungen

Cookidoo kann dieselbe Kennung mehrfach liefern, insbesondere beim Zusammenführen
von Zutaten aus mehreren Rezepten. Family OS erhält alle gelieferten Positionen,
Mengen und Häkchen. Es fasst solche Einträge nicht still zusammen und bricht den
Ladevorgang deshalb nicht mehr ab. Die Reihenfolge gleichnamiger Kennungen wird
stabil sortiert, damit eine andere Lieferreihenfolge keinen falschen Konflikt erzeugt.

Ein Hinweis kennzeichnet diesen Fall. Häkchen mit mehrfacher Kennung werden in
Family OS gesperrt und müssen direkt in Cookidoo geändert werden; der Schutz gilt
auch auf dem Server, nicht nur für die Schaltflächen.

Rezeptzutaten lassen sich trotz mehrfacher Kennungen hinzufügen und entfernen
(Entscheidung E-16). Statt einzelne Positionen zuzuordnen, zählt Family OS nach dem
Schreiben nach: Wochenplan, eigene Artikel und die übrigen Rezepte müssen exakt gleich
sein; Kennungen, die das Rezept nicht verwendet, müssen unverändert sein. Bei Kennungen
des Rezepts darf beim Hinzufügen keine bisherige Position und kein Häkchen fehlen; beim
Entfernen darf nichts Neues entstehen und jede Zutat, die ein anderes Rezept braucht,
muss vorhanden bleiben. Weicht etwas ab, bleibt ein Prüfhinweis und weitere
Schreibvorgänge sind angehalten.
