---
verfahren:        Social_Facebook
titel:            Facebook-Seite PATRONOS — Anbindung nur lesend
quelle_auftrag:   M-16 (30.09.2026)
status:           aktiv (Stufe 1, nur lesend)
letzte_pruefung:  2026-09-30
---
# Facebook-Seite @patronosai — Stufe 1 (nur lesend)
**Weg:** dieselbe Meta-App 2333675603760821, im selben Durchgang wie Instagram. Seite @patronosai muss dem Patron als Admin zugeordnet sein; Kontotyp/Rollen bisher **unbekannt** (Bericht 18.09. empfiehlt Nachkontrolle).
**Lese-Scopes:** `pages_show_list`, `pages_read_engagement`, `read_insights`. **Nicht:** `pages_manage_posts`, `pages_manage_engagement`.
**Schlüsselbund:** `PATRONOS_FACEBOOK_LESE` (Nutzer- oder Seiten-Token; Code holt das Seiten-Token selbst). **Klickfolge:** wie Instagram, im Meta-Dialog die Seite @patronosai anhaken.
**Lesetest:** Name, Fans/Follower, 3 letzte Beiträge mit Datum, Insights 28 Tage (`page_post_engagements`, `page_media_view`; Teilfehler werden ehrlich als „teilweise_gelesen" gemeldet, Metriknamen bei Meta ändern sich häufig).
**Kosten:** 0 USD. Kein Veröffentlichen, Sperrschalter bleibt an.
