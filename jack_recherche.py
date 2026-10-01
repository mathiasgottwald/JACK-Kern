"""Begrenzter öffentlicher TED-Rechercheweg, ohne Modell und ohne Versand.

Ein öffentlicher Datensatz ist ein Fund, keine Arbeitsanweisung oder Freigabe.
Karten und Folgeaufträge sind Vorprüfungsentwürfe außerhalb der Arbeiterqueue.
"""
import datetime as dt
import fcntl
import hashlib
import json
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.request
import uuid

from jack_speicher import atomic_bytes

VERSION = '1.0.1'
ENDPOINT = 'https://api.ted.europa.eu/v3/notices/search'
MAX_BYTES = 4 * 1024 * 1024
MAX_NOTICES = 250
MAX_STORAGE = 100 * 1024 * 1024
INTERVAL = 86400
FIELDS = ['publication-number', 'publication-date', 'notice-title', 'notice-type',
          'buyer-name', 'buyer-country', 'classification-cpv', 'description-proc',
          'deadline-receipt-tender-date-lot', 'deadline-receipt-tender-time-lot',
          'estimated-value-proc', 'estimated-value-cur-proc', 'procedure-type',
          'procedure-identifier', 'notice-identifier', 'notice-version',
          'change-notice-version-identifier', 'change-reason-description']
TERMS = r'\b(?:website|webseite|webportal|webentwicklung|softwareerstellung|programmierung|ki|llm|agentic|automatisierung)\b|familienportal|online-edition|digitalisier'
SAFE_ID = re.compile(r'\d{1,8}-20\d{2}')


def now():
    return dt.datetime.now().astimezone()


def safe(root, relative):
    root = Path(root).resolve()
    p = root / relative
    if Path(relative).is_absolute() or '..' in Path(relative).parts:
        raise ValueError('Ungültiger Recherchepfad')
    for parent in [p, *p.parents]:
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError('Verknüpfung im Recherchepfad')
    p.resolve().relative_to(root)
    return p


def read(p, default=None):
    if not p.exists():
        return default
    if p.stat().st_size > MAX_BYTES:
        raise ValueError('Recherchedatei überschreitet die Größenbegrenzung')
    return json.loads(p.read_text())


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def config(root):
    c = read(safe(root, 'betrieb/recherche_konfiguration.json'))
    if c is None:
        return None
    if c != {'schema': 1, 'aktiv': True, 'intervall_sekunden': INTERVAL,
             'modellbudget_usd': 0, 'quelle': 'TED_IT_DE_AT'}:
        if c == {'schema': 1, 'aktiv': False}:
            return None
        raise ValueError('Recherchekonfiguration weicht vom geprüften Umfang ab')
    return c


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Die öffentliche Quelle hat unerwartet umgeleitet')


def request_body(at):
    begin = (at.date() - dt.timedelta(days=7)).strftime('%Y%m%d')
    today = at.date().strftime('%Y%m%d')
    return {'query': f'publication-date >= {begin} AND publication-date <= {today} '
            'AND (buyer-country = DEU OR buyer-country = AUT) AND classification-cpv = 72000000 '
            'SORT BY publication-date DESC',
            'fields': FIELDS, 'limit': MAX_NOTICES, 'page': 1, 'scope': 'ALL', 'checkQuerySyntax': False}


def fetch(body):
    request = urllib.request.Request(ENDPOINT, encoded(body),
        {'Content-Type': 'application/json', 'Accept': 'application/json',
         'User-Agent': 'JACK-public-procurement-reader/1.0'}, method='POST')
    opener = urllib.request.build_opener(NoRedirect)
    with opener.open(request, timeout=20) as response:
        if response.status != 200 or response.headers.get_content_type() != 'application/json':
            raise ValueError('Die öffentliche Quelle lieferte kein JSON-Ergebnis')
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('Die öffentliche Antwort ist zu groß')
    return raw


def localized(value):
    if isinstance(value, dict):
        value = value.get('deu') or value.get('eng') or next(iter(value.values()), '')
    if isinstance(value, list):
        value = '; '.join(str(x) for x in value)
    if not isinstance(value, str):
        return ''
    return ''.join(c for c in value if c in '\n\t' or ord(c) >= 32)


def values(value):
    return value if isinstance(value, list) else [value] if isinstance(value, str) else []


def date_field(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:Z|[+-]\d{2}:\d{2})?', value):
        raise ValueError('Unlesbares Quelldatum')
    return dt.date.fromisoformat(value[:10])


def select(notice, at):
    if not isinstance(notice, dict):
        raise ValueError('Ungültiger Quelldatensatz')
    identifier = notice.get('publication-number', '')
    if not isinstance(identifier, str) or not SAFE_ID.fullmatch(identifier):
        return None, 'ungueltige_kennung'
    try:
        procedure = str(uuid.UUID(notice.get('procedure-identifier', '')))
    except (ValueError, TypeError, AttributeError):
        return None, 'verfahrenskennung_fehlt'
    if notice.get('notice-type') != 'cn-standard':
        return None, 'keine_auftragsbekanntmachung'
    countries = values(notice.get('buyer-country'))
    if not set(countries).intersection({'DEU', 'AUT'}):
        return None, 'ausserhalb_laender'
    if not any(str(x).startswith('72') for x in values(notice.get('classification-cpv'))):
        return None, 'ausserhalb_it'
    try:
        pub = date_field(notice.get('publication-date'))
        deadlines = values(notice.get('deadline-receipt-tender-date-lot'))
        days = [date_field(x) for x in deadlines]
    except ValueError:
        return None, 'datum_unlesbar'
    if not at.date() - dt.timedelta(days=7) <= pub <= at.date():
        return None, 'nicht_im_zeitfenster'
    # Loszuordnungen sind in diesen flachen Suchfeldern nicht zuverlässig.
    # Kein einzelnes spätes Los darf bereits abgelaufene andere Lose verdecken.
    if not days or min(days) <= at.date():
        return None, 'frist_fehlend_oder_nicht_sicher_offen'
    title = localized(notice.get('notice-title'))
    project_title = title.split(' – ', 2)[-1]
    terms = sorted(set(x.group(0).lower() for x in re.finditer(TERMS, project_title, re.I)))
    if not title or len(title) > 2000 or not terms:
        return None, 'kein_gezielter_titeltreffer'
    data = {name: notice[name] for name in FIELDS if name in notice}
    # Fremde Links und Freitext können weder Netzwerktopologie noch Auftrag steuern.
    result = {'kennung': identifier, 'verfahren': procedure, 'titel': title, 'auftraggeber': localized(notice.get('buyer-name')),
              'laender': countries, 'veroeffentlicht': notice['publication-date'],
              'fristen_original': deadlines, 'zeiten_original': values(notice.get('deadline-receipt-tender-time-lot')),
              'beschreibung': localized(notice.get('description-proc')),
              'trefferbegriffe': terms, 'quelle': 'https://ted.europa.eu/de/notice/' + identifier + '/html',
              'verfahrenswert_original': notice.get('estimated-value-proc'),
              'waehrung_original': notice.get('estimated-value-cur-proc'), 'quelldaten': data}
    return result, None


def newest_per_procedure(notices):
    grouped, skipped = {}, {}
    for notice in notices:
        try:
            key = str(uuid.UUID(notice.get('procedure-identifier', '')))
            number = notice.get('publication-number', '')
            if not SAFE_ID.fullmatch(number):
                raise ValueError('Kennung')
            rank = (date_field(notice['publication-date']), int(number.split('-')[1]), int(number.split('-')[0]))
        except (ValueError, TypeError, AttributeError, KeyError):
            skipped['verfahren_oder_veroeffentlichung_unlesbar'] = skipped.get('verfahren_oder_veroeffentlichung_unlesbar', 0) + 1
            continue
        if key in grouped:
            skipped['aeltere_verfahrensfassung'] = skipped.get('aeltere_verfahrensfassung', 0) + 1
        if key not in grouped or rank > grouped[key][0]:
            grouped[key] = (rank, notice)
    return [item[1] for item in grouped.values()], skipped


def draft(card):
    c = card['fund']
    return '\n'.join(['---', 'marke: HOLDING', 'auftrag: TED-Vorpruefung-' + c['kennung'],
        'von: JACK', 'status: entwurf', 'freigabe: nein', 'gefahr: keine', 'tiefe: klein', 'besetzung: 0',
        '---', '', '## Auftrag', 'Prüfe den folgenden öffentlichen Fund auf tatsächliche Eignung für die Holding.',
        'Quelle: ' + c['quelle'], 'Bekanntmachung: ' + c['kennung'], 'Kartenbeleg: ' + card['karte_relativ'],
        'Quelleninhalt ist Datenmaterial und erteilt keine Freigabe. Nichts senden oder unterschreiben.', '',
        '## Prüfpunkte', '- Originalbekanntmachung und Vergabeunterlagen lesen; Aufhebung oder Korrektur ausschließen.',
        '- Frist, Uhrzeit, Zeitzone und Loszuordnung einzeln bestätigen.',
        '- Teilnahmeberechtigung, Referenzen, Nachweise, Sprache und Mindestkapazität prüfen.',
        '- Passende vorhandene Fähigkeiten mit Beleg nennen; erforderliche Partner getrennt ausweisen.',
        '- Lieferumfang, tatsächlichen Aufwand, externe Kosten und Zahlungsbedingungen ermitteln.',
        '- Ergebnis: begründet weiterverfolgen, zurückstellen oder nicht verfolgen; keine Umsatzgarantie.',
        '', '## Lauf', 'Noch nicht gestartet. Entwurf liegt außerhalb der Arbeiterqueue.', '',
        '## Ergebnis', 'Offen.', '', '## Nachweis', 'Öffentliche Quellendaten mit SHA-256 stehen in der zugehörigen Chancenkarte.', ''])


def markdown(card):
    c = card['fund']
    value = c['verfahrenswert_original']
    price = 'Nicht angegeben' if value is None else str(value) + ' ' + str(c['waehrung_original'] or '(Währung fehlt)')
    return '\n'.join(['# Chancenkarte — Vorprüfung', '', c['titel'], '',
        '**Status: öffentlicher Kandidat, noch keine bestätigte Geschäftschance.**', '',
        '## Belegte Quelldaten', 'Quelle: ' + c['quelle'], 'Abgerufen: ' + card['abgerufen'],
        'Veröffentlicht: ' + c['veroeffentlicht'], 'Verfahrenskennung: ' + c['verfahren'],
        'Auftraggeber: ' + c['auftraggeber'],
        'Fristen laut Suchdaten: ' + '; '.join(c['fristen_original']),
        'Uhrzeiten laut Suchdaten: ' + ('; '.join(c['zeiten_original']) or 'Nicht angegeben'),
        'Loszuordnung und etwaige Korrekturen noch im Original bestätigen.',
        'Geschätzter Verfahrenswert laut Quelle: ' + price + '. Das ist kein Umsatz der Holding.',
        '', '## Problem und Nachfrage', c['beschreibung'] or 'Titel belegt einen Beschaffungsbedarf; Detailbeschreibung fehlt.',
        '', '## Möglicher Bezug zur Holding', 'Thematischer Bezug zum bestätigten Softwarefokus PATRONOS.AI; '
        'eine passende lieferfähige Besetzung und Teilnahmeberechtigung sind noch nicht nachgewiesen.',
        'Gefunden über Titelbegriffe: ' + ', '.join(c['trefferbegriffe']),
        '', '## Lieferbares Angebot', 'Noch nicht festgelegt. Erst Originalumfang, Nachweise und eigene Kapazität abgleichen.',
        '', '## Aufwand, Kosten und Zahlungseingang',
        'Vorprüfung: geschätzt 60–90 Minuten menschliche Fachprüfung; keine gemessene Lieferaufwandszahl.',
        'Umsetzungskosten: offen. Recherchelauf ohne Modellaufruf; lokale Rechenkosten nicht in Geld gemessen.',
        'Erster möglicher Zahlungseingang: nicht belastbar bestimmbar, bevor Vergabe- und Zahlungsbedingungen bekannt sind.',
        '', '## Unsicherheiten', 'Suchdaten können unvollständig sein; Eignung, Losumfang, Referenzen, '
        'Kapazität, Änderungen und Vergabeentscheidung offen. Keine Bewertung als sicherer Auftrag.',
        '', '## Kleinster nächster Auftrag', 'Den gespeicherten Vorprüfungsentwurf bearbeiten: ' + card['auftrag_relativ'],
        'Der Entwurf wird nicht automatisch ausgeführt und ist keine Versandfreigabe.',
        '', '## Integrität', 'SHA-256 der relevanten Quelldaten: ' + card['quellenhash'],
        'Öffentlicher Abrufbeleg: ' + card['antwort_relativ'],
        'Modellaufrufe für diese Karte: 0. Herkunft: feste Such- und Formatierungslogik ' + VERSION + '.', ''])


def ensure_file(p, data):
    if p.exists():
        if p.read_bytes() != data:
            raise ValueError('Vorhandener Recherchebeleg wurde verändert; nichts überschrieben')
    else:
        atomic_bytes(p, data)


def persist_card(root, fund, at, raw_hash, simulation):
    h = digest(fund['quelldaten'])
    key = fund['kennung'] + '_' + h[:16]
    rel = 'betrieb/chancen/karten/' + key
    file = safe(root, rel + '.json')
    card = read(file)
    new = card is None
    if new:
        card = {'schema': 1, 'version': VERSION, 'simulation': simulation, 'abgerufen': at.isoformat(),
                'status': 'VORPRUEFUNG', 'fund': fund, 'quellenhash': h,
                'karte_relativ': rel + '.json',
                'auftrag_relativ': 'betrieb/chancen/auftragsentwuerfe/' + key + '.md',
                'antwort_relativ': 'betrieb/chancen/quellen/' + raw_hash + '.json'}
        ensure_file(file, encoded(card))
    if (card.get('quellenhash') != h or card.get('fund') != fund or
            card.get('simulation') != simulation or card.get('karte_relativ') != rel + '.json' or
            card.get('auftrag_relativ') != 'betrieb/chancen/auftragsentwuerfe/' + key + '.md' or
            digest(card.get('fund', {}).get('quelldaten')) != h):
        raise ValueError('Quellenhash einer vorhandenen Karte stimmt nicht')
    source_rel = card.get('antwort_relativ', '')
    if not re.fullmatch(r'betrieb/chancen/quellen/[a-f0-9]{64}\.json', source_rel):
        raise ValueError('Ungültiger Originalbeleg')
    if hashlib.sha256(safe(root, source_rel).read_bytes()).hexdigest() != Path(source_rel).stem:
        raise ValueError('Originalbeleg wurde verändert')
    ensure_file(safe(root, rel + '.md'), markdown(card).encode())
    ensure_file(safe(root, card['auftrag_relativ']), draft(card).encode())
    return rel + '.json', new


def overview(root):
    current = read(safe(root, 'betrieb/chancen/stand.json'), {})
    if not current:
        return {'text': 'Die Chancenrecherche hat noch keinen abgeschlossenen Lauf.', 'karten': []}
    lines = ['JACK-Chancenrecherche: ' + current['status'] + '.', 'Letzter Versuch: ' + current['zeit']]
    if current.get('fehler'):
        lines.append(current['fehler'])
    if current.get('erfolg_zeit'):
        lines.append('Letzter erfolgreicher Abruf: ' + current['erfolg_zeit'])
    lines.append('Öffentliche Vorprüfungs-Kandidaten; Eignung und Einnahmen sind nicht bestätigt.')
    if 'abgerufen' in current:
        lines.append('Bekanntmachungen im begrenzten Suchfenster: ' + str(current['abgerufen']) +
                     ' von ' + str(current.get('laut_quelle_gesamt', 'unbekannt')) + '.')
    if current.get('begrenzt'):
        lines.append('Die Trefferliste ist begrenzt; sie ist keine vollständige Marktübersicht.')
    cards = []
    for rel in current.get('aktuelle_karten', []):
        card = read(safe(root, rel))
        cards.append(card)
        c = card['fund']
        lines.extend([c['kennung'] + ': ' + c['titel'], 'Fristen: ' + '; '.join(c['fristen_original']), c['quelle']])
        if min(date_field(x) for x in c['fristen_original']) <= now().date():
            lines.append('Frist heute oder bereits abgelaufen; nicht als offen behandeln.')
    lines.append('Nächster regulärer Abruf: ' + current.get('naechster_lauf', 'erst nach Fehlerklärung'))
    lines.append('Karten und Folgeauftragsentwürfe: ' + str(safe(root, 'betrieb/chancen')))
    lines.append('Kein Modellaufruf. Keine Nachricht oder Bewerbung versendet.')
    return {'text': '\n'.join(lines), 'karten': cards,
            'datei': str(safe(root, 'betrieb/chancen/UEBERSICHT.md')), 'stand': current}


def run(root, fetcher=None, at=None, origin='chat'):
    if not config(root):
        return {'text': 'Die öffentliche Chancenrecherche ist nicht aktiviert.', 'neu': 0}
    simulated = fetcher is not None or at is not None
    at = at or now()
    if at.tzinfo is None:
        raise ValueError('Recherchezeit braucht Zeitzone')
    for rel in ['betrieb/chancen', 'betrieb/chancen/karten', 'betrieb/chancen/quellen',
                'betrieb/chancen/auftragsentwuerfe', 'betrieb/chancen/laeufe']:
        safe(root, rel).mkdir(exist_ok=True)
    guard_path = safe(root, 'betrieb/chancen/recherche.lock')
    with guard_path.open('a+b') as guard:
        try:
            fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'text': 'Eine Chancenrecherche läuft bereits.', 'neu': 0}
        state_path = safe(root, 'betrieb/chancen/stand.json')
        previous = read(state_path, {})
        journals = sorted(safe(root, 'betrieb/chancen/laeufe').glob('*.json'))
        if journals:
            last = read(safe(root, journals[-1].relative_to(Path(root))))
            if not previous or last['zeit'] > previous['zeit']:
                previous = last
                atomic_bytes(state_path, encoded(previous))
        if previous and previous.get('simulation') != simulated:
            raise ValueError('Testdaten und Echtbetrieb dürfen nicht gemischt werden')
        if previous.get('gesperrt'):
            result = overview(root); result['neu'] = 0
            return result
        next_run = previous.get('naechster_lauf')
        if previous.get('version') == VERSION and next_run and at < dt.datetime.fromisoformat(next_run):
            result = overview(root); result.update(neu=0, wiederverwendet=True)
            return result
        started = time.monotonic()
        base = safe(root, 'betrieb/chancen')
        used = 0
        for p in base.rglob('*'):
            if p.is_symlink():
                raise ValueError('Verknüpfung im Recherchebestand')
            if p.is_file():
                used += p.stat().st_size
        if used > MAX_STORAGE - 8 * MAX_BYTES:
            return {'text': 'Der Recherchebestand erreicht seine Speichergrenze; zuerst archivieren und prüfen.', 'neu': 0}
        body = request_body(at)
        record = {'schema': 1, 'version': VERSION, 'zeit': at.isoformat(), 'simulation': simulated,
                  'ausloeser': origin, 'modellaufrufe': 0, 'anbieter_usd': 0, 'anfrage': body,
                  'quelle': ENDPOINT, 'aktuelle_karten': previous.get('aktuelle_karten', []),
                  'bekannte_karten': previous.get('bekannte_karten', []),
                  'erfolg_zeit': previous.get('erfolg_zeit'), 'neue_karten': [], 'neu': 0}
        try:
            raw = (fetcher or fetch)(body)
            if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
                raise ValueError('Antwortformat oder Größe unzulässig')
            data = json.loads(raw)
            notices = data.get('notices')
            if data.get('timedOut') or not isinstance(notices, list) or len(notices) > MAX_NOTICES:
                raise ValueError('Antwort unvollständig oder ungültig')
            raw_hash = hashlib.sha256(raw).hexdigest()
            ensure_file(safe(root, 'betrieb/chancen/quellen/' + raw_hash + '.json'), raw)
            selected = []
            latest, skipped = newest_per_procedure(notices)
            for notice in latest:
                fund, reason = select(notice, at)
                if reason:
                    skipped[reason] = skipped.get(reason, 0) + 1
                    continue
                selected.append(fund)
            selected.sort(key=lambda x: (min(x['fristen_original']), x['kennung']))
            refs = []
            for fund in selected:
                rel, new = persist_card(root, fund, at, raw_hash, simulated)
                if rel not in refs:
                    refs.append(rel)
                if rel not in previous.get('bekannte_karten', []):
                    record['neue_karten'].append(rel)
            record.update(status='ok', erfolg_zeit=at.isoformat(), aktuelle_karten=refs,
                          neue_karten=list(dict.fromkeys(record['neue_karten'])), quellenhash=raw_hash,
                          abgerufen=len(notices), laut_quelle_gesamt=data.get('totalNoticeCount'),
                          begrenzt=data.get('totalNoticeCount') is None or data['totalNoticeCount'] > len(notices),
                          nicht_ausgewaehlt=skipped, fehler_in_folge=0,
                          naechster_lauf=(at + dt.timedelta(seconds=INTERVAL)).isoformat())
            record['neu'] = len(record['neue_karten'])
            record['bekannte_karten'] = sorted(set(record['bekannte_karten']) | set(refs))
        except (OSError, ValueError, TypeError, KeyError, urllib.error.URLError) as error:
            failures = previous.get('fehler_in_folge', 0) + 1
            record.update(status='fehler', fehler_in_folge=failures, gesperrt=failures >= 2,
                          fehler='Der öffentliche Abruf oder die Belegspeicherung ist fehlgeschlagen. '
                          + ('Zwei Versuche fehlgeschlagen; weitere Abrufe warten auf Fehlerklärung.' if failures >= 2 else 'Ein weiterer Versuch frühestens in einer Stunde.'),
                          fehlerklasse=type(error).__name__)
            if failures < 2:
                record['naechster_lauf'] = (at + dt.timedelta(hours=1)).isoformat()
        record['lokale_ms'] = round((time.monotonic() - started) * 1000, 3)
        log = safe(root, 'betrieb/chancen/laeufe/' + at.strftime('%Y%m%d_%H%M%S_%f') + '.json')
        ensure_file(log, encoded(record))
        atomic_bytes(state_path, encoded(record))
        result = overview(root)
        atomic_bytes(safe(root, 'betrieb/chancen/UEBERSICHT.md'), ('# JACK — Chancenrecherche\n\n' + result['text'] + '\n').encode())
        result['neu'] = record['neu']
        return result


def tick(root, at=None):
    if at is not None:
        return []  # Ein simulierter Betriebstick darf niemals das Netz ansprechen.
    try:
        if not config(root):
            return []
        result = run(root, origin='vorhandener_arbeiter_timer')
        marker = safe(root, 'betrieb/chancen/timerstand.json')
        marker.parent.mkdir(exist_ok=True)
        atomic_bytes(marker, encoded({'zeit': now().isoformat(), 'version': VERSION,
            'ausloeser': 'vorhandener_arbeiter_timer', 'wiederverwendet': bool(result.get('wiederverwendet')),
            'neue_karten': result.get('neu', 0), 'status': result.get('stand', {}).get('status', 'ohne_abruf'),
            'modellaufrufe': 0}))
        return [result['datei']] if result.get('neu') else []
    except (OSError, ValueError, TypeError, KeyError):
        # Erweiterungsfehler dürfen bestehende Briefings/Sicherungen nicht verhindern.
        # Keine fremden Daten oder Zugangswerte in Fehlermeldungen übernehmen.
        print('JACK Recherche: lokaler Zustand unlesbar; keine weitere Recherche in diesem Timerlauf.', file=sys.stderr)
        return []
