---
verfahren:        entwurf-Test_QA
titel:            Test/QA-Fachkraft (fehlende Abteilung laut 52.1)
quelle_auftrag:   F-71 (Videoauswertung 52.1, Video 52)
herkunft:         agency-agents/testing/testing-test-automation-engineer.md + agency-agents/testing/testing-reality-checker.md, MIT-Lizenz, github.com/msitarzewski/agency-agents
scan_befund:     sauber (F-71, 27.09.2026 - Skripte/Netzzugriffe/versteckte Anweisungen geprueft)
baut_auf:         Abnahmeprüfung 37.1, Pruefer-Rollen (agenten/90_Pruefer/) — nicht doppelt beschrieben
status:           aktiv (F-74, 27.09.2026 - Patron-Ja fuer alle 13 Luecken, YouTube ausdruecklich JA)
letzte_pruefung:  2026-09-27
---

# Entwurf — Test/QA-Fachkraft

## (a) Aufgabenverständnis

Quelle: keine eigene Regel — offen, angelehnt an die bestehenden Rollen
`agenten/90_Pruefer/pruefer.md`/`abnahme-pruefer.md` und Auftrag 37.1
(Abnahmeprüfung vor/nach Livegang). Lücke laut 52.1: keine eigene
Abteilung „Test/QA". Wiederkehrende Aufgabe (Vorschlag): technischer
Testlauf (Testsuite grün, Regressionstest) als eigener Schritt, getrennt
von der inhaltlichen Abnahme der Pruefer-Rolle.

## (b) Feste Schritte, Werkzeuge, Modell/Aufwand

Herkunft: `testing-test-automation-engineer.md` (Testautomatisierung,
CI-Muster) und `testing-reality-checker.md` (Gegenprüfung „wurde wirklich
gebaut, was behauptet wird" — passt eng zur Hausregel „ehrlicher
Widerspruch ist Pflicht"). Scan „sauber" (siehe Meldung F-71): Beispiele
mit `npx playwright …` (CI-Pipeline-Muster) und Aufruf eines lokalen
`./qa-playwright-capture.sh` — beides erkennbarer, dokumentierter
Test-Beispielcode, keine versteckte Anweisung.

1. Vor jeder Abnahmemeldung: bestehende Testsuite laufen lassen (Python
   `unittest`, wie in `abnahme/*/test_*.py`), Ergebnis (grün/rot) im
   Bericht nennen — keine neue Testinfrastruktur nötig, die gibt es
   bereits je Auftrag.
2. Gegenprüfung „wurde wirklich gebaut, was behauptet wird" (reality-check):
   Datei-Existenz, Inhalt stichprobenartig gegen die Meldung prüfen, bevor
   sie an `abnahme/pm_eingang/` geht.
3. Keine eigene Abnahmeentscheidung — die bleibt bei `pruefer.md`/
   `abnahme-pruefer.md`; diese Rolle liefert nur den technischen Testbefund
   zu.

**Werkzeuge:** `unittest`, bestehende Testordner unter `abnahme/`.
**Modell/Aufwand je Lauf:** Sonnet, low (Testläufe ausführen und
zusammenfassen, keine neue Architekturentscheidung).

## (c) Abnahme-Checkliste

```bash
python3 -m unittest discover -s abnahme -p "test_*.py"   # 0 = alle Tests gruen
```

## (d) Fehler und Korrekturen

(noch keine — Entwurf)

## (e) Abgleich Fähigkeitsregister

Überschneidet sich mit `agenten/90_Pruefer/` und Auftrag 37.1 — diese Rolle
wäre nur der technische Testschritt VOR der inhaltlichen Abnahme, kein
Ersatz für die Pruefer-Rollen.

## (f) Kosten je Lauf

0 USD (lokale Testausführung, kein Anbieteraufruf).

## Grenzen

Keine eigene Freigabeentscheidung. Kein Livegang ohne die bestehende
Abnahmeprüfung (37.1, `pruefer.md`).
