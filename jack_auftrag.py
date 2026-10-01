"""Unveraenderliche Auftragsanforderungen und belegte Einzelabschluesse.

Kein Modell, keine Netzverbindung und keine Ausfuehrung fremder Befehle.
Der Dienst schreibt Vertraege unter betrieb/; der Arbeiter darf sie nur lesen.
Eine Datei als Beleg beweist ihren Inhalt nicht: die fachliche Annahme bleibt
Aufgabe des unabhaengigen Pruefers. Seine Annahme bindet den Ergebnisstand.
"""
import datetime as dt
import hashlib
import json
import os
import re
import stat
import uuid
from pathlib import Path

SCHEMA = 1
# Paket 1 "Vollstaendiger Auftrag" (F-1, 24.09.2026): Schema 2 kommt hinzu,
# Schema 1 bleibt unveraendert gueltig. Kein Altvertrag wird umgeschrieben.
SCHEMA_2 = 2
SCHEMATA = (SCHEMA, SCHEMA_2)
MAX_BELEG_BYTES = 64 * 1024 * 1024
MAX_GESAMT_BYTES = 256 * 1024 * 1024
GRUPPEN = ('offen', 'laeuft', 'freigabe', 'erledigt', 'problem', 'zurueckgestellt')
_ANNAHME_CACHE = {}


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _text(value, name, maximum=20000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or '\x00' in value:
        raise ValueError(name + ' fehlt, ist ungueltig oder zu lang')
    return value.strip()


def _dateiname(name):
    if not isinstance(name, str) or not re.fullmatch(r'[^./\\\x00-\x1f][^/\\\x00-\x1f]*\.md', name) or len(name) > 220:
        raise ValueError('Ein einfacher Auftragsdateiname ist erforderlich')
    return name


def _neu(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())


def _vertragspfad(root, name):
    return Path(root) / 'betrieb' / 'auftragsvertraege' / (_hash(_dateiname(name).encode()) + '.json')


def _vorpruefungspfad(root, name):
    return Path(root) / 'betrieb' / 'auftragsvorpruefungen' / (_hash(_dateiname(name).encode()) + '.json')


def _wortgrenzen_abgleichen(rules, points):
    """Klare numerische Obergrenzen duerfen nicht durch fehlende Regeln verschwinden."""
    for point in points:
        limits = {int(n) for n in re.findall(
            r'\b(?:höchstens|hoechstens|maximal|max\.?|bis zu)\s+([0-9]+)\s+W(?:ö|oe)rter(?:n)?\b',
            point['text'], re.I)}
        matching = [r for r in rules if r['pflichtpunkt'] == point['kennung']]
        if limits and (len(limits) != 1 or not matching
                       or any(r['max_woerter'] not in limits for r in matching)):
            raise ValueError(point['kennung'] + ': Wortgrenze braucht passende lokale_pruefungen '
                             '(Datei und max_woerter); verschiedene Grenzen in eigene Pflichtpunkte aufteilen')


def _pruefregeln(raw, points):
    """Explizite Vorgaben statt geratener Regeln aus freiem Auftragsprosa."""
    if not isinstance(raw, list) or len(raw) > 40:
        raise ValueError('Lokale Pruefungen brauchen eine Liste mit hoechstens 40 Regeln')
    ids = {p['kennung'] for p in points}
    result, seen = [], set()
    for rule in raw:
        if not isinstance(rule, dict) or set(rule) != {'pflichtpunkt', 'datei', 'max_woerter'}:
            raise ValueError('Wortregel braucht pflichtpunkt, datei und max_woerter')
        path = _text(rule['datei'], 'Datei der Wortregel', 1200)
        p = Path(path)
        if (p.is_absolute() or '..' in p.parts or p.as_posix() != path
                or '\\' in path or ':' in path or p.suffix.lower() not in ('.md', '.txt')
                or any(ord(c) < 32 for c in path)):
            raise ValueError('Wortregel braucht einen kanonischen .md/.txt-Pfad relativ zur Holding')
        if not isinstance(rule['pflichtpunkt'], str) or rule['pflichtpunkt'] not in ids:
            raise ValueError('Wortregel nennt keinen verbindlichen Pflichtpunkt')
        if type(rule['max_woerter']) is not int or not 1 <= rule['max_woerter'] <= 200000:
            raise ValueError('Wortgrenze muss eine ganze Zahl zwischen 1 und 200000 sein')
        if path.casefold() in seen:
            raise ValueError('Wortregel fuer dieselbe Datei doppelt')
        seen.add(path.casefold())
        result.append(dict(rule))
    return result


def _lokale_regeln(root, vertrag, digest):
    rules = _pruefregeln(vertrag.get('lokale_pruefungen', []), vertrag['pflichtpunkte'])
    path = _vorpruefungspfad(root, vertrag['datei'])
    extra_hash = None
    if path.exists() or path.is_symlink():
        if path.stat().st_size > 150000:
            raise ValueError('Ergaenzte Vorpruefung ist zu gross')
        vault = Path(root).resolve().parent.parent
        record = _beleg(vault, path.relative_to(vault).as_posix())
        raw = path.read_bytes()
        if _hash(raw) != record['sha256']:
            raise ValueError('Vorpruefung wurde waehrend des Lesens veraendert')
        data = json.loads(raw)
        if (not isinstance(data, dict) or data.get('schema') != 1 or data.get('vertrag_sha256') != digest
                or data.get('datei') != vertrag['datei']):
            raise ValueError('Ergaenzte Vorpruefung gehoert nicht zum unveraenderten Vertrag')
        rules += _pruefregeln(data.get('regeln'), vertrag['pflichtpunkte'])
        extra_hash = record['sha256']
    rules = _pruefregeln(rules, vertrag['pflichtpunkte'])
    _wortgrenzen_abgleichen(rules, vertrag['pflichtpunkte'])
    return rules, extra_hash


def vorpruefung_festlegen(root, name, regeln, quelle):
    """Einmalige interne Ergaenzung fuer bestehende Vertraege; kein Arbeiterwerkzeug."""
    root = Path(root).resolve()
    checked = lesen(root, name)
    if checked is None:
        raise ValueError('Gebundener Auftrag erforderlich')
    vertrag, digest = checked
    if quittung(root, vertrag) is not None:
        raise ValueError('Bereits angenommene Auftraege erhalten keine neuen Regeln')
    path = _vorpruefungspfad(root, name)
    if path.exists() or path.is_symlink():
        raise ValueError('Ergaenzte Vorpruefung besteht bereits')
    old = _pruefregeln(vertrag.get('lokale_pruefungen', []), vertrag['pflichtpunkte'])
    rules = _pruefregeln(regeln, vertrag['pflichtpunkte'])
    if not rules:
        raise ValueError('Mindestens eine lokale Regel erforderlich')
    _pruefregeln(old + rules, vertrag['pflichtpunkte'])
    _wortgrenzen_abgleichen(old + rules, vertrag['pflichtpunkte'])
    data = {'schema': 1, 'datei': name, 'vertrag_sha256': digest,
            'regeln': rules, 'quelle': _text(quelle, 'Regelquelle', 2000),
            'zeit': dt.datetime.now().astimezone().isoformat()}
    _neu(_vorpruefungspfad(root, name), _json(data) + '\n')
    return data


def name_belegt(root, name):
    paths = [_vertragspfad(root, name)] + [Path(root)/'auftraege'/g/name for g in GRUPPEN]
    return any(p.exists() or p.is_symlink() for p in paths)


def kopf(text):
    lines = text.splitlines()
    if not lines or lines[0] != '---':
        raise ValueError('Auftragskopf fehlt')
    result = {}
    for line in lines[1:]:
        if line == '---':
            return result
        key, sep, value = line.partition(':')
        if not sep or key.strip() in result:
            raise ValueError('Auftragskopf ist ungueltig')
        result[key.strip()] = value.strip()
    raise ValueError('Auftragskopf ist nicht abgeschlossen')


def abschnitt(text, title):
    matches = list(re.finditer(r'^## ' + re.escape(title) + r'[ \t]*\n(.*?)(?=^## |\Z)', text, re.M | re.S))
    if len(matches) != 1:
        raise ValueError('Genau ein Abschnitt ' + title + ' ist erforderlich')
    return matches[0][1].strip()


def _pflichtpunkte(eingabe):
    raw = eingabe.get('pflichtpunkte')
    if raw is None:
        raw = [re.sub(r'^\s*(?:[-*]|\d+[.)])\s+', '', s).strip()
               for s in _text(eingabe.get('pruefpunkte'), 'Pruefpunkte').splitlines() if s.strip()]
    if not isinstance(raw, list) or not 1 <= len(raw) <= 40:
        raise ValueError('Ein bis 40 einzelne Pflichtpunkte sind erforderlich')
    points = [_text(p, 'Pflichtpunkt', 1800) for p in raw]
    if len(set(p.casefold() for p in points)) != len(points):
        raise ValueError('Pflichtpunkte duerfen sich nicht doppeln')
    return [{'kennung': 'P%02d' % (i+1), 'text': p} for i, p in enumerate(points)]


# Pflichtfelder fuer Videoauftraege (Auftrag Videobetrieb Teil 1, P03, 23.09.2026).
# Drei Gruppen, weil sie unterschiedlich geprueft werden: kurze Einzeiler,
# laengerer Fliesstext (Botschaft/Rechte duerfen mehrere Saetze sein) und
# Listen (mehrere Quellen/Konten/Ausgangsdateien moeglich).
VIDEO_TEXTFELDER = ('ziel', 'inhaltsmarke', 'ceo', 'zielgruppe', 'sprache',
                     'format', 'dauer', 'termin', 'kostenobergrenze',
                     'veroeffentlichungsbefugnis')
VIDEO_FLIESSTEXTFELDER = ('botschaft', 'handlungsaufforderung', 'rechte')
VIDEO_LISTENFELDER = ('ausgangsmaterial', 'quellen', 'zielkonten')
VIDEO_FELDER = VIDEO_TEXTFELDER + VIDEO_FLIESSTEXTFELDER + VIDEO_LISTENFELDER


def _video_ceo_aus_konfiguration(root, marke):
    """Bestehende Zuordnung Marke->CEO aus betrieb/videoproduktion.json lesen,
    damit sie bei einem Videoauftrag nicht erneut erfragt werden muss."""
    try:
        import jack_videoproduktion
        konfiguration = jack_videoproduktion._laden(root)
        treffer = [n for n in konfiguration.get('marken', {}) if n.casefold() == str(marke).casefold()]
        if len(treffer) == 1:
            eintrag = konfiguration['marken'][treffer[0]]
            ceo = eintrag.get('ceo') if isinstance(eintrag, dict) else None
            if isinstance(ceo, str) and ceo:
                return ceo
    except (OSError, ValueError, KeyError):
        pass
    return None


def _video_leitbild_hinweis(marke):
    """Bereits getroffene Markenentscheidungen zu PLHH/Triade automatisch
    anhaengen statt sie bei jedem Videoauftrag neu abzufragen. Bewusst eng:
    nur die zwei belegten Faelle; jede andere Marke bekommt den
    Holding-Regelfall (PLHH gilt), keine geratene Sonderregel."""
    if str(marke).casefold() == 'cashflow_kompass':
        return ('CASHFLOW_KOMPASS hat eine eigene Marken-DNA: PLHH und die Triade '
                'NATUR-TIER-MENSCH gelten hier ausdruecklich NICHT (Quelle: '
                '00_Marken/CASHFLOW_KOMPASS/2026-09-15_CLAUDECODE_CASHFLOW_Digitaler-CEO.md, '
                'Abschnitt "MARKEN-DNA — GILT NUR HIER").')
    return ('Holding-Leitbild PLHH (Peace, Love & Harmony for more Humanity) und die '
            'Triade NATUR-TIER-MENSCH gelten (CLAUDE.md/AGENTS.md Abschnitt A3); keine '
            'bekannte markenspezifische Ausnahme.')


def _video_felder(root, marke, eingabe_video):
    """Prueft, ergaenzt und normalisiert die Pflichtfelder eines Videoauftrags.
    Fehlt ein Feld und laesst es sich nicht aus einer bereits getroffenen
    Markenentscheidung ableiten, loest das eine echte Rueckfrage aus (ValueError) -
    es wird nichts geraten."""
    if not isinstance(eingabe_video, dict):
        raise ValueError('Videoauftrag braucht die Pflichtfelder unter "video": ' + ', '.join(VIDEO_FELDER))
    werte = dict(eingabe_video)
    if not werte.get('inhaltsmarke'):
        werte['inhaltsmarke'] = marke
    if not werte.get('ceo'):
        automatisch = _video_ceo_aus_konfiguration(root, marke)
        if automatisch:
            werte['ceo'] = automatisch
    ergebnis = {}
    for feld in VIDEO_TEXTFELDER:
        ergebnis[feld] = _text(werte.get(feld), 'Videofeld ' + feld, 300)
    for feld in VIDEO_FLIESSTEXTFELDER:
        ergebnis[feld] = _text(werte.get(feld), 'Videofeld ' + feld, 4000)
    for feld in VIDEO_LISTENFELDER:
        raw = werte.get(feld)
        if not isinstance(raw, list) or not 1 <= len(raw) <= 20:
            raise ValueError('Videofeld ' + feld + ' braucht eine Liste mit 1 bis 20 Eintraegen')
        ergebnis[feld] = [_text(item, 'Videofeld ' + feld, 400) for item in raw]
    ergebnis['leitbild_hinweis'] = _video_leitbild_hinweis(marke)
    # Wie bei beschreibung/pruefpunkte (siehe anlegen()): kein eigener
    # ##-Abschnitt im Feldinhalt, sonst liest abschnitt() den Videoauftrag beim
    # spaeteren Pruefen falsch ab.
    flach = list(ergebnis[f] for f in VIDEO_TEXTFELDER + VIDEO_FLIESSTEXTFELDER)
    for feld in VIDEO_LISTENFELDER:
        flach.extend(ergebnis[feld])
    if any(re.search(r'^## ', wert, re.M) for wert in flach):
        raise ValueError('Videofelder duerfen keine eigenen ##-Abschnitte enthalten')
    return ergebnis


def _video_abschnitt(video):
    """Rendert die Pflichtfelder als Abschnitt des sichtbaren Auftrags. Dieselbe
    Funktion erzeugt den Text beim Anlegen UND bei jeder spaeteren Pruefung -
    beide Seiten koennen so nie auseinanderlaufen."""
    zeilen = []
    beschriftung = {
        'ziel': 'Ziel', 'inhaltsmarke': 'Inhaltsmarke', 'ceo': 'CEO',
        'zielgruppe': 'Zielgruppe', 'botschaft': 'Botschaft',
        'handlungsaufforderung': 'Handlungsaufforderung', 'sprache': 'Sprache',
        'format': 'Format', 'dauer': 'Dauer', 'ausgangsmaterial': 'Ausgangsmaterial',
        'rechte': 'Rechte', 'quellen': 'Quellen', 'zielkonten': 'Zielkonten',
        'termin': 'Termin', 'kostenobergrenze': 'Kostenobergrenze',
        'veroeffentlichungsbefugnis': 'Veröffentlichungsbefugnis',
    }
    for feld in VIDEO_TEXTFELDER + VIDEO_FLIESSTEXTFELDER:
        zeilen.append('**' + beschriftung[feld] + ':** ' + video[feld])
    for feld in VIDEO_LISTENFELDER:
        zeilen.append('**' + beschriftung[feld] + ':**')
        zeilen.extend('- ' + item for item in video[feld])
    zeilen.append('**Leitbild-Hinweis (automatisch geladen):** ' + video['leitbild_hinweis'])
    return '\n'.join(zeilen)


# Schema 2 (Paket 1, F-1, 24.09.2026): zehn Rahmenfelder; das elfte Feld sind die
# bestehenden Pflichtpunkte. Jedes Feld steht im geschuetzten Vertrag UND als eigener
# ##-Abschnitt "Rahmen: <Titel>" im Auftrag; pruefe_auftrag() vergleicht beides.
# Der Praefix haelt die Ueberschriften von Arbeitsabschnitten wie "## Ziel" fern.
# M7 (Patron, 24.09.2026, gestaffelt): Pflicht sind alle zehn Felder bei tiefe mittel/gross
# ODER gefahr aussen; bei tiefe klein UND gefahr keine bleiben sie optional.
RAHMEN_FELDER = ('ziel', 'ausgangslage', 'zustaendigkeit', 'werkzeuge', 'kostenrahmen',
                 'qualitaetsmassstab', 'freigaben_noetig', 'pruefkriterien', 'ablageort', 'rueckweg')
RAHMEN_LISTENFELDER = ('werkzeuge', 'freigaben_noetig', 'pruefkriterien')
RAHMEN_TITEL = {'ziel': 'Ziel', 'ausgangslage': 'Ausgangslage', 'zustaendigkeit': 'Zuständigkeit',
                'werkzeuge': 'Werkzeuge', 'kostenrahmen': 'Kostenrahmen',
                'qualitaetsmassstab': 'Qualitätsmaßstab', 'freigaben_noetig': 'Nötige Freigaben',
                'pruefkriterien': 'Prüfkriterien', 'ablageort': 'Ablageort', 'rueckweg': 'Rückweg'}
RAHMEN_MAX_ZEICHEN = 2000
RAHMEN_MAX_EINTRAEGE = 20
RAHMEN_NICHT_ANGEGEBEN = '(nicht angegeben)'
# Quelle eines Wertes, der nicht woertlich aus dem Rahmenfeld des Auftrags stammt.
RAHMEN_QUELLEN = {'video': '(übernommen aus den Videofeldern dieses Auftrags)',
                  'standard': '(Standardweg; im Auftrag nicht gesondert angegeben)'}
# Bei ablauf video werden diese Werte uebernommen und nicht doppelt erfragt.
# Ein zusaetzlich angegebenes Rahmenfeld muss den Videowert enthalten.
RAHMEN_AUS_VIDEO = (('ziel', 'ziel'), ('kostenrahmen', 'kostenobergrenze'),
                    ('freigaben_noetig', 'veroeffentlichungsbefugnis'), ('zustaendigkeit', 'ceo'))


RAHMEN_PFLICHT_TIEFEN = ('mittel', 'gross')


class RahmenFehlt(ValueError):
    """Pflicht-Rahmenfelder fehlen beim Anlegen; .fehlend nennt sie (fuer die Rueckfrage im Gespraech)."""
    def __init__(self, meldung, fehlend):
        super().__init__(meldung)
        self.fehlend = fehlend


class RechercheTiefe(ValueError):
    """Ablauf recherche mit Tiefe klein: abgewiesen (F-5, 24.09.2026; Nr. 122 scheiterte an der API-Grenze 0,75 USD)."""


RECHERCHE_MIN_TIEFE_TEXT = ('Recherche braucht Tiefe mittel oder gross: bei Tiefe klein reicht die technische API-Grenze '
                            '(0,75 USD) nicht fuer Seitenabruf und Pruefer (Nr. 122, 24.09.2026). Nichts angelegt.')


def rahmen_pflicht(tiefe, gefahr):
    """M7 gestaffelt: True, wenn alle zehn Rahmenfelder Pflicht sind."""
    return tiefe in RAHMEN_PFLICHT_TIEFEN or gefahr == 'aussen'


def rahmen_pflicht_text(tiefe, gefahr):
    """Klartext fuer Gespraech und Fehlermeldung."""
    if rahmen_pflicht(tiefe, gefahr):
        return ('Fuer tiefe ' + str(tiefe) + ' und gefahr ' + str(gefahr) + ' sind alle '
                + str(len(RAHMEN_FELDER)) + ' Rahmenfelder Pflicht (tiefe mittel/gross oder gefahr aussen): '
                + ', '.join(RAHMEN_FELDER))
    return ('Fuer tiefe klein und gefahr keine sind die Rahmenfelder optional: '
            + ', '.join(RAHMEN_FELDER))


def rahmen_fehlend(eingabe, video=None):
    """Rahmenfelder, die weder angegeben noch aus den Videofeldern gedeckt sind."""
    gedeckt = {f for f, _ in RAHMEN_AUS_VIDEO} if video is not None else set()
    return [f for f in RAHMEN_FELDER if not _angegeben(eingabe.get(f)) and f not in gedeckt]


def rahmen_titel(feld):
    return 'Rahmen: ' + RAHMEN_TITEL[feld]


def _angegeben(wert):
    return wert is not None and wert != '' and wert != []


def _rahmenwert(feld, wert):
    """Ein Rahmenfeld pruefen: Text bis 2.000 Zeichen oder Liste mit 1-20 Eintraegen."""
    name = 'Auftragsfeld ' + feld
    if feld in RAHMEN_LISTENFELDER:
        if not isinstance(wert, list) or not 1 <= len(wert) <= RAHMEN_MAX_EINTRAEGE:
            raise ValueError(name + ' braucht eine Liste mit 1 bis 20 Eintraegen')
        eintraege = []
        for item in wert:
            if not isinstance(item, str) or '\n' in item or '\r' in item:
                raise ValueError(name + ': jeder Eintrag ist eine einzelne Textzeile')
            eintraege.append(_text(item, name, RAHMEN_MAX_ZEICHEN))
        if sum(len(e) for e in eintraege) > RAHMEN_MAX_ZEICHEN:
            raise ValueError(name + ' ist laenger als 2000 Zeichen')
        if len(set(e.casefold() for e in eintraege)) != len(eintraege):
            raise ValueError(name + ': Eintraege duerfen sich nicht doppeln')
        return eintraege
    if not isinstance(wert, str):
        raise ValueError(name + ' muss Text sein')
    # Beim Lesen wandelt Python \r in \n; der Vergleich mit dem Vertrag bliebe sonst
    # dauerhaft ungleich.
    wert = _text(wert.replace('\r\n', '\n').replace('\r', '\n'), name, RAHMEN_MAX_ZEICHEN)
    if re.search(r'^## ', wert, re.M):
        raise ValueError(name + ' darf keine eigenen ##-Abschnitte enthalten')
    return wert


def _rahmen_standard_rueckweg(max_versuche):
    return ('Standardweg: höchstens %d Arbeitsversuch(e); danach wird der Auftrag unter '
            'auftraege/problem/ abgelegt und dem Patron gemeldet. Bestehende Dateien werden vor '
            'jeder Änderung automatisch unter betrieb/dateisicherungen/<Laufkennung>/ gesichert; '
            'gelöscht wird nichts.' % max_versuche)


def _rahmen_felder(eingabe, video, max_versuche):
    """Schema-2-Felder bilden. None, wenn kein Rahmenfeld mitkommt (dann Schema 1)."""
    if not any(_angegeben(eingabe.get(f)) for f in RAHMEN_FELDER):
        return None
    werte = {f: (_rahmenwert(f, eingabe[f]) if _angegeben(eingabe.get(f)) else None)
             for f in RAHMEN_FELDER}
    quellen = {}
    if video is not None:
        for feld, videofeld in RAHMEN_AUS_VIDEO:
            vorgabe = video[videofeld]
            if werte[feld] is None:
                if feld == 'freigaben_noetig':
                    werte[feld] = ['Veröffentlichungsbefugnis: ' + vorgabe]
                elif feld == 'zustaendigkeit':
                    werte[feld] = 'CEO: ' + vorgabe
                else:
                    werte[feld] = vorgabe
                quellen[feld] = 'video'
                continue
            gesamt = ' '.join(werte[feld]) if isinstance(werte[feld], list) else werte[feld]
            if ' '.join(vorgabe.split()).casefold() not in ' '.join(gesamt.split()).casefold():
                raise ValueError('Auftragsfeld ' + feld + ' widerspricht dem Videofeld ' + videofeld
                                 + ' ("' + vorgabe[:80] + '"); nur einmal angeben')
    if werte['rueckweg'] is None:
        werte['rueckweg'] = _rahmen_standard_rueckweg(max_versuche)
        quellen['rueckweg'] = 'standard'
    return werte, quellen


def rahmen_abschnitt(vertrag, feld):
    """Inhalt des Abschnitts "Rahmen: <Titel>". Dieselbe Funktion erzeugt den Text
    beim Anlegen und bei jeder spaeteren Pruefung."""
    wert = vertrag.get(feld)
    if wert is None:
        return RAHMEN_NICHT_ANGEGEBEN
    text = '\n'.join('- ' + e for e in wert) if isinstance(wert, list) else wert
    quelle = (vertrag.get('rahmen_quellen') or {}).get(feld)
    return text + ('\n\n' + RAHMEN_QUELLEN[quelle] if quelle else '')


def _rahmen_pruefen(data):
    """Vertragsseite: Schema 2 braucht alle zehn Schluessel, Schema 1 keinen davon."""
    vorhanden = [f for f in RAHMEN_FELDER + ('rahmen_quellen',) if f in data]
    if data.get('schema') == SCHEMA:
        if vorhanden:
            raise ValueError('Schema-1-Vertrag enthaelt Schema-2-Felder')
        return
    fehlend = [f for f in RAHMEN_FELDER if f not in data]
    if fehlend:
        raise ValueError('Schema-2-Vertrag ohne Feld ' + ', '.join(fehlend))
    for feld in RAHMEN_FELDER:
        if data[feld] is not None and _rahmenwert(feld, data[feld]) != data[feld]:
            raise ValueError('Schema-2-Vertragsfeld ' + feld + ' ist nicht normalisiert')
    quellen = data.get('rahmen_quellen')
    if (not isinstance(quellen, dict) or any(k not in RAHMEN_FELDER or v not in RAHMEN_QUELLEN
                                             or data.get(k) is None for k, v in quellen.items())):
        raise ValueError('Schema-2-Vertrag hat ungueltige Feldquellen')
    if not any(data[f] is not None and f not in quellen for f in RAHMEN_FELDER):
        raise ValueError('Schema-2-Vertrag ohne eigenes Rahmenfeld')
    # M7: nur Schema 2 wird gestaffelt geprueft; Altvertraege (Schema 1) bleiben unangetastet.
    if rahmen_pflicht(data.get('tiefe'), data.get('gefahr')):
        leer = [f for f in RAHMEN_FELDER if data[f] is None]
        if leer:
            raise ValueError('Schema-2-Vertrag tiefe ' + str(data.get('tiefe')) + ' / gefahr '
                             + str(data.get('gefahr')) + ' braucht alle Rahmenfelder; es fehlen: '
                             + ', '.join(leer))


LERNHINWEIS_FELDER = ('kennung', 'regel', 'hinweis', 'n', 'letzter', 'belege')


def _lernhinweise_pruefen(liste):
    """F-20: Vertragsfeld lernhinweise - hoechstens 3, feste Form, Hinweistext nach der Regel-Zeichenmenge."""
    import jack_lernen
    if not isinstance(liste, list) or len(liste) > jack_lernen.MAX_HINWEISE:
        raise ValueError('Vertragsfeld lernhinweise ist ungueltig')
    for nr, h in enumerate(liste, 1):
        if (not isinstance(h, dict) or tuple(sorted(h)) != tuple(sorted(LERNHINWEIS_FELDER))
                or h['kennung'] != 'L%d' % nr or not re.fullmatch(r'R\d{2}', str(h['regel']))
                or not jack_lernen.hinweis_gueltig(h['hinweis'])
                or type(h['n']) is not int or h['n'] < 1
                or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(h['letzter']))
                or not isinstance(h['belege'], list) or len(h['belege']) > 3
                or not all(re.fullmatch(r'[0-9a-f]{32}', str(b)) for b in h['belege'])):
            raise ValueError('Lernhinweis %d im Vertrag ist ungueltig' % nr)
    return liste


def lernhinweise_abschnitt(liste):
    """Inhalt des Abschnitts '## Lernhinweise' - dieselbe Funktion beim Anlegen und bei jeder Pruefung."""
    if not liste:
        return '- keine: keine freigegebene Regel ist fuer diese Marke und diesen Ablauf belegt.'
    return '\n'.join('- %s (Regel %s, %d belegte Läufe, zuletzt %s): %s' % (
        h['kennung'], h['regel'], h['n'], h['letzter'], h['hinweis']) for h in liste)


def rahmenstand(vertrag):
    """Anzeige: Altauftraege sind nicht fehlerhaft, ihre Felder wurden nur nie erfasst."""
    if vertrag is None or vertrag.get('schema') != SCHEMA_2:
        return {'schema': vertrag.get('schema', SCHEMA) if vertrag else None,
                'text': 'Altauftrag — Felder nicht erfasst'}
    quellen = vertrag.get('rahmen_quellen') or {}
    angegeben = [f for f in RAHMEN_FELDER if vertrag.get(f) is not None and f not in quellen]
    return {'schema': SCHEMA_2, 'angegeben': angegeben, 'ergaenzt': sorted(quellen),
            'text': 'Vollständiger Auftrag: %d/%d Rahmenfelder angegeben, %d automatisch ergänzt'
                    % (len(angegeben), len(RAHMEN_FELDER), len(quellen))}


def anlegen(root, datei, eingabe, original='', herkunft=None):
    """Nur der Dienst ruft dies nach erkannter Beauftragung auf, nie der Arbeiter."""
    if herkunft in ('test', 'probe', 'simulation'):
        raise ValueError('Ein Testgespraech legt keine echten Auftraege an')
    root, datei = Path(root).resolve(), Path(datei)
    if datei.parent.resolve() != root / 'auftraege' / 'offen':
        raise ValueError('Neue Auftraege gehoeren nach auftraege/offen/')
    name = _dateiname(datei.name)
    if datei.exists() or datei.is_symlink():
        raise ValueError('Auftragsdatei besteht bereits')
    for field in ('marke', 'auftrag', 'tiefe', 'gefahr'):
        _text(eingabe.get(field), field, 180)
        if '\n' in eingabe[field] or '\r' in eingabe[field]:
            raise ValueError('Kopfwerte muessen einzeilig sein')
    if eingabe['tiefe'] not in ('klein', 'mittel', 'gross') or eingabe['gefahr'] not in ('keine', 'aussen'):
        raise ValueError('Auftragstiefe oder Gefahr ist ungueltig')
    import jack_faehigkeiten
    ablauf = eingabe.get('ablauf', 'arbeit')
    if ablauf == 'recherche' and eingabe['tiefe'] == 'klein':
        raise RechercheTiefe(RECHERCHE_MIN_TIEFE_TEXT)
    vorlage = jack_faehigkeiten.ablauf(ablauf)
    if ablauf == 'veroeffentlichen' and eingabe['gefahr'] != 'aussen':
        raise ValueError('Veroeffentlichen ist eine Aussenaktion und braucht gefahr: aussen')
    points = _pflichtpunkte(eingabe)
    for extra in vorlage['pflichtpunkte']:
        if extra not in [p['text'] for p in points]:
            points.append({'kennung':'P%02d' % (len(points)+1), 'text':extra})
    if len(points) > 40:
        raise ValueError('Mit Qualitaetskriterien mehr als 40 Pflichtpunkte; Auftrag aufteilen')
    video_felder = _video_felder(root, eingabe['marke'], eingabe.get('video')) if ablauf == 'video' else None
    if rahmen_pflicht(eingabe['tiefe'], eingabe['gefahr']):
        fehlend = rahmen_fehlend(eingabe, video_felder)
        if fehlend:
            raise RahmenFehlt('Rahmenfelder fehlen: ' + ', '.join(f + ' (' + RAHMEN_TITEL[f] + ')' for f in fehlend)
                              + '. ' + rahmen_pflicht_text(eingabe['tiefe'], eingabe['gefahr']), fehlend)
    vertrag = {
        'schema': SCHEMA, 'kennung': uuid.uuid4().hex, 'datei': name,
        'zeit': dt.datetime.now().astimezone().isoformat(),
        'marke': eingabe['marke'], 'auftrag': eingabe['auftrag'],
        'beschreibung': _text(eingabe.get('was'), 'Auftrag'),
        'original': original if original else eingabe['was'],
        'originalquelle': 'Patron-Gespraech' if original else 'Auftragsbeschreibung',
        'pruefpunkte': _text(eingabe.get('pruefpunkte'), 'Pruefpunkte'),
        'pflichtpunkte': points, 'ablauf': ablauf,
        'tiefe': eingabe['tiefe'], 'gefahr': eingabe['gefahr'],
    }
    if video_felder is not None:
        vertrag['video'] = video_felder
    if 'max_versuche' in eingabe:
        limit = eingabe['max_versuche']
        if type(limit) is not int or limit not in (1, 2):
            raise ValueError('Maximale Versuche muessen 1 oder 2 sein')
        vertrag['max_versuche'] = limit
    if 'lokale_pruefungen' in eingabe:
        vertrag['lokale_pruefungen'] = _pruefregeln(eingabe['lokale_pruefungen'], points)
    _wortgrenzen_abgleichen(vertrag.get('lokale_pruefungen', []), points)
    rahmen = _rahmen_felder(eingabe, video_felder, vertrag.get('max_versuche', 2))
    if rahmen is not None:
        vertrag['schema'] = SCHEMA_2
        vertrag.update(rahmen[0])
        vertrag['rahmen_quellen'] = rahmen[1]
    # F-20 (Paket 6): bis zu 3 Lernhinweise, nur aus der freigegebenen Regelliste, im Vertrag gebunden.
    # Ein Fehler hier verhindert nie den Auftrag; er bekommt dann einfach keine Hinweise.
    try:
        import jack_lernen
        lernhinweise = jack_lernen.fuer_vertrag(root, eingabe['marke'], ablauf)
    except Exception:
        lernhinweise = None
    if lernhinweise is not None:        # None = keine Regelliste vorhanden (Altverhalten, z. B. Wegwerf-Tests)
        vertrag['lernhinweise'] = _lernhinweise_pruefen(lernhinweise)
    _text(vertrag['original'], 'Originalauftrag', 50000)
    if any(re.search(r'^## ', vertrag[key], re.M) for key in ('beschreibung', 'pruefpunkte')):
        raise ValueError('Auftragsbeschreibung und Pruefpunkte duerfen keine eigenen ##-Abschnitte enthalten; einfache Absätze oder ### verwenden')
    encoded = _json(vertrag) + '\n'
    if rahmen is not None and len(encoded.encode()) > 150000:
        raise ValueError('Auftragsvertrag waere groesser als 150000 Byte; Auftrag aufteilen')
    vertrags_hash = _hash(encoded.encode())
    vertragsquelle = _vertragspfad(root, name).relative_to(root.parent.parent).as_posix()
    videoabschnitt = ('## Videoauftrag\n' + _video_abschnitt(video_felder) + '\n\n') if video_felder is not None else ''
    if 'lernhinweise' in vertrag:
        videoabschnitt += '## Lernhinweise\n' + lernhinweise_abschnitt(vertrag['lernhinweise']) + '\n\n'
    rahmenabschnitte = ''.join('## ' + rahmen_titel(f) + '\n' + rahmen_abschnitt(vertrag, f) + '\n\n'
                               for f in RAHMEN_FELDER) if rahmen is not None else ''
    order = ('---\nmarke:      {marke}\nauftrag:    {auftrag}\n'
             'erteilt:    {zeit}\nvon:        Patron\nstatus:     offen\n'
             'freigabe:   nein\ngefahr:     {gefahr}\ntiefe:      {tiefe}\nablauf:     {ablauf}\n'
             + ('schema:     2\n' if rahmen is not None else '') +
             'besetzung:  0\nvertrag:    {kennung}\nvertrag_sha256: {sha}\nvertragsquelle: {quelle}\n---\n\n'
             '## Auftrag\n{beschreibung}\n\n## Prüfpunkte\n{pruefpunkte}\n\n'
             '{rahmenabschnitte}'
             '{videoabschnitt}'
             '## Verbindliche Pflichtpunkte\n{punkte}\n\n'
             '## Lauf\n(füllt der ausführende CEO)\n\n'
             '## Ergebnis\n(füllt der Arbeiter)\n\n'
             '## Nachweis\n(Dateien, Pfade, Belege — keine Behauptung ohne Beleg)\n\n'
             '## Pflichtpunktnachweise\n```json\n{vorlage}\n```\n').format(
                 **vertrag, sha=vertrags_hash, quelle=vertragsquelle, videoabschnitt=videoabschnitt,
                 rahmenabschnitte=rahmenabschnitte,
                 punkte='\n'.join('- '+p['kennung']+': '+p['text'] for p in vertrag['pflichtpunkte']),
                 vorlage=json.dumps([{'kennung': p['kennung'], 'status': 'offen', 'ergebnis': '', 'belege': []}
                                      for p in vertrag['pflichtpunkte']], ensure_ascii=False, indent=2))
    if 'max_versuche' in vertrag:
        order = order.replace('besetzung:  0\n', 'besetzung:  0\nmax_versuche: '+str(vertrag['max_versuche'])+'\n', 1)
    # Erst der geschuetzte Vertrag, dann der sichtbare Auftrag. Ein verwaister
    # Vertrag startet nichts. Es wird nie ein bestehender Auftrag ersetzt.
    _neu(_vertragspfad(root, name), encoded)
    _neu(datei, order)
    return vertrag


def lesen(root, name):
    path = _vertragspfad(root, name)
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 150000:
        raise ValueError('Auftragsvertrag nicht sicher lesbar')
    raw = path.read_bytes()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError('Auftragsvertrag ist kein Objekt')
    if data.get('schema') not in SCHEMATA or type(data.get('schema')) is not int or data.get('datei') != name:
        raise ValueError('Auftragsvertrag passt nicht zur Datei')
    _rahmen_pruefen(data)
    if not re.fullmatch(r'[0-9a-f]{32}', str(data.get('kennung', ''))):
        raise ValueError('Auftragskennung ungueltig')
    for key in ('marke', 'auftrag', 'beschreibung', 'original', 'pruefpunkte', 'ablauf', 'tiefe', 'gefahr'):
        _text(data.get(key), 'Vertragsfeld '+key, 50000)
    points = data.get('pflichtpunkte')
    if not isinstance(points, list) or not 1 <= len(points) <= 40:
        raise ValueError('Verbindliche Pflichtpunkte fehlen im Vertrag')
    for index, point in enumerate(points, 1):
        if not isinstance(point, dict) or point.get('kennung') != 'P%02d' % index:
            raise ValueError('Vertrag hat ungueltige Pflichtpunktkennungen')
        _text(point.get('text'), 'Vertragspflichtpunkt', 1800)
    _pruefregeln(data.get('lokale_pruefungen', []), points)
    if data.get('ablauf') == 'video':
        video = data.get('video')
        if not isinstance(video, dict):
            raise ValueError('Videoauftrag ohne gespeicherte Pflichtfelder')
        for feld in VIDEO_TEXTFELDER + VIDEO_FLIESSTEXTFELDER:
            _text(video.get(feld), 'Vertrags-Videofeld ' + feld, 4000)
        for feld in VIDEO_LISTENFELDER:
            eintraege = video.get(feld)
            if not isinstance(eintraege, list) or not 1 <= len(eintraege) <= 20:
                raise ValueError('Vertrags-Videofeld ' + feld + ' ist ungueltig')
            for item in eintraege:
                _text(item, 'Vertrags-Videofeld ' + feld, 400)
        _text(video.get('leitbild_hinweis'), 'Vertrags-Videofeld leitbild_hinweis', 2000)
    if 'lernhinweise' in data:
        _lernhinweise_pruefen(data['lernhinweise'])
    return data, _hash(raw)


def pruefe_auftrag(root, datei):
    datei = Path(datei)
    if datei.is_symlink() or not datei.is_file() or datei.stat().st_size > 500000:
        raise ValueError('Auftrag nicht sicher lesbar')
    text = datei.read_text(encoding='utf-8')
    fields = kopf(text)
    stored = lesen(root, datei.name)
    if stored is None:
        if fields.get('vertrag') or fields.get('vertrag_sha256'):
            raise ValueError('Geschuetzter Auftragsvertrag fehlt')
        return None
    vertrag, digest = stored
    if fields.get('vertrag') != vertrag['kennung'] or fields.get('vertrag_sha256') != digest:
        raise ValueError('Auftragsbindung wurde entfernt oder veraendert')
    if fields.get('vertragsquelle') != _vertragspfad(Path(root).resolve(), datei.name).relative_to(Path(root).resolve().parent.parent).as_posix():
        raise ValueError('Quelle des geschuetzten Vertrags wurde veraendert')
    for key in ('marke', 'gefahr', 'auftrag', 'ablauf'):
        if fields.get(key) != vertrag[key]:
            raise ValueError('Geschuetztes Auftragsfeld veraendert: ' + key)
    if 'max_versuche' in vertrag:
        if type(vertrag['max_versuche']) is not int or vertrag['max_versuche'] not in (1, 2):
            raise ValueError('Ungueltige geschuetzte Versuchsgrenze')
        if fields.get('max_versuche') != str(vertrag['max_versuche']):
            raise ValueError('Geschuetzte Versuchsgrenze wurde veraendert')
    for title, key in (('Auftrag', 'beschreibung'), ('Prüfpunkte', 'pruefpunkte')):
        if abschnitt(text, title) != vertrag[key]:
            raise ValueError('Geschuetzter Auftragsinhalt veraendert: ' + title)
    points = '\n'.join('- '+p['kennung']+': '+p['text'] for p in vertrag['pflichtpunkte'])
    if abschnitt(text, 'Verbindliche Pflichtpunkte') != points:
        raise ValueError('Pflichtpunkte wurden veraendert')
    if vertrag.get('ablauf') == 'video':
        if abschnitt(text, 'Videoauftrag') != _video_abschnitt(vertrag['video']):
            raise ValueError('Geschuetzter Auftragsinhalt veraendert: Videoauftrag')
    # F-20: Lernhinweise gelten nur aus dem Vertrag; ein selbst eingefuegter Abschnitt ist eine Aenderung.
    if 'lernhinweise' in vertrag:
        try:
            gleich = abschnitt(text, 'Lernhinweise') == lernhinweise_abschnitt(vertrag['lernhinweise'])
        except ValueError:
            gleich = False
        if not gleich:
            raise ValueError('Geschuetzter Auftragsinhalt veraendert: Lernhinweise')
    elif re.search(r'^## Lernhinweise[ \t]*$', text, re.M):
        raise ValueError('Lernhinweise ohne Vertragsbindung sind unzulaessig')
    # Schema 2: Kopfzeile und alle zehn Rahmenabschnitte. Massgeblich ist das Schema
    # im geschuetzten Vertrag, nie die Kopfzeile; Schema 1 prueft wie bisher.
    if vertrag['schema'] == SCHEMA_2:
        if fields.get('schema') != str(SCHEMA_2):
            raise ValueError('Schema im Auftragskopf passt nicht zum Vertrag')
        # Ein Rahmenwert im Kopf saehe gueltig aus, ist aber nicht gebunden.
        schatten = sorted(set(fields) & set(RAHMEN_FELDER))
        if schatten:
            raise ValueError('Rahmenfeld gehoert nicht in den Auftragskopf: ' + ', '.join(schatten))
        for feld in RAHMEN_FELDER:
            try:
                inhalt = abschnitt(text, rahmen_titel(feld))
            except ValueError:
                raise ValueError('Pflichtabschnitt fehlt oder ist doppelt: ' + rahmen_titel(feld)) from None
            if inhalt != rahmen_abschnitt(vertrag, feld):
                raise ValueError('Geschuetzter Auftragsinhalt veraendert: ' + rahmen_titel(feld))
    elif fields.get('schema', str(SCHEMA)) != str(SCHEMA):
        raise ValueError('Schema im Auftragskopf passt nicht zum Vertrag')
    return vertrag, digest, text


def versuchslimit(root, datei):
    """Auftrag darf die bestehende Grenze nur verringern; Fehler sperren."""
    checked = pruefe_auftrag(root, datei)
    return checked[0].get('max_versuche', 2) if checked else 2


def _nachweise(text):
    body = abschnitt(text, 'Pflichtpunktnachweise')
    match = re.fullmatch(r'```json\s*\n(.*?)\n```', body, re.S)
    if not match:
        raise ValueError('Pflichtpunktnachweise muessen genau einen JSON-Block enthalten')
    data = json.loads(match[1])
    if not isinstance(data, list) or len(data) > 40 or any(not isinstance(p, dict) for p in data):
        raise ValueError('Pflichtpunktnachweise sind keine gueltige Liste')
    return data


def _beleg(vault, raw):
    vault = Path(vault).resolve()
    raw = _text(raw, 'Belegpfad', 1200)
    p = Path(raw)
    if p.is_absolute() or '..' in p.parts or '\\' in raw or ':' in raw:
        raise ValueError('Belegpfad muss relativ zur Holding sein')
    lower = [s.casefold() for s in p.parts]
    if any(s in ('.git', '.claude', '.codex', 'secrets', '__pycache__', 'node_modules') or s.endswith('.nosync') for s in lower):
        raise ValueError('Interne Laufzeit- oder Schluesseldatei ist kein Ergebnisbeleg')
    if 'auftragsvertraege' in lower or 'auftragsabschluesse' in lower or 'tor2' in lower:
        raise ValueError('Auftrag und Annahme selbst ersetzen keinen Ergebnisbeleg')
    if p.name.casefold().startswith('.env') or p.name.casefold() in ('schluessel.txt', 'settings.local.json') or p.suffix.casefold() in ('.key', '.pem', '.p12'):
        raise ValueError('Schluesseldatei ist kein Ergebnisbeleg')
    target = vault / p
    if any(x.is_symlink() for x in [target, *target.parents] if x != vault and vault in x.parents):
        raise ValueError('Belegpfad darf keinen Verweis enthalten; kanonischen Pfad verwenden')
    target = target.resolve()
    if vault not in target.parents:
        raise ValueError('Beleg liegt ausserhalb der Holding')
    fd = os.open(target, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= MAX_BELEG_BYTES:
            raise ValueError('Beleg ist leer, keine normale Datei oder groesser als 64 MiB')
        h = hashlib.sha256()
        read = 0
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            read += len(chunk)
            if read > MAX_BELEG_BYTES:
                raise ValueError('Beleg waechst waehrend der Pruefung')
            h.update(chunk)
        after = os.fstat(stream.fileno())
    current = target.stat()
    signature = lambda st: (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
    if signature(before) != signature(after) or signature(after) != signature(current):
        raise ValueError('Beleg wurde waehrend der Pruefung veraendert')
    record = {'pfad': target.relative_to(vault).as_posix(), 'sha256': h.hexdigest(), 'bytes': read}
    if tuple(x.casefold() for x in target.relative_to(vault).parts[:4]) == ('00_marken','jack','betrieb','medienpruefungen'):
        import jack_medien
        record['medienquelle'] = jack_medien.nachweis_pruefen(vault/'00_Marken/JACK', target)
    return record


def snapshot(root, datei, vault=None):
    """Vollstaendige eingereichte Nachweise; noch KEINE fachliche Annahme."""
    root = Path(root).resolve()
    vault = Path(vault).resolve() if vault else root.parent.parent
    checked = pruefe_auftrag(root, datei)
    if checked is None:
        return None
    vertrag, digest, text = checked
    rows = _nachweise(text)
    ids = [p.get('kennung') for p in rows]
    required = [p['kennung'] for p in vertrag['pflichtpunkte']]
    if len(set(str(p) for p in ids)) != len(ids) or sorted(str(p) for p in ids) != sorted(required):
        raise ValueError('Jeder verbindliche Pflichtpunkt braucht genau einen Nachweis')
    files, outcomes = {}, []
    for row in rows:
        # Einreichung ist noch keine unabhaengige Annahme. Insbesondere die
        # verlangte Pruefung selbst darf vor ihrem Start nicht als erledigt gelten.
        if row.get('status') not in ('erfuellt', 'pruefbereit'):
            raise ValueError('Pflichtpunkt ' + str(row.get('kennung')) + ' ist nicht erfuellt')
        result = _text(row.get('ergebnis'), 'Ergebnis des Pflichtpunkts', 3000)
        paths = row.get('belege')
        if not isinstance(paths, list) or not 1 <= len(paths) <= 8:
            raise ValueError('Pflichtpunkt braucht ein bis acht konkrete Belegdateien')
        for raw in paths:
            if not isinstance(raw, str):
                raise ValueError('Belegpfad muss Text sein')
            if raw not in files:
                if len(files) >= 40:
                    raise ValueError('Mehr als 40 Belegdateien; Auftrag aufteilen')
                files[raw] = _beleg(vault, raw)
                if Path(vault / files[raw]['pfad']).resolve() == Path(datei).resolve():
                    raise ValueError('Der Auftrag selbst ist kein unabhaengiger Ergebnisbeleg')
                if sum(f['bytes'] for f in files.values()) > MAX_GESAMT_BYTES:
                    raise ValueError('Belegumfang ueber 256 MiB; gezielten Pruefbericht verwenden')
        outcomes.append({'kennung': row['kennung'], 'ergebnis': result,
                         'belege': sorted(files[p]['pfad'] for p in paths)})
    content = {'vertrag_sha256': digest, 'kennung': vertrag['kennung'],
               'ergebnis': abschnitt(text, 'Ergebnis'), 'nachweis': abschnitt(text, 'Nachweis'),
               'pflichtpunkte': sorted(outcomes, key=lambda x: x['kennung']),
               'dateien': sorted(files.values(), key=lambda x: x['pfad'])}
    _, extra_hash = _lokale_regeln(root, vertrag, digest)
    if extra_hash:
        content['vorpruefung_sha256'] = extra_hash
    return {'sha256': _hash(_json(content).encode()), **content}


def _sperrfall_protokollieren(root, datei, errors, stand):
    """Jede Sperre kostenlos festhalten; ein Schreibfehler darf die Sperre nie kippen."""
    try:
        arten = sorted({'zu_lang' if 'erlaubt ' in e else 'unvollstaendig' for e in errors})
        eintrag = {'zeit': dt.datetime.now().astimezone().isoformat(), 'auftrag': Path(datei).name,
                   'arten': arten, 'gruende': errors,
                   'ergebnisstand_sha256': stand['sha256'] if stand else None}
        pfad = Path(root) / 'betrieb' / 'vorpruefung_sperren.jsonl'
        vergleich = {k: eintrag[k] for k in ('auftrag', 'gruende', 'ergebnisstand_sha256')}
        if pfad.is_file():
            with pfad.open('rb') as f:
                f.seek(0, os.SEEK_END)
                f.seek(max(0, f.tell() - 65536))
                zeilen = f.read().decode('utf-8', 'replace').splitlines()
            if zeilen:
                letzte = json.loads(zeilen[-1])
                if all(letzte.get(k) == v for k, v in vergleich.items()):
                    return
        pfad.parent.mkdir(parents=True, exist_ok=True)
        with pfad.open('a', encoding='utf-8') as f:
            f.write(json.dumps(eintrag, ensure_ascii=False, sort_keys=True) + '\n')
    except (OSError, ValueError, TypeError, KeyError):
        pass


# ════════ Wortzahl aus dem Code (F-6, 24.09.2026) ═══════════════════════════
# Befund aus F-5 (Nr. 123): Die Fachkraft schrieb "189 Woerter", gemessen wurden
# 209. Massgeblich ist NUR die Zaehlung der lokalen Vorpruefung; das Limit
# gilt gegen den gemessenen Wert. Eine abweichende Modellangabe (mehr als 5 %)
# wird ignoriert und als Vermerk protokolliert - sie sperrt nichts.
WORTZAHL_TOLERANZ = 0.05
_WORTZAHL_ANGABE = re.compile(r'(?<![\d.,])(\d{1,6})\s+(?:W(?:oe|\u00f6)rter[nr]?|Worte[nr]?|words?)\b', re.I)


def _abschnitt_oder_leer(text, title):
    try:
        return abschnitt(text, title)
    except ValueError:
        return ''


def wortzahl_angaben(text):
    """Alle vom Modell genannten Wortzahlen (Zahl vor 'Woerter/Worte/words') in text."""
    return [int(m[1]) for m in _WORTZAHL_ANGABE.finditer(text or '')]


def wortzahl_vermerke(text, counts):
    """Vermerke fuer Modellangaben, die um mehr als 5 % von ALLEN Messwerten abweichen.

    Angaben, die dem erlaubten Limit einer Regel entsprechen, sind keine
    Ergebnis-Zaehlung und werden nicht bewertet. Ohne Messwert kein Vermerk."""
    if not counts:
        return []
    gemessen = [c['ist'] for c in counts]
    limits = {c['max_woerter'] for c in counts}
    vermerke = []
    for angabe in sorted(set(wortzahl_angaben(text))):
        if angabe in limits:
            continue
        if any(abs(angabe - ist) <= WORTZAHL_TOLERANZ * ist for ist in gemessen):
            continue
        nah = min(gemessen, key=lambda ist: abs(angabe - ist))
        abw = abs(angabe - nah) / nah * 100 if nah else 100.0
        grenze = next((c['max_woerter'] for c in counts if c['ist'] == nah), None)
        vermerke.append({'angegeben': angabe, 'gemessen': nah, 'abweichung_prozent': round(abw, 1),
                         'limit': grenze,
                         'text': 'Wortzahl-Angabe %d ignoriert, gemessen %d (%.1f %% Abweichung, ueber 5 %%); '
                                 'das Limit %s gilt gegen %d.' % (angabe, nah, abw, grenze, nah)})
    return vermerke


# ════════ F-11 (Paket 4, P04): Zahlen gegen die Messung - entscheidungstragend sperrt ═══════
# Befund Nr. 124 (Paket 3): Ergebnis und Pflichtpunktnachweis P01 nannten "67 Woerter", gemessen waren 75.
# Der Pruefer nahm trotzdem an ("Abweichung ohne Auswirkung"). PM-Entscheidung 24.09.2026: eine Zahl, die
# von der Messung abweicht, sperrt die Annahme, wenn sie in einer ENTSCHEIDUNGSTRAGENDEN Aussage steht:
#   - im Abschnitt "Ergebnis" (das, was als Ergebnis gemeldet wird), oder
#   - im Nachweis ("ergebnis") eines Pflichtpunkts, fuer den eine lokale Wortregel gilt.
# Angaben in "Lauf"/"Nachweis" bleiben ein Vermerk (F-6). Toleranz wie F-6: 5 %.
def zahlen_abweichungen(text, counts):
    """Liste der entscheidungstragenden Wortzahl-Angaben, die von der Messung abweichen (leer = ok)."""
    if not counts:
        return []
    teile = [('Abschnitt Ergebnis', _abschnitt_oder_leer(text, 'Ergebnis'), counts)]
    try:
        zeilen = _nachweise(text)
    except (ValueError, TypeError):
        zeilen = []
    for zeile in zeilen:
        eigene = [c for c in counts if c.get('pflichtpunkt') == zeile.get('kennung')]
        if eigene and isinstance(zeile.get('ergebnis'), str):
            teile.append(('Pflichtpunktnachweis ' + str(zeile['kennung']), zeile['ergebnis'], eigene))
    raus = []
    for stelle, inhalt, messwerte in teile:
        for v in wortzahl_vermerke(inhalt, messwerte):
            raus.append({**v, 'stelle': stelle,
                         'text': '%s nennt %d Woerter, gemessen %d (%.1f %% Abweichung)'
                                 % (stelle, v['angegeben'], v['gemessen'], v['abweichung_prozent'])})
    return raus


def _vermerk_protokollieren(root, datei, vermerke, stand):
    """Vermerke kostenlos festhalten (betrieb/wortzahl_vermerke.jsonl). Nie werfen."""
    try:
        pfad = Path(root) / 'betrieb' / 'wortzahl_vermerke.jsonl'
        eintrag = {'zeit': dt.datetime.now().astimezone().isoformat(), 'auftrag': Path(datei).name,
                   'vermerke': vermerke, 'ergebnisstand_sha256': stand['sha256'] if stand else None}
        vergleich = {k: eintrag[k] for k in ('auftrag', 'vermerke', 'ergebnisstand_sha256')}
        if pfad.is_file():
            with pfad.open('rb') as f:
                f.seek(0, os.SEEK_END)
                f.seek(max(0, f.tell() - 65536))
                zeilen = f.read().decode('utf-8', 'replace').splitlines()
            if zeilen:
                letzte = json.loads(zeilen[-1])
                if all(letzte.get(k) == v for k, v in vergleich.items()):
                    return
        pfad.parent.mkdir(parents=True, exist_ok=True)
        with pfad.open('a', encoding='utf-8') as f:
            f.write(json.dumps(eintrag, ensure_ascii=False, sort_keys=True) + '\n')
    except (OSError, ValueError, TypeError, KeyError):
        pass


def lokale_vorpruefung(root, datei, protokollieren=True):
    """Kostenlose Formpruefung vor Prueferstart; keine fachliche Annahme.

    F-9: protokollieren=False fuer reine Anzeigen (Tafel, Vorgangsbuch) - dann keine Sperrfall-/Vermerkzeile."""
    root = Path(root).resolve()
    checked = pruefe_auftrag(root, datei)
    if checked is None:
        return {'ok': True, 'gebunden': False, 'wortzahlen': [],
                'text': 'Altauftrag ohne geschuetzte Pflichtpunkte; lokale Vorpruefung nicht anwendbar.'}
    vertrag, digest, text = checked
    rules, _ = _lokale_regeln(root, vertrag, digest)
    errors, counts = [], []
    for title in ('Lauf', 'Ergebnis', 'Nachweis'):
        try:
            body = abschnitt(text, title)
            if not body or re.match(r'^\((?:füllt|fuellt|Dateien, Pfade)', body):
                errors.append('Abschnitt ' + title + ' ist noch nicht ausgefuellt')
        except ValueError as error:
            errors.append(str(error))
    try:
        stand = snapshot(root, datei)
    except (OSError, ValueError) as error:
        errors.append(str(error))
        stand = None
    for rule in rules:
        try:
            record = _beleg(root.parent.parent, rule['datei'])
            if record['bytes'] > 2 * 1024 * 1024:
                raise ValueError('Text fuer Wortzaehlung groesser als 2 MiB')
            raw = (root.parent.parent / record['pfad']).read_bytes()
            if _hash(raw) != record['sha256']:
                raise ValueError('Text wurde waehrend der Wortzaehlung veraendert')
            count = len(raw.decode('utf-8').split())
            counts.append({**rule, 'ist': count, 'sha256': record['sha256']})
            if count == 0:
                errors.append(rule['pflichtpunkt'] + ': Text enthaelt nur Leerraum')
            if count > rule['max_woerter']:
                errors.append(rule['pflichtpunkt'] + ': ' + rule['datei'] + ': '
                              + str(count) + ' Woerter/Bloecke, erlaubt ' + str(rule['max_woerter']))
            if stand and not any(p['kennung'] == rule['pflichtpunkt'] and rule['datei'] in p['belege']
                                 for p in stand['pflichtpunkte']):
                errors.append(rule['pflichtpunkt'] + ': Wortregel-Datei fehlt als Pflichtpunktbeleg')
        except (OSError, ValueError) as error:
            errors.append(rule['pflichtpunkt'] + ': ' + str(error))
    recherche = _recherche_objekt_pruefen(root, vertrag, stand, errors)
    # F-11 (P04): entscheidungstragende Zahl weicht von der Messung ab -> Korrektur vor dem Pruefer, keine Annahme
    abweichungen = zahlen_abweichungen(text, counts)
    for a in abweichungen:
        errors.append('ZAHL WEICHT VON DER MESSUNG AB (entscheidungstragend): ' + a['text']
                      + '. Zahl im Auftrag korrigieren (Korrekturrunde); so ist keine ANNAHME moeglich')
    if errors and protokollieren:
        _sperrfall_protokollieren(root, datei, errors, stand)
    # F-6: Modellangaben zur Wortzahl gegen die Messung pruefen - nur Vermerk, keine Sperre.
    vermerke = []
    if counts:
        modelltext = '\n'.join(part for part in
                               (_abschnitt_oder_leer(text, titel) for titel in ('Lauf', 'Ergebnis', 'Nachweis'))
                               if part)
        vermerke = wortzahl_vermerke(modelltext, counts)
        if vermerke and protokollieren:
            _vermerk_protokollieren(root, datei, vermerke, stand)
    summary = ('Lokale Vorpruefung gesperrt: ' + '; '.join(errors) if errors else
               'Lokale Vorpruefung bestanden: Pflichtangaben und Belege vorhanden. '
               + ('; '.join(c['pflichtpunkt'] + ': ' + str(c['ist']) + '/' + str(c['max_woerter'])
                           + ' Woerter/Bloecke' for c in counts) if counts else 'Keine Wortgrenzen hinterlegt.'))
    if vermerke:
        summary += ' Vermerk: ' + ' '.join(v['text'] for v in vermerke)
    if recherche and recherche.get('vollstaendig'):
        summary = (summary.rstrip('.') + '. Recherche-Objekt vollstaendig: %d Kriterien, %d Quellen, %d Optionen.'
                   % (recherche['kriterien'], recherche['quellen'], recherche['optionen']))
    return {'ok': not errors, 'gebunden': True, 'fehler': errors, 'wortzahlen': counts,
            'vermerke': vermerke, 'zahlen_abweichungen': abweichungen,
            'ergebnisstand_sha256': stand['sha256'] if stand else None,
            'recherche_objekt': recherche,
            'text': summary + ' Fachliche Richtigkeit und unabhaengige Annahme bleiben gesondert.'}


def _recherche_objekt_pruefen(root, vertrag, stand, errors):
    """F-4 (Paket 2, M6): Traegt der Vertrag den Recherche-Pflichtpunkt, muss sein
    Beleg ein vollstaendiges Recherche-Objekt (JSON) sein - sonst startet der
    Pruefer nicht. Altvertraege ohne diesen Punkt bleiben unberuehrt."""
    # Erst den Ablauf pruefen: alle anderen Vertraege brauchen jack_faehigkeiten
    # hier nicht (Wegwerf-Pruefstaende kopieren nur jack_auftrag.py).
    if vertrag.get('ablauf') != 'recherche':
        return None
    import jack_faehigkeiten
    punkt = next((p for p in vertrag['pflichtpunkte']
                  if p['text'] == jack_faehigkeiten.RECHERCHE_PFLICHTPUNKT), None)
    if punkt is None:
        return None
    if not stand:
        return {'vollstaendig': False, 'fehlend': ['Nachweise nicht lesbar']}
    belege = next((p['belege'] for p in stand['pflichtpunkte'] if p['kennung'] == punkt['kennung']), [])
    dateien = [b for b in belege if b.lower().endswith('.json')]
    if not dateien:
        errors.append(punkt['kennung'] + ': Recherche-Objekt (JSON-Datei) fehlt als Beleg')
        return {'vollstaendig': False, 'fehlend': ['JSON-Beleg fehlt']}
    try:
        record = _beleg(root.parent.parent, dateien[0])
        if record['bytes'] > 1024 * 1024:
            raise ValueError('Recherche-Objekt groesser als 1 MiB')
        raw = (root.parent.parent / record['pfad']).read_bytes()
        if _hash(raw) != record['sha256']:
            raise ValueError('Recherche-Objekt wurde waehrend der Pruefung veraendert')
        ergebnis = jack_faehigkeiten.recherche_pruefen(json.loads(raw.decode('utf-8')))
    except (OSError, ValueError) as error:
        errors.append(punkt['kennung'] + ': Recherche-Objekt nicht lesbar: ' + str(error))
        return {'vollstaendig': False, 'fehlend': [str(error)], 'datei': dateien[0]}
    ergebnis['datei'] = dateien[0]
    if not ergebnis['vollstaendig']:
        errors.append(punkt['kennung'] + ': Recherche-Objekt unvollstaendig: ' + '; '.join(ergebnis['fehlend'][:8]))
    return ergebnis


def pruefe_schreibstand(root, name, lauf_id, target):
    """Gepruefte Einreichung im selben Lauf vor weiteren Werkzeugschreibzugriffen schuetzen."""
    if not name or not re.fullmatch(r'[0-9a-f]{32}', lauf_id or ''):
        return
    root = Path(root).resolve()
    log = root / 'arbeiter_zugriffe.jsonl'
    if not log.exists():
        return
    accepted = None
    with log.open(encoding='utf-8') as stream:
        for line in stream:
            if lauf_id not in line:
                continue
            rec = json.loads(line)
            if (rec.get('lauf_id') != lauf_id or rec.get('auftrag') != name
                    or rec.get('tool') != 'Write' or rec.get('entscheidung') != 'allow'
                    or not rec.get('agent_id') or not rec.get('auftragsnachweis_sha256')):
                continue
            path = Path(rec.get('pfad') or '/')
            if path.parent != root / 'abnahme/tor2':
                continue
            # PreToolUse kann auch vor einem gescheiterten Schreibvorgang laufen.
            # Erst der tatsaechlich vorhandene Annahmezettel bindet.
            if not path.is_file():
                continue
            verdict = path.read_text(encoding='utf-8')
            if re.search(r'^urteil:[ \t]*ANNAHME[ \t]*$', verdict, re.M):
                accepted = rec
    if accepted is None:
        return
    order = root / 'auftraege/laeuft' / _dateiname(name)
    stand = snapshot(root, order)
    if stand is None or stand['sha256'] != accepted['auftragsnachweis_sha256']:
        raise ValueError('Gepruefter Ergebnisstand wurde bereits veraendert; keine weiteren Schreibzugriffe in diesem Lauf')
    protected = {order.resolve()}
    for record in stand['dateien']:
        protected.add((root.parent.parent / record['pfad']).resolve())
        if 'medienquelle' in record:
            protected.add((root.parent.parent / record['medienquelle']['pfad']).resolve())
    if Path(target).resolve() in protected:
        raise ValueError('Tor-2-Annahme liegt vor: Auftrag und gepruefte Belege bleiben unveraendert. '
                         'Pflichtpunkte nicht auf angenommen setzen und keinen Pruefzettel nachtraeglich '
                         'als Beleg eintragen. Jetzt FERTIG melden; den Abschluss setzt der Arbeiter.')


def tor2_snapshot(root, name):
    """Vor dem Schreiben eines Annahmezettels durch den geschuetzten Hook."""
    if not name:
        return None
    datei = Path(root) / 'auftraege' / 'laeuft' / _dateiname(name)
    check = lokale_vorpruefung(root, datei)
    if not check['ok']:
        raise ValueError(check['text'])
    return snapshot(root, datei)


def pruefe_prueftext(verdict, name, required):
    """Dasselbe Pflichtformat vor dem Schreiben und beim Abschluss pruefen."""
    if not re.search(r'^urteil:[ \t]*ANNAHME[ \t]*$', verdict, re.M):
        raise ValueError('Keine Annahme des Pruefers')
    order_match = re.search(r'^auftrag:[ \t]*(.*?)\s*$', verdict, re.M)
    if not order_match or order_match[1] not in (Path(name).name, Path(name).stem):
        raise ValueError('Pruefzettel gehoert zu einem anderen Auftrag')
    match = re.search(r'^pflichtpunkte:[ \t]*(.*?)\s*$', verdict, re.M)
    actual = re.findall(r'P\d{2}', match[1]) if match else []
    if sorted(actual) != sorted(required):
        raise ValueError('Pruefer muss jeden Pflichtpunkt ausdruecklich bestaetigen. '
                         'Pflichtzeile vor dem Schreiben ergaenzen: pflichtpunkte: '
                         + ', '.join(required))


# Befund 21.09.2026 (P02): ein Pflichtpunkt mit drei Saetzen wurde angenommen,
# obwohl nur zwei belegt waren. Die Zerlegung macht deshalb der Code, nicht der Pruefer.
_ABKUERZUNGEN = frozenset(('a', 'b', 'd', 'h', 'o', 's', 'u', 'z', 'abs', 'bspw', 'bzw', 'ca', 'dr',
                           'etc', 'evtl', 'ff', 'ggf', 'inkl', 'max', 'min', 'nr', 'sog', 'usw',
                           'vgl', 'zzgl'))
MIN_ZITAT = 12
MAX_ZITATQUELLE_BYTES = 2 * 1024 * 1024


def teilaussagen(text):
    """Pflichtpunkt deterministisch an Satzende und Semikolon zerlegen."""
    teile, start = [], 0
    for m in re.finditer(r'[.!?;](?=\s|$)', text):
        if m[0] == '.':
            wort = re.search(r'(\S+)$', text[start:m.start()])
            w = re.sub(r'^\W+', '', wort[1]).casefold().rsplit('.', 1)[-1] if wort else ''
            if w in _ABKUERZUNGEN or (w.isdigit() and len(w) <= 2):
                continue
        teile.append(text[start:m.end()])
        start = m.end()
    teile.append(text[start:])
    return [t.strip() for t in teile if len(t.strip(' \t;.!?')) >= 3]


def _zitatform(text):
    for alt, neu in ((' ', ' '), ('„', '"'), ('“', '"'), ('”', '"'), ('‚', "'"),
                     ('‘', "'"), ('’', "'"), ('–', '-'), ('—', '-')):
        text = text.replace(alt, neu)
    return ' '.join(re.sub(r'[*`]', '', text).split()).casefold()


def pruefe_teilbelege(root, datei, verdict, stand):
    """Zusammengesetzter Pflichtpunkt: je Teilaussage ein eigenes woertliches Zitat aus seinen Belegen."""
    root = Path(root).resolve()
    vault = root.parent.parent
    checked = pruefe_auftrag(root, datei)
    if checked is None or stand is None:
        return
    teile = {p['kennung']: teilaussagen(p['text']) for p in checked[0]['pflichtpunkte']}
    gefunden, fehler = {}, []
    for zeile in re.findall(r'^teilbeleg:[ \t]*(.*?)\s*$', verdict, re.M):
        m = re.fullmatch(r'(P\d{2})\.(\d{1,2})[ \t]*\|[ \t]*(.+)', zeile)
        if not m or m[1] not in teile or not 1 <= int(m[2]) <= len(teile[m[1]]):
            fehler.append('unbekannte Teilbelegzeile "' + zeile[:80] + '"')
            continue
        zitate = [next(g for g in z if g) for z in
                  re.findall(r'"([^"]+)"|„([^“”"]+)[“”"]|“([^”"]+)”', m[3])]
        gefunden.setdefault((m[1], int(m[2])), []).extend(zitate)
    dateien = {d['pfad']: d for d in stand['dateien']}
    belege = {p['kennung']: p['belege'] for p in stand['pflichtpunkte']}
    texte = {}

    def quelltext(pfad):
        if pfad not in texte:
            texte[pfad] = None
            record = dateien.get(pfad)
            if record and record['bytes'] <= MAX_ZITATQUELLE_BYTES:
                raw = (vault / pfad).read_bytes()
                if _hash(raw) != record['sha256']:
                    raise ValueError('Beleg ' + pfad + ' weicht vom geprueften Ergebnisstand ab')
                try:
                    texte[pfad] = _zitatform(raw.decode('utf-8'))
                except UnicodeDecodeError:
                    pass
        return texte[pfad]

    for kennung, saetze in teile.items():
        benutzt = {}
        quellen = None
        for nr, satz in enumerate(saetze, 1):
            ref = '%s.%d' % (kennung, nr)
            zitate = gefunden.get((kennung, nr))
            if zitate is None:
                if len(saetze) > 1:
                    fehler.append(ref + ' fehlt ("' + satz[:160] + '")')
                continue
            if not zitate:
                fehler.append(ref + ' ohne woertliches Zitat in Anfuehrungszeichen')
                continue
            if quellen is None:
                quellen = [t for t in (quelltext(p) for p in belege.get(kennung, [])) if t]
            for zitat in zitate:
                form = _zitatform(zitat)
                if len(form) < MIN_ZITAT:
                    fehler.append(ref + ': Zitat kuerzer als %d Zeichen' % MIN_ZITAT)
                elif not any(form in t for t in quellen):
                    fehler.append(ref + ': Zitat steht in keiner Belegdatei von ' + kennung
                                  + ' ("' + zitat[:80] + '")')
                elif benutzt.setdefault(form, ref) != ref:
                    fehler.append(ref + ': dasselbe Zitat wie ' + benutzt[form]
                                  + '; jede Teilaussage braucht eine eigene Stelle')
    if fehler:
        raise ValueError('Annahme unwirksam: zusammengesetzte Pflichtpunkte brauchen je Teilaussage '
                         'ein eigenes woertliches Zitat aus einer Belegdatei desselben Pflichtpunkts. '
                         + '; '.join(fehler) + '. Format je Teilaussage: teilbeleg: P02.3 | '
                         '"woertliches Zitat". Fehlt die Stelle im Ergebnis: urteil: ZURUECKWEISUNG.')


# ════════ F-7 (24.09.2026): Zettelformat fuer den Pruefer + eine Korrekturrunde ═══════
# F-6: Der Pruefer scheiterte an Pflichtzeile und Teilaussagen-Zitaten und schrieb nach zwei
# Abweisungen keinen dritten Zettel. Jetzt (1) liefert der Waechter dem Pruefer das exakte
# Format samt Beispiel schon im Prompt und (2) darf der Pruefer im SELBEN Lauf nach genau
# einer Rueckmeldung mit der Fehlstelle einmal neu liefern. Der zweite Formfehler macht die
# Annahme in diesem Lauf endgueltig unwirksam; danach gilt nur noch ZURUECKWEISUNG.
TOR2_KORREKTUR_MAX = 1
BEISPIEL_ZETTEL = (
    'auftrag: 2026-09-23_0800_JACK_teilbelege_kurznotiz.md\n'
    'zeit: unbekannt\n'
    'urteil: ANNAHME\n'
    'pruefpunkte: P01 zerfaellt in fuenf Teilaussagen; je Teilaussage ein woertliches Zitat aus der '
    'Ergebnisdatei. Wortzahl laut lokaler Messung 92/150, unterhalb der Grenze.\n'
    'teilbeleg: P01.1 | "# Teilbeleg-Regel für zusammengesetzte Pflichtpunkte"\n'
    'teilbeleg: P01.2 | "Ein Pflichtpunkt mit mehreren Sätzen oder Semikolon zerfällt in Teilaussagen '
    '(P02.1, P02.2, P02.3 …)."\n'
    'teilbeleg: P01.3 | "teilbeleg: P02.3"\n'
    'teilbeleg: P01.4 | "Fehlt auch nur eine Teilaussage, bleibt der ganze Punkt offen — Annahme unwirksam."\n'
    'teilbeleg: P01.5 | "Am 21.09.2026 wurde ein Auftrag mit unvollständiger Teilbelegung angenommen: '
    'Pflichtpunkt P02 verlangte mehrere Teilaussagen, von denen eine fehlte."\n'
    'pflichtpunkte: P01\n')


def zettelformat_anweisung(root, datei):
    """Der Formatblock fuer den Pruefer-Prompt: Pflichtzeile, Teilaussagen dieses Auftrags, Beispiel.

    Kommt aus dem Code (dieselbe Zerlegung wie pruefe_teilbelege), nicht aus der Erinnerung des CEO.
    Ohne gebundenen Vertrag: leer."""
    root = Path(root).resolve()
    checked = pruefe_auftrag(root, datei)
    if checked is None:
        return ''
    stand = snapshot(root, datei)
    belege = {p['kennung']: p['belege'] for p in (stand or {}).get('pflichtpunkte', [])}
    kennungen = [p['kennung'] for p in checked[0]['pflichtpunkte']]
    zeilen = ['ZETTELFORMAT (bindend; der Waechter prueft jede Annahme vor dem Schreiben):',
              'Pflichtzeile bei ANNAHME, woertlich diese Kennungen: pflichtpunkte: ' + ', '.join(kennungen),
              'Ein Pflichtpunkt mit mehreren Saetzen oder Semikolon besteht aus Teilaussagen. Fuer JEDE Teilaussage '
              'eine eigene Zeile  teilbeleg: <Kennung.Nr> | "woertliches Zitat" . Dieser Auftrag verlangt:']
    verlangt = False
    for p in checked[0]['pflichtpunkte']:
        teile = teilaussagen(p['text'])
        if len(teile) < 2:
            zeilen.append('- %s: eine Aussage, keine teilbeleg-Zeile noetig; im pruefpunkte-Text belegen.' % p['kennung'])
            continue
        verlangt = True
        zeilen.append('- %s (Belegdateien: %s):' % (p['kennung'], '; '.join(belege.get(p['kennung'], [])) or 'siehe Auftrag'))
        for nr, satz in enumerate(teile, 1):
            zeilen.append('    teilbeleg: %s.%d | "<Zitat>"   fuer: %s' % (p['kennung'], nr, satz[:200]))
    if not verlangt:
        zeilen.append('(Kein Pflichtpunkt dieses Auftrags ist zusammengesetzt.)')
    zeilen += [
        'Regeln fuer jedes Zitat: ein ZUSAMMENHAENGENDES Stueck aus einer Belegdatei genau dieses Pflichtpunkts, '
        'Zeichen fuer Zeichen wie im Ergebnis, mindestens 12 Zeichen, mit doppelten Anfuehrungszeichen umschlossen '
        'und OHNE weiteres Anfuehrungszeichen darin (bei JSON einen Wert oder ein Stueck zwischen den Anfuehrungszeichen '
        'waehlen). Jede Teilaussage bekommt eine EIGENE Stelle; dieselbe Stelle zweimal zaehlt nicht.',
        'Keine Zusammenfassung statt Zitat, keine Umformulierung, keine Auslassungspunkte im Zitat. Eine Kuerzung '
        'zeigst du an, indem du im pruefpunkte-Text "Ausschnitt" schreibst und nur das kuerzere zusammenhaengende '
        'Stueck zitierst - nie ein zusammengeschobenes.',
        'Traegt keine Stelle im Ergebnis die Teilaussage: urteil: ZURUECKWEISUNG mit dieser Teilaussage als Mangel; '
        'ein nur aehnlich klingendes Zitat ist kein Beleg.',
        'Bei Recherche-Objekten zaehlen die Teile einzeln: Quellen mit Abrufdatum, Kriterien, Empfehlung mit '
        'Nachteilen - jeder Teil ein eigenes Zitat, keine Sammelstelle.',
        'ZAHLEN (F-11): Jede Zahl in einer entscheidungstragenden Aussage (sie traegt einen Pflichtpunkt, das '
        'gemeldete Ergebnis oder eine Empfehlung) vergleichst du mit der LOKALEN MESSUNG oder der Quelle. Weicht '
        'sie ab, ist das ein Mangel - auch wenn eine Grenze trotzdem eingehalten waere: urteil: ZURUECKWEISUNG '
        'mit Zahl, Messwert und Fundstelle. Nie "Abweichung ohne Auswirkung" annehmen.',
        'Korrekturrunde: liegt ein Formfehler vor, meldet der Waechter die genaue Fehlstelle; du hast danach '
        'GENAU EINE Wiederholung im selben Lauf. Der zweite Formfehler macht die Annahme endgueltig unwirksam.']
    # F-20 (Paket 6): die Lernhinweise aus dem Vertrag sind zusaetzliche Pruefpunkte (Text nur aus der Regelliste).
    if checked[0].get('lernhinweise'):
        zeilen.append('LERNHINWEISE (F-20; aus der freigegebenen Regelliste, im Vertrag gebunden) - zusaetzliche '
                      'Pruefpunkte. Fuer JEDEN eine eigene Zeile  lernhinweis: <Kennung> | eingehalten | <Fundstelle>  '
                      '(oder: verletzt | <Fundstelle>, oder: nicht pruefbar | <Grund>). Verletzt ist ein Hinweis nur, '
                      'wenn Ergebnis oder Nachweis ihn sichtbar brechen; dann ist das ein Mangel wie ein Pflichtpunkt:')
        zeilen += ['- %s (Regel %s): %s' % (h['kennung'], h['regel'], h['hinweis'])
                   for h in checked[0]['lernhinweise']]
    zeilen += [
        'BEISPIEL eines vollstaendigen, angenommenen Zettels (anderer Auftrag; nur die Form uebernehmen, nichts von '
        'dem Inhalt):',
        '<<<', BEISPIEL_ZETTEL.rstrip('\n'), '>>>']
    return '\n'.join(zeilen)


def _korrekturpfad(root, lauf_id, name):
    schluessel = lauf_id if re.fullmatch(r'[0-9a-f]{32}', lauf_id or '') else _hash(Path(name).name.encode('utf-8'))
    return Path(root) / 'betrieb' / 'tor2_korrekturen' / (schluessel + '.json')


def tor2_korrektur_stand(root, lauf_id, name=''):
    """{'formfehler': n, 'gesperrt': bool, 'meldungen': [...]} fuer diesen Lauf; ohne Datei alles leer."""
    pfad = _korrekturpfad(root, lauf_id, name)
    try:
        wert = json.loads(pfad.read_text(encoding='utf-8'))
        return {'formfehler': int(wert['formfehler']), 'gesperrt': bool(wert['gesperrt']),
                'meldungen': list(wert.get('meldungen') or [])}
    except (OSError, ValueError, KeyError, TypeError):
        return {'formfehler': 0, 'gesperrt': False, 'meldungen': []}


def tor2_annahme_pruefen(root, datei, verdict, stand, name, lauf_id, required):
    """Waechter-Weg fuer eine ANNAHME: Format pruefen, Fehlstelle melden, genau eine Wiederholung erlauben."""
    zustand = tor2_korrektur_stand(root, lauf_id, name)
    if zustand['gesperrt']:
        raise ValueError('TOR-2-FORMAT: Der Zettel war in diesem Lauf schon %d Mal fehlerhaft; die Annahme ist '
                         'endgueltig abgewiesen, keine weitere Wiederholung. Schreibe hoechstens noch einen Zettel '
                         'mit urteil: ZURUECKWEISUNG und dem Grund.' % zustand['formfehler'])
    try:
        pruefe_prueftext(verdict, name, required)
        pruefe_teilbelege(root, datei, verdict, stand)
    except ValueError as fehler:
        n = zustand['formfehler'] + 1
        letzte = n > TOR2_KORREKTUR_MAX
        pfad = _korrekturpfad(root, lauf_id, name)
        pfad.parent.mkdir(parents=True, exist_ok=True)
        rest = pfad.with_name('.' + pfad.name + '.neu')
        rest.write_text(_json({'schema': 1, 'auftrag': Path(name).name, 'lauf_id': lauf_id,
                               'formfehler': n, 'gesperrt': letzte,
                               'meldungen': (zustand['meldungen'] + [str(fehler)[:600]]),
                               'zeit': dt.datetime.now().astimezone().isoformat()}) + '\n', encoding='utf-8')
        os.replace(rest, pfad)
        if letzte:
            raise ValueError('TOR-2-FORMAT: zweiter Formfehler in diesem Lauf - Annahme endgueltig abgewiesen, '
                             'keine weitere Wiederholung. Letzte Fehlstelle: %s Schreibe hoechstens noch einen '
                             'Zettel mit urteil: ZURUECKWEISUNG und dem Grund.' % fehler)
        raise ValueError('TOR-2-FORMAT KORREKTURRUNDE %d von %d: Zettel nicht geschrieben. Exakte Fehlstelle: %s '
                         'Liefere JETZT den vollstaendig korrigierten Zettel neu (Write auf denselben Dateinamen; '
                         'er wurde nicht angelegt). Das ist die einzige Wiederholung.' % (n, TOR2_KORREKTUR_MAX, fehler))


def budgetabschluss_pruefen(root, datei, lauf_id):
    """Nur ein protokollierter API-Budgetabbruch darf nochmals zum vollen Tor 2.

    Keine Annahme: Fachkraft, unabhaengiger Zettel und unveraenderte Belege
    prueft weiterhin ausschliesslich der bestehende Abschlussweg.
    """
    try:
        if not re.fullmatch(r'[0-9a-f]{32}', lauf_id or ''):
            return False
        checked = pruefe_auftrag(root, datei)
        if checked is None or kopf(checked[2]).get('status') not in ('offen', 'laeuft'):
            return False
        import jack_kosten
        matches = [row for row in jack_kosten.rows(root)
                   if row.get('ereignis') == 'ende'
                   and row.get('auftrag') == Path(datei).name
                   and row.get('auftragslauf') == lauf_id
                   and row.get('art') == 'arbeiter_api']
        if len(matches) != 1 or matches[0].get('status') != 'fehler':
            return False
        session = matches[0].get('anbieter_lauf')
        if not isinstance(session, str) or not re.fullmatch(r'[0-9a-f-]{36}', session):
            return False
        records = []
        with (Path(root) / 'arbeiter_api_laeufe.jsonl').open(encoding='utf-8') as stream:
            for line in stream:
                if session not in line:
                    continue
                record = json.loads(line)
                if record.get('session_id') == session:
                    records.append(record)
        return (len(records) == 1 and records[0].get('is_error') is True
                and records[0].get('subtype') == 'error_max_budget_usd')
    except (OSError, ValueError, KeyError, TypeError):
        return False


# ════════ Fortsetzen nach Zeitgrenze (F-6, 24.09.2026, Kern von Paket 3) ═══════
# Ein Auftrag in problem/, dessen Abbruchgrund die Zeitgrenze war und dessen
# Fachkraft-Ausgabe formal vollstaendig vorliegt, wird am letzten sicheren
# Schritt (fachkraft_fertig) fortgesetzt - nicht neu begonnen. Der Beleg
# betrieb/fortsetzungen/<sha256(Name)>.json bindet die Fachkraft-Ausgabe per
# SHA-256 und die Fachkraft-agent_id aus dem Werkzeugprotokoll. Der Arbeiter
# darf betrieb/ ausser entwuerfe/ nie schreiben; der Beleg kommt nur aus dem Planer.
# Fortsetzen ist kein neuer Versuch (versuch bleibt), erzeugt keine zweite
# Fachkraft-Ausfuehrung und ist auf FORTSETZUNG_MAX Mal je Auftrag begrenzt.
FORTSETZUNG_SCHRITT = 'fachkraft_fertig'
FORTSETZUNG_MAX = 1
# F-7: PM-Entscheidung 24.09.2026 - genau EIN weiterer, ausdruecklich freigegebener Nachlauf NUR fuer Tor 2,
# wenn Tor 2 noch nie einen Zettel geschrieben hat. Ohne Freigabe-Text und ohne unveraenderte Fachkraft-Ausgabe nie.
TOR2_NACHLAUF_MAX = 1
FORTSETZUNG_SCHEMA = 1
_ABBRUCH_ZEITGRENZE = re.compile(r'Zeitgrenze|Minuten beendet', re.I)


def fortsetzung_pfad(root, name):
    return Path(root) / 'betrieb' / 'fortsetzungen' / (_hash(Path(name).name.encode('utf-8')) + '.json')


def fortsetzung_lesen(root, name):
    """Der gespeicherte Fortsetzungsbeleg oder None. Ein kaputter Beleg ist ein Fehler.

    F-9: Schema 2 (beliebiger sicherer Schritt, hash-gebunden) kommt hinzu; Schema 1 bleibt unveraendert."""
    pfad = fortsetzung_pfad(root, name)
    if not pfad.is_file() or pfad.is_symlink():
        return None
    beleg = json.loads(pfad.read_text(encoding='utf-8'))
    if isinstance(beleg, dict) and beleg.get('schema') == FORTSETZUNG_SCHEMA_2:
        return _fortsetzung2_pruefen(beleg, name)
    if (not isinstance(beleg, dict) or beleg.get('schema') != FORTSETZUNG_SCHEMA
            or beleg.get('auftrag') != Path(name).name
            or beleg.get('letzter_sicherer_schritt') != FORTSETZUNG_SCHRITT
            or not isinstance(beleg.get('dateien'), list) or not beleg['dateien']
            or not isinstance(beleg.get('fachkraft_agent_ids'), list) or not beleg['fachkraft_agent_ids']
            or not isinstance(beleg.get('fortsetzungen'), int)):
        raise ValueError('Fortsetzungsbeleg ist ungueltig')
    return beleg


def abbruchgrund(text):
    """Text des LETZTEN Abschnitts '## Problem (...)' im Auftrag, sonst ''."""
    treffer = list(re.finditer(r'^## Problem \([^)\n]*\)[ \t]*\n(.*?)(?=^## |\Z)', text, re.M | re.S))
    return treffer[-1][1].strip() if treffer else ''


def _zugriffe_des_auftrags(root, name):
    pfad = Path(root) / 'arbeiter_zugriffe.jsonl'
    if not pfad.is_file():
        return []
    zeilen = []
    with pfad.open(encoding='utf-8') as f:
        for line in f:
            if name not in line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get('auftrag') == name:
                zeilen.append(row)
    return zeilen


def fortsetzung_vorbereiten(root, datei, budget_usd='0.60', tor2_nachlauf=None):
    """Prueft alle Voraussetzungen und legt den Fortsetzungsbeleg an (genau einmal).

    Wirft ValueError mit dem Grund, wenn irgendetwas fehlt. Aendert die Auftragsdatei
    nicht - das macht jack_planer.fortsetzen."""
    root = Path(root).resolve()
    datei = Path(datei)
    name = datei.name
    checked = pruefe_auftrag(root, datei)
    if checked is None:
        raise ValueError('Fortsetzen gilt nur fuer geschuetzte Vertragsauftraege')
    vertrag, digest, text = checked
    kopfwerte = kopf(text)
    if kopfwerte.get('status') != 'problem':
        raise ValueError('Nur ein Auftrag mit Status problem kann fortgesetzt werden')
    grund = abbruchgrund(text)
    bisher = fortsetzung_lesen(root, name)
    nachlauf = bool(tor2_nachlauf and str(tor2_nachlauf).strip())
    if nachlauf:
        if bisher is None:
            raise ValueError('Tor-2-Nachlauf setzt eine erste Fortsetzung voraus')
        if bisher['fortsetzungen'] >= FORTSETZUNG_MAX + TOR2_NACHLAUF_MAX:
            raise ValueError('Tor-2-Nachlauf schon verbraucht (%d Fortsetzungen)' % bisher['fortsetzungen'])
        gebucht = sorted((Path(root) / 'abnahme' / 'tor2').glob(Path(name).stem + '__pruefung*.md'))
        if gebucht:
            raise ValueError('Tor 2 hat schon einen Zettel geschrieben (%s); kein Nachlauf' % gebucht[0].name)
        if kopfwerte.get('fortsetzung') not in ('', None, bisher['kennung']):
            raise ValueError('Auftrag traegt eine fremde Fortsetzung')
    else:
        if not _ABBRUCH_ZEITGRENZE.search(grund):
            raise ValueError('Abbruchgrund ist nicht die Zeitgrenze: ' + (grund[:120] or '(kein Problemabschnitt)'))
        if bisher is not None and bisher['fortsetzungen'] >= FORTSETZUNG_MAX:
            raise ValueError('Fortsetzungsgrenze erreicht: dieser Auftrag wurde bereits %d Mal fortgesetzt'
                             % bisher['fortsetzungen'])
        if kopfwerte.get('fortsetzung'):
            raise ValueError('Auftrag traegt schon eine Fortsetzung')
    check = lokale_vorpruefung(root, datei)
    if not check['ok'] or not check['gebunden']:
        raise ValueError('Fachkraft-Ausgabe ist nicht formal vollstaendig: ' + check['text'])
    stand = snapshot(root, datei)
    vault = root.parent.parent
    dateien = [{'pfad': d['pfad'], 'sha256': d['sha256']} for d in stand['dateien']]
    if nachlauf and sorted((d['pfad'], d['sha256']) for d in bisher['dateien']) != sorted((d['pfad'], d['sha256']) for d in dateien):
        raise ValueError('Fachkraft-Ausgabe weicht vom ersten Fortsetzungsbeleg ab; kein Nachlauf')
    belege = {(vault / d['pfad']).resolve() for d in dateien}
    zugriffe = _zugriffe_des_auftrags(root, name)
    laeufe = [r for r in zugriffe if r.get('tool') == 'Agent' and r.get('entscheidung') == 'allow'
              and r.get('agent_typ') in ('jack-fachkraft', 'jack-fachkraft-stark') and r.get('lauf_id')]
    if not laeufe:
        raise ValueError('Keine Fachkraft-Ausfuehrung im Werkzeugprotokoll nachgewiesen')
    lauf_id = laeufe[-1]['lauf_id']
    if not re.fullmatch(r'[0-9a-f]{32}', lauf_id):
        raise ValueError('Laufkennung der Fachkraft-Ausfuehrung ist ungueltig')
    lauf = [r for r in zugriffe if r.get('lauf_id') == lauf_id]
    tor2 = (root / 'abnahme' / 'tor2').resolve()
    for r in lauf:
        if r.get('tool') == 'Write' and r.get('entscheidung') == 'allow':
            try:
                if Path(str(r.get('pfad') or '/')).resolve().parent == tor2:
                    raise ValueError('Tor 2 hat in diesem Lauf schon einen Zettel geschrieben; kein Fortsetzen')
            except OSError:
                pass
    ids = sorted({r['agent_id'] for r in lauf
                  if r.get('agent_id') and r.get('tool') in ('Write', 'Edit') and r.get('entscheidung') == 'allow'
                  and Path(str(r.get('pfad') or '/')).resolve() in belege})
    if not ids:
        raise ValueError('Kein Unteragent hat die Ergebnisdateien im Werkzeugprotokoll geschrieben')
    beleg = {'schema': FORTSETZUNG_SCHEMA, 'kennung': _hash((name + dt.datetime.now().isoformat()).encode())[:16],
             'zeit': dt.datetime.now().astimezone().isoformat(), 'auftrag': name, 'grund': 'Zeitgrenze',
             'abbruch': grund[:300], 'letzter_sicherer_schritt': FORTSETZUNG_SCHRITT,
             'ursprungslauf_id': lauf_id, 'fachkraft_agent_ids': ids, 'dateien': dateien,
             'vertrag_sha256': digest, 'versuch': kopfwerte.get('versuch', '0'),
             'budget_usd': str(budget_usd), 'fortsetzungen': (bisher['fortsetzungen'] if bisher else 0) + 1}
    pfad = fortsetzung_pfad(root, name)
    if bisher is not None and not nachlauf:
        raise ValueError('Fortsetzungsbeleg besteht bereits; keine zweite Fortsetzung')
    if nachlauf:
        # Nichts loeschen: der erste Beleg bleibt als Sicherung, der neue ersetzt ihn atomar.
        beleg.update({'tor2_nachlauf': str(tor2_nachlauf).strip()[:200], 'vorheriger_beleg_kennung': bisher['kennung']})
        alt = pfad.with_name(pfad.name + '.vor_nachlauf_' + bisher['kennung'])
        if alt.exists():
            raise ValueError('Sicherung des ersten Fortsetzungsbelegs existiert schon')
        alt.write_bytes(pfad.read_bytes())
        neu = pfad.with_name('.' + pfad.name + '.neu')
        neu.write_text(_json(beleg) + '\n', encoding='utf-8')
        os.replace(neu, pfad)
        return beleg
    _neu(pfad, _json(beleg) + '\n')
    return beleg


def nachlauf_startfehler_wiederaufnahme(root, datei):
    """F-7: Ein Tor-2-Nachlauf, der VOR jeder bezahlten Arbeit scheiterte (Startfehler), darf genau einmal
    wieder aufgenommen werden. Bewiesen wird das aus den Buechern: kein Kostenbuch-Eintrag mit diesem Auftrag
    seit dem Beleg, kein Werkzeugzugriff dieses Auftrags seit dem Beleg, kein Tor-2-Zettel. Sonst ValueError."""
    root = Path(root).resolve()
    name = Path(datei).name
    beleg = fortsetzung_lesen(root, name)
    if beleg is None or not beleg.get('tor2_nachlauf'):
        raise ValueError('Kein Tor-2-Nachlauf-Beleg vorhanden')
    if int(beleg.get('startfehler_wiederaufnahmen', 0)) >= 1:
        raise ValueError('Startfehler-Wiederaufnahme dieses Nachlaufs schon verbraucht')
    seit = dt.datetime.fromisoformat(beleg['zeit'])
    if list((root / 'abnahme' / 'tor2').glob(Path(name).stem + '__pruefung*.md')):
        raise ValueError('Tor 2 hat schon einen Zettel geschrieben')
    kosten = root / 'betrieb' / 'kostenlaeufe.jsonl'
    if kosten.is_file():
        for zeile in kosten.read_text(encoding='utf-8').splitlines():
            if name not in zeile:
                continue
            try:
                row = json.loads(zeile)
            except ValueError:
                continue
            if row.get('auftrag') == name and dt.datetime.fromisoformat(row['zeit']) >= seit:
                raise ValueError('Im Kostenbuch steht seit dem Nachlauf ein Eintrag fuer diesen Auftrag; kein Startfehler')
    if any(dt.datetime.fromisoformat(r['zeit']) >= seit for r in _zugriffe_des_auftrags(root, name)):
        raise ValueError('Der Nachlauf hat Werkzeuge benutzt; kein Startfehler')
    pfad = fortsetzung_pfad(root, name)
    neu = dict(beleg, startfehler_wiederaufnahmen=int(beleg.get('startfehler_wiederaufnahmen', 0)) + 1)
    alt = pfad.with_name(pfad.name + '.vor_startfehler_' + beleg['kennung'])
    if alt.exists():
        raise ValueError('Sicherung fuer die Startfehler-Wiederaufnahme existiert schon')
    alt.write_bytes(pfad.read_bytes())
    tmp = pfad.with_name('.' + pfad.name + '.neu')
    tmp.write_text(_json(neu) + '\n', encoding='utf-8')
    os.replace(tmp, pfad)
    return neu


def fortsetzung_fachkraft_nachweis(root, datei):
    """(ok, agent_ids): traegt der Auftrag eine gueltige Fortsetzung, deren hash-gebundene
    Fachkraft-Ausgabe im aktuellen Belegstand UNVERAENDERT vorliegt? Dann ersetzt der Beleg
    die Fachkraft-Delegation im Werkzeugprotokoll DIESES Laufs. Sonst (False, set())."""
    try:
        root = Path(root).resolve()
        name = Path(datei).name
        beleg = fortsetzung_lesen(root, name)
        if beleg is None:
            return False, set()
        checked = pruefe_auftrag(root, datei)
        if checked is None or checked[1] != beleg.get('vertrag_sha256'):
            return False, set()
        if kopf(checked[2]).get('fortsetzung') != beleg['kennung']:
            return False, set()
        if beleg.get('schema') == FORTSETZUNG_SCHEMA_2:
            # F-9: Schema 2 bindet ALLE von der Fachkraft geschriebenen Dateien - direkt auf der Platte pruefen
            vault = root.parent.parent
            for d in beleg['dateien']:
                p = vault / d['pfad']
                if p.is_symlink() or not p.is_file() or _hash(p.read_bytes()) != d['sha256']:
                    return False, set()
            return True, set(beleg['fachkraft_agent_ids'])
        aktuell = {d['pfad']: d['sha256'] for d in snapshot(root, datei)['dateien']}
        for d in beleg['dateien']:
            if aktuell.get(d['pfad']) != d['sha256']:
                return False, set()
        return True, set(beleg['fachkraft_agent_ids'])
    except (OSError, ValueError, KeyError, TypeError):
        return False, set()


def fortsetzung_kopf(root, datei):
    """Kopfwerte fuer arbeiter.sh: '<kennung> <budget_usd>' wenn eine gueltige Fortsetzung
    anliegt, sonst leer. Kein Beleg, kein Kopf-Eintrag oder falscher Vertrag = leer.
    F-9: bei Schema 2 zusaetzlich '<schritt> <abbruchklasse>' (Schema-1-Ausgabe unveraendert)."""
    try:
        root = Path(root).resolve()
        beleg = fortsetzung_lesen(root, Path(datei).name)
        checked = pruefe_auftrag(root, datei)
        if beleg is None or checked is None or checked[1] != beleg.get('vertrag_sha256'):
            return ''
        if kopf(checked[2]).get('fortsetzung') != beleg['kennung']:
            return ''
        if beleg.get('schema') == FORTSETZUNG_SCHEMA_2:
            return '%s %s %s %s' % (beleg['kennung'], beleg.get('budget_usd') or '0', beleg['letzter_sicherer_schritt'],
                                    beleg.get('grund') or 'unbekannt')
        return beleg['kennung'] + ' ' + str(beleg.get('budget_usd') or '')
    except (OSError, ValueError, KeyError, TypeError):
        return ''


# ════════ Fortsetzen fuer alle Abbruchgruende (F-9, 24.09.2026, Paket 3) ═══════
# Schema 2 des Fortsetzungsbelegs: der letzte sichere Schritt ist fachkraft_fertig (Fachkraft ist mit
# Ergebnisdateien zurueckgekehrt) oder tor1_fertig (lokale Vorpruefung aller Pflichtpunkte bestanden).
# Abbruchgruende: Zeitgrenze, Deckel (Budgetgrenze des Laufs), Anbieterfehler, Dienst-Neustart/Prozess
# beendet, Betriebs-STOPP. Ein Patron-Stopp ist KEIN fortsetzbarer Abbruch ("Abbruch bleibt Abbruch").
# Grenzen: je Schritt hoechstens FORTSETZUNG2_JE_SCHRITT, insgesamt FORTSETZUNG2_MAX Fortsetzungen.
FORTSETZUNG_SCHEMA_2 = 2
FORTSETZUNG2_SCHRITTE = ('fachkraft_fertig', 'tor1_fertig')
FORTSETZUNG2_JE_SCHRITT = 1
FORTSETZUNG2_MAX = 2
ABBRUCH_KLASSEN = (
    ('patron', re.compile(r'Vom Patron gestoppt|Patron-Stopp|vom Patron beendet', re.I)),
    ('tor2', re.compile(r'Tor 2 hat zurueckgewiesen|TOR2-VERSTOSS|TOR2-PROBLEM|Abnahme verweigert|ZURUECKWEISUNG', re.I)),
    ('zeitgrenze', _ABBRUCH_ZEITGRENZE),
    ('deckel', re.compile(r'error_max_budget_usd|Budgetgrenze|max[_-]budget|Deckel', re.I)),
    ('stopp', re.compile(r'Betriebs-STOPP|STOPP-Datei', re.I)),
    ('dienst_neustart', re.compile(r'Dienst-Neustart|Prozess beendet ohne Abschluss|Abbruch von aussen \(SIG(?:TERM|HUP)\)', re.I)),
    ('anbieter', re.compile(r'API NICHT ERREICHBAR|nicht erreichbar|overloaded|Anbieterfehler|api_error|\b5\d\d\b|rate.?limit', re.I)),
)
FORTSETZBAR = ('zeitgrenze', 'deckel', 'anbieter', 'dienst_neustart', 'stopp')


def abbruch_klasse(text):
    """Ordnet einen Abbruchgrund einer Klasse zu (erste passende Regel). Unbekannt = 'unbekannt'."""
    for name, muster in ABBRUCH_KLASSEN:
        if muster.search(text or ''):
            return name
    return 'unbekannt'


def _fortsetzung2_hash(beleg):
    teile = {k: beleg.get(k) for k in ('auftrag', 'letzter_sicherer_schritt', 'dateien', 'fachkraft_agent_ids',
                                       'vertrag_sha256', 'ergebnisstand_sha256')}
    return _hash(_json(teile).encode('utf-8'))


def _fortsetzung2_pruefen(beleg, name):
    if (beleg.get('auftrag') != Path(name).name
            or beleg.get('letzter_sicherer_schritt') not in FORTSETZUNG2_SCHRITTE
            or not isinstance(beleg.get('dateien'), list) or not beleg['dateien']
            or any(not isinstance(d, dict) or not re.fullmatch(r'[0-9a-f]{64}', str(d.get('sha256', ''))) for d in beleg['dateien'])
            or not isinstance(beleg.get('fachkraft_agent_ids'), list) or not beleg['fachkraft_agent_ids']
            or not isinstance(beleg.get('fortsetzungen'), int)
            or not isinstance(beleg.get('fortsetzungen_je_schritt'), dict)
            or beleg.get('schritt_sha256') != _fortsetzung2_hash(beleg)):
        raise ValueError('Fortsetzungsbeleg (Schema 2) ist ungueltig oder nicht mehr hash-gebunden')
    return beleg


def _laeufe_des_auftrags(zugriffe):
    folge = []
    for r in zugriffe:
        lid = r.get('lauf_id')
        if lid and lid not in folge:
            folge.append(lid)
    return folge


def fortsetzung_vorbereiten_2(root, datei, budget_usd='0.60'):
    """Schema-2-Beleg fuer einen Auftrag in problem/ (alle fortsetzbaren Abbruchgruende).

    Prueft: Vertrag, Status problem, Abbruchklasse fortsetzbar (Patron-Stopp nie), kein Tor-2-Zettel im
    abgebrochenen Lauf, Fachkraft-Ausgabe hash-gebunden (aus dem Werkzeugprotokoll oder - bei einem
    abgebrochenen Fortsetzungslauf - aus dem vorigen Beleg, dann muss sie unveraendert sein), Grenzen je
    Schritt und insgesamt. Aendert die Auftragsdatei nicht; das macht jack_planer.fortsetzen."""
    import jack_vorgaenge
    root = Path(root).resolve()
    datei = Path(datei)
    name = datei.name
    checked = pruefe_auftrag(root, datei)
    if checked is None:
        raise ValueError('Fortsetzen gilt nur fuer geschuetzte Vertragsauftraege')
    vertrag, digest, text = checked
    kopfwerte = kopf(text)
    if kopfwerte.get('status') != 'problem':
        raise ValueError('Nur ein Auftrag mit Status problem kann fortgesetzt werden')
    grund = abbruchgrund(text)
    klasse = abbruch_klasse(grund)
    if klasse == 'patron' or re.search(r'^## Vom Patron gestoppt', text, re.M):
        raise ValueError('Abbruch bleibt Abbruch: der Patron hat diesen Auftrag gestoppt; er wird nie fortgesetzt, '
                         'nur neu erteilt')
    if klasse not in FORTSETZBAR:
        raise ValueError('Abbruchgrund ist nicht die Zeitgrenze und kein anderer fortsetzbarer Abbruch '
                         '(Deckel, Anbieterfehler, Dienst-Neustart, STOPP): ' + (grund[:120] or '(kein Problemabschnitt)'))
    bisher = fortsetzung_lesen(root, name)
    if bisher is not None and bisher.get('schema') != FORTSETZUNG_SCHEMA_2:
        raise ValueError('Fortsetzungsgrenze erreicht: dieser Auftrag wurde bereits nach Schema 1 fortgesetzt')
    if kopfwerte.get('fortsetzung') and (bisher is None or kopfwerte['fortsetzung'] != bisher['kennung']):
        raise ValueError('Auftrag traegt eine fremde Fortsetzung')
    zugriffe = _zugriffe_des_auftrags(root, name)
    laeufe = _laeufe_des_auftrags(zugriffe)
    letzter_lauf = laeufe[-1] if laeufe else None
    tor2 = (root / 'abnahme' / 'tor2').resolve()
    for r in zugriffe:
        if r.get('lauf_id') == letzter_lauf and r.get('tool') == 'Write' and r.get('entscheidung') == 'allow':
            try:
                if Path(str(r.get('pfad') or '/')).resolve().parent == tor2:
                    raise ValueError('Tor 2 hat in diesem Lauf schon einen Zettel geschrieben; kein Fortsetzen')
            except OSError:
                pass
    vault = root.parent.parent
    if bisher is not None and kopfwerte.get('fortsetzung') == bisher['kennung']:
        # abgebrochener Fortsetzungslauf: der Fachkraft-Schritt kommt aus dem vorigen Beleg
        dateien, ids = bisher['dateien'], bisher['fachkraft_agent_ids']
        for d in dateien:
            p = vault / d['pfad']
            if not p.is_file() or _hash(p.read_bytes()) != d['sha256']:
                raise ValueError('Fachkraft-Ausgabe weicht vom Fortsetzungsbeleg ab (%s); kein Fortsetzen' % d['pfad'])
        ursprung = bisher.get('ursprungslauf_id')
    else:
        fk = jack_vorgaenge.fachkraft_stand(root, name, zugriffe)
        if not fk or not fk['agent_ids']:
            raise ValueError('Keine Fachkraft-Ausfuehrung im Werkzeugprotokoll nachgewiesen; kein sicherer Schritt')
        if not fk['zurueck']:
            raise ValueError('Fachkraft ist im Werkzeugprotokoll nicht zurueckgekehrt; ihr Schritt ist nicht sicher')
        dateien = []
        for roh in fk['dateien']:
            p = Path(roh).resolve()
            if vault.resolve() not in p.parents or not p.is_file() or p.is_symlink():
                raise ValueError('Fachkraft-Ergebnisdatei fehlt oder liegt ausserhalb der Holding: ' + str(roh)[-80:])
            if p.parent == tor2:
                continue
            dateien.append({'pfad': str(p.relative_to(vault.resolve())), 'sha256': _hash(p.read_bytes())})
        if not dateien:
            raise ValueError('Die Fachkraft hat keine Ergebnisdatei geschrieben; kein sicherer Schritt')
        ids = fk['agent_ids']
        ursprung = fk['lauf_id']
    check = lokale_vorpruefung(root, datei)
    schritt = 'tor1_fertig' if (check['ok'] and check['gebunden']) else 'fachkraft_fertig'
    je_schritt = dict((bisher or {}).get('fortsetzungen_je_schritt') or {})
    gesamt = (bisher or {}).get('fortsetzungen', 0)
    if je_schritt.get(schritt, 0) >= FORTSETZUNG2_JE_SCHRITT:
        raise ValueError('Fortsetzungsgrenze erreicht: Schritt %s wurde bereits %d Mal fortgesetzt'
                         % (schritt, je_schritt[schritt]))
    if gesamt >= FORTSETZUNG2_MAX:
        raise ValueError('Fortsetzungsgrenze erreicht: insgesamt %d Fortsetzungen' % gesamt)
    je_schritt[schritt] = je_schritt.get(schritt, 0) + 1
    beleg = {'schema': FORTSETZUNG_SCHEMA_2, 'kennung': _hash((name + dt.datetime.now().isoformat()).encode())[:16],
             'zeit': dt.datetime.now().astimezone().isoformat(), 'auftrag': name, 'grund': klasse,
             'abbruch': grund[:300], 'letzter_sicherer_schritt': schritt, 'ursprungslauf_id': ursprung,
             'abgebrochener_lauf_id': letzter_lauf, 'fachkraft_agent_ids': sorted(ids), 'dateien': dateien,
             'ergebnisstand_sha256': check.get('ergebnisstand_sha256') if schritt == 'tor1_fertig' else None,
             'vertrag_sha256': digest, 'versuch': kopfwerte.get('versuch', '0'), 'budget_usd': str(budget_usd),
             'fortsetzungen': gesamt + 1, 'fortsetzungen_je_schritt': je_schritt,
             'vorheriger_beleg_kennung': (bisher or {}).get('kennung')}
    beleg['schritt_sha256'] = _fortsetzung2_hash(beleg)
    pfad = fortsetzung_pfad(root, name)
    if bisher is None:
        _neu(pfad, _json(beleg) + '\n')
        return beleg
    alt = pfad.with_name(pfad.name + '.vor_' + bisher['kennung'])
    if alt.exists():
        raise ValueError('Sicherung des vorigen Fortsetzungsbelegs existiert schon')
    alt.write_bytes(pfad.read_bytes())          # nichts loeschen: der vorige Beleg bleibt als Sicherung
    neu = pfad.with_name('.' + pfad.name + '.neu')
    neu.write_text(_json(beleg) + '\n', encoding='utf-8')
    os.replace(neu, pfad)
    return beleg


def abschliessen(root, datei, lauf_id, zettel, protokoll_snapshot):
    check = lokale_vorpruefung(root, datei)
    if not check['ok']:
        raise ValueError(check['text'])
    current = snapshot(root, datei)
    if current is None:
        return None
    if not re.fullmatch(r'[0-9a-f]{32}', lauf_id):
        raise ValueError('Gueltige Laufkennung fehlt')
    if current['sha256'] != protokoll_snapshot:
        raise ValueError('Ergebnisstand stimmt nicht mit der unabhaengigen Pruefung ueberein')
    verdict = Path(zettel).read_text(encoding='utf-8')
    required = [p['kennung'] for p in current['pflichtpunkte']]
    pruefe_prueftext(verdict, Path(datei).name, required)
    pruefe_teilbelege(root, datei, verdict, current)
    stored = lesen(root, Path(datei).name)
    receipt = {'schema': stored[0]['schema'] if stored else SCHEMA,
               'zeit': dt.datetime.now().astimezone().isoformat(),
               'datei': Path(datei).name, 'lauf_id': lauf_id, 'urteil': 'ANNAHME',
               'pruefzettel': str(Path(zettel).resolve()),
               'pruefzettel_sha256': _hash(Path(zettel).read_bytes()), 'ergebnisstand': current}
    path = Path(root) / 'betrieb' / 'auftragsabschluesse' / (current['kennung']+'_'+lauf_id+'.json')
    if path.exists():
        saved = json.loads(path.read_text())
        if saved.get('ergebnisstand') != current or saved.get('pruefzettel_sha256') != receipt['pruefzettel_sha256']:
            raise ValueError('Widerspruechlicher Abschluss fuer denselben Lauf')
        return saved
    _neu(path, _json(receipt)+'\n')
    return receipt


def quittung(root, vertrag):
    folder = Path(root) / 'betrieb' / 'auftragsabschluesse'
    candidates = []
    for path in folder.glob(vertrag['kennung']+'_*.json'):
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 1000000:
                continue
            data = json.loads(path.read_text())
            if not isinstance(data, dict) or not isinstance(data.get('ergebnisstand'), dict):
                continue
            # Die Quittung traegt das Schema ihres Vertrags (Altquittungen: 1).
            if (type(data.get('schema')) is int and data.get('schema') == vertrag.get('schema', SCHEMA)
                    and data.get('urteil') == 'ANNAHME'
                    and data.get('datei') == vertrag['datei']
                    and data['ergebnisstand'].get('kennung') == vertrag['kennung']
                    and re.fullmatch(r'[0-9a-f]{32}', str(data.get('lauf_id', '')))
                    and path.name == vertrag['kennung']+'_'+data['lauf_id']+'.json'):
                candidates.append((dt.datetime.fromisoformat(data['zeit']).timestamp(), data))
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return max(candidates, key=lambda x: x[0])[1] if candidates else None


def _annahme_aktuell(root, datei, vertrag, digest):
    """Alte Annahme gilt nur, solange Ergebnis und Pruefzettel unveraendert sind.

    Metadaten erkennen Aenderungen fuer den Cache. Beim ersten Zugriff und nach
    jeder Aenderung werden alle Inhalte erneut gehasht, auch ein referenziertes
    Video. So liest die regelmaessige Anzeige grosse Dateien nicht staendig neu.
    """
    root = Path(root).resolve(); vault = root.parent.parent
    receipt = quittung(root, vertrag)
    if receipt is None or receipt['ergebnisstand'].get('vertrag_sha256') != digest:
        return False
    snap = receipt['ergebnisstand']
    paths = [Path(datei), _vertragspfad(root, vertrag['datei']),
             root/'betrieb/auftragsabschluesse'/(vertrag['kennung']+'_'+receipt['lauf_id']+'.json')]
    extra = _vorpruefungspfad(root, vertrag['datei'])
    if extra.exists() or extra.is_symlink() or snap.get('vorpruefung_sha256'):
        paths.append(extra)
    verdict = Path(receipt.get('pruefzettel', ''))
    if verdict.parent != root/'abnahme/tor2':
        return False
    paths.append(verdict)
    for record in snap.get('dateien', []):
        paths.append(vault/record['pfad'])
        if 'medienquelle' in record:
            paths.append(vault/record['medienquelle']['pfad'])
    signatures = []
    for path in paths:
        if vault not in path.resolve().parents or any(p.is_symlink() for p in [path, *path.parents] if vault in p.parents):
            return False
        st = path.stat()
        if not stat.S_ISREG(st.st_mode):
            return False
        signatures.append((str(path), st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns))
    signature = tuple(signatures)
    key = (str(root), vertrag['kennung'])
    cached = _ANNAHME_CACHE.get(key)
    if cached is not None and cached[0] == signature:
        return cached[1]
    current = snapshot(root, datei)
    valid = current == snap and _hash(verdict.read_bytes()) == receipt.get('pruefzettel_sha256')
    if len(_ANNAHME_CACHE) >= 256:
        _ANNAHME_CACHE.clear()
    _ANNAHME_CACHE[key] = (signature, valid)
    return valid


def ist_erfolgreich(root, datei):
    """Ein Abbruch ist kein erfuellter Vorgaenger; Altauftraege bleiben lesbar."""
    try:
        text = Path(datei).read_text(encoding='utf-8')
        fields = kopf(text)
        if fields.get('status') != 'erledigt' or re.search(r'^## Vom Patron gestoppt', text, re.M):
            return False
        checked = pruefe_auftrag(root, datei)
        return checked is None or _annahme_aktuell(root, datei, checked[0], checked[1])
    except (OSError, ValueError, TypeError, KeyError):
        return False


def kurzstand(root, datei):
    try:
        checked = pruefe_auftrag(root, datei)
        if checked is None:
            felder = rahmenstand(None)
            return {'gebunden': False, 'schema': None, 'felder': felder['text'],
                    'text': felder['text'] + '; keine Einzelbelege erfasst'}
        vertrag, _, text = checked
        felder = rahmenstand(vertrag)
        required = {p['kennung'] for p in vertrag['pflichtpunkte']}
        try:
            rows = _nachweise(text)
            submitted = {p.get('kennung') for p in rows
                         if p.get('status') in ('erfuellt', 'pruefbereit') and p.get('belege')}
        except (ValueError, TypeError):
            submitted = set()
        accepted = ist_erfolgreich(root, datei)
        n = len(required & submitted)
        return {'gebunden': True, 'kennung': vertrag['kennung'], 'ablauf': vertrag['ablauf'], 'pflichtpunkte': len(required),
                'eingereicht': n, 'angenommen': accepted, 'max_versuche': vertrag.get('max_versuche', 2),
                'schema': vertrag['schema'], 'felder': felder['text'],
                'text': ('%d/%d Pflichtpunkte unabhängig angenommen' % (len(required), len(required)) if accepted
                         else '%d/%d Pflichtpunkte eingereicht; Abnahme offen' % (n, len(required)))
                        + ' · ' + felder['text']}
    except (OSError, ValueError, TypeError) as error:
        try:
            gebunden = _vertragspfad(root,Path(datei).name).exists() or bool(re.search(r'^vertrag(?:_sha256)?:',Path(datei).read_text(),re.M))
        except (OSError,ValueError):
            gebunden = False
        return {'gebunden': gebunden, 'angenommen': False, 'fehler': str(error),
                'text': 'Auftrag prüfen: ' + str(error)}


def datei_sichern(root, target, lauf_id):
    """Hook-Sicherung vor jeder Aenderung einer bestehenden Datei.

    Gleicher Pfad und identischer Inhalt werden pro Lauf nur einmal gesichert.
    Die Schreibfreigabe kommt weiterhin ausschliesslich vom Pfadwaechter.
    """
    root, target = Path(root).resolve(), Path(target)
    vault = root.parent.parent
    if not re.fullmatch(r'[0-9a-f]{32}', str(lauf_id)):
        raise ValueError('Ohne gueltigen Auftragslauf keine Dateiaenderung')
    if target.is_symlink() or vault not in target.resolve().parents:
        raise ValueError('Zu sichernde Datei liegt nicht sicher in der Holding')
    before = target.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_GESAMT_BYTES:
        raise ValueError('Datei nicht sicherbar oder groesser als 256 MiB')
    with target.open('rb') as stream:
        raw = stream.read(MAX_GESAMT_BYTES+1)
    if len(raw) > MAX_GESAMT_BYTES:
        raise ValueError('Datei waechst ueber die Sicherungsgrenze')
    after = target.stat()
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError('Datei hat sich waehrend der Sicherung veraendert')
    rel = target.resolve().relative_to(vault).as_posix()
    digest = _hash(raw)
    folder = root/'betrieb/dateisicherungen'/lauf_id/_hash(rel.encode())[:24]
    folder.mkdir(parents=True, exist_ok=True)
    saved = folder/(digest+'.sicherung')
    if not saved.exists():
        with saved.open('xb') as f:
            f.write(raw); f.flush(); os.fsync(f.fileno())
    if saved.is_symlink() or _hash(saved.read_bytes()) != digest:
        raise ValueError('Sicherung konnte nicht bytegleich bestaetigt werden')
    meta = folder/(digest+'.json')
    if not meta.exists():
        _neu(meta, _json({'pfad':rel, 'sha256':digest, 'bytes':len(raw),
                         'zeit':dt.datetime.now().astimezone().isoformat()})+'\n')
    return str(saved.relative_to(vault))


def kosten(root, name):
    """Neue zugeordnete Auftragskosten; Altverbrauch wird nicht zugerechnet."""
    from decimal import Decimal, InvalidOperation
    import jack_kosten
    latest = {}
    for row in jack_kosten.rows(root):
        if row.get('auftrag') == name and row.get('id'):
            latest[row['id']] = row
    gemeldet, geschaetzt = Decimal(0), Decimal(0)
    unbeziffert = 0
    for row in latest.values():
        source = 'usd_gemeldet' if row.get('usd_gemeldet') is not None else 'usd_geschaetzt'
        try:
            amount = Decimal(str(row.get(source)))
            if not amount.is_finite() or amount < 0:
                raise ValueError('Kein valider Betrag')
        except (InvalidOperation, ValueError):
            unbeziffert += 1
            continue
        if source == 'usd_gemeldet': gemeldet += amount
        else: geschaetzt += amount
    return {'laeufe':len(latest), 'gemeldet_usd':str(gemeldet), 'geschaetzt_usd':str(geschaetzt),
            'unbeziffert':unbeziffert, 'quelle':'betrieb/kostenlaeufe.jsonl, neue Auftragszuordnung',
            'hinweis':'Alle zugeordneten Versuche; keine unbelegte Zuordnung aelterer Kosten. Abo-Grundkosten sind nicht enthalten.'}


def ergebnislage(root):
    """Nur gebundene Auftraege mit Annahmequittung zaehlen hier als Erfolg."""
    root = Path(root)
    counts = dict(angenommen=0, offen=0, laeuft=0, freigabe=0, problem=0,
                  zurueckgestellt=0, gestoppt=0, ungeklaert=0)
    legacy, bound, seen = 0, 0, set()
    for group in GRUPPEN:
        for p in (root/'auftraege'/group).glob('*.md'):
            if p.is_symlink() or p.name.lower().startswith('readme'):
                continue
            info = kurzstand(root, p)
            if not info.get('gebunden'):
                legacy += 1
                continue
            bound += 1
            if p.name in seen or info.get('fehler'):
                counts['ungeklaert'] += 1
                continue
            seen.add(p.name)
            try:
                state = kopf(p.read_text()).get('status')
            except (OSError, ValueError):
                state = 'ungeklaert'
            if state == 'gestoppt': counts['gestoppt'] += 1
            elif group == 'erledigt':
                counts['angenommen' if info.get('angenommen') else 'ungeklaert'] += 1
            else:
                counts[group] += 1
    return {'gebundene_auftraege':bound, 'altauftraege_ohne_einzelbelege':legacy, **counts,
            'hinweis':'Nur neue gebundene Auftraege mit Einzelbelegen und unabhaengiger Annahme. Keine Gesamtabnahme aller JACK-Funktionen.',
            'text':'%d neue Aufträge unabhängig angenommen · %d weitere gebundene Aufträge · %d Altvorgänge gesondert' % (counts['angenommen'], bound-counts['angenommen'], legacy)}


if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    if len(sys.argv) == 3 and sys.argv[1] == '--fortsetzung':
        # F-6: fuer arbeiter.sh - "<kennung> <budget_usd>" oder leer
        print(fortsetzung_kopf(Path(__file__).resolve().parent, Path(sys.argv[2])))
        raise SystemExit(0)
    if len(sys.argv) != 3 or sys.argv[1] != '--pruefe':
        raise SystemExit('Erlaubt: --pruefe <Auftragsdatei>')
    try:
        root = Path(__file__).resolve().parent
        checked = pruefe_auftrag(root, Path(sys.argv[2]))
        if checked:
            import jack_faehigkeiten
            bereit = jack_faehigkeiten.vorpruefung(root, checked[0]['ablauf'], motor=kopf(checked[2]).get('motor','api'))
            if not bereit['ausfuehrbar']:
                raise ValueError(bereit['text'])
    except (OSError, ValueError) as error:
        raise SystemExit(str(error))
