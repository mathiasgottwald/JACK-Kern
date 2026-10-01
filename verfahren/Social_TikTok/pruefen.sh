#!/bin/bash
# Abnahme-Muster fuer Playbook "Social_TikTok" (F-74). Aufruf: pruefen.sh <entwurf.md>
set -u
DATEI="${1:-}"
[ -z "$DATEI" ] && { echo "Aufruf: pruefen.sh <entwurf.md>" >&2; exit 1; }
[ -f "$DATEI" ] || { echo "BEFUND: Datei nicht gefunden: $DATEI" >&2; exit 1; }

BEFUNDE=0
if grep -iE "veroeffentlicht|gepostet|online gestellt" "$DATEI" | grep -qvi "entwurf"; then
  echo "BEFUND: Formulierung deutet auf eine bereits erfolgte Veroeffentlichung hin (Planungsteil erlaubt, Veroeffentlichung nicht)" >&2
  BEFUNDE=1
fi

[ "$BEFUNDE" -ne 0 ] && exit 1
echo "Social_TikTok: alle Pflichtpruefungen bestaetigt (nur Planung)."
exit 0
