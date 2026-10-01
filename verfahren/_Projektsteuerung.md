---
verfahren:        entwurf-Projektsteuerung
titel:            Projektsteuerungs-Fachkraft (fehlende Rolle laut 52.1)
quelle_auftrag:   F-71 (Videoauswertung 52.1, Video 52)
herkunft:         agency-agents/project-management/project-management-project-shepherd.md, MIT-Lizenz, github.com/msitarzewski/agency-agents
scan_befund:     sauber (F-71, 27.09.2026 - Skripte/Netzzugriffe/versteckte Anweisungen geprueft)
baut_auf:         PM-Postfach-System (auftraege/pm_ausgang/) — nicht doppelt beschrieben
status:           aktiv (F-74, 27.09.2026 - Patron-Ja fuer alle 13 Luecken, YouTube ausdruecklich JA)
letzte_pruefung:  2026-09-27
---

# Entwurf — Projektsteuerungs-Fachkraft

## (a) Aufgabenverständnis

Quelle: keine eigene Regel — offen, angelehnt an das bestehende
PM-Postfach-System (`auftraege/pm_ausgang/README_PM_POSTFACH.md`). Lücke
laut 52.1: keine eigene Rolle für Projektsteuerung über die reine
Postfach-Mechanik hinaus. Wiederkehrende Aufgabe (Vorschlag):
wochenweiser Überblick über offene Aufträge je Kanal (kern/sprache/
patronos/logos/ux/cashflow), Rückstände erkennen, dem Patron bündeln.

## (b) Feste Schritte, Werkzeuge, Modell/Aufwand

Herkunft: `project-management-project-shepherd.md`. Scan „sauber" (siehe
Meldung F-71): 193 Zeilen, keine Skripte/Netzzugriffe/versteckten
Anweisungen.

1. Bestand aus `auftraege/pm_ausgang/<kanal>/` und `erledigt/` lesen —
   nur lesend, keine eigene Auftragsvergabe (die bleibt beim PM CHECK).
2. Wochenüberblick: wie viele Aufträge offen/erledigt je Kanal, welche
   liegen ungewöhnlich lange (Bezug zu F-61/F-67 „steht_trotz_auftrag").
3. Bericht nach `abnahme/pm_eingang/` oder als Dashboard-Karte — keine
   Änderung an Aufträgen selbst.

**Werkzeuge:** `auftraege/pm_ausgang/`, `betrieb/neustarts.log`,
`betrieb/herzschlag/`.
**Modell/Aufwand je Lauf:** Haiku–Sonnet, low (reine Zusammenfassung
bestehender Dateien).

## (c) Abnahme-Checkliste

```bash
verfahren/Projektsteuerung/pruefen.sh <bericht.md>   # 0 = ok, 1 = Fehlmuster
```
Prüft: Datei vorhanden; enthält keine Behauptung, einen Auftrag geändert,
verschoben oder gelöscht zu haben — diese Rolle ist rein lesend/berichtend.

## (d) Fehler und Korrekturen

(noch keine — Entwurf)

## (e) Abgleich Fähigkeitsregister

Überschneidet sich mit dem bestehenden PM-Postfach-System und dem
Netzwächter (F-28/F-58/F-61) — dieses Playbook wäre nur ein zusätzlicher
Wochenbericht, keine neue Steuerungslogik.

## (f) Kosten je Lauf

0 USD (reine Dateiauswertung, kein Anbieteraufruf).

## Grenzen

Keine eigene Auftragsvergabe, keine Änderung an laufenden Aufträgen. Nur
Überblick und Bericht.
