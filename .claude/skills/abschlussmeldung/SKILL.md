---
name: abschlussmeldung
description: Schreibt die Abschlussmeldung eines JACK-Postfach-Auftrags nach abnahme/pm_eingang/<AUFTRAG>_MELDUNG.md mit allen Pflichtfeldern. Verwenden, sobald ein Auftrag aus auftraege/pm_ausgang/ fertig oder blockiert ist.
---

# Abschlussmeldung (F-24)

**Datei:** `00_Marken/JACK/abnahme/pm_eingang/<AUFTRAG>_MELDUNG.md`, zum Beispiel `F-21_MELDUNG.md`. Danach den Auftrag nach `auftraege/pm_ausgang/erledigt/` verschieben (`mv -n`). Ist er nur teilweise fertig (etwa wegen einer fehlenden Freigabe), bleibt er in `kern/`, und die Meldung sagt das.

## Pflichtfelder (in dieser Reihenfolge)
1. **Kopfzeile:** `# F-<NN> — <Titel>: MELDUNG (<TT.MM.JJJJ>, <HH:MM>)`. Die Uhrzeit vorher mit `date '+%H:%M'` holen, nie schätzen.
2. **Ergebnis in einem Satz** zuerst: fertig, abgenommen oder blockiert, dazu Kosten.
3. **Modell und Aufwand** je Teil, mit Abweichung vom Auftrag (A6b).
4. **Status je Punkt** (P01 … oder 1., 2., …): Statuswort aus `geprüft · umgesetzt · veröffentlicht · persönlich abgenommen · offen · blockiert`; Kennzeichen `angenommen` oder `vermutet`, wo nichts geprüft ist.
5. **Zahlen** mit Quelle: Tests (Dateien, Tests, rote), Suite vorher/nachher, Messwerte. Keine Zahl ohne Messung.
6. **Pfade:** Ergebnisdateien, Bericht, Belege, Sicherungen (`_Sicherung_<Datum>_<Auftrag>`).
7. **Kosten:** betragText-Form („14 Cent“, „1,38 USD“), bezahlte Läufe mit Nummer, Tor-2-Urteil. Sonst ausdrücklich 0 USD.
8. **Dienst:** Neustart ja/nein, mit PID alt → neu und Eintrag in `betrieb/neustarts.log`.
9. **Offene Punkte und Fragen**, höchstens 3 Fragen, je mit Empfehlung.

## Regeln
- Ehrlich: Rot bleibt rot und wird benannt. Eine fremde Änderung wird gemeldet, nicht „behoben“.
- Nichts als erledigt melden, was nicht belegt ist. Wirkung ohne Daten heißt „noch nicht belegt“.
- Kurz: Ergebnis, dann Einzelheiten, dann Fragen.
