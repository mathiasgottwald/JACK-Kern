#!/usr/bin/python3
"""47.1 Aufgabe 4 (F-97): Obergrenze fuer Regeldateien (Lernregeln). Standard 150 Zeilen / 2.500 Tokens (Tokens = Zeichen/4, grob).
Aufruf: regeldatei_pruefen.py <datei> [--zeilen 150] [--tokens 2500]     Exit 0 = darunter, Exit 3 = darueber (dann VERDICHTEN, nicht wachsen lassen)
        regeldatei_pruefen.py --neue-regel <datei> "Text"                haengt EINE Zeile '- JJJJ-MM-TT · Anlass: Text' an, nur wenn die Grenze danach haelt (sonst Exit 3, nichts geschrieben; Sicherung .vor_regel_<zeit>)"""
import shutil
import sys
import time
from pathlib import Path


def masse(pfad):
    t = Path(pfad).read_text(encoding="utf-8")
    return len(t.splitlines()), len(t) // 4


def main(a):
    zeilen_max, tokens_max = 150, 2500
    if "--zeilen" in a:
        zeilen_max = int(a[a.index("--zeilen") + 1])
    if "--tokens" in a:
        tokens_max = int(a[a.index("--tokens") + 1])
    if a[1:2] == ["--neue-regel"] and len(a) >= 4:
        p, text = Path(a[2]), a[3].strip().replace("\n", " ")
        alt = p.read_text(encoding="utf-8") if p.exists() else ""
        neu = alt.rstrip("\n") + "\n- %s · Anlass: %s\n" % (time.strftime("%Y-%m-%d"), text)
        z, t = len(neu.splitlines()), len(neu) // 4
        if z > zeilen_max or t > tokens_max:
            print("GRENZE: %s haette danach %d Zeilen / ~%d Tokens (Grenze %d / %d) - erst verdichten" % (p.name, z, t, zeilen_max, tokens_max))
            return 3
        if p.exists():
            shutil.copy2(p, str(p) + ".vor_regel_" + time.strftime("%Y%m%d_%H%M%S"))
        p.write_text(neu, encoding="utf-8")
        print("Regel angefuegt (%d Zeilen, ~%d Tokens)" % (z, t))
        return 0
    if len(a) < 2:
        print(__doc__); return 2
    z, t = masse(a[1])
    ok = z <= zeilen_max and t <= tokens_max
    print("%s: %d Zeilen, ~%d Tokens (Grenze %d / %d) -> %s" % (Path(a[1]).name, z, t, zeilen_max, tokens_max, "OK" if ok else "ZU GROSS - verdichten"))
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main(sys.argv))
