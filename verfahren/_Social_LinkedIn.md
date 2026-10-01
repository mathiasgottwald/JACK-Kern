---
verfahren:        entwurf-Social_LinkedIn
titel:            Social-Media-Fachkraft LinkedIn (fehlende Plattformrolle laut 52.1)
quelle_auftrag:   F-71 (Videoauswertung 52.1, Video 52)
herkunft:         agency-agents/marketing/marketing-linkedin-content-creator.md, MIT-Lizenz, github.com/msitarzewski/agency-agents
scan_befund:     sauber (F-71, 27.09.2026 - Skripte/Netzzugriffe/versteckte Anweisungen geprueft)
baut_auf:         marketing-fachkraft.md, vertrieb-fachkraft.md, Auftrag 45.1
status:           aktiv (F-74, 27.09.2026 - Patron-Ja fuer alle 13 Luecken, YouTube ausdruecklich JA)
letzte_pruefung:  2026-09-27
---

# Entwurf — Social-Media-Fachkraft LinkedIn

## (a) Aufgabenverständnis

Quelle: keine eigene Regel — offen. Lücke laut 52.1: keine
plattformspezifische Rolle für LinkedIn. Wiederkehrende Aufgabe (Vorschlag):
B2B-/Positionierungstexte je Marke (v. a. PATRONOS, GOTT_WALD), abgestimmt
mit `vertrieb-fachkraft.md` (Nachfasspläne, Kundenlisten).

## (b) Feste Schritte, Werkzeuge, Modell/Aufwand

Herkunft: `marketing-linkedin-content-creator.md`. Scan „sauber" (siehe
Meldung F-71): 214 Zeilen, keine Skripte/Netzzugriffe/versteckten
Anweisungen.

1. Positionierungstext je Marke, Ton sachlich-fachlich (LinkedIn-Kultur),
   keine erfundenen Kennzahlen oder Kundenaussagen.
2. Abstimmung mit `vertrieb-fachkraft.md`, wenn ein Beitrag konkrete
   Kunden-/Vertriebsaussagen enthält.
3. Veröffentlichung nur über offizielle Schnittstellen, Bezug zu 45.1.

**Werkzeuge:** `vertrieb-fachkraft.md`-Ergebnisse, künftige
LinkedIn-Anbindung aus 45.1.
**Modell/Aufwand je Lauf:** Sonnet, low.

## (c) Abnahme-Checkliste

```bash
verfahren/Social_LinkedIn/pruefen.sh <entwurf.md>   # 0 = ok, 1 = Fehlmuster
```
Prüft: Datei vorhanden; kein Hinweis auf eine bereits erfolgte
Veröffentlichung (Planungsteil ist aktiv, Veröffentlichung bleibt gesperrt
bis 45.1 UND Freigabe).

## (d) Fehler und Korrekturen

(noch keine — Entwurf)

## (e) Abgleich Fähigkeitsregister

Überschneidet sich mit `marketing-fachkraft.md`/`vertrieb-fachkraft.md` und
Auftrag 45.1 — Baustein darunter, kein eigenständiger neuer Kanal-Zugang.

## (f) Kosten je Lauf

0 USD für Textplanung; Veröffentlichungskosten erst nach Anbindung (45.1).

## Grenzen

Keine erfundenen Kundenzitate oder Erfolgszahlen. Nichts veröffentlichen
ohne Freigabe des Patrons.

## PATRONOS Stufe 1 — nur lesend (M-16, 30.09.2026)
**Seite:** linkedin.com/company/patronosai (Organisations-ID wird beim Durchgang aus der Admin-URL gelesen).
**Belegt (Quelle: Microsoft Learn, LinkedIn Community Management Overview, Stand 15.05.2026, abgerufen 30.09.2026):** Die Community Management API ist ein „Vetted Product" mit Development Tier (Erstfreigabe, begrenztes Aufrufvolumen: 500 Aufrufe je App, 100 je Mitglied) und Standard Tier (Screencast). **Lesezugriff ohne diese Prüfung gibt es nicht** — schon die Development-Stufe muss beantragt und von LinkedIn genehmigt werden. Antragsdetails (Super-Admin, verifizierte Seite, Firmenname/Adresse, Geschäfts-Mail) stammen nur aus Drittquellen; die Microsoft-Seite zur Stufenfreigabe war nicht abrufbar (404) → **nicht belegt**. Development-Zugang verfällt nach 12 Monaten ohne Standard-Antrag.
**Lese-Scopes:** `r_organization_social`, `r_organization_admin`. Nicht: `w_organization_social`, `w_member_social`. Header `Linkedin-Version: 202609` (202510 endet am 15.10.2026).
**Schlüsselbund:** `PATRONOS_LINKEDIN_UNTERNEHMEN_LESE` (Token-Text; LinkedIn-Tokens laufen ab, Refresh-Verhalten der Development-Stufe offen).
**Blocker (nur Patron):** Zugang /in/patronosai ist durch die Sicherheitsprüfung gesperrt; die Seite braucht einen Super-Admin. Schrittfolge: 1. LinkedIn-Sicherheitsprüfung für das Profil abschließen. 2. Prüfen, ob dieses Profil Super-Admin der Seite ist (Seite → Admin-Ansicht → Administratoren). 3. developer.linkedin.com: App „PATRONOS JACK" mit Seite verknüpfen, Produkt „Community Management API" beantragen. 4. Genehmigung abwarten. Mehr beschreibe ich nicht.
**Kosten:** 0 USD. **Empfehlung:** als letzte der vier kostenlosen Plattformen, Wartezeit unbekannt.
