#!/bin/bash
# Abnahme-Muster fuer Playbook "CEO_Statusbericht" (F-73). Aufruf: pruefen.sh <berichtsdatei.md>
# Exit-Code 0 = alle Pflichtpruefungen bestanden. Exit-Code 1 = Befund mit Text auf stderr.
set -u
DATEI="${1:-}"
if [ -z "$DATEI" ]; then
  echo "Aufruf: pruefen.sh <berichtsdatei.md>" >&2
  exit 1
fi
if [ ! -f "$DATEI" ]; then
  echo "BEFUND: Datei nicht gefunden: $DATEI" >&2
  exit 1
fi

BEFUNDE=0

for feld in "Marke:" "Zeitraum:" "Von:"; do
  wert=$(grep -m1 "^${feld}" "$DATEI" | sed "s/^${feld}//" | tr -d '[:space:]')
  if [ -z "$wert" ]; then
    echo "BEFUND: Kopf-Pflichtfeld '$feld' fehlt oder ist leer" >&2
    BEFUNDE=1
  fi
done

ERSTES_DRITTEL=$(( $(wc -l < "$DATEI") / 3 + 1 ))
if ! head -n "$ERSTES_DRITTEL" "$DATEI" | grep -qiE "Ergebnis|Entscheidung"; then
  echo "BEFUND: Weder 'Ergebnis' noch 'Entscheidung' im ersten Drittel der Datei gefunden (F-69-Reihenfolge)" >&2
  BEFUNDE=1
fi

ZEILEN=$(wc -l < "$DATEI")
if [ "$ZEILEN" -gt 60 ]; then
  echo "BEFUND: Bericht hat $ZEILEN Zeilen, mehr als die zulaessigen 60 (~1 Bildschirmseite)" >&2
  BEFUNDE=1
fi

if [ "$BEFUNDE" -ne 0 ]; then
  exit 1
fi
echo "CEO-Statusbericht: alle Pflichtpruefungen bestaetigt."
exit 0
