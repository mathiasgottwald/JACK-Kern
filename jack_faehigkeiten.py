"""Lesendes Faehigkeitsregister fuer JACKs tatsaechlichen Dienst.

Eine Codex-App-Verbindung ist kein JACK-Werkzeug. Dieses Register fuehrt
ausschliesslich vorhandene Dienstwege auf und meldet fehlende Ausfuehrungswege
vor einem kostenpflichtigen Arbeiterlauf. Keine Installation, kein Netzzugriff.
"""
import ast
import datetime as dt
import hashlib
import json
import os
from pathlib import Path


def _lesen(path, fallback=None):
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 2_000_000:
            return fallback
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return fallback


def _werkzeuge(root):
    """Nur das Schema lesen, den Server nicht importieren oder starten."""
    try:
        tree = ast.parse((Path(root)/'server.py').read_text())
    except (OSError, SyntaxError):
        return set()
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            values = {k.value:v for k,v in zip(node.keys,node.values) if isinstance(k,ast.Constant) and isinstance(k.value,str)}
            if 'input_schema' in values and isinstance(values.get('name'),ast.Constant):
                names.add(values['name'].value)
    # Das Profilwerkzeug wird als Modulkonstante in die Liste aufgenommen.
    if (Path(root)/'jack_dialog.py').is_file():
        names.add('patron_profil')
    return names


def stand(root, werkzeuge=None, motor='api', heute=None):
    if motor not in ('api', 'ruflo', 'claude'):
        raise ValueError('Unbekannter Arbeitsmotor')
    root = Path(root)
    tools = set(werkzeuge) if werkzeuge is not None else _werkzeuge(root)
    sources = _lesen(root/'betrieb/verbindungen.json', {}) or {}
    if not isinstance(sources, dict): sources = {}
    source_rows = sources.get('quellen', [])
    connections = {q.get('schluessel'): q for q in source_rows if isinstance(q, dict)} if isinstance(source_rows, list) else {}
    import jack_guthaben
    try:
        # Ein ausdruecklich gesetzter Abo-Motor bleibt sein bestehender Weg.
        # Kein automatischer Ausweichweg: Kontingent und Planer pruefen ihn weiter.
        api_halt = jack_guthaben.api_sperre(root) if motor in ('api','ruflo') else ''
    except Exception:
        api_halt = 'API-Bereitschaft derzeit nicht pruefbar'
    rows = []

    def add(key, name, required, files, price, reason='', last=None, limits=''):
        missing = sorted(set(required)-tools)
        missing_files = [f for f in files if not (root/f).is_file()]
        if missing or missing_files:
            reason = 'Dienstweg fehlt: ' + ', '.join(missing+missing_files)
        rows.append({'kennung':key, 'name':name, 'ausfuehrbar':not bool(reason),
                     'status':'blockiert' if reason else 'konfiguriert',
                     'hindernis':reason, 'werkzeuge':required, 'quellen':files,
                     'kosten':price, 'letzter_verbindungsstand':last,
                     'grenzen':limits, 'qualitaetsgarantie':False})

    add('ablage','Ablage finden und lesen',['suche_ablage','nachschlagen'],['jack_ablage_suche.py'],
        'Kein Modellaufruf durch die Suchfunktion selbst.', limits='Gezielte interne Suche; geschuetzte Dateien bleiben gesperrt.')
    cfg = _lesen(root/'betrieb/websuche_konfiguration.json', {}) or {}
    if not isinstance(cfg, dict): cfg = {}
    runner = root/'jack_websuche_runner.py'
    search_reason = ''
    if cfg.get('aktiv') is not True or cfg.get('modellbudget_usd') != 0:
        search_reason = 'Oeffentliche Suche nicht aktiv freigegeben'
    elif not runner.is_file() or hashlib.sha256(runner.read_bytes()).hexdigest() != cfg.get('runner_sha256'):
        search_reason = 'Suchlauf weicht von der geprueften Fassung ab'
    else:
        import jack_websuche
        if cfg.get('version') != jack_websuche.VERSION:
            search_reason = 'Suchkonfiguration gehoert zu einer anderen Version'
        elif not (jack_websuche.RUNTIME/'python/bin/python').is_file():
            search_reason = 'Lokale Suchlaufzeit fehlt'
    add('web','Oeffentlich recherchieren',['websuche','webseite_lesen'],['jack_websuche.py','jack_webabruf.py'],
        'Vorhandener Suchweg ohne Modellaufruf und ohne Suchanbieter-Konto.', search_reason,
        connections.get('websuche'), 'Bestehende Tagesgrenzen und Cache; Originalquellen statt Suchauszuege als Beleg.')
    add('arbeit','Facharbeit mit getrennter Pruefung',['auftrag_erteilen'],['arbeiter.sh','jack_auftrag.py'],
        'Bestehender Modellrouter und Auftragsdeckel; keine neue Budgetfreigabe.', api_halt or '',
        limits='Interne Datei- und Recherchearbeit innerhalb der bestehenden Arbeitergrenzen. Kein Shell-Ausfuehrungs- oder Publikationsrecht.')
    # F-4 (24.09.2026): Seit 21.09. heisst das Dialogwerkzeug mail_antwort_entwerfen
    # (jack_postfaecher.py). Mit dem alten Namen war diese Zeile live "blockiert".
    add('mailentwurf','Mail lokal entwerfen',['mail_antwort_entwerfen'],['jack_postfaecher.py'],
        'Antwortentwurf an einer gefundenen Mail mit einem Fachkraft-Modelllauf (Kostenart fachentwurf, Deckelpruefung).',
        limits='Entwurf ist kein Versand; vorhandener Versandweg und Freigabecode bleiben gesondert.')
    add('gedaechtnis','Bestaetigte Patron-Praeferenzen',['patron_profil'],['jack_dialog.py'],
        'Lokale Merksatzablage ohne eigenen Modellaufruf.', limits='Explizites Merken/Korrigieren; keine erfundenen Vorlieben und keine neuen Befugnisse.')
    add('videoproduktion_vorbereiten','Zentrale Videoauftraege vorbereiten und passenden Weg waehlen',
        ['videoauftrag_vorbereiten','videoverfahren_waehlen','videoproduktion_stand'],
        ['jack_videoproduktion.py','betrieb/videoproduktion.json'],
        'Lokale Auftragsakte und Auswahl von Higgsfield, lokalem FFmpeg, optionalem After Effects oder Runway ohne Anbieter- oder Modellaufruf.',
        limits='Briefing und Produktionsakte; Higgsfield ist der zentrale Weg mit eigenem API-Adapter. Noch keine Medienerzeugung, kein Upload und keine Veroeffentlichung durch die Vorbereitung.')
    add('software_ausfuehren','Software bauen, testen und ausrollen',[],[],
        'Noch kein abgesicherter automatischer Ausfuehrungsweg.',
        'Der Arbeiter kann Dateien bearbeiten; eine isolierte Build-/Test-/Deploy-Schnittstelle fehlt. Kein fertiges Softwareprodukt behaupten.')
    import jack_runway
    runway = jack_runway.bereitschaft(root)
    import jack_higgsfield
    higgsfield = jack_higgsfield.bereitschaft(root)
    add('medien_erzeugen','Fertige Bilder und Videos erzeugen lassen',
        ['higgsfield_bereitschaft','higgsfield_video_starten','higgsfield_video_aktualisieren'],
        ['jack_higgsfield.py','betrieb/videoproduktion.json'],
        'Higgsfield-API mit festem 3,00-USD-Auftragsdeckel; Runway bleibt ein separater PATRONOS-Spezialadapter.',
        '' if higgsfield.get('bereit') else higgsfield.get('hinweis','Higgsfield-Adapter nicht bereit'),
        limits='Erster freigegebener Adapter: Text-zu-Video mit Seedance 2.0. Keine automatische Aufladung oder Veroeffentlichung; Ergebnis wird lokal gespeichert und technisch geprueft.')
    import jack_medien
    add('medien_pruefen','Lokale Videos technisch pruefen',['medien_pruefen'],['jack_medien.py'],
        'Vorhandene lokale Medienwerkzeuge; keine API-Gebuehr.',
        '' if jack_medien.FFMPEG.is_file() and jack_medien.FFPROBE.is_file() else 'Lokale Medienwerkzeuge fehlen',
        limits='Technische Pruefung mit Datei-Hash, kein Urteil ueber Gestaltung, Inhalt oder Wirkung.')
    add('publizieren','In einem Zielkanal veroeffentlichen',[],[],
        'Kanalbezogene Kosten und Rechte noch zu belegen.',
        'Im JACK-Dienst fehlt eine kanalgebundene Veroeffentlichungsschnittstelle mit Vorgangskennung und nachfolgender Sichtkontrolle.')
    register = _register_ergaenzen(root, rows, connections, heute)
    return {'zeit':dt.datetime.now().astimezone().isoformat(), 'motor':motor, 'faehigkeiten':rows,
            'hinweis':'Konfiguriert bedeutet aufrufbarer Dienstweg, keine erfolgreiche Liveabnahme. Dieses Register erteilt keine neuen Rechte.',
            'quelle':'Lokaler Dienstcode, bestehende Suchkonfiguration, Guthabenwache und Verbindungsprotokoll',
            'register':register}


# ════════ Paket 2 „Verlaessliche Werkzeugwahl" (F-4, 24.09.2026) ════════════
# Freigabe des Patrons (PM-Chat, Frage 13): nur hinzufuegen, nichts umbenennen,
# Werkzeugwahl ANZEIGEND. Die statischen Angaben stehen in der Steuerdatei
# betrieb/faehigkeitsregister.json; hier kommen nur die Live-Teile dazu.
#
# Zwei Begriffe, die nie vermischt werden:
#   ausweichweg    - andere FAEHIGKEIT, die bei Ausfall angeboten werden darf.
#                    Wird nur angezeigt; hier wird nie gewechselt.
#   rueckfallkette - automatischer MODELL-Wechsel im Gespraech (server.py
#                    _rueckfall_versuchen, kostenstufen.json "rueckfall").
#                    Steht nicht in diesem Register und wird hier nicht beruehrt.
REGISTER = 'betrieb/faehigkeitsregister.json'
DATENKLASSEN = ('oeffentlich', 'intern', 'vertraulich')   # aufsteigend
REGISTERFELDER = ('datenklasse', 'anbieter', 'kostenquelle', 'ausweichweg',
                  'erlaubte_anbieter', 'angaben_stand')
# Kostenquelle: nur Verweise auf vorhandene Zahlenquellen, nie eine eigene Zahl.
KOSTENVERWEISE = {'kostenlaeufe': {'art'}, 'modellpreise': {'modell'},
                  'vertragsregister': {'anbieter'}, 'deckel': {'datei', 'feld'},
                  'keine': {'grund'}}
ERFOLGSQUELLEN = {'kostenlaeufe': {'art', 'status'}, 'auftragsabschluesse': {'ablauf'},
                  'verbindungen': {'schluessel'}}
ALTERSGRENZE_VORGABE = 30
VERALTET = 'veraltet — neu prüfen'


def _ohne_zahl(wert):
    """True, wenn nirgends eine Zahl steckt (bool zaehlt ebenfalls nicht als Verweis)."""
    if isinstance(wert, (bool, int, float)):
        return False
    if isinstance(wert, dict):
        return all(_ohne_zahl(v) for v in wert.values())
    if isinstance(wert, list):
        return all(_ohne_zahl(v) for v in wert)
    return isinstance(wert, str)


def _textliste(wert, feld, leer_erlaubt=True):
    if not isinstance(wert, list) or not all(isinstance(x, str) and x.strip() for x in wert):
        raise ValueError(feld + ' muss eine Liste von Texten sein')
    if not leer_erlaubt and not wert:
        raise ValueError(feld + ' darf nicht leer sein')
    return wert


def eintrag_pruefen(kennung, eintrag):
    """Prueft einen Registereintrag. Ungueltig heisst: er zaehlt als fehlend."""
    if not isinstance(eintrag, dict):
        raise ValueError('Eintrag ist kein Objekt')
    fehlt = [f for f in REGISTERFELDER + ('quelle',) if f not in eintrag]
    if fehlt:
        raise ValueError('Feld fehlt: ' + ', '.join(fehlt))
    if eintrag['datenklasse'] not in DATENKLASSEN:
        raise ValueError('Unbekannte Datenklasse')
    _textliste(eintrag['anbieter'], 'anbieter')
    _textliste(eintrag['erlaubte_anbieter'], 'erlaubte_anbieter')
    _textliste(eintrag['ausweichweg'], 'ausweichweg')
    if kennung in eintrag['ausweichweg']:
        raise ValueError('Eine Faehigkeit ist nie ihr eigener Ausweichweg')
    kosten = eintrag['kostenquelle']
    if not isinstance(kosten, list) or not kosten:
        raise ValueError('kostenquelle braucht mindestens einen Verweis')
    for v in kosten:
        if not isinstance(v, dict) or v.get('verweis') not in KOSTENVERWEISE:
            raise ValueError('Unbekannter Kostenverweis')
        if set(v) - {'verweis'} - KOSTENVERWEISE[v['verweis']]:
            raise ValueError('Kostenverweis mit fremdem Feld: ' + ', '.join(sorted(set(v) - {'verweis'} - KOSTENVERWEISE[v['verweis']])))
        if not _ohne_zahl(v):
            raise ValueError('Kostenquelle enthaelt eine Zahl; erlaubt sind nur Verweise')
    try:
        dt.date.fromisoformat(eintrag['angaben_stand'])
    except (TypeError, ValueError):
        raise ValueError('angaben_stand ist kein Datum JJJJ-MM-TT')
    quelle = eintrag['quelle']
    if not isinstance(quelle, dict) or not all(isinstance(quelle.get(f), str) and quelle[f].strip()
                                               for f in REGISTERFELDER if f != 'angaben_stand'):
        raise ValueError('quelle braucht je Angabe einen Text')
    for q in eintrag.get('erfolgsquellen', []) or []:
        if not isinstance(q, dict) or q.get('quelle') not in ERFOLGSQUELLEN or set(q) - {'quelle'} - ERFOLGSQUELLEN[q['quelle']]:
            raise ValueError('Ungueltige Erfolgsquelle')
    return eintrag


def register_lesen(root):
    """Liest die Steuerdatei. Fehlt sie oder ist ein Eintrag ungueltig, gilt er als
    nicht vorhanden (Felder null). Eine kaputte Datei erteilt nie etwas."""
    data = _lesen(Path(root)/REGISTER, None)
    raus = {'vorhanden': isinstance(data, dict), 'eintraege': {}, 'fehler': [],
            'altersgrenze_tage': ALTERSGRENZE_VORGABE, 'quelle': REGISTER}
    if not isinstance(data, dict):
        if (Path(root)/REGISTER).exists():
            raus['fehler'].append('Registerdatei nicht lesbar')
        return raus
    if data.get('schema') != 1:
        raus['fehler'].append('Unbekanntes Registerschema')
        return raus
    grenze = data.get('altersgrenze_tage')
    if type(grenze) is int and 1 <= grenze <= 365:
        raus['altersgrenze_tage'] = grenze
    else:
        raus['fehler'].append('altersgrenze_tage ungueltig; Vorgabe %d Tage' % ALTERSGRENZE_VORGABE)
    eintraege = data.get('faehigkeiten')
    if not isinstance(eintraege, dict):
        raus['fehler'].append('Abschnitt faehigkeiten fehlt')
        return raus
    for kennung, eintrag in eintraege.items():
        try:
            raus['eintraege'][kennung] = eintrag_pruefen(kennung, eintrag)
        except ValueError as fehler:
            raus['fehler'].append(str(kennung) + ': ' + str(fehler))
    return raus


def modellanbieter(root):
    """Leitet aus kostenstufen.json ab, welche MODELLanbieter je Datenklasse erlaubt
    sind. Nur aktive Anbieter; Zusatzanbieter nur mit eigener Datenklassenliste."""
    ks = _lesen(Path(root)/'betrieb/kostenstufen.json', {}) or {}
    stufen = ks.get('stufen') if isinstance(ks.get('stufen'), dict) else {}
    klassen = ks.get('datenklassen') if isinstance(ks.get('datenklassen'), dict) else {}
    alle, erlaubt = set(), {k: set() for k in DATENKLASSEN}
    for nr, stufe in stufen.items():
        if not isinstance(stufe, dict) or not isinstance(stufe.get('anbieter'), str):
            continue
        alle.add(stufe['anbieter'])
        offen = set()
        for dk in DATENKLASSEN:
            regel = klassen.get(dk) if isinstance(klassen.get(dk), dict) else {}
            if nr in (regel.get('erlaubt') or []) or (
                    ks.get('freigegeben') is True and nr in (regel.get('erlaubt_nach_freigabe') or [])):
                offen.add(dk)
        for dk in offen:
            erlaubt[dk].add(stufe['anbieter'])
        for name, zusatz in (stufe.get('weitere_anbieter') or {}).items():
            alle.add(name)
            if isinstance(zusatz, dict) and zusatz.get('aktiv') is True:
                for dk in set(zusatz.get('datenklassen') or stufe.get('datenklassen') or []) & offen:
                    erlaubt[dk].add(name)
    return {'alle': alle, 'erlaubt': erlaubt, 'quelle': 'betrieb/kostenstufen.json'}


def anbieter_erlaubt(anbieter, datenklasse, erlaubte, modell):
    """Ein Anbieter ist erlaubt, wenn das Register ihn nennt UND - falls er ein
    Modellanbieter ist - kostenstufen.json ihn fuer die Datenklasse zulaesst."""
    if anbieter not in erlaubte:
        return False, 'Anbieter ' + anbieter + ' steht nicht in erlaubte_anbieter'
    if anbieter in modell['alle'] and anbieter not in modell['erlaubt'].get(datenklasse, set()):
        return False, 'Anbieter ' + anbieter + ' ist laut kostenstufen.json fuer ' + datenklasse + ' nicht erlaubt oder nicht aktiv'
    return True, ''


def ausweichweg_pruefen(kennung, register, zeilen, modell):
    """Ein Ausweichweg zaehlt nur, wenn er im Register steht, ausfuehrbar ist und
    Datenklasse und Anbieter erlaubt sind. Ergebnis wird ANGEZEIGT, nie genutzt."""
    quelle = register['eintraege'].get(kennung)
    if quelle is None:
        return []
    raus = []
    for ziel in quelle['ausweichweg']:
        eintrag, zeile = register['eintraege'].get(ziel), zeilen.get(ziel)
        grund = ''
        if eintrag is None:
            grund = 'nicht im Faehigkeitsregister'
        elif zeile is None or not zeile.get('ausfuehrbar'):
            grund = 'nicht ausfuehrbar' + (': ' + zeile['hindernis'] if zeile and zeile.get('hindernis') else '')
        elif DATENKLASSEN.index(eintrag['datenklasse']) < DATENKLASSEN.index(quelle['datenklasse']):
            grund = 'Datenklasse ' + eintrag['datenklasse'] + ' reicht nicht fuer ' + quelle['datenklasse']
        else:
            for anbieter in eintrag['anbieter']:
                ok, warum = anbieter_erlaubt(anbieter, quelle['datenklasse'], quelle['erlaubte_anbieter'], modell)
                if not ok:
                    grund = warum
                    break
        raus.append({'kennung': ziel, 'erlaubt': not grund, 'grund': grund or 'erlaubt'})
    return raus


def _zeitpunkt(text):
    try:
        wert = dt.datetime.fromisoformat(str(text))
        return wert if wert.tzinfo else wert.astimezone()
    except (TypeError, ValueError):
        return None


_BUCH_CACHE = {}


def _kostenbuch(root):
    """Nur 'ende'-Zeilen des Kostenbuchs; zwischengespeichert bis sich die Datei aendert."""
    p = Path(root)/'betrieb/kostenlaeufe.jsonl'
    try:
        info = p.stat()
        if p.is_symlink() or info.st_size > 64_000_000:
            return []
    except OSError:
        return []
    schluessel = (str(p), info.st_mtime_ns, info.st_size)
    if _BUCH_CACHE.get('schluessel') != schluessel:
        zeilen = []
        with p.open(encoding='utf-8', errors='replace') as strom:
            for zeile in strom:
                if '"ende"' not in zeile:
                    continue
                try:
                    satz = json.loads(zeile)
                except ValueError:
                    continue
                if isinstance(satz, dict) and satz.get('ereignis') == 'ende':
                    zeilen.append({k: satz.get(k) for k in ('id', 'art', 'status', 'auftrag', 'zeit', 'ende', 'anbieter')})
        _BUCH_CACHE.clear()
        _BUCH_CACHE.update(schluessel=schluessel, zeilen=zeilen)
    return _BUCH_CACHE['zeilen']


def _annahmen(root):
    """Angenommene Auftraege (Quittung mit Urteil ANNAHME) samt Ablauf aus dem Vertrag."""
    root = Path(root)
    ablauf_je_kennung = {}
    for p in sorted((root/'betrieb/auftragsvertraege').glob('*.json')):
        v = _lesen(p, {}) or {}
        if isinstance(v, dict) and v.get('kennung'):
            ablauf_je_kennung[v['kennung']] = v.get('ablauf', 'arbeit')
    raus = []
    for p in sorted((root/'betrieb/auftragsabschluesse').glob('*.json')):
        q = _lesen(p, {}) or {}
        if not isinstance(q, dict) or q.get('urteil') != 'ANNAHME':
            continue
        kennung = p.name.split('_', 1)[0]
        zettel = str(q.get('pruefzettel') or '')
        if zettel.startswith(str(root) + '/'):
            zettel = zettel[len(str(root)) + 1:]
        raus.append({'zeit': q.get('zeit'), 'auftrag': q.get('datei'), 'ablauf': ablauf_je_kennung.get(kennung),
                     'beleg': 'betrieb/auftragsabschluesse/' + p.name, 'pruefzettel': zettel or None})
    return raus


def letzter_erfolg(root, eintrag, connections, heute=None, buch=None, annahmen=None):
    """Juengster belegter Erfolg aus den genannten Quellen. Liest nur, prueft nie selbst."""
    if eintrag is None:
        return None
    kandidaten = []
    for q in eintrag.get('erfolgsquellen') or []:
        if q['quelle'] == 'kostenlaeufe':
            arten, stati = set(q.get('art') or []), set(q.get('status') or ['ok'])
            for z in (buch if buch is not None else _kostenbuch(root)):
                if z.get('art') in arten and z.get('status') in stati:
                    kandidaten.append({'art': 'lauf_ok', 'zeit': z.get('ende') or z.get('zeit'),
                                       'auftrag': z.get('auftrag'), 'lauf_art': z.get('art'),
                                       'quelle': 'betrieb/kostenlaeufe.jsonl',
                                       'beleg': 'betrieb/kostenlaeufe.jsonl#id=' + str(z.get('id'))})
        elif q['quelle'] == 'auftragsabschluesse':
            for a in (annahmen if annahmen is not None else _annahmen(root)):
                if q.get('ablauf') and a['ablauf'] != q['ablauf']:
                    continue
                kandidaten.append({'art': 'auftrag_angenommen', 'zeit': a['zeit'], 'auftrag': a['auftrag'],
                                   'ablauf': a['ablauf'], 'quelle': 'betrieb/auftragsabschluesse',
                                   'beleg': a['beleg'], 'pruefzettel': a['pruefzettel']})
        elif q['quelle'] == 'verbindungen':
            v = connections.get(q.get('schluessel')) or {}
            if v.get('letzter_erfolg'):
                kandidaten.append({'art': 'verbindung_ok', 'zeit': v['letzter_erfolg'], 'auftrag': None,
                                   'quelle': 'betrieb/verbindungen.json',
                                   'beleg': 'betrieb/verbindungen.json#' + str(q.get('schluessel')),
                                   'geprueft': v.get('geprueft'), 'status': v.get('status')})
    kandidaten = [k for k in kandidaten if _zeitpunkt(k['zeit'])]
    if not kandidaten:
        return None
    best = max(kandidaten, key=lambda k: _zeitpunkt(k['zeit']))
    jetzt = heute or dt.datetime.now().astimezone()
    best['alter_tage'] = max(0, (jetzt - _zeitpunkt(best['zeit'])).days)
    return best


def _zugang(eintrag, connections, heute=None):
    """Live-Zugang aus verbindungen.json samt Alter der Pruefung - nur gelesen."""
    if eintrag is None:
        return None
    jetzt = heute or dt.datetime.now().astimezone()
    raus = []
    for q in eintrag.get('erfolgsquellen') or []:
        if q['quelle'] != 'verbindungen':
            continue
        v = connections.get(q.get('schluessel')) or {}
        geprueft = _zeitpunkt(v.get('geprueft'))
        raus.append({'schluessel': q.get('schluessel'), 'status': v.get('status', 'unbekannt'),
                     'geprueft': v.get('geprueft'),
                     'geprueft_alter_minuten': round((jetzt - geprueft).total_seconds() / 60) if geprueft else None,
                     'quelle': 'betrieb/verbindungen.json (Verbindungswaechter, 5-Minuten-Takt)'})
    return raus or None


def _register_ergaenzen(root, rows, connections, heute=None):
    """M2-M5: jede Zeile bekommt die Registerfelder. Fehlt ein Eintrag, stehen die
    Felder auf null und 'ausfuehrbar' bleibt genau wie bisher."""
    register = register_lesen(root)
    modell = modellanbieter(root)
    jetzt = heute or dt.datetime.now().astimezone()
    zeilen = {r['kennung']: r for r in rows}
    buch = _kostenbuch(root)
    annahmen = _annahmen(root)
    for r in rows:
        e = register['eintraege'].get(r['kennung'])
        for feld in REGISTERFELDER:
            r[feld] = e[feld] if e else None
        r['registereintrag'] = e is not None
        r['angaben_quelle'] = e['quelle'] if e else None
        if e:
            alter = (jetzt.date() - dt.date.fromisoformat(e['angaben_stand'])).days
            r['angaben_alter_tage'] = alter
            r['angaben_veraltet'] = alter > register['altersgrenze_tage']
            r['angaben_hinweis'] = VERALTET if r['angaben_veraltet'] else ''
            eigene = [anbieter_erlaubt(a, e['datenklasse'], e['erlaubte_anbieter'], modell) for a in e['anbieter']]
            r['anbieter_hinweis'] = '; '.join(w for ok, w in eigene if not ok)
        else:
            r['angaben_alter_tage'] = r['angaben_veraltet'] = None
            r['angaben_hinweis'] = 'kein Registereintrag'
            r['anbieter_hinweis'] = ''
        r['letzter_erfolg'] = letzter_erfolg(root, e, connections, jetzt, buch, annahmen)
        r['letzter_erfolg_hinweis'] = ('' if r['letzter_erfolg'] else
                                       'nicht belegt' + (': ' + e['quelle'].get('erfolgsquellen', '')
                                                         if e and isinstance(e['quelle'].get('erfolgsquellen'), str) else ''))
        r['zugang'] = _zugang(e, connections, jetzt)
    for r in rows:
        r['ausweichweg_pruefung'] = ausweichweg_pruefen(r['kennung'], register, zeilen, modell)
        r['ausweichweg_vorhanden'] = any(w['erlaubt'] for w in r['ausweichweg_pruefung'])
    return {'datei': REGISTER, 'vorhanden': register['vorhanden'], 'fehler': register['fehler'],
            'altersgrenze_tage': register['altersgrenze_tage'],
            'automatischer_wechsel': False,
            'hinweis': 'Werkzeugwahl nur anzeigend: ein erlaubter Ausweichweg wird gemeldet, nie selbst genutzt. '
                       'Ausweichweg (Faehigkeit) ist nicht die Rueckfallkette (Modell).'}


# Ein Ablauf konkretisiert Pruefpunkte, erweitert aber keine Befugnisse.
ABLAEUFE = {
    'arbeit': {'name':'Interner Auftrag', 'braucht':['arbeit'], 'pflichtpunkte':[]},
    'recherche': {'name':'Recherche und begruendete Wahl', 'braucht':['arbeit','ablage','web'], 'pflichtpunkte':[
        'Aktuelle Tatsachen und Vergleichsdaten nennen nachvollziehbare Originalquellen mit Abrufdatum; offene Annahmen sind gekennzeichnet.',
        'Die Empfehlung begruendet Eignung, Qualitaet, gesamte Kosten und Nachteile anhand der Anforderungen; kein pauschales Bestes ohne Vergleich.',
        # F-4 (M6): die Empfehlung als pruefbares Objekt. Die lokale Vorpruefung
        # (jack_auftrag.lokale_vorpruefung) sperrt den Prueferstart, solange es fehlt
        # oder unvollstaendig ist. Nur neue Vertraege tragen diesen Punkt.
        'Das Recherche-Objekt liegt als JSON-Datei (Schema 1, Aufbau in auftraege/README_AUFTRAEGE.md, Abschnitt Werkzeugwahl) als Beleg dieses Punkts vor und enthaelt Kriterienliste, Quellen mit Abrufdatum, mindestens zwei verglichene Optionen und die Empfehlung mit Eignung, Qualitaet, Gesamtkosten und Nachteilen.']},
    'content': {'name':'Text und Skript fertigstellen', 'braucht':['arbeit','ablage'], 'pflichtpunkte':[
        'Die Endfassung erfuellt Marke, Zielgruppe, Zweck und verlangtes Format; sie ist als nutzbare Datei abgelegt.',
        'Fakten, Quellen und fremde Inhalte sind geprueft oder offen gekennzeichnet; keine erfundenen Leistungs- oder Erfolgsversprechen.']},
    'video': {'name':'Fertiges Video erzeugen und pruefen', 'braucht':['arbeit','medien_erzeugen'], 'pflichtpunkte':[
        'Briefing, Skript und Szenenfolge decken alle beauftragten Aussagen und Markenanforderungen ab.',
        'Das fertige Video ist abspielbar; Bild, Ton, Untertitel, Dauer und Zielformat sind am tatsaechlichen Export geprueft. Nutzungsrechte und Quelldateien sind dokumentiert.']},
    'software': {'name':'Software implementieren und abnehmen', 'braucht':['arbeit','software_ausfuehren'], 'pflichtpunkte':[
        'Die Aenderung erfuellt jeden vereinbarten Anwendungsfall; relevante Tests und der reale Bedienweg sind belegt.',
        'Auslieferung und Rueckweg sind dokumentiert. Eine lokale Pruefung wird nicht als bestandene Produktionsabnahme ausgegeben.']},
    'veroeffentlichen': {'name':'Im beauftragten Kanal veroeffentlichen', 'braucht':['arbeit','publizieren'], 'pflichtpunkte':[
        'Konkrete Endfassung, Marke, Konto, Zielkanal und Handlung sind vom Auftrag oder einer gueltigen Freigabe gedeckt.',
        'Ein eindeutiger Vorgang verhindert doppelte Veroeffentlichung. Die tatsaechliche Ziel-URL mit richtigem Inhalt und Sichtbarkeit ist nach dem Abschluss geprueft.']},
}


def ablauf(name):
    if not isinstance(name,str) or name not in ABLAEUFE:
        raise ValueError('Unbekannter Arbeitsablauf')
    return ABLAEUFE[name]


RECHERCHE_PFLICHTPUNKT = ABLAEUFE['recherche']['pflichtpunkte'][2]


def vorpruefung(root, name, register=None, motor='api'):
    wanted = ablauf(name)
    register = stand(root, motor=motor) if register is None else register
    rows = {r['kennung']:r for r in register['faehigkeiten']}
    blocks = []
    for key in wanted['braucht']:
        row = rows.get(key)
        if not row or not row['ausfuehrbar']:
            # F-4 (M4): melden, ob ein ERLAUBTER Ausweichweg bestuende. Gewechselt
            # wird nie - die Zeile bleibt blockiert, der Auftrag wartet.
            wege = [w['kennung'] for w in (row or {}).get('ausweichweg_pruefung') or [] if w['erlaubt']]
            blocks.append({'faehigkeit':key, 'grund':row['hindernis'] if row else 'Nicht im Faehigkeitsregister',
                           'ausweichweg_vorhanden':bool(wege), 'ausweichweg':wege})
    # F-4 (M5): veraltete Angaben nur melden, nie sperren.
    hinweise = ['%s: %s (Stand %s)' % (k, VERALTET, rows[k].get('angaben_stand'))
                for k in wanted['braucht'] if rows.get(k) and rows[k].get('angaben_veraltet')]
    text = ('; '.join(b['grund'] + ' · Ausweichweg vorhanden: ' + ('ja (' + ', '.join(b['ausweichweg']) + '; nicht gewechselt)'
                                                                   if b['ausweichweg_vorhanden'] else 'nein')
                      for b in blocks)
            or 'Dienstwege vorhanden; Rechte, Budget und Ergebnis werden weiterhin einzeln geprueft.')
    if hinweise:
        text += ' Hinweis: ' + '; '.join(hinweise) + '.'
    return {'ablauf':name, 'ausfuehrbar':not blocks, 'blockaden':blocks, 'hinweise':hinweise,
            'ausweichweg_vorhanden':any(b['ausweichweg_vorhanden'] for b in blocks) if blocks else None,
            'automatischer_wechsel':False, 'text':text}


# ════════ Spiegel in betrieb/README_WERKZEUGE_JACK.md (F-4, T11) ═════════════
# Regen-Muster wie 11_Lieferanten (jack_vertraege.markdown_schreiben): die
# Maschinenform ist massgeblich, die Markdown-Tabelle wird daraus neu erzeugt.
# Ersetzt wird NUR der markierte Block; der handgefuehrte Teil bleibt stehen.
SPIEGEL = 'betrieb/README_WERKZEUGE_JACK.md'
SPIEGEL_ANFANG = '<!-- FAEHIGKEITSREGISTER-SPIEGEL ANFANG — erzeugt aus betrieb/faehigkeitsregister.json, nicht von Hand aendern -->'
SPIEGEL_ENDE = '<!-- FAEHIGKEITSREGISTER-SPIEGEL ENDE -->'


def _zelle(wert):
    return str(wert).replace('|', '/').replace('\n', ' ')


def spiegel_text(root):
    register = register_lesen(root)
    kosten = lambda k: 'keine' if k['verweis'] == 'keine' else k['verweis'] + ': ' + ', '.join(
        '/'.join(v) if isinstance(v, list) else v for f, v in k.items() if f != 'verweis')
    zeilen = ['| Fähigkeit | Datenklasse | Anbieter | Kostenquelle (Verweise) | Ausweichweg | Erlaubte Anbieter | Stand |',
              '|---|---|---|---|---|---|---|']
    for kennung, e in register['eintraege'].items():
        zeilen.append('| ' + ' | '.join(_zelle(x) for x in (
            kennung, e['datenklasse'], ', '.join(e['anbieter']) or '—', ' · '.join(kosten(k) for k in e['kostenquelle']),
            ', '.join(e['ausweichweg']) or 'keiner', ', '.join(e['erlaubte_anbieter']) or '—', e['angaben_stand'])) + ' |')
    return '\n'.join([SPIEGEL_ANFANG, '',
                      '**Fähigkeitsregister (gespiegelt).** Maschinenform: `betrieb/faehigkeitsregister.json` (Steuerdatei). '
                      'Neu erzeugen: `/usr/bin/python3 jack_faehigkeiten.py --spiegeln`. Live-Werte (ausführbar, letzter Erfolg, '
                      'Alter, Ausweichweg-Prüfung) stehen unter `/arbeitsfaehigkeit` und im Kasten „Agenten". Altersgrenze: %d Tage.'
                      % register['altersgrenze_tage'], ''] + zeilen +
                     (['', 'Registerfehler: ' + '; '.join(register['fehler'])] if register['fehler'] else []) +
                     ['', 'Gespiegelt: ' + dt.datetime.now().astimezone().strftime('%d.%m.%Y, %H:%M Uhr'), '', SPIEGEL_ENDE])


def spiegel_schreiben(root):
    """Ersetzt den markierten Block. Fehlen die Marken, wird nichts geschrieben."""
    ziel = Path(root)/SPIEGEL
    alt = ziel.read_text(encoding='utf-8')
    if alt.count(SPIEGEL_ANFANG) != 1 or alt.count(SPIEGEL_ENDE) != 1 or alt.index(SPIEGEL_ANFANG) > alt.index(SPIEGEL_ENDE):
        raise ValueError('Spiegelmarken fehlen oder sind doppelt; nichts geschrieben')
    kopf, rest = alt.split(SPIEGEL_ANFANG, 1)
    neu = kopf + spiegel_text(root) + rest.split(SPIEGEL_ENDE, 1)[1]
    tmp = ziel.with_name(ziel.name + '.neu')
    tmp.write_text(neu, encoding='utf-8')
    os.replace(tmp, ziel)
    return str(ziel)


# ════════ M6: Recherche-Objekt (F-4, 24.09.2026) ═════════════════════════════
# Die Empfehlung einer Recherche ist ein pruefbares Objekt, kein Fliesstext.
# Hier wird nur die VOLLSTAENDIGKEIT geprueft; ob die Empfehlung fachlich traegt,
# entscheidet weiterhin der unabhaengige Pruefer (Tor 2). Kein Anbieter wird hier
# gewaehlt.
EMPFEHLUNG_FELDER = ('eignung', 'qualitaet', 'gesamtkosten', 'begruendung')


def recherche_pruefen(obj, heute=None):
    fehlt = []
    heute = heute or dt.date.today()
    text = lambda v, n=3: isinstance(v, str) and len(v.strip()) >= n
    if not isinstance(obj, dict):
        return {'vollstaendig': False, 'fehlend': ['Recherche-Objekt ist kein JSON-Objekt']}
    if obj.get('schema') != 1:
        fehlt.append('schema muss 1 sein')
    if not text(obj.get('frage'), 10):
        fehlt.append('frage fehlt')
    kriterien = obj.get('kriterien') if isinstance(obj.get('kriterien'), list) else []
    k_ids = [k.get('kennung') for k in kriterien if isinstance(k, dict)]
    if len(kriterien) < 2 or len(set(k_ids)) != len(kriterien) or not all(
            isinstance(k, dict) and text(k.get('kennung'), 1) and text(k.get('name')) and text(k.get('beschreibung'))
            for k in kriterien):
        fehlt.append('kriterien: mindestens zwei, je kennung, name und beschreibung, Kennungen eindeutig')
    quellen = obj.get('quellen') if isinstance(obj.get('quellen'), list) else []
    q_ids = set()
    if not quellen:
        fehlt.append('quellen fehlen')
    for i, q in enumerate(quellen):
        if not isinstance(q, dict) or not text(q.get('kennung'), 1) or not text(q.get('titel')):
            fehlt.append('quelle %d: kennung und titel' % (i + 1)); continue
        q_ids.add(q['kennung'])
        if not (isinstance(q.get('url'), str) and q['url'].startswith(('https://', 'http://'))):
            fehlt.append('quelle %s: url (http/https)' % q['kennung'])
        try:
            abruf = dt.date.fromisoformat(str(q.get('abgerufen_am')))
            if abruf > heute:
                fehlt.append('quelle %s: abgerufen_am liegt in der Zukunft' % q['kennung'])
        except ValueError:
            fehlt.append('quelle %s: abgerufen_am als Datum JJJJ-MM-TT' % q['kennung'])
    optionen = obj.get('optionen') if isinstance(obj.get('optionen'), list) else []
    namen = [o.get('name') for o in optionen if isinstance(o, dict)]
    if len(optionen) < 2 or len(set(namen)) != len(optionen):
        fehlt.append('optionen: mindestens zwei verschiedene verglichene Optionen')
    for o in optionen:
        if not isinstance(o, dict) or not text(o.get('name'), 1):
            continue
        bewertung = o.get('bewertung') if isinstance(o.get('bewertung'), dict) else {}
        ohne = [k for k in k_ids if not text(bewertung.get(k), 2)]
        if ohne:
            fehlt.append('option %s: Bewertung fehlt fuer %s' % (o['name'], ', '.join(map(str, ohne))))
        refs = o.get('quellen') if isinstance(o.get('quellen'), list) else []
        if not refs or not set(refs) <= q_ids:
            fehlt.append('option %s: quellen muessen vorhandene Quellkennungen nennen' % o['name'])
    e = obj.get('empfehlung') if isinstance(obj.get('empfehlung'), dict) else None
    if e is None:
        fehlt.append('empfehlung fehlt')
    else:
        if e.get('option') not in namen:
            fehlt.append('empfehlung.option muss eine der verglichenen Optionen sein')
        for f in EMPFEHLUNG_FELDER:
            if not text(e.get(f)):
                fehlt.append('empfehlung.' + f + ' fehlt')
        nachteile = e.get('nachteile')
        if not isinstance(nachteile, list) or not nachteile or not all(text(n) for n in nachteile):
            fehlt.append('empfehlung.nachteile: mindestens ein Nachteil')
        refs = e.get('quellen') if isinstance(e.get('quellen'), list) else []
        if not refs or not set(refs) <= q_ids:
            fehlt.append('empfehlung.quellen muessen vorhandene Quellkennungen nennen')
    if not isinstance(obj.get('annahmen'), list) or not all(text(a) for a in obj.get('annahmen') or []):
        fehlt.append('annahmen: Liste (leer erlaubt), offene Annahmen gekennzeichnet')
    return {'vollstaendig': not fehlt, 'fehlend': fehlt,
            'kriterien': len(kriterien), 'quellen': len(quellen), 'optionen': len(optionen)}


if __name__ == '__main__':
    import sys
    if sys.argv[1:] != ['--spiegeln']:
        raise SystemExit('Erlaubt: --spiegeln')
    print(spiegel_schreiben(Path(__file__).resolve().parent))
