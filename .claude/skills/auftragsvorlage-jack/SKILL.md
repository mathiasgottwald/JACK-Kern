---
name: auftragsvorlage-jack
description: Erzeugt einen JACK-Postfach-Auftrag im PM-Schema (Datei für auftraege/pm_ausgang/kern/ oder konten/). Verwenden, wenn ein Auftrag an JACK-Kern oder an den Konten-Chat geschrieben werden soll.
---

# Auftragsvorlage JACK (PM-Schema, F-24)

Ein Auftrag ist **eine** Datei, ein geschlossener Block. Aufgabe und Prüfpunkte stehen zusammen. Die letzte Zeile sagt, wohin die Meldung geht.

**Ablage:** `00_Marken/JACK/auftraege/pm_ausgang/<kanal>/F-<NN>_<kurzname>.md`, Kanal `kern` (Terminal JACK-Kern) oder `konten` (Browser/Konten).
**Nummer:** die nächste freie F-Nummer. Vorher in `kern/`, `konten/` und `erledigt/` nachsehen.

## Aufbau (genau diese Reihenfolge)

```
AUFTRAG F-<NN> — <TITEL IN GROSSBUCHSTABEN> — <Kostenrahmen, z. B. 0 USD oder Rahmen 1,00 USD>
Modell: <Haiku|Sonnet|Opus>, Aufwand <low|medium|high>. <Reihenfolge, z. B. "Nach F-21, vor F-23.">
Kontext: <Beleg-Pfade und Stand; nur Geprüftes als Fakt, Annahmen kennzeichnen>

Pflichtpunkte:
P01 <ein Satz, prüfbar, mit Pfad oder Zahl>
P02 …
(Abnahme, falls bezahlt: "GENAU EIN bezahlter Lauf, Rahmen <x> USD, Tiefe <…>; kein zweiter Anlauf.")

Regeln: Deutsch, minimal-invasiv, Sicherung vor jeder Dateiänderung, nichts löschen/verschieben, kein Echtversand,
keine neuen kostenpflichtigen Dienste, Neustart-Regel aus README_PM_POSTFACH.md, Suite ohne neue rote. Annahmen kennzeichnen.
Meldung abnahme/pm_eingang/F-<NN>_MELDUNG.md: <was sie enthalten muss>. Danach nach erledigt/.
```

## Prüfen vor dem Ablegen
1. Modell **und** Aufwand angegeben (A6b).
2. Jeder Pflichtpunkt ist einzeln prüfbar; kein Punkt verlangt „alles“.
3. Kosten: Rahmen in USD, bezahlte Läufe gezählt; Unterschrift und Geldtransfer nie ohne „freigegeben“ des Patrons.
4. Außenwirkung (Versand, Veröffentlichung, Konten) nur mit ausdrücklicher Freigabe im Auftrag.
5. Letzte Zeile: Meldungspfad und „Danach nach erledigt/“.
