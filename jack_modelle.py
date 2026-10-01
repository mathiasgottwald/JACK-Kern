"""Eine validierte Modellauswahl fuer JACK, Fachentwurf, Rat und Arbeiter."""
import copy
import hashlib
import json
from pathlib import Path
import re
import sys

# Seit 16.09.2026 (Block 2) sind neben den drei Grundrollen auch die
# Abteilungsrollen startbar. Jede zeigt weiterhin auf die gemeinsame
# Modellauswahl; einzelne Modelle je Rolle bleiben ausgeschlossen.
ROLES={'jack-fachkraft':'fachkraft','jack-pruefer':'ceo_und_pruefer','jack-fachkraft-stark':'ceo_und_pruefer',
       'daten-fachkraft':'fachkraft','inhalt-fachkraft':'fachkraft',
       'marketing-fachkraft':'fachkraft','vertrieb-fachkraft':'fachkraft',
       'technik-fachkraft':'fachkraft','abnahme-pruefer':'ceo_und_pruefer',
       # 17.09.2026: Abteilung 30_Recht. Rechtliche Einordnung ist nach
       # betrieb/kostenstufen.json Stufe 2 - deshalb ceo_und_pruefer, nicht
       # fachkraft. Schreibrecht bleibt, die Rolle ist kein Pruefer.
       'recht-fachkraft':'ceo_und_pruefer'}
# Rollen ohne Schreibrecht - die Pruefer. Sie duerfen nie dieselbe Rolle sein
# wie die ausfuehrende Fachkraft.
NUR_LESEN=frozenset({'jack-pruefer','abnahme-pruefer'})
# Block 30 (20.09.2026): EINE Ausnahme, und sie macht den Pruefer nicht
# schreibend am Ergebnis. jack-pruefer braucht "Write", weil er seinen
# TOR-2-ZETTEL selbst anlegen muss - das Urteil ueber einen Lauf darf nicht
# durch die Hand dessen gehen, ueber den geurteilt wird. Alles andere bleibt
# ihm verwehrt: "Edit" hat er nicht, er kann also keine bestehende Datei
# aendern, und der Pfadwaechter in arbeiter.sh laesst ihn mit "Write" nur in
# abnahme/tor2/ und nur ein einziges Mal je Zettel. Die Abnahme prueft
# zusaetzlich nach: hat der Zettelschreiber sonst irgendwo geschrieben, gilt
# er als befangen und der Lauf faellt durch.
ZETTELSCHREIBER=frozenset({'jack-pruefer'})

def load(root):
    path=Path(root)/'modellwahl.json'
    if path.is_symlink():raise ValueError('Modellkonfiguration darf kein Verweis sein')
    data=json.loads(path.read_text())
    for role in ('fachkraft','ceo_und_pruefer'):
        if not isinstance(data.get(role),str) or not re.fullmatch(r'claude-[a-z0-9-]{3,90}',data[role]):
            raise ValueError('Ungueltiges Modell fuer '+role)
    # Eigene Rolle nur fuer den gesprochenen Dialog (Freigabe des Patrons, 16.09.2026).
    # Fehlt sie, gilt weiter ceo_und_pruefer - alte Konfigurationen bleiben gueltig.
    data.setdefault('dialog',data['ceo_und_pruefer'])
    if not re.fullmatch(r'claude-[a-z0-9-]{3,90}',data['dialog']):
        raise ValueError('Ungueltiges Modell fuer dialog')
    k=data.get('kimi')
    if not isinstance(k,dict) or any(type(k.get(x)) is not bool for x in ('aktiv','datenfreigabe')):
        raise ValueError('Kimi-Freigaben fehlen oder sind ungueltig')
    if not isinstance(k.get('modell'),str) or not re.fullmatch(r'kimi-[a-z0-9.-]{2,60}',k['modell']):
        raise ValueError('Ungueltige Kimi-Modellkennung')
    if k['aktiv'] and not k['datenfreigabe']:raise ValueError('Kimi ohne Datenfreigabe gesperrt')
    # Groq (Einbau 23.09.2026): fehlt der Block, gilt er als abgeschaltet. Es gibt genau ein freigegebenes Modell.
    g=data.setdefault('groq',{'aktiv':False,'datenfreigabe':False,'modell':'openai/gpt-oss-120b','tarif':'free'})
    if not isinstance(g,dict) or any(type(g.get(x)) is not bool for x in ('aktiv','datenfreigabe')):
        raise ValueError('Groq-Freigaben fehlen oder sind ungueltig')
    if g.get('modell')!='openai/gpt-oss-120b':
        raise ValueError('Ungueltige Groq-Modellkennung')
    if g['aktiv'] and not g['datenfreigabe']:raise ValueError('Groq ohne Datenfreigabe gesperrt')
    return data


def agents(root, config=None):
    config=config or load(root)
    path=Path(root)/'arbeiter_agenten.json'
    if path.is_symlink():raise ValueError('Agentenkonfiguration darf kein Verweis sein')
    result=json.loads(path.read_text())
    if set(result)!=set(ROLES):raise ValueError('Feste Arbeiterrollen stimmen nicht')
    for name,role in ROLES.items():
        entry=result[name]
        if entry.pop('model_role',None)!=role or 'model' in entry:
            raise ValueError('Arbeiterrolle muss auf die gemeinsame Modellauswahl verweisen')
        if name in ZETTELSCHREIBER:
            expected=['Read','Glob','Grep','Write']
        elif name in NUR_LESEN:
            expected=['Read','Glob','Grep']
        else:
            expected=['Read','Write','Edit','Glob','Grep']
        if entry.get('tools')!=expected or entry.get('permissionMode')!='acceptEdits':
            raise ValueError('Werkzeuggrenzen der festen Rolle stimmen nicht')
        entry['model']=config[role]
    return result


def status(root):
    try:
        c=load(root);a=agents(root,c)
        return {'status':'geprueft','ceo':c['ceo_und_pruefer'],'fachkraft':c['fachkraft'],
                'dialog':c['dialog'],'rollen':sorted(a),'rollen_anzahl':len(a),
                'pruefer':a['jack-pruefer']['model'],'kimi_aktiv':c['kimi']['aktiv'],'groq_aktiv':c['groq']['aktiv'],
                'konfiguration_sha256':hashlib.sha256(json.dumps(c,sort_keys=True).encode()).hexdigest()}
    except (OSError,ValueError,KeyError,TypeError):
        return {'status':'fehler','text':'Modellkonfiguration ungueltig; keine neue Modellarbeit starten.'}


if __name__=='__main__':
    root=Path(__file__).resolve().parent
    try:
        config=load(root);resolved=agents(root,config)
        if len(sys.argv)>1 and sys.argv[1]=='arbeiter':
            print(config['ceo_und_pruefer']);print(config['fachkraft']);print(json.dumps(resolved,ensure_ascii=False))
        else:print(json.dumps(status(root),ensure_ascii=False))
    except Exception:
        print('Modellkonfiguration ungueltig',file=sys.stderr);raise SystemExit(1)
