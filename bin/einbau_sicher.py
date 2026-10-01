#!/usr/bin/env python3
"""F-75 (28.09.2026): verallgemeinerter Einbauweg fuer Kanäle, die eine Arbeitskopie (ausserhalb iCloud, Muster
`~/Arbeitskopien/JACK-<kanal>/`) auf die Live-Wurzel zurueckspielen wollen — Kollisionsschutz fuer index.html,
server.py, lib/* (nur `kern` aendert diese sonst direkt). Verallgemeinert aus `abnahme/S16_2026-09-25/einbau_S18.py`
(Vorprüfung Live == erwarteter Stand, sonst Abbruch statt Ueberschreiben; Sicherung vor jedem Schreiben;
Rueckbau bei Teilfehler).

Ablauf:
1. Arbeitskopie anlegen (rsync-Kopie der betroffenen Dateien), dort bauen und TESTEN (eigener Port, nie 8778).
2. `einbau_sicher.py <kanal> <arbeitskopie> --erstellen <datei> [<datei> ...]`
   Schreibt `_EINBAU_MANIFEST.json` in die Arbeitskopie: sha256 der aktuellen LIVE-Version jeder genannten Datei
   (der Stand, aus dem die Arbeitskopie gebaut wurde) — direkt nach dem Anlegen der Arbeitskopie aufrufen.
3. `einbau_sicher.py <kanal> <arbeitskopie> [--trocken]`
   Liest das Manifest. Prueft je Datei: Live-Hash == Manifest-Hash? Weicht auch nur eine Datei ab (jemand hat
   Live inzwischen geaendert), wird NICHTS geschrieben (Exit 3) - "neu aufsetzen, nicht ueberschreiben".
   Stimmt alles: `--trocken` meldet nur "wuerde einbauen" (Exit 0); ohne `--trocken` wird jede Datei zuerst nach
   `<live_datei>.vor_<kanal>_<JJJJMMTT_HHMMSS>` gesichert, dann aus der Arbeitskopie ueberschrieben. Schlaegt das
   Schreiben einer Datei fehl, werden alle bereits geschriebenen Dateien aus ihren Sicherungen zurueckgestellt
   (Teilfehler-Rueckbau).
Kein Neustart hier - danach genau einmal ueber `bin/neustart_sicher.sh` (Ruhe-Regel), nur bei jack_ruhe frei.
"""
import datetime as dt
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

JACK = Path(os.environ.get("JACK_EINBAU_WURZEL") or Path(__file__).resolve().parents[1])
MANIFEST_NAME = "_EINBAU_MANIFEST.json"


def _hash(pfad):
    if not pfad.is_file():
        return None
    h = hashlib.sha256()
    with pfad.open("rb") as f:
        for stueck in iter(lambda: f.read(65536), b""):
            h.update(stueck)
    return h.hexdigest()


def erstellen(kanal, arbeitskopie, dateien):
    manifest = {}
    for rel in dateien:
        live_datei = JACK / rel
        h = _hash(live_datei)
        if h is None:
            raise SystemExit("Live-Datei fehlt, kann nicht als Ausgangsstand gelten: %s" % rel)
        manifest[rel] = h
    (arbeitskopie / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Manifest geschrieben: %s (%d Datei(en))" % (arbeitskopie / MANIFEST_NAME, len(manifest)))
    return 0


def einbauen(kanal, arbeitskopie, trocken):
    manifest_pfad = arbeitskopie / MANIFEST_NAME
    if not manifest_pfad.is_file():
        raise SystemExit("Kein Manifest in der Arbeitskopie - vorher --erstellen aufrufen: %s" % manifest_pfad)
    manifest = json.loads(manifest_pfad.read_text(encoding="utf-8"))
    if not manifest:
        raise SystemExit("Manifest ist leer")

    abweichungen = []
    for rel, erwartet in manifest.items():
        ist = _hash(JACK / rel)
        if ist != erwartet:
            abweichungen.append(rel)
    if abweichungen:
        print("ABBRUCH: Live weicht vom erwarteten Ausgangsstand ab, nichts veraendert: %s" % ", ".join(abweichungen),
              file=sys.stderr)
        print("Neu aufsetzen (frische Arbeitskopie), nicht ueberschreiben.", file=sys.stderr)
        return 3

    fehlend = [rel for rel in manifest if not (arbeitskopie / rel).is_file()]
    if fehlend:
        raise SystemExit("In der Arbeitskopie fehlen Dateien aus dem Manifest: %s" % ", ".join(fehlend))

    if trocken:
        print("TROCKENLAUF ok: alle %d Datei(en) entsprechen noch dem Ausgangsstand, wuerde einbauen." % len(manifest))
        return 0

    zeit = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    fertig = []
    try:
        for rel in manifest:
            live_datei = JACK / rel
            sicherung = live_datei.parent / ("%s.vor_%s_%s" % (live_datei.name, kanal, zeit))
            if sicherung.exists():
                raise SystemExit("Sicherung existiert schon (nichts ueberschreiben): %s" % sicherung)
            shutil.copy2(live_datei, sicherung)
            shutil.copy2(arbeitskopie / rel, live_datei)
            fertig.append((rel, sicherung))
    except Exception as fehler:
        for rel, sicherung in fertig:
            shutil.copy2(sicherung, JACK / rel)
        print("EINBAU FEHLGESCHLAGEN (%s) - %d Datei(en) aus den Sicherungen zurueckgestellt." % (fehler, len(fertig)),
              file=sys.stderr)
        return 1
    print("EINGEBAUT (%d Datei(en), Sicherungen *.vor_%s_%s). Jetzt: Tests gegen Live, dann EIN Neustart ueber "
          "bin/neustart_sicher.sh." % (len(manifest), kanal, zeit))
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 2:
        raise SystemExit(__doc__)
    kanal, arbeitskopie = argv[0], Path(argv[1]).expanduser()
    rest = argv[2:]
    if not arbeitskopie.is_dir():
        raise SystemExit("Arbeitskopie nicht gefunden: %s" % arbeitskopie)
    if rest and rest[0] == "--erstellen":
        dateien = rest[1:]
        if not dateien:
            raise SystemExit("Aufruf: einbau_sicher.py <kanal> <arbeitskopie> --erstellen <datei> [<datei> ...]")
        return erstellen(kanal, arbeitskopie, dateien)
    trocken = "--trocken" in rest
    return einbauen(kanal, arbeitskopie, trocken)


if __name__ == "__main__":
    sys.exit(main())
