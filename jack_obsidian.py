"""Flüchtige lokale Verbindung zum echten Obsidian-Graphen, ohne Dateizugriff."""
import base64
import math
import threading
import time
from collections import deque

VAULT = 'GOTT WALD HOLDING'
LOCK = threading.RLock()
STATE = {'bild': b'', 'gesehen': 0, 'seq': 0, 'fehler': 'Obsidian ist noch nicht verbunden.'}
QUEUE = deque(maxlen=50)
VIEWER = 0

def status():
    with LOCK:
        live = bool(STATE['bild']) and time.monotonic()-STATE['gesehen'] < 5
        return {'live': live, 'seq': STATE['seq'], 'quelle': 'Obsidian Originalgraph',
                'vault': VAULT, 'fehler': None if live else STATE['fehler'] or 'Obsidian liefert kein aktuelles Bild.'}

def frame(data):
    if data.get('vault') != VAULT:
        raise ValueError('Falscher Obsidian-Vault')
    value = data.get('png')
    if not isinstance(value, str) or len(value) > 4_000_000:
        raise ValueError('Ungültiges Graphbild')
    raw = base64.b64decode(value, validate=True)
    if not raw.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('Kein PNG-Graphbild')
    with LOCK:
        STATE.update(bild=raw, gesehen=time.monotonic(), seq=STATE['seq']+1, fehler=None)

def problem(data):
    with LOCK:
        STATE.update(bild=b'', fehler='Obsidian-Graph nicht verfügbar: ' + str(data.get('fehler','unbekannt'))[:180])

def image():
    with LOCK:
        return STATE['bild'] if status()['live'] else None

def control(data):
    global VIEWER
    kind = data.get('art')
    if kind not in {'ansehen','stop','wheel','down','move','up'}:
        raise ValueError('Nur Graphansicht und Navigation erlaubt')
    with LOCK:
        if kind=='ansehen':
            VIEWER = time.monotonic()
            return
        if kind=='stop':
            VIEWER = 0
            QUEUE.clear()
            return
        seq=data.get('seq')
        if not status()['live'] or type(seq) is not int or not STATE['seq']-2<=seq<=STATE['seq']:
            raise ValueError('Graphbild nicht mehr aktuell')
        event={'art':kind}
        for key in ('x','y'):
            number=data.get(key)
            if type(number) not in (int,float) or not math.isfinite(number) or not 0<=number<=1:
                raise ValueError('Position außerhalb des Graphen')
            event[key]=number
        if kind=='wheel':
            number=data.get('delta')
            if type(number) not in (int,float) or not math.isfinite(number):
                raise ValueError('Ungültiger Zoom')
            event['delta']=max(-500,min(500,number))
        if len(QUEUE)>=50:
            raise ValueError('Graphbedienung wartet noch')
        QUEUE.append(event)

def commands():
    with LOCK:
        active = bool(VIEWER) and time.monotonic()-VIEWER<5
        commands=list(QUEUE) if active else []
        QUEUE.clear()
        return {'ansehen':active,'aktionen':commands}


# ---------------------------------------------------------------- F-26: JACK-Spiegel fuer Obsidian (nur Links)
# Nach jeder PM-Pruefung (Datei *_geprueft* in abnahme/pm_eingang/) und bei jedem Postfach-Auftrag schreibt der
# Betriebstakt (jack_betrieb.tick, kein eigener Zeitgeber) zwei Notizen unter OBSIDIAN/: PM_STAND.md und
# AUFTRAEGE_LAUFEND.md. Nur Markdown mit Wikilinks auf die echten Dateien, keine kopierten Inhalte, je < 50 KB.
# Geschrieben wird nur, wenn sich der Bestand geaendert hat; im Testbetrieb (umgeleitete Betriebsablage) nie.
SPIEGEL_ORDNER = 'OBSIDIAN'
SPIEGEL_MAX_BYTES = 50 * 1024
SPIEGEL_KANAELE = ('kern', 'konten', 'logos', 'patronos', 'cashflow', 'sprache', 'videoauswertung')


def _wikilink(vault, pfad, text=None):
    from pathlib import Path
    rel = Path(pfad).resolve().relative_to(vault).as_posix()
    ziel = rel[:-3] if rel.endswith('.md') else rel
    return '[[%s|%s]]' % (ziel, text or Path(rel).name) if text else '[[%s]]' % ziel


def _dateien(ordner, muster='*.md'):
    from pathlib import Path
    ordner = Path(ordner)
    if not ordner.is_dir():
        return []
    return sorted((p for p in ordner.glob(muster) if p.is_file() and not p.is_symlink()),
                  key=lambda p: p.stat().st_mtime, reverse=True)


def _kappen(zeilen):
    text, raus = '', []
    for z in zeilen:
        if len((text + z + '\n').encode('utf-8')) > SPIEGEL_MAX_BYTES - 200:
            raus.append('… (gekürzt, Grenze 50 KB)')
            break
        text += z + '\n'
        raus.append(z)
    return '\n'.join(raus) + '\n'


def spiegel_notizen(root):
    """{'PM_STAND.md': text, 'AUFTRAEGE_LAUFEND.md': text} (ohne zu schreiben)."""
    from pathlib import Path
    import datetime as dt
    import re
    root = Path(root).resolve()
    vault = root.parent.parent
    eingang = root / 'abnahme' / 'pm_eingang'
    ausgang = root / 'auftraege' / 'pm_ausgang'
    jetzt = dt.datetime.now().astimezone().strftime('%d.%m.%Y %H:%M')
    pm = ['# PM-Stand (JACK-Spiegel)', '',
          'Automatisch geschrieben vom Betriebstakt am %s. Nur Verweise, keine Inhalte. Start: [[00_START]].' % jetzt, '',
          '## Offene Postfach-Aufträge']
    for kanal in SPIEGEL_KANAELE:
        offen = _dateien(ausgang / kanal)
        pm.append('- **%s:** %s' % (kanal, ', '.join(_wikilink(vault, p, p.stem) for p in offen) or 'leer'))
    fragen = [p for p in _dateien(eingang) if p.name.endswith('_FRAGE.md')]
    pm += ['', '## Offene Rückfragen an den PM'] + (['- ' + _wikilink(vault, p, p.stem) for p in fragen] or ['- keine'])
    pm += ['', '## Meldungen (neueste zuerst; geprüft = vom PM abgenommen)']
    for p in _dateien(eingang)[:200]:
        if p.name.endswith('_FRAGE.md'):
            continue
        stand = 'geprüft' if '_geprueft' in p.stem else 'offen'
        pm.append('- %s · %s · %s' % (_wikilink(vault, p, p.stem), stand,
                                      dt.datetime.fromtimestamp(p.stat().st_mtime).strftime('%d.%m. %H:%M')))
    zettel = sorted((p for p in (root / 'abnahme').glob('*_zettel.md') if p.is_file()),
                    key=lambda p: int(re.match(r'(\d+)', p.name)[1]) if re.match(r'\d+', p.name) else 0, reverse=True)
    pm += ['', '## Abnahmezettel (Paket 4)'] + (['- ' + _wikilink(vault, p, p.stem) for p in zettel[:60]] or ['- keine'])
    pm += ['', '## Kosten und Regeln',
           '- Kostenbuch: `00_Marken/JACK/betrieb/kostenlaeufe.jsonl` (JSONL, in Obsidian nicht sichtbar)',
           '- ' + _wikilink(vault, root / 'NAECHSTE_SCHRITTE.md', 'Abschlussliste') + ' · ' +
           _wikilink(vault, root / 'auftraege' / 'AUSBAUPLAN_AUTONOMIE_2026-09-21.md', 'Ausbauplan')]
    au = ['# Laufende Aufträge (JACK-Spiegel)', '',
          'Automatisch geschrieben vom Betriebstakt am %s. Start: [[00_START]] · [[00_Marken/JACK/OBSIDIAN/PM_STAND|PM-Stand]].' % jetzt]
    for titel, ordner in (('Läuft', 'laeuft'), ('Offen', 'offen'), ('Wartet auf Freigabe', 'freigabe'),
                          ('Problem', 'problem'), ('Zuletzt erledigt', 'erledigt')):
        liste = _dateien(root / 'auftraege' / ordner)
        if ordner == 'erledigt':
            liste = liste[:40]
        au += ['', '## %s (%d)' % (titel, len(liste))] + (['- ' + _wikilink(vault, p, p.stem) for p in liste] or ['- keine'])
    return {'PM_STAND.md': _kappen(pm), 'AUFTRAEGE_LAUFEND.md': _kappen(au)}


def _bestand(root):
    from pathlib import Path
    import hashlib
    root = Path(root)
    teile = []
    for ordner in [root / 'abnahme' / 'pm_eingang'] + [root / 'auftraege' / 'pm_ausgang' / k for k in SPIEGEL_KANAELE] + \
                  [root / 'auftraege' / o for o in ('laeuft', 'offen', 'freigabe', 'problem', 'erledigt')]:
        for p in _dateien(ordner):
            teile.append('%s|%d' % (p, int(p.stat().st_mtime)))
    teile += sorted(str(p) for p in (root / 'abnahme').glob('*_zettel.md'))
    return hashlib.sha256('\n'.join(sorted(teile)).encode('utf-8')).hexdigest()


def tick(root, at=None):
    """Einhaengepunkt fuer jack_betrieb.tick. -> Liste geschriebener Dateien (leer, wenn unveraendert)."""
    import os
    from pathlib import Path
    root = Path(root).resolve()
    fuer = os.environ.get('JACK_BETRIEB_FUER')
    if os.environ.get('JACK_BETRIEB_DIR') and fuer and Path(fuer).resolve() == root:
        return []                                   # Testbetrieb: Live-Spiegel nie beruehren
    ziel = root / SPIEGEL_ORDNER
    ziel.mkdir(exist_ok=True)
    marke = ziel / '.bestand'
    stand = _bestand(root)
    try:
        if marke.read_text() == stand and all((ziel / n).is_file() for n in ('PM_STAND.md', 'AUFTRAEGE_LAUFEND.md')):
            return []
    except OSError:
        pass
    geschrieben = []
    for name, text in spiegel_notizen(root).items():
        p = ziel / name
        tmp = p.with_name(name + '.neu')
        tmp.write_text(text, encoding='utf-8')
        os.replace(tmp, p)
        geschrieben.append(str(p))
    marke.write_text(stand)
    return geschrieben
