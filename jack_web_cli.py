#!/usr/bin/env python3
"""Der einzige Netzzugang der Fachkraefte — nur lesen.

Freigabe des Patrons vom 16.09.2026, erweitert am 17.09.2026 (Block 20).
Genau drei Befehle:

    jack_web_cli.py suche <Anfrage>
    jack_web_cli.py lies  <https-Adresse>
    jack_web_cli.py feed  <https-Adresse>

Mehr gibt es nicht. `feed` liest einen RSS- oder Atom-Feed und meldet nur die
NEUEN Eintraege seit dem letzten Abruf. Er ruft ausschliesslich Adressen ab, die
in betrieb/rss_quellen.json stehen - und dort kommt eine Adresse nur durch eine
Freigabe des Patrons hinein. Es wird nichts gesendet, nichts angemeldet, nichts gekauft
und nichts installiert. Alle Grenzen (Tagesmenge, Wiederverwendung, oeffentliche
Adressen, Protokoll) stecken in jack_websuche und jack_webabruf und gelten hier
unveraendert. Der Pfadwaechter in arbeiter.sh laesst ueber Bash ausschliesslich
diesen Aufruf zu; jeder andere Befehl wird abgewiesen.

Rueckgabe: 0 mit Ergebnis auf der Ausgabe, 2 mit Grund bei einer Grenze.
"""
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent
sys.path.insert(0, str(WURZEL))


def main(argv):
    if len(argv) != 3 or argv[1] not in ('suche', 'lies', 'feed'):
        print('Benutzung: jack_web_cli.py suche <Anfrage> | lies <https-Adresse>'
              ' | feed <https-Adresse>', file=sys.stderr)
        return 2
    befehl, wert = argv[1], argv[2]
    try:
        if befehl == 'suche':
            import jack_websuche
            ergebnis = jack_websuche.search(WURZEL, wert)
        elif befehl == 'feed':
            import jack_rss
            ergebnis = jack_rss.abrufen(WURZEL, wert)
        else:
            import jack_webabruf
            ergebnis = jack_webabruf.fetch(WURZEL, wert)
    except ValueError as fehler:
        print('NICHT MOEGLICH: ' + str(fehler), file=sys.stderr)
        return 2
    except OSError as fehler:
        print('NICHT MOEGLICH: ' + str(fehler)[:300], file=sys.stderr)
        return 2
    print(ergebnis['text'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
