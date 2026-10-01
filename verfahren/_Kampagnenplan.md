---
verfahren:        Kampagnenplan
titel:            Kampagnenplan (marketing-fachkraft, mit Redaktionsteil aus inhalt-fachkraft)
quelle_auftrag:   F-73 (nach F-70-Vorschlag, Patron 27.09. 17:00: weitermachen)
herkunft:         eigen (kein Fremdmaterial)
baut_auf:         agenten/10_Marketing/marketing-fachkraft.md, agenten/60_Inhalt/inhalt-fachkraft.md — beide Rollen
                  bleiben eigenstaendig, dieses Playbook ist ihr gemeinsamer wiederkehrender Arbeitsschritt
status:           gebaut, Muster mit pruefen.sh belegt
letzte_pruefung:  2026-09-27
---

# Kampagnenplan (marketing + inhalt, mit Redaktionsteil)

## (a) Aufgabenverständnis

Quelle: F-70-Vorschlag, Zeilen „marketing-fachkraft" und „inhalt-fachkraft"
(`abnahme/pm_eingang/F-70_VORSCHLAG_ROLLEN.md`). Wiederkehrende Aufgabe:
Kampagnenplan je Marke (Ziel, Kanal, Zeitplan, Budgetrahmen als Vorschlag)
und die dazugehörige Textredaktion (Markenstimme durchsetzen) in einem
Schritt, statt getrennt und potenziell widersprüchlich.

## (b) Feste Schritte, Werkzeuge, Modell/Aufwand

1. **Kampagnenteil (marketing-fachkraft):** Ziel, Zielgruppe, Kanal-Mix,
   Zeitplan aus bestehenden Markendateien (`00_Marken/<MARKE>/`) ableiten —
   keine erfundenen Kennzahlen (Reichweite, Conversion) ohne Beleg.
2. **Redaktionsteil (inhalt-fachkraft):** Texte für jeden geplanten Kanal
   nach der Markenstimme prüfen/schreiben, echte Umlaute, keine
   Vorlagenreste (Bezug F-29 Nachtrag 4: Überschriftenzeilen nicht an den
   Fließtext kleben lassen).
3. **Wettbewerbsblick (optional):** nur mit belegter Quelle, nie erfunden.
4. Kein Auslösen einer echten Kampagne oder Buchung — das ist Geldtransfer
   (Regel 5) und ein eigener, freigabepflichtiger Schritt.
5. Markenmaterial nach Regel 20 (echtes Logo/CI), keine erfundene CI.

**Werkzeuge:** `00_Marken/<MARKE>/`, bestehende Wettbewerbs-/Radar-Daten
(Auftrag 29.1, wo vorhanden).
**Modell/Aufwand je Lauf:** Sonnet, low–medium.

## (c) Abnahme-Checkliste

```bash
verfahren/Kampagnenplan/pruefen.sh <plandatei.md>   # 0 = ok, 1 = Fehlmuster
```
Prüft: Datei vorhanden; enthält je einen Abschnitt „Kampagne" und
„Redaktion"/„Text"; keine Zeile mit einem bekannten Vorlagenrest
(„Der Befund in einem Satz", „Warum das nötig ist" — Bezug F-29).

## (d) Fehler und Korrekturen

(noch keine — frisch gebaut)

## (e) Abgleich Fähigkeitsregister

Neu, kein Vorgänger — siehe `faehigkeiten/FAEHIGKEITSREGISTER.md`.

## (f) Kosten je Lauf

0 USD für Planung/Text; Kosten nur bei echter Kampagnenschaltung (nicht Teil
dieses Playbooks, siehe `_Bezahlte_Werbung`-Entwurf aus F-71).

## Grenzen

Keine echte Kampagnenschaltung, keine Buchung, keine erfundenen Kennzahlen
oder Kundenzitate. Nichts veröffentlichen ohne Freigabe des Patrons.
