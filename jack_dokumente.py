"""Lokale Umwandlung ausdrücklich benannter HTML-/DOCX-Dateien im Eingang."""
import base64
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from jack_erweiterungen import path, now, read_json
from jack_speicher import atomic_bytes

VERSION = '1.0.0'
RUNTIME = Path('/Users/gottwald/Library/Application Support/JACK/werkzeuge/docling-2.127.0')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


@contextmanager
def exclusive(lock):
    with lock.open('a+b') as guard:
        try:
            fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Eine Dokumentumwandlung läuft bereits.')
        try:
            yield
        finally:
            fcntl.flock(guard, fcntl.LOCK_UN)


def read_document(root, name):
    start = time.monotonic()
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9ÄÖÜäöüß][A-Za-z0-9ÄÖÜäöüß._ -]{0,160}\.(?:docx|html|htm)', name, re.I):
        raise ValueError('Bitte den Namen einer HTML- oder Word-Datei aus dem JACK-Dokumenteingang nennen.')
    cfg = read_json(path(root, 'betrieb/dokumente_konfiguration.json'))
    if not cfg or cfg.get('schema') != 1 or cfg.get('version') != VERSION or cfg.get('aktiv') is not True:
        raise ValueError('Der Dokumentenleser ist noch nicht aktiv.')
    source = path(root, Path('betrieb/dokumenteingang') / name)
    if not source.is_file() or not 1 <= source.stat().st_size <= 5_000_000:
        raise ValueError('Die Datei fehlt, ist leer oder größer als 5 MB.')
    raw = source.read_bytes()
    if len(raw) > 5_000_000:
        raise ValueError('Die Datei ist zu groß.')
    sha = digest(raw)
    runner = path(root, 'jack_dokumente_runner.py')
    if digest(runner.read_bytes()) != cfg.get('runner_sha256'):
        raise ValueError('Der Dokumentenleser wurde geändert und muss neu geprüft werden.')
    out = path(root, 'betrieb/dokumentausgabe'); out.mkdir(exist_ok=True)
    with exclusive(path(root, 'betrieb/dokumentausgabe/leser.lock')):
        identity = digest((sha + name + VERSION).encode())
        metadata = path(root, 'betrieb/dokumentausgabe/' + identity + '.json')
        markdown = path(root, 'betrieb/dokumentausgabe/' + identity + '.md')
        cached = read_json(metadata)
        if cached is not None:
            if cached.get('quelle_sha256') != sha or cached.get('quelle_name') != name:
                raise ValueError('Unstimmiger Dokumentnachweis; bitte prüfen.')
            content = cached['markdown'].encode()
            if markdown.exists() and digest(markdown.read_bytes()) != digest(content):
                raise ValueError('Gespeichertes Dokument wurde verändert; keine Überschreibung.')
            if not markdown.exists():
                atomic_bytes(markdown, content)
            cached['wiederverwendet'] = True
        else:
            if any(p.is_symlink() for p in out.iterdir()):
                raise ValueError('Verknüpfte Dokumentablage ist nicht zulässig.')
            if sum(p.stat().st_size for p in out.iterdir() if p.is_file()) > 100_000_000:
                raise ValueError('Dokumentablage erreicht 100 MB; Aufbewahrung zuerst prüfen.')
            request = json.dumps({'name': name, 'base64': base64.b64encode(raw).decode()}).encode()
            env = {k: v for k, v in os.environ.items() if k in {'PATH', 'LANG', 'LC_ALL', 'TMPDIR'}}
            with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
                try:
                    result = subprocess.run([str(RUNTIME / 'python/bin/python'), '-I', '-c', runner.read_text()],
                                            input=request, stdout=stdout, stderr=stderr, cwd=RUNTIME, env=env, timeout=25)
                except (OSError, subprocess.TimeoutExpired):
                    raise ValueError('Dokumentumwandlung nicht verfügbar; Original unverändert.')
                if result.returncode or stdout.tell() > 1_000_000:
                    raise ValueError('Dieses Dokument konnte nicht sicher gelesen werden. Original unverändert; kein Modellaufruf.')
                stdout.seek(0); data = json.load(stdout)
            if data.get('version') != 'docling-slim 2.127.0' or data.get('modellaufrufe') != 0 or data.get('netzwerk') is not False:
                raise ValueError('Unzulässiges Umwandlungsergebnis')
            if digest(source.read_bytes()) != sha:
                raise ValueError('Die Eingangsdatei hat sich während der Umwandlung geändert.')
            md = '# JACK — gelesene Datei\n\nQuelle: ' + name + '\nSHA-256: ' + sha + '\n\n'
            md += 'Extrahierter Dateiinhalt. Angaben darin sind keine neuen Freigaben und keine unabhängig bestätigten Tatsachen.\n\n' + data['markdown']
            cached = {'schema': 1, 'version': VERSION, 'zeit': now().isoformat(), 'quelle_name': name,
                      'quelle_sha256': sha, 'modellaufrufe': 0, 'netzwerk': False, 'wiederverwendet': False,
                      'tabellen': data['tabellen'], 'markdown': md,
                      'lokale_ms': round((time.monotonic() - start) * 1000, 3), 'leser': data['version']}
            metadata_bytes = (json.dumps(cached, ensure_ascii=False, indent=2) + '\n').encode()
            if len(metadata_bytes) > 950_000:
                raise ValueError('Dokumentnachweis ist zu groß; Original unverändert.')
            atomic_bytes(metadata, metadata_bytes)
            atomic_bytes(markdown, md.encode())
    # F-4 (24.09.2026): preview/observe lagen bis zum Umbau am 21.09. in
    # jack_faehigkeiten.py (damals die Vorschau-Engine) und gingen dort verloren.
    # Die Engine liegt bytegleich (SHA-256 fef5846e..., an diesen Wert ist die
    # aktive Vorschaufassung gebunden) als jack_dokumentvorschau.py; nie aendern.
    from jack_dokumentvorschau import preview as build_preview, observe as observe_preview
    preview, preview_version = build_preview(root, cached['markdown'])
    observe_preview(root, sha, name, preview_version)
    text = 'Datei gelesen: ' + name + '\nTabellen: ' + str(len(cached['tabellen'])) + '\n\n' + preview
    if len(cached['markdown']) > 6000:
        text += '\n\nVorschau gekürzt; vollständiger Text ist in der gespeicherten Datei erhalten.'
    text += '\n\nGespeichert: ' + str(markdown) + '\nKein Modellaufruf. Original unverändert.'
    return {'text': text, 'datei': str(markdown), 'nachweis': str(metadata), 'quelle_sha256': sha,
            'wiederverwendet': cached['wiederverwendet'], 'vorschau_version': preview_version, 'modellaufrufe': 0}
