#!/usr/bin/env python3
"""Begrenzte Regression mit synthetischen Testdaten, ohne JACK-Dienst/Anbieter.

Aufruf: python3 -B pruefungen/regression_verlaesslichkeit.py --belege NEUER_PFAD
Optional --quelle REPO erlaubt dieselbe Gegenprobe am unveraenderten Ausgang.
Die ausgefuehrte Runner-Datei bleibt bytegleich. Belege werden nie geloescht.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import types
from unittest.mock import Mock, patch


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--belege', type=Path, required=True)
    parser.add_argument('--quelle', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    source = args.quelle.resolve()
    evidence = args.belege.resolve()
    runner = (source / 'bin/alle_tests.py').read_bytes()
    connections = (source / 'jack_verbindungen.py').read_bytes()
    runner_ast = ast.parse(runner)
    exclusions = next(ast.literal_eval(n.value) for n in runner_ast.body
                      if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == 'AUSSCHLUSS' for t in n.targets))
    if any(part in str(evidence) for part in exclusions):
        parser.error('Belegpfad faellt selbst unter die Runner-Ausschluesse; neutralen Pfad verwenden.')
    evidence.mkdir(parents=True, exist_ok=False)
    results = []
    green = "print('TESTDATEN erfolgreich')\n"
    red = "import sys\nprint('TESTDATEN Fehler', file=sys.stderr)\nsys.exit(7)\n"
    slow = "import time\ntime.sleep(2)\n"
    cases = [
        ('erfolg', {'test_ok.py': green}, [], 0, (1, 1, 0, 0)),
        ('fehler', {'test_rot.py': red}, [], 1, (1, 0, 1, 0)),
        ('timeout', {'test_langsam.py': slow}, [], 1, (1, 0, 0, 1)),
        ('leer', {}, [], 1, (0, 0, 0, 0)),
        ('erfolg_und_timeout', {'test_ok.py': green, 'test_langsam.py': slow}, [], 1, (2, 1, 0, 1)),
        ('filter_leer', {'test_ok.py': green}, ['--muster', 'unpassend'], 1, (0, 0, 0, 0)),
        ('filter_passend', {'test_ok.py': green, 'test_rot.py': red}, ['--muster', 'test_ok'], 0, (1, 1, 0, 0)),
        ('ausschluss', {'test_ok.py': green, 'kandidat/test_rot.py': red}, [], 0, (1, 1, 0, 0)),
    ]
    for name, files, flags, expected, counts in cases:
        case = evidence / name
        (case / 'bin').mkdir(parents=True)
        (case / 'abnahme').mkdir()
        script = case / 'bin/alle_tests.py'
        script.write_bytes(runner)
        for filename, content in files.items():
            fixture = case / 'abnahme' / filename
            fixture.parent.mkdir(parents=True, exist_ok=True)
            fixture.write_text(content, encoding='utf-8')
        completed = subprocess.run(
            [sys.executable, '-I', '-B', str(script), '--zeit', '1'] + flags,
            cwd=case, capture_output=True, text=True, timeout=8,
            env={'PATH': os.defpath, 'PYTHONDONTWRITEBYTECODE': '1'},
        )
        summary = '%d Dateien: %d gruen, %d rot, %d Zeitueberschreitung' % counts
        passed = (completed.returncode == expected
                  and completed.stdout.splitlines()[:1] == [summary]
                  and not completed.stderr
                  and (not counts[2] or 'ROT ' in completed.stdout)
                  and (not counts[3] or 'ZEIT ' in completed.stdout)
                  and script.read_bytes() == runner)
        results.append({'fall': name, 'bestanden': passed, 'exit': completed.returncode,
                        'exit_erwartet': expected, 'stdout': completed.stdout, 'stderr': completed.stderr})

    # Nur die echte Einzelfunktion laden, keine JACK-Module oder Dienste starten.
    connection_ast = ast.parse(connections)
    function = next(n for n in connection_ast.body
                    if isinstance(n, ast.FunctionDef) and n.name == '_pruefe_codex')
    scope = {'_kurz': lambda error: str(error).replace('TEST_SECRET', '[REDACTED]')[:200]}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source / 'jack_verbindungen.py'), 'exec'), scope)
    check = scope['_pruefe_codex']
    for name, found, error, expected in [
        ('codex_gefunden', Path('/TESTDATEN/codex'), None, 'ok'),
        ('codex_fehlt', None, None, 'warnung'),
        ('codex_resolver_fehler', None, ValueError('TEST_SECRET'), 'fehler'),
    ]:
        resolver = Mock(return_value=found, side_effect=error)
        bridge = types.ModuleType('codex_bruecke')
        bridge.codex_pfad = resolver
        bridge.CODEX = evidence / 'nicht_installierter_alter_pfad'
        try:
            with patch.dict(sys.modules, {'codex_bruecke': bridge}):
                status, detail = check(source)
            passed = (status == expected
                      and 'TEST_SECRET' not in detail
                      and (status != 'ok' or 'Anmeldung nicht geprueft' in detail))
        except Exception as failure:
            status, detail, passed = 'exception', type(failure).__name__, False
        results.append({'fall': name, 'bestanden': passed, 'status': status, 'detail': detail})

    unchanged = ((source / 'bin/alle_tests.py').read_bytes() == runner
                 and (source / 'jack_verbindungen.py').read_bytes() == connections)
    passed = all(result['bestanden'] for result in results) and unchanged
    report = {
        'bestanden': passed, 'quelle_unveraendert': unchanged,
        'runner_sha256': digest(runner), 'verbindungen_sha256': digest(connections),
        'ergebnisse': results,
        'grenzen': [
            'Nur synthetische Testprogramme, keine echte JACK-Gesamtsuite.',
            'Codex-Resolver als Schnittstelle ersetzt; keine Anmeldung oder Modellantwort.',
            'Keine Dienstneustarts und keine Produktionsabnahme.',
        ],
    }
    (evidence / 'ergebnis.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'bestanden': passed, 'pruefungen': len(results),
                      'erfolgreich': sum(r['bestanden'] for r in results), 'beleg': str(evidence / 'ergebnis.json')}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
