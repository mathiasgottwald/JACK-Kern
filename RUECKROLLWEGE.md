# RÜCKROLLWEGE — JACK, Stand 18.09.2026 (Block 23e, Paket an DIN)

**Wozu diese Datei.** In den Berichten von Block 16 und der Kette A standen
Rückrollwege, die so **nicht laufen**: die Tilde in Anführungszeichen
(`"~/Library/…"`) wird von der Shell nicht ersetzt, und ohne `cd` zeigt
`"$f.vor_blockN…"` ins Leere. Hier steht je Block **eine** Zeile, die wirklich
läuft — kopieren, ins Terminal, Enter.

**Zwei Dinge vorher lesen:**

1. **Reihenfolge rückwärts.** Eine Sicherung `*.vor_blockN_2026-09-17` enthält
   den Stand **vor** Block N — also einschließlich aller Blöcke davor, aber
   ohne alle danach. Wer Block 17 zurückrollt, verliert damit auch 18, 19, 20.
   Richtig ist deshalb: **23d → 23c → 23b → 23 → 22 → 21 → 20 → 19 → 18 → 17 → 16b → 16**,
   so weit wie nötig.
   Der Logowechsel steht daneben, nicht darin: er lässt sich einzeln
   zurücknehmen, ohne Block 21 anzufassen.
   Es genügt, die Zeile des ältesten Blocks zu nehmen, den man loswerden will.
2. **`ACTIVE_CONTEXT.md` wird mit zurückgerollt.** Das ist Absicht: sonst
   beschreibt sie einen Stand, den es nicht mehr gibt. Die Entscheidungsdateien
   unter `entscheidungen/` und die Belege unter `abnahme/` bleiben **immer**
   liegen — sie erzählen, was war.

**Nichts wird gelöscht.** `cp -p` überschreibt nur die Arbeitsdatei; jede
Sicherung bleibt, wo sie ist.

---

## Block 25 — Sprachsteuerung vorbereitet, NICHT eingebaut (17.09.2026, angehalten)

Dieser Lauf wurde angehalten, bevor er `server.py`, `index.html` oder den
Dienst angefasst hat (Grund: `entscheidungen/2026-09-17_Block25_Entscheidungen_im_Lauf.md`).
Es gibt nur neue, eigenständige Dateien — keine bestehende Datei wurde
verändert, deshalb genügt Löschen statt Zurückkopieren:

```
cd ~/"Library/Mobile Documents/com~apple~CloudDocs/GOTT WALD HOLDING/00_Marken/JACK" && rm -f jack_steuerung.py betrieb/steuerung_katalog.json && rm -rf abnahme/Block25_2026-09-17
```

`entscheidungen/2026-09-17_Block25_Entscheidungen_im_Lauf.md` bleibt stehen
(Entscheidungsdateien werden nie zurückgerollt, siehe oben). Ein anderer
Faden (Session „jack-5c") hat im selben Zeitfenster bereits
`server.py.vor_block25_2026-09-17`, `index.html.vor_block25_2026-09-17` und
`jack_erweiterungen.py.vor_block25_2026-09-17` angelegt — Stand 21:53 Uhr
identisch mit den Originalen (noch keine echte Änderung). Falls diese Session
doch etwas eingebaut hat, bevor der Patron das hier liest, zusätzlich:

```
cd ~/"Library/Mobile Documents/com~apple~CloudDocs/GOTT WALD HOLDING/00_Marken/JACK" && for f in server.py index.html jack_erweiterungen.py; do cp -p "$f.vor_block25_2026-09-17" "$f"; done && launchctl kickstart -k gui/$(id -u)/world.gottwald.jack.server
```

## Block 24 — Abnahme-Tor, Buchführung, Geisterordner, Pfadwächter, API-Budget (17.09.2026)

```
cd ~/"Library/Mobile Documents/com~apple~CloudDocs/GOTT WALD HOLDING/00_Marken/JACK" && for f in arbeiter.sh arbeiter_api_start.py betrieb/betriebsgrenzen.json betrieb/laufende.json "auftraege/erledigt/2026-09-16_164951_KOSTENWAECHTER_Vertragsregister.md" "auftraege/erledigt/2026-09-17_KOSTENSTUFEN_Tabelle_und_Messtest.md" ACTIVE_CONTEXT.md RUECKROLLWEGE.md; do cp -p "$f.vor_block24_2026-09-17" "$f"; done && mv "99_Archiv/Geisterordner_07_Projekte_2026-09-15/07_Projekte" "07_Projekte"
```

Kein `launchctl kickstart` nötig — Block 24 ändert nichts an `server.py` oder
`index.html`; `arbeiter.sh` wird ohnehin bei jedem der launchd-Läufe im
5-Minuten-Takt neu eingelesen.

Was diese Zeile NICHT zurückrollt: die neuen Belegdateien unter
`abnahme/Block24_2026-09-17/` (Testskripte, Fixtures, Sandbox, Ergebnisse) und
die Entscheidungsdatei
`entscheidungen/2026-09-17_Block24_Abnahme-Tor_und_Pfadwaechter.md` bleiben
liegen — sie erzählen, was war, wie in allen vorherigen Blöcken.

---

## Block 23e — Logo live, Text bereinigt, Paket an DIN (18.09.2026)

**Was sich NICHT zurückrollen lässt:** Die Mail an DIN ist um **07:03:51**
hinausgegangen. Eine gesendete Mail kommt nicht zurück. Wer etwas richtigstellen
will, schreibt eine zweite — über dieselbe Freigabekette.

**Was sich zurückrollen lässt:**

*Der Text an DIN* (für künftige Fassungen; die gesendete bleibt, wie sie ist):

```
cd ~/"Library/Mobile Documents/com~apple~CloudDocs/GOTT WALD HOLDING/00_Marken/JACK/betrieb/entwuerfe" && cp -p "2026-09-17_165533_mitarbeiter_Your-signature--our-CI-guide---and-your-first-ta_6aad93.md.vor_block23e_2026-09-18" "2026-09-17_165533_mitarbeiter_Your-signature--our-CI-guide---and-your-first-ta_6aad93.md" && echo fertig
```

*Die zwei Code-Änderungen* (Karten-Prüfung im Testversand, Gesendet-Ordner):

```
cd ~/"Library/Mobile Documents/com~apple~CloudDocs/GOTT WALD HOLDING/00_Marken/JACK" && cp -p jack_mitarbeiter.py.vor_block23e_2026-09-18 jack_mitarbeiter.py && cp -p jack_postfaecher.py.vor_block23c_2026-09-18 jack_postfaecher.py && launchctl kickstart -k gui/$(id -u)/world.gottwald.jack.server
```

**Achtung bei der zweiten Zeile:** Sie holt `jack_postfaecher.py` auf den Stand
**vor Block 23c** zurück — damit ist auch das eingebettete Logo wieder weg. Wer
nur den Gesendet-Ordner zurückdrehen will, nimmt in `GESENDET_ORDNER` den
Eintrag `'"INBOX.Sent Messages"'` von Hand heraus. Dann liegt aus
`office@gottwald.world` wieder keine Kopie.

*Das Logo im Netz:* Die alte Datei liegt als
`13_Korrespondenz/Email-Setting/logo/gottwald-logo.png.vor_block23c_2026-09-18_aus_Webprojekt`.
Zurückstellen heißt: Datei nach
`GOTT-WALD-World/public/signatur/gottwald-logo.png` kopieren, committen, pushen.
**Das ist ein Schritt nach außen** und gehört dem Patron. Der Kreis wäre danach
in von Hand installierten Signaturen wieder ein Ei.

---

## Block 23c-Nachtrag (23d) — HEAD OFFICE mit Rhythmus (18.09.2026)

**Was zurückgerollt wird:** die drei Gruppen im HEAD-OFFICE-Block und das Logo
über dem Namen.

**Was das bedeutet:** HEAD OFFICE ist wieder eine Liste aus sechs gleich
aussehenden Zeilen, das Logo steht wieder neben dem Namen — und damit stehen
Name und Rolle wieder 60 px weiter rechts als alles darunter.

```
cd ~/"Library/Mobile Documents/com~apple~CloudDocs/GOTT WALD HOLDING/13_Korrespondenz/Email-Setting" && for f in maildesign.json maildesign_bauen.py README_POSTAUSGANG.md Rahmen/*.html Signaturen_Email/Signatur_*/*.html Signaturen_Email/Signatur_*/*_TEXT.txt Signaturen_Email/Vorschau/*_Gmail.html Signaturen_Email/Vorschau/*_Outlook.html; do [ -f "$f.vor_block23d_2026-09-18" ] && cp -p "$f.vor_block23d_2026-09-18" "$f"; done; echo fertig
```

```
cd ~/"Library/Mobile Documents/com~apple~CloudDocs/GOTT WALD HOLDING" && for f in 00_Marken/JACK/RUECKROLLWEGE.md 00_Marken/JACK/ACTIVE_CONTEXT.md 00_Marken/JACK/abnahme/Block23_2026-09-17/pruefung_block23.py "08_Mitarbeiter/Dween_Mohammad/ALLGEMEIN/Dokumente/CI/Signature_Package_Dween_Mohammad.zip"; do [ -f "$f.vor_block23d_2026-09-18" ] && cp -p "$f.vor_block23d_2026-09-18" "$f"; done; echo fertig
```

**Danach prüfen:** `pruefung_block23.py` muss wieder **171** Prüfungen melden
(die 23c-Fassung), nicht 186.

**Nur das Logo zurück neben den Namen, sonst nichts?** Das geht nicht über
`maildesign.json` — es ist der Aufbau der Signaturvorlage in
`maildesign_bauen.py`. Der Abschnitt trägt einen Kommentar, der beide Wege
erklärt; die Vorfassung liegt als `.vor_block23d_2026-09-18` daneben.

---

## Block 23c — Logo eingebettet, runder Kreis, Kontaktblock (18.09.2026)

**Was zurückgerollt wird:** das eingebettete Logo, die quadratischen
Logodateien, der Head-Office-Kontaktblock mit Telefonnummer, die kleinere
GROUP-Zeile.

**Was das bedeutet:** Danach ist das Logo wieder ein Netzbild — Apple Mail zeigt
es erst nach „Bilder laden". Die Logodatei ist wieder 252 × 256 px, der Kreis
also wieder ein Ei. Die Zeile „Contact by email only" steht wieder in jeder
Signatur, die Telefonnummer ist wieder weg, HEAD OFFICE beginnt wieder mit dem
Rechtsträger, und die GROUP-Zeile steht wieder auf 13 px.

Zwei Zeilen, **beide ausführen, in dieser Reihenfolge.**

```
cd ~/"Library/Mobile Documents/com~apple~CloudDocs/GOTT WALD HOLDING/13_Korrespondenz/Email-Setting" && for f in maildesign.json maildesign_bauen.py signaturpaket_bauen.py signaturen.json README_POSTAUSGANG.md Rahmen/*.html Signaturen_Email/Signatur_*/*.html Signaturen_Email/Signatur_*/*_TEXT.txt Signaturen_Email/Signatur_*/assets/gottwald-logo.png Signaturen_Email/Signatur_Dween_Mohammad_DIN/Installation_Guide.pdf Signaturen_Email/Vorschau/*_Gmail.html Signaturen_Email/Vorschau/*_Outlook.html; do [ -f "$f.vor_block23c_2026-09-18" ] && cp -p "$f.vor_block23c_2026-09-18" "$f"; done; echo fertig
```

```
cd ~/"Library/Mobile Documents/com~apple~CloudDocs/GOTT WALD HOLDING" && for f in 00_Marken/JACK/jack_postfaecher.py 00_Marken/JACK/RUECKROLLWEGE.md 00_Marken/JACK/ACTIVE_CONTEXT.md 00_Marken/JACK/abnahme/Block23_2026-09-17/pruefung_block23.py "08_Mitarbeiter/Dween_Mohammad/ALLGEMEIN/Dokumente/CI/Signature_Package_Dween_Mohammad.zip" 00_Marken/GOTT_WALD_Holding/04_Web_Code/GOTT-WALD-World/public/signatur/gottwald-logo.png; do [ -f "$f.vor_block23c_2026-09-18" ] && cp -p "$f.vor_block23c_2026-09-18" "$f"; done && launchctl kickstart -k gui/$(id -u)/world.gottwald.jack.server
```

**Danach prüfen:** `python3 00_Marken/JACK/abnahme/Block23_2026-09-17/pruefung_block23.py`
muss wieder **136 von 136** melden (die Block-23b-Fassung). Meldet sie 171, ist
die zweite Zeile nicht gelaufen.

**Was liegen bleibt und nichts kaputt macht:** der Ordner
`13_Korrespondenz/Email-Setting/logo/` mit den quadratischen Dateien, die Belege
unter `abnahme/Block23c_2026-09-18/`, die Entscheidung unter
`entscheidungen/2026-09-18_block23c_maildesign.md` und der archivierte
MEISTERWERK-Vorschlag unter `99_Archiv/`. Nichts davon wird gelesen, wenn die
alten Dateien liegen.

**Nur das eingebettete Logo zurücknehmen, sonst nichts?** In `maildesign.json`
den Schlüssel `logo.cid` leeren — dann findet `logo_einbetten()` keine cid und
lässt den Körper unverändert. Kein Neubau nötig, der Versand liest die Datei
bei jedem Senden frisch.

---

## Block 23b — Maildesign-Nachbesserung (18.09.2026)

**Was zurückgerollt wird:** die sieben Änderungen vom 18.09.2026 — Logo 72 px,
heller Kopf, vier bündige Signaturzeilen, HEAD OFFICE, dreizeilige GROUP,
Handy-Maße. Danach steht wieder der Auftritt vom 17.09.2026, 21:31 — der, den
der Patron grundsätzlich angenommen hat.

**Was das bedeutet:** Der Kopf ist wieder tiefschwarz, das Logo wieder 48 px,
die Rolle steht wieder mit dem Rechtsträger in einer Zeile, die PLHH-Zeile
wieder eingerückt, der Block heißt wieder REGISTERED OFFICE ohne Tamari und
ohne Office-Adresse, und die GROUP-Zeile ist wieder eine einzige.

Zwei Zeilen, **beide ausführen, in dieser Reihenfolge.**

```
cd ~/"Library/Mobile Documents/com~apple~CloudDocs/GOTT WALD HOLDING/13_Korrespondenz/Email-Setting" && for f in maildesign.json maildesign_bauen.py signaturpaket_bauen.py signaturen.json README_POSTAUSGANG.md Rahmen/*.html Signaturen_Email/Signatur_*/*.html Signaturen_Email/Signatur_*/*_TEXT.txt Signaturen_Email/Signatur_Dween_Mohammad_DIN/Installation_Guide.pdf Signaturen_Email/Vorschau/*_Gmail.html Signaturen_Email/Vorschau/*_Outlook.html; do [ -f "$f.vor_block23b_2026-09-18" ] && cp -p "$f.vor_block23b_2026-09-18" "$f"; done; echo fertig
```

```
cd ~/"Library/Mobile Documents/com~apple~CloudDocs/GOTT WALD HOLDING" && for f in 00_Marken/JACK/jack_postfaecher.py 00_Marken/JACK/RUECKROLLWEGE.md 00_Marken/JACK/ACTIVE_CONTEXT.md 00_Marken/JACK/abnahme/Block23_2026-09-17/pruefung_block23.py "08_Mitarbeiter/Dween_Mohammad/ALLGEMEIN/Dokumente/CI/Signature_Package_Dween_Mohammad.zip"; do [ -f "$f.vor_block23b_2026-09-18" ] && cp -p "$f.vor_block23b_2026-09-18" "$f"; done && launchctl kickstart -k gui/$(id -u)/world.gottwald.jack.server
```

**Danach prüfen:** `python3 00_Marken/JACK/abnahme/Block23_2026-09-17/pruefung_block23.py`
muss wieder **80 von 80** melden (die Block-23-Fassung der Prüfung). Meldet sie
136, ist die zweite Zeile nicht gelaufen.

**Was liegen bleibt und nichts kaputt macht:** die Belege unter
`abnahme/Block23b_2026-09-18/`, die Entscheidung unter
`entscheidungen/2026-09-18_block23b_maildesign_nachbesserung.md` und
`abnahme/Block23b_2026-09-18/testmail_block23b.py`. Sie erzählen, was war.

**Nur den Kopf zurückholen, sonst nichts?** Geht: in `maildesign.json`
`verwendung.kopf_grund.farbe` auf `#020C12`, `kopf_firmenname.farbe` auf
`#F4F4F2`, `kopf_webadresse.farbe` auf `#D4AF37`, `mass.logo_px` auf `48` —
dann `python3 maildesign_bauen.py`. Dafür gibt es die eine Quelle.

---

## Block 23 — Maildesign neu: Kopf, Signatur, Fußzeile (17.09.2026)

**Was zurückgerollt wird:** der gesamte neue Mailauftritt — die 13 Markenrahmen,
alle 21 neu erzeugten Signaturen samt Textfassungen, die 26 Vorschauseiten, die
Rollen in `signaturen.json`, DINs Rolle in den Stammdaten, der CI-Leitfaden mit
seinem PDF, das Signaturpaket und die vier Änderungen im Versand
(Vorschautext, Grußformel mit Namen, 15 px / 1,6 / 70 Zeichen, Nur-Text-Fassung).

**Was das bedeutet:** Danach steht wieder der Auftritt, den der Patron am
17.09.2026 um 20:30 abgelehnt hat — doppelter Firmenname im Kopf, Firmenname
statt Vorschautext im Postfach, Türkis als Linkfarbe, die GROUP-Zeile dreifarbig,
die Anschrift zweimal, „p.p. JACK" in DINs Signatur und „Thank you," ohne Namen.

Zwei Zeilen, weil die Dateien in zwei Ordnern liegen. **Beide ausführen, in
dieser Reihenfolge.**

```
cd ~/"Library/Mobile Documents/com~apple~CloudDocs/GOTT WALD HOLDING/13_Korrespondenz/Email-Setting" && for f in signaturen.json README_POSTAUSGANG.md Rahmen/*.html Signaturen_Email/Signatur_*/*.html Signaturen_Email/Signatur_*/*_TEXT.txt Signaturen_Email/Signatur_Dween_Mohammad_DIN/ANLEITUNG.md Signaturen_Email/Vorschau/*_Gmail.html Signaturen_Email/Vorschau/*_Outlook.html; do [ -f "$f.vor_block23_2026-09-17" ] && cp -p "$f.vor_block23_2026-09-17" "$f"; done; echo fertig
```

```
cd ~/"Library/Mobile Documents/com~apple~CloudDocs/GOTT WALD HOLDING" && for f in 00_Marken/JACK/jack_postfaecher.py 00_Marken/JACK/RUECKROLLWEGE.md 00_Marken/JACK/ACTIVE_CONTEXT.md 08_Mitarbeiter/Dween_Mohammad/00_Stammdaten/stammdaten.json "08_Mitarbeiter/Dween_Mohammad/ALLGEMEIN/Dokumente/CI/2026-09-17_GOTT-WALD_CI-Quick-Guide_v1_Quelle.html" "08_Mitarbeiter/Dween_Mohammad/ALLGEMEIN/Dokumente/CI/2026-09-17_GOTT-WALD_CI-Quick-Guide_v1.pdf" "08_Mitarbeiter/Dween_Mohammad/ALLGEMEIN/Dokumente/CI/Signature_Package_Dween_Mohammad.zip"; do [ -f "$f.vor_block23_2026-09-17" ] && cp -p "$f.vor_block23_2026-09-17" "$f"; done && launchctl kickstart -k gui/$(id -u)/world.gottwald.jack.server
```

**Danach prüfen:** `python3 00_Marken/JACK/abnahme/Block22_2026-09-17/test_block22.py`
muss weiterhin 42 von 42 melden. Die Block-23-Prüfung schlägt dann fehl — das
ist richtig so, sie prüft ja den zurückgerollten Zustand.

**Was liegen bleibt und nichts kaputt macht:**
`maildesign.json`, `maildesign_bauen.py` und `signaturpaket_bauen.py` bleiben
stehen. Sie werden von nichts gelesen, solange die alten Rahmen liegen — der
alte `rahmen()` kennt keine Platzhalter. Ebenso bleiben die Belege unter
`abnahme/Block23_2026-09-17/` und die Entscheidung unter
`entscheidungen/2026-09-17_block23_maildesign.md`.

**Der eine Sonderfall:** Rollt man nur den ersten Befehl zurück und nicht den
zweiten, stehen die alten Rahmen mit dem neuen Versand zusammen. Dann bliebe der
Vorschautext leer und die Fußzeile trüge die Anschrift wieder doppelt. Deshalb:
**immer beide Zeilen.**

---

## Block 22 — Freigabekette für Mitarbeiter-Mails (17.09.2026)

**Was zurückgerollt wird:** die Sperre „erst Testversand an den Patron, dann
Freigabe", der feste SMTP-Umschlag beim Testversand, die Kopie im
Gesendet-Ordner und die letzten fünf Mails auf der ÜBERSICHT.

**Was das bedeutet:** Danach kann eine Mitarbeiter-Mail wieder mit einem
einzigen Klick auf FREIGEBEN hinausgehen, ohne dass der Patron sie je gesehen
hat. Genau das ist am 17.09.2026 um 19:10 passiert. Diese Zeile also nur
verwenden, wenn die Sperre selbst kaputt ist — nicht, weil sie im Weg steht.

```
cd ~/"Library/Mobile Documents/com~apple~CloudDocs/GOTT WALD HOLDING/00_Marken/JACK" && for f in index.html jack_mitarbeiter.py jack_oberflaeche.py jack_postfaecher.py server.py RUECKROLLWEGE.md ACTIVE_CONTEXT.md; do cp -p "$f.vor_block22_2026-09-17" "$f"; done && launchctl kickstart -k gui/$(id -u)/world.gottwald.jack.server
```

Die neue Datei `betrieb/testversand_vermerke.json` bleibt danach liegen und
wird von nichts mehr gelesen. Sie wird nicht gelöscht — sie ist der Nachweis,
welche Mail wann beim Patron war. Ebenso bleibt der angepasste Abnahmetest
`abnahme/Block21_2026-09-17/test_block21.py`; sein Stand vor Block 22 liegt
daneben als `test_block21.py.vor_block22_2026-09-17`.

---

## Rechtsstandards (17.09.2026) — Abteilung 30_Recht startbar

Rollt **nur** die JACK-Dateien zurück. Playbook, Website und Verträge stehen in
`entscheidungen/2026-09-17_rechtsstandards_umsetzung.md`, Abschnitt „Rückrollweg".

```
cd ~/"Library/Mobile Documents/com~apple~CloudDocs/GOTT WALD HOLDING/00_Marken/JACK" && for f in arbeiter_agenten.json jack_modelle.py agenten/BESETZUNG.md agenten/README_AGENTEN.md ACTIVE_CONTEXT.md; do cp -p "$f.vor_rechtsstandards_2026-09-17" "$f"; done && /usr/bin/python3 -I jack_modelle.py
```

Die letzte Ausgabe muss `"status": "geprueft"` enthalten. Tut sie das nicht, ist
die Rücknahme unvollständig — dann **nicht** weiterarbeiten, sondern nachsehen.
Die Rollendatei `agenten/30_Recht/recht-fachkraft.md` und die Erfahrungsdatei
`agenten/99_Erfahrung/recht-fachkraft.md` bleiben liegen; sie schaden nicht,
solange die Rolle nicht registriert ist.

---

## Signaturen, DIN-Mail und Testversand (17.09.2026)

Drei Dinge in einem Block: die neue GROUP-Zeile in allen Signaturen, die
DIN-Mail mit zwei statt fünf Anhängen, und der Knopf TESTVERSAND AN PATRON.

**Zeile 1 — Code und Maske zurück:**

```
cd ~/"Library/Mobile Documents/com~apple~CloudDocs/GOTT WALD HOLDING/00_Marken/JACK" && for f in index.html server.py jack_postfaecher.py jack_oberflaeche.py jack_mitarbeiter.py RUECKROLLWEGE.md ACTIVE_CONTEXT.md; do cp -p "$f.vor_signatur_2026-09-17" "$f"; done && launchctl kickstart -k gui/$(id -u)/world.gottwald.jack.server
```

**Zeile 2 — alle 82 Signaturdateien zurück** (jede liegt als
`<datei>.vor_signatur_2026-09-17` neben sich):

```
cd ~/"Library/Mobile Documents/com~apple~CloudDocs/GOTT WALD HOLDING" && find 13_Korrespondenz/Email-Setting 08_Mitarbeiter/Dween_Mohammad -name "*.vor_signatur_2026-09-17" -print0 | while IFS= read -r -d "" s; do cp -p "$s" "${s%.vor_signatur_2026-09-17}"; done
```

**Zeile 3 — die DIN-Karte und ihr Entwurf zurück:**

```
cd ~/"Library/Mobile Documents/com~apple~CloudDocs/GOTT WALD HOLDING/00_Marken/JACK" && cp -p auftraege/freigabe/2026-09-17_165533_MITARBEITER_Your_signature_our_CI_guide_and_your_fir.md.vor_signatur_2026-09-17 auftraege/freigabe/2026-09-17_165533_MITARBEITER_Your_signature_our_CI_guide_and_your_fir.md && cp -p betrieb/entwuerfe/2026-09-17_165533_mitarbeiter_Your-signature--our-CI-guide---and-your-first-ta_6aad93.md.vor_signatur_2026-09-17 betrieb/entwuerfe/2026-09-17_165533_mitarbeiter_Your-signature--our-CI-guide---and-your-first-ta_6aad93.md
```

Danach muss

```
grep -c "PATRONOS.AI" ../../13_Korrespondenz/Email-Setting/Signaturen_Email/Signatur_Tamari_Kapanadze_Office/*_TEXT.txt
```

**0** melden. Meldet es 1, ist die Rücknahme unvollständig — dann nicht
weiterarbeiten, sondern nachsehen.

**Was liegen bleibt — mit Absicht:**

| Bleibt | Warum |
|---|---|
| `Signature_Package_Dween_Mohammad.zip`, `Installation_Guide.pdf`, `Installation_Guide_Quelle.html` | neu; nach der Rücknahme zeigt niemand mehr darauf. Gelöscht wird nichts |
| `abnahme/Signatur_Testversand_2026-09-17/` | Belege. Sie erzählen, was war |

**🔴 Was keine Rücknahme erreicht:** Signaturen, die schon in ein
Mailprogramm eingesetzt wurden. Die sind Kopien und leben dort weiter — in
beide Richtungen. Wer die alte Zeile zurückhaben will, muss sie dort von Hand
neu einsetzen.

## Logo „J Ornament" (17.09.2026)

Nimmt das neue Logo zurück und stellt das goldene Didot-J wieder her — in der
Maske, im Server, in den Bilddateien **und** im Symbol der JACK.app.

```
cd ~/"Library/Mobile Documents/com~apple~CloudDocs/GOTT WALD HOLDING/00_Marken/JACK" && for f in index.html server.py RUECKROLLWEGE.md ACTIVE_CONTEXT.md; do cp -p "$f.vor_logo_ornament_2026-09-17" "$f"; done && cp -p logo/vor_logo_ornament_2026-09-17/JACK.icns logo/vor_logo_ornament_2026-09-17/jack_logo_1024.png logo/vor_logo_ornament_2026-09-17/jack_logo_512.png logo/vor_logo_ornament_2026-09-17/jack_logo_192.png logo/vor_logo_ornament_2026-09-17/jack_logo_180.png logo/vor_logo_ornament_2026-09-17/jack_logo.svg logo/ && cp -p logo/vor_logo_ornament_2026-09-17/JACK.iconset/*.png logo/JACK.iconset/ && cp -p logo/JACK.icns /Applications/JACK.app/Contents/Resources/JACK.icns && touch /Applications/JACK.app && /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f /Applications/JACK.app && killall Dock && launchctl kickstart -k gui/$(id -u)/world.gottwald.jack.server
```

Danach muss `curl -s localhost:8778/logo.svg -o /dev/null -w "%{content_type}"`
wieder **image/svg+xml** melden. Meldet es `image/png`, ist die Rücknahme
unvollständig — dann nicht weiterarbeiten, sondern nachsehen.

**Was liegen bleibt — mit Absicht:**

| Bleibt | Warum |
|---|---|
| `logo/favicon-16.png`, `favicon-32.png`, `apple-touch-icon.png` | neu; nach der Rücknahme zeigt niemand mehr darauf. Gelöscht wird nichts |
| `logo/quelle_2026-09-17/` | die Quelldatei des Patrons |
| `logo/vor_logo_ornament_2026-09-17/` | die Sicherung selbst |
| `abnahme/Logo_Ornament_2026-09-17/`, `entscheidungen/2026-09-17_logo_j_ornament.md` | Belege. Sie erzählen, was war |

**Am iPhone wirkt die Rücknahme nicht von selbst.** Das Symbol am
Home-Bildschirm ist eine Kopie aus dem Augenblick des Anlegens. Es muss von
Hand entfernt und neu angelegt werden — derselbe Weg wie beim Einführen.

## Block 21 — Mitarbeiter-Bereich (17.09.2026)

Rollt die **elf** geänderten Dateien zurück (zehn hier, dazu `signaturen.json`). Alles Neue bleibt liegen —
siehe unten. Die Zeile enthält auch `13_Korrespondenz/Email-Setting/signaturen.json`;
deshalb sind es zwei `cd`-Sprünge in einer Zeile.

```
cd ~/"Library/Mobile Documents/com~apple~CloudDocs/GOTT WALD HOLDING/00_Marken/JACK" && for f in index.html server.py jack_postfaecher.py jack_oberflaeche.py jack_betrieb.py betrieb/postfaecher.json betrieb/oberflaeche.json betrieb/README_POSTFAECHER.md ACTIVE_CONTEXT.md NAECHSTE_SCHRITTE.md; do cp -p "$f.vor_block21_2026-09-17" "$f"; done && cp -p ../../13_Korrespondenz/Email-Setting/signaturen.json.vor_block21_2026-09-17 ../../13_Korrespondenz/Email-Setting/signaturen.json && launchctl kickstart -k gui/$(id -u)/world.gottwald.jack.server
```

Danach muss `/usr/bin/python3 -I abnahme/test_freigaben.py` weiter „alle 6
Pruefungen bestanden" melden. Tut es das nicht, ist die Rücknahme unvollständig.

### 🔴 Den Nachtrag allein zurückzunehmen geht NICHT

Hier stand bis zum 17.09.2026, 17:45 eine Zeile, die nur `jack_mitarbeiter.py`
und `betrieb/README_MITARBEITER.md` zurückgestellt hat. **Die Zeile war falsch
und ist entfernt.** Befund 2 der unabhängigen Prüfung:

`server.py`, `jack_oberflaeche.py` und `jack_postfaecher.py` rufen **18 Namen**
auf, die es in `jack_mitarbeiter.py.vor_nachtrag_2026-09-17` nicht gibt — unter
anderem `schritte`, `skillprofil`, `messung`, `bericht_pruefen`,
`ist_mitarbeiteradresse`, `direkte_frage`. In `server.py` sind diese Aufrufe
ungeschützt: jeder Klick auf einen Mitarbeiter-Weg hätte danach HTTP 500
geliefert, ohne dass irgendetwas davor gewarnt hätte.

**Richtig ist deshalb:** Wer den Nachtrag loswerden will, nimmt **den ganzen
Block 21** zurück (die Zeile oben). Die Sicherung `.vor_nachtrag_2026-09-17`
bleibt liegen — sie ist zum **Nachlesen** gut, nicht zum Zurückrollen.

**Was diese Zeilen NICHT zurückrollen — mit Absicht:**

| Bleibt liegen | Warum |
|---|---|
| `jack_mitarbeiter.py`, `jack_whatsapp_import.py` | neu, es gibt keinen früheren Stand. Ohne die Aufrufe in `server.py`, `jack_betrieb.py` und `jack_postfaecher.py` lädt sie niemand |
| `betrieb/mitarbeiter*.json*`, `betrieb/mitarbeiter.jsonl` | neue Betriebsdateien, werden von nichts mehr gelesen |
| `08_Mitarbeiter/Dween_Mohammad/` mit `akte_index.jsonl` | **Das ist ein Bestand, kein Programmstand.** Eine Akte wird nie zurückgerollt |
| `13_Korrespondenz/…/Signatur_Dween_Mohammad_DIN/` und `…/Signatur_JACK_Office_of_the_Patron/` | Dateien, keine Programmlogik. Ohne Eintrag in `signaturen.json` benutzt sie niemand |
| `abnahme/Block21_2026-09-17/`, `entscheidungen/2026-09-17_…` | Belege. Sie erzählen, was war |
| `betrieb/README_MITARBEITER.md` | neu; beschreibt dann einen Stand, den es nicht mehr gibt — schadet aber nichts |

## Block 20 — RSS-Feeds

```
cd ~/"Library/Mobile Documents/com~apple~CloudDocs/GOTT WALD HOLDING/00_Marken/JACK" && for f in index.html jack_oberflaeche.py jack_web_cli.py arbeiter.sh server.py ACTIVE_CONTEXT.md; do cp -p "$f.vor_block20_2026-09-17" "$f"; done && launchctl kickstart -k gui/$(id -u)/world.gottwald.jack.server
```

## Block 19 — Funktions-Disziplin

```
cd ~/"Library/Mobile Documents/com~apple~CloudDocs/GOTT WALD HOLDING/00_Marken/JACK" && for f in index.html jack_betrieb.py jack_oberflaeche.py server.py ACTIVE_CONTEXT.md; do cp -p "$f.vor_block19_2026-09-17" "$f"; done && launchctl kickstart -k gui/$(id -u)/world.gottwald.jack.server
```

## Block 18 — Gedächtnis-Bereinigung

```
cd ~/"Library/Mobile Documents/com~apple~CloudDocs/GOTT WALD HOLDING/00_Marken/JACK" && for f in index.html jack_betrieb.py jack_oberflaeche.py jack_speicher.py server.py ACTIVE_CONTEXT.md; do cp -p "$f.vor_block18_2026-09-17" "$f"; done && launchctl kickstart -k gui/$(id -u)/world.gottwald.jack.server
```

## Block 17 — Verbindungsüberwachung

```
cd ~/"Library/Mobile Documents/com~apple~CloudDocs/GOTT WALD HOLDING/00_Marken/JACK" && for f in index.html jack_oberflaeche.py jack_wache.py server.py ACTIVE_CONTEXT.md; do cp -p "$f.vor_block17_2026-09-17" "$f"; done && launchctl kickstart -k gui/$(id -u)/world.gottwald.jack.server
```

## Block 16b — Nachtrag (Goldtitel, Servergruppe, Postfachauswertung)

```
cd ~/"Library/Mobile Documents/com~apple~CloudDocs/GOTT WALD HOLDING/00_Marken/JACK" && for f in jack_oberflaeche.py index.html jack_verbindungen.py ACTIVE_CONTEXT.md; do cp -p "$f.vor_block16c_2026-09-17" "$f"; done && launchctl kickstart -k gui/$(id -u)/world.gottwald.jack.server
```

## Block 16b — Nachbesserungen

```
cd ~/"Library/Mobile Documents/com~apple~CloudDocs/GOTT WALD HOLDING/00_Marken/JACK" && for f in index.html jack_oberflaeche.py server.py; do cp -p "$f.vor_block16b_2026-09-17" "$f"; done && launchctl kickstart -k gui/$(id -u)/world.gottwald.jack.server
```

## Block 16 — Freigabe sichtbar

```
cd ~/"Library/Mobile Documents/com~apple~CloudDocs/GOTT WALD HOLDING/00_Marken/JACK" && for f in index.html jack_oberflaeche.py server.py ACTIVE_CONTEXT.md; do cp -p "$f.vor_block16_2026-09-17" "$f"; done && launchctl kickstart -k gui/$(id -u)/world.gottwald.jack.server
```

---

## Was diese Zeilen NICHT zurückrollen

Die vier Module aus der Kette A (`jack_verbindungen.py`, `jack_gedaechtnis.py`,
`jack_nutzung.py`, `jack_rss.py`) bleiben liegen. Sie sind neu, es gibt also
keinen früheren Stand. Ohne die Aufrufe in `server.py` und `jack_betrieb.py`
lädt sie niemand — sie liegen dann still herum und tun nichts.

Neue Betriebsdateien (`betrieb/verbindungen*.json*`, `betrieb/nutzung.jsonl`,
`betrieb/rss_quellen.json`, `betrieb/rss/`, `betrieb/gedaechtnis_bereinigung.*`)
bleiben ebenfalls liegen. Sie werden von nichts mehr gelesen.

## Wie jede Zeile geprüft wurde

* `bash -n` auf jede Zeile — sie ist syntaktisch gültig.
* Trockenlauf mit `echo` statt `cp` — jeder Pfad wurde aufgelöst und jede
  Sicherungsdatei als vorhanden nachgewiesen.

Beleg: `abnahme/Sichtpruefung_Block16b_2026-09-17/P2_Rueckrollwege_geprueft.txt`

## Block 25 (18.09.2026) — Sprachsteuerung, Wissensleiter, Außenwelt

Sicherungen vor der ersten Änderung dieses Laufs:
`server.py.vor_block25_2026-09-17` (weiterverwendet, siehe V3),
`index.html.vor_block25_2026-09-17` (weiterverwendet),
`jack_erweiterungen.py.vor_block25_2026-09-17` (weiterverwendet, unverändert
geblieben — diese Datei wurde in diesem Lauf gar nicht bearbeitet),
`jack_betrieb.py.vor_block25_2026-09-18`,
`jack_oberflaeche.py.vor_block25_2026-09-18` (beide nachträglich
rekonstruiert, siehe Mangel-Notiz in
`entscheidungen/2026-09-18_Block25_Entscheidungen_im_Lauf.md`, Abschnitt E5).
`ACTIVE_CONTEXT.md.vor_block25_2026-09-18` sichert die alte Regel-Fassung
(V1). Neue Dateien ohne Vorzustand: `jack_steuerungsprotokoll.py`,
`jack_ablage_suche.py`, `jack_aussenwelt.py` — Rückrollweg dafür ist
Löschen, kein Zurückspielen.

**Ein Rückrollbefehl für alles Bestehende:**
```
cp server.py.vor_block25_2026-09-17 server.py
cp index.html.vor_block25_2026-09-17 index.html
cp jack_betrieb.py.vor_block25_2026-09-18 jack_betrieb.py
cp jack_oberflaeche.py.vor_block25_2026-09-18 jack_oberflaeche.py
cp ACTIVE_CONTEXT.md.vor_block25_2026-09-18 ACTIVE_CONTEXT.md
rm -f jack_steuerungsprotokoll.py jack_ablage_suche.py jack_aussenwelt.py
```
Danach den Dienst wie in `BETRIEB_UND_ABNAHME.md` beschrieben neu starten.

**Was dieser Rückrollweg NICHT betrifft:** `jack_steuerung.py` (Block 25,
Teil B — bereits vor diesem Lauf fertig und geprüft, unverändert),
`betrieb/steuerung_katalog.json` (dito). Neue Betriebsdateien
(`betrieb/steuerung.jsonl`, `betrieb/steuerung_unbekannt.jsonl`) bleiben
liegen — sie werden ohne den obigen Code von nichts mehr geschrieben oder
gelesen.

**Wichtig — mindestens ein zweiter Faden** hat in diesem Zeitraum ebenfalls
an denselben Dateien geschrieben (siehe
`entscheidungen/2026-09-18_Block25_Entscheidungen_im_Lauf.md`). Ein Rückroll
auf die Stände von 2026-09-17 würde auch dessen Arbeit verwerfen, nicht nur
diese hier — vor einem echten Rückroll den Patron das prüfen lassen.

## Block 26 (18.09.2026) — Entscheidungsregeln, Karten-Hygiene, Autonomie-Quote, Bremsen-Bericht

Sicherung vor der ersten Änderung: `jack_betrieb.py.vor_block26_2026-09-18`
(rekonstruiert und byteweise gegen die aktuelle Datei verifiziert — siehe
`entscheidungen/2026-09-18_Block26_Entscheidungen_im_Lauf.md`, Abschnitt 2,
für den vollen Hergang). Betrieb_routine.py wurde NICHT verändert (ruft
`jack_betrieb.tick()` bereits generisch auf). Neue Dateien ohne Vorzustand:
`betrieb/entscheidungsregeln.json`, `jack_regeln.py`, `jack_autonomie.py`,
`jack_bremsen.py` — Rückrollweg dafür ist Löschen bzw. Entfernen aus dem
Einhängepunkt, kein Zurückspielen.

**Rückrollbefehl für jack_betrieb.py:**
```
cp jack_betrieb.py.vor_block26_2026-09-18 jack_betrieb.py
```
Das entfernt die Autonomie-Zeile aus `brief()` und die drei neuen Bausteine
(`jack_regeln`, `jack_autonomie`, `jack_bremsen`) aus `tick()`. Die drei
neuen Module selbst bleiben liegen, werden aber nicht mehr aufgerufen.

**Rückrollweg für bewegte Karten:** JEDE Bewegung von `jack_regeln.py`
steht mit `von` und `nach` in `betrieb/regelentscheidungen.jsonl` — eine
Karte zurückzuholen heißt: die Datei von `nach` nach `von` zurückverschieben
und den angehängten „## Regelentscheidung ..."-Absatz am Dateiende
entfernen. Kein Inhalt wurde je gelöscht, nur verschoben.

**Was dieser Rückrollweg NICHT betrifft:** die Freigabekette Block 22
(unverändert), `jack_postfaecher.py`/`jack_oberflaeche.py` (nicht
angefasst, Block 26 arbeitet nachgelagert auf den bereits erzeugten
Karten), `server.py`/`index.html` (Teil 2 wurde nicht begonnen, siehe
`entscheidungen/2026-09-18_Block26_Entscheidungen_im_Lauf.md` Abschnitt 4 —
kein Dienst-Neustart in diesem Block).

Weitere Sicherungen vor Änderung (Text-Anhänge, ganz am Ende):
`ACTIVE_CONTEXT.md.vor_block26_2026-09-18`, `NAECHSTE_SCHRITTE.md.vor_block26_2026-09-18`.
Rückrollbefehl je eine Zeile:
```
cp ACTIVE_CONTEXT.md.vor_block26_2026-09-18 ACTIVE_CONTEXT.md
cp NAECHSTE_SCHRITTE.md.vor_block26_2026-09-18 NAECHSTE_SCHRITTE.md
```

## Block 26 — Nachtrag N1-N3 (18.09.2026) — Karenzzeit, R9, Sicherungs-Hook

Sicherung VOR der ersten Änderung diesmal vorab angelegt (nicht nachträglich
rekonstruiert wie beim Hauptlauf): `jack_regeln.py.vor_block26_nachtrag_2026-09-18`,
`02_Dokumente/INTERN/CLAUDE.md.vor_block26_nachtrag_2026-09-18` (Original der
Holding-CLAUDE.md, `CLAUDE.md` in der Wurzel ist nur ein Symlink darauf).
Neue Dateien ohne Vorzustand: `lib/sicherung_hook.py`, `.claude/settings.json`,
`.claude/aktueller_block`.

**Rückrollbefehl jack_regeln.py (N1 Karenzzeit + aktiver Vorgang, N2 Regel R9):**
```
cp jack_regeln.py.vor_block26_nachtrag_2026-09-18 jack_regeln.py
```
Entfernt die Karenzzeit-/Aktiv-Vorgang-Prüfung und Regel R9 wieder; die
übrige Block-26-Logik (R1-R5, R7) bleibt unverändert erhalten.

**Rückrollbefehl CLAUDE.md (N3, ein Satz unter A5):**
```
cp "02_Dokumente/INTERN/CLAUDE.md.vor_block26_nachtrag_2026-09-18" "../../02_Dokumente/INTERN/CLAUDE.md"
```
(Pfad relativ zu diesem Ordner — von der Holding-Wurzel aus:
`cp "02_Dokumente/INTERN/CLAUDE.md.vor_block26_nachtrag_2026-09-18" "02_Dokumente/INTERN/CLAUDE.md"`.)

**Rückrollweg N3 Sicherungs-Hook:** `lib/sicherung_hook.py`, `.claude/settings.json`
und `.claude/aktueller_block` sind neu — Rückrollweg ist Löschen:
```
cd ~/"Library/Mobile Documents/com~apple~CloudDocs/GOTT WALD HOLDING/00_Marken/JACK" && rm -f lib/sicherung_hook.py .claude/settings.json .claude/aktueller_block
```
Betrifft NICHT `betrieb/sicherungen_hook.jsonl` (Protokoll, bleibt liegen)
oder `.claude/hook_sicherungen_stand.json` (Session-Merkliste, kann bleiben
oder gelöscht werden — enthält keine Geheimnisse, nur Dateipfade).

**Was dieser Nachtrag NICHT betrifft:** Teil 2 (weiterhin nicht begonnen,
wartet jetzt zusätzlich auf „## Block 25b", siehe N4), server.py/index.html
(unverändert), die Freigabekette Block 22 (unverändert).

## Block 25b (18.09.2026) — Gesprächsfluss: Echo-Sperre, Doppel-Schutz, Satzvorlagen

Sicherung vor der ersten Änderung (`*.vor_block25b_2026-09-18`):
`server.py`, `index.html`, `jack_steuerung.py`, `ACTIVE_CONTEXT.md`,
`NAECHSTE_SCHRITTE.md`, `RUECKROLLWEGE.md`, `betrieb/README_SPRACHSTEUERUNG.md`.
Neue Dateien ohne Vorzustand (Rückrollweg dafür ist Löschen, nicht
Zurückspielen): `jack_sprache.py`, `lib/jack_sprache.js`,
`betrieb/sprache_saetze.json`, `betrieb/sprache_woerterbuch.json`, sowie die
vier Testdateien und Berichte unter `abnahme/Block25b_2026-09-18/`.
`jack_aussenwelt.py` und `jack_steuerungsprotokoll.py` wurden ebenfalls
geändert, aber erst NACH Block 25b überhaupt zum ersten Mal (keine
Vor-Sicherung nötig — sie existierten unveraendert seit Block 25, ihr voller
Vorzustand steht bereits in dessen eigenem `.vor_block25_2026-09-18`, falls
vorhanden, sonst in Git-losem Zustand über die 99_Archiv-Kopie dieses
Auftrags nachvollziehbar).

**Rückrollbefehl (alles auf einmal):**
```
cd "~/Library/Mobile Documents/com~apple~CloudDocs/GOTT WALD HOLDING/00_Marken/JACK" \
  && for f in server.py index.html jack_steuerung.py ACTIVE_CONTEXT.md NAECHSTE_SCHRITTE.md \
              RUECKROLLWEGE.md betrieb/README_SPRACHSTEUERUNG.md; do \
       cp -p "$f.vor_block25b_2026-09-18" "$f"; done \
  && rm -f jack_sprache.py lib/jack_sprache.js betrieb/sprache_saetze.json betrieb/sprache_woerterbuch.json \
  && launchctl kickstart -k gui/$(id -u)/world.gottwald.jack.server
```
`jack_aussenwelt.py`/`jack_steuerungsprotokoll.py` haben keinen eigenen
Rückrollbefehl in diesem Block — ihre Änderungen sind additiv (eine neue
Fallunterscheidung bzw. zwei neue Funktionen) und werden von keinem anderen
Modul mehr aufgerufen, sobald `server.py`/`jack_steuerung.py` zurückgerollt
sind; sie bleiben harmlos liegen.

**Was dieser Block NICHT betrifft:** Block 26 (`jack_regeln.py`,
`jack_autonomie.py`, `jack_bremsen.py`, `jack_betrieb.py` — nicht angefasst),
Block 23c (`jack_postfaecher.py`, `jack_mitarbeiter.py`,
`13_Korrespondenz/Email-Setting` — nicht angefasst, nur `jack_postfaecher.py`
und `jack_mitarbeiter.py` per Lesezugriff aufgerufen wie bisher), Messtest
27.1 (`jack_lokal*.py`, `jack_messtest.py`, `modell_router.py`,
`betrieb/lokal_modell.json`, `betrieb/kostenstufen.json`, `lokal.nosync/` —
nicht angefasst), die Freigabekette Block 22 (unverändert).

## Block 26, Teil 2 (18.09.2026) — Empfehlung, Einzelentscheidung, Hausaufgaben, R6, Autonomie-Anzeige, Neustart

Sicherung VOR der ersten Änderung (einmalig, vor jeder Datei in dieser
Liste): `server.py.vor_block26_teil2_2026-09-18`,
`index.html.vor_block26_teil2_2026-09-18`,
`jack_steuerung.py.vor_block26_teil2_2026-09-18`,
`jack_regeln.py.vor_block26_teil2_2026-09-18`,
`jack_oberflaeche.py.vor_block26_teil2_2026-09-18`,
`jack_autonomie.py.vor_block26_teil2_2026-09-18`,
`betrieb/steuerung_katalog.json.vor_block26_teil2_2026-09-18`,
`ACTIVE_CONTEXT.md.vor_block26_teil2_2026-09-18`,
`RUECKROLLWEGE.md.vor_block26_teil2_2026-09-18`,
`NAECHSTE_SCHRITTE.md.vor_block26_teil2_2026-09-18`. Diese Sicherungen
liegen VOR den Block-27/28-Änderungen an denselben Dateien — ein Rückroll
auf diesen Stand würde auch Block 27 (Freigabecode-Pflicht) und Block 28
(Schutz wartender Mitarbeiter-Karten) verwerfen, siehe Warnung unten.

**Rückrollbefehl (alles auf einmal):**
```
cd "~/Library/Mobile Documents/com~apple~CloudDocs/GOTT WALD HOLDING/00_Marken/JACK" \
  && for f in server.py index.html jack_steuerung.py jack_regeln.py jack_oberflaeche.py \
              jack_autonomie.py betrieb/steuerung_katalog.json ACTIVE_CONTEXT.md \
              RUECKROLLWEGE.md NAECHSTE_SCHRITTE.md; do \
       cp -p "$f.vor_block26_teil2_2026-09-18" "$f"; done \
  && launchctl kickstart -k gui/$(id -u)/world.gottwald.jack.server
```
**🔴 Wichtig:** Dieser EINE Befehl rollt auch die inzwischen (später, im selben
Sitzungsfenster) gelandeten Blöcke 27 und 28 zurück, soweit sie dieselben
Dateien angefasst haben (`server.py`, `index.html`, `jack_regeln.py`,
`jack_oberflaeche.py`) — insbesondere die Freigabecode-Pflicht (Block 27)
und den Schutz wartender Mitarbeiter-Karten (Block 28) wären dann wieder
weg. Vor einem echten Rückroll immer zuerst prüfen, ob Block 27/28 seither
ebenfalls zurückgerollt werden sollen, und wenn nicht, deren Änderungen von
Hand erneut einspielen (siehe deren eigene Abschnitte weiter oben und
`entscheidungen/2026-09-18_block27_versandfreigabe.md`,
`entscheidungen/2026-09-18_block28_wartende_mitarbeiterkarte.md`).

**Neue Dateien ohne Vorzustand:** keine — alle Änderungen liegen in bereits
bestehenden Dateien. `betrieb/r6_verarbeitet.jsonl` entsteht neu bei der
ersten tatsächlichen Anwendung von R6 (T2.4) — Rückrollweg dafür ist
Löschen, kein Zurückspielen: `rm -f betrieb/r6_verarbeitet.jsonl`.

**Rückrollweg für die sechs am 18.09.2026 bereinigten Doppel-Empfehlungen**
(eigener Wettlauf-Fund, siehe `entscheidungen/2026-09-18_Block26_Teil2_
Entscheidungen.md`, Abschnitt 3): nicht nötig zurückzurollen — der jeweils
ERSTE (vollständige) „## Empfehlung von JACK"-Abschnitt blieb in jeder der
sechs Karten stehen, nur der identische zweite wurde entfernt. Kein
Karteninhalt ging verloren.

**Was dieser Block NICHT betrifft:** `jack_postfaecher.py`, `jack_mitarbeiter.py`
(nicht angefasst — nur aufgerufen, wie von PARALLELBETRIEB verlangt; Block 27
und Block 28 haben diese beiden Dateien unabhängig von Teil 2 geändert, siehe
deren eigene Rückrollabschnitte), die Freigabekette Block 22 (unverändert),
`jack_betrieb.py`/`betrieb_routine.py` (Teil 2 hängt sich NICHT dort ein —
`jack_regeln.tick()` ruft `empfehlungen_erzeugen()`/`standberichte_pruefen()`
bereits selbst auf, kein neuer Einhängepunkt nötig).

---

## S-1 „Verstehen zuerst“ (24.09.2026, Arbeiter „JACK Sprache“)

**Alle Sicherungen** heißen `<datei>.vor_S1_2026-09-24` und liegen neben dem Original:
`server.py`, `jack_steuerung.py`, `jack_sprache.py`, `lib/jack_sprache.js`, `jack_dialog.py`,
`jack_sprach_eingang.py`, `jack_steuerungsprotokoll.py`, `jack_betrieb.py`, `jack_sprachdiagnose.py`,
`index.html`, `betrieb/sprache_saetze.json`, `betrieb/sprache_woerterbuch.json`,
`betrieb/README_SPRACHSTEUERUNG.md`, `NAECHSTE_SCHRITTE.md`, `RUECKROLLWEGE.md`,
`abnahme/Gespraechsfluss_2026-09-21/test_dialog.py`, `abnahme/Sichtpruefung_Block18_2026-09-17/test_gedaechtnis.py`.

**Neue Dateien (ohne Vorzustand):** `jack_hausnamen.py`, `betrieb/sprache_gegenproben.json`,
`betrieb/sprache_hausnamen.json` (entsteht bei jedem Dienststart), `abnahme/S1_2026-09-24/`.

**Rückroll in einem Schritt** (alle zusammen, weil sie sich gegenseitig voraussetzen — `server.py` lädt
`jack_hausnamen`, `jack_steuerung.py` ebenfalls):
`for f in <Liste oben>; do cp -p "$f.vor_S1_2026-09-24" "$f"; done`, danach die drei neuen Dateien in
`99_Archiv/_Papierkorb_zur_Pruefung/` verschieben (nichts löschen), Dienst neu starten
(`launchctl kickstart -k gui/$(id -u)/world.gottwald.jack.server`), HTTP 200 auf `/status` prüfen.
Einzeln zurückrollbar sind nur die reinen Datenstände (`betrieb/sprache_saetze.json`,
`betrieb/sprache_woerterbuch.json`). **`index.html` NICHT aus `.vor_S1_2026-09-24` zurückkopieren:** die Sicherung
enthält die parallel entstandenen F-18-Änderungen (Bereich Berichte) nicht. Für S-1 in `index.html` von Hand nur
zurücknehmen: die Funktion `erstTonSprechende` samt `let sprechendeFuerFrage, erstTonSprechendeBasis`, die zwei
Aufrufe `erstTonSprechende();` hinter `sprachMessung('erstes_audio_ab_frage',…)`, die Zeile
`erstTonSprechendeBasis=sprechendeFuerFrage;…` in `frage()` und die Zeile `sprechendeFuerFrage = MESSUNG.sprechende || 0;`
in `ohrSenden()` (dann fehlt nur diese Messung). Die Ein-Schritt-Schleife oben daher ohne `index.html` ausführen. Bei einem Teil-Rückroll von `server.py` alleine würde `jack_steuerungsprotokoll.merken(..., herkunft=...)`
scheitern; deshalb immer `jack_steuerungsprotokoll.py` und `jack_betrieb.py` mit zurückrollen.

---

## S-2 „Tempo“ (24.09.2026, Arbeiter „JACK Sprache")

**Sicherungen:** `<datei>.vor_S2_2026-09-24` neben dem Original für `server.py`, `jack_sprach_eingang.py`,
`jack_stimme_lokal.py`, `modell_router.py`, `jack_hausnamen.py`, `jack_steuerung.py`, `betrieb/sprache_saetze.json`,
`betrieb/sprache_gegenproben.json`, `betrieb/README_SPRACHSTEUERUNG.md`, `RUECKROLLWEGE.md`, `NAECHSTE_SCHRITTE.md`,
`abnahme/Block25b_2026-09-18/test_stufe0_live.py`, `abnahme/Mail_und_Gespraechsfluss_2026-09-21/test_mail_gespraechsfluss.py`.
(`index.html` blieb in S-2 unverändert.)
**Neue Dateien:** `betrieb/sprache_dialog_stufen.json`, `abnahme/S2_2026-09-24/` (Messstand, Tests, Messungen).
**Zurückrollen:** die genannten Dateien aus `.vor_S2_2026-09-24` zurückkopieren (alle zusammen — `server.py` ruft
`jack_sprach_eingang._server_beenden` und `modell_router.dialog_stufe`), `betrieb/sprache_dialog_stufen.json` nach
`99_Archiv/_Papierkorb_zur_Pruefung/` verschieben, Dienst neu starten; ein eventuell verwaister `whisper-server`
muss danach von Hand beendet werden (`pgrep -fl whisper-server`, dann `kill <PID>`; die zurückgerollte Fassung hat keine Waisen-Bereinigung).
**`NAECHSTE_SCHRITTE.md` und `RUECKROLLWEGE.md` NICHT aus der Sicherung zurückkopieren** — sie enthalten seither Einträge anderer Kanäle (z. B. F-21); stattdessen den S-2-Abschnitt/-Text von Hand entfernen. **Nur die Modellwahl abschalten:** in
`betrieb/sprache_dialog_stufen.json` `"stufe_schnell_aktiv": false` setzen (kein Neustart nötig) — dann antwortet wieder
immer das große Modell; `"denken"` in `stark` auf `"aus"`/`"niedrig"`/`"mittel"` stellt die Nachdenktiefe ein.

---

## S-2b „Tempo-Rest“ (25.09.2026, Arbeiter „JACK Sprache“)
**Sicherungen** `<datei>.vor_S2b_2026-09-25`: `server.py`, `jack_sprach_eingang.py`, `jack_hausnamen.py`, `modell_router.py`, `jack_betrieb.py` (unverändert geblieben — nur gesichert), `betrieb/sprache_dialog_stufen.json`, `betrieb/sprache_saetze.json`, `betrieb/README_SPRACHSTEUERUNG.md`, `RUECKROLLWEGE.md`, `NAECHSTE_SCHRITTE.md`, `abnahme/S2_2026-09-24/test_s2_tempo.py`, `abnahme/Gespraechsfluss_2026-09-21/test_dialog.py`.
**Neue Dateien:** `jack_sprach_lage.py`, `betrieb/sprache_lage.json` (entsteht laufend), `abnahme/S2b_2026-09-25/`.
**Zurückrollen:** die genannten Dateien aus der Sicherung zurückkopieren — aber **nicht** `NAECHSTE_SCHRITTE.md`/`RUECKROLLWEGE.md` (fremde Einträge); dort den S-2b-Text von Hand entfernen. `jack_sprach_lage.py` nach `99_Archiv/_Papierkorb_zur_Pruefung/` verschieben, Dienst neu starten. **Nur die Lage abschalten:** in `server.py` die Zeile `threading.Thread(target=lagefaden …)` entfernen und in `frage_jack` den Block „S-2b P1“ — oder schneller: die Datei `betrieb/sprache_lage.json` löschen lassen ist wirkungslos (wird neu geschrieben); deshalb Rückroll über die Sicherung.
S-2b-Nachtrag (25.09.): `jack_sprach_lage.py` hat ein Format-Feld `version`; eine Lage-Datei anderer Version wird sofort neu berechnet. In `server.py` neu: Warnung bei gekürzter Mail-Suche (`_werkzeug_mail_suchen`), Satzgrenze vor der Abriss-Ansage. Alles über die Sicherung `.vor_S2b_2026-09-25` zurückrollbar.

---

## S-2c Netzaufrufe (25.09.2026, Arbeiter „JACK Sprache“)
**Sicherungen** `<datei>.vor_S2c_2026-09-25`: `server.py`, `jack_kalender.py`, `jack_sprachdiagnose.py`, `betrieb/README_SPRACHSTEUERUNG.md`, `RUECKROLLWEGE.md`, drei angepasste Tests (`test_s2_tempo.py`, `test_s1_verstehen.py`, `test_mail_gespraechsfluss.py`). **Neu:** `jack_netzwiederholung.py`, `abnahme/S2c_2026-09-25/`.
**Zurückrollen:** `server.py`, `jack_kalender.py`, `jack_sprachdiagnose.py` aus der Sicherung zurückkopieren — Achtung: `server.py.vor_S2c` enthält den Stand nach S-2b; spätere Änderungen anderer Kanäle vorher per Diff prüfen. `jack_netzwiederholung.py` nach `99_Archiv/_Papierkorb_zur_Pruefung/`, Dienst neu starten.

---

## S-3 Persona, Merken, Stimmen (25.09.2026, Arbeiter „JACK Sprache“)
**Sicherungen** `<datei>.vor_S3_2026-09-25`: `server.py`, `jack_dialog.py`, `jack_sprache.py`, `lib/jack_sprache.js`, `betrieb/sprache_dialog_stufen.json`, `betrieb/README_SPRACHSTEUERUNG.md`, `RUECKROLLWEGE.md`, `NAECHSTE_SCHRITTE.md`, fünf angepasste Tests (`test_s1_verstehen.py`, `test_s2_tempo.py`, `test_dialog.py`, zwei `test_server_review.py` unter Groq_*). **Neu:** `jack_tonpruefung.py`, `abnahme/S3_2026-09-25/`, `stimme/piper.nosync/` und `stimme/piper-stimmen.nosync/` (nur lokal, Hörproben).
**Zurückrollen:** die Dateien aus der Sicherung zurückkopieren (NICHT `NAECHSTE_SCHRITTE.md`/`RUECKROLLWEGE.md` — fremde Einträge; dort den S-3-Text von Hand entfernen), Dienst neu starten. **Nur die Persona zurück:** in `server.py` `SYSTEM_DIALOG` durch `SYSTEM` ersetzen (2 Stellen in `frage_jack` und eine im Ersatzweg `_rueckfall_versuchen`, dort `jack_dialog.PERSONA` zurück auf den alten Satz „Du bist JACK, KI-Geschäftspartner des Patrons …“) und die alte `REGELN` aus `jack_dialog.py.vor_S3_2026-09-25` einsetzen. **Nur die schnelle Stufe wieder an:** `"stufe_schnell_aktiv": true` in `betrieb/sprache_dialog_stufen.json`. `loest_stopp_aus` (Python und JS) ist gestrichen; Rückweg nur über die Sicherungen von `jack_sprache.py` und `lib/jack_sprache.js`. Stimm-Werkzeuge unter `stimme/*.nosync` nach `99_Archiv/_Papierkorb_zur_Pruefung/` verschieben, wenn sie nicht gebraucht werden (nichts im Betrieb hängt daran).

---

## S-3b Feinschliff (25.09.2026, Arbeiter „JACK Sprache“)
**Sicherungen** `<datei>.vor_S3b_2026-09-25`: `server.py`, `jack_dialog.py`, `modell_router.py`, `jack_tonpruefung.py`, `betrieb/sprache_dialog_stufen.json`, `betrieb/README_SPRACHSTEUERUNG.md`, `RUECKROLLWEGE.md`, `NAECHSTE_SCHRITTE.md`, angepasste Tests (`test_s1_verstehen.py`, `test_s2_tempo.py`, `test_dialog.py`, `test_s3.py`), `PREISTABELLE_ANBIETER.md`. **Neu:** `jack_sprechfilter.py`, `abnahme/S3b_2026-09-25/`, `abnahme/S3_2026-09-25/buchungsplan*.{json,py}`, `herzschlag_sprache.sh`.
**Zurückrollen:** Dateien aus der Sicherung zurückkopieren (NICHT `NAECHSTE_SCHRITTE.md`/`RUECKROLLWEGE.md`), Dienst neu starten. **Nur den Sprechfilter aus:** in `server.py` die zwei Stellen `jack_sprechfilter.Satzfilter`/`jack_sprechfilter.filtere` entfernen. **Nur das Routing zurück:** `betrieb/sprache_dialog_stufen.json` aus der Sicherung. **Merken-Sperre zurück:** `jack_dialog.py.vor_S3b_2026-09-25` (Stand nach S-3 mit Wortliste).

---

## S-5 Zählfragen und Wissensquellen (25.09.2026, Arbeiter „JACK Sprache“)
**Sicherungen** `<datei>.vor_S5_2026-09-25`: `server.py`, `jack_betrieb.py`, `betrieb/patron_profil.jsonl`, `betrieb/gespraeche.jsonl` (unverändert, nur Sicherung), `betrieb/README_SPRACHSTEUERUNG.md`, `RUECKROLLWEGE.md`. **Neu:** `jack_sprach_zahlen.py`, `betrieb/sprache_wissensquellen.json`, `betrieb/sprache_ausschluss.json`, `abnahme/S5_2026-09-25/`.
**Zurückrollen:** `server.py` und `jack_betrieb.py` aus der Sicherung, Dienst neu starten. **Nur die Zählfragen aus:** in `server.py` den Block „S-5 P1“ in `frage_jack` entfernen. **Nur der Ausschluss aus:** `betrieb/sprache_ausschluss.json` mit `{"zeiten": []}` ersetzen. **Wissensquellen aus:** Datei umbenennen (Nachschlagen fällt still zurück).

---

## S-6 Handy-Vollansicht (25.09.2026, Arbeiter „JACK Sprache“)
**Sicherungen** `<datei>.vor_S6_2026-09-25`: `index.html`, `server.py`, `betrieb/README_SPRACHSTEUERUNG.md`, `RUECKROLLWEGE.md`. **Neu:** `jack_sprach_handy.py`, `abnahme/S6_2026-09-25/`.
**Zurückrollen:** `index.html` aus der Sicherung kopieren (kein Neustart nötig); `server.py` aus der Sicherung, Dienst neu starten. **Nur die Skulptur wieder immer zeigen:** in `index.html` die Zeile `body.vollfenster #kernfeld{display:none}` entfernen. **Nur der Gehirn-Auszug aus:** in `server.py` den Block „S-6“ in `/gehirn/karte` entfernen.

---

## S-3c Faktentreue (25.09.2026, Arbeiter „JACK Sprache“)
**Sicherungen** `<datei>.vor_S3c_2026-09-25`: `jack_dialog.py`, `jack_sprach_lage.py`, `jack_sprechfilter.py`, `jack_netzwiederholung.py`, `jack_kalender.py`, `server.py`, `modell_router.py`, `betrieb/sprache_dialog_stufen.json`, README, RUECKROLLWEGE, `test_s3b.py`, `test_s3.py`, `test_s2c.py`, `test_s2_tempo.py`. **Neu:** `abnahme/S3c_2026-09-25/`.
**Zurückrollen:** Dateien aus der Sicherung zurückkopieren (nicht `NAECHSTE_SCHRITTE.md`/`RUECKROLLWEGE.md`), Dienst per `neustart_sicher.sh` neu starten. **Nur die Regeln zurück:** `jack_dialog.py.vor_S3c_2026-09-25`. **Nur der Filter zurück:** `jack_sprechfilter.py.vor_S3c_2026-09-25`. **Nur die Netz-Änderung zurück:** `jack_netzwiederholung.py`, `jack_kalender.py`, `server.py` aus der Sicherung.
