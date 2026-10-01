#!/bin/bash
# Abnahme-Muster fuer Playbook "85_Design" (F-74). Aufruf: pruefen.sh <pruefbericht.md>
set -u
DATEI="${1:-}"
[ -z "$DATEI" ] && { echo "Aufruf: pruefen.sh <pruefbericht.md>" >&2; exit 1; }
[ -f "$DATEI" ] || { echo "BEFUND: Datei nicht gefunden: $DATEI" >&2; exit 1; }

BEFUNDE=0
# Echte Fundstelle: "Fundstelle:"/"Quelle:" gefolgt von nicht-leerem Text, ODER ein Pfad unter 00_Marken/.
if ! grep -qiE "(Fundstelle|Quelle):[[:space:]]*[^[:space:]]" "$DATEI" && ! grep -q "00_Marken/" "$DATEI"; then
  echo "BEFUND: keine echte Fundstelle/Quelle (Pfad oder 'Fundstelle: ...') fuer das Markenmaterial genannt" >&2
  BEFUNDE=1
fi
grep -qiE "erfundenes Logo|neue Farbe ohne Beleg|keine Quelle" "$DATEI" && { echo "BEFUND: Hinweis auf erfundenes/unbelegtes Markenmaterial gefunden" >&2; BEFUNDE=1; }

[ "$BEFUNDE" -ne 0 ] && exit 1
echo "85_Design: alle Pflichtpruefungen bestaetigt."
exit 0
