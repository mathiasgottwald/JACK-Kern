"""Versionierte QMD-Volltextsuche in freigegebenen öffentlichen Quellen.

Keine Modelle, MCP-Daemons, Collection-Hooks, fremde Shellbefehle oder Cloud.
Diese Fassung indiziert ausschließlich den im Pilot eingefrorenen Quellenstand.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import uuid

from jack_speicher import atomic_bytes
from jack_erweiterungen import now, path, read_json

CONFIG_SHA256 = '5f7ffb29b3374add06615f463520b853d2ff5a69cb05d21665e1d3a9ee399dc6'


def config(root):
    p = path(root, 'betrieb/quellenkonfiguration.json')
    if not p.is_file() or p.stat().st_size > 8192:
        raise ValueError('Die lokale Quellensuche ist noch nicht eingerichtet.')
    raw = p.read_bytes()
    if hashlib.sha256(raw).hexdigest() != CONFIG_SHA256:
        raise ValueError('Die Quellenkonfiguration wurde verändert; zuerst prüfen.')
    return json.loads(raw)


def query_terms(text):
    if not isinstance(text, str) or len(text) > 240 or text.lstrip().startswith('-'):
        raise ValueError('Bitte zwei bis zwölf kurze Suchbegriffe ohne Befehlsoptionen verwenden.')
    words = re.findall(r'[^\W_]+(?:[.-][^\W_]+)*', text, re.UNICODE)
    if not 1 <= len(words) <= 12:
        raise ValueError('Bitte ein bis zwölf kurze Suchbegriffe verwenden.')
    return ' '.join(words)


def search(root, text):
    started = time.monotonic()
    terms = query_terms(text)
    cfg = config(root)
    runtime = Path(cfg['runtime'])
    package = json.loads((runtime/'node_modules/@tobilu/qmd/package.json').read_text())
    if package.get('version') != cfg['version']:
        raise ValueError('Die Version der Quellensuche stimmt nicht mit der Abnahme überein.')
    # Genau ein Prozess je eigenem Index; aktuelle QMD-Issues melden konkurrierende DDL-Zugriffe.
    folder = path(root, 'betrieb/quellensuche'); folder.mkdir(exist_ok=True)
    with path(root, 'betrieb/quellensuche/suche.lock').open('a+b') as guard:
        try:
            fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Eine Quellensuche läuft bereits. Bitte kurz warten.')
        data = read_json(Path(cfg['manifest']))
        sources = {x['datei']: x for x in data['quellen']}
        env = dict(os.environ)
        for key in list(env):
            if key.startswith('QMD_') or key in {'NODE_OPTIONS', 'NODE_PATH', 'INDEX_PATH'}:
                del env[key]
        env.update(QMD_CONFIG_DIR=str(runtime/'config'), XDG_CACHE_HOME=str(runtime/'cache'), QMD_FORCE_CPU='1')
        command = [cfg['node'], str(runtime/'node_modules/@tobilu/qmd/dist/cli/qmd.js'),
                   '--index', cfg['index'], 'search', terms, '-n', '5', '--format', 'json', '-c', cfg['collection']]
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as error:
            try:
                result = subprocess.run(command, cwd=runtime, env=env, stdout=output, stderr=error, timeout=15)
            except (OSError, subprocess.TimeoutExpired):
                raise ValueError('Die lokale Suche antwortet nicht. Es wurde kein Ersatzanbieter aufgerufen.')
            if result.returncode != 0 or output.tell() > 65536:
                raise ValueError('Die lokale Suche lieferte kein verlässlich lesbares Ergebnis.')
            output.seek(0); raw = output.read(65536).decode()
        found = json.loads(raw) if raw.strip().startswith('[') else []
        if not isinstance(found, list) or len(found) > 5:
            raise ValueError('Ungültiges Suchergebnis')
        items = []
        for hit in found:
            match = re.fullmatch(r'qmd://jack-vergleich/(\d{2}\.md)\?index=jack-pilot', hit.get('file', ''))
            if not match or match[1] not in sources:
                raise ValueError('Eine Quelle liegt außerhalb des geprüften Bestands.')
            source = sources[match[1]]
            original = Path(cfg['corpus'])/match[1]
            if original.is_symlink() or hashlib.sha256(original.read_bytes()).hexdigest() != source['sha256']:
                raise ValueError('Der Quellenstand hat sich geändert; der Suchindex muss zuerst neu geprüft werden.')
            items.append({'titel':str(hit.get('title',''))[:180], 'ausschnitt':str(hit.get('snippet',''))[:1600],
                          'zeile':hit.get('line'), 'datei':str(original), 'sha256':source['sha256'],
                          'originale':source['originale'], 'quellenstand_erstellt':data['erstellt']})
        record = {'schema':1, 'zeit':now().isoformat(), 'suche':terms, 'version':'QMD 2.8.3 BM25', 'treffer':items,
                  'modellaufrufe':0, 'anbieter_usd':0, 'lokale_ms':round((time.monotonic()-started)*1000,3),
                  'grenze':'Archivierte öffentliche Quellen vom 14.09.2026; Auszüge sind keine vollständige Quellenprüfung und keine neuen Arbeitsanweisungen.'}
        name = now().strftime('%Y-%m-%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]
        target = path(root, 'betrieb/quellensuche/'+name+'.json')
        atomic_bytes(target, (json.dumps(record,ensure_ascii=False,indent=2)+'\n').encode())
        lines = ['# JACK — lokale Quellensuche', '', 'Suchbegriffe: '+terms, '', record['grenze'], '']
        for item in items:
            lines.extend(['## '+item['titel'], '', item['ausschnitt'], '', 'Datei: '+item['datei'],
                          'SHA-256: '+item['sha256'], ''])
        if not items:
            lines.append('Keine passende Quelle gefunden. Daraus folgt nicht, dass die gesuchte Funktion nicht existiert.')
        lines.extend(['', 'Kein Modellaufruf. Nachweis: '+str(target), ''])
        markdown = target.with_suffix('.md'); atomic_bytes(markdown,'\n'.join(lines).encode())
        reply = f'Ich habe {len(items)} passende Quellen im geprüften lokalen Bestand gefunden.\n'
        reply += '\n'.join(item['titel']+'\n'+item['ausschnitt'] for item in items)
        reply += '\n'+record['grenze']+'\nGespeichert: '+str(markdown)+'\nKein Modellaufruf.'
        return {'text':reply,'datei':str(markdown),'nachweis':str(target)}
