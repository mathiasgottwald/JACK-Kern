#!/bin/bash
# Abnahme-Muster fuer Playbook "Social_YouTube" (F-74). Aufruf: pruefen.sh <entwurf.md>
set -u
DATEI="${1:-}"
[ -z "$DATEI" ] && { echo "Aufruf: pruefen.sh <entwurf.md>" >&2; exit 1; }
[ -f "$DATEI" ] || { echo "BEFUND: Datei nicht gefunden: $DATEI" >&2; exit 1; }

BEFUNDE=0
if grep -iE "veroeffentlicht|online gestellt" "$DATEI" | grep -qvi "entwurf"; then
  echo "BEFUND: Formulierung deutet auf eine bereits erfolgte Veroeffentlichung hin" >&2
  BEFUNDE=1
fi
if grep -qiE "gesichtslos|Massenkanal" "$DATEI" && ! grep -qi "geprueft" "$DATEI"; then
  echo "BEFUND: Sperrlisten-Stichwort (gesichtsloser Massenkanal) ohne Gegenbeleg 'geprueft'" >&2
  BEFUNDE=1
fi
if grep -qi "Kinderinhalt" "$DATEI" && ! grep -qi "geprueft" "$DATEI"; then
  echo "BEFUND: Kinderinhalt erwaehnt ohne 'geprueft' (Sperrliste 33.1)" >&2
  BEFUNDE=1
fi
if grep -qiE "Konto (angelegt|erstellt)" "$DATEI" && ! grep -qi "Patron" "$DATEI"; then
  echo "BEFUND: Kontoanlage erwaehnt ohne Bezug zum Patron (Kontoanlage nur durch den Patron)" >&2
  BEFUNDE=1
fi

[ "$BEFUNDE" -ne 0 ] && exit 1
echo "Social_YouTube: alle Pflichtpruefungen bestaetigt (nur Planung, Sperrliste eingehalten)."
exit 0
