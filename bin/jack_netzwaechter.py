#!/usr/bin/env python3
"""F-28 (PM 24.09.2026): Netz-Waechter und automatischer Wiederanlauf nach Internet-Ausfall. 0 USD, keine KI-Aufrufe.

Alle 60 s (launchd world.gottwald.jack.netzwaechter, KeepAlive; das Skript laeuft als Schleife):
1. Internet pruefen: DNS + HTTPS-HEAD auf zwei Ziele, je 5 s Zeitlimit; online, sobald ein Ziel antwortet.
   Zustand -> betrieb/netz.json, Wechsel (weg / wieder da, Dauer) -> betrieb/netz.log.
2. Jeden Dauerlaeufer aus betrieb/netzwaechter.json pruefen (HTTP, Dateialter, Prozess, Postfach-Herzschlag).
   Steht er laenger als seine Toleranz -> Wiederanlauf:
   - Dienste (launchd): `launchctl kickstart -k`, vorher README-Neustart-Regel (fremde Sicherung *.vor_* juenger
     als 10 Min -> warten); Eintrag in betrieb/neustarts.log.
   - Claude-Code-Postfach-Terminals: lebt der claude-Prozess, aber Herzschlag UND Rechenzeit stehen > 10 Min, wird
     nur "weiter" in genau dessen Terminal getippt (kein zweiter Agent auf demselben Kanal). Ist der Prozess beendet,
     oeffnet der Waechter einen neuen Terminal-Tab mit dem bekannten Startbefehl. Nie bei vorhandenem STOPP_PM.
   Hoechstens 3 Wiederanlaeufe je Laeufer und Stunde; danach eine Karte in auftraege/freigabe/ statt Endlosschleife.
Aufruf: jack_netzwaechter.py [--einmal] [--trocken]
"""
import datetime as dt
import fcntl
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import jack_ruhe                                       # F-56: Ruhe-Regel Patron (kein Neustart waehrend der Patron JACK benutzt)
import jack_herzschlag                                 # F-45: aelteste_datei_alter (eine Definition fuer Herzschlag und Waechter)

JACK = Path(os.environ.get("JACK_NETZ_WURZEL") or Path(__file__).resolve().parents[1])
BETRIEB = JACK / "betrieb"
KONFIG = BETRIEB / "netzwaechter.json"
ZUSTAND = BETRIEB / "netz.json"
LOG = BETRIEB / "netz.log"
STAND = BETRIEB / "netzwaechter_stand.json"
NEUSTARTS = BETRIEB / "neustarts.log"
NEUSTART_SPERRE = BETRIEB / ".kanal_neustart.lock"


class _kanal_neustart_sperre:
    """F-89 (29.09.2026, M-5a): exklusive Dateisperre um den Lese-Pruef-Schreib-Zyklus von kanal_neustart.
    Ursache des Mehrfachstarts vom 29.09. 18:02-18:05: mehrere Prozesse (Waechter-Takt UND separate
    `neustart_sicher.py --terminal`-Aufrufe) lasen betrieb/netzwaechter_stand.json unabhaengig voneinander,
    bevor der jeweils andere seinen Neustart-Zeitstempel zurueckgeschrieben hatte - die Ein-Neustart-je-Stunde-
    Pruefung griff dadurch nicht. Die Sperre serialisiert ALLE Aufrufer (dieser Prozess wie externe) auf
    Dateisystemebene (fcntl.flock, blockierend) - kein Erraten von Zeitfenstern noetig."""

    def __enter__(self):
        NEUSTART_SPERRE.parent.mkdir(parents=True, exist_ok=True)
        self._f = open(NEUSTART_SPERRE, "a")
        fcntl.flock(self._f.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        fcntl.flock(self._f.fileno(), fcntl.LOCK_UN)
        self._f.close()
        return False
HERZ = BETRIEB / "herzschlag"
STANDARD_ZIELE = [{"host": "www.apple.com", "url": "https://www.apple.com/library/test/success.html"},
                  {"host": "api.anthropic.com", "url": "https://api.anthropic.com/"}]
MAX_JE_STUNDE = 3
# F-45: Zustand "wartet" im Herzschlag, aber die aelteste Auftragsdatei im eigenen Kanal ist aelter als das -> das Terminal steht trotz Auftrag.
STEHT_TROTZ_AUFTRAG_S = 900
HERZ_FRISCH_S = 300          # F-55: juenger = frisch
UNBEKANNT_TOLERANZ_S = 900   # F-58: PID "unbekannt": hoechstens 15 Min Toleranz ohne Bewegung, dann ok(Bewegung) oder Eskalation
ESKALATION_NACH = 2          # F-58: so viele wirkungslose Anstoesse, dann Kanal-Neustart (Ruhe-Regel, hoechstens 1 je Stunde und Kanal)
ALTFORMAT_STILLSTAND_S = 7200  # F-58: altes Format ohne zustand: so lange darf ein Auftrag ohne Bewegung liegen, auch wenn die Rechenzeit Arbeit zeigt
DATEISTILLE_S = 1200          # F-61 (Luecke D): so lange darf ein Auftrag ohne Aufnahme und ohne Dateibewegung liegen
BEWEGUNG_S = 1800            # F-55: so lange darf ein Auftrag ohne Bewegung liegen, solange der Herzschlag frisch ist
NEU_LESEN_SATZ = "Kanal %s neu lesen — Postfach-Schleife fortsetzen"
# F-50: auch bei leerem/fehlendem "zustand" (alte Schleifen) Alarm, wenn die Datei > 15 Min liegt UND das Terminal nicht erkennbar arbeitet
# (Rechenzeit-Rate der letzten >= 3 Min unter ARBEIT_CPU_S_JE_MIN). Steht im Herzschlag-Text "Kanal leer", obwohl eine Datei seit > 5 Min
# (und aelter als der Herzschlag) im Ordner liegt: sofortiger Alarm (Widerspruch).
ARBEIT_CPU_S_JE_MIN = 1.0
WIDERSPRUCH_S = 300
SICHERUNG_RUHE_S = 600
STUMM_S = 2700               # F-112: Zustand "arbeitet" ohne eigene Datei > 45 Min: Vermerk "haengt" + "weiter" tippen
WECK_STUMM_S = 1800          # F-115: PM-Mitteilung 30 Min unbearbeitet und Sitzung ohne eigene Datei: wie "stumm" behandeln (Stufen F-112)
STUMM_NEUSTART_S = 3600      # F-112: > 60 Min: Kanal-Neustart (Ruhe-Regel, 1 je Stunde)


def jetzt():
    return dt.datetime.now().astimezone()


def _lesen(pfad, standard):
    try:
        return json.loads(Path(pfad).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return standard


def _schreiben(pfad, daten):
    pfad = Path(pfad)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    tmp = pfad.with_name(pfad.name + ".neu")
    tmp.write_text(json.dumps(daten, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, pfad)


def _anhaengen(pfad, zeile):
    with Path(pfad).open("a", encoding="utf-8") as f:
        f.write(zeile.rstrip("\n") + "\n")


# ------------------------------------------------------------------ 1 Internet
def ziel_pruefen(ziel, zeitlimit=5.0):
    t0 = time.monotonic()
    try:
        socket.setdefaulttimeout(zeitlimit)
        socket.getaddrinfo(ziel["host"], 443)
    except OSError as fehler:
        return {"ziel": ziel["host"], "ok": False, "schritt": "dns", "fehler": type(fehler).__name__}
    finally:
        socket.setdefaulttimeout(None)
    try:
        anfrage = urllib.request.Request(ziel["url"], method="HEAD", headers={"User-Agent": "JACK-Netzwaechter"})
        with urllib.request.urlopen(anfrage, timeout=zeitlimit) as antwort:
            code = antwort.status
    except urllib.error.HTTPError as fehler:            # jede HTTP-Antwort heisst: Netz ist da
        code = fehler.code
    except (OSError, ValueError) as fehler:
        return {"ziel": ziel["host"], "ok": False, "schritt": "https", "fehler": type(fehler).__name__}
    return {"ziel": ziel["host"], "ok": True, "http": code, "ms": round((time.monotonic() - t0) * 1000)}


def netz_pruefen(ziele):
    ergebnisse = [ziel_pruefen(z) for z in ziele]
    return any(e["ok"] for e in ergebnisse), ergebnisse


# ------------------------------------------------------------------ 2 Laeufer
def _prozess_lebt(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def _ist_claude_terminal_prozess(pid):
    """F-90 (M-8, Nr.18): eine lebende PID allein reicht nicht - macOS vergibt eine beendete PID irgendwann an
    einen voellig anderen Prozess neu (beobachtet bei Kanal sprache am 29.09.2026: die im Herzschlag gespeicherte
    PID gehoerte inzwischen zu einem GameControllerConfigService-Systemhelfer, nicht mehr zur Postfach-Sitzung).
    Zusaetzliche Pruefung: der Kommandoname der PID muss "claude" sein (das CLI-Binary aus dem Startbefehl). Nur
    fuer Postfach-Kanaele verwendet (siehe _postfach_prozess_lebt) - andere Laeufer-Arten pruefen weiterhin nur
    _prozess_lebt."""
    try:
        comm = subprocess.run(["/bin/ps", "-o", "comm=", "-p", str(int(pid))],
                              capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        return False
    return comm.rsplit("/", 1)[-1] == "claude"


def _postfach_prozess_lebt(pid):
    """F-90: lebt die PID UND ist es (noch) derselbe claude-Terminal-Prozess - erst dann gilt ein Postfach-Kanal
    als 'laeuft noch'. Verhindert, dass der Waechter eine wiederverwendete, fremde PID toetet oder als lebenden
    Kanal-Prozess behandelt."""
    return _prozess_lebt(pid) and _ist_claude_terminal_prozess(pid)


def _rechenzeit(pid):
    """Summe der CPU-Sekunden von Prozess und Kindern (ps), None wenn unbekannt."""
    try:
        aus = subprocess.run(["/bin/ps", "-A", "-o", "pid=,ppid=,time="], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    kinder, zeit = {}, {}
    for z in aus.splitlines():
        teile = z.split()
        if len(teile) != 3:
            continue
        p, pp, t = teile
        kinder.setdefault(pp, []).append(p)
        m = re.fullmatch(r"(?:(\d+)-)?(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)", t)
        if m:
            tage, std, mnt, sek = m.groups()
            zeit[p] = int(tage or 0) * 86400 + int(std or 0) * 3600 + int(mnt) * 60 + float(sek)
    summe, offen = 0.0, [str(pid)]
    while offen:
        p = offen.pop()
        summe += zeit.get(p, 0.0)
        offen += kinder.get(p, [])
    return round(summe, 2) if str(pid) in zeit else None


def _alter_s(pfad):
    try:
        return time.time() - Path(os.path.expanduser(pfad)).stat().st_mtime
    except OSError:
        return None


def _claude_prozesse():
    """F-36: alle laufenden claude-Prozesse als [{pid, tty, cwd}] (ps + lsof, nur lesend)."""
    raus = []
    try:
        pids = subprocess.run(["/usr/bin/pgrep", "-x", "claude"], capture_output=True, text=True, timeout=10).stdout.split()
        for pid in pids:
            tty = subprocess.run(["/bin/ps", "-o", "tty=", "-p", pid], capture_output=True, text=True, timeout=10).stdout.strip()
            aus = subprocess.run(["/usr/sbin/lsof", "-a", "-p", pid, "-d", "cwd", "-Fn"], capture_output=True, text=True, timeout=15).stdout
            cwd = next((z[1:] for z in aus.splitlines() if z.startswith("n")), "")
            raus.append({"pid": pid, "tty": tty, "cwd": cwd})
    except (OSError, subprocess.SubprocessError):
        pass
    return raus


def _tab_titel(tty):
    """Titel des Terminal-Tabs mit diesem tty (nur lesend; leer, wenn keine Automation-Freigabe/kein Tab)."""
    try:
        aus = _osascript('tell application "Terminal"\nset s to ""\nrepeat with w in windows\nrepeat with t in tabs of w\n'
                         's to s & (tty of t) & "|" & (custom title of t) & linefeed\nend repeat\nend repeat\nreturn s\nend tell')
    except (RuntimeError, OSError, subprocess.SubprocessError):
        return ""
    for z in aus.splitlines():
        dev, _, titel = z.partition("|")
        if dev.replace("/dev/", "") == str(tty).replace("/dev/", ""):
            return titel.strip()
    return ""


def _ohne_herzschlag(l, stand, jetzt_s):
    """F-36: Kanal ohne Herzschlag. Den claude-Prozess ueber den Arbeitsordner finden; steht seine Rechenzeit
    laenger als toleranz_s, ist der Status 'steht_ohne_herzschlag' (nur melden, nichts tippen)."""
    ordner = os.path.realpath(os.path.expanduser(l.get("ordner") or ""))
    treffer = [p for p in _claude_prozesse() if p.get("cwd") and os.path.realpath(p["cwd"]) == ordner]
    if not treffer:
        return {"status": "unbekannt", "grund": "kein Herzschlag und kein claude-Prozess im Ordner"}
    if len(treffer) > 1:
        return {"status": "unbekannt", "grund": "kein Herzschlag; %d claude-Prozesse im selben Ordner - nicht eindeutig" % len(treffer)}
    p = treffer[0]
    cpu = _rechenzeit(p["pid"])
    merk = stand.setdefault("cpu", {}).setdefault(l["name"], {})
    if merk.get("pid") != p["pid"] or merk.get("cpu") != cpu:
        merk.update(pid=p["pid"], cpu=cpu, seit=jetzt_s)
    ruhe = jetzt_s - float(merk.get("seit") or jetzt_s)
    if ruhe > l.get("toleranz_s", 600):
        return {"status": "steht_ohne_herzschlag", "grund": "steht (ohne Herzschlag): Rechenzeit seit %d s unverändert" % ruhe,
                "pid": p["pid"], "tty": p["tty"]}
    return {"status": "ok_ohne_herzschlag", "grund": "kein Herzschlag; Prozess %s: Rechenzeit seit %d s unverändert (Grenze %d s)" % (p["pid"], ruhe, l.get("toleranz_s", 600)),
            "pid": p["pid"], "tty": p["tty"]}


# ---- F-99 G/K: Systemkarten gehen nicht ungefragt an den Patron -------------------------------------------------------------
SYSTEMKARTE_ERST_NACH_S = 3600      # erst wenn der Befund so lange anhaelt UND der Waechter/PM ihn nicht selbst geloest hat


def _syskarte(kopf, rumpf, herkunft="", dateiname=None, sofort=False, **_):
    """Eine Waechter-Karte. Immer Label INTERN und gefahr keine (nichts geht nach aussen). Solange der Befund juenger als
    SYSTEMKARTE_ERST_NACH_S ist, entsteht KEINE Freigabekarte: der Waechter/PM klaert selbst, PM bekommt eine Notiz in
    abnahme/pm_eingang/. `sofort=True` (echte Entscheidung des Patrons, z. B. Neustart-Ja) schreibt gleich."""
    import jack_freigaben
    kopf = dict(kopf)
    kopf["label"] = "INTERN"
    kopf["gefahr"] = "keine"
    if not sofort:
        pfad_state = JACK / "betrieb" / "waechter_karten_erstmals.json"
        stand = _lesen(pfad_state, {}) or {}
        schluessel = str(dateiname or kopf.get("betreff"))
        jetzt_s = time.time()
        erst = stand.get(schluessel)
        if not erst or jetzt_s - erst > 6 * 3600:
            stand[schluessel] = erst = jetzt_s
            _schreiben(pfad_state, stand)
        if jetzt_s - erst < SYSTEMKARTE_ERST_NACH_S:
            notiz = JACK / "abnahme" / "pm_eingang" / ("WAECHTER_%s" % re.sub(r"[^\w.-]+", "_", schluessel)[:100])
            notiz.parent.mkdir(parents=True, exist_ok=True)
            if not notiz.exists():
                notiz.write_text("# Wächter-Befund (noch keine Karte für den Patron)\n\n%s\n\n%s\n\nDer Wächter/PM klärt das selbst. "
                                 "Bleibt der Befund länger als %d Min, entsteht eine INTERN-Karte für den Patron.\n"
                                 % (kopf.get("betreff", ""), kopf.get("kern", ""), SYSTEMKARTE_ERST_NACH_S // 60), encoding="utf-8")
            return None
    return jack_freigaben.karte_schreiben(root=JACK, kopf=kopf, rumpf=rumpf, herkunft=herkunft, dateiname=dateiname)



def karte_ohne_herzschlag(l, befund):
    """F-36: Karte mit Tab-Name und dem Satz zum Eintippen. Kein Eingriff; einmal je Kanal und Tag.
    F-78 (29.09.2026): echte v2-Werte statt der Altform (nur marke/auftrag, kein
    projekt/eingegangen/an/betreff/kern/frage/empfehlung/frist/dringlichkeit)."""
    import jack_freigaben
    name = "%s_NETZWAECHTER_%s_ohne_Herzschlag.md" % (jetzt().strftime("%Y-%m-%d"), re.sub(r"\W", "_", l["name"]))
    if (JACK / "auftraege" / "freigabe" / name).exists():
        return name
    titel = _tab_titel(befund.get("tty") or "") or "(Titel nicht lesbar)"
    minuten = l.get("toleranz_s", 600) // 60
    v2 = {
        "projekt": "Netzwächter", "marke": "JACK", "eingegangen": jetzt().strftime("%Y-%m-%d %H:%M"),
        "von": "JACK-Netzwächter (F-36)", "an": "Patron", "art": "netzwaechter",
        "betreff": "Terminal „%s“ (Kanal %s) ohne Herzschlag" % (titel, l["kanal"]),
        "kern": "Das Terminal „%s“ (Kanal %s) sendet keinen Herzschlag, Rechenzeit seit über %d "
                "Minuten unverändert." % (titel, l["kanal"], minuten),
        "frage": "Soll es angestoßen werden?",
        "empfehlung": "Im Terminal-Tab „%s“ (Gerät /dev/%s, dieser Mac) das Wort `weiter` tippen und "
                      "Enter drücken. Der Wächter tippt nichts selbst, weil dafür die "
                      "Automation-Freigabe nötig ist." % (titel, str(befund.get("tty")).replace("/dev/", "")),
        "frist": "keine", "dringlichkeit": "mittel",
        "ablauf": "Kein Eingriff durch den Wächter - der Patron tippt selbst.",
    }
    pfad = _syskarte(kopf=v2, rumpf="\n".join([
        "## Auftrag",
        "Das Terminal „%s“ (Kanal %s) sendet keinen Herzschlag, und seine Rechenzeit hat sich seit über %d Minuten nicht bewegt. Soll es angestoßen werden?" % (
            titel, l["kanal"], minuten),
        "", "**Empfehlung von JACK:** Im Terminal-Tab „%s“ (Gerät /dev/%s, dieser Mac) das Wort `weiter` tippen und Enter drücken. "
        "Der Wächter tippt nichts selbst, weil dafür die Automation-Freigabe nötig ist." % (titel, str(befund.get("tty")).replace("/dev/", "")),
        "", "**Wo:** Programm „Terminal“ → Tab mit dem Titel oben. Befund: %s." % befund.get("grund"), ""
    ]), herkunft="bin/jack_netzwaechter.karte_ohne_herzschlag", dateiname=name)
    return pfad.name if pfad else ""


def _cpu_rate(verlauf):
    """CPU-Sekunden je Minute ueber den Verlauf, wenn er mindestens 180 s umfasst; sonst None."""
    pts = [v for v in verlauf if v[1] is not None]
    if len(pts) < 2 or pts[-1][0] - pts[0][0] < 180:
        return None
    return max(0.0, (pts[-1][1] - pts[0][1]) / (pts[-1][0] - pts[0][0]) * 60.0)


def _pid_bekannt(pid):
    return str(pid).strip().isdigit()


MELDUNG_PRAEFIX = {"kern": "F-", "sprache": "S-", "patronos": "P-", "cashflow": "VA-", "logos": "L-", "ux": "U-"}


def _meldung_alter(l, jetzt_s):
    """F-58: Alter (s) der juengsten Meldung dieses Kanals in abnahme/pm_eingang (Dateiname beginnt mit dem Kanal-Praefix), None wenn keine."""
    praefix = l.get("meldung_praefix") or MELDUNG_PRAEFIX.get(l.get("kanal"), "")
    if not praefix:
        return None
    juengste = 0.0
    try:
        for p in (JACK / "abnahme" / "pm_eingang").iterdir():
            if p.name.startswith(praefix) and p.is_file():
                juengste = max(juengste, p.stat().st_mtime)
    except OSError:
        return None
    return jetzt_s - juengste if juengste else None


def _pid_per_ordner(l):
    """F-58: Ist der Prozess nicht im Herzschlag, aber genau ein claude laeuft im Arbeitsordner des Kanals, ist es seiner."""
    ordner = os.path.realpath(os.path.expanduser(l.get("ordner") or ""))
    treffer = [p for p in _claude_prozesse() if p.get("cwd") and os.path.realpath(p["cwd"]) == ordner]
    return int(treffer[0]["pid"]) if len(treffer) == 1 and str(treffer[0]["pid"]).isdigit() else None


def _pid_unbekannt(l, herz, herz_alter, stand, jetzt_s):
    """F-58: claude_pid null/"unbekannt" (Herzschlag konnte den Prozess nicht ermitteln). Gilt als LEBEND, solange der Herzschlag frisch ist und
    sich Dateien im Kanal oder Meldungsordner bewegen; die Toleranz dauert hoechstens 15 Min, danach ok (Bewegung) oder Eskalation."""
    ruhe = _ohne_bewegung(l, herz, stand, jetzt_s)
    meld = _meldung_alter(l, jetzt_s)
    stille = min(ruhe, meld) if meld is not None else ruhe
    liegt = jack_herzschlag.aelteste_datei_alter(JACK, l["kanal"], jetzt_s)
    frisch = herz_alter <= min(l.get("toleranz_s", 600), UNBEKANNT_TOLERANZ_S)
    if frisch and liegt is not None and stille > UNBEKANNT_TOLERANZ_S:
        return {"status": "steht_trotz_auftrag", "herz": herz, "kanal": l["kanal"],
                "grund": "steht trotz Auftrag: PID unbekannt, Herzschlag vor %d s, die älteste Datei im Kanal liegt seit %d Min, seit %d Min keine Bewegung"
                         % (herz_alter, liegt // 60, stille // 60)}
    if frisch:
        return {"status": "ok", "grund": "Herzschlag vor %d s, PID unbekannt - lebend (%s)" % (
            herz_alter, "Kanal leer" if liegt is None else "Bewegung vor %d Min" % (stille // 60))}
    if stille <= UNBEKANNT_TOLERANZ_S:
        return {"status": "ok", "grund": "PID unbekannt, Herzschlag vor %d s, aber Bewegung vor %d Min (Toleranz %d Min)" % (herz_alter, stille // 60, UNBEKANNT_TOLERANZ_S // 60)}
    return {"status": "beendet", "herz": herz, "grund": "PID unbekannt, Herzschlag vor %d s, seit %d Min ohne Bewegung" % (herz_alter, stille // 60)}


def _lebt_ohne_herzschlag(l, lebende, herz, herz_alter, stand, jetzt_s):
    """F-105: Kanalprozess lebt, Herzschlag-PID ist tot/veraltet. Status bleibt "ok" (kein Alarm, kein Neustart); Log alle 15 Min.
    Erst wenn das > 1 Std anhaelt UND im Kanal seit > 15 Min ein Auftrag liegt: "steht_trotz_auftrag" - das fuehrt nur zum Tippen
    in genau diesen Tab (tty des LEBENDEN Prozesses); die PID bleibt aus dem Befund heraus, damit nie ein lebender Prozess getoetet wird."""
    p = lebende[0]
    seit = stand.setdefault("lebt_ohne_herz", {}).setdefault(l["name"], jetzt_s)
    dauer = jetzt_s - float(seit)
    grund = "lebt ohne Herzschlag: claude PID %s (%s) läuft, Herzschlag-PID %s tot, Herzschlag vor %d s (seit %d Min beobachtet)" % (
        p["pid"], p["tty"] or "ohne tty", herz.get("claude_pid"), herz_alter, dauer // 60)
    gemerkt = stand.setdefault("lebt_log", {})
    if jetzt_s - float(gemerkt.get(l["name"]) or 0) >= LEBT_LOG_ABSTAND_S:
        gemerkt[l["name"]] = jetzt_s
        _anhaengen(NEUSTARTS, "%s\tKanal Netzwaechter\tKanal %s\tKEIN Neustart (F-105): %s"
                   % (jetzt().strftime("%Y-%m-%d %H:%M:%S"), l["kanal"], grund))
    liegt = jack_herzschlag.aelteste_datei_alter(JACK, l["kanal"], jetzt_s)
    if dauer > LEBT_OHNE_HERZ_TIPP_S and liegt is not None and liegt > STEHT_TROTZ_AUFTRAG_S and p["tty"]:
        h = {k: v for k, v in herz.items() if k != "claude_pid"}
        h["tty"] = p["tty"]
        return {"status": "steht_trotz_auftrag", "herz": h, "kanal": l["kanal"],
                "grund": "steht trotz Auftrag: %s; die älteste Datei im Kanal liegt seit %d Min" % (grund, liegt // 60)}
    return {"status": "ok", "hinweis": "lebt_ohne_herzschlag", "grund": grund}


def laeufer_pruefen(l, stand, jetzt_s=None):
    """-> dict(status 'ok'|'steht'|'haengt'|'beendet'|'unbekannt', grund, massnahme)."""
    jetzt_s = jetzt_s or time.time()
    art = l["art"]
    if art == "http":
        try:
            with urllib.request.urlopen(l["url"], timeout=5) as a:
                return {"status": "ok" if a.status == 200 else "steht", "grund": "HTTP %d" % a.status}
        except (OSError, ValueError) as fehler:
            return {"status": "steht", "grund": "keine Antwort (%s)" % type(fehler).__name__}
    if art == "datei_alter":
        alter = _alter_s(l["datei"])
        if alter is None:
            return {"status": "unbekannt", "grund": "Datei fehlt"}
        return {"status": "ok" if alter <= l["toleranz_s"] else "steht", "grund": "zuletzt vor %d s" % alter}
    if art == "prozess":
        try:
            treffer = subprocess.run(["/usr/bin/pgrep", "-f", l["muster"]], capture_output=True, text=True, timeout=10).stdout.split()
        except (OSError, subprocess.SubprocessError):
            treffer = []
        return {"status": "ok" if treffer else "steht", "grund": ("PID " + ",".join(treffer)) if treffer else "Prozess fehlt"}
    if art == "postfach":
        herz = _lesen(HERZ / (l["kanal"] + ".json"), None)
        if not herz:
            return _ohne_herzschlag(l, stand, jetzt_s)
        pid = herz.get("claude_pid")
        herz_alter = jetzt_s - float(herz.get("epoch") or 0)
        if not _pid_bekannt(pid):
            pid = _pid_per_ordner(l)
            if pid is None:
                return _pid_unbekannt(l, herz, herz_alter, stand, jetzt_s)
        if not _postfach_prozess_lebt(pid):
            # F-105: die im Herzschlag stehende PID ist tot, aber ein claude mit dem Kanal-Startbefehl LEBT (Beispiel 30.09.: cashflow,
            # der neue Prozess schrieb waehrend der Arbeit keinen Herzschlag) -> KEIN Neustart, nur Vermerk "lebt ohne Herzschlag".
            lebende = _kanal_prozesse(l["kanal"])
            if lebende:
                return _lebt_ohne_herzschlag(l, lebende, herz, herz_alter, stand, jetzt_s)
            stand.get("lebt_ohne_herz", {}).pop(l["name"], None)
            # F-68: die Toleranz muss an der REALEN Zeit haengen, seit DIESER Prozess tot ist - nicht am Alter der Datei.
            # Befund: ein verwaister Herzschlag-Schreiber (abnahme/S3_2026-09-25/herzschlag_sprache.sh, claude_pid 88727
            # seit Freitag tot) schrieb alle 120 s einen frischen Zeitstempel; herz_alter blieb dadurch fuer immer klein
            # und "Toleranz laeuft" nie ab. Jetzt zaehlt, seit wann DIESE pid als tot beobachtet wird.
            merk_tot = stand.setdefault("pid_tot", {}).setdefault(l["name"], {})
            if merk_tot.get("pid") != pid:
                merk_tot.update(pid=pid, seit=jetzt_s)
            tot_seit_s = jetzt_s - float(merk_tot.get("seit") or jetzt_s)
            # F-68: "Toleranz laeuft" nur, wenn WEDER die Datei selbst alt ist (Herzschlag steht wirklich still, F-28-Fall)
            # NOCH die PID schon laenger als die Toleranz als tot beobachtet wird (Phantom-Refresh-Fall, siehe oben).
            if herz_alter <= l["toleranz_s"] and tot_seit_s <= l["toleranz_s"]:
                return {"status": "ok", "grund": "claude-Prozess %s beendet seit %d s, Herzschlag vor %d s - Toleranz läuft" % (pid, tot_seit_s, herz_alter)}
            return {"status": "beendet", "grund": "claude-Prozess %s beendet seit %d s (Herzschlag zuletzt vor %d s)" % (pid, tot_seit_s, herz_alter), "herz": herz}
        else:
            stand.get("pid_tot", {}).pop(l["name"], None)
        # F-117: Dauerbetrieb (DAUERBETRIEB_*-Datei im Kanal): die Sitzung muss je Zyklus (>= 30 Min) eine EIGENE Datei schreiben. Der Waechter rechnet selbst - dem
        # Zustand im Herzschlag ("arbeitet") traut er nicht, denn aeltere Wrapper melden "arbeitet" ohne eigene Dateien (bewerbungen 5 Std, patronos 3 Std).
        try:
            dauer = any(p.name.startswith("DAUERBETRIEB_") for p in (JACK / "auftraege" / "pm_ausgang" / str(l["kanal"])).iterdir() if p.is_file())
        except OSError:
            dauer = False
        if dauer and str(herz.get("zustand") or "").lower() in ("arbeitet", "haengt", "wartet"):
            eigen = jack_herzschlag.eigene_aktivitaet_s(JACK, l["kanal"], jetzt_s, herz.get("auftrag"))
            eigen_s = eigen if eigen is not None else STUMM_S
            if eigen_s >= STUMM_S:
                return {"status": "stumm", "herz": herz, "kanal": l["kanal"], "stumm_s": eigen_s, "dauer": True,
                        "grund": "Dauerbetrieb: seit %s keine eigene Datei der Sitzung" % (("%d Min" % (eigen // 60)) if eigen is not None else "unbekannter Zeit")}
        # F-115: Sitzung "arbeitet"/"haengt" (steht evtl. im Gespraech, Schleife laeuft nicht), im Kanal liegt eine PM-Mitteilung > 15 Min: einmal Weck-Satz;
        # nach 30 Min ohne eigene Datei wie "stumm" (weiter alle 5 Min, ab 60 Min Neustart).
        if str(herz.get("zustand") or "").lower() in ("arbeitet", "haengt", "wartet") and herz_alter <= HERZ_FRISCH_S:     # F-116: auch "wartet" - laeuft die Schleife und liegt trotzdem eine PM-Datei, hat sie nicht geweckt
            weck = jack_herzschlag.pm_weckdateien(JACK, l["kanal"], jetzt_s)
            if weck:
                eigen = jack_herzschlag.eigene_aktivitaet_s(JACK, l["kanal"], jetzt_s, herz.get("auftrag"))
                if weck[0][1] >= WECK_STUMM_S and (eigen is None or eigen >= 600):
                    return {"status": "stumm", "herz": herz, "kanal": l["kanal"], "stumm_s": weck[0][1],
                            "grund": "PM-Mitteilung %s liegt seit %d Min unbearbeitet im Kanal, keine eigene Datei seit %s" % (weck[0][0], weck[0][1] // 60, ("%d Min" % (eigen // 60)) if eigen is not None else "unbekannt")}
                return {"status": "weckreiz", "herz": herz, "kanal": l["kanal"], "dateien": [n for n, _ in weck],
                        "grund": "PM-Mitteilung(en) seit > 15 Min im Kanal ungelesen: %s" % ", ".join(n for n, _ in weck[:3])}
        # F-112: Der Takt des Wrappers schrieb "haengt" (arbeitet, aber 45 Min keine eigene Datei) und im Kanal liegt ein Auftrag: Status "stumm".
        if str(herz.get("zustand") or "").lower() == "haengt" and herz.get("quelle") == "takt" and herz_alter <= HERZ_FRISCH_S \
                and jack_herzschlag.aelteste_datei_alter(JACK, l["kanal"], jetzt_s) is not None:
            eigen = jack_herzschlag.eigene_aktivitaet_s(JACK, l["kanal"], jetzt_s, herz.get("auftrag"))
            if eigen is None or eigen >= STUMM_S:
                eigen = eigen if eigen is not None else STUMM_NEUSTART_S
                return {"status": "stumm", "herz": herz, "kanal": l["kanal"], "stumm_s": eigen,
                        "grund": "hängt: Zustand 'arbeitet', aber seit %d Min keine eigene Datei (Auftrag %s liegt im Kanal)" % (eigen // 60, herz.get("auftrag") or "?")}
        cpu = _rechenzeit(pid)
        merk = stand.setdefault("cpu", {}).setdefault(l["name"], {})
        if merk.get("pid") != pid or merk.get("cpu") != cpu:
            merk.update(pid=pid, cpu=cpu, seit=jetzt_s)
        cpu_ruhe = jetzt_s - float(merk.get("seit") or jetzt_s)
        # F-58: "unveraendert" allein reichte nicht - eine wartende Sitzung ruehrt die Rechenzeit um Hundertstel, dadurch galt patronos
        # 13 Stunden ohne Herzschlag als ok. Zusaetzlich zaehlt jetzt die Rate (unter der Arbeitsschwelle ueber mindestens 3 Min).
        verlauf0 = stand.setdefault("cpu_verlauf", {}).setdefault(l["name"], [])
        rate0 = _cpu_rate(verlauf0 + [[jetzt_s, cpu]])
        # F-61: Ohne wartenden Auftrag gibt es nichts anzustossen - ein erloschener Herzschlag bei leerem Kanal ist ruhig (cashflow bekam sonst
        # alle 17 Min ein "weiter"). Kommt ein Auftrag, greift dieser Zweig, sobald er im Kanal liegt.
        liegt0 = jack_herzschlag.aelteste_datei_alter(JACK, l["kanal"], jetzt_s)
        if herz_alter > l["toleranz_s"] and liegt0 is not None and (cpu_ruhe > l["toleranz_s"] or (rate0 is not None and rate0 < ARBEIT_CPU_S_JE_MIN)):
            return {"status": "haengt", "grund": "Herzschlag vor %d s, Rechenzeit seit %d s unverändert" % (herz_alter, cpu_ruhe),
                    "herz": herz}
        # F-45: Herzschlag sagt "wartet" und ist frisch, im Kanal liegt aber seit > 15 Min ein Auftrag = steht trotz Auftrag.
        # F-50: dasselbe bei leerem/fehlendem "zustand" (alte Schleife), wenn das Terminal nicht erkennbar arbeitet, und bei dem
        # Widerspruch "Kanal leer" im Herzschlag-Text bei nicht leerem Ordner. "arbeitet"/anderer Text im zustand: kein Alarm.
        verlauf = stand.setdefault("cpu_verlauf", {}).setdefault(l["name"], [])
        verlauf.append([jetzt_s, cpu])
        verlauf[:] = [v for v in verlauf if jetzt_s - v[0] <= 400]
        rate = _cpu_rate(verlauf)
        zust = str(herz.get("zustand") or "").strip().lower()
        liegt = jack_herzschlag.aelteste_datei_alter(JACK, l["kanal"], jetzt_s)
        if herz_alter <= l["toleranz_s"] and liegt is not None:
            grenze = l.get("steht_trotz_auftrag_s", STEHT_TROTZ_AUFTRAG_S)
            arbeitet = rate is None or rate > ARBEIT_CPU_S_JE_MIN         # unbekannt (zu wenig Verlauf) zaehlt vorsichtig als "arbeitet"
            if zust.startswith("wart") and liegt > grenze:
                warum = "Herzschlag meldet 'wartet' (vor %d s)" % herz_alter
            elif zust == "" and liegt > grenze and not arbeitet:
                warum = "Herzschlag ohne Zustand (alte Schleife, vor %d s), Terminal arbeitet nicht (Rechenzeit %.1f s/Min)" % (herz_alter, rate)
            elif zust == "" and liegt > ALTFORMAT_STILLSTAND_S and _ohne_bewegung(l, herz, stand, jetzt_s) > ALTFORMAT_STILLSTAND_S:
                # F-58: altes Herzschlag-Format (ohne zustand): die Bewegungsregel gilt auch, wenn die Rechenzeit "Arbeit" vortaeuscht -
                # ein Kanal, in dem 2 Stunden lang nichts aufgenommen wird, steht (Rechenzeit-Rauschen einer wartenden Sitzung).
                warum = "Herzschlag ohne Zustand (altes Format, vor %d s), Auftrag seit %d Min ohne Bewegung" % (herz_alter, _ohne_bewegung(l, herz, stand, jetzt_s) // 60)
            elif "kanal leer" in str(herz.get("auftrag") or "").lower() and liegt > WIDERSPRUCH_S and liegt > herz_alter + 60:
                warum = "Widerspruch: Herzschlag sagt '%s', im Ordner liegt aber eine Datei" % str(herz.get("auftrag"))[:60]
            else:
                warum = ""
            # F-61 (Luecke D): Egal was der Herzschlag sagt ("arbeitet" eingeschlossen): liegt ein Auftrag im Kanal, dessen Datei NEUER ist als die
            # letzte Aufnahme, und es gab 20 Min keine Dateibewegung (Kanal, abnahme/, Repo), dann hat die Schleife ihn nicht genommen.
            luecke_d = ""
            if not warum:
                aufn = _zeit(herz.get("letzte_aufnahme")) if herz.get("letzte_aufnahme") else None
                aufn = aufn.timestamp() if aufn else None
                aelteste_mtime = jetzt_s - liegt
                still = _ohne_bewegung(l, herz, stand, jetzt_s)
                akt = jack_herzschlag.dateiaktivitaet_s(JACK, l["kanal"], jetzt_s)       # eigene Messung des Waechters (Kanal, abnahme/, Repo)
                if isinstance(akt, (int, float)):
                    still = min(still, float(akt))
                if (aufn is None or aufn < aelteste_mtime) and still >= DATEISTILLE_S and liegt >= DATEISTILLE_S:
                    luecke_d = warum = "Lücke D: Herzschlag meldet '%s', ein Auftrag liegt seit %d Min im Kanal, keine Aufnahme (letzte: %s), seit %d Min keine Dateibewegung" % (
                        zust or "ohne Zustand", liegt // 60, herz.get("letzte_aufnahme") or "unbekannt", still // 60)
            # F-55: Rot nur bei Stillstand. Frischer Herzschlag (<= 5 Min) mit Zustand "arbeitet" ist nie rot; sonst nur, wenn der
            # Herzschlag aelter als 5 Min ist ODER der Auftrag > 30 Min ohne Bewegung liegt. Die Widerspruchsregel (F-50) bleibt.
            ruhe = _ohne_bewegung(l, herz, stand, jetzt_s)
            if luecke_d:
                pass                                            # F-61: gilt auch bei "arbeitet" und frischem Herzschlag
            elif warum and not warum.startswith("Widerspruch"):
                if zust.startswith("arbeit") and herz_alter <= HERZ_FRISCH_S:
                    warum = ""
                elif herz_alter <= HERZ_FRISCH_S and ruhe <= BEWEGUNG_S:
                    warum = ""
            elif warum and zust.startswith("arbeit") and herz_alter <= HERZ_FRISCH_S:
                warum = ""
            if warum:
                return {"status": "steht_trotz_auftrag", "herz": herz, "kanal": l["kanal"],
                        "grund": "steht trotz Auftrag: %s; die älteste Datei im Kanal liegt seit %d Min (letzte Aufnahme: %s)"
                                 % (warum, liegt // 60, herz.get("letzte_aufnahme") or "unbekannt")}
        # F-72: Schutznetz - ein Herzschlag aelter als die Toleranz darf NIE "ok" sein, auch wenn kein Auftrag im Kanal
        # liegt (liegt is None, F-61-Fall) und die CPU-Rate keinen "haengt"-Befund ausloest (Befund: postfach_cashflow
        # 75283 s alt, Prozess lebt/arbeitet an anderer Stelle, kein anderer Zweig griff -> faelschlich "ok").
        if herz_alter > l["toleranz_s"]:
            # F-99 K: lange Auftragsarbeit ohne Herzschlag ist KEIN Stillstand. Dateiaktivitaet im Kanal/abnahme/Repo in den letzten
            # 10 Min (eigene Messung) heisst "arbeitet"; der Alarm kommt erst bei Stille.
            akt = jack_herzschlag.eigene_aktivitaet_s(JACK, l["kanal"], jetzt_s, herz.get("auftrag"))     # F-117: nur EIGENE Dateien (nicht Repo/andere Kanaele)
            if isinstance(akt, (int, float)) and akt <= 600:
                return {"status": "ok", "grund": "Herzschlag vor %d s, aber eigene Dateiaktivität vor %d s: arbeitet an einem Auftrag" % (herz_alter, akt)}
            return {"status": "herz_alt", "herz": herz, "kanal": l["kanal"],
                    "grund": "Herzschlag alt: vor %d s (Toleranz %d s), kein Auftrag/keine CPU-Bewegung hat das sonst erkannt"
                             % (herz_alter, l["toleranz_s"])}
        return {"status": "ok", "grund": "Herzschlag vor %d s, Prozess %s arbeitet/wartet" % (herz_alter, pid)}
    return {"status": "unbekannt", "grund": "Art unbekannt"}


def _ohne_bewegung(l, herz, stand, jetzt_s):
    """F-55: Sekunden ohne Bewegung im Kanal. Bewegung = neue/geaenderte Datei im Kanal, neue `letzte_aufnahme` oder ein anderer
    Herzschlag-Text `auftrag`. Erste Beobachtung: seit der juengsten Dateiaenderung im Kanal."""
    ordner = JACK / "auftraege" / "pm_ausgang" / str(l["kanal"])
    juengste = 0.0
    try:
        for p in ordner.iterdir():
            if p.is_file():
                juengste = max(juengste, p.stat().st_mtime)
    except OSError:
        pass
    schluessel = [str(herz.get("auftrag") or ""), str(herz.get("letzte_aufnahme") or ""), round(juengste, 1)]
    merk = stand.setdefault("bewegung", {}).setdefault(l["name"], {})
    if merk.get("schluessel") != schluessel:
        if "schluessel" in merk or not juengste:
            merk["seit"] = jetzt_s
        else:
            merk["seit"] = juengste
        merk["schluessel"] = schluessel
    return max(0.0, jetzt_s - float(merk.get("seit") or jetzt_s))


# ------------------------------------------------------------------ 3 Wiederanlauf
def fremde_sicherung_jung(jack=JACK):
    grenze = time.time() - SICHERUNG_RUHE_S
    for muster in ("*.vor_*", "betrieb/*.vor_*"):
        for p in jack.glob(muster):
            try:
                if p.stat().st_mtime > grenze:
                    return p.name
            except OSError:
                continue
    return None


def _osascript(skript):
    # F-68-Nachtrag (Patron-Anweisung 27.09.2026, nach echten Terminal-Fenstern aus einer ungewollt ungemockten
    # Testschleife): JACK_NETZ_WURZEL setzt AUSNAHMSLOS nur eine Testumgebung (siehe modul()-Helfer in jedem
    # abnahme/*/test_*.py; die echte, produktive Wurzel setzt diese Variable nie). Ein osascript-Aufruf dort waere
    # immer ein Programmierfehler - lieber ein lauter Testfehler als ein echtes Terminal-Fenster auf dem Mac des
    # Patrons. Wer in einem Test wirklich terminal_starten/terminal_tippen ausloesen will, mockt _osascript selbst.
    if os.environ.get("JACK_NETZ_WURZEL"):
        raise RuntimeError("_osascript blockiert: JACK_NETZ_WURZEL ist gesetzt (Testumgebung) - echte Terminal-"
                           "Steuerung ist hier verboten. In Tests IMMER terminal_starten/terminal_tippen/_osascript mocken.")
    r = subprocess.run(["/usr/bin/osascript", "-e", skript], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip()[:300])
    return r.stdout.strip()


def _as_text(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def terminal_tippen(tty, satz):
    """Satz + Enter in genau den Terminal-Tab mit diesem tty (Terminal.app, Automation-Freigabe noetig; F-36 geprueft)."""
    return _osascript('tell application "Terminal"\nrepeat with w in windows\nrepeat with t in tabs of w\n'
                      'if tty of t is %s then\ndo script %s in t\nreturn "ok"\nend if\nend repeat\nend repeat\n'
                      'return "tab fehlt"\nend tell' % (_as_text("/dev/" + tty.replace("/dev/", "")), _as_text(satz)))


def terminal_weiter(tty):
    """'weiter' + Enter in genau den Terminal-Tab mit diesem tty."""
    return terminal_tippen(tty, "weiter")


# F-86 (K): jedes Kanal-Fenster traegt dauerhaft genau diesen Titel.
TERMINAL_TITEL = {"kern": "JACK Kern", "cashflow": "JACK Cashflow", "gruendung": "JACK Gründung",
                  "bewerbungen": "JACK Bewerbungen", "inhalt": "JACK Inhalt", "patronos": "JACK PATRONOS",
                  "sprache": "JACK Sprache", "social": "JACK Social"}


# ------------------------------------------------------------------ F-105: kein Doppelstart
# Befund 30.09.2026 15:33-15:35: nach dem Rechner-Neustart startete der Waechter cashflow dreimal (Herzschlag trug die tote PID,
# der neue Prozess schrieb waehrend der Arbeit keinen). Jetzt: Startsperre nach Rechner-Neustart, lebender Kanalprozess = kein Start,
# hoechstens 1 Start je Kanal und 15 Min, Startwrapper mit Sperrdatei (bin/kanal_start.py).
STARTSPERRE_BOOT_S = 180
KANAL_START_ABSTAND_S = 900
LEBT_LOG_ABSTAND_S = 900
LEBT_OHNE_HERZ_TIPP_S = 3600
KANAL_START = Path(__file__).resolve().parent / "kanal_start.py"


def _ps_zeilen():
    """Zeilen `pid tty command` aller Prozesse. In der Testumgebung (JACK_NETZ_WURZEL) leer - Tests mocken diese Funktion."""
    if os.environ.get("JACK_NETZ_WURZEL"):
        return []
    try:
        return subprocess.run(["/bin/ps", "-axo", "pid=,tty=,command="], capture_output=True, text=True, timeout=10).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        return []


def _kanal_prozesse(kanal, ausser=()):
    """F-105: lebende claude-Prozesse [{pid, tty}] mit dem Kanal-Startbefehl (`pm_ausgang/<kanal>/` im Auftragstext).
    Nur das claude-Programm selbst zaehlt (nicht caffeinate/zsh/Bash-Werkzeuge, die den Text ebenfalls tragen)."""
    marke = "pm_ausgang/%s/" % kanal
    raus = []
    for z in _ps_zeilen():
        m = re.match(r"\s*(\d+)\s+(\S+)\s+(\S*/)?claude\s(.*)$", z)
        if m and marke in m.group(4) and int(m.group(1)) not in {int(a) for a in ausser if str(a).isdigit()}:
            raus.append({"pid": int(m.group(1)), "tty": "" if m.group(2) in ("?", "??") else m.group(2)})
    return raus


def _boot_epoch():
    if os.environ.get("JACK_NETZ_WURZEL"):
        return None
    try:
        aus = subprocess.run(["/usr/sbin/sysctl", "-n", "kern.boottime"], capture_output=True, text=True, timeout=5).stdout
        m = re.search(r"sec\s*=\s*(\d+)", aus)
        return float(m.group(1)) if m else None
    except (OSError, subprocess.SubprocessError):
        return None


def _wrapper_haelt_sperre(kanal):
    """F-105 Punkt 5: haelt ein laufender Startwrapper die Sperrdatei betrieb/laeuft/<kanal>.pid (flock)?"""
    try:
        import kanal_start
        return kanal_start.laeuft(kanal, JACK) is not None
    except Exception:
        return False


def start_sperre(l, stand, jetzt_s, ausser=(), pruefe_abstand=True):
    """F-105: Grund (Text), warum der Waechter diesen Kanal JETZT NICHT starten darf, sonst None."""
    boot = _boot_epoch()
    if boot and jetzt_s - boot < STARTSPERRE_BOOT_S:
        return "Startsperre nach Rechner-Neustart (%d von %d s)" % (jetzt_s - boot, STARTSPERRE_BOOT_S)
    lebt = _kanal_prozesse(l["kanal"], ausser)
    if lebt:
        return "lebt ohne Herzschlag: claude PID %s (%s) läuft mit dem Kanal-Startbefehl" % (lebt[0]["pid"], lebt[0]["tty"] or "ohne tty")
    if _wrapper_haelt_sperre(l["kanal"]) and not ausser:
        return "Startwrapper für Kanal %s hält die Sperrdatei (betrieb/laeuft)" % l["kanal"]
    letzte = (stand.get("kanal_starts") or {}).get(l["name"])
    if pruefe_abstand and letzte and jetzt_s - float(letzte) < KANAL_START_ABSTAND_S:
        return "höchstens 1 Start je Kanal und 15 Min (letzter vor %d s)" % (jetzt_s - float(letzte))
    return None


def start_vermerken(l, stand, jetzt_s):
    stand.setdefault("kanal_starts", {})[l["name"]] = jetzt_s


def start_verweigert(l, stand, jetzt_s, grund):
    """Eintrag im neustarts.log (je Kanal hoechstens alle 15 Min) und Rueckgabe der Massnahme."""
    gemerkt = stand.setdefault("start_log", {})
    if jetzt_s - float(gemerkt.get(l["name"]) or 0) >= LEBT_LOG_ABSTAND_S:
        gemerkt[l["name"]] = jetzt_s
        _anhaengen(NEUSTARTS, "%s\tKanal Netzwaechter\tKanal %s\tKEIN Start (F-105): %s"
                   % (jetzt().strftime("%Y-%m-%d %H:%M:%S"), l["kanal"], grund))
    return {"massnahme": "kein Start (F-105): " + grund}


def terminal_starten(kanal, ordner, befehl):
    # F-105: der Befehl laeuft ueber den Startwrapper (Sperrdatei je Kanal, Herzschlag-Takt waehrend der Arbeit)
    zeile = "cd %s && /usr/bin/python3 %s %s %s" % (_shell(ordner), _shell(str(KANAL_START)), _shell(kanal), _shell(befehl))
    return _osascript('tell application "Terminal"\nactivate\nset t to do script %s\nset custom title of t to %s\n'
                      'return "ok"\nend tell' % (_as_text(zeile), _as_text(TERMINAL_TITEL.get(kanal, "JACK " + kanal.capitalize()))))


def _shell(s):
    return "'" + s.replace("'", "'\\''") + "'"


def _signatur(l, herz):
    """F-58: Was sich aendern muss, damit ein Anstoss als wirksam gilt: Kanaldateien (Name + Aenderungszeit), Herzschlag-Zustand/-Text/letzte Aufnahme."""
    ordner = JACK / "auftraege" / "pm_ausgang" / str(l["kanal"])
    dateien = []
    try:
        dateien = sorted((p.name, round(p.stat().st_mtime)) for p in ordner.iterdir() if p.is_file())
    except OSError:
        pass
    return [dateien, str(herz.get("zustand") or ""), str(herz.get("auftrag") or ""), str(herz.get("letzte_aufnahme") or "")]


def _eskalation_faellig(l, befund, stand, jetzt_s):
    """-> Grundtext oder None. steht_trotz_auftrag/haengt: ESKALATION_NACH Anstoesse liegen vor, der letzte >= 5 Min her, und der Zustand hat
    sich seither nicht bewegt. Ohne tty (nichts zu tippen): sofort. haengt zusaetzlich erst nach 30 Min ohne Herzschlag. beendet mit unbekannter PID."""
    herz = befund.get("herz") or {}
    name = l["name"]
    status = befund.get("status")
    if status == "beendet":
        return "Prozess unbekannt und seit Ende der Toleranz ohne Bewegung" if not _pid_bekannt(herz.get("claude_pid")) else None
    if status in ("haengt", "herz_alt") and jetzt_s - float(herz.get("epoch") or jetzt_s) < 1800:
        return None
    ans = [a for a in stand.setdefault("anstoesse", {}).get(name, []) if jetzt_s - a["t"] < 6 * 3600]
    stand["anstoesse"][name] = ans
    kein_tty = not str(herz.get("tty") or "").strip()
    if kein_tty:
        return "Anstoß nicht möglich (tty unbekannt)"
    sig = _signatur(l, herz)
    wirkungslos = [a for a in ans if a["sig"] == sig]
    if status == "haengt":            # ein Herzschlag NACH dem Anstoss ist eine Wirkung (die Sitzung lebt), auch wenn er wieder verstummt
        wirkungslos = [a for a in wirkungslos if float(herz.get("epoch") or 0) <= a["t"]]
    if len(wirkungslos) >= ESKALATION_NACH and jetzt_s - max(a["t"] for a in wirkungslos) >= 300:
        return "Anstoß ×%d wirkungslos" % ESKALATION_NACH
    return None


def kanal_neustart(l, befund, stand, grund, trocken=False, jetzt_s=None, ignoriere_ruhe=False):
    """F-58: Kanal-Terminal neu starten (alter claude-Prozess beenden, wenn bekannt, neuer Terminal-Tab mit dem Startbefehl).
    Regeln: STOPP_PM ⇒ nichts; Ruhe-Regel Patron (jack_ruhe) ⇒ verschoben - ausser `ignoriere_ruhe` (F-68: der Patron hat
    diesen einen Neustart per FREIGEBEN auf der Karte ausdruecklich erlaubt, das ersetzt die Ruhe-Regel fuer DIESEN Klick);
    hoechstens 1 Neustart je Kanal und Stunde (gilt immer, auch mit ignoriere_ruhe)."""
    jetzt_s = jetzt_s or time.time()
    name = l["name"]
    if (JACK / "auftraege/pm_ausgang/STOPP_PM").exists():
        return {"massnahme": "kein Kanal-Neustart: STOPP_PM gesetzt"}
    aktiv, warum = (False, "") if ignoriere_ruhe else jack_ruhe.patron_aktiv(BETRIEB)
    if aktiv:
        gemerkt = stand.setdefault("ruhe_log", {})
        if jetzt_s - float(gemerkt.get(name) or 0) >= 300:
            gemerkt[name] = jetzt_s
            _anhaengen(NEUSTARTS, "%s\tKanal Netzwaechter\tNeustart verschoben: Patron aktiv (Kanal %s: %s) - %s"
                       % (jetzt().strftime("%Y-%m-%d %H:%M:%S"), l["kanal"], grund, warum))
        return {"massnahme": "verschoben: Patron aktiv (%s)" % warum}
    # F-89 (M-5a): Sperre um den kritischen Abschnitt - schliesst die Rennbedingung, die am 29.09. zu vier
    # gleichzeitig gestarteten Kern-Terminals fuehrte (mehrere Prozesse lasen den Stand, bevor einer seinen
    # Zeitstempel zurueckgeschrieben hatte). Innerhalb der Sperre wird der persistierte Stand fuer GENAU diesen
    # Kanal frisch von der Platte gelesen (nicht das evtl. veraltete `stand`-Objekt des Aufrufers) und die
    # Entscheidung sofort zurueckgeschrieben, bevor die Sperre wieder freigegeben wird.
    with _kanal_neustart_sperre():
        persistiert = _lesen(STAND, {}) or {}
        frueher = [t for t in (persistiert.get("kanal_neustarts") or {}).get(name, []) if jetzt_s - t < 3600]
        stand.setdefault("kanal_neustarts", {})[name] = frueher
        if frueher:
            return {"massnahme": "gesperrt (höchstens 1 Kanal-Neustart je Stunde, letzter vor %d Min)" % ((jetzt_s - max(frueher)) // 60)}
        herz = befund.get("herz") or {}
        pid = herz.get("claude_pid")
        alt = "alter Prozess %s beendet" % pid if _pid_bekannt(pid) and _postfach_prozess_lebt(pid) else "alter Prozess unbekannt/beendet"
        # F-105: nach dem Beenden des bekannten Prozesses darf kein ANDERER Kanalprozess leben; Startsperre nach Rechner-Neustart
        sp = start_sperre(l, stand, jetzt_s, ausser=[pid] if _pid_bekannt(pid) else (), pruefe_abstand=False)
        if sp:
            return start_verweigert(l, stand, jetzt_s, sp)
        if trocken:
            return {"massnahme": "TROCKEN: Kanal-Neustart (%s; %s)" % (grund, alt)}
        # Zeitstempel SOFORT reservieren (vor dem eigentlichen Neustart) und persistieren, damit ein Zweitprozess,
        # der waehrend des laufenden Neustarts (Prozess beenden, Terminal oeffnen - kann Sekunden dauern) auf die
        # Sperre wartet, sie beim Eintritt bereits gesetzt vorfindet.
        frueher.append(jetzt_s)
        persistiert.setdefault("kanal_neustarts", {})[name] = frueher
        _schreiben(STAND, persistiert)
        try:
            if _pid_bekannt(pid) and _postfach_prozess_lebt(pid):
                os.kill(int(pid), 15)
                for _ in range(20):
                    if not _prozess_lebt(pid):
                        break
                    time.sleep(0.5)
            terminal_starten(l["kanal"], l["ordner"], l["befehl"])
            start_vermerken(l, stand, jetzt_s)
            ergebnis = "ok"
        except Exception as fehler:
            ergebnis = "fehlgeschlagen: %s" % str(fehler)[:200]
    stand.setdefault("anstoesse", {})[name] = []
    _anhaengen(NEUSTARTS, "%s\tKanal Netzwaechter\tKanal %s\tKanal-Neustart, Grund: %s (%s), neuer Terminal-Tab -> %s"
               % (jetzt().strftime("%Y-%m-%d %H:%M:%S"), l["kanal"], grund, alt, ergebnis))
    return {"massnahme": "Kanal-Neustart: %s (%s) - %s" % (grund, alt, ergebnis)}


def wiederanlauf(l, befund, stand, trocken=False, jetzt_s=None):
    jetzt_s = jetzt_s or time.time()
    name = l["name"]
    liste = [t for t in stand.setdefault("neustarts", {}).get(name, []) if jetzt_s - t < 3600]
    stand["neustarts"][name] = liste
    # F-58: Eskalation. Nach ESKALATION_NACH wirkungslosen Anstoessen (Kanaldatei und Herzschlag-Zustand unveraendert) - oder wenn gar nicht
    # getippt werden kann (tty unbekannt) - wird der Kanal neu gestartet (Ruhe-Regel, hoechstens 1 je Stunde und Kanal).
    # F-72: "herz_alt" (Herzschlag aelter als Toleranz, kein anderer Befund hat es erkannt - eigener Name, damit er
    # nicht mit dem allgemeinen "steht" fuer http/prozess/datei_alter kollidiert) laeuft durch dieselbe
    # Anstoss-/Neustart-Kette wie "haengt" - der Prozess lebt nachweislich (sonst waere der Befund "beendet"),
    # also erst per Anstoss wecken, erst nach ESKALATION_NACH wirkungslosen Anstoessen neu starten.
    if l["art"] == "postfach" and befund.get("status") == "weckreiz":
        herz = befund.get("herz") or {}
        sig = sorted(befund.get("dateien") or [])
        gemerkt = stand.setdefault("weck", {}).get(name) or {}
        if gemerkt.get("sig") == sig:
            return {"massnahme": "wartet: Weck-Satz für diese Mitteilung(en) schon getippt (%d Min her)" % ((jetzt_s - float(gemerkt.get("t") or jetzt_s)) // 60)}
        if (JACK / "auftraege/pm_ausgang/STOPP_PM").exists():
            return {"massnahme": "kein Weck-Satz: STOPP_PM gesetzt"}
        satz = "Kanal %s neu lesen — alle Dateien in auftraege/pm_ausgang/%s/ in Reihenfolge ihrer Zeit abarbeiten, erste Datei %s" % (l["kanal"], l["kanal"], sig and befund["dateien"][0])
        if trocken:
            return {"massnahme": "TROCKEN: Weck-Satz getippt in %s" % herz.get("tty")}
        try:
            terminal_tippen(herz.get("tty") or "", satz)
            ergebnis = "ok"
        except Exception as fehler:
            ergebnis = "fehlgeschlagen: %s" % str(fehler)[:200]
        stand["weck"][name] = {"sig": sig, "t": jetzt_s}
        _anhaengen(NEUSTARTS, "%s\tKanal Netzwaechter\tLaeufer %s (%s)\tWeck-Satz getippt in %s -> %s" % (jetzt().strftime("%Y-%m-%d %H:%M:%S"), name, befund.get("grund"), herz.get("tty"), ergebnis))
        return {"massnahme": "Weck-Satz getippt in %s - %s" % (herz.get("tty"), ergebnis)}
    if l["art"] == "postfach" and befund.get("status") == "stumm" and befund.get("dauer") and (befund.get("stumm_s") or 0) >= STUMM_S:
        # F-117: Dauerbetrieb ohne eigene Datei: ZUERST ein Weck-Satz; Neustart erst, wenn 15 Min danach noch immer keine eigene Datei entstanden ist.
        herz = befund.get("herz") or {}
        gemerkt = stand.setdefault("weck_dauer", {}).get(name) or {}
        if gemerkt and jetzt_s - float(gemerkt.get("t") or 0) < 900:
            return {"massnahme": "wartet: Weck-Satz vor %d Min getippt, Neustart frühestens nach 15 Min ohne eigene Datei" % ((jetzt_s - float(gemerkt["t"])) // 60)}
        if gemerkt and (befund.get("stumm_s") or 0) < jetzt_s - float(gemerkt["t"]):
            stand["weck_dauer"].pop(name, None)             # die Sitzung hat seit dem Weck-Satz eine eigene Datei geschrieben (Wirkung): dieser neue Stillstand beginnt von vorn
            gemerkt = {}
        if not gemerkt:
            if (JACK / "auftraege/pm_ausgang/STOPP_PM").exists():
                return {"massnahme": "kein Weck-Satz: STOPP_PM gesetzt"}
            satz = "Kanal %s neu lesen — alle Dateien in auftraege/pm_ausgang/%s/ in Reihenfolge ihrer Zeit abarbeiten, dann den nächsten Dauerbetrieb-Zyklus mit Meldung %s-ZYKLUS_<HH>.md" % (l["kanal"], l["kanal"], l["kanal"])
            if trocken:
                return {"massnahme": "TROCKEN: Weck-Satz (Dauerbetrieb) getippt in %s" % herz.get("tty")}
            try:
                terminal_tippen(herz.get("tty") or "", satz)
                ergebnis = "ok"
            except Exception as fehler:
                ergebnis = "fehlgeschlagen: %s" % str(fehler)[:200]
            stand["weck_dauer"][name] = {"t": jetzt_s}
            _anhaengen(NEUSTARTS, "%s\tKanal Netzwaechter\tLaeufer %s (%s)\tWeck-Satz (Dauerbetrieb) getippt in %s -> %s" % (jetzt().strftime("%Y-%m-%d %H:%M:%S"), name, befund.get("grund"), herz.get("tty"), ergebnis))
            return {"massnahme": "Weck-Satz (Dauerbetrieb) getippt in %s - %s" % (herz.get("tty"), ergebnis)}
        r = kanal_neustart(l, befund, stand, "Dauerbetrieb: 15 Min nach dem Weck-Satz noch keine eigene Datei (F-117)", trocken=trocken, jetzt_s=jetzt_s)
        if not trocken and (r["massnahme"].startswith("verschoben: Patron aktiv") or r["massnahme"].startswith("gesperrt (")):
            karte_neustart_noetig(l, "Dauerbetrieb stumm (%s)" % r["massnahme"])
        if not trocken and r["massnahme"].startswith("Kanal-Neustart"):
            stand["weck_dauer"].pop(name, None)
        return r
    if l["art"] == "postfach" and befund.get("status") == "stumm" and (befund.get("stumm_s") or 0) >= STUMM_NEUSTART_S:
        # F-112: ab 60 Min ohne eigene Datei Neustart (vorher wurde ab 45 Min angestossen: "weiter")
        r = kanal_neustart(l, befund, stand, "stumm seit %d Min ohne eigene Datei (F-112)" % (befund["stumm_s"] // 60), trocken=trocken, jetzt_s=jetzt_s)
        if not trocken and (r["massnahme"].startswith("verschoben: Patron aktiv") or r["massnahme"].startswith("gesperrt (")):
            karte_neustart_noetig(l, "stumm seit %d Min (%s)" % (befund["stumm_s"] // 60, r["massnahme"]))
        return r
    if l["art"] == "postfach" and befund.get("status") in ("steht_trotz_auftrag", "haengt", "herz_alt", "beendet"):
        entscheidung = _eskalation_faellig(l, befund, stand, jetzt_s)
        if entscheidung:
            r = kanal_neustart(l, befund, stand, entscheidung, trocken=trocken, jetzt_s=jetzt_s)
            # F-68: NUR jetzt (Waechter kommt selbst nicht weiter) eine Karte - nicht schon beim ersten Anstoss.
            if not trocken and (r["massnahme"].startswith("verschoben: Patron aktiv") or r["massnahme"].startswith("gesperrt (")):
                karte_neustart_noetig(l, "%s (%s)" % (entscheidung, r["massnahme"]))
            return r
    if befund.get("status") in ("steht_trotz_auftrag", "haengt", "herz_alt", "stumm") and liste and jetzt_s - max(liste) < 300:
        return {"massnahme": "wartet (Abstand: letzter Anstoß vor %d s, nächster frühestens nach 5 Min)" % (jetzt_s - max(liste))}
    if len(liste) >= MAX_JE_STUNDE:
        karte_deckel(l, befund, liste)
        return {"massnahme": "gesperrt (Deckel 3 je Stunde erreicht, Karte im Freigabe-Ordner)"}
    if l["art"] == "postfach":
        if (JACK / "auftraege/pm_ausgang/STOPP_PM").exists():
            return {"massnahme": "kein Wiederanlauf: STOPP_PM gesetzt"}
        herz = befund.get("herz") or {}
        if befund["status"] in ("haengt", "herz_alt", "stumm"):
            aktion, tun = "weiter getippt in %s%s" % (herz.get("tty"), " (stumm: Vermerk 'hängt', F-112)" if befund["status"] == "stumm" else ""), lambda: terminal_weiter(herz.get("tty") or "")
            if not trocken:
                stand.setdefault("anstoesse", {}).setdefault(name, []).append({"t": jetzt_s, "sig": _signatur(l, herz)})
        elif befund["status"] == "steht_trotz_auftrag":
            satz = NEU_LESEN_SATZ % l["kanal"]
            aktion, tun = "getippt in %s: %s" % (herz.get("tty"), satz), lambda: terminal_tippen(herz.get("tty") or "", satz)
            if not trocken:
                stand.setdefault("anstoesse", {}).setdefault(name, []).append({"t": jetzt_s, "sig": _signatur(l, herz)})
        else:
            # F-105: Startsperre nach Rechner-Neustart, lebender Kanalprozess, 1 Start je Kanal und 15 Min
            sp = start_sperre(l, stand, jetzt_s)
            if sp:
                return start_verweigert(l, stand, jetzt_s, sp)
            aktion, tun = "neuer Terminal-Tab", lambda: terminal_starten(l["kanal"], l["ordner"], l["befehl"])
            if not trocken:
                start_vermerken(l, stand, jetzt_s)
    else:
        # F-67: Ist der Dienst gar nicht da (nicht nur haengend), gilt die Ruhe-Regel nicht - sofortiger Neustart.
        dienst_fehlt = jack_ruhe.dienst_fehlt_ganz(befund)
        if not dienst_fehlt:
            # F-56: Ruhe-Regel Patron - solange der Patron JACK benutzt, kein Dienst-Neustart (er zerstoert seine Sitzung). Neu pruefen im naechsten Takt.
            aktiv, warum = jack_ruhe.patron_aktiv(BETRIEB)
            if aktiv:
                gemerkt = stand.setdefault("ruhe_log", {})
                if jetzt_s - float(gemerkt.get(name) or 0) >= 300:
                    gemerkt[name] = jetzt_s
                    _anhaengen(NEUSTARTS, "%s\tKanal Netzwaechter\tNeustart verschoben: Patron aktiv (Laeufer %s: %s) - %s"
                               % (jetzt().strftime("%Y-%m-%d %H:%M:%S"), name, befund.get("grund"), warum))
                return {"massnahme": "verschoben: Patron aktiv (%s), neue Pruefung im naechsten Takt" % warum}
        jung = fremde_sicherung_jung()
        if jung:
            return {"massnahme": "wartet (README-Regel: fremde Sicherung %s jünger als 10 Min)" % jung}
        if dienst_fehlt and not trocken:
            _anhaengen(NEUSTARTS, "%s\tKanal Netzwaechter\tNeustart sofort: Dienst fehlt (Ruhe-Ausnahme F-67) - Laeufer %s"
                       % (jetzt().strftime("%Y-%m-%d %H:%M:%S"), name))
        aktion = "launchctl kickstart -k %s" % l["dienst"]
        tun = lambda: subprocess.run(["/bin/launchctl", "kickstart", "-k", "gui/%d/%s" % (os.getuid(), l["dienst"])],
                                     check=True, capture_output=True, timeout=60)
    if trocken:
        return {"massnahme": "TROCKEN: " + aktion}
    try:
        tun()
        ergebnis = "ok"
    except Exception as fehler:
        ergebnis = "fehlgeschlagen: %s" % str(fehler)[:200]
    liste.append(jetzt_s)
    _anhaengen(NEUSTARTS, "%s\tKanal Netzwaechter\tLaeufer %s (%s)\t%s -> %s" % (
        jetzt().strftime("%Y-%m-%d %H:%M:%S"), name, befund.get("grund"), aktion, ergebnis))
    return {"massnahme": aktion + " – " + ergebnis}


def karte_steht_trotz_auftrag(l, befund):
    """F-45: Karte mit Tab-Titel und dem Satz, der eingetippt wird (einmal je Kanal und Tag). Der Waechter tippt ihn selbst (max. 3 je Stunde).
    F-78 (29.09.2026): echte v2-Werte statt der Altform."""
    import jack_freigaben
    name = "%s_NETZWAECHTER_%s_steht_trotz_Auftrag.md" % (jetzt().strftime("%Y-%m-%d"), re.sub(r"\W", "_", l["name"]))
    if (JACK / "auftraege" / "freigabe" / name).exists():
        return name
    herz = befund.get("herz") or {}
    titel = _tab_titel(herz.get("tty") or "") or "(Titel nicht lesbar)"
    satz = NEU_LESEN_SATZ % l["kanal"]
    v2 = {
        "projekt": "Netzwächter", "marke": "JACK", "eingegangen": jetzt().strftime("%Y-%m-%d %H:%M"),
        "von": "JACK-Netzwächter (F-45)", "an": "Patron", "art": "netzwaechter",
        "betreff": "Terminal „%s“ (Kanal %s) steht trotz Auftrag" % (titel, l["kanal"]),
        "kern": "Das Terminal „%s“ (Kanal %s) meldet „wartet“, aber im Kanal liegt seit über %d "
                "Minuten ein Auftrag." % (titel, l["kanal"], STEHT_TROTZ_AUFTRAG_S // 60),
        "frage": "Soll es angestoßen werden?",
        "empfehlung": "Ja. Der Wächter tippt selbst in genau diesen Tab (%s): `%s` (höchstens 3 mal "
                      "je Stunde). Klappt das nicht, den Satz von Hand in den Tab „%s“ tippen." % (herz.get("tty"), satz, titel),
        "frist": "keine", "dringlichkeit": "mittel",
        "ablauf": "Der Wächter tippt selbst zu (max. 3x/Stunde), Eintrag in betrieb/neustarts.log.",
    }
    pfad = _syskarte(kopf=v2, rumpf="\n".join([
        "## Auftrag",
        "Das Terminal „%s“ (Kanal %s) meldet „wartet“, aber im Kanal liegt seit über %d Minuten ein Auftrag. Soll es angestoßen werden?"
        % (titel, l["kanal"], STEHT_TROTZ_AUFTRAG_S // 60),
        "", "**Empfehlung von JACK:** Ja. Der Wächter tippt selbst in genau diesen Tab (%s): `%s` (höchstens 3 mal je Stunde, Eintrag in `betrieb/neustarts.log`). "
        "Klappt das nicht, tippe den Satz von Hand in den Tab „%s“." % (herz.get("tty"), satz, titel),
        "", "**Wo:** Programm „Terminal“ → Tab mit dem Titel oben. Befund: %s." % befund.get("grund"), ""
    ]), herkunft="bin/jack_netzwaechter.karte_steht_trotz_auftrag", dateiname=name)
    return pfad.name if pfad else ""


NEUSTART_NOETIG_PRAEFIX = "NETZWAECHTER_%s_neustart_noetig"


def karte_neustart_noetig(l, grund):
    """F-68 (27.09.2026): NUR wenn der Waechter selbst nicht mehr weiterkommt (Neustart durch die Ruhe-Regel verschoben
    oder durch den 1x/Stunde-Deckel gesperrt) - mit einer ECHTEN Alternative: FREIGEBEN startet die Sitzung sofort neu,
    das Ja des Patrons ersetzt fuer diesen einen Klick die Ruhe-Regel. Keine Karte fuer das, was der Waechter selbst tut
    (Anstoss-Tippen, automatischer Neustart) - Patron-Befund 27.09. 08:40 ('Was ist der Sinn?')."""
    import jack_freigaben
    name = "%s_%s.md" % (jetzt().strftime("%Y-%m-%d"), re.sub(r"\W", "_", NEUSTART_NOETIG_PRAEFIX % l["name"]))
    if (JACK / "auftraege" / "freigabe" / name).exists():
        return name
    # F-78 (29.09.2026): echte v2-Werte statt der Altform.
    v2 = {
        "projekt": "Netzwächter", "marke": "JACK", "eingegangen": jetzt().strftime("%Y-%m-%d %H:%M"),
        "von": "JACK-Netzwächter (F-68)", "an": "Patron", "art": "entscheidung",
        "betreff": "Sitzung „%s“ neu starten?" % l["kanal"],
        "kern": "Sitzung „%s“ neu starten? Der Wächter kommt selbst nicht weiter: %s" % (l["kanal"], grund),
        "frage": "Sitzung „%s“ jetzt neu starten?" % l["kanal"],
        "empfehlung": "FREIGEBEN startet die Sitzung sofort neu (`neustart_sicher.sh %s … --terminal`) - "
                      "dein Ja ersetzt für diesen einen Klick die Ruhe-Regel." % l["kanal"],
        "frist": "keine", "dringlichkeit": "mittel",
        "ablauf": "WARTEN/ABLEHNEN: nichts geschieht, der Wächter prüft weiter und schließt diese "
                  "Karte von selbst, sobald die Sitzung wieder in Ordnung ist.",
        "vorgang": "netzwaechter_neustart", "kanal": l.get("kanal", ""), "laeufer": l["name"],
    }
    pfad = _syskarte(sofort=True, kopf=v2, rumpf="\n".join([
        "## Auftrag",
        "Sitzung „%s“ neu starten? Der Wächter kommt selbst nicht weiter: %s" % (l["kanal"], grund),
        "", "**Empfehlung von JACK:** FREIGEBEN startet die Sitzung sofort neu (`neustart_sicher.sh %s … --terminal`) — "
        "dein Ja ersetzt für diesen einen Klick die Ruhe-Regel. WARTEN/ABLEHNEN: nichts geschieht, der Wächter prüft weiter "
        "und schließt diese Karte von selbst, sobald die Sitzung wieder in Ordnung ist." % l["kanal"],
        "", "## Prüfpunkte", "Läuft die Sitzung bis dahin von selbst wieder an, schließt sich diese Karte automatisch.", ""
    ]), herkunft="bin/jack_netzwaechter.karte_neustart_noetig", dateiname=name)
    return pfad.name if pfad else ""


def _karten_nach_muster_schliessen(muster_suffix):
    """Gemeinsamer Kern fuer alle automatischen Karten-Schliesser: verschiebt jede Karte, deren Dateiname auf
    muster_suffix endet, nach freigabe/ersetzt/ mit status: erledigt (dieselbe Ablage wie F-64: 'kein Loeschen',
    der Patron sieht es nie als offene Karte)."""
    treffer = list((JACK / "auftraege" / "freigabe").glob("*_%s.md" % muster_suffix))
    if not treffer:
        return None
    ziel_ordner = JACK / "auftraege" / "freigabe" / "ersetzt"
    ziel_ordner.mkdir(parents=True, exist_ok=True)
    import shutil
    zeit = jetzt().strftime("%Y-%m-%d %H:%M")
    for karte in treffer:
        text = karte.read_text(encoding="utf-8")
        text = re.sub(r"^status:\s*\S+", "status:     erledigt", text, count=1, flags=re.M)
        text += "\nerledigt_am: %s\n" % zeit
        karte.write_text(text, encoding="utf-8")
        shutil.move(str(karte), str(ziel_ordner / karte.name))
    return zeit


def karte_neustart_noetig_schliessen(l):
    """F-68 Punkt 5: die Karte aus karte_neustart_noetig() automatisch schliessen, sobald der Laeufer wieder ok ist."""
    return _karten_nach_muster_schliessen(re.sub(r"\W", "_", NEUSTART_NOETIG_PRAEFIX % l["name"]))


def karte_steht_trotz_auftrag_schliessen(l):
    """F-72: dieselbe automatische Schliessung fuer die AELTERE Kartenart aus karte_steht_trotz_auftrag() (F-45).
    Befund F-72: diese Funktion wird seit einem frueheren Umbau nicht mehr aufgerufen, um NEUE Karten zu schreiben
    (der Waechter tippt seither direkt in den Tab statt eine Karte anzulegen, siehe wiederanlauf()) - aber eine
    bereits geschriebene Karte dieser Art wurde bisher nie automatisch geschlossen, auch nicht von einer stehen
    gebliebenen, aelteren Laufzeit dieses Skripts. Schliesst jede Karte dieses Musters, sobald der Laeufer wieder
    'ok' ist - unabhaengig davon, welche Codeversion sie geschrieben hat."""
    return _karten_nach_muster_schliessen("NETZWAECHTER_%s_steht_trotz_Auftrag" % re.sub(r"\W", "_", l["name"]))


def karte_deckel(l, befund, liste):
    # F-78 (29.09.2026): echte v2-Werte statt der Altform.
    import jack_freigaben
    name = "%s_NETZWAECHTER_%s.md" % (jetzt().strftime("%Y-%m-%d"), re.sub(r"\W", "_", l["name"]))
    if (JACK / "auftraege" / "freigabe" / name).exists():
        return
    v2 = {
        "projekt": "Netzwächter", "marke": "JACK", "eingegangen": jetzt().strftime("%Y-%m-%d %H:%M"),
        "von": "JACK-Netzwächter (F-28)", "an": "Patron", "art": "netzwaechter",
        "betreff": "Dauerläufer %s: Neustart-Deckel erreicht" % l["name"],
        "kern": "Der Dauerläufer %s stand in der letzten Stunde %d-mal und wurde %d-mal neu "
                "gestartet." % (l["name"], len(liste) + 1, len(liste)),
        "frage": "Ursache klären?",
        "empfehlung": "Der Wächter startet ihn jetzt nicht mehr von selbst (Deckel 3 je Stunde). "
                      "Bitte Ursache prüfen: %s." % befund.get("grund"),
        "frist": "keine", "dringlichkeit": "mittel",
        "ablauf": "Diese Karte startet nichts. Nach Klärung zählt der Deckel ab der nächsten vollen Stunde neu.",
    }
    _syskarte(kopf=v2, rumpf="\n".join([
        "## Auftrag",
        "Der Dauerläufer **%s** stand in der letzten Stunde %d-mal und wurde %d-mal neu gestartet. Der Wächter startet ihn "
        "jetzt nicht mehr von selbst (Deckel 3 je Stunde). Bitte Ursache prüfen." % (l["name"], len(liste) + 1, len(liste)),
        "", "Letzter Befund: %s" % befund.get("grund"), "Protokoll: `00_Marken/JACK/betrieb/neustarts.log`, `betrieb/netz.log`.",
        "", "## Prüfpunkte", "Diese Karte startet nichts. Nach Klärung zählt der Deckel ab der nächsten vollen Stunde neu.", ""
    ]), herkunft="bin/jack_netzwaechter.karte_deckel", dateiname=name)


# ------------------------------------------------------------------ Takt
def takt(trocken=False, jetzt_s=None):
    jetzt_s = jetzt_s or time.time()
    konf = _lesen(KONFIG, {})
    stand = _lesen(STAND, {})
    online, ziele = netz_pruefen(konf.get("ziele") or STANDARD_ZIELE)
    alt = _lesen(ZUSTAND, {})
    zeit = jetzt().isoformat()
    zustand = {"schema": 1, "zeit": zeit, "online": online, "ziele": ziele,
               "seit": alt.get("seit") if alt.get("online") == online and alt.get("seit") else zeit,
               "letzter_ausfall": alt.get("letzter_ausfall"), "laeufer": {}}
    if alt and alt.get("online") != online:
        if online:
            von = _zeit(alt.get("seit"))
            dauer = round((jetzt() - von).total_seconds()) if von else None
            zustand["letzter_ausfall"] = {"von": alt.get("seit"), "bis": zeit, "dauer_s": dauer}
            _anhaengen(LOG, "%s\tNETZ WIEDER DA\tAusfall %s s (seit %s)" % (zeit[:19], dauer, str(alt.get("seit"))[:19]))
        else:
            _anhaengen(LOG, "%s\tNETZ WEG\t%s" % (zeit[:19], "; ".join("%s:%s" % (z["ziel"], z.get("schritt")) for z in ziele)))
    for l in konf.get("laeufer") or []:
        if not l.get("aktiv", True):
            continue
        # F-75: "pausiert" (mit Grund) - weder anstossen noch Karten anlegen noch neu starten, Herzschlag-Alter
        # wird nicht einmal geprueft (anders als "aktiv: false" bleibt der Laeufer sichtbar, mit erklaertem Grund).
        # F-86: der Pause-Schalter der System-Tabelle (betrieb/kanal_pause/<kanal>) wirkt wie "pausiert".
        _pm = (JACK / "betrieb" / "kanal_pause" / str(l.get("kanal") or "-")) if l.get("kanal") else None
        if l.get("pausiert") or (_pm is not None and _pm.is_file()):
            zustand["laeufer"][l["name"]] = {"status": "pausiert", "grund": l.get("grund") or "vom Patron pausiert (System)"}
            continue
        befund = laeufer_pruefen(l, stand, jetzt_s)
        # Toleranz fuer Dienste: 'steht' muss laenger als toleranz_s andauern (Beginn im Stand)
        seit = stand.setdefault("steht_seit", {})
        # F-68 Punkt 5: sobald dieser Laeufer wieder ok ist, eine offene "neustart_noetig"-Karte automatisch schliessen -
        # unabhaengig davon, wodurch er wieder ok wurde (Wächter selbst, Terminal-Tippen, Patron von Hand).
        if befund["status"] == "ok" and not trocken:
            karte_neustart_noetig_schliessen(l)
            karte_steht_trotz_auftrag_schliessen(l)  # F-72: schliesst auch Karten der aelteren F-45-Art automatisch
        if befund["status"] in ("steht", "haengt", "beendet", "steht_trotz_auftrag", "herz_alt", "stumm", "weckreiz"):
            seit.setdefault(l["name"], jetzt_s)
            dauer = jetzt_s - seit[l["name"]]
            if l["art"] in ("http", "prozess") and dauer < l.get("toleranz_s", 180):
                befund["massnahme"] = "beobachten (%d von %d s)" % (dauer, l.get("toleranz_s", 180))
            elif l.get("neustart", True):
                befund.update(wiederanlauf(l, befund, stand, trocken, jetzt_s))
            else:
                befund["massnahme"] = "nur melden"
        else:
            seit.pop(l["name"], None)
        if befund["status"] == "steht_ohne_herzschlag" and not trocken:
            befund["massnahme"] = "nur melden: Karte %s" % karte_ohne_herzschlag(l, befund)
        elif befund["status"] == "steht_ohne_herzschlag":
            befund["massnahme"] = "TROCKEN: Karte wuerde angelegt"
        zustand["laeufer"][l["name"]] = {k: v for k, v in befund.items() if k != "herz"}
    zustand["neustarts_letzte_stunde"] = {k: len([t for t in v if jetzt_s - t < 3600]) for k, v in (stand.get("neustarts") or {}).items()}
    _schreiben(ZUSTAND, zustand)
    _schreiben(STAND, stand)
    return zustand


def _zeit(s):
    try:
        return dt.datetime.fromisoformat(str(s))
    except ValueError:
        return None


def main():
    args = sys.argv[1:]
    trocken = "--trocken" in args
    if "--einmal" in args:
        print(json.dumps(takt(trocken), ensure_ascii=False, indent=1))
        return 0
    while True:
        try:
            takt(trocken)
        except Exception as fehler:            # der Waechter selbst darf nie aussteigen
            _anhaengen(LOG, "%s\tWAECHTER-FEHLER\t%s: %s" % (jetzt().isoformat()[:19], type(fehler).__name__, str(fehler)[:200]))
        time.sleep(int(_lesen(KONFIG, {}).get("takt_s") or 60))


if __name__ == "__main__":
    sys.exit(main())
