#!/bin/bash
# Abnahme-Muster fuer Playbook "Datenauswertung" (F-73). Aufruf: pruefen.sh <auswertung.md>
set -u
DATEI="${1:-}"
[ -z "$DATEI" ] && { echo "Aufruf: pruefen.sh <auswertung.md>" >&2; exit 1; }
[ -f "$DATEI" ] || { echo "BEFUND: Datei nicht gefunden: $DATEI" >&2; exit 1; }

BEFUNDE=0
grep -qiE "Quelle|Fundstelle" "$DATEI" || { echo "BEFUND: kein Wort 'Quelle'/'Fundstelle' in der Datei gefunden" >&2; BEFUNDE=1; }

ZAHLENZEILEN=$(grep -cE "[0-9]+ ?(%|USD|Stk\\.)" "$DATEI")
BELEGZEILEN=$(grep -icE "Quelle|Fundstelle" "$DATEI")
if [ "$ZAHLENZEILEN" -gt 0 ] && [ "$BELEGZEILEN" -eq 0 ]; then
  echo "BEFUND: $ZAHLENZEILEN Zeile(n) mit Zahl, aber keine Beleg-Angabe" >&2
  BEFUNDE=1
fi

[ "$BEFUNDE" -ne 0 ] && exit 1
echo "Datenauswertung: alle Pflichtpruefungen bestaetigt."
exit 0
