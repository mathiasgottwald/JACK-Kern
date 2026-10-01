#!/bin/bash
# Abnahme-Muster fuer Playbook "SEO" (F-74). Aufruf: pruefen.sh <vorschlag.md>
set -u
DATEI="${1:-}"
[ -z "$DATEI" ] && { echo "Aufruf: pruefen.sh <vorschlag.md>" >&2; exit 1; }
[ -f "$DATEI" ] || { echo "BEFUND: Datei nicht gefunden: $DATEI" >&2; exit 1; }

BEFUNDE=0
if grep -iE "automatisch veroeffentlicht|live geschaltet" "$DATEI" | grep -qvi "vorschlag"; then
  echo "BEFUND: Formulierung deutet auf eine bereits automatisch veroeffentlichte Aenderung hin" >&2
  BEFUNDE=1
fi

[ "$BEFUNDE" -ne 0 ] && exit 1
echo "SEO: alle Pflichtpruefungen bestaetigt (nur Vorschlag)."
exit 0
