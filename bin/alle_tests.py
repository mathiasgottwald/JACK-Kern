#!/usr/bin/python3
"""F-91 (M-3b Nr. 1): EIN Runner fuer alle Testdateien (`unittest discover` findet im JACK-Ordner 0 von ~270, weil viele
Tests eigenstaendige Skripte sind). Startet jede abnahme/**/test_*.py einzeln mit Zeitlimit und fasst zusammen.
Aufruf: alle_tests.py [--zeit 60] [--muster f8]      Nichts wird geschrieben ausser der Zusammenfassung auf stdout.
Achtung: Tests, die Mail/Netz anfassen koennten (test_f47, test_f53, test_f28, test_f50 ...), sind absichtlich AUSGESCHLOSSEN."""
import argparse, subprocess, sys
from pathlib import Path
JACK = Path(__file__).resolve().parents[1]
AUSSCHLUSS = ("_veraltet_F91", "sicherung", "kandidat", "live_test",
              "/_alt/", "Block21_2026-09-17/test_block21.py", "Block22_2026-09-17/test_block22.py", "/staende/", "site-packages", "/python/", "node_modules", "lokal.nosync", "_browser.py")   # NACHT kern 2026-09-30: Fremdbibliotheken und Browser-Laeufe nicht mitzaehlen
p = argparse.ArgumentParser(); p.add_argument("--zeit", type=int, default=60); p.add_argument("--muster", default="")
a = p.parse_args()
dateien = sorted(x for x in (JACK / "abnahme").rglob("test_*.py") if not any(t in str(x) for t in AUSSCHLUSS) and a.muster in str(x))
rot, gruen, zeit = [], 0, []
for d in dateien:
    try:
        r = subprocess.run([sys.executable, str(d)], capture_output=True, text=True, timeout=a.zeit, cwd=str(d.parent))
        (gruen := gruen + 1) if r.returncode == 0 else rot.append(d.relative_to(JACK))
    except subprocess.TimeoutExpired:
        zeit.append(d.relative_to(JACK))
print("%d Dateien: %d gruen, %d rot, %d Zeitueberschreitung" % (len(dateien), gruen, len(rot), len(zeit)))
for x in rot: print("ROT  ", x)
for x in zeit: print("ZEIT ", x)
sys.exit(1 if rot or zeit or not dateien else 0)
