"""Verbindungsueberwachung (Block 17, Auftrag 2.2 der Videoauswertung).

Ziel des Patrons: Ist eine angebundene Quelle getrennt, sagt JACK das offen -
statt aus altem Wissen zu antworten oder zu raten.

Grundsaetze dieses Moduls:

* **Kein Modellaufruf.** Keine Pruefung hier kostet einen Cent.
* **Nur lesen.** Keine Pruefung sendet etwas, aendert etwas oder ruft Inhalte
  ab. Beim Postfach wird ausschliesslich die Anmeldung geprueft (LOGIN und
  sofort LOGOUT) - kein Abruf, keine Mail, kein Ordner.
* **Keine Zugangsdaten im Protokoll.** Jeder Text laeuft durch `betrieb.redact`.
* **Teure Pruefungen hoechstens alle 15 Minuten.** Teuer heisst hier: sie gehen
  ueber das Netz. Billige Pruefungen (Datei da, Dienst da) laufen im normalen
  60-Sekunden-Takt der Betriebspruefung mit.
* **Kein Sperren fremder Konten.** Ein Postfachserver wird nur dann angemeldet,
  wenn fuer mindestens ein Postfach dieses Servers ein Passwort im Tresor liegt
  UND der letzte Stand "verbunden" war. Steht ein Postfach auf Fehler, wird
  dieser Stand gemeldet, aber NICHT erneut angemeldet - wiederholte
  Fehlanmeldungen sperren sonst das Konto.

Status je Quelle: ``ok`` / ``warnung`` / ``fehler`` - dazu der Zeitpunkt der
letzten erfolgreichen Verbindung. Ein Wechsel ``ok -> fehler`` erzeugt GENAU
EINE Meldung (nicht bei jeder Pruefung), abgelegt in
``betrieb/verbindungen_meldungen.jsonl``.
"""
import datetime as dt
import json
import os
import socket
import ssl
import time
from pathlib import Path

import jack_betrieb as b

STAND = 'verbindungen.json'
VERLAUF = 'verbindungen.jsonl'
MELDUNGEN = 'verbindungen_meldungen.jsonl'

# Netzpruefungen hoechstens alle 15 Minuten (Vorgabe Auftrag 2.2, Aufgabe 1).
TEUER_ABSTAND_S = 15 * 60
WARTEZEIT_S = 10


def _jetzt():
    return b.now()


def _lesen(pfad, ersatz):
    try:
        if pfad.is_symlink():
            return ersatz
        return json.loads(pfad.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return ersatz


def _schreiben(pfad, wert):
    if pfad.is_symlink():
        raise ValueError('Verweis statt Betriebsdatei')
    temp = pfad.with_name(pfad.name + '.' + str(os.getpid()) + '.tmp')
    with temp.open('w', encoding='utf-8') as datei:
        json.dump(wert, datei, ensure_ascii=False, indent=2)
        datei.flush()
        os.fsync(datei.fileno())
    os.replace(temp, pfad)


def _kurz(text, laenge=200):
    """Jeder Text, der in eine Datei geht, laeuft vorher durch redact."""
    return b.redact(str(text))[:laenge]


# ------------------------------------------------------------ Einzelpruefungen
# Jede Pruefung gibt (status, detail) zurueck und wirft nie.

def _pruefe_postfachserver(root, anbieter):
    """NUR Anmeldung, kein Abruf. IMAP LOGIN, danach sofort LOGOUT."""
    import imaplib
    import jack_postfaecher as post
    try:
        daten = post.konfiguration(root)
    except ValueError as fehler:
        return 'fehler', _kurz(fehler)
    server = (daten.get('server') or {}).get(anbieter)
    if not server:
        return 'fehler', 'Kein Server fuer "%s" in postfaecher.json' % anbieter
    eigene = [p for p in daten['postfaecher'] if p.get('anbieter') == anbieter]
    if not eigene:
        return 'warnung', 'Kein Postfach fuer diesen Server eingetragen'
    # Nur ein Postfach anmelden - der Server ist fuer alle derselbe.
    kandidaten = [p for p in eigene if p.get('status') == 'verbunden'
                  and post.tresor_vorhanden(p['passwort_schluessel'])]
    if not kandidaten:
        fehlerhafte = [p for p in eigene if p.get('status') not in (None, 'verbunden')]
        if fehlerhafte:
            return 'fehler', ('%d von %d Postfach/Postfaechern steht auf "%s" - '
                              'keine erneute Anmeldung, damit das Konto nicht gesperrt wird'
                              % (len(fehlerhafte), len(eigene),
                                 _kurz(fehlerhafte[0].get('status'), 40)))
        return 'warnung', 'Kein Passwort im Tresor; Anmeldung nicht pruefbar'
    postfach = kandidaten[0]
    geheim = post.tresor_lesen(postfach['passwort_schluessel'])
    if not geheim:
        return 'warnung', 'Passwort im Tresor nicht lesbar; Anmeldung nicht geprueft'
    verbindung = None
    try:
        verbindung = imaplib.IMAP4_SSL(server['imap'], int(server['imap_port']),
                                       ssl_context=ssl.create_default_context(),
                                       timeout=WARTEZEIT_S)
        verbindung.login(postfach['adresse'], geheim)
        # Kein SELECT, kein SEARCH, kein FETCH: nur die Anmeldung zaehlt.
        #
        # Nachtrag des Patrons vom 17.09.2026: Der Server kann antworten und
        # trotzdem kann EIN Postfach dieses Servers klemmen. Genau das war am
        # 17.09. um 08:15 bei office@gottwald.world der Fall - die Gruppe stand
        # auf "ok", das Postfach auf "fehler", und der Streifen sagte nichts.
        # Ein einzelnes kaputtes Postfach faellt jetzt als "warnung" auf.
        kaputt = [p for p in eigene if p.get('status') not in (None, 'verbunden')]
        if kaputt:
            namen = ', '.join(p['adresse'] for p in kaputt[:3])
            if len(kaputt) > 3:
                namen += ' und %d weitere' % (len(kaputt) - 3)
            return 'warnung', _kurz(
                'Server antwortet, aber %d von %d Postfach/Postfaechern steht auf '
                '"%s": %s' % (len(kaputt), len(eigene),
                              str(kaputt[0].get('status')), namen), 240)
        return 'ok', ('Anmeldung bestaetigt fuer %d Postfach/Postfaecher an %s'
                      % (len(eigene), server['imap']))
    except Exception as fehler:
        return 'fehler', _kurz('Anmeldung nicht moeglich: ' + str(fehler))
    finally:
        try:
            if verbindung is not None:
                verbindung.logout()
        except Exception:
            pass


def _pruefe_kalender(root):
    """Kopfabfrage beim iCloud-Kalender. Aendert nichts und schreibt keinen Stand."""
    import jack_kalender as kal
    try:
        kal._zugang(root)
    except ValueError as fehler:
        return 'warnung', _kurz(fehler)
    rumpf = ('<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
             '<d:prop><c:calendar-home-set/></d:prop></d:propfind>')
    try:
        status, _ = kal._anfrage(root, 'PROPFIND', '/', rumpf,
                                 {'Depth': '0', 'Content-Type': 'application/xml'})
    except Exception as fehler:
        return 'fehler', _kurz('Server nicht erreichbar: ' + str(fehler))
    if status in (200, 207):
        return 'ok', 'Anmeldung bestaetigt bei ' + kal.SERVER
    return 'fehler', _kurz(kal._klartext(status))


def _pruefe_websuche(root):
    """Ohne Suchlauf: laufe ich sonst in die Tagesgrenze von zehn Suchen.

    Geprueft wird deshalb der Weg selbst: Konfiguration aktiv, unveraenderter
    Suchlaeufer, vorhandenes lokales SearXNG.
    """
    try:
        import jack_websuche as such
        from jack_erweiterungen import path, read_json
    except Exception as fehler:
        return 'fehler', _kurz(fehler)
    cfg = read_json(path(root, 'betrieb/websuche_konfiguration.json'), {}) or {}
    if cfg.get('aktiv') is not True or cfg.get('version') != such.VERSION:
        return 'fehler', 'Websuche ist nicht in der geprueften Fassung aktiv'
    laeufer = path(root, 'jack_websuche_runner.py')
    try:
        if such.digest(laeufer.read_bytes()) != cfg.get('runner_sha256'):
            return 'fehler', 'Der Suchweg wurde veraendert; neue Pruefung noetig'
    except OSError as fehler:
        return 'fehler', _kurz(fehler)
    python = such.RUNTIME / 'python/bin/python'
    if not python.is_file():
        return 'fehler', 'Lokales SearXNG fehlt auf diesem Mac'
    return 'ok', 'Lokales SearXNG vorhanden, Suchweg unveraendert'


def _pruefe_webabruf(root):
    """Ist ueberhaupt ein oeffentliches Netz da? Nur Namensaufloesung, kein Abruf.

    Ein echter Seitenabruf wuerde die Tagesgrenze von 30 Abrufen verbrauchen.
    Die Namensaufloesung beweist die Netzverbindung, sendet aber keinen Inhalt.
    """
    try:
        infos = socket.getaddrinfo('one.one.one.one', 443, proto=socket.IPPROTO_TCP)
    except OSError as fehler:
        return 'fehler', _kurz('Keine Namensaufloesung: ' + str(fehler))
    if not infos:
        return 'fehler', 'Keine Namensaufloesung im oeffentlichen Netz'
    return 'ok', 'Oeffentliches Netz erreichbar (Namensaufloesung)'


def _pruefe_obsidian(root):
    try:
        import jack_obsidian
        lage = jack_obsidian.status()
    except Exception as fehler:
        return 'fehler', _kurz(fehler)
    if lage.get('live'):
        return 'ok', 'Graph liefert aktuelle Bilder aus "%s"' % lage.get('vault', '')
    return 'warnung', _kurz(lage.get('fehler') or 'Obsidian liefert kein aktuelles Bild.')


def _pruefe_codex(root):
    try:
        import codex_bruecke
    except Exception as fehler:
        return 'fehler', _kurz(fehler)
    if codex_bruecke.CODEX.is_file():
        return 'ok', 'Codex vorhanden: ' + str(codex_bruecke.CODEX)
    return 'warnung', 'Codex ist auf diesem Mac nicht installiert'


def _pruefe_tailscale(root):
    import subprocess
    zugang = _lesen(b.area(root) / 'zugang.json', {}) or {}
    name = str(zugang.get('handy_name') or '').strip()
    if not name:
        return 'warnung', 'Kein Handy-Name hinterlegt'
    pfad = '/Applications/Tailscale.app/Contents/MacOS/Tailscale'
    if not os.path.isfile(pfad):
        return 'fehler', 'Tailscale ist auf diesem Mac nicht installiert'
    try:
        verbunden = subprocess.run([pfad, 'status'], capture_output=True,
                                   text=True, timeout=8)
        weiter = subprocess.run([pfad, 'serve', 'status'], capture_output=True,
                                text=True, timeout=8)
    except Exception as fehler:
        return 'fehler', _kurz(fehler)
    an = verbunden.returncode == 0 and bool(verbunden.stdout.strip())
    serve = '8778' in weiter.stdout and 'https://' in weiter.stdout
    if an and serve:
        return 'ok', 'Erreichbar unter https://' + name
    if an:
        return 'warnung', 'Verbunden, aber die Weiterleitung auf 8778 fehlt'
    return 'fehler', 'Tailscale ist nicht verbunden'


# --------------------------------------------------------------- Verzeichnis
# teuer = geht ueber das Netz -> hoechstens alle 15 Minuten.
VERZEICHNIS = [
    {'schluessel': 'postfach_united-domains', 'name': 'Postfächer united-domains',
     'gruppe': 'Postfach', 'teuer': True,
     'pruefung': lambda root: _pruefe_postfachserver(root, 'united-domains')},
    {'schluessel': 'postfach_google', 'name': 'Postfach Google',
     'gruppe': 'Postfach', 'teuer': True,
     'pruefung': lambda root: _pruefe_postfachserver(root, 'google')},
    {'schluessel': 'postfach_apple', 'name': 'Postfach Apple',
     'gruppe': 'Postfach', 'teuer': True,
     'pruefung': lambda root: _pruefe_postfachserver(root, 'apple')},
    {'schluessel': 'kalender', 'name': 'Kalender (iCloud)',
     'gruppe': 'Kalender', 'teuer': True, 'pruefung': _pruefe_kalender},
    {'schluessel': 'websuche', 'name': 'Websuche (lokales SearXNG)',
     'gruppe': 'Web', 'teuer': False, 'pruefung': _pruefe_websuche},
    {'schluessel': 'webabruf', 'name': 'Seitenabruf (öffentliches Netz)',
     'gruppe': 'Web', 'teuer': True, 'pruefung': _pruefe_webabruf},
    {'schluessel': 'obsidian', 'name': 'Obsidian-Graph',
     'gruppe': 'Wissen', 'teuer': False, 'pruefung': _pruefe_obsidian},
    {'schluessel': 'codex', 'name': 'Codex-Brücke',
     'gruppe': 'Prüfung', 'teuer': False, 'pruefung': _pruefe_codex},
    {'schluessel': 'tailscale', 'name': 'Handy-Zugang (Tailscale)',
     'gruppe': 'Zugang', 'teuer': False, 'pruefung': _pruefe_tailscale},
]

# Welche Quelle braucht JACK fuer welche Art von Frage? Wird fuer den offenen
# Hinweis in der Antwort gebraucht (Auftrag 2.2, Aufgabe 3).
BRAUCHT = {
    'postfach_united-domains': ('mail', 'postfach', 'posteingang', 'e-mail', 'nachricht'),
    'postfach_google': ('mail', 'postfach', 'gmail', 'e-mail'),
    'postfach_apple': ('mail', 'postfach', 'icloud', 'e-mail'),
    'kalender': ('termin', 'kalender', 'besprechung', 'uhrzeit'),
    'websuche': ('such', 'recherche', 'aktuell', 'preis', 'kurs'),
    'webabruf': ('seite', 'internet', 'quelle', 'aktuell', 'preis', 'kurs'),
    'obsidian': ('graph', 'obsidian', 'wissen'),
    'codex': ('codex', 'gegenpruefung'),
    'tailscale': ('handy', 'unterwegs', 'tailscale'),
}


def _leer(eintrag, jetzt):
    return {'schluessel': eintrag['schluessel'], 'name': eintrag['name'],
            'gruppe': eintrag['gruppe'], 'teuer': eintrag['teuer'],
            'status': 'wartet', 'detail': 'Noch nicht geprüft',
            'letzter_erfolg': None, 'geprueft': None, 'seit': jetzt.isoformat()}


def pruefen(root, zwang=False, at=None):
    """Prüft alle Anbindungen und schreibt den Stand. Gibt den Stand zurück.

    `zwang=True` prüft auch die teuren Wege, egal wie kurz der letzte Lauf her
    ist - fuer den Knopf und fuer Tests. Der Wache-Takt ruft ohne Zwang auf.
    """
    root = Path(root)
    jetzt = at or _jetzt()
    bereich = b.area(root)
    alt = _lesen(bereich / STAND, {}) or {}
    alte = {q['schluessel']: q for q in alt.get('quellen', []) if isinstance(q, dict)}

    quellen, wechsel, meldungen = [], [], []
    for eintrag in VERZEICHNIS:
        vorher = alte.get(eintrag['schluessel']) or _leer(eintrag, jetzt)
        neu = dict(vorher)
        neu.update({'name': eintrag['name'], 'gruppe': eintrag['gruppe'],
                    'teuer': eintrag['teuer']})
        faellig = True
        if eintrag['teuer'] and not zwang and vorher.get('geprueft'):
            try:
                alter = (jetzt - dt.datetime.fromisoformat(vorher['geprueft'])).total_seconds()
                faellig = alter >= TEUER_ABSTAND_S or alter < 0
            except (ValueError, TypeError):
                faellig = True
        if not faellig:
            neu['uebersprungen'] = 'Teure Prüfung frühestens alle 15 Minuten'
            quellen.append(neu)
            continue
        neu.pop('uebersprungen', None)
        beginn = time.monotonic()
        try:
            status, detail = eintrag['pruefung'](root)
        except Exception as fehler:          # eine Quelle darf die Wache nie stoppen
            status, detail = 'fehler', _kurz(fehler)
        if status not in ('ok', 'warnung', 'fehler'):
            status, detail = 'fehler', 'Unklares Prüfergebnis'
        neu['status'] = status
        neu['detail'] = _kurz(detail)
        neu['geprueft'] = jetzt.isoformat()
        neu['ms'] = round((time.monotonic() - beginn) * 1000)
        if status == 'ok':
            neu['letzter_erfolg'] = jetzt.isoformat()
        vorstatus = vorher.get('status')
        if vorstatus != status:
            neu['seit'] = jetzt.isoformat()
            wechsel.append({'quelle': eintrag['schluessel'], 'name': eintrag['name'],
                            'vorher': vorstatus, 'nachher': status,
                            'detail': neu['detail']})
            # Genau EINE Meldung je Wechsel nach fehler - nicht je Prüfung.
            if status == 'fehler' and vorstatus in ('ok', 'warnung'):
                meldungen.append({'zeit': jetzt.isoformat(), 'quelle': eintrag['schluessel'],
                                  'name': eintrag['name'], 'vorher': vorstatus,
                                  'nachher': 'fehler', 'detail': neu['detail'],
                                  'letzter_erfolg': neu.get('letzter_erfolg'),
                                  'gelesen': False})
        quellen.append(neu)

    ok = sum(1 for q in quellen if q['status'] == 'ok')
    schwer = sum(1 for q in quellen if q['status'] == 'fehler')
    leicht = sum(1 for q in quellen if q['status'] == 'warnung')
    stand = {'zeit': jetzt.isoformat(), 'anzahl': len(quellen), 'ok': ok,
             'fehler': schwer, 'warnung': leicht,
             'status': 'fehler' if schwer else 'warnung' if leicht else 'ok',
             'kurz': '%d von %d ok' % (ok, len(quellen)),
             'quellen': quellen,
             'quelle': 'betrieb/' + STAND + ' — geprüft ohne Modellaufruf'}
    _schreiben(bereich / STAND, stand)
    for zeile in wechsel:
        b.append(bereich / VERLAUF, {'zeit': jetzt.isoformat(), **zeile})
    for zeile in meldungen:
        b.append(bereich / MELDUNGEN, zeile)
    return stand


def stand(root):
    """Liest den letzten Stand, ohne zu prüfen. Nie geraten."""
    daten = _lesen(b.area(Path(root)) / STAND, None)
    if not isinstance(daten, dict) or not isinstance(daten.get('quellen'), list):
        return {'zeit': None, 'anzahl': 0, 'ok': 0, 'fehler': 0, 'warnung': 0,
                'status': 'wartet', 'kurz': 'noch nicht geprüft', 'quellen': [],
                'quelle': 'betrieb/' + STAND + ' — noch nicht angelegt'}
    return daten


def stoerungen(root):
    """Alle Quellen, deren Status nicht ok ist."""
    return [q for q in stand(root).get('quellen', []) if q.get('status') != 'ok']


def offene_meldungen(root, hoechstens=20):
    """Die Wechsel nach fehler, je Wechsel genau einer."""
    try:
        return b.records(b.area(Path(root)) / MELDUNGEN, limit=hoechstens)
    except (OSError, ValueError):
        return []


def hinweis_fuer_antwort(root, frage=''):
    """Ein Satz fuer JACKs Gedaechtnis: welche Quelle ist gerade nicht erreichbar.

    Auftrag 2.2, Aufgabe 3: Stuetzt sich eine Antwort auf eine Quelle mit
    Status ungleich ok, wird das offen genannt - oder die Antwort unterbleibt.
    """
    kaputt = stoerungen(root)
    if not kaputt:
        return ''
    text = (frage or '').lower()
    zeilen = []
    for quelle in kaputt:
        woerter = BRAUCHT.get(quelle.get('schluessel'), ())
        betroffen = any(w in text for w in woerter) if text else False
        seit = quelle.get('letzter_erfolg') or 'kein Erfolg seit Beobachtungsbeginn'
        zeilen.append('%s: %s — %s (letzte erfolgreiche Verbindung: %s)%s'
                      % (quelle.get('name'), quelle.get('status'),
                         quelle.get('detail'), seit,
                         '  <-- betrifft diese Frage' if betroffen else ''))
    return ('# Getrennte oder gestörte Quellen (Stand der Verbindungsüberwachung)\n'
            'Diese Quellen sind gerade NICHT in Ordnung. Stützt sich deine Antwort auf '
            'eine davon, nenne die Trennung offen im Antworttext (Beispiel: '
            '"Kalender seit 14:05 nicht erreichbar — Angabe ungeprüft") oder antworte '
            'nicht. Nie aus altem Wissen so tun, als wäre die Quelle aktuell.\n'
            + '\n'.join(zeilen))
