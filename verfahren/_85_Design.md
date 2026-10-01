---
verfahren:        entwurf-85_Design
titel:            Design-Fachkraft (Abteilung 85_Design, derzeit leer)
quelle_auftrag:   F-71 (Videoauswertung 52.1, Video 52)
herkunft:         agency-agents/design/design-brand-guardian.md + agency-agents/design/design-ux-architect.md, MIT-Lizenz, github.com/msitarzewski/agency-agents
scan_befund:     sauber (F-71, 27.09.2026 - Skripte/Netzzugriffe/versteckte Anweisungen geprueft)
baut_auf:         Regel 20 (Markenmaterial, echtes Logo/CI) — nicht doppelt beschrieben
status:           aktiv (F-74, 27.09.2026 - Patron-Ja fuer alle 13 Luecken, YouTube ausdruecklich JA)
letzte_pruefung:  2026-09-27
---

# Entwurf — Design-Fachkraft (85_Design)

## (a) Aufgabenverständnis

Quelle: Regel 20 der Holding (echtes Markenmaterial, keine erfundene CI,
Logo/Text nie vom Erzeugungsmodell rendern). Lücke laut 52.1: `85_Design`
ist eine leere Abteilung. Wiederkehrende Aufgabe (Vorschlag): vor jeder
Veröffentlichung mit Außenwirkung prüfen, ob echtes Markenmaterial verwendet
wurde (Brand-Guardian-Rolle), und Oberflächen-/UX-Entwürfe gegen die
Hausregeln K1–K8 prüfen.

## (b) Feste Schritte, Werkzeuge, Modell/Aufwand

Herkunft: `design-brand-guardian.md` (CI-Konsistenzprüfung) und
`design-ux-architect.md` (Oberflächenstruktur). Scan „sauber" (siehe
Meldung F-71) — keine Skripte, Netzzugriffe oder versteckten Anweisungen
gefunden.

1. Vor jedem Ergebnis mit Außenwirkung: Markenmaterial suchen (Regel 20),
   Logo/CI-Fundstelle im Bericht nennen.
2. Prüfen, ob Text/Logo im Ergebnis vom Erzeugungsmodell gerendert wurde
   (verboten) oder erst in der Nachbearbeitung eingesetzt (Pflicht) —
   technischer Beleg, nicht nur Behauptung.
3. Bei Oberflächenänderungen (`index.html` u. ä.): Hausregeln K1–K8 (Regel
   21) als Checkliste abhaken, „Kein Weiß auf Gold", Beträge über
   `betragText(usd)`.

**Werkzeuge:** Markenordner `00_Marken/<MARKE>/`, `betragText()`,
bestehende K1–K8-Regeln (`regeln/oberflaeche.md`).
**Modell/Aufwand je Lauf:** Sonnet, low–medium (Prüf-/Checklisten-Aufgabe,
kein eigener Bildaufruf).

## (c) Abnahme-Checkliste

```bash
verfahren/85_Design/pruefen.sh <pruefbericht.md>   # 0 = ok, 1 = Fehlmuster
```
Prüft: Datei vorhanden; nennt eine Fundstelle/Quelle für das verwendete
Markenmaterial; kein Hinweis auf erfundenes Logo oder unbelegte neue Farbe.

## (d) Fehler und Korrekturen

(noch keine — Entwurf)

## (e) Abgleich Fähigkeitsregister

Überschneidet sich mit Regel 20 (Markenmaterial) und Regel 21 (Oberfläche,
K1–K8) — dieses Playbook würde diese Regeln nur als wiederkehrenden
Prüfschritt bündeln, keine neue Prüflogik erfinden.

## (f) Kosten je Lauf

Geschätzt 0 USD (Prüf-/Checklistenaufgabe ohne Anbieteraufruf); Kosten
entstehen erst, wenn diese Rolle selbst Bildmaterial erzeugen lässt — das
ist NICHT Teil dieses Entwurfs (Bilderzeugung bleibt bei den bestehenden
Verfahren 7.1/8.1/11.1 und Higgsfield-Anbindung).

## Grenzen

Kein eigenes Logo/keine eigene CI erfinden. Kein Rendern von Text/Logo durch
das Erzeugungsmodell. Nichts veröffentlichen ohne Freigabe des Patrons.
