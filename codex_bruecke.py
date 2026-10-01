"""Vorhandenes Codex fuer einen begrenzten Leseauftrag starten; keine Installation."""
from pathlib import Path
import json
import os
import signal
import subprocess
import jack_betrieb as betrieb
import jack_kosten

CODEX=Path('/Applications/ChatGPT.app/Contents/Resources/codex')   # alter Standardort (existiert auf diesem Mac nicht)


def codex_pfad(root=None):
    """F-97: wo liegt die Codex-CLI wirklich? Nur LESEN und finden, nichts installieren.
    Reihenfolge: betrieb/codex_pfad.txt (vom Patron/Kern gesetzt), Umgebungsvariable JACK_CODEX, alter Standardort, PATH,
    ein bereits vorhandenes npm-Paket unter ~/Documents/Codex/*/... Rueckgabe Path oder None."""
    kandidaten=[]
    try:
        if root is not None:
            datei=betrieb.area(root)/'codex_pfad.txt'
            if datei.is_file():kandidaten.append(Path(datei.read_text().strip()))
    except OSError:pass
    if os.environ.get('JACK_CODEX'):kandidaten.append(Path(os.environ['JACK_CODEX']))
    kandidaten.append(CODEX)
    import shutil as _sh
    if _sh.which('codex'):kandidaten.append(Path(_sh.which('codex')))
    try:
        kandidaten+=sorted(Path.home().glob('Documents/Codex/*/*/work/*/lab/*/node_modules/@openai/codex-darwin-arm64/vendor/*/bin/codex'))
    except OSError:pass
    for k in kandidaten:
        try:
            if k.is_file() and os.access(k,os.X_OK):return k
        except OSError:continue
    return None


def review(root,question):
    codex=codex_pfad(root)
    if codex is None:raise ValueError('Codex ist nicht installiert')
    if not isinstance(question,str) or not question.strip() or len(question)>10000:raise ValueError('Pruefauftrag fehlt oder ist zu lang')
    folder=betrieb.area(root)/'codex';folder.mkdir(exist_ok=True)
    output=betrieb.draft_path(root,'codex-pruefung','.md')
    prompt='Fuehre keine Werkzeuge aus. Pruefe ausschliesslich den folgenden Text, auf Deutsch, maximal 200 Woerter. Keine Dateiaenderungen, kein Senden, keine Installation. Benenne ein Problem mit Loesung und kennzeichne Unsicherheit.\n\n'+question
    args=[str(codex),'exec','--sandbox','read-only','--ignore-user-config','--ephemeral','--skip-git-repo-check','-C',str(folder),'-c','approval_policy="never"','--json','-']
    env={k:v for k,v in os.environ.items() if not k.startswith(('ANTHROPIC_','ELEVENLABS_','MOONSHOT_'))}
    with jack_kosten.track(root,"codex","openai","Codex-Standard",billing="codex_zugang") as cost:
        process=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env,start_new_session=True)
        try:
            out,err=process.communicate(prompt,timeout=120)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGTERM)
            try:out,err=process.communicate(timeout=5)
            except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);out,err=process.communicate()
            partial=[]
            for line in out.splitlines():
                try:
                    event=json.loads(line)
                    if event.get('type')=='turn.completed':partial.append(event.get('usage'))
                except ValueError:pass
            cost.update(verbrauch=partial)
            raise ValueError('Codex-Pruefung nach zwei Minuten beendet')
        events=[]
        for line in out.splitlines():
            try:events.append(json.loads(line))
            except ValueError:pass
        cost.update(verbrauch=[e.get("usage") for e in events if e.get("type")=="turn.completed"])
        texts=[e.get('item',{}).get('text','') for e in events if e.get('type')=='item.completed' and e.get('item',{}).get('type')=='agent_message']
        if process.returncode or not texts:raise ValueError('Codex lieferte keinen gueltigen Abschluss; Anmeldung oder Limit pruefen')
        output.write_text(texts[-1])
        record={'zeit':betrieb.now().isoformat(),'datei':str(output),'sandbox':'read-only','verbrauch':[e.get('usage') for e in events if e.get('type')=='turn.completed']}
        betrieb.append(betrieb.area(root)/'codex-laeufe.jsonl',record)
        return {**record,'antwort':texts[-1]}
