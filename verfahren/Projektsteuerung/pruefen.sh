#!/bin/bash
# Abnahme-Muster fuer Playbook "Projektsteuerung" (F-74). Aufruf: pruefen.sh <bericht.md>
set -u
DATEI="${1:-}"
[ -z "$DATEI" ] && { echo "Aufruf: pruefen.sh <bericht.md>" >&2; exit 1; }
[ -f "$DATEI" ] || { echo "BEFUND: Datei nicht gefunden: $DATEI" >&2; exit 1; }

BEFUNDE=0
if grep -qiE "auftrag geloescht|auftrag verschoben|auftrag geaendert" "$DATEI"; then
  echo "BEFUND: Bericht behauptet eine Aenderung an einem Auftrag - diese Rolle ist rein lesend/berichtend" >&2
  BEFUNDE=1
fi

[ "$BEFUNDE" -ne 0 ] && exit 1
echo "Projektsteuerung: alle Pflichtpruefungen bestaetigt (rein lesend)."
exit 0
