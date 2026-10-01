---
verfahren:        Social_YouTube
titel:            Social-Media-Fachkraft YouTube
quelle_auftrag:   F-71 (Videoauswertung 52.1, Video 52), aktiviert F-74 (Patron 27.09. 17:00: "hört zu 100 % mit rein")
herkunft:         agency-agents/marketing/marketing-video-optimization-specialist.md, MIT-Lizenz,
                  github.com/msitarzewski/agency-agents — KEIN dediziertes YouTube-Template im Bestand gefunden,
                  eigener Teil (Sperrliste, Kontoanlage-Regel) ergänzt in F-74
scan_befund:      sauber (F-71, 27.09.2026 - Skripte/Netzzugriffe/versteckte Anweisungen geprueft)
baut_auf:         Verfahren 7.1/8.1/9.1, Auftrag 33.1 (YouTube-Regeln CASHFLOW, Methode dort verworfen - Sperrliste
                  bleibt gueltig), Auftrag 45.1 (Social-Media-Zentrale, noch nicht gebaut)
status:           aktiv (F-74, 27.09.2026 - Patron-Ja fuer alle 13 Luecken, YouTube ausdruecklich JA); Planungsteil
                  aktiv, Veroeffentlichung erst nach 45.1 UND Freigabe
letzte_pruefung:  2026-09-27
---

# Social-Media-Fachkraft YouTube

## (a) Aufgabenverständnis

Quelle: Auftrag 33.1 (YouTube-Regeln für CASHFLOW — die dort geprüfte
Methode selbst wurde verworfen, die Sperrliste/Warnung bleibt aber gültig
und gilt hier ebenso) plus Patron-Entscheidung F-74 (27.09.2026 17:00:
YouTube ausdrücklich JA, „hört zu 100 % mit rein"). Wiederkehrende
Aufgabe: Titel-/Beschreibungs-/Thumbnail-Optimierung für eigene, bereits
produzierte Videos.

**Hinweis (ehrlich, nicht verschwiegen):** Im Bestand von `agency-agents`
gibt es **keine** Vorlage mit „youtube" im Namen. Nächstbeste Vorlage:
`marketing-video-optimization-specialist.md` (allgemeine Video-SEO/
Optimierung, plattformübergreifend, keine YouTube-Spezifika wie
Kapitelmarken oder Community-Tab). Der YouTube-spezifische Teil (Sperrliste,
Kontoanlage-Regel) ist deshalb hier eigenständig ergänzt, nicht aus der
Fremdvorlage übernommen.

## (b) Feste Schritte, Werkzeuge, Modell/Aufwand

Scan „sauber" (siehe F-71-Meldung): 119 Zeilen, keine Skripte/Netzzugriffe/
versteckten Anweisungen in der Fremdvorlage.

1. Titel/Beschreibung/Tags aus eigenem Videomaterial (Verfahren 7.1/8.1/9.1)
   ableiten — keine Clickbait-Übertreibung, keine erfundenen Eigenschaften.
2. Thumbnail nur aus echtem, freigegebenem Bildmaterial (Regel 20).
3. **Sperrliste (aus Auftrag 33.1, technisch/organisatorisch bindend, nicht
   nur Empfehlung):**
   - Kein „inauthentic content" nach YouTube-Richtlinie (massenhaft
     gleichförmige, gesichtslose KI-Kanäle).
   - Keine Kinderinhalte mit KI-Stimme ohne gesonderte, dokumentierte
     Prüfung.
   - Keine gesichtslosen KI-Massenkanäle (Serienproduktion ohne erkennbare
     eigene Marke/Person dahinter).
4. **Kontoanlage nur durch den Patron** — kein Kanal, kein Google-/YouTube-
   Konto wird von einer Fachkraft oder einem Agenten selbst angelegt.
5. Veröffentlichung nur über eine spätere, offizielle Anbindung (Auftrag
   45.1) UND nach Freigabe des Patrons — bis dahin bleibt dieses Playbook
   auf den **Planungsteil** (1–2) beschränkt.

**Werkzeuge:** Verfahren 7.1/8.1/9.1, künftige YouTube-Anbindung aus 45.1.
**Modell/Aufwand je Lauf:** Sonnet, low.

## (c) Abnahme-Checkliste

```bash
verfahren/Social_YouTube/pruefen.sh <entwurf.md>   # 0 = ok, 1 = Fehlmuster
```
Prüft: Datei vorhanden; keines der Sperrlisten-Stichworte
(„Massenkanal"/„gesichtslos" ohne Gegenbeleg, „Kinderinhalt" ohne
„geprüft") kommt unbelegt vor; kein Hinweis auf eine bereits ausgelöste
Veröffentlichung (Wort „veröffentlicht"/„online" ohne „Entwurf").

## (d) Fehler und Korrekturen

(noch keine — frisch aktiviert)

## (e) Abgleich Fähigkeitsregister

Überschneidet sich mit Auftrag 33.1 (Sperrliste, dort bereits entschieden)
und 45.1 (Anbindung, noch nicht gebaut) — dieses Playbook ist nur die
Optimierungs-/Planungsrolle für ohnehin bereits erlaubte, eigene Videos.
Siehe `faehigkeiten/FAEHIGKEITSREGISTER.md`.

## (f) Kosten je Lauf

0 USD für Textoptimierung/Planung; Veröffentlichungskosten erst nach
Anbindung (45.1) und nach deren eigenen Kostenstufen.

## Grenzen

Keine „inauthentic content"-Methoden, keine gesichtslosen KI-Massenkanäle,
keine Kinderinhalte mit KI-Stimme ohne gesonderte Prüfung (alles aus 33.1).
Keine Kontoanlage außer durch den Patron selbst. Nichts veröffentlichen ohne
45.1 UND Freigabe des Patrons.

## PATRONOS Stufe 1 — nur lesend (M-16, 30.09.2026)
**Kanal:** @patronosai, ID UCvcWaJx2dcqiLAfrPkspYiw (Anzeigename bleibt „PATRONOSAI").
**Weg:** Google-Cloud-Projekt + YouTube Data API v3 + YouTube Analytics API, OAuth durch den Kanalinhaber. Ob ein Cloud-Projekt für PATRONOS existiert: im Register/der Schlüsselinventur **kein Eintrag gefunden** → neues Projekt „patronos-jack-lesen" (angenommen, beim Durchgang im Google-Konto gegenprüfen; vorhandenes wiederverwenden, falls sichtbar).
**Scopes, exakt:** `https://www.googleapis.com/auth/youtube.readonly` und `https://www.googleapis.com/auth/yt-analytics.readonly`. **Kein** `youtube`, `youtube.upload`, `youtube.force-ssl`.
**Schlüsselbund:** `PATRONOS_YOUTUBE_LESE` = JSON `{"client_id","client_secret","refresh_token"}` (Eingabe durch den Patron, nie Chat/Datei). Refresh-Token hält, solange die OAuth-Zustimmung nicht auf „Testing" bleibt (dort läuft es nach 7 Tagen ab) → Zustimmungsbildschirm auf „In production" (ohne sensible Scopes-Prüfung für eigene Nutzung: angenommen, beim Durchgang prüfen).
**Kontingent (Quelle: Google-Doku/Übersichten, 30.09.2026):** 10.000 Einheiten/Tag je Projekt; `channels.list` 1 Einheit, dieser Lauf ca. 4 Einheiten; 0 USD.
**Klickfolge Patron** (Titel beim Durchgang wörtlich nachtragen, *angenommen*): console.cloud.google.com mit dem Google-Konto des Kanals → Projekt anlegen → APIs aktivieren (beide) → OAuth-Zustimmungsbildschirm → OAuth-Client „Desktop" → einmalige Zustimmung für die zwei Lese-Scopes.
