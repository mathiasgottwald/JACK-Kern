"""Kurzer Fensterstarter. Chrome bleibt ein eigener Prozess, launchd besitzt den Server."""
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.request
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parent))
import jack_betrieb as b

ROOT = Path(__file__).resolve().parent
CHROME = Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
PROFILE = Path.home() / 'Library/Application Support/JACK-Fenster'
NATIVE = ROOT / 'lib/jack-fenster'
LABEL = 'world.gottwald.jack.server'
DOMAIN = f'gui/{os.getuid()}'
URL = 'http://127.0.0.1:8778'


def command(args, timeout=5):
    return subprocess.run(list(map(str, args)), capture_output=True, text=True, timeout=timeout)


def status():
    try:
        with urllib.request.urlopen(URL + '/status', timeout=1) as response:
            data = json.load(response)
            return data if response.status == 200 and data.get('dienst') == 'JACK' else None
    except (OSError, ValueError):
        return None


def service_pid():
    result = command(['/bin/launchctl', 'print', DOMAIN + '/' + LABEL])
    match = re.search(r'^\s*pid = (\d+)\s*$', result.stdout, re.M)
    return int(match[1]) if result.returncode == 0 and match else None


def chrome_state():
    lines = command(['/bin/ps', '-axo', 'pid=,command=']).stdout.splitlines()
    chrome, own = [], []
    for line in lines:
        parts = line.strip().split(None, 1)
        if len(parts) != 2 or not parts[1].startswith(str(CHROME)) or '--type=' in parts[1]:
            continue
        pid = int(parts[0]); chrome.append(pid)
        if '--user-data-dir=' + str(PROFILE) in parts[1]:
            own.append(pid)
    if len(own) > 1:
        raise ValueError('Mehrere Chrome-Prozesse verwenden JACKs Profil. Bitte die JACK-Fenster prüfen.')
    return chrome, own[0] if own else None


def windows():
    try:
        with urllib.request.urlopen(URL + '/appfenster', timeout=1) as response:
            return json.load(response).get('fenster', [])
    except (OSError, ValueError):
        return []


def native_notice(message):
    if NATIVE.is_file():
        subprocess.Popen([str(NATIVE), 'hinweis', message], start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        # Systemdialog bleibt auch beim fehlenden eigenen Helfer verfügbar.
        subprocess.Popen(['/usr/bin/osascript', '-e',
                          'on run argv\ndisplay alert "JACK konnte nicht starten" message (item 1 of argv) as warning\nend run', message],
                         start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run():
    record = {'zeit': b.now().isoformat(), 'quelle': 'echter_lauf', 'id': uuid.uuid4().hex,
              'pid_vorher': None, 'pid_nachher': None, 'fall': None, 'ergebnis': 'fehler',
              'meldung': '', 'fenster_nachweis': None}
    try:
        with Path(__file__).open() as lock:
            deadline = time.monotonic() + 25
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise ValueError('Ein anderer JACK-Start läuft noch. Bitte kurz warten.')
                    time.sleep(.1)
            record['pid_vorher'] = service_pid()
            if not CHROME.is_file() or not os.access(CHROME, os.X_OK):
                raise ValueError('Google Chrome fehlt. Bitte die Installation im Programme-Ordner prüfen.')
            if not PROFILE.is_dir():
                raise ValueError('Das vorhandene Profil JACK-Fenster fehlt. Es wurde kein Ersatzprofil angelegt.')
            if not NATIVE.is_file():
                raise ValueError('Der Fensterhelfer fehlt. Bitte JACKs Startdateien wiederherstellen.')
            ready = status()
            if not ready:
                record['fall'] = 'e'
                if command(['/bin/launchctl', 'print', DOMAIN + '/' + LABEL]).returncode:
                    plist = Path.home() / 'Library/LaunchAgents' / (LABEL + '.plist')
                    if command(['/bin/launchctl', 'bootstrap', DOMAIN, plist]).returncode:
                        raise ValueError('JACKs Startdienst konnte nicht geladen werden. Die Dienstkonfiguration muss geprüft werden.')
                if command(['/bin/launchctl', 'kickstart', DOMAIN + '/' + LABEL]).returncode:
                    raise ValueError('JACKs Startdienst konnte nicht angestoßen werden.')
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    if status():
                        break
                    time.sleep(.2)
                else:
                    raise ValueError('Der JACK-Dienst antwortet nach 20 Sekunden nicht. Bitte die Betriebsprüfung ansehen.')
            chrome, own = chrome_state()
            page = windows()
            count = int(command([NATIVE, 'fenster', own], timeout=20).stdout.strip()) if own else 0
            record['fenster_vorher']=count
            record['seiten_vorher']=len(page)
            # Ein verborgener Tab kann gedrosselte Timer haben. Aktivieren löst ein frisches Lebenszeichen aus.
            if own and not page:
                command([NATIVE, 'vorne', own], timeout=20)
                until=time.monotonic()+3
                while time.monotonic()<until:
                    page=windows()
                    if page:break
                    time.sleep(.2)
            existing = bool(own and page)
            mode = 'b' if existing else 'c' if own else 'd' if chrome else 'a'
            record['fensterfall'] = mode
            record['fall'] = record['fall'] or mode
            if existing:
                if command([NATIVE, 'vorne', own], timeout=20).returncode:
                    raise ValueError('Das bestehende JACK-Fenster konnte nicht nach vorne geholt werden.')
            else:
                # Nicht exec: Sonst kann der Dock-Wiederaufruf beim überlebenden Chrome landen.
                subprocess.Popen([str(CHROME), '--profile-directory=Default', '--new-window',
                                  '--app=' + URL + '/?jackfenster=' + record['id'],
                                  '--user-data-dir=' + str(PROFILE), '--window-size=1600,1000',
                                  '--no-first-run', '--no-default-browser-check'],
                                 start_new_session=True, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    page = [p for p in windows() if p.get('id') == record['id']]
                    if page:
                        break
                    time.sleep(.2)
                else:
                    raise ValueError('Chrome wurde gestartet, aber die JACK-Seite bestätigt sich nicht. Bitte das Fenster prüfen; es wird kein zweiter Start versucht.')
            _, current_chrome=chrome_state()
            record['chrome_pid']=current_chrome
            record['fenster_nachher']=int(command([NATIVE,'fenster',current_chrome], timeout=20).stdout.strip()) if current_chrome else None
            if existing and count>0 and record['fenster_nachher']!=count:
                raise ValueError('Die Fensterzahl hat sich unerwartet geändert. Bitte JACKs Fenster prüfen.')
            record.update(pid_nachher=service_pid(), ergebnis='ok', fenster_nachweis='JACK-Seite',
                          meldung='Bestehendes JACK-Fenster aktiviert' if existing else 'JACK-Seite im neuen App-Fenster bestätigt',
                          mikrofon_stumm=all(p.get('stumm') is True for p in page))
    except Exception as error:
        record['meldung'] = ('Die Fensterprüfung antwortet nicht rechtzeitig.' if isinstance(error, subprocess.TimeoutExpired) else str(error) if isinstance(error, ValueError) else 'Start fehlgeschlagen: ' + type(error).__name__)
        try:
            record['pid_nachher'] = service_pid()
        except Exception:
            pass
    try:
        b.append(b.area(ROOT) / 'appstarts.jsonl', record)
    except Exception:
        record['ergebnis'] = 'fehler'
        record['meldung'] += ' Das Startprotokoll in iCloud ist ebenfalls nicht schreibbar.'
    if record['ergebnis'] != 'ok':
        native_notice(record['meldung'])
    return 0 if record['ergebnis'] == 'ok' else 1


if __name__ == '__main__':
    raise SystemExit(run())
