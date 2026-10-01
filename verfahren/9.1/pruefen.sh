#!/bin/bash
# Abnahme-Muster fuer Verfahren 9.1 (Cleanup) — F-70.
# Exit-Code 0 = alle vier Pflichtpruefungen technisch bestaetigt.
# Exit-Code 1 = mindestens ein Befund; Text dazu auf stderr.
# 0 USD, kein Netzwerk-/Anbieteraufruf, nur lokale Pruef- und ffmpeg/ffprobe-Logik.
set -u
HIER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JACK="$(cd "$HIER/../.." && pwd)"
export PYTHONPATH="$JACK:${PYTHONPATH:-}"

python3 - "$JACK" <<'PYEOF'
import sys, tempfile, subprocess
from pathlib import Path

jack = Path(sys.argv[1])
sys.path.insert(0, str(jack))
import jack_medien as M

befunde = 0

def pruefe(bedingung, text):
    global befunde
    if not bedingung:
        print("BEFUND: " + text, file=sys.stderr)
        befunde += 1

# (1) Unvollstaendige Kategorienliste wird abgelehnt.
try:
    M.cleanup_pruefliste({"personen": {"gefunden": False, "fundstellen": []}})
    pruefe(False, "unvollstaendige Cleanup-Pruefliste wurde NICHT abgelehnt")
except ValueError:
    pruefe(True, "")

# (2) gefunden=true ohne Fundstelle wird abgelehnt.
try:
    voll = {k: {"gefunden": False, "fundstellen": []} for k in M.CLEANUP_KATEGORIEN}
    voll["personen"] = {"gefunden": True, "fundstellen": []}
    M.cleanup_pruefliste(voll)
    pruefe(False, "gefunden=true ohne Fundstelle wurde NICHT abgelehnt")
except ValueError:
    pruefe(True, "")

# (3) Vollstaendige, gueltige Pruefliste wird angenommen.
try:
    voll = {k: {"gefunden": False, "fundstellen": []} for k in M.CLEANUP_KATEGORIEN}
    voll["kennzeichen"] = {"gefunden": True, "fundstellen": ["Sekunde 3, Nummernschild im Hintergrund"]}
    ergebnis = M.cleanup_pruefliste(voll)
    pruefe(ergebnis.get("art") == "jack_cleanup_pruefliste", "gueltige Pruefliste lieferte kein erwartetes Ergebnis")
except ValueError as e:
    pruefe(False, "gueltige, vollstaendige Pruefliste wurde faelschlich abgelehnt: %s" % e)

# (4) Ersatzflaeche mit falscher Pixelgroesse wird abgelehnt (nur, wenn ffmpeg/ffprobe lokal vorhanden sind).
if M.FFPROBE.is_file() and M.FFMPEG.is_file():
    with tempfile.TemporaryDirectory(dir=str(jack.parent.parent)) as tmp:
        tmpdir = Path(tmp)
        falsch = tmpdir / "falsch_32x32.png"
        subprocess.run([str(M.FFMPEG), "-y", "-f", "lavfi", "-i", "color=c=red:s=32x32", str(falsch)],
                       capture_output=True, timeout=20)
        rel = falsch.relative_to(jack.parent.parent)
        try:
            M._ersatzflaeche_pruefen(jack, str(rel), 64, 64)
            pruefe(False, "Ersatzflaeche mit falscher Pixelgroesse wurde NICHT abgelehnt")
        except ValueError as e:
            pruefe("exakt" in str(e), "falsche Fehlermeldung bei falscher Pixelgroesse: %s" % e)
else:
    print("HINWEIS: ffmpeg/ffprobe lokal nicht gefunden - Pruefung (4) uebersprungen", file=sys.stderr)

if befunde:
    sys.exit(1)
print("9.1 Cleanup: alle Pflichtpruefungen bestaetigt.")
sys.exit(0)
PYEOF
exit $?
