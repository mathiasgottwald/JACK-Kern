#!/bin/bash
# F-113: Foto des Dashboards fuer alle Kanaele (nur Lesen). Aufruf: foto.sh <kennung|/pfad|datei.html> <breite> <zielpng>
exec node "$(dirname "$0")/foto.mjs" "$@"
