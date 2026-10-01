#!/usr/bin/env python3
"""Monatlicher Modellabgleich (Block 11, Aufgabe 5).

Einmal im Monat nachsehen, ob es je Stufe ein guenstigeres Modell gibt, das
gleich gut ist. Das Ergebnis ist ein VORSCHLAG im Freigaben-Kasten - nie eine
Aenderung. modellwahl.json fasst dieses Programm nicht an.

Was es liest: die oeffentliche Preisseite des Anbieters. Nur lesen.
Was es NICHT tut: sich irgendwo anmelden, irgendwo etwas eingeben, auf
Gratis-Webdiensten Aufgaben ausprobieren. Holding-Inhalte gehen dort nie hinein.
"""
import json
import sys
import urllib.request
from pathlib import Path

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER))
import jack_betrieb as b
import jack_kosten

PREISSEITE = "https://claude.com/pricing"
ABSTAND_TAGE = 30
STAND = "modellabgleich.json"


def _stand():
    try:
        return json.loads((b.area(HIER) / STAND).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def faellig():
    """Ist der Abgleich dran? Er laeuft hoechstens einmal im Monat."""
    s = _stand()
    letzter = s.get("zuletzt")
    if not letzter:
        return True, "noch nie gelaufen"
    try:
        import datetime as dt
        tage = (b.now() - dt.datetime.fromisoformat(letzter)).days
    except Exception:
        return True, "letzter Lauf nicht lesbar"
    if tage >= ABSTAND_TAGE:
        return True, "letzter Lauf vor %d Tagen" % tage
    return False, "letzter Lauf vor %d Tagen - faellig in %d" % (tage, ABSTAND_TAGE - tage)


def abgleichen(schreiben=True):
    """Preise holen, mit der eigenen Preisdatei vergleichen, Vorschlag ablegen."""
    eigene = jack_kosten.preise(HIER)
    bericht = {"zeit": b.now().isoformat(), "quelle": PREISSEITE,
               "eigener_stand": eigene.get("abgerufen", "unbekannt"),
               "abweichungen": [], "hinweis": "", "erreicht": False}
    try:
        anfrage = urllib.request.Request(
            PREISSEITE, headers={"User-Agent": "JACK/1.0 (lesender Preisabgleich)"})
        with urllib.request.urlopen(anfrage, timeout=25) as antwort:
            roh = antwort.read(600000).decode("utf-8", "replace")
        bericht["erreicht"] = True
    except Exception as fehler:
        bericht["hinweis"] = ("Preisseite nicht erreichbar (%s). Die eigene Preisdatei "
                              "bleibt unveraendert; es wird nichts geraten."
                              % type(fehler).__name__)
        roh = ""
    if roh:
        import re
        # Nur Zahlenpaare der Form "$X / MTok" einsammeln. Wird die Seite
        # umgebaut, findet das Muster nichts - dann steht das im Bericht, und
        # es wird trotzdem nichts geraten.
        treffer = re.findall(r"\$\s*([0-9]+(?:\.[0-9]+)?)\s*/\s*MTok", roh)
        bericht["gefundene_preise"] = len(treffer)
        if not treffer:
            bericht["hinweis"] = ("Die Preisseite war erreichbar, aber das bekannte "
                                  "Muster stand nicht darin. Bitte von Hand nachsehen.")
    if schreiben:
        s = _stand()
        s["zuletzt"] = bericht["zeit"]
        s["letzter_bericht"] = bericht
        p = b.area(HIER) / STAND
        p.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    return bericht


if __name__ == "__main__":
    was = sys.argv[1] if len(sys.argv) > 1 else "faellig"
    if was == "faellig":
        dran, grund = faellig()
        print(json.dumps({"faellig": dran, "grund": grund}, ensure_ascii=False))
    elif was == "lauf":
        print(json.dumps(abgleichen(), ensure_ascii=False, indent=1))
    else:
        print("faellig | lauf")
