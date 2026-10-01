---
verfahren:        Auslieferungsvorbereitung
titel:            Auslieferungsvorbereitung (technik-fachkraft)
quelle_auftrag:   F-73 (nach F-70-Vorschlag, Patron 27.09. 17:00: weitermachen)
herkunft:         eigen (kein Fremdmaterial)
baut_auf:         agenten/50_Technik/technik-fachkraft.md — Rolle bleibt eigenstaendig; ueberschneidet sich NICHT
                  mit Auftrag 37.1 (Abnahmepruefung vor/nach Livegang) - dieses Playbook ist der TECHNISCHE
                  Vorbereitungsschritt davor (Tests gruen, Sicherungen vorhanden), 37.1 bleibt die inhaltliche Abnahme
status:           gebaut, Muster mit pruefen.sh belegt
letzte_pruefung:  2026-09-27
---

# Auslieferungsvorbereitung (technik-fachkraft)

## (a) Aufgabenverständnis

Quelle: F-70-Vorschlag, Zeile „technik-fachkraft". Wiederkehrende Aufgabe:
vor jeder Auslieferung/jedem Livegang technisch pruefen, dass Tests gruen
sind und Sicherungen vorhanden sind — getrennt von der inhaltlichen Abnahme
(bleibt bei Auftrag 37.1 / den Pruefer-Rollen).

## (b) Feste Schritte, Werkzeuge, Modell/Aufwand

1. Testsuite der betroffenen Aenderung laufen lassen (`unittest`), Ergebnis
   dokumentieren.
2. Sicherungskopie(n) pruefen: existiert `.vor_<Kennung>` fuer jede
   geaenderte Datei? (Regel 6, kein Ueberschreiben ohne Sicherung.)
3. Kein `git push`/keine Auslieferung, solange (1) oder (2) fehlschlaegt.
4. Ergebnis nach der F-69-Regel melden (Ergebnis zuerst).

**Werkzeuge:** `unittest`, Dateisystem-Pruefung auf `.vor_*`-Dateien.
**Modell/Aufwand je Lauf:** Sonnet, low.

## (c) Abnahme-Checkliste

```bash
verfahren/Auslieferungsvorbereitung/pruefen.sh <geaenderte_datei>   # 0 = ok, 1 = Fehlmuster
```
Prüft: eine `.vor_*`-Sicherung mit gleichem Namensstamm liegt im selben
Ordner wie die geänderte Datei.

## (d) Fehler und Korrekturen

(noch keine — frisch gebaut)

## (e) Abgleich Fähigkeitsregister

Überschneidet sich NICHT mit Auftrag 37.1 (inhaltliche Abnahme) oder den
Pruefer-Rollen — dieses Playbook ist ausschliesslich der technische
Vorbereitungsschritt (Tests, Sicherungen). Siehe
`faehigkeiten/FAEHIGKEITSREGISTER.md`.

## (f) Kosten je Lauf

0 USD (lokale Testausführung und Dateipruefung, kein Anbieteraufruf).

## Grenzen

Keine inhaltliche Freigabeentscheidung. Keine Auslieferung ohne gruene
Tests und vorhandene Sicherung.
