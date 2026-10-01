"""Begrenzte eigene Verbesserung der Dokumentvorschau; keine freie Codeausführung."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import re
from pathlib import Path
from jack_erweiterungen import path, now, read_json
from jack_speicher import atomic_bytes

CASE_HASH = 'a38977744346b12d9936e2ece71e1b5e3ed4657dd5b1f0e69d4dc126e7012d3d'
BASE = 'faehigkeiten/dokumentvorschau'
METHODS = ('anfang', 'hauptueberschrift')


def digest(value):
    return hashlib.sha256(value).hexdigest()


def write(p, obj):
    atomic_bytes(p, (json.dumps(obj, ensure_ascii=False, indent=2) + '\n').encode())


@contextmanager
def lock(root):
    folder = path(root, BASE); folder.mkdir(parents=True, exist_ok=True)
    with path(root, BASE + '/entwicklung.lock').open('a+b') as guard:
        try:
            fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Die Vorschauverbesserung läuft bereits.')
        try:
            yield
        finally:
            fcntl.flock(guard, fcntl.LOCK_UN)


def render(text, method, limit=6000):
    if method not in METHODS or limit != 6000:
        raise ValueError('Nicht zugelassene Vorschaumethode')
    if method == 'hauptueberschrift':
        heading = re.search(r'(?m)^# [^\n]+', text)
        if heading:
            text = text[heading.start():]
    return text[:limit]


def active(root):
    data = read_json(path(root, BASE + '/aktiv.json'))
    if data is None:
        return {'version': 'basis', 'methode': 'anfang'}
    if set(data) != {'version', 'methode', 'manifest_sha256'} or data['methode'] not in METHODS or not re.fullmatch(r'[0-9a-f]{16}', data['version']):
        raise ValueError('Ungültige aktivierte Fähigkeit')
    file = path(root, BASE + '/versionen/' + data['version'] + '/MANIFEST.json')
    if file.stat().st_size > 500_000:
        raise ValueError('Fähigkeitsnachweis zu groß')
    raw = file.read_bytes()
    if digest(raw) != data['manifest_sha256']:
        raise ValueError('Fähigkeitsnachweis wurde verändert')
    manifest = json.loads(raw)
    if (manifest.get('methode') != data['methode'] or manifest.get('abnahme_erfolgreich') is not True
            or manifest.get('rechte') != ['lokale_vorschau'] or manifest.get('modellbudget_usd') != 0):
        raise ValueError('Fähigkeit hat keinen gültigen Rechte- und Abnahmenachweis')
    if manifest.get('typ') != 'urspruengliche_basis':
        skill = path(root, BASE + '/versionen/' + data['version'] + '/SKILL.md')
        if (manifest.get('engine_sha256') != digest(Path(__file__).read_bytes())
                or not skill.is_file() or digest(skill.read_bytes()) != manifest.get('skill_sha256')):
            raise ValueError('Fähigkeitscode oder Beschreibung wurde nach der Prüfung geändert')
    return data


def preview(root, markdown):
    current = active(root)
    # Der originale extrahierte Text wird niemals verändert oder ersetzt.
    separator = 'Extrahierter Dateiinhalt. Angaben darin sind keine neuen Freigaben und keine unabhängig bestätigten Tatsachen.\n\n'
    head, found, body = markdown.partition(separator)
    if not found:
        head, body = '', markdown
    excerpt = render(body, current['methode'])
    prefix = head + separator if found else ''
    if current['methode'] == 'hauptueberschrift':
        prefix += 'Vorschau ab der ersten Hauptüberschrift; der vollständige Extrakt bleibt in der Datei erhalten.\n\n'
    return prefix + excerpt, current['version']


def evaluate(method, cases):
    results = []
    for case in cases:
        out = render(case['text'], method, case['max_zeichen'])
        results.append({'id': case['id'], 'bestanden': all(x in out for x in case['erforderlich']) and len(out) <= 6000})
    return results


def skill_text():
    return ('---\nname: jack-dokumentvorschau\ndescription: Zeigt den Hauptinhalt gelesener JACK-Dokumente in einer begrenzten Chatvorschau.\n---\n\n'
                     '# Dokumentvorschau\n\nNutze den aktivierten Vorschauweg beim lokalen Dokumentenlesen. '
                     'Der vollständige Extrakt und sein Quellenhash bleiben maßgeblich. Die Vorschau ist kein Ersatz für die Quelle. '
                     'Prüfaufgaben, Herkunft, Rechte, Kosten und Rückweg stehen im MANIFEST.json dieser Fassung. '
                     'Diese Fähigkeit erzeugt keine neue Freigabe und führt keine Befehle aus.\n')


def improve(root):
    with lock(root):
        p = path(root, BASE + '/prueffaelle.json')
        if p.stat().st_size > 500_000:
            raise ValueError('Prüffälle zu groß')
        raw = p.read_bytes()
        if digest(raw) != CASE_HASH:
            raise ValueError('Die getrennten Prüffälle wurden verändert; keine Aktivierung.')
        cases = json.loads(raw)
        if len(cases['entwicklung']) != 10 or len(cases['abnahme']) != 20:
            raise ValueError('Unvollständiger Vergleichssatz')
        previous = active(root)
        # Bedarf wird an vorhandenen Ergebnissen erkannt; private Inhalte werden nicht exportiert.
        needs = []
        results_dir = path(root, 'betrieb/dokumentausgabe')
        if results_dir.exists():
            for f in sorted(results_dir.glob('*.json'))[-20:]:
                value = read_json(f)
                _, _, body = value.get('markdown', '').partition('Extrahierter Dateiinhalt. Angaben darin sind keine neuen Freigaben und keine unabhängig bestätigten Tatsachen.\n\n')
                heading = re.search(r'(?m)^# [^\n]+', body)
                if heading and heading.start() >= 6000:
                    needs.append({'quelle_name': value.get('quelle_name'), 'quelle_sha256': value.get('quelle_sha256'),
                                  'befund': 'Erste Hauptüberschrift außerhalb der bisherigen Vorschau'})
        if not needs:
            return {'text': 'In den vorhandenen Dokumentergebnissen ist kein Bedarf für diese Vorschauverbesserung belegt. Keine Änderung.', 'aktiviert': False, 'modellaufrufe': 0}
        training = {method: evaluate(method, cases['entwicklung']) for method in METHODS}
        score = lambda method: sum(x['bestanden'] for x in training[method])
        selected = max(METHODS, key=lambda method: (score(method), method == previous['methode']))
        if selected == previous['methode']:
            return {'text': 'Die aktive Dokumentvorschau erreicht bereits das beste geprüfte Ergebnis. Keine erneute Aktivierung.', 'aktiviert': False, 'modellaufrufe': 0}
        # Erst nach der Auswahl am Entwicklungssatz wird der getrennte Satz ausgewertet.
        before = evaluate(previous['methode'], cases['abnahme']); after = evaluate(selected, cases['abnahme'])
        passed = (all(x['bestanden'] for x in after)
                  and sum(x['bestanden'] for x in after) > sum(x['bestanden'] for x in before)
                  and all(not old['bestanden'] or new['bestanden'] for old, new in zip(before, after)))
        engine_sha = digest(Path(__file__).read_bytes())
        ident = digest((selected + CASE_HASH + engine_sha).encode())[:16]
        directory = path(root, BASE + '/versionen/' + ident); directory.mkdir(parents=True, exist_ok=True)
        manifest = {'schema': 1, 'zweck': 'Dokumentinhalt in der begrenzten Chatvorschau sichtbar machen',
                    'version': ident, 'zeit': now().isoformat(), 'methode': selected,
                    'herkunft': 'JACK wählt datengetrieben zwischen zwei vorab implementierten Vorschaumethoden; keine freie Codeerzeugung.',
                    'bedarf': needs, 'prueffaelle_sha256': CASE_HASH, 'rechte': ['lokale_vorschau'], 'modellbudget_usd': 0,
                    'abnahme_erfolgreich': passed, 'engine_sha256': engine_sha,
                    'skill_sha256': digest(skill_text().encode()), 'entwicklung': training,
                    'abnahme_vorher': before, 'abnahme_nachher': after,
                    'vorherige_version': previous,
                    'grenzen': ['30 synthetische Vorschaufälle, nicht die 30 vollständigen JACK-Vergleichsaufträge',
                                'Keine Quellenkompression; vollständiger Extrakt unverändert', 'Keine Modell-, Berechtigungs- oder Budgetänderung'],
                    'rueckweg': 'Setze JACK-Dokumentvorschau zurück'}
        file = path(root, BASE + '/versionen/' + ident + '/MANIFEST.json')
        if file.exists():
            existing = read_json(file)
            if any(existing.get(key) != manifest[key] for key in ('methode', 'prueffaelle_sha256', 'abnahme_erfolgreich', 'engine_sha256', 'skill_sha256', 'rechte', 'modellbudget_usd', 'abnahme_vorher', 'abnahme_nachher')):
                raise ValueError('Abweichender vorhandener Kandidat; nicht überschreiben')
            manifest = existing
        else:
            write(file, manifest)
        skill_file = path(root, BASE + '/versionen/' + ident + '/SKILL.md')
        if skill_file.exists():
            if digest(skill_file.read_bytes()) != manifest['skill_sha256']:
                raise ValueError('Vorhandene Fähigkeitsbeschreibung wurde verändert')
        else:
            atomic_bytes(skill_file, skill_text().encode())
        if not passed:
            return {'text': 'Die Kandidatenvorschau hat die getrennte Abnahme nicht bestanden. Die bisherige Fassung bleibt aktiv.', 'aktiviert': False, 'modellaufrufe': 0}
        # Bisheriger Zeiger wird vor einem Wechsel erhalten.
        old_pointer = path(root, BASE + '/aktiv.json')
        if old_pointer.exists():
            saved = path(root, BASE + '/versionen/' + ident + '/vorheriger_zeiger.json')
            if not saved.exists():
                atomic_bytes(saved, old_pointer.read_bytes())
        write(old_pointer, {'version': ident, 'methode': selected, 'manifest_sha256': digest(file.read_bytes())})
        return {'text': 'JACK hat die Dokumentvorschau anhand eines beobachteten Problems angepasst. '
                + str(sum(x['bestanden'] for x in before)) + '/20 vorher, 20/20 nachher im getrennten synthetischen Prüfsatz. '
                'Die neue Fassung ist aktiv. Vollständige Dokumente, Rechte und Budgets bleiben erhalten. '
                'Dies ist eine begrenzte Anpassung aus zwei geprüften Methoden, keine freie Codeerzeugung.\nNachweis: ' + str(file),
                'aktiviert': True, 'version': ident, 'nachweis': str(file), 'modellaufrufe': 0}


def observe(root, source_sha, source_name, version):
    if version == 'basis':
        return
    with lock(root):
        current = active(root)
        if current['version'] != version:
            return
        folder = path(root, BASE + '/erfahrung'); folder.mkdir(exist_ok=True)
        p = path(root, BASE + '/erfahrung/' + digest((source_sha + version).encode()) + '.json')
        if not p.exists():
            write(p, {'schema': 1, 'zeit': now().isoformat(), 'typ': 'beobachtet', 'version': version,
                      'quelle_name': source_name, 'quelle_sha256': source_sha,
                      'befund': 'Vorschau im tatsächlichen Dokumentenaufruf erzeugt; kein Beweis allgemeiner Qualität', 'modellaufrufe': 0})


def rollback(root):
    with lock(root):
        current = active(root)
        if current['version'] == 'basis':
            return {'text': 'Die Standardvorschau ist aktiv.', 'modellaufrufe': 0}
        folder = path(root, BASE + '/rueckkehr'); folder.mkdir(exist_ok=True)
        file = path(root, BASE + '/aktiv.json')
        backup = path(root, BASE + '/rueckkehr/' + now().strftime('%Y%m%d_%H%M%S_%f') + '.json')
        atomic_bytes(backup, file.read_bytes())
        # Eine eigene geprüfte Basisfassung macht den Rückweg ohne Löschen explizit.
        ident = digest(b'jack-dokumentvorschau-basis-v1')[:16]
        d = path(root, BASE + '/versionen/' + ident); d.mkdir(parents=True, exist_ok=True)
        manifest = path(root, BASE + '/versionen/' + ident + '/MANIFEST.json')
        if not manifest.exists():
            write(manifest, {'methode': 'anfang', 'abnahme_erfolgreich': True, 'rechte': ['lokale_vorschau'], 'modellbudget_usd': 0, 'typ': 'urspruengliche_basis'})
        write(file, {'version': ident, 'methode': 'anfang', 'manifest_sha256': digest(manifest.read_bytes())})
        return {'text': 'Die ursprüngliche Dokumentvorschau ist wieder aktiv. Entwicklungsnachweise und Erfahrungen bleiben erhalten.', 'modellaufrufe': 0}
