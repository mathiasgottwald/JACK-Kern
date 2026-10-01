#!/usr/bin/python3
"""47.1 Aufgabe 2 (F-97): gemeinsame Sperrliste - zwei Terminals nie an derselben Datei (Regel 22b).
    sperrliste.py anmelden <kanal> <datei> [<datei> ...]   traegt die Dateien ein; Exit 3 + Meldung, wenn eine schon ein ANDERER Kanal haelt
    sperrliste.py pruefen  <kanal> <datei>                  Exit 0 = frei oder eigene, Exit 3 = gesperrt durch anderen Kanal (Hook/Pruefschritt vor dem Schreiben)
    sperrliste.py freigeben <kanal>                          gibt alle Dateien dieses Kanals frei
    sperrliste.py zeigen
Eintraege verfallen nach 12 Stunden (vergessene Sperren). Datei: betrieb/sperrliste.json (nur LESEN/SCHREIBEN dieser Liste - keine
Projektdatei wird veraendert). Die Pruefung VERWEIGERT und MELDET, sie ueberschreibt nie."""
import fcntl
import json
import os
import sys
import time
from pathlib import Path

JACK = Path(os.environ.get("JACK_SPERR_WURZEL") or Path(__file__).resolve().parents[1])
LISTE = JACK / "betrieb" / "sperrliste.json"
VERFALL_S = 12 * 3600


def _lesen():
    try:
        d = json.loads(LISTE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    jetzt = time.time()
    return {k: v for k, v in d.items() if jetzt - float(v.get("epoch", 0)) < VERFALL_S}


def _schreiben(d):
    LISTE.parent.mkdir(parents=True, exist_ok=True)
    tmp = LISTE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, LISTE)


def _norm(datei):
    return str(Path(datei).expanduser().resolve())


def _mit_schloss(fn):
    LISTE.parent.mkdir(parents=True, exist_ok=True)
    with open(LISTE.with_suffix(".lock"), "w") as l:
        fcntl.flock(l, fcntl.LOCK_EX)
        return fn()


def anmelden(kanal, dateien):
    def tun():
        d = _lesen()
        belegt = {}
        for f in dateien:
            k = _norm(f)
            if k in d and d[k]["kanal"] != kanal:
                belegt[k] = d[k]["kanal"]
        if belegt:
            return 3, belegt
        for f in dateien:
            d[_norm(f)] = {"kanal": kanal, "epoch": time.time(), "zeit": time.strftime("%Y-%m-%dT%H:%M:%S")}
        _schreiben(d)
        return 0, {}
    return _mit_schloss(tun)


def pruefen(kanal, datei):
    h = _lesen().get(_norm(datei))
    if h and h["kanal"] != kanal:
        return 3, h["kanal"]
    return 0, ""


def freigeben(kanal):
    def tun():
        d = {k: v for k, v in _lesen().items() if v["kanal"] != kanal}
        _schreiben(d)
        return 0
    return _mit_schloss(tun)


def main(argv):
    if len(argv) < 2:
        print(__doc__); return 2
    cmd = argv[1]
    if cmd == "anmelden" and len(argv) >= 4:
        code, belegt = anmelden(argv[2], argv[3:])
        for f, k in belegt.items():
            print("GESPERRT: %s wird von Kanal %s gehalten - nicht anfassen, Rueckfrage an PM" % (f, k))
        return code
    if cmd == "pruefen" and len(argv) == 4:
        code, k = pruefen(argv[2], argv[3])
        if code:
            print("GESPERRT: %s wird von Kanal %s gehalten - nicht anfassen" % (argv[3], k))
        return code
    if cmd == "freigeben" and len(argv) == 3:
        return freigeben(argv[2])
    if cmd == "zeigen":
        for f, v in _lesen().items():
            print(v["kanal"], v["zeit"], f)
        return 0
    print(__doc__); return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
