#!/usr/bin/env python3
"""F-75 (28.09.2026): sammelt alle offenen Patron-Punkte aus vier Quellen in EINE nummerierte Datei
`auftraege/freigabe/<datum>_ENTSCHEIDUNGSBLATT.md` (Nr · Thema · Optionen · Empfehlung · Frist). Antwortformat
des Patrons: "1 ja, 2 A, 3 nein". Kein Versand, nur Datei - die Karte erscheint im Dashboard wie jede andere
Freigabe (jack_oberflaeche.freigabenlage() liest jede .md mit Frontmatter aus auftraege/freigabe/, kein Code
noetig). Gedacht fuer einen taeglichen Lauf um 07:00 (siehe --launchd-vorschlag, NICHT installiert).

Quellen:
1. auftraege/freigabe/*.md mit status: freigabe UND freigabe: nein (offene Freigabe-Karten, ohne ersetzt/).
2. abnahme/pm_eingang/*_wartet_patron.md
3. auftraege/pm_ausgang/wartet_patron/*.md
4. betrieb/ENTSCHEIDUNGEN_FUER_DEN_PATRON.md: Abschnitte (## <datum> - <Titel>), deren Text NICHT bereits
   "Entschieden vom Patron"/"freigegeben"/"ABGELEHNT" enthaelt (= noch offen).

Aufruf: entscheidungsblatt.py [--trocken] [--launchd-vorschlag]
"""
import datetime as dt
import os
import re
import sys
from pathlib import Path

JACK = Path(os.environ.get("JACK_ENTSCHEIDUNG_WURZEL") or Path(__file__).resolve().parents[1])
FREIGABE = JACK / "auftraege" / "freigabe"
PM_EINGANG = JACK / "abnahme" / "pm_eingang"
WARTET_PATRON = JACK / "auftraege" / "pm_ausgang" / "wartet_patron"
ENTSCHEIDUNGEN = JACK / "betrieb" / "ENTSCHEIDUNGEN_FUER_DEN_PATRON.md"
RESOLVED_MARKER = re.compile(r"Entschieden vom Patron|freigegeben\b|ABGELEHNT", re.I)


def _kopf(text):
    m = re.match(r"^---\n(.*?)\n---\n?", text, re.S)
    if not m:
        return {}
    kopf = {}
    for zeile in m.group(1).splitlines():
        if ":" in zeile:
            k, _, v = zeile.partition(":")
            kopf[k.strip()] = v.split("#")[0].strip()
    return kopf


def _erster_satz(text, ab=0, laenge=200):
    rumpf = re.sub(r"^---.*?---\n?", "", text, flags=re.S).strip()
    rumpf = re.sub(r"^#.*$", "", rumpf, flags=re.M).strip()
    return " ".join(rumpf.split())[:laenge]


def _aus_freigabekarten():
    punkte = []
    if not FREIGABE.is_dir():
        return punkte
    for datei in sorted(FREIGABE.glob("*.md")):
        text = datei.read_text(encoding="utf-8", errors="replace")
        kopf = _kopf(text)
        if kopf.get("status") != "freigabe" or kopf.get("freigabe") != "nein":
            continue
        thema = (kopf.get("titel") or kopf.get("auftrag") or datei.stem).replace("_", " ")
        m = re.search(r"\*\*Empfehlung[^:]*:\*\*\s*(.+)", text)
        empfehlung = m.group(1).strip()[:150] if m else "keine explizite Empfehlung im Text"
        punkte.append({"thema": thema, "optionen": "FREIGEBEN / WARTEN / ABLEHNEN",
                        "empfehlung": empfehlung, "frist": "-", "quelle": "freigabe/%s" % datei.name})
    return punkte


def _aus_wartet_patron_dateien(ordner, quelle_praefix):
    punkte = []
    if not ordner.is_dir():
        return punkte
    muster = "*_wartet_patron.md" if quelle_praefix == "pm_eingang" else "*.md"
    for datei in sorted(ordner.glob(muster)):
        text = datei.read_text(encoding="utf-8", errors="replace")
        thema = datei.stem.replace("_wartet_patron", "").replace("_", " ")
        punkte.append({"thema": thema, "optionen": "siehe Datei", "empfehlung": _erster_satz(text)[:150],
                        "frist": "-", "quelle": "%s/%s" % (quelle_praefix, datei.name)})
    return punkte


def _aus_entscheidungslog():
    punkte = []
    if not ENTSCHEIDUNGEN.is_file():
        return punkte
    text = ENTSCHEIDUNGEN.read_text(encoding="utf-8", errors="replace")
    abschnitte = re.split(r"(?m)^## ", text)[1:]
    for a in abschnitte:
        zeilen = a.split("\n", 1)
        titel = zeilen[0].strip()
        rumpf = zeilen[1] if len(zeilen) > 1 else ""
        block = rumpf[:600]
        if RESOLVED_MARKER.search(block):
            continue
        punkte.append({"thema": titel, "optionen": "siehe Eintrag", "empfehlung": _erster_satz(block)[:150],
                        "frist": "-", "quelle": "betrieb/ENTSCHEIDUNGEN_FUER_DEN_PATRON.md#%s" % titel[:40]})
    return punkte


def sammeln():
    punkte = []
    punkte += _aus_freigabekarten()
    punkte += _aus_wartet_patron_dateien(PM_EINGANG, "pm_eingang")
    punkte += _aus_wartet_patron_dateien(WARTET_PATRON, "wartet_patron")
    punkte += _aus_entscheidungslog()
    return punkte


def blatt_text(punkte, datum):
    zeilen = [
        "---", "marke:      JACK", "auftrag:    Entscheidungsblatt_%s" % datum,
        "erteilt:    %s" % dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "von:        JACK (bin/entscheidungsblatt.py, F-75)", "status:     freigabe", "freigabe:   nein",
        "gefahr:     keine", "tiefe:      klein", "bereiche:   betrieb", "art:        entscheidungsblatt", "---", "",
        "# Entscheidungsblatt %s" % datum, "",
        "Antwortformat: **\"1 ja, 2 A, 3 nein\"** (Nr. + Entscheidung je Zeile, kommagetrennt).", "",
    ]
    if not punkte:
        zeilen.append("Keine offenen Punkte gefunden.")
    for i, p in enumerate(punkte, 1):
        zeilen += [
            "## %d. %s" % (i, p["thema"]),
            "**Optionen:** %s" % p["optionen"],
            "**Empfehlung:** %s" % p["empfehlung"],
            "**Frist:** %s" % p["frist"],
            "**Quelle:** `%s`" % p["quelle"], "",
        ]
    return "\n".join(zeilen)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--launchd-vorschlag" in argv:
        print(LAUNCHD_VORSCHLAG)
        return 0
    punkte = sammeln()
    datum = dt.date.today().isoformat()
    text = blatt_text(punkte, datum)
    ziel = FREIGABE / ("%s_ENTSCHEIDUNGSBLATT.md" % datum)
    if "--trocken" in argv:
        print("TROCKEN: wuerde schreiben nach %s (%d Punkt(e))" % (ziel, len(punkte)))
        print(text)
        return 0
    FREIGABE.mkdir(parents=True, exist_ok=True)
    ziel.write_text(text, encoding="utf-8")
    print("Geschrieben: %s (%d Punkt(e))" % (ziel, len(punkte)))
    return 0


LAUNCHD_VORSCHLAG = """Vorschlag (NICHT installiert, nur Text fuer die Meldung):
~/Library/LaunchAgents/world.gottwald.jack.entscheidungsblatt.plist
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>world.gottwald.jack.entscheidungsblatt</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/python3</string>
    <string>{JACK}/bin/entscheidungsblatt.py</string>
  </array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>7</integer><key>Minute</key><integer>0</integer></dict>
</dict></plist>
Einbau (nur nach Freigabe des Patrons): launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/world.gottwald.jack.entscheidungsblatt.plist
""".format(JACK=str(JACK))


if __name__ == "__main__":
    sys.exit(main())
