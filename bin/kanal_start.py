#!/usr/bin/env python3
"""F-105 (30.09.2026): Startwrapper fuer Postfach-Kanal-Terminals.

Aufruf (der Netzwaechter setzt ihn selbst davor; von Hand genauso):
    python3 "$J/bin/kanal_start.py" <kanal> '<kompletter Startbefehl, z. B. caffeinate -dims claude ...>'

1. Sperrdatei betrieb/laeuft/<kanal>.pid (flock, haelt der Wrapper solange er lebt, faellt bei jedem Ende - auch kill -9 - automatisch weg):
   ein zweiter Start desselben Kanals erkennt sie und beendet sich sofort (Exit 0, eine Zeile).
2. Hintergrund-Takt (alle 30 s, Grenze 60 s): schreibt den Herzschlag auch WAEHREND langer Arbeit, mit der PID des echten claude
   und des Wrappers (jack_herzschlag.takt). Ohne diesen Takt trug der Herzschlag nach einem Rechner-Neustart die tote PID (Befund F-105).
3. Beim Ende (Befehl beendet, SIGTERM) wird die Sperre freigegeben."""
import fcntl
import importlib
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jack_herzschlag

JACK = Path(os.environ.get("JACK_NETZ_WURZEL") or Path(__file__).resolve().parents[1])
TAKT_S = int(os.environ.get("JACK_KANAL_TAKT_S") or 30)


def sperrpfad(kanal, jack=None):
    return Path(jack or JACK) / "betrieb" / "laeuft" / (kanal + ".pid")


def laeuft(kanal, jack=None):
    """-> Inhalt der Sperrdatei (dict), wenn ein lebender Wrapper sie haelt, sonst None. Prueft per flock (kein PID-Raten)."""
    pfad = sperrpfad(kanal, jack)
    try:
        f = open(pfad, "r+", encoding="utf-8")
    except OSError:
        return None
    with f:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            try:
                return json.loads(f.read() or "{}") or {"kanal": kanal}
            except ValueError:
                return {"kanal": kanal}
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        return None


def sperre_nehmen(kanal, jack=None):
    """-> offene Datei (Sperre gehalten) oder None, wenn der Kanal schon laeuft."""
    pfad = sperrpfad(kanal, jack)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    f = open(pfad, "a+", encoding="utf-8")
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


def _sperre_schreiben(f, kanal, tty, seit, claude_pid=None):
    f.seek(0)
    f.truncate()
    f.write(json.dumps({"kanal": kanal, "pid": os.getpid(), "tty": tty, "seit": seit, "claude_pid": claude_pid,
                        "beat": int(time.time())}, ensure_ascii=False))
    f.flush()


def _claude_unter(wurzel_pid):
    """PID des claude-Programms unter dem Kindprozess des Wrappers (caffeinate startet es als Kind)."""
    try:
        aus = subprocess.run(["/bin/ps", "-axo", "pid=,ppid=,comm="], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    kinder, comm = {}, {}
    for z in aus.splitlines():
        t = z.split(None, 2)
        if len(t) == 3 and t[0].isdigit() and t[1].isdigit():
            kinder.setdefault(int(t[1]), []).append(int(t[0]))
            comm[int(t[0])] = t[2].rsplit("/", 1)[-1]
    offen, gesehen = [wurzel_pid], set()
    while offen:
        p = offen.pop(0)
        if p in gesehen:
            continue
        gesehen.add(p)
        if comm.get(p) == "claude":
            return p
        offen += kinder.get(p, [])
    return None


def _tty_von(pid):
    try:
        t = subprocess.run(["/bin/ps", "-o", "tty=", "-p", str(pid)], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""
    return "" if t in ("?", "??") else t


def main(argv):
    if len(argv) < 2:
        sys.exit("Aufruf: kanal_start.py <kanal> '<Startbefehl>'")
    kanal, befehl = argv[0], argv[1]
    if not re.fullmatch(r"[a-z_]+", kanal):
        sys.exit("Kanalname ungueltig: %s" % kanal)
    f = sperre_nehmen(kanal)
    if f is None:
        info = laeuft(kanal) or {}
        print("Kanal %s läuft bereits (Wrapper-PID %s, %s) - dieser zweite Start beendet sich sofort. Dieses Fenster kann geschlossen werden."
              % (kanal, info.get("pid", "?"), info.get("tty") or "ohne tty"))
        return 0
    seit = int(time.time())
    kind = subprocess.Popen(["/bin/zsh", "-c", befehl])
    tty = _tty_von(os.getpid())
    stop = threading.Event()

    def takt():
        while not stop.is_set():
            try:
                cpid = _claude_unter(kind.pid)
                if cpid:
                    importlib.reload(jack_herzschlag)      # F-115: Regeln des Herzschlags gelten sofort auch fuer laufende Sitzungen (Wrapper-Code war sonst bis zum Neustart eingefroren)
                    jack_herzschlag.takt(kanal, cpid, _tty_von(cpid) or tty, laeufer_pid=os.getpid(), jack=JACK)
                _sperre_schreiben(f, kanal, tty, seit, cpid)
            except Exception:
                pass                                   # der Takt darf den Kanal nie stoeren
            stop.wait(TAKT_S)
    _sperre_schreiben(f, kanal, tty, seit)
    threading.Thread(target=takt, daemon=True).start()

    def weiter(sig, _f):
        try:
            kind.send_signal(sig)
        except OSError:
            pass
    signal.signal(signal.SIGTERM, weiter)
    signal.signal(signal.SIGHUP, weiter)
    while True:
        try:
            rc = kind.wait()
            break
        except KeyboardInterrupt:                      # Strg-C gilt der Claude-Sitzung, nicht dem Wrapper
            continue
    stop.set()
    try:
        f.seek(0)
        f.truncate()
    except OSError:
        pass
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
