---
verfahren:        Social_Medienspeicher
titel:            Zentraler Medienspeicher für Social-Media-Beiträge (alle Marken)
quelle_auftrag:   CF-5 (28.09.2026), Patron-Entscheidung 17:00: bestehendes Supabase-Projekt, kein neuer Dienst
baut_auf:         jack_social.py (medien_bereitstellen/medien_archivieren)
status:           live seit 28.09.2026 (CF-5b) — echter Lauf gegen das tatsächliche Supabase-Projekt bestätigt
letzte_pruefung:  2026-09-28 (CF-5b, echter Upload/Download/Archivierung)
---

# Social_Medienspeicher — ein Speicher für alle Marken und Plattformen

Standard-Playbook nach `_VORLAGE_PLAYBOOK.md`. Instagram (und künftig weitere
Plattformen, die eine öffentlich erreichbare Bild-/Video-URL verlangen)
brauchen einen Ort, an dem ein Medium kurz öffentlich liegt, bevor es
veröffentlicht wird.

## (a) Aufgabenverständnis

Quelle: Patron-Entscheidung 28.09.2026, 17:00, wörtlich: „Wir machen das immer
so, wie es am besten ist … alles verbunden, alles läuft." Konkret: kein neuer
Dienst, sondern das bestehende Supabase-Projekt **gott-wald-holding**
(Projekt-Ref `pvhlbebzaxdnevpszubk`, Region eu-central-1/Frankfurt).

## (b) Feste Schritte, Werkzeuge, Modell/Aufwand

**Einstiegsfunktionen:** `jack_social.medien_bereitstellen(marke, medium_rel, nr, root)`,
`jack_social.medien_archivieren(bucket, objektpfad, root)`.

1. Lokales Bild (muss im Vault liegen, kein Symlink) hochladen in den
   öffentlichen Bucket `social-medien`, Pfadschema
   `<MARKE>/<JJJJ>/<MM>/<Datum>_<Nr>_<Kurzprüfsumme>.<Endung>`.
2. Rück-Download der öffentlichen URL, Bytevergleich mit dem Original — erst
   danach gilt das Bild als „bereitgestellt". Ohne diesen Nachweis kein Post
   (siehe `_Social_Instagram.md`, Tor-Punkt 7).
3. Nach einem erfolgreichen Post: Kopie in den **privaten** Archiv-Bucket
   `social-medien-archiv` (A5 — nur kopiert, das Original im öffentlichen
   Bucket wird **nicht automatisch entfernt**, das bräuchte eine eigene
   Freigabe-Entscheidung, siehe Meldung CF-5).

**Werkzeuge:** Supabase Storage REST-API (`urllib`, Standardbibliothek, kein
neues Paket). **Modell/Aufwand je Lauf:** kein Modellaufruf, reine
Dateiübertragung.

**Echte Bucket-Namen und URL-Muster (live seit CF-5b, 28.09.2026):**
- Öffentlicher Bucket: `social-medien`
- Privater Archiv-Bucket: `social-medien-archiv`
- Öffentliche URL: `https://pvhlbebzaxdnevpszubk.supabase.co/storage/v1/object/public/social-medien/<MARKE>/<JJJJ>/<MM>/<Datum>_<Nr>_<Kurzprüfsumme>.<Endung>`
- Beide Buckets über die Supabase-API angelegt (`POST /storage/v1/bucket`),
  nicht über das Dashboard — `social-medien` mit `"public": true`,
  `social-medien-archiv` mit `"public": false`.

## (c) Abnahme-Checkliste

```bash
python3 abnahme/CF5_2026-09-28/test_cf5.py   # Klasse "Medienspeicher", 0 = ok
```

**Echter Einsatz bereits erfolgt (CF-5b, 28.09.2026):** Dienstschlüssel
`GOTT_WALD_SUPABASE_HOLDING_DIENST` liegt seit 17:10 im Schlüsselbund. Beide
Buckets angelegt, ein echtes Testbild (`13_Korrespondenz/Email-Setting/
Briefpapier/CASHFLOW_KOMPASS/Vorschau_CASHFLOW_KOMPASS.png` — 01_Bilder und
05_Marketing der Marke enthielten kein Bild, deshalb dieses vorhandene
Markenbild als Ersatz, Annahme) hoch-, herunter- und archivieren lassen:
Prüfsumme öffentlich = Prüfsumme Archiv = `0a2effdc0529d4a1e296de82dfc24f252aef6d5953b91eba5f355ac0473cd327`,
Original-Datei lokal unverändert, Original-Objekt im öffentlichen Bucket
nicht gelöscht (A5).

## (d) Fehler und Korrekturen

**28.09.2026 (eigener Test vor Auslieferung):** Die Symlink-Prüfung griff
nicht, weil sie nach `.resolve()` lief (das löst den Symlink bereits auf,
`is_symlink()` sieht danach nur noch die echte Datei). Behoben: erst auf dem
unaufgelösten Pfad prüfen, dann auflösen.

## (e) Abgleich Fähigkeitsregister (vor dem Bau)

Kein bestehendes Playbook deckt einen zentralen Medienspeicher ab — echter
Neubau, im Fähigkeitsregister nachgetragen (Nachtrag CF-5).

## (f) Kosten je Lauf

0 USD zusätzlich — nutzt das bestehende Supabase-Projekt der Holding
(Speicherkosten fallen dort ohnehin an, kein neuer Vertrag).

## Grenzen

Keine automatische Entfernung aus dem öffentlichen Bucket (A5). `medien_bereitstellen`
setzt den Content-Type beim Hochladen fest auf `image/jpeg` (auch für PNG-Testbilder
wie im CF-5b-Lauf) — die Bytes selbst kommen unverändert zurück (belegt), die
MIME-Angabe im Speicher stimmt bei Nicht-JPEG-Bildern aber nicht; für echte
Social-Posts sind ohnehin nur JPEGs vorgesehen (siehe `_Social_Instagram.md`).
