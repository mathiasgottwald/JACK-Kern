---
verfahren:        47.1-11
titel:            Anbieterübergreifende Kreuzprüfung bei Risikoschritten
quelle_auftrag:   02_Dokumente/2026-09-16_Videoauswertung.md, Auftrag 47.1, Aufgabe 11 (Video 62); umgesetzt F-97
baut_auf:         Aufgabe 9 (Fertig-Kriterium als Befehl), codex_bruecke.py
status:           gebaut, Attrappentest grün, Codex vorhanden und angemeldet; Messtest offen (siehe unten)
letzte_pruefung:  2026-09-30
---

# 47.1-11 — Kreuzprüfung bei Risikoschritten

Standard-Playbook nach `_VORLAGE_PLAYBOOK.md`. Grundsatz: Routine prüft der Exit-Code-Befehl bzw. derselbe Anbieter; nur bei
**Risikoschritten** prüft ein ANDERER Anbieter (Claude baut → Codex prüft; Codex baut → Claude prüft). Höchstens **2 Runden**, danach entscheidet der Patron.

## (a) Aufgabenverständnis
Quelle: Patron-Entscheid 30.09.2026 (Auftrag 47.1 Aufgabe 11). Risikoschritt = Geld, Recht, Sicherheit, Livegang, Architektur, Löschen/Migration.

## (b) Feste Schritte, Werkzeuge, Modell/Aufwand
**Einstiegsfunktion:** `jack_kreuzpruefung.pruefen(root, vorgang, bauer, gegenstand, art="plan"|"ergebnis")`
1. `risikoschritt(text)` entscheidet: kein Risiko → „übersprungen“ (0 Kosten, Exit-Code-Befehl genügt).
2. Bauer Claude → `codex_bruecke.review` (nur lesend, Sandbox read-only); Bauer Codex → Claude (`modell_router`, günstigste Fachkraft-Stufe).
3. Ergebnis + Kosten in `betrieb/kreuzpruefung.jsonl` (Kosten je Lauf zusätzlich in `jack_kosten`).
4. Runde 2 nur nach Nachbesserung; Runde 3 gibt es nicht → `an_patron`.
5. Fable nur zur Endkontrolle (Regel 18), nie in dieser Schleife.

Prompt-Vorlage (wird von der Funktion gelesen — Änderungen nur hier):

<!--PROMPT-->
Du bist der unabhängige Zweitprüfer. Du hast diesen Schritt NICHT gebaut und sollst ihn kritisch prüfen.
Art der Prüfung: {art} (Plan vor der Umsetzung oder Ergebnis nach der Umsetzung).
Risikobereich: {bereiche}.
Prüfe ausschließlich den folgenden Text. Führe nichts aus, ändere nichts, sende nichts.
1. Nenne die drei wichtigsten Risiken oder Fehler, konkret mit Stelle.
2. Fehlt eine Absicherung (Sicherung vor Änderung, Rückweg, Freigabe des Patrons, Test)? Welche?
3. Widerspricht etwas den Hausregeln: nichts löschen, kein Versand ohne Freigabe, kein Geldtransfer, Secrets nie in Git?
4. Gib zum Schluss genau eine Zeile: URTEIL: OK oder URTEIL: NACHBESSERN oder URTEIL: STOPP.
Antworte auf Deutsch, höchstens 200 Wörter. Keine Schmeichelei; wenn alles stimmt, sag das kurz.

TEXT:
{gegenstand}
<!--/PROMPT-->

## (c) Abnahme-Checkliste (als Befehl)
`python3 abnahme/F-97/test_f97.py` → Exit 0 (Risikoerkennung, Rundendeckel 2, Attrappe beider Richtungen, kein Aufruf ohne Risiko).

## (d) Fehler und Korrekturen
- 30.09.2026: Codex-CLI liegt nicht am Standardort der Brücke (`/Applications/ChatGPT.app/Contents/Resources/codex` gibt es nicht) → `codex_pfad()` findet sie (Konfig, Umgebung, PATH, vorhandenes npm-Paket).

## (e) Abgleich Fähigkeitsregister
Neu, keine Doppelung: `codex_bruecke.py` bleibt der einzige Codex-Zugang; `jack_pruefer*` prüft weiter nach Tor 2 innerhalb desselben Anbieters.

## Messtest (offen)
10 echte Risikoschritte, gefundene echte Fehler je Euro gegen gleiche-Anbieter-Prüfung. Standard erst bei belegtem Mehrwert. Stand: siehe `abnahme/pm_eingang/F-97_MELDUNG.md`.
