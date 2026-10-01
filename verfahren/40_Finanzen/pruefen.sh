#!/bin/bash
# Abnahme-Muster fuer Playbook "40_Finanzen" (F-74). Aufruf: pruefen.sh <bericht.md>
set -u
DATEI="${1:-}"
[ -z "$DATEI" ] && { echo "Aufruf: pruefen.sh <bericht.md>" >&2; exit 1; }
[ -f "$DATEI" ] || { echo "BEFUND: Datei nicht gefunden: $DATEI" >&2; exit 1; }

BEFUNDE=0
if grep -qE "[0-9]+\.[0-9]{2,}( |\\$)" "$DATEI"; then
  echo "BEFUND: Rohzahl mit Punkt statt betragText gefunden" >&2
  BEFUNDE=1
fi
if grep -qiE "Buchung ausgeloest|Zahlung ausgeloest|Ueberweisung ausgefuehrt" "$DATEI"; then
  echo "BEFUND: Formulierung deutet auf einen bereits ausgeloesten Geldtransfer hin" >&2
  BEFUNDE=1
fi

[ "$BEFUNDE" -ne 0 ] && exit 1
echo "40_Finanzen: alle Pflichtpruefungen bestaetigt."
exit 0
