"""Persistent offline Qwen speech worker. Protocol carries only speech text and PCM."""
import base64
from collections import deque
import contextlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

CONFIG = json.loads(Path(sys.argv[1]).read_text())
os.environ.update(HF_HUB_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1',
                  HF_HUB_DISABLE_IMPLICIT_TOKEN='1', TOKENIZERS_PARALLELISM='false',
                  HF_HOME=str(Path(CONFIG['modell']).parent/'hf'))
PARENT = os.getppid()
LOCK = threading.RLock()
COND = threading.Condition()
QUEUE = deque()
CANCELLED = set()
SHUTDOWN = threading.Event()

def emit(row):
    with LOCK:
        print(json.dumps(row,ensure_ascii=False),flush=True)

def read():
    try:
        for line in iter(lambda:sys.stdin.readline(16000),''):
            if len(line)>=16000 or not line.endswith('\n'):
                raise ValueError('Input limit')
            row=json.loads(line);kind=row.get('typ');ident=row.get('id')
            if not isinstance(ident,str) or len(ident)!=32 or any(c not in '0123456789abcdef' for c in ident):
                raise ValueError('Request id')
            with COND:
                if kind=='sprechen':
                    text=row.get('text')
                    if not isinstance(text,str) or not 0<len(text)<=6000 or len(QUEUE)>=32:
                        raise ValueError('Text limit')
                    display=row.get('anzeige',text)
                    if not isinstance(display,str) or not 0<len(display)<=6000:raise ValueError('Display limit')
                    QUEUE.append((ident,text,display))
                elif kind=='stopp':
                    CANCELLED.add(ident)
                else:
                    raise ValueError('Input type')
                COND.notify_all()
    except Exception:
        emit({'typ':'prozess_fehler','grund':'eingabe'})
    finally:
        SHUTDOWN.set()
        with COND:COND.notify_all()

def cancelled(ident):
    return SHUTDOWN.is_set() or ident in CANCELLED

def watch_parent():
    while not SHUTDOWN.wait(.5):
        if os.getppid()!=PARENT:
            os._exit(0)

def generate(model,text):
    # streaming_interval war urspruenglich .64 - der erste Tonblock kam erst spaet.
    # ACHTUNG: Die erste Messreihe lief bei eingeschaltetem Stromsparmodus und war
    # deshalb verzerrt. Am 16.09.2026 OHNE Stromsparmodus neu gemessen, 12 Saetze:
    #   .64 -> 348,5 ms | .32 -> 210,0 ms | .16 -> 220,6 ms | .08 -> 200,8 ms
    #   ganzer Satz:      .32 -> 901,0 ms | .16 -> 952,7 ms
    # .32 ist ohne Drosselung der beste Wert - frueher UND schnellerer ganzer Satz;
    # die Wertebereiche ueberlappen nicht (.32: 206,7-218,4 | .16: 218,2-232,9).
    # Tonlaenge identisch, Lautheitsverlauf deckungsgleich (Korrelation 0,9988).
    if CONFIG.get('referenz_audio'):
        yield from model.generate(text=text,ref_audio=CONFIG['referenz_audio'],ref_text=CONFIG['referenz_text'],
            lang_code='German',temperature=.7,max_tokens=700,stream=True,streaming_interval=.32,verbose=False)
    else:
        yield from model.generate_voice_design(text=text,instruct=CONFIG['profil'],language='German',
            temperature=.8,max_tokens=700,stream=True,streaming_interval=.32,verbose=False)

def speak(model,ident,text,display,mx,np,count=1):
    proc=None;reader=None;failure=[];received=[0]
    try:
        proc=subprocess.Popen(['/opt/homebrew/bin/ffmpeg','-hide_banner','-loglevel','error',
            '-f','s16le','-ar','24000','-ac','1','-probesize','32','-analyzeduration','0','-i','pipe:0',
            '-af','atempo='+str(CONFIG['tempo']),'-f','s16le','-ar','24000','-ac','1','pipe:1'],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,bufsize=0)
        def audio_out():
            first=True;rest=b''
            try:
                while True:
                    chunk=proc.stdout.read(4096)
                    if not chunk:return
                    chunk=rest+chunk;rest=chunk[len(chunk)//2*2:];chunk=chunk[:len(chunk)//2*2]
                    if not chunk or cancelled(ident):continue
                    received[0]+=len(chunk)
                    emit({'typ':'audio','id':ident,'rate':24000,'audio':base64.b64encode(chunk).decode(),
                          'chars':[display+' '] if first else [],'starts':[0] if first else [],'durations':[]})
                    first=False
            except Exception:failure.append(True)
        reader=threading.Thread(target=audio_out,daemon=True);reader.start()
        mx.random.seed(CONFIG['seed'])
        begun=time.monotonic()
        for result in generate(model,text):
            if cancelled(ident):break
            if time.monotonic()-begun>90:raise TimeoutError()
            samples=np.array(result.audio,dtype=np.float32).reshape(-1)
            if not np.isfinite(samples).all():raise ValueError('PCM samples')
            pcm=(np.clip(samples,-1,1)*32767).astype('<i2').tobytes()
            view=memoryview(pcm)
            while view:
                n=proc.stdin.write(view)
                if not n:raise OSError('PCM pipe closed')
                view=view[n:]
        proc.stdin.close()
        if cancelled(ident) and proc.poll() is None:proc.terminate()
        proc.wait(timeout=3);reader.join(timeout=2)
        if not cancelled(ident) and (proc.returncode!=0 or failure or not received[0] or reader.is_alive()):
            raise RuntimeError('No complete audio')
    except Exception:
        if not cancelled(ident):emit({'typ':'audio_fehler','id':ident,'grund':'Lokale Stimme konnte den Satz nicht vollständig erzeugen.'})
    finally:
        if proc is not None:
            if proc.poll() is None:
                proc.terminate()
                try:proc.wait(timeout=2)
                except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=2)
            for pipe in (proc.stdin,proc.stdout):
                with contextlib.suppress(Exception):pipe.close()
        if reader:reader.join(timeout=1)
        for _ in range(count):emit({'typ':'abschnitt_ende','id':ident})

def main():
    signal.signal(signal.SIGTERM,lambda *a:SHUTDOWN.set())
    threading.Thread(target=read,daemon=True).start()
    threading.Thread(target=watch_parent,daemon=True).start()
    import mlx.core as mx
    import numpy as np
    from mlx_audio.tts.utils import load_model
    with contextlib.redirect_stdout(sys.stderr):
        model=load_model(CONFIG['modell'])
        mx.random.seed(CONFIG['seed'])
        for result in generate(model,'Patron, ich bin da.'):
            mx.eval(result.audio)
            if SHUTDOWN.is_set():return
    emit({'typ':'prozess_bereit'})
    while not SHUTDOWN.is_set():
        with COND:
            if not QUEUE:COND.wait(timeout=.5)
            if not QUEUE:continue
            ident,text,display=QUEUE.popleft();count=1
            # While the first clause is spoken, later text arrives. Synthesize
            # adjacent queued clauses together to retain phrasing and avoid
            # a model prefill and an audio seam for every short sentence.
            while QUEUE and QUEUE[0][0]==ident and len(text)+len(QUEUE[0][1])<1200:
                _,more,shown=QUEUE.popleft();text+=' '+more;display+=' '+shown;count+=1
        if cancelled(ident):
            for _ in range(count):emit({'typ':'abschnitt_ende','id':ident})
        else:speak(model,ident,text,display,mx,np,count)
        with COND:
            if not any(item[0]==ident for item in QUEUE):CANCELLED.discard(ident)

if __name__=='__main__':
    try:main()
    except Exception:emit({'typ':'prozess_fehler','grund':'start'})
