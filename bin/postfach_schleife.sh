#!/bin/bash
# F-58/F-61: EINE Warte-Schleife fuer alle Kanaele (F-45-Herzschlag mit zustand / aelteste_datei_kanal / letzte_aufnahme).
# WICHTIG (F-61): Diese Schleife MUSS als Hintergrundaufgabe des Agenten laufen (Bash-Tool mit run_in_background=true).
# Sie endet, sobald eine Auftragsdatei im Kanal liegt oder STOPP_PM existiert - das Ende weckt den Agenten AUTOMATISCH (Task-Benachrichtigung).
# Ohne diesen Hintergrundprozess endet die Runde des Agenten nach der Abschlussmeldung und er nimmt nichts mehr auf, bis jemand tippt.
# Aufruf: bash "$J/bin/postfach_schleife.sh" <kanal>        (immer neu starten, sobald ein Auftrag erledigt und gemeldet ist)
K=${1:?Kanal fehlt (kern|cashflow|gruendung|bewerbungen|inhalt|patronos|sprache|social)}; Z=${2:-wartet}
if [ "$2" = "--trocken" ]; then
  # F-62: Trockenlauf in einer Wegwerf-Wurzel (keine echten Kanaldateien, kein echter Herzschlag): zeigt, dass ein neuer Auftrag
  # den Warteprozess in <= 5 s beendet (= Weckruf). Ausgabe: PASS/FAIL mit Sekunden.
  S="$(cd "$(dirname "$0")" && pwd)"; W=$(mktemp -d); mkdir -p "$W/bin" "$W/betrieb/herzschlag" "$W/auftraege/pm_ausgang/$K" "$W/abnahme/pm_eingang"
  cp "$S/jack_herzschlag.py" "$S/postfach_schleife.sh" "$W/bin/"
  JACK_ROOT="$W" JACK_SCHLEIFE_TAKT_S=1 bash "$W/bin/postfach_schleife.sh" "$K" > "$W/aus.txt" 2>&1 & P=$!
  sleep 2; [ -e "/proc/$P" ] || kill -0 $P 2>/dev/null || { echo "FAIL: Warteprozess lief nicht"; rm -rf "$W"; exit 1; }
  echo "Herzschlag im Warten: $(python3 -c "import json;print(json.load(open('$W/betrieb/herzschlag/$K.json'))['zustand'])")"
  T0=$(python3 -c "import time;print(time.time())"); echo "# Testauftrag" > "$W/auftraege/pm_ausgang/$K/TEST-1_auftrag.md"
  wait $P; T1=$(python3 -c "import time;print(time.time())")
  D=$(python3 -c "print(round($T1-$T0,1))")
  if python3 -c "import sys;sys.exit(0 if $T1-$T0<=5 else 1)"; then echo "PASS: Kanal $K: Warteprozess endete $D s nach neuem Auftrag (<= 5 s)"; R=0; else echo "FAIL: $D s"; R=1; fi
  rm -rf "$W"; exit $R
fi
J=${JACK_ROOT:-"$HOME/Library/Mobile Documents/com~apple~CloudDocs/GOTT WALD HOLDING/00_Marken/JACK"}; T=${JACK_SCHLEIFE_TAKT_S:-120}
neu(){ find "$J/auftraege/pm_ausgang/$K" -maxdepth 1 -type f 2>/dev/null -exec basename {} \; | grep -v '^\.' | grep -v -i '^readme' ; }   # F-116 (PM-Wortlaut): JEDE Datei im Kanalordner weckt die Schleife - auch DAUERBETRIEB_*/NACHT_* (so laeuft der Dauerbetrieb: die Schleife endet sofort, der Zyklus beginnt von vorn); die F-114-Ausnahmen gelten nur fuer die Waechter-Bewertung
# F-86: Pause-Schalter (System-Tabelle): liegt betrieb/kanal_pause/<kanal>, wartet die Schleife weiter, auch wenn ein Auftrag im Kanal liegt.
pause(){ [ -e "$J/betrieb/kanal_pause/$K" ]; }
until [ -e "$J/auftraege/pm_ausgang/STOPP_PM" ] || { [ "$Z" = wartet ] && [ -n "$(neu)" ] && ! pause; }; do
  /usr/bin/python3 "$J/bin/jack_herzschlag.py" "$K" --zustand "$Z" > /dev/null; sleep "$T"
done
date '+%H:%M:%S'; ls "$J/auftraege/pm_ausgang/$K"
