#!/bin/bash
# Abnahme-Muster fuer Playbook "Kampagnenplan" (F-73). Aufruf: pruefen.sh <plandatei.md>
set -u
DATEI="${1:-}"
[ -z "$DATEI" ] && { echo "Aufruf: pruefen.sh <plandatei.md>" >&2; exit 1; }
[ -f "$DATEI" ] || { echo "BEFUND: Datei nicht gefunden: $DATEI" >&2; exit 1; }

BEFUNDE=0
grep -qiE "^##? .*Kampagne" "$DATEI" || { echo "BEFUND: kein Abschnitt 'Kampagne' gefunden" >&2; BEFUNDE=1; }
grep -qiE "^##? .*(Redaktion|Text)" "$DATEI" || { echo "BEFUND: kein Abschnitt 'Redaktion'/'Text' gefunden" >&2; BEFUNDE=1; }
grep -qiE "Der Befund in einem Satz|Warum das nötig ist" "$DATEI" && { echo "BEFUND: Vorlagenrest gefunden (F-29)" >&2; BEFUNDE=1; }

[ "$BEFUNDE" -ne 0 ] && exit 1
echo "Kampagnenplan: alle Pflichtpruefungen bestaetigt."
exit 0
