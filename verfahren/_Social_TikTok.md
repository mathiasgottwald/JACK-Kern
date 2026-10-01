---
verfahren:        entwurf-Social_TikTok
titel:            Social-Media-Fachkraft TikTok (fehlende Plattformrolle laut 52.1)
quelle_auftrag:   F-71 (Videoauswertung 52.1, Video 52)
herkunft:         agency-agents/marketing/marketing-tiktok-strategist.md, MIT-Lizenz, github.com/msitarzewski/agency-agents
scan_befund:     sauber (F-71, 27.09.2026 - Skripte/Netzzugriffe/versteckte Anweisungen geprueft)
baut_auf:         marketing-fachkraft.md, Verfahren 7.1/9.1 (Videomaterial), Auftrag 45.1 (Social-Media-Zentrale)
status:           aktiv (F-74, 27.09.2026 - Patron-Ja fuer alle 13 Luecken, YouTube ausdruecklich JA)
letzte_pruefung:  2026-09-27
---

# Entwurf — Social-Media-Fachkraft TikTok

## (a) Aufgabenverständnis

Quelle: keine eigene Regel — offen, angelehnt an Auftrag 45.1
(Social-Media-Zentrale, Anbindung über offizielle Schnittstellen). Lücke
laut 52.1: keine plattformspezifische Rolle für TikTok. Wiederkehrende
Aufgabe (Vorschlag): TikTok-Postingplan und Formatberatung (Hook, Länge,
Trendbezug) je Marke, aus bereits produziertem eigenem Material (7.1/9.1).

## (b) Feste Schritte, Werkzeuge, Modell/Aufwand

Herkunft: `marketing-tiktok-strategist.md`. Scan „sauber" (siehe Meldung
F-71): 124 Zeilen, keine Skripte/Netzzugriffe/versteckten Anweisungen.

1. Postingplan aus bestehendem, eigenem Videomaterial (Verfahren 7.1/8.1/9.1) —
   kein fremdes Material, keine Trend-Sounds ohne Rechteklärung.
2. Hook-/Längen-/Format-Beratung nach der Vorlage, angepasst an
   Markenstimme (Regel 3, PLHH-Leitbild).
3. Veröffentlichung NUR über offizielle Schnittstellen (TikTok-API/offizielle
   Tools), nicht über Drittanbieter-Automatisierung ohne Sicherheitsprüfung
   (Bezug zu 45.1/Composio-Vorbehalt).
4. Kennzeichnung KI-erzeugter Inhalte wie in 7.1.

**Werkzeuge:** Verfahren 7.1/8.1/9.1 (Materialquelle), künftige
TikTok-Anbindung aus 45.1 (noch nicht gebaut).
**Modell/Aufwand je Lauf:** Sonnet, low (Textplanung, kein Bild-/Videoaufruf
in diesem Playbook selbst).

## (c) Abnahme-Checkliste

```bash
verfahren/Social_TikTok/pruefen.sh <entwurf.md>   # 0 = ok, 1 = Fehlmuster
```
Prüft: Datei vorhanden; kein Hinweis auf eine bereits erfolgte
Veröffentlichung (Planungsteil ist aktiv, Veröffentlichung bleibt gesperrt
bis 45.1 UND Freigabe).

## (d) Fehler und Korrekturen

(noch keine — Entwurf)

## (e) Abgleich Fähigkeitsregister

Überschneidet sich mit `marketing-fachkraft.md` (Kampagnenpläne) und
Auftrag 45.1 — dieses Playbook wäre der TikTok-spezifische Baustein
darunter, kein eigenständiger neuer Kanal-Zugang.

## (f) Kosten je Lauf

0 USD für Planung; Veröffentlichungskosten erst nach Anbindung (45.1) und
nach den dortigen Kostenstufen.

## Grenzen

Kein Fremdmaterial, keine Massenware, keine Gratis-Webdienste/Proxys
(bestehende Regel aus 45.1). Nichts veröffentlichen ohne Freigabe des
Patrons.

## PATRONOS Stufe 1 — nur lesend (M-16, 30.09.2026)
**Konto:** TikTok @patronosai. **Weg:** TikTok for Developers, Display API (`/v2/user/info/`, `/v2/video/list/`), Login Kit. Scopes exakt: `user.info.basic`, `user.info.stats`, `video.list`. Kein `video.publish`/`video.upload`.
**Belegte Bedingungen (Quelle: TikTok for Developers, App Review Guidelines und Display-API-Get-Started, abgerufen 30.09.2026):** Die Richtlinien verlangen **keine** Gewerbeanmeldung und kein Business-Konto — das Wort kommt dort nicht vor. Verlangt werden: gültige offizielle Website mit sichtbarer Datenschutzerklärung und Nutzungsbedingungen (nicht nur Login-/Landingpage), Demo-Video des kompletten Ablaufs, Sandbox-Test bei erster Prüfung, „Apps must not be for private or personal use". Prüfdauer laut Drittquellen 3–4 Tage. Die Behauptung „Gewerbeanmeldung nötig" (Bericht 18.09.) ist damit **nicht belegt**. Offen: ob ein Zugriff nur auf das eigene Konto ohne abgeschlossene App-Prüfung geht — die Doku sagt dazu nichts.
**Token:** Access 24 h, Refresh 1 Jahr → `PATRONOS_TIKTOK_LESE` = JSON `{"client_key","client_secret","refresh_token"}`; der Code tauscht bei jedem Lauf.
**Klickfolge Patron** (*angenommen*, Titel beim Durchgang wörtlich nachtragen): developers.tiktok.com anmelden → App anlegen (Name PATRONOSAI, Website patronos.ai, Datenschutz/AGB-Links) → Login Kit + Display API hinzufügen → Scopes oben → Sandbox, @patronosai als Zielnutzer → Zustimmung klicken.
**Kosten:** 0 USD.
