---
verfahren:        CEO_Statusbericht
titel:            Gemeinsamer Statusbericht aller CEO-Rollen (00_Vorstand)
quelle_auftrag:   F-73 (nach F-70-Vorschlag, Patron 27.09. 17:00: weitermachen)
herkunft:         eigen (kein Fremdmaterial) — abgeleitet aus F-70-Vorschlag "_CEO_Statusbericht.md"
baut_auf:         gilt fuer alle 11 CEO-Rollen unter agenten/00_Vorstand/ceo-*.md — jede Rolle bleibt eigenstaendig,
                  dieses Playbook ist NUR der gemeinsame Berichtsschritt, kein Ersatz der Rolle selbst
status:           gebaut, Muster mit `pruefen.sh` belegt
letzte_pruefung:  2026-09-27
---

# CEO-Statusbericht (gemeinsames Playbook aller CEO-Rollen)

## (a) Aufgabenverständnis

Quelle: F-70-Vorschlag (`abnahme/pm_eingang/F-70_VORSCHLAG_ROLLEN.md`), vom
Patron am 27.09.2026 17:00 zum Weiterbauen freigegeben. Jede der 11
CEO-Rollen (`agenten/00_Vorstand/ceo-*.md`) berichtet regelmäßig an JACK.
Bisher hatte jede Rolle dafür keinen festen, gemeinsamen Ablauf — dieses
Playbook liefert ihn, ohne die Rollen selbst zu verändern oder
zusammenzulegen.

## (b) Feste Schritte, Werkzeuge, Modell/Aufwand

**Kopf (Pflicht, erste Zeilen des Berichts):**
```
Marke:      <MARKE aus dem Frontmatter der jeweiligen ceo-*.md-Datei>
Zeitraum:   <von> – <bis>
Von:        <Rollenname, z. B. ceo-yig-care>
```

**Rumpf (Pflicht, nach der F-69-Schreibregel, Ergebnis zuerst):**
1. **Ergebnis/Entscheidung** — ein Satz, was im Zeitraum erreicht oder
   entschieden wurde.
2. **2–4 Gründe** — kurz, nummeriert.
3. **Belege** — Dateipfade, Protokolle, Zahlen; nichts Behauptetes ohne
   Fundstelle.
4. **Kosten je Lauf** (siehe (f)) — auch wenn 0 USD, immer explizit nennen.

**Ablauf:**
1. Bestehende Dateien der Marke lesen (`00_Marken/<MARKE>/`, `betrieb/`
   soweit zuständig) — keine neue Datenquelle ohne Freigabe.
2. Kopf und Rumpf nach obigem Muster füllen.
3. Bericht ablegen als `abnahme/pm_eingang/<KENNUNG>_MELDUNG.md` oder in den
   PM-Rückkanal der Marke, je nach bestehendem Auftragsweg der Rolle.
4. Nichts an den Patron ohne den Weg über JACK (Regel: CEO-Rollen sprechen
   nie direkt mit dem Patron).

**Werkzeuge:** die Markendateien selbst, kein zusätzliches Werkzeug.
**Modell/Aufwand je Lauf:** Sonnet, low (reine Zusammenfassung, keine neue
Entscheidung — Entscheidungen bleiben Sache der jeweiligen CEO-Rolle nach
ihrem eigenen Playbook).

## (c) Abnahme-Checkliste

```bash
verfahren/CEO_Statusbericht/pruefen.sh <berichtsdatei.md>   # 0 = ok, 1 = Fehlmuster
```
Prüft: (1) Datei vorhanden und lesbar, (2) alle drei Kopf-Pflichtfelder
(`Marke:`, `Zeitraum:`, `Von:`) gefüllt (nicht leer), (3) die Wörter
„Ergebnis" oder „Entscheidung" kommen vor jedem Grund/Beleg-Abschnitt vor
(F-69-Reihenfolge, einfache Näherung: Wort kommt im ersten Drittel der Datei
vor), (4) Bericht ist höchstens eine Bildschirmseite lang (≤ 60 Zeilen).

## (d) Fehler und Korrekturen

(noch keine — frisch gebaut)

## (e) Abgleich Fähigkeitsregister

Neu, kein Vorgänger — siehe `faehigkeiten/FAEHIGKEITSREGISTER.md`, Eintrag
„CEO_Statusbericht".

## (f) Kosten je Lauf

0 USD (reine Textzusammenfassung bestehender Dateien, kein Anbieteraufruf).

## Grenzen

Kein Ersatz für die jeweilige CEO-Rolle oder ihr eigenes Playbook — nur der
Berichtsschritt. Keine Entscheidung, kein Geldtransfer, kein direkter
Kontakt zum Patron (immer über JACK).
