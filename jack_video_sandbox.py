"""Probelauf der Videoproduktion (Verfahren 7.1) in einer abgeschotteten Sandbox.

Einzige Aufrufform, die der Pfadwaechter in arbeiter.sh zulaesst:
  /usr/bin/python3 -I '<JACK>/jack_video_sandbox.py' probelauf 'VP-JJJJMMTT-hhmmss-xxxxxxxx'

Zusagen dieses Skripts (Patron-Auftrag 23.09.2026, Weg A):
- Die Kennung wird streng geprueft, sonst Abbruch.
- Echte Dateien (videoproduktion.json, betriebsgrenzen.json, Auftragsakte, drei
  Mediendateien) werden nur gelesen und in einen neuen Temp-Ordner kopiert; nie
  zurueckgeschrieben.
- Der eigentliche Lauf laeuft unter macOS sandbox-exec: kein Netz, Schreiben nur
  im Temp-Ordner - vom Betriebssystem erzwungen, auch fuer Unterprozesse (ffprobe).
  Der innere Lauf bricht ab, wenn diese Sperre nicht nachweislich wirkt.
- Zusaetzlich im Prozess: socket/urllib gesperrt und gezaehlt, Schluesselbund
  wird nicht gelesen, echte Anbieterwege (starten, _api, _hochladen) gesperrt.
- Aufgerufen wird nur der Trockenlauf-Weg verfahren_7_1_video_zu_video ->
  wuerde_starten. Einen Weg zu einem echten Anbieteraufruf gibt es hier nicht.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

JACK = Path(__file__).resolve().parent
VAULT_ECHT = JACK.parent.parent
KENNUNG = re.compile(r"VP-[0-9]{8}-[0-9]{6}-[a-f0-9]{8}")
PRAEFIX = "jack_video_sandbox_"
SANDBOX_EXEC = "/usr/bin/sandbox-exec"
PYTHON = "/usr/bin/python3"
MAX_MEDIUM = 500_000_000
MAX_AKTE = 500_000


def _abbruch(text, code=2):
    print("ABBRUCH: " + text, file=sys.stderr)
    sys.exit(code)


def _kein_verweis(pfad, bis):
    for teil in [pfad, *pfad.parents]:
        if teil == bis:
            return
        if teil.is_symlink():
            _abbruch("Pfad enthaelt einen Verweis: " + str(teil))
    _abbruch("Pfad liegt ausserhalb der Holding: " + str(pfad))


TEMP_WURZEL = "/private/var/folders/"


def _temp_basis():
    basis = Path(os.path.realpath(tempfile.gettempdir()))
    if not str(basis).startswith(TEMP_WURZEL):
        _abbruch("Temp-Ordner liegt nicht unter " + TEMP_WURZEL)
    return basis


def _profil(tmp):
    return ("(version 1)(allow default)(deny network*)(deny file-write*)"
            '(allow file-write* (subpath "%s"))(allow file-write-data (literal "/dev/null"))' % tmp)


# ---------------------------------------------------------------- aussen ---
def _akte_finden(konfig, kennung):
    treffer = []
    for eintrag in (konfig.get("marken") or {}).values():
        ordner = eintrag.get("ordner") if isinstance(eintrag, dict) else None
        if not isinstance(ordner, str) or not ordner or Path(ordner).name != ordner or ordner in (".", ".."):
            continue
        pfad = VAULT_ECHT / "00_Marken" / ordner / "06_Medien" / "JACK_Videoproduktion" / kennung / "auftrag.json"
        if pfad.is_file():
            _kein_verweis(pfad, VAULT_ECHT)
            treffer.append((ordner, pfad))
    if len(treffer) != 1:
        _abbruch("Videoauftrag %s nicht eindeutig gefunden (%d Treffer)" % (kennung, len(treffer)))
    return treffer[0]


def _brieffeld(brief, name, pflicht=True):
    m = re.search(r"^" + re.escape(name) + r": (.+)$", brief, re.M)
    if not m:
        if pflicht:
            _abbruch("Feld '%s' fehlt im Brief der Auftragsakte" % name)
        return None
    return m.group(1).strip()


def _medium(ordner, relativ):
    p = Path(relativ)
    if p.is_absolute() or ".." in p.parts or p.parts[:3] != ("00_Marken", ordner, "06_Medien"):
        _abbruch("Mediendatei liegt nicht in 00_Marken/%s/06_Medien: %s" % (ordner, relativ))
    echt = VAULT_ECHT / p
    _kein_verweis(echt, VAULT_ECHT)
    if not echt.is_file() or echt.stat().st_size > MAX_MEDIUM:
        _abbruch("Mediendatei fehlt oder ist zu gross: " + relativ)
    return p


def _aufbauen(kennung, tmp):
    konfig = json.loads((JACK / "betrieb/videoproduktion.json").read_text(encoding="utf-8"))
    ordner, akte_echt = _akte_finden(konfig, kennung)
    if akte_echt.stat().st_size > MAX_AKTE:
        _abbruch("Auftragsakte ist zu gross")
    akte = json.loads(akte_echt.read_text(encoding="utf-8"))
    brief = str(akte.get("brief") or "")
    laenge = re.search(r"^Länge: (\d+) Sekunden", brief, re.M)
    figur = _brieffeld(brief, "Figurenblatt", pflicht=False)
    parameter = {
        "kennung": kennung,
        "clip": str(_medium(ordner, _brieffeld(brief, "Ausgangsclip"))),
        "figurenblatt": str(_medium(ordner, figur)) if figur else None,
        "ortsbild": str(_medium(ordner, _brieffeld(brief, "Ortsbild"))),
        "handlung": _brieffeld(brief, "Handlung"),
        "aussage": _brieffeld(brief, "Aussage"),
        "ortsbild_beschreibung": akte.get("ortsbild_beschreibung"),
        "dauer": int(laenge.group(1)) if laenge else 5,
        "dauer_quelle": "Brief 'Länge: N Sekunden'" if laenge else "Standardwert 5 (kein Längenfeld im Brief)",
        "akte_status": akte.get("status"),
    }
    if not isinstance(parameter["ortsbild_beschreibung"], str):
        _abbruch("ortsbild_beschreibung fehlt in der Auftragsakte")
    vault = tmp / "VAULT"
    betrieb = vault / "00_Marken/JACK/betrieb"
    betrieb.mkdir(parents=True)
    for name in ("videoproduktion.json", "betriebsgrenzen.json"):
        shutil.copyfile(JACK / "betrieb" / name, betrieb / name)
    ziel_akte = vault / akte_echt.relative_to(VAULT_ECHT)
    ziel_akte.parent.mkdir(parents=True)
    shutil.copyfile(akte_echt, ziel_akte)
    for rel in {parameter["clip"], parameter["ortsbild"], parameter["figurenblatt"]} - {None}:
        (vault / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(VAULT_ECHT / rel, vault / rel)
    (tmp / "tmp").mkdir()
    (tmp / "home").mkdir()
    (tmp / "parameter.json").write_text(json.dumps(parameter, ensure_ascii=False, indent=1), encoding="utf-8")


def probelauf(kennung):
    if not KENNUNG.fullmatch(kennung):
        _abbruch("Ungueltige Kennung - erwartet VP-JJJJMMTT-hhmmss-xxxxxxxx")
    tmp = Path(tempfile.mkdtemp(prefix=PRAEFIX, dir=_temp_basis())).resolve()
    if any(z in str(tmp) for z in '"\\'):
        _abbruch("Temp-Pfad enthaelt unzulaessige Zeichen")
    try:
        _aufbauen(kennung, tmp)
        print("Sandbox:", tmp)
        print("Betriebssystem-Sperre: sandbox-exec, kein Netz, Schreiben nur im Sandbox-Ordner")
        sys.stdout.flush()
        umgebung = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(tmp / "home"),
                    "TMPDIR": str(tmp / "tmp"), "LANG": "de_DE.UTF-8"}
        lauf = subprocess.run([SANDBOX_EXEC, "-p", _profil(tmp), PYTHON, "-I", str(Path(__file__).resolve()),
                               "_innen", kennung, str(tmp)], env=umgebung, timeout=600)
        return lauf.returncode
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ----------------------------------------------------------------- innen ---
def _os_sperre_nachweisen(tmp):
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2)
    try:
        s.connect(("127.0.0.1", 9))
        _abbruch("Netz ist NICHT gesperrt - Lauf verweigert", 4)
    except PermissionError:
        pass
    except OSError as fehler:
        _abbruch("Netz ist NICHT durch das Betriebssystem gesperrt (%s) - Lauf verweigert"
                 % type(fehler).__name__, 4)
    finally:
        s.close()
    probe = tmp.parent / (PRAEFIX + "schreibprobe_" + os.urandom(6).hex())
    try:
        probe.write_text("x")
    except PermissionError:
        return
    probe.unlink()
    _abbruch("Schreiben ausserhalb der Sandbox ist NICHT gesperrt - Lauf verweigert", 4)


def innen(kennung, tmp_text):
    tmp = Path(tmp_text)
    if (not KENNUNG.fullmatch(kennung) or str(tmp) != os.path.realpath(tmp)
            or not str(tmp).startswith(TEMP_WURZEL) or not tmp.name.startswith(PRAEFIX)
            or not (tmp / "parameter.json").is_file()):
        _abbruch("Ungueltiger innerer Aufruf")
    _os_sperre_nachweisen(tmp)

    import socket
    import urllib.request
    netzversuche = []

    def gesperrt(*args, **kwargs):
        netzversuche.append(repr(args)[:200])
        raise OSError("NETZ IM PROBELAUF GESPERRT")

    socket.socket.connect = gesperrt
    socket.socket.connect_ex = gesperrt
    socket.create_connection = gesperrt
    socket.getaddrinfo = gesperrt
    urllib.request.urlopen = gesperrt

    sys.path.insert(0, str(JACK))
    import jack_tresor
    jack_tresor.stand = lambda name: ("da", "SANDBOX:KEIN_ECHTER_SCHLUESSEL", "")
    import jack_higgsfield
    import jack_kosten
    import jack_videoproduktion

    anbieterversuche = []

    def anbieter_gesperrt(name):
        def sperre(*args, **kwargs):
            anbieterversuche.append(name)
            raise RuntimeError(name + " ist im Probelauf gesperrt")
        return sperre

    for name in ("starten", "_api", "_hochladen"):
        setattr(jack_higgsfield, name, anbieter_gesperrt("jack_higgsfield." + name))

    echt_wuerde_starten = jack_higgsfield.wuerde_starten
    uebergaben = []

    def wuerde_starten_mitschnitt(root, kennung_, prompt, modell="seedance_2_text", dauer=5, referenzbild=None):
        uebergaben.append({"prompt": prompt, "modell": modell, "dauer": dauer, "referenzbild": referenzbild})
        return echt_wuerde_starten(root, kennung_, prompt, modell=modell, dauer=dauer, referenzbild=referenzbild)

    jack_higgsfield.wuerde_starten = wuerde_starten_mitschnitt

    p = json.loads((tmp / "parameter.json").read_text(encoding="utf-8"))
    root = str(tmp / "VAULT/00_Marken/JACK")
    bericht = {"kennung": kennung, "akte_status_vorher": p["akte_status"], "dauer": p["dauer"],
               "dauer_quelle": p["dauer_quelle"]}
    try:
        bericht["ergebnis"] = jack_videoproduktion.verfahren_7_1_video_zu_video(
            root, kennung, [{"pfad": p["clip"]}], p["figurenblatt"], p["ortsbild"],
            p["handlung"], p["aussage"], p["ortsbild_beschreibung"], stufe="entwurf", dauer=p["dauer"])
    except Exception as fehler:
        bericht["ergebnis"] = {"fehlertyp": type(fehler).__name__, "meldung": str(fehler)}

    if uebergaben:
        u = uebergaben[-1]
        bericht["prompt_vom_echten_code"] = u["prompt"]
        bericht["prompt_zeichen"] = len(u["prompt"])
        bericht["modell"] = u["modell"]
    kosten = (bericht["ergebnis"] or {}).get("kosten_usd_geschaetzt_maximal")
    if kosten is not None:
        bericht["kosten_usd_obergrenze"] = kosten
        bericht["kosten_quelle"] = "wuerde_starten()"
    elif uebergaben:
        try:
            _, higgsfield = jack_higgsfield._konfiguration(root)
            bericht["kosten_usd_obergrenze"] = str(jack_higgsfield._kosten(
                jack_higgsfield._modell(higgsfield, uebergaben[-1]["modell"]), uebergaben[-1]["dauer"]))
            bericht["kosten_quelle"] = ("jack_higgsfield._kosten() - wuerde_starten() hat vor der eigenen "
                                        "Kostenrechnung gestoppt")
        except Exception as fehler:
            bericht["kosten_usd_obergrenze"] = None
            bericht["kosten_quelle"] = "nicht berechenbar: " + str(fehler)
    stand = jack_kosten.reservierungen_stand(root)
    bericht["reservierungen_offen"] = len(stand["offen"]) + len(stand["abgelaufen_ungeklaert"])
    bericht["reservierungszeilen"] = list(jack_kosten.reservierungszeilen(root))
    bericht["netzversuche"] = len(netzversuche)
    bericht["anbieterversuche"] = anbieterversuche
    print(json.dumps(bericht, ensure_ascii=False, indent=1, default=str))
    return 3 if netzversuche or anbieterversuche else 0


def main(argv):
    if len(argv) == 2 and argv[0] == "probelauf":
        return probelauf(argv[1])
    if len(argv) == 3 and argv[0] == "_innen":
        return innen(argv[1], argv[2])
    _abbruch("Aufruf: jack_video_sandbox.py probelauf 'VP-JJJJMMTT-hhmmss-xxxxxxxx'")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
