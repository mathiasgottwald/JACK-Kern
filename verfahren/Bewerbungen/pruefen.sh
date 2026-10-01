#!/bin/bash
# Abnahme-Muster fuer Verfahren "Bewerbungen" (B-3, Standard 47.1) - prueft EIN Bewerbungspaket
# gegen den HR-Manager-Standard (abnahme/pm_eingang/BEWERBUNGEN_ANSAGE_PM_2026-09-27.md, Punkt 2).
# Exit-Code 0 = alle Pflichtpruefungen bestanden. Exit-Code 1 = mindestens ein Befund, Text auf stderr.
# 0 USD, kein Netzwerk-/Anbieteraufruf, nur lokale Dateipruefung.
# Aufruf: pruefen.sh <Paketordner>   (absolut ODER relativ zu Bewerbungen/10_Stellen/)
set -u
HIER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JACK="$(cd "$HIER/../.." && pwd)"
BEWERBUNGEN="$(cd "$JACK/../MATHIAS_GOTTWALD/02_Dokumente/Bewerbungen" && pwd)"

PAKET="${1:?Paketordner fehlt, z.B. 10_Stellen/2026-09-27_EpicFusion_AI-Agent-Business-Consultant}"
if [ -d "$PAKET" ]; then
  ORDNER="$(cd "$PAKET" && pwd)"
elif [ -d "$BEWERBUNGEN/$PAKET" ]; then
  ORDNER="$(cd "$BEWERBUNGEN/$PAKET" && pwd)"
else
  echo "BEFUND: Paketordner nicht gefunden: $PAKET" >&2
  exit 1
fi

export PYTHONPATH="$JACK:${PYTHONPATH:-}"
python3 - "$ORDNER" "$BEWERBUNGEN" <<'PYEOF'
import re
import sys
from pathlib import Path

ordner = Path(sys.argv[1])
bewerbungen = Path(sys.argv[2])
befunde = 0


def pruefe(bedingung, text):
    global befunde
    if not bedingung:
        print("BEFUND: " + text, file=sys.stderr)
        befunde += 1


# (1) Eine Analyse-Datei existiert.
analysen = sorted(ordner.glob("00_Analyse_*.md"))
pruefe(bool(analysen), "keine 00_Analyse_*.md im Paketordner gefunden")

# (2) Die Analyse enthaelt alle fuenf Pflichtabschnitte des HR-Manager-Standards.
PFLICHT = ["Stellenanalyse", "Unternehmensrecherche", "Gehaltsrahmen", "Differenzierung", "Versandweg"]
if analysen:
    text = analysen[0].read_text(encoding="utf-8", errors="replace")
    for wort in PFLICHT:
        pruefe(wort.lower() in text.lower(), "Pflichtabschnitt '%s' fehlt in %s" % (wort, analysen[0].name))
else:
    befunde += len(PFLICHT)
    for wort in PFLICHT:
        print("BEFUND: Pflichtabschnitt '%s' nicht pruefbar - keine Analyse-Datei" % wort, file=sys.stderr)

# (3) Bewerbungsmappe mit mindestens einem Anschreiben- und einem Lebenslauf-PDF.
mappe = ordner / "Bewerbungsmappe"
pruefe(mappe.is_dir(), "kein Bewerbungsmappe/-Ordner im Paket")
if mappe.is_dir():
    pdfs = [p.name.lower() for p in mappe.glob("*.pdf")]
    pruefe(any("anschreiben" in p for p in pdfs), "kein Anschreiben-PDF in Bewerbungsmappe/")
    pruefe(any("lebenslauf" in p for p in pdfs), "kein Lebenslauf-PDF in Bewerbungsmappe/")

# (4) Der Tracker fuehrt einen Eintrag mit dem Paketordner-Pfad.
tracker = bewerbungen / "06_Tracker.md"
rel = None
try:
    rel = ordner.relative_to(bewerbungen).as_posix()
except ValueError:
    rel = ordner.name
if tracker.is_file():
    ttext = tracker.read_text(encoding="utf-8", errors="replace")
    pruefe(rel in ttext or ordner.name in ttext, "06_Tracker.md fuehrt keinen erkennbaren Eintrag zu '%s'" % rel)
else:
    pruefe(False, "06_Tracker.md nicht gefunden")

# (5) Versandsperren-Stichprobe: keine UEBERGABE_BEWERBUNG-Datei fuer dieses Paket behauptet einen
# Versand ohne dokumentierte Freigabe.
pm_eingang = bewerbungen.parents[3] / "00_Marken" / "JACK" / "abnahme" / "pm_eingang"
firma_hinweis = ordner.name.split("_", 2)[-1] if "_" in ordner.name else ordner.name
verdaechtig = []
if pm_eingang.is_dir():
    for f in pm_eingang.glob("UEBERGABE_BEWERBUNG_*.md"):
        t = f.read_text(encoding="utf-8", errors="replace").lower()
        if firma_hinweis.lower()[:12] in f.name.lower() and ("gesendet" in t or "versendet" in t) and "freigege" not in t:
            verdaechtig.append(f.name)
pruefe(not verdaechtig, "Uebergabe-Datei(en) behaupten Versand ohne erkennbare Freigabe: %s" % ", ".join(verdaechtig))

if befunde:
    print("Bewerbungspaket '%s': %d Befund(e)." % (ordner.name, befunde), file=sys.stderr)
    sys.exit(1)
print("Bewerbungspaket '%s': alle Pflichtpruefungen bestanden." % ordner.name)
sys.exit(0)
PYEOF
exit $?
