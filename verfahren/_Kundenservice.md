---
verfahren:        entwurf-Kundenservice
titel:            Kundenservice-Fachkraft (fehlende Rolle laut 52.1)
quelle_auftrag:   F-71 (Videoauswertung 52.1, Video 52)
herkunft:         agency-agents/support/support-support-responder.md, MIT-Lizenz, github.com/msitarzewski/agency-agents
scan_befund:     sauber (F-71, 27.09.2026 - Skripte/Netzzugriffe/versteckte Anweisungen geprueft)
baut_auf:         vertrieb-fachkraft.md — nicht doppelt beschrieben
status:           aktiv (F-74, 27.09.2026 - Patron-Ja fuer alle 13 Luecken, YouTube ausdruecklich JA)
letzte_pruefung:  2026-09-27
---

# Entwurf — Kundenservice-Fachkraft

## (a) Aufgabenverständnis

Quelle: keine eigene Regel — offen. Lücke laut 52.1: keine eigene
Kundenservice-Rolle. Wiederkehrende Aufgabe (Vorschlag): Antwortentwürfe
auf Kundenanfragen je Marke, im Ton der Markenstimme — Antwort geht immer
erst als Entwurf an den Patron oder eine freigegebene Prüfstelle, nie
direkt automatisch an den Kunden.

## (b) Feste Schritte, Werkzeuge, Modell/Aufwand

Herkunft: `support-support-responder.md`. Scan „sauber" (siehe Meldung
F-71): 584 Zeilen, keine Skripte/Netzzugriffe/versteckten Anweisungen.

1. Kundenanfrage lesen, Antwortentwurf nach Markenstimme und PLHH-Leitbild
   bauen.
2. Keine erfundenen Zusagen (Preise, Liefertermine, Garantien) ohne Beleg
   aus den Holding-Dateien.
3. Entwurf geht an eine Freigabestelle (Patron oder benannte Vertretung),
   nie automatischer Direktversand.

**Werkzeuge:** `jack_postfaecher.py` (Versandpunkt, falls die Antwort
später per Mail geht — nur nach Freigabe), Markenstimme-Vorgaben.
**Modell/Aufwand je Lauf:** Sonnet, low.

## (c) Abnahme-Checkliste

```bash
verfahren/Kundenservice/pruefen.sh <entwurf.md>   # 0 = ok, 1 = Fehlmuster
```
Prüft: Datei vorhanden; enthält keine Formulierung, die einen bereits
erfolgten Versand behauptet (Wörter „gesendet"/„beantwortet"/„verschickt"
ohne „Entwurf" im selben Absatz) — F-74, Punkt 3: „nur Entwürfe, kein
Direktversand".

## (d) Fehler und Korrekturen

(noch keine — Entwurf)

## (e) Abgleich Fähigkeitsregister

`jack_postfaecher.py` hat bereits einen einzigen Versandpunkt (`senden()`)
mit Testpflicht — dieses Playbook nutzt ihn, baut keinen zweiten Versandweg.

## (f) Kosten je Lauf

0 USD für Textentwurf; Versandkosten (falls E-Mail) nach bestehender
Kostenregel für `jack_postfaecher.py`.

## Grenzen

Keine automatische Antwort ohne Freigabe. Keine erfundenen Zusagen. Kein
zweiter Versandweg neben `jack_postfaecher.senden()`.
