"""Stimme B als begrenzter PCM-Strom. Keine Aufnahme und keine Zugangsdaten im Browser."""
import base64
import json
from pathlib import Path
import subprocess
import threading
import time
import jack_kosten


class Sprachstrom:
    def __init__(self, root, key, voice, emit, cancelled, popen=subprocess.Popen):
        self.root = Path(root)
        self.emit = emit
        self.cancelled = cancelled
        self.lock = threading.RLock()
        self.done = threading.Event()
        self.closed = False
        self.final = False
        self.error = None
        self.chars = 0
        self.audio_bytes = 0
        self.cost = None
        self.carry = ''
        if not key or not voice:
            raise ValueError('Stimmzugang fehlt')
        self.proc = popen(['/opt/homebrew/bin/node', str(Path(__file__).with_name('jack_tts_socket.mjs'))],
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          text=True, bufsize=1)
        self._send({'typ':'init', 'key':key, 'voice':voice})
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        self.watcher = threading.Thread(target=self._watch, daemon=True)
        self.watcher.start()

    def _send(self, row):
        with self.lock:
            if self.closed or self.error:
                return False
            try:
                self.proc.stdin.write(json.dumps(row)+'\n')
                self.proc.stdin.flush()
                return True
            except (OSError, ValueError):
                self._fail('Stimmverbindung unterbrochen')
                return False

    def _fail(self, reason):
        with self.lock:
            if self.error or self.closed:
                return
            self.error = reason
        try:
            self.emit({'typ':'audio_fehler', 'grund':reason})
        except Exception:
            pass
        self.done.set()

    def _read(self):
        try:
            for line in iter(lambda:self.proc.stdout.readline(2100000), ''):
                if self.closed or self.cancelled():
                    break
                if len(line) >= 2100000 or not line.endswith('\n'):
                    raise ValueError('Audiopaket zu gross')
                row = json.loads(line)
                kind = row.get('typ')
                if kind == 'audio':
                    data = base64.b64decode(row['audio'], validate=True)
                    if len(data) % 2 or row.get('rate') != 24000 or len(data) > 1500000:
                        raise ValueError('PCM-Format')
                    chars, starts, durations = row.get('chars',[]), row.get('starts',[]), row.get('durations',[])
                    if not all(isinstance(x,list) for x in (chars,starts,durations)):
                        raise ValueError('Text-Zuordnung')
                    self.audio_bytes += len(data)
                    self.emit(row)
                elif kind == 'stimme_bereit':
                    self.emit(row)
                elif kind == 'audio_ende':
                    self.final = True
                    self.emit(row)
                    break
                elif kind == 'audio_fehler':
                    self._fail({'guthaben':'Das ElevenLabs-Guthaben für Stimme B ist aufgebraucht. Die Antwort steht im Chat.','zugang':'ElevenLabs hat den Stimmzugang abgelehnt. Die Antwort steht im Chat.'}.get(row.get('grund'),'Direkte Stimme ist nicht verfügbar. Die Antwort steht im Chat.'))
                    break
            if not self.final and not self.closed and not self.cancelled() and not self.error:
                self._fail('Stimmübertragung ohne bestätigtes Ende')
        except Exception:
            self._fail('Stimmübertragung unterbrochen')
        finally:
            self.done.set()

    def _watch(self):
        deadline = time.monotonic() + 175
        while not self.done.wait(.1):
            if self.cancelled():
                self.close(aborted=True)
                return
            if time.monotonic() >= deadline:
                self._fail('Zeitlimit der Stimmübertragung')
                return

    def text(self, value):
        if not value or self.error or self.closed or self.cancelled():
            return
        if not isinstance(value,str):
            raise ValueError('Stimmtext')
        if self.chars + len(value) > 6000:
            self._fail('Die weitere Antwort steht im Chat; das Stimm-Limit ist erreicht')
            return
        if self.cost is None:
            self.cost = jack_kosten.begin(self.root, 'stimme', 'elevenlabs', 'eleven_multilingual_v2', billing='elevenlabs_zugang')
        self.chars += len(value)
        self.carry += value
        # Keine Wortfragmente mit zusätzlichen Leerzeichen verfälschen.
        end = max(self.carry.rfind(' '), self.carry.rfind('\n'))
        if end >= 0:
            self._send({'typ':'text','text':self.carry[:end+1]})
            self.carry = self.carry[end+1:]

    def flush(self):
        if self.carry:
            self._send({'typ':'text','text':self.carry+' '})
            self.carry = ''
        self._send({'typ':'flush'})

    def finish(self):
        self.flush()
        self._send({'typ':'ende'})
        deadline = time.monotonic() + 25
        while not self.done.wait(.1):
            if self.cancelled():
                self.close(aborted=True)
                return False
            if time.monotonic() >= deadline:
                self._fail('Stimme antwortet nicht rechtzeitig')
                break
        return self.final and not self.error

    def close(self, aborted=False):
        with self.lock:
            if self.closed:
                return
            self.closed = True
        self.done.set()
        try:
            self.proc.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            self.proc.wait(timeout=.5)
        except subprocess.TimeoutExpired:
            self.proc.terminate()  # Ausschließlich der von diesem Dialog gestartete Prozess.
            try:self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:self._fail('Stimmprozess endet nicht')
        if self.reader is not threading.current_thread():
            self.reader.join(timeout=1)
        if self.cost is not None:
            jack_kosten.end(self.root, self.cost,
                           status='abgebrochen' if aborted or self.cancelled() else 'ok' if self.final and not self.error else 'fehler',
                           verbrauch={'zeichen_angefordert':self.chars, 'audio_bytes':self.audio_bytes},
                           error='Stimmuebertragung' if self.error else None)
