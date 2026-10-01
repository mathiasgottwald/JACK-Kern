#!/usr/bin/env python3
"""Expliziter API-Lauf mit vorhandenem JACK-Schluessel und begrenztem Budget.

Rueckgabewerte:
  0  Lauf erfolgreich
  1  Lauf fachlich fehlgeschlagen - KEIN Rueckfall, der Auftrag hat ein Problem
  3  API NICHT ERREICHBAR - der Arbeiter faellt auf das Abo zurueck (Entscheidung
     des Patrons vom 16.09.2026: das Abo bleibt Rueckfall)

--hilfe zeigt die drei Budgetstufen und macht KEINEN Anthropic-Aufruf (Block 24,
17.09.2026, Pruefpunkt P4).
"""
import datetime
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
import jack_modelle
import jack_kosten
import jack_grenzen

# Block 24 (17.09.2026), Teil E: Budget und Aufwand richten sich nach dem
# Kopffeld "tiefe" des Auftrags, nicht mehr nach einer festen Zahl im Code.
# Die massgeblichen Werte liegen in betrieb/betriebsgrenzen.json unter
# "api_lauf_je_tiefe" - diese Konstante ist nur der Rueckfall, falls die Datei
# fehlt oder den Schluessel noch nicht kennt.
STANDARD_STUFEN = {
    "klein": {"budget_usd": 0.75, "aufwand": "low"},
    "mittel": {"budget_usd": 2.00, "aufwand": "medium"},
    "gross": {"budget_usd": 4.00, "aufwand": "high"},
}


def stufen_laden():
    pfad = ROOT / "betrieb" / "betriebsgrenzen.json"
    try:
        grenzen = json.loads(pfad.read_text(encoding="utf-8"))
        stufen = grenzen.get("api_lauf_je_tiefe")
        if isinstance(stufen, dict) and all(t in stufen for t in STANDARD_STUFEN):
            return stufen
    except (OSError, ValueError):
        pass
    return STANDARD_STUFEN


def hilfe_ausgabe():
    stufen = stufen_laden()
    print("API-Lauf-Budgetstufen (betrieb/betriebsgrenzen.json -> api_lauf_je_tiefe):")
    for tiefe in ("klein", "mittel", "gross"):
        stufe = stufen.get(tiefe, STANDARD_STUFEN[tiefe])
        print(f"  {tiefe}: {stufe.get('budget_usd')} USD, Aufwand {stufe.get('aufwand')}")


class AbbruchVonAussen(Exception):
    """F-9 (Paket 3): SIGTERM/SIGHUP an den Arbeiterlauf (Patron-STOPP, Unterbrechung, Dienst-Neustart)."""


def _abbruch_signal(nummer, _rahmen):
    raise AbbruchVonAussen(signal.Signals(nummer).name)


def api_key():
    """Zugang ausschliesslich aus dem macOS-Schluesselbund."""
    import jack_tresor
    return jack_tresor.lesen('ANTHROPIC_API_KEY')


def main():
    args = sys.argv[1:]
    if '--hilfe' in args:
        hilfe_ausgabe()
        return 0

    tiefe = 'klein'
    if '--tiefe' in args:
        index = args.index('--tiefe')
        if index + 1 >= len(args):
            raise ValueError('--tiefe braucht einen Wert')
        tiefe = args[index + 1]
        if tiefe not in STANDARD_STUFEN:
            tiefe = 'klein'
        del args[index:index + 2]
    stufe = stufen_laden().get(tiefe, STANDARD_STUFEN[tiefe])
    budget_usd = stufe.get('budget_usd', STANDARD_STUFEN[tiefe]['budget_usd'])
    aufwand = stufe.get('aufwand', STANDARD_STUFEN[tiefe]['aufwand'])

    # F-6 (24.09.2026): Zeitgrenze je Ablauf aus betriebsgrenzen.json statt fest 8 Minuten.
    # Ohne --ablauf oder bei ungueltigem Eintrag gilt weiter 8 (jack_grenzen.zeitgrenze_minuten).
    ablauf = 'arbeit'
    if '--ablauf' in args:
        index = args.index('--ablauf')
        if index + 1 >= len(args):
            raise ValueError('--ablauf braucht einen Wert')
        ablauf = args[index + 1]
        del args[index:index + 2]
    minuten = jack_grenzen.zeitgrenze_minuten(ROOT, ablauf)
    # F-11 (Paket 4): Zeitgrenze je Auftrag (Kopffeld zeitgrenze_minuten, von arbeiter.sh uebergeben).
    # F-12: hoechstens zeitgrenze_max_auftragskopf (Standard 30); darueber wird gekappt und gemeldet.
    # Unter 3 oder keine Zahl: ignoriert, nie geraten.
    if '--zeitgrenze-minuten' in args:
        index = args.index('--zeitgrenze-minuten')
        if index + 1 >= len(args):
            raise ValueError('--zeitgrenze-minuten braucht einen Wert')
        eigene, gekappt, obergrenze = jack_grenzen.zeitgrenze_auftragskopf(ROOT, args[index + 1])
        if gekappt:
            print('HINWEIS: Zeitgrenze laut Auftragskopf %s Minuten auf %d gekappt (zeitgrenze_max_auftragskopf).'
                  % (args[index + 1], obergrenze), flush=True)
        del args[index:index + 2]
        if eigene is not None:
            minuten = eigene
    # F-6: Fortsetzung eines Auftrags nach Zeitgrenze - der Rahmen darf die Tiefenstufe
    # nur SENKEN, nie heben.
    if '--budget-usd' in args:
        index = args.index('--budget-usd')
        if index + 1 >= len(args):
            raise ValueError('--budget-usd braucht einen Wert')
        try:
            deckel = float(args[index + 1])
        except ValueError:
            raise ValueError('--budget-usd ist keine Zahl') from None
        del args[index:index + 2]
        if deckel > 0:
            budget_usd = min(float(budget_usd), deckel)

    key = api_key()
    if not key:
        print('API NICHT ERREICHBAR: kein API-Zugang hinterlegt.')
        return 3
    env = os.environ.copy()
    for name in ('ANTHROPIC_AUTH_TOKEN', 'CLAUDE_CODE_OAUTH_TOKEN', 'ANTHROPIC_BASE_URL',
                 'CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX', 'CLAUDE_CODE_USE_FOUNDRY'):
        env.pop(name, None)
    env['ANTHROPIC_API_KEY'] = key
    env['CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC'] = '1'
    model=jack_modelle.load(ROOT)['ceo_und_pruefer']
    if '--model' in args:
        if args.count('--model')!=1 or args[args.index('--model')+1]!=model:
            raise ValueError('CEO-Modell weicht von der gemeinsamen Auswahl ab')
    else:args += ['--model',model]
    command = ['/opt/homebrew/bin/claude', *args,
               '--effort', aufwand, '--max-budget-usd', str(budget_usd), '--output-format', 'json']
    with jack_kosten.track(ROOT,"arbeiter_api","anthropic",model) as cost:
        cost["status"]="fehler"
        # F-9 (Paket 3): claude laeuft in einer eigenen Prozessgruppe. Ein Signal an den Arbeiterlauf
        # (Patron-STOPP, Unterbrechung) traf bisher nur diesen Python-Prozess - claude lief verwaist und
        # bezahlt weiter, die Kosten blieben ungebucht. Jetzt: Signal weiterreichen, Teilergebnis und
        # Kosten wie bei der Zeitgrenze buchen, Abbruchgrund melden.
        signal.signal(signal.SIGTERM, _abbruch_signal)
        signal.signal(signal.SIGHUP, _abbruch_signal)
        process = subprocess.Popen(command, cwd=ROOT.parents[1], env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, start_new_session=True)
        # F-11 (Paket 4, P02): ab hier kann der Lauf Geld kosten. Endet er ohne gemeldeten Betrag (Abbruch,
        # Zeitgrenze, STOPP, kein Abschlussprotokoll), bucht jack_kosten.end den Rahmen als Obergrenze.
        cost["usd_obergrenze"] = budget_usd
        try:
            output, error = process.communicate(timeout=minuten * 60)
        except AbbruchVonAussen as abbruch:
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            signal.signal(signal.SIGHUP, signal.SIG_IGN)
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                output, error = process.communicate(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                output, error = process.communicate()
            partial = None
            try:
                partial=json.loads(output)
                cost.update(verbrauch=jack_kosten.cli_usage(partial),usd=partial.get('total_cost_usd'),request_id=partial.get('session_id'))
            except (ValueError,AttributeError,TypeError):pass
            cost.update(error='abbruch_von_aussen')
            # F-9 Nachtrag (T8-Befund): im Abnahmelauf lieferte claude beim Abbruch kein auswertbares Teilergebnis,
            # der Lauf blieb im Kostenbuch ohne Betrag. Jetzt steht immer ein Laufbeleg mit dem, was ankam.
            try:
                beleg = {k: (partial or {}).get(k) for k in ('session_id', 'subtype', 'is_error', 'total_cost_usd',
                                                              'usage', 'modelUsage', 'num_turns')} if isinstance(partial, dict) else {}
                beleg.update(zeit=datetime.datetime.now().astimezone().isoformat(), tiefe=tiefe, budget_usd=budget_usd,
                             aufwand=aufwand, abbruch=str(abbruch), ausgabe_zeichen=len(output or ''),
                             ausgabe_json=isinstance(partial, dict), stderr_ende=(error or '')[-300:],
                             auftrag=os.environ.get('JACK_AUFTRAG_DATEI', ''))
                with (ROOT / 'arbeiter_api_laeufe.jsonl').open('a') as stream:
                    stream.write(json.dumps(beleg, ensure_ascii=False) + '\n')
            except (OSError, TypeError, ValueError):
                pass
            try:
                print('PROBLEM: Abbruch von aussen (%s): API-Lauf beendet; vorhandene Arbeit bleibt erhalten.' % abbruch, flush=True)
            except (OSError, ValueError):
                pass
            return 1
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                output, error = process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                output, error = process.communicate()
            try:
                partial=json.loads(output)
                cost.update(verbrauch=jack_kosten.cli_usage(partial),usd=partial.get('total_cost_usd'),request_id=partial.get('session_id'))
            except (ValueError,AttributeError):pass
            print('PROBLEM: Zeitgrenze: API-Lauf nach %d Minuten beendet (Ablauf %s); vorhandene Arbeit bleibt erhalten.' % (minuten, ablauf))
            return 1
        try:
            result = json.loads(output)
        except ValueError:
            # Kein Abschlussprotokoll: entweder die Verbindung stand nicht oder
            # der Zugang wurde abgewiesen. Beides heisst "nicht erreichbar" -
            # dann darf das Abo einspringen, ohne einen Versuch zu verbrennen.
            zusammen = ((output or '') + ' ' + (error or '')).lower()
            nicht_erreichbar = any(wort in zusammen for wort in (
                'connection', 'network', 'timed out', 'timeout', 'unreachable',
                'econnrefused', 'enotfound', 'getaddrinfo', 'authentication',
                'invalid api key', 'unauthorized', '401', '403', '429',
                'overloaded', '529', 'service unavailable', '503'))
            if nicht_erreichbar:
                print('API NICHT ERREICHBAR: ' + (error or output or '')[:300])
                # Nicht erreichbar heisst: kein angenommener Aufruf - keine Obergrenze buchen.
                cost.pop('usd_obergrenze', None)
                cost.update(status='fehler', error='api_nicht_erreichbar')
                return 3
            print('PROBLEM: API-Lauf lieferte kein gueltiges Abschlussprotokoll.')
            return 1
        cost.update(verbrauch=jack_kosten.cli_usage(result),usd=result.get('total_cost_usd'),request_id=result.get('session_id'),status='fehler' if process.returncode or result.get('is_error') else 'ok')
        record = {k: result.get(k) for k in ('session_id', 'subtype', 'is_error', 'total_cost_usd', 'usage', 'modelUsage', 'num_turns', 'result')}
        record['zeit'] = datetime.datetime.now().astimezone().isoformat()
        record['tiefe'] = tiefe
        record['budget_usd'] = budget_usd
        record['aufwand'] = aufwand
        with (ROOT / 'arbeiter_api_laeufe.jsonl').open('a') as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + '\n')
        text = result.get('result') or 'PROBLEM: API-Lauf ohne Ergebnis (' + str(result.get('subtype')) + ')'
        print(text)
        return 1 if process.returncode or result.get('is_error') else 0


if __name__ == '__main__':
    raise SystemExit(main())
