#!/bin/bash
# Abnahme-Muster fuer Playbook "Angebotsentwurf" (F-73). Aufruf: pruefen.sh <angebot.md>
set -u
DATEI="${1:-}"
[ -z "$DATEI" ] && { echo "Aufruf: pruefen.sh <angebot.md>" >&2; exit 1; }
[ -f "$DATEI" ] || { echo "BEFUND: Datei nicht gefunden: $DATEI" >&2; exit 1; }

BEFUNDE=0
grep -qiE "^##? .*Angebot" "$DATEI" || { echo "BEFUND: kein Abschnitt 'Angebot' gefunden" >&2; BEFUNDE=1; }
if ! grep -qE "[0-9]+,[0-9]{2} USD" "$DATEI"; then
  echo "BEFUND: kein Betrag im betragText-Format ('X,XX USD') gefunden" >&2
  BEFUNDE=1
fi
if grep -qE "[0-9]+\.[0-9]{2,}( |\\$)" "$DATEI"; then
  echo "BEFUND: Rohzahl mit Punkt statt betragText gefunden" >&2
  BEFUNDE=1
fi

[ "$BEFUNDE" -ne 0 ] && exit 1
echo "Angebotsentwurf: alle Pflichtpruefungen bestaetigt."
exit 0
