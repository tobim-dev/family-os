# Family OS · Anforderungskatalog

Stand: 26. September 2026. Grundlage: das Anforderungsinterview mit Tobi und die
anschließenden Änderungswünsche in dieser Unterhaltung bis zur Dokumentationsanfrage.
Dieser Katalog beschreibt das gewünschte Produkt, nicht nur den bereits gebauten Teil.

## Einordnung und Verbindlichkeit

- **Anforderung:** ausdrücklich beschriebener Wunsch oder bestätigte Entscheidung.
- **Kontext:** heutiger Ablauf, Rahmenbedingung oder Präferenz; nicht automatisch eine neue Automatisierung.
- **Offen:** noch nicht entschieden oder nicht hinreichend konkretisiert.
- **Implementierungsentscheidung:** bereits gewählte technische oder fachliche Ausgestaltung,
  die nicht als eigenständiger Nutzerwunsch ausgegeben wird.

Die Statusangaben sind eine Bestandsaufnahme anhand der vorhandenen Dokumentation und
bisherigen Rückmeldungen, keine erneute vollständige Code- oder Produktionsabnahme.
**Vorhanden** bedeutet dokumentiert implementiert; **Teilweise** bedeutet verbleibende
Lücken; **Ausstehend** bedeutet als Funktion noch nicht vorhanden; **Rahmen** bezeichnet
eine Vorgabe oder einen Kontext ohne eigenständige Fertigmeldung.

Der [Dokumentationsabgleich](ANFORDERUNGSABGLEICH.md) hält fest, was vor diesem Katalog
bereits im Repository stand und was ergänzt wurde. Betrieb und Einrichtung stehen in
[README.md](README.md), [UNRAID.md](UNRAID.md), [VERBINDUNGEN.md](VERBINDUNGEN.md) und
[COOKIDOO.md](COOKIDOO.md). Tests und praktische Abnahmegrenzen stehen in
[PRUEFSTAND.md](PRUEFSTAND.md). Implementierungseinschränkungen ersetzen keine Anforderung.

Einige Interviewantworten sind nur als „Ja, passt“ erhalten; die zugehörigen Fragen
sind im verfügbaren Gespräch nicht enthalten. Daraus werden keine zusätzlichen
Detailanforderungen konstruiert. Solche Unklarheiten stehen unter „Offene Entscheidungen“.

## 1. Ziel, Nutzer und Prioritäten

Quelle: ursprünglicher Produktwunsch, geschilderte Alltagssituationen und ausdrücklich
gewählte erste Funktionsbereiche.

| ID | Anforderung oder Kontext | Stand / überprüfbares Ergebnis |
| --- | --- | --- |
| Z-01 | Eine zentrale Anlaufstelle für die Familienplanung schaffen, damit weniger vergessen wird und Informationen ohne Suchen in Nachrichten auffindbar sind. | Teilweise: Betreuung, Aufgaben und Essen vorhanden; übrige Bereiche fehlen. |
| Z-02 | Hoher Grad an Automation und Proaktivität soll den Alltag entlasten. Zuverlässigkeit und Ergebnisqualität haben Vorrang; Fehler dürfen keine zusätzliche Alltagsarbeit verursachen. | Teilweise: Kalenderabgleich, Aufgaben und Mitteilungen; weitere Routinen ausstehend. Keine Behauptung absoluter Fehlerfreiheit. |
| Z-03 | Tobi und Britta sind die Nutzer. Lina wird mitgeplant. Die Anwendung soll zunächst innerhalb der Familie bleiben. | Rahmen / vorhanden: zwei persönliche Konten; kein Nanny-Konto als Voraussetzung. |
| Z-04 | Bedienung so einfach wie möglich, mit erkennbarem Nutzen und möglichst wenig laufender Datenpflege. | Rahmen: insbesondere bei Vorräten keine Einzelverbrauchserfassung verlangen. |
| Z-05 | KI nur dort einsetzen, wo sie sinnvoll unterstützt; zuverlässige Automation bleibt der Schwerpunkt. | Rahmen: kein KI-Zwang, kein bereits festgelegter Anbieter. |
| Z-06 | Erste fachliche Priorität: Betreuungsplanung mit Klärungspunkten, Nanny-Planung einschließlich Stundenübersicht sowie Essensplanung und Einkauf. | Teilweise: alle drei Bereiche in erster Ausbaustufe vorhanden; Nanny noch ohne Google-Kalender. |
| Z-07 | Auf der vom Nutzer positiv bewerteten Demo aufbauen. | Vorhanden: bestehende Gestaltung und Bedienstruktur werden fortgeführt. |
| Z-08 | Brittas eigene Rückmeldung zunächst zurückstellen, technische Machbarkeit zuerst prüfen. | Rahmen: zurückgestellt bedeutet nicht abgenommen oder dauerhaft ausgeschlossen. |

Kontext zum Interviewzeitpunkt: Beide Eltern arbeiten Vollzeit. Lina war damals kurz
vor ihrem 16. Lebensmonat. Dies ist eine historische Angabe, kein dauerhaft festes Alter
und keine Grundlage, um ein Geburtsdatum zu errechnen oder im Repository zu speichern.

## 2. Betreuung und Kalender

Quelle: monatliche Planung auf der Couch, Regeln zur Bestätigung, spätere Wünsche nach
aktivem gemeinsamem Planungsmodus und monatlicher Ansicht „Gemeinsam getragen“.

| ID | Anforderung oder Kontext | Stand / überprüfbares Ergebnis |
| --- | --- | --- |
| B-01 | Bring- und Abholverantwortung ungefähr einen Monat im Voraus planen. Gemeinsame Sitzung meist am Wochenende; Tag für Tag mit den Arbeitsnotebooks. | Vorhanden: Monatsplanung; manuelle Abstimmung der beruflichen Verfügbarkeit bleibt erforderlich. |
| B-02 | Auf die Arbeitskalender darf wegen Company Policy nicht zugegriffen werden. | Rahmen: keine Firmenanbindung oder verdeckte Übernahme beruflicher Kalenderdaten vorsehen. |
| B-03 | Den bestehenden gemeinsam genutzten Google-Kalender verwenden, keinen neuen separaten Familienkalender voraussetzen. | Vorhanden; Verbindung vom Nutzer bestätigt. |
| B-04 | Betreuung montags bis freitags; offizielle Krippenzeit 08:00–17:00 Uhr. Übliche Abholung etwa 16:15 Uhr, also vor dem offiziellen Ende. | Rahmen: tatsächliche Betreuung und Arbeitskalenderblock unterscheiden. |
| B-05 | Pro vollständiger Betreuungswoche zehn Wege: fünfmal bringen, fünfmal abholen. Möglichst gleichmäßig aufteilen, typischerweise fünf Wege je Person; keine festen Wochentage. | Teilweise: Verteilungslogik vorhanden; Ausnahmen wie Schließtage noch zu konkretisieren. |
| B-06 | Abholen bedeutet normalerweise auch Nachmittagsbetreuung bis zum Zubettgehen; Nanny-Betreuung ist eine Ausnahme. | Teilweise: Abholungen separat sichtbar; keine festgelegte numerische Gewichtung oder Nanny-Verrechnung. |
| B-07 | „Gemeinsam getragen“ auf Monatsbasis statt Wochenbasis darstellen. | Vorhanden: spätere ausdrückliche Änderung; Wochenregel bleibt Orientierungswert, Auswertung ist monatlich. |
| B-08 | Arbeitskalendereinträge heißen „Lina bringen“ bzw. „Lina abholen“ und werden dort als abwesend markiert. | Teilweise: manuelle Pflege durch die Eltern; keine automatische Kontrolle des Firmenkalenders. |
| B-09 | Tobis übliche Arbeitsblöcke: Bringen 07:45–08:45 Uhr, Abholen 15:30–17:30 Uhr, einschließlich Wegezeit. | Vorhanden als Vorgabe; Brittas eigene Zeitfenster sind nicht separat erhoben. |
| B-10 | Vorläufige Termine dürfen vor der Zustimmung im Gemeinschaftskalender stehen, müssen dort eindeutig vorläufig gekennzeichnet sein. | Vorhanden: bestätigten und vorläufigen Stand unterscheiden. |
| B-11 | Im normalen Modus muss die andere Person einer neuen Zuordnung oder Änderung aktiv zustimmen. Keine ungewollte Änderung durch bloßes Lesen oder Schweigen. | Vorhanden: bisheriger bestätigter Plan gilt bis zur Freigabe. |
| B-12 | Untermonatige Änderungen müssen möglich sein; ein Klärungspunkt zeigt zunächst Gesprächsbedarf für beide an. Er muss nicht sofort gelöst werden. | Vorhanden: offener Punkt kann bestehen bleiben, ohne den gültigen Termin zu ändern. |
| B-13 | Nach einer bestätigten Änderung eine explizite Aufgabe „Arbeitskalender aktualisieren“ erzeugen. | Vorhanden: betroffene Person pflegt den eigenen Kalender; Aufgabe hält ausstehende manuelle Übernahme sichtbar. |
| B-14 | Historischer Ablauf: direkte Absprache, unterwegs meist iMessage; verbindlich wurde die Änderung durch geänderte Kalendereinträge. | Kontext: keine daraus abgeleitete Pflicht, iMessage zu integrieren. Im Produkt Freigabe und externe Übertragung getrennt kenntlich machen. |
| B-15 | Explizit aktivierbarer gemeinsamer Planungsmodus für die Couch: ohne zusätzliche Einzelbestätigung Termine gemeinsam zuordnen. | Vorhanden: bewusst gestartete Ausnahme zu B-11; kein Abschaffen der normalen Freigaben. |
| B-16 | Nanny-Wünsche bereits bei der monatlichen Betreuungsplanung mitdenken. Eltern holen Lina immer selbst ab und treffen die Nanny zuhause. | Teilweise: Nanny-Tage mit Hinweis „früher abholen“ im Monatskalender; Wünsche werden in der Nanny-Ansicht angelegt. Keine Abholzuständigkeit an die Nanny. |

Die konkrete Monatsformel im aktuellen Produkt zählt bestätigte Wege an Werktagen,
zeigt Abholungen getrennt und setzt als Ziel die Hälfte aller vorgesehenen Wege.
Diese Formel ist eine Implementierungsentscheidung, keine abschließend vereinbarte
Bewertung aller Betreuungslasten. Feiertage, Abwesenheiten und Krippenschließtage
sind damit noch nicht umfassend abgebildet.

## 3. Nanny-Planung, Stunden und Monatsabschluss

Quelle: zweiter geschilderter Alltagsprozess und spätere Antworten zur Zuständigkeit.

| ID | Anforderung oder Kontext | Stand / überprüfbares Ergebnis |
| --- | --- | --- |
| N-01 | Flexible Betreuung nach der Krippe planen: gewöhnlich einmal pro Woche 16:00–18:00 Uhr, gelegentlich zweimal. Keine festen Tage. | Vorhanden: freie Tage, Vorgabe 16:00–18:00, Überschneidungsschutz. |
| N-02 | Einzelne gewünschte Termine per WhatsApp anfragen und von der Nanny bestätigen lassen. | Vorhanden: Status Wunsch/angefragt/bestätigt/Nanny kann nicht/abgesagt; vorbereiteter WhatsApp-Text (einzeln oder gesammelt), Bestätigung manuell. Siehe N-08. |
| N-03 | WhatsApp ist der bevorzugte Kontaktkanal; die Nanny soll die Familienanwendung zunächst nicht selbst nutzen müssen. | Rahmen: kein Nanny-Login als zwingender Teil des Ablaufs. Automatisches Versenden ist nicht im Detail festgelegt. |
| N-04 | Stundenübersicht als Grundlage der monatlichen Abrechnung führen. Bisher werden Kalendertermine herangezogen, die gewöhnlich wie geplant stattfinden. | Vorhanden: geplante Zeit zählt, Abweichungen minutengenau mit Grund (N-09). |
| N-05 | Tobi pflegt die Stunden und macht die Abrechnung. | Vorhanden: Aufgaben „Nanny anfragen“, „Nanny-Abrechnung“, „Nanny-Lohn überweisen“ gehen an Tobi; beide Eltern können Einträge pflegen, alles im Verlauf. |
| N-06 | Nanny ist auf Minijob-Basis beschäftigt; vereinbarter Lohn 20 EUR pro Stunde. | Rahmen / vorhanden: Stundenlohn einstellbar (Vorgabe 20 EUR), wird beim Monatsabschluss eingefroren. Keine Abgabenberechnung. |
| N-07 | Monatlich Stunden und daraus folgenden Lohnbetrag nachvollziehbar zusammenstellen. Tobi überweist den Betrag. | Vorhanden: Monatsübersicht je Termin, Summe auf volle Cent, Abschluss nach Monatsende, Markierung „überwiesen“. Keine automatische Überweisung. |
| N-08 | Entscheidung 26.09.2026 (O-03): WhatsApp als vorbereiteter Text; Tobi/Britta senden selbst und tragen die Zusage manuell ein. Kein automatischer Versand. | Vorhanden: Öffnen des Links ändert keinen Status; optionale Nummer der Nanny. |
| N-09 | Entscheidung 26.09.2026 (O-04): Abgerechnet wird die geplante Zeit; Abweichungen minutengenau korrigierbar. Kurzfristige Absagen bestätigter Termine: im Einzelfall „bezahlt“ oder „nicht bezahlt“. | Vorhanden: Korrektur nur mit Grund; Absage bestätigter Termine verlangt die Entscheidung. |
| N-11 | Wunsch 26.09.2026: Nanny-Termine für einen Monat gemeinsam planen und der Nanny alle Termine eines Monats in einer WhatsApp-Nachricht schicken. | Vorhanden: Monatsplaner (mehrere Werktage, gemeinsame Zeit), Monatsnachricht, gesammelte Antwort mit Zusage/Absage je Termin, eine Anfrage-Aufgabe pro Monat. |
| N-10 | Entscheidung 26.09.2026 (O-04): An Nanny-Tagen holen die Eltern Lina früher ab, damit die Übergabe zuhause zum Nanny-Beginn (gewöhnlich 16:00) klappt. | Teilweise: Hinweis an der Abholung und in der Tagesübersicht; Abholzeit wird nicht automatisch geändert. |

Geklärt am 26.09.2026: WhatsApp-Umfang, Stundenbasis, Ausfälle und Nanny-Start (N-08 bis N-10).
Offen bleiben Auszahlungskorrekturen nach der Überweisung, zusätzliche Unterlagen der
Minijob-Abrechnung und die Übertragung der Nanny-Termine in den Google-Kalender.
Implementierungsentscheidungen: Wünsche benötigen keine gegenseitige Freigabe (die andere
Person erhält eine Mitteilung); nur noch nicht angefragte Wünsche sind änderbar; ein
abgeschlossener Monat kann bis zur Markierung „überwiesen“ wieder geöffnet werden.

## 4. Essensplanung und Einkauf mit Cookidoo

Quelle: Wochenablauf, Ernährungswünsche, akzeptierte inoffizielle Anbindung und spätere
Cookidoo-Erprobung. Die aktuellen technischen Einschränkungen stehen in COOKIDOO.md.

| ID | Anforderung oder Kontext | Stand / überprüfbares Ergebnis |
| --- | --- | --- |
| E-01 | Für eine Woche im Voraus planen, Samstagabend bis Freitagabend, ein Gericht für jeden Abend. | Vorhanden als Wochenansicht; automatischer vollständiger Wochenvorschlag noch ausstehend. |
| E-02 | Tobi plant gewöhnlich Donnerstag oder Freitagmittag. Einkauf normalerweise Freitagabend oder Samstagvormittag bei Kaufland. | Kontext für spätere rechtzeitige Unterstützung; keine feste Erinnerungsuhrzeit vereinbart. |
| E-03 | Ausschließlich Thermomix-Gerichte verwenden, Planung in Cookidoo „Meine Woche“. | Teilweise: Cookidoo-Anbindung vorhanden; zuverlässige Gesamtbedienung am realen Konto noch abzunehmen. |
| E-04 | Britta und Tobi essen vegetarisch; Lina isst mit. | Rahmen: vegetarische Eignung ist fachliche Vorgabe, nicht allein durch ein Suchwort erfüllt. Weitere Unverträglichkeiten wurden nicht erhoben. |
| E-05 | Gerichte dürfen bevorzugt proteinreich sein. | Vorhanden in den Wochenvorschlägen (E-15): Eiweiß pro Portion aus Cookidoo-Nährwerten als Rangkriterium; keine feste Proteinmenge vereinbart. |
| E-06 | Kochzeit in der Regel höchstens 45 Minuten, am Wochenende auch länger. | Teilweise: Suche mit Zeitlimit; Gesamtzeit wird aktuell verwendet. Kein vereinbartes starres Wochenendlimit. |
| E-07 | Die normalen Cookidoo-Portionen, meist vier, reichen für die Familie. | Vorhanden: Standardmengen übernehmen; keine automatische Umrechnung auf drei Portionen verlangen. |
| E-08 | Das System soll Planung und Übertragung gerne automatisieren, sofern zuverlässig; eine inoffizielle Cookidoo-API ist akzeptiert. | Teilweise: Lesen, gezielte Änderungen und automatische Wochenvorschläge (E-15); Übernahme nach Cookidoo nur per Klick. Zuverlässigkeit bleibt Bedingung. |
| E-09 | Bestehender Wochenablauf: Einkaufsliste von alten Rezeptzutaten bereinigen, selbst ergänzte Artikel dabei erhalten, dann Zutaten aller geplanten Gerichte hinzufügen. | Vorhanden: geführter Wochenwechsel (E-16) mit Vorschau, Auswahl je Rezept und Schritt-für-Schritt-Prüfung; eigene Artikel bleiben unberührt. Praktische Abnahme am echten Konto offen. |
| E-10 | Danach Vorräte zuhause durchgehen und bereits vorhandene Zutaten abhaken. Nur den Rest einkaufen. | Teilweise: Wochenwechsel endet mit dem Hinweis aufs Abhaken; gezielte Häkchen vorhanden. Artikel mit mehrfacher Cookidoo-Kennung weiterhin nur direkt dort abhakbar. |
| E-11 | Liste auch unter der Woche für akuten Bedarf, Frühstück und andere Artikel ergänzen. | Vorhanden als eigene Einkaufsartikel; reale Gesamtintegration noch nicht vollständig abgenommen. |
| E-12 | Vorhandene eigene Artikel und bereits gesetzte Häkchen bei Übertragungen berücksichtigen; keine unbeabsichtigte Listenlöschung oder Doppeländerung. | Teilweise: gezielte, geprüfte Operationen; Rezeptzutaten auch bei mehrfachen Kennungen mit Zählprüfung (E-16), Abweichung → Prüfhinweis. Keine absolute Verlustfreiheitsgarantie der inoffiziellen Schnittstelle. |
| E-15 | Wunsch 26.09.2026: Automatische Rezeptvorschläge für die Essensplanung; Claude API darf genutzt werden, dabei so wenig Daten wie möglich übertragen. | Vorhanden: Kandidaten aus Cookidoo, harte Regeln lokal (vegetarisch, Zeit, Wiederholung, Eiweiß), optionale Auswahl durch Claude mit minimalen anonymen Daten, lokaler Ersatz ohne Schlüssel oder bei Fehlern, Übernahme nur per Klick. |
| E-14 | Wunsch 26.09.2026: Bei der Cookidoo-Planung Bilder der Rezepte anzeigen. | Vorhanden: Vorschaubilder in Wochenplan, Suche und Rezeptdetails, über den NAS geladen und zwischengespeichert (D-01, keine externen Ressourcen im Browser). Reale Anzeige mit dem echten Cookidoo-Konto noch zu bestätigen. |
| E-16 | Entscheidung 26.09.2026 (O-06): Beim Wochenwechsel gelten alle Rezepte auf der Einkaufsliste als alt, die in der gewählten Woche (Sa–Fr) nicht geplant sind; einzelne können in der Vorschau behalten werden. Alte Rezepte werden samt abgehakter Zutaten entfernt (Vorschau zeigt sie). Mehrfache Kennungen sperren Rezeptzutaten nicht mehr; stattdessen Zählprüfung: eigene Artikel exakt gleich, bei nicht betroffenen Kennungen keine Position und kein Häkchen weniger, Abweichung → Stopp mit Prüfhinweis. | Vorhanden: Vorschau, Auswahl, erst entfernen dann hinzufügen, jeder Schritt einzeln geprüft; eigene Cookidoo-Rezepte bleiben manuell. Abnahme am echten Konto offen. |
| E-13 | Einkaufsinformationen sollen unterwegs schnell zugänglich sein. | Teilweise: mobile Ansicht und manuell gespeicherte Offline-Kopie; vollständiger Offline-Abgleich ausstehend. Siehe V-01 für die noch offene genaue Ausfallanforderung. |

Die beim Debugging eingeführte Sperre für mehrdeutige Einkaufskennungen ist eine
vorläufige Implementierungsgrenze. Sie ist kein nachträglich reduzierter Nutzerwunsch.
Alle gelieferten Positionen bleiben lesbar; automatische Wochenplanung und bequemer
vollständiger Einkaufsprozess bleiben offene Produktarbeit.

## 5. PAYBACK, Wunschgutscheine und Kaufland-Gutscheine

Quelle: erster Einkaufsbericht und spätere Konkretisierung von Aktionen und Ablage.

| ID | Anforderung oder Kontext | Stand / überprüfbares Ergebnis |
| --- | --- | --- |
| G-01 | Möglichst viele PAYBACK-Punkte sammeln: Tobi prüft Aktionen und kauft dann Wunschgutscheine zur Umwandlung in Kaufland-Gutscheine. | Ausstehend als Unterstützung; kein festgelegtes Kaufbudget und keine autonome Kaufentscheidung. |
| G-02 | Relevante Aktionen melden und rechtzeitig an die Vorbereitung für den Einkauf erinnern. | Ausstehend: Aktionsquelle und Meldekriterien noch festzulegen. |
| G-03 | Zeitbedarf berücksichtigen: nach Kauf gewöhnlich etwa 24 Stunden bis zur Umwandlung, danach etwa eine Stunde bis zur Bereitstellung per E-Mail. | Ausstehend: Planungswerte mit Pufferbedarf, keine garantierten Anbieterfristen. |
| G-04 | Gutscheine werden über einen E-Mail-Link als PDF bereitgestellt und sollen an der Kaufland-Kasse schnell griffbereit sein. | Ausstehend: zentraler Zugriff; E-Mail-Anbieter oder automatischer Postfachzugriff nicht vereinbart. |
| G-05 | Übersicht aktiver, teilweise genutzter und vollständig verbrauchter Gutscheine bereitstellen. | Ausstehend: Teilrest nachvollziehbar; Herkunft bzw. automatische Ermittlung eines Restbetrags noch offen. |
| G-06 | Aktuelle Ablage: iCloud-Ordner „Einkaufsgutscheine“; vollständig verbrauchte PDFs in Unterordner „Archiv“, teilweise genutzte bleiben aktiv. | Kontext / ausstehend: Ordnerlogik berücksichtigen. Eine automatische iCloud-Synchronisierung wurde nicht verbindlich festgelegt. |
| G-07 | Kaufvorbereitung und Umwandlung können wegen zahlreicher CAPTCHAs schwierig sein. Aktionsmeldungen und Erinnerungen sind ausdrücklich erwünscht. | Rahmen: Vollautomatisierung von Kauf/Umwandlung nicht zugesagt; keine CAPTCHA-Umgehung vorsehen. |

## 6. Kleidung, Krippenausstattung, Vinted und Windeln

Quelle: Aufgabenbereich Britta und Konkretisierung des bisherigen Ad-hoc-Ablaufs.

| ID | Anforderung oder Kontext | Stand / überprüfbares Ergebnis |
| --- | --- | --- |
| K-01 | Britta verantwortet die Koordination von Linas Kleidung. | Ausstehend als eigener Bereich; Verantwortung berücksichtigen. |
| K-02 | Aussortieren und erkennen, was nicht mehr passt; bisher ohne feste Bestandslisten und oft spontan. | Ausstehend: Unterstützung ohne aufwendige Pflichtinventur. |
| K-03 | Pro Saison erkennen, was gebraucht wird und ob Kleidung gekauft werden muss. Manche Käufe sind dringend, andere länger planbar. | Ausstehend: Bedarf und Dringlichkeit unterscheiden; keine Mengen-/Größenregeln erfunden. |
| K-04 | Ausreichende Wechselkleidung in der Krippe im Blick behalten. Personal meldet Bedarf meist beim Abholen; Eltern planen zusätzlich proaktiv. | Ausstehend: Meldung erfassen und Nachfüllaufgabe mit Verantwortung ermöglichen. |
| K-05 | Verkauf aussortierter Kleidung auf Vinted unterstützen; Bilder und Artikelbeschreibungen sind Teil des gewünschten Umfangs. Britta nutzt hierfür bereits KI im Chat. | Ausstehend: konkreter Bildbearbeitungsumfang und Veröffentlichungsablauf offen. Kein autonomes Einstellen oder Verkaufen voraussetzen. |
| K-06 | Windelvorrat zuhause berücksichtigen; die Krippe stellt ihre Windeln selbst. | Ausstehend: keinen elterlichen Windelbestand für die Krippe verlangen. |
| K-07 | Einfache Erfassung wie „Neue Windelpackung geöffnet“ reicht. Genaue Verbrauchsmengen und jede einzelne Entnahme zu protokollieren wäre zu aufwendig. | Ausstehend: ereignisbasierte Unterstützung statt Stückbuchhaltung; Schwellen und Nachkauflogik offen. |

## 7. Eingaben, Aufgaben und Mitteilungen

Quelle: Antworten zu Alltagsbedienung, Zuständigkeiten und Übersichten.

| ID | Anforderung oder Kontext | Stand / überprüfbares Ergebnis |
| --- | --- | --- |
| A-01 | Informationen per Texteingabe oder Sprachnachricht erfassen können. | Teilweise: Texteingaben vorhanden, Sprache ausstehend. |
| A-02 | Sprachaufnahmen nach Umwandlung in Text löschen. | Ausstehend: Sprachverarbeitung muss Löschung als Bestandteil des Ablaufs enthalten. Verhalten bei fehlgeschlagener Transkription noch offen. |
| A-03 | Jede Aufgabe hat eine verantwortliche Person; keine Aufgaben ohne Zuständigkeit. Erinnerungen sind notwendig. | Vorhanden für bestehende Aufgaben; auf neue Bereiche übertragen. |
| A-04 | Benachrichtigungen auf beiden iPhones ermöglichen. | Teilweise: Web Push implementiert, reale Zustellung und Geräteeinstellungen noch abzunehmen. |
| A-05 | Neue Terminabstimmungen sofort per Push melden, unabhängig von der Uhrzeit. | Teilweise: in der Anwendung ohne Nachtruhe; keine zugesagte Umgehung des iPhone-Fokusmodus. |
| A-06 | Tagesübersicht mit Aufgaben und Terminen für den nächsten Tag am Vorabend. | Vorhanden in der Implementierung; konkrete 19-Uhr-Ausgestaltung siehe Entscheidungen, reale Push-Abnahme offen. |
| A-07 | Wochenübersicht als Zusammenfassung am Sonntagabend. | Vorhanden in der Implementierung; reale Push-Abnahme offen. |
| A-08 | Namen dürfen in Kalendern und Push-Mitteilungen stehen. | Rahmen: ausdrückliche Erlaubnis, keine generelle Freigabe aller sensiblen Details. |
| A-09 | Klärungspunkte sind für beide sichtbar und können zunächst offenbleiben. | Vorhanden; siehe B-12. Eine Benachrichtigung oder ihr Lesen löst den Punkt nicht automatisch. |

## 8. Datenschutz, Qualität, Verfügbarkeit und Betrieb

Quelle: ursprünglicher Qualitätsanspruch sowie Antworten zu KI, NAS, Erreichbarkeit,
Kosten und späterer GitHub-/Unraid-Veröffentlichung.

| ID | Anforderung oder Kontext | Stand / überprüfbares Ergebnis |
| --- | --- | --- |
| D-01 | Datensparsam arbeiten, ohne die nötige Qualität der Aufgaben zu opfern; NAS als zentrale Datenhaltung. | Rahmen: Datenumfang je Integration begründen, keine beliebige Cloud-Kopie der Familienplanung. |
| D-02 | Ausgewählte Inhalte dürfen an einen KI-Dienst übermittelt werden. Adressen und Geburtstage sollen auf dem NAS bleiben. | Rahmen / vorhanden: Anbieter Claude API (Entscheidung 26.09.2026). Datenfilter für Essensvorschläge: nur Wochentag + Zeitgrenze und je Kandidat anonyme Nummer, Rezeptname, Minuten, Eiweiß, Zutatennamen. Gesendeter Inhalt in der App einsehbar. |
| D-03 | Außerhalb der verbotenen Arbeitskalender dürfen benötigte Anbindungen geprüft werden, insbesondere Cookidoo und Gemeinschaftskalender. | Rahmen: keine Pflicht, sämtliche verfügbaren Konten anzubinden oder beliebige Daten weiterzugeben. |
| Q-01 | Hohe Zuverlässigkeit: Änderungen, Fehler und unklare Ergebnisse müssen nachvollziehbar sein; fehlgeschlagene Übertragung darf nicht als Erfolg erscheinen. | Teilweise: Prüfungen, Diagnosen, Status, Wiederholungsschutz und tägliche automatische Sicherung; praktische Gesamt-Abnahme verbleibt. Aus dem Qualitätsziel abgeleitete Akzeptanzbedingung. |
| V-01 | Google-Kalender und Einkaufsliste wurden als besonders kritische Bereiche genannt; der Rest ist zunächst weniger kritisch. | Rahmen: genaue Ausfall-/Offline-Frage hinter dieser Antwort ist nicht vollständig überliefert. Verfügbarkeitsdauer, Offline-Schreiben und Wiederabgleich ausdrücklich noch klären. |
| T-01 | Webanwendung auf dem eigenen Unraid-NAS als Docker-Container betreiben. | Vorhanden; NAS-Betrieb vom Nutzer bestätigt. |
| T-02 | Hardware: Intel 14. Generation, 32 GB RAM, nur integrierte GPU. | Rahmen: keine dedizierte GPU voraussetzen; insbesondere für spätere lokale KI relevant. |
| T-03 | Anwendung aus dem Internet ohne VPN erreichbar, mit Nutzerkennung und MFA. | Vorhanden als Betriebsmodell; konkrete Absicherung und Installation siehe UNRAID.md. |
| T-04 | Domain und Zugang vorhanden, öffentliche IPv4 vorhanden; Reverse Proxy konfiguriert Tobi selbst. | Rahmen: kein notwendiger VPN- oder zusätzlicher kostenpflichtiger Zugangsdienst. |
| T-05 | Zieladresse `fos.lausbuben.cloud`, öffentliche Adresse trotzdem konfigurierbar halten. | Vorhanden über Konfiguration, keine fest verdrahtete Domain als Voraussetzung. |
| T-06 | Tobi betreut Updates und technische Probleme. | Rahmen: verständliche Installation, Update- und Diagnoseanleitung bereitstellen. |
| T-07 | Kosten niedrig halten; etwa 5–10 EUR pro Monat für externe Dienste sind akzeptabel. | Rahmen: Planungsbudget, keine belegte Ist-Kostenrechnung oder Freigabe beliebiger Abonnements. |
| T-08 | Quellcode im bereits angelegten GitHub-Repository `tobim-dev/family-os` führen; direkte Pushes wurden ausdrücklich erlaubt. | Vorhanden: dieses Repository ist das Lieferziel. |
| T-09 | GitHub Actions als Test-/Build-Pipeline nutzen. | Vorhanden: Tests und Containerprüfung vor Veröffentlichung. |
| T-10 | Unraid-XML bereitstellen, damit die Anwendung als Container-App installierbar ist. | Vorhanden: eigene Vorlage. Ein Eintrag im öffentlichen Community-Apps-Katalog ist damit nicht automatisch vereinbart. |

## 9. Bereits gewählte Ausgestaltung, getrennt von Nutzeranforderungen

Diese Punkte erklären den aktuellen Stand. Sie dürfen angepasst werden, solange die
oben festgehaltenen Anforderungen erhalten bleiben. Sie sind nicht allein deshalb
verbindliche Interviewanforderungen, weil sie bereits implementiert wurden.

| Entscheidung | Aktuelle Ausgestaltung / Quelle |
| --- | --- |
| Technik | FastAPI, SQLite, einfache Weboberfläche; persistente Daten und Schlüssel im NAS-Datenverzeichnis. README.md und UNRAID.md. |
| Gemeinsamer Planungsmodus | Bewusster Start, pro Anmeldung, Laufzeit zwei Stunden, endet bei Abmeldung oder manuellem Beenden. Nutzer wünschte den Modus; diese konkrete Geltung/Dauer ist Ausgestaltung. |
| Faire Monatsverteilung | Werktage × zwei Wege als Bezugsgröße, halbe Wegezahl als Ziel, Abholungen getrennt; keine komplette Lastgewichtung. |
| Erinnerungszeiten | Aktuell Tages-/Wochenübersicht 19 Uhr, normale Erinnerungen ab 9 Uhr, normale Nachtruhe 21–7 Uhr. Sonntagabend/Vorabend und sofortige Terminabstimmungen sind Nutzeranforderungen; die übrigen exakten Uhrzeiten sind hier als Implementierungsstand vermerkt. |
| Google | Eigene Family-OS-Einträge im bestehenden Zielkalender; kein Import beliebiger fremder Google-Termine. Ob solche Termine künftig in einer Gesamtübersicht benötigt werden, ist offen. |
| Cookidoo | Inoffizielle Bibliothek, verschlüsselte Tokens, getrennte Anmeldung/Erstabruf, gezielte Änderungen, Diagnose und manuelle Prüfung unklarer Schreibvorgänge. Grenzen in COOKIDOO.md. |
| Offline | Manuell speicherbare HTML-Einkaufskopie ist ein Zwischenstand, keine vollständige Offline-App und kein automatischer Rückabgleich. |
| Backups | Manuelle Sicherung sowie tägliche automatische Sicherung (ab 3 Uhr, 14 Tage, mit Integritätsprüfung und Fehlermeldung) im NAS-Datenordner. Vorläufige Implementierungsentscheidung; ein getrenntes Sicherungsziel und Wiederherstellungsziele sind nicht festgelegt. |
| Containerlieferung | GHCR-Image mit `latest` und Commit-Tags; Update wird von Tobi auf Unraid ausgelöst. Eine Pipeline-Veröffentlichung ist noch kein NAS-Update. |

## 10. Offene Entscheidungen und Abnahme

| ID | Noch zu klären / zu prüfen | Betroffene Anforderungen |
| --- | --- | --- |
| O-01 | Brittas Rückmeldung nachholen, ohne den bisherigen Aufschub als Zustimmung zu allen Details zu behandeln. | Z-08, K-01–K-07 |
| O-02 | Brittas Zeitblöcke, Urlaub, Feiertage, Krankheit und Krippenschließtage; Bewertung ungleicher Abhol-/Nachmittagslast und Nanny-Ausnahmen. | B-04–B-09 |
| O-03 | Geklärt 26.09.2026 → N-08. | N-01–N-03 |
| O-04 | Weitgehend geklärt 26.09.2026 → N-09, N-10. Offen: Monatsunterlagen für den Minijob, Korrektur nach Überweisung, Nanny im Google-Kalender. | N-04–N-07 |
| O-05 | Teilweise umgesetzt (E-15) mit vorläufigen Implementierungsregeln: Vegetarisch per Zutaten-/Kategorieprüfung (keine Garantie, Hinweis „bitte prüfen“), keine Wiederholung aus vier Wochen, Mo–Fr 45 / Sa–So 90 Minuten als änderbare Vorgabe. Offen: weitere Familienpräferenzen, Abneigungen, Wiederholungsfenster bestätigen. | E-04–E-08 |
| O-06 | Geklärt 26.09.2026 → E-16. Offen bleibt nur das Abhaken mehrdeutiger Einzelartikel (weiter direkt in Cookidoo). | E-09–E-12 |
| O-07 | Quellen und Kriterien für PAYBACK-Aktionen, Erinnerungszeitpunkt, Gutscheinrestbeträge, PDF-/E-Mail-/iCloud-Zugriff und Automatisierungsgrenzen. | G-01–G-07 |
| O-08 | Saisonbedarf und einfache Kleidungs-/Windel-Erfassung, Nachkaufschwellen und Vinted-Bild-/Text-/Veröffentlichungsablauf mit Britta konkretisieren. | K-01–K-07 |
| O-09 | Spracherkennung lokal oder extern, erlaubte Inhalte, Kontrolle des Texts und Löschung bei Fehlern. | A-01–A-02, D-02 |
| O-10 | Kalender/Einkauf bei NAS- oder Netzausfall: lesend/schreibend, Dauer, iPhone-Verhalten, Wiederabgleich und Konflikte. | V-01, E-13 |
| O-11 | Teilweise: Claude API für Essensvorschläge freigegeben (26.09.2026), Modell Claude Haiku 4.5, Monatslimit 40 Anfragen, Token-Verbrauch in der App sichtbar. Offen: tatsächliche Kosten nach einigen Wochen gegen T-07 prüfen; API-Konto/Schlüssel richtet Tobi ein. | Z-05, D-02, T-07 |
| O-12 | Reale Push-Zustellung auf beiden iPhones, Wiederherstellung aus Backup und Cookidoo-Gesamtablauf nach den jüngsten Fehlerkorrekturen prüfen. | A-04–A-07, Q-01 |

Bereits gemeldet: Google-Verbindung erfolgreich, beide Familienkonten eingerichtet,
Terminzuordnung nach Einrichtung Brittas funktionsfähig. Cookidoo-Anmeldung gelang;
das Laden scheiterte anschließend an mehrfach gelieferten Kennungen. Der entsprechende
Fix wurde veröffentlicht, aber die erfolgreiche Nutzung nach diesem Fix wurde bis zum
Stand dieses Katalogs noch nicht vom Nutzer bestätigt. Diese Tatsachen sind keine
pauschale Abnahme aller Integrationen.

## 11. Pflege des Katalogs

Bei neuen Wünschen bestehende IDs beibehalten, neue Anforderungen mit neuer ID ergänzen
und Änderungen samt Quelle beschreiben. Implementierungsfortschritt aktualisiert den
Status, löscht aber keine noch unerfüllten Anforderungen. Bei einer bewussten Änderung
wie „monatlich statt wöchentlich“ die neue Entscheidung ausdrücklich festhalten.
Offene Fragen werden erst nach Klärung als beschlossene Anforderungen übernommen.
