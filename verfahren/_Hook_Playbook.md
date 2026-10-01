---
verfahren:        Hook_Playbook
titel:            Hook-Formeln und Varianten-Abnahme (Auftrag 45.1, Aufgabe 9a)
quelle_auftrag:   02_Dokumente/2026-09-16_Videoauswertung.md, Auftrag 45.1, Aufgabe 9a (Nachtrag Video 54, 27.09.2026)
baut_auf:         _Social_TikTok.md, _Social_Instagram.md, _Social_LinkedIn.md, _Social_YouTube.md (F-74) — für Plattformformat; dieses Playbook liefert nur die Hook-Formel
status:           gebaut, pruefen.sh mit Gut-/Fehlbeispiel getestet
letzte_pruefung:  2026-09-27
---

# Hook_Playbook — Hook-Formeln je Marke, Abnahme-Checkliste, Varianten

Standard-Playbook nach `_VORLAGE_PLAYBOOK.md`. Liefert **nur** die ersten 0–3 Sekunden
eines Beitrags (den Hook) und die Auswahl unter mehreren Varianten — Länge, Schnitt,
Untertitel und Plattformformat stehen in den `_Social_*.md`-Playbooks (F-74) und werden
hier nicht wiederholt.

## (a) Aufgabenverständnis

Quelle: Auftrag 45.1, Aufgabe 9a (Nachtrag aus Video 54, 27.09.2026). Wiederkehrende
Aufgabe: Für jeden geplanten Kurzvideo-/Feed-Beitrag mehrere Hook-Varianten nach
belegten Formeln erzeugen, gegen eine Checkliste abnehmen und eine begründete
Empfehlung für die beste Variante geben. Kostenlos — **kein Kommentar-Köder**
(„schreib X, dann bekommst du den Link" u. ä.), das ist eine plattformfremde
Täuschung, kein Hook.

## (b) Feste Schritte, Werkzeuge, Modell/Aufwand

**Einstiegsfunktion:** `verfahren/Hook_Playbook/pruefen.sh <entwurf.md>`

1. **Formel wählen** (je nach Marke, siehe Tabelle unten) — mindestens eine der
   sechs Grundformeln, angepasst an die Markenstimme.
2. **Mindestens 3 Varianten** aus verschiedenen Formeln für denselben Beitrag
   schreiben (1–2 Sätze, 0–3 Sekunden Sprechzeit).
3. **Abnahme-Checkliste** (Abschnitt c) auf jede Variante anwenden.
4. **Empfehlung**: eine Variante auswählen, **mit Begründung** (welche Formel,
   warum zur Marke/zum Thema passend, welcher Beleg — z. B. Aktualität aus der
   Chancenliste wie im CASHFLOW-Ausspielplan).
5. Ergebnis geht in den Entwurf, der von `_Social_*.md` weiterverarbeitet wird
   (Produktion erst nach Freigabe, wie dort geregelt).

**Werkzeuge:** keine (reine Textarbeit, kein Modellaufruf über den aktuellen
Schreibvorgang hinaus).
**Modell/Aufwand je Lauf:** Sonnet, low (kurze Textvarianten, keine Recherche).

### Hook-Formeln je Marke

| Marke | Leitformel | Warum diese |
|---|---|---|
| PATRONOS | **Aktualität/Kontrast**: „Während alle über X reden, passiert Y." | Dach-Kanal, Nachrichtenbezug, hohe Reichweite über viele Marken |
| CASHFLOW_KOMPASS | **Offene Frage**: „Bevor Sie X wählen: eine Frage." | passt zum bestehenden Ton (sachlich, „Sie", siehe `betrieb/content/`) und zum Vorrat vom 25.09. (`05_Marketing/2026-09_Organik_Vorrat/`) |
| MEISTERWERK | **Widerspruch/Irrtum**: „Der häufigste Fehler bei X ist nicht, was Sie denken." | Coaching-Positionierung, Autorität durch Klarstellung |
| ANALOG_WERKE | **Sinnlich/Konkret**: „So fühlt sich X an, bevor Sie es sehen." | analoge/haptische Markenwelt |
| PLHH | **Werte-Aufruf**: „Was wäre, wenn X der Natur nützt statt schadet?" | Leitbild PLHH/Triade NATUR–TIER–MENSCH |
| YIG_CARE | **Persönliche Ansprache**: „Ein Gedanke für Ihren Tag, bevor er beginnt." | Frequenz-/Wellbeing-Positionierung, ruhiger Ton |
| STEPHAN_MANDLIK, give1get1 | **Offene Frage** (wie CASHFLOW) als Standard, bis eigene Markenstimme dokumentiert ist | keine eigene Stimme im Steckbrief belegt — sicherster Standard |

Jede Formel ist ein Muster, kein Textbaustein: die Variante wird für den konkreten
Beitrag neu geschrieben, nie wortgleich wiederverwendet.

## (c) Abnahme-Checkliste (Befehl mit Exit-Code)

```bash
verfahren/Hook_Playbook/pruefen.sh <entwurf.md>   # 0 = ok, 1 = Befund mit Text auf stderr
```

Geprüft wird pro Datei:
1. **Mindestens 3 Varianten** vorhanden (nummerierte Liste `1.`/`2.`/`3.` unter einer
   Überschrift „Varianten").
2. **Begründete Empfehlung** vorhanden (Abschnitt „Empfehlung" mit mindestens einem
   Satz Begründung, nicht nur eine Nummer).
3. **Kein Kommentar-Köder**: keine Aufforderung, einen Kommentar/ein Wort zu
   hinterlassen, um an Inhalt/Link zu gelangen.
4. **Keine erfundene Dringlichkeit/Verknappung** („nur heute", „letzte Chance" u. ä.
   — dieselbe Grenze wie im Shop-Prüfer `bin/shop_pruefen.py` der Marke CASHFLOW,
   hier plattformübergreifend angewandt).
5. **Kein Wirkungs-/Verdienstversprechen** ohne Beleg.
6. **Länge je Variante**: höchstens 220 Zeichen (0–3 Sekunden Sprechzeit).

Getestet mit zwei Beispielen (liegen bei, dienen nur der Prüfung dieses
Playbooks, sind keine echten Beiträge):
- `beispiele/gut.md` → `pruefen.sh` liefert 0
- `beispiele/schlecht.md` (Kommentar-Köder + Verknappung + nur 2 Varianten) → `pruefen.sh` liefert 1 mit allen drei Befunden

## (d) Fehler und Korrekturen

*(leer — noch kein Fehler aufgetreten, 27.09.2026)*

## (e) Abgleich Fähigkeitsregister (vor dem Bau)

Geprüft am 27.09.2026: `_Social_TikTok/Instagram/LinkedIn/YouTube.md` (F-74) decken
Postingplan, Format und Länge je Plattform ab — **keine** davon liefert Hook-Varianten
oder eine Abnahme-Checkliste für Hooks. `Kampagnenplan` deckt die kanalübergreifende
Kampagne ab, nicht die einzelne Hook-Formel. Kein Doppelbau; Eintrag neu im
Fähigkeitsregister (siehe dort).

## (f) Kosten je Lauf

0 USD, reine Textarbeit und Prüflogik ohne Anbieteraufruf. Produktion (Video/Bild) ist
nicht Teil dieses Playbooks und läuft über 39.1/40.1/7.1 mit eigener Kostenstufe (24.1).

## Grenzen

- Liefert nur den Hook-Text, nie das fertige Video/den fertigen Beitrag.
- Kein Kommentar-Köder, keine erfundene Verknappung, kein unbelegtes Versprechen.
- Keine Veröffentlichung — Freigabe und Produktion laufen ausschließlich über die
  `_Social_*.md`-Playbooks und den bestehenden Freigabeweg der jeweiligen Marke.
