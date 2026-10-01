---
verfahren:        entwurf-40_Finanzen
titel:            Finanz-Fachkraft (Abteilung 40_Finanzen, derzeit leer)
quelle_auftrag:   F-71 (Videoauswertung 52.1, Video 52)
herkunft:         agency-agents/finance/finance-financial-analyst.md + agency-agents/finance/finance-fpa-analyst.md, MIT-Lizenz, github.com/msitarzewski/agency-agents
baut_auf:         keins (neue Rolle, Lücke laut 52.1)
status:           entwurf — NICHT aktiv, NICHT in agenten/
letzte_pruefung:  2026-09-27
---

# Entwurf — Finanz-Fachkraft (40_Finanzen)

Standard-Playbook nach `_VORLAGE_PLAYBOOK.md` (F-70). Entwurf, keine Rolle —
liegt bewusst in `verfahren/_entwurf_F71/`, nicht in `agenten/`, bis der
Patron zustimmt.

## (a) Aufgabenverständnis

Quelle: keine — offen, kein Patron-Interview und keine bestehende Regel zu
Finanz-Auswertung je Marke. Lücke laut Auftrag 52.1: Abteilung `40_Finanzen`
existiert im Ordnerschema, aber ohne Rollen-Datei.

Wiederkehrende Aufgabe (Vorschlag): monatlicher Finanzstatus je Marke
(Umsatz, Kosten, Marge) und einfache Szenariorechnung, aus den bereits
vorhandenen Holding-Dateien (`betrieb/*.json`, Kostenprotokoll `jack_kosten`).

## (b) Feste Schritte, Werkzeuge, Modell/Aufwand

Herkunft: zwei Vorlagen aus `agency-agents` — `finance-financial-analyst.md`
(Kennzahlen, Bericht) und `finance-fpa-analyst.md` (Planung/Szenarien).
Beide MIT-lizenziert, Scan „sauber" (siehe Meldung F-71, Abschnitt Scan).

1. Bestehende Finanzdaten der Marke lesen (`betrieb/`, `jack_kosten`,
   `jack_guthaben.py`) — keine neue Datenquelle ohne Freigabe.
2. Kennzahlenbericht bauen (Umsatz, Kosten, Marge, Tagesdeckel-Auslastung) —
   Beträge ausschließlich über `betragText(usd)` (Hausregel K-Reihe).
3. Auf Wunsch: einfache Szenariorechnung (z. B. „was, wenn Kosten X % steigen") —
   nur mit den bereits vorhandenen Zahlen, keine erfundenen Annahmen ohne
   Kennzeichnung „angenommen".
4. Bericht nach `abnahme/pm_eingang/` oder Dashboard-Karte — Freigabe nach
   Abschnitt 7 der Vorlage (Genehmigungsschritte), kein Geldtransfer, keine
   Buchung ohne „freigegeben" des Patrons (Regel 4/5, Holding-CLAUDE.md).

**Werkzeuge:** `jack_kosten`, `jack_guthaben.py`, `betrieb/*.json`.
**Modell/Aufwand je Lauf:** Sonnet, low–medium (reine Auswertung bestehender
Zahlen, kein Modellaufruf für die Kernrechnung nötig).

## (c) Abnahme-Checkliste

offen — kein `pruefen.sh` im Entwurf; erst beim Bau mit echten Testdaten
sinnvoll.

## (d) Fehler und Korrekturen

(noch keine — Entwurf, kein Betrieb)

## (e) Abgleich Fähigkeitsregister

Teilweise vorhanden: `jack_kosten`, `jack_guthaben.py` liefern bereits
Kostendaten — ein neues Playbook würde nur den Berichtsschritt ergänzen,
keine neue Datenerhebung. Kein Doppelbau nötig.

## (f) Kosten je Lauf

Geschätzt 0 USD bis gering (reine Auswertung vorhandener Dateien, kein
Anbieteraufruf nötig für die Kernfunktion) — genauer Wert erst nach Bau.

## Grenzen

Keine Buchung, kein Zahlungsauftrag, keine Steuererklärung. Nur Auswertung
und Bericht. Kein Zugriff auf externe Bankkonten oder Zahlungsdienste ohne
gesonderte Freigabe.
