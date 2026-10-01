#!/usr/bin/python3
"""F-56 (25.09.2026): der EINE erlaubte Weg, den JACK-Dienst neu zu starten.

Aufruf: neustart_sicher.sh <kanal> "<grund>" [--dienst LABEL] [--nur-pruefen] [--trocken]
  1. Ruhe-Regel Patron (jack_ruhe): solange der Patron JACK benutzt (letzte 30 Min), kein Neustart. Alle 5 Min neu pruefen,
     jedes Mal Eintrag "Neustart verschoben: Patron aktiv" in betrieb/neustarts.log (hoechstens einer je Pruefung).
  2. Neustart-Takt: je Kanal hoechstens einer in 15 Min (Zeile mit demselben Kanal in neustarts.log).
  3. Ablauf wie t7_neustart: STOPP setzen -> launchctl kickstart -k -> HTTP 200 -> /arbeitsfaehigkeit -> STOPP aufheben -> Eintrag.
Umgebung (nur Tests): JACK_RUHE_TAKT_S (Standard 300), JACK_RUHE_MAX_S (Standard: ohne Grenze).
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

JACK = Path(os.environ.get("JACK_NEUSTART_WURZEL") or Path(__file__).resolve().parents[1])
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import jack_ruhe

LOG = JACK / "betrieb" / "neustarts.log"
DIENST = "world.gottwald.jack.server"
TAKT_MIN = 15


def _log(zeile):
    with LOG.open("a", encoding="utf-8") as f:
        f.write(zeile.rstrip("\n") + "\n")


def _jetzt():
    return dt.datetime.now()


def letzter_neustart(kanal):
    try:
        zeilen = LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for z in reversed(zeilen):
        t = z.split("\t")
        if len(t) >= 2 and t[1].strip() == "Kanal " + kanal and "verschoben" not in z:
            try:
                return dt.datetime.strptime(t[0], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
    return None


def warten_und_freigeben(kanal, grund, takt_s, max_s=None):
    """Blockiert, bis Ruhe herrscht. -> (True, Satz) oder (False, Satz) bei max_s."""
    start = time.time()
    start_dt = _jetzt()
    while True:
        gestartet = letzter_neustart(kanal)
        if gestartet and gestartet > start_dt:
            return False, "erledigt: inzwischen neu gestartet (%s)" % gestartet.strftime("%H:%M:%S")
        aktiv, warum = jack_ruhe.patron_aktiv(JACK / "betrieb")
        if aktiv:
            _log("%s\tKanal %s\tNeustart verschoben: Patron aktiv (%s) - %s" % (_jetzt().strftime("%Y-%m-%d %H:%M:%S"), kanal, grund, warum))
        else:
            letzter = letzter_neustart(kanal)
            if letzter and (_jetzt() - letzter).total_seconds() < TAKT_MIN * 60 and not jack_ruhe.ruhe_aufgehoben(JACK / "betrieb"):
                _log("%s\tKanal %s\tNeustart verschoben: Neustart-Takt (letzter %s, 15 Min Abstand) - %s"
                     % (_jetzt().strftime("%Y-%m-%d %H:%M:%S"), kanal, letzter.strftime("%H:%M:%S"), grund))
                warum = "Neustart-Takt"
            else:
                return True, "Ruhe: " + warum
        if max_s is not None and time.time() - start >= max_s:
            return False, "verschoben: " + warum
        time.sleep(takt_s)


def neustarten(kanal, grund, dienst=DIENST):
    def steuern(was):
        return subprocess.run(["/usr/bin/python3", "-c", "import json,jack_planer as P; print(json.dumps(P.steuern(%r, von=%r), ensure_ascii=False))" % (was, "neustart_sicher:" + kanal)],
                              cwd=str(JACK), capture_output=True, text=True, timeout=60).stdout.strip()
    pid = lambda: subprocess.run(["/bin/launchctl", "print", "gui/%d/%s" % (os.getuid(), dienst)], capture_output=True, text=True).stdout
    def pid_von(t):
        for z in t.splitlines():
            if z.strip().startswith("pid ="):
                return z.split("=")[1].strip()
        return "?"
    vorher = pid_von(pid())
    steuern("stopp_setzen")
    try:
        subprocess.run(["/bin/launchctl", "kickstart", "-k", "gui/%d/%s" % (os.getuid(), dienst)], check=True, capture_output=True, timeout=60)
        ok = False
        for _ in range(40):
            time.sleep(1)
            try:
                ok = urllib.request.urlopen("http://127.0.0.1:8778/status", timeout=3).status == 200
            except Exception:
                ok = False
            if ok:
                break
    finally:
        steuern("stopp_aufheben")
    nachher = pid_von(pid())
    _log("%s\tKanal %s\t%s\tPID %s -> %s (%s)" % (_jetzt().strftime("%Y-%m-%d %H:%M:%S"), kanal, grund, vorher, nachher, "HTTP 200" if ok else "KEINE ANTWORT"))
    if ok:
        # F-100 D: die Aufhebung gilt fuer genau EINEN Neustart; das Dashboard zeigt danach ruhig "Neu eingebaut: <Grund>".
        jack_ruhe.aufheben_verbrauchen(JACK / "betrieb")
        try:
            (JACK / "betrieb" / "neu_eingebaut.json").write_text(json.dumps({"zeit": _jetzt().isoformat(), "grund": grund, "kanal": kanal}, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    return ok


def kanal_terminal(kanal, grund, trocken=False):
    """F-58: Kanal-Neustart ueber den Waechter-Code (eine Definition der Regeln). Exit 0 = gestartet/trocken, 3 = verschoben/gesperrt."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import jack_netzwaechter as W
    konfig = W._lesen(W.KONFIG, {}) or {}
    l = next((x for x in konfig.get("laeufer", []) if x.get("art") == "postfach" and x.get("kanal") == kanal), None)
    if not l:
        print("Kein Postfach-Läufer für Kanal %s in netzwaechter.json" % kanal)
        return 1
    stand = W._lesen(W.STAND, {}) or {}
    herz = W._lesen(W.HERZ / (kanal + ".json"), {}) or {}
    r = W.kanal_neustart(l, {"herz": herz}, stand, grund, trocken=trocken)
    W._schreiben(W.STAND, stand)
    print(r["massnahme"])
    return 0 if (r["massnahme"].startswith("Kanal-Neustart") or r["massnahme"].startswith("TROCKEN")) else 3


def main(argv=None):
    a = argparse.ArgumentParser()
    a.add_argument("kanal")
    a.add_argument("grund")
    a.add_argument("--dienst", default=DIENST)
    a.add_argument("--terminal", action="store_true", help="F-58: statt des Dienstes das Terminal des Kanals neu starten (alter claude-Prozess beenden, neuer Tab); gleiche Ruhe-Regel, hoechstens 1 je Stunde und Kanal")
    a.add_argument("--nur-pruefen", action="store_true", help="nur sagen, ob ein Neustart jetzt erlaubt waere (Exit 0 = ja, 3 = nein)")
    a.add_argument("--trocken", action="store_true", help="warten/pruefen wie echt, aber nicht neu starten")
    a = a.parse_args(argv)
    if a.nur_pruefen:
        aktiv, warum = jack_ruhe.patron_aktiv(JACK / "betrieb")
        print(json.dumps({"neustart_erlaubt": not aktiv, "grund": warum}, ensure_ascii=False))
        return 3 if aktiv else 0
    if a.terminal:
        return kanal_terminal(a.kanal, a.grund, a.trocken)
    takt = float(os.environ.get("JACK_RUHE_TAKT_S", "300"))
    grenze = os.environ.get("JACK_RUHE_MAX_S")
    ok, satz = warten_und_freigeben(a.kanal, a.grund, takt, float(grenze) if grenze else None)
    if not ok:
        print(satz)
        return 3
    if a.trocken:
        print("TROCKEN: Neustart wuerde jetzt laufen (%s)" % satz)
        return 0
    print("Neustart (%s)" % satz)
    return 0 if neustarten(a.kanal, a.grund, a.dienst) else 1


if __name__ == "__main__":
    raise SystemExit(main())
