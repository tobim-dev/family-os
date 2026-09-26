# Prüfstand · 26. September 2026

## Ergebnis

Betreuung, gemeinsamer Planungsmodus, monatliche Verteilung, Google-Verbindung
und Mitteilungen sind um eine erste Cookidoo-Anbindung ergänzt. Die aktuellen
Entwicklertests verwenden ausschließlich lokale und simulierte Daten. Tobi hat
den bestehenden Betrieb auf Unraid und die Google-Verbindung bereits bestätigt.

## Automatisch geprüft

129 Tests bestanden (`python -m unittest discover -s tests -v`):

- Passwort und TOTP nötig; Wiederverwendung eines Codes abgewiesen.
- Fehlversuche begrenzt, abgelaufene Sitzungen abgewiesen.
- Demo- und Produktionsdaten nicht vermischbar.
- Geschützte Endpunkte und Herkunftsprüfung für schreibende Anfragen.
- Erst die zweite Person bestätigt einen Vorschlag verbindlich.
- Bestehende Zuständigkeit bleibt bis dahin erhalten.
- Überarbeiteter Vorschlag benötigt neue Zustimmung.
- Doppelte offene und veraltete Vorschläge werden abgewiesen.
- Fehlerhafte Sammelbestätigung wird vollständig zurückgerollt.
- Gleichzeitige Bestätigungen erzeugen genau eine Änderung und Folgeaufgabe.
- Klärungspunkt hat eine verantwortliche Person und wird über bestätigte Neuplanung abgeschlossen.
- Fristablauf ersetzt keine Zustimmung.
- Daten bleiben nach erneutem Start erhalten.
- SQLite-Sicherung enthält konsistenten Plan und Folgeaufgabe; Integritätsprüfung erfolgreich.
- Monatsentwurf verteilt Wege gleichmäßig und überschreibt keinen bestehenden Monat.

Schema-Migrationen:

- Neue Datenbank erhält die aktuelle Schema-Version; wiederholter Start ändert nichts.
- Bestehende, unversionierte Datenbanken (auch der erste veröffentlichte Stand ohne
  gemeinsamen Planungsmodus und Cookidoo-Tabellen) werden ohne Datenverlust übernommen.
  Zusätzlich manuell mit Datenbanken geprüft, die der Code von `f7cd278` und `e66e48a` erzeugt hat.
- Fremder Tabellenaufbau wird abgewiesen und bleibt unverändert.
- Neuere Datenbank wird von älterem Code abgewiesen.
- Vor einer Migration mit Daten entsteht eine geschützte Kopie mit altem Stand.
- Fehlgeschlagene Migration und Fremdschlüsselverletzung werden vollständig zurückgerollt.
- Tabellenumbau mit Fremdschlüsseln funktioniert.

Nanny-Planung (Migration 2):

- Bestehende Aufgaben bleiben bei der Migration erhalten; vorher entsteht eine Sicherung.
- Wunsch erzeugt Aufgabe für Tobi und Mitteilung an die andere Person.
- Ungültige, vergangene und überschneidende Wünsche werden abgewiesen.
- Zustandswechsel nur in erlaubter Reihenfolge; veraltete Versionen werden abgewiesen.
- Nur noch nicht angefragte Wünsche sind änderbar.
- Absage eines bestätigten Termins verlangt die Entscheidung „bezahlt / nicht bezahlt“.
- Abrechnung: geplante Zeit, korrigierte Zeit, bezahlte Absage; nicht bezahlte Absagen
  und Absagen der Nanny zählen nicht. Rundung auf volle Cent.
- Korrektur erst ab dem Termin, mit Grund, rücksetzbar.
- Abschluss erst nach Monatsende und ohne ungeklärte Termine; danach eingefroren
  (Stundenlohnänderung wirkt nicht), Termine gesperrt, Wiederöffnen bis zur Überweisung.
- Abrechnungsaufgabe ab dem Monatsersten 9 Uhr genau einmal.
- Monatsplanung: mehrere Tage atomar (Überschneidung → nichts gespeichert), nur ein Monat,
  eine Mitteilung, eine Anfrage-Aufgabe pro Monat mit aktueller Anzahl, erledigt nach Anfrage.
- Gesammelte Antwort (Zusage/Absage gemischt) atomar; veraltete Version → nichts geändert.

Automatische Sicherung:

- Genau eine Sicherung pro Tag ab der eingestellten Stunde; versäumte Tage werden nachgeholt.
- Kopie besteht die Integritätsprüfung, enthält den aktuellen Stand und die Schlüssel; Rechte 600/700.
- Nur die neuesten N Tagesordner bleiben; fremde Ordner werden nie gelöscht.
- Fehlgeschlagene Integritätsprüfung hinterlässt keinen Ordner und keine Teilkopie.
- Nicht beschreibbares Ziel: Fehler im Status, eine Mitteilung pro Tag, neuer Versuch erst nach einer Stunde,
  danach Erfolg und Fehler gelöscht. Die Demo schreibt keine Sicherungen.

Zusätzliche Integrationstests mit simulierten Google-/Push-Antworten:

- Vorläufige und bestätigte Einträge bleiben getrennt; Freitextgründe werden nicht übertragen.
- Sommerzeit wird in Kalenderzeiten und Nachtruhe berücksichtigt.
- Verlorene Antwort nach erfolgreichem Anlegen: Neustart erzeugt keinen Doppeleintrag.
- Externe Änderungen und Löschungen stoppen die Übertragung und erzeugen Mitteilungen.
- Bestätigter Ersatz erreicht Google vor Entfernung des vorläufigen Eintrags.
- Während der Übertragung geänderter lokaler Stand bleibt zur Übertragung vorgemerkt.
- Persönlicher Lesestatus ändert keine Freigabe.
- Abendübersichten und tägliche Fristerinnerungen werden nicht doppelt erzeugt.
- Die Demo führt keine externen Kalender- oder Push-Aufrufe aus.
- Unzulässige Push-Zieladressen werden abgewiesen.
- OAuth-Rückweg ist einmalig, sitzungs- und cookiegebunden; Abmeldung macht ihn ungültig.
- Google-Tokens sind verschlüsselt; fehlender Schlüssel verhindert unsicheren Ersatz.
- Sicherung enthält Datenbank, Verschlüsselungs-, Push- und Google-Clientdatei.
- Push-Fehler bleiben ausstehend; abgelaufene Abonnements werden deaktiviert.
- Push-Annahme erzeugt keine falsche Lesebestätigung.
- Kalenderabweichung lässt sich nur nach Prüfung des aktuellen Stands erneut übertragen.

Wochenvorschläge (simulierte Cookidoo- und Claude-Antworten):

- Lokal: kein Fleisch/Fisch, Zeitgrenze je Tag, keine Doppelungen, bereits geplante Tage und
  Rezepte der Woche ausgelassen, Rezepte der letzten vier Wochen ausgeschlossen, Details zwischengespeichert.
- An Claude gehen nur `tage` (Wochentag, Minuten) und `kandidaten` (anonyme Nummer, Name, Minuten,
  Eiweiß, Zutaten); keine Namen, Daten, Cookidoo-IDs, Bildadressen oder Wünsche.
- Ungültige Claude-Auswahl (doppelt, zu lang, erfunden, nicht angefragter Tag) wird verworfen und lokal ergänzt.
- Claude-Fehler und erreichtes Monatslimit führen zum lokalen Vorschlag mit Hinweis.
- Vorschläge schreiben nichts nach Cookidoo; die Demo ruft weder Cookidoo noch Claude auf.
- Vegetarisch-Prüfung: Speck im Flammkuchen, Rinderbrühe, Sardellen erkannt; Fleischtomaten und Hühnereier erlaubt.
- Browser: Vorschlagsdialog, Panel mobil ohne Überbreite, „Gesendete Daten“, „Alle übernehmen“
  mit jeweils aktueller Revision je Schritt.

Rezeptbilder:

- Nur HTTPS vom Cookidoo-Bildserver (keine fremden Hosts, Ports, Zugangsdaten im Link).
- Unbekannte oder ungültige Rezept-IDs werden ignoriert; der Browser übergibt nur die ID.
- Bild wird einmal geladen und danach vom NAS-Cache ausgeliefert; Fehlschlag pausiert erneute Versuche.
- Demo lädt nie externe Bilder. Bild-Adressen verändern die Schreib-Revision nicht.
- Endpunkt verlangt Anmeldung; nur Bilder erlauben Browser-Caching, alle anderen Antworten bleiben `no-store`.
- Download-Funktion lokal geprüft: gültiges Bild, zu groß, falscher Typ, HTTP 404.
- Browser (1440 px und 390 px): Bild angezeigt, fehlendes Bild fällt auf Kachel zurück, keine Überbreite.

Zusätzliche Cookidoo-Tests mit simulierten Antworten:

- Samstag bis Freitag über zwei Anbieterwochen und einen Monatswechsel.
- Gezielte Kalenderänderungen, Wiederholung einer bestätigten Anfrage ohne Doppeleintrag.
- Veralteter Stand und belegter Tag verhindern eine ungewollte Änderung.
- Unklare Antwort hält weitere Schreibvorgänge bis zur manuellen Prüfung an.
- Prüfbestätigung liest neu, ohne den alten Schreibvorgang zu wiederholen.
- Rezeptzutaten hinzufügen/entfernen erhält eigene Artikel und bestehende Häkchen.
- Gemeinsam verwendete Zutaten bleiben beim Entfernen eines Rezepts vorhanden.
- Unerwarteter Verlust anderer Artikel wird erkannt und als Prüfhinweis gespeichert.
- Einzeln abhaken, eigene Artikel ergänzen, Zugriffsschutz und HTML-Escaping im Export.
- Mehrfache Kennungen werden samt allen Mengen/Häkchen geladen und exportiert; wechselnde Reihenfolge verändert die Revision nicht.
- Mehrdeutige Einzelartikel werden vor dem Abhaken gesperrt; unabhängige Änderungen bleiben möglich.

Wochenwechsel der Einkaufsliste (E-16, Cookidoo-Ersatz mit mehrfachen Kennungen je Rezept):

- Vorschau nennt alte, neue und bleibende Rezepte, abgehakte Zutaten, eigene Artikel und
  eigene Cookidoo-Rezepte als „nicht automatisch“; die Vorschau schreibt nichts.
- Vollständiger Wechsel: alte Rezepte entfernt, neue ergänzt, eigene Artikel unverändert,
  gemeinsam genutzte Zutaten der verbleibenden Rezepte erhalten.
- Mehrfache Kennungen: Entfernen lässt die Einträge anderer Rezepte stehen, Hinzufügen
  erhält bestehende Häkchen.
- Prüfhinweis (und Stopp weiterer Schreibvorgänge), wenn Cookidoo gemeinsame Zutaten
  mit entfernt, Häkchen verliert, unbeteiligte Zutaten ändert oder eigene Artikel verliert.
- Kein Fehlalarm, wenn Cookidoo einzelne Rezeptzutaten (z. B. Wasser) gar nicht auf die Liste setzt.
- Browser: Entfernen vor Hinzufügen, nur ausgewählte Rezepte, aktuelle Revision je Schritt,
  Stopp beim ersten Fehler. Dialog bei 1300 px und 390 px mit simuliertem Cookidoo durchgespielt.
- Neustart während einer Übertragung erfordert eine Prüfung; parallele Anfragen werden abgewiesen.
- Ein anderer Cookidoo-Zugang wird vor der Anmeldung abgewiesen.
- Passwort und E-Mail werden nicht dauerhaft gespeichert; Tokens verschlüsselt gespeichert und wiederhergestellt.

Elf JavaScript-Tests für Fehlerdarstellung, Cookidoo-Verbindung, Wochenwechsel und Nanny-WhatsApp-Texte bestehen. Oberfläche, neuer
Cookidoo-Bereich und Service Worker sind syntaktisch geprüft.

## In der Oberfläche geprüft

- Änderungsvorschlag als Tobi erstellt: alte Zuordnung blieb sichtbar und gültig.
- Als Britta angemeldet und Vorschlag bestätigt: Zuordnung wechselte.
- Persönliche Arbeitskalender-Aufgabe erschien und wurde ausdrücklich abgeschlossen.
- Neuer Monatsentwurf erzeugte 44 vorläufige Zuordnungen für Oktober 2026.
- Monatsansicht bei 390 px und 1440 px Breite geprüft; keine horizontale Überbreite.
- Mobile Kalenderansicht als lesbare Tagesliste, Desktop als Monatsraster.
- Optionale Browser-Navigation `open_family_view` registriert, gültige Eingabe
  führte zur Monatsplanung; ungültige Eingabe wurde abgewiesen. Keine Schreib-
  oder Freigabefunktionen über dieses Werkzeug.

Neue Oberfläche lokal geprüft:

- Verbindungen zeigt Google ausdrücklich als nicht verbunden und Termine als lokal vorbereitet.
- Testmitteilung erscheint nur im persönlichen Eingang; „Als gelesen“ entfernt den Neu-Status.
- Navigation bei 390 px Breite korrigiert: alle damaligen sechs Ansichten sind erreichbar.
- Verbindungsansicht auf schmaler Breite visuell geprüft; Desktopbreite 1440 px ohne Seitenüberbreite.
- Domain ist konfigurierbar; die Demo nennt die geplante Adresse.

Nanny-Oberfläche (Playwright, Demo, 1440 px und 390 px):

- Wunsch angelegt, WhatsApp-Anfrage geöffnet (Link mit vollständigem Text), als angefragt
  markiert, Zusage eingetragen, tatsächliche Zeit korrigiert; Summe 4,5 Std. = 90,00 €.
- Aufgabe „Nanny anfragen“ verschwindet nach der Anfrage.
- Abholhinweis erscheint im Monatskalender; keine horizontale Überbreite, acht
  Navigationspunkte auf 390 px Breite. Keine JavaScript-Fehler.
- Monatsablauf: Oktober mit vier Tagen geplant, Monatsnachricht mit allen fünf Wünschen,
  als angefragt markiert, Antwort „alle zugesagt“ außer einem Tag gespeichert.
  Monatsplaner auf 390 px ohne Überbreite.
- Echte WhatsApp-Übergabe auf dem iPhone noch nicht geprüft.

Cookidoo-Oberfläche dieser Etappe:

- Beispielwoche und Einkaufsartikel im Desktop-Browser geprüft.
- Mobile Darstellung mit 390 px Breite ohne horizontale Überbreite geprüft.
- Diese Ansicht ist eine Demo; echte Anmeldung und Schreiben in Cookidoo wurden
  in dieser Prüfung nicht ausgeführt.

## Praktisch noch offen

- Cookidoo-Anmeldung am NAS gelang laut übermittelten Logs. Der danach beobachtete Ladefehler wegen mehrfacher Kennungen wurde korrigiert; Rückmeldung zum erfolgreichen Gesamtablauf nach diesem Fix steht noch aus.
- Containerbau und Starttests laufen in GitHub Actions; kein lokaler Docker-Daemon.
- Vollständiger Wiederherstellungslauf in separater NAS-Testinstallation.
- Browserprüfung auf den tatsächlichen iPhones; die bisherigen Tests verwendeten
  eine Browseransicht in iPhone-Breite, kein physisches iPhone.
- Google-Verbindung und Terminzuordnung wurden vom Nutzer als funktionierend bestätigt.
- Push-Zustellung, Berechtigungen und Fokusverhalten auf beiden echten iPhones: offen.
- Cookidoo-End-to-End-Test dieser neuen Oberfläche am echten Konto steht aus, einschließlich
  Wochenwechsel: Verhalten der echten Schnittstelle bei gemeinsam genutzten Zutaten (getrennte
  Einträge oder zusammengeführte Menge) ist nicht belegt.
- Nanny-Termine im Google-Kalender, echter Claude-Aufruf mit eurem Schlüssel, automatischer Offline-Abgleich und Sprache folgen später.

Die Entwickler-Testbibliothek meldet eine Abkündigung ihres bisherigen HTTP-Test-
Adapters. Die Tests sind erfolgreich; die Meldung betrifft nicht den laufenden
Anwendungsserver und sollte bei einem späteren Abhängigkeitsupdate berücksichtigt werden.
