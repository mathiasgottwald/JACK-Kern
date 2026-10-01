"""Stufe-0-Absichtserkennung für die Sprachsteuerung (Block 25, Teil B).

Kein Modell, keine Kosten, unter 300 ms. Erkennt Alltagsdeutsch für den
Aktionskatalog in betrieb/steuerung_katalog.json und wandelt einen Satz (oder
einen Mehrschrittsatz) in eine Aktionsfolge um. Was nicht sicher erkannt wird,
kommt als Rückfrage zurück — nie als geratene Ausführung.

Diese Datei ist eigenständig und testbar ohne den laufenden Dienst: `erkenne()`
nimmt reinen Text (und optional einen Kontext aus dem Gespräch) und gibt eine
Liste von Aktionsschritten oder eine Rückfrage zurück. Der Einbau in
server.py/index.html (Aufrufstelle, Stream-Ereignis, Quittung) ist in
abnahme/Block25_2026-09-17/EINBAUPLAN.md beschrieben und noch nicht
vorgenommen (siehe entscheidungen/2026-09-17_Block25_Entscheidungen_im_Lauf.md).

Stand 17.09.2026 — vorbereitet, nicht eingebaut.
"""
import json
import re
from pathlib import Path

try:
    import jack_aussenwelt as _aussenwelt
except ImportError:  # pragma: no cover - Modul liegt immer daneben
    _aussenwelt = None

import jack_hausnamen

SCHEMA = 1

ANREDE = re.compile(
    r'^(?:(?:also|hey|na|ok|okay|du)\s+)?'
    r'(?:check|jack|tschack|dschaeck|dschack|jeck)\s*[,]?\s+',
    re.IGNORECASE,
)

KASTEN_SYNONYME = {
    'marken': ['marke', 'marken', 'brand', 'brands'],
    'auftraege': ['auftrag', 'auftraege', 'auftraegen', 'aufträge', 'job', 'jobs',
                  'arbeit', 'arbeiten'],
    'freigaben': ['freigabe', 'freigaben', 'entscheidung', 'entscheidungen'],
    'agenten': ['agent', 'agenten', 'team'],
    'email': ['email', 'e-mail', 'e mail', 'emails', 'e-mails', 'e mails', 'mail', 'mails',
              'post', 'postfach', 'postfaecher', 'posteingang', 'nachricht', 'nachrichten'],
    'gespraech': ['gespraech', 'gespräch', 'chat', 'dialog'],
    'wissen': ['wissen', 'ablage', 'wissensablage'],
    'verbindungen': ['verbindung', 'verbindungen', 'anbindung', 'anbindungen',
                      'connection', 'connections'],
    'mitarbeiter': ['mitarbeiter', 'mitarbeitern', 'leute', 'kollege', 'kollegin',
                     'team mitglied'],
}

AUFTRAG_FILTER_WOERTER = {
    'offen': 'offen', 'offenen': 'offen', 'offene': 'offen',
    'laufen': 'laeuft', 'laeuft': 'laeuft', 'laufend': 'laeuft', 'laufende': 'laeuft',
    'problem': 'problem', 'probleme': 'problem', 'fehler': 'problem',
    'freigabe': 'freigabe', 'freigaben': 'freigabe',
}

OEFFNEN_VERBEN = [
    'oeffne', 'öffne', 'oeffnen sie', 'mach auf', 'machst du auf', 'zeig mir',
    'zeig mal', 'zeige mir', 'zeige mal', 'zeig die', 'zeig den', 'zeig das',
    'zeige die', 'zeige den', 'zeige das', 'geh auf', 'geh in', 'geh zu',
    'gehe auf', 'gehe in', 'gehe zu', 'wechsle zu', 'wechsle auf', 'ich will sehen',
    'ich moechte sehen', 'kurz die', 'kurz den', 'schau rein', 'schau mal rein',
    'schau nach', 'guck mal auf', 'guck mal rein',
]
SCHLIESSEN_VERBEN = ['schliess', 'schließ', 'mach zu', 'klapp zu', 'klapp ein', 'schliesse']
VOLLANSICHT_WOERTER = ['vollansicht', 'volle ansicht', 'ganze ansicht', 'ganz gross',
                        'alles anzeigen']
ZURUECK_WOERTER = ['zurueck', 'zurück', 'einen schritt zurueck', 'geh zurueck']
WEITER_WOERTER = ['weiter', 'mach weiter', 'naechstes', 'nächstes', 'geh weiter']
STOPP_WOERTER = ['stopp', 'stop', 'halt', 'hoer auf', 'hör auf', 'sei still', 'ruhe']
GENAUER_WOERTER = ['genauer', 'erzaehl mehr', 'erzähl mehr', 'mehr dazu', 'vertiefe das',
                    'geh tiefer']
VORLESEN_WOERTER = ['lies vor', 'lies das vor', 'trag mir das vor', 'lies mir das vor']
RUNDGANG_WOERTER = ['schau bei', 'schau dir', 'geh die durch', 'mach einen rundgang', 'rundgang']
SCROLL_HOCH = ['scroll hoch', 'scrolle hoch', 'nach oben']
SCROLL_RUNTER = ['scroll runter', 'scrolle runter', 'nach unten']

# Block 26, Teil 2 (T2.2): Sprachbefehle fuer die Einzelentscheidung im
# Freigaben-Kasten - nur gueltig innerhalb von kontext['einzelentscheidung']
# (siehe _segment). Volltreffer auf den GANZEN Satzteil (nach _mehrschritt_teile
# schon vom Rest des Satzes getrennt), kein Enthalten-Test. Geprueft wird
# gegen `folded` (_normalisiere/_falten hat ä/ö/ü/ß da schon in ae/oe/ue/ss
# umgeschrieben - "später" steht hier deshalb als "spaeter").
_ENTSCHEID_JA_RE = re.compile(r'^ja[.!,]*$', re.IGNORECASE)
_ENTSCHEID_NEIN_RE = re.compile(r'^nein[.!,]*$', re.IGNORECASE)
_ENTSCHEID_SPAETER_RE = re.compile(r'^spaeter[.!,]*$', re.IGNORECASE)
_ENTSCHEID_VORLESEN_RE = re.compile(
    r'^vorlesen[.!,]*$|^lies (?:die empfehlung |sie )?vor[.!,]*$', re.IGNORECASE)
_ENTSCHEID_NAECHSTE_RE = re.compile(r'^naechste entscheidung[.!,]*$', re.IGNORECASE)

# Block 25b, Teil E: Aussenwelt-Ziele (Karten, Kalender, Browser, ...), die
# Stufe 0 direkt erkennt, statt bei fehlendem Kasten-Wort in die alte
# Kasten-Sackgasse (Rueckfrage nach dem gemeinten Kasten) zu laufen (Befund
# 18.09.2026, 06:42:05 - "mach Google Maps auf" landete dort, obwohl kein
# Kasten gemeint war). 'mail' bleibt aussen vor - das Wort gehoert bereits
# KASTEN_SYNONYME['email'].
_AUSSENWELT_AUSSCHLUSS = {'mail'}


_AUSSENWELT_WOERTER_CACHE = None


def _aussenwelt_woerter():
    # Erst berechnet, wenn wirklich gebraucht (nicht beim Import) - _falten()
    # ist erst weiter unten in dieser Datei definiert.
    global _AUSSENWELT_WOERTER_CACHE
    if _AUSSENWELT_WOERTER_CACHE is not None:
        return _AUSSENWELT_WOERTER_CACHE
    woerter = {}
    if _aussenwelt is not None:
        for wort in _aussenwelt.KARTEN_WOERTER:
            woerter[_falten(wort)] = 'karten'
        for wort in _aussenwelt.APPS:
            if wort in _AUSSENWELT_AUSSCHLUSS:
                continue
            woerter.setdefault(_falten(wort), wort)
    _AUSSENWELT_WOERTER_CACHE = woerter
    return woerter


def _aussenwelt_ziel_aus_wort(folded_text):
    beste = None
    for wort, ziel in _aussenwelt_woerter().items():
        if re.search(r'\b' + re.escape(wort) + r'\b', folded_text):
            if beste is None or len(wort) > len(beste[1]):
                beste = (ziel, wort)
    return beste[0] if beste else None


# E1/E2: die Adresse kommt meist als eigener Folgesatz ("zum Marienplatz 1 in
# Rosenheim") oder als Korrektur ("nein, Marienplatz" / "Marienplatz, nicht
# Marktplatz"), nicht im selben Satz wie "mach Google Maps auf".
_ADRESSE_KORREKTUR_NEIN = re.compile(r'^nein\s*[,]?\s+(.+)$', re.IGNORECASE)
_ADRESSE_KORREKTUR_NICHT = re.compile(r'^(.+?)\s*,\s*nicht\s+.+$', re.IGNORECASE)
_ADRESSE_PRAEPOSITION = re.compile(
    r'\b(?:zum|zur|nach|in\s+die|in\s+den|in\s+das|zu)\s+(.+)$', re.IGNORECASE)
_ADRESSE_HINWEIS = re.compile(r'stra(?:ss|ß)e|platz|weg|allee|ring\b', re.IGNORECASE)


def _aussenwelt_adresse_aus_folgesatz(text_original):
    """Bekommt einen Satz, der NACH einem 'Karten offen, wohin soll's gehen?'
    kam - lies daraus eine Adresse oder eine Korrektur, sonst None (dann ist
    der Satz kein Adressfolgesatz und wird normal weiterverarbeitet)."""
    text_original = (text_original or '').strip()
    if not text_original:
        return None
    for muster in (_ADRESSE_KORREKTUR_NEIN, _ADRESSE_KORREKTUR_NICHT, _ADRESSE_PRAEPOSITION):
        treffer = muster.search(text_original)
        if treffer:
            return treffer.group(1).strip(' ,.')
    if re.search(r'\d', text_original) or _ADRESSE_HINWEIS.search(text_original):
        return text_original.strip(' ,.')
    return None


PRONOMEN_MAIL = re.compile(r'\b(sie|ihr|ihn|es)\b', re.IGNORECASE)
PRONOMEN_ORDINAL = re.compile(
    r'\bdie\s+(erste|zweite|dritte|vierte|fuenfte|fünfte)\b', re.IGNORECASE)
ORDINAL_INDEX = {'erste': 0, 'zweite': 1, 'dritte': 2, 'vierte': 3, 'fuenfte': 4, 'fünfte': 4}

ANTWORT_TRIGGER = re.compile(
    r'^(?:(?:kannst|könntest|koenntest) du )?(?:bitte )?'
    r'(?:antworte|schreib(?:e)?)\s+(?:ihr|ihm|dem|der)\b\s*[,:]?\s*(?:dass\s+)?(.+)$',
    re.IGNORECASE | re.DOTALL,
)
AENDERN_TRIGGER = re.compile(r'(?:ändere|aendere)\s*[,:]?\s*(.+)$',
                              re.IGNORECASE | re.DOTALL)

# Trennbare Verben ("mach ... auf", "lies ... vor") stehen im Deutschen oft
# nicht als zusammenhängende Zeichenkette im Satz. Diese Muster erlauben eine
# begrenzte Lücke zwischen den beiden Teilen.
TRENNBAR_AUF = re.compile(r'\bmach\w{0,3}\b.{0,40}\bauf\b', re.IGNORECASE)
TRENNBAR_ZU = re.compile(r'\bmach\w{0,3}\b.{0,40}\bzu\b', re.IGNORECASE)
TRENNBAR_VOR = re.compile(r'\b(?:lies\w{0,3}|trag\w{0,3})\b.{0,40}\bvor\b', re.IGNORECASE)
WILL_SEHEN = re.compile(r'\b(?:will|moechte)\b.{0,40}\bsehen\b', re.IGNORECASE)


def _falten(text):
    text = text.lower()
    for a, b in (('ä', 'ae'), ('ö', 'oe'), ('ü', 'ue'), ('ß', 'ss')):
        text = text.replace(a, b)
    return text


def _normalisiere(text):
    text = ' '.join(text.split())
    text = _falten(text)
    return text


def _katalog(root):
    if root is None:
        return None
    pfad = Path(root) / 'betrieb' / 'steuerung_katalog.json'
    if not pfad.exists():
        return None
    return json.loads(pfad.read_text())


def _ziel_aus_wort(folded_text):
    """Ganzwort-Suche, längster Treffer gewinnt — 'arbeit' darf nicht in
    'mitarbeiter' greifen, 'mails' braucht keinen eigenen Präfix-Treffer auf
    'mail', weil beide Formen explizit in KASTEN_SYNONYME stehen."""
    beste = None
    for kasten, woerter in KASTEN_SYNONYME.items():
        for wort in woerter:
            gefaltet = _falten(wort)
            if re.search(r'\b' + re.escape(gefaltet) + r'\b', folded_text):
                if beste is None or len(gefaltet) > len(beste[1]):
                    beste = (kasten, gefaltet)
    return beste[0] if beste else None


def _enthaelt(text, woerter):
    return any(w in text for w in woerter)


def _markennamen(root):
    namen = []
    try:
        if root is not None:
            marken_ordner = Path(root).parent
            if marken_ordner.is_dir():
                namen = [p.name for p in marken_ordner.iterdir() if p.is_dir()]
    except OSError:
        pass
    return namen


def _rueckfrage(grund, vorschlag=None):
    eintrag = {'unsicher': True, 'grund': grund}
    if vorschlag:
        eintrag['vorschlag'] = vorschlag
    return eintrag


def _mehrschritt_teile(text_original):
    """Trennt an ' und ', respektiert aber Freitext nach antworte/aendere-Auslösern."""
    for trigger in (ANTWORT_TRIGGER, AENDERN_TRIGGER):
        match = trigger.search(text_original)
        if match:
            vor = text_original[:match.start()].strip(' ,.')
            rest_teile = [vor] if vor else []
            teile = re.split(r'\s+und\s+', rest_teile[0], flags=re.IGNORECASE) if rest_teile else []
            teile = [t.strip() for t in teile if t.strip()]
            teile.append(text_original[match.start():].strip())
            return teile
    teile = re.split(r'\s+und\s+', text_original, flags=re.IGNORECASE)
    return [t.strip() for t in teile if t.strip()]


def _mail_parameter(text_original, folded):
    """Liest Absender/Betreff/nur_offen aus einem Mail-bezogenen Satz — unabhängig davon,
    ob er mit einem Öffnen-Verb (zeig mir/geh auf) oder mit 'such(e)' beginnt."""
    parameter = {}
    if ('nur offen' in folded or 'offene mails' in folded or 'offenen mails' in folded
            or 'nur die offenen' in folded or 'ungelesen' in folded):
        parameter['nur_offen'] = True
    betreff_match = re.search(
        r'(?:mit\s+dem\s+betreff|zum\s+betreff|betreff)\s+(.+?)(?:\s+raus)?$', text_original,
        re.IGNORECASE)
    if betreff_match:
        parameter['betreff'] = betreff_match.group(1).strip(' ,.:')
        return parameter
    von_match = re.search(r'\b(?:von|vom)\s+(.+?)(?:\s+raus)?$', text_original, re.IGNORECASE)
    if von_match:
        absender = von_match.group(1).strip(' ,.:')
        mitarbeiter = re.search(r'\bmitarbeiter(?:n)?\s*(.*)$', absender, re.IGNORECASE)
        if mitarbeiter:
            # Erst der Server gleicht gegen Register und Firmenadresse ab.
            # Der gesprochene Satzrest darf keinen falschen Absender bilden.
            parameter['mitarbeiter'] = mitarbeiter.group(1).strip(' ,.:')
        else:
            parameter['absender'] = absender
    return parameter


def _kurzbefehl(text, woerter):
    """Ein 'halt' in einer Erzählung ist kein Stopp-Befehl."""
    alternativen = '|'.join(re.escape(_falten(w)) for w in woerter)
    return bool(re.fullmatch(r'(?:(?:kannst|koenntest) du )?(?:bitte )?(?:' +
                             alternativen + r')(?: bitte| mal| kurz| jetzt)*[.!?,]*', text))


def _direkter_name(folded, root):
    """Der Satzrest nach dem Oeffnen-Verb ist genau ein bekannter Markenname oder ein bekannter Mitarbeitername.
    Hoervarianten (bin, denn) zaehlen hier NICHT - die gelten nur, wenn "Mitarbeiter" oder "Mail von" im Satz steht."""
    if root is None:
        return None
    rest = folded
    for wort in sorted(OEFFNEN_VERBEN, key=len, reverse=True):
        rest = rest.replace(_falten(wort), ' ')
    rest = re.sub(r'\b(?:mach\w{0,3}|auf)\b', ' ', rest)
    tokens = [t for t in re.findall(r'[a-z0-9]+', rest)
              if t not in jack_hausnamen.FUELLWOERTER and t not in ('marke', 'marken')]
    if not tokens or len(tokens) > 3:
        return None
    gesucht = ' '.join(tokens)
    treffer = [n for n in _markennamen(root)
               if _falten(n.replace('_', ' ')) == gesucht
               or (len(gesucht) >= 4 and _falten(n.replace('_', ' ')).startswith(gesucht + ' '))]
    if len(treffer) == 1:
        return {'aktion': 'zeige_marke', 'parameter': {'name': treffer[0]}}
    r = jack_hausnamen.pruefe_name(root, gesucht, 'mitarbeiter')
    if r['status'] == 'bekannt':
        return {'aktion': 'zeige_mitarbeiter', 'parameter': {'name': r['name']}}
    return None


def _segment(text_original, root, kontext):
    folded = _normalisiere(text_original)
    kontext = kontext or {}

    # Block 26, Teil 2 (T2.2): "ja"/"nein"/"spaeter"/"vorlesen"/"naechste
    # entscheidung" gelten NUR als Kartenentscheidung, solange der Client
    # ueber /freigaben/kontext gemeldet hat, dass die Ein-Karte-Anzeige
    # gerade offen ist (kontext['einzelentscheidung']). Ohne diese Sperre
    # wuerde jedes gesprochene "ja" im normalen Gespraech - eines der
    # haeufigsten deutschen Woerter ueberhaupt - als geratene Freigabe
    # ausgefuehrt. Volltreffer auf den GANZEN (getrennten) Satzteil, kein
    # Enthalten-Test - "ja" darf nicht in "Jahr" oder "objektiv" greifen.
    if kontext.get('einzelentscheidung'):
        if _ENTSCHEID_NAECHSTE_RE.match(folded):
            return {'aktion': 'naechste_entscheidung', 'parameter': {}}
        if _ENTSCHEID_JA_RE.match(folded):
            return {'aktion': 'entscheidung_ja', 'parameter': {}}
        if _ENTSCHEID_NEIN_RE.match(folded):
            return {'aktion': 'entscheidung_nein', 'parameter': {}}
        if _ENTSCHEID_SPAETER_RE.match(folded):
            return {'aktion': 'entscheidung_spaeter', 'parameter': {}}
        if _ENTSCHEID_VORLESEN_RE.match(folded):
            return {'aktion': 'entscheidung_vorlesen', 'parameter': {}}

    match = ANTWORT_TRIGGER.search(text_original)
    if match:
        anweisung = match.group(1).strip()
        if not anweisung:
            return _rueckfrage('Was soll in der Antwort stehen?')
        kennung = kontext.get('offene_mail')
        if not kennung:
            return _rueckfrage('Welche Mail meinst du? Gerade ist keine offen.')
        return {'aktion': 'mail_antwort', 'parameter': {'kennung': kennung, 'anweisung': anweisung}}

    match = (AENDERN_TRIGGER.search(text_original)
             if folded.startswith(('aendere', 'ändere')) and kontext.get('offene_mail')
             and re.search(r'\b(?:entwurf|mail|antwort)\b', folded) else None)
    if match:
        anweisung = match.group(1).strip()
        kennung = kontext.get('offene_mail')
        return {'aktion': 'entwurf_aendern', 'parameter': {'kennung': kennung, 'anweisung': anweisung}}

    if _kurzbefehl(folded, STOPP_WOERTER):
        return {'aktion': 'stopp', 'parameter': {}}
    if _enthaelt(folded, [_falten(w) for w in VORLESEN_WOERTER]) or TRENNBAR_VOR.search(folded):
        return {'aktion': 'entwurf_vorlesen', 'parameter': {'kennung': kontext.get('offene_mail')}}
    if _enthaelt(folded, [_falten(w) for w in RUNDGANG_WOERTER]):
        ziel = _ziel_aus_wort(folded)
        if ziel:
            return {'aktion': 'rundgang', 'parameter': {'kasten': ziel}}
        if 'rundgang' in folded:
            return _rueckfrage('Wo soll ich den Rundgang machen — bei den Marken, den Aufträgen oder den Agenten?')
        # 'schau bei'/'schau dir' ohne erkennbares Ziel: eher Füllwort eines
        # Mehrschrittsatzes (z. B. der Nachsatz "gib mir eine Übersicht") als
        # ein eigenständiger, unklarer Befehl — nicht raten, aber auch nicht
        # den ganzen Satz an einer Rückfrage scheitern lassen.
    if _kurzbefehl(folded, GENAUER_WOERTER):
        return {'aktion': 'genauer', 'parameter': {}}
    if _kurzbefehl(folded, WEITER_WOERTER + ['weitermachen', 'fortsetzen']):
        return {'aktion': 'weiter', 'parameter': {}}
    if _kurzbefehl(folded, ZURUECK_WOERTER):
        return {'aktion': 'zurueck', 'parameter': {}}
    if _enthaelt(folded, [_falten(w) for w in SCROLL_HOCH]):
        return {'aktion': 'scrolle', 'parameter': {'richtung': 'hoch'}}
    if _enthaelt(folded, [_falten(w) for w in SCROLL_RUNTER]):
        return {'aktion': 'scrolle', 'parameter': {'richtung': 'runter'}}
    if _enthaelt(folded, [_falten(w) for w in VOLLANSICHT_WOERTER]):
        return {'aktion': 'vollansicht', 'parameter': {}}

    if PRONOMEN_ORDINAL.search(text_original):
        wort = PRONOMEN_ORDINAL.search(text_original).group(1)
        index = ORDINAL_INDEX.get(_falten(wort))
        letzte_liste = kontext.get('letzte_mail_liste')
        if letzte_liste and index is not None and index < len(letzte_liste):
            return {'aktion': 'mail_oeffnen', 'parameter': {'kennung': letzte_liste[index]}}
        return _rueckfrage('Welche Liste meinst du mit „die ' + wort + '“? Ich habe gerade keine vor mir.')

    ist_schliessen = _enthaelt(folded, [_falten(w) for w in SCHLIESSEN_VERBEN]) or bool(TRENNBAR_ZU.search(folded))
    ist_oeffnen = (_enthaelt(folded, [_falten(w) for w in OEFFNEN_VERBEN])
                   or bool(TRENNBAR_AUF.search(folded)) or bool(WILL_SEHEN.search(folded)))
    if ist_oeffnen or ist_schliessen:
        schliessen = ist_schliessen
        if PRONOMEN_MAIL.search(text_original) and re.search(r'\b(sie|ihn|es)\b', text_original, re.IGNORECASE):
            ziel_wort_vorhanden = _ziel_aus_wort(folded)
            if not ziel_wort_vorhanden:
                letzte_liste = kontext.get('letzte_mail_liste')
                offene_mail = kontext.get('offene_mail')
                # Block 25b, Teil F1: Bezug auf eine bereits offene Mail hat
                # Vorrang. Vorher scheiterte "öffne sie" nach einem
                # Ein-Treffer-Fund an genau dieser Stelle, weil das
                # automatische Oeffnen (server.py) STEUERKONTEXT["offene_mail"]
                # bereits gesetzt hatte - die alte Bedingung verlangte
                # "offene_mail is None" und lief dann in die "Welcher Kasten
                # ist gemeint?"-Sackgasse (Befund 18.09.2026, 06:13-Fall).
                # Ein B1-Doppel-Schutz in server.py verhindert das doppelte
                # erneute Oeffnen derselben Mail.
                if not schliessen and offene_mail:
                    return {'aktion': 'mail_oeffnen', 'parameter': {'kennung': offene_mail}}
                if not schliessen and letzte_liste and len(letzte_liste) == 1:
                    return {'aktion': 'mail_oeffnen', 'parameter': {'kennung': letzte_liste[0]}}
                if not schliessen and letzte_liste and len(letzte_liste) > 1:
                    return _rueckfrage(
                        'Da sind ' + str(len(letzte_liste)) + ' Mails — welche meinst du?')
                if not schliessen and not letzte_liste:
                    return _rueckfrage('Welche Mail meinst du? Ich habe gerade keine vor mir.')
        ziel = _ziel_aus_wort(folded)
        # In "E-Mails von unserem Mitarbeiter DIN" bezeichnet Mitarbeiter
        # die Person, nicht den zu oeffnenden Bereich. Die bisherige Regel
        # nahm wegen des laengeren Wortes faelschlich den Mitarbeiterkasten.
        if (ziel == 'mitarbeiter'
                and re.search(r'\b(?:mail|mails|email|emails|e-mail|e-mails|nachricht|nachrichten|post)\b', folded)
                and re.search(r'\b(?:von|vom)\b', folded)):
            ziel = 'email'
        if schliessen and ziel:
            return {'aktion': 'schliesse_kasten', 'parameter': {'ziel': ziel}}
        if ziel == 'marken':
            for name in _markennamen(root):
                if _falten(name.replace('_', ' ')) in folded or _falten(name) in folded:
                    return {'aktion': 'zeige_marke', 'parameter': {'name': name}}
            # S-2 P6(d): "GOTT WALD" meint GOTT_WALD_Holding (eindeutiger Namensanfang)
            direkt = _direkter_name(folded, root)
            if direkt and direkt.get('aktion') == 'zeige_marke':
                return direkt
        if ziel == 'mitarbeiter':
            rest = folded
            for wort in KASTEN_SYNONYME['mitarbeiter']:
                rest = rest.replace(_falten(wort), '')
            for wort in OEFFNEN_VERBEN + SCHLIESSEN_VERBEN:
                rest = rest.replace(_falten(wort), '')
            name = rest.strip(' ,.')
            if name:
                return {'aktion': 'zeige_mitarbeiter', 'parameter': {'name': name}}
            return {'aktion': 'oeffne_kasten', 'parameter': {'ziel': 'mitarbeiter'}}
        if ziel == 'email':
            parameter = _mail_parameter(text_original, folded)
            return {'aktion': 'posteingang', 'parameter': parameter}
        if ziel == 'auftraege':
            gefunden_filter = None
            for wort, wert in AUFTRAG_FILTER_WOERTER.items():
                if _falten(wort) in folded:
                    gefunden_filter = wert
                    break
            return {'aktion': 'zeige_auftraege',
                     'parameter': {'filter': gefunden_filter} if gefunden_filter else {}}
        if ziel == 'freigaben':
            return {'aktion': 'zeige_freigaben', 'parameter': {}}
        if ziel == 'agenten':
            return {'aktion': 'zeige_agenten', 'parameter': {}}
        if ziel == 'wissen':
            return {'aktion': 'zeige_wissen', 'parameter': {}}
        if ziel == 'verbindungen':
            return {'aktion': 'zeige_verbindungen', 'parameter': {}}
        if ziel == 'gespraech':
            return {'aktion': 'oeffne_kasten', 'parameter': {'ziel': 'gespraech'}}
        if ziel:
            return {'aktion': 'schliesse_kasten' if schliessen else 'oeffne_kasten',
                    'parameter': {'ziel': ziel}}
        if not schliessen:
            aussen_ziel = _aussenwelt_ziel_aus_wort(folded)
            if aussen_ziel:
                return {'aktion': 'aussen_oeffnen', 'parameter': {'ziel': aussen_ziel}}
            # S-1: "zeig mir PATRONOS" / "zeig mir Dween Mohammad" - ein bekannter Name ist ein bekanntes Ziel,
            # auch ohne das Wort "Marke"/"Mitarbeiter" im Satz. Nur ein Name aus der Hausnamenliste, nie geraten.
            direkt = _direkter_name(folded, root)
            if direkt:
                return direkt
        # Block 25b, Teil D2: keine Sackgasse mehr fuer einen unbekannten
        # "oeffne"/"schliess"-Satz ohne erkennbares Ziel - das war die alte
        # Rueckfrage nach dem gemeinten Kasten aus dem Befund (18.09.2026,
        # 06:42:05, "mach Google Maps auf"). None laesst den Satz an das
        # Modell durch (mit Katalog und Wissensleiter, Block 25 B3), statt
        # ihn lokal zu erraten oder zu blockieren. Eine Rueckfrage stellt
        # Stufe 0 nur noch bei echter Zweideutigkeit zwischen zwei bekannten
        # Zielen (Mail-Treffer oben, unveraendert).
        return None

    if re.search(r'\b(mail|mails|email|emails|e-mail|e-mails|nachricht|nachrichten|post)\b',
                 folded):
        parameter = _mail_parameter(text_original, folded)
        if parameter:
            return {'aktion': 'posteingang', 'parameter': parameter}

    if re.fullmatch(r'oeffne\s+sie|mach\s+sie\s+auf', folded):
        return _rueckfrage('Welche Mail meinst du? Ich habe gerade keine vor mir.')

    # Block 25b, Teil E1/E2: der Satz danach nennt oft nur noch die Adresse
    # oder eine Korrektur, ohne "Check"/"öffne" davor - Bezug auf die letzte
    # Aussenwelt-Aktion (wie E5 aus Block 25 fuer Mails). Bewusst akzeptiertes
    # Restrisiko: ein zufaellig zahlenhaltiger Satz koennte hier faelschlich
    # als Adresse gelten, solange der Kontext "karten" noch steht - siehe
    # entscheidungen/2026-09-18_Block25b_Entscheidungen_im_Lauf.md.
    if (kontext or {}).get('aussenwelt_ziel') == 'karten':
        adresse = _aussenwelt_adresse_aus_folgesatz(text_original)
        if adresse:
            return {'aktion': 'aussen_oeffnen', 'parameter': {'ziel': 'karten', 'adresse': adresse}}

    return None



# ---------------------------------------------------------------------------
# S-1, P1 (24.09.2026): "Verstehen vor Handeln". Ein Sofortbefehl greift nur
# noch, wenn der ganze (Teil-)Satz nach der Anrede ein kurzer, eindeutiger
# Befehl ist: bekanntes Verb + bekanntes Ziel (das prueft _segment), hoechstens
# 7 Woerter, kein Nebensatz, kein Fragewort am Anfang. Jeder andere Satz gibt
# None zurueck und geht in den Gespraechsweg (KI mit den Steuerwerkzeugen).
# ---------------------------------------------------------------------------
MAX_BEFEHLSWOERTER = 7
FRAGE_UEBERALL = frozenset({
    'wer', 'wen', 'wem', 'wessen', 'was', 'wie', 'wieso', 'warum', 'weshalb', 'welche', 'welcher', 'welches',
    'welchen', 'welchem', 'wann', 'wo', 'woher', 'wohin', 'wieviel', 'wieviele'})
# Ausdruecklich erlaubter Nachsatz, der einen Befehl begleitet ("... und gib mir eine Uebersicht").
NACHSATZ_OK = re.compile(r'^(?:und\s+)?(?:gib mir|zeig mir|mach mir)?\s*(?:mal\s+)?(?:eine?n?\s+)?(?:kurze[nr]?\s+)?'
                         r'(?:uebersicht|ueberblick)(?:\s+(?:dazu|bitte))?$')
NEBENSATZ_WOERTER = frozenset({'dass', 'weil', 'ob', 'wenn', 'aber', 'obwohl'})
FRAGE_ANFAENGE = frozenset({
    'wer', 'was', 'wie', 'wieso', 'warum', 'weshalb', 'welche', 'welcher', 'welches',
    'welchen', 'welchem', 'wann', 'wo', 'woher', 'wohin', 'wieviel', 'wieviele',
    'haben', 'hat', 'hast', 'habt', 'gibt', 'ist', 'sind'})


def _befehlsworte(text):
    return [w for w in re.split(r'[\s,;:!?.]+', _falten(text)) if w]


def _ist_kurzer_befehl(teil, ergebnis):
    """Darf dieser erkannte Teilsatz ohne KI ausgefuehrt werden?"""
    aktion = (ergebnis or {}).get('aktion')
    parameter = (ergebnis or {}).get('parameter') or {}
    text = teil.strip()
    if aktion in ('mail_antwort', 'entwurf_aendern'):
        # Freitext-Auftrag ("antworte ihr: ..."): der frei gesprochene Text ist
        # kein Satzbau-Kriterium; nur was VOR dem Ausloeser steht zaehlt.
        treffer = ANTWORT_TRIGGER.search(text) or AENDERN_TRIGGER.search(text)
        text = text[:treffer.start()] if treffer else text
        return not _befehlsworte(text) or _ist_kurzer_befehl_text(text, gezaehlt=True)
    if aktion == 'aussen_oeffnen':
        # "Google Maps auf, ich muss in die Rosenheimer Strasse 12": der Befehl
        # ist der erste Satzteil; eine mitgelieferte Adresse ist Angabe, kein Befehlsteil.
        if not _ist_kurzer_befehl_text(text, gezaehlt=False):   # Nebensatz/Fragewort gilt fuer den GANZEN Satz
            return False
        if 'adresse' in parameter:
            return True
        text = text.split(',')[0]
    return _ist_kurzer_befehl_text(text, gezaehlt=True)


def _ist_kurzer_befehl_text(text, gezaehlt=True):
    woerter = _befehlsworte(text)
    if not woerter:
        return True
    if woerter[0] in FRAGE_ANFAENGE:
        return False
    # S-2 P6(b): ein Fragewort MITTEN im Satz ("..., welche Mails Din geschrieben hat") macht ihn zur Frage
    if any(w in FRAGE_UEBERALL for w in woerter[1:]):
        return False
    if any(w in NEBENSATZ_WOERTER for w in woerter):
        return False
    return len(woerter) <= MAX_BEFEHLSWOERTER if gezaehlt else True


def _genitiv_mails(anzeige):
    if anzeige and anzeige[-1].lower() in 'sxzß':
        return 'die Mails von ' + anzeige
    return anzeige + 's Mails'


def _namen_pruefen(ergebnis, root, kontext):
    """S-1 P1/P3: Namen aus dem Satzrest nur verwenden, wenn sie bekannt sind
    (Mitarbeiterliste inkl. Alias, Absender im Postfach). Rueckgabe:
      das (ggf. berichtigte) Ergebnis | eine Rueckfrage mit Vorschlag
      | None = Gespraechsweg (nie "Kein Mitarbeiter namens <Satzrest> gefunden")."""
    if root is None:
        return ergebnis
    aktion = ergebnis.get('aktion')
    parameter = dict(ergebnis.get('parameter') or {})

    def pruefen(roh, art):
        return jack_hausnamen.pruefe_name(root, roh, art)

    if aktion == 'zeige_mitarbeiter':
        r = pruefen(parameter.get('name', ''), 'mitarbeiter')
        if r['status'] == 'leer':
            return {'aktion': 'oeffne_kasten', 'parameter': {'ziel': 'mitarbeiter'}}
        if r['status'] in ('bekannt', 'sicher'):
            return {'aktion': aktion, 'parameter': {**parameter, 'name': r['name']}}
        if r['status'] == 'unsicher':
            return _rueckfrage('Meinst du ' + r['vorschlag'] + '? Dann öffne ich die Akte.', r['vorschlag'])
        return None
    if aktion == 'posteingang':
        for schluessel, art in (('mitarbeiter', 'mitarbeiter'), ('absender', 'absender')):
            roh = parameter.get(schluessel)
            if roh is None or roh == '':
                continue
            if schluessel == 'absender' and jack_hausnamen.ist_pronomen(roh):
                if (kontext or {}).get('letzter_mitarbeiter'):
                    continue
                return None
            r = pruefen(roh, art)
            if r['status'] == 'leer':
                parameter.pop(schluessel, None)
                if schluessel == 'mitarbeiter':
                    parameter['mitarbeiter'] = ''
                continue
            if r['status'] in ('bekannt', 'sicher'):
                if schluessel == 'absender' and r.get('anzeige') and r['name'] != r['anzeige'] and \
                        jack_hausnamen.pruefe_name(root, roh, 'mitarbeiter')['status'] in ('bekannt', 'sicher'):
                    parameter.pop('absender', None)
                    parameter['mitarbeiter'] = r['name']
                else:
                    parameter[schluessel] = r['name'] if art == 'mitarbeiter' or r['name'] != ' '.join(
                        jack_hausnamen._rest_tokens(roh)) else roh
                continue
            if r['status'] == 'unsicher':
                return _rueckfrage('Meinst du ' + r['vorschlag'] + '? Dann schaue ich in ' +
                                   ('seine' if r['vorschlag'] else 'die') + ' Mails.', r['vorschlag'])
            return None
        return {'aktion': aktion, 'parameter': parameter}
    return ergebnis


def erkenne(text, root=None, kontext=None):
    """Nimmt einen erkannten Sprach- oder Textsatz entgegen.

    Gibt zurück:
      - {'schritte': [ {aktion, parameter}, ... ]}  bei sicherer Erkennung,
      - {'unsicher': True, 'grund': '...'}  bei Unsicherheit (keine Ausführung),
      - None, wenn der Satz nichts mit der Sprachsteuerung zu tun hat
        (dann läuft der bestehende Weg: jack_erweiterungen.intent, danach frage_jack).
    """
    if not isinstance(text, str) or not text.strip():
        return None
    original = text.strip()
    anrede_treffer = ANREDE.match(original)
    kern = original[anrede_treffer.end():].strip() if anrede_treffer else original
    if not kern:
        return _rueckfrage('Ja, ich höre. Was soll ich tun?')

    teile = _mehrschritt_teile(kern)
    if not teile:
        teile = [kern]

    schritte = []
    laufender_kontext = dict(kontext or {})
    fanden_etwas = False
    unerkannt = False
    for teil in teile:
        ergebnis = _segment(teil, root, laufender_kontext)
        if ergebnis is None:
            if not anrede_treffer and not fanden_etwas:
                return None
            if not NACHSATZ_OK.match(_falten(teil).strip(' ,.')):
                unerkannt = True
            continue
        # S-1 P1: erkannt heisst noch nicht ausfuehren. Ist der Satz kein kurzer,
        # eindeutiger Befehl, geht der GANZE Satz in den Gespraechsweg.
        if not _ist_kurzer_befehl(teil, ergebnis):
            return None
        ergebnis = _namen_pruefen(ergebnis, root, laufender_kontext) if not ergebnis.get('unsicher') else ergebnis
        if ergebnis is None:
            return None
        if ergebnis.get('unsicher'):
            return ergebnis
        fanden_etwas = True
        schritte.append(ergebnis)
        if ergebnis['aktion'] == 'mail_oeffnen':
            laufender_kontext['offene_mail'] = ergebnis['parameter'].get('kennung')
        if ergebnis['aktion'] == 'zeige_marke':
            laufender_kontext['letzte_marke'] = ergebnis['parameter'].get('name')
        if ergebnis['aktion'] == 'aussen_oeffnen':
            laufender_kontext['aussenwelt_ziel'] = ergebnis['parameter'].get('ziel')

    if unerkannt:
        # S-1 P1: ein Teilsatz, den Stufe 0 nicht versteht, darf nicht still wegfallen, waehrend der Rest ausgefuehrt
        # wird ("... und sag mir worum es geht"): der GANZE Satz geht in den Gespraechsweg.
        return None
    if not schritte:
        # Block 25b, Teil D2: auch der Anrede-Fall ("Check, <nichts Bekanntes>")
        # ist keine Sackgasse mehr - None laesst den Satz an das Modell durch,
        # das den Katalog und die Wissensleiter kennt (Block 25 B3). Vorher
        # blockierte diese Zeile jeden mit "Check"/"Jack" eingeleiteten Satz,
        # den Stufe 0 nicht kannte - und genau so beginnen die meisten Saetze
        # in diesem System (README_SPRACHSTEUERUNG.md).
        return None
    return {'schritte': schritte}
