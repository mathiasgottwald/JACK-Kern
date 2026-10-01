"""Lokales Verbrauchsbuch: Anbieterbetraege, fehlende Angaben und offene Laeufe getrennt."""
from contextlib import contextmanager
import datetime as dt
from decimal import Decimal,InvalidOperation
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parent))
import jack_speicher
import jack_betrieb as b

KINDS={'gespraech':'Gespräch','fachentwurf':'Fachentwurf','rat':'Modellrat','stimme':'Stimme','codex':'Codex','arbeiter_api':'Arbeiter API','arbeiter_abo':'Arbeiter Abo','arbeiter_ruflo':'Arbeiter Ruflo','messtest':'Messtest','video':'Videoerzeugung','groq':'Groq (gratis, nur oeffentlich)','veroeffentlichung':'Veroeffentlichung (F-15)'}
USAGE={'input_tokens','output_tokens','cache_creation_input_tokens','cache_read_input_tokens','cached_input_tokens','prompt_tokens','completion_tokens','total_tokens','zeichen_angefordert','zeichen_gemeldet','audio_bytes'}
USAGE.update({'cache_creation_5m_input_tokens', 'cache_creation_1h_input_tokens'})


def usage(value):
    result={}
    if isinstance(value,list):
        for part in value:
            for k,v in usage(part).items():result[k]=result.get(k,0)+v
    elif isinstance(value,dict):
        for k,v in value.items():
            if k in USAGE and type(v) in (int,float) and math.isfinite(v) and v>=0:result[k]=v
        cache = value.get('cache_creation')
        if isinstance(cache, dict):
            for duration in ('5m', '1h'):
                v = cache.get('ephemeral_' + duration + '_input_tokens')
                if type(v) in (int, float) and math.isfinite(v) and v >= 0:
                    result['cache_creation_' + duration + '_input_tokens'] = v
    return result


def cli_usage(result):
    """CLI usage kann nur den Hauptagenten enthalten; modelUsage umfasst alle."""
    fields = {'inputTokens': 'input_tokens', 'outputTokens': 'output_tokens',
              'cacheReadInputTokens': 'cache_read_input_tokens',
              'cacheCreationInputTokens': 'cache_creation_input_tokens'}
    models = result.get('modelUsage')
    if isinstance(models, dict) and models:
        rows = [usage({new: entry[old] for old, new in fields.items() if old in entry})
                for entry in models.values() if isinstance(entry, dict)]
        if rows and all(rows):
            return usage(rows)
    return usage(result.get('usage'))


def amount(value):
    if value is None or isinstance(value,bool):return None
    try:
        n=Decimal(str(value))
        return str(n) if n.is_finite() and n>=0 else None
    except (InvalidOperation,ValueError):return None


def ledger(root):return b.area(root)/'kostenlaeufe.jsonl'


# ═══ Kostenschaetzung (Block 10, 16.09.2026) ═══════════════════════════════
# Der Anbieter meldet zu den meisten Laeufen KEINEN Geldbetrag - am 16.09.2026
# zu 275 von 295. Ein Geld-Deckel, der nur gemeldete Betraege sieht, deckelt
# den kleineren Teil der Ausgaben. Deshalb wird aus dem gemeldeten
# Tokenverbrauch und den BELEGTEN Listenpreisen ein Betrag geschaetzt.
#
# Drei Regeln, die das ehrlich halten:
#   1. Die Preise stehen in betrieb/modellpreise.json MIT Quelle und
#      Abrufdatum. Kein Preis wird im Code erfunden.
#   2. Fehlt fuer ein Modell ein belegter Preis, bleibt der Lauf "ohne
#      Betrag". Es wird nicht geraten, nicht gemittelt, nicht hochgerechnet.
#   3. Das Feld heisst usd_geschaetzt und wird ueberall als SCHAETZUNG
#      angezeigt. Wo der Anbieter einen Betrag meldet, gilt seiner.
PREISDATEI = 'modellpreise.json'
_PREISE = {}
_PREIS_SIG = {}


def preise(root):
    """Belegte Listenpreise. Fehlt die Datei, wird nichts geschaetzt."""
    schluessel = str(b.area(root))
    try:
        pfad = b.area(root)/PREISDATEI
        st = pfad.stat()
        signatur = (st.st_mtime_ns, st.st_size, st.st_ino)
        if schluessel in _PREISE and _PREIS_SIG.get(schluessel) == signatur:
            return _PREISE[schluessel]
        daten = json.loads(pfad.read_text(encoding='utf-8'))
        if not isinstance(daten, dict) or not isinstance(daten.get('modelle'), dict):
            raise ValueError('Preisdatei ist kein Modellverzeichnis')
    except (OSError, ValueError):
        daten = {'modelle': {}, 'quelle': '', 'abgerufen': ''}
        signatur = None
    _PREISE[schluessel] = daten
    _PREIS_SIG[schluessel] = signatur
    return daten


def schaetzung(root, modell, verbrauch):
    """(Betrag als Text, Preisstand) oder (None, '') - nie geraten.

    Gerechnet wird mit Decimal, damit aus Cent-Betraegen keine
    Gleitkomma-Faransen werden.
    """
    v = usage(verbrauch)
    if not v:
        return None, ''
    daten = preise(root)
    satz = (daten.get('modelle') or {}).get(str(modell or ''))
    if not satz:
        return None, ''
    mio = Decimal(1000000)
    try:
        if any(not Decimal(str(satz[k])).is_finite() or Decimal(str(satz[k])) < 0
               for k in ('eingabe', 'ausgabe', 'cache_lesen', 'cache_schreiben', 'cache_schreiben_1h') if k in satz):
            return None, ''
        schreiben = Decimal(str(v.get('cache_creation_input_tokens', 0)))
        stunde = Decimal(str(v.get('cache_creation_1h_input_tokens', 0)))
        minuten = Decimal(str(v.get('cache_creation_5m_input_tokens', 0)))
        if stunde + minuten > schreiben:
            return None, ''
        # Eine Stunde kostet 2x Eingabe, fuenf Minuten 1,25x. Frueher wurde
        # jeder Cache-Schreibvorgang mit dem billigeren Fuenf-Minuten-Satz gebucht.
        stundensatz = satz.get('cache_schreiben_1h')
        if stunde and stundensatz is None:
            return None, ''
        betrag = (Decimal(str(v.get('input_tokens', 0))) * Decimal(str(satz['eingabe']))
                  + Decimal(str(v.get('output_tokens', 0))) * Decimal(str(satz['ausgabe']))
                  + Decimal(str(v.get('cache_read_input_tokens', 0))) * Decimal(str(satz.get('cache_lesen', 0)))
                  + (schreiben - stunde) * Decimal(str(satz.get('cache_schreiben', 0)))
                  + stunde * Decimal(str(stundensatz or 0))
                  ) / mio
    except (InvalidOperation, KeyError, TypeError):
        return None, ''
    stand = '%s, abgerufen %s' % (daten.get('quelle', 'ohne Quelle'),
                                  daten.get('abgerufen', 'ohne Datum'))
    return str(betrag.quantize(Decimal('0.000001'))), stand


# ═══ Globale Budgetreservierung fuer Videolaeufe (Videobetrieb Teil 3, P08, 23.09.2026) ═══
# Der bestehende Kostenwaechter (jack_grenzen) sieht nur bereits VERBUCHTEN
# Verbrauch. Zwei gleichzeitig gestartete Videoauftraege (unterschiedliche
# Kennungen, also unterschiedliche higgsfield.sperre/runway.sperre-Dateien)
# koennten beide denselben Deckel-Rest lesen, bevor auch nur einer von ihnen
# einen Kostenlauf geschrieben hat. Diese Sperre ist deshalb GLOBAL (nicht je
# Auftrag) und macht Pruefung und Reservierung eines Betrags atomar: kein
# Lesen-dann-Schreiben ohne Sperre, wie bereits in jack_higgsfield.py und
# jack_runway.py (_sperre) fuer den jeweiligen Einzelauftrag verwendet.
RESERVIERUNGSDATEI = 'video_reservierungen.jsonl'
RESERVIERUNG_FRIST_SEKUNDEN = 15*60
RESERVIERUNG_STATUS = ('ok','fehler','gestoppt_vor_aufruf')


def _reservierungspfad(root):
    return b.area(root)/RESERVIERUNGSDATEI


@contextmanager
def _reservierungssperre(root):
    pfad = b.area(root)/'video_reservierungen.sperre'
    with pfad.open('a+') as datei:
        fcntl.flock(datei, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(datei, fcntl.LOCK_UN)


def _reservierung_schreiben(root, zeile):
    p = _reservierungspfad(root)
    flags = os.O_WRONLY|os.O_APPEND|os.O_CREAT|getattr(os,'O_NOFOLLOW',0)
    fd = os.open(p, flags, 0o600)
    with os.fdopen(fd,'a') as f:
        f.write(json.dumps(zeile,ensure_ascii=False)+'\n'); f.flush(); os.fsync(f.fileno())


def reservierungszeilen(root):
    return jack_speicher.iter_records(_reservierungspfad(root))


def _offene_reservierungen(root, jetzt):
    zeilen = list(reservierungszeilen(root))
    geloest = {z['id'] for z in zeilen if z.get('ereignis')=='geloest' and z.get('id')}
    offen = []
    for z in zeilen:
        if z.get('ereignis') != 'reserviert' or not z.get('id') or z['id'] in geloest:
            continue
        try:
            abgelaufen = dt.datetime.fromisoformat(z['frist']) < jetzt
        except (KeyError, TypeError, ValueError):
            abgelaufen = True
        offen.append({**z, 'abgelaufen': abgelaufen})
    return offen


def reservieren(root, kennung, betrag_usd):
    """Atomare globale Budgetreservierung vor einem bezahlten Videostart (P08).

    Zaehlt bereits verbuchten Verbrauch (jack_grenzen) UND alle noch offenen
    Reservierungen - auch abgelaufen-ungeklaerte, damit nichts still-
    schweigend aus der Rechnung verschwindet - gegen Stunden- und Tages-
    deckel, bevor diese Reservierung selbst geschrieben wird. Alles unter
    derselben Sperre, damit zwei gleichzeitige Starts niemals beide
    durchkommen, wenn sie zusammen den Deckel ueberschreiten wuerden.
    Liefert die Reservierungskennung; muss ueber reservierung_abschliessen()
    aufgeloest werden (Status ok, fehler oder gestoppt_vor_aufruf).
    """
    import jack_grenzen
    try:
        betrag = Decimal(str(betrag_usd))
        if not betrag.is_finite() or betrag < 0:
            raise ValueError('Reservierungsbetrag ist ungueltig')
    except InvalidOperation:
        raise ValueError('Reservierungsbetrag ist ungueltig')
    if not isinstance(kennung, str) or not kennung:
        raise ValueError('Videoauftragskennung fehlt fuer die Reservierung')
    with _reservierungssperre(root):
        jetzt = b.now()
        offene = _offene_reservierungen(root, jetzt)
        zusaetzlich_offen = sum((Decimal(str(o['betrag_usd'])) for o in offene), Decimal(0))
        try:
            stand = jack_grenzen.verbrauch(root)
            grenzen = jack_grenzen.lesen(root)
            status = jack_grenzen.deckel_status(root, grenzen, stand)
            if status['erreicht']:
                raise ValueError(status['grund'])
            for grenze,istfeld,name in (('budget_usd_je_stunde','stunde_usd','Stundendeckel'),
                                        ('budget_usd_je_tag','tag_usd','Tagesdeckel')):
                deckel = grenzen.get(grenze)
                if grenze == 'budget_usd_je_tag':
                    _,_,deckel = jack_grenzen.tagesdeckel(root, grenzen)
                if deckel not in (None,'',0):
                    ist = Decimal(str(stand.get(istfeld,'0'))) + zusaetzlich_offen + betrag
                    if ist > Decimal(str(deckel)):
                        raise ValueError(name+' wuerde durch offene Reservierungen und diesen Videolauf ueberschritten')
        except ValueError:
            raise
        except Exception as fehler:
            raise ValueError('Kostenwaechter nicht pruefbar; keine Reservierung') from fehler
        eintrag = {'id':uuid.uuid4().hex,'ereignis':'reserviert','zeit':jetzt.isoformat(),
                   'kennung':kennung,'betrag_usd':str(betrag),
                   'frist':(jetzt+dt.timedelta(seconds=RESERVIERUNG_FRIST_SEKUNDEN)).isoformat()}
        lauf = os.environ.get('JACK_AUFTRAG_RUN_ID',''); auftrag = os.environ.get('JACK_AUFTRAG_DATEI','')
        if len(lauf)==32 and all(c in '0123456789abcdef' for c in lauf) and auftrag.endswith('.md') and not any(c in auftrag for c in '/\\\r\n'):
            eintrag['auftragslauf']=lauf; eintrag['auftrag']=auftrag[:220]
        _reservierung_schreiben(root, eintrag)
        return eintrag['id']


def reservierung_abschliessen(root, reservierung_id, status, kosten_lauf_id=None):
    """Loest eine Reservierung auf (P08): ok, fehler oder gestoppt_vor_aufruf.

    Abgebrochene oder fehlgeschlagene Anbieterauftraege durchlaufen denselben
    Weg wie erfolgreiche - keiner bleibt unaufgeloest liegen. Idempotent wie
    jack_kosten.end(): ein zweiter Abschluss mit demselben Status wird
    bestaetigt, ein widerspruechlicher abgelehnt (kein doppeltes Verrechnen).
    """
    if status not in RESERVIERUNG_STATUS:
        raise ValueError('Ungueltiger Reservierungsstatus')
    if not re.fullmatch(r'[0-9a-f]{32}', str(reservierung_id or '')):
        raise ValueError('Ungueltige Reservierungskennung')
    with _reservierungssperre(root):
        for z in reservierungszeilen(root):
            if z.get('ereignis')=='geloest' and z.get('id')==reservierung_id:
                if z.get('status') != status:
                    raise ValueError('Widerspruechlicher zweiter Reservierungsabschluss')
                return z
        eintrag = {'id':reservierung_id,'ereignis':'geloest','zeit':b.now().isoformat(),'status':status}
        if kosten_lauf_id:
            eintrag['kosten_lauf_id']=str(kosten_lauf_id)[:64]
        _reservierung_schreiben(root, eintrag)
        return eintrag


def reservierungen_stand(root):
    """Sichtbarer Bericht (P08): offene, abgelaufen-ungeklaerte und geloeste Reservierungen.

    Eine Reservierung ohne Loesung bleibt sichtbar, auch nach Ablauf ihrer
    Frist - sie verschwindet nicht stillschweigend und zaehlt in
    _offene_reservierungen() weiterhin gegen den Deckel, bis sie aufgeloest ist.
    """
    zeilen = list(reservierungszeilen(root))
    geloest = {z['id']:z for z in zeilen if z.get('ereignis')=='geloest' and z.get('id')}
    jetzt = b.now()
    offen, abgelaufen_ungeklaert, geschlossen, gesehen = [], [], [], set()
    for z in zeilen:
        if z.get('ereignis') != 'reserviert' or not z.get('id') or z['id'] in gesehen:
            continue
        gesehen.add(z['id'])
        loesung = geloest.get(z['id'])
        if loesung is not None:
            geschlossen.append({**z, 'status':loesung.get('status'), 'geloest_zeit':loesung.get('zeit')})
            continue
        try:
            ist_abgelaufen = dt.datetime.fromisoformat(z['frist']) < jetzt
        except (KeyError, TypeError, ValueError):
            ist_abgelaufen = True
        (abgelaufen_ungeklaert if ist_abgelaufen else offen).append(z)
    summe = sum((Decimal(str(z['betrag_usd'])) for z in offen+abgelaufen_ungeklaert), Decimal(0))
    return {'offen':offen, 'abgelaufen_ungeklaert':abgelaufen_ungeklaert, 'geschlossen':geschlossen,
            'summe_offen_usd':str(summe),
            'hinweis':'Abgelaufen-ungeklaerte Reservierungen zaehlen weiterhin gegen den Deckel, bis sie '
                      'aufgeloest werden; sie verschwinden nicht und werden nicht doppelt verrechnet.'}


def rows(root):
    return jack_speicher.iter_records(ledger(root))


def append(root,row):
    p=ledger(root)
    flags=os.O_WRONLY|os.O_APPEND|os.O_CREAT|getattr(os,'O_NOFOLLOW',0)
    fd=os.open(p,flags,0o600)
    with os.fdopen(fd,'a') as f:
        fcntl.flock(f,fcntl.LOCK_EX)
        f.write(json.dumps(row,ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())


def begin(root,kind,provider,model, billing='api',ident=None,at=None,historical=False,teil_von=None,vorgang=None):
    """Ein Lauf ins Verbrauchsbuch.

    teil_von (Block 15, D1): Dieser Lauf ist TEIL eines groesseren Vorgangs -
    etwa eine einzelne Messaufgabe innerhalb eines Messtests. Sein GELD zaehlt
    voll mit (nichts geht am Geld vorbei), aber im Deckel auf die ZAHL der
    Laeufe zaehlt er nicht noch einmal: sonst waere ein Messtest mit 60
    Aufgaben nach 60 Aufgaben am Stundendeckel - und genau das ist am
    17.09.2026 passiert, Stufe 2 wurde nie gemessen.
    """
    if kind not in KINDS:raise ValueError('Unbekannte Ausfuehrungsart')
    row={'id':ident or uuid.uuid4().hex,'ereignis':'start','zeit':at or b.now().isoformat(),
         'art':kind,'anbieter':provider,'modell':model,'abrechnung':billing,'historisch':historical}
    if teil_von:row['teil_von']=str(teil_von)[:64]
    # F-9 (Paket 3): Vorgangskennung der Aussenaktion steht im Kostenbuch, BEVOR der Aufruf rausgeht.
    if vorgang:row['vorgang']=str(vorgang)[:40]
    # Arbeiter-Kosten gehoeren zu genau diesem Auftrag, auch bei Fehlversuchen.
    lauf = os.environ.get('JACK_AUFTRAG_RUN_ID', '')
    auftrag = os.environ.get('JACK_AUFTRAG_DATEI', '')
    if len(lauf) == 32 and all(c in '0123456789abcdef' for c in lauf) and auftrag.endswith('.md') and not any(c in auftrag for c in '/\\\r\n'):
        row['auftragslauf'] = lauf
        row['auftrag'] = auftrag[:220]
    append(root,row)
    return row


OBERGRENZE_TEXT=('geschaetzt: Kostenrahmen des Laufs als Obergrenze (Abbruch ohne gemeldeten Betrag, F-11 P02); '
                 'tatsaechlicher Betrag unbekannt, hoechstens dieser Wert')
# Arten mit Geldabrechnung, fuer die "kein Lauf ohne Betrag" gilt (Arbeiterlaeufe; F-11 P02).
BETRAGSPFLICHT_ARTEN=('arbeiter_api',)


def end(root,start,status='ok',verbrauch=None,usd=None,request_id=None,error=None,at=None,
        usd_estimated=None,price_source=None,usd_obergrenze=None):
    """usd_obergrenze (F-11, Paket 4, P02): Kostenrahmen eines Laufs, der abgebrochen wurde (Abbruch von aussen,
    Zeitgrenze, STOPP, kein Abschlussprotokoll). Meldet der Anbieter keinen Betrag und laesst sich aus dem
    Verbrauch nichts schaetzen, wird der Rahmen konservativ als usd_geschaetzt gebucht (betrag_art obergrenze).
    Kein bezahlter Lauf endet mehr ohne Betrag."""
    verbrauch_erfasst=usage(verbrauch)
    usd_gemeldet=amount(usd)
    # Block 31.3: gebucht wird nur, was Token > 0 hat. Am 20.09.2026 meldete
    # der Anbieter bei "Credit balance is too low" (0 Token) trotzdem einen
    # Betrag (~0.33 USD je Fehllauf) - end() uebernahm ihn bisher ungeprueft.
    # Ein gemeldeter Betrag OHNE jeden Token ist kein glaubwuerdiger Verbrauch:
    # 0,00 USD buchen, Status auf 'fehler', der verworfene Betrag bleibt zur
    # Nachvollziehbarkeit in usd_verworfen stehen.
    verworfen=None
    if sum(verbrauch_erfasst.values()) <= 0 and usd_gemeldet is not None:
        verworfen=usd_gemeldet
        usd_gemeldet='0.00'
        status='fehler'
    row={**start,'ereignis':'ende','ende':at or b.now().isoformat(),'status':status,
         'verbrauch':verbrauch_erfasst,'usd_gemeldet':usd_gemeldet}
    if verworfen is not None:
        row['usd_verworfen']=verworfen
        row['fehlerart']='kein_verbrauch_aber_betrag_gemeldet'
    # Block 10: Schaetzung daneben, nie statt des gemeldeten Betrags.
    if row['usd_gemeldet'] is None and usd_estimated is not None:
        geschaetzt,stand=amount(usd_estimated),str(price_source or '')[:500]
    else:
        geschaetzt,stand=schaetzung(root,start.get('modell'),verbrauch) if row['usd_gemeldet'] is None else (None, '')
    if geschaetzt is not None:
        row['usd_geschaetzt']=geschaetzt;row['preisstand']=stand
    elif row['usd_gemeldet'] is None and amount(usd_obergrenze) is not None:
        row['usd_geschaetzt']=amount(usd_obergrenze);row['betrag_art']='obergrenze'
        row['preisstand']=OBERGRENZE_TEXT
    if isinstance(request_id,str):row['anbieter_lauf']=request_id[:160]
    if error:row['fehlerart']=str(error)[:60]
    # A-7 T2 (24.09.2026): Tor-2-Dauer als Messwert - Dauer je Schritt eines Arbeiterlaufs.
    # Nie den Kostenabschluss gefaehrden: ein Fehler hier landet nur als Vermerk im Feld.
    if start.get('art') in DAUER_ARTEN and start.get('auftragslauf'):
        try:row['dauer_s']=schritt_dauern(root,start['auftragslauf'],start['zeit'],row['ende'])
        except Exception as fehler:row['dauer_s']={'fehler':type(fehler).__name__}
    path=ledger(root)
    fd=os.open(path,os.O_RDWR|os.O_APPEND|os.O_CREAT|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'a+') as f:
        fcntl.flock(f,fcntl.LOCK_EX);f.seek(0)
        for line in f:
            if not line.strip():continue
            old=json.loads(line)
            if old.get('id')==row['id'] and old.get('ereignis')=='ende':
                fields=('status','verbrauch','usd_gemeldet','anbieter_lauf','fehlerart')
                if row['usd_gemeldet'] is None:
                    fields += ('usd_geschaetzt',)
                if any(old.get(key)!=row.get(key) for key in fields):
                    raise ValueError('Widersprüchlicher zweiter Kostenabschluss')
                return old
        f.seek(0,2);f.write(json.dumps(row,ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())
    return row


def nachbuchen(root,ident,usd,grund,betrag_art='obergrenze',von='JACK',kennzeichen=None,ohne_ende=False,ersetzen=False):
    """F-11 (Paket 4, P02): Betrag fuer einen Lauf OHNE Betrag nachtragen - nur anhaengen, nie ueberschreiben.

    Die Ende-Zeile bleibt unveraendert. Angehaengt wird eine Zeile ereignis 'nachbuchung' mit derselben id,
    allen Feldern der Ende-Zeile und usd_geschaetzt (Kennzeichen betrag_art/kennzeichen, preisstand = Grund).
    Leser, die je id die letzte Nicht-Start-Zeile nehmen (Tagesdeckel, Guthaben, Auftragskosten), sehen den Betrag.
    F-12: ohne_ende=True bucht einen Start OHNE Ende-Zeile nach (status 'ohne_ende'); ersetzen=True haengt eine
    NEUE Nachbuchung an eine bestehende an (z. B. geaendertes Kennzeichen) - die alte Zeile bleibt stehen, die
    neue gilt (letzte Zeile je id). Verweigert: Lauf unbekannt, Betrag schon gemeldet/geschaetzt, doppelte
    Nachbuchung ohne ersetzen, kein gueltiger Betrag."""
    wert=amount(usd)
    if wert is None:raise ValueError('Nachbuchung braucht einen gueltigen Betrag')
    if betrag_art not in BETRAGSARTEN:raise ValueError('Unbekannte Betragsart')
    if not isinstance(grund,str) or len(grund.strip())<10:raise ValueError('Nachbuchung braucht einen Grund')
    path=ledger(root)
    fd=os.open(path,os.O_RDWR|os.O_APPEND|os.O_CREAT|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'a+') as f:
        fcntl.flock(f,fcntl.LOCK_EX);f.seek(0)
        start=ende=nach=None
        for line in f:
            if not line.strip():continue
            old=json.loads(line)
            if old.get('id')!=ident:continue
            if old.get('ereignis')=='nachbuchung':nach=old
            elif old.get('ereignis')=='ende':ende=old
            elif old.get('ereignis')=='start':start=old
        if nach is not None and not ersetzen:raise ValueError('Dieser Lauf wurde bereits nachgebucht')
        if ersetzen and nach is None:raise ValueError('Ersetzen nur fuer eine bestehende Nachbuchung')
        if ende is None:
            if not ohne_ende or start is None:raise ValueError('Lauf ohne Ende-Zeile; nur mit ohne_ende=True nachzubuchen')
            basis={**start,'status':'ohne_ende','verbrauch':{},'usd_gemeldet':None}
        else:
            basis=ende
        if basis.get('usd_gemeldet') is not None or basis.get('usd_geschaetzt') is not None:
            raise ValueError('Lauf hat bereits einen Betrag')
        row={**basis,'ereignis':'nachbuchung','nachbuchung_zeit':b.now().isoformat(),'usd_geschaetzt':wert,
             'betrag_art':betrag_art,'preisstand':str(grund).strip()[:400],'nachgebucht_von':str(von)[:80]}
        if kennzeichen:row['kennzeichen']=str(kennzeichen)[:120]
        if nach is not None:row['ersetzt_nachbuchung_vom']=nach.get('nachbuchung_zeit')
        f.seek(0,2);f.write(json.dumps(row,ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())
    return row


BETRAGSARTEN=('obergrenze','null_belegt','lokal','abgewiesen','sammelzeile')


def laeufe_ohne_betrag(root,arten=None):
    """Waechter (F-11 P02, F-12 erweitert): nicht historische Laeufe ohne jeden Betrag (weder gemeldet noch
    geschaetzt noch nachgebucht). arten=None: jede Zeile mit Geldabrechnung 'api' und JEDER Start ohne Ende
    (gleich welche Abrechnung). Leer = keine Kostenluecke."""
    byid={}
    for row in rows(root):
        ident=row.get('id')
        if not ident:continue
        if row.get('ereignis')=='start':byid.setdefault(ident,row)
        else:byid[ident]=row
    raus=[]
    for r in byid.values():
        if r.get('historisch') or (arten is not None and r.get('art') not in arten):continue
        if r.get('ereignis')=='start':
            raus.append({'id':r['id'],'zeit':r.get('zeit'),'art':r.get('art'),'fehlt':'Ende-Zeile','auftrag':r.get('auftrag')})
            continue
        if r.get('abrechnung')!='api':continue
        if r.get('usd_gemeldet') is None and r.get('usd_geschaetzt') is None:
            geschaetzt,_=schaetzung(root,r.get('modell'),r.get('verbrauch'))
            if geschaetzt is None:
                raus.append({'id':r['id'],'zeit':r.get('zeit'),'art':r.get('art'),'fehlt':'Betrag',
                             'status':r.get('status'),'fehlerart':r.get('fehlerart'),'auftrag':r.get('auftrag')})
    return raus


DAUER_ARTEN=('arbeiter_api','arbeiter_abo','arbeiter_ruflo')
ZUGRIFFE='arbeiter_zugriffe.jsonl'
ROLLEN={'jack-fachkraft':'fachkraft','jack-fachkraft-stark':'fachkraft','jack-pruefer':'pruefer'}


def _zeitpunkt(wert):
    try:
        z=dt.datetime.fromisoformat(str(wert))
    except ValueError:
        return None
    return z if z.tzinfo else z.replace(tzinfo=b.ZONE)


def schritt_dauern(root,lauf_id,beginn,ende):
    """A-7 T2: Sekunden je Schritt (Fachkraft, Pruefer, CEO) eines Auftragslaufs.

    Quelle ist das Werkzeugprotokoll des Pfadwaechters (arbeiter_zugriffe.jsonl), dieselbe Datei,
    aus der das Tor-2-Gate die Rollen liest. Ein Unteragent laeuft von seiner Delegation (Agent-
    Aufruf des CEO mit agent_typ) bis zum naechsten eigenen Schritt des CEO danach, hoechstens bis
    Laufende; die Zuordnung Delegation -> agent_id folgt der Reihenfolge. CEO = Gesamt minus
    Unteragenten. Nur Werkzeugzeitpunkte sind belegt; reines Nachdenken ohne Werkzeug zaehlt zum
    umgebenden Schritt."""
    t0,t1=_zeitpunkt(beginn),_zeitpunkt(ende)
    if t0 is None or t1 is None:raise ValueError('Laufbeginn oder -ende unlesbar')
    zeilen=[]
    pfad=Path(root)/ZUGRIFFE
    if pfad.is_file():
        with pfad.open(encoding='utf-8',errors='replace') as f:
            for line in f:
                if lauf_id not in line:continue
                try:r=json.loads(line)
                except ValueError:continue
                z=_zeitpunkt(r.get('zeit'))
                if r.get('lauf_id')==lauf_id and z is not None:zeilen.append((z,r))
    zeilen.sort(key=lambda x:x[0])
    offen,rolle_von,fenster=[],{},{}
    for z,r in zeilen:
        aid=r.get('agent_id')
        if not aid:
            if r.get('tool')=='Agent' and r.get('entscheidung')=='allow':
                offen.append((z,ROLLEN.get(r.get('agent_typ'),'unbekannt')))
            continue
        if aid not in rolle_von:
            beginn_a,rolle=offen.pop(0) if offen else (z,'unbekannt')
            rolle_von[aid]=rolle;fenster[aid]=[beginn_a,z]
        fenster[aid][1]=z
    ceo=[z for z,r in zeilen if not r.get('agent_id')]
    schritte={}
    for aid,(s,e) in fenster.items():
        bis=min(next((z for z in ceo if z>e),t1),t1)
        schritte[rolle_von[aid]]=schritte.get(rolle_von[aid],0.0)+max(0.0,(bis-s).total_seconds())
    gesamt=max(0.0,(t1-t0).total_seconds())
    ergebnis={'gesamt':round(gesamt,1),'fachkraft':round(schritte.get('fachkraft',0.0),1),
              'pruefer':round(schritte.get('pruefer',0.0),1),
              'ceo':round(max(0.0,gesamt-sum(schritte.values())),1),'werkzeugzeilen':len(zeilen)}
    if 'unbekannt' in schritte:ergebnis['unbekannt']=round(schritte['unbekannt'],1)
    return ergebnis


def dauer_wochenbericht(root,tage=7,jetzt=None):
    """A-7 T2: Median der Schrittdauern der letzten Tage aus dem Kostenbuch (Feld dauer_s).
    Ein Schritt zaehlt nur in Laeufen, in denen er vorkam (Dauer > 0)."""
    import statistics
    jetzt=jetzt or b.now()
    ab=jetzt-dt.timedelta(days=tage)
    laeufe=[]
    for r in rows(root):
        d=r.get('dauer_s')
        z=_zeitpunkt(r.get('zeit'))
        if r.get('ereignis')=='ende' and isinstance(d,dict) and 'gesamt' in d and z is not None and z>=ab:
            laeufe.append(r)
    schritte={}
    for name in ('fachkraft','pruefer','ceo','gesamt'):
        werte=[float(r['dauer_s'].get(name) or 0) for r in laeufe]
        werte=[w for w in werte if w>0]
        schritte[name]={'laeufe':len(werte),'median_s':round(statistics.median(werte),1) if werte else None,
                        'max_s':round(max(werte),1) if werte else None}
    text=['# Wochenbericht Schrittdauer (Tor-2-Dauer)','',
          'Zeitraum: %s bis %s · Läufe mit Messwert: %d' % (ab.strftime('%d.%m.%Y %H:%M'),jetzt.strftime('%d.%m.%Y %H:%M'),len(laeufe)),'',
          '| Schritt | Läufe | Median (s) | Maximum (s) |','|---|---|---|---|']
    for name,titel in (('fachkraft','Fachkraft'),('ceo','CEO'),('pruefer','Prüfer (Tor 2)'),('gesamt','Gesamt')):
        s=schritte[name]
        text.append('| %s | %d | %s | %s |' % (titel,s['laeufe'],'—' if s['median_s'] is None else s['median_s'],
                                               '—' if s['max_s'] is None else s['max_s']))
    text+=['','Quelle: betrieb/kostenlaeufe.jsonl, Feld dauer_s (seit 24.09.2026, A-7). Ältere Läufe haben kein Feld.']
    return {'tage':tage,'laeufe':len(laeufe),'schritte':schritte,'text':'\n'.join(text)+'\n'}


@contextmanager
def track(root,kind,provider,model,billing='api',teil_von=None):
    start=begin(root,kind,provider,model,billing,teil_von=teil_von);data={}
    try:yield data
    except BaseException as error:
        data.pop('status',None)
        end(root,start,'fehler',**data,error=type(error).__name__);raise
    else:end(root,start,**data)


def import_history(root):
    marker=b.area(root)/'kosten_erfassung.json'
    if marker.exists():return 0
    existing={r['id']:r for r in rows(root)};count=0
    def save(source,index,row,kind,provider,model,u,cost=None,billing='api',failed=False):
        nonlocal count
        ident='alt-'+hashlib.sha256((source+':'+str(index)+json.dumps(row,sort_keys=True)).encode()).hexdigest()[:24]
        if existing.get(ident,{}).get('ereignis')=='ende':return
        at=row.get('zeit') or b.now().isoformat()
        start=existing.get(ident) or begin(root,kind,provider,model,billing,ident,at,True)
        existing[ident]=end(root,start,'fehler' if failed else 'ok',u,cost,at=at);count+=1
    for name in ['arbeiter_api_laeufe.jsonl','betrieb/modelllaeufe.jsonl','betrieb/ratslaeufe.jsonl','betrieb/codex-laeufe.jsonl']:
        for i,row in enumerate(b.records(Path(root)/name)):
            if name=='arbeiter_api_laeufe.jsonl':
                save(name,i,row,'arbeiter_api','anthropic','mehrere Modelle',row.get('usage'),row.get('total_cost_usd'),failed=bool(row.get('is_error')))
            elif name=='betrieb/modelllaeufe.jsonl':
                save(name,i,row,'fachentwurf',row.get('anbieter'),row.get('modell'),row.get('verbrauch'))
            elif name=='betrieb/ratslaeufe.jsonl':
                for n,item in enumerate(row.get('stimmen',[])+[row.get('pruefung',{})]):
                    save(name,str(i)+'-'+str(n),{**item,'zeit':row['zeit']},'rat',item.get('anbieter'),item.get('modell'),item.get('verbrauch'))
            else:save(name,i,row,'codex','openai','nicht gemeldet',row.get('verbrauch'),billing='codex_zugang')
    with marker.open('x') as f:json.dump({'aktiv_seit':b.now().isoformat(),'historie_unvollstaendig':True},f)
    return count


def summary(root):
    try:
        raw=rows(root);byid={}
        for row in raw:
            ident=row['id']
            if row.get('ereignis')=='start':byid.setdefault(ident,row)
            elif row.get('ereignis') in ('ende','nachbuchung'):byid[ident]=row  # F-11: Nachbuchung traegt den Betrag
        entries=list(byid.values());groups=[];today=str(b.now().date())
        def estimate(row):
            if row.get('usd_gemeldet') is not None or row.get('abrechnung') != 'api':
                return None
            value = row.get('usd_geschaetzt')
            if value is None:
                value, _ = schaetzung(root, row.get('modell'), row.get('verbrauch'))
            return amount(value)
        estimates = {r['id']: estimate(r) for r in entries}
        for kind,label in KINDS.items():
            selected=[r for r in entries if r['art']==kind]
            def total(items):return str(sum((Decimal(r['usd_gemeldet']) for r in items if r.get('usd_gemeldet') is not None),Decimal(0)))
            measured=[r for r in selected if r.get('usd_gemeldet') is not None]
            estimated=[estimates[r['id']] for r in selected if estimates[r['id']] is not None]
            groups.append({'art':kind,'name':label,'laeufe':len(selected),'heute':sum(jack_speicher.day(r['zeit'])==today for r in selected),
                           'usd_gemeldet':total(selected) if measured else None,
                           'usd_geschaetzt':str(sum(map(Decimal, estimated), Decimal(0))) if estimated else None,
                           'geschaetzte_laeufe':len(estimated),
                           'ohne_betrag':len(selected)-len(measured)-len(estimated),'offen':sum(r['ereignis']=='start' for r in selected),
                           'fehler':sum(r.get('status')=='fehler' for r in selected),
                           'verbrauch':usage([r.get('verbrauch') for r in selected])})
        known=[r for r in entries if r.get('usd_gemeldet') is not None]
        total=str(sum((Decimal(r['usd_gemeldet']) for r in known),Decimal(0))) if known else None
        estimated = [v for v in estimates.values() if v is not None]
        estimated_total = str(sum(map(Decimal, estimated), Decimal(0))) if estimated else None
        marker=b.area(root)/'kosten_erfassung.json'
        since=json.loads(marker.read_text())['aktiv_seit'] if marker.exists() else min((r['zeit'] for r in entries if not r.get('historisch')),default=None)
        text='Kostenübersicht: '+(total+' USD gemeldet' if total is not None else 'Noch kein Geldbetrag gemeldet')+'. Keine vollständige Rechnung.\n'
        text+='\n'.join(g['name']+': '+str(g['laeufe'])+' Läufe; '+(g['usd_gemeldet']+' USD gemeldet' if g['usd_gemeldet'] is not None else 'Geldbetrag unbekannt')+'; '+str(g['ohne_betrag'])+' ohne Geldbetrag.' for g in groups)
        text+='\nZusaetzliche geschaetzte Teilbetraege: '+(estimated_total+' USD' if estimated_total is not None else 'keine belegbare Schaetzung')+'. Fehlende Betraege sind nicht null. Abo-Gebuehren und andere Anwendungen sind nicht enthalten. Auftragsbudgets und Tagesgrenzen stehen im Kostenwaechter.'
        return {'status':'ok','zeit':b.now().isoformat(),'erfassung_seit':since,'usd_gemeldet':total,'laeufe_mit_betrag':len(known),'laeufe_ohne_betrag':len(entries)-len(known),
                'usd_geschaetzt':estimated_total,'laeufe_mit_schaetzung':len(estimated),
                'laeufe_ohne_betrag_und_schaetzung':len(entries)-len(known)-len(estimated),
                'gruppen':groups,'gesamtbudget_usd':None,'vollstaendige_rechnung':False,'text':text}
    except (OSError,ValueError,KeyError,TypeError):
        return {'status':'fehler','usd_gemeldet':None,'text':'Verbrauchsbuch nicht zuverlässig lesbar. Keine belastbare Summe verfügbar.'}


if __name__=='__main__':
    root=Path(__file__).resolve().parent
    if sys.argv[1]=='start-abo':
        start=begin(root,'arbeiter_abo','anthropic',sys.argv[2],'claude_abo');print(start['id'])
    elif sys.argv[1]=='ende-abo':
        start=next(r for r in rows(root) if r['id']==sys.argv[2] and r['ereignis']=='start')
        end(root,start,'ok' if sys.argv[3]=='0' else 'fehler')
    elif sys.argv[1]=='wochenbericht-dauern':
        bericht=dauer_wochenbericht(root)
        if len(sys.argv)>2:Path(sys.argv[2]).write_text(bericht['text'],encoding='utf-8')
        print(bericht['text'])
    else:print(json.dumps(summary(root),ensure_ascii=False))
