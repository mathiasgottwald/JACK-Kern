---
verfahren:        <Nummer, z.B. 7.1>
titel:            <Kurztitel>
quelle_auftrag:   <Datei/Abschnitt, aus dem das Verfahren stammt>
baut_auf:         <andere Verfahrensnummer oder "keins (Grundverfahren)">
status:           <Kurzstand: gebaut/geprüft/gestoppt vor Aufruf/offen>
letzte_pruefung:  <Datum>
---

# <Nummer> — <Titel>

Standard-Playbook nach `_VORLAGE_PLAYBOOK.md` (F-70, 27.09.2026). Grundsatz:
wenige Agenten, aber ein Playbook je wiederkehrender Aufgabe — kein neuer
Spezial-Agent ohne Patron-Ja (Anthropic „Don't Build Agents, Build Skills
Instead", 11/2025).

## (a) Aufgabenverständnis

Quelle: <Patron-Interview-Datum ODER bestehende Regel/Datei — wenn keins von
beidem vorliegt: „offen — kein Interview, keine belegte Regel">.

<1–3 Sätze: was die Aufgabe ist, wiederkehrend woraus/wofür.>

## (b) Feste Schritte, Werkzeuge, Modell/Aufwand

**Einstiegsfunktion:** `<modul.funktion(parameter...)>`

1. <Schritt 1>
2. <Schritt 2>
3. ...

**Werkzeuge:** <Module/Skripte/Dienste, die dieser Schritt aufruft>
**Modell/Aufwand je Lauf:** <z. B. Sonnet, low — oder "kein Modellaufruf, reine Prüflogik">

## (c) Abnahme-Checkliste (Befehl mit Exit-Code, wo möglich)

```bash
verfahren/<nummer>/pruefen.sh   # 0 = ok, ungleich 0 = Befund mit Text auf stderr
```

Wenn kein Skript möglich ist: Checkliste als nummerierte Punkte, jeder mit
belegbarem Testfall.

## (d) Fehler und Korrekturen

<Jeder in diesem Verfahren aufgetretene Fehler wird HIER behoben, nicht nur im
Einzelauftrag. Format je Eintrag: Datum, Fehler, Korrektur, Beleg (Testfall/PM-Nr.).
Leer lassen, solange keiner aufgetreten ist — nicht mit "keine" auffüllen.>

## (e) Abgleich Fähigkeitsregister (vor dem Bau)

<Prüfung, ob eine bestehende Funktion/ein bestehendes Modul dasselbe schon
kann, mit Fundstelle — oder "offen, noch nicht abgeglichen".>

## (f) Kosten je Lauf

<USD/Cent je Lauf, Quelle der Zahl (z. B. `betrieb/<bereich>.json`), oder
"0 USD, reine Prüflogik ohne Anbieteraufruf".>

## Grenzen

<Was dieses Verfahren nie tut — unverändert aus dem Ursprungsverfahren, falls vorhanden.>
