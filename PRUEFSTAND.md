# Prüfstand · 25. September 2026

## Ergebnis

Die zweite Etappe ist lokal ausführbar: Betreuung, Freigaben, Klärungspunkte,
persönliche Folgeaufgaben und persistenter Stand. Kein externer Kalender wurde
verändert, keine Nachricht versendet und keine echte Familienplanung importiert.

## Automatisch geprüft

34 Tests bestanden (`python -m unittest discover -s tests -v`):

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

JavaScript für Oberfläche und Service Worker syntaktisch geprüft.

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
- Navigation bei 390 px Breite korrigiert: alle sechs Ansichten sind erreichbar.
- Verbindungsansicht auf schmaler Breite visuell geprüft; Desktopbreite 1440 px ohne Seitenüberbreite.
- Domain ist konfigurierbar; die Demo nennt die geplante Adresse.

## Praktisch noch offen

- Docker-Image bauen und auf Unraid starten: lokaler Docker-Daemon war nicht aktiv.
- Reverse Proxy, HTTPS und Einrichtung beider echten MFA-Konten auf dem NAS.
- Vollständiger Wiederherstellungslauf in separater NAS-Testinstallation.
- Browserprüfung auf den tatsächlichen iPhones; die bisherigen Tests verwendeten
  eine Browseransicht in iPhone-Breite, kein physisches iPhone.
- Google-OAuth und Übertragung im echten Gemeinschaftskalender: noch nicht live geprüft.
- Push-Zustellung, Berechtigungen und Fokusverhalten auf beiden echten iPhones: offen.
- Nanny, Cookidoo, Offline-Einkaufsliste und Sprache: folgende Etappen.

Die Entwickler-Testbibliothek meldet eine Abkündigung ihres bisherigen HTTP-Test-
Adapters. Die Tests sind erfolgreich; die Meldung betrifft nicht den laufenden
Anwendungsserver und sollte bei einem späteren Abhängigkeitsupdate berücksichtigt werden.
