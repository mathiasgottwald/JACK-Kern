---
verfahren:        Angebotsentwurf
titel:            Angebotsentwurf (vertrieb-fachkraft)
quelle_auftrag:   F-73 (nach F-70-Vorschlag, Patron 27.09. 17:00: weitermachen)
herkunft:         eigen (kein Fremdmaterial)
baut_auf:         agenten/20_Vertrieb/vertrieb-fachkraft.md — Rolle bleibt eigenstaendig
status:           gebaut, Muster mit pruefen.sh belegt
letzte_pruefung:  2026-09-27
---

# Angebotsentwurf (vertrieb-fachkraft)

## (a) Aufgabenverständnis

Quelle: F-70-Vorschlag, Zeile „vertrieb-fachkraft". Wiederkehrende Aufgabe:
Angebotsentwurf und Nachfassplan je Kunde/Marke — nur lokal, keine
Zusagen ohne Beleg.

## (b) Feste Schritte, Werkzeuge, Modell/Aufwand

1. Kundenanfrage/-liste lesen (nur lokale Dateien, kein externer
   CRM-Zugriff ohne Freigabe).
2. Angebotsentwurf: Leistung, Preisrahmen, Frist — Preise nach
   `betragText(usd)` (Hausregel).
3. Nachfassplan: Zeitpunkte, Anlass — kein automatischer Versand, nur
   Entwurf.
4. Kein echtes Angebot verschicken oder rechtlich bindend machen ohne
   Freigabe des Patrons (Regel 4/5 sinngemäß: keine Zusage ohne Freigabe).

**Werkzeuge:** lokale Kundendateien, `betragText()`.
**Modell/Aufwand je Lauf:** Sonnet, low.

## (c) Abnahme-Checkliste

```bash
verfahren/Angebotsentwurf/pruefen.sh <angebot.md>   # 0 = ok, 1 = Fehlmuster
```
Prüft: Datei vorhanden; enthält Abschnitt „Angebot" und mindestens einen
Betrag im Format `betragText` (Komma als Dezimaltrennzeichen, „USD" am
Ende) statt Rohzahl mit Punkt.

## (d) Fehler und Korrekturen

(noch keine — frisch gebaut)

## (e) Abgleich Fähigkeitsregister

Neu, kein Vorgänger — siehe `faehigkeiten/FAEHIGKEITSREGISTER.md`.

## (f) Kosten je Lauf

0 USD (reiner Textentwurf, kein Anbieteraufruf).

## Grenzen

Kein Versand, keine rechtlich bindende Zusage ohne Freigabe. Keine
erfundenen Preise oder Leistungen.
