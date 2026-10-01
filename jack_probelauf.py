#!/usr/bin/env python3
"""Wegwerf-Aufgabe fuer TESTAUFTRAEGE (Vorgabe des Patrons vom 16.09.2026).

Ein Testauftrag laeuft NIE gegen ein Modell. Er zaehlt Dateien und wartet kurz -
genug, um Gleichzeitigkeit, Sperren, Abhaengigkeiten und die Auftragstafel zu
belegen, ohne einen einzigen Anbieterlauf und ohne einen Cent Kosten.

Er schreibt seinen Fortschritt in Teilaufgaben, damit der Balken der
Auftragstafel aus echten Zahlen gespeist wird und nicht aus einer Schaetzung.
"""
import re
import sys
import time
from pathlib import Path

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER))
import jack_planer as planer


def zahl_aus_kopf(text, schluessel, standard):
    m = re.search(r"^%s:\s*(\d+)\s*$" % schluessel, text, re.M)
    return int(m.group(1)) if m else standard


def main():
    pfad = Path(sys.argv[1])
    datei = pfad.name
    text = pfad.read_text(encoding="utf-8", errors="replace")
    schritte = zahl_aus_kopf(text, "probe_schritte", 4)
    dauer = zahl_aus_kopf(text, "probe_sekunden", 6)
    # Kommen waehrend der Arbeit Teilaufgaben dazu? Dann waechst der Nenner
    # und der Balken laeuft zurueck - das ist ehrlich und erwuenscht.
    zusatz_ab = zahl_aus_kopf(text, "probe_zusatz_ab", 0)
    zusatz = zahl_aus_kopf(text, "probe_zusatz", 0)
    unbekannt = re.search(r"^probe_unbekannt:\s*ja\s*$", text, re.M) is not None

    planer.fortschritt_setzen(datei, geplant=None if unbekannt else schritte,
                              erledigt=0, schritt="Wegwerf-Aufgabe, kein Modellaufruf")
    print("PROBELAUF %s: %d Schritte, %d s, kein Modellaufruf" % (datei, schritte, dauer))
    je = max(0.2, dauer / max(1, schritte))
    geplant = schritte
    for i in range(1, schritte + 1):
        time.sleep(je)
        if zusatz and zusatz_ab and i == zusatz_ab:
            geplant += zusatz
            print("  Teilaufgaben dazugekommen: geplant jetzt %d" % geplant)
            planer.fortschritt_setzen(datei, geplant=None if unbekannt else geplant,
                                      erledigt=i,
                                      schritt="zusaetzliche Teilaufgaben erkannt")
            schritte = geplant
            continue
        n = len(list((HIER / "betrieb").glob("*.json")))   # echte, harmlose Arbeit
        planer.fortschritt_setzen(datei, geplant=None if unbekannt else geplant,
                                  erledigt=i,
                                  schritt="Teilaufgabe %d: %d Betriebsdateien gezaehlt" % (i, n))
        print("  Schritt %d von %d erledigt (%d Betriebsdateien)" % (i, geplant, n))
    planer.fortschritt_setzen(datei, erledigt=geplant, schritt="fertig")
    # Wie ein echter Lauf: der Auftrag wandert nach erledigt/. Sonst wuerde der
    # Planer ihn im naechsten Takt erneut starten - und Abhaengigkeiten koennten
    # nie erfuellt werden.
    ziel = pfad.parent.parent / "erledigt" / datei
    ziel.parent.mkdir(exist_ok=True)
    neu = text.replace("status:     offen", "status:     erledigt")
    neu += ("\n## Ergebnis (Probelauf)\nWegwerf-Aufgabe ohne Modellaufruf abgeschlossen: "
            "%d Teilaufgaben.\n" % geplant)
    ziel.write_text(neu, encoding="utf-8")
    pfad.unlink()
    print("PROBELAUF %s fertig, nach erledigt/ verschoben." % datei)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
