#!/usr/bin/env python3
"""Was kostet der Kontext eines Arbeiterlaufs - je Schritt und je Rolle?

Block 30 (20.09.2026). Zwei Zahlen werden gemessen, keine geraten:

  ZEICHEN  - hart gezaehlt aus den Dateien.
  TOKEN    - bei Anthropic mit /v1/messages/count_tokens gezaehlt. Das ist
             dieselbe Zaehlung, nach der abgerechnet wird, und sie kostet
             nichts. Ist der Schluessel oder das Netz nicht da, steht statt
             einer Zahl "nicht gezaehlt" - es wird NICHTS geschaetzt und
             nichts hochgerechnet.

Aufruf:  python3 kontext_messung.py <auftragsdatei> [--titel "..."]
"""
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER))
import jack_tresor

MODELL = "claude-sonnet-5"


def token_zaehlen(text, schluessel):
    """Exakte Tokenzahl von Anthropic - oder None. Nie geraten."""
    if not schluessel or not text:
        return 0 if not text else None
    anfrage = urllib.request.Request(
        "https://api.anthropic.com/v1/messages/count_tokens",
        data=json.dumps({"model": MODELL,
                         "messages": [{"role": "user", "content": text}]}).encode("utf-8"),
        headers={"x-api-key": schluessel, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"})
    try:
        with urllib.request.urlopen(anfrage, timeout=30) as antwort:
            return json.loads(antwort.read())["input_tokens"]
    except (urllib.error.URLError, KeyError, ValueError, OSError):
        return None


def anweisungsrahmen(arbeiter):
    """Der feste Teil der CEO-Anweisung, ohne Ordnung, Besetzung und Auftrag."""
    text = arbeiter.read_text(encoding="utf-8")
    anfang = text.index('ANWEISUNG="')
    ende = text.index('\n\n  EINSTELLUNGEN=', anfang)
    rahmen = text[anfang + len('ANWEISUNG="'):ende].rstrip().rstrip('"')
    for platzhalter in ("$ORDNUNG", "$BESETZUNG", "$AUFTRAG"):
        rahmen = rahmen.replace(platzhalter, "")
    return rahmen


def abschnitte(datei, titel):
    text = datei.read_text(encoding="utf-8")
    raus = []
    for t in titel:
        ebene = len(t) - len(t.lstrip("#"))
        treffer = re.search(r"^" + re.escape(t) + r"[ \t]*$(.*?)(?=^#{1," + str(ebene) + r"} |\Z)",
                            text, re.M | re.S)
        if treffer:
            raus.append(t + treffer[1].rstrip())
    return "\n\n".join(raus)


ORDNUNG_DIAET = ["## 1. Die Kette", "## 3. Die zwei Tore", "## 4. Tiefe nach Auftragsgrösse",
                 "## 8. Harte Verbote", "## 9. Modellwahl — billig, wo es reicht"]
BESETZUNG_DIAET = ["### Bereit und startbar", "### Getrennte Prüfung — Pflicht"]


def messen(auftragsdatei):
    schluessel = jack_tresor.lesen("ANTHROPIC_API_KEY")
    ordnung = HIER / "agenten" / "README_AGENTEN.md"
    besetzung = HIER / "agenten" / "BESETZUNG.md"
    pruefer = HIER / "agenten" / "90_Pruefer" / "pruefer.md"
    auftrag = Path(auftragsdatei)

    teile = {
        "CEO · Anweisungsrahmen (fest)": (anweisungsrahmen(HIER / "arbeiter.sh"),
                                          anweisungsrahmen(HIER / "arbeiter.sh")),
        "CEO · Betriebsordnung": (ordnung.read_text(encoding="utf-8"),
                                  abschnitte(ordnung, ORDNUNG_DIAET)),
        "CEO · Besetzung": (besetzung.read_text(encoding="utf-8"),
                            abschnitte(besetzung, BESETZUNG_DIAET)),
        "CEO · Auftragstext": (auftrag.read_text(encoding="utf-8"),
                               auftrag.read_text(encoding="utf-8")),
        "Fachkraft · Rollenanweisung": (rolle("jack-fachkraft"), rolle("jack-fachkraft")),
        "Prüfer · Rollenanweisung": (rolle("jack-pruefer"), rolle("jack-pruefer")),
        "Prüfer · Prüfregeln (pruefer.md)": (pruefer.read_text(encoding="utf-8"),
                                             pruefer.read_text(encoding="utf-8")),
    }
    zeilen = []
    for name, (voll, diaet) in teile.items():
        zeilen.append({"teil": name,
                       "zeichen_vorher": len(voll), "zeichen_nachher": len(diaet),
                       "token_vorher": token_zaehlen(voll, schluessel),
                       "token_nachher": token_zaehlen(diaet, schluessel) if diaet != voll
                                        else None})
    for z in zeilen:
        if z["token_nachher"] is None and z["zeichen_vorher"] == z["zeichen_nachher"]:
            z["token_nachher"] = z["token_vorher"]
    return zeilen, bool(schluessel)


def rolle(name):
    daten = json.loads((HIER / "arbeiter_agenten.json").read_text(encoding="utf-8"))
    return daten.get(name, {}).get("prompt", "")


if __name__ == "__main__":
    datei = sys.argv[1]
    zeilen, hat_schluessel = messen(datei)
    print(json.dumps({"auftrag": datei, "token_gezaehlt": hat_schluessel, "teile": zeilen},
                     ensure_ascii=False, indent=1))
