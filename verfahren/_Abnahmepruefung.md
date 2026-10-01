---
verfahren:        Abnahmepruefung
titel:            Abnahmepruefung (pruefer + abnahme-pruefer, gemeinsames Playbook)
quelle_auftrag:   F-73 (nach F-70-Vorschlag, Patron 27.09. 17:00: weitermachen)
herkunft:         eigen (kein Fremdmaterial)
baut_auf:         agenten/90_Pruefer/pruefer.md, agenten/90_Pruefer/abnahme-pruefer.md — beide Rollen bleiben
                  eigenstaendig; Bezug zu Auftrag 37.1 (Abnahmepruefung vor/nach Livegang) und zum
                  Test/QA-Entwurf aus F-71 (liefert nur den technischen Testbefund zu, keine eigene Entscheidung)
status:           gebaut, Muster mit pruefen.sh belegt
letzte_pruefung:  2026-09-27
---

# Abnahmeprüfung (pruefer + abnahme-pruefer, gemeinsames Playbook)

## (a) Aufgabenverständnis

Quelle: F-70-Vorschlag, Zeilen „pruefer" und „abnahme-pruefer" — beide
Rollen wurden dort als überschneidend vorgeschlagen. Wiederkehrende
Aufgabe: unabhängige Abnahme vor jeder Freigabe/Meldung an den Patron —
**Kernregel, technisch erzwungen wo möglich: eine Rolle prüft nie ihre
eigene Arbeit.**

## (b) Feste Schritte, Werkzeuge, Modell/Aufwand

1. Prüfen, ob die Autoren-Rolle (aus dem Kopf der Meldung/Datei) mit der
   prüfenden Rolle identisch ist — wenn ja: ablehnen, andere Rolle
   anfordern.
2. Behauptungen gegen Belege prüfen (Fundstellen, Testergebnisse) — nie
   selbst neu schreiben, nur prüfen.
3. Ergebnis: „geprüft"/„angenommen"/„ungeprüft" je Aussage (wie
   recht-fachkraft, gleiche Dreiteilung).
4. Bezug zu Auftrag 37.1: die technische Testgrundlage kann aus dem
   Test/QA-Playbook (F-71-Entwurf) kommen — diese Rolle entscheidet, nutzt
   aber keinen eigenen zweiten Testlauf, wo bereits einer vorliegt.

**Werkzeuge:** die zu prüfende Datei/Meldung selbst, ggf. Testergebnisse
aus dem Test/QA-Playbook.
**Modell/Aufwand je Lauf:** Sonnet, medium (Prüfentscheidung, kein
Routine-Abhaken).

## (c) Abnahme-Checkliste

```bash
verfahren/Abnahmepruefung/pruefen.sh <meldung.md> <pruefende_rolle>
```
Prüft: (1) Datei vorhanden, (2) die Zeile „Von:" in der Meldung nennt nicht
dieselbe Rolle wie `<pruefende_rolle>` (Selbstprüfung ausgeschlossen).

## (d) Fehler und Korrekturen

(noch keine — frisch gebaut)

## (e) Abgleich Fähigkeitsregister

Ersetzt NICHT `agenten/90_Pruefer/pruefer.md`/`abnahme-pruefer.md` — beide
Rollen bleiben bestehen, dieses Playbook ist ihr gemeinsamer Arbeitsschritt.
Siehe `faehigkeiten/FAEHIGKEITSREGISTER.md`.

## (f) Kosten je Lauf

0 USD (reine Prüflogik, kein Anbieteraufruf für den Prüfschritt selbst).

## Grenzen

Prüft nie die eigene Arbeit. Schreibt nichts neu, nur Prüfergebnis. Keine
Freigabe an den Patron ohne diesen Schritt.
