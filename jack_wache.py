"""Lokale Betriebspruefung. Beobachtet; startet keine Modelle oder Auftraege."""
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
import jack_betrieb as b

INTERVALL = 60
FRISCHE = 180
DAUER_STUNDEN = 72
_STARTED = None
# Block 7b (H3): Die Weiterleitung wird bei Bedarf selbst neu gesetzt.
# snapshot() laeuft auch bei jedem Abruf der Betriebspruefung - ohne diese
# Sperre wuerde jeder Seitenaufruf einen Setzversuch ausloesen.
SERVE_SPERRE = 120
_SERVE_VERSUCH = 0.0


def stamp(value):
    result = dt.datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError('Zeit ohne Zeitzone')
    return result


def read_json(path, default):
    if not path.exists():
        return default
    if path.is_symlink():
        raise ValueError('Verweis statt Betriebsdatei')
    return json.loads(path.read_text())


def atomic(path, data):
    if path.is_symlink():
        raise ValueError('Verweis statt Betriebsdatei')
    temp = path.with_name(path.name + '.' + str(os.getpid()) + '.tmp')
    with temp.open('w') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


def tail(path, size=65536):
    if not path.exists() or path.is_symlink():
        return ''
    with path.open('rb') as f:
        f.seek(max(0, path.stat().st_size-size))
        return f.read().decode('utf-8', errors='replace')


def host_state(root):
    def command(args):
        result = subprocess.run(args, capture_output=True, text=True, timeout=5)
        return result.returncode, result.stdout
    boot = command(['/usr/sbin/sysctl', '-n', 'kern.boottime'])[1]
    match = re.search(r'sec = (\d+)', boot)
    _, worker = command(['/bin/launchctl', 'print', f'gui/{os.getuid()}/world.gottwald.jack.arbeiter'])
    _, server = command(['/bin/launchctl', 'print', f'gui/{os.getuid()}/world.gottwald.jack.server'])
    code = re.search(r'last exit code = (-?\d+)', worker)
    busy = False
    with (root/'arbeiter.sh').open() as f:
        try:
            fcntl.flock(f, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            busy = True
    starts = re.findall(r'^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\s+ARBEITER-LAUF', tail(root/'arbeiter_launchd.log'), re.M)
    server_pid = re.search(r'^\s*pid = (\d+)\s*$', server, re.M)
    return {'boot': int(match[1]) if match else None, 'server_pid': int(server_pid[1]) if server_pid else None,
            'server_geladen': 'state = running' in server,
            'arbeiter_geladen': 'type = LaunchAgent' in worker,
            'arbeiter_exit': int(code[1]) if code else None,
            'arbeiter_aktiv': busy,
            'arbeiter_letzter_start': dt.datetime.strptime(starts[-1], '%Y-%m-%d %H:%M:%S').replace(tzinfo=b.ZONE).isoformat() if starts else None}


def gleicher_nachweispfad(recorded, current):
    try:
        path=Path(recorded)
        return path.is_absolute() and path.resolve(strict=True)==Path(current).resolve(strict=True)
    except (OSError,ValueError,TypeError):
        return False


def next_slot(at, hour):
    result=at.replace(hour=hour, minute=0, second=0, microsecond=0)
    return result if result>at else result+dt.timedelta(days=1)


def goal(label, status, detail, when=None):
    return {'name':label,'status':status,'detail':detail,'belegt_um':when}


def verify_archive(root, record, cache):
    if not record:
        return {'status':'fehlt','detail':'Noch keine Sicherung erfasst'}, cache
    try:
        path=Path(record['datei'])
        allowed=root.parents[1]/'99_Archiv/JACK_Sicherungen'
        if path.is_symlink() or path.resolve().parent!=allowed.resolve():
            raise ValueError('Archivpfad ist nicht in JACK_Sicherungen')
        st=path.stat()
        signature=[str(path),st.st_size,st.st_mtime_ns]
        if cache.get('signatur')!=signature:
            b.verify_backup(path)
            cache={'signatur':signature,'hashes_geprueft':True,'zeit':b.now().isoformat()}
        return {'status':'bestanden','detail':f"{record.get('dateien','?')} Dateien; Archiv und Prüfsummen lesbar",'zeit':record.get('zeit'),'datei':str(path),'erneut_geprueft_um':cache['zeit']},cache
    except Exception as error:
        return {'status':'fehler','detail':b.redact(str(error))[:240],'datei':record.get('datei')},{}


def serve_protokoll(root, art, ergebnis, einzelheit=''):
    """Jeder Eingriff am Handy-Weg steht im selben Protokoll wie jeder Zugriff."""
    try:
        b.append(b.area(root)/'zugriffe_handy.jsonl',
                 {'zeit': b.now().isoformat(), 'art': art, 'login': '(betriebspruefung)',
                  'pfad': 'serve --bg 8778', 'entscheidung': ergebnis,
                  'einzelheit': str(einzelheit)[:300]})
    except Exception:
        pass


def serve_neu_setzen(root, pfad):
    """H3: Fehlt die Weiterleitung, wird sie neu gesetzt - nicht nur gemeldet.

    Es wird ausschliesslich `serve` verwendet, nie `funnel`: serve bleibt im
    privaten Tailnet, funnel waere oeffentlich und ist verboten. Die Sperre
    verhindert, dass ein haeufiger Abruf der Betriebspruefung den Befehl
    wiederholt ausloest.
    """
    global _SERVE_VERSUCH
    jetzt = time.time()
    if jetzt - _SERVE_VERSUCH < SERVE_SPERRE:
        return False, 'Wartezeit nach dem letzten Versuch läuft noch'
    _SERVE_VERSUCH = jetzt
    try:
        lauf = subprocess.run([pfad, 'serve', '--bg', '8778'],
                              capture_output=True, text=True, timeout=25)
    except Exception as fehler:
        serve_protokoll(root, 'serve_neu_gesetzt', 'fehlgeschlagen', fehler)
        return False, 'Befehl nicht ausführbar'
    try:
        nach = subprocess.run([pfad, 'serve', 'status'],
                              capture_output=True, text=True, timeout=10)
        steht = '8778' in nach.stdout and 'https://' in nach.stdout
    except Exception:
        steht = False
    if steht:
        serve_protokoll(root, 'serve_neu_gesetzt', 'gesetzt')
        return True, ''
    zeilen = (lauf.stderr or lauf.stdout or '').strip().splitlines()
    grund = zeilen[0][:160] if zeilen else 'ohne Rückmeldung'
    serve_protokoll(root, 'serve_neu_gesetzt', 'fehlgeschlagen', grund)
    return False, grund


def observe(root, at=None, host=None):
    root=Path(root)
    real=at is None and host is None
    at=at or b.now()
    h=host if host is not None else host_state(root)
    area=b.area(root)
    baseline_path=area/'beobachtung_beginn.json'
    previous=read_json(area/'beobachtung_stand.json',{})
    config=read_json(baseline_path,{})
    if not config:
        config={'aktiv_seit':at.isoformat(),'erster_boot':h.get('boot'), 'quelle':'echter_lauf' if real else 'simulation',
                'erste_faelligkeit':{k:next_slot(at,hour).isoformat() for k,hour in [('nacht',0),('morgen',8),('abend',18)]},
                'log_ab_zeile':len(tail(root/'arbeiter.log').splitlines())}
        atomic(baseline_path,config)
    baseline=stamp(config['aktiv_seit'])
    checks=[]
    def add(name,status,detail):checks.append({'name':name,'status':status,'detail':detail})
    add('JACK-Dienst','ok' if h.get('server_geladen') else 'fehler','Läuft unter dem Benutzer-Startdienst' if h.get('server_geladen') else 'Startdienst nicht als laufend nachgewiesen')
    add('Arbeiter-Timer','ok' if h.get('arbeiter_geladen') and h.get('arbeiter_exit') in (None,0) else 'fehler',
        'Letzter Start endete mit Fehlercode '+str(h['arbeiter_exit']) if h.get('arbeiter_exit') not in (None,0) else 'Geladen; Arbeit aktiv' if h.get('arbeiter_aktiv') else 'Geladen, wartet auf nächsten Lauf' if h.get('arbeiter_geladen') else 'Timer fehlt')
    routines=b.records(area/'routinen.jsonl',limit=5000)
    latest=routines[-1] if routines else None
    if latest:
        age=(at-stamp(latest['ende'])).total_seconds()
        status='fehler' if latest.get('status')!='ok' else 'warnung' if age>900 and not h.get('arbeiter_aktiv') else 'ok'
        add('Tagesroutine',status,('Zuletzt erfolgreich: '+latest['ende']) if latest.get('status')=='ok' else 'Letzter Lauf fehlgeschlagen; Routinenprotokoll prüfen')
    else:
        add('Tagesroutine','wartet' if (at-baseline).total_seconds()<900 else 'warnung','Erster protokollierter Routinenlauf steht aus')
    last_start=h.get('arbeiter_letzter_start')
    if last_start:
        age=(at-stamp(last_start)).total_seconds()
        if age>900 and not h.get('arbeiter_aktiv'):
            add('Timer-Lebenszeichen','warnung','Seit über 15 Minuten kein Start beobachtet')
    queues={g:list((root/'auftraege'/g).glob('*.md')) for g in ('offen','laeuft','freigabe')}
    running=[]
    for path in queues['laeuft']:
        if path.is_symlink() or path.name.lower().startswith('readme'):continue
        age=max(0,(at.timestamp()-path.stat().st_mtime))
        running.append(path.name)
        if not h.get('arbeiter_aktiv') or age>1800:
            add('Auftrag prüfen','warnung',path.name+' — kein aktiver Arbeiter oder seit 30 Minuten unverändert; keine automatische Wiederholung')
    for path in queues['offen']:
        if path.is_symlink():continue
        match=re.search(r'^versuch:\s*(\d+)',path.read_text(),re.M)
        if match and int(match[1])>=2:add('Versuche verbraucht','warnung',path.name+' — zwei Fehlversuche, Prüfung nötig')
    if queues['freigabe']:add('Entscheidung nötig','hinweis',str(len(queues['freigabe']))+' Auftrag/Aufträge warten auf Freigabe')
    backups=b.records(area/'sicherungen.jsonl',limit=1500)
    archive,cache=verify_archive(root,backups[-1] if backups else None,previous.get('archiv_cache',{}))
    add('Sicherung','ok' if archive['status']=='bestanden' else 'fehler',archive['detail'])
    # Block 17 (Auftrag 2.2): Alle Anbindungen mit Status ok/warnung/fehler und
    # dem Zeitpunkt der letzten erfolgreichen Verbindung. Kein Modellaufruf,
    # nichts gesendet; teure (Netz-)Pruefungen hoechstens alle 15 Minuten.
    #
    # Bewusst NICHT in `checks`: eine getrennte Fremdquelle ist kein Fehler des
    # JACK-Betriebs. Stuende sie in `checks`, wuerde jede Stoerung die
    # 72-Stunden-Dauerbeobachtung zuruecksetzen - der Gmail-Fehlerstand allein
    # wuerde die Abnahme dauerhaft blockieren. Die Anbindungen erscheinen
    # deshalb als eigener Abschnitt der Wache (state['verbindungen']) und in
    # der Vollansicht "Verbindungen".
    verbindungen = {'anzahl': 0, 'ok': 0, 'fehler': 0, 'warnung': 0,
                    'status': 'wartet', 'kurz': 'nicht prüfbar', 'quellen': []}
    try:
        import jack_verbindungen
        verbindungen = jack_verbindungen.pruefen(root, at=at)
    except Exception as fehler:
        verbindungen['detail'] = b.redact(str(fehler))[:240]
    # Block 7 (H3): Fehlt allein die Weiterleitung auf 8778, setzt die Wache sie
    # selbst - Melden allein hat dem Patron nichts genuetzt. Der Zustand kommt
    # aus derselben Pruefung wie oben; Tailscale wird nicht zweimal befragt.
    try:
        tail_quelle = next((q for q in verbindungen.get('quellen', [])
                            if q.get('schluessel') == 'tailscale'), None)
        if tail_quelle and tail_quelle.get('status') == 'warnung' \
                and 'Weiterleitung' in str(tail_quelle.get('detail', '')):
            pfad = '/Applications/Tailscale.app/Contents/MacOS/Tailscale'
            gesetzt, grund = serve_neu_setzen(root, pfad)
            if gesetzt:
                add('Handy-Zugang (Tailscale)', 'ok',
                    'Weiterleitung fehlte und wurde neu gesetzt')
            else:
                add('Handy-Zugang (Tailscale)', 'warnung',
                    'Weiterleitung fehlt; automatisches Setzen hat nicht gegriffen: ' + grund)
    except Exception:
        pass
    if archive.get('zeit') and (at-stamp(archive['zeit'])).total_seconds()>36*3600:
        add('Alter der Sicherung','warnung','Die letzte erfolgreiche Sicherung ist älter als 36 Stunden')
    # Ein Plan oder eine manuelle Sicherung beweist keinen automatischen Nachtlauf.
    accept={}
    for kind,hour in [('nacht',0),('morgen',8),('abend',18)]:
        label={'nacht':'Automatischer Nachtlauf','morgen':'Morgenbriefing','abend':'Abendabschluss'}[kind]
        first=stamp(config['erste_faelligkeit'][kind])
        day=at.replace(hour=hour,minute=0,second=0,microsecond=0)
        if day>at:day-=dt.timedelta(days=1)
        expected=max(first,day)
        deadline=expected+dt.timedelta(hours=6,minutes=10) if kind=='nacht' else expected+dt.timedelta(minutes=10)
        evidence=None
        if kind=='nacht':
            for row in backups:
                when=stamp(row['zeit'])
                if row.get('anlass')=='nachtlauf' and row.get('quelle')=='timer' and expected<=when<=deadline:
                    check=archive if row.get('datei')==archive.get('datei') else verify_archive(root,row,{})[0]
                    if check['status']=='bestanden':evidence=row
        else:
            path=area/'tagesberichte'/f'{expected.date()}_{kind}.md'
            if path.is_file() and not path.is_symlink():
                match=re.search(r'^Stand: (.+)$',path.read_text(),re.M)
                for row in routines:
                    if row.get('quelle')!='timer' or row.get('status')!='ok':continue
                    if any(gleicher_nachweispfad(recorded,path) for recorded in row.get('neue_dateien',[])) and match:
                        created=stamp(match[1]);completed=stamp(row['ende'])
                        if expected<=created<=completed<=deadline:evidence={'zeit':completed.isoformat(),'datei':str(path)}
        if evidence:
            accept[kind]=goal(label,'bestanden','Tatsächlicher automatischer Lauf belegt: '+evidence['datei'],evidence['zeit'])
        elif at>deadline:
            accept[kind]=goal(label,'überfällig','Kein pünktlicher automatischer Nachweis für '+str(expected.date()))
            add(label,'warnung',accept[kind]['detail'])
        else:
            accept[kind]=goal(label,'wartet','Nächster Nachweis ab '+expected.isoformat())
    starts=[r for r in b.records(area/'appstarts.jsonl',limit=2000)
            if r.get('quelle')=='echter_lauf' and baseline < stamp(r['zeit']) <= at]
    last=starts[-1] if starts else None
    failed=last and last.get('ergebnis')!='ok'
    confirmed=last and last.get('fenster_nachweis')=='JACK-Seite' and not failed
    equal=confirmed and type(last.get('pid_vorher')) is int and last['pid_vorher']>0 and last['pid_vorher']==last.get('pid_nachher')
    changed=last and type(last.get('pid_nachher')) is int and last.get('pid_vorher')!=last['pid_nachher']
    accept['app']=goal('App-Start ohne Dienstwechsel','bestanden' if equal else 'warnung' if changed or failed else 'wartet',
                      'JACK-Seite und gleiche Dienstkennung protokolliert' if equal else
                      'Letzter App-Start fehlgeschlagen; Startprotokoll prüfen' if failed else
                      'Dienstkennung beim App-Start geändert; Startprotokoll prüfen' if changed else
                      'Noch kein erfolgreicher Fensterstart mit gleicher Dienstkennung belegt',last['zeit'] if equal else None)
    prior_host=previous.get('host',{})
    service_restarts=previous.get('dienst_neustarts',[])
    if prior_host.get('server_pid') and h.get('server_pid') and h.get('server_geladen') and prior_host['server_pid']!=h['server_pid']:
        service_restarts=(service_restarts+[{'zeit':at.isoformat(),'vorher':prior_host['server_pid'],'nachher':h.get('server_pid'),'gleicher_mac_start':prior_host.get('boot')==h.get('boot')}])[-20:]
    accept['dienst']=goal('JACK-Dienstwiederanlauf','bestanden' if service_restarts else 'wartet',
                         'Neue Dienstkennung tatsächlich beobachtet' if service_restarts else 'Noch kein neuer Dienststart seit Beginn beobachtet',service_restarts[-1]['zeit'] if service_restarts else None)
    boot_changed=h.get('boot') and config.get('erster_boot') and h['boot']!=config['erster_boot']
    reboot_ok=bool(boot_changed and h.get('arbeiter_geladen') and latest and latest.get('status')=='ok' and latest.get('quelle')=='timer' and stamp(latest['ende']).timestamp()>h['boot'])
    accept['mac']=goal('Mac-Neustart','bestanden' if reboot_ok else 'wartet','Neue Mac-Startzeit und danach Tagesroutine belegt' if reboot_ok else 'Kein vollständiger Mac-Neustart seit Beginn nachgewiesen',at.isoformat() if reboot_ok else None)
    gaps=previous.get('messluecken',0)
    continuous=previous.get('beobachtet_seit',at.isoformat())
    gap=previous.get('zeit') and (at-stamp(previous['zeit'])).total_seconds()>FRISCHE
    if gap or any(x['status'] in ('fehler','warnung') for x in checks):
        continuous=at.isoformat()
        if gap:gaps+=1
    # Historische Tests vor Beginn nicht zu neuen Betriebsfehlern umdeuten.
    errors=[]
    for line in tail(root/'arbeiter.log').splitlines():
        match=re.match(r'^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\s+(.*)',line)
        if not match:continue
        when=dt.datetime.strptime(match[1],'%Y-%m-%d %H:%M:%S').replace(tzinfo=b.ZONE)
        if when<baseline:continue
        if re.match(r'(PROBLEM:|ABGEBROCHEN|ABBRUCH GESICHERT|ABNAHME FEHLGESCHLAGEN|KAPUTTER|UNGUELTIG|KONNTE NICHT)',match[2]):
            errors.append({'zeit':when.isoformat(),'text':b.redact(match[2])[:400]})
    errors=errors[-10:]
    old_errors=previous.get('fehler_seit_beginn',[])
    if any(row not in old_errors for row in errors):
        add('Neuer Betriebsfehler','warnung','Neuen Eintrag im Fehlerprotokoll prüfen; Dauerbeobachtung beginnt erneut')
        continuous=at.isoformat()
    hours=max(0,(at-stamp(continuous)).total_seconds()/3600)
    accept['dauer']=goal('72 Stunden Betriebsbeobachtung','bestanden' if hours>=DAUER_STUNDEN else 'beobachtung',f'{hours:.2f} von 72 Stunden ohne Warnung und ohne Prüflücke über drei Minuten; {gaps} Messlücke(n). Unbeobachtete Zeiträume sind nicht abgenommen.')
    severity='fehler' if any(x['status']=='fehler' for x in checks) else 'warnung' if any(x['status']=='warnung' for x in checks) else 'ok'
    state={'zeit':at.isoformat(),'aktiv_seit':config['aktiv_seit'],'quelle':'echter_lauf' if real else 'simulation','status':severity,'pruefungen':checks,
           'abnahmen':accept,'verbindungen':verbindungen,'letzte_sicherung':archive,'archiv_cache':cache,'host':h,'dienst_neustarts':service_restarts,
           'beobachtet_seit':continuous,'beobachtete_stunden':round(hours,3),'messluecken':gaps,'fehler_seit_beginn':errors[-10:],'laufende_auftraege':running}
    changes=[]
    for name,current in accept.items():
        before=previous.get('abnahmen',{}).get(name,{}).get('status')
        if current['status']!=before:changes.append({'art':'abnahme','punkt':name,'vorher':before,'nachher':current['status']})
    old_sign={(x['name'],x['status'],x['detail']) for x in previous.get('pruefungen',[]) if x['status'] in ('fehler','warnung')}
    new_sign={(x['name'],x['status'],x['detail']) for x in checks if x['status'] in ('fehler','warnung')}
    if old_sign!=new_sign:changes.append({'art':'hinweise','vorher':sorted(old_sign),'nachher':sorted(new_sign)})
    if errors!=previous.get('fehler_seit_beginn',[]):changes.append({'art':'fehlerprotokoll','eintraege':errors[-10:]})
    if changes:b.append(area/'beobachtung_ereignisse.jsonl',{'zeit':at.isoformat(),'aenderungen':changes})
    b.append(area/'beobachtung_verlauf.jsonl',{'zeit':at.isoformat(),'status':severity,'server_pid':h.get('server_pid'),'boot':h.get('boot'),'stunden':state['beobachtete_stunden']})
    atomic(area/'beobachtung_stand.json',state)
    return state


def snapshot(root):
    try:
        state=read_json(b.area(root)/'beobachtung_stand.json',{})
        if not state:
            failed=b.records(b.area(root)/'beobachtung_fehler.jsonl')
            if failed or (_STARTED and time.monotonic()-_STARTED>FRISCHE):
                return {'status':'fehler','text':'Die Betriebsprüfung konnte nicht abgeschlossen werden. Fehlerprotokoll prüfen.'}
            return {'status':'wartet','text':'Die erste Betriebsprüfung steht aus.'}
        state.pop('archiv_cache',None)
        if (b.now()-stamp(state['zeit'])).total_seconds()>FRISCHE:
            state['status']='veraltet'
        failed=b.records(b.area(root)/'beobachtung_fehler.jsonl')
        if failed and stamp(failed[-1]['zeit'])>stamp(state['zeit']):
            state['status']='fehler'
            state['pruefungen'].append({'name':'Überwachung','status':'fehler','detail':'Letzter Prüflauf fehlgeschlagen: '+failed[-1]['fehler']})
        state['text']=render(state)
        return state
    except Exception:
        return {'status':'fehler','text':'Betriebsprüfung nicht lesbar. Keine aktuelle Abnahme möglich.'}


def render(state):
    words={'ok':'Betriebsprüfung aktuell','warnung':'Betrieb prüfen','fehler':'Betriebsfehler','veraltet':'Betriebsprüfung veraltet'}
    def local(value):
        try:return stamp(value).astimezone(b.ZONE).strftime('%d.%m.%Y, %H:%M Uhr')
        except (ValueError,TypeError):return 'noch offen'
    labels={'ok':'in Ordnung','warnung':'prüfen','fehler':'Fehler','wartet':'steht aus','bestanden':'bestanden','überfällig':'überfällig','beobachtung':'läuft'}
    lines=[words.get(state.get('status'),'Betriebsprüfung'), 'Geprüft: '+local(state.get('zeit')),'']
    for x in state.get('pruefungen',[]):
        detail=x['detail']
        if detail.startswith('Zuletzt erfolgreich: '):detail='Zuletzt erfolgreich am '+local(detail.split(': ',1)[1])
        lines.append(x['name']+': '+labels.get(x['status'],x['status'])+' — '+detail)
    lines += ['', 'Noch offene und bestandene Prüfungen:']
    for x in state.get('abnahmen',{}).values():
        detail=x['detail']
        if detail.startswith('Nächster Nachweis ab '):detail='Nächster Nachweis ab '+local(detail[len('Nächster Nachweis ab '):])
        if x.get('belegt_um'):detail='Belegt am '+local(x['belegt_um'])
        lines.append(x['name']+': '+labels.get(x['status'],x['status'])+' — '+detail)
    # Block 17: die Anbindungen mit Status und letzter erfolgreicher Verbindung.
    v=state.get('verbindungen') or {}
    if v.get('quellen'):
        lines+=['','Anbindungen ('+str(v.get('kurz') or '')+'):']
        for q in v['quellen']:
            erfolg='zuletzt erreichbar '+local(q['letzter_erfolg']) if q.get('letzter_erfolg') else 'noch nie erreichbar'
            lines.append(q.get('name','?')+': '+labels.get(q.get('status'),str(q.get('status')))+
                         ' — '+str(q.get('detail',''))+' ('+erfolg+')')
    errors=state.get('fehler_seit_beginn',[])
    if errors:lines+=['','Aufgetretene Fehler seit Beginn:']+[local(x['zeit'])+' — '+x['text'] for x in errors]
    return '\n'.join(lines)


def loop(root):
    while True:
        try:observe(root)
        except Exception as error:
            b.append(b.area(root)/'beobachtung_fehler.jsonl',{'zeit':b.now().isoformat(),'fehler':b.redact(str(error))[:300]})
        time.sleep(INTERVALL)


def start(root):
    global _STARTED
    _STARTED=time.monotonic()
    thread=threading.Thread(target=loop,args=(Path(root),),name='JACK-Betriebspruefung',daemon=True)
    thread.start()
    return thread
