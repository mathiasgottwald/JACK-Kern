---
verfahren:        entwurf-Social_Instagram
titel:            Social-Media-Fachkraft Instagram (fehlende Plattformrolle laut 52.1)
quelle_auftrag:   F-71 (Videoauswertung 52.1, Video 52)
herkunft:         agency-agents/marketing/marketing-instagram-curator.md, MIT-Lizenz, github.com/msitarzewski/agency-agents
scan_befund:     sauber (F-71, 27.09.2026 - Skripte/Netzzugriffe/versteckte Anweisungen geprueft)
baut_auf:         marketing-fachkraft.md, Verfahren 7.1/8.1/9.1, Auftrag 45.1
status:           aktiv (F-74, 27.09.2026 - Patron-Ja fuer alle 13 Luecken, YouTube ausdruecklich JA)
letzte_pruefung:  2026-09-27
---

# Entwurf — Social-Media-Fachkraft Instagram

## (a) Aufgabenverständnis

Quelle: keine eigene Regel — offen, angelehnt an Auftrag 45.1. Lücke laut
52.1: keine plattformspezifische Rolle für Instagram. Wiederkehrende
Aufgabe (Vorschlag): Feed-/Reels-/Story-Kuratierung je Marke, visuelle
Konsistenz mit dem echten Markenmaterial (Regel 20).

## (b) Feste Schritte, Werkzeuge, Modell/Aufwand

Herkunft: `marketing-instagram-curator.md`. Scan „sauber" (siehe Meldung
F-71): 112 Zeilen, keine Skripte/Netzzugriffe/versteckten Anweisungen.

1. Bildauswahl/-planung nur aus eigenem, freigegebenem Markenmaterial
   (Regel 20) — kein erfundenes Logo, keine erfundene CI.
2. Feed-Rhythmus und Story-/Reels-Mix nach Vorlage, angepasst an
   Markenstimme.
3. Veröffentlichung nur über offizielle Schnittstellen (Meta/Instagram-API),
   Bezug zu 45.1.
4. Kennzeichnung KI-erzeugter Inhalte wie in 7.1.

**Werkzeuge:** Markenordner `00_Marken/<MARKE>/`, Verfahren 7.1/8.1/9.1,
künftige Instagram-Anbindung aus 45.1.
**Modell/Aufwand je Lauf:** Sonnet, low.

## (c) Abnahme-Checkliste

```bash
verfahren/Social_Instagram/pruefen.sh <entwurf.md>   # 0 = ok, 1 = Fehlmuster
```
Prüft: Datei vorhanden; kein Hinweis auf eine bereits erfolgte
Veröffentlichung (Planungsteil ist aktiv, Veröffentlichung bleibt gesperrt
bis 45.1 UND Freigabe).

## (d) Fehler und Korrekturen

**28.09.2026 (CF-4/CF-5):** Veröffentlichungs-Tor zweimal von Opus abgelehnt
(Zeilennummer-Prüfung ohne Bindung an Inhalt/Marke/Kanal; danach Ticket ohne
Datums-/Kartenbezug ließ einen nie freigegebenen Beitrag über ein liegen
gebliebenes Ticket vom Vortag veröffentlichen, Logo-Nachweis prüfte ein
anderes Bild als das tatsächlich hochgeladene). Neu gebaut (`jack_social.py`,
Kommentarblock „Veröffentlichen (Tor B)"): Karte+Ticket+Bild fest über
Prüfsummen gebunden, Ticket wird vor jedem Netzaufruf verbraucht. Bis zur
dritten unabhängigen Prüfung bleibt `VEROEFFENTLICHEN_GESPERRT = True` —
siehe `entscheidungen/2026-09-28_social-media-zentrale-stufe3-instagram.md`.

**Ein-Rechner-Regel (CF-5, schriftlich festgelegt):** Instagram-Veröffentlichung
läuft ausschließlich auf dem Rechner, der in
`betrieb/social_kanaele.json` unter `erlaubter_rechner_instagram` eingetragen
ist (Stand 28.09.2026: `Mac.home`). Grund: Die Holding-Ablage liegt in
iCloud Drive, iCloud synchronisiert nicht atomar — zwei Macs könnten sonst
gleichzeitig dasselbe Ticket verbrauchen wollen. Technisch erzwungen in
`instagram_veroeffentlichen_aus_tagesliste` (`_dieser_rechner_ist_erlaubt`,
Vergleich gegen `platform.node()`) — fehlt der Eintrag oder passt der
Rechnername nicht, wird ohne jeden Netzaufruf mit `falscher_rechner`
abgebrochen. Umzug auf einen anderen Rechner: den Wert bewusst in
`social_kanaele.json` ändern, nicht automatisch nachziehen lassen.

## (e) Abgleich Fähigkeitsregister

Überschneidet sich mit `marketing-fachkraft.md` und Auftrag 45.1 — Baustein
darunter, kein eigenständiger neuer Kanal-Zugang.

## (f) Kosten je Lauf

0 USD für Planung; Veröffentlichungskosten erst nach Anbindung (45.1).

## Grenzen

Kein Fremdmaterial, keine Gratis-Webdienste/Proxys. Nichts veröffentlichen
ohne Freigabe des Patrons.

## PATRONOS Stufe 1 — nur lesend (M-16, 30.09.2026)
**Konto:** Instagram @patronosai (Anzeigename bleibt „PATRONOSAI", keine Profiländerung). Kontotyp muss Business/Creator und mit der Facebook-Seite @patronosai verknüpft sein (sonst kein Graph-Zugriff) — Kontotyp bisher **unbekannt**, wird beim Durchgang geprüft.
**Weg:** bestehende Meta-App 2333675603760821 (wie CF-4b), EIN Durchgang zusammen mit Facebook (`_Social_Facebook.md`).
**Lese-Scopes, exakt:** `instagram_basic`, `instagram_manage_insights`, `pages_show_list`, `pages_read_engagement`, `business_management` nur falls Meta die Seite sonst nicht zeigt. **Nicht** beantragen: `instagram_content_publish`, `instagram_manage_comments`, `pages_manage_posts`.
**Schlüsselbund:** `PATRONOS_INSTAGRAM_LESE` (Token-Text). **Rechner:** der Mac, an dem Chrome mit dem Meta-Konto des Patrons angemeldet ist.
**Klickfolge Patron** (Bildschirmtitel werden beim Durchgang wörtlich nachgetragen — bisher nicht live gesehen, daher *angenommen*): 1. Chrome, developers.facebook.com, angemeldet sein. 2. Graph-API-Explorer, App 2333675603760821 wählen. 3. Berechtigungen oben genau anhaken, „Token generieren", Seite @patronosai und Instagram-Konto im Meta-Dialog bestätigen. 4. Langzeit-Token (60 Tage) erzeugen lassen. 5. Token kopieren; JACK sagt dann den einen Terminalbefehl an, der ihn aus der Zwischenablage in den Schlüsselbund legt (Verfahren CF-4: Eingabe durch den Patron, nie im Chat).
**Danach JACK:** `jack_social_lesen.meta_konten_finden(token)` findet `page_id` und `ig_user_id`, Register wird ergänzt, Lesetest (Follower, 3 Beiträge, 7-Tage-Kennzahlen).
**Kosten:** 0 USD. **Token-Ablauf:** ca. 60 Tage → Erinnerungskarte anlegen.
