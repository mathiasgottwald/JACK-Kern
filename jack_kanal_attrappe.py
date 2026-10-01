#!/usr/bin/env python3
"""Kanal-Attrappe fuer Paket 3 (F-9, 24.09.2026): ein nachgebildeter Anbieter, 0 USD, kein Netz.

Die "Anbieterseite" ist eine Datei im Betriebsordner (betrieb/kanal_attrappe.json): jeder dort
eingetroffene Aufruf wird mit seiner Vorgangskennung gezaehlt. Damit laesst sich beweisen, wie oft ein
Aufruf WIRKLICH beim Anbieter ankam - unabhaengig davon, was die eigene Akte glaubt.

Modi eines Aufrufs (senden):
  ok                 Aufruf kommt an, Antwort kommt zurueck
  antwort_verloren   Aufruf kommt an, die Antwort geht verloren (Zeitueberschreitung beim Aufrufer)
  nicht_angekommen   Netzfehler VOR dem Anbieter: nichts kommt an, der Aufrufer sieht nur einen Fehler
  abgewiesen         Anbieter antwortet mit Ablehnung (wie HTTP 4xx): belegter Nicht-Erfolg
  absturz            Aufruf kommt an, danach stirbt der Aufrufer, bevor er die Antwort vermerkt (SIGKILL)
Zustandsabfrage (pruefen): findet Aufrufe per Vorgangskennung; mit pruefbar=False ist die Abfrage
(wie bei Runway/Higgsfield ohne Anbieterkennung) nicht moeglich.
"""
import contextlib
import fcntl
import json
import os
import signal
import uuid

import jack_betrieb as betrieb
import jack_vorgaenge

DATEI = "kanal_attrappe.json"


@contextlib.contextmanager
def _anbieter(root):
    pfad = betrieb.area(root) / DATEI
    sperre = betrieb.area(root) / (DATEI + ".sperre")
    with sperre.open("a+") as s:
        fcntl.flock(s, fcntl.LOCK_EX)
        try:
            daten = json.loads(pfad.read_text(encoding="utf-8")) if pfad.is_file() else {}
        except ValueError:
            daten = {}
        daten.setdefault("aufrufe", [])
        daten.setdefault("pruefbar", True)
        yield daten
        tmp = pfad.with_name("." + pfad.name + ".neu")
        tmp.write_text(json.dumps(daten, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, pfad)
        fcntl.flock(s, fcntl.LOCK_UN)


def einstellen(root, pruefbar=True):
    with _anbieter(root) as d:
        d["pruefbar"] = bool(pruefbar)


def aufrufe(root, vg=None):
    with _anbieter(root) as d:
        return [a for a in d["aufrufe"] if vg is None or a["vg"] == vg]


def _anbieterseite(root, vg, inhalt):
    kennung = "att-" + uuid.uuid4().hex[:12]
    with _anbieter(root) as d:
        d["aufrufe"].append({"vg": vg, "anbieter_kennung": kennung, "zeit": betrieb.now().isoformat(),
                             "inhalt": str(inhalt)[:200]})
    return kennung


def senden(root, bezug, inhalt, modus="ok", kanal="attrappe", schritt="senden", auftrag=None, freigabe=None):
    """Eine Aussenaktion ueber die Attrappe - mit Vorgangskennung VOR dem Aufruf."""
    def aufruf(vg):
        if modus == "nicht_angekommen":
            raise ConnectionError("Netz nicht erreichbar (Attrappe): nichts ist angekommen")
        if modus == "abgewiesen":
            raise jack_vorgaenge.AnbieterAbgewiesen("Attrappe lehnt ab (wie HTTP 422)")
        kennung = _anbieterseite(root, vg, inhalt)
        if modus == "antwort_verloren":
            raise TimeoutError("Antwort ausgeblieben (Attrappe)")
        if modus == "absturz":
            os.kill(os.getpid(), signal.SIGKILL)
        return kennung
    return jack_vorgaenge.ausfuehren(root, kanal, bezug, schritt, inhalt, aufruf, auftrag=auftrag, freigabe=freigabe)


def pruefen(root, v):
    """Zustandspruefer fuer jack_vorgaenge: sucht den Aufruf per Vorgangskennung beim 'Anbieter'."""
    with _anbieter(root) as d:
        if not d.get("pruefbar", True):
            return {"ergebnis": "nicht_pruefbar", "beleg": "Attrappe: Zustandsabfrage abgeschaltet (wie Anbieter ohne Suche)"}
        treffer = [a for a in d["aufrufe"] if a["vg"] == v["vg"]]
    if treffer:
        return {"ergebnis": "angekommen", "anbieter_kennung": treffer[-1]["anbieter_kennung"],
                "beleg": "Attrappe kennt %d Aufruf(e) mit %s" % (len(treffer), v["vg"])}
    return {"ergebnis": "nicht_angekommen", "beleg": "Attrappe kennt keinen Aufruf mit " + v["vg"]}


if __name__ == "__main__":
    import sys
    from pathlib import Path
    wurzel = Path(__file__).resolve().parent
    modus = sys.argv[2] if len(sys.argv) > 2 else "ok"
    print(json.dumps(senden(wurzel, sys.argv[1], "Attrappe " + sys.argv[1], modus=modus), ensure_ascii=False))
