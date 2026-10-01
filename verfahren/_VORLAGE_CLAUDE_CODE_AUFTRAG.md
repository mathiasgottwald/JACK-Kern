# Vorlage: Claude-Code-Auftrag (Auftrag 47.1, Aufgaben 3, 7, 9, 11) — F-97

Jeder Auftrag an ein Claude-Code-Terminal trägt diese vier Blöcke. Fehlt einer, gilt der Auftrag als unvollständig (Rückfrage als FRAGE-Datei).

## 1. Plan zuerst (Aufgabe 3)
- Das Terminal beginnt im Planungsschritt (`--permission-mode plan` bzw. Plan-Abschnitt vor jeder Änderung): Ziel, Dateiliste (Regel 22b), Reihenfolge, Rückweg.
- Ein zweiter Prüfer liest den Plan gegen Auftrag und Grenzen (bei Risikoschritt: anderer Anbieter, Punkt 4).
- Erst danach Umsetzung. Rückfrage an den Patron nur bei echter Entscheidung, gesammelt (nicht stoppend).

## 2. Fertig-Kriterium als Befehl (Aufgabe 9)
```
FERTIG-BEFEHL:  <ein Befehl, der bei „hat geklappt“ mit Exit-Code 0 endet>   (Test, Prüfskript, curl-Statuscheck, alle_tests.py --muster …)
```
Dieser Befehl ist der erste Prüfer — vor jedem Prüfer-Agenten. Er kostet 0 Tokens und schmeichelt nicht.
Schleifen (`/loop`) nur mit Deckel: höchstens N Durchläufe, Bericht nach jedem fünften, Abbruch bei Exit 0. Warten auf Ereignisse per Hintergrundskript (`bin/postfach_schleife.sh`), nicht per Prompt im Takt.

## 3. Prüfschleife (Aufgabe 7)
Selbstprüfung (Tests, Browser mit Schreibsperre, Befehl aus 2) → Prüfer-Agent (Tor 1/Tor 2) → bei Livegang 37.1.

## 4. Risikoschritt? (Aufgabe 11)
Geld, Recht, Sicherheit, Livegang, Architektur, Löschen/Migration → Kreuzprüfung durch den anderen Anbieter:
`python3 -c "import jack_kreuzpruefung as k; print(k.pruefen(ROOT, '<vorgang>', 'claude', open('plan.md').read(), art='plan'))"`
Höchstens 2 Runden, danach entscheidet der Patron. Playbook: `verfahren/Kreuzpruefung.md`.

## Vor dem ersten Schreiben (Aufgaben 1, 2)
```
bin/arbeitskopie.sh <repo> <kanal>              # eigene Kopie außerhalb iCloud (nur Repo-Arbeit)
bin/sperrliste.py anmelden <kanal> <datei> …    # Exit 3 = eine andere Sitzung hält die Datei → nicht anfassen
… arbeiten …
bin/sperrliste.py freigeben <kanal>
```
