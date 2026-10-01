"""Belegte wiederkehrende Fehler als kurze, sichere Arbeitshinweise.

Liest nur strukturierte lokale Hook-Ereignisse. Rohtexte aus Dateien oder
Webseiten werden nie zu Regeln. Hinweise aendern weder Rechte noch Budgets.
"""
from collections import Counter
import datetime as dt
import json
from pathlib import Path
import re
import sys
import fcntl
import os

REGELN = (
    ('pflichtpunkte', ('Pflichtpunkt', 'Pflichtpunkte'),
     'Vor Tor 2 jeden verbindlichen Pflichtpunkt mit vorhandenem Ergebnisbeleg abschliessen; fehlende Punkte offen lassen.'),
    ('ergebnisstand', ('Ergebnisstand stimmt nicht', 'seit der technischen Pruefung veraendert'),
     'Nach der Pruefung keine Ergebnisdatei austauschen. Aenderungen brauchen einen neuen unabhaengigen Pruefbeleg.'),
    ('sicherung', ('Sicherung konnte nicht', 'keine Dateiaenderung', 'Datei hat sich waehrend der Sicherung'),
     'Bei fehlgeschlagener Sicherung nicht erneut blind schreiben; Dateizustand klaeren und den bestehenden Inhalt bewahren.'),
    ('belegpfad', ('Beleg liegt ausserhalb', 'Belegpfad darf keinen Verweis', 'Schluesseldatei ist kein'),
     'Nur kanonische Ergebnisdateien innerhalb der Holding als Beleg verwenden; keine Verweise oder Schluesseldateien.'),
)


def sammeln(root, name, an=None):
    import jack_auftrag
    current=jack_auftrag.lesen(root,name)
    if current is None:return []
    contract=current[0];at=an or dt.datetime.now().astimezone();counts=Counter();sources={};seen=set();orders={}
    def records():
        for relative in ('arbeiter_zugriffe.jsonl','betrieb/lernsignale.jsonl'):
            log=Path(root)/relative
            if not log.is_file():continue
            with log.open(encoding='utf-8',errors='replace') as stream:
                for nr,line in enumerate(stream,1):yield relative,nr,line
    for relative,nr,line in records():
            try:
                rec=json.loads(line)
                if not isinstance(rec,dict):continue
                if rec.get('entscheidung')!='deny' or not re.fullmatch(r'[0-9a-f]{32}',str(rec.get('lauf_id',''))):continue
                stamp=dt.datetime.fromisoformat(rec.get('zeit',''))
                if stamp.tzinfo is None:stamp=stamp.replace(tzinfo=at.tzinfo)
                if not 0 <= (at-stamp).total_seconds() <= 30*86400:continue
                other=rec.get('auftrag','')
                if other not in orders:orders[other]=jack_auftrag.lesen(root,other)
                origin=orders[other]
                if not origin or origin[0]['ablauf']!=contract['ablauf'] or origin[0]['marke']!=contract['marke']:continue
                for key,tokens,advice in REGELN:
                    if not any(token in str(rec.get('grund','')) for token in tokens):continue
                    ident=(rec['lauf_id'],key)
                    if ident in seen:continue
                    seen.add(ident);counts[key]+=1;sources[key]=relative+':'+str(nr)
            except (OSError,ValueError,TypeError,KeyError):continue
    hints={key:advice for key,_,advice in REGELN}
    return [{'fehlerart':key,'betroffene_laeufe':number,'hinweis':hints[key],'quelle':sources[key]}
            for key,number in counts.most_common(3)]


def kontext(root,name):
    """F-20 (Paket 6, PM-Entscheidung 1): Hinweise NUR aus der freigegebenen Regelliste betrieb/lernregeln.json.
    Neuer Vertrag: die dort gebundenen Lernhinweise (auch leer). Altvertrag ohne Feld: dieselbe Regelliste live.
    sammeln() bleibt als Altfunktion bestehen, speist aber keinen Lauf mehr."""
    import jack_auftrag,jack_lernen
    current=jack_auftrag.lesen(root,name)
    if current is None:return 'Keine Lernhinweise (Auftrag ohne geschuetzten Vertrag).'
    vertrag=current[0]
    if 'lernhinweise' in vertrag:
        liste,quelle=vertrag['lernhinweise'],'im Vertrag gebunden, Abschnitt Lernhinweise'
    else:
        try:jack_lernen.katalog_aktualisieren(root)
        except (OSError,ValueError):pass
        liste,quelle=jack_lernen.hinweise(root,vertrag['marke'],vertrag['ablauf'])['hinweise'],'Regelliste (Altvertrag)'
    if not liste:return 'Keine Lernhinweise: keine freigegebene Regel ist fuer diese Marke und diesen Ablauf belegt.'
    return '\n'.join('- %s (Regel %s, %d belegte Laeufe; %s): %s'%(h.get('kennung','L%d'%i),h['regel'],h['n'],quelle,h['hinweis'])
                     for i,h in enumerate(liste,1))


def merken(root,name,grund,lauf_id):
    import jack_auftrag
    if not re.fullmatch(r'[0-9a-f]{32}',str(lauf_id)) or jack_auftrag.lesen(root,name) is None:return
    # Nur bekannte technische Fehlermuster; niemals fremde Anweisungen speichern.
    for key,tokens,_ in REGELN:
        if not any(t in grund for t in tokens):continue
        row={'zeit':dt.datetime.now().astimezone().isoformat(),'auftrag':name,'lauf_id':lauf_id,
             'entscheidung':'deny','grund':tokens[0],'fehlerart':key,'quelle':'Abschlusspruefung'}
        p=Path(root)/'betrieb/lernsignale.jsonl';p.parent.mkdir(exist_ok=True)
        with p.open('a',encoding='utf-8') as f:
            fcntl.flock(f,fcntl.LOCK_EX);f.write(json.dumps(row,ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())


if __name__=='__main__':
    sys.path.insert(0,str(Path(__file__).resolve().parent))
    if len(sys.argv)==4 and sys.argv[1]=='--fehler':
        merken(Path(__file__).resolve().parent,sys.argv[2],sys.argv[3],os.environ.get('JACK_AUFTRAG_RUN_ID',''))
        raise SystemExit(0)
    if len(sys.argv)!=2:raise SystemExit('Ein Auftragsdateiname ist erforderlich')
    try:print(kontext(Path(__file__).resolve().parent,sys.argv[1]))
    except (OSError,ValueError,KeyError):print('Erfahrungsbelege derzeit nicht lesbar; keine neue Regel abgeleitet.')
