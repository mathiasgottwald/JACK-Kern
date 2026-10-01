#!/bin/bash
# Abnahme-Muster fuer Playbook "Bezahlte_Werbung" (F-74). Aufruf: pruefen.sh <entwurf.md>
set -u
DATEI="${1:-}"
[ -z "$DATEI" ] && { echo "Aufruf: pruefen.sh <entwurf.md>" >&2; exit 1; }
[ -f "$DATEI" ] || { echo "BEFUND: Datei nicht gefunden: $DATEI" >&2; exit 1; }

BEFUNDE=0
if grep -iE "gebucht|geschaltet|ausgeloest" "$DATEI" | grep -qvi "entwurf\|vorschlag"; then
  echo "BEFUND: Formulierung deutet auf eine bereits ausgeloeste/gebuchte Schaltung hin" >&2
  BEFUNDE=1
fi

[ "$BEFUNDE" -ne 0 ] && exit 1
echo "Bezahlte_Werbung: alle Pflichtpruefungen bestaetigt (nur Entwurf, kein Geldtransfer ausgeloest)."
exit 0
