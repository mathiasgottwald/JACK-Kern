"""Lokale Ablaufdiagnose. Nur Marken und Zeiten - nie Gespraechsinhalte, nie Audio,
nie Zugangsdaten. Seit 16.09.2026 zusaetzlich anhaengend auf Platte, damit ueber
mehr als die letzten 600 Ereignisse hinaus gemessen werden kann."""
from collections import deque
import json
import re
import threading
import time
from pathlib import Path

import jack_betrieb as betrieb

# Diese sechs Marken muss jeder vollstaendige Wortwechsel tragen.
PFLICHTMARKEN = ('erkennung_final', 'frage_gesendet', 'erster_text_ab_frage',
                 'erstes_audio_ab_frage', 'antwort_vollstaendig_ab_frage',
                 'ausgabe_vollstaendig')
DATEI = 'sprachdiagnose.jsonl'
_SCHREIBSPERRE = threading.Lock()
_WURZEL = {'pfad': None}


def wurzel(root=None):
    """Die Ablage wird beim Serverstart einmal gesetzt."""
    if root is not None:
        _WURZEL['pfad'] = Path(root)
    return _WURZEL['pfad']


def _auf_platte(rows):
    """Haengt die Ereignisse an betrieb/sprachdiagnose.jsonl an. Ein Fehler beim
    Schreiben darf das Gespraech nie stoeren."""
    root = _WURZEL['pfad']
    if root is None or not rows:
        return
    try:
        ziel = betrieb.area(root) / DATEI
        zeilen = []
        for row in rows:
            eintrag = dict(row)
            eintrag.pop('empfangen', None)
            eintrag['zeit'] = betrieb.now().isoformat()
            zeilen.append(json.dumps(eintrag, ensure_ascii=False))
        with _SCHREIBSPERRE:
            with ziel.open('a', encoding='utf-8') as datei:
                datei.write('\n'.join(zeilen) + '\n')
    except Exception:
        pass

_LOCK = threading.Lock()
_ROWS = deque(maxlen=600)
PHASEN = frozenset('''stimme_vorbereitet eingabe_bestaetigt seite_bereit mikro_an mikro_aus mikro_pegel_bereit mikro_pegel_fehler
erkennung_start erkennung_ende erkennung_zwischen erkennung_final erkennung_sprechstart
erkennung_sprechende erkennung_echo erkennung_veraltet erkennung_neustart eingabe_gesendet
eingabe_entwurf sprechpause_erkannt einwand_erkannt durch_dazwischenreden_unterbrochen
bestaetigte_eingabe_hat_vorrang stopp_angefordert stopp_bestaetigt stopp_fehler dienst_bereit
frage_gesendet frage_fehler erstes_audio_ab_frage erster_text_ab_frage
antwort_vollstaendig_ab_frage ausgabe_vollstaendig ausgabe_fehler audio_fehler
audio_nachladepause werkzeuge_werden_geprueft erkennung_network erkennung_no-speech
erkennung_audio-capture erkennung_not-allowed erkennung_service-not-allowed
erkennung_aborted erkennung_language-not-supported erkennung_bad-grammar erkennung_fehler
wartezeit_nach_letztem_wort erster_ton_ab_sprechende
umgebung_ios umgebung_standalone umgebung_unsicher umgebung_kein_erkenner
tonwelt_entsperrt tonwelt_gesperrt sprachhilfe_gezeigt'''.split())


def aufnehmen(body):
    ident = body.get('fenster')
    if not isinstance(ident, str) or not re.fullmatch('[a-f0-9]{32}', ident):
        raise ValueError('Fensterkennung')
    if body.get('version') != '2026-09-21.dialog3':
        raise ValueError('Versionskennung')
    events = body.get('ereignisse')
    if not isinstance(events, list) or len(events) > 40:
        raise ValueError('Ereigniszahl')
    rows = []
    for item in events:
        if not isinstance(item, dict) or item.get('phase') not in PHASEN:
            raise ValueError('Ereignis')
        row = {'fenster': ident, 'version': body['version'], 'phase': item['phase']}
        for key in ('dauer_ms', 'folge', 'runde', 'zeichen'):
            value = item.get(key, 0)
            if type(value) is not int or not 0 <= value <= 100000000:
                raise ValueError('Messwert')
            row[key] = value
        row['empfangen'] = round(time.time(), 3)
        rows.append(row)
    with _LOCK:
        _ROWS.extend(rows)
    _auf_platte(rows)


def lesen():
    with _LOCK:
        cutoff = time.time() - 1200
        return [dict(row) for row in _ROWS if row['empfangen'] >= cutoff]


# ------------------------------------------------------------------ Tagesauszug
def _median(werte):
    werte = sorted(werte)
    if not werte:
        return None
    mitte = len(werte) // 2
    if len(werte) % 2:
        return werte[mitte]
    return (werte[mitte - 1] + werte[mitte]) / 2


def tageswerte(root, tag=None):
    """Median und schlechtester Wert je Marke fuer einen Tag. Liest nur die
    Diagnosedatei, nie Gespraechsinhalte."""
    tag = tag or betrieb.now().date().isoformat()
    ziel = betrieb.area(root) / DATEI
    je_marke = {}
    if ziel.is_file():
        with ziel.open(encoding='utf-8') as datei:
            for zeile in datei:
                zeile = zeile.strip()
                if not zeile:
                    continue
                try:
                    row = json.loads(zeile)
                except ValueError:
                    continue
                if not str(row.get('zeit', '')).startswith(tag):
                    continue
                phase = row.get('phase')
                dauer = row.get('dauer_ms')
                if not isinstance(phase, str) or type(dauer) is not int:
                    continue
                je_marke.setdefault(phase, []).append(dauer)
    ergebnis = {}
    for phase, werte in je_marke.items():
        messbar = [w for w in werte if w > 0]
        ergebnis[phase] = {
            'ereignisse': len(werte),
            'mit_zeitwert': len(messbar),
            'median_ms': _median(messbar),
            'schlechtester_ms': max(messbar) if messbar else None,
        }
    return {'tag': tag, 'marken': ergebnis,
            'fehlende_pflichtmarken': [m for m in PFLICHTMARKEN if m not in ergebnis]}


def tagesbericht(root, tag=None):
    """Schreibt den Auszug nach betrieb/tagesberichte/<Tag>_sprache.md."""
    daten = tageswerte(root, tag)
    ordner = betrieb.area(root) / 'tagesberichte'
    ordner.mkdir(exist_ok=True)
    ziel = ordner / (daten['tag'] + '_sprache.md')
    zeilen = ['# JACK - Sprachdiagnose ' + daten['tag'], '',
              'Stand: ' + betrieb.now().isoformat(), '',
              'Nur Marken und Zeiten. Keine Gespraechsinhalte, kein Audio.', '',
              '| Marke | Ereignisse | mit Zeitwert | Median ms | schlechtester ms |',
              '|---|---|---|---|---|']
    for phase in sorted(daten['marken']):
        w = daten['marken'][phase]
        zeilen.append('| %s | %d | %d | %s | %s |' % (
            phase, w['ereignisse'], w['mit_zeitwert'],
            'keiner' if w['median_ms'] is None else round(w['median_ms']),
            'keiner' if w['schlechtester_ms'] is None else w['schlechtester_ms']))
    if not daten['marken']:
        zeilen.append('| keine Aufzeichnung | 0 | 0 | keiner | keiner |')
    if daten['fehlende_pflichtmarken']:
        zeilen += ['', 'Fehlende Pflichtmarken an diesem Tag: ' +
                   ', '.join(daten['fehlende_pflichtmarken'])]
    else:
        zeilen += ['', 'Alle sechs Pflichtmarken sind belegt.']
    ziel.write_text('\n'.join(zeilen) + '\n', encoding='utf-8')
    return ziel
