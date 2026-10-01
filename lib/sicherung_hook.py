#!/usr/bin/env python3
"""PreToolUse-Hook (Nachtrag N3, 18.09.2026): legt vor Edit/Write/MultiEdit
auf eine Bestandsdatei im JACK-Ordner automatisch eine Sicherungskopie
<datei>.vor_<block>_<datum> an — die Pflicht bleibt (Sicherung VOR der
ersten Aenderung), der Hook ist das Netz, falls sie vergessen wird.

F-11 (Paket 4, P05, 24.09.2026):
  - greift auch bei Bash-Schreibzugriffen (>, >>, >|, &>, tee, cp, mv, sed -i,
    dd of=, truncate, Python-Schreibpfade in `python -c`/Heredoc: open(...,'w'/'a'/'x'/'r+'),
    Path(...).write_text/write_bytes, shutil.copy*/move). Erkennung ist bestmoeglich:
    was ein aufgerufenes Skript INTERN schreibt, sieht kein Hook (Grenze, kein Versprechen).
  - Kopienflut-Schutz: hoechstens EINE Sicherung je Datei je Minute (zusaetzlich wie bisher
    einmal je Sitzung und Datei).
  - Pfade werden aufgeloest (07_Projekte/JACK ist ein Verweis auf 00_Marken/JACK).
  - Arbeiterlaeufe laden diesen Hook ueber arbeiter.sh (einstellungen_json). Dort schreibt er je
    Aufruf eine Zeile "geladen" (mit Laufkennung) - der Nachweis, dass er wirklich laeuft.
  - Testwurzel ueber JACK_SICHERUNG_WURZEL (nur Tests; nie im Betrieb gesetzt).

Blockiert NIE (immer exit 0, kein `permissionDecision`), loescht nie,
aendert nie Dateiinhalte — die einzige Wirkung ist `shutil.copy2` (Kopie)
und ein Protokolleintrag. Fehler werden protokolliert, nie geworfen.
"""
import json
import os
import re
import shlex
import shutil
import sys
import time
import traceback
from datetime import date, datetime
from pathlib import Path

JACK_ROOT = Path(os.environ.get('JACK_SICHERUNG_WURZEL') or
                 "/Users/gottwald/Library/Mobile Documents/com~apple~CloudDocs/GOTT WALD HOLDING/00_Marken/JACK")
ERLAUBTE_ENDUNGEN = {'.py', '.html', '.js', '.sh', '.json', '.md', '.swift', '.mjs'}
# Nur diese Bereiche werden gesichert (Positivliste). betrieb/ nur fuer *.json
# (die *.jsonl-Protokolle sind ohnehin Anhaenge-Dateien, keine Bestandsdateien
# im Sinne dieser Regel und durch die Endungsliste schon ausgeschlossen).
ERLAUBTE_BEREICHE = ('lib', 'agenten', 'faehigkeiten')
AUSGESCHLOSSENE_BEREICHE = ('auftraege', 'abnahme', 'entscheidungen', '99_Archiv')
STAND_DATEI = JACK_ROOT / '.claude' / 'hook_sicherungen_stand.json'
PROTOKOLL = JACK_ROOT / 'betrieb' / 'sicherungen_hook.jsonl'
BLOCK_DATEI = JACK_ROOT / '.claude' / 'aktueller_block'
# F-11: Kopienflut-Schutz - hoechstens eine Sicherung je Datei in diesem Abstand (Sekunden).
MINDESTABSTAND_S = 60


def _erlaubter_pfad(pfad: Path) -> bool:
    try:
        relativ = pfad.relative_to(JACK_ROOT.resolve())
    except ValueError:
        return False
    teile = relativ.parts
    if not teile:
        return False
    if teile[0] in AUSGESCHLOSSENE_BEREICHE:
        return False
    if pfad.suffix not in ERLAUBTE_ENDUNGEN:
        return False
    if len(teile) == 1:
        return True  # Wurzel der Holding-Marke JACK
    if teile[0] == 'betrieb':
        return pfad.suffix == '.json'  # betrieb/*.json ja, betrieb/entwuerfe/ und *.jsonl nein (Endung/Namensraum)
    return teile[0] in ERLAUBTE_BEREICHE


def _aktueller_block() -> str:
    try:
        text = BLOCK_DATEI.read_text(encoding='utf-8').strip()
        if text:
            return text
    except OSError:
        pass
    return None


def _stand_lesen():
    try:
        d = json.loads(STAND_DATEI.read_text(encoding='utf-8'))
        return d if isinstance(d, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _bereits_gesichert(session_id, datei_pfad) -> bool:
    return datei_pfad in _stand_lesen().get(session_id, [])


def _zu_frueh(datei_pfad, jetzt=None) -> bool:
    """F-11: Kopienflut-Schutz - letzte Sicherung dieser Datei (gleich welche Sitzung) juenger als 60 s?"""
    zuletzt = (_stand_lesen().get('_zuletzt') or {}).get(datei_pfad)
    try:
        return zuletzt is not None and (jetzt or time.time()) - float(zuletzt) < MINDESTABSTAND_S
    except (TypeError, ValueError):
        return False


def _als_gesichert_merken(session_id, datei_pfad, jetzt=None):
    d = _stand_lesen()
    d.setdefault(session_id, [])
    if datei_pfad not in d[session_id]:
        d[session_id].append(datei_pfad)
    d.setdefault('_zuletzt', {})[datei_pfad] = jetzt or time.time()
    STAND_DATEI.parent.mkdir(exist_ok=True, parents=True)
    tmp = STAND_DATEI.with_name(STAND_DATEI.name + '.neu')
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(tmp, STAND_DATEI)


def _protokollieren(satz):
    PROTOKOLL.parent.mkdir(exist_ok=True, parents=True)
    with PROTOKOLL.open('a', encoding='utf-8') as f:
        f.write(json.dumps(satz, ensure_ascii=False) + '\n')


# ---------------------------------------------------------------- Bash (F-11)
_TRENNER = {';', '&&', '||', '|', '&', '\n', '(', ')', ';;', '|&'}
_UMLEITUNG = {'>', '>>', '>|', '&>', '&>>'}
_PY_OPEN = re.compile(r"""open\(\s*(?:r|f|rb|fr)?(['"])([^'"]+)\1\s*,\s*(['"])(?:[^'"]*[wax+][^'"]*)\3""")
_PY_PATH_WRITE = re.compile(r"""Path\(\s*(['"])([^'"]+)\1\s*\)\s*\.\s*write_(?:text|bytes)\s*\(""")
_PY_SHUTIL = re.compile(r"""shutil\.(?:copy|copy2|copyfile|move)\(\s*(['"])([^'"]+)\1\s*,\s*(['"])([^'"]+)\3""")
_PYTHON = re.compile(r'(^|/)python(3(\.\d+)?)?$')


def _woerter(befehl):
    try:
        lexer = shlex.shlex(befehl, posix=True, punctuation_chars=';&|()<>')
        lexer.whitespace_split = True
        lexer.commenters = ''
        return list(lexer)
    except ValueError:
        # z. B. offenes Anfuehrungszeichen: grob an Leerraum trennen
        return befehl.split()


def _einfache_befehle(woerter):
    teil = []
    for w in woerter:
        if w in _TRENNER:
            if teil:
                yield teil
            teil = []
        else:
            teil.append(w)
    if teil:
        yield teil


def _ohne_optionen(argumente):
    return [a for a in argumente if not a.startswith('-')]


def bash_ziele(befehl, cwd=None):
    """Alle Dateien, die dieser Bash-Befehl (bestmoeglich erkannt) schreiben, ersetzen oder wegbewegen kann.

    Liefert absolute Path-Objekte (nicht aufgeloest); Ziele wie /dev/null oder &1 werden ausgelassen."""
    if not isinstance(befehl, str) or not befehl.strip():
        return []
    basis = Path(cwd) if cwd else Path.cwd()
    ziele = []

    def merken(text):
        if not text or text.startswith('&') or text in ('/dev/null', '/dev/stdout', '/dev/stderr', '-'):
            return
        p = Path(os.path.expanduser(text))
        ziele.append(p if p.is_absolute() else basis / p)

    woerter = _woerter(befehl)
    # Umleitungen stehen ueberall im Befehl (auch hinter Heredoc-Markern)
    for i, w in enumerate(woerter):
        if w in _UMLEITUNG and i + 1 < len(woerter) and woerter[i + 1] not in _TRENNER | _UMLEITUNG:
            merken(woerter[i + 1])
    python_gesehen = False
    for teil in _einfache_befehle(woerter):
        # Umleitungen und ihre Ziele fuer die Argumentanalyse entfernen
        rein, i = [], 0
        while i < len(teil):
            if teil[i] in _UMLEITUNG or teil[i] in ('<', '<<', '<<<', '<<-'):
                i += 2
                continue
            rein.append(teil[i])
            i += 1
        while rein and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*=.*', rein[0]):
            rein = rein[1:]  # VAR=wert vor dem Befehl
        while rein and rein[0] in ('sudo', 'command', 'exec', 'nohup', 'time', 'env'):
            rein = rein[1:]
        if not rein:
            continue
        name, argumente = Path(rein[0]).name, rein[1:]
        if name == 'tee':
            for a in _ohne_optionen(argumente):
                merken(a)
        elif name in ('cp', 'mv', 'install', 'rsync', 'ln'):
            pfade = _ohne_optionen(argumente)
            if len(pfade) >= 2:
                ziel = pfade[-1]
                zielpfad = Path(os.path.expanduser(ziel))
                zielpfad = zielpfad if zielpfad.is_absolute() else basis / zielpfad
                if zielpfad.is_dir():
                    for quelle in pfade[:-1]:
                        merken(str(zielpfad / Path(quelle).name))
                else:
                    merken(ziel)
                if name == 'mv':
                    for quelle in pfade[:-1]:
                        merken(quelle)  # die Quelle verschwindet an ihrem Ort
        elif name in ('sed', 'gsed', 'perl') and any(a == '-i' or a.startswith('-i') or a.startswith('--in-place')
                                                    for a in argumente):
            skript_als_option = any(a in ('-e', '-f', '--expression', '--file') for a in argumente)
            rest, ueberspringen = [], False
            for a in argumente:
                if ueberspringen:
                    ueberspringen = False
                    continue
                if a in ('-e', '-f', '--expression', '--file'):
                    ueberspringen = True
                    continue
                if a.startswith('-'):
                    continue
                rest.append(a)
            for a in (rest if skript_als_option else rest[1:]):
                merken(a)
        elif name == 'dd':
            for a in argumente:
                if a.startswith('of='):
                    merken(a[3:])
        elif name == 'truncate':
            for a in _ohne_optionen(argumente):
                if not re.fullmatch(r'[+\-<>/%]?\d+[KMGkmg]?', a):
                    merken(a)
        elif _PYTHON.search(name):
            python_gesehen = True
    if python_gesehen:
        for m in _PY_OPEN.finditer(befehl):
            merken(m.group(2))
        for m in _PY_PATH_WRITE.finditer(befehl):
            merken(m.group(2))
        for m in _PY_SHUTIL.finditer(befehl):
            merken(m.group(4))
            if 'move' in m.group(0):
                merken(m.group(2))
    # doppelte entfernen, Reihenfolge behalten
    raus, gesehen = [], set()
    for z in ziele:
        if str(z) not in gesehen:
            gesehen.add(str(z))
            raus.append(z)
    return raus


def _dateien_aus_tool_input(tool_name, tool_input, cwd=None):
    if tool_name in ('Write', 'Edit', 'MultiEdit'):
        fp = tool_input.get('file_path')
        return [fp] if fp else []
    if tool_name == 'Bash':
        return [str(p) for p in bash_ziele(tool_input.get('command'), cwd)]
    return []


def sichern(datei_str, session_id, werkzeug, jetzt=None):
    """Eine Datei sichern, wenn sie existiert, im erlaubten Bereich liegt und die Grenzen es zulassen.
    Rueckgabe: Pfad der Sicherung oder None."""
    pfad = Path(datei_str)
    if not pfad.is_absolute():
        return None
    try:
        pfad = pfad.resolve()
    except OSError:
        return None
    if not pfad.is_file():
        return None  # neue Datei (oder Verzeichnis) -> nichts zu sichern
    if not _erlaubter_pfad(pfad):
        return None
    datei_pfad_str = str(pfad)
    if _bereits_gesichert(session_id, datei_pfad_str):
        return None
    if _zu_frueh(datei_pfad_str, jetzt):
        _protokollieren({'zeit': datetime.now().isoformat(), 'session': session_id, 'datei': datei_pfad_str,
                         'werkzeug': werkzeug, 'status': 'uebersprungen_kopienflut',
                         'grund': 'letzte Sicherung juenger als %d s' % MINDESTABSTAND_S})
        return None
    block = _aktueller_block() or f"sitzung_{session_id[:8]}"
    datum = date.today().isoformat()
    ziel = Path(f"{datei_pfad_str}.vor_{block}_{datum}")
    zaehler = 1
    while ziel.exists():
        zaehler += 1
        ziel = Path(f"{datei_pfad_str}.vor_{block}_{datum}_{zaehler}")
    shutil.copy2(pfad, ziel)
    _als_gesichert_merken(session_id, datei_pfad_str, jetzt)
    _protokollieren({
        'zeit': datetime.now().isoformat(),
        'session': session_id, 'datei': datei_pfad_str, 'werkzeug': werkzeug,
        'sicherung': str(ziel), 'block': block, 'status': 'ok',
        'lauf_id': os.environ.get('JACK_AUFTRAG_RUN_ID') or None,
    })
    return str(ziel)


def main():
    try:
        rohdaten = sys.stdin.read()
        ereignis = json.loads(rohdaten) if rohdaten.strip() else {}
    except Exception:
        return 0  # kein lesbares Ereignis -> nichts tun, nie blockieren

    try:
        tool_name = ereignis.get('tool_name', '')
        tool_input = ereignis.get('tool_input', {}) or {}
        session_id = ereignis.get('session_id', 'unbekannte_sitzung')
        dateien = _dateien_aus_tool_input(tool_name, tool_input, ereignis.get('cwd'))
        gesichert = [s for s in (sichern(d, session_id, tool_name) for d in dateien) if s]
        # F-11: in einem Arbeiterlauf (arbeiter.sh setzt die Laufkennung) jede Ausfuehrung belegen
        lauf = os.environ.get('JACK_AUFTRAG_RUN_ID')
        if lauf:
            _protokollieren({'zeit': datetime.now().isoformat(), 'status': 'geladen', 'quelle': 'arbeiterlauf',
                             'lauf_id': lauf, 'auftrag': os.environ.get('JACK_AUFTRAG_DATEI', ''),
                             'session': session_id, 'werkzeug': tool_name,
                             'ziele': len(dateien), 'gesichert': len(gesichert)})
    except Exception as fehler:
        try:
            _protokollieren({
                'zeit': datetime.now().isoformat(),
                'session': ereignis.get('session_id', 'unbekannt') if isinstance(ereignis, dict) else 'unbekannt',
                'status': 'fehler', 'fehler': f"{fehler}: {traceback.format_exc()[-300:]}",
            })
        except Exception:
            pass
    return 0  # NIE blockieren, unabhaengig vom Ausgang


if __name__ == '__main__':
    sys.exit(main())
