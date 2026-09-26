# Abgleich der Anforderungen mit der bisherigen Repository-Dokumentation

Stand: 26. September 2026. Geprüfter Ausgangsstand: Commit
`769427d29d33ca9d8584b33e961a4176d17bf2ce`, vor Ergänzung dieses Katalogs.

Geprüft wurden sämtliche damals vorhandenen Markdown-Dateien im Repository:
README.md, UNRAID.md, VERBINDUNGEN.md, COOKIDOO.md und PRUEFSTAND.md.
Verglichen wurde mit dem verfügbaren Anforderungsinterview und den späteren
Änderungswünschen. Externe lokale Cookidoo-Prüfdateien sind keine im Repository
vorhandene Anforderungsdokumentation.

**Ergebnis:** Nein, zuvor waren nicht alle erhobenen Anforderungen als Markdown im
Repository dokumentiert. Die vorhandenen Dateien beschrieben überwiegend Bedienung,
Einrichtung, implementierte Funktionen und Tests. Ein vollständiger Produktkatalog
mit den noch nicht gebauten Bereichen fehlte.

„Vorhanden“ in dieser Tabelle bedeutet **vorher dokumentiert**, nicht automatisch
vollständig implementiert oder abgenommen. Der neue Soll-Katalog ist
[ANFORDERUNGEN.md](ANFORDERUNGEN.md).

| Bereich / IDs im neuen Katalog | Vorherige Abdeckung | Bereits vorhanden | Fehlende bzw. nun ergänzte Inhalte |
| --- | --- | --- | --- |
| Produktziel, Nutzer, Priorität Z-01–Z-08 | Teilweise | README: Familienplanung, bestehende Bereiche, Demo, zurückgestellte Rückmeldung Brittas. | Zentrales Such-/Vergessensproblem, Proaktivität und geringer Pflegeaufwand, KI als optionale Hilfe, ausdrückliche erste Priorität einschließlich Nanny. |
| Betreuung B-01–B-06, B-16 | Teilweise | README: Monatsentwurf, gleichmäßige fünf Wege pro voller Woche, Nanny-Ausnahmen als Lücke. | Couch-Ablauf mit Arbeitsnotebooks, zwei Vollzeitbeschäftigte, Mo–Fr 08–17 Uhr, übliche Abholung 16:15, keine festen Wochentage, Nachmittag bis Zubettgehen und Nanny-Übergabe zuhause. |
| Monatliche Fairness B-07 | Nicht ausdrücklich als Anforderung | README beschreibt Monatsplanung; Wochenziel fünf Wege dokumentiert. | Späterer ausdrücklicher Wechsel von „Gemeinsam getragen“ auf Monatsbetrachtung; Unterschied zwischen Wochenorientierung und Monatsauswertung. |
| Arbeitskalender B-02, B-08–B-09, B-13 | Teilweise | README/VERBINDUNGEN: keine Firmenanbindung, persönliche Aktualisierungsaufgaben. | Company-Policy als zwingende Grenze, genaue Eintragsnamen, Abwesend-Status und Tobis konkrete Zeitblöcke. |
| Freigaben, Klärung, gemeinsamer Modus B-10–B-15, A-09 | Weitgehend | README/VERBINDUNGEN: vorläufige Google-Einträge, aktive Bestätigung, Klärungspunkte, Arbeitskalenderaufgaben, Couch-Modus. | Historischer iMessage-/Kalenderablauf und explizite Trennung von Nutzerwunsch und gewählter zweistündiger Modusdauer. |
| Nanny N-01–N-07 | Nur als ausstehender Bereich genannt | README/PRUEFSTAND nennen Nanny als spätere Arbeit. | Ein- bis zweimal pro Woche, gewöhnlich 16–18 Uhr, flexible Tage, Einzelanfrage/Bestätigung per WhatsApp, familieninterne Nutzung, Stunden aus Kalender, Tobi zuständig, 20 EUR/Stunde, Minijob, Monatsabrechnung und Überweisung. |
| Essensplanung E-01–E-08 | Teilweise bis weitgehend | COOKIDOO: Sa–Fr, Standardportionen, Zeitlimit, vegetarische/proteinorientierte Auswahl als Lücke, inoffizielle API. | Donnerstag/Freitagmittag als Planungszeit, Freitagabend/Samstagvormittag bei Kaufland, ausschließlich Thermomix, Lina isst mit, vier Portionen genügen, längere Wochenendgerichte und Automatisierungswunsch als Soll. |
| Einkaufsablauf E-09–E-13 | Teilweise (E-09 mit E-16 vorhanden) | COOKIDOO: eigene Artikel, Häkchen, gezielte Rezeptzutaten, kein Leeren, manuelle Offline-Kopie, Mehrdeutigkeitsgrenzen. | Vollständiger bisheriger Wochenwechsel einschließlich Bereinigung alter Rezeptzutaten, Vorratsdurchgang, Frühstück/Spontanbedarf; Dokumentation, dass derzeitige Sperren die Anforderungen nicht ersetzen. |
| PAYBACK/Gutscheine G-01–G-07 | Fehlend | Keine fachliche Beschreibung in den fünf Dateien. | Aktionsmeldungen, Punktesammeln, Wunschgutschein→Kaufland, ca. 24 Stunden plus eine Stunde, E-Mail-Link/PDF, Kassen-Zugriff, aktive/teilverbrauchte/archivierte Gutscheine, iCloud-Ordner, CAPTCHA-Grenzen. |
| Kleidung/Krippe/Vinted K-01–K-05 | Fehlend | Keine fachliche Beschreibung. | Brittas Zuständigkeit, Aussortieren, Saisonbedarf, dringende/geplante Käufe, Wechselkleidung in Krippe, Hinweise beim Abholen, Bilder/Artikeltexte für Vinted. |
| Windeln K-06–K-07 | Fehlend | Keine fachliche Beschreibung. | Nur Heimvorrat, Krippe stellt selbst, Meldung „Neue Packung geöffnet“, keine Einzelverbrauchserfassung. |
| Eingaben/Aufgaben A-01–A-03 | Teilweise | README: persönliche Aufgaben/Erinnerungen, Spracherkennung als ausstehend. | Sprache und Text als Eingabewunsch, Aufnahme nach Transkription löschen, explizit keine Aufgabe ohne Verantwortung. |
| Push/Übersichten A-04–A-08 | Weitgehend | README/VERBINDUNGEN: iPhone-Push, sofortige Terminabstimmung ohne Nachtruhe, Vorabend/Sonntag, Implementierungszeiten. | Erlaubnis für Namen in Kalender/Push und Unterscheidung zwischen gewünschtem Abendzeitpunkt und implementierten exakten Uhrzeiten. |
| Datenschutz/Qualität D-01–D-03, Q-01 | Teilweise | README/VERBINDUNGEN/COOKIDOO: lokale Daten, Authentifizierung, verschlüsselte Tokens, Freigabe-/Fehlerbehandlung. | Erlaubnis ausgewählter externer KI-Inhalte, Adressen/Geburtstage bleiben lokal, Datensparsamkeit bei hoher Qualität als expliziter Maßstab. |
| Verfügbarkeit V-01 | Teilweise / Kontext unvollständig | README/COOKIDOO: Offline-Kopie und fehlender vollständiger Offline-Abgleich. | Google-Kalender und Einkaufsliste als vom Nutzer besonders kritisch benannte Bereiche; exaktes Ausfallszenario nicht aus pauschaler Zustimmung rekonstruieren. |
| NAS/Zugang T-01–T-05 | Weitgehend | UNRAID/README/VERBINDUNGEN: Docker, Intel-Zielplattform, Domain konfigurierbar, Reverse Proxy, persönliche MFA-Konten. | 14. Intel-Generation, 32 GB RAM, nur iGPU, öffentliche IPv4, ausdrücklicher Zugang ohne VPN und vorhandene Infrastruktur. |
| Betrieb/Kosten T-06–T-07 | Teilweise bzw. fehlend | UNRAID/README: Anleitungen für Installation, Updates, Backup. | Tobi als technischer Verantwortlicher und etwa 5–10 EUR monatliches Budget für externe Dienste. |
| Repository/Pipeline/Unraid-XML T-08–T-10 | Weitgehend | UNRAID/README: GitHub Actions, GHCR, XML, Installations-/Updateablauf. | Nutzerauftrag einschließlich direkter Push-Erlaubnis als Projektentscheidung festgehalten. |
| Offene Punkte O-01–O-12 | Verstreut / unvollständig | README/PRUEFSTAND/COOKIDOO nennen technische Grenzen und fehlende Abnahmen. | Zusammengeführte fachliche Fragen; keine Erfindung von Details aus nicht mehr sichtbaren Interviewfragen. |

## Mit dieser Dokumentation geändert

- Zentralen Soll-Katalog mit stabilen Anforderungs-IDs, Kontext, grobem Umsetzungsstand
  und offenen Entscheidungen ergänzt.
- Diesen Vergleich zum vorherigen Markdown-Bestand festgehalten.
- Einstieg in beide Dokumente in README.md ergänzt.
- Überholte pauschale Aussagen zur noch ausstehenden Google-Einrichtung bzw.
  Cookidoo-Anmeldung an die berichteten Ergebnisse angepasst. Eine vollständige
  Integrationsabnahme wird dadurch ausdrücklich nicht behauptet.

Dieser Abgleich betrifft die Dokumentation. Er implementiert keine Nanny-, Gutschein-,
Vinted-, Vorrats- oder KI-Funktion und macht keine noch offene Entscheidung verbindlich.
