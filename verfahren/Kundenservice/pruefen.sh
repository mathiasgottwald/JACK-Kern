#!/bin/bash
# Abnahme-Muster fuer Playbook "Kundenservice" (F-74). Aufruf: pruefen.sh <entwurf.md>
set -u
DATEI="${1:-}"
[ -z "$DATEI" ] && { echo "Aufruf: pruefen.sh <entwurf.md>" >&2; exit 1; }
[ -f "$DATEI" ] || { echo "BEFUND: Datei nicht gefunden: $DATEI" >&2; exit 1; }

BEFUNDE=0
if grep -iE "gesendet|beantwortet|verschickt" "$DATEI" | grep -qvi "entwurf"; then
  echo "BEFUND: Formulierung deutet auf einen bereits erfolgten Versand hin (nur Entwuerfe erlaubt)" >&2
  BEFUNDE=1
fi

[ "$BEFUNDE" -ne 0 ] && exit 1
echo "Kundenservice: alle Pflichtpruefungen bestaetigt (kein Direktversand)."
exit 0
