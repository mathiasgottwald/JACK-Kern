#!/bin/bash
# Abnahme-Muster fuer Playbook "Auslieferungsvorbereitung" (F-73). Aufruf: pruefen.sh <geaenderte_datei>
set -u
DATEI="${1:-}"
[ -z "$DATEI" ] && { echo "Aufruf: pruefen.sh <geaenderte_datei>" >&2; exit 1; }
[ -f "$DATEI" ] || { echo "BEFUND: Datei nicht gefunden: $DATEI" >&2; exit 1; }

TREFFER=$(ls -1 "${DATEI}".vor_* 2>/dev/null | wc -l | tr -d ' ')
if [ "$TREFFER" -eq 0 ]; then
  echo "BEFUND: keine Sicherung '${DATEI}.vor_*' gefunden" >&2
  exit 1
fi
echo "Auslieferungsvorbereitung: Sicherung gefunden ($TREFFER Treffer)."
exit 0
