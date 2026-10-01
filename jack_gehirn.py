"""Lesender Vault-Graph nach Obsidian-Markdown und JSON Canvas 1.0."""
from collections import defaultdict
import hashlib
import fcntl
import json
import math
import os
from pathlib import Path
import re
import threading
import time
from urllib.parse import unquote
import jack_betrieb as b
from jack_speicher import atomic_bytes

SCHWER = {'01_Bilder', '06_Medien', '04_Web_Code', '99_Archiv', 'node_modules',
          '.git', '.next', '.venv', 'dist', '__pycache__'}
GESPERRT = ('schluessel', 'schlüssel', 'credentials', 'secrets', 'password', 'passwort')
_LOCK = threading.Lock()
_JOB = {'laeuft': False, 'fehler': None}


def ausgeschlossen(rel, filters):
    if any(p in SCHWER or p.startswith('.') or p.endswith('.nosync') for p in rel.parts):
        return True
    if any(part in rel.name.lower() for part in GESPERRT) or rel.suffix.lower() in {'.pem', '.key', '.p12', '.pfx'}:
        return True
    name = rel.as_posix()
    teile = tuple(p.casefold() for p in rel.parts)
    if (teile[:2] in (('07_projekte', 'jack'), ('00_marken', 'jack'))
            and len(teile) > 2 and teile[2] in ('betrieb', 'lib', 'abnahme', 'ruflo')):
        return True
    for rule in filters:
        if rule.startswith('/') and rule.endswith('/'):
            if re.search(rule[1:-1], name):
                return True
        elif name == rule.rstrip('/') or name.startswith(rule.rstrip('/') + '/'):
            return True
    return False


def gruppe(path):
    parts = Path(path).parts
    if 'auftraege' in parts:
        return 'Aufträge'
    if 'agenten' in parts or (parts and parts[0] == '08_Mitarbeiter'):
        return 'Agenten'
    if '07_Projekte' in parts:
        return 'Projekte'
    if parts and parts[0] == '00_Marken':
        return 'Marken'
    return 'Holding'


def build(vault):
    vault = Path(vault).resolve()
    config = vault / '.obsidian/app.json'
    filters = json.loads(config.read_text()).get('userIgnoreFilters', []) if config.is_file() else []
    nodes, edges, docs, names = {}, set(), {}, defaultdict(list)
    errors, skipped, ambiguous = [], 0, 0
    began = time.monotonic()
    def node(rel, kind):
        key = str(rel)
        nodes[key] = {'id': key, 'label': rel.name, 'pfad': key, 'art': kind,
                      'gruppe': gruppe(key), 'zweck': 'Ordner' if kind == 'ordner' else 'Datei; Zweck nicht ausdrücklich beschrieben'}
        names[rel.stem].append(key)
    for folder, dirs, files in os.walk(vault, followlinks=False, onerror=lambda e: errors.append({'pfad': str(Path(e.filename).relative_to(vault)), 'grund': type(e).__name__})):
        parent = Path(folder)
        kept = []
        for name in sorted(dirs):
            path = parent / name
            rel = path.relative_to(vault)
            if ausgeschlossen(rel, filters):
                continue
            node(rel, 'verweis' if path.is_symlink() else 'ordner')
            if not path.is_symlink():
                kept.append(name)
        dirs[:] = kept
        for name in sorted(files):
            path = parent / name
            rel = path.relative_to(vault)
            if ausgeschlossen(rel, filters):
                continue
            node(rel, 'verweis' if path.is_symlink() else 'datei')
            if path.is_symlink():
                continue
            if path.suffix.lower() not in {'.md', '.canvas', '.base'}:
                continue
            try:
                st = path.stat()
                # Platzhalter werden nicht durch das Einlesen heruntergeladen.
                if getattr(st, 'st_flags', 0) & 0x40000000:
                    skipped += 1
                    errors.append({'pfad': str(rel), 'grund': 'Nur in iCloud; nicht lokal eingelesen'})
                    continue
                if st.st_size > 512_000:
                    skipped += 1
                    continue
                text = path.read_text(encoding='utf-8')
                docs[str(rel)] = text
                heading = re.search(r'^#{1,2}\s+(.+)$', text, re.M)
                if heading:
                    nodes[str(rel)]['zweck'] = b.redact(heading[1])[:200]
            except (OSError, UnicodeError) as error:
                errors.append({'pfad': str(rel), 'grund': type(error).__name__})
        if len(nodes) > 100000 or time.monotonic() - began > 120:
            raise ValueError('Vault zu groß für einen vollständigen sicheren Lauf; bisheriger Graph bleibt erhalten')
    def link(source, target, kind):
        if source in nodes and target in nodes and source != target:
            edges.add((source, target, kind))
    def resolve(source, raw):
        nonlocal ambiguous
        raw = unquote(raw.split('|')[0].split('#')[0]).strip()
        if not raw:
            return source
        if raw.startswith(str(vault) + '/'):
            raw = raw[len(str(vault)) + 1:]
        rel = Path(raw)
        if rel.is_absolute() or '..' in rel.parts:
            return None
        for candidate in [str(Path(source).parent / rel), raw]:
            for name in [candidate, candidate + '.md']:
                if name in nodes:
                    return name
        candidates = names.get(rel.stem, [])
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            ambiguous += 1
        return None
    for key, data in nodes.items():
        link(str(Path(key).parent), key, 'enthält')
        path = vault / key
        if data['art'] == 'verweis':
            try:
                target = path.resolve().relative_to(vault).as_posix()
                link(key, target, 'Symlink')
            except (OSError, ValueError, RuntimeError):
                pass
    for source, text in docs.items():
        if source.endswith('.canvas'):
            try:
                canvas = json.loads(text)
                files = {n['id']: resolve(source, n['file']) for n in canvas.get('nodes', []) if n.get('type') == 'file'}
                for target in files.values():
                    link(source, target, 'Canvas-Datei')
                for edge in canvas.get('edges', []):
                    link(files.get(edge.get('fromNode')), files.get(edge.get('toNode')), 'Canvas-Verweis')
            except (ValueError, KeyError, TypeError):
                errors.append({'pfad': source, 'grund': 'Canvas nicht lesbar'})
        for raw in re.findall(r'!?\[\[([^\]]+)\]\]', text):
            link(source, resolve(source, raw), 'Wikilink')
        for raw in re.findall(r'\]\(([^)]+)\)', text):
            link(source, resolve(source, raw), 'Markdown-Link')
        for raw in re.findall(r'(?:\d{2}_[A-Za-z_]+/[^\n`<>"\']+?\.(?:md|canvas|base|py|sh|html|pdf))', text):
            link(source, resolve(source, raw), 'Pfadnennung')
    groups = ['Marken', 'Projekte', 'Agenten', 'Aufträge', 'Holding']
    counts = defaultdict(int)
    for data in nodes.values():
        index = counts[data['gruppe']]
        counts[data['gruppe']] += 1
        group = groups.index(data['gruppe'])
        radius = 40 * math.sqrt(index)
        angle = index * 2.399963
        data['x'] = round(group * 1800 + radius * math.cos(angle))
        data['y'] = round(radius * math.sin(angle))
    return {'zeit': b.now().isoformat(), 'vault': vault.name, 'nodes': list(nodes.values()),
            'edges': [{'source': s, 'target': t, 'art': k} for s, t, k in sorted(edges)],
            'gruppen': dict(counts), 'ausgeschlossen': sorted(SCHWER), 'obsidian_filter': filters,
            'lesefehler': errors[:100], 'lesefehler_anzahl': len(errors), 'uebersprungene_inhalte': skipped,
            'mehrdeutige_verweise': ambiguous, 'sekunden': round(time.monotonic() - began, 3),
            'hinweis': 'Dateiinhalte bleiben unverändert. iCloud-Platzhalter, große Inhalte und mehrdeutige Verweise werden nicht erraten.'}


# ---------------------------------------------------------------- Karte
# Der volle Graph hat 51.723 Knoten und 36 MB - das kann kein Browser zeichnen
# und kein Mensch lesen. Fuer die Karte in der Maske bleiben Ordner und Notizen
# (.md, .canvas, .base) sowie die Kanten zwischen ihnen. Was weggelassen wird,
# steht in der Antwort - es wird nichts stillschweigend unterschlagen.
KARTE_ARTEN = ('.md', '.canvas', '.base')
_KARTE = {'signatur': None, 'daten': None}


def karte(root):
    """Schlanke Karte fuer die Maske. Kein Modellaufruf, nur Lesen."""
    root = Path(root)
    quelle = b.area(root) / 'gehirn.json'
    if quelle.is_symlink():
        raise ValueError('Verweis statt Graph')
    if not quelle.is_file():
        raise ValueError('Der Vault wurde noch nicht eingelesen. '
                         '"Karte aktualisieren" waehlen.')
    st = quelle.stat()
    signatur = [st.st_size, st.st_mtime_ns]
    # Nur neu rechnen, wenn sich die Quelle geaendert hat.
    if _KARTE['signatur'] == signatur and _KARTE['daten'] is not None:
        return _KARTE['daten']

    began = time.monotonic()
    voll = json.loads(quelle.read_text(encoding='utf-8'))
    behalten, index = [], {}
    for eintrag in voll['nodes']:
        pfad = eintrag['pfad']
        if eintrag['art'] != 'ordner' and not pfad.lower().endswith(KARTE_ARTEN):
            continue
        index[eintrag['id']] = len(behalten)
        behalten.append(eintrag)

    gruppen = sorted({e['gruppe'] for e in behalten})
    knoten = [[e['label'], gruppen.index(e['gruppe']),
               0 if e['art'] == 'ordner' else 1,
               e['x'], e['y'], e['pfad'], e.get('zweck', '')[:120]]
              for e in behalten]

    arten = sorted({e['art'] for e in voll['edges']})
    kanten, nachbarn = [], defaultdict(set)
    for e in voll['edges']:
        a, z = index.get(e['source']), index.get(e['target'])
        if a is None or z is None or a == z:
            continue
        kanten.append([a, z, arten.index(e['art'])])
        nachbarn[a].add(z)
        nachbarn[z].add(a)

    verknuepft = sum(1 for k in kanten if arten[k[2]] != 'enthält')
    daten = {
        'zeit': voll.get('zeit'), 'vault': voll.get('vault'),
        'gruppen': gruppen, 'kantenarten': arten,
        'knoten': knoten, 'kanten': kanten,
        'anzahl_knoten': len(knoten), 'anzahl_kanten': len(kanten),
        'anzahl_verknuepfungen': verknuepft,
        'weggelassen_knoten': len(voll['nodes']) - len(knoten),
        'weggelassen_kanten': len(voll['edges']) - len(kanten),
        'gruppen_zaehler': {g: sum(1 for k in knoten if gruppen[k[1]] == g) for g in gruppen},
        'aufbau_sekunden': voll.get('sekunden'),
        'karte_sekunden': round(time.monotonic() - began, 3),
        'lesefehler_anzahl': voll.get('lesefehler_anzahl'),
        'uebersprungene_inhalte': voll.get('uebersprungene_inhalte'),
        'felder': 'knoten = [Name, GruppenNr, 0=Ordner 1=Notiz, x, y, Pfad, Zweck]; '
                  'kanten = [vonNr, nachNr, ArtNr]',
        'hinweis': ('Gezeigt werden Ordner und Notizen (.md, .canvas, .base) sowie die '
                    'Kanten zwischen ihnen. Bilder, Code und andere Dateien bleiben '
                    'aussen vor - sie stehen im vollen Graphen unter /gehirn.'),
    }
    _KARTE['signatur'], _KARTE['daten'] = signatur, daten
    return daten


NOTIZ_ARTEN = ('.md', '.canvas', '.base', '.txt', '.csv', '.json')
NOTIZ_MAX = 200_000


def notiz(root, pfad):
    """Liest EINE Notiz aus dem Vault zum Lesen in JACK. Nur lesen, nie schreiben."""
    root = Path(root)
    vault = root.parents[1]
    if not isinstance(pfad, str) or not pfad or len(pfad) > 1000:
        raise ValueError('Kein Pfad angegeben')
    rel = Path(pfad)
    if rel.is_absolute() or '..' in rel.parts:
        raise ValueError('Unzulaessiger Pfad')
    if ausgeschlossen(rel, []):
        raise ValueError('Diese Datei ist in der Karte gesperrt')
    ziel = vault / rel
    for teil in [ziel] + list(ziel.parents)[:len(rel.parts)]:
        if teil.is_symlink():
            raise ValueError('Verknuepfte Ablage wird nicht gelesen')
    if not ziel.is_file():
        if ziel.is_dir():
            eintraege = []
            for kind in sorted(ziel.iterdir())[:200]:
                if ausgeschlossen(kind.relative_to(vault), []):
                    continue
                eintraege.append({'name': kind.name, 'pfad': str(kind.relative_to(vault)),
                                  'art': 'ordner' if kind.is_dir() else 'datei'})
            return {'art': 'ordner', 'pfad': str(rel), 'name': rel.name,
                    'eintraege': eintraege, 'anzahl': len(eintraege)}
        raise ValueError('Diese Datei gibt es nicht mehr')
    if ziel.suffix.lower() not in NOTIZ_ARTEN:
        return {'art': 'nicht_lesbar', 'pfad': str(rel), 'name': rel.name,
                'text': 'Diese Datei ist kein Text. JACK zeigt nur Notizen und Listen an.',
                'bytes': ziel.stat().st_size}
    st = ziel.stat()
    if st.st_size > NOTIZ_MAX:
        return {'art': 'zu_gross', 'pfad': str(rel), 'name': rel.name,
                'text': 'Diese Notiz ist groesser als 200.000 Zeichen und wird '
                        'nicht in der Maske geoeffnet.', 'bytes': st.st_size}
    text = ziel.read_text(encoding='utf-8', errors='replace')
    return {'art': 'notiz', 'pfad': str(rel), 'name': rel.name,
            'text': b.redact(text), 'bytes': st.st_size,
            'geaendert': b.now().fromtimestamp(st.st_mtime).isoformat(),
            'zeilen': text.count(chr(10)) + 1}


def rebuild(root):
    root = Path(root)
    if not _LOCK.acquire(blocking=False):
        raise ValueError('Einlesen läuft bereits')
    disk_lock = None
    try:
        disk_lock = Path(__file__).open()
        try:
            fcntl.flock(disk_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Ein anderer JACK-Prozess liest den Vault bereits ein')
        _JOB.update(laeuft=True, fehler=None)
        data = build(root.parents[1])
        atomic_bytes(b.area(root) / 'gehirn.json', json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode())
        _JOB['stand'] = data['zeit']
        return data
    except Exception as error:
        _JOB['fehler'] = str(error)[:240]
        raise
    finally:
        if disk_lock is not None:
            disk_lock.close()
        _JOB['laeuft'] = False
        _LOCK.release()


def start_rebuild(root):
    if _JOB['laeuft']:
        return dict(_JOB)
    _JOB.update(laeuft=True, fehler=None)
    def run():
        try:
            rebuild(root)
        except Exception:
            pass  # Der Fehler bleibt im sichtbaren Jobstatus erhalten.
    threading.Thread(target=run, name='JACK-Gehirn', daemon=True).start()
    return dict(_JOB)


def daily(root, at):
    path = b.area(root) / 'gehirn.json'
    if path.exists() and not path.is_symlink():
        if json.loads(path.read_text()).get('zeit', '').startswith(str(at.date())):
            return []
    rebuild(root)
    return [str(path)]
