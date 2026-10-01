#!/usr/bin/env python3
"""Ein gemeinsamer Startweg; Prozesssperren bleiben bis zum Ende erhalten.

Ohne Einzelauftrag entscheidet der Planer. Auch manuelle Einzelstarts halten
dieselben Bereichs- und Auftragssperren. Sperrdateien werden nie geloescht.
"""
import contextlib
import fcntl
import hashlib
import os
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def dateiname(name):
    if not isinstance(name, str) or not name.endswith('.md') or name.startswith('.') or '/' in name or '\\' in name or '\n' in name:
        raise ValueError('Ein einfacher Auftragsdateiname mit .md ist erforderlich')
    return name


def sperrpfad(root, name):
    folder = Path(root) / 'betrieb' / 'start_sperren'
    folder.mkdir(exist_ok=True)
    return folder / (hashlib.sha256(name.encode()).hexdigest() + '.lock')


@contextlib.contextmanager
def halten(root, name, bereiche):
    """Ein Auftrag und alle seine Bereiche atomar belegen oder sofort abweisen."""
    import jack_sperren
    dateiname(name)
    bereiche = sorted(set(bereiche)) or ['alles']
    if not all(jack_sperren.gueltig(b) for b in bereiche):
        raise ValueError('Ungueltiger Auftragsbereich')
    handles = []
    try:
        keys = [('auftrag:' + name, fcntl.LOCK_EX),
                ('bereiche:alle', fcntl.LOCK_EX if 'alles' in bereiche else fcntl.LOCK_SH)]
        if 'alles' not in bereiche:
            keys += [('bereich:' + b, fcntl.LOCK_EX) for b in bereiche]
        for key, mode in keys:
            fd = os.open(sperrpfad(root, key), os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
            handles.append(fd)
            fcntl.flock(fd, mode | fcntl.LOCK_NB)
            os.set_inheritable(fd, True)
        yield handles[0]
    finally:
        for fd in reversed(handles):
            os.close(fd)


def nachweis(root, name):
    """Der interne Bash-Einstieg braucht die tatsaechlich geerbte Prozesssperre."""
    try:
        fd = int(os.environ.get('JACK_AUFTRAG_SPERRE_FD', '-1'))
        p = sperrpfad(root, 'auftrag:' + dateiname(name))
        a, b = os.fstat(fd), p.stat()
        if (a.st_dev, a.st_ino) != (b.st_dev, b.st_ino):
            return False
        probe = os.open(p, os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0))
        try:
            try:
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            return False
        finally:
            os.close(probe)
    except (OSError, ValueError):
        return False


def main(args=None):
    args = sys.argv[1:] if args is None else args
    if len(args) == 2 and args[0] == '--pruefe-sperre':
        return 0 if nachweis(ROOT, args[1]) else 2
    if not args:
        import datetime
        print(datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
              + '  ARBEITER-LAUF PID=%s Planerpruefung' % os.getpid(), flush=True)
        import jack_planer
        jack_planer.takt()
        return 0
    if len(args) != 2 or args[0] != '--nur':
        print('ARBEITER: Erlaubt ist --nur <Auftragsdatei> oder der normale Planerlauf.')
        return 2
    name = dateiname(args[1])
    import jack_sperren
    p = ROOT / 'auftraege' / 'offen' / name
    if p.is_symlink() or not p.is_file():
        print('ARBEITER: Auftrag liegt nicht in offen/.')
        return 0
    text = p.read_text(encoding='utf-8')
    import jack_planer
    import jack_guthaben
    kopf = jack_planer.kopf(text)
    zustand = jack_planer.zustand_lesen()
    if zustand.get('alles_pausiert'):
        print('ARBEITER: Notbremse aktiv; kein Einzelstart.')
        return 0
    if (ROOT / 'betrieb' / 'STOPP').exists():
        print('ARBEITER: STOPP-Datei gesetzt; kein Einzelstart.')
        return 0
    import jack_oberflaeche
    marke = kopf.get('marke', 'HOLDING')
    if jack_oberflaeche.sperren_lesen(ROOT).get(marke, {}).get('zustand') in ('gestoppt', 'pausiert'):
        print('ARBEITER: Marke pausiert; kein Einzelstart.')
        return 0
    if kopf.get('motor', 'api') in ('api', 'ruflo'):
        grund = jack_guthaben.api_sperre(ROOT)
        if grund:
            print('ARBEITER: ' + grund)
            return 0
    bereiche = jack_sperren.bereiche_aus_kopf(text)
    if any(s.lower() in text.lower() for s in jack_sperren.STEUERDATEIEN):
        bereiche = sorted(set(bereiche) | {'steuerung'})
    try:
        with halten(ROOT, name, bereiche) as fd:
            if not p.is_file():
                return 0
            os.environ['JACK_AUFTRAG_SPERRE_FD'] = str(fd)
            os.environ['JACK_AUFTRAG_RUN_ID'] = uuid.uuid4().hex
            os.execv('/bin/bash', ['/bin/bash', str(ROOT / 'arbeiter.sh'), '--gesperrt', '--nur', name])
    except BlockingIOError:
        print('ARBEITER: Auftrag oder Bereich arbeitet bereits; kein zweiter Start.')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
