"""Kartenwaechter (Block 26, T1.2; R9 aus dem Nachtrag vom 18.09.2026).

Wendet R1-R5, R7 und R9 aus betrieb/entscheidungsregeln.json auf die Karten
in auftraege/freigabe/ an. Verschiebt Karten (mv, NIE loeschen) nach
erledigt/, zurueckgestellt/, offen/ oder
99_Archiv/Freigaben_gegenstandslos/<Datum>/, haengt jeder bewegten Karte
einen Regelentscheidungs-Vermerk an und schreibt je Bewegung eine Zeile nach
betrieb/regelentscheidungen.jsonl. Eine Karenzzeit (KARENZZEIT_MINUTEN) und
eine Pruefung auf aktive Vorgaenge (_aktiver_vorgang) gelten VOR jeder Regel
universell (Nachtrag N1).

Architektonische Sicherheitsgrenze (Pruefpunkt P7): dieses Modul enthaelt
keinen Code fuer Versand, Veroeffentlichung, Zahlung oder Installation — es
kann Klasse 'nie' aus entscheidungsregeln.json schon technisch nicht
ausloesen. Die einzigen Wirkungen sind Path.rename (echtes Verschieben
innerhalb der Holding, kein rm/unlink) und Datei-/JSONL-Schreiben (Vermerk
an der bereits verschobenen Karte, Protokollzeilen). Zwei unabhaengige
Opus-Pruefungen (18.09.2026) haben diese Fassung geprueft; beide endeten
zunaechst mit ZURUECKWEISUNG, siehe entscheidungen/2026-09-18_Block26_
Entscheidungsregeln.md fuer den vollen Verlauf der Nachbesserungen.
"""
import datetime as dt
import fcntl
import glob
import json
import os
import re
from pathlib import Path
from zoneinfo import ZoneInfo

ZONE = ZoneInfo('Europe/Vienna')

FRIST_ZUR_KENNTNIS_STUNDEN = 24
ZEITFENSTER_DUPLIKAT_S = 120
# Karenzzeit (Nachtrag N1, 18.09.2026): Vorfall 06:35:22 Uhr — der
# automatische Fuenf-Minuten-Takt hat zwei Karten, die jack_postfaecher.py
# im selben Tick angelegt hatte, Sekundenbruchteile spaeter im selben Tick
# schon wieder verschoben; ein Versandskript, das kurz danach noch auf die
# Karte zugreifen wollte, brach mit FileNotFoundError ab. Keine Karte wird
# jetzt bewegt, solange sie juenger ist als diese Frist.
KARENZZEIT_MINUTEN = 10
# Ein aktiver Testversand gilt so lange als laufend (mitarbeiter.jsonl).
AKTIVER_TESTVERSAND_MINUTEN = 15
# Positivliste der als harmlos bekannten gefahr-Werte (Nachbesserung nach der
# dritten Opus-Pruefung P7: 'GEFAHR_MIT_MARKERPFLICHT' als Sperrliste liess
# gefahr='mittel' unbemerkt durch — echte Karten mit diesem Wert existieren).
# Jeder Wert, der NICHT in dieser Liste steht (auch ein kuenftiger, heute
# unbekannter), braucht den zusaetzlichen Marker-/Selbst-Nachweis.
GEFAHR_OHNE_MARKERPFLICHT = ('keine', 'innen')


def _braucht_marker_nachweis(felder):
    return (felder.get('gefahr', '') or '').strip().casefold() not in GEFAHR_OHNE_MARKERPFLICHT


EMAIL_MUSTER = re.compile(r'[A-Za-z0-9_.+-]+@[A-Za-z0-9-]+\.[A-Za-z0-9.-]+')


def _adressen_normalisiert(text):
    """EMAIL_MUSTER frisst am Domain-Ende auch einen folgenden Satzpunkt mit
    ('...icloud.com.' -> Treffer endet auf '.com.'). Ein Satzzeichen am Ende
    gehoert nie zur Adresse, deshalb hier abstreifen — sonst vergleicht z. B.
    _gegenseite_in_selbst eine Adresse mit Punkt gegen eine Selbst-Liste ohne
    Punkt und findet faelschlich keinen Treffer (gefunden beim eigenen
    Regressionstest fuer die dritte Opus-Nachbesserung)."""
    return set(a.rstrip('.,;:!?)]}').lower() for a in EMAIL_MUSTER.findall(text))


TEST_BETREFF_MUSTER = re.compile(r'(?i)\btest\b|\[test\]|signature test|testmail')
R1_ABSENDER_MUSTER = re.compile(r'(?i)no-?reply|notifications-noreply@linkedin\.com|newsletter-noreply')
R2_BETREFF_MARKER_MUSTER = re.compile(r'(?i)\[TEST\]|Testmail|Klicktest')
R2_TRAEGER_MARKER = (
    'wird NICHT freigegeben',
    'soll nie gesendet werden',
    'geht nirgends hin',
    'dient allein dem Browser-Klicktest',
)
# R2 gilt nur fuer Karten, die selbst eine Sende-/Antwort-Handlung sind
# (mailantwort, mitarbeitermail). MITARBEITER_HINWEIS-Karten (art=entscheidung,
# vorgang=mitarbeiter_hinweis) sind passive Beobachtungen und gehoeren auch
# bei [TEST]/Test im Betreff zu R3, nicht zu R2.
R2_ARTEN = {'mailantwort', 'mitarbeitermail'}
# R7 startet NUR Karten mit einer dieser 'art'-Werte UND leerem 'bereiche'
# (Positivliste statt Sperrliste — Nachbesserung nach Opus-Pruefung P7: eine
# Sperrliste ist fail-open fuer jeden neuen/unbekannten Wert, eine
# Positivliste ist es nicht). '' steht fuer Karten ganz ohne art-Feld (z. B.
# generische Patron-Auftraege wie 'Goldene-Buecher Grundstruktur').
R7_STARTBARE_ARTEN = {'', 'auftrag'}


def now():
    return dt.datetime.now(ZONE)


def lade_regeln(root):
    pfad = Path(root) / 'betrieb' / 'entscheidungsregeln.json'
    return json.loads(pfad.read_text(encoding='utf-8'))


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


def _frontmatter(text):
    if not text.startswith('---\n'):
        return {}, text
    ende = text.find('\n---', 4)
    if ende == -1:
        return {}, text
    kopf = text[4:ende]
    rest = text[ende + 4:]
    felder = {}
    for zeile in kopf.splitlines():
        if ':' not in zeile:
            continue
        k, v = zeile.split(':', 1)
        felder[k.strip()] = v.strip()
    return felder, rest


def _selbst_adressen(root):
    """Baut die Selbst-Liste live aus postfaecher.json und allen
    Mitarbeiter-Stammdaten — keine feste Liste in entscheidungsregeln.json,
    damit neue Postfaecher/Mitarbeiter automatisch erfasst sind. Eine
    einzelne kaputte Stammdaten-Datei darf den ganzen Lauf nie abbrechen
    (Nachbesserung nach der zweiten Opus-Pruefung P7, Punkt 6) — sie wird
    uebersprungen, nicht die ganze Selbst-Liste verworfen."""
    adressen = set()
    holding = Path(root).parents[1]
    postfaecher = Path(root) / 'betrieb' / 'postfaecher.json'
    if postfaecher.exists():
        try:
            d = json.loads(postfaecher.read_text(encoding='utf-8'))
            for p in d.get('postfaecher', []):
                a = p.get('adresse')
                if a:
                    adressen.add(a.lower())
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            pass
    for sd in glob.glob(str(holding / '08_Mitarbeiter' / '*' / '00_Stammdaten' / 'stammdaten.json')):
        try:
            d = json.loads(Path(sd).read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            continue
        kontakt = d.get('kontakt', {})
        for feld in ('email_arbeit', 'email_privat'):
            v = kontakt.get(feld)
            if v:
                adressen.add(v.lower())
    return adressen


def _adressen_in_zeile(body, label):
    m = re.search(rf'^\|\s*{re.escape(label)}\s*\|(.*)\|\s*$', body, re.M)
    if not m:
        return set()
    return _adressen_normalisiert(m.group(1))


def _betreff_aus_body(body):
    m = re.search(r'^\|\s*Betreff\s*\|(.*)\|\s*$', body, re.M)
    if m:
        return m.group(1).strip()
    m = re.search(r'(?i)Betreff:\s*(.+?)(?:\.\s*$|\n|$)', body, re.M)
    return m.group(1).strip() if m else ''


def _r2_betreff_treffer(text):
    """Nur die STARKEN Testmarker: [TEST], Testmail, Klicktest. Das lose Wort
    'TEST' als eigener Betreff-Baustein wird NICHT hier, sondern erst in
    _pruefe_r2 zusammen mit der Gegenseiten-Pruefung behandelt (Nachbesserung
    nach Opus-Pruefung P7: ein echter externer Betreff wie 'Load Test
    Ergebnisse' darf allein am Wort 'Test' nicht als Testkarte durchgehen)."""
    m = R2_BETREFF_MARKER_MUSTER.search(text)
    return m.group(0) if m else None


def _test_wort_treffer(text):
    for token in re.split(r'[^A-Za-z]+', text):
        if token.upper() == 'TEST':
            return True
    return False


def _gegenseite_in_selbst(felder, body, selbst):
    """True nur, wenn JEDE im Kartentext gefundene E-Mail-Adresse in der
    Selbst-Liste steht — kein Rateschritt noetig, wer 'Sender' und wer
    'Empfaenger' ist. Enthaelt der Text irgendeine fremde Adresse, gilt die
    Gegenseite NICHT als nachgewiesen selbst.

    Nachbesserung nach der DRITTEN Opus-Pruefung P7: die vorige Fassung
    verlangte eine '| An |'-Tabellenzeile — die echten Block-23/23b/23c/23d-
    Traeger-Karten nennen die Adresse aber im Fliesstext ('... ausschliesslich
    an Gottwald.mathias@icloud.com.'), nicht in einer Tabelle, und fielen
    dadurch faelschlich durch. 'Alle Adressen ⊆ Selbst-Liste' ist robuster
    als ein Fliesstext-Muster zu raten (Regression aus der zweiten
    Nachbesserung, die genau das vermeiden sollte) und bleibt trotzdem sicher:
    kommt irgendwo eine fremde Adresse vor, ist der Nachweis nicht erbracht."""
    adressen = _adressen_normalisiert(body)
    return bool(adressen) and adressen <= selbst


def _lese_karten(root, fehler=None):
    """fehler: optionale Liste, in die unlesbare Karten eingetragen werden
    (Nachbesserung nach der zweiten Opus-Pruefung P7, Punkt 6) — eine
    einzelne unlesbare Datei darf den ganzen Lauf nicht abbrechen."""
    ordner = Path(root) / 'auftraege' / 'freigabe'
    karten = []
    for p in sorted(ordner.glob('*.md')):
        if p.is_symlink() or '.vor_' in p.name or p.name.lower().startswith('readme'):
            continue
        try:
            text = p.read_text(encoding='utf-8')
            felder, body = _frontmatter(text)
        except (OSError, UnicodeDecodeError) as fehlergrund:
            if fehler is not None:
                fehler.append({'karte': p.name, 'fehler': f"lesen fehlgeschlagen: {fehlergrund}"[:300]})
            continue
        karten.append({'pfad': p, 'text': text, 'felder': felder, 'body': body})
    return karten


def _gegenseite_text(body):
    """Der Text zwischen 'an' und '— Betreff:' im festen Kartenformat
    'Antwort aus X an Y — Betreff: ...', das jack_postfaecher.py fuer
    mailantwort-Karten erzeugt. Leerer String, wenn das Muster fehlt."""
    m = re.search(r'(?i)Antwort aus\s+\S+.*?\ban\s+(.+?)\s*[—-]\s*Betreff:', body)
    return m.group(1) if m else ''


def _pruefe_r1(felder, body):
    if felder.get('art') != 'mailantwort':
        return None
    mailart = felder.get('mailart', '')
    if mailart != 'Newsletter/Werbung':
        return None
    # Zuerst nur im strukturierten Gegenseiten-Ausschnitt suchen (praeziser);
    # nur wenn dieses feste Muster fehlt, auf den ganzen Text ausweichen
    # (Nachbesserung nach der dritten Opus-Pruefung P7, Punkt R1: ein
    # Treffer irgendwo im Fliesstext ist schwaecher als ein Treffer direkt
    # bei der Gegenseiten-Adresse).
    ausschnitt = _gegenseite_text(body)
    treffer = R1_ABSENDER_MUSTER.search(ausschnitt) if ausschnitt else None
    quelle = 'Gegenseiten-Ausschnitt'
    if treffer is None:
        treffer = R1_ABSENDER_MUSTER.search(body)
        quelle = 'gesamter Kartentext'
    if treffer:
        marker = f"mailart={mailart}; Absender-Muster '{treffer.group(0)}' ({quelle})"
        return ('R1', 'gegenstandslos', 'Antwortentwurf auf automatisierte Mail/Newsletter', marker)
    return None


def _pruefe_r2(felder, body, dateiname, selbst):
    # HARTE Vorbedingung (Nachbesserung nach der zweiten Opus-Pruefung P7,
    # Punkt 2): nur Karten, die selbst eine Sende-/Antwort-Handlung SIND
    # (mailantwort, mitarbeitermail), kommen ueberhaupt fuer R2 in Frage —
    # kein Bypass mehr ueber einen zufaelligen Traeger-Satz im Fliesstext
    # bei einer anderen Kartenart.
    if felder.get('art') not in R2_ARTEN:
        return None
    braucht_selbst_nachweis = _braucht_marker_nachweis(felder)

    marker_treffer = next((m for m in R2_TRAEGER_MARKER if m in body), None)
    if marker_treffer:
        # Auch der starke Traeger-Satz zaehlt bei gefahr=hoch/aussen nur mit
        # nachgewiesener Selbst-Gegenseite (Nachbesserung: ein echter Satz wie
        # "Der Vertrag wird NICHT freigegeben" in einer echten Aussenmail darf
        # nicht allein am Wortlaut durchgehen).
        if braucht_selbst_nachweis and not _gegenseite_in_selbst(felder, body, selbst):
            return None
        return ('R2', 'erledigt', 'Testkarte/Traeger — nach Testversand bzw. sofort erledigt', marker_treffer)

    betreff_felder = ' '.join([felder.get('auftrag', ''), dateiname, _betreff_aus_body(body)])
    muster_treffer = _r2_betreff_treffer(betreff_felder)
    if muster_treffer:
        if braucht_selbst_nachweis and not _gegenseite_in_selbst(felder, body, selbst):
            return None
        return ('R2', 'erledigt', 'Testkarte/Traeger — nach Testversand bzw. sofort erledigt',
                f"Betreff/Auftrag-Muster '{muster_treffer}'")

    # Loser Wortmarker 'TEST' (z. B. in 'Re_TEST_Markenauftritt') zaehlt nur,
    # wenn die Gegenseite nachweislich kein Dritter ist — sonst koennte ein
    # echter externer Betreff wie 'Load Test Ergebnisse' faelschlich
    # durchgehen (Nachbesserung nach Opus-Pruefung P7, Punkt 2).
    if _test_wort_treffer(betreff_felder) and _gegenseite_in_selbst(felder, body, selbst):
        return ('R2', 'erledigt', 'Testkarte/Traeger — nach Testversand bzw. sofort erledigt',
                "Betreff-Wort 'TEST' UND Gegenseite in Selbst-Liste")
    return None


def _pruefe_r3(felder, body, selbst):
    if felder.get('vorgang') != 'mitarbeiter_hinweis':
        return None
    von = _adressen_in_zeile(body, 'Von')
    an = _adressen_in_zeile(body, 'An')
    beide_selbst = bool(von) and bool(an) and von <= selbst and an <= selbst
    if beide_selbst:
        marker = f"Von {sorted(von)} und An {sorted(an)} beide in Selbst-Liste"
        return ('R3', 'gegenstandslos', 'Mitarbeiter-Hinweis: Gegenseite kein Dritter', marker)
    if _braucht_marker_nachweis(felder):
        # Ausserhalb von gefahr=keine/innen nur die starke Selbst-Selbst-
        # Pruefung oben zulassen, nicht den schwaecheren Dritte+Test-Betreff-
        # Zweig (Nachbesserung nach Opus-Pruefung P7).
        return None
    test_treffer = TEST_BETREFF_MUSTER.search(_betreff_aus_body(body))
    if test_treffer:
        marker = f"Betreff-Testmuster '{test_treffer.group(0)}' (Gegenseite Dritter)"
        return ('R3', 'gegenstandslos', 'Mitarbeiter-Hinweis: Dritte, aber Test-Betreff', marker)
    return None


def _zeit_von_karte(k):
    try:
        zeit = dt.datetime.fromisoformat(k['felder'].get('erteilt', '').replace(' ', 'T'))
        if zeit.tzinfo is None:
            zeit = zeit.replace(tzinfo=ZONE)
        return zeit
    except Exception:
        return None


def _r4_duplikate(karten):
    """Liefert {Path: (kennung, ziel, grund, marker)} fuer alle NICHT-ersten
    Karten einer erkannten Dublette (die zeitlich fruheste Karte je Gruppe
    bleibt unberuehrt von R4 und faellt ggf. unter eine andere Regel).

    Zwei Staerken (Nachbesserung nach Opus-Pruefung P7, Punkt 5):
    - STARK: gleicher 'eintrag'-Hash — erlaubt auch bei gefahr hoch/aussen.
    - SCHWACH: gleicher Betreff, Zeitabstand <= Fenster — nur bei gefahr
      innen/keine, UND ueber echte Cluster (Union-Find) statt paarweiser
      Verkettung, damit der Vermerk nie auf eine Karte zeigt, die selbst
      schon (als Nicht-Erste) verschoben wird.
    """
    ergebnisse = {}

    # 1) STARK: gleicher eintrag-Hash. Karten ohne lesbares 'erteilt' nehmen
    # NICHT teil (Nachbesserung nach der zweiten Opus-Pruefung P7, Punkt 5):
    # ohne verlaessliche Zeit laesst sich nicht sagen, welche Karte zuerst
    # da war, also lieber beide unberuehrt lassen als raten.
    nach_eintrag = {}
    for k in karten:
        eintrag = k['felder'].get('eintrag')
        if eintrag and _zeit_von_karte(k) is not None:
            nach_eintrag.setdefault(eintrag, []).append(k)
    for eintrag, gruppe in nach_eintrag.items():
        if len(gruppe) < 2:
            continue
        sortiert = sorted(gruppe, key=_zeit_von_karte)
        erste = sortiert[0]
        for zweite in sortiert[1:]:
            marker = f"gleicher eintrag '{eintrag}' wie {erste['pfad'].name} [stark]"
            ergebnisse[zweite['pfad']] = ('R4', 'gegenstandslos', f"Duplikat derselben Mail — verbleibt bei {erste['pfad'].name}", marker)

    # 2) SCHWACH: gleicher Betreff im Zeitfenster, nur bei gefahr innen/keine,
    # nur mit lesbarem 'erteilt'.
    rest = [k for k in karten if k['pfad'] not in ergebnisse and not k['felder'].get('eintrag')
            and not _braucht_marker_nachweis(k['felder'])
            and _zeit_von_karte(k) is not None]
    betreffe = {id(k): (_betreff_aus_body(k['body']).lower() or k['felder'].get('auftrag', '').lower()) for k in rest}
    zeiten = {id(k): _zeit_von_karte(k) for k in rest}
    wurzel = {id(k): id(k) for k in rest}

    def find(x):
        while wurzel[x] != x:
            wurzel[x] = wurzel[wurzel[x]]
            x = wurzel[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            wurzel[ra] = rb

    for i, a in enumerate(rest):
        if not betreffe[id(a)]:
            continue
        for b in rest[i + 1:]:
            if betreffe[id(a)] != betreffe[id(b)]:
                continue
            if abs((zeiten[id(a)] - zeiten[id(b)]).total_seconds()) <= ZEITFENSTER_DUPLIKAT_S:
                union(id(a), id(b))

    cluster = {}
    for k in rest:
        cluster.setdefault(find(id(k)), []).append(k)
    for gruppe in cluster.values():
        if len(gruppe) < 2:
            continue
        gruppe_sortiert = sorted(gruppe, key=lambda k: zeiten[id(k)])
        spanne_s = (zeiten[id(gruppe_sortiert[-1])] - zeiten[id(gruppe_sortiert[0])]).total_seconds()
        if spanne_s > ZEITFENSTER_DUPLIKAT_S:
            # Transitive Kette breiter als das Fenster (z. B. eine Serie
            # periodischer Mails gleichen Betreffs): KEIN Duplikat-Schluss,
            # lieber alle Karten des Clusters unberuehrt lassen (Nachbesserung
            # nach der zweiten Opus-Pruefung P7, Punkt 5).
            continue
        erste = gruppe_sortiert[0]
        for zweite in gruppe_sortiert[1:]:
            marker = f"gleicher Betreff, Zeitabstand <= {ZEITFENSTER_DUPLIKAT_S}s zu {erste['pfad'].name} [schwach]"
            ergebnisse[zweite['pfad']] = ('R4', 'gegenstandslos', f"Duplikat derselben Mail (Zeitfenster) — verbleibt bei {erste['pfad'].name}", marker)
    return ergebnisse


def _pruefe_r5(felder, an):
    if felder.get('art') != 'zur_kenntnis':
        return None
    erteilt = felder.get('erteilt', '')
    try:
        zeit = dt.datetime.fromisoformat(erteilt.replace(' ', 'T'))
        if zeit.tzinfo is None:
            zeit = zeit.replace(tzinfo=ZONE)
    except Exception:
        return None
    alter_stunden = (an - zeit).total_seconds() / 3600
    if alter_stunden >= FRIST_ZUR_KENNTNIS_STUNDEN:
        marker = f"erteilt {erteilt}, Alter {alter_stunden:.1f}h >= {FRIST_ZUR_KENNTNIS_STUNDEN}h"
        return ('R5', 'erledigt', 'ZUR-KENNTNIS-Karte nach 24h verfallen', marker)
    return None


def _pruefe_r7(felder, markensperren):
    gefahr = (felder.get('gefahr', '') or '').strip().casefold()
    tiefe = (felder.get('tiefe', '') or '').strip().casefold()
    if gefahr not in ('keine', 'innen') or tiefe != 'klein':
        return None
    art = (felder.get('art', '') or '').strip().casefold()
    bereiche = (felder.get('bereiche', '') or '').strip().casefold()
    # Positivliste statt Sperrliste (Nachbesserung nach Opus-Pruefung P7,
    # Punkt 4): nur ausdruecklich als startbar erkannte art-Werte kommen
    # ueberhaupt in Frage; jeder neue/unbekannte art-Wert bleibt liegen.
    if art not in R7_STARTBARE_ARTEN:
        return None
    # bereiche muss LEER sein, nicht nur "keine der bekannten Inhaltsfreigabe-
    # Woerter enthalten" (Nachbesserung nach der zweiten Opus-Pruefung P7,
    # Punkt 4/3): R7 ist die einzige Regel, die Inhalt ohne jede weitere
    # Pruefung startet, deshalb hier die engste denkbare Bedingung — jede
    # nicht-leere, nicht auf der Positivliste stehende bereiche-Angabe
    # (auch unbekannte) haelt die Karte an, nicht nur bekannte Reizwoerter.
    if bereiche:
        return None
    # 'marke' und die Schluessel aus markensperren.json casefold vergleichen
    # (Nachbesserung nach der zweiten Opus-Pruefung P7, Punkt 4: sonst
    # entkommt z. B. 'marke: goldene-buecher' der Sperre auf 'Goldene-Buecher').
    marke_norm = (felder.get('marke', '') or '').strip().casefold()
    sperre = next((v for k, v in markensperren.items() if k.strip().casefold() == marke_norm), None)
    if sperre and sperre.get('zustand') == 'gestoppt':
        marker = f"Marke {felder.get('marke', '')} gestoppt seit {sperre.get('seit')}"
        return ('R7', 'zurueckgestellt', f"Marke auf Stopp: {sperre.get('grund', '')}", marker)
    marker = f"gefahr={gefahr}, tiefe={tiefe}, art='{art}' in Positivliste, bereiche leer"
    return ('R7', 'offen', 'Ohne Inhaltsfreigabe, klein und gefahrlos — Start ohne Karte', marker)


# Nachtrag N2 (18.09.2026): der zuverlaessige, real vorkommende Marker ist
# die Ueberschrift '## ENTSCHIEDEN — Patron' (gefunden in beiden echten
# 'bereits entschieden'-Karten). Die vom Patron zusaetzlich genannte Phrase
# 'Entscheidung des Patrons' allein waere zu locker — dieselbe Karte traegt
# im Titel auch 'Entscheidung des Patrons NOETIG' (also GENAU DAS GEGENTEIL),
# deshalb verlangt das Muster einen abgeschlossenen Zustand, nicht nur das
# Vorkommen der Woerter.
# Block 26, Teil 2 (18.09.2026): alle vier Alternativen sind zeilenverankert
# (^...$), nicht nur die erste. Fund der Opus-Endkontrolle (P7-Analog) zu
# Teil 2: die drei ungeankerten Alternativen waren ueber ein Fliesstext-
# Vorkommen ueberall in der Karte auszuloesen - und Teil 2 selbst (T2.1,
# empfehlungen_erzeugen) schreibt jetzt Modelltext in genau diese Karten
# hinein. Ein Kartentext, der das Modell zu einem Satz wie "... wurde vom
# Patron entschieden ..." in der Begruendung verleitet, haette eine noch
# offene Entscheidung stillschweigend aus dem Freigaben-Kasten verschwinden
# lassen. Jetzt muss die Zeile GANZ (bis auf Leerraum) aus dem Muster
# bestehen - das erzeugt das eigene Empfehlungs-Format (immer mit
# "**Warum:** "/"**Empfehlung:** " davor) nie.
R9_ENTSCHIEDEN_MUSTER = re.compile(
    r'(?im)^##\s*ENTSCHIEDEN\b.*Patron$'
    r'|^\s*Entscheidung des Patrons\s*:\s*(?:ja|entschieden|erledigt|erteilt)\s*$'
    r'|^\s*freigegeben\s+(?:wurde\s+)?durch den Patron\s*$'
    r'|^\s*vom Patron (?:entschieden|freigegeben)\s*$'
)
# Positivliste der "Entscheidungsarten" aus auftraege/README_AUFTRAEGE.md
# (Block 13, 17.09.2026): NUR bei diesen art-Werten bedeutet FREIGEBEN
# "nach erledigt/". Bei art=auftrag (und allen anderen/fehlenden Werten)
# bedeutet FREIGEBEN "nach offen/, der Arbeiter holt sie" — ein echter
# Auftrag, den R9 faelschlich nach erledigt/ schoebe, wuerde NIE ausgefuehrt
# und ginge still verloren (Fund der fokussierten Opus-Pruefung zu R9,
# 18.09.2026, ZURUECKWEISUNG Punkt 1).
R9_ENTSCHEIDUNGSARTEN = {
    'vertragsregister', 'kostenstufen', 'regeldateien',
    'verhaltensregeln', 'werkzeuge', 'anleitung', 'entscheidung',
}


def _entschieden_block_hat_inhalt(body, treffer):
    """Nachbesserung nach der fokussierten Opus-Pruefung zu R9 (Punkt 2/3):
    beide realen '.vor_patronentscheidung'-Zwischenstaende zeigen, dass die
    Ueberschrift '## ENTSCHIEDEN — Patron' auch als LEERE Vorlage vorkommen
    kann, bevor der eigentliche Text folgt. Nur eine Ueberschrift mit
    mindestens einer nicht-leeren Zeile darunter (bis zur naechsten
    '##'-Ueberschrift oder Dateiende) zaehlt als abgeschlossen."""
    rest = body[treffer.end():]
    ende = re.search(r'(?m)^##\s', rest)
    abschnitt = rest[:ende.start()] if ende else rest
    return any(zeile.strip() for zeile in abschnitt.splitlines())


def _pruefe_r9(root, felder, body, pfad):
    # HARTE Vorbedingungen, waehrend der eigenen Verifikation und der
    # fokussierten Opus-Pruefung gefunden:
    # 1) Nur art in der Entscheidungsarten-Positivliste — sonst koennte ein
    #    freigegebener, noch nicht ausgefuehrter ECHTER Auftrag (art=auftrag)
    #    nach erledigt/ statt offen/ verschwinden.
    # 2) freigabe: ja im Kopf (nicht nur Fliesstext) — eine Karte kann eine
    #    eingebettete '## ENTSCHIEDEN — Patron'-Teilentscheidung zu EINER
    #    Teilfrage enthalten und trotzdem insgesamt noch offen sein (reale
    #    Beispiele: die Schluessel- und RECHTSCHECK-Karten, beide
    #    gefahr=hoch, enthalten die Ueberschrift, sind aber NICHT
    #    abgeschlossen).
    art = (felder.get('art', '') or '').strip().casefold()
    if art not in R9_ENTSCHEIDUNGSARTEN:
        return None
    if (felder.get('freigabe', '') or '').strip().casefold() != 'ja':
        return None
    treffer = R9_ENTSCHIEDEN_MUSTER.search(body)
    if treffer and _entschieden_block_hat_inhalt(body, treffer):
        marker = f"Textmuster '{treffer.group(0)[:70].strip()}', Block nicht leer"
        return ('R9', 'erledigt', 'Bereits entschieden — Textmuster im Kartentext', marker)
    # Der zweite Nachweisweg aus dem Nachtrag (Datei unter entscheidungen/,
    # die die Karte namentlich nennt) wurde ENTFERNT (Nachbesserung nach der
    # fokussierten Opus-Pruefung, Punkt 4): die Suche traf zu locker (28 von
    # 50 Dateien allein am Wort 'entschieden', auch bei 'noch nicht
    # entschieden'). freigabe: ja + ein gefuellter ENTSCHIEDEN-Block beweisen
    # mehr als ein Teilstring-Treffer in einer fremden Datei.
    return None


def _mit_sicherheitsgate(treffer, felder):
    """Letzte Verteidigungslinie (Backstop), NICHT die einzige: die
    eigentliche Risikoabwaegung fuer gefahr=hoch/aussen sitzt bereits IN den
    einzelnen Regelfunktionen (R2 verlangt bei losem 'TEST'-Wort zusaetzlich
    eine nachgewiesene Selbst-Gegenseite; R3 laesst bei hoch/aussen nur die
    starke Selbst-Selbst-Pruefung zu, nicht den schwaecheren Dritte+Test-
    Zweig; R4 laesst den unscharfen Zeitfenster-Zweig bei hoch/aussen gar
    nicht erst zu). Nachbesserung nach Opus-Pruefung P7, Punkt 1: vorher war
    dieses Gate wirkungslos, weil jede Regel immer einen nichtleeren Marker
    lieferte — jetzt liefern die riskanten Regelzweige bei gefahr=hoch/aussen
    bereits selbst None, und dieses Gate faengt zusaetzlich jeden Fall ab,
    in dem trotzdem (Programmierfehler, kuenftige Regel) ein leerer Marker
    durchrutschen wuerde."""
    if treffer is None:
        return None
    kennung, ziel, grund, marker = treffer
    if kennung in ('R1', 'R2', 'R3', 'R4', 'R5', 'R9'):
        if _braucht_marker_nachweis(felder) and not marker:
            return None
    return treffer


def _kartenalter_minuten(pfad, felder, an):
    """'Das juengere zaehlt': die spaetere (juengste) der beiden Zeitquellen
    mtime/erteilt gilt als Referenz — im Zweifel wird die Karte als JUENGER
    behandelt, nie als aelter (konservativ in Richtung 'noch nicht bewegen').
    Liefert None nur, wenn ueberhaupt keine Zeit ermittelbar ist (Datei
    verschwunden zwischen Lesen und Pruefen) — dann behandelt der Aufrufer
    das wie 'zu jung', bewegt also ebenfalls nicht."""
    quellen = []
    try:
        mtime = dt.datetime.fromtimestamp(pfad.stat().st_mtime, tz=ZONE)
        quellen.append(mtime)
    except OSError:
        pass
    erteilt_zeit = _zeit_von_karte({'felder': felder})
    if erteilt_zeit is not None:
        quellen.append(erteilt_zeit)
    if not quellen:
        return None
    juengste = max(quellen)
    return (an - juengste).total_seconds() / 60


def _testversand_aktiv(root, dateiname, an):
    pfad = Path(root) / 'betrieb' / 'mitarbeiter.jsonl'
    for r in _lies_jsonl_liste(pfad):
        if r.get('art') != 'testversand' or r.get('vorlage') != dateiname:
            continue
        try:
            zeit = dt.datetime.fromisoformat(r.get('zeit', ''))
        except (ValueError, TypeError):
            continue
        if 0 <= (an - zeit).total_seconds() / 60 <= AKTIVER_TESTVERSAND_MINUTEN:
            return True
    return False


def _lies_jsonl_liste(pfad):
    if not pfad.exists():
        return []
    ergebnis = []
    try:
        with pfad.open(encoding='utf-8') as f:
            for zeile in f:
                zeile = zeile.strip()
                if not zeile:
                    continue
                try:
                    ergebnis.append(json.loads(zeile))
                except json.JSONDecodeError:
                    continue
    except (OSError, UnicodeDecodeError):
        pass
    return ergebnis


def _laeuft_referenziert(root, dateiname):
    pfad = Path(root) / 'betrieb' / 'laufende.json'
    if not pfad.exists():
        return False
    try:
        d = json.loads(pfad.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return False
    # Einfache, robuste Pruefung: taucht der Dateiname irgendwo im laeufe-
    # Baum auf (als Schluessel oder als Wert), gilt er als referenziert.
    # laufende.json hat kein festes Schema fuer Freigabe-Karten (es
    # verfolgt in erster Linie Auftragsdateien) — deshalb bewusst
    # grosszuegig: im Zweifel bleibt die Karte lieber liegen.
    return dateiname in json.dumps(d.get('laeufe', {}), ensure_ascii=False)


def _aktiver_vorgang(root, pfad, an):
    """Nachtrag N1: eine Sperrdatei <karte>.lock, ein Eintrag in
    betrieb/laufende.json, oder ein Testversand-Log-Eintrag der letzten
    AKTIVER_TESTVERSAND_MINUTEN Minuten mit dieser Karte als 'vorlage'
    haelt die Karte an, unabhaengig vom Alter."""
    if Path(str(pfad) + '.lock').exists():
        return True
    if _laeuft_referenziert(root, pfad.name):
        return True
    if _testversand_aktiv(root, pfad.name, an):
        return True
    return False


def _geschuetzt(root, pfad):
    """Block 28: wartende Mitarbeiter-Karten bewegt keine Regel. Im Zweifel geschuetzt."""
    try:
        import jack_mitarbeiter
        return jack_mitarbeiter.karte_geschuetzt(root, pfad)
    except Exception:
        return 'mitarbeitermail' in Path(pfad).read_text(encoding='utf-8', errors='replace')[:2000]


def _auswertung(root, an, lese_fehler=None, gesperrt=None):
    selbst = _selbst_adressen(root)
    markensperren = {}
    mp = Path(root) / 'betrieb' / 'markensperren.json'
    if mp.exists():
        try:
            markensperren = json.loads(mp.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            if lese_fehler is not None:
                lese_fehler.append({'karte': None, 'fehler': 'markensperren.json unlesbar — R7 sperrt diesmal keine Marke'})
    karten = _lese_karten(root, fehler=lese_fehler)
    r4_treffer = _r4_duplikate(karten)
    ergebnis = {}
    for k in karten:
        felder, body, pfad = k['felder'], k['body'], k['pfad']
        # Nachtrag N1 (18.09.2026): Karenzzeit und Sperre bei aktivem
        # Vorgang gelten VOR jeder Regel, universell — keine Karte wird
        # bewegt, waehrend sie noch frisch ist oder ein anderer Vorgang
        # (Sperrdatei, laufende.json, Testversand der letzten 15 Minuten)
        # auf sie zeigt.
        alter_minuten = _kartenalter_minuten(pfad, felder, an)
        if alter_minuten is None or alter_minuten < KARENZZEIT_MINUTEN:
            continue
        if _aktiver_vorgang(root, pfad, an):
            continue
        treffer = _pruefe_r1(felder, body)
        if treffer is None:
            treffer = _pruefe_r2(felder, body, pfad.name, selbst)
        if treffer is None:
            treffer = _pruefe_r3(felder, body, selbst)
        if treffer is None:
            treffer = r4_treffer.get(pfad)
        if treffer is None:
            treffer = _pruefe_r5(felder, an)
        if treffer is None:
            treffer = _pruefe_r7(felder, markensperren)
        if treffer is None:
            treffer = _pruefe_r9(root, felder, body, pfad)
        treffer = _mit_sicherheitsgate(treffer, felder)
        if treffer is not None and _geschuetzt(root, pfad):
            if gesperrt is not None:
                gesperrt.append((pfad, treffer))
            continue
        if treffer is not None:
            ergebnis[pfad] = treffer
    return ergebnis, len(karten)


def trockenlauf(root, at=None):
    an = at or now()
    lese_fehler = []
    treffer, gesamt = _auswertung(root, an, lese_fehler)
    zeilen = [
        {'karte': pfad.name, 'regel': kennung, 'ziel': ziel, 'grund': grund, 'marker': marker}
        for pfad, (kennung, ziel, grund, marker) in treffer.items()
    ]
    zeilen.sort(key=lambda z: z['karte'])
    return {'zeit': an.isoformat(), 'karten_gesamt': gesamt, 'bewegt': len(zeilen),
            'bleibt': gesamt - len(zeilen), 'zeilen': zeilen, 'lese_fehler': lese_fehler}


def _ziel_ordner(root, ziel, an):
    if ziel == 'gegenstandslos':
        return Path(root) / '99_Archiv' / 'Freigaben_gegenstandslos' / an.strftime('%Y-%m-%d')
    return Path(root) / 'auftraege' / ziel


def anwenden(root, at=None):
    an = at or now()
    fehler = []
    gesperrt = []
    treffer, _ = _auswertung(root, an, lese_fehler=fehler, gesperrt=gesperrt)
    holding = Path(root).parents[1]
    for pfad, (kennung, ziel, grund, marker) in gesperrt:
        _append_jsonl(Path(root) / 'betrieb' / 'regelentscheidungen.jsonl', {
            'zeit': an.isoformat(), 'karte': pfad.name, 'regel': kennung,
            'art': 'gesperrt_mitarbeiterkarte', 'haette': ziel, 'grund': grund,
            'wirkung': 'nicht bewegt - wartende Mitarbeiter-Karte (Block 28)'})
    bewegt = []
    for pfad, (kennung, ziel, grund, marker) in treffer.items():
        try:
            if not pfad.exists():
                # Schon von einem ueberlappenden Lauf bewegt (z. B. Tick
                # waehrend eines manuellen Laufs) — nichts zu tun.
                continue
            zielordner = _ziel_ordner(root, ziel, an)
            zielordner.mkdir(parents=True, exist_ok=True)
            zielpfad = zielordner / pfad.name
            zaehler = 1
            while zielpfad.exists():
                zaehler += 1
                zielpfad = zielordner / f"{pfad.stem}_{an.strftime('%H%M%S')}_{zaehler}{pfad.suffix}"
            # ECHTES Verschieben zuerst (Path.rename, atomar innerhalb der
            # Holding — kein rm/unlink, N6-konform), der Vermerk kommt DANACH
            # an die jetzt am Zielort liegende Datei (Nachbesserung nach der
            # zweiten Opus-Pruefung P7, Punkt 1: bricht der Lauf zwischen
            # rename und Vermerk ab, ist die Karte vollstaendig samt Inhalt
            # am Zielort vorhanden — es fehlt hoechstens der Vermerk, nichts
            # geht verloren). Der Vermerk wird im ANHAENGE-Modus geschrieben,
            # nicht per Lesen+Ueberschreiben (Nachbesserung nach der dritten
            # Opus-Pruefung P7, Punkt 1: write_text(read_text()+neu) leert
            # die Datei kurzzeitig auf 0 Byte, bevor der neue Inhalt steht —
            # bricht der Lauf genau da ab, waere der Karteninhalt weg. Ein
            # reines Anhaengen kann eine Datei nie auf 0 Byte kuerzen).
            pfad.rename(zielpfad)
            vermerk = f"\n\n## Regelentscheidung {an.isoformat()} — {kennung}: {grund} ({marker})\n"
            with zielpfad.open('a', encoding='utf-8') as f:
                f.write(vermerk)
            satz = {
                'zeit': an.isoformat(), 'karte': pfad.name, 'regel': kennung,
                'von': str(pfad.relative_to(holding)),
                'nach': str(zielpfad.relative_to(holding)),
                'grund': grund, 'marker': marker,
            }
            _append_jsonl(Path(root) / 'betrieb' / 'regelentscheidungen.jsonl', satz)
            bewegt.append(satz)
        except Exception as fehlergrund:
            fehler.append({'zeit': an.isoformat(), 'karte': pfad.name, 'fehler': str(fehlergrund)[:300]})
    if fehler:
        _append_jsonl(Path(root) / 'betrieb' / 'regelentscheidungen_fehler.jsonl',
                       {'zeit': an.isoformat(), 'anzahl': len(fehler), 'fehler': fehler})
    return bewegt


# ═══ Block 26, Teil 2 (18.09.2026) ═══════════════════════════════════════
# T2.1 Empfehlung von JACK, T2.3 Klassifizierung (R8), T2.4 R6 Standbericht.
# Beides laeuft NACHGELAGERT zu R1-R9 (nach anwenden()), auf das, was noch in
# auftraege/freigabe/ liegt. Ein Fehler hier darf R1-R9 nie aufhalten - siehe
# lauf().


def klasse_von(felder):
    """R8: handelnder=Patron ODER art=anleitung -> 'hausaufgabe'. Sonst
    'ein_klick': jede Karte, die nach R1-R9 noch in auftraege/freigabe/
    liegt und keine Hausaufgabe ist, ist laut Grundsatz aus
    betrieb/entscheidungsregeln.json (E1/E2) eine echte Aussenwirkungs- oder
    Inhaltsfreigabe - eine Karte fuer den Patron entsteht nur dafuer, R1-R9
    haetten alles andere schon bewegt. Case-insensitiv, unabhaengig davon, ob
    die Feldnamen (wie bei diesem Modul ueblich) Original- oder (wie bei
    jack_oberflaeche.py) Kleinschreibung tragen."""
    def feld(name):
        for k, v in (felder or {}).items():
            if k.strip().lower() == name:
                return (v or '').strip()
        return ''
    # F-83 (29.09.2026, Patron-Beschwerde): eine wiederkehrende Erinnerung (bereiche: erinnerung, siehe
    # jack_vertraege.py/bin/freigabekarten_v2_migration.py) zaehlte bisher als echte Entscheidung mit -
    # sie tauchte in "Freigabe N von M" auf, obwohl sie in "Hausaufgaben & Erinnerungen" gehoert.
    if (feld('handelnder').lower() == 'patron' or feld('art').lower() == 'anleitung'
            or feld('bereiche').lower() == 'erinnerung'):
        return 'hausaufgabe'
    return 'ein_klick'


def _schluessel(root, name='ANTHROPIC_API_KEY'):
    """Wie server.py:schluessel() - eigenstaendig nachgebaut, damit dieses
    Modul server.py nicht importieren muss (Kreisimport vermeiden: server.py
    importiert bereits Module, die ihrerseits jack_regeln aufrufen)."""
    try:
        import jack_tresor
        wert = jack_tresor.lesen(name)
        if wert:
            return wert
    except Exception:
        pass
    for datei in ('SCHLUESSEL.txt', '.env'):
        pfad = Path(root) / datei
        if not pfad.exists():
            continue
        try:
            zeilen = pfad.read_text(encoding='utf-8').splitlines()
        except OSError:
            continue
        for zeile in zeilen:
            if zeile.strip().startswith(name) and '=' in zeile:
                wert = zeile.split('=', 1)[1].strip().strip('"').strip("'")
                if wert and not wert.startswith('HIER_'):
                    return wert
    return None


EMPFEHLUNG_UEBERSCHRIFT = '## Empfehlung von JACK'


def _hat_empfehlung(body):
    return EMPFEHLUNG_UEBERSCHRIFT in (body or '')


# Nachbesserung 23.09.2026 (Fehlbefund an
# auftraege/freigabe/2026-09-23_PRUEFBERICHT_Ponytail_Hooks_vor_Installation.md):
# empfehlungen_erzeugen() rief fuer eine Karte OHNE jede Angabe (kein
# marke-/gefahr-Feld, keine Abschnitte 'Auftrag'/'Worum es geht') trotzdem
# das Modell auf - das Modell bekam praktisch keinen echten Inhalt und hat
# sich eine plausibel klingende, aber sachfremde Freigabe-Situation
# ausgedacht (Thema Lieferantenzertifizierung statt Sicherheitsbericht).
# Zwei getrennte Sicherungen dagegen, beide NUR in empfehlungen_erzeugen():
#
# 1) _bericht_ohne_freigabekarte(): Sicherheits-/Pruefberichte (erkennbar am
#    Dateinamen) und Dateien ganz ohne die vier Kernfelder sind keine echten
#    Freigabe-Karten - sie werden komplett uebersprungen (kein Hinweis,
#    keine Empfehlung, kein Modellaufruf), die Begruendung geht nach
#    betrieb/regelentscheidungen.jsonl. klasse_von() selbst bleibt
#    unveraendert (Block 28 und jack_oberflaeche.py verlassen sich auf ihr
#    bisheriges Verhalten) - der Filter sitzt ausschliesslich hier.
# 2) HINWEIS_UEBERSCHRIFT/_ohne_empfehlungsgrundlage(): eine echte, aber sehr
#    duenne Karte (marke/gefahr auf Standardwert UND weder 'Auftrag' noch
#    'Worum es geht' gefuellt) bekommt einen FESTEN Hinweistext statt einer
#    geratenen Empfehlung - kein Modellaufruf.
# Zeilenschema der Dateinamen ist <Datum>_<TYP>_<Rest>.md (siehe echter
# Fehlbefund '2026-09-23_PRUEFBERICHT_Ponytail_Hooks_vor_Installation.md') -
# das Praefix steht also NICHT am reinen Stringanfang, sondern direkt hinter
# dem Datumsstempel. Deshalb Suche nach '_<TYP>_' bzw. '<TYP>_' am Anfang,
# nicht name.startswith(...) (Regressionstest 23.09.2026 hat den ersten,
# zu engen Ansatz aufgedeckt).
BERICHT_DATEI_MUSTER = re.compile(r'(?:^|_)(PRUEFBERICHT|MESSBERICHT|BERICHT)_', re.I)
FREIGABE_KERNFELDER = ('marke', 'gefahr', 'handelnder', 'art')


def _bericht_ohne_freigabekarte(pfad, felder):
    """Liefert einen Protokoll-Grund (String), wenn `pfad` keine echte
    Freigabe-Karte ist (Berichts-Dateiname ODER voelliges Fehlen der vier
    Kernfelder marke/gefahr/handelnder/art), sonst None."""
    treffer = BERICHT_DATEI_MUSTER.search(pfad.name)
    if treffer:
        return f"Dateiname enthaelt Berichts-Praefix '{treffer.group(1)}_'"
    if not any((felder.get(f) or '').strip() for f in FREIGABE_KERNFELDER):
        return 'keines der Felder marke/gefahr/handelnder/art im Kopf vorhanden'
    return None


HINWEIS_UEBERSCHRIFT = '## Hinweis JACK — keine automatische Empfehlung moeglich'


def _hat_hinweis(body):
    return HINWEIS_UEBERSCHRIFT in (body or '')


def _ohne_empfehlungsgrundlage(marke, gefahr, kurz, worum):
    """True, wenn Marke und Gefahr auf ihrem Standardwert stehen UND weder
    'Auftrag' noch 'Worum es geht' Text geliefert haben - dann bekaeme das
    Modell praktisch keinen echten Inhalt und wuerde sich (wie am
    23.09.2026 geschehen) eine Situation ausdenken."""
    return (
        (marke or '').strip().casefold() in ('', 'unbekannt')
        and (gefahr or '').strip().casefold() in ('', 'keine')
        and not kurz
        and not worum
    )


def _karte_anhaengen_wenn_ohne(pfad, marker, text_zusatz):
    """Haengt text_zusatz nur an, wenn `marker` noch NICHT in der Datei
    steht - geprueft ERST NACHDEM die exklusive Sperre (fcntl.flock, wie
    _append_jsonl oben) steht, kein Zeitfenster mehr zwischen Pruefung und
    Anhaengen. Notwendig, weil zwischen dem ersten (billigen) Check und dem
    Anhaengen ein Modellaufruf liegt, der Sekunden dauert - in dieser Zeit
    kann ein zweiter, gleichzeitiger Lauf (z. B. der Fuenf-Minuten-Takt
    waehrend eines Handlaufs) dieselbe Karte ebenfalls bearbeiten.
    Regressionsgrund (18.09.2026): genau das geschah beim ersten echten
    Lauf und erzeugte den Abschnitt zweimal in sechs Karten - siehe
    entscheidungen/2026-09-18_Block26_Entscheidungen_im_Lauf.md. Gibt True
    zurueck, wenn tatsaechlich angehaengt wurde, sonst False (ein anderer
    Lauf war schneller - kein doppelter Abschnitt, keine verschwendete
    Modellantwort im Text).

    Nachbesserung (Opus-Endkontrolle, 18.09.2026): `pfad.open('a+')` legt
    die Datei NEU an, wenn ein anderer, gleichzeitiger Lauf die Karte
    waehrenddessen verschoben hat (R1-R9/R6) - es waere eine Geisterkarte
    ohne Frontmatter entstanden. `os.open` OHNE `O_CREAT` schliesst das:
    fehlt die Datei, kommt FileNotFoundError, es wird nichts angelegt."""
    try:
        fd = os.open(str(pfad), os.O_RDWR | os.O_APPEND)
    except FileNotFoundError:
        return False
    try:
        with os.fdopen(fd, 'r+', encoding='utf-8') as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.seek(0)
            aktuell = f.read()
            if marker in aktuell:
                return False
            f.seek(0, 2)
            f.write(text_zusatz)
            f.flush()
            return True
    except FileNotFoundError:
        return False


_EMPFEHLUNG_ANZEIGE_RE = re.compile(
    r'\*\*(Entscheid|Empfehlung|Warum|Bei Ja|Bei Nein):\*\*\s*(.+)')


def empfehlung_lesen(body):
    """Fuer jack_oberflaeche.py (T2.1-Anzeige): liest den bereits erzeugten
    Empfehlungs-Abschnitt einer Karte zurueck, ohne einen neuen Modellaufruf.
    None, wenn die Karte (noch) keine Empfehlung traegt."""
    if not _hat_empfehlung(body):
        return None
    treffer = re.search(re.escape(EMPFEHLUNG_UEBERSCHRIFT) + r'(.*)$', body or '', re.S)
    abschnitt = treffer.group(1) if treffer else ''
    felder = {k: v.strip() for k, v in _EMPFEHLUNG_ANZEIGE_RE.findall(abschnitt)}
    entscheid = felder.get('Entscheid', '').strip().upper()
    if entscheid not in ('FREIGEBEN', 'ABLEHNEN', 'WARTEN'):
        entscheid = 'FREIGEBEN'
    return {
        'entscheid': entscheid,
        'empfehlung': felder.get('Empfehlung', ''),
        'warum': felder.get('Warum', ''),
        'bei_ja': felder.get('Bei Ja', ''),
        'bei_nein': felder.get('Bei Nein', ''),
    }


def _empfehlung_frage(titel, kurz, worum, gefahr, marke, aussen):
    angaben = ['Titel: %s' % (titel or '(ohne Titel)'),
               'Marke: %s' % (marke or 'unbekannt'),
               'Gefahr: %s%s' % (gefahr or 'keine', ' (wirkt nach aussen)' if aussen else '')]
    if worum:
        angaben.append('Worum es geht: %s' % worum)
    if kurz:
        angaben.append('Kurzfassung: %s' % kurz)
    return (
        'Du bereitest fuer den Patron (Mathias Gottwald, GOTT WALD HOLDING) eine '
        'Empfehlung zu genau EINER wartenden Freigabe-Karte vor. Du entscheidest '
        'NICHTS - der Patron drueckt den Knopf. Gib GENAU diese fuenf Zeilen '
        'zurueck, sonst nichts, keine Einleitung, keine Erklaerung drumherum:\n'
        'ENTSCHEID: FREIGEBEN oder ABLEHNEN oder WARTEN\n'
        'EMPFEHLUNG: ein Satz, was du empfiehlst\n'
        'WARUM: ein Satz, die Begruendung\n'
        'BEI_JA: ein Satz, was passiert, wenn der Patron FREIGEBEN drueckt\n'
        'BEI_NEIN: ein Satz, was passiert, wenn der Patron ABLEHNEN drueckt\n\n'
        'Angaben zur Karte:\n' + '\n'.join(angaben)
    )


_EMPFEHLUNG_ZEILE_RE = re.compile(
    r'^(ENTSCHEID|EMPFEHLUNG|WARUM|BEI_JA|BEI_NEIN)\s*:\s*(.+)$', re.M)


def _empfehlung_parsen(antwort):
    felder = {k: v.strip() for k, v in _EMPFEHLUNG_ZEILE_RE.findall(antwort or '')}
    entscheid = felder.get('ENTSCHEID', '').strip().upper()
    if entscheid not in ('FREIGEBEN', 'ABLEHNEN', 'WARTEN'):
        # Sicherer Ruckfall: der bisherige Standard-Knopf (FREIGEBEN) bleibt
        # golden, statt aus einem unklaren Modelltext zu raten.
        entscheid = 'FREIGEBEN'
    empfehlung = felder.get('EMPFEHLUNG') or '(keine Empfehlung im Modelltext gefunden)'
    warum = felder.get('WARUM') or ('(keine Begruendung im Modelltext gefunden — '
                                    'siehe Empfehlung oben)')
    bei_ja = felder.get('BEI_JA') or 'Die Karte wird angewandt.'
    bei_nein = felder.get('BEI_NEIN') or 'Die Karte wird abgelehnt und abgelegt.'
    return entscheid, empfehlung, warum, bei_ja, bei_nein


def _empfehlung_abschnitt(entscheid, empfehlung, warum, bei_ja, bei_nein, stufe, modell, an):
    return (
        '\n\n' + EMPFEHLUNG_UEBERSCHRIFT + '\n\n'
        '**Entscheid:** %s\n'
        '**Empfehlung:** %s\n'
        '**Warum:** %s\n'
        '**Bei Ja:** %s\n'
        '**Bei Nein:** %s\n\n'
        '_Erzeugt %s — Stufe %s (%s) — unabhaengige Pruefung nicht '
        'durchgefuehrt (Sprosse Fachentwurf)._\n'
        % (entscheid, empfehlung, warum, bei_ja, bei_nein, an.isoformat(), stufe, modell)
    )


def empfehlungen_erzeugen(root, an=None):
    """T2.1: jede Karte der Klasse 'ein_klick' ohne eigene Empfehlung bekommt
    eine von JACK - Stufe 1 (Fachkraft), bei gefahr=hoch Stufe 2 (Pruefer).
    Ohne Modellaufruf, wenn die Karte schon eine traegt oder kein Schluessel
    da ist. Ein Fehler an EINER Karte haelt die anderen nicht auf und haelt
    vor allem R1-R9 (anwenden(), oben) nie auf - diese Funktion laeuft erst
    danach und wird von lauf() separat abgesichert."""
    an = an or now()
    root = Path(root)
    ordner = root / 'auftraege' / 'freigabe'
    if not ordner.is_dir():
        return []
    if not _schluessel(root):
        return []
    # modell_router.draft() erwartet fuer 'keys' einen AUFRUFBAREN Zugriff
    # (wie server.py:schluessel), keinen bereits aufgeloesten String - eine
    # fruehere Fassung uebergab hier den String direkt und scheiterte an
    # jedem Kartenzugriff mit "'str' object is not callable".
    schluessel_fn = lambda name='ANTHROPIC_API_KEY': _schluessel(root, name)
    try:
        import modell_router
    except Exception:
        return []
    erzeugt = []
    for pfad in sorted(ordner.glob('*.md')):
        # F-77 (28.09.2026, kern): ein fuehrender Unterstrich ist die Vorlagen-Konvention im ganzen Haus
        # (_VORLAGE_...) - ohne diese Ausnahme bekam die neue Karten-Vorlage
        # auftraege/freigabe/_VORLAGE_FREIGABEKARTE_v2.md faelschlich eine echte, kostenpflichtige
        # Modell-Empfehlung. Datei ausserhalb der kern-Zustaendigkeitsliste - kleine, symmetrische
        # Ausnahme zur bestehenden readme-Ausnahme direkt daneben, Sicherung jack_regeln.py.vor_F77.
        if pfad.is_symlink() or pfad.name.lower().startswith('readme') or pfad.name.startswith('_'):
            continue
        try:
            text = pfad.read_text(encoding='utf-8')
        except OSError:
            continue
        felder, body = _frontmatter(text)
        if klasse_von(felder) != 'ein_klick' or _hat_empfehlung(body) or _hat_hinweis(body):
            continue
        # Nachbesserung 23.09.2026: Berichte/Karten ganz ohne Kernfelder sind
        # keine echten Freigabe-Karten - komplett uebersprungen, kein
        # Modellaufruf, kein Kartentext, nur ein Protokolleintrag.
        uebersprung_grund = _bericht_ohne_freigabekarte(pfad, felder)
        if uebersprung_grund:
            _append_jsonl(root / 'betrieb' / 'regelentscheidungen.jsonl', {
                'zeit': an.isoformat(), 'karte': pfad.name, 'regel': 'T2.1-Filter',
                'grund': uebersprung_grund,
                'wirkung': 'keine Empfehlung erzeugt - keine echte Freigabe-Karte'})
            continue
        # Block 28: an einer wartenden Mitarbeiter-Karte schreibt keine Regel mit.
        if _geschuetzt(root, pfad):
            continue
        try:
            titel = (felder.get('karte') or felder.get('auftrag') or pfad.stem).replace('_', ' ')
            kurz_treffer = re.search(r'^##+\s*Auftrag\s*$(.+?)(^##\s|\Z)', body, re.M | re.S)
            kurz = re.sub(r'\s+', ' ', (kurz_treffer[1] if kurz_treffer else '')).strip()[:220]
            worum_treffer = re.search(r'^##+\s*Worum es geht\s*$(.+?)(^##\s|\Z)', body, re.M | re.S)
            worum = re.sub(r'\s+', ' ', (worum_treffer[1] if worum_treffer else '')).strip()[:220]
            gefahr = (felder.get('gefahr') or 'keine').strip().lower()
            marke = felder.get('marke', '') or ''
            if _ohne_empfehlungsgrundlage(marke, gefahr, kurz, worum):
                hinweis = ('\n\n' + HINWEIS_UEBERSCHRIFT + '\n\n'
                           "Zu wenig Angaben: Marke/Gefahr fehlen, keine Abschnitte "
                           "'Auftrag'/'Worum es geht' gefunden. Kein Modellaufruf "
                           "ausgeloest (Nachbesserung 23.09.2026).\n")
                if _karte_anhaengen_wenn_ohne(pfad, HINWEIS_UEBERSCHRIFT, hinweis):
                    erzeugt.append(pfad.name)
                continue
            rolle = 'pruefer' if gefahr == 'hoch' else 'fachkraft'
            frage = _empfehlung_frage(titel, kurz, worum, gefahr,
                                      marke, gefahr in ('hoch', 'aussen'))
            ergebnis = modell_router.draft(root, schluessel_fn, frage, role=rolle,
                                           art='fachentwurf', datenklasse='intern')
            entscheid, empfehlung, warum, bei_ja, bei_nein = _empfehlung_parsen(
                ergebnis.get('antwort', ''))
            abschnitt = _empfehlung_abschnitt(entscheid, empfehlung, warum, bei_ja, bei_nein,
                                              ergebnis.get('stufe'), ergebnis.get('modell'), an)
            if _karte_anhaengen_wenn_ohne(pfad, EMPFEHLUNG_UEBERSCHRIFT, abschnitt):
                erzeugt.append(pfad.name)
        except Exception as fehlergrund:
            try:
                _append_jsonl(root / 'betrieb' / 'regelentscheidungen_fehler.jsonl',
                              {'zeit': an.isoformat(), 'anzahl': 1,
                               'fehler': [{'karte': pfad.name,
                                          'fehler': ('Empfehlung nicht erzeugt: %s'
                                                     % fehlergrund)[:300]}]})
            except Exception:
                pass
    return erzeugt


# ─────────────────────────── T2.4: R6 Standbericht ─────────────────────────
R6_VERARBEITET_DATEI = 'r6_verarbeitet.jsonl'


def _r6_bereits_verarbeitet(root, postfach, uid):
    """Billiger Vorab-Check OHNE Sperre - nur um die IMAP-/Modellkosten fuer
    laengst erledigte Mails zu sparen. Der verbindliche, wettlaufsichere
    Check ist _r6_beanspruchen() unten."""
    pfad = Path(root) / 'betrieb' / R6_VERARBEITET_DATEI
    if not pfad.exists():
        return False
    try:
        for zeile in pfad.read_text(encoding='utf-8').splitlines():
            try:
                rec = json.loads(zeile)
            except (json.JSONDecodeError, ValueError):
                continue
            if rec.get('postfach') == postfach and rec.get('uid') == uid:
                return True
    except OSError:
        pass
    return False


def _r6_beanspruchen(root, postfach, uid, an):
    """Beansprucht (postfach, uid) EXKLUSIV, bevor der teure Modellaufruf
    beginnt - Pruefung UND Markierung liegen unter derselben Sperre, kein
    Zeitfenster mehr dazwischen. Gibt True zurueck, wenn dieser Lauf die
    Mail beanspruchen durfte (dann macht er weiter), sonst False (ein
    anderer, gleichzeitiger Lauf war schneller - keine doppelte Fassung,
    keine doppelten Modellkosten).

    Nachbesserung (Opus-Endkontrolle, 18.09.2026): die erste Fassung prüfte
    _r6_bereits_verarbeitet() VOR dem Modellaufruf und markierte erst NACH
    dessen Ende (_r6_markieren) - zwei gleichzeitige Laeufe haetten dieselbe
    Mail beide bearbeitet und zwei Einsatzvorschlaege erzeugt."""
    pfad = Path(root) / 'betrieb' / R6_VERARBEITET_DATEI
    pfad.parent.mkdir(exist_ok=True, parents=True)
    with pfad.open('a+', encoding='utf-8') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        for zeile in f.read().splitlines():
            try:
                rec = json.loads(zeile)
            except (json.JSONDecodeError, ValueError):
                continue
            if rec.get('postfach') == postfach and rec.get('uid') == uid:
                return False
        f.seek(0, 2)
        f.write(json.dumps({'zeit': an.isoformat(), 'postfach': postfach, 'uid': uid},
                           ensure_ascii=False) + '\n')
        f.flush()
        return True


def _r6_kennung_von_absender(root, absender, jack_mitarbeiter):
    """Loest die Absenderadresse auf einen Mitarbeiter-kennung auf - ueber
    die Stammdaten (email_arbeit/email_privat), casefold verglichen. Kein
    Treffer -> None (R6 gilt nur fuer echte Mitarbeiter-Absender).

    Nachbesserung (Opus-Endkontrolle, 18.09.2026): die erste Fassung suchte
    das erste beliebige "etwas@etwas"-Vorkommen im GESAMTEN From-Header per
    Regex - ein gefaelschter Anzeigename wie
    '"dween.mohammad@gottwald.world" <angreifer@evil.tld>' haette die ECHTE
    Adresse ignoriert und stattdessen den Anzeigenamen als Treffer genommen
    (kein Spoofing noetig, SPF/DKIM wird hier nicht geprueft). `email.utils.
    parseaddr` liest stattdessen die tatsaechliche Briefumschlag-Adresse aus
    einem RFC-822-From-Header, genau wie das restliche System (u. a.
    jack_postfaecher.py) E-Mail-Header behandelt. Ausserdem trug die erste
    Fassung das falsche Feld ('kennung' statt 'id' - register() liefert 'id',
    siehe jack_mitarbeiter._eintrag) und haette dadurch NIE einen Treffer
    gefunden."""
    import email.utils
    _, adresse = email.utils.parseaddr(str(absender or ''))
    adresse = adresse.strip().lower()
    if not adresse or '@' not in adresse:
        return None
    try:
        eintraege = jack_mitarbeiter.register(root).get('mitarbeiter', [])
    except Exception:
        return None
    for e in eintraege:
        kennung = e.get('id')
        if not kennung:
            continue
        try:
            stamm = jack_mitarbeiter.stammdaten(root, kennung)
        except Exception:
            continue
        kontakt = (stamm or {}).get('kontakt', {})
        for feld in ('email_arbeit', 'email_privat'):
            if str(kontakt.get(feld) or '').lower() == adresse:
                return kennung
    return None


def _r6_pruefung_frage(name, kennung, betreff, text, vorbelastet):
    return (
        'Du prueft fuer den Patron (Mathias Gottwald, GOTT WALD HOLDING) einen '
        'eingegangenen Standbericht von %s (Kennung %s). Du entscheidest NICHTS '
        'und schickst NICHTS - dein Ergebnis ist ein Entwurf, den der Patron im '
        'Freigaben-Kasten sieht und selbst entscheidet. Erfinde keine Fakten, die '
        'nicht im Bericht stehen; Angaben ohne Beleg kennzeichnest du als ANNAHME.\n\n'
        'Gib GENAU dieses JSON zurueck, sonst nichts, kein Fliesstext drumherum:\n'
        '{"kurzfassung": ["stichpunkt", "..."], '
        '"befunde": [{"arbeit":"","stand":"erledigt|in Arbeit|offen|unklar",'
        '"beleg":"","bewertung":""}], "stunden_genannt": 0, '
        '"verbesserungen": ["...", "..."], '
        '"einsatzkarte": [{"marke":"","geeignet":"ja|teilweise|nein",'
        '"begruendung":"","quelle":"Bericht"}], '
        '"optionen": [{"rang":1,"marke":"","teil":"","ziel":"","stunden":"",'
        '"warum_din":"","nutzen":"","risiko":"","quelle":"Bericht",'
        '"abschluss":false}, {"rang":2}, {"rang":3}], '
        '"wochenplan": [{"block":"","was":"","stunden":""}]}\n\n'
        'Genau drei Eintraege in "optionen", Rang 1 bis 3. %s\n\n'
        'Betreff: %s\n\nBericht:\n%s'
        % (name, kennung,
           ('Es liegt bereits eine offene Fassung mit noch nicht abgeschlossener '
            'Arbeit vor - Rang 1 MUSS deren Abschluss sein ("abschluss": true), '
            'sonst darf "abschluss" bei keiner Option true sein.' if vorbelastet else
            'Es liegt noch keine offene Fassung vor - "abschluss" bleibt bei allen '
            'drei Optionen false.'),
           betreff, (text or '')[:6000])
    )


def _r6_json_parsen(antwort):
    text = (antwort or '').strip()
    treffer = re.search(r'\{.*\}', text, re.S)
    if not treffer:
        raise ValueError('Kein JSON im Modelltext gefunden')
    daten = json.loads(treffer.group(0))
    optionen = daten.get('optionen') or []
    if len(optionen) != 3:
        raise ValueError('Es muessen genau drei Optionen sein, gereiht (%d erhalten)'
                         % len(optionen))
    return daten


def standberichte_pruefen(root, an=None):
    """R6: eine neue Mitarbeiter-Mail mit Standbericht (oder Anlass Termin/
    Vertrag) bekommt einen aktualisierten Einsatzvorschlag - die vorherige,
    noch offene Fassung wandert dabei aus auftraege/freigabe/ nach
    auftraege/erledigt/ (verschoben, nie geloescht, N6-konform),
    damit der Patron nur die EINE aktuelle Entscheidung sieht (R6-Wirkung).
    Jede verarbeitete Mail wird in betrieb/r6_verarbeitet.jsonl vermerkt -
    ein zweiter Lauf verarbeitet sie nie erneut (Idempotenz wie R1-R9)."""
    an = an or now()
    root = Path(root)
    posteingang = root / 'betrieb' / 'posteingang.jsonl'
    if not posteingang.exists():
        return []
    try:
        import jack_mitarbeiter
        import jack_postfaecher
        import modell_router
    except Exception:
        return []
    if not _schluessel(root):
        return []
    schluessel_fn = lambda name='ANTHROPIC_API_KEY': _schluessel(root, name)
    erzeugt = []
    try:
        zeilen = posteingang.read_text(encoding='utf-8').splitlines()[-500:]
    except OSError:
        return []
    for zeile in zeilen:
        try:
            rec = json.loads(zeile)
        except (json.JSONDecodeError, ValueError):
            continue
        postfach, uid = rec.get('postfach'), rec.get('uid')
        if not postfach or uid is None or _r6_bereits_verarbeitet(root, postfach, uid):
            continue
        betreff = rec.get('betreff', '')
        kennung = _r6_kennung_von_absender(root, rec.get('absender', ''), jack_mitarbeiter)
        if not kennung:
            continue  # kein bekannter Mitarbeiter-Absender - R6 gilt nicht
        # Guenstiger Vorfilter am Betreff allein, bevor die IMAP-Mail geholt
        # wird - der volle Test (mit Text) kommt gleich danach noch einmal.
        try:
            vorfilter = (jack_mitarbeiter.ist_bericht(betreff, '')
                        or any(a in ('Termin', 'Vertrag')
                               for a in jack_mitarbeiter.auffaelligkeiten(betreff, '')))
        except Exception:
            vorfilter = False
        if not vorfilter:
            continue
        try:
            geholt = jack_postfaecher.mail_lesen(root, postfach, uid)
        except Exception:
            continue
        if not geholt or not geholt.get('ok'):
            continue
        text = geholt.get('text', '')
        try:
            ist_kandidat = (jack_mitarbeiter.ist_bericht(betreff, text)
                            or any(a in ('Termin', 'Vertrag')
                                   for a in jack_mitarbeiter.auffaelligkeiten(betreff, text)))
        except Exception:
            ist_kandidat = False
        if not ist_kandidat:
            _r6_beanspruchen(root, postfach, uid, an)
            continue
        # Block 26, Teil 2, Nachbesserung (Opus-Endkontrolle): beanspruchen
        # VOR dem Modellaufruf, nicht erst danach - siehe _r6_beanspruchen().
        # War ein anderer, gleichzeitiger Lauf schneller, wird hier
        # uebersprungen, OHNE Modellkosten auszugeben.
        if not _r6_beanspruchen(root, postfach, uid, an):
            continue
        try:
            verlauf = jack_mitarbeiter.einsatz_verlauf(root, kennung)
            alte_datei = verlauf.get('aktuell')
            alter_pfad = (root / 'auftraege' / 'freigabe' / alte_datei) if alte_datei else None
            noch_offen = bool(alter_pfad and alter_pfad.exists())
            stamm = jack_mitarbeiter.stammdaten(root, kennung)
            name = stamm.get('rufname') or kennung
            frage = _r6_pruefung_frage(name, kennung, betreff, text, noch_offen)
            ergebnis = modell_router.draft(root, schluessel_fn, frage, role='fachkraft',
                                           art='fachentwurf', datenklasse='intern')
            daten = _r6_json_parsen(ergebnis.get('antwort', ''))
            vorlage = jack_mitarbeiter.einsatzkarte_vorlegen(
                root, kennung,
                {'kurzfassung': daten.get('kurzfassung', []),
                 'befunde': daten.get('befunde', []),
                 'stunden_genannt': daten.get('stunden_genannt', 0),
                 'verbesserungen': daten.get('verbesserungen', [])},
                daten.get('einsatzkarte', []), daten.get('optionen', []),
                daten.get('wochenplan', []), von='JACK',
                grund_aenderung='Neuer Standbericht eingegangen (%s)' % betreff)
            if noch_offen and alter_pfad and alter_pfad.exists():
                holding = root.parents[1]
                # Nachbesserung (Opus-Endkontrolle, 18.09.2026): R1-R9
                # (_ziel_ordner oben) legen "erledigt" als GESCHWISTER von
                # "freigabe" an (auftraege/erledigt/), nicht darunter - die
                # erste R6-Fassung benutzte faelschlich
                # auftraege/freigabe/erledigt/, ein zweiter, vom Rest des
                # Systems nie gesehener Ordner.
                ziel = root / 'auftraege' / 'erledigt'
                ziel.mkdir(parents=True, exist_ok=True)
                von_pfad = alter_pfad
                neuer_pfad = ziel / alter_pfad.name
                von_pfad.rename(neuer_pfad)
                with neuer_pfad.open('a', encoding='utf-8') as f:
                    f.write('\n\n## Regelentscheidung %s — R6: ueberholt durch neuen '
                           'Standbericht, siehe %s\n' % (an.isoformat(), vorlage.get('vorlage', '')))
                _append_jsonl(root / 'betrieb' / 'regelentscheidungen.jsonl',
                              {'zeit': an.isoformat(), 'karte': von_pfad.name, 'regel': 'R6',
                               'von': str(von_pfad.relative_to(holding)),
                               'nach': str(neuer_pfad.relative_to(holding)),
                               'grund': 'Ueberholt durch neue Fassung ' + str(vorlage.get('vorlage', '')),
                               'marker': 'r6_standbericht'})
            erzeugt.append(vorlage.get('vorlage'))
        except Exception as fehlergrund:
            try:
                _append_jsonl(root / 'betrieb' / 'regelentscheidungen_fehler.jsonl',
                              {'zeit': an.isoformat(), 'anzahl': 1,
                               'fehler': [{'karte': None,
                                          'fehler': ('R6 fuer %s (%s): %s'
                                                     % (kennung, betreff, fehlergrund))[:300]}]})
            except Exception:
                pass
    return erzeugt


def lauf(root, at=None):
    """Einhaengepunkt fuer jack_betrieb.tick: ein Aufruf, keine Rueckfrage.

    Reihenfolge bewusst: ZUERST R1-R9 (anwenden) - das ist der
    sicherheitskritische Teil (P7-geprueft). ERST DANACH, und je in einem
    eigenen try/except, T2.1 (Empfehlung) und T2.4 (R6) - ein Fehler dort
    darf R1-R9 nie beruehren und haelt auch den jeweils anderen der beiden
    nicht auf."""
    start = now()
    bewegt = anwenden(root, at)
    empfehlungen = []
    try:
        empfehlungen = empfehlungen_erzeugen(root, at)
    except Exception as fehlergrund:
        try:
            _append_jsonl(Path(root) / 'betrieb' / 'regelentscheidungen_fehler.jsonl',
                          {'zeit': (at or now()).isoformat(), 'anzahl': 1,
                           'fehler': [{'karte': None,
                                      'fehler': f"Empfehlungen abgebrochen: {fehlergrund}"[:300]}]})
        except Exception:
            pass
    r6 = []
    try:
        r6 = standberichte_pruefen(root, at)
    except Exception as fehlergrund:
        try:
            _append_jsonl(Path(root) / 'betrieb' / 'regelentscheidungen_fehler.jsonl',
                          {'zeit': (at or now()).isoformat(), 'anzahl': 1,
                           'fehler': [{'karte': None,
                                      'fehler': f"R6 abgebrochen: {fehlergrund}"[:300]}]})
        except Exception:
            pass
    return {'start': start.isoformat(), 'ende': now().isoformat(),
            'bewegt': len(bewegt), 'karten': [b['karte'] for b in bewegt],
            'empfehlungen': empfehlungen, 'r6': r6}


def tick(root, at=None):
    """Aufrufkonvention wie die anderen Bausteine in jack_betrieb.tick:
    Rueckgabe ist eine Liste veraenderter/erzeugter Pfade, nie eine
    Ausnahme (Nachbesserung nach Opus-Pruefung P7, Punkt 6: jack_betrieb.tick
    faengt Bausteinfehler zwar selbst per try/except ab, aber dieses Modul
    soll die eigene Zusage einhalten, nicht nur sich auf den Aufrufer
    verlassen)."""
    try:
        ergebnis = lauf(root, at)
        return list(ergebnis.get('karten', []))
    except Exception as fehlergrund:
        # Nachbesserung nach der dritten Opus-Pruefung P7, Punkt 6: ein
        # Abbruch hier darf nicht spurlos verschwinden, auch wenn tick() nach
        # aussen leer zurueckgibt.
        try:
            _append_jsonl(Path(root) / 'betrieb' / 'regelentscheidungen_fehler.jsonl',
                          {'zeit': (at or now()).isoformat(), 'anzahl': 1,
                           'fehler': [{'karte': None, 'fehler': f"tick() abgebrochen: {fehlergrund}"[:300]}]})
        except Exception:
            pass
        return []
