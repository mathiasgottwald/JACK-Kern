---
verfahren:        Datenauswertung
titel:            Datenauswertung (daten-fachkraft)
quelle_auftrag:   F-73 (nach F-70-Vorschlag, Patron 27.09. 17:00: weitermachen)
herkunft:         eigen (kein Fremdmaterial)
baut_auf:         agenten/70_Daten/daten-fachkraft.md — Rolle bleibt eigenstaendig
status:           gebaut, Muster mit pruefen.sh belegt
letzte_pruefung:  2026-09-27
---

# Datenauswertung (daten-fachkraft)

## (a) Aufgabenverständnis

Quelle: F-70-Vorschlag, Zeile „daten-fachkraft". Wiederkehrende Aufgabe:
Auswertungen und Übersichtstafeln aus bestehenden Holding-Dateien, jede
Zahl mit Fundstelle.

## (b) Feste Schritte, Werkzeuge, Modell/Aufwand

1. Datenquelle(n) benennen (Dateipfad, Stand/Datum).
2. Auswertung bauen — jede Kennzahl mit Fundstelle (Datei + Zeile/Feld).
3. Keine geschätzte Zahl ohne Kennzeichnung „angenommen"/„geschätzt".
4. Beträge über `betragText(usd)`, Daten/Zeiten in absoluter Form (kein
   „gestern"/„letzte Woche" ohne Datum).

**Werkzeuge:** die jeweilige Datenquelle (z. B. `betrieb/*.json`,
Markenordner).
**Modell/Aufwand je Lauf:** Sonnet, low.

## (c) Abnahme-Checkliste

```bash
verfahren/Datenauswertung/pruefen.sh <auswertung.md>   # 0 = ok, 1 = Fehlmuster
```
Prüft: Datei vorhanden; enthält Abschnitt „Quelle"/„Fundstelle"; jede Zahl
mit „%"/„USD"/„Stk." hat mindestens eine Fundstellen-Angabe im selben
Absatz oder eine Kennzeichnung „angenommen"/„geschätzt" (einfache
Näherung: Wort „Fundstelle" oder „Quelle" kommt mindestens einmal je 10
Zeilen mit Zahl vor).

## (d) Fehler und Korrekturen

(noch keine — frisch gebaut)

## (e) Abgleich Fähigkeitsregister

Neu, kein Vorgänger — siehe `faehigkeiten/FAEHIGKEITSREGISTER.md`.

## (f) Kosten je Lauf

0 USD (reine Dateiauswertung, kein Anbieteraufruf).

## Grenzen

Keine erfundenen oder ungekennzeichnet geschätzten Zahlen. Keine
Weitergabe an Dritte ohne Freigabe.
