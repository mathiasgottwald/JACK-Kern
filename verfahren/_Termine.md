---
verfahren:        Termine
titel:            Termin-Workflow (Kalender, Fahrzeit, Alarme, automatische Änderung)
quelle_auftrag:   F-79 (28.09.2026, Patron-Anordnung 18:30)
herkunft:         eigen (kein Fremdmaterial)
baut_auf:         Block 6 Teil F (jack_kalender.py, CalDAV-Anbindung) — Rolle bleibt: EINZIGER Schreibweg
                  in den Kalender bleibt jack_kalender.py, jack_termine.py baut nur Akte/Alarme/Fahrzeit
status:           gebaut, Muster mit pruefen.sh belegt (Attrappen-CalDAV, kein echter Netzwerkschreibzugriff)
letzte_pruefung:  2026-09-28
---

# Termin-Workflow

## (a) Aufgabenverständnis

Quelle: Patron-Anweisung 28.09.2026 18:30 (wörtlich): „Wenn ich den Termin fixiere, muss er bei mir
eingetragen sein, mit Alarm am Handy, Fahrzeit über Google Maps ausgerechnet — er muss wissen, wann ich wo
wie wegfahren muss. Schreiben die zurück 'es geht um 11', muss er automatisch geändert werden, mit Memo."
Wiederkehrende Aufgabe: jeder bestätigte externe Termin bekommt automatisch Kalendereintrag + Fahrzeit +
2 Alarme; ändert die Gegenseite eindeutig, wird der Eintrag automatisch mitgeändert (mit Memo, nie an
fremden Einträgen).

## (b) Feste Schritte, Werkzeuge, Modell/Aufwand

**Einstiegspunkte:** `jack_termine.termin_bei_mailfreigabe_eintragen(root, kopf, von)`,
`jack_termine.aenderung_anwenden(root, akte_pfad, neuer_zeitpunkt, quelle)`,
`jack_termine.akte_zu_absender(root, absender_email)`.

1. **Termin-Akte** (`betrieb/termine/<datum>_<kurz>.json`): id, titel, projekt, marke, gegenseite, beginn,
   ende, ort, quelle, status (vorgeschlagen → eingetragen → geändert | abgesagt), kalender_uid, fahrzeit,
   abfahrt, alarme, memo-Verlauf (nie gelöscht, nur status geändert).
2. **Ein FREIGEBEN = Mail + Kalender:** hat eine `externemail`-Karte ein `termin:`-Feld, trägt
   `jack_oberflaeche._anwenden()` (Zweig `externemail`) nach erfolgreichem Versand automatisch den Termin
   ein — dieselbe verbrauchte Freigabe deckt beides (Anordnung Patron, siehe Kopfkommentar
   `jack_kalender.py`). **Ausnahme von der Grundregel „Kalender lernt nicht, immer eigene Freigabe"** — nur
   für diesen einen, ausdrücklich angeordneten Fall.
3. **Fahrzeit:** Google Maps Routes API (Schlüssel `GOTT_WALD_GOOGLE_MAPS` im Schlüsselbund, nur Start/Ziel
   werden übertragen, kein Terminname, keine Gegenseite-Daten); ohne Schlüssel Rückfall auf
   `betrieb/fahrzeiten_tabelle.json`, immer als „geschätzt" gekennzeichnet.
4. **Abfahrt** = Beginn − Fahrzeit − 30 Min Puffer − 10 Min Parken/Weg. Zwei VALARM: Vortag 18:00, Abfahrtszeit.
5. **Automatische Änderung durch die Gegenseite** (`jack_postfaecher._verarbeiten`, Hook vor der normalen
   Weiche): nur an Akten mit `kalender_uid` und Status `eingetragen`/`geaendert` (JACK-eigene, bereits im
   Kalender stehende Termine), nur bei EINDEUTIGER neuer Zeit (`aenderung_eindeutig`), sonst normale
   Entscheidungs-Karte. Sicherung des vorherigen Aktenstands vor jeder Änderung, Memo-Karte
   `TERMIN_GEAENDERT` (GELESEN/RÜCKGÄNGIG), Rückgängig über `aenderung_rueckgaengig`.

**Werkzeuge:** `jack_kalender.py` (einziger Schreibweg), `betrieb/standort.json`,
`betrieb/fahrzeiten_tabelle.json`, `betrieb/kosten_fahrzeit.jsonl`.
**Modell/Aufwand je Lauf:** kein Modellaufruf — reine Regel-/Terminlogik, 0 USD (außer Google-Maps-Abfrage,
kostenlos im Rahmen des Monatsguthabens).

## (c) Abnahme-Checkliste

```bash
python3 -m unittest abnahme.F79_2026-09-28.test_f79   # 0 = alle Tests gruen (Attrappen-CalDAV)
```

## (d) Fehler und Korrekturen

(noch keine — frisch gebaut, Opus-Endprüfung siehe `abnahme/pm_eingang/F-79_MELDUNG.md`)

## (e) Abgleich Fähigkeitsregister

Neu, kein Vorgänger — siehe `faehigkeiten/FAEHIGKEITSREGISTER.md`.

## (f) Kosten je Lauf

0 USD (Fahrzeit-Fallback-Tabelle) bzw. kostenlos im Google-Monatsguthaben (Routes API, protokolliert in
`betrieb/kosten_fahrzeit.jsonl`).

## Grenzen

Kein zweiter Schreibweg in den Kalender außer `jack_kalender.py`. Keine automatische Änderung an
Einträgen, die JACK nicht selbst angelegt hat. Kein Standortverlauf nach außen — nur Start/Ziel an Google
Maps. Kein Löschen von Termin-Akten, nur Statuswechsel.
