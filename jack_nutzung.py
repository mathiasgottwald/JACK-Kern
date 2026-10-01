"""Funktions-Disziplin (Block 19, Auftrag 2.4 der Videoauswertung).

Ziel des Patrons: JACK waechst nur um Funktionen und Agenten, die wirklich
genutzt werden.

Grundsaetze dieses Moduls:

* **Keine Zahl ohne Quelle.** Jede Faehigkeit und jeder Agent nennt die Datei,
  aus der die Zahl stammt. Was sich aus den Dateien nicht ableiten laesst, heisst
  "unbekannt" und wird nie geschaetzt.
* **Nichts wird abgeschaltet.** Der Monatsbericht ist ein **Vorschlag**
  ("archivieren?"). Entschieden wird im Freigaben-Kasten, vom Patron.
* **Kein Modellaufruf.** Reine Dateiarbeit.
* **Kein zweiter Zeitgeber.** Der Monatsbericht haengt in der Tagesroutine.

Gezaehlt wird aus drei vorhandenen Protokollen plus dem eigenen:

  betrieb/nutzung.jsonl        seit Block 19: jeder Werkzeugaufruf
  betrieb/werkzeugeinsatz.jsonl  Nachschlagen, Websuche, Seitenabruf (ab Block 10)
  betrieb/kostenlaeufe.jsonl     Fachentwurf, Rat, Codex, Messtest, Arbeiterlauf
  arbeiter_zugriffe.jsonl        Agentenstarts je Rolle
"""
import datetime as dt
import json
from pathlib import Path

import jack_betrieb as b

PROTOKOLL = 'nutzung.jsonl'
FENSTER_TAGE = 30
# Ab so vielen Tagen ohne Einsatz schlaegt der Monatsbericht "archivieren?" vor.
RUHE_TAGE = 30


# ------------------------------------------------------------ Verzeichnisse
# Die Namen muessen zu server.WERKZEUGE passen. Der Test in
# abnahme/Sichtpruefung_Block19_2026-09-17/ prueft das bei jedem Lauf.
FAEHIGKEITEN = [
    ('patron_profil', 'Persönliche Merksätze'),
    ('faehigkeiten_pruefen', 'Arbeitswege und Blockaden prüfen'),
    ('videoauftrag_vorbereiten', 'Videoauftrag lokal vorbereiten'),
    ('videoverfahren_waehlen', 'Passenden Videoweg waehlen'),
    ('videoproduktion_stand', 'Videoproduktion lesen'),
    ('videoerzeugung_bereitschaft', 'Videoerzeugung prüfen'),
    ('higgsfield_bereitschaft', 'Higgsfield-Videoerzeugung prüfen'),
    ('higgsfield_video_starten', 'Higgsfield-Video intern erzeugen'),
    ('higgsfield_video_aktualisieren', 'Higgsfield-Video abschließen'),
    ('videoerzeugung_starten', 'Video intern erzeugen'),
    ('videoerzeugung_aktualisieren', 'Videoerzeugung abschließen'),
    ('medien_pruefen', 'Lokales Video technisch prüfen'),
    ('entscheidung_speichern', 'Entscheidung ablegen'),
    ('stand_aktualisieren', 'ACTIVE_CONTEXT aktualisieren'),
    ('auftrag_erteilen', 'Auftrag anlegen'),
    ('nachschlagen',    'Nachschlagen in der Ablage'),
    ('freigeben',       'Freigabe umsetzen'),
    ('kostenuebersicht', 'Kostenübersicht'),
    ('betriebspruefung', 'Betriebsprüfung lesen'),
    ('verbesserungen',  'Verbesserungsvorschläge lesen'),
    ('fachentwurf',     'Fachentwurf erstellen'),
    ('rat_befragen',    'Rat mehrerer Modelle'),
    ('codex_pruefung',  'Codex-Gegenprüfung'),
    ('tagesbericht',    'Morgenbriefing / Abendabschluss'),
    # F-4 (24.09.2026): server.py fuehrt seit 21.09. (Sprachmodul-Neuentwurf)
    # statt "mail_entwurf" das Werkzeug "mail_antwort_entwerfen". Der alte Name
    # stand hier weiter; der Katalogtest war seitdem rot. Alte Zeilen
    # "mail_entwurf" bleiben in nutzung.jsonl stehen, zaehlen aber nicht fuer das
    # neue Werkzeug (anderer Weg: Antwort an eine gefundene Mail).
    ('mail_antwort_entwerfen', 'E-Mail-Antwort entwerfen'),
    ('kalender_entwurf', 'Terminentwurf'),
    ('websuche',        'Websuche'),
    ('webseite_lesen',  'Öffentliche Seite lesen'),
    ('aussen_oeffnen', 'Browser oder Anwendung öffnen'),
    ('deckel_freigeben', 'Tagesdeckel auf Patron-Befehl anheben'),
    ('mail_oeffnen', 'Nachricht öffnen'),
    ('mail_suchen', 'Nachrichten suchen'),
    ('oberflaeche_steuern', 'Oberfläche steuern'),
    ('suche_ablage', 'Ablage durchsuchen'),
]

# Wie eine alte Protokollzeile auf eine Faehigkeit zeigt.
ALTLASTEN = {
    'werkzeugeinsatz.jsonl': {
        'nachschlagen': 'nachschlagen',
        'nachschlagen_uebersprungen': 'nachschlagen',
        'websuche': 'websuche',
        'webseite_lesen': 'webseite_lesen',
    },
    'kostenlaeufe.jsonl': {
        'fachentwurf': 'fachentwurf',
        'rat': 'rat_befragen',
        'codex': 'codex_pruefung',
    },
}


def merken(root, name, **felder):
    """Ein Werkzeugeinsatz. Wird von server.werkzeug_ausfuehren gerufen."""
    try:
        satz = {'zeit': b.now().isoformat(), 'art': 'faehigkeit', 'name': str(name)[:60]}
        satz.update({k: str(v)[:200] for k, v in felder.items()})
        b.append(b.area(Path(root)) / PROTOKOLL, satz)
    except Exception:
        pass


def _zeiten_aus(pfad, treffer):
    """Alle Zeitpunkte je Name aus einer jsonl-Datei. Wirft nie."""
    raus = {}
    try:
        if not pfad.is_file() or pfad.is_symlink():
            return raus
        with pfad.open(encoding='utf-8', errors='replace') as strom:
            for zeile in strom:
                if not zeile.strip():
                    continue
                try:
                    satz = json.loads(zeile)
                except ValueError:
                    continue
                name = treffer(satz)
                if not name:
                    continue
                zeit = str(satz.get('zeit') or '')
                if zeit:
                    raus.setdefault(name, []).append(zeit)
    except OSError:
        pass
    return raus


def _mischen(ziel, teil):
    for name, zeiten in teil.items():
        ziel.setdefault(name, []).extend(zeiten)


def _auswerten(zeiten, jetzt):
    """Letzter Einsatz, Zahl der letzten 30 Tage, Tage seit dem letzten Mal."""
    if not zeiten:
        return {'einsaetze_gesamt': 0, 'einsaetze_30_tage': 0,
                'letzter_einsatz': None, 'tage_her': None, 'ruht': True}
    grenze = (jetzt - dt.timedelta(days=FENSTER_TAGE)).isoformat()
    letzte = max(zeiten)
    tage = None
    try:
        tage = (jetzt - dt.datetime.fromisoformat(letzte)).days
    except (ValueError, TypeError):
        pass
    return {'einsaetze_gesamt': len(zeiten),
            'einsaetze_30_tage': sum(1 for z in zeiten if z >= grenze),
            'letzter_einsatz': letzte, 'tage_her': tage,
            'ruht': tage is not None and tage >= RUHE_TAGE}


def lage(root, at=None):
    """Nutzungszähler je Fähigkeit und je Agent. Liest nur."""
    root = Path(root)
    jetzt = at or b.now()
    bereich = b.area(root)

    eigen = _zeiten_aus(bereich / PROTOKOLL,
                        lambda s: s.get('name') if s.get('art') == 'faehigkeit' else None)
    zeiten = {}
    _mischen(zeiten, eigen)
    for datei, abbildung in ALTLASTEN.items():
        _mischen(zeiten, _zeiten_aus(
            bereich / datei,
            lambda s, a=abbildung: (a.get(s.get('art'))
                                    if s.get('ereignis') in (None, 'ende') else None)))

    faehigkeiten = []
    for name, titel in FAEHIGKEITEN:
        faehigkeiten.append({'name': name, 'titel': titel, 'art': 'Fähigkeit',
                             **_auswerten(zeiten.get(name, []), jetzt),
                             'quelle': 'betrieb/%s + %s' % (PROTOKOLL,
                                                            ', '.join(ALTLASTEN))})

    # Agenten: ein Start ist eine Zeile "tool: Agent" mit entscheidung "allow".
    agentenzeiten = _zeiten_aus(
        root / 'arbeiter_zugriffe.jsonl',
        lambda s: s.get('agent_typ') if (s.get('tool') == 'Agent'
                                         and s.get('entscheidung') == 'allow') else None)
    try:
        rollen = json.loads((root / 'arbeiter_agenten.json').read_text(encoding='utf-8'))
        rollen = rollen if isinstance(rollen, dict) else {}
    except (OSError, ValueError):
        rollen = {}
    agenten = []
    for name in sorted(set(rollen) | set(agentenzeiten)):
        beschreibung = (rollen.get(name) or {}).get('description', '')
        agenten.append({'name': name, 'titel': name,
                        'art': 'Agent' if name in rollen else 'Agent (nicht konfiguriert)',
                        'beschreibung': str(beschreibung)[:160],
                        **_auswerten(agentenzeiten.get(name, []), jetzt),
                        'quelle': 'arbeiter_zugriffe.jsonl + arbeiter_agenten.json'})

    ruhend = [e for e in faehigkeiten + agenten if e['ruht']]
    return {'zeit': jetzt.isoformat(),
            'faehigkeiten': faehigkeiten, 'agenten': agenten,
            'anzahl_faehigkeiten': len(faehigkeiten), 'anzahl_agenten': len(agenten),
            'ruhend': len(ruhend), 'fenster_tage': FENSTER_TAGE,
            'kurz': '%d von %d ruhen seit %d Tagen'
                    % (len(ruhend), len(faehigkeiten) + len(agenten), RUHE_TAGE),
            'quelle': ('betrieb/%s, betrieb/werkzeugeinsatz.jsonl, '
                       'betrieb/kostenlaeufe.jsonl, arbeiter_zugriffe.jsonl'
                       % PROTOKOLL)}


# ------------------------------------------------------ Monatsbericht (Vorschlag)
def monatsbericht(root, at=None):
    """Entscheidungsvorlage 'archivieren?'. Schaltet NICHTS ab."""
    root = Path(root)
    at = at or b.now()
    stand = lage(root, at)
    ordner = root / 'auftraege' / 'freigabe'
    ordner.mkdir(parents=True, exist_ok=True)
    datei = ordner / (at.strftime('%Y-%m-%d') + '_FUNKTIONEN_Monatsbericht_archivieren.md')
    ruhend = [e for e in stand['faehigkeiten'] + stand['agenten'] if e['ruht']]

    import jack_freigaben
    v2 = jack_freigaben.v2_kopfzeilen({
        'projekt': 'JACK Steuerung', 'marke': 'JACK', 'eingegangen': at.strftime('%Y-%m-%d %H:%M'),
        'von': 'JACK (Block 19, Funktions-Disziplin)', 'an': 'Patron', 'art': 'entscheidung',
        'betreff': 'Funktionen ohne Einsatz seit %d Tagen — %d zur Kenntnis' % (RUHE_TAGE, len(ruhend)),
        'kern': '%d Funktionen hatten seit %d Tagen keinen Einsatz. Es wird nichts abgeschaltet oder archiviert; jede Abschaltung braucht einen eigenen Auftrag.'
                % (len(ruhend), RUHE_TAGE),
        'frage': 'Bericht gesehen?',
        'empfehlung': 'Zur Kenntnis nehmen (FREIGEBEN), weil dadurch nichts abgeschaltet wird; einzelne Abschaltungen kommen nur auf deinen eigenen Auftrag.',
        'frist': 'keine', 'dringlichkeit': 'niedrig',
        'ablauf': 'FREIGEBEN vermerkt nur, dass du den Bericht gesehen hast. Nichts wird abgeschaltet oder archiviert.'})
    zeilen = ['---'] + v2 + [
              'auftrag:    Funktions-Disziplin — %d Funktionen ohne Einsatz seit %d Tagen'
              % (len(ruhend), RUHE_TAGE),
              'erteilt:    ' + at.strftime('%Y-%m-%d %H:%M'),
              'status:     freigabe',
              'freigabe:   nein',
              'gefahr:     keine',
              'tiefe:      klein',
              'bereiche:   steuerung',
              'vorgang:    funktionen_monatsbericht',
              'optionen:   A',
              'option_a_titel: Bericht gesehen',
              'option_a_dann:  Nur vermerkt; nichts wird abgeschaltet oder archiviert.',
              '---',
              '',
              '## Worum es geht',
              '',
              'Lehre 2 aus der Videoauswertung: JACK soll nur um das wachsen, was',
              'wirklich benutzt wird. Dieser Bericht zeigt, was seit %d Tagen keinen'
              % RUHE_TAGE,
              'Einsatz hatte — als **Frage**, nicht als Maßnahme.',
              '',
              '**Es wird nichts abgeschaltet und nichts archiviert.** FREIGEBEN',
              'vermerkt nur, dass du den Bericht gesehen hast. Jede einzelne',
              'Abschaltung braucht einen eigenen Auftrag.',
              '',
              '## Ohne Einsatz seit %d Tagen — archivieren?' % RUHE_TAGE,
              '']
    if ruhend:
        zeilen += ['| Was | Art | Letzter Einsatz | 30 Tage | Quelle |', '|---|---|---|---|---|']
        for e in ruhend:
            zeilen.append('| %s | %s | %s | %d | %s |'
                          % (e['titel'], e['art'],
                             (str(e['letzter_einsatz'])[:19] if e['letzter_einsatz']
                              else 'nie benutzt'),
                             e['einsaetze_30_tage'], e['quelle']))
    else:
        zeilen.append('Nichts. Alles war in den letzten %d Tagen im Einsatz.' % RUHE_TAGE)

    genutzt = [e for e in stand['faehigkeiten'] + stand['agenten'] if not e['ruht']]
    zeilen += ['', '## Im Einsatz — bleibt unangetastet', '']
    if genutzt:
        zeilen += ['| Was | Art | Letzter Einsatz | 30 Tage |', '|---|---|---|---|']
        for e in genutzt:
            zeilen.append('| %s | %s | %s | %d |'
                          % (e['titel'], e['art'], str(e['letzter_einsatz'])[:19],
                             e['einsaetze_30_tage']))
    else:
        zeilen.append('Nichts — in den letzten %d Tagen wurde nichts benutzt.' % RUHE_TAGE)

    zeilen += ['',
               '## Ehrlich dazu',
               '',
               '* Gezählt wird erst, seit es gezählt wird. Ältere Einsätze stehen nur',
               '  dort, wo ein Protokoll sie ohnehin schon festhielt (Nachschlagen,',
               '  Websuche, Seitenabruf, Fachentwurf, Rat, Codex, Agentenstarts).',
               '* "nie benutzt" heißt: in keinem dieser Protokolle. Es heißt nicht,',
               '  dass die Funktion kaputt ist.',
               '',
               '## Quellen',
               '',
               '`' + stand['quelle'] + '`',
               '']
    datei.write_text('\n'.join(zeilen) + '\n', encoding='utf-8')
    return {'zeit': at.isoformat(), 'datei': str(datei), 'ruhend': len(ruhend),
            'gesamt': len(stand['faehigkeiten']) + len(stand['agenten']),
            'meldung': '%d von %d Funktionen ruhen seit %d Tagen. Der Bericht liegt '
                       'als Entscheidung im Freigaben-Kasten: %s'
                       % (len(ruhend), len(stand['faehigkeiten']) + len(stand['agenten']),
                          RUHE_TAGE, datei.name)}


# ------------------------------------------- Vorschlagsvorlage fuer Neues
PFLICHTANGABEN = ('auftrag', 'erwartete_nutzung', 'kosten')


def vorschlag(root, name, auftrag, erwartete_nutzung, kosten, art='Fähigkeit',
              begruendung='', at=None):
    """Jeder Vorschlag für Neues nennt die drei Pflichtangaben — sonst gar nicht.

    Auftrag 2.4, Aufgabe 3: welcher echte Auftrag ihn braucht, erwartete
    Nutzung, Kosten.
    """
    root = Path(root)
    at = at or b.now()
    werte = {'auftrag': str(auftrag or '').strip(),
             'erwartete_nutzung': str(erwartete_nutzung or '').strip(),
             'kosten': str(kosten or '').strip()}
    fehlt = [k for k in PFLICHTANGABEN if not werte[k]]
    if not str(name or '').strip():
        fehlt.append('name')
    if fehlt:
        raise ValueError('Ein Vorschlag ohne %s wird nicht angelegt. '
                         'Pflicht sind: welcher echte Auftrag ihn braucht, '
                         'erwartete Nutzung, Kosten.' % ', '.join(fehlt))
    ordner = root / 'auftraege' / 'freigabe'
    ordner.mkdir(parents=True, exist_ok=True)
    kurz = ''.join(c if c.isalnum() else '_' for c in str(name))[:40].strip('_')
    datei = ordner / (at.strftime('%Y-%m-%d') + '_FUNKTION_Vorschlag_' + kurz + '.md')
    zeilen = ['---',
              'marke:      JACK',
              'auftrag:    Neue %s: %s' % (art, name),
              'erteilt:    ' + at.strftime('%Y-%m-%d %H:%M'),
              'von:        JACK (Block 19, Vorschlagsvorlage)',
              'status:     freigabe',
              'freigabe:   nein',
              'gefahr:     keine',
              'tiefe:      klein',
              'bereiche:   steuerung',
              'art:        entscheidung',
              'vorgang:    funktion_vorschlag',
              '---',
              '',
              '## %s: %s' % (art, name),
              '',
              '### 1. Welcher echte Auftrag braucht sie?',
              '',
              werte['auftrag'],
              '',
              '### 2. Erwartete Nutzung',
              '',
              werte['erwartete_nutzung'],
              '',
              '### 3. Kosten',
              '',
              werte['kosten'],
              '']
    if begruendung:
        zeilen += ['### Weitere Begründung', '', str(begruendung), '']
    zeilen += ['## Regel dahinter',
               '',
               'Lehre 2 (Auftrag 2.4): JACK wächst nur um das, was wirklich benutzt',
               'wird. Ein Vorschlag ohne diese drei Angaben wird gar nicht erst',
               'angelegt. Nach 30 Tagen ohne Einsatz erscheint die Funktion im',
               'Monatsbericht mit der Frage „archivieren?".',
               '']
    datei.write_text('\n'.join(zeilen) + '\n', encoding='utf-8')
    return {'zeit': at.isoformat(), 'datei': str(datei), 'name': str(name),
            'meldung': 'Vorschlag liegt im Freigaben-Kasten: ' + datei.name}


def tick(root, at=None):
    """Monatsbericht am Ersten. Haengt in der Tagesroutine, kein zweiter Zeitgeber."""
    root = Path(root)
    at = at or b.now()
    if at.day != 1:
        return []
    schon = list((root / 'auftraege' / 'freigabe').glob(
        at.strftime('%Y-%m-') + '*_FUNKTIONEN_Monatsbericht_*.md'))
    schon += list((root / 'auftraege' / 'erledigt').glob(
        at.strftime('%Y-%m-') + '*_FUNKTIONEN_Monatsbericht_*.md'))
    if schon:
        return []
    return [monatsbericht(root, at)['datei']]
