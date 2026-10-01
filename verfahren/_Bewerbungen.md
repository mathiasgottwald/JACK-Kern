---
verfahren:        Bewerbungen (Standard 47.1, Aufgabe 10)
titel:            Bewerbungsablauf des Patrons — Suche, HR-Manager-Paket, Freigabe
quelle_auftrag:   00_Marken/JACK/auftraege/pm_ausgang/bewerbungen/MANDAT_BEWERBUNGEN.md
baut_auf:         keins (Grundverfahren) — führt B-1, B-2 und den HR-Manager-Standard zusammen
status:           gebaut, pruefen.sh real an vorhandenem Paket (EpicFusion) durchgelaufen
letzte_pruefung:  2026-09-30
---

# Bewerbungen — Suche, Paket, Freigabe

Standard-Playbook nach `_VORLAGE_PLAYBOOK.md` (F-70, 27.09.2026). Fasst den
bestehenden Bewerbungsablauf zusammen (B-1 Tagessuche, B-2 Auftrag/Ausschreibung,
HR-Manager-Standard aus `abnahme/pm_eingang/BEWERBUNGEN_ANSAGE_PM_2026-09-27.md`)
— **ersetzt nichts**, nur Zusammenführung + Abnahme-Checkliste.

## (a) Aufgabenverständnis

Quelle: `MANDAT_BEWERBUNGEN.md` (25.09.2026), Ansagen vom 27.09. (HR-Manager-Standard)
und 28.09. (Suchfeld-Erweiterung).

JACK ist der persönliche Bewerbungsmanager des Patrons: täglich Stellen/Aufträge/
Ausschreibungen suchen, je Treffer ein vollständiges Bewerbungspaket bauen
(Stellenanalyse, Unternehmensrecherche, Gehaltsrahmen, Differenzierung, Versand-/
Nachfassplan, PDF-Mappe), im Tracker führen — versendet wird **nie** ohne
Freigabekarte des Patrons.

## (b) Feste Schritte, Werkzeuge, Modell/Aufwand

**Einstiegsfunktion:** `bin/bewerbungen_tagessuche.py` (täglich 06:00, Cron) und
`bin/bewerbungen_suche_erweitert.py` (im Anschluss, selber Lauf).

1. **Tagessuche (B-1):** `bewerbungen_tagessuche.py` fragt die Jobbörse der
   Bundesagentur (v6-API) nach den Zielberufen aus `03_Zielberufe.md` ab,
   schreibt `04_Tagesliste_<Datum>.md` (Abschnitt „Anstellung") und
   `suche/<Datum>.json`. Dubletten gegen `05_suche_gesehen.json`.
2. **Erweiterte Suche (B-2):** `bewerbungen_suche_erweitert.py` ergänzt zwei
   Abschnitte in derselben Tagesliste — „Auftrag/Mandat" (freelancermap.de,
   automatisiert, robots.txt-konform) und „Ausschreibung" (Landingpage-
   Erreichbarkeit; die eigentlichen Vergabeportale — service.bund.de, Bayern-
   Vergabeportal/DTVP — sind per robots.txt oder JS-Oberfläche nicht
   automatisiert durchsuchbar, siehe Skript-Docstring; dafür **wöchentliche
   manuelle Prüfung** statt täglichem Skript).
3. **HR-Manager-Paket je Treffer** (kein Skript — Modellarbeit): eine
   `00_Analyse_<Firma>.md` mit fünf Pflichtabschnitten (siehe Checkliste unten)
   plus `Bewerbungsmappe/` mit Anschreiben, Lebenslauf, ggf. Zusatznachweisen
   als PDF, Ablage unter `10_Stellen/<Datum>_<Firma>_<Rolle>/`.
4. **Tracker:** `06_Tracker.md` je Stelle/Auftrag/Ausschreibung fortschreiben
   (Spalte „Art" seit M-9/B-2).
5. **Freigabe statt Versand:** nie direkt senden. Übergabe an PM CHECK als
   `abnahme/pm_eingang/UEBERGABE_BEWERBUNG_<Datum>_<Arbeitgeber>.md`
   (Empfänger, Betreff, Text, Anhänge) — Freigabekarte läuft dort über
   Testversand → Code → FREIGEBEN.

**Werkzeuge:** `bin/bewerbungen_tagessuche.py`, `bin/bewerbungen_suche_erweitert.py`,
`03_Zielberufe.md`, `00_PERSONENBILD.md`, `06_Tracker.md`.
**Modell/Aufwand je Lauf:** Tagessuche/erweiterte Suche selbst: **kein
Modellaufruf** (reine API-/HTML-Abfrage). HR-Manager-Paket je Treffer: **Sonnet,
medium** (MANDAT-Vorgabe). Einmalig Master-Lebenslauf/Anschreiben-Vorlage
(bereits erledigt, Phase 2): **Opus, high**.

## (c) Abnahme-Checkliste

```bash
verfahren/Bewerbungen/pruefen.sh <Paketordner>   # 0 = ok, 1 = Befund auf stderr
```

Prüft je Bewerbungspaket (`10_Stellen/<Datum>_<Firma>_<Rolle>/`): (1) eine
`00_Analyse_*.md` existiert, (2) sie enthält alle fünf Pflichtabschnitte
(Stellenanalyse, Unternehmensrecherche, Gehaltsrahmen, Differenzierung,
Versandweg/Nachfassplan), (3) ein `Bewerbungsmappe/`-Ordner existiert mit
mindestens einem Anschreiben- und einem Lebenslauf-PDF, (4) `06_Tracker.md`
führt einen Eintrag mit dem Paketordner-Pfad, (5) es liegt **keine**
`abnahme/pm_eingang/UEBERGABE_BEWERBUNG_*`-Datei für dieses Paket, die schon
„gesendet"/„versendet" vermerkt, ohne dass eine Freigabe protokolliert ist
(Versandsperren-Stichprobe). Jeder Fehlschlag → Exit 1, Text auf stderr.

## (d) Fehler und Korrekturen

30.09.2026 — Erstbau des Playbooks (B-3). Noch kein im Playbook selbst
aufgetretener Fehler zu dokumentieren (die 9 MASTERMIND-Befunde aus M-3/M-9
stehen in `abnahme/MASTERMIND/bewerbungen.md` und `bewerbungen_2.md`, nicht
hier — sie betreffen die Skripte, nicht das Playbook-Verfahren selbst).

## (e) Abgleich Fähigkeitsregister

offen — noch nicht gegen ein systemweites Fähigkeitsregister abgeglichen
(kein solches Register unter diesem Namen im JACK-Ordner gefunden, Stand
30.09.2026).

## (f) Kosten je Lauf

Tagessuche/erweiterte Suche: 0 USD (reine API-/HTML-Abfrage, kein
Modellaufruf). HR-Manager-Paket je Treffer: Sonnet medium, Größenordnung nach
MANDAT „Deckel" je Auftrag (aktuelle Aufträge: 1–3 USD). **Anmerkung zur
Auftragsangabe „Kostenstufe 24.1":** in `betrieb/kostenstufen.json` sind die
Stufen 0–3 benannt (lokal/günstige API/Standard/Premium), keine Stufe „24.1"
gefunden — als Annahme übernommen: gemeint ist die Modellwahlregel aus
MANDAT_BEWERBUNGEN.md („Modell und Aufwand"), nicht ein Eintrag in
`kostenstufen.json`. Bei Bedarf bitte die genaue Fundstelle von „24.1" nennen.

## Grenzen

Kein Versand, keine Kontoanlage auf Jobplattformen, keine Erfindungen im
Lebenslauf, Funktion des Patrons immer „Patron". Nichts wird ohne Freigabekarte
verschickt — auch nicht testweise an eine echte Adresse.
