#!/bin/bash
# F-56: einziger erlaubter Weg fuer einen Dienst-Neustart (Ruhe-Regel Patron, Takt 15 Min). Aufruf: neustart_sicher.sh <kanal> "<grund>" [--nur-pruefen|--trocken]
exec /usr/bin/python3 "$(dirname "$0")/neustart_sicher.py" "$@"
