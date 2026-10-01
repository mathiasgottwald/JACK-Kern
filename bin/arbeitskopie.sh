#!/bin/bash
# 47.1 Aufgabe 1 (F-97): eigene Arbeitskopie je Terminal AUSSERHALB von iCloud (Regel Arbeitskopien 24.09.2026).
# Aufruf: arbeitskopie.sh <repo-pfad-oder-url> <kanal>      -> legt ~/Arbeitskopien/<repo>-<kanal> an (frischer Klon), falls sie fehlt,
#                                                             und gibt den Pfad aus. Vorhandene Kopien werden NIE ueberschrieben/geloescht.
# Ergebnisse gehen per Commit/PR nach origin (Regel 22a/e), nie direkt auf main.
set -e
QUELLE=${1:?Repo (Pfad oder URL) fehlt}; KANAL=${2:?Kanal fehlt}
NAME=$(basename "${QUELLE%.git}")
ZIEL="${JACK_ARBEITSKOPIEN:-$HOME/Arbeitskopien}/$NAME-$KANAL"
case "$ZIEL" in *"Mobile Documents"*|*iCloud*) echo "FEHLER: Arbeitskopie darf nicht in iCloud liegen: $ZIEL" >&2; exit 4;; esac
if [ -d "$ZIEL/.git" ]; then echo "$ZIEL"; exit 0; fi
if [ -e "$ZIEL" ]; then echo "FEHLER: $ZIEL existiert, ist aber kein Git-Klon - nichts angefasst" >&2; exit 5; fi
mkdir -p "$(dirname "$ZIEL")"
git clone --quiet "$QUELLE" "$ZIEL"
git -C "$ZIEL" checkout --quiet -b "arbeit/$KANAL" 2>/dev/null || true
echo "$ZIEL"
