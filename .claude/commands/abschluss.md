---
description: Abschluss eines JACK-Auftrags — Sicherung prüfen, Tests, Meldung, Auftrag ablegen (Auftrag 47.1 Aufgabe 6)
---
Schließe den aktuellen Postfach-Auftrag ab, genau in dieser Reihenfolge:
1. Sicherungen: Für jede geänderte Datei existiert `<datei>.vor_<Nr>`. Fehlt eine, erst anlegen (nichts überschreiben ohne Sicherung).
2. Fertig-Befehl des Auftrags ausführen (`FERTIG-BEFEHL`), dazu `python3 bin/alle_tests.py --muster <Nr-Teil>`; rote Tests nennen, nicht verschweigen.
3. Bei Risikoschritt: Kreuzprüfung nach `verfahren/Kreuzpruefung.md`.
4. Meldung nach `abnahme/pm_eingang/<Nr>_MELDUNG.md`: erste Zeile = die im Auftrag verlangte Ja/Nein-Zeile, dann 2–4 Gründe, dann Belege, dann Offenes.
5. Auftrag nach `auftraege/pm_ausgang/erledigt/` verschieben, Sperrliste freigeben (`bin/sperrliste.py freigeben <kanal>`).
6. Kanal prüfen; leer → `bash bin/postfach_schleife.sh <kanal>` im Hintergrund starten.
