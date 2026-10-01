#!/bin/bash
JACK="$HOME/Library/Mobile Documents/com~apple~CloudDocs/GOTT WALD HOLDING/07_Projekte/JACK"
# --- Ruflo faehrt mit JACK hoch und runter (20.09.2026) ----------------------
# Ruflo ist die Begleitschicht fuer Arbeiterlaeufe mit "motor: ruflo": gemeinsames
# Gedaechtnis und Koordination ueber einen lokalen MCP-Server. Es ist KEIN zweiter
# Kopf und spricht nie mit dem Patron. Siehe 00_Marken/JACK/ruflo/README.md.
#
# Faellt der Start aus, startet JACK trotzdem. Dann werden Ruflo-Auftraege mit
# "RUFLO LAEUFT NICHT" abgewiesen - das ist ehrlicher als ein stiller Motorwechsel.
RUFLO_LOG="$JACK/.claude-flow.nosync/start.log"
mkdir -p "$JACK/.claude-flow.nosync" 2>/dev/null
/bin/bash "$JACK/ruflo/ruflo_server.sh" start >> "$RUFLO_LOG" 2>&1
trap '/bin/bash "$JACK/ruflo/ruflo_server.sh" stop >> "$RUFLO_LOG" 2>&1' EXIT INT TERM

# Kein exec mehr: JACK laeuft als Kindprozess, damit der trap oben beim Beenden
# noch greift und Ruflo mit heruntergefahren wird.
/usr/bin/python3 -I - "$JACK" <<'PY'
import sys, json, datetime, fcntl, subprocess, uuid
from pathlib import Path
from zoneinfo import ZoneInfo
root = Path(sys.argv[1])
sys.path.insert(0, str(root))
try:
    import jack_app
except Exception as error:
    message = "JACKs Startdateien fehlen oder sind nicht lesbar (" + type(error).__name__ + "). Bitte die Sicherung prüfen."
    record = dict(zeit=datetime.datetime.now(ZoneInfo("Europe/Vienna")).isoformat(),
                  id=uuid.uuid4().hex, quelle="echter_lauf", pid_vorher=None,
                  pid_nachher=None, fall=None, ergebnis="fehler", meldung=message)
    try:
        with (root / "betrieb/appstarts.jsonl").open("a", encoding="utf-8") as log:
            fcntl.flock(log, fcntl.LOCK_EX)
            log.write(json.dumps(record, ensure_ascii=False)+"\n")
    except Exception:
        message += " Auch das Startprotokoll ist nicht schreibbar."
    subprocess.Popen(["/usr/bin/osascript", "-e",
        'on run argv\ndisplay alert "JACK konnte nicht starten" message (item 1 of argv) as warning\nend run',
        message], start_new_session=True)
    raise SystemExit(1)
raise SystemExit(jack_app.run())
PY
exit $?
