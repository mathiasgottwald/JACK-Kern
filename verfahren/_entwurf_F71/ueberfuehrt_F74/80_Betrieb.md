---
verfahren:        entwurf-80_Betrieb
titel:            Betriebs-Fachkraft (Abteilung 80_Betrieb, derzeit leer)
quelle_auftrag:   F-71 (Videoauswertung 52.1, Video 52)
herkunft:         agency-agents/project-management/project-management-studio-operations.md + agency-agents/support/support-infrastructure-maintainer.md, MIT-Lizenz, github.com/msitarzewski/agency-agents
baut_auf:         keins (neue Rolle, Lücke laut 52.1)
status:           entwurf — NICHT aktiv, NICHT in agenten/
letzte_pruefung:  2026-09-27
---

# Entwurf — Betriebs-Fachkraft (80_Betrieb)

## (a) Aufgabenverständnis

Quelle: keine — offen. Lücke laut 52.1: `80_Betrieb` ist eine leere
Abteilung im Ordnerschema. Wiederkehrende Aufgabe (Vorschlag): laufender
Betrieb der JACK-Dienste beobachten (Herzschlag, Netzwächter, Neustarts)
und Tagesablauf/Kalenderfragen für die Holding bündeln — **nicht** die
technische Dienstkontrolle selbst, die bleibt bei `bin/jack_netzwaechter.py`
(kern-Zuständigkeit).

## (b) Feste Schritte, Werkzeuge, Modell/Aufwand

Herkunft: `project-management-studio-operations.md` (Tagesablauf, Ressourcen,
Terminplanung) und `support-infrastructure-maintainer.md` (nur der
Beobachtungsteil — **nicht** die Terraform-/AWS-Beispiele daraus, die
passen nicht zur lokalen Holding-Infrastruktur). Scan „sauber" (siehe
Meldung F-71): Die Vorlage `support-infrastructure-maintainer.md` enthält
Beispiel-`curl`-Aufrufe an einen Slack-Webhook und ein Terraform-`user_data`-
Skript — beides erkennbarer, dokumentierter Beispielcode zu Cloud-
Infrastruktur, kein verstecktes Kommando; für JACK ohnehin nicht 1:1
übernehmbar (kein AWS/Terraform-Bestand).

1. Täglicher Betriebsüberblick aus bestehenden Dateien
   (`betrieb/neustarts.log`, `betrieb/herzschlag/`, `betrieb/netz.log`) —
   nur lesen, keine neue Überwachungslogik (die hat `jack_netzwaechter.py`
   bereits, kein Doppelbau).
2. Kurzbericht „Was lief heute, was stand" für den Patron — nach der
   Schreibregel 17a (Ergebnis zuerst).
3. Terminliche Bündelung wiederkehrender Betriebsaufgaben (z. B. monatliche
   Wiederholungs-Scans aus 34.1), keine eigenständige Ausführung technischer
   Neustarts (bleibt `bin/neustart_sicher.sh`).

**Werkzeuge:** bestehende Log-/Herzschlag-Dateien, `jack_netzwaechter.py`
(nur lesend).
**Modell/Aufwand je Lauf:** Haiku–Sonnet, low (reine Zusammenfassung
bestehender Protokolle).

## (c) Abnahme-Checkliste

offen — kein `pruefen.sh` im Entwurf.

## (d) Fehler und Korrekturen

(noch keine — Entwurf)

## (e) Abgleich Fähigkeitsregister

Überschneidet sich mit `jack_netzwaechter.py`/F-28/F-58: Doppelbau
ausdrücklich ausgeschlossen — dieses Playbook wäre nur ein Berichtsschritt
oben drauf, keine neue Überwachung.

## (f) Kosten je Lauf

Geschätzt 0 USD (reine Log-Auswertung, kein Anbieteraufruf).

## Grenzen

Keine eigene Dienstkontrolle, keine Neustarts, keine Änderung an
`jack_netzwaechter.py`/`neustart_sicher.sh`. Nur Bericht und Terminbündelung.
