"""Local-only Qwen speech routing with a reusable model and explicit cancellation."""
import atexit
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
import uuid

BROKERS={}
BROKER_LOCK=threading.RLock()

# Only the speech copy is normalized. Brand IDs, displayed text and saved replies
# stay byte-for-byte unchanged. Acronyms are spelled, never expanded by guessing.
AUSSPRACHE={
    'ANALOG_WERKE':'Analogwerke', 'CASHFLOW_KOMPASS':'Cashflow Kompass',
    'GOTT_WALD_Holding':'Gottwald Holding', 'Goldene-Bücher':'Goldene Bücher',
    'MATHIAS_GOTTWALD':'Mathias Gottwald', 'MEISTERWERK':'Meisterwerk',
    'PATRONOS':'Patronos', 'PLHH':'Pe El Ha Ha',
    'STEPHAN_MANDLIK':'Stephan Mandlik', 'YIG_CARE':'Ypsilon I Ge Care',
    'give1get1':'give one get one',
}
NAMEN=re.compile(r'(?<!\w)('+ '|'.join(re.escape(x) for x in sorted(AUSSPRACHE,key=len,reverse=True))+r')(?!\w)',re.I)
NAMEN_KLEIN={k.casefold():v for k,v in AUSSPRACHE.items()}
def sprechtext(text):
    return NAMEN.sub(lambda m:NAMEN_KLEIN[m.group().casefold()],text)

def abschnitt(text):
    """Take a complete sentence or a sufficiently long clause, never a word cut."""
    for m in re.finditer(r'([.!?:;,])\s+',text):
        prefix=text[:m.start()+1]
        if m[1] in '.!?':
            if m[1]=='.' and re.search(r'(?:\b(?:Dr|Prof|bzw|ca|Nr|usw)|z\.\s*B|u\.\s*a)\.$',prefix,re.I):continue
            return prefix,text[m.end():]
        if len(prefix)>=48 and len(prefix.split())>=5:
            return prefix,text[m.end():]
    return None,text

def config(root):
    p=Path(root)/'jack_stimmprofil.json'
    if not p.exists():return None
    c=json.loads(p.read_text())
    if c.get('anbieter')!='qwen_lokal':return None
    if c.get('tempo')!=1.15 or not Path(c['python']).is_file() or not Path(c['modell']).is_dir():
        raise ValueError('Lokales Stimmprofil ist unvollständig')
    if c.get('referenz_audio') and (not Path(c['referenz_audio']).is_file() or not c.get('referenz_text')):
        raise ValueError('Feste Stimmreferenz fehlt')
    return c

class Broker:
    def __init__(self,root,c):
        self.lock=threading.RLock();self.voices={};self.ready=threading.Event();self.error=None
        env={k:v for k,v in os.environ.items() if k in ('HOME','PATH','LANG','TMPDIR','USER','LOGNAME')}
        self.proc=subprocess.Popen([c['python'],'-I',str(Path(__file__).with_name('jack_qwen_worker.py')),
            str(Path(root)/'jack_stimmprofil.json')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,text=True,bufsize=1,env=env)
        self.reader=threading.Thread(target=self.read,daemon=True);self.reader.start()
        atexit.register(self.close)
    def send(self,row):
        with self.lock:
            if self.proc.poll() is not None:raise RuntimeError('Lokaler Stimmprozess ist beendet')
            self.proc.stdin.write(json.dumps(row,ensure_ascii=False)+'\n');self.proc.stdin.flush()
    def read(self):
        try:
            for line in iter(lambda:self.proc.stdout.readline(2100000),''):
                if len(line)>=2100000 or not line.endswith('\n'):raise ValueError('Audio packet limit')
                row=json.loads(line);kind=row.get('typ')
                if kind=='prozess_bereit':self.ready.set();continue
                if kind=='prozess_fehler':raise RuntimeError('Lokale Stimme ist nicht verfügbar')
                with self.lock:voice=self.voices.get(row.get('id'))
                if voice:voice.event(row)
            raise RuntimeError('Lokaler Stimmprozess wurde beendet')
        except Exception:
            self.error='Lokale Stimme ist nicht verfügbar. Die Antwort steht im Chat.'
            with self.lock:voices=list(self.voices.values())
            for voice in voices:voice.fail(self.error)
    def close(self):
        with self.lock:
            if self.proc.poll() is not None:return
            try:self.proc.stdin.close()
            except OSError:pass
            self.proc.terminate()
        try:self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:self.proc.kill();self.proc.wait(timeout=2)

def broker(root):
    root=str(Path(root).resolve())
    with BROKER_LOCK:
        b=BROKERS.get(root)
        if b is None:
            c=config(root)
            if c is None:raise ValueError('Keine lokale Stimme gewählt')
            b=BROKERS[root]=Broker(root,c)
        return b

def start(root):
    if config(root):broker(root)

def status(root):
    c=config(root)
    if not c:return None
    with BROKER_LOCK:b=BROKERS.get(str(Path(root).resolve()))
    ready=bool(b and b.ready.is_set() and b.proc.poll() is None and not b.error)
    return {'anbieter':'qwen_lokal','name':c['name'],'lokal':True,'tempo':c['tempo'],'bereit':ready,
            'status':'bereit' if ready else b.error if b and b.error else 'Stimme wird geladen'}

class Sprachstrom:
    def __init__(self,root,emit,cancelled):
        self.broker=broker(root);self.emit=emit;self.cancelled=cancelled;self.id=uuid.uuid4().hex
        self.lock=threading.RLock();self.done=threading.Event();self.idle=threading.Event();self.idle.set()
        self.carry='';self.chars=0;self.pending=0;self.closed=False;self.final=False;self.input_closed=False;self.error=None
        with self.broker.lock:self.broker.voices[self.id]=self
        if self.broker.error:self.fail(self.broker.error)
    def fail(self,reason):
        with self.lock:
            if self.error or self.closed:return
            self.error=reason;self.done.set()
        try:self.emit({'typ':'audio_fehler','grund':reason})
        except Exception:pass
    def event(self,row):
        try:
            with self.lock:
                if row['typ']=='abschnitt_ende':
                    self.pending-=1
                    if self.pending<0:raise ValueError('Unexpected completion')
                    if self.pending==0:
                        self.idle.set()
                        if self.input_closed and not self.closed and not self.error:
                            self.final=True;self.emit({'typ':'audio_ende'});self.done.set()
                    return
                if self.closed or self.cancelled():return
                if row['typ']=='audio':
                    data=base64.b64decode(row['audio'],validate=True)
                    if len(data)%2 or not data or len(data)>1500000 or row.get('rate')!=24000:
                        raise ValueError('Invalid PCM')
                    self.emit({k:v for k,v in row.items() if k!='id'})
                elif row['typ']=='audio_fehler':self.fail(row['grund'])
        except Exception:self.fail('Lokale Sprachausgabe wurde unterbrochen.')
    def submit(self,text):
        if not text.strip():return
        with self.lock:
            self.pending+=1;self.idle.clear()
            try:self.broker.send({'typ':'sprechen','id':self.id,'text':sprechtext(text.strip()),'anzeige':text.strip()})
            except Exception:
                self.pending-=1
                if not self.pending:self.idle.set()
                self.fail('Lokale Stimme konnte nicht gestartet werden.')
    def text(self,value):
        with self.lock:
            if self.closed or self.error or self.cancelled():return
            if not isinstance(value,str):raise ValueError('Stimmtext')
            if self.chars+len(value)>6000:self.fail('Die weitere Antwort steht im Chat; die Sprachantwort ist zu lang.');return
            self.chars+=len(value);self.carry+=value
            while True:
                part,rest=abschnitt(self.carry)
                if part is None:break
                self.carry=rest;self.submit(part)
    def flush(self):
        with self.lock:
            if self.closed or self.error or self.cancelled():return
            part=self.carry;self.carry='';self.submit(part)
    def finish(self):
        self.flush()
        with self.lock:
            self.input_closed=True
            if not self.pending and not self.error:
                self.final=True;self.emit({'typ':'audio_ende'});self.done.set()
        deadline=time.monotonic()+90
        while not self.done.wait(.05):
            if self.cancelled():self.close(aborted=True);return False
            if time.monotonic()>deadline:self.fail('Lokale Stimme antwortet nicht rechtzeitig.');break
        return self.final and not self.error
    def close(self,aborted=False):
        with self.lock:
            if self.closed:return
            self.closed=True;self.done.set()
        if self.pending:
            try:self.broker.send({'typ':'stopp','id':self.id})
            except Exception:pass
            if not self.idle.wait(3):self.broker.close()
        with self.broker.lock:self.broker.voices.pop(self.id,None)

def wav(root,text,cancelled=lambda:False):
    import io,wave
    parts=[]
    voice=Sprachstrom(root,lambda event:parts.append(base64.b64decode(event['audio'])) if event['typ']=='audio' else None,cancelled)
    try:
        voice.text(text)
        if not voice.finish():raise RuntimeError(voice.error or 'Lokale Stimme unterbrochen')
    finally:voice.close(aborted=cancelled())
    out=io.BytesIO()
    with wave.open(out,'wb') as stream:
        stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(24000);stream.writeframes(b''.join(parts))
    return out.getvalue()


def aufwaermen(root,text='Bereit.'):
    """S-2 P4: die Stimme beim Dienststart einmal sprechen lassen (Ton wird verworfen), damit der erste echte Satz
    ohne Kaltstart kommt. Fehler sind unkritisch."""
    try:
        if not config(root):return False
        b=broker(root)
        if not b.ready.wait(180):return False
        voice=Sprachstrom(root,lambda event:None,lambda:False)
        try:
            voice.text(text)
            return bool(voice.finish())
        finally:
            voice.close()
    except Exception:
        return False

