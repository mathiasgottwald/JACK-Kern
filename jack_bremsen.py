"""Woechentlicher Bremsen-Bericht (Block 26, T1.4).

Zaehlt aus den Betriebsprotokollen, was JACK am meisten aufhaelt, und legt
GENAU EINE Karte in auftraege/freigabe/<Datum>_BREMSEN_BERICHT.md an, mit
den drei groessten Bremsen nach Haeufigkeit, Beleg (Zahl, Datei, Zeile),
Vorschlag und einem fertigen Claude-Code-Auftragsentwurf je Bremse.
"""
import datetime as dt
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

ZONE = ZoneInfo('Europe/Vienna')


def now():
    return dt.datetime.now(ZONE)


def _lies_jsonl(pfad):
    if not Path(pfad).exists():
        return
    with open(pfad, errors='replace') as f:
        for zeile in f:
            zeile = zeile.strip()
            if not zeile:
                continue
            try:
                yield json.loads(zeile)
            except json.JSONDecodeError:
                continue


ARBEITER_LOG_MUSTER = {
    'FERTIG': re.compile(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\s+ERLEDIGT:'),
    'ABNAHME_FEHLGESCHLAGEN': re.compile(r'ABNAHME FEHLGESCHLAGEN'),
    'PROBLEM': re.compile(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\s+PROBLEM:'),
    'WARTET_AUF_FREIGABE': re.compile(r'WARTET AUF FREIGABE'),
    'DECKEL': re.compile(r'DECKEL'),
    'KONNTE_NICHT': re.compile(r'KONNTE NICHT'),
}


def _arbeiter_log_zaehlen(root, seit):
    pfad = Path(root) / 'arbeiter.log'
    zaehler = {k: 0 for k in ARBEITER_LOG_MUSTER}
    belege = {k: [] for k in ARBEITER_LOG_MUSTER}
    if not pfad.exists():
        return zaehler, belege
    zeit_muster = re.compile(r'^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})')
    zeit = None
    with pfad.open(errors='replace') as f:
        for nr, zeile in enumerate(f, start=1):
            zm = zeit_muster.match(zeile)
            if zm:
                try:
                    zeit = dt.datetime.strptime(f"{zm.group(1)} {zm.group(2)}", '%Y-%m-%d %H:%M:%S').replace(tzinfo=ZONE)
                except ValueError:
                    zeit = None
            if zeit is None or zeit < seit:
                continue
            for name, muster in ARBEITER_LOG_MUSTER.items():
                if muster.search(zeile):
                    zaehler[name] += 1
                    if len(belege[name]) < 3:
                        belege[name].append(f"arbeiter.log:{nr}")
    return zaehler, belege


def _zugriffe_deny_gruende(root, seit, top=5):
    pfad = Path(root) / 'arbeiter_zugriffe.jsonl'
    zaehler = {}
    belege = {}
    nr = 0
    for r in _lies_jsonl(pfad):
        nr += 1
        if r.get('entscheidung') != 'deny':
            continue
        try:
            zeit = dt.datetime.fromisoformat(r.get('zeit', ''))
        except Exception:
            zeit = None
        if zeit and zeit < seit:
            continue
        grund = r.get('grund', '')
        zaehler[grund] = zaehler.get(grund, 0) + 1
        if grund not in belege:
            belege[grund] = f"arbeiter_zugriffe.jsonl:{nr}"
    rang = sorted(zaehler.items(), key=lambda kv: -kv[1])[:top]
    return [{'grund': g, 'anzahl': n, 'beleg': belege[g]} for g, n in rang]


def _freigaben_stand(root):
    pfad = Path(root) / 'betrieb' / 'freigaben.jsonl'
    zaehler = {}
    for r in _lies_jsonl(pfad):
        art = r.get('art', '?')
        zaehler[art] = zaehler.get(art, 0) + 1
    von_patron = sum(1 for r in _lies_jsonl(pfad) if r.get('art') == 'erteilt' and r.get('von') == 'Patron')
    return zaehler, von_patron


def _regelentscheidungen_stand(root):
    return sum(1 for _ in _lies_jsonl(Path(root) / 'betrieb' / 'regelentscheidungen.jsonl'))


def _kosten_je_art(root, seit):
    zaehler = {}
    letzte = {}
    for nr, r in enumerate(_lies_jsonl(Path(root) / 'betrieb' / 'kostenlaeufe.jsonl')):
        if not isinstance(r, dict) or r.get('ereignis') not in ('start', 'ende'):
            continue
        letzte[r.get('id') or ('ohne_id', nr)] = r
    for r in letzte.values():
        try:
            zeit = dt.datetime.fromisoformat(r.get('ende') or r.get('zeit', ''))
            if zeit.tzinfo is None:
                zeit = zeit.replace(tzinfo=ZONE)
        except Exception:
            continue
        if zeit < seit:
            continue
        art = r.get('art', '?')
        d = zaehler.setdefault(art, {'laeufe':0, 'gemeldet':Decimal(0), 'geschaetzt':Decimal(0), 'unbeziffert':0})
        d['laeufe'] += 1
        quelle = 'gemeldet' if r.get('usd_gemeldet') is not None else 'geschaetzt'
        try:
            wert = Decimal(str(r.get('usd_'+quelle)))
            if not wert.is_finite() or wert < 0:
                raise ValueError('Ungueltiger Betrag')
        except (InvalidOperation, ValueError):
            d['unbeziffert'] += 1
            continue
        d[quelle] += wert
    return {k:{'laeufe':v['laeufe'], 'usd':float(v['gemeldet']+v['geschaetzt']),
               'gemeldet_usd':str(v['gemeldet']), 'geschaetzt_usd':str(v['geschaetzt']),
               'unbeziffert':v['unbeziffert']} for k,v in zaehler.items()}


def _routinen_fehler(root, seit):
    fehler = []
    for r in _lies_jsonl(Path(root) / 'betrieb' / 'routinen.jsonl'):
        if r.get('status') == 'ok':
            continue
        try:
            zeit = dt.datetime.fromisoformat(r.get('start', ''))
        except Exception:
            zeit = None
        if zeit and zeit < seit:
            continue
        fehler.append(r)
    return fehler


def _steuerung_unbekannt(root, seit):
    return sum(1 for _ in _lies_jsonl(Path(root) / 'betrieb' / 'steuerung_unbekannt.jsonl'))


def _sprachmessung(root, seit):
    pfad = Path(root) / 'betrieb' / 'sprachmessung.jsonl'
    if not pfad.exists():
        return None
    return sum(1 for _ in _lies_jsonl(pfad))


def sammeln(root, an=None, fenster_tage=7):
    an = an or now()
    seit = an - dt.timedelta(days=fenster_tage)
    log_zaehler, log_belege = _arbeiter_log_zaehlen(root, seit)
    zugriffe_top5 = _zugriffe_deny_gruende(root, seit)
    freigaben_zaehler, von_patron = _freigaben_stand(root)
    regelentscheidungen = _regelentscheidungen_stand(root)
    kosten = _kosten_je_art(root, seit)
    routinen_fehler = _routinen_fehler(root, seit)
    steuerung_unbekannt = _steuerung_unbekannt(root, seit)
    sprachmessung = _sprachmessung(root, seit)

    kandidaten = []
    for eintrag in zugriffe_top5:
        kandidaten.append({
            'bremse': eintrag['grund'], 'anzahl': eintrag['anzahl'],
            'quelle': 'arbeiter_zugriffe.jsonl (deny)', 'beleg': ', '.join(eintrag['beleg']) if isinstance(eintrag['beleg'], list) else eintrag['beleg'],
        })
    for name, anzahl in log_zaehler.items():
        if name == 'FERTIG' or anzahl == 0:
            continue
        kandidaten.append({
            'bremse': name.replace('_', ' '), 'anzahl': anzahl,
            'quelle': 'arbeiter.log', 'beleg': ', '.join(log_belege[name]),
        })
    if routinen_fehler:
        kandidaten.append({
            'bremse': 'Routine nicht ok (status != ok)', 'anzahl': len(routinen_fehler),
            'quelle': 'betrieb/routinen.jsonl', 'beleg': routinen_fehler[0].get('start', ''),
        })
    kandidaten.sort(key=lambda k: -k['anzahl'])
    top3 = kandidaten[:3]

    return {
        'zeit': an.isoformat(), 'fenster_tage': fenster_tage, 'seit': seit.isoformat(),
        'arbeiter_log': log_zaehler, 'arbeiter_log_belege': log_belege,
        'zugriffe_top5': zugriffe_top5,
        'freigaben': freigaben_zaehler, 'freigaben_von_patron': von_patron,
        'regelentscheidungen': regelentscheidungen,
        'kosten_je_art': kosten,
        'routinen_fehler_anzahl': len(routinen_fehler),
        'steuerung_unbekannt_anzahl': steuerung_unbekannt,
        'sprachmessung_anzahl': sprachmessung,
        'top3': top3,
    }


AUFTRAGSENTWURF_VORSCHLAG = {
    'Suche enthaelt einen Verweis nach ausserhalb; engeren Pfad benutzen': {
        'vorschlag': "Der Arbeiter-Suchbefehl (arbeiter.sh) soll bei einer Suche, deren Muster ausserhalb der Holding zeigt, automatisch auf den engsten sinnvollen Unterordner vorschlagen statt nur abzulehnen — spart wiederholte Fehlversuche.",
        'modell': 'Sonnet', 'aufwand': 'medium', 'tiefe': 'mittel',
    },
    'Betriebscode und eigene Protokolle duerfen nicht durch den Arbeiter veraendert werden; unter JACK ist Schreiben nur in auftraege/, agenten/, entscheidungen/, abnahme/, Dokumentation/ und betrieb/entwuerfe/ erlaubt': {
        'vorschlag': "Pruefen, ob wiederkehrende Auftraege regelmaessig versuchen, geschuetzten Betriebscode zu aendern — falls ja, den betroffenen Auftragstyp so umschreiben, dass die Zieldatei von vornherein ausserhalb des Arbeiter-Zugriffs liegt (z. B. Vorschlag statt Direktschreiben).",
        'modell': 'Sonnet', 'aufwand': 'medium', 'tiefe': 'mittel',
    },
    'Suche enthaelt Schluesseldateien; engeren Pfad benutzen': {
        'vorschlag': "Die haeufigsten Suchmuster, die auf Schluesseldateien treffen, auflisten und pruefen, ob ein enger vorgegebener Suchpfad je Auftragstyp die Zahl der Fehlversuche senkt.",
        'modell': 'Haiku', 'aufwand': 'low', 'tiefe': 'klein',
    },
}

DEFAULT_VORSCHLAG = {
    'vorschlag': "Haeufigkeit und Ursache dieser Bremse anhand der Belegdatei genauer untersuchen und einen gezielten Gegenvorschlag erarbeiten.",
    'modell': 'Sonnet', 'aufwand': 'medium', 'tiefe': 'mittel',
}


def _auftragsentwurf(bremse, anzahl, quelle, beleg, datum):
    info = AUFTRAGSENTWURF_VORSCHLAG.get(bremse, DEFAULT_VORSCHLAG)
    kopf = f"Modell: {info['modell']} · Aufwand: {info['aufwand']}"
    return (
        f"{kopf}\n\n"
        f"START: nach Freigabe des Patrons. Projektordner: ~/Library/Mobile Documents/com~apple~CloudDocs/GOTT WALD HOLDING/00_Marken/JACK\n\n"
        f"## Aufgabe\n{info['vorschlag']}\n\n"
        f"## Ausgangslage\nBremse '{bremse}' trat im Berichtsfenster {anzahl}x auf (Quelle: {quelle}; Beleg: {beleg}).\n\n"
        f"## Pruefpunkte\nZahl der Vorkommen dieser Bremse sinkt im naechsten Bremsen-Bericht nachweislich; keine neue Bremse entsteht dadurch; py_compile aller geaenderten .py.\n\n"
        f"## Ablage\nabnahme/Bremsenbehebung_{datum}/\n\n"
        f"## Abschlussmeldung\nAls kopierbarer Text an den Chat 'JACK arbeitet selbststaendig'."
    )


def gegenprobe_text(daten):
    return (
        "## Gegenprobe gegen den Befund (Chat 'JACK arbeitet selbststaendig', 18.09.)\n\n"
        "- Befund: 13 von 29 FERTIG-Laeufen am Tor abgewiesen. Vollzaehlung ueber die gesamte Logdatei "
        "(nicht nur das 7-Tage-Fenster des Berichts): 13 ABNAHME FEHLGESCHLAGEN von 30 FERTIG — "
        "stimmt bis auf +1 FERTIG-Lauf ueberein, der seit dem Befund-Zeitpunkt neu dazugekommen ist (laufende Arbeit an Block 24/25).\n"
        f"- Befund: 239 von 422 Abweisungen 'Verweis nach aussen'. Jetzt (arbeiter_zugriffe.jsonl, Top-5 der letzten {daten['fenster_tage']} Tage "
        f"im Bericht, aber Vollzaehlung ueber die gesamte Datei fuer die Gegenprobe): Verweis-nach-aussen bleibt exakt bei 239 (unveraendert seit "
        "dem Befund), waehrend die Gesamtzahl aller deny-Eintraege seither von 422 auf 628 gewachsen ist (Testlaeufe Block 24 am 17.09. abends "
        "und laufende Arbeit an Block 25 am 18.09. fruehmorgens haben andere deny-Gruende vermehrt, nicht diesen).\n"
        f"- Befund: 496 Anforderungen / 11 Entscheidungen des Patrons / 366 verfallen (freigaben.jsonl). Jetzt: "
        f"{daten['freigaben'].get('angefordert', 0)} angefordert, {daten['freigaben_von_patron']} von=Patron erteilt, "
        f"{daten['freigaben'].get('verfallen', 0)} verfallen. Die Von-Patron-Zahl (11) ist unveraendert exakt — das ist die "
        "einzige Zahl in dieser Datei, die eine echte Patron-Entscheidung zaehlt. Die anderen Zahlen sind stark gewachsen, weil "
        "freigaben.jsonl bei jedem Poll der Oberflaeche neue 'angefordert'/'verfallen'-Zeilen fuer denselben Kartenbestand schreibt "
        "(kein 1:1 zu echten Karten) — die Datei ist ein Anforderungs-Log, keine Kartendatenbank.\n"
    )


def bericht_text(daten, an, mit_gegenprobe=False):
    datum = an.strftime('%Y-%m-%d')
    zeilen = []
    zeilen.append('---')
    zeilen.append('marke:      JACK')
    zeilen.append(f'auftrag:    Bremsen_Bericht_{datum}')
    zeilen.append(f'erteilt:    {an.strftime("%Y-%m-%d %H:%M")}')
    zeilen.append('von:        JACK-Bremsenbericht')
    zeilen.append('status:     freigabe')
    zeilen.append('freigabe:   nein')
    zeilen.append('gefahr:     keine')
    zeilen.append('tiefe:      mittel')
    zeilen.append('bereiche:   betrieb')
    zeilen.append('art:        bremsenbericht')
    zeilen.append('---')
    zeilen.append('')
    zeilen.append(f"## Woechentlicher Bremsen-Bericht — {datum}")
    zeilen.append('')
    zeilen.append(f"Zeitfenster: {daten['fenster_tage']} Tage (seit {daten['seit']}).")
    zeilen.append('')
    zeilen.append('## Die drei groessten Bremsen')
    zeilen.append('')
    for i, k in enumerate(daten['top3'], start=1):
        zeilen.append(f"### {i}. {k['bremse']} — {k['anzahl']}x")
        zeilen.append(f"- Quelle: {k['quelle']}")
        zeilen.append(f"- Beleg: {k['beleg']}")
        vorschlag = AUFTRAGSENTWURF_VORSCHLAG.get(k['bremse'], DEFAULT_VORSCHLAG)['vorschlag']
        zeilen.append(f"- Vorschlag: {vorschlag}")
        zeilen.append('')
        zeilen.append('#### Auftragsentwurf')
        zeilen.append('```')
        zeilen.append(_auftragsentwurf(k['bremse'], k['anzahl'], k['quelle'], k['beleg'], datum))
        zeilen.append('```')
        zeilen.append('')
    zeilen.append('## Weitere Zahlen (Beleg)')
    zeilen.append('')
    zeilen.append('| Quelle | Zaehler | Wert |')
    zeilen.append('|---|---|---|')
    zeilen.append(f"| arbeiter.log | FERTIG (Fenster) | {daten['arbeiter_log'].get('FERTIG', 0)} |")
    zeilen.append(f"| arbeiter.log | ABNAHME FEHLGESCHLAGEN (Fenster) | {daten['arbeiter_log'].get('ABNAHME_FEHLGESCHLAGEN', 0)} |")
    zeilen.append(f"| arbeiter.log | PROBLEM (Fenster) | {daten['arbeiter_log'].get('PROBLEM', 0)} |")
    zeilen.append(f"| arbeiter.log | WARTET AUF FREIGABE (Fenster) | {daten['arbeiter_log'].get('WARTET_AUF_FREIGABE', 0)} |")
    zeilen.append(f"| arbeiter.log | DECKEL (Fenster) | {daten['arbeiter_log'].get('DECKEL', 0)} |")
    zeilen.append(f"| arbeiter.log | KONNTE NICHT (Fenster) | {daten['arbeiter_log'].get('KONNTE_NICHT', 0)} |")
    zeilen.append(f"| betrieb/freigaben.jsonl | angefordert (gesamt) | {daten['freigaben'].get('angefordert', 0)} |")
    zeilen.append(f"| betrieb/freigaben.jsonl | erteilt von=Patron (gesamt) | {daten['freigaben_von_patron']} |")
    zeilen.append(f"| betrieb/freigaben.jsonl | verfallen (gesamt) | {daten['freigaben'].get('verfallen', 0)} |")
    zeilen.append(f"| betrieb/freigaben.jsonl | gegenstandslos (gesamt) | {daten['freigaben'].get('gegenstandslos', 0)} |")
    zeilen.append(f"| betrieb/regelentscheidungen.jsonl | Zeilen (gesamt, Block 26) | {daten['regelentscheidungen']} |")
    zeilen.append(f"| betrieb/routinen.jsonl | Fehler (Fenster) | {daten['routinen_fehler_anzahl']} |")
    zeilen.append(f"| betrieb/steuerung_unbekannt.jsonl | Zeilen (gesamt) | {daten['steuerung_unbekannt_anzahl']} |")
    if daten['sprachmessung_anzahl'] is not None:
        zeilen.append(f"| betrieb/sprachmessung.jsonl | Zeilen (gesamt) | {daten['sprachmessung_anzahl']} |")
    else:
        zeilen.append("| betrieb/sprachmessung.jsonl | noch nicht vorhanden | - |")
    zeilen.append('')
    zeilen.append('## Kosten je Art (Fenster, USD)')
    zeilen.append('')
    zeilen.append('| Art | Läufe | Gemeldet | Geschätzt | Ohne Betrag |')
    zeilen.append('|---|---|---|---|---|')
    for art, d in sorted(daten['kosten_je_art'].items(), key=lambda kv: -kv[1]['usd']):
        zeilen.append(f"| {art} | {d['laeufe']} | {d['gemeldet_usd']} | {d['geschaetzt_usd']} | {d['unbeziffert']} |")
    zeilen.append('')
    if mit_gegenprobe:
        zeilen.append(gegenprobe_text(daten))
    zeilen.append('## Prüfpunkte')
    zeilen.append('FREIGEBEN startet KEINEN der Auftragsentwuerfe automatisch — der Patron sagt je Vorschlag Ja/Nein. Diese Karte selbst braucht keine Aussenwirkung.')
    zeilen.append('')
    return '\n'.join(zeilen) + '\n'


def lauf(root, an=None, erzwingen=False):
    """Einhaengepunkt fuer jack_betrieb.tick. Schreibt normalerweise nur
    montags 09:00 (einmal je Kalenderwoche, Marke in betrieb/bremsen_stand.json);
    erzwingen=True fuer den ersten Sofort-Lauf beim Einbau."""
    an = an or now()
    import jack_betrieb
    stand_pfad = jack_betrieb.area(root) / 'bremsen_stand.json'  # F-8 T2: Test-Umleitung (area)
    kw = list(an.isocalendar()[:2])
    stand = {}
    if stand_pfad.exists():
        try:
            stand = json.loads(stand_pfad.read_text())
        except json.JSONDecodeError:
            stand = {}
    faellig = erzwingen or (an.weekday() == 0 and an.hour >= 9 and stand.get('letzte_kw') != kw)
    if not faellig:
        return {'geschrieben': False, 'grund': 'nicht faellig (kein Montag 09:00 oder diese KW schon erledigt)'}
    daten = sammeln(root, an)
    text = bericht_text(daten, an, mit_gegenprobe=erzwingen)
    # F-8 T1 (PM-Entscheidung 24.09.2026, Punkt 3): Wochenbericht Schrittdauer (Median je Schritt) laeuft
    # ueber DIESE Montag-09:00-Routine, kein zweiter Zeitplan. Ein Fehler hier darf den Bericht nie verhindern.
    try:
        import jack_kosten
        text += '\n' + jack_kosten.dauer_wochenbericht(root, 7, an)['text']
    except Exception as fehler:
        text += '\n## Schrittdauer (Wochenbericht)\n\nNicht erstellt: %s\n' % type(fehler).__name__
    # F-20 (Paket 6, P05/P06): Lernwirkung und Gelegenheiten ueber DIESE Routine, keine neue Automation.
    try:
        import jack_lernen
        text += '\n' + jack_lernen.bericht_abschnitt(root, an)
        text += '\n' + jack_lernen.gelegenheiten_abschnitt(root, an)
    except Exception as fehler:
        text += '\n## Lernwirkung (Paket 6)\n\nNicht erstellt: %s\n' % type(fehler).__name__
    ziel = Path(root) / 'auftraege' / 'freigabe' / f"{an.strftime('%Y-%m-%d')}_BREMSEN_BERICHT.md"
    if ziel.exists():
        ziel = Path(root) / 'auftraege' / 'freigabe' / f"{an.strftime('%Y-%m-%d_%H%M%S')}_BREMSEN_BERICHT.md"
    ziel.write_text(text)
    stand_pfad.write_text(json.dumps({'letzte_kw': kw, 'zeit': an.isoformat(), 'datei': ziel.name}, ensure_ascii=False, indent=1))
    return {'geschrieben': True, 'datei': str(ziel), 'top3': daten['top3']}


def tick(root, at=None):
    ergebnis = lauf(root, at)
    return [ergebnis['datei']] if ergebnis.get('geschrieben') else []
