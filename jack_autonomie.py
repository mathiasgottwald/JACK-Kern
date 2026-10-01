"""Aktivitaet ohne Rueckfrage (historisch: Autonomie-Quote, Block 26).

Zaehlt protokollierte Ereignisse ohne Patron-Rueckfrage gegen erfasste
Patron-Entscheidungen. Starts, Beobachtungen und Befehle sind KEIN Nachweis
erfolgreich abgeschlossener Auftraege. Die genaue Herleitung jeder Zahl steht
in betrieb/README_AUTONOMIE.md — hier nur die Berechnung selbst, damit sie
aus den Rohdaten nachrechenbar bleibt.

Quellen "ohne Patron" (JACK allein):
  - betrieb/regelentscheidungen.jsonl — jede Zeile ist eine autonome
    Kartenentscheidung von jack_regeln.py.
  - arbeiter.log — START-Zeilen (erster Versuch je Auftragsdatei) fuer
    Auftraege, deren Dateiname NIE als 'erteilt' in betrieb/freigaben.jsonl
    auftaucht (also nie eine Patron-Freigabe durchlaufen hat).
  - betrieb/posteingang.jsonl — Mails mit weg in {lernstufen, nur_ueberwachen}
    (JACK ordnet/entwirft/beobachtet, ohne dass eine Karte noetig wurde;
    weg=patron_immer zaehlt NICHT, das geht immer zum Patron).
  - betrieb/steuerung.jsonl — Sprachbefehle mit stufe==0, sobald Block 25
    diese Datei schreibt (heute meist noch nicht vorhanden -> 0).

Quelle "mit Patron":
  - betrieb/freigaben.jsonl — Zeilen mit art=='erteilt' und von=='Patron'.
"""
import datetime as dt
import fcntl
import json
import re
from pathlib import Path
from zoneinfo import ZoneInfo

ZONE = ZoneInfo('Europe/Vienna')


def now():
    return dt.datetime.now(ZONE)


def _tag(zeit_iso):
    try:
        z = dt.datetime.fromisoformat(zeit_iso.replace(' ', 'T'))
    except Exception:
        return None
    if z.tzinfo is None:
        z = z.replace(tzinfo=ZONE)
    return z.astimezone(ZONE).date().isoformat()


def _lies_jsonl(pfad):
    if not pfad.exists():
        return
    with pfad.open() as f:
        for zeile in f:
            zeile = zeile.strip()
            if not zeile:
                continue
            try:
                yield json.loads(zeile)
            except json.JSONDecodeError:
                continue


def _append_jsonl(pfad, record):
    pfad.parent.mkdir(exist_ok=True, parents=True)
    with pfad.open('a+b') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0, 2)
        if f.tell():
            f.seek(-1, 2)
            if f.read() != b'\n':
                f.write(b'\n')
        f.write((json.dumps(record, ensure_ascii=False) + '\n').encode())
        f.flush()


def _leerer_tageszaehler():
    return {'regelentscheidungen': 0, 'auftraege_ohne_karte': 0,
            'mails_ohne_karte': 0, 'sprachbefehle_stufe0': 0,
            'patron_entscheidungen': 0}


def _regelentscheidungen_je_tag(root, tage):
    for r in _lies_jsonl(Path(root) / 'betrieb' / 'regelentscheidungen.jsonl'):
        tag = _tag(r.get('zeit', ''))
        if tag:
            tage.setdefault(tag, _leerer_tageszaehler())['regelentscheidungen'] += 1


def _freigaben_je_tag(root, tage, ohne_freigabe_dateien):
    for r in _lies_jsonl(Path(root) / 'betrieb' / 'freigaben.jsonl'):
        if r.get('art') != 'erteilt':
            continue
        datei = r.get('datei', '')
        if datei:
            ohne_freigabe_dateien.add(datei)
        if r.get('von') == 'Patron':
            tag = _tag(r.get('zeit', ''))
            if tag:
                tage.setdefault(tag, _leerer_tageszaehler())['patron_entscheidungen'] += 1


ARBEITER_START_MUSTER = re.compile(r'^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})\s+START:\s+(\S+?)(?:\s+\(Versuch (\d+)\))?\s*$')


def _auftraege_ohne_karte_je_tag(root, tage, freigegebene_dateien):
    pfad = Path(root) / 'arbeiter.log'
    if not pfad.exists():
        return
    gesehen = set()
    with pfad.open(errors='replace') as f:
        for zeile in f:
            m = ARBEITER_START_MUSTER.match(zeile.strip())
            if not m:
                continue
            datum, zeitstr, datei, versuch = m.groups()
            if versuch and versuch != '1':
                continue
            if datei in gesehen:
                continue
            gesehen.add(datei)
            if datei in freigegebene_dateien:
                continue
            tage.setdefault(datum, _leerer_tageszaehler())['auftraege_ohne_karte'] += 1


MAILWEGE_OHNE_KARTE = {'lernstufen', 'nur_ueberwachen'}


def _mails_ohne_karte_je_tag(root, tage):
    for r in _lies_jsonl(Path(root) / 'betrieb' / 'posteingang.jsonl'):
        if r.get('weg') not in MAILWEGE_OHNE_KARTE:
            continue
        tag = _tag(r.get('zeit', ''))
        if tag:
            tage.setdefault(tag, _leerer_tageszaehler())['mails_ohne_karte'] += 1


def _sprachbefehle_je_tag(root, tage):
    pfad = Path(root) / 'betrieb' / 'steuerung.jsonl'
    for r in _lies_jsonl(pfad):
        if r.get('stufe') != 0:
            continue
        tag = _tag(r.get('zeit', ''))
        if tag:
            tage.setdefault(tag, _leerer_tageszaehler())['sprachbefehle_stufe0'] += 1


def _berechne_tage(root):
    tage = {}
    freigegebene_dateien = set()
    # Reihenfolge wichtig: freigaben.jsonl zuerst, damit ohne_freigabe_dateien
    # beim Zaehlen von arbeiter.log schon vollstaendig ist.
    _freigaben_je_tag(root, tage, freigegebene_dateien)
    _regelentscheidungen_je_tag(root, tage)
    _auftraege_ohne_karte_je_tag(root, tage, freigegebene_dateien)
    _mails_ohne_karte_je_tag(root, tage)
    _sprachbefehle_je_tag(root, tage)
    ergebnis = {}
    for tag, z in tage.items():
        ohne_patron = (z['regelentscheidungen'] + z['auftraege_ohne_karte']
                       + z['mails_ohne_karte'] + z['sprachbefehle_stufe0'])
        mit_patron = z['patron_entscheidungen']
        gesamt = ohne_patron + mit_patron
        quote = round(100 * ohne_patron / gesamt, 1) if gesamt else None
        ergebnis[tag] = {**z, 'ohne_patron': ohne_patron, 'mit_patron': mit_patron,
                          'vorgaenge_gesamt': gesamt, 'quote_prozent': quote}
    return ergebnis


def _fenster(tage_dict, tage_liste):
    z = _leerer_tageszaehler()
    z['ohne_patron'] = z['mit_patron'] = z['vorgaenge_gesamt'] = 0
    for tag in tage_liste:
        eintrag = tage_dict.get(tag)
        if not eintrag:
            continue
        for feld in z:
            z[feld] += eintrag.get(feld, 0)
    quote = round(100 * z['ohne_patron'] / z['vorgaenge_gesamt'], 1) if z['vorgaenge_gesamt'] else None
    z['quote_prozent'] = quote
    z['tage'] = tage_liste
    return z


def berechnen(root, an=None):
    import jack_auftrag
    an = an or now()
    tage_dict = _berechne_tage(root)
    heute = an.date()
    letzte_7 = [(heute - dt.timedelta(days=i)).isoformat() for i in range(7)]
    letzte_30 = [(heute - dt.timedelta(days=i)).isoformat() for i in range(30)]
    heute_iso = heute.isoformat()
    gestern_iso = (heute - dt.timedelta(days=1)).isoformat()
    ergebnis = {
        'zeit': an.isoformat(),
        'definition': {
            'name': 'Aktivitaet ohne Rueckfrage',
            'basis': 'Protokollierte Ereignisse, nicht abgeschlossene Auftraege',
            'keine_erfolgsquote': True,
            'abschlussqualitaet': 'nicht aus dieser Kennzahl ableitbar',
        },
        'heute': tage_dict.get(heute_iso, {**_leerer_tageszaehler(), 'ohne_patron': 0, 'mit_patron': 0, 'vorgaenge_gesamt': 0, 'quote_prozent': None}),
        'gestern': tage_dict.get(gestern_iso, {**_leerer_tageszaehler(), 'ohne_patron': 0, 'mit_patron': 0, 'vorgaenge_gesamt': 0, 'quote_prozent': None}),
        '7_tage': _fenster(tage_dict, letzte_7),
        '30_tage': _fenster(tage_dict, letzte_30),
        'alle_tage': tage_dict,
        'auftragsergebnisse': jack_auftrag.ergebnislage(root),
    }
    return ergebnis


def schreiben(root, an=None):
    an = an or now()
    ergebnis = berechnen(root, an)
    ziel_json = Path(root) / 'betrieb' / 'autonomie.json'
    ziel_json.write_text(json.dumps(ergebnis, ensure_ascii=False, indent=1))
    ziel_jsonl = Path(root) / 'betrieb' / 'autonomie.jsonl'
    zeilen = []
    for tag in sorted(ergebnis['alle_tage']):
        z = ergebnis['alle_tage'][tag]
        zeilen.append(json.dumps({'tag': tag, **z}, ensure_ascii=False))
    ziel_jsonl.write_text('\n'.join(zeilen) + ('\n' if zeilen else ''))
    return ergebnis


def briefzeile(root, an=None):
    """Ereignisanteil im Briefing; keine Aussage ueber Auftragserfolg."""
    an = an or now()
    ergebnis = berechnen(root, an)
    gestern = ergebnis['gestern']
    offen_fuer_patron = 0
    freigabe_ordner = Path(root) / 'auftraege' / 'freigabe'
    if freigabe_ordner.exists():
        offen_fuer_patron = len([p for p in freigabe_ordner.glob('*.md')
                                  if not p.is_symlink() and '.vor_' not in p.name
                                  and not p.name.lower().startswith('readme')])
    if gestern['vorgaenge_gesamt'] == 0:
        quote_text = 'keine Ereignisse erfasst'
    else:
        quote_text = f"{gestern['quote_prozent']}% ({gestern['ohne_patron']} von {gestern['vorgaenge_gesamt']} Ereignissen ohne Rueckfrage)"
    return f"Aktivitaet gestern: {quote_text} · keine Erfolgsquote · automatische Regelentscheidungen: {gestern['regelentscheidungen']} · offen fuer dich: {offen_fuer_patron}"


def lauf(root, at=None):
    """Einhaengepunkt fuer jack_betrieb.tick: einmal je Tag reicht, ist aber
    guenstig genug (reine Dateileserei), um bei jedem Tick neu zu rechnen."""
    ergebnis = schreiben(root, at)
    return {'zeit': ergebnis['zeit'], 'heute_vorgaenge': ergebnis['heute']['vorgaenge_gesamt']}


def tick(root, at=None):
    lauf(root, at)
    return [str(Path(root) / 'betrieb' / 'autonomie.json')]
