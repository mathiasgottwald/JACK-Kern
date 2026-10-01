#!/bin/bash
# Abnahme-Muster fuer Playbook "80_Betrieb" (F-74). Aufruf: pruefen.sh <bericht.md>
set -u
DATEI="${1:-}"
[ -z "$DATEI" ] && { echo "Aufruf: pruefen.sh <bericht.md>" >&2; exit 1; }
[ -f "$DATEI" ] || { echo "BEFUND: Datei nicht gefunden: $DATEI" >&2; exit 1; }

BEFUNDE=0
if grep -qiE "launchctl kickstart|neustart_sicher" "$DATEI"; then
  echo "BEFUND: Bericht enthaelt einen Neustart-Befehl - diese Rolle darf keine Dienste neu starten" >&2
  BEFUNDE=1
fi

[ "$BEFUNDE" -ne 0 ] && exit 1
echo "80_Betrieb: alle Pflichtpruefungen bestaetigt (keine eigene Dienstkontrolle)."
exit 0
