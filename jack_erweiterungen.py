"""Lokaler Ausbaustand, knappe Übergaben und belegte Beobachtungszeit.

Diese Statusfunktionen verwenden keine Modelle. Ausdrückliche Suchaufträge
werden an die begrenzten separaten Suchmodule weitergereicht.
Die bestehende Fünf-Minuten-Routine ruft observe auf. Ein Prüfstand ist keine
Aktivierungsfreigabe. Inspiration: Marcin Resource Library, Übergaben; die
Forderung des dortigen SNAPSHOT-Prompts nach Schlüsselwerten wird verworfen.
"""
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
from pathlib import Path
import time
import uuid
from zoneinfo import ZoneInfo
from jack_speicher import atomic_bytes

ZONE = ZoneInfo('Europe/Vienna')
STATUSES = {'OFFEN', 'IN PRÜFUNG', 'IM PILOT', 'INTEGRIERT', 'VERIFIZIERT', 'ABGELEHNT', 'BLOCKIERT'}
CODE = ('server.py', 'jack_betrieb.py', 'jack_erweiterungen.py', 'jack_speicher.py',
        'jack_kosten.py', 'arbeiter.sh', 'index.html', 'modellwahl.json')


def now():
    return dt.datetime.now(ZONE)


def path(root, relative):
    root = Path(root).resolve()
    rel = Path(relative)
    if rel.is_absolute() or '..' in rel.parts:
        raise ValueError('Unzulässiger Ablagepfad')
    p = root
    for part in rel.parts:
        p = p / part
        if p.is_symlink():
            raise ValueError('Verknüpfte Ablage ist nicht zulässig')
    return p


def read_json(p, default=None):
    if not p.exists():
        return default
    if p.is_symlink() or p.stat().st_size > 1_000_000:
        raise ValueError('Ungültige oder zu große Zustandsdatei')
    return json.loads(p.read_text())


def write_json(p, value):
    atomic_bytes(p, (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode())


def journal_tail(p):
    """Das dauerhafte Journal bleibt bei abgebrochenem Snapshot maßgeblich."""
    if not p.exists():
        return None
    with p.open('rb') as stream:
        stream.seek(0, 2)
        size = stream.tell()
        stream.seek(max(0, size - 16384))
        tail = stream.read()
    if not tail:
        return None
    if not tail.endswith(b'\n'):
        raise ValueError('Unvollständiger Messbeleg; keine Zeit wird angerechnet')
    value = json.loads(tail.rstrip(b'\n').split(b'\n')[-1])
    if value.get('schema') != 1 or 'letzte_messung' not in value:
        raise ValueError('Ungültiger Messbeleg')
    value.pop('typ', None)
    return value


def configuration(root):
    value = read_json(path(root, 'betrieb/erweiterungen_konfiguration.json'))
    if value is None:
        return None
    if value.get('schema') != 1 or value.get('modellbudget_usd') != 0:
        raise ValueError('Ausbau-Beobachtung muss ohne Modellbudget laufen')
    rel = Path(value.get('ablage', ''))
    if len(rel.parts) != 2 or rel.parts[0] != 'abnahme':
        raise ValueError('Ausbaudokumentation muss unter abnahme liegen')
    if not path(root, rel).is_dir():
        raise ValueError('Ausbaudokumentation fehlt')
    return value


def state(root):
    config = configuration(root)
    if not config:
        return {'eingerichtet': False, 'text': 'Die Ausbauprüfung ist noch nicht verbunden.'}
    document = path(root, Path(config['ablage']) / 'JACK-Erweiterungsstand.json')
    data = read_json(document)
    if not isinstance(data, dict):
        raise ValueError('Ausbaustand fehlt')
    positions = data.get('positionen', [])
    numbers = [x.get('nummer') for x in positions]
    if sorted(numbers) != [str(i).zfill(2) for i in range(1, 39)]:
        raise ValueError('Prüfstand muss genau die 38 Positionen enthalten')
    counts = {s: 0 for s in sorted(STATUSES)}
    for item in positions:
        if item.get('status') not in counts:
            raise ValueError('Unbekannter Prüfstatus')
        counts[item['status']] += 1
    trial = read_json(path(root, 'betrieb/erweiterungen/beobachtung.json'), {})
    seconds = trial.get('beobachtete_sekunden', 0)
    last = trial.get('letzte_messung')
    age = None if not last else (now() - dt.datetime.fromisoformat(last)).total_seconds()
    fresh = age is not None and 0 <= age <= 360
    text = ('JACK-Ausbau: 38 Kandidaten erfasst.\n' +
            '\n'.join(f'{s}: {n}' for s, n in counts.items() if n) +
            f'\nTatsächlich gemessene Ausbau-Beobachtung: {seconds / 3600:.2f} Stunden.' +
            f'\nMessstand: {"aktuell" if fresh else "noch nicht vorhanden oder veraltet"}.' +
            '\nDie Zielersparnis von 80–90 Prozent ist noch nicht nachgewiesen.' +
            '\nNormale Arbeiteraufträge beachten weiterhin die vorhandene Kontingentpause.' +
            '\nDie Originalansicht von Obsidian und die vollständige App-Abnahme bleiben offen.' +
            '\nFür eine lokale Übergabe: „Erstelle JACK-Übergabe“.' +
            '\nTechnische Quellen finden: „Suche JACK-Quelle: QMD collection search“.' )
    return {'eingerichtet': True, 'stand': data.get('aktualisiert'), 'anzahl': counts,
            'ablage': str(document.parent), 'text': text,
            'beobachtung': {'sekunden': seconds, 'zusammenhaengend_sekunden': trial.get('zusammenhaengend_sekunden', 0),
                            'messluecken': trial.get('messluecken', 0), 'aktuell': fresh, 'letzte_messung': last},
            'modellaufrufe_dieser_funktion': 0}


def observe(root, at=None):
    """Belegt nur reale Timerintervalle; Datumsvorgabe ist ein isolierter Test."""
    start = time.monotonic()
    config = configuration(root)
    if not config or not config.get('beobachtung_aktiv'):
        return []
    current = at or now()
    simulated = at is not None
    folder = path(root, 'betrieb/erweiterungen'); folder.mkdir(exist_ok=True)
    lock = path(root, 'betrieb/erweiterungen/beobachtung.lock')
    with lock.open('a+b') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        state_path = path(root, 'betrieb/erweiterungen/beobachtung.json')
        old = read_json(state_path, {})
        log = path(root, 'betrieb/erweiterungen/beobachtung.jsonl')
        last_record = journal_tail(log)
        if last_record is not None and last_record != old:
            old = last_record
            write_json(state_path, old)
        if old and old.get('simulation') != simulated:
            raise ValueError('Simulation und Echtbetrieb dürfen nicht gemischt werden')
        # Nach außen gemeldete Hostdaten stammen aus der bestehenden Minutenprüfung.
        watchdog = read_json(path(root, 'betrieb/beobachtung_stand.json'), {})
        watchdog_time = watchdog.get('zeit')
        watchdog_age = None if not watchdog_time else (current - dt.datetime.fromisoformat(watchdog_time)).total_seconds()
        healthy = (watchdog.get('status') == 'ok' and watchdog_age is not None and 0 <= watchdog_age <= 180)
        host = watchdog.get('host', {})
        observed = float(old.get('beobachtete_sekunden', 0)); consecutive = float(old.get('zusammenhaengend_sekunden', 0))
        gaps = int(old.get('messluecken', 0)); delta = None
        if old.get('letzte_messung'):
            delta = (current - dt.datetime.fromisoformat(old['letzte_messung'])).total_seconds()
            if delta == 0:
                return []
            same_boot = old.get('mac_start') == host.get('boot') and host.get('boot') is not None
            same_server = old.get('server_pid') == host.get('server_pid') and isinstance(host.get('server_pid'), int) and host['server_pid'] > 0
            if 0 < delta <= 360 and healthy and old.get('gesund') and same_boot and same_server:
                observed += delta; consecutive += delta
            else:
                consecutive = 0; gaps += 1
        signature = hashlib.sha256(json.dumps({'status': watchdog.get('status'), 'pid': host.get('server_pid'),
                                               'boot': host.get('boot'), 'arbeiter': host.get('arbeiter_geladen')}, sort_keys=True).encode()).hexdigest()
        changed = signature != old.get('signatur')
        record = {'schema': 1, 'simulation': simulated, 'start': old.get('start', current.isoformat()),
                  'letzte_messung': current.isoformat(), 'beobachtete_sekunden': round(observed, 3),
                  'zusammenhaengend_sekunden': round(consecutive, 3), 'messluecken': gaps,
                  'messungen': old.get('messungen', 0) + 1, 'gesund': healthy,
                  'mac_start': host.get('boot'), 'server_pid': host.get('server_pid'), 'signatur': signature,
                  'modellaufrufe': 0, 'zusatzkosten_anbieter_usd': 0,
                  'lokale_rechenkosten': 'Nicht in Geld gemessen; lokale Laufzeit getrennt erfasst.',
                  '24h_belegt': consecutive >= 86400 and not simulated,
                  'pruefdauer_ms': round((time.monotonic() - start) * 1000, 3)}
        # Nur Metadaten, keine Gesprächs- oder Schlüsselwerte. Ereignisse bei Änderung.
        event = dict(record, typ='aenderung' if changed else 'messung')
        with log.open('ab') as stream:
            stream.write((json.dumps(event, ensure_ascii=False) + '\n').encode()); stream.flush()
            os.fsync(stream.fileno())
        write_json(state_path, record)
        return [str(state_path)] if changed else []


def handoff(root):
    status = state(root)
    if not status['eingerichtet']:
        raise ValueError('Ausbauprüfung ist noch nicht verbunden')
    folder = path(root, 'betrieb/uebergaben'); folder.mkdir(exist_ok=True)
    name = 'JACK_' + now().strftime('%Y-%m-%d_%H%M%S') + '_' + uuid.uuid4().hex[:8]
    data = {'schema': 1, 'zeit': now().isoformat(), 'projekt': str(Path(root).resolve()),
            'pruefstand': status['ablage'], 'positionen': status['anzahl'],
            'beobachtung': status['beobachtung'], 'dateihashes': {},
            'rechte': 'Bestehende Freigaben, Stopps und Budgets gelten. Keine Zugangsdaten in Übergaben.',
            'naechster_schritt': 'JACK-Erweiterungsstand.json und JACK-38-Pruefmatrix.csv in der Prüfablage lesen; Ausgangszustand live verifizieren; nächste offene Einzelprüfung fortsetzen.',
            'offene_grenzen': ['Obsidian nach zwei Speicherabbrüchen gestoppt', 'App-Fensterabnahme offen',
                              'Abo-Kontingentpause beachten', 'Keine gemessene 80–90-Prozent-Gesamtersparnis'],
            'modellaufrufe': 0}
    for item in CODE:
        p = path(root, item)
        if p.is_file():
            data['dateihashes'][item] = hashlib.sha256(p.read_bytes()).hexdigest()
    metadata = path(root, 'betrieb/uebergaben/' + name + '.json')
    markdown = path(root, 'betrieb/uebergaben/' + name + '.md')
    write_json(metadata, data)
    lines = ['# JACK — überprüfbarer Übergabestand', '', 'Erstellt: ' + data['zeit'], '',
             'Projekt: ' + data['projekt'], 'Prüfablage: ' + data['pruefstand'], '',
             data['rechte'], '', 'Nächster Schritt: ' + data['naechster_schritt'], '',
             'Offene Grenzen:', *['- ' + x for x in data['offene_grenzen']], '',
             'Lokaler maschinenlesbarer Nachweis: ' + str(metadata), '',
             'Die Übergabe erzeugt keine neue Freigabe. Null Modellaufrufe. Schlüsseldateien und Gesprächsinhalte wurden nicht übernommen.', '']
    atomic_bytes(markdown, '\n'.join(lines).encode())
    return {'datei': str(markdown), 'nachweis': str(metadata),
            'text': 'Die JACK-Übergabe ist lokal gespeichert.\n' + str(markdown) + '\nEnthalten: Prüfstand, nächste Schritte, offene Grenzen und Code-Prüfsummen. Keine Zugangsdaten. Kein Modellaufruf.'}


def intent(text):
    web = re.fullmatch(r"\s*Suche JACK-Web:\s*(.+?)\s*", text, re.I)
    if web:
        return "web:" + web[1]
    document = re.fullmatch(r"\s*Lies JACK-Datei:\s*(.+?)\s*", text, re.I)
    if document:
        return "dokument:" + document[1]
    normalized_research = ' '.join(text.strip().rstrip('.!?').lower().split())
    if normalized_research in {'verbessere jacks dokumentvorschau', 'verbessere jack-dokumentvorschau'}:
        return 'vorschau_verbessern'
    if normalized_research == 'setze jack-dokumentvorschau zurück':
        return 'vorschau_zurueck'
    if normalized_research in {'suche jack-chancen', 'recherchiere jack-chancen'}:
        return 'chancen_suchen'
    if normalized_research == 'zeige jack-chancen':
        return 'chancen_zeigen'
    source = re.fullmatch(r'\s*Suche JACK-Quelle:\s*(.+?)\s*', text, re.I)
    if source:
        return 'quellen:' + source[1]
    normalized = ' '.join(text.strip().rstrip('.!?').lower().split())
    if normalized in {'zeige den jack-ausbaustand', 'jack-ausbaustand', 'zeige jack-ausbaustand'}:
        return 'stand'
    if normalized in {'erstelle jack-übergabe', 'erstelle jack-uebergabe'}:
        return 'uebergabe'
    return None


def dispatch(root, action):
    if action.startswith("web:"):
        from jack_websuche import search
        return search(root, action[len("web:"):])
    if action in {'vorschau_verbessern', 'vorschau_zurueck'}:
        # F-4 (24.09.2026): die Vorschau-Engine heisst jack_dokumentvorschau
        # (bytegleich zur gebundenen Fassung vom 14.09.); jack_faehigkeiten ist
        # seit 21.09. das Faehigkeitsregister.
        import jack_dokumentvorschau
        return jack_dokumentvorschau.improve(root) if action == 'vorschau_verbessern' else jack_dokumentvorschau.rollback(root)
    if action.startswith("dokument:"):
        from jack_dokumente import read_document
        return read_document(root, action[len("dokument:"):])
    if action in {'chancen_suchen', 'chancen_zeigen'}:
        import jack_recherche
        return jack_recherche.run(root) if action == 'chancen_suchen' else jack_recherche.overview(root)
    if action.startswith('quellen:'):
        from jack_quellen import search
        return search(root, action[len('quellen:'):])
    if action == 'stand':
        return state(root)
    if action == 'uebergabe':
        return handoff(root)
    raise ValueError('Unbekannte lokale Ausbauaktion')
