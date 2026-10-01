"""Lokales Gedächtnis, belegte Tagesberichte, Sicherungen und sichere Entwürfe."""
import datetime as dt
from collections import deque
import jack_speicher
from email.message import EmailMessage
from email import policy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import uuid
import zipfile
from zoneinfo import ZoneInfo

ZONE = ZoneInfo('Europe/Vienna')


def now():
    return dt.datetime.now(ZONE)


# F-8 T2 (24.09.2026): Test-Isolation. Sind JACK_BETRIEB_DIR (Ziel) UND JACK_BETRIEB_FUER (die Wurzel, deren
# Ablage umgeleitet wird) gesetzt, liegt die Betriebsablage GENAU DIESER Wurzel im Ziel statt in betrieb/.
# Beide Variablen setzt jack_testumgebung. Wurzeln, die ein Test selbst anlegt - auch Kopien dieses Moduls
# in einer Test-Wurzel - bleiben unberuehrt. Ohne die Variablen (Dienst, Arbeiter) aendert sich nichts.
# Alle Schreibwege laufen ueber area().
def area(root):
    umleitung, fuer = os.environ.get('JACK_BETRIEB_DIR'), os.environ.get('JACK_BETRIEB_FUER')
    if umleitung and fuer and Path(root).resolve() == Path(fuer).resolve():
        u = Path(umleitung)
        if u.is_symlink():
            raise ValueError('Umgeleitete Betriebsablage darf kein Symlink sein')
        u.mkdir(parents=True, exist_ok=True)
        return u
    p = Path(root) / 'betrieb'
    if p.is_symlink():
        raise ValueError('Betriebsablage darf kein Symlink sein')
    p.mkdir(exist_ok=True)
    return p


def append(path, record):
    if path.is_symlink():
        raise ValueError('Protokoll darf kein Symlink sein')
    with path.open('a+b') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0,2)
        if f.tell():
            f.seek(-1,2)
            if f.read() != b'\n':
                f.write(b'\n')
        f.write((json.dumps(record, ensure_ascii=False) + '\n').encode())
        f.flush()


def records(path, limit=None):
    rows = jack_speicher.iter_records(path)
    return list(deque(rows, maxlen=limit)) if limit is not None else list(rows)


def redact(text):
    text = re.sub(r'\bsk-(?:ant-)?[A-Za-z0-9_-]{16,}', '[Schlüssel ausgeblendet]', str(text))
    return re.sub(r'(?im)^.*(?:API_KEY|AUTH_TOKEN|PASSWORD|PASSWORT)\s*[:=].*$', '[Zugangsdaten ausgeblendet]', text)


# Block 18 (Auftrag 2.3): Probe- und Testlaeufe werden BEIM ENTSTEHEN
# gekennzeichnet. Nur so laesst sich spaeter sauber bereinigen, ohne zu raten.
PROBE_ARTEN = ('probe', 'test')


def remember(root, question, answer, evidence='', herkunft=None):
    satz = {'typ': 'dialog', 'zeit': now().isoformat(),
            'frage': redact(question), 'antwort': redact(answer),
            'nachweis': redact(evidence)}
    # S-1 P5 (24.09.2026): jeder neue Eintrag traegt herkunft - patron, test oder probe.
    satz['herkunft'] = str(herkunft).lower() if str(herkunft or '').lower() in PROBE_ARTEN else 'patron'
    append(area(root) / 'gespraeche.jsonl', satz)


def new_session(root):
    append(area(root) / 'gespraeche.jsonl', {'typ': 'neues_gespraech', 'zeit': now().isoformat(), 'herkunft': 'patron'})


def _ausgeschlossen(root):
    """S-5 P2: Zeitstempel von Eintraegen, die NICHT in den Gespraechskontext gehoeren (z. B. Testdialoge, die als 'patron' gespeichert wurden).
    Die Zeilen bleiben unveraendert in gespraeche.jsonl (nichts wird geloescht); betrieb/sprache_ausschluss.json fuehrt ihre Zeiten."""
    try:
        return set(json.loads((area(root) / 'sprache_ausschluss.json').read_text(encoding='utf-8')).get('zeiten') or [])
    except (OSError, ValueError, AttributeError):
        return set()


def history(root, limit=10):
    current = deque(maxlen=limit)
    weg = _ausgeschlossen(root)
    for row in jack_speicher.iter_records(area(root) / 'gespraeche.jsonl'):
        if row.get('typ') == 'neues_gespraech':
            current.clear()
        elif row.get('typ') == 'dialog':
            # Block 18: Probe- und Testeintraege gehoeren nicht in den
            # Gespraechskontext. Sie stehen weiter in der Datei, aber JACK
            # baut seine Antwort nicht auf einem Sprachtest auf.
            if str(row.get('herkunft') or '').lower() in PROBE_ARTEN or row.get('zeit') in weg:
                continue
            current.append(row)
    return list(current)


def recall(root, query):
    text = jack_speicher.search_memory(root, query, now())
    weg = _ausgeschlossen(root)
    if weg and text:
        text = '\n'.join(z for z in text.split('\n') if not any(z.startswith(w) for w in weg))
    return text


def brief(root, kind='morgen', at=None):
    import jack_auftrag
    at = at or now()
    vault = Path(root).parents[1]
    queues = {'gestoppt': []}
    for group in ('offen', 'laeuft', 'freigabe', 'erledigt'):
        items = []
        for p in sorted((Path(root) / 'auftraege' / group).glob('*.md')):
            if p.is_symlink() or p.name.lower().startswith('readme'):
                continue
            text = p.read_text()
            if not text.startswith('---\n'):
                continue
            title = re.search(r'^auftrag:\s*(.+)$', text, re.M)
            attempts = re.search(r'^versuch:\s*(\d+)', text, re.M)
            waiting = re.search(r'^warte_bis:[ \t]*(.+)$', text, re.M)
            ziel = items
            if group == 'erledigt' and re.search(r'^status:[ \t]*gestoppt|^## Vom Patron gestoppt', text, re.M):
                ziel = queues['gestoppt']
            ziel.append({'auftrag': title[1].strip() if title else p.stem, 'pfad': str(p.relative_to(vault)),
                          'versuch': int(attempts[1]) if attempts else 0,
                          'qualitaet': jack_auftrag.kurzstand(root,p),
                          'warte_bis': waiting[1].strip() if waiting else ''})
        queues[group] = items
    label = 'Morgenbriefing' if kind == 'morgen' else 'Abendabschluss'
    lines = [f'# JACK — {label}', '', f'Stand: {at.isoformat()}', '',
             'Automatisch aus den Auftragsdateien gelesen. Keine Live-Abnahme der Marken.', '']
    for group, title in [('freigabe','Entscheidungen'),('laeuft','In Bearbeitung'),('offen','Nächste Arbeit'),('erledigt','Abschlussablage'),('gestoppt','Gestoppt, nicht abgeschlossen')]:
        lines += [f'## {title}', '']
        for row in queues[group][-15:]:
            suffix = f" · wartet bis {row['warte_bis']}" if row['warte_bis'] else ''
            if group == 'offen' and row['versuch'] >= 2:
                suffix += ' · zwei Versuche verbraucht, Prüfung nötig'
            if row['qualitaet'].get('gebunden'):
                suffix += ' · ' + row['qualitaet']['text']
            lines += [f"- {row['auftrag']}{suffix} — `{row['pfad']}`"]
        if not queues[group]:
            lines += ['Keine Einträge.']
        lines += ['']
    lines += (_nachtketteteil(root) + _postfachteil(root) + _kalenderteil(root)
              + _kostenteil(root) + _sprachsteuerungteil(root) + _autonomieteil(root))
    lines += ['', '## Belegte Auftragsabschlüsse', '', jack_auftrag.ergebnislage(root)['text']]
    return {'zeit': at.isoformat(), 'art': kind, 'auftraege': queues, 'text': '\n'.join(lines)}


def _autonomieteil(root):
    """Block 26 (T1.3): eine Zeile Autonomie-Quote im Morgen- und
    Abendbriefing. Faellt etwas aus, bleibt es still."""
    try:
        import jack_autonomie
        return [jack_autonomie.briefzeile(root), '']
    except Exception:
        return []


def _sprachsteuerungteil(root):
    """Block 25 (Teil H1): dieselbe Kennzahlenzeile wie im Kasten Wissen, auch
    im Briefing. Faellt etwas aus, bleibt es still."""
    try:
        import jack_steuerungsprotokoll
        auszug = jack_steuerungsprotokoll.tagesauszug(root)
        if not auszug.get('anzahl'):
            return []
        return ['## Sprachsteuerung', '', auszug['text'], '']
    except Exception:
        return []


def _nachtketteteil(root):
    """Lief ueber Nacht eine Kette, sagt das Briefing es als Erstes.

    Der Patron soll nicht erst in einen Ordner sehen muessen, um zu erfahren,
    dass in der Nacht gearbeitet wurde. Faellt etwas aus, bleibt es still -
    ein Briefing darf daran nie haengen.
    """
    try:
        ordner = Path(root) / 'auftraege'
        berichte = sorted(ordner.glob('NACHTKETTE_BERICHT_*.md'))
        if not berichte:
            return []
        letzter = berichte[-1]
        text = letzter.read_text(encoding='utf-8', errors='replace')
        kopf = ''
        for z in text.splitlines():
            if z.startswith('**Die Nachtkette ist durch'):
                kopf = z.strip('* ')
                break
        offen = len(list((ordner / 'freigabe').glob('*.md')))
        zeile = kopf or ('Die Nachtkette ist durch — %d Punkte warten auf dich.' % offen)
        return ['## Nachtkette', '', zeile, '',
                'Ganzer Bericht: `%s`' % letzter.name, '']
    except Exception:
        return []


def _kostenteil(root):
    """Block 8 (A2, D2): Geld im Briefing - Guthaben, Deckel, Fristen.

    Faellt etwas aus, bleibt es still; ein Briefing darf daran nie haengen.
    Es wird nichts geschaetzt: was unbekannt ist, steht als unbekannt da.
    """
    zeilen = []
    try:
        import jack_guthaben
        lage = jack_guthaben.lage(root)
        g, d, ab = lage['guthaben'], lage['deckel'], lage['abweisungen']
        zeilen = ['## Geld', '']
        zeilen.append(g['satz'])
        if d.get('erreicht'):
            zeilen.append(d['satz'] + ' Gespräch und Sprache bleiben frei.')
        elif (d.get('anteil') or 0) >= 0.8:
            zeilen.append(d['satz'])
        if ab.get('geld'):
            zeilen.append('%d Lauf/Läufe wurden wegen zu geringen Guthabens abgewiesen '
                          '(zuletzt %s).' % (ab['geld'], str(ab.get('geld_zuletzt'))[:16]))
        if ab.get('kontingent'):
            zeilen.append('Abo-Kontingent erschöpft: %d Abweisung(en), zuletzt %s.'
                          % (ab['kontingent'], str(ab.get('kontingent_zuletzt'))[:16]))
        zeilen.append('')
    except Exception:
        return []
    try:
        import jack_vertraege
        faellig = jack_vertraege.fristen(root)['faellig']
        if faellig:
            zeilen += ['### Fristen', '']
            for f in faellig:
                zeilen.append('- %s: %s, in %d Tagen (Kündigungsfrist %s)'
                              % (f.get('anbieter'), f.get('datum'), f.get('in_tagen'),
                                 f.get('frist')))
            zeilen.append('')
    except Exception:
        pass
    return zeilen


BRIEFING_STAND = 'morgenbriefing_stand.json'


def briefing_stand(root):
    """Block 6 E2: Steht das Morgenbriefing des heutigen Tages noch aus?

    Faellig ist es, wenn die Datei fuer heute existiert und der Patron sie
    weder gehoert noch als erledigt abgelegt hat. Sagt er "spaeter", wird beim
    naechsten Oeffnen erneut gefragt - deshalb wird "spaeter" nicht gemerkt.
    """
    at = now()
    pfad = area(root)/'tagesberichte'/f'{at.date()}_morgen.md'
    stand = {}
    p = area(root)/BRIEFING_STAND
    try:
        stand = json.loads(p.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        stand = {}
    heute = stand.get(str(at.date()), {})
    if not pfad.is_file():
        return {'faellig': False, 'grund': 'Für heute liegt noch kein Briefing.',
                'datum': str(at.date())}
    if heute.get('wahl') in ('gehoert', 'erledigt'):
        return {'faellig': False, 'grund': 'Heute schon erledigt.',
                'wahl': heute['wahl'], 'datum': str(at.date())}
    return {'faellig': True, 'datum': str(at.date()),
            'geschrieben': dt.datetime.fromtimestamp(pfad.stat().st_mtime).isoformat(),
            'text': pfad.read_text(encoding='utf-8'),
            'frage': 'Möchtest du dein Morgenbriefing hören?'}


def briefing_merken(root, wahl):
    """gehoert | spaeter | erledigt. 'spaeter' wird bewusst NICHT gemerkt."""
    if wahl not in ('gehoert', 'spaeter', 'erledigt'):
        raise ValueError('Unbekannte Wahl')
    at = now()
    p = area(root)/BRIEFING_STAND
    try:
        stand = json.loads(p.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        stand = {}
    if wahl == 'spaeter':
        return {'ok': True, 'wahl': wahl, 'faellig': True,
                'meldung': 'Beim nächsten Öffnen frage ich erneut.'}
    stand[str(at.date())] = {'wahl': wahl, 'zeit': at.isoformat()}
    jack_speicher.atomic_bytes(p, (json.dumps(stand, ensure_ascii=False, indent=1)+'\n').encode())
    return {'ok': True, 'wahl': wahl, 'faellig': False,
            'meldung': 'Gehört.' if wahl == 'gehoert' else 'Als erledigt abgelegt.'}


def _postfachteil(root):
    """Block 6 E3: Postfaecher im Briefing. Faellt etwas aus, bleibt es still."""
    try:
        import jack_postfaecher
        lage = jack_postfaecher.lage(root)
    except Exception:
        return []
    zeilen = ['## Postfächer', '',
              f"{lage['anzahl']} Postfächer, {lage['verbunden']} verbunden, "
              f"{lage['ungelesen']} ungelesen.", '']
    for marke in lage['marken']:
        neu = sum(p['ungelesen'] for p in marke['postfaecher'])
        fehler = [p for p in marke['postfaecher'] if p['ampel'] == 'rot']
        if neu or fehler:
            teil = f"- {marke['marke']}: {neu} ungelesen"
            if fehler:
                teil += f", {len(fehler)} mit Fehler"
            zeilen.append(teil)
    try:
        gestern = str((now() - dt.timedelta(days=1)).date())
        stufe3 = [r for r in records(area(root)/'postausgang.jsonl')
                  if str(r.get('zeit','')).startswith(gestern)]
        zeilen += ['', f"Gestern still gesendet (Stufe 3): {len(stufe3)}."]
    except Exception:
        pass
    return zeilen + ['']


def _kalenderteil(root):
    try:
        import jack_kalender
        k = jack_kalender.uebersicht(root)
    except Exception:
        return []
    return ['## Kalender', '', k['satz'], '']


def backup(root, at=None, anlass="manuell", quelle="manuell"):
    root = Path(root)
    at = at or now()
    target = root.parents[1] / '99_Archiv' / 'JACK_Sicherungen'
    target.mkdir(exist_ok=True)
    path = target / ('JACK_' + at.strftime('%Y-%m-%d_%H%M%S') + '_' + uuid.uuid4().hex[:8] + '.zip')
    manifest, excluded, directories = {}, [], []
    with zipfile.ZipFile(path, 'x', zipfile.ZIP_DEFLATED) as z:
        def dateien():
            # Nicht erst nach dem Besuch aussortieren: lokale Modelle und
            # Laufzeiten koennen hunderttausende Dateien enthalten.
            for folder, dirs, files in os.walk(root, followlinks=False):
                base = Path(folder)
                dirs[:] = sorted(d for d in dirs if d not in ('__pycache__', '.git')
                                  and not d.endswith('.nosync') and not (base/d).is_symlink())
                for name in sorted(dirs + files):
                    yield base/name
        for p in dateien():
            rel = p.relative_to(root)
            if p.is_symlink() or any(x in ('__pycache__','.git','.DS_Store') or x.endswith('.nosync') for x in rel.parts):
                continue
            if p.is_dir():
                directories.append(str(rel)); continue
            if not p.is_file():
                continue
            if p.name.lower().startswith('.env') or p.name.lower() == 'schluessel.txt' or p.suffix in ('.pem','.key','.p12'):
                excluded.append(str(rel)); continue
            data = p.read_bytes()
            manifest[str(rel)] = hashlib.sha256(data).hexdigest()
            z.writestr(str(rel), data)
        original_configs = {}
        live_root = Path.home()/'Library/Mobile Documents/com~apple~CloudDocs/GOTT WALD HOLDING/07_Projekte/JACK'
        if root.resolve() == live_root.resolve():
            for label in ('world.gottwald.jack.arbeiter','world.gottwald.jack.server'):
                config=Path.home()/'Library/LaunchAgents'/(label+'.plist')
                if config.is_file() and not config.is_symlink():
                    name='STARTKONFIGURATION/'+config.name;data=config.read_bytes()
                    manifest[name]=hashlib.sha256(data).hexdigest();z.writestr(name,data)
                    original_configs[name]=str(config)
            entry = Path('/Applications/JACK.app/Contents/MacOS/JACK')
            if entry.is_file() and not entry.is_symlink():
                name='STARTKONFIGURATION/JACK.app/Contents/MacOS/JACK';data=entry.read_bytes()
                manifest[name]=hashlib.sha256(data).hexdigest();z.writestr(name,data)
                original_configs[name]=str(entry)
        z.writestr('SICHERUNG_MANIFEST.json', json.dumps({'zeit':at.isoformat(),'dateien':manifest,'ordner':directories,'nicht_enthalten':excluded,'startkonfiguration_original':original_configs}, ensure_ascii=False, indent=2))
    verified = verify_backup(path)
    record = {'zeit':at.isoformat(),'anlass':anlass,'quelle':quelle,'datei':str(path),'dateien':len(manifest),'hashes_geprueft':verified,'nicht_enthalten':excluded}
    append(area(root)/'sicherungen.jsonl',record)
    return record


def verify_backup(path, restore_to=None):
    with zipfile.ZipFile(path) as z:
        if z.testzip() is not None:
            raise ValueError('Sicherung beschädigt')
        manifest = json.loads(z.read('SICHERUNG_MANIFEST.json'))
        names = z.namelist()
        if len(names) != len(set(names)) or set(names) != set(manifest['dateien']) | {'SICHERUNG_MANIFEST.json'}:
            raise ValueError('Archivinhalt stimmt nicht mit Manifest überein')
        if restore_to:
            destination = Path(restore_to)
            if destination.is_symlink() or any(p.is_symlink() for p in destination.parents):
                raise ValueError('Wiederherstellungsziel enthält einen Verweis')
            if destination.exists() and any(destination.iterdir()):
                raise ValueError('Wiederherstellungsziel muss leer sein')
        for directory in manifest.get('ordner', []):
            rel = Path(directory)
            if rel.is_absolute() or '..' in rel.parts:
                raise ValueError('Unsicherer Archivordner')
            if restore_to:
                (Path(restore_to)/rel).mkdir(parents=True,exist_ok=True)
        for name, expected in manifest['dateien'].items():
            rel = Path(name)
            if rel.is_absolute() or '..' in rel.parts:
                raise ValueError('Unsicherer Archivpfad')
            data = z.read(name)
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError('Dateiprüfsumme stimmt nicht')
            if restore_to:
                target = Path(restore_to)/rel
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('xb') as f:
                    f.write(data)
    return True


def tick(root, at=None):
    echt = at is None
    at = at or now()
    folder = area(root)/'tagesberichte'; folder.mkdir(exist_ok=True)
    generated = []
    # Zuerst die Tagesberichte: sie sind zeitgebunden (08:00 und 18:00) und
    # duerfen nicht hinter dem Vault-Aufbau warten.
    for hour, kind in ((8,'morgen'),(18,'abend')):
        path = folder / f'{at.date()}_{kind}.md'
        if at.hour >= hour and not path.exists():
            report = brief(root,kind,at)
            try:
                with path.open('x') as f: f.write(report['text'])
                generated.append(str(path))
            except FileExistsError:
                pass
    import jack_gehirn
    generated.extend(jack_gehirn.daily(root, at))
    import jack_erweiterungen
    generated.extend(jack_erweiterungen.observe(root, None if echt else at))
    import jack_recherche
    generated.extend(jack_recherche.tick(root, None if echt else at))
    # Block 6: Postfaecher und Kalender haengen in DIESER Routine - kein
    # zweiter Zeitgeber. Ein Fehler dort darf die Routine nie anhalten.
    # Block 8: Der Kostenwaechter haengt in DERSELBEN Routine - kein zweiter
    # Zeitgeber. Monatsbericht am 1. um 08:00, Fristen einmal am Tag.
    # Block 18: Die Gedaechtnis-Bereinigung haengt in DERSELBEN Routine - kein
    # zweiter Zeitgeber. Sie laeuft hoechstens woechentlich und bereinigt nie
    # von sich aus, wenn der Patron entscheiden muss.
    # Block 19: Der Monatsbericht der Funktions-Disziplin haengt ebenfalls hier -
    # er laeuft nur am Ersten und legt einen Vorschlag ab, nichts weiter.
    # Block 21: Der Mitarbeiter-Waechter haengt in DERSELBEN Routine. Er meldet
    # nur (keine offene Aufgabe, Zahltag, Vertrag offen) und handelt nie selbst.
    # Block 26: Kartenwaechter (Karten-Hygiene), Autonomie-Quote und der
    # woechentliche Bremsen-Bericht haengen ebenfalls in DERSELBEN Routine -
    # kein eigener Zeitgeber. jack_regeln bewegt nur Karten (nie senden/
    # loeschen/zahlen), jack_bremsen schreibt hoechstens einmal je Woche.
    for baustein in ('jack_postfaecher', 'jack_kalender', 'jack_vertraege',
                     'jack_gedaechtnis', 'jack_nutzung', 'jack_mitarbeiter',
                     'jack_regeln', 'jack_autonomie', 'jack_bremsen', 'jack_obsidian'):   # F-26: JACK-Spiegel (nur Links)
        try:
            generated.extend(__import__(baustein).tick(root, None if echt else at) or [])
        except Exception:
            pass
    # Nachtlauf durch den bereits aktiven Fünf-Minuten-Arbeiter.
    if at.hour < 6 and not any(r.get('zeit','').startswith(str(at.date())) and r.get('anlass')=='nachtlauf' for r in records(area(root)/'sicherungen.jsonl')):
        generated.append(backup(root,at,anlass='nachtlauf',quelle='timer' if echt else 'simulation')['datei'])
    return generated


def draft_path(root, title, suffix):
    folder=area(root)/'entwuerfe';folder.mkdir(exist_ok=True)
    slug=re.sub(r'[^a-zA-Z0-9_-]','-',title).strip('-')[:60] or 'entwurf'
    return folder/(now().strftime('%Y-%m-%d_%H%M%S')+'_'+slug+'_'+uuid.uuid4().hex[:6]+suffix)


def email_draft(root, recipient, subject, body):
    if not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+',recipient) or any(c in subject for c in '\r\n'):
        raise ValueError('Ungültiger Empfänger oder Betreff')
    msg=EmailMessage(policy=policy.SMTP)
    msg['To']=recipient;msg['Subject']=subject;msg['X-Unsent']='1';msg.set_content(body)
    p=draft_path(root,subject,'.eml');p.write_bytes(msg.as_bytes())
    return str(p)


def calendar_draft(root,title,start,end,description=''):
    begin=dt.datetime.fromisoformat(start);finish=dt.datetime.fromisoformat(end)
    if begin.tzinfo is None or finish.tzinfo is None or finish<=begin:
        raise ValueError('Beginn und Ende brauchen Zeitzone; Ende muss später liegen')
    def escape(s):return s.replace('\\','\\\\').replace('\r','').replace('\n','\\n').replace(';','\\;').replace(',','\\,')
    def stamp(d):return d.astimezone(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    lines=['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//GOTT WALD//JACK//DE','BEGIN:VEVENT',
           'UID:'+uuid.uuid4().hex+'@jack.local','DTSTAMP:'+stamp(now()),'DTSTART:'+stamp(begin),'DTEND:'+stamp(finish),
           'SUMMARY:'+escape(title),'DESCRIPTION:'+escape(description),'STATUS:TENTATIVE','END:VEVENT','END:VCALENDAR']
    folded=[]
    for line in lines:
        current=''
        for char in line:
            if len((current+char).encode())>73:
                folded.append(current);current=' '
            current+=char
        folded.append(current)
    p=draft_path(root,title,'.ics');p.write_bytes(('\r\n'.join(folded)+'\r\n').encode())
    return str(p)


def kontingent(root):
    path=Path(root)/'arbeiter_pausen.jsonl'
    if not path.exists():return {'status':'bereit','bis':None}
    rows=records(path)
    try:
        until=dt.datetime.fromisoformat(rows[-1]['bis'])
        if until.tzinfo is None:raise ValueError('Zeitzone fehlt')
    except (ValueError,KeyError,IndexError,TypeError):
        return {'status':'Pausenprotokoll prüfen','bis':None}
    return {'status':'Kontingentpause' if until>now() else 'bereit','bis':until.isoformat() if until>now() else None}


def status(root):
    rows=jack_speicher.iter_records(area(root)/'gespraeche.jsonl')
    backups=records(area(root)/'sicherungen.jsonl',limit=1)
    return {'arbeiter':kontingent(root),'gespeicherte_gespraechspaare':sum(r.get('typ')=='dialog' for r in rows),
            'letzte_sicherung':backups[-1] if backups else None,
            'tagesberichte':sorted(p.name for p in (area(root)/'tagesberichte').glob('*.md'))[-4:],
            'entwuerfe':sorted(p.name for p in (area(root)/'entwuerfe').glob('*') if p.is_file() and not p.is_symlink())[-10:],
            'mail':'Lokale Entwürfe; Konto nicht verbunden','kalender':'Lokale Terminentwürfe; Konto nicht verbunden',
            'handy':'Oberfläche mobil; Fernzugriff noch nicht eingerichtet'}
