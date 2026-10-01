#!/bin/bash
# Abnahme-Muster fuer Playbook "Abnahmepruefung" (F-73). Aufruf: pruefen.sh <meldung.md> <pruefende_rolle>
set -u
DATEI="${1:-}"
ROLLE="${2:-}"
if [ -z "$DATEI" ] || [ -z "$ROLLE" ]; then
  echo "Aufruf: pruefen.sh <meldung.md> <pruefende_rolle>" >&2
  exit 1
fi
[ -f "$DATEI" ] || { echo "BEFUND: Datei nicht gefunden: $DATEI" >&2; exit 1; }

AUTOR=$(grep -m1 -iE "^Von:" "$DATEI" | sed -E 's/^Von:[[:space:]]*//i' | tr -d '[:space:]')
ROLLE_NORM=$(echo "$ROLLE" | tr -d '[:space:]')
if [ -n "$AUTOR" ] && [ "$AUTOR" = "$ROLLE_NORM" ]; then
  echo "BEFUND: Selbstpruefung ausgeschlossen - Autor '$AUTOR' == pruefende Rolle '$ROLLE_NORM'" >&2
  exit 1
fi
echo "Abnahmepruefung: keine Selbstpruefung, Pflichtpruefung bestaetigt."
exit 0
