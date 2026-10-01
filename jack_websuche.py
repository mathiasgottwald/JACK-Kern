"""Begrenzte öffentliche Websuche: zehn Abrufe/Tag, acht Stunden Wiederverwendung."""
from contextlib import contextmanager
from pathlib import Path
import datetime as dt
import fcntl,hashlib,ipaddress,json,re,subprocess,time
from urllib.parse import urlsplit
from jack_erweiterungen import path,now,read_json,write_json
from jack_speicher import atomic_bytes
VERSION='1.0.0'
REVISION='d4ce87c23431f607162fc5c39ce52c538d64588f'
RUNTIME=Path.home()/'Library/Application Support/JACK/werkzeuge/searxng-d4ce87c23'

def digest(data):return hashlib.sha256(data).hexdigest()

@contextmanager
def locked(root):
 folder=path(root,'betrieb/websuche');folder.mkdir(parents=True,exist_ok=True)
 with path(root,'betrieb/websuche/suche.lock').open('a+b') as f:
  try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:raise ValueError('Eine Websuche läuft bereits.')
  try:yield
  finally:fcntl.flock(f,fcntl.LOCK_UN)

def public_url(url):
 try:
  parsed=urlsplit(url);host=parsed.hostname or ''
  if parsed.scheme!='https' or parsed.username or parsed.password or parsed.port not in (None,443) or '.' not in host or host.endswith(('.local','.localhost')):return False
  try:return ipaddress.ip_address(host).is_global
  except ValueError:return not host.endswith('.internal')
 except ValueError:return False

def sanitize(data):
 if not isinstance(data,dict) or not isinstance(data.get('treffer'),list) or len(data['treffer'])>10 or not isinstance(data.get('fehler'),list):raise ValueError('Ungültige Antwort der Websuche')
 results=[]
 for item in data['treffer']:
  if not isinstance(item,dict) or not all(isinstance(item.get(k),str) for k in ['titel','url','text']):raise ValueError('Ungültiger Suchtreffer')
  if not public_url(item['url']):continue
  engines=item.get('engines');
  if not isinstance(engines,list) or not engines or any(x not in ['brave','duckduckgo'] for x in engines):raise ValueError('Nicht freigegebener Suchanbieter')
  results.append({'titel':item['titel'][:500],'url':item['url'][:2000],'text':item['text'][:1500],'engines':sorted(engines)})
 return {'treffer':results,'fehler':data['fehler'][:10]}

def invoke(runner,query):
 result=subprocess.run([str(RUNTIME/'python/bin/python'),'-I','-c',runner.read_text(),str(RUNTIME)],input=json.dumps({'query':query}),text=True,capture_output=True,timeout=25,env={'PATH':'/usr/bin:/bin','LANG':'de_AT.UTF-8','LC_ALL':'de_AT.UTF-8','TMPDIR':'/tmp'},cwd=str(RUNTIME))
 if result.returncode!=0:raise ValueError('Lokaler Suchlauf fehlgeschlagen; kein automatischer Ersatzanbieter.')
 if len(result.stdout)>100000:raise ValueError('Suchantwort zu groß')
 return sanitize(json.loads(result.stdout))

def markdown(record):
 lines=['# JACK — öffentliche Websuche','', 'Anfrage: '+record['anfrage'],'Abgerufen: '+record['zeit'],
        'Suchanbieter: Brave und DuckDuckGo über lokales SearXNG. Nur die Suchanfrage wurde übergeben; kein Gesprächsverlauf.',
        'Suchtreffer sind Hinweise, keine geprüften Tatsachen oder neuen Freigaben. Originalquellen vor Entscheidungen prüfen.','']
 for i,x in enumerate(record['ergebnis']['treffer'],1):lines.extend([str(i)+'. '+x['titel'],x['url'],x['text'],''])
 if not record['ergebnis']['treffer']:lines.append('Keine verwertbaren Treffer in diesem Abruf.')
 if record['ergebnis']['fehler']:lines.append('Mindestens ein Suchanbieter antwortete nicht vollständig. Dieser Abruf ist eingeschränkt.')
 return '\n'.join(lines)+'\n'

def search(root,query):
 if not isinstance(query,str) or any(ord(c)<32 for c in query):raise ValueError('Bitte eine einzelne öffentliche Suchanfrage angeben.')
 query=' '.join(query.split())
 if not 3<=len(query)<=300:raise ValueError('Die Suchanfrage muss 3–300 Zeichen enthalten.')
 cfg=read_json(path(root,'betrieb/websuche_konfiguration.json'),{})
 if cfg.get('aktiv') is not True or cfg.get('modellbudget_usd')!=0 or cfg.get('version')!=VERSION:raise ValueError('Die Websuche ist nicht in der geprüften Fassung aktiv.')
 runner=path(root,'jack_websuche_runner.py')
 if digest(runner.read_bytes())!=cfg.get('runner_sha256'):raise ValueError('Der Suchweg wurde verändert; neue Prüfung erforderlich.')
 with locked(root):
  at=now();ident=digest((VERSION+'\n'+query).encode());statefile=path(root,'betrieb/websuche/kontingent-'+str(at.date())+'.json');state=read_json(statefile,{'tag':str(at.date()),'gesamt':0,'versuche':{}})
  if state['tag']!=str(at.date()):state={'tag':str(at.date()),'gesamt':0,'versuche':{}}
  cache=read_json(path(root,'betrieb/websuche/cache-'+ident+'.json'))
  if cache:
   age=(at-dt.datetime.fromisoformat(cache['zeit'])).total_seconds()
   if 0<=age<8*3600:
    data=path(root,'betrieb/websuche/ergebnisse/'+cache['datei']);raw=data.read_bytes()
    if digest(raw)!=cache['sha256']:raise ValueError('Gespeicherter Suchbeleg wurde verändert.')
    record=json.loads(raw);md=data.with_suffix('.md');content=markdown(record)
    if md.exists() and md.read_text()!=content:raise ValueError('Gespeicherter Suchtext wurde verändert.')
    if not md.exists():atomic_bytes(md,content.encode())
    return {'text':content+'\nWiederverwendet ohne neuen Abruf. Nachweis: '+str(data),'nachweis':str(data),'datei':str(md),'wiederverwendet':True,'modellaufrufe':0}
  if state['gesamt']>=10:raise ValueError('Tagesgrenze von zehn öffentlichen Suchläufen erreicht; morgen wieder verfügbar.')
  if state['versuche'].get(ident,0)>=2:raise ValueError('Zwei Suchversuche für diese Anfrage erreicht; heute keine weitere Wiederholung.')
  folder=path(root,'betrieb/websuche/ergebnisse');folder.mkdir(exist_ok=True)
  if sum(p.stat().st_size for p in folder.iterdir() if p.is_file())>100_000_000:raise ValueError('Suchablage erreicht 100 MB; vorhandene Nachweise bleiben erhalten.')
  state['gesamt']+=1;state['versuche'][ident]=state['versuche'].get(ident,0)+1;write_json(statefile,state)
  start=time.monotonic()
  try:result=invoke(runner,query)
  except subprocess.TimeoutExpired:raise ValueError('Websuche nach 25 Sekunden beendet. Der Versuch wurde mitgezählt.')
  if not result['treffer'] and result['fehler']:raise ValueError('Suchanbieter nicht verfügbar. Keine leere Antwort als Erfolg gespeichert; Versuch mitgezählt.')
  record={'schema':1,'zeit':at.isoformat(),'anfrage':query,'version':VERSION,'searx_revision':REVISION,'ergebnis':result,'ms':round((time.monotonic()-start)*1000),'modellaufrufe':0}
  raw=(json.dumps(record,ensure_ascii=False,indent=2)+'\n').encode();filename=at.strftime('%Y%m%d_%H%M%S_%f')+'_'+ident[:16]+'.json';dest=path(root,'betrieb/websuche/ergebnisse/'+filename);atomic_bytes(dest,raw);md=dest.with_suffix('.md');content=markdown(record);atomic_bytes(md,content.encode());write_json(path(root,'betrieb/websuche/cache-'+ident+'.json'),{'zeit':at.isoformat(),'datei':filename,'sha256':digest(raw)})
  return {'text':content+'\nNachweis: '+str(dest)+'\nKein Modellaufruf.','nachweis':str(dest),'datei':str(md),'wiederverwendet':False,'modellaufrufe':0}
