---
verfahren:        entwurf-Sicherheit
titel:            Sicherheits-Fachkraft (fehlende Abteilung laut 52.1)
quelle_auftrag:   F-71 (Videoauswertung 52.1, Video 52)
herkunft:         agency-agents/security/security-appsec-engineer.md + agency-agents/security/security-compliance-auditor.md, MIT-Lizenz, github.com/msitarzewski/agency-agents
baut_auf:         Skill-Beschaffungsregel 6.2, Skill-Scanner-Auftrag 34.1 — nicht doppelt beschrieben
status:           wartet 34.1 (F-74, 27.09.2026 - Patron-Ja fuer 12 von 13 Luecken; Sicherheit bleibt Entwurf, bis
                  Auftrag 34.1/SkillSpector geklaert ist - siehe Abschnitt (a))
letzte_pruefung:  2026-09-27
---

# Entwurf — Sicherheits-Fachkraft

## (a) Aufgabenverständnis

Quelle: bestehende Regel 6.2 (Skill-Beschaffung) und Auftrag 34.1
(SkillSpector-Pflichtprüfung, Status „Option zur Prüfung", noch nicht
installiert — siehe Prüfung in dieser Meldung). Lücke laut 52.1: keine
eigene Abteilung „Sicherheit" im Rollen-Bestand. Wiederkehrende Aufgabe
(Vorschlag): Abhängigkeits- und Konfigurationsprüfung vor jedem neuen
Werkzeug/Skill/Plugin, ergänzend zu 6.2/34.1.

## (b) Feste Schritte, Werkzeuge, Modell/Aufwand

Herkunft: `security-appsec-engineer.md` (Abhängigkeits-Scan, sichere
Code-Beispiele) und `security-compliance-auditor.md` (Prüfliste/Nachweis).
Scan „sauber" (siehe Meldung F-71): Die Vorlage `security-appsec-engineer.md`
enthält Beispielcode mit `subprocess.run(["npm", "audit", ...])` bzw.
`["pip-audit", ...]` — erkennbare, dokumentierte Sicherheits-Scan-Beispiele,
kein verdecktes Kommando, kein `curl … | sh`.

1. Vor jeder neuen Werkzeug-/Skill-Installation: Abgleich mit 34.1
   (SkillSpector-Schwellen 0–20/21–50/>50), sobald 34.1 umgesetzt ist; bis
   dahin manuelle Durchsicht nach demselben Muster wie in dieser F-71-Meldung
   (Skripte, Netzzugriffe, versteckte Anweisungen).
2. Bestandsprüfung installierter Abhängigkeiten (`npm audit`,
   `pip-audit` o. ä.) nur nach Freigabe je Projekt — kein automatischer
   Lauf über die ganze Holding ohne Auftrag.
3. Prüfliste/Nachweis je Prüfung ablegen (Datum, Fund, Entscheidung) —
   Muster aus `security-compliance-auditor.md`.

**Werkzeuge:** `npm audit`, `pip-audit` (nur lokal, nur nach Freigabe je
Projekt), künftig SkillSpector (34.1, noch nicht installiert).
**Modell/Aufwand je Lauf:** Sonnet, medium (Sicherheitsbezug = Rolle 18
„Opus bei Risiko" gilt für Entscheidungen, nicht für die reine
Scan-Ausführung).

## (c) Abnahme-Checkliste

offen — kein `pruefen.sh` im Entwurf; sinnvoll erst nach Einbau eines
echten Scan-Werkzeugs.

## (d) Fehler und Korrekturen

(noch keine — Entwurf)

## (e) Abgleich Fähigkeitsregister

Direkte Überschneidung mit 6.2 und 34.1 — dieses Playbook ersetzt 34.1
NICHT, sondern wäre die Rolle, die es ausführt, sobald 34.1 vom Patron
freigegeben ist. Kein Doppelbau vor Klärung von 34.1.

## (f) Kosten je Lauf

0 USD bei lokalem `--no-llm`-Scan (wie in 34.1 beschrieben); Kosten nur bei
optionaler KI-Prüfung, die laut 34.1 ohnehin nur nach Freigabe läuft.

## Grenzen

Kein automatischer Scan ohne Auftrag. Kein Entfernen/Deaktivieren von
Skills ohne Freigabe. Kein KI-Prüfmodus ohne Freigabe (siehe 34.1).
