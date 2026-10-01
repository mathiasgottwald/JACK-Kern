#!/bin/zsh
# Auftrag 27.1, Aufgabe 5 - Kandidaten-Messtest, der erst abends anlaeuft.
#
# Warum es dieses Skript gibt: Der Patron hat angeordnet, den Messtest erst ab
# 20:00 Uhr zu starten - tagsueber baut Tab C2 auf demselben iMac, und die
# Stimme hat immer Vorrang. Tagsueber sind auf dieser Maschine gemessen nur
# 8 bis 11 GB frei; ein Kandidat mit 12 bis 16 GB passt da nicht hinein.
#
# Warum kein launchd: launchd-Hintergrundprozesse kommen auf diesem Mac nicht
# an iCloud Drive heran (CLAUDE.md, Abschnitt 9: Exit 126, Operation not
# permitted). Dieses Skript laeuft deshalb als gewoehnlicher, abgekoppelter
# Prozess des angemeldeten Benutzers.
#
# Aufruf:
#   nohup ./messtest_27.1_abends.sh <Modellordner> > /dev/null 2>&1 &
# Erst an einem spaeteren Tag ab 20:00 (Patron 17.09.2026: Kandidat B am 18.09.):
#   nohup ./messtest_27.1_abends.sh <Modellordner> --ab 2026-09-18 > /dev/null 2>&1 &
# Sofort starten, ohne auf 20:00 zu warten:
#   ./messtest_27.1_abends.sh <Modellordner> --jetzt
#
# Es wird NICHTS geloescht und nichts ueberschrieben. Das Skript schreibt nur
# in sein eigenes Protokoll; alles Weitere macht jack_messtest.py.

set -u
JACK="/Users/gottwald/Library/Mobile Documents/com~apple~CloudDocs/GOTT WALD HOLDING/00_Marken/JACK"
KANDIDAT="${1:-}"
JETZT=""
# --ab JJJJ-MM-TT: frueher als an diesem Tag wird gar nicht erst nachgesehen.
# Ohne den Schalter gilt heute. Zwei Kandidaten am selben Abend waeren sonst
# gleichzeitig losgelaufen - und jack_messtest laesst immer nur EINEN Lauf zu.
ABTAG=""
shift 2>/dev/null || true
while [ $# -gt 0 ]; do
  case "$1" in
    --jetzt) JETZT="--jetzt" ;;
    --ab)    shift; ABTAG="${1:-}" ;;
    *)       echo "Unbekannter Schalter: $1" >&2; exit 2 ;;
  esac
  shift
done
STUNDE=20
AUFGEBEN=23          # nach 23:00 nicht mehr anfangen - der Lauf soll fertig werden
BELEG="$JACK/abnahme/Sichtpruefung_27.1_2026-09-17"
PROTOKOLL="$BELEG/A5_Start_${KANDIDAT}.log"

if [ -z "$KANDIDAT" ]; then
  echo "Aufruf: $0 <Modellordner aus lokal.nosync/modelle> [--ab JJJJ-MM-TT] [--jetzt]" >&2
  exit 2
fi
# Das Datum als Zahl: die eingebaute Pruefung von zsh kann Zeichenketten nicht
# der Groesse nach vergleichen, Zahlen schon. Ein Datum ist ohnehin eine.
ABZAHL=""
if [ -n "$ABTAG" ]; then
  ABZAHL=$(printf '%s' "$ABTAG" | tr -d '-')
  case "$ABZAHL" in
    [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]) ;;
    *) echo "--ab braucht ein Datum wie 2026-09-18, nicht '$ABTAG'" >&2; exit 2 ;;
  esac
fi
mkdir -p "$BELEG"

sagen() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$PROTOKOLL"; }

sagen "Wachposten gestartet fuer Kandidat '$KANDIDAT' (PID $$). Beginn ${ABTAG:-heute} ab ${STUNDE}:00 Uhr."

if [ "$JETZT" != "--jetzt" ]; then
  # Erst auf den Tag warten, dann auf die Stunde. Beides mit einer Uhr, die
  # jede Minute neu abgelesen wird - ein schlafender Mac verschiebt den Start,
  # er verliert ihn nicht.
  if [ -n "$ABZAHL" ]; then
    while [ "$(date +%Y%m%d)" -lt "$ABZAHL" ]; do
      sleep 60
    done
  fi
  while [ "$(date +%H)" -lt $STUNDE ]; do
    sleep 60
  done
fi

cd "$JACK" || { sagen "ABBRUCH: Projektordner nicht erreichbar."; exit 1; }

while :; do
  H=$(date +%H)
  if [ -n "$ABZAHL" ] && [ "$(date +%Y%m%d)" -lt "$ABZAHL" ]; then
    sleep 60; continue
  fi
  if [ "$JETZT" != "--jetzt" ] && [ "$H" -ge $AUFGEBEN ]; then
    sagen "ABBRUCH: Nach ${AUFGEBEN}:00 wird nicht mehr angefangen. Kein Lauf, keine Kosten."
    exit 1
  fi
  # Probelauf ZUERST: einmal laden, eine Frage, wieder entladen. Kostet nichts
  # und laeuft nur lokal. Erst wenn der Kandidat ueberhaupt rechnet, wird der
  # Messtest gestartet - sonst bezahlt man Stufe 1 und 2 fuer einen Lauf, der
  # an Stufe 0 scheitert. Nebenbei stehen Ladezeit und Speicher im Protokoll.
  PROBE=$(/usr/bin/python3 jack_lokal.py frage \
          "Antworte mit genau einem kurzen deutschen Satz: Bist du bereit?" \
          "$KANDIDAT" 2>&1)
  if ! printf '%s' "$PROBE" | /usr/bin/grep -q '"antwort"'; then
    sagen "Probelauf nicht bestanden - kein Messtest, keine Kosten. Meldung:"
    printf '%s\n' "$PROBE" | /usr/bin/head -c 1200 >> "$PROTOKOLL"
    printf '\n' >> "$PROTOKOLL"
    sleep 600
    continue
  fi
  sagen "Probelauf bestanden:"
  printf '%s\n' "$PROBE" >> "$PROTOKOLL"

  # jack_messtest prueft selbst: Speicher (die Stimme hat Vorrang), Geld-Deckel,
  # und dass kein zweiter Messtest laeuft. Wir lesen nur sein Urteil.
  ERG=$(/usr/bin/python3 -I jack_messtest.py kandidat "$KANDIDAT" --vordergrund 2>&1)
  if printf '%s' "$ERG" | /usr/bin/grep -q '"ok": true'; then
    sagen "Lauf beendet. Ergebnis:"
    printf '%s\n' "$ERG" >> "$PROTOKOLL"
    exit 0
  fi
  sagen "Noch nicht moeglich - in 10 Minuten wieder. Meldung:"
  printf '%s\n' "$ERG" | /usr/bin/head -c 1200 >> "$PROTOKOLL"
  printf '\n' >> "$PROTOKOLL"
  sleep 600
done
