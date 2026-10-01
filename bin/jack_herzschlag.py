#!/usr/bin/env python3
"""F-45 (25.09.2026): Herzschlag der Postfach-Terminals - jetzt gekoppelt an die echte Kanalpruefung.

Aufruf in der Warte-Schleife (README_PM_POSTFACH.md), alle 120 s:
    python3 "$J/bin/jack_herzschlag.py" <kanal> [--zustand wartet|arbeitet] [--auftrag "Text"]
Schreibt betrieb/herzschlag/<kanal>.json mit den bisherigen Feldern (kanal, epoch, zeit, claude_pid, tty, zustand, auftrag)
und zusaetzlich
    aelteste_datei_kanal   Alter in s der aeltesten Auftragsdatei im eigenen Kanal (null = Kanal leer)
    letzte_aufnahme        ISO-Zeit, zu der die Schleife zuletzt einen Auftrag geholt hat (Datei verschwand aus dem Kanal)
Der Netz-Waechter prueft die Kanalordner selbst (aelteste_datei_alter) - der Herzschlag allein reicht ihm nicht.
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

JACK = Path(os.environ.get("JACK_NETZ_WURZEL") or Path(__file__).resolve().parents[1])


# F-114 (PM 30.09. 23:57): Dauerbetrieb-, Weiter-, Foto-Weg-, Nacht- und PM-Mitteilungsdateien sind KEIN offener Auftrag (sonst tippt der Waechter
# "weiter" in Kanaele, die nichts zu tun haben). Dieselbe Regel steht in bin/postfach_schleife.sh (Funktion neu).
KEIN_AUFTRAG = re.compile(r"^(DAUERBETRIEB_|ZYKLUS_WEITER_|FOTO_WEG_|NACHT_|Z-\d+_)|_PM_|_PM\.md$")


def _md_dateien(jack, kanal):
    """Auftragsdateien im Kanal: nur *.md, ohne README und Punktdateien; eine Datei mit unbeantworteter Rueckfrage
    (abnahme/pm_eingang/<Kennung>_FRAGE.md) gilt als bewusst liegen gelassen und zaehlt nicht."""
    ordner = Path(jack) / "auftraege" / "pm_ausgang" / kanal
    eingang = Path(jack) / "abnahme" / "pm_eingang"
    raus = []
    try:
        for p in sorted(ordner.iterdir()):
            if not p.is_file() or p.is_symlink() or p.name.startswith(".") or not p.name.endswith(".md") or p.name.lower() == "readme.md" or KEIN_AUFTRAG.search(p.name):
                continue
            m = re.match(r"^([A-Za-z]+-[\d.]+[a-z]?)", p.name)
            if m and (eingang / (m.group(1) + "_FRAGE.md")).is_file():
                continue
            raus.append(p)
    except OSError:
        pass
    return raus


WECK = re.compile(r"_PM_|_PM\.md$|^ZYKLUS_WEITER_|^Z-\d+_")          # F-117: auch "Z-0323_zyklus_weiter.md"
WECK_ALTER_S = 900           # F-115: eine PM-Mitteilung, die so lange unbearbeitet im Kanal liegt, bekommt einmal einen Weck-Satz


def pm_weckdateien(jack, kanal, jetzt_s=None, mindestalter=WECK_ALTER_S):
    """F-115: Mitteilungen des PM im Kanalordner (`*_PM_*.md`, `ZYKLUS_WEITER_*`), aelter als `mindestalter`, noch nicht nach erledigt/ gewandert.
    Zaehlen NICHT als Auftrag (F-114), sind aber der Weckreiz fuer eine Sitzung, die im Gespraech steht und die Schleife nicht laufen hat.
    -> [(name, alter_s)], aelteste zuerst."""
    jetzt_s = jetzt_s or time.time()
    raus = []
    try:
        for p in Path(jack, "auftraege", "pm_ausgang", kanal).iterdir():
            if not p.is_file() or p.name.startswith(".") or not p.name.endswith(".md") or p.name.startswith(("DAUERBETRIEB_", "NACHT_")) or not WECK.search(p.name):
                continue
            alter = jetzt_s - p.stat().st_mtime
            if alter >= mindestalter:
                raus.append((p.name, round(alter)))
    except OSError:
        pass
    return sorted(raus, key=lambda x: -x[1])


def aelteste_datei_alter(jack, kanal, jetzt_s=None):
    """Alter in Sekunden der aeltesten Auftragsdatei im Kanal, None wenn der Kanal leer ist."""
    jetzt_s = jetzt_s or time.time()
    try:
        alter = [jetzt_s - p.stat().st_mtime for p in _md_dateien(jack, kanal)]
    except OSError:
        return None
    return round(max(alter)) if alter else None


def _ist_claude(pid):
    try:
        aus = subprocess.run(["/bin/ps", "-o", "comm=", "-p", str(pid)], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return False
    return "claude" in aus.lower()


def _tty_von(pid):
    try:
        t = subprocess.run(["/bin/ps", "-o", "tty=", "-p", str(pid)], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""
    return "" if t in ("?", "??") else t


def _claude_prozess():
    """F-58: 1. Umgebungsvariable CLAUDE_PID (Claude Code setzt sie fuer jeden Kindprozess; ueberlebt nohup/Hintergrundschleifen, die
    ihren Elternprozess verlieren - genau daran scheiterte die Suche ueber die Elternkette bei kern: pid null seit 13:51),
    2. Elternkette, 3. (None, "") - der Aufrufer schreibt dann "unbekannt"."""
    env = os.environ.get("CLAUDE_PID", "").strip()
    if env.isdigit() and _ist_claude(env):
        return int(env), _tty_von(env)
    p = os.getppid()
    for _ in range(12):
        if p <= 1:
            break
        try:
            aus = subprocess.run(["/bin/ps", "-o", "comm=,ppid=", "-p", str(p)], capture_output=True, text=True, timeout=5).stdout.split()
        except (OSError, subprocess.SubprocessError):
            break
        if aus and "claude" in aus[0]:
            tty = subprocess.run(["/bin/ps", "-o", "tty=", "-p", str(p)], capture_output=True, text=True, timeout=5).stdout.strip()
            return p, tty
        p = int(aus[-1]) if aus and aus[-1].isdigit() else 0
    return None, ""


ARBEIT_FENSTER_S = 600      # F-61: "arbeitet" gilt nur, wenn in den letzten 10 Min eine Datei geschrieben wurde


def dateiaktivitaet_s(jack, kanal, jetzt_s=None, grenze=6000):
    """F-61: Sekunden seit der letzten Dateiaenderung im Kanal, in abnahme/ (bis Tiefe 2, also pm_eingang und die Pruefordner) und im Repo
    (*.py/*.md/*.html im JACK-Ordner und bin/). betrieb/ zaehlt nicht: dort schreiben Dienste laufend Protokolle, das waere nie still.
    None = nichts gefunden."""
    jetzt_s = jetzt_s or time.time()
    jack = Path(jack)
    neueste, n = 0.0, 0

    def pruefen(p):
        nonlocal neueste
        try:
            neueste = max(neueste, p.stat().st_mtime)
        except OSError:
            pass
    ordner = [jack / "auftraege" / "pm_ausgang" / kanal, jack, jack / "bin", jack / "abnahme"]
    for basis in ordner:
        try:
            for p in basis.iterdir():
                n += 1
                if n > grenze:
                    break
                if p.is_file() and not p.name.startswith(".") and (basis == ordner[0] or p.suffix in (".py", ".md", ".html", ".sh")):
                    pruefen(p)
                elif p.is_dir() and basis == ordner[3]:
                    pruefen(p)
                    for q in p.iterdir():
                        n += 1
                        if q.is_file() and not q.name.startswith("."):
                            pruefen(q)
        except OSError:
            continue
    return round(jetzt_s - neueste) if neueste else None


STUMM_S = 2700               # F-112: "arbeitet" ohne eigene Datei laenger als 45 Min = "haengt" (Vermerk), danach "weiter", ab 60 Min Neustart (Waechter)
PM_PRAEFIX = {"kern": "F-", "sprache": "S-", "patronos": "P-", "cashflow": ("VA-", "M-", "CF-"), "gruendung": "G-", "bewerbungen": "B-", "inhalt": "I-", "social": "SM-"}


def eigene_aktivitaet_s(jack, kanal, jetzt_s=None, auftrag=None):
    """F-112: Sekunden seit der letzten Datei, die DIESER Kanal selbst geschrieben hat: Dateien in abnahme/pm_eingang (der Kanalordner selbst zaehlt nicht: dort schreibt der PM)
    und abnahme/<Ordner> (Tiefe 2), deren Name mit der Auftragskennung (z. B. M-16), dem Kanalpraefix (z. B. VA-) beginnt oder mit NACHT_<KANAL>/<KANAL>_ anfaengt
    (Dateien ANDERER ueber diesen Kanal, z. B. *_AN_CASHFLOW_* oder *_UNVOLLSTAENDIG, zaehlen nicht). Das Repo und fremde Kanaele zaehlen NICHT (Befund 30.09.2026: cashflow stand 3,5 Std still und galt als
    'arbeitet', weil der allgemeine Dateimesser die Schreibvorgaenge anderer Kanaele sah). None = nichts gefunden."""
    jetzt_s = jetzt_s or time.time()
    jack = Path(jack)
    kl = str(kanal).lower()
    pf = PM_PRAEFIX.get(kl, ())
    kennungen = list(pf) if isinstance(pf, tuple) else [pf]
    m = re.search(r"\b([A-Z]{1,3}-\d+[a-z]?)", str(auftrag or ""))
    if m:
        kennungen.append(m.group(1))
    kennungen = [k for k in kennungen if k]

    eigene = tuple(kennungen) + ("NACHT_" + kl.upper(), kl.upper() + "_")
    # Zyklus-/Pruefberichte tragen den Kanalnamen klein und mit Bindestrich oder Praefix (patronos-ZYKLUS_23, GEGENPRUEFUNG_patronos_...) - Gegenpruefung patronos 30.09.
    eigene_klein = (kl + "-", kl + "_", "nacht_" + kl, "gegenpruefung_" + kl, "korrektur_" + kl, "morgen_patron_" + kl)

    def meins(name):
        return name.startswith(eigene) or name.lower().startswith(eigene_klein)
    neueste = 0.0

    def pruefen(p):
        nonlocal neueste
        try:
            neueste = max(neueste, p.stat().st_mtime)
        except OSError:
            pass
    for basis in (jack / "abnahme" / "pm_eingang", jack / "abnahme"):
        try:
            for p in basis.iterdir():
                if p.name.startswith(".") or not meins(p.name):
                    continue
                pruefen(p)
                if p.is_dir() and basis.name == "abnahme":
                    for q in p.iterdir():
                        if q.is_file() and not q.name.startswith("."):
                            pruefen(q)
        except OSError:
            continue
    # Gnadenfrist: eine frisch gestartete Sitzung (Startsperre betrieb/laeuft/<kanal>.pid, Feld "seit") gilt ab ihrem Start als aktiv
    try:
        seit = float(json.loads((jack / "betrieb" / "laeuft" / (kanal + ".pid")).read_text(encoding="utf-8")).get("seit") or 0)
        neueste = max(neueste, seit)
    except (OSError, ValueError, TypeError):
        pass
    return round(jetzt_s - neueste) if neueste else None


def schreiben(kanal, zustand="wartet", auftrag=None, jack=None, pid=None, tty=None, jetzt_s=None, aufnahme=None, quelle=None, laeufer_pid=None):
    jack = Path(jack or JACK)
    jetzt_s = jetzt_s or time.time()
    if pid is None:
        pid, tty = _claude_prozess()
        if pid is None:
            pid = "unbekannt"            # F-58: der Waechter behandelt "unbekannt" als lebend, solange Herzschlag und Bewegung frisch sind
    ziel = jack / "betrieb" / "herzschlag"
    ziel.mkdir(parents=True, exist_ok=True)
    datei = ziel / (kanal + ".json")
    stand = ziel / (kanal + ".stand.json")
    try:
        alt = json.loads(stand.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        alt = {}
    jetzt_liste = sorted(p.name for p in _md_dateien(jack, kanal))
    letzte = alt.get("letzte_aufnahme")
    if aufnahme or any(n not in jetzt_liste for n in alt.get("dateien", [])):          # Datei aus dem Kanal verschwunden (oder ausdruecklich gemeldet) = Auftrag geholt
        letzte = dt.datetime.fromtimestamp(jetzt_s).astimezone().isoformat(timespec="seconds")
    stand.write_text(json.dumps({"dateien": jetzt_liste, "letzte_aufnahme": letzte}, ensure_ascii=False), encoding="utf-8")
    aktiv = dateiaktivitaet_s(jack, kanal, jetzt_s)
    eigen = None
    if quelle == "takt" and zustand == "arbeitet":
        # F-112: der Takt des Wrappers prueft nur die EIGENEN Dateien des Kanals: bis 45 Min "arbeitet", danach "haengt" (Vermerk fuer den Waechter)
        eigen = eigene_aktivitaet_s(jack, kanal, jetzt_s, auftrag or alt.get("auftrag"))
        if eigen is None or eigen > STUMM_S:
            zustand = "haengt"
    elif zustand == "arbeitet" and (aktiv is None or aktiv > ARBEIT_FENSTER_S):
        zustand = "wartet"                       # F-61: "arbeitet" nur bei Dateibewegung in den letzten 10 Min - sonst ist es Warten (der Waechter darf dann handeln)
    wert = {"kanal": kanal, "epoch": int(jetzt_s), "zeit": dt.datetime.fromtimestamp(jetzt_s).astimezone().strftime("%Y-%m-%dT%H:%M:%S%z"),
            "claude_pid": pid, "tty": tty or "", "zustand": zustand, "aelteste_datei_kanal": aelteste_datei_alter(jack, kanal, jetzt_s),
            "letzte_aufnahme": letzte, "letzte_dateiaktivitaet_s": aktiv}
    if eigen is not None or zustand == "haengt":
        wert["eigene_aktivitaet_s"] = eigen
    if auftrag:
        wert["auftrag"] = str(auftrag)[:160]
    if quelle:                               # F-105: "takt" = Hintergrund-Takt des Startwrappers (bin/kanal_start.py), sonst die Warte-Schleife
        wert["quelle"] = quelle
    if laeufer_pid:
        wert["laeufer_pid"] = laeufer_pid
    tmp = datei.with_name(datei.name + ".tmp")
    tmp.write_text(json.dumps(wert, ensure_ascii=False), encoding="utf-8")
    os.replace(str(tmp), str(datei))
    return wert


TAKT_SCHLEIFE_FRISCH_S = 150     # F-105: schrieb die Warte-Schleife in den letzten 150 s, muss der Takt nichts tun (sie schreibt alle 120 s)


def takt(kanal, claude_pid, tty="", laeufer_pid=None, jack=None, jetzt_s=None):
    """F-105 (Punkt 3): Hintergrund-Takt des Startwrappers, alle <= 60 s, WAEHREND der Arbeit. Schreibt "arbeitet" (mit der PID des echten claude
    und des Wrappers), aber nur, wenn nicht gerade die Warte-Schleife (ohne Feld quelle) frisch geschrieben hat - deren Zustand "wartet" bleibt.
    "arbeitet" gilt weiter nur mit Dateibewegung der letzten 10 Min (F-61, in schreiben()). Rueckgabe: geschriebener Wert oder None."""
    jack = Path(jack or JACK)
    jetzt_s = jetzt_s or time.time()
    try:
        alt = json.loads((jack / "betrieb" / "herzschlag" / (kanal + ".json")).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        alt = {}
    alter = jetzt_s - float(alt.get("epoch") or 0)
    if alt.get("claude_pid") == claude_pid and not alt.get("quelle") and alter < TAKT_SCHLEIFE_FRISCH_S:
        return None
    return schreiben(kanal, "arbeitet", alt.get("auftrag"), jack=jack, pid=claude_pid, tty=tty, jetzt_s=jetzt_s,
                     quelle="takt", laeufer_pid=laeufer_pid)


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        sys.exit("Aufruf: jack_herzschlag.py <kanal> [--zustand wartet|arbeitet] [--auftrag Text]")
    z = a[a.index("--zustand") + 1] if "--zustand" in a else "wartet"
    t = a[a.index("--auftrag") + 1] if "--auftrag" in a else None
    aufn = a[a.index("--aufnahme") + 1] if "--aufnahme" in a else None
    print(json.dumps(schreiben(a[0], z, t, aufnahme=aufn), ensure_ascii=False))
