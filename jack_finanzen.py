#!/usr/bin/env python3
"""Ansicht „Finanzen" und „Verbindungen" (Auftrag F-14, 24.09.2026) - NUR LESEN.

Quellen: betrieb/vertragsregister.json (Zeilen: anbieter, zweck, marke, preis, intervall, status, notiz,
zeitstempel, check_relevant, details ...) und betrieb/verbindungsregister.json (verbindungen: name, gruppe,
zweck, kostenpflichtig, finanzen_verweis, status, notiz, zeitstempel ...). Dieses Modul schreibt nie.

Befund bei der Inspektion (24.09.2026): Das Vertragsregister hat KEINE Felder betrag/waehrung/rhythmus. Preis und
Intervall sind Freitext ("214,20 EUR/Monat (...)", "ca. 39 $/Monat", Intervall in 26 von 48 Zeilen "unbekannt").
Betrag, Waehrung und Rhythmus werden deshalb aus dem Text ABGELEITET (erster Betrag mit Waehrungszeichen) und in
der Ansicht als "abgeleitet" gekennzeichnet; nichts wird umgerechnet (EUR und USD getrennt), nichts geraten -
ohne erkennbaren Betrag bleibt er "unbekannt".
"""
import datetime as dt
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

import jack_betrieb as betrieb

STATUSWERTE = ("geprueft", "angenommen", "vermutet", "offen", "blockiert")
WARTET = ("blockiert", "offen")
VERALTET_TAGE = 30
_BETRAG = re.compile(r"(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{1,2}))?\s*(EUR|€|USD|\$)", re.I)
_BETRAG_VORN = re.compile(r"(\$|€)\s*(\d{1,3}(?:\.\d{3})+|\d+)(?:[.,](\d{1,2}))?")
_DATUM = re.compile(r"(\d{4}-\d{2}-\d{2})")
GRUPPENNAMEN = {"Postfach": "Postfächer", "KI-Werkzeug": "KI-Motoren und KI-Werkzeuge",
                "Pruefung / KI-Werkzeug": "KI-Motoren und KI-Werkzeuge", "Agentensystem": "Agentensysteme",
                "Dienst": "Server, Hosting und Dienste", "Web": "Web", "Kalender": "Kalender",
                "Veroeffentlichung": "Kanäle (Veröffentlichung)", "Vertrieb": "Kanäle (Vertrieb)",
                "Wissen": "Wissen", "Zugang": "Zugang",
                "Kanaele Veroeffentlichung/Vertrieb": "Kanäle (Veröffentlichung/Vertrieb)"}


def _text(wert):
    """Feldwert als Text. Liste statt Text -> zusammengefuegt, zweiter Rueckgabewert meldet den Formfehler."""
    if wert is None:
        return "", False
    if isinstance(wert, str):
        return wert, False
    if isinstance(wert, list):
        return "; ".join(_text(x)[0] for x in wert), True
    if isinstance(wert, dict):
        return json.dumps(wert, ensure_ascii=False), True
    return str(wert), True


def betrag(preis):
    """(Decimal, 'EUR'|'USD', ungefaehr: bool) oder (None, None, False). Erster Betrag mit Waehrungszeichen."""
    text = preis or ""
    m = _BETRAG.search(text)
    if m:
        ganz, rest, zeichen, anfang = m.group(1), m.group(2), m.group(3), m.start()
    else:
        v = _BETRAG_VORN.search(text)
        if not v:
            return None, None, False
        zeichen, ganz, rest, anfang = v.group(1), v.group(2), v.group(3), v.start()
    try:
        wert = Decimal(ganz.replace(".", "") + ("." + rest if rest else ""))
    except InvalidOperation:
        return None, None, False
    waehrung = "EUR" if zeichen in ("€",) or zeichen.upper() == "EUR" else "USD"
    ungefaehr = bool(re.search(r"(ca\.|circa|rund|etwa)", text[:anfang], re.I))
    return wert, waehrung, ungefaehr


def rhythmus(intervall, preis):
    """monatlich | jaehrlich | einmalig | variabel | unbekannt - abgeleitet. Das Intervall hat Vorrang; nur wenn es nichts
    sagt, entscheidet der Preistext."""
    i, p = (intervall or "").lower(), (preis or "").lower()
    variabel = ("nutzung", "verbrauch", "variabel", "unregelm", "laufend", "pay-as-you-go", "prepaid")
    if "gemischt" in i:
        return "unbekannt"
    if "einmalig" in i or "einmalig" in p:          # F-18: eigene Rhythmusart
        return "einmalig"
    if any(w in i for w in variabel):
        return "variabel"
    if "jaehrlich" in i or "jährlich" in i:
        return "jaehrlich"
    if i.startswith("monatlich"):
        return "monatlich"
    if "/jahr" in p:
        return "jaehrlich"
    if "/monat" in p:
        return "monatlich"
    if any(w in p for w in variabel):
        return "variabel"
    return "unbekannt"


def _datum(zeitstempel):
    m = _DATUM.search(zeitstempel or "")
    return m.group(1) if m else None


def _schluessel(anbieter):
    return re.sub(r"[^a-z0-9]+", " ", (anbieter or "").lower()).strip()


def _laden(root, name, liste):
    """(zeilen, fehler) - fehler ist ein Klartext; die Ansicht stuerzt nie."""
    pfad = betrieb.area(root) / name
    try:
        daten = json.loads(pfad.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [], "Datei fehlt: betrieb/%s" % name
    except (OSError, ValueError) as fehler:
        return [], "Datei betrieb/%s nicht lesbar (%s)" % (name, type(fehler).__name__)
    zeilen = daten.get(liste) if isinstance(daten, dict) else None
    if not isinstance(zeilen, list):
        return [], "betrieb/%s: Feld '%s' ist keine Liste" % (name, liste)
    return [z for z in zeilen if isinstance(z, dict)], None


def finanzen(root, heute=None):
    heute = heute or betrieb.now().date()
    zeilen, fehler = _laden(root, "vertragsregister.json", "zeilen")
    raus, gesehen, feldfehler = [], {}, []
    for nr, z in enumerate(zeilen):
        f = {k: _text(z.get(k)) for k in ("anbieter", "zweck", "marke", "preis", "intervall", "status", "notiz",
                                           "zeitstempel", "check_relevant", "naechste_verlaengerung", "details_text")}
        kaputt = sorted(k for k, (_, falsch) in f.items() if falsch)
        if kaputt:
            feldfehler.append("%s: %s als Liste/Objekt statt Text" % (f["anbieter"][0] or "Zeile %d" % (nr + 1), ", ".join(kaputt)))
        w = {k: v[0] for k, v in f.items()}
        # F-18: Register traegt betrag/waehrung/rhythmus selbst - direkt lesen; Textableitung nur als Rueckfall.
        if "betrag" in z and isinstance(z.get("betrag"), (int, float, type(None))) and not isinstance(z.get("betrag"), bool):
            b = Decimal(str(z["betrag"])) if z.get("betrag") is not None else None
            waehrung = z.get("waehrung") if z.get("waehrung") in ("EUR", "USD") else None
            if b is not None and waehrung is None:
                b = None                                        # Betrag ohne Waehrung zaehlt nicht (nie raten)
            ungefaehr = "(ca.)" in str(z.get("herkunft_betrag") or "")
            quelle_betrag = "Registerfeld"
        else:
            b, waehrung, ungefaehr = betrag(w["preis"])
            quelle_betrag = "aus Preistext abgeleitet"
        schluessel = _schluessel(w["anbieter"])
        dublette = schluessel in gesehen and bool(schluessel)
        gesehen.setdefault(schluessel, nr)
        status = w["status"] if w["status"] in STATUSWERTE else "unbekannt"
        raus.append({"anbieter": w["anbieter"], "zweck": w["zweck"], "marke": w["marke"], "preis": w["preis"],
                     "intervall": w["intervall"],
                     "rhythmus": (z["rhythmus"] if z.get("rhythmus") in ("monatlich", "jaehrlich", "einmalig", "variabel", "unbekannt")
                                  else rhythmus(w["intervall"], w["preis"])), "quelle_betrag": quelle_betrag,
                     "betrag": str(b) if b is not None else None, "waehrung": waehrung, "ungefaehr": ungefaehr,
                     "status": status, "status_roh": w["status"], "notiz": w["notiz"], "details": w["details_text"],
                     "zeitstempel": w["zeitstempel"], "datum": _datum(w["zeitstempel"]),
                     "check_relevant": w["check_relevant"].strip().lower().startswith("ja"),
                     "naechste_verlaengerung": w["naechste_verlaengerung"], "dublette": dublette,
                     "feldfehler": kaputt})
    bloecke = {r: {"EUR": Decimal(0), "USD": Decimal(0), "zeilen": 0, "ohne_betrag": 0}
               for r in ("monatlich", "jaehrlich", "variabel")}
    ohne_zuordnung = 0
    for z in raus:
        if z["dublette"]:
            continue
        blk = bloecke.get(z["rhythmus"])
        if blk is None:
            ohne_zuordnung += 1
            continue
        blk["zeilen"] += 1
        if z["betrag"] is None:
            blk["ohne_betrag"] += 1
        else:
            blk[z["waehrung"]] += Decimal(z["betrag"])
    daten = [z["datum"] for z in raus if z["datum"]]
    stand = max(daten) if daten else None
    alter = (heute - dt.date.fromisoformat(stand)).days if stand else None
    return {"zeilen": raus, "fehler": fehler, "feldfehler": feldfehler,
            "bloecke": {r: {**v, "EUR": str(v["EUR"]), "USD": str(v["USD"])} for r, v in bloecke.items()},
            "ohne_zuordnung": ohne_zuordnung, "dubletten": sum(1 for z in raus if z["dublette"]),
            "stand": stand, "stand_alter_tage": alter, "veraltet": alter is None or alter > VERALTET_TAGE}


def _finanzzeile(verweis, anbieter):
    """Verknuepfte Finanzzeile: zuerst gleicher Name, sonst die groesste Wortueberschneidung (mind. 2 Woerter
    mit 3+ Zeichen, oder 1 Wort, wenn der Verweis nur eines hat). Kein Treffer -> None, nie geraten."""
    s = _schluessel(verweis)
    if not s or s == "-":
        return None
    for a, k in anbieter:
        if k == s:
            return a
    woerter = {w for w in s.split(" ") if len(w) >= 3}
    bester, punkte = None, 0
    for a, k in anbieter:
        gemeinsam = len(woerter & {w for w in k.split(" ") if len(w) >= 3})
        if gemeinsam > punkte:
            bester, punkte = a, gemeinsam
    noetig = 1 if len(woerter) <= 1 else 2
    return bester if punkte >= noetig else None


def verbindungen(root, finanzzeilen=()):
    zeilen, fehler = _laden(root, "verbindungsregister.json", "verbindungen")
    anbieter = [(z["anbieter"], _schluessel(z["anbieter"])) for z in finanzzeilen]
    gruppen, feldfehler = {}, []
    for nr, z in enumerate(zeilen):
        f = {k: _text(z.get(k)) for k in ("name", "gruppe", "zweck", "kostenpflichtig", "finanzen_verweis", "status",
                                           "notiz", "zeitstempel", "quelle")}
        kaputt = sorted(k for k, (_, falsch) in f.items() if falsch)
        if kaputt:
            feldfehler.append("%s: %s als Liste/Objekt statt Text" % (f["name"][0] or "Zeile %d" % (nr + 1), ", ".join(kaputt)))
        w = {k: v[0] for k, v in f.items()}
        kostenpflichtig = w["kostenpflichtig"].strip().lower().startswith("ja")
        verweis = _finanzzeile(w["finanzen_verweis"], anbieter)
        gruppe = GRUPPENNAMEN.get(w["gruppe"], w["gruppe"] or "ohne Gruppe")
        gruppen.setdefault(gruppe, []).append({
            "name": w["name"], "zweck": w["zweck"], "status": w["status"] if w["status"] in STATUSWERTE else "unbekannt",
            "kostenpflichtig": kostenpflichtig, "kostenpflichtig_text": w["kostenpflichtig"],
            "finanzen_verweis": w["finanzen_verweis"], "finanzzeile": verweis if kostenpflichtig else None,
            "notiz": w["notiz"], "zeitstempel": w["zeitstempel"], "datum": _datum(w["zeitstempel"]), "feldfehler": kaputt})
    return {"gruppen": [{"name": g, "zeilen": z} for g, z in sorted(gruppen.items())], "fehler": fehler,
            "feldfehler": feldfehler}


def ansicht(root, heute=None):
    """Alles fuer die Oberflaeche (GET /finanzen). Nie werfen."""
    try:
        f = finanzen(root, heute)
        v = verbindungen(root, f["zeilen"])
        wartet = [{"quelle": "Finanzen", "name": z["anbieter"], "status": z["status"], "kurz": z["notiz"][:180]}
                  for z in f["zeilen"] if z["status"] in WARTET]   # auch Dubletten: Wartendes nie verstecken
        wartet += [{"quelle": "Verbindungen", "name": z["name"], "status": z["status"], "kurz": z["notiz"][:180]}
                   for g in v["gruppen"] for z in g["zeilen"] if z["status"] in WARTET]
        return {"status": "ok", "zeit": betrieb.now().isoformat(), "finanzen": f, "verbindungen": v,
                "wartet_auf_patron": wartet,
                "hinweis": "Nur lesen. Betrag, Währung und Rhythmus stehen seit F-18 als Felder im Register "
                           "(aus Preis/Intervall abgeleitet, gekennzeichnet); EUR und USD werden nicht umgerechnet. "
                           "Dubletten zählen einmal."}
    except Exception as fehler:  # die Ansicht stuerzt nie
        return {"status": "fehler", "text": "Finanzansicht nicht berechenbar: %s" % type(fehler).__name__}


if __name__ == "__main__":
    print(json.dumps(ansicht(Path(__file__).resolve().parent), ensure_ascii=False, indent=1)[:3000])
