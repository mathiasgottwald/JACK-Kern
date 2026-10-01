#!/usr/bin/env python3
"""Was die Maske zeigt: Anordnung der Kaesten, Markenlage, Agentenlage, Freigaben.

Block 5, 16.09.2026. Grundsatz dieses Moduls: **keine Zahl ohne Quelle.**
Jede Angabe traegt das Feld "quelle" mit der Datei, aus der sie stammt. Was
sich aus den vorhandenen Dateien nicht ableiten laesst, heisst hier "unbekannt"
und wird nie geschaetzt.

Kein Design, kein HTML - nur Daten.
"""
import collections
import datetime as dt
import json
import os
import re
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path

import jack_betrieb as betrieb

ANORDNUNG = "oberflaeche.json"
MARKENSPERREN = "markensperren.json"
PROTOKOLL = "oberflaeche.jsonl"

# Die Anordnung beim allerersten Start. Ab dann gilt, was in der Datei steht.
# Reihenfolge und Seite aendert der Patron durch EINE Zeile in dieser Datei.
STANDARD = {
    "schema": 5,
    "hinweis": ("Reihenfolge, Seite und Sichtbarkeit je Kasten. 'seite' ist links "
                "oder rechts, 'rang' sortiert von oben nach unten, 'sichtbar' auf "
                "false blendet einen Kasten aus, ohne ihn zu verlieren. Eine Zeile "
                "aendern genuegt; kein Neustart des Dienstes noetig, die Maske "
                "liest neu. 'zu' wird seit Block 7e (16.09.2026) NICHT MEHR "
                "GELESEN: in der Leiste ist jeder Kasten immer ein Streifen, und "
                "ein Klick darauf legt die Vollansicht in die rechte Spalte. Das "
                "Feld darf stehen bleiben, es hat keine Wirkung mehr."),
    # Seit Block 5c (16.09.2026) stehen ALLE Kaesten links in einer schmalen
    # Leiste; rechts liegt die Buehne. Das Feld "seite" bleibt erhalten, damit
    # ein Kasten spaeter wieder nach rechts gestellt werden kann.
    "kaesten": [
        # F-86 (29.09.2026): die neun Bereiche des Patrons zuerst, dann die uebrigen - jeder genau einmal.
        {"id": "uebersicht", "titel": "Übersicht", "seite": "links", "rang": 1, "sichtbar": True},
        {"id": "freigaben", "titel": "Freigaben", "seite": "links", "rang": 2, "sichtbar": True},
        {"id": "email", "titel": "Postfach", "seite": "links", "rang": 3, "sichtbar": True},
        {"id": "termine", "titel": "Termine", "seite": "links", "rang": 4, "sichtbar": True},
        {"id": "marken", "titel": "Marken", "seite": "links", "rang": 5, "sichtbar": True},
        {"id": "social", "titel": "Social", "seite": "links", "rang": 6, "sichtbar": True},
        {"id": "hausaufgaben", "titel": "Hausaufgaben & Erinnerungen", "seite": "links", "rang": 7, "sichtbar": True},
        {"id": "kosten", "titel": "Kosten", "seite": "links", "rang": 8, "sichtbar": True},
        {"id": "system", "titel": "System", "seite": "links", "rang": 9, "sichtbar": True},
        {"id": "gespraech", "titel": "Gespräch", "seite": "links", "rang": 10, "sichtbar": True},
        {"id": "auftraege", "titel": "Aufträge", "seite": "links", "rang": 11, "sichtbar": True},
        {"id": "agenten", "titel": "Agenten", "seite": "links", "rang": 12, "sichtbar": True},
        {"id": "wissen", "titel": "Wissen", "seite": "links", "rang": 13, "sichtbar": True},
        {"id": "verbindungen", "titel": "Verbindungen", "seite": "links", "rang": 14, "sichtbar": True},
        {"id": "mitarbeiter", "titel": "Mitarbeiter", "seite": "links", "rang": 15, "sichtbar": True},
        {"id": "hilfe", "titel": "Hilfe", "seite": "links", "rang": 16, "sichtbar": True},      # NACHT kern 2 Nr. 2 (Bedienhandbuch, nur Lesen)
    ],
    # Block 6b: Die Breite der drei Spalten steht hier, nicht im Code.
    # Die Mitte traegt den Sprachkern und faellt nie unter 280 Pixel.
    "spalten": {"links": 24, "mitte": 32, "rechts": 44},
    "zu": {},
}


# ------------------------------------------------------------------ Grundlagen
def _area(root):
    return betrieb.area(root)


def _lesen(p, ersatz):
    try:
        if p.is_symlink() or p.stat().st_size > 1_000_000:
            return ersatz
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ersatz


def _schreiben(p, wert):
    tmp = p.with_suffix(p.suffix + ".neu")
    tmp.write_text(json.dumps(wert, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def protokoll(root, art, **felder):
    """Block 16b (1.1): Ein Testlauf ist nie eine Entscheidung des Patrons.

    Beginnt die Datei mit TEST_ oder meldet der Aufrufer test=True, traegt die
    Zeile `test: true` und `von: "Test"`. Bestehende Zeilen werden NICHT
    umgeschrieben - das Protokoll ist ein Protokoll. Die Leseseite filtert.
    """
    try:
        e = {"zeit": betrieb.now().isoformat(), "art": art}
        e.update(felder)
        if e.get("test") is True or str(e.get("datei") or "").startswith("TEST_"):
            e["test"] = True
            e["von"] = "Test"
        else:
            e.pop("test", None)
        with (_area(root) / PROTOKOLL).open("a", encoding="utf-8") as d:
            d.write(json.dumps(e, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ------------------------------------------------------------------ Anordnung
def anordnung(root):
    """Liest betrieb/oberflaeche.json. Fehlt sie, wird der Standard angelegt."""
    p = _area(root) / ANORDNUNG
    if not p.exists():
        _schreiben(p, STANDARD)
        return json.loads(json.dumps(STANDARD))
    daten = _lesen(p, None)
    if not isinstance(daten, dict) or not isinstance(daten.get("kaesten"), list):
        return json.loads(json.dumps(STANDARD))
    standard = {k["id"]: k for k in STANDARD["kaesten"]}
    kaesten = []
    for k in daten["kaesten"]:
        if not isinstance(k, dict) or k.get("id") not in standard:
            continue
        kaesten.append({"id": k["id"],
                        "titel": str(k.get("titel") or k["id"]),
                        "seite": "links" if k.get("seite") == "links" else "rechts",
                        "rang": int(k.get("rang") or 99),
                        # Fehlt das Feld (alte Datei aus Block 5), gilt sichtbar.
                        "sichtbar": bool(k.get("sichtbar", True))})
    # Ein Kasten, der in der Datei fehlt, geht nicht verloren - er kommt ans Ende.
    haben = {k["id"] for k in kaesten}
    for k in STANDARD["kaesten"]:
        if k["id"] not in haben:
            kaesten.append(dict(k, rang=99))
    kaesten.sort(key=lambda k: (k["seite"], k["rang"], k["id"]))
    zu = daten.get("zu") if isinstance(daten.get("zu"), dict) else {}
    zu = {k: bool(v) for k, v in zu.items() if k in standard}
    spalten = daten.get("spalten") if isinstance(daten.get("spalten"), dict) else {}
    raus = {}
    for name, ersatz in (("links", 24), ("mitte", 32), ("rechts", 44)):
        try:
            wert = float(spalten.get(name, ersatz))
        except (TypeError, ValueError):
            wert = ersatz
        raus[name] = max(10.0, min(70.0, wert))
    # Zusammen immer 100 Prozent - sonst klafft eine Luecke oder es ueberlappt.
    summe = sum(raus.values()) or 100.0
    raus = {k: round(v * 100.0 / summe, 2) for k, v in raus.items()}
    return {"schema": 5, "hinweis": daten.get("hinweis", STANDARD["hinweis"]),
            "kaesten": kaesten, "zu": _akkordeon(kaesten, zu),
            "spalten": raus, "datei": str(p)}


def _akkordeon(kaesten, zu):
    """Je Seite ist hoechstens EIN Kasten offen.

    Entscheidung des Patrons vom 16.09.2026: ein aufgeklappter Kasten bekommt die
    ganze Hoehe seiner Seite. Diese Regel wird hier durchgesetzt und nicht nur in
    der Maske - dann stimmt sie auch, wenn jemand die Datei von Hand aendert.
    Bei mehreren offenen Kaesten auf einer Seite gewinnt der oberste.
    """
    raus = dict(zu)
    for seite in ("links", "rechts"):
        reihe = [k for k in kaesten if k["seite"] == seite and k.get("sichtbar", True)]
        offen = [k["id"] for k in reihe if not raus.get(k["id"], False)]
        for kennung in offen[1:]:
            raus[kennung] = True
    # Ein unsichtbarer Kasten gilt als zugeklappt; er belegt keine Seite.
    for k in kaesten:
        if not k.get("sichtbar", True):
            raus[k["id"]] = True
    return raus


def klapp_setzen(root, kasten, zu):
    """Merkt sich je Kasten, ob er zugeklappt ist. Ueberlebt jeden Neustart."""
    p = _area(root) / ANORDNUNG
    if not p.exists():
        _schreiben(p, STANDARD)
    daten = _lesen(p, json.loads(json.dumps(STANDARD)))
    if not isinstance(daten, dict):
        daten = json.loads(json.dumps(STANDARD))
    bekannt = {k["id"] for k in STANDARD["kaesten"]}
    if kasten not in bekannt:
        raise ValueError("Unbekannter Kasten")
    stand = daten.get("zu")
    if not isinstance(stand, dict):
        stand = {}
    stand[kasten] = bool(zu)
    if not zu:
        # Akkordeon: wer aufklappt, schliesst die anderen seiner Seite.
        gelesen = anordnung(root)
        meine = next((k for k in gelesen["kaesten"] if k["id"] == kasten), None)
        if meine:
            for k in gelesen["kaesten"]:
                if k["id"] != kasten and k["seite"] == meine["seite"]:
                    stand[k["id"]] = True
    daten["zu"] = stand
    _schreiben(p, daten)
    return {"ok": True, "kasten": kasten, "zu": bool(zu), "stand": stand}


# ------------------------------------------------------------------ Auftragsköpfe
def _kopf(text):
    kopf, zeilen = {}, text.splitlines()
    if not zeilen or zeilen[0].strip() != "---":
        return kopf
    for zeile in zeilen[1:]:
        if zeile.strip() == "---":
            break
        schluessel, trenner, wert = zeile.partition(":")
        if trenner:
            kopf[schluessel.strip().lower()] = wert.strip()
    return kopf


def _auftragsdateien(root, ordner):
    ziel = Path(root) / "auftraege" / ordner
    if not ziel.is_dir():
        return []
    raus = []
    for f in sorted(ziel.glob("*.md")):
        # F-77: ein fuehrender Unterstrich ist im ganzen Haus die Vorlagen-Konvention (_VORLAGE_...), nie
        # eine echte Karte - sonst erscheint z. B. _VORLAGE_FREIGABEKARTE_v2.md faelschlich im Dashboard.
        if (f.is_symlink() or f.name.lower().startswith("readme") or f.name.startswith("_")
                or re.search(r"\.(bak|vor_[^.]*)(\.|$)", f.name, re.I)):
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        raus.append((f, _kopf(text), text))
    return raus


def _marke_von(kopf, datei):
    m = (kopf.get("marke") or "").strip()
    return m or "HOLDING"


def _hat_problem(kopf, text):
    """Ein PROBLEM ist belegt, nicht geraten: verbrauchte Versuche oder ein
    ausdruecklicher PROBLEM-Vermerk im Text."""
    try:
        if int(kopf.get("versuch") or 0) >= 2:
            return True, "Der Auftrag wurde schon zweimal versucht und ist nicht durchgelaufen"
    except ValueError:
        pass
    if re.search(r"^\s*(##\s*Problem|PROBLEM:)", text, re.M):
        return True, "PROBLEM-Vermerk im Auftragstext"
    return False, ""


def _ergebnissatz(text):
    """Ein Satz aus dem Abschnitt Ergebnis - nie erfunden, nur zitiert."""
    treffer = re.search(r"^##+\s*Ergebnis\s*$(.+?)(^##\s|\Z)", text, re.M | re.S)
    if not treffer:
        treffer = re.search(r"^##+\s*Status\s*$(.+?)(^##\s|\Z)", text, re.M | re.S)
    if not treffer:
        return ""
    rumpf = re.sub(r"[*_`|#>]", " ", treffer[1])
    rumpf = re.sub(r"\s+", " ", rumpf).strip()
    satz = re.split(r"(?<=[.!?])\s", rumpf)[0] if rumpf else ""
    return satz[:200]


# ------------------------------------------------------------------ Markensperren
def sperren_lesen(root):
    return _lesen(_area(root) / MARKENSPERREN, {})


def marke_gesperrt(root, marke):
    e = sperren_lesen(root).get(marke)
    return bool(e and e.get("zustand") == "gestoppt")


def marken_steuern(root, marke, befehl, von="Patron"):
    """PAUSE, WEITER, STOPP je Marke - wirkt auf ALLE Auftraege dieser Marke.

    PAUSE/WEITER greifen ueber den Planer auf jeden laufenden Auftrag der Marke
    durch. STOPP setzt zusaetzlich eine Sperre: keine neuen Laeufe mehr, und die
    laufenden werden sauber beendet (derselbe Weg wie der Stopp-Knopf je Auftrag,
    also SIGTERM mit Nachfrist, kein hartes Abwuergen).
    """
    import jack_planer
    if befehl not in ("pause", "weiter", "stopp", "frei"):
        raise ValueError("Unbekannter Befehl")
    marke = str(marke or "").strip()
    if not marke or len(marke) > 80 or not re.fullmatch(r"[A-Za-z0-9_.\- ]+", marke):
        raise ValueError("Unzulaessiger Markenname")

    sperren = sperren_lesen(root)
    zustand = jack_planer.zustand_lesen()
    betroffen = [d for d, l in zustand.get("laeufe", {}).items()
                 if (l.get("marke") or "HOLDING") == marke]

    wirkungen = []
    if befehl == "stopp":
        sperren[marke] = {"zustand": "gestoppt", "seit": betrieb.now().isoformat(), "von": von}
        _schreiben(_area(root) / MARKENSPERREN, sperren)
        for datei in betroffen:
            wirkungen.append(jack_planer.steuern("stopp", datei, von=von).get("wirkung", ""))
        wirkung = ("Marke %s gesperrt: keine neuen Auftraege. %d laufende beendet."
                   % (marke, len(betroffen)))
    elif befehl == "frei":
        sperren.pop(marke, None)
        _schreiben(_area(root) / MARKENSPERREN, sperren)
        wirkung = "Sperre fuer %s aufgehoben. Neue Auftraege sind wieder moeglich." % marke
    else:
        for datei in betroffen:
            wirkungen.append(jack_planer.steuern(befehl, datei, von=von).get("wirkung", ""))
        if befehl == "pause":
            sperren[marke] = {"zustand": "pausiert", "seit": betrieb.now().isoformat(), "von": von}
        else:
            sperren.pop(marke, None)
        _schreiben(_area(root) / MARKENSPERREN, sperren)
        wort = "angehalten" if befehl == "pause" else "fortgesetzt"
        wirkung = "Marke %s: %d laufende Auftraege %s." % (marke, len(betroffen), wort)
    protokoll(root, "marken_steuern", marke=marke, befehl=befehl, von=von,
              betroffen=betroffen, wirkung=wirkung)
    return {"ok": True, "marke": marke, "befehl": befehl, "wirkung": wirkung,
            "betroffen": betroffen, "einzeln": wirkungen}


# ------------------------------------------------------------------ Markenlage
MARKEN_STANDARD = {"marken": [
    {"id": i, "status": "aktiv", "aliase": []} for i in
    ("PATRONOS", "CASHFLOW_KOMPASS", "GOTT_WALD", "MATHIAS_GOTTWALD", "MEISTERWERK", "ANALOG_WERKE", "PLHH", "YIG_CARE")] + [
    {"id": i, "status": "ruhend", "aliase": []} for i in ("STEPHAN_MANDLIK", "give1get1", "Goldene-Buecher")],
    "keine_marken": ["HOLDING", "JACK", "PRIVAT", "alle"]}


def _mnorm(name):
    return re.sub(r"[\s_\-]+", "", str(name or "")).casefold()


def marken_konfiguration(root):
    """F-42: betrieb/marken.json (die elf echten Marken, Reihenfolge, Status); fehlt sie, gilt MARKEN_STANDARD."""
    k = _lesen(_area(root) / "marken.json", None)
    if not isinstance(k, dict) or not isinstance(k.get("marken"), list) or not k["marken"]:
        return MARKEN_STANDARD
    return k


def markenlage(root, vault=None):
    """Je Marke: Ampel aus echten Betriebsdaten, Zaehler und erledigte Auftraege.

    GRUEN  mindestens ein Auftrag laeuft oder wartet in der Warteschlange
    GELB   Auftraege vorhanden, aber keiner laeuft - oder ein PROBLEM liegt vor
    ROT    der Patron hat die Marke gestoppt
    WEISS  fuer diese Marke wurde noch nie ein Auftrag erteilt
    """
    import jack_planer
    root = Path(root)
    vault = Path(vault) if vault else root.parent.parent

    zustand = jack_planer.zustand_lesen()
    laufende = collections.Counter()
    for l in zustand.get("laeufe", {}).values():
        laufende[l.get("marke") or "HOLDING"] += 1

    gruppen = {}
    for ordner in ("offen", "laeuft", "freigabe", "erledigt"):
        for datei, kopf, text in _auftragsdateien(root, ordner):
            marke = _marke_von(kopf, datei)
            eintrag = gruppen.setdefault(marke, {"offen": [], "laeuft": [], "freigabe": [],
                                                 "erledigt": [], "problem": []})
            problem, grund = _hat_problem(kopf, text)
            satz = {"datei": datei.name,
                    "titel": (kopf.get("auftrag") or datei.stem).replace("_", " "),
                    "erteilt": kopf.get("erteilt", ""),
                    "ergebnis": _ergebnissatz(text) if ordner == "erledigt" else ""}
            eintrag[ordner].append(satz)
            if problem and ordner != "erledigt":
                eintrag["problem"].append({"datei": datei.name, "grund": grund})

    # F-42: nur die echten Marken aus betrieb/marken.json, Schreibvarianten zu EINER Marke zusammengefuehrt.
    konf = marken_konfiguration(root)
    kanon = {}
    for eintrag in konf["marken"]:
        kanon[_mnorm(eintrag["id"])] = eintrag["id"]
        for alias in eintrag.get("aliase") or []:
            kanon[_mnorm(alias)] = eintrag["id"]
    keine = {_mnorm(x) for x in konf.get("keine_marken") or []}
    leer = lambda: {"offen": [], "laeuft": [], "freigabe": [], "erledigt": [], "problem": []}
    zusammen, ausserhalb = {}, collections.Counter()
    for roh, g in gruppen.items():
        ziel = kanon.get(_mnorm(roh))
        if not ziel:
            ausserhalb[roh] += sum(len(v) for v in g.values())
            continue
        z = zusammen.setdefault(ziel, leer())
        for schluessel, liste in g.items():
            z[schluessel] += liste
    gruppen = zusammen
    laufende_kanon = collections.Counter()
    for roh, n in laufende.items():
        if kanon.get(_mnorm(roh)):
            laufende_kanon[kanon[_mnorm(roh)]] += n
    laufende = laufende_kanon
    ordner_marken = []
    verzeichnis = vault / "00_Marken"
    if verzeichnis.is_dir():
        ordner_marken = sorted(p.name for p in verzeichnis.iterdir() if p.is_dir())
    nicht_zugeordnet = [o for o in ordner_marken if not kanon.get(_mnorm(o)) and _mnorm(o) not in keine]
    sperren = {}
    for roh, s in sperren_lesen(root).items():
        ziel = kanon.get(_mnorm(roh))
        if ziel and (ziel not in sperren or s.get("zustand") == "gestoppt"):
            sperren[ziel] = s
    status_je = {e["id"]: e.get("status", "aktiv") for e in konf["marken"]}
    raus = []
    for marke in [e["id"] for e in konf["marken"]]:
        g = gruppen.get(marke, leer())
        laeuft_jetzt = laufende.get(marke, 0)
        wartend = len(g["offen"])
        gesamt = wartend + len(g["laeuft"]) + len(g["freigabe"]) + len(g["erledigt"])
        sperre = sperren.get(marke, {})
        if sperre.get("zustand") == "gestoppt":
            ampel, grund = "rot", "vom Patron gestoppt am " + str(sperre.get("seit", ""))[:16]
        elif laeuft_jetzt or wartend:
            ampel = "gruen"
            grund = ("%d laufend, %d in der Warteschlange" % (laeuft_jetzt, wartend))
        elif g["problem"]:
            ampel, grund = "gelb", "PROBLEM: " + g["problem"][0]["grund"]
        elif gesamt:
            ampel, grund = "gelb", "Aufträge vorhanden, keiner läuft"
        else:
            ampel, grund = "weiss", "für diese Marke wurde noch nie ein Auftrag erteilt"
        raus.append({
            "marke": marke,
            "kuerzel": _kuerzel(marke),
            "ampel": ampel,
            "grund": grund,
            "zustand": sperre.get("zustand", "frei"),
            "laeuft": laeuft_jetzt,
            "wartend": wartend,
            "freigabe": len(g["freigabe"]),
            "probleme": len(g["problem"]),
            "erledigt_anzahl": len(g["erledigt"]),
            "erledigt": sorted(g["erledigt"], key=lambda x: x["erteilt"], reverse=True)[:25],
            "aktiv": bool(laeuft_jetzt or wartend),
            "status": status_je.get(marke, "aktiv"),
        })
    # F-42: Reihenfolge wie in betrieb/marken.json (aktive Marken zuerst, ruhende zuletzt), nicht nach Tagesarbeit.
    return {"zeit": betrieb.now().isoformat(), "marken": raus, "reihenfolge": "konfiguration",
            "nicht_zugeordnet": nicht_zugeordnet, "ausserhalb": dict(ausserhalb),
            "quelle": "betrieb/marken.json (11 Marken), auftraege/{offen,laeuft,freigabe,erledigt}/, "
                      "betrieb/laufende.json, betrieb/markensperren.json"}


def _kuerzel(marke):
    teile = re.split(r"[_\-\s]+", marke)
    if len(teile) >= 2:
        return (teile[0][:1] + teile[1][:1]).upper()
    return marke[:2].upper()


# ------------------------------------------------------------------ Agentenlage
def _betrag(wert):
    """Ein gemeldeter Betrag - oder None. Nie geschaetzt, nie auf null gesetzt."""
    if wert is None or isinstance(wert, bool):
        return None
    try:
        zahl = Decimal(str(wert))
    except (InvalidOperation, ValueError):
        return None
    return float(zahl) if zahl.is_finite() and zahl >= 0 else None


def _rollen(root):
    try:
        daten = json.loads((Path(root) / "arbeiter_agenten.json").read_text(encoding="utf-8"))
        return daten if isinstance(daten, dict) else {}
    except (OSError, ValueError):
        return {}


def _zurueckweisungen(root, rolle):
    p = Path(root) / "agenten" / "99_Erfahrung" / (rolle + ".md")
    try:
        return len(re.findall(r"^##\s*Zur[üu]ckweisung", p.read_text(encoding="utf-8"), re.M))
    except OSError:
        return None


def _kostenzahlen(root, kostensicht, heute_gemeldet_usd):
    """F-34: die drei Kostenzahlen mit Beschriftung, Quelle und Rohwert. Eine Quelle je Zahl:
    Heute + Tagesdeckel = jack_grenzen.verbrauch (gemeldet + geschaetzt); Seit = jack_kosten.summary."""
    from decimal import Decimal
    import jack_grenzen
    v = jack_grenzen.verbrauch(root)
    tag = Decimal(str(v.get("tag_usd") or 0))
    grenze = (jack_grenzen.lesen(root) or {}).get("budget_usd_je_tag")
    seit = str(kostensicht.get("erfassung_seit") or "")[:10]
    try:
        seit_text = "Seit %s.%s." % (seit[8:10], seit[5:7])
    except Exception:
        seit_text = "Seit Beginn"
    return {
        "heute": {"beschriftung": "Heute", "usd": float(tag), "roh": str(v.get("tag_usd")),
                  "gemeldet_usd": float(Decimal(str(v.get("tag_usd_gemeldet") or 0))),
                  "geschaetzt_usd": float(Decimal(str(v.get("tag_usd_geschaetzt") or 0))),
                  "quelle": "jack_grenzen.verbrauch (tag_usd = gemeldet + geschaetzt)"},
        "tagesdeckel": {"beschriftung": "Tagesdeckel", "usd": float(tag), "grenze_usd": grenze,
                        "roh": str(v.get("tag_usd")), "quelle": "jack_grenzen.verbrauch / budget_usd_je_tag"},
        "seit": {"beschriftung": seit_text, "usd": float(Decimal(str(kostensicht.get("usd_gemeldet") or 0))),
                 "geschaetzt_usd": float(Decimal(str(kostensicht.get("usd_geschaetzt") or 0))),
                 "roh": str(kostensicht.get("usd_gemeldet")), "seit": seit,
                 "quelle": "jack_kosten.summary (usd_gemeldet; Schaetzung getrennt)"},
    }


# ------------------------------------------------------------------ F-40: PM-Postfach und Netz/Laeufer
PM_KANAELE = ("kern", "cashflow", "gruendung", "bewerbungen", "inhalt", "patronos", "sprache", "social")   # F-86: die Claude-Code-Kanaele (F-111: + social)
# Praefix der Meldungen/Rueckfragen je Kanal (README_PM_POSTFACH): F-, S-, P-, VA- (cashflow); logos/ux ohne festes Praefix.
PM_PRAEFIX = {"kern": "F-", "sprache": "S-", "patronos": "P-", "cashflow": "VA-",
              "gruendung": "G-", "bewerbungen": "B-", "inhalt": "I-", "social": "SM-"}


# ------------------------------------------------------------------ F-86: EIN Schalter je Kanal (System-Tabelle)
# Pause = der Kanal nimmt keinen NEUEN Auftrag auf: postfach_schleife.sh wartet weiter, der Waechter stoesst nicht an.
# Eine laufende Arbeit endet normal - nichts wird abgebrochen, nichts geloescht. Marker: betrieb/kanal_pause/<kanal>.
def _pause_ordner(root):
    return _area(root) / "kanal_pause"


def kanal_pause(root, kanal):
    """(pausiert, grund) - Marker des Patrons ODER 'pausiert' im Waechter-Laeufer (z. B. Sprache seit F-75)."""
    if not re.fullmatch(r"[a-z_]{2,20}", str(kanal or "")):
        return False, ""
    m = _pause_ordner(root) / kanal
    if m.is_file() and not m.is_symlink():
        return True, "vom Patron pausiert"
    konf = _lesen(_area(root) / "netzwaechter.json", {})
    for l in konf.get("laeufer") or []:
        if l.get("kanal") == kanal and l.get("pausiert"):
            return True, str(l.get("grund") or "pausiert")
    return False, ""


def kanal_schalter(root, kanal, pausiert, von="Patron"):
    """Setzt oder loest die Pause EINES Kanals. Nur die sieben bekannten Kanaele; nie ein Dienst."""
    if kanal not in PM_KANAELE:
        return {"ok": False, "meldung": "Unbekannter Kanal."}
    jetzt_pausiert, grund = kanal_pause(root, kanal)
    ordner = _pause_ordner(root)
    marker = ordner / kanal
    if pausiert:
        ordner.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({"seit": betrieb.now().isoformat(), "von": von}, ensure_ascii=False), encoding="utf-8")
        satz = "Kanal %s pausiert: nimmt keinen neuen Auftrag auf, laufende Arbeit endet normal." % kanal
    else:
        if marker.is_file() and not marker.is_symlink():
            marker.unlink()
        rest, grund2 = kanal_pause(root, kanal)
        satz = ("Kanal %s läuft wieder." % kanal) if not rest else "Kanal %s bleibt pausiert (%s)." % (kanal, grund2)
    try:
        with (_area(root) / "kanal_schalter.log").open("a", encoding="utf-8") as f:
            f.write("%s\t%s\t%s\t%s\n" % (betrieb.now().isoformat(), kanal, "pausiert" if pausiert else "fortgesetzt", von))
    except OSError:
        pass
    return {"ok": True, "kanal": kanal, "pausiert": kanal_pause(root, kanal)[0], "meldung": satz}


def _md_namen(ordner):
    try:
        return sorted(p.name for p in Path(ordner).iterdir()
                      if p.is_file() and not p.is_symlink() and p.name.endswith(".md")
                      and not p.name.startswith(".") and p.name.lower() != "readme.md")
    except OSError:
        return []


def _kopfzeile(pfad):
    try:
        erste = ""
        for z in Path(pfad).read_text(encoding="utf-8", errors="replace").splitlines():
            if z.startswith("#"):
                return z.lstrip("# ").strip()[:120]
            if not erste and z.strip() and z.strip() != "---":
                erste = z.strip()[:120]
        if erste:
            return erste
    except OSError:
        pass
    return Path(pfad).stem


def _sicher(fn, root):
    """F-40: eine Stoerung in einer Zusatzkarte darf die Agentenlage nie kippen."""
    try:
        return fn(root)
    except Exception as fehler:
        return {"fehler": type(fehler).__name__ + ": " + str(fehler)[:120]}


def pm_postfach(root):
    """F-40: je PM-Kanal offene Auftraege, Zustand (aus Herzschlag/Waechter), offene Rueckfragen; dazu 'Wartet auf dich'.
    Nur lesen. Quellen: auftraege/pm_ausgang/<kanal>/, betrieb/herzschlag/<kanal>.json, betrieb/netz.json,
    abnahme/pm_eingang/*_FRAGE.md (beantwortete tragen '_beantwortet' im Namen), auftraege/pm_ausgang/wartet_patron/."""
    root = Path(root)
    ausgang = root / "auftraege" / "pm_ausgang"
    fragen = [n for n in _md_namen(root / "abnahme" / "pm_eingang") if n.endswith("_FRAGE.md")]   # beantwortete heissen ..._FRAGE_beantwortet.md
    netz = _lesen(_area(root) / "netz.json", {})
    jetzt = time.time()
    kanaele = []
    for k in PM_KANAELE:
        offen = _md_namen(ausgang / k)
        herz = _lesen(_area(root) / "herzschlag" / (k + ".json"), None)
        alter = None
        if herz and herz.get("epoch"):
            try:
                alter = max(0, int(jetzt - float(herz["epoch"])))
            except (TypeError, ValueError):
                alter = None
        wnet = (netz.get("laeufer") or {}).get("postfach_" + k) or {}
        if wnet.get("status") in ("haengt", "beendet", "steht_ohne_herzschlag", "steht_trotz_auftrag", "stumm"):
            zustand, satz = "steht", "Wächter: " + str(wnet.get("grund") or wnet.get("status"))
        elif alter is not None and alter <= 600:
            zustand = "arbeitet" if offen else "wartet"
            satz = "Herzschlag vor %d s" % alter
        elif alter is not None and wnet.get("status") in ("ok", "ok_ohne_herzschlag"):
            zustand, satz = "arbeitet", "kein Herzschlag seit %d Min, Prozess lebt (Wächter ok)" % (alter // 60)
        elif alter is not None:
            zustand, satz = "steht", "kein Herzschlag seit %d Min" % (alter // 60)
        else:
            zustand, satz = "unbekannt", "noch kein Herzschlag"
        pf = PM_PRAEFIX.get(k)
        pausiert, pgrund = kanal_pause(root, k)
        if pausiert:
            zustand, satz = "pausiert", "Pause: " + pgrund
        kanaele.append({"kanal": k, "offen": len(offen), "auftraege": offen[:5], "zustand": zustand, "satz": satz,
                        "pausiert": pausiert, "pausiert_vom_patron": pgrund == "vom Patron pausiert",
                        "herzschlag_alter_s": alter, "herz_auftrag": (herz or {}).get("auftrag") or "",
                        "rueckfragen": [n for n in fragen if pf and n.startswith(pf)],
                        "quelle": "auftraege/pm_ausgang/%s/ · betrieb/herzschlag/%s.json" % (k, k)})
    wartet = [{"datei": n, "titel": _kopfzeile(ausgang / "wartet_patron" / n)} for n in _md_namen(ausgang / "wartet_patron")]
    return {"zeit": betrieb.now().isoformat(), "kanaele": kanaele, "rueckfragen_gesamt": fragen, "wartet_auf_dich": wartet,
            "quelle": "auftraege/pm_ausgang/, abnahme/pm_eingang/, betrieb/herzschlag/, betrieb/netz.json (nur lesen)"}


def netz_laeufer(root):
    """F-40: Ampel je Dauerlaeufer aus betrieb/netz.json (Netz-Waechter F-28/F-36), letzter Ausfall, Neustarts letzte Stunde."""
    netz = _lesen(_area(root) / "netz.json", {})
    if not netz:
        return {"stand": "fehlt", "laeufer": [], "quelle": "betrieb/netz.json"}
    try:
        alter = int((betrieb.now() - dt.datetime.fromisoformat(netz["zeit"])).total_seconds())
    except (KeyError, ValueError, TypeError):
        alter = None
    rot = ("steht", "haengt", "beendet", "steht_ohne_herzschlag", "steht_trotz_auftrag", "stumm")
    laeufer = []
    for name, v in (netz.get("laeufer") or {}).items():
        st = v.get("status")
        ampel = "rot" if st in rot else ("gruen" if st in ("ok", "ok_ohne_herzschlag") else "gelb")
        laeufer.append({"name": name, "status": st, "ampel": ampel, "grund": v.get("grund") or "",
                        "massnahme": v.get("massnahme") or "",
                        "neustarts_letzte_stunde": (netz.get("neustarts_letzte_stunde") or {}).get(name, 0)})
    return {"stand": "ok" if alter is not None and alter <= 300 else "veraltet", "alter_s": alter, "zeit": netz.get("zeit"),
            "online": bool(netz.get("online")), "seit": netz.get("seit"), "letzter_ausfall": netz.get("letzter_ausfall"),
            "neustarts_letzte_stunde": netz.get("neustarts_letzte_stunde") or {}, "laeufer": laeufer,
            "ziele": [{"ziel": z.get("ziel"), "ok": z.get("ok"), "ms": z.get("ms")} for z in (netz.get("ziele") or [])],
            "quelle": "betrieb/netz.json"}


def agentenlage(root):
    """Wer arbeitet, wie oft, wie teuer, wie gut - alles aus vorhandenen Dateien.

    Wichtig und bewusst so: die Kosten je ROLLE sind aus den vorhandenen Daten
    NICHT ableitbar. Ein Arbeiterlauf meldet EINEN Betrag fuer den ganzen Lauf -
    ausfuehrende Chefpruefung und alle Unteragenten zusammen. Dieser Betrag wird deshalb
    beim Lauf ausgewiesen und bei der Rolle als "unbekannt", nie aufgeteilt.
    """
    import jack_planer
    root = Path(root)
    heute = str(betrieb.now().date())

    # 1. Wer arbeitet JETZT
    zustand = jack_planer.zustand_lesen()
    jetzt = time.time()
    aktiv = []
    for datei, l in sorted(zustand.get("laeufe", {}).items(),
                           key=lambda x: x[1].get("nummer", 0)):
        aktiv.append({"nummer": l.get("nummer"), "auftrag": l.get("titel") or datei,
                      "datei": datei, "marke": l.get("marke") or "HOLDING",
                      "zustand": l.get("zustand", "laeuft"),
                      "laufzeit_s": round(jetzt - l.get("start_epoch", jetzt)),
                      "lebt": jack_planer.lebt(l.get("pid"), datei),
                      "motor": l.get("motor", "")})

    # 2. Starts je Rolle - eine Zeile "tool: Agent" ist ein Start
    sieben = str((betrieb.now() - dt.timedelta(days=7)).date())
    starts, starts_heute, starts_woche = (collections.Counter(), collections.Counter(),
                                          collections.Counter())
    letzter = {}
    zeilen = 0
    p = root / "arbeiter_zugriffe.jsonl"
    try:
        with p.open(encoding="utf-8") as strom:
            for zeile in strom:
                try:
                    d = json.loads(zeile)
                except ValueError:
                    continue
                zeilen += 1
                if d.get("tool") != "Agent" or d.get("entscheidung") != "allow":
                    continue
                typ = d.get("agent_typ")
                if not typ:
                    continue
                tag = str(d.get("zeit", ""))[:10]
                starts[typ] += 1
                if tag == heute:
                    starts_heute[typ] += 1
                if tag >= sieben:
                    starts_woche[typ] += 1
                letzter[typ] = d.get("zeit", "")
    except OSError:
        pass

    modelle = {}
    try:
        import jack_modelle
        modelle = jack_modelle.load(root)
    except Exception:
        modelle = {}

    rollen = []
    for name, rolle in sorted(_rollen(root).items()):
        n = starts.get(name, 0)
        abgelehnt = _zurueckweisungen(root, name)
        pruefer = "pruefer" in name
        if pruefer or not n or abgelehnt is None:
            quote, quote_text = None, "—"
        else:
            quote = max(0.0, (n - abgelehnt) / n)
            quote_text = "%d %%" % round(quote * 100)
        rollen.append({
            "rolle": name,
            "modellrolle": rolle.get("model_role", ""),
            "modell": modelle.get(rolle.get("model_role", ""), "unbekannt"),
            "werkzeuge": rolle.get("tools", []),
            "laeufe": n,
            "laeufe_heute": starts_heute.get(name, 0),
            "laeufe_woche": starts_woche.get(name, 0),
            "letzter_lauf": letzter.get(name, ""),
            "zurueckweisungen": abgelehnt,
            "erfolgsquote": quote,
            "erfolgsquote_text": quote_text,
            "kosten_usd": None,
            "kosten_text": "unbekannt",
            "kosten_grund": ("Ein Arbeiterlauf meldet einen Betrag fuer den ganzen Lauf, "
                             "nicht je Rolle. Aufteilen waere geschaetzt."),
            "nie_eingesetzt": n == 0,
            "quelle_laeufe": "arbeiter_zugriffe.jsonl (Zeilen mit tool=Agent)",
            "quelle_zurueckweisungen": "agenten/99_Erfahrung/%s.md" % name,
        })
    rollen.sort(key=lambda r: (-r["laeufe"], r["rolle"]))

    # 3. Gemeldete Betraege und separat gekennzeichnete Schaetzungen.
    import jack_kosten
    kostensicht = jack_kosten.summary(root)
    schaetzungen = {g['art']: g for g in kostensicht.get('gruppen', [])}
    arten = collections.defaultdict(lambda: {"laeufe": 0, "heute": 0, "woche": 0,
                                             "usd": 0.0, "usd_heute": 0.0,
                                             "usd_woche": 0.0, "ohne_betrag": 0,
                                             "ok": 0, "fehler": 0})
    kosten_zeilen = 0
    p = betrieb.area(root) / "kostenlaeufe.jsonl"
    try:
        with p.open(encoding="utf-8") as strom:
            for zeile in strom:
                try:
                    d = json.loads(zeile)
                except ValueError:
                    continue
                if d.get("ereignis") != "ende":
                    continue
                kosten_zeilen += 1
                a = arten[d.get("art") or "unbekannt"]
                a["laeufe"] += 1
                tag = str(d.get("zeit", ""))[:10]
                istheute = tag == heute
                istwoche = tag >= sieben
                if istheute:
                    a["heute"] += 1
                if istwoche:
                    a["woche"] += 1
                # Die Betraege stehen als Zeichenkette im Buch (Decimal-genau,
                # so legt sie jack_kosten.amount ab). Ein float-Test wuerde sie
                # alle als "unbekannt" verwerfen - genau das waere falsch.
                betrag = _betrag(d.get("usd_gemeldet"))
                if betrag is None:
                    a["ohne_betrag"] += 1
                else:
                    a["usd"] += betrag
                    if istheute:
                        a["usd_heute"] += betrag
                    if istwoche:
                        a["usd_woche"] += betrag
                if d.get("status") == "ok":
                    a["ok"] += 1
                elif d.get("status"):
                    a["fehler"] += 1
    except OSError:
        pass

    geld = []
    for name, a in sorted(arten.items(), key=lambda x: -x[1]["usd"]):
        vollstaendig = a["ohne_betrag"] == 0
        geld.append({
            "art": name, "laeufe": a["laeufe"], "laeufe_heute": a["heute"],
            "usd_geschaetzt": schaetzungen.get(name, {}).get('usd_geschaetzt'),
            "laeufe_woche": a["woche"],
            "usd": round(a["usd"], 6) if a["usd"] else (0.0 if vollstaendig else None),
            "usd_heute": round(a["usd_heute"], 6),
            "usd_woche": round(a["usd_woche"], 6),
            "usd_text": (("%.4f USD" % a["usd"]) if a["usd"] or vollstaendig else "unbekannt"),
            "ohne_betrag": a["ohne_betrag"],
            "ok": a["ok"], "fehler": a["fehler"],
            "je_erfolg": (round(a["usd"] / a["ok"], 6) if a["ok"] and a["usd"] else None),
            "je_erfolg_text": (("%.4f USD" % (a["usd"] / a["ok"])) if a["ok"] and a["usd"]
                               else "nicht berechenbar"),
            "quelle": "betrieb/kostenlaeufe.jsonl",
        })
    rang = sorted([g for g in geld if g["je_erfolg"] is not None],
                  key=lambda g: g["je_erfolg"])
    ohne_rang = [g["art"] for g in geld if g["je_erfolg"] is None]

    heute_gemeldet_usd = round(sum(g["usd_heute"] for g in geld), 6)
    # F-34: EINE Quelle fuer "Heute" und "Tagesdeckel": jack_grenzen.verbrauch (gemeldet + geschaetzt).
    # Vorher zeigte der Streifen nur das Gemeldete (4,87), der Deckel 9,14.
    kosten = _kostenzahlen(root, kostensicht, heute_gemeldet_usd)
    heute_usd = kosten["heute"]["usd"]
    heute_laeufe = sum(g["laeufe_heute"] for g in geld)
    woche_usd = round(sum(g["usd_woche"] for g in geld), 6)
    woche_laeufe = sum(g["laeufe_woche"] for g in geld)
    ohne_betrag_gesamt = sum(g["ohne_betrag"] for g in geld)
    return {
        "zeit": betrieb.now().isoformat(),
        "aktiv": aktiv,
        "rollen": rollen,
        "geld": geld,
        "rangliste": rang,
        "ohne_rangliste": ohne_rang,
        "heute_usd": heute_usd,
        "heute_gemeldet_usd": heute_gemeldet_usd,
        "kosten": kosten,
        "pm_postfach": _sicher(pm_postfach, root),
        "netz": _sicher(netz_laeufer, root),
        "heute_laeufe": heute_laeufe,
        "woche_usd": woche_usd,
        "woche_laeufe": woche_laeufe,
        "ohne_betrag_gesamt": ohne_betrag_gesamt,
        "usd_geschaetzt": kostensicht.get('usd_geschaetzt'),
        "laeufe_mit_schaetzung": kostensicht.get('laeufe_mit_schaetzung', 0),
        "agenten_starts_heute": sum(starts_heute.values()),
        "agenten_starts_woche": sum(starts_woche.values()),
        "agenten_starts_gesamt": sum(starts.values()),
        # Block 6b F1: so knapp, dass es in den Streifen passt.
        "kurz": "%d aktiv · Heute %s USD" % (len(aktiv), ("%.2f" % heute_usd).replace(".", ",")),   # F-31: A9, "USD" statt "$"
        "kurz_lang": "%d aktiv · Heute %s USD · %d Läufe heute" % (
            len(aktiv), ("%.2f" % heute_usd).replace(".", ","), heute_laeufe),
        "quellen": {
            "aktiv": "betrieb/laufende.json",
            "laeufe": "arbeiter_zugriffe.jsonl (%d Zeilen gelesen)" % zeilen,
            "geld": "betrieb/kostenlaeufe.jsonl (%d abgeschlossene Laeufe)" % kosten_zeilen,
            "rollen": "arbeiter_agenten.json und agenten/BESETZUNG.md",
            "zurueckweisungen": "agenten/99_Erfahrung/<rolle>.md",
        },
    }


# ------------------------------------------------------------------ Wissen
def wissenslage(root, vault=None):
    """Die Quellen, aus denen JACK liest - als Liste, nicht als Zahl.

    Je Quelle: Name, Art, ein Stand und die Zahl, die dazu gehoert (Zeilen,
    Eintraege, Alter). Nichts geschaetzt: was eine Datei nicht hergibt, heisst
    hier "unbekannt".
    """
    root = Path(root)
    vault = Path(vault) if vault else root.parent.parent
    jetzt = time.time()
    raus = []

    def zeilen(pfad):
        try:
            with pfad.open(encoding="utf-8", errors="replace") as strom:
                return sum(1 for _ in strom)
        except OSError:
            return None

    def alter(pfad):
        try:
            return int((jetzt - pfad.stat().st_mtime) // 86400)
        except OSError:
            return None

    for name, art, beschreibung in (
            ("VAULT_INDEX.md", "Karte der Ablage", "Wo in der Holding was liegt"),
            ("CLAUDE.md", "Identität und Grenzen", "Wer JACK ist, was er darf, was nie")):
        pfad = vault / name
        n = zeilen(pfad)
        raus.append({"name": name, "art": art, "beschreibung": beschreibung,
                     "zahl": ("%d Zeilen" % n) if n is not None else "unbekannt",
                     "alter_tage": alter(pfad), "vorhanden": pfad.is_file(),
                     "frage": "Was steht in %s?" % name,
                     "quelle": str(pfad.relative_to(vault)) if pfad.is_file() else name})

    ordner = vault / "00_Marken"
    marken = sorted(x.name for x in ordner.iterdir() if x.is_dir()) if ordner.is_dir() else []
    for marke in marken:
        ac = ordner / marke / "ACTIVE_CONTEXT.md"
        ent = ordner / marke / "entscheidungen"
        anzahl = len([d for d in ent.glob("*.md") if d.name != "README.md"]) if ent.is_dir() else 0
        stand = ""
        if ac.is_file():
            text = ac.read_text(encoding="utf-8", errors="replace")
            treffer = re.search(r"^##+\s*Stand\s*$(.+?)(^##\s|\Z)", text, re.M | re.S)
            if treffer:
                rumpf = re.sub(r"[*_`|#>]", " ", treffer[1])
                stand = re.sub(r"\s+", " ", rumpf).strip()[:160]
        raus.append({
            "name": marke.replace("_", " "), "art": "Marken-Stand",
            "beschreibung": stand or ("Noch kein Stand hinterlegt." if ac.is_file()
                                      else "Keine ACTIVE_CONTEXT.md in dieser Marke."),
            "zahl": ("%d Entscheidung%s" % (anzahl, "" if anzahl == 1 else "en")),
            "alter_tage": alter(ac) if ac.is_file() else None,
            "vorhanden": ac.is_file(),
            "frage": "Wie ist der Stand bei %s?" % marke.replace("_", " "),
            "quelle": "00_Marken/%s/ACTIVE_CONTEXT.md" % marke})

    gehirn = _area(root) / "gehirn.json"
    try:
        groesse = gehirn.stat().st_size
        gstand = "%.1f MB, zuletzt %s" % (groesse / 1_000_000,
                  dt.datetime.fromtimestamp(gehirn.stat().st_mtime).strftime("%d.%m.%Y %H:%M"))
        gok = True
    except OSError:
        gstand, gok = "Noch nicht aufgebaut.", False

    # Block 25 (Teil H1): Tageskennzahlen der Sprachsteuerung als eigener Posten.
    try:
        import jack_steuerungsprotokoll
        auszug = jack_steuerungsprotokoll.tagesauszug(root)
        raus.append({"name": "Sprachsteuerung", "art": "Tageskennzahlen",
                     "beschreibung": auszug["text"], "zahl": "%d Befehle" % auszug["anzahl"],
                     "alter_tage": 0, "vorhanden": auszug["anzahl"] > 0,
                     "frage": "Wie lief die Sprachsteuerung heute?",
                     "quelle": auszug["quelle"]})
    except Exception:
        pass

    # Ereignisanteil der letzten sieben Tage, keine Auftrags-Erfolgsquote.
    try:
        import jack_autonomie
        ergebnis = jack_autonomie.berechnen(root)
        woche = ergebnis.get("7_tage", {})
        prozent = woche.get("quote_prozent")
        raus.append({
            "name": "Aktivität ohne Rückfrage", "art": "Letzte 7 Tage",
            "beschreibung": ("Anteil erfasster Ereignisse ohne Rückfrage: automatische "
                             "Regelentscheidungen, Auftragsstarts ohne Karte, Mailbeobachtungen "
                             "und direkte Sprachbefehle. Keine Erfolgsquote; daraus folgt "
                             "nicht, dass Aufträge vollständig oder gut erledigt wurden."
                             if prozent is not None else
                             "In den letzten sieben Tagen wurden keine Ereignisse erfasst. "
                             "Eine Erfolgsquote ist damit nicht belegt."),
            "zahl": ("%s %%" % prozent) if prozent is not None else "keine Ereignisse",
            "alter_tage": 0, "vorhanden": prozent is not None,
            "frage": "Was hat JACK in den letzten sieben Tagen ohne Rückfrage getan, und welche Ergebnisse sind belegt?",
            "quelle": "betrieb/autonomie.json"})
        abschluesse = ergebnis.get('auftragsergebnisse', {})
        raus.append({'name':'Belegte Auftragsabschlüsse', 'art':'Einzelbelege und unabhängige Annahme',
                     'beschreibung':abschluesse.get('text','Noch kein Abschlussstand')+'. '+abschluesse.get('hinweis',''),
                     'zahl':str(abschluesse.get('angenommen',0)), 'alter_tage':0, 'vorhanden':True,
                     'frage':'Welche Aufträge sind vollständig belegt und unabhängig angenommen?',
                     'quelle':'betrieb/auftragsvertraege/ und betrieb/auftragsabschluesse/'})
    except Exception:
        pass

    return {"zeit": betrieb.now().isoformat(), "quellen": raus, "anzahl": len(raus),
            "gehirn": {"status": "bereit" if gok else "fehlt", "detail": gstand,
                       "quelle": "betrieb/gehirn.json"},
            "quelle": "VAULT_INDEX.md, CLAUDE.md und 00_Marken/*/ACTIVE_CONTEXT.md"}


# ------------------------------------------------------------------ Freigaben
# ═══ Block 26, Teil 2 (T2.2): Gewichtung fuer die Ein-Karte-Reihenfolge ═════
# "gefahr hoch -> Geld -> Recht -> Mitarbeiter -> Inhalt -> Vorschlaege"
# (Auftrag T2.2). gefahr=hoch schlaegt immer alles andere. Die uebrigen fuenf
# Stufen sind eine Wortlisten-Heuristik auf Titel/Etikett/Kurzsatz/Worum -
# es gibt kein einzelnes Kopffeld, das diese fuenf Kategorien traegt. Bei
# Unklarheit faellt eine Karte auf "Inhalt" (die breiteste, neutralste
# Stufe), nie auf "Vorschlaege" (die niedrigste) - eine unbekannte Karte
# wird eher zu frueh als zu spaet gezeigt.
_GEWICHT_GELD_RE = re.compile(
    r"(?i)\bgeld\b|zahlung|geldgrenze|\bbudget\b|kosten\w*grenze|rechnung|"
    r"überweis|ueberweis|\bUSD\b|\bEUR\b|\bbetrag\b")
_GEWICHT_RECHT_RE = re.compile(
    r"(?i)\brecht\w*|vertrag|contract|\blegal\b|dsgvo|\bagb\b|impressum|klausel")
_GEWICHT_MITARBEITER_RE = re.compile(r"(?i)mitarbeiter")
_GEWICHT_VORSCHLAG_RE = re.compile(
    r"(?i)vorschlag|regelaenderung|regeländerung|werkzeug|verbesserung")


def _gewicht(kopf, titel, etikett, kurz, worum):
    if (kopf.get("gefahr") or "").strip().lower() == "hoch":
        return 0
    art = (kopf.get("art") or "").strip().lower()
    if art == "kostenstufen" or _GEWICHT_GELD_RE.search(
            " ".join([titel or "", etikett or "", kurz or "", worum or ""])):
        return 1
    if art == "vertragsregister" or _GEWICHT_RECHT_RE.search(
            " ".join([titel or "", etikett or "", kurz or "", worum or ""])):
        return 2
    if art == "mitarbeitermail" or kopf.get("mitarbeiter") or _GEWICHT_MITARBEITER_RE.search(
            " ".join([titel or "", etikett or ""])):
        return 3
    if art in ("regeldateien", "verhaltensregeln", "werkzeuge") or _GEWICHT_VORSCHLAG_RE.search(
            " ".join([titel or "", etikett or ""])):
        return 5
    return 4  # Inhalt - der neutrale Regelfall


# F-77 (28.09.2026): Kartenkopf-Standard v2, siehe auftraege/freigabe/_VORLAGE_FREIGABEKARTE_v2.md.
# F-78 (29.09.2026): die Liste selbst wohnt jetzt in jack_freigaben.py (V2_PFLICHTFELDER) - das ist
# auch die Stelle, die karte_schreiben() beim Schreiben prueft. Hier nur noch ein Verweis, damit es
# nicht zwei Quellen gibt, die auseinanderlaufen koennten.
import jack_freigaben as _jack_freigaben
_V2_PFLICHTFELDER = _jack_freigaben.V2_PFLICHTFELDER


def freigabenlage(root):
    """Was in auftraege/freigabe/ liegt, mit Marke, Alter und einem Kurzsatz."""
    import jack_freigaben
    import jack_regeln
    jack_freigaben.anfragen_anlegen(root)
    offene = {e["datei"]: e for e in jack_freigaben.offene(root, inkl_wiedervorlage=True)}   # F-66: volle Sicht, Filterung unten
    jetzt = time.time()
    # Block 9c (F6f): Mailentwuerfe werden AN DER MAIL bearbeitet. Hier steht
    # nur ein Verweis - zwei Bearbeitungsstellen fuehren irgendwann zu zwei
    # verschiedenen Fassungen. Die Zuordnung Datei -> Mail kommt aus
    # betrieb/mailentwuerfe.json.
    zu_mail = {}
    try:
        import json as _json
        roh = _json.loads((betrieb.area(root) / "mailentwuerfe.json")
                          .read_text(encoding="utf-8"))
        for e in roh.values():
            if e.get("freigabedatei"):
                zu_mail[e["freigabedatei"]] = e
    except (OSError, ValueError):
        pass
    try:
        import jack_freigabe_vorgang as _v0
        _v0.fertige_abschliessen(root)                       # F-100: entschiedene Vorgangs-Karte schliesst sich, wenn alle Mails erledigt sind
    except Exception:
        pass
    try:
        _jack_freigaben.nachnummerieren(root)                # F-100 A: jede offene Karte hat eine feste Nummer (nur Kopf, mit Sicherung)
    except Exception:
        pass
    try:
        _jack_freigaben.zugangskarten_aufraeumen(root)       # F-108: Code-Karten verfallen nach 30 Min (Code wird geschwaerzt)
    except Exception:
        pass
    try:
        import jack_freigabe_vorgang
        vorgangslage = jack_freigabe_vorgang.lage(root)      # F-98: verbundene Freigaben
    except Exception:
        vorgangslage = {}
    raus = []
    for datei, kopf, text in _auftragsdateien(root, "freigabe"):
        try:
            alter_s = jetzt - datei.stat().st_mtime
        except OSError:
            alter_s = 0
        kurz = _kurzsatz(text)
        worum = _worumsatz(text)
        titel = (kopf.get("auftrag") or datei.stem).replace("_", " ")
        etikett, titel_rest = _etikett(titel)
        # Block 28: Eine feste Ueberschrift ("titel:") gilt wortgleich - sie
        # wird weder umgebaut noch am Gedankenstrich in Etikett und Rest geteilt.
        if kopf.get("titel"):
            titel = titel_rest = kopf["titel"]
            etikett = ""
        e = offene.get(datei.name, {})
        mail = zu_mail.get(datei.name) or {}
        # Block 26, Teil 2: T2.1 (Empfehlung), T2.2 (Gewicht/Reihenfolge),
        # T2.3 (Klasse - Hausaufgabe oder eine echte Entscheidung).
        try:
            klasse = jack_regeln.klasse_von(kopf)
        except Exception:
            klasse = "ein_klick"
        try:
            empfehlung = jack_regeln.empfehlung_lesen(text)
        except Exception:
            empfehlung = None
        try:
            gewicht = _gewicht(kopf, titel, etikett, kurz, worum)
        except Exception:
            gewicht = 4
        # F-77 (28.09.2026): Kartenkopf-Standard v2 - feste Pflichtfelder, roh durchgereicht (keine Erfindung,
        # keine Ableitung hier - das leistet bin/freigabekarten_v2_migration.py beim Schreiben der Karte).
        # v2_vollstaendig prueft nur, ob ALLE 13 Felder als SCHLUESSEL im Kopf stehen (auch wenn der Wert
        # woertlich "unbekannt" ist) - eine Karte ohne diese Felder ist die eigentliche Luecke.
        kopf = _jack_freigaben.an_vorgabe(kopf)       # NACHT KERN 4: `an: —` bei reinen Patron-Karten heisst `an: Patron`
        v2 = {f: kopf.get(f, "") for f in _V2_PFLICHTFELDER}
        # F-78 (29.09.2026): strenger als vorher - nicht nur "der Schluessel steht da", sondern auch
        # "der Wert ist kein Platzhalter" (kein leerer String, kein "unbekannt"/"—"). Sonst galt eine
        # Karte mit `an: —` faelschlich als vollstaendig (Fund bei jack_termine._memo_karte_anlegen).
        v2_vollstaendig = _jack_freigaben.kopf_vollstaendig(kopf)
        inhalt_ok, inhalt_grund = _inhalt_pruefung(root, kopf, text)              # Nachtrag PM 5/6/7: nichts freigeben, was man nicht sieht
        if v2_vollstaendig and not inhalt_ok:
            v2_vollstaendig = False
        # NACHT KERN 3 (PM 23:20): der Zaehler sagte bei 26 Karten nicht, WAS fehlt - jetzt nennt der Grund die Felder beim Namen.
        kopf_grund = ""
        if not v2_vollstaendig and inhalt_ok:
            fehlt = [f for f in _V2_PFLICHTFELDER if f not in kopf or _jack_freigaben.feld_ungueltig(kopf.get(f))]
            if fehlt:
                kopf_grund = "Kartenkopf: Pflichtfeld(er) fehlen oder stehen auf Platzhalter (leer, „—“, „unbekannt“): " + ", ".join(fehlt) + " — Kanal muss nachliefern."
        raus.append({
            "unvollstaendig_grund": (inhalt_grund if not inhalt_ok else kopf_grund),
            "optionen_kopf": _optionen_kopf(kopf),
            "klick_satz": _klick_satz(kopf),
            "rumpf_text": (re.sub(r"^---.*?\n---\s*", "", text or "", flags=re.S)[:20000] if "PORTAL" in str(kopf.get("ablauf") or "").upper() else ""),
            "portal_link": (kopf.get("portal_link") or (re.search(r"https?://[^\s)>\]]+", text or "") or [None])[0] or "") if "PORTAL" in str(kopf.get("ablauf") or "").upper() else "",
            "nummer": kopf.get("nummer", ""),
            "ohne_test": _ohne_test_karte(root, kopf),
            "mitarbeiter": kopf.get("mitarbeiter", ""),
            "termin": _terminblock(root, kopf, datei.name, vorgangslage),
            "vorgang": vorgangslage.get(datei.name),
            "vergleich": _vergleichstabelle(text) if vorgangslage.get(datei.name, {}).get("fuehrend") else None,
            "empfehlung_abschnitt": _ohne_technik(_abschnitt(text, "Empfehlung von JACK")) if vorgangslage.get(datei.name, {}).get("fuehrend") else "",
            "empfehlung_gliederung": _empfehlung_gliedern(text) if vorgangslage.get(datei.name, {}).get("fuehrend") else [],
            "belege": _abschnitt(text, "Quellen") if vorgangslage.get(datei.name, {}).get("fuehrend") else "",
            "v2": v2, "v2_vollstaendig": v2_vollstaendig,
            # F-108: Code-Karte (Konto & Zugang) - Code gross, Volltext, Verfall; die Maske liest nur.
            "zugang": str(kopf.get("zugang", "")).strip().lower() == "ja",
            "zugang_code": kopf.get("zugang_code", "") if str(kopf.get("zugang", "")).strip().lower() == "ja" else "",
            "zugang_verfaellt": kopf.get("verfaellt", "") if str(kopf.get("zugang", "")).strip().lower() == "ja" else "",
            "zugang_volltext": (text.split("## Volltext der Mail", 1)[1].strip()[:8000]
                                if str(kopf.get("zugang", "")).strip().lower() == "ja" and "## Volltext der Mail" in text else ""),
            "mail_postfach": mail.get("postfach", ""),
            "mail_uid": mail.get("uid"),
            "mail_absender": mail.get("an", ""),
            "datei": datei.name,
            "titel": titel,
            "klasse": klasse,
            "gewicht": gewicht,
            "empfehlung": empfehlung,
            # Block 16b (5): Art-Etikett und der erklaerende Satz kommen aus der
            # Vorlage selbst - die Maske erfindet keinen davon.
            "etikett": etikett,
            "titel_rest": titel_rest,
            "worum": worum,
            "marke": _marke_von(kopf, datei),
            "erteilt": kopf.get("erteilt", ""),
            "alter_tage": int(alter_s // 86400),
            "alter_text": _alterstext(alter_s),
            "gefahr": kopf.get("gefahr", "keine"),
            "aussen": kopf.get("gefahr") == "aussen",
            "versuch": kopf.get("versuch", "0"),
            "wartemarke": kopf.get("wartemarke", ""),
            "kurz": kurz,
            "kennung": e.get("kennung", ""),
            "kennung_status": e.get("status", "fehlt"),
            "laeuft_ab_in_s": e.get("kennung_laeuft_ab_in_s", e.get("laeuft_ab_in_s", 0)),   # F-55: nur die Kennung, keine Dringlichkeit
            "frist": e.get("frist"), "thema": e.get("thema", ""),
            # 17.09.2026: Nur an einer Mitarbeiter-Mail gibt es den Knopf
            # TESTVERSAND AN PATRON. Die Maske entscheidet das nicht selbst -
            # sie liest es hier.
            # F-53: dieselbe Kette (Knopf, Freigabecode, gesperrtes FREIGEBEN) fuer jede Mail-Karte; der Schluessel heisst
            # aus Altgruenden "mitarbeitermail", die Maske liest ihn als "Mail-Karte mit Testversand".
            # F-82: "mailantwort" gehoert seit der Freischaltung des FREIGEBEN-Knopfs zur selben Kette
            # dazu - sonst blieb der TESTVERSAND-Knopf hier aus, obwohl FREIGEBEN schon ging.
            "mitarbeitermail": kopf.get("art") in ("mitarbeitermail", "externemail", "mailantwort")
                               and bool(kopf.get("entwurf")),
            "mitarbeiter": kopf.get("mitarbeiter", ""),
            # Block 22: Darf diese Karte ueberhaupt freigegeben werden? Die
            # Maske fragt nicht, sie liest. Die Entscheidung faellt im Server
            # und faellt dort noch einmal, wenn der Knopf gedrueckt wird.
            "testversand_ok": _testversand_ok(root, kopf, datei.name),
            "testversand_hinweis": _testversand_satz(root, kopf, datei.name),
            "testversand_abgewiesen": _testversand_abgewiesen(root, kopf, datei.name),
            # F-52: Bei einer Extern-Mail ist der volle Text der Mail das, was der Patron freigibt - die Maske zeigt ihn.
            # F-77: mailantwort-Karten (Kanal-Postfach-Antworten) zeigen den Entwurf jetzt ebenso wie externemail.
            "mailtext": _mailtext(text) if kopf.get("art") in ("externemail", "mailantwort") else "",
            "mail_an": kopf.get("an", "") if kopf.get("art") in ("externemail", "mailantwort") else "",
            # F-82: die eingegangene Mail der Gegenseite (gekuerzt), damit der Patron beides auf einen
            # Blick sieht - nur vorhanden, wenn sie beim Erzeugen des Entwurfs mitgeschrieben wurde
            # (F-82, kuenftige Karten; aeltere Karten haben diesen Abschnitt nicht).
            "eingegangene_mail": _eingegangene_mail(text) if kopf.get("art") == "mailantwort" else "",
            "entwurf_fehlt": (kopf.get("art") == "mailantwort" and _entwurf_fehlt(root, kopf)),
            # F-83: der Entwurfs-Dateiname selbst - die Fokusansicht braucht ihn fuer SPEICHERN/
            # JACK ÜBERARBEITEN (an der Freigabe-Karte, nicht an der Mail-Ansicht).
            "entwurf": kopf.get("entwurf", "") if kopf.get("art") in ("externemail", "mailantwort", "mitarbeitermail") else "",
        })
    # Block 26, Teil 2 (T2.2/T2.3): Hausaufgaben ganz nach unten (eigene
    # Gruppe in der Oberflaeche), dann wer eine Wartemarke hat, dann nach
    # Gewicht (gefahr hoch -> Geld -> Recht -> Mitarbeiter -> Inhalt ->
    # Vorschlaege), zuletzt wie bisher nach 'erteilt'.
    # F-66: eine Karte mit Warten-Datum in der Zukunft geht in eine eigene Liste "wiedervorlagen" und
    # NICHT in die Freigabenliste; ist ihr Datum erreicht, bleibt sie in "raus" (oben, eigenes Kennzeichen).
    wiedervorlagen = []
    aktiv = []
    for x in raus:
        e = offene.get(x["datei"], {})
        if e.get("warte_bis") and not e.get("wiedervorlage_faellig"):
            wiedervorlagen.append({"datei": x["datei"], "titel": x["titel_rest"] or x["titel"], "warte_bis": e["warte_bis"], "marke": x["marke"]})
            continue
        x["wiedervorlage_faellig"] = bool(e.get("wiedervorlage_faellig"))
        x["warte_bis"] = e.get("warte_bis")
        aktiv.append(x)
    raus = aktiv
    wiedervorlagen.sort(key=lambda w: w["warte_bis"])
    for x in raus:          # NACHT kern 2: jede unvollstaendige Karte meldet sich EINMAL beim erzeugenden Kanal
        if x.get("v2_vollstaendig") is False and not x.get("warte_bis"):
            try:
                nachforderung_schreiben(root, x["datei"], x.get("unvollstaendig_grund") or "", str((x.get("v2") or {}).get("von") or ""))
            except Exception:
                pass
    try:
        nachforderungen_aufraeumen(root, raus)
    except Exception:
        pass
    raus.sort(key=lambda x: (x["klasse"] == "hausaufgabe", not x.get("zugang"), not x.get("wiedervorlage_faellig"), bool(x["wartemarke"]),
                             x["gewicht"], x["erteilt"]))
    _wiedervorlagen_melden(root, [x for x in raus if x.get("wiedervorlage_faellig")])
    # 16.09.2026: Der Tagesdeckel gehoert dorthin, wo der Patron entscheidet.
    # Ist er erreicht, steht es hier rot - und zwar bevor er sich fragt, warum
    # nichts mehr laeuft.
    deckel = {"ampel": "gruen", "satz": "", "stand": {}}
    try:
        import jack_grenzen
        stand = jack_grenzen.verbrauch(root)
        erreicht, grund = jack_grenzen.deckel_erreicht(root, stand=stand)
        deckel["stand"] = {"tag_usd": stand.get("tag_usd"),
                           "tag_laeufe": stand.get("tag_laeufe"),
                           "tag_quellen": stand.get("tag_quellen", {}),
                           "grenze": (jack_grenzen.lesen(root) or {}).get("budget_usd_je_tag")}
        if erreicht:
            deckel["ampel"] = "rot"
            # Der Deckel deckelt Geld, nicht das Reden. Was gesperrt ist und was
            # nicht, gehoert in denselben Satz - sonst sucht der Patron den
            # Fehler beim Sprechen, wo keiner ist.
            deckel["satz"] = (grund + " Gespräch und Sprache laufen über das Abo "
                              "und bleiben frei.")
        else:
            grenze = deckel["stand"].get("grenze")
            if grenze:
                from decimal import Decimal
                anteil = Decimal(stand["tag_usd"]) / Decimal(str(grenze))
                if anteil >= Decimal("0.8"):
                    deckel["ampel"] = "gelb"
                    import jack_guthaben as _g
                    deckel["satz"] = ("Tagesdeckel zu %d %% ausgeschöpft: %s von %s USD."
                                      % (int(anteil * 100), _g.usd_zahl(stand["tag_usd"]), _g.usd_zahl(grenze)))
    except Exception as fehler:
        # Eine Stoerung der Pruefung ist selbst eine Meldung wert - sie hat den
        # Deckel am 16.09.2026 stumm ausser Kraft gesetzt.
        deckel["ampel"] = "rot"
        deckel["satz"] = "Tagesdeckel nicht prüfbar: " + str(fehler)[:160]
    # Legacy-Prozentfeld bleibt kompatibel; sichtbarer Text benennt die Grenze.
    woche_prozent, woche_zeile = None, ""
    try:
        import jack_autonomie
        woche = jack_autonomie.berechnen(root).get("7_tage", {})
        woche_prozent = woche.get("quote_prozent")
        woche_zeile = ("Aktivität ohne Rückfrage (7 Tage): %s %% · keine Erfolgsquote" % woche_prozent
                       if woche_prozent is not None else
                       "Aktivität ohne Rückfrage (7 Tage): noch keine Ereignisse erfasst · keine Erfolgsquote")
    except Exception:
        pass
    try:
        farben = (json.loads((betrieb.area(root) / "marken_farben.json").read_text(encoding="utf-8")) or {}).get("marken", {})   # F-109 A1
    except (OSError, ValueError):
        farben = {}
    return {"zeit": betrieb.now().isoformat(), "eintraege": raus, "deckel": deckel,
            "woche_ohne_patron_prozent": woche_prozent, "woche_zeile": woche_zeile,
            "wiedervorlagen": wiedervorlagen, "marken_farben": farben,
            "quelle": "auftraege/freigabe/ und betrieb/freigaben.json"}


WIEDERVORLAGEN_GEMELDET = "wiedervorlagen_gemeldet.json"


def _wiedervorlagen_melden(root, faellige):
    """F-66 Punkt 3: wird eine Wiedervorlage faellig, EINMAL eine Zeile in ENTSCHEIDUNGEN_FUER_DEN_PATRON.md - der
    JACK-Tagesbericht (jack_betrieb.brief) zeigt 'wartet bis ...' ohnehin automatisch fuer jede Karte mit warte_bis,
    das braucht keine eigene Zeile hier."""
    if not faellige:
        return
    stand_pfad = betrieb.area(root) / WIEDERVORLAGEN_GEMELDET
    try:
        gemeldet = json.loads(stand_pfad.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        gemeldet = {}
    neu = [e for e in faellige if e["datei"] not in gemeldet]
    if not neu:
        return
    ziel = betrieb.area(root) / "ENTSCHEIDUNGEN_FUER_DEN_PATRON.md"
    zeit = betrieb.now().strftime("%Y-%m-%d %H:%M")
    with ziel.open("a", encoding="utf-8") as f:
        for e in neu:
            f.write("\n## %s — Wiedervorlage fällig: %s\n\n**Wiedervorlage fällig (%s):** `%s` ist wieder da — Karte `auftraege/freigabe/%s`.\n"
                   % (zeit[:10], e.get("titel_rest") or e.get("titel"), zeit, e.get("titel_rest") or e.get("titel"), e["datei"]))
    for e in neu:
        gemeldet[e["datei"]] = zeit
    stand_pfad.write_text(json.dumps(gemeldet, ensure_ascii=False, indent=1), encoding="utf-8")


def _testversand_ok(root, kopf, datei):
    """Block 22: Liegt zu dieser Karte ein gueltiger Testversand vor?

    Nur Mitarbeiter-Mails kennen diese Frage. Alle anderen Karten geben True
    zurueck - an ihnen aendert Block 22 nichts.
    """
    if kopf.get("art") not in ("mitarbeitermail", "externemail", "mailantwort") or not kopf.get("entwurf"):
        return True
    if _testversand_abgewiesen(root, kopf, datei):      # F-47: die Testmail ist nie angekommen - der Freigabecode existiert nicht
        return False
    try:
        import jack_mitarbeiter
        ok, _ = jack_mitarbeiter.testversand_gueltig(root, datei,
                                                     kopf.get("entwurf"))
        return bool(ok)
    except Exception:
        return False


def _testversand_abgewiesen(root, kopf, datei):
    """F-47: Grund, wenn die Testmail dieser Karte als Ruecklaeufer (MAILER-DAEMON) zurueckkam - sonst ''."""
    if kopf.get("art") not in ("mitarbeitermail", "externemail", "mailantwort") or not kopf.get("entwurf"):
        return ""
    try:
        import jack_postfaecher
        return jack_postfaecher.rueckl_zur_karte(root, datei)
    except Exception:
        return ""


def _mailtext(text):
    # F-77: neue Karten (v2) tragen den Mailtext unter "## Antwort / Entwurf" (Codeblock) - die alten
    # Ueberschriften "## Text der Mail"/"## Entwurf" bleiben als Rueckfall fuer nicht migrierte Karten gueltig.
    for muster in (r"^## Antwort / Entwurf\s*\n```\n(.*?)\n```", r"^## Text der Mail[^\n]*\s*\n```\n(.*?)\n```",
                   r"^## Entwurf\s*\n```\n(.*?)\n```"):
        m = re.search(muster, text or "", re.M | re.S)
        if m:
            return m.group(1).strip()
    return ""


def _eingegangene_mail(text):
    """F-82: der Abschnitt '## Eingegangene Mail' (von jack_postfaecher._entwurf_vorlegen bei einer
    mailantwort-Karte mitgeschrieben, sofern der Text der eingegangenen Mail beim Erzeugen vorlag).
    Fehlt der Abschnitt (z.B. bei aelteren Karten vor F-82), kommt ''."""
    m = re.search(r"^## Eingegangene Mail[^\n]*\s*\n```\n(.*?)\n```", text or "", re.M | re.S)
    return m.group(1).strip() if m else ""


def _entwurf_fehlt(root, kopf):
    """F-82: true, wenn eine mailantwort-Karte keinen (oder keinen lesbaren/leeren) Entwurf hat -
    die Karte bekommt dann eine rot gesperrte Darstellung statt stumm zu scheitern (wie F-77)."""
    entwurf = str(kopf.get("entwurf", "")).strip()
    if not entwurf:
        return True
    pfad = betrieb.area(root) / "entwuerfe" / entwurf
    if not pfad.is_file() or pfad.is_symlink():
        return True
    try:
        rumpf = pfad.read_text(encoding="utf-8").split("\n---\n", 1)
        return not (rumpf[1].strip() if len(rumpf) > 1 else "")
    except OSError:
        return True


def _testversand_satz(root, kopf, datei):
    """Die ruhige Hinweiszeile unter dem gesperrten Knopf."""
    if kopf.get("art") not in ("mitarbeitermail", "externemail", "mailantwort") or not kopf.get("entwurf"):
        return ""
    grund = _testversand_abgewiesen(root, kopf, datei)
    if grund:
        return ("Testmail abgewiesen: %s. Der Freigabecode ist nie angekommen; bitte den Testversand wiederholen." % grund)
    try:
        import jack_mitarbeiter
        _, satz = jack_mitarbeiter.testversand_gueltig(root, datei,
                                                       kopf.get("entwurf"))
        return satz
    except Exception as fehler:
        return "Der Stand des Testversands liess sich nicht lesen: %s" % str(fehler)[:120]


def _kurzsatz(text):
    treffer = re.search(r"^##+\s*Auftrag\s*$(.+?)(^##\s|\Z)", text, re.M | re.S)
    rumpf = treffer[1] if treffer else text
    rumpf = re.sub(r"^---.*?^---", " ", rumpf, flags=re.M | re.S)
    # F-31: Ueberschriftenzeilen gehoeren nicht in den Satz ("... erzeugen Der Befund in einem Satz Die Schluessel ...")
    rumpf = re.sub(r"^\s*#+[^\n]*$", " ", rumpf, flags=re.M)
    rumpf = re.sub(r"[*_`|#>]", " ", rumpf)
    rumpf = re.sub(r"\s+", " ", rumpf).strip()
    satz = re.split(r"(?<=[.!?])(?<!\d\.)\s", rumpf)[0] if rumpf else ""     # F-31: "21.09." beendet keinen Satz
    return satz[:220]


def _worumsatz(text):
    """Block 16b (5.3): Ein Satz, der die Vorlage ohne Oeffnen erklaert.

    Zuerst der Abschnitt "Worum es geht" - so heisst er in den Vorlagen, die
    JACK selbst schreibt. Fehlt er, gilt derselbe Weg wie bisher ueber den
    Abschnitt "Auftrag". Gefunden wird nichts erfunden: ist beides leer,
    bleibt das Feld leer und die Zeile erscheint nicht.
    """
    treffer = re.search(r"^##+\s*Worum es geht\s*$(.+?)(^##\s|\Z)",
                        text, re.M | re.S)
    if not treffer:
        return ""
    rumpf = re.sub(r"[*_`|#>]", " ", treffer[1])
    rumpf = re.sub(r"\s+", " ", rumpf).strip()
    satz = re.split(r"(?<=[.!?])(?<!\d\.)\s", rumpf)[0] if rumpf else ""     # F-31: "21.09." beendet keinen Satz
    return satz[:220]


def _etikett(titel):
    """Block 16b (5.1): Der Teil vor dem Gedankenstrich ist die ART des Vorgangs.

    "RSS-Quelle freigeben — status.claude.com" wird zu
    ("RSS-Quelle freigeben", "status.claude.com"). Ohne Gedankenstrich gibt es
    kein Etikett - dann ist der ganze Titel der Titel.
    """
    for trenner in (" — ", " – ", " - "):
        if trenner in titel:
            vorn, hinten = titel.split(trenner, 1)
            vorn, hinten = vorn.strip(), hinten.strip()
            # Ein Etikett ist eine Art, kein halber Satz.
            if 2 <= len(vorn) <= 42 and hinten:
                return vorn, hinten
    return "", titel


def _alterstext(sekunden):
    if sekunden < 3600:
        return "seit %d Minuten" % max(1, int(sekunden // 60))
    if sekunden < 86400:
        return "seit %d Stunden" % int(sekunden // 3600)
    tage = int(sekunden // 86400)
    return "seit %d Tag%s" % (tage, "" if tage == 1 else "en")


# ══════════ Block 13, 17.09.2026: zwei Arten von Vorgaengen ════════════════
# Was am 16./17.09. geschehen ist: Eine Freigabe-VORLAGE ("Gib die
# Stufen-Tabelle frei", "Uebernimm die neue CLAUDE.md") wurde nach dem Klick
# auf FREIGEBEN wie ein Arbeitsauftrag nach offen/ verschoben. Der Planer hat
# sie dem API-Arbeiter gegeben, der Arbeiter hat versucht, ein Dokument
# "auszufuehren", und ist ergebnislos ins Budget gelaufen - viermal, rund
# 2,3 USD. Danach lief er alle fuenf Minuten erneut an und schrieb 211-mal
# "ABGEBROCHEN nach 2 Versuchen" ins Log.
#
# Die Ursache ist nicht der Arbeiter. Die Ursache ist, dass zwei voellig
# verschiedene Dinge gleich behandelt wurden:
#
#   ENTSCHEIDUNGSVORLAGE  Der Patron entscheidet etwas. FREIGEBEN wendet die
#                         Entscheidung an - regelbasiert, ohne Modell, ohne
#                         Arbeiter - und legt die Datei ab. Nie nach offen/.
#   AUFTRAG               Jemand soll etwas tun. FREIGEBEN gibt ihn frei, er
#                         geht nach offen/ und der Arbeiter holt ihn.
#
# Erkannt wird das am Frontmatter-Feld `art:`. Fehlt es, gilt der alte Weg -
# so aendert sich fuer bestehende Auftraege nichts.
ENTSCHEIDUNGSARTEN = ("vertragsregister", "kostenstufen", "regeldateien",
                      "verhaltensregeln", "werkzeuge", "anleitung", "entscheidung",
                      # Block 21: Mail an einen Mitarbeiter. FREIGEBEN sendet sie
                      # und legt sie in die Akte - es entsteht kein Arbeitsauftrag.
                      "mitarbeitermail",
                      # F-52: persoenliche Mail des Patrons an Dritte (Mailart Extern): FREIGEBEN sendet sie - seit F-53 nur nach Testversand + Freigabecode.
                      "externemail",
                      # F-82 (29.09.2026, Patron-Anordnung): Antwort auf eine eingegangene Mail (Kanal-
                      # Postfach). Bis F-82 wurde FREIGEBEN hier abgewiesen ("an der Mail freigeben") -
                      # der Patron wollte das nicht: eine Freigabe geschieht an EINEM Ort. Jetzt derselbe
                      # Testversand-> Code-> FREIGEBEN-Weg wie externemail, derselbe Sendeweg (jack_postfaecher.senden).
                      "mailantwort",
                      # F-79: Mitteilung "Termin automatisch geaendert" (Gegenseite-Antwort). GELESEN
                      # (freigegeben) legt nur ab, RUECKGAENGIG (abgelehnt) stellt den alten Zeitpunkt
                      # wieder her - siehe der zurkenntnis-Sonderfall unten in freigabe_entscheiden().
                      "zurkenntnis")


def _art_von(text):
    m = re.search(r"^art:\s*(\S+)", text, re.M)
    return (m.group(1).strip().lower() if m else "")


def _anwenden(root, art, datei, text, von, freigabecode=""):
    """Die Entscheidung des Patrons ausfuehren - ohne Modell, ohne Arbeiter.

    Gibt (ok, Satz) zurueck. Faellt eine Anwendung aus, wird das gemeldet und
    die Vorlage bleibt liegen; es wird nie so getan, als haette es geklappt.
    """
    root = Path(root)
    if art == "kostenstufen":
        import shutil
        p = betrieb.area(root) / "kostenstufen.json"
        shutil.copy2(p, p.with_name("kostenstufen.json.vor_freigabe_%s"
                                    % betrieb.now().strftime("%Y-%m-%d_%H%M%S")))
        d = json.loads(p.read_text(encoding="utf-8"))
        d["status"] = "freigegeben vom Patron am " + betrieb.now().strftime("%Y-%m-%d %H:%M")
        d["freigegeben"] = True
        saetze = ["Stufen-Tabelle ist aktiv. Stufe 1 ist damit auch fuer "
                  "'vertraulich' erlaubt."]
        # Block 15 (E3): Traegt die Vorlage eine Messtest-Laufnummer, werden
        # die empfohlenen Stufen JETZT angewandt. Vorher setzte FREIGEBEN nur
        # die Tabelle auf "aktiv" - der gemessene Vorschlag blieb liegen.
        m = re.search(r"^messtest_lauf:\s*(\d+)", text or "", re.M)
        if m:
            try:
                import jack_messtest
                bericht = jack_messtest.auswerten(root, int(m.group(1)))
            except Exception as fehler:
                saetze.append("Der Messtest-Vorschlag liess sich nicht lesen (%s) - "
                              "die Stufen wurden NICHT verschoben."
                              % str(fehler)[:100])
                bericht = None
            if bericht:
                bewegt = []
                for a in bericht.get("aenderungen", []):
                    von, nach = str(a["stufe_heute"]), str(a["stufe_empfohlen"])
                    stufen = d.get("stufen") or {}
                    if von not in stufen or nach not in stufen:
                        continue
                    liste_von = stufen[von].setdefault("taugt_fuer", [])
                    liste_nach = stufen[nach].setdefault("taugt_fuer", [])
                    if a["art"] in liste_von:
                        liste_von.remove(a["art"])
                    if a["art"] not in liste_nach:
                        liste_nach.append(a["art"])
                    bewegt.append("%s: Stufe %s -> %s" % (a["art"], von, nach))
                if bewegt:
                    d["messtest_angewandt"] = {
                        "lauf": int(m.group(1)),
                        "zeit": betrieb.now().isoformat(),
                        "aenderungen": bewegt,
                        "quote_je_stufe": bericht.get("quote_je_stufe"),
                        "grundlage": "%s von %s Urteilen" % (bericht.get("urteile"),
                                                             bericht.get("urteile_geplant"))}
                    saetze.append("Aus Messtest Lauf %s uebernommen: %s."
                                  % (m.group(1), " · ".join(bewegt)))
                else:
                    saetze.append("Der Messtest empfahl keine Verschiebung - die "
                                  "Aufgabenarten bleiben, wo sie waren.")
        p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        saetze.append("Der Messtest hat einen eigenen Knopf und laeuft NICHT mit "
                      "dieser Freigabe an.")
        return True, " ".join(saetze)
    if art == "vertragsregister":
        p = betrieb.area(root) / "vertragsregister.json"
        d = json.loads(p.read_text(encoding="utf-8"))
        d["gueltig_seit"] = d.get("gueltig_seit") or betrieb.now().isoformat()
        d["freigegeben"] = True
        p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        return True, "Vertragsregister gilt: %d Zeilen." % len(d.get("zeilen", []))
    if art == "regeldateien":
        return _regeldateien_uebernehmen(root)
    if art == "verhaltensregeln":
        return _verhaltensblock_aufnehmen(root)
    if art == "werkzeuge":
        p = betrieb.area(root) / "werkzeug_merkliste.md"
        p.write_text(text, encoding="utf-8")
        return True, ("Als Merkliste abgelegt (betrieb/werkzeug_merkliste.md). "
                      "Es wurde NICHTS installiert - dafuer braucht jedes Werkzeug "
                      "eine eigene Freigabe.")
    if art == "anleitung":
        return True, "Als gelesen abgelegt. Es war nichts auszufuehren."
    if art == "zurkenntnis":
        # F-79: GELESEN auf einer "Termin automatisch geaendert"-Mitteilung legt nur ab - die
        # eigentliche Rueckgaengig-Handlung sitzt in freigabe_entscheiden() (Zweig entscheidung ==
        # "abgelehnt"), weil sie schon VOR dem Verschieben nach erledigt/ passieren muss.
        # F-83: dieselbe Kartenart traegt auch Sicherheitscode-Mitteilungen (ohne akte_pfad) - dort
        # heisst GELESEN "ERLEDIGT" und es gibt keinen Termin, um den es geht.
        if _kopf(text).get("akte_pfad"):
            return True, "Als gelesen abgelegt. Der geaenderte Termin bleibt so eingetragen."
        return True, "Als erledigt abgelegt."
    if art == "externemail":
        # F-52: FREIGEBEN = der Patron hat genau diese Fassung gesehen. Die Pruefsumme des aktuellen Entwurfs geht mit; ohne sie sendet
        # jack_postfaecher.senden keine Mail der Art "Extern".
        import jack_freigaben
        import jack_postfaecher
        kopf = _kopf(text)
        entwurf = str(kopf.get("entwurf", "")).strip()
        if not entwurf:
            return False, "In der Vorlage fehlt die Zeile entwurf: - es wurde nichts gesendet."
        pfad = betrieb.area(root) / "entwuerfe" / entwurf
        if not pfad.is_file():
            return False, "Den Entwurf gibt es nicht mehr - es wurde nichts gesendet."
        # F-53: erst Testversand + Freigabecode aus der [TEST]-Mail (gleiche Kette wie Block 22/27), dann die Pruefsumme (F-52).
        import jack_mitarbeiter
        ok_test, grund_test = jack_mitarbeiter.testversand_gueltig(root, str(datei), entwurf)
        if not ok_test:
            protokoll(root, "externemail_gesperrt", datei=str(datei)[:160], grund=grund_test)
            return False, grund_test
        fk, _ = jack_freigaben.anfordern(root, str(datei), grund="Extern-Mail - Freigabe des Patrons")
        frei = jack_mitarbeiter.freigabe_vermerken(
            root, str(datei), entwurf, code=freigabecode, kennung=fk or "",
            ausloeser="Maske (FREIGEBEN-Knopf), gemeldet: %s" % von)
        if not frei.get("ok"):
            return False, frei.get("grund", "Freigabe abgewiesen.")
        if fk:
            jack_freigaben.erteilen(root, fk, von="Patron", herkunft="maske+freigabecode")
        antwort = jack_postfaecher.senden(root, entwurf, von="Maske (FREIGEBEN-Knopf), gemeldet: %s" % von,
                                          patron_freigabe_sha=jack_postfaecher.extern_pruefsumme(pfad))
        if not antwort.get("ok"):
            try:
                jack_postfaecher.extern_meldung(root, {"sammel_meldung": _kopf(pfad.read_text(encoding="utf-8")).get("sammel_meldung", ""),
                                                       "an": _kopf(text).get("an", ""), "betreff": ""}, "FEHLGESCHLAGEN",
                                                grund=str(antwort.get("meldung", ""))[:200])
            except Exception:
                pass
            return False, "Nicht gesendet: " + str(antwort.get("meldung", ""))[:200]
        if fk:
            jack_freigaben.verbrauchen(root, fk, str(datei), herkunft="externemail")
        satz = [antwort.get("meldung", "Gesendet.")]
        if antwort.get("beleg"):
            satz.append("Kopie im Belegordner: %s." % antwort["beleg"])
        # F-79 (28.09.2026, Patron-Anordnung 18:30): traegt die Karte ein termin:-Feld, deckt DIESE
        # verbrauchte Mail-Freigabe auch den Kalendereintrag - kein zweiter Freigabeschritt.
        if kopf.get("termin"):
            try:
                import jack_termine
                termin_ergebnis = jack_termine.termin_bei_mailfreigabe_eintragen(root, kopf, von=von)
                if termin_ergebnis:
                    satz.append(termin_ergebnis.get("meldung", ""))
            except Exception as fehler:
                satz.append("Kalender NICHT eingetragen (%s) - Mail wurde trotzdem gesendet." % str(fehler)[:150])
        return True, " ".join(satz)
    if art == "mailantwort":
        # F-82 (29.09.2026, Patron-Anordnung): dieselbe Kette wie externemail - Testversand-Pflicht
        # (F-53), dann Freigabecode, dann derselbe Sendeweg (jack_postfaecher.senden), den bisher
        # ausschliesslich die Mail-Ansicht (/postfach/senden) genutzt hat. Kein eigener, nachgebauter
        # Versandweg - dieselbe Funktion, nur von hier aus aufgerufen.
        import jack_freigaben
        import jack_mitarbeiter
        import jack_postfaecher
        kopf = _kopf(text)
        entwurf = str(kopf.get("entwurf", "")).strip()
        if not entwurf:
            return False, "In der Vorlage fehlt die Zeile entwurf: - es wurde nichts gesendet."
        pfad = betrieb.area(root) / "entwuerfe" / entwurf
        if not pfad.is_file():
            return False, "Den Entwurf gibt es nicht mehr - es wurde nichts gesendet."
        entwurf_text = pfad.read_text(encoding="utf-8")
        entwurf_rumpf = entwurf_text.split("\n---\n", 1)
        if not (entwurf_rumpf[1].strip() if len(entwurf_rumpf) > 1 else ""):
            return False, "Der Entwurf ist leer - es wurde nichts gesendet."
        # Doppelversand-Sperre: wurde diese Antwort inzwischen an der Mail-Ansicht (oder einem
        # frueheren Klick hier) schon gesendet, wird NICHT erneut gesendet - die Karte legt sich nur ab.
        entwurf_kopf = _kopf(entwurf_text)
        if str(entwurf_kopf.get("zustand", "")).strip().lower() == "gesendet":
            return True, "Diese Antwort wurde bereits gesendet (Entwurf-Zustand: gesendet) - die Karte wird nur abgelegt."
        ok_test, grund_test = jack_mitarbeiter.testversand_gueltig(root, str(datei), entwurf)
        if not ok_test:
            protokoll(root, "mailantwort_gesperrt", datei=str(datei)[:160], grund=grund_test)
            return False, grund_test
        fk, _ = jack_freigaben.anfordern(root, str(datei), grund="Mailantwort - Freigabe des Patrons")
        frei = jack_mitarbeiter.freigabe_vermerken(
            root, str(datei), entwurf, code=freigabecode, kennung=fk or "",
            ausloeser="Maske (FREIGEBEN-Knopf), gemeldet: %s" % von)
        if not frei.get("ok"):
            return False, frei.get("grund", "Freigabe abgewiesen.")
        if fk:
            jack_freigaben.erteilen(root, fk, von="Patron", herkunft="maske+freigabecode")
        # F-102: Entwuerfe der Mailart "Extern" brauchen die F-52-Pruefsumme (wie im externemail-Zweig) - ohne sie sperrte senden()
        # jedes Mal ("extern_gesperrt"), obwohl Testversand + Code gueltig waren. Keine andere Sperre wird gelockert.
        antwort = jack_postfaecher.senden(root, entwurf, von="Maske (FREIGEBEN-Knopf), gemeldet: %s" % von,
                                          patron_freigabe_sha=jack_postfaecher.extern_pruefsumme(pfad))
        if not antwort.get("ok"):
            return False, "Nicht gesendet: " + str(antwort.get("meldung", ""))[:200]
        if fk:
            jack_freigaben.verbrauchen(root, fk, str(datei), herkunft="mailantwort")
        satz = [antwort.get("meldung", "Gesendet.")]
        if antwort.get("message_id"):
            satz.append("Beleg: Message-ID %s." % antwort["message_id"])
        if antwort.get("kopie"):
            satz.append("Kopie im Gesendet-Ordner: %s." % antwort["kopie"])
        return True, " ".join(satz)
    if art == "mitarbeitermail":
        # Block 21: Der EINZIGE Weg, auf dem eine Mail an einen Mitarbeiter
        # hinausgeht. Ohne diesen Knopf des Patrons passiert nichts.
        import jack_mitarbeiter
        import jack_postfaecher
        kopf = _kopf(text)
        entwurf = str(kopf.get("entwurf", "")).strip()
        kennung = str(kopf.get("mitarbeiter", "")).strip()
        if not entwurf or not kennung:
            return False, ("In der Vorlage fehlt die Zeile entwurf: oder mitarbeiter: - "
                           "es wurde nichts gesendet.")
        # ── Block 22 (17.09.2026): Die Freigabekette. Vor allem anderen.
        #    Ohne gueltigen Testversand geht diese Karte nicht hinaus - egal,
        #    wer oder was den Knopf gedrueckt hat. Am 17.09. um 19:10 fehlte
        #    genau diese Sperre, und eine Mail ging ungeprueft an den
        #    Mitarbeiter (Beleg: betrieb/oberflaeche.jsonl).
        import jack_freigaben
        # F-104: abgenommene Mailart an abgenommenen Empfaenger (Referenz-Aufmachung): Vorschau -> FREIGEBEN, kein Testversand, kein Code.
        # Die Aufmachungs-Pruefung und die Pruefsumme der angezeigten Fassung stehen in senden() selbst.
        try:
            import jack_mail_referenz
            kopf_e, _r = jack_postfaecher._entwurf_zerlegen(root, entwurf)
            regel_ref = jack_mail_referenz.regel_fuer(root, kopf_e)
        except Exception:
            regel_ref = None
        if regel_ref:
            fk, _ = jack_freigaben.anfordern(root, str(datei), grund="Mail an %s - Freigabe (Referenz-Aufmachung)" % kennung)
            if fk:
                jack_freigaben.erteilen(root, fk, von="Patron", herkunft="maske+referenz")
            antwort = jack_postfaecher.senden(root, entwurf, von="Maske (FREIGEBEN-Knopf, Referenz-Aufmachung)",
                                              patron_freigabe_sha=jack_postfaecher.extern_pruefsumme(betrieb.area(root) / "entwuerfe" / entwurf))
            if not antwort.get("ok"):
                jack_mitarbeiter.messung_merken(root, kennung, "versand_gescheitert", vorlage=str(datei)[:120], grund=str(antwort.get("meldung", ""))[:160])
                return False, "Nicht gesendet: " + str(antwort.get("meldung", ""))[:200]
            if fk:
                jack_freigaben.verbrauchen(root, fk, str(datei), herkunft="mitarbeitermail")
            jack_mitarbeiter.messung_merken(root, kennung, "gesendet", vorlage=str(datei)[:120], aenderung=None, schritt=kopf.get("schritt") or "", direkte_frage=False)
            if kopf.get("schritt"):
                try:
                    jack_mitarbeiter.schritt_setzen(root, kennung, int(kopf["schritt"]), "gesendet", beleg=str(datei)[:120])
                except Exception:
                    pass
            return True, " ".join(x for x in [antwort.get("meldung", "Gesendet."), ("Kopie in der Akte: %s." % Path(antwort["akte"]).name) if antwort.get("akte") else ""] if x)
        ok_test, grund_test = jack_mitarbeiter.testversand_gueltig(
            root, str(datei), entwurf)
        if not ok_test:
            protokoll(root, "mitarbeitermail_gesperrt", datei=str(datei)[:160],
                      mitarbeiter=kennung, grund=grund_test)
            return False, grund_test
        # ── Block 27 (18.09.2026): Der Knopf allein ist keine Freigabe mehr.
        #    Erst der Freigabecode aus der [TEST]-Mail beweist, dass der Patron
        #    genau diese Fassung gesehen hat. Ohne ihn: abgewiesen, protokolliert.
        fk, _ = jack_freigaben.anfordern(
            root, str(datei), grund="Mail an %s - Freigabe des Patrons" % kennung)
        frei = jack_mitarbeiter.freigabe_vermerken(
            root, str(datei), entwurf, code=freigabecode, kennung=fk or "",
            ausloeser="Maske (FREIGEBEN-Knopf), gemeldet: %s" % von)
        if not frei.get("ok"):
            return False, frei.get("grund", "Freigabe abgewiesen.")
        # Der Eintrag "freigegeben" gehoert ins Freigabenbuch, BEVOR gesendet wird.
        if fk:
            jack_freigaben.erteilen(root, fk, von="Patron",
                                    herkunft="maske+freigabecode")
        # Nachtrag 7: Vor dem Senden messen, wie viel der Patron geaendert hat.
        aenderung = None
        try:
            entwurfsdatei = betrieb.area(root) / "entwuerfe" / entwurf
            ur = entwurfsdatei.with_suffix(".urfassung")
            if ur.is_file():
                jetzt_text = entwurfsdatei.read_text(encoding="utf-8").split("---", 2)[-1].strip()
                aenderung = jack_mitarbeiter._aehnlichkeit(
                    ur.read_text(encoding="utf-8").strip(), jetzt_text)
        except Exception:
            aenderung = None
        antwort = jack_postfaecher.senden(root, entwurf,
                                          von="Maske (FREIGEBEN-Knopf mit Freigabecode)")
        if not antwort.get("ok"):
            jack_mitarbeiter.messung_merken(root, kennung, "versand_gescheitert",
                                            vorlage=str(datei)[:120],
                                            grund=str(antwort.get("meldung", ""))[:160])
            return False, "Nicht gesendet: " + str(antwort.get("meldung", ""))[:200]
        if fk:
            jack_freigaben.verbrauchen(root, fk, str(datei), herkunft="mitarbeitermail")
        jack_mitarbeiter.messung_merken(root, kennung, "gesendet",
                                        vorlage=str(datei)[:120], aenderung=aenderung,
                                        schritt=kopf.get("schritt") or "",
                                        direkte_frage=kopf.get("vorgang") == "direkte_frage")
        if kopf.get("schritt"):
            try:
                jack_mitarbeiter.schritt_setzen(root, kennung, int(kopf["schritt"]),
                                                "gesendet", beleg=str(datei)[:120])
            except Exception:
                pass
        saetze = [antwort.get("meldung", "Gesendet.")]
        if aenderung is not None:
            saetze.append("Du hast %d %% des Entwurfs geändert (nur für dich vermerkt)."
                          % round(aenderung * 100))
        saetze.append("Die Mail liegt mit allen Anhängen in der Akte (%s)."
                      % (antwort.get("akte") or "Ablage siehe Protokoll"))
        titel = str(kopf.get("auftrag_titel", "")).strip()
        if titel:
            try:
                jack_mitarbeiter.auftrag_anlegen(
                    root, kennung, str(kopf.get("projekt", "ALLGEMEIN")), titel,
                    text.split("## Text der Mail", 1)[-1].strip(),
                    faellig=str(kopf.get("faellig", "")), von="JACK")
                saetze.append("Der Arbeitsauftrag »%s« steht jetzt in seiner Aufgabenliste."
                              % titel)
            except Exception as fehler:
                saetze.append("Die Mail ist raus, der Auftrag liess sich aber nicht "
                              "eintragen (%s)." % str(fehler)[:120])
        return True, " ".join(saetze)
    # Block 18: Eine Entscheidungsvorlage nennt im Kopf ihren Vorgang. Ohne das
    # wuerde FREIGEBEN nur "vermerkt" sagen und nichts tun - genau der Fehler,
    # den Block 16 abgestellt hat.
    vorgang = re.search(r"^vorgang:\s*(\S+)", text or "", re.M)
    if art == "entscheidung" and vorgang and vorgang.group(1) == "rss_quelle":
        # Block 20: Erst diese Freigabe traegt die Adresse in rss_quellen.json
        # ein. Ohne sie wird sie nie abgerufen.
        import jack_rss
        adresse = re.search(r"^rss_url:\s*(\S+)", text or "", re.M)
        if not adresse:
            return False, "In der Vorlage fehlt die Zeile rss_url — nichts aufgenommen."
        marke = re.search(r"^rss_marke:\s*(.*)$", text or "", re.M)
        zweck = re.search(r"^\| Zweck \| (.*?) \|", text or "", re.M)
        ergebnis = jack_rss.quelle_freigeben(
            root, adresse.group(1), marke.group(1).strip() if marke else "",
            zweck.group(1).strip() if zweck else "", von=von)
        return True, ergebnis["meldung"]
    if art == "entscheidung" and vorgang and vorgang.group(1) == "netzwaechter_neustart":
        # F-68: FREIGEBEN auf dieser Karte heisst "ja, jetzt neu starten" - das ersetzt fuer DIESEN Klick die Ruhe-Regel
        # (der Patron hat sie explizit hier freigegeben, nicht nebenbei irgendwas anderes geklickt).
        kopf = _kopf(text)
        kanal = str(kopf.get("kanal", "")).strip()
        laeufer = str(kopf.get("laeufer", "")).strip()
        if not kanal or not laeufer:
            return False, "In der Vorlage fehlt kanal: oder laeufer: - es wurde nichts neu gestartet."
        import sys as _sys
        _sys.path.insert(0, str(Path(root) / "bin"))
        # F-68: keine Umgebungsvariable, kein reload() hier - im Betrieb ist `root` ohnehin die echte JACK-Wurzel (dieselbe,
        # gegen die jack_netzwaechter.py ohne JACK_NETZ_WURZEL rechnet). Tests setzen die Umgebungsvariable VOR dem ersten
        # Import und laden das Modul selbst einmal neu - ein reload HIER wuerde in Tests gesetzte Attrappen wieder loeschen.
        import jack_netzwaechter as W
        konf = W._lesen(W.KONFIG, {}) or {}
        l = next((x for x in konf.get("laeufer", []) if x.get("name") == laeufer), None)
        if not l:
            return False, "Läufer %s steht nicht mehr in netzwaechter.json - vermutlich schon erledigt." % laeufer
        stand = W._lesen(W.STAND, {}) or {}
        r = W.kanal_neustart(l, {"herz": W._lesen(W.HERZ / (kanal + ".json"), {}) or {}}, stand, "Patron-Ja (F-68 Karte)", ignoriere_ruhe=True)
        W._schreiben(W.STAND, stand)
        return r["massnahme"].startswith("Kanal-Neustart") or r["massnahme"].startswith("TROCKEN"), r["massnahme"]
    if art == "entscheidung" and vorgang and vorgang.group(1) == "erinnerung":
        # F-56: FREIGEBEN = "erledigt". Die Karte geht nach erledigt/, die woechentliche Erinnerung (Kopf wiederholung:) endet damit.
        return True, "Erinnerung als erledigt vermerkt - sie kommt nicht wieder."
    if art == "entscheidung" and vorgang and vorgang.group(1) == "funktionen_monatsbericht":
        # Block 19: Es wird NICHTS abgeschaltet und nichts archiviert. Jede
        # einzelne Abschaltung braucht einen eigenen Auftrag.
        return True, ("Monatsbericht als gesehen abgelegt. Es wurde NICHTS "
                      "abgeschaltet und nichts archiviert - dafuer braucht jede "
                      "Funktion einen eigenen Auftrag.")
    if art == "entscheidung" and vorgang and vorgang.group(1) == "funktion_vorschlag":
        return True, ("Vorschlag angenommen und abgelegt. Gebaut ist damit noch "
                      "nichts - dafuer braucht es einen Auftrag.")
    if art == "entscheidung" and vorgang and vorgang.group(1) == "gedaechtnis_bereinigung":
        import jack_gedaechtnis
        ergebnis = jack_gedaechtnis.bereinigen(root, freigegeben=True,
                                               ausloeser="freigabe:" + str(von)[:20])
        return bool(ergebnis.get("ausgefuehrt")), ergebnis.get("meldung", "")
    return True, "Entscheidung vermerkt."


def _regeldateien_uebernehmen(root):
    """Den Vorschlag aus Block 12 aktiv schalten - mit Sicherung und Diff."""
    import difflib
    import shutil
    wurzel = Path(root).parents[1]
    v = wurzel / "02_Dokumente" / "INTERN" / "vorschlag_block12"
    if not (v / "AGENTS.md").is_file():
        return False, "Der Vorschlag liegt nicht unter 02_Dokumente/INTERN/vorschlag_block12/."
    sicher = wurzel / "99_Archiv" / ("JACK_Regeldateien_ersetzt_%s"
                                     % betrieb.now().strftime("%Y-%m-%d_%H%M%S"))
    sicher.mkdir(parents=True, exist_ok=True)
    zeilen = []
    for name, ziel in (("CLAUDE.md", wurzel / "02_Dokumente" / "INTERN" / "CLAUDE.md"),
                       ("AGENTS.md", wurzel / "AGENTS.md")):
        alt = ziel.read_text(encoding="utf-8") if ziel.is_file() else ""
        neu = (v / name).read_text(encoding="utf-8")
        if ziel.is_file():
            shutil.copy2(ziel, sicher / (ziel.name + ".vor_uebernahme"))
        ziel.write_text(neu, encoding="utf-8")
        weg = len(alt.splitlines()) - len(neu.splitlines())
        zeilen.append("%s: %d -> %d Zeilen (%+d)"
                      % (name, len(alt.splitlines()), len(neu.splitlines()), -weg))
        (sicher / (name + ".diff")).write_text(
            "\n".join(difflib.unified_diff(alt.splitlines(), neu.splitlines(),
                                            "vorher/" + name, "nachher/" + name, lineterm="")),
            encoding="utf-8")
    regeln = wurzel / ".claude" / "rules"
    regeln.mkdir(parents=True, exist_ok=True)
    for r in sorted((v / ".claude" / "rules").glob("*.md")):
        shutil.copy2(r, regeln / r.name)
        zeilen.append("Regel %s angelegt (laedt nur ueber paths)" % r.name)
    return True, ("Regeldateien uebernommen. " + " · ".join(zeilen)
                  + " · Sicherung und Diff: " + sicher.name)


def _verhaltensblock_aufnehmen(root):
    """Die vier Grundsaetze in die gemeinsame Regeldatei aufnehmen."""
    wurzel = Path(root).parents[1]
    ziel = wurzel / "AGENTS.md"
    if not ziel.is_file():
        return False, "AGENTS.md nicht gefunden."
    text = ziel.read_text(encoding="utf-8")
    if "## 11. Beim Programmieren" in text:
        return True, "Der Block steht schon in AGENTS.md - nichts doppelt eingefuegt."
    block = (
        "\n## 11. Beim Programmieren\n\n"
        "- **Erst denken, dann tippen.** Vor der ersten Zeile: Was soll herauskommen,\n"
        "  woran ist es zu erkennen, welche Datei ist betroffen?\n"
        "- **Das Einfachste, das traegt.** Kein Bauteil, keine Ebene, keine Abhaengigkeit,\n"
        "  fuer die es keinen Grund gibt. Wer etwas hinzufuegt, nennt den Grund.\n"
        "- **Kleiner Schnitt.** Aendere, was die Aufgabe verlangt \u2014 nicht, was daneben\n"
        "  auch noch auffaellt. Anderes wird gemeldet, nicht nebenbei umgebaut.\n"
        "- **Am Ziel messen.** Fertig ist, was die Pruefpunkte erfuellt; nicht, was laeuft.\n\n"
        "**Einfach heisst nie: weniger Umfang, weniger Pruefpunkte, weniger Sicherungen.\n"
        "Regeln des Patrons haben Vorrang.**\n\n"
        "*Herkunft: andrej-karpathy-skills (MIT), gekuerzt auf das, was hier fehlte.*\n")
    import shutil
    shutil.copy2(ziel, ziel.with_name("AGENTS.md.vor_verhaltensblock_%s"
                                      % betrieb.now().strftime("%Y-%m-%d")))
    ziel.write_text(text.rstrip() + "\n" + block, encoding="utf-8")
    return True, ("Verhaltensblock in AGENTS.md aufgenommen (%d Zeilen gesamt)."
                  % len(ziel.read_text(encoding="utf-8").splitlines()))


# ══════════ Block 16 (H): Was heute entschieden wurde ══════════════════════
# Der Patron hat am 17.09. um 06:16 eine Vorlage freigegeben und danach nicht
# mehr gewusst, WAS daraus geworden ist. Eine Entscheidung darf nicht in einer
# Protokolldatei verschwinden, die man erst suchen muss.
def ist_testeintrag(e):
    """Block 16b (1.2): Ein Testlauf ist keine Entscheidung des Patrons.

    Erkannt wird er an zwei Merkmalen, die beide im Protokoll stehen: dem Feld
    `test` (seit Block 16b) und dem Dateinamen mit Praefix TEST_ (gilt auch
    rueckwirkend fuer die 22 Zeilen, die vor Block 16b entstanden sind).
    Das Protokoll wird dafuer NICHT umgeschrieben - gefiltert wird beim Lesen.
    """
    return bool(e.get("test") is True
                or str(e.get("datei") or "").startswith("TEST_"))


def entschieden(root, tage=1, mit_tests=False):
    """Die Entscheidungen der letzten Tage - aus dem Protokoll, nicht geraten.

    Je Eintrag: Zeit, Datei, Titel, Entscheidung, Wirkung (der Satz, den die
    Anwendung selbst zurueckgegeben hat) und wo die Datei jetzt liegt.

    Block 16b: Testlaeufe zaehlen NICHT mit. `mit_tests=True` zeigt sie
    zusaetzlich an (Umschalter "TESTS ZEIGEN"), markiert als `test: true`.
    """
    import datetime as dt
    root = Path(root)
    grenze = (betrieb.now() - dt.timedelta(days=max(0, tage - 1))).date().isoformat()
    heute = betrieb.now().date().isoformat()
    roh, tests = {}, 0
    for e in betrieb.records(_area(root) / PROTOKOLL):
        if e.get("art") != "freigabe_entscheidung":
            continue
        zeit = str(e.get("zeit") or "")
        if zeit[:10] < grenze:
            continue
        datei = str(e.get("datei") or "")
        if ist_testeintrag(e) and not mit_tests:
            tests += 1
            continue
        # Mehrere Versuche zur selben Datei: der LETZTE gilt.
        roh[datei] = e
    raus = []
    for datei, e in roh.items():
        wo, titel = "", ""
        for gruppe in ("erledigt", "offen", "laeuft", "freigabe", "problem"):
            p = root / "auftraege" / gruppe / datei
            if p.is_file():
                wo = gruppe + "/"
                try:
                    kopf = re.search(r"^auftrag:\s*(.+)$",
                                     p.read_text(encoding="utf-8", errors="replace")[:1500], re.M)
                    titel = kopf.group(1).strip() if kopf else ""
                except OSError:
                    titel = ""
                break
        wirkung = str(e.get("wirkung") or "")
        # "abgewiesen: ..." ist keine Entscheidung, sondern ein Hinweis.
        if wirkung.startswith("abgewiesen") or wirkung.startswith("nicht "):
            zustand = "abgewiesen"
        else:
            zustand = str(e.get("entscheidung") or "")
        raus.append({
            "zeit": str(e.get("zeit") or "")[11:16],
            "tag": str(e.get("zeit") or "")[:10],
            "heute": str(e.get("zeit") or "")[:10] == heute,
            "datei": datei,
            "titel": (titel or datei.replace("_", " ").replace(".md", ""))[:90],
            "entscheidung": zustand,
            "vorlagenart": e.get("vorlagenart", ""),
            "wirkung": wirkung,
            "wo": wo or "nicht mehr auffindbar",
            "von": e.get("von", ""),
            "test": ist_testeintrag(e),
        })
    raus.sort(key=lambda x: (x["tag"], x["zeit"]), reverse=True)
    return {"zeit": betrieb.now().isoformat(), "eintraege": raus,
            "heute": len([x for x in raus if x["heute"] and not x["test"]]),
            "tests_ausgeblendet": tests, "mit_tests": bool(mit_tests),
            "quelle": "betrieb/oberflaeche.jsonl + Lage der Dateien in auftraege/ "
                      "(Testlaeufe werden beim Lesen gefiltert, nicht geloescht)"}


def _optionen_kopf(kopf):
    """[{key, titel, wirkung, karte}] aus den Kopffeldern optionen / option_x_titel / option_x_wirkung / option_x_karte (nur Anzeige)."""
    raus = []
    for key in [x.strip() for x in re.split(r"[,;]", str(kopf.get("optionen") or "")) if x.strip()]:
        k = key.lower()
        raus.append({"key": key.upper(), "titel": kopf.get("option_%s_titel" % k, ""), "wirkung": kopf.get("option_%s_wirkung" % k, ""),
                     "karte": kopf.get("option_%s_karte" % k, "")})
    return raus


def _klick_satz(kopf):
    """Nachtrag PM 7 (2): eine Zeile unter den Knoepfen - was der Klick ausloest. Quelle ist ausschliesslich `ablauf:`."""
    a = re.sub(r"\s+", " ", str(kopf.get("ablauf") or "")).strip()
    return a[:220]


def social_anzeige(root):
    """NACHT KERN 3 (SM-8): die Social-Ansicht las eine fest eingebaute Liste vom 28.09. Jetzt aus dem Kanalregister `betrieb/social_kanaele.json`:
    Status beginnt mit 'verbunden' = gelesen; alles andere (auch 'aktiv, Patron bestaetigt' ohne Beleg) = kein Konto. Stand = letzte Aenderung der Datei."""
    p = Path(root) / "betrieb" / "social_kanaele.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        stand = dt.datetime.fromtimestamp(p.stat().st_mtime).strftime("%d.%m.%Y %H:%M")
    except (OSError, ValueError):
        return {"ok": False, "kanaele": []}
    kan = []
    for k in d.get("kanaele") or []:
        st = str(k.get("status") or "").strip().lower()
        kan.append({"marke": k.get("marke"), "plattform": k.get("plattform"),
                    "zustand": "gelesen" if st.startswith("verbunden") else "nicht_verbunden"})
    return {"ok": True, "stand": stand, "kanaele": kan}


def bewerbungen_lage(root):
    """NACHT kern 2 Nr. 4: eine Zeile fuer die Uebersicht aus dem Tracker (06_Tracker.md, Kanal bewerbungen): x offen (Paket fertig, Entscheidung steht aus) ·
    y wartet auf Antwort · nachster Schritt. Nur Lesen; nichts wird geraten - was der Tracker nicht hergibt, bleibt 'unbekannt'."""
    p = Path(root).parent / "MATHIAS_GOTTWALD" / "02_Dokumente" / "Bewerbungen" / "06_Tracker.md"
    try:
        zeilen = p.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {"ok": False, "meldung": "Der Tracker liegt gerade nicht vor."}
    offen = wartet = verworfen = 0
    for z in zeilen:
        if not z.startswith("|") or z.startswith("|---") or z.startswith("| Stelle"):
            continue
        sp = [x.strip() for x in z.strip().strip("|").split("|")]
        if len(sp) < 8:
            continue
        status, ergebnis = sp[3].lower(), sp[7].lower()
        if "verworfen" in status or "verworfen" in ergebnis:
            verworfen += 1
        elif re.search(r"versendet|eingetragen|beworben|eingereicht|wartet auf antwort", status + " " + ergebnis):
            wartet += 1
        elif "paket fertig" in status:
            offen += 1
    karten = len(list((Path(root) / "auftraege" / "freigabe").glob("*BEWERBUNG*.md")))
    schritt = ("%d Bewerbungskarte(n) in den Freigaben entscheiden" % karten) if karten else "kein Paket wartet auf dich"
    return {"ok": True, "offen": offen, "wartet_antwort": wartet, "verworfen": verworfen, "karten": karten, "naechster_schritt": schritt,
            "zeile": "Bewerbungen: %d offen · %d wartet Antwort · nächster Schritt: %s" % (offen, wartet, schritt)}


def nachforderung_schreiben(root, datei, grund, erzeuger=""):
    """F-77/NACHT kern 2 (30.09.2026): legt fuer eine UNVOLLSTAENDIGE Karte genau EINE Nachforderung an den erzeugenden Kanal an
    (abnahme/pm_eingang/<Karte>_UNVOLLSTAENDIG.md); kein zweiter Anlauf, solange die Datei liegt. -> True, wenn neu geschrieben.
    Vorher gab es sie nur fuer fehlende Kartenkopf-Felder - Karten mit fehlenden Optionen oder ohne Mail-Entwurf (Inhaltspruefung) blieben
    stumm rot, ohne dass der Kanal davon erfuhr."""
    ziel = Path(root) / "abnahme" / "pm_eingang" / (str(datei)[:-3] + "_UNVOLLSTAENDIG.md")
    if ziel.exists():
        return False
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text("\n".join([
        "# %s — Karte unvollständig, Kanal muss nachliefern" % datei, "",
        "**Grund:** %s" % (grund or "Kartenkopf v2 unvollständig (Pflichtfelder leer oder „unbekannt“)."),
        "**Erzeuger:** %s" % (erzeuger or "unbekannt (Kopfzeile `von:` fehlt)"),
        "**Karte:** `auftraege/freigabe/%s`" % datei, "",
        "Die Karte erscheint dem Patron bis dahin rot als „UNVOLLSTÄNDIG“, ohne Knöpfe zum Entscheiden. Standard: "
        "`auftraege/freigabe/_VORLAGE_FREIGABEKARTE_v2.md`; Entscheidungskarten mit Auswahl brauchen `optionen: A, B` + `option_a_titel: …`; "
        "eine Ja/Nein-Frage braucht trotzdem `optionen: Ja, Nein` (oder `art: zurkenntnis`, wenn nichts zu entscheiden ist).",
        "*(automatisch von JACK-Kern angelegt, einmal je Karte)*", ""]), encoding="utf-8")
    try:
        betrieb.append(betrieb.area(root) / "oberflaeche.jsonl", {"zeit": betrieb.now().isoformat(), "art": "karte_unvollstaendig_nachgefordert", "datei": str(datei)[:120], "grund": str(grund)[:160]})
    except Exception:
        pass
    return True


def nachforderungen_aufraeumen(root, eintraege):
    """F-103-Freischaltung Nacharbeit 3 (PM 30.09.2026): ein UNVOLLSTAENDIG-Vermerk in pm_eingang wandert nach `_geprueft/`, sobald seine Karte
    vollstaendig ist oder nicht mehr in auftraege/freigabe/ liegt. Nichts wird geloescht. Karten in Wiedervorlage (nicht in `eintraege`) bleiben unberuehrt.
    -> Anzahl verschoben."""
    import shutil
    basis = Path(root) / "abnahme" / "pm_eingang"
    frei = Path(root) / "auftraege" / "freigabe"
    vollstaendig = {x["datei"] for x in eintraege if x.get("v2_vollstaendig") is not False}
    n = 0
    for f in sorted(basis.glob("*_UNVOLLSTAENDIG.md")):
        datei = f.name[:-len("_UNVOLLSTAENDIG.md")] + ".md"
        if (frei / datei).is_file() and datei not in vollstaendig:
            continue
        ziel = basis / "_geprueft"
        ziel.mkdir(exist_ok=True)
        z = ziel / f.name
        if z.exists():
            z = ziel / (f.stem + "_" + betrieb.now().strftime("%H%M%S") + f.suffix)
        try:
            shutil.move(str(f), str(z)); n += 1
        except OSError:
            pass
    return n


def _inhalt_pruefung(root, kopf, text):
    """(ok, Grund). Eine Karte, deren Klick etwas SENDET/EINTRAEGT/VEROEFFENTLICHT, muss den vollen Inhalt zeigen (Nachtrag PM 5); Entscheidungskarten
    brauchen Optionen im Kopf (Nachtrag PM 6); jede Karte einen klaren Satz in `ablauf:` (Nachtrag PM 7). Sonst UNVOLLSTAENDIG - nicht freigebbar."""
    art = str(kopf.get("art") or "")
    ablauf = str(kopf.get("ablauf") or "")
    if art in ("anleitung", "zurkenntnis", "zur_kenntnis", "hausaufgabe"):
        return True, ""
    if len(ablauf.strip()) < 15:
        return False, "Kein klarer Satz unter „Ablauf“, was der Klick auslöst — Kanal muss nachliefern."
    if art == "entscheidung" and kopf.get("fuehrend", "").strip().lower() != "nein":
        opts = _optionen_kopf(kopf)
        if not opts:
            return False, "Optionen fehlen im Kartenkopf (optionen: A, B … und option_a_titel …) — Kanal muss nachliefern."
        for o in opts:
            if not o["titel"].strip():
                return False, "Titel der Option %s fehlt (option_%s_titel:, höchstens 8 Wörter)." % (o["key"], o["key"].lower())
            if len(o["titel"].split()) > 8:
                return False, "Titel der Option %s ist zu lang (höchstens 8 Wörter)." % o["key"]
    if art == "uebersicht":
        opts = _optionen_kopf(kopf)
        if not opts or any(not o["karte"] for o in opts):
            return False, "Übersichtskarte braucht je Option ein Ziel (option_x_karte:) — Kanal muss nachliefern."
    ohne_versand = re.sub(r"(?i)\b(kein|ohne|keinen)\s+testversand", "", ablauf)          # "kein Testversand" heisst gerade: es wird nichts gesendet
    sendet = art in ("externemail", "mailantwort", "mitarbeitermail") or "TESTVERSAND" in ohne_versand.upper()
    if sendet:
        if _entwurf_fehlt(root, kopf):
            return False, "Inhalt fehlt: zu dieser Karte gibt es keinen lesbaren Mail-Entwurf, also keine Vorschau — Kanal muss den Entwurf nachliefern."
    if "PORTAL" in ablauf.upper() and len(re.sub(r"\s+", " ", re.sub(r"^---.*?\n---", "", text or "", flags=re.S)).strip()) < 200:
        return False, "Inhalt fehlt: der Text zum Eintragen steht nicht in der Karte — Kanal muss ihn nachliefern."
    if art == "kalender" and not str(kopf.get("termin") or kopf.get("ics") or "").strip():
        return False, "Inhalt fehlt: der Termin (Datum/Uhrzeit/Ort) steht nicht in der Karte."
    return True, ""


def _ohne_test_karte(root, kopf):
    """F-104: True, wenn an dieser Mail-Karte die abgenommene Referenz-Aufmachung gilt (Vorschau -> FREIGEBEN, kein Testversand)."""
    try:
        if kopf.get("art") != "mitarbeitermail" or not kopf.get("entwurf"):
            return False
        import jack_mail_referenz, jack_postfaecher
        k, _ = jack_postfaecher._entwurf_zerlegen(root, kopf["entwurf"])
        return bool(jack_mail_referenz.regel_fuer(root, k))
    except Exception:
        return False


def _terminblock(root, kopf, dateiname, vorgangslage):
    """F-99: Pflichtinhalt jeder Karte mit Termin (Kalender-Karte oder Mail-Karte mit `termin:`): mit wem, Ort, Anlass,
    Abhaengigkeit, Fahrzeit/Alarm, Zeitzone, Label. Nur aus Kopffeldern und Vorgangsdaten - nichts wird erfunden.
    -> dict oder None (Karte ohne Termin)."""
    roh = (kopf.get("termin") or "").strip()
    if not roh:
        return None
    try:
        beginn = dt.datetime.fromisoformat(roh)
    except ValueError:
        return None
    tage = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
    abh = (kopf.get("abhaengigkeit") or "").strip()
    v = (vorgangslage or {}).get(dateiname) or {}
    if not abh and v and not v.get("fuehrend") and v.get("fuehrende_karte"):
        try:
            import jack_freigabe_vorgang as _vg
            karten = _vg._karten(root)
            fk = karten[v["fuehrende_karte"]][1]
            eigene = next((o for o in _vg.optionen(fk, karten) if dateiname in o["karten"]), None)
            titel_f = _vg._titel(fk, v["fuehrende_karte"])
            abh = ("Gilt nur, wenn %s gewählt wird (offene Entscheidung: %s)." % (eigene["titel"], titel_f)) if eigene \
                else "Hängt an der offenen Entscheidung: %s." % titel_f
        except Exception:
            abh = ""
    fz = {"min": kopf.get("fahrzeit_min", ""), "quelle": kopf.get("fahrzeit_quelle", ""), "abfahrt": kopf.get("abfahrt", ""),
          "von": kopf.get("abfahrt_von", "")}
    if not fz["min"] and kopf.get("termin_ort"):
        try:                                         # nur Tabelle, nie ein bezahlter Maps-Aufruf beim blossen Anzeigen
            import jack_termine as T
            standort = T.standort_lesen(root)["ort"]
            m = T._tabellenminuten(T._tabelle_lesen(root), standort, kopf["termin_ort"])
            if m:
                ab = T.abfahrt_berechnen(beginn, m)
                fz = {"min": str(m), "quelle": "geschaetzt", "abfahrt": ab.isoformat(), "von": standort}
        except Exception:
            pass
    aussen = kopf.get("gefahr") == "aussen" or (kopf.get("art") not in ("kalender",) and (kopf.get("gefahr") or "") != "keine")
    return {
        "wann": "%s %s, %s Uhr" % (tage[beginn.weekday()], beginn.strftime("%d.%m.%Y"), beginn.strftime("%H:%M")),
        "mit": kopf.get("termin_mit") or kopf.get("von") or kopf.get("an") or "",
        "ort": kopf.get("termin_ort", ""),
        "anlass": kopf.get("termin_anlass") or kopf.get("titel") or kopf.get("betreff") or "",
        "abhaengigkeit": abh,
        "fahrzeit_min": fz["min"], "fahrzeit_quelle": fz["quelle"],
        "abfahrt": fz["abfahrt"][11:16] if len(fz["abfahrt"]) >= 16 else "",
        "abfahrt_von": fz["von"],
        "zone": kopf.get("zeitzone") or "Europe/Berlin",
        "label": "NACH AUSSEN (Mail geht raus, dazu der Kalendereintrag)" if aussen else "INTERN — nichts geht nach aussen",
    }


def _abschnitt(text, ueberschrift):
    """F-98: Text unter '## <ueberschrift...>' bis zur naechsten '## ' (ohne die Ueberschrift)."""
    m = re.search(r"^##\s+%s[^\n]*\n(.*?)(?=^##\s|\Z)" % re.escape(ueberschrift), text or "", re.M | re.S)
    return m.group(1).strip() if m else ""


_PFAD_RE = re.compile(r"`?[\w./\-]*[\w\-]+\.(?:md|pdf|json|jsonl|py|mjs|png)`?|`?\b(?:betrieb|abnahme|auftraege|Notar)/[\w./\-]+`?")


def _ohne_technik(t):
    """F-99 I / F-100 B: keine Backticks, keine Dateipfade im Patron-Text (Belege stehen unter DETAILS)."""
    t = _PFAD_RE.sub("", str(t or ""))
    t = t.replace("`", "")
    t = re.sub(r"\(\s*(?:Entw(?:ü|ue)rfe|Beleg|Quelle)[^)]*:\s*(?:und\s*|,\s*)*\)", "", t)      # leer gewordene "(Entwürfe: … )"
    t = re.sub(r"\(\s*\)", "", t)
    t = re.sub(r",\s*\)", ")", t)
    t = re.sub(r"\s+([.,;)])", r"\1", t)
    return re.sub(r"[ \t]{2,}", " ", t).strip()


def _klammerfrei_teilen(text, trenner=","):
    teile, tief, akt = [], 0, ""
    for c in text:
        tief += (c == "(") - (c == ")")
        if c == trenner and tief == 0:
            teile.append(akt.strip()); akt = ""
        else:
            akt += c
    if akt.strip():
        teile.append(akt.strip())
    return [t for t in teile if t]


def _kurzfett(t):
    """Fett nur fuer kurze Stellen (<= 60 Zeichen); nie ganze Absaetze fett."""
    return re.sub(r"\*\*(.+?)\*\*", lambda m: m.group(0) if len(m.group(1)) <= 60 else m.group(1), t)


def _empfehlung_gliedern(text):
    """F-100 B: Abschnitt 'Empfehlung von JACK' -> [{"titel":..., "punkte":[...]}] fuer Empfehlung, Alternative, Warum,
    Kriterien der Abwaegung - je eine Zwischenueberschrift, darunter kurze Punkte. [] wenn nichts Erkennbares."""
    a = _abschnitt(text, "Empfehlung von JACK").split("**Mit dieser Freigabe erledigt")[0]
    a = _ohne_technik(a)
    marken = list(re.finditer(r"\*\*(Empfehlung|Alternative|Warum|Kriterien der Abwägung)\s*:?\s*([^*]*?)\*\*\s*:?", a))
    if not marken:
        return []
    raus = []
    for n, m in enumerate(marken):
        ende = marken[n + 1].start() if n + 1 < len(marken) else len(a)
        koerper = (m.group(2).strip() + " " + a[m.end():ende].strip()).strip()
        koerper = re.sub(r"^[\s.:]+", "", koerper)
        if m.group(1) == "Kriterien der Abwägung":
            punkte = _klammerfrei_teilen(koerper.rstrip("."), ",")
        else:
            koerper = re.sub(r"\s*(Spricht dafür|Spricht dagegen):", r"\n\1:", koerper)
            punkte = []
            for zeile in koerper.split("\n"):
                punkte += [x.strip() for x in re.split(r"(?<=[.;])\s+(?=[A-ZÄÖÜ„*])", zeile.strip()) if x.strip()]
        punkte = [_kurzfett(x) for x in punkte if x.strip(" .*")]
        if punkte:
            raus.append({"titel": m.group(1).replace("Kriterien der Abwägung", "Kriterien"), "punkte": punkte})
    reihenfolge = {"Empfehlung": 0, "Alternative": 1, "Warum": 2, "Kriterien": 3}
    return sorted(raus, key=lambda x: reihenfolge.get(x["titel"], 9))


def _vergleichstabelle(text):
    """F-98: erste Markdown-Tabelle unter '## Vergleich...' -> {"kopf":[...], "zeilen":[[...]]} oder None."""
    abschnitt = _abschnitt(text, "Vergleich")
    zeilen = [z for z in abschnitt.splitlines() if z.strip().startswith("|")]
    if len(zeilen) < 3:
        return None
    zellen = lambda z: [c.strip() for c in z.strip().strip("|").split("|")]
    return {"kopf": [_ohne_technik(c) for c in zellen(zeilen[0])], "zeilen": [[_ohne_technik(c) for c in zellen(z)] for z in zeilen[2:]]}


def freigabe_entscheiden(root, datei, entscheidung, von="Patron", freigabecode="", warte_bis="", option=""):
    """Der Knopf IST die Freigabe - und der ganze Weg in einem Schritt.

    freigegeben: die serverseitige Freigabe aus Block 3 wird erteilt UND
                 verbraucht, der Auftragskopf umgeschrieben, die Datei nach
                 offen/ verschoben. Der Patron sieht sie unten verschwinden
                 und oben in den Auftraegen auftauchen.
    abgelehnt:   Vermerk in die Datei, Kopf auf erledigt, nach erledigt/.
    warten:      bleibt liegen, bekommt eine sichtbare Wartemarke.
    """
    import shutil
    import jack_freigaben
    root = Path(root)
    if entscheidung not in ("freigegeben", "abgelehnt", "warten"):
        raise ValueError("Unbekannte Entscheidung")
    if not re.fullmatch(r"[^/\\]{1,200}\.md", str(datei or "")):
        raise ValueError("Unzulaessiger Dateiname")
    quelle = root / "auftraege" / "freigabe" / datei
    if not quelle.is_file() or quelle.is_symlink():
        # F-68 Punkt 6: eine Karte, die der Waechter zwischenzeitlich SELBST erledigt hat (Sitzung wieder ok), meldet
        # dem Patron kein "Vorgang hat sich geaendert" mehr - sie schliesst sich einfach, ohne zweiten Klick.
        erledigt = root / "auftraege" / "freigabe" / "ersetzt" / datei
        if erledigt.is_file():
            et = erledigt.read_text(encoding="utf-8", errors="replace")
            m = re.search(r"^erledigt_am:\s*(.+)$", et, re.M)
            zeit_txt = m.group(1).strip() if m else "kürzlich"
            protokoll(root, "freigabe_entscheidung", datei=datei, entscheidung=entscheidung, von=von,
                      wirkung="inzwischen erledigt (%s)" % zeit_txt)
            return {"ok": True, "wirkung": "Inzwischen erledigt (%s) — diese Karte hat sich von selbst erübrigt." % zeit_txt,
                    "ziel": "erledigt", "bereits_erledigt": True}
        raise ValueError("Dieser Vorgang liegt nicht mehr in auftraege/freigabe/")
    text = quelle.read_text(encoding="utf-8")
    jetzt_text = betrieb.now().strftime("%Y-%m-%d %H:%M")
    # Block 16b (1.1): Dieselbe Regel wie im Planer - Praefix TEST_ ODER Kopf
    # "test: ja". Keine zweite Definition von "Test" im Haus.
    import jack_planer
    test_lauf = jack_planer.ist_test(datei, _kopf(text))

    if entscheidung == "warten":
        # F-66: "Warten" fragt seither BIS WANN. warte_bis kommt fertig vom Dashboard (eine der vier Wahlmoeglichkeiten
        # oder ein frei gewaehltes Datum); Format YYYY-MM-DD HH:MM. Ohne Angabe bleibt das alte Verhalten (nur Wartemarke,
        # kein Termin, kein Verschwinden aus der Liste) - Rueckfall fuer Aufrufer, die das Feld nicht mitgeben.
        warte_bis = str(warte_bis or "").strip()
        satz_zusatz = ""
        if warte_bis:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", warte_bis):
                raise ValueError("Ungueltiges Datum fuer Wiedervorlage (erwartet JJJJ-MM-TT SS:MM).")
            neu = _kopf_setzen(text, "warte_bis", warte_bis)
            satz_zusatz = " Wiedervorlage am %s." % warte_bis
        else:
            neu = text
        neu = _kopf_setzen(neu, "wartemarke", jetzt_text + " vom Patron zurueckgestellt" + (" bis " + warte_bis if warte_bis else ""))
        quelle.write_text(neu, encoding="utf-8")
        protokoll(root, "freigabe_entscheidung", test=test_lauf, datei=datei, entscheidung="warten",
                  von=von, warte_bis=warte_bis, wirkung="Wartemarke gesetzt, bleibt in freigabe/" + satz_zusatz)
        return {"ok": True, "wirkung": ("Zurueckgestellt bis %s. Die Karte kommt dann von selbst wieder." % warte_bis
                                       if warte_bis else "Zurueckgestellt. Der Vorgang bleibt liegen und rutscht nach unten."),
                "ziel": "freigabe"}

    art = _art_von(text)
    entscheidungsvorlage = art in ENTSCHEIDUNGSARTEN

    # Block 13, dieselbe Falle an anderer Stelle: Ein Mailentwurf ist auch kein Arbeitsauftrag - das
    # bleibt so. Bis F-82 wurde "mailantwort" deshalb HIER abgewiesen und musste "an der Mail"
    # freigegeben werden. Patron-Anordnung 29.09.2026 ("Wenn ich eine Freigabe habe, dann mache ich
    # das hier drin"): "mailantwort" steht jetzt in ENTSCHEIDUNGSARTEN und laeuft ueber denselben
    # Weg wie externemail (Block unten, "entscheidungsvorlage") - _anwenden() sendet dort wirklich,
    # es entsteht weiterhin KEIN Arbeitsauftrag unter offen/.

    # F-79 (28.09.2026): eine "zurkenntnis"-Karte (Termin automatisch geändert) hat statt FREIGEBEN/ABLEHNEN
    # die Bedeutung GELESEN/RÜCKGÄNGIG - RÜCKGÄNGIG (= Klick auf den ABLEHNEN-Knopf) stellt ueber
    # jack_termine den vorherigen Zeitpunkt wieder her, BEVOR die Karte wie gewohnt nach erledigt/ wandert.
    # Zweite Opus-Endpruefung F-79, Fund B1: ein Fehlschlag hier durfte NIE stillschweigend durchfallen -
    # die Karte waere trotzdem nach erledigt/ verschoben worden und der Patron haette "Abgelehnt und nach
    # erledigt verschoben" gelesen, ohne dass der Termin wirklich zurueckgestellt wurde. Jetzt: bei
    # Fehlschlag bricht die Entscheidung HIER ab, die Karte bleibt liegen, der Patron sieht den echten Grund.
    if entscheidung == "abgelehnt" and art == "zurkenntnis":
        kopf_zk = _kopf(text)
        if not (kopf_zk.get("akte_pfad") and kopf_zk.get("alt_beginn")):
            if str(kopf_zk.get("zugang", "")).strip().lower() == "ja":
                # F-108: Code-Karte - "NEU ANFORDERN NÖTIG" ist keine Warnung, nur ein Vermerk. Code wird sofort geschwaerzt.
                import jack_freigaben as _jf
                neu = _jf._zugang_schwaerzen(_kopf_setzen(text, "status", "erledigt"))
                neu += "\n\n## Vermerk %s\nPatron: NEU ANFORDERN NÖTIG (Code funktionierte nicht).\n" % jetzt_text
                ziel = _frei_verschieben(root / "auftraege" / "erledigt", quelle, neu)
                protokoll(root, "freigabe_entscheidung", test=test_lauf, datei=datei, entscheidung="abgelehnt",
                          von=von, ziel=ziel.name, wirkung="Zugangskarte: neu anfordern noetig, nach erledigt/ verschoben")
                if not test_lauf:
                    try:        # damit die Ruhe-Regel (jack_ruhe, herkunft maske*) diese Patron-Aktion sieht
                        _jf.buchen(root, "zugang_neu_anfordern", datei=datei, herkunft="maske")
                    except Exception:
                        pass
                return {"ok": True, "wirkung": "Vermerkt: neuen Code beim Dienst anfordern. Karte abgelegt: " + ziel.name,
                        "ziel": "erledigt"}
            # F-83: keine Termin-Akte an dieser Karte (z.B. Sicherheitscode-Mitteilung) - ABLEHNEN
            # bedeutet hier "NICHT ICH", keine Rueckgaengig-Handlung. Statt eines Fehlers entsteht eine
            # Warnkarte, die Karte selbst wandert wie gewohnt nach erledigt/ (Code steht nur in der Mail,
            # bewusst nicht hier wiederholt).
            try:
                import jack_freigaben
                v2_warn = {
                    "projekt": kopf_zk.get("projekt") or "Konten & Zugänge", "marke": kopf_zk.get("marke") or "HOLDING",
                    "eingegangen": jetzt_text, "von": kopf_zk.get("von") or "unbekannter Absender",
                    "an": "Patron", "art": "entscheidung",
                    "betreff": "WARNUNG — nicht selbst angeforderter Sicherheitscode",
                    "kern": "Der Patron hat auf der Karte „%s“ NICHT ICH gewählt - der Sicherheitscode "
                            "wurde nicht von ihm selbst angefordert." % kopf_zk.get("betreff", datei),
                    "frage": "Konto/Zugang jetzt prüfen?",
                    "empfehlung": "Passwort des betroffenen Kontos zeitnah ändern und prüfen, ob eine "
                                  "fremde Anmeldung stattgefunden hat.",
                    "frist": "so bald wie möglich", "dringlichkeit": "hoch",
                    "ablauf": "ZUR KENNTNIS — keine automatische Handlung, nur Warnung.",
                }
                jack_freigaben.karte_schreiben(root, v2_warn, "## Auftrag\nDer Patron hat NICHT ICH gewählt. "
                    "Bitte das betroffene Konto pruefen.\n", herkunft="jack_oberflaeche.freigabe_entscheiden (NICHT ICH)")
            except Exception as fehler:
                protokoll(root, "nicht_ich_warnkarte_fehler", datei=datei, grund=str(fehler)[:160])
            protokoll(root, "sicherheitscode_nicht_ich", datei=datei, von=von)
            neu = _kopf_setzen(text, "status", "erledigt")
            neu = _kopf_setzen(neu, "abgelehnt", jetzt_text + " vom Patron (NICHT ICH)")
            neu += ("\n\n## Vom Patron als 'NICHT ICH' gemeldet am %s\nEine Warnkarte wurde angelegt. "
                    "Nichts geloescht.\n" % jetzt_text)
            ziel = _frei_verschieben(root / "auftraege" / "erledigt", quelle, neu)
            protokoll(root, "freigabe_entscheidung", test=test_lauf, datei=datei, entscheidung="abgelehnt",
                      von=von, ziel=ziel.name, wirkung="NICHT ICH - Warnkarte angelegt, nach erledigt/ verschoben")
            return {"ok": True, "wirkung": "Als 'NICHT ICH' gemeldet, Warnkarte angelegt, nach erledigt verschoben: " + ziel.name,
                    "ziel": "erledigt"}
        try:
            import jack_termine
            ergebnis_rg = jack_termine.aenderung_rueckgaengig(
                root, Path(kopf_zk["akte_pfad"]), alt_beginn=kopf_zk["alt_beginn"], von=von)
        except Exception as fehler:
            protokoll(root, "termin_rueckgaengig_fehler", datei=datei, grund=str(fehler)[:160])
            return {"ok": False, "ziel": "freigabe",
                    "wirkung": "Rückgängig fehlgeschlagen (%s). Die Karte bleibt liegen, nichts wurde "
                               "verschoben." % str(fehler)[:160]}
        protokoll(root, "termin_rueckgaengig", datei=datei, ok=ergebnis_rg.get("ok"),
                  meldung=ergebnis_rg.get("meldung", ""))
        if not ergebnis_rg.get("ok"):
            return {"ok": False, "ziel": "freigabe",
                    "wirkung": "Rückgängig fehlgeschlagen: %s. Die Karte bleibt liegen, nichts wurde "
                               "verschoben." % ergebnis_rg.get("meldung", "")}

    if entscheidung == "abgelehnt":
        neu = _kopf_setzen(text, "status", "erledigt")
        neu = _kopf_setzen(neu, "abgelehnt", jetzt_text + " vom Patron")
        neu += ("\n\n## Vom Patron abgelehnt am %s\nDer Patron hat diesen Vorgang in der "
                "Maske abgelehnt. Er wird nicht ausgefuehrt. Nichts geloescht - die Datei "
                "liegt vollstaendig in auftraege/erledigt/.\n" % jetzt_text)
        ziel = _frei_verschieben(root / "auftraege" / "erledigt", quelle, neu)
        protokoll(root, "freigabe_entscheidung", test=test_lauf, datei=datei, entscheidung="abgelehnt",
                  von=von, ziel=ziel.name, wirkung="nach erledigt/ verschoben")
        return {"ok": True, "wirkung": "Abgelehnt und nach erledigt verschoben: " + ziel.name,
                "ziel": "erledigt"}

    # ── Block 13: Entscheidungsvorlage? Dann wird die Entscheidung ANGEWANDT,
    #    nicht ein Arbeiter gestartet. Die Datei geht nach erledigt/, nie nach
    #    offen/ - dort wuerde der Planer sie dem API-Arbeiter geben.
    if entscheidung == "freigegeben" and entscheidungsvorlage:
        # F-98: fuehrende Karte eines verbundenen Vorgangs - FREIGEBEN braucht die gewaehlte Option, danach werden die
        # verbundenen Karten erledigt bzw. vorbereitet (gesendet wird nichts).
        vorgang_satz = ""
        try:
            import jack_freigabe_vorgang as _vg
            kopf_vg = _kopf(text)
            if art == "entscheidung" and kopf_vg.get("fuehrend", "").lower() != "ja" and _optionen_kopf(kopf_vg):
                # Nachtrag PM 6: Entscheidungskarte mit Optionen im Kopf (ohne verbundene Karten) - die Wahl wird festgehalten
                if not str(option or "").strip():
                    raise ValueError("Bitte zuerst die Option waehlen (FREIGEBEN A, B …).")
                gew = next((o for o in _optionen_kopf(kopf_vg) if o["key"] == str(option).upper()), None)
                if not gew:
                    raise ValueError("Unbekannte Option")
                vorgang_satz = "Option %s (%s) gewählt." % (gew["key"], gew["titel"])
            elif art == "entscheidung" and kopf_vg.get("fuehrend", "").lower() == "ja" and _vg.optionen(kopf_vg):
                if not str(option or "").strip():
                    raise ValueError("Bitte zuerst die Option waehlen (FREIGEBEN A oder FREIGEBEN B).")
                if kopf_vg.get("option_gewaehlt", "").strip():
                    raise ValueError("Die Option %s ist schon gewaehlt - die Mails stehen unten in dieser Karte." % kopf_vg["option_gewaehlt"])
                _vg.wirkung(root, datei, option)               # Fehler hier = nichts angefasst
                vorgang_satz = _vg.abschliessen(root, datei, option, von=von)
                # F-100 (Nachtrag PM 2): bleiben Mails der gewaehlten Option offen, BLEIBT die fuehrende Karte und zeigt sie direkt
                # unter der Entscheidung (Vorschau, TESTVERSAND, Code, FREIGEBEN). Sie schliesst sich, sobald alle erledigt sind.
                if _vg.offene_mailkarten(root, datei):
                    neu_text = _kopf_setzen(text, "option_gewaehlt", str(option).upper())
                    neu_text = _kopf_setzen(neu_text, "entschieden_am", jetzt_text)
                    quelle.write_text(neu_text, encoding="utf-8")
                    protokoll(root, "freigabe_entscheidung", test=test_lauf, datei=datei, vorlagenart=art, entscheidung="freigegeben",
                              von=von, wirkung=vorgang_satz + " Karte bleibt offen: Mails unter der Entscheidung.")
                    return {"ok": True, "ziel": "freigabe", "vorgang_offen": True,
                            "wirkung": vorgang_satz + " Die Mails stehen jetzt direkt unter der Entscheidung in dieser Karte."}
        except ValueError:
            raise
        except Exception as fehler:
            protokoll(root, "freigabe_entscheidung", test=test_lauf, datei=datei, vorlagenart=art, entscheidung="freigegeben",
                      von=von, wirkung="Vorgang nicht abgeschlossen: " + str(fehler)[:160])
            return {"ok": False, "ziel": "freigabe",
                    "wirkung": "Die verbundenen Karten liessen sich nicht anwenden: %s. Nichts wurde freigegeben." % str(fehler)[:160]}
        try:
            ok, satz = _anwenden(root, art, datei, text, von,
                                 freigabecode=freigabecode)
            if vorgang_satz:
                satz = vorgang_satz
        except Exception as fehler:
            protokoll(root, "freigabe_entscheidung", test=test_lauf, datei=datei, vorlagenart=art,
                      entscheidung="freigegeben", von=von,
                      wirkung="Anwendung fehlgeschlagen: " + str(fehler)[:160])
            return {"ok": False, "ziel": "freigabe",
                    "wirkung": ("Die Entscheidung liess sich nicht anwenden: %s. "
                                "Die Vorlage bleibt liegen." % str(fehler)[:160])}
        if not ok:
            protokoll(root, "freigabe_entscheidung", test=test_lauf, datei=datei, vorlagenart=art,
                      entscheidung="freigegeben", von=von, wirkung="nicht angewandt: " + satz)
            return {"ok": False, "ziel": "freigabe",
                    "wirkung": satz + " Die Vorlage bleibt liegen."}
        neu = _kopf_setzen(text, "status", "erledigt")
        neu = _kopf_setzen(neu, "freigabe", "ja")
        neu = _kopf_setzen(neu, "freigegeben", jetzt_text + " durch den Patron")
        neu = _kopf_loeschen(neu, "wartemarke")
        neu += ("\n\n## Vom Patron freigegeben am %s\n\n%s\n\n"
                "Dies war eine **Entscheidungsvorlage**, kein Arbeitsauftrag. Die "
                "Entscheidung wurde unmittelbar angewandt - ohne Modellaufruf und "
                "ohne den API-Arbeiter. Nichts wurde nach auftraege/offen/ gelegt.\n"
                % (jetzt_text, satz))
        ziel = _frei_verschieben(root / "auftraege" / "erledigt", quelle, neu)
        # Block 16 (H1): Die Kurzfassung der WIRKUNG gehoert ins Protokoll -
        # "Entscheidung angewandt" sagt nicht, was angewandt wurde.
        protokoll(root, "freigabe_entscheidung", test=test_lauf, datei=datei, vorlagenart=art,
                  entscheidung="freigegeben", von=von, ziel=ziel.name,
                  wirkung=satz,
                  wirkung_lang="Entscheidung angewandt, nach erledigt/ verschoben")
        return {"ok": True, "ziel": "erledigt", "datei_neu": ziel.name,
                "entscheidungsvorlage": True, "wirkung": satz}

    # freigegeben - der volle Weg aus Block 3 (nur fuer echte Auftraege)
    kennung = None
    for e in jack_freigaben.offene(root):
        if e["datei"] == datei and e["status"] in ("wartet", "erteilt"):
            kennung = e["kennung"]
            break
    if not kennung:
        kennung, _ = jack_freigaben.anfordern(root, datei, grund="Aus der Maske entschieden")
    if not kennung:
        raise ValueError("Fuer diesen Vorgang gibt es keine Freigabekennung")
    ok, meldung = jack_freigaben.erteilen(root, kennung, von=von, herkunft="maske")
    if not ok:
        protokoll(root, "freigabe_entscheidung", test=test_lauf, datei=datei, entscheidung="freigegeben",
                  von=von, wirkung="abgewiesen: " + meldung)
        return {"ok": False, "wirkung": meldung, "ziel": "freigabe"}
    verbraucht, meldung2 = jack_freigaben.verbrauchen(root, kennung, datei, herkunft="maske")
    if not verbraucht:
        protokoll(root, "freigabe_entscheidung", test=test_lauf, datei=datei, entscheidung="freigegeben",
                  von=von, wirkung="nicht verbraucht: " + meldung2)
        return {"ok": False, "wirkung": meldung2, "ziel": "freigabe"}
    neu = _kopf_setzen(text, "status", "offen")
    neu = _kopf_setzen(neu, "freigabe", "ja")
    neu = _kopf_setzen(neu, "freigegeben", jetzt_text + " durch den Patron")
    neu = _kopf_loeschen(neu, "wartemarke")
    ziel = _frei_verschieben(root / "auftraege" / "offen", quelle, neu)
    protokoll(root, "freigabe_entscheidung", test=test_lauf, datei=datei, entscheidung="freigegeben",
              von=von, kennung=kennung, ziel=ziel.name,
              wirkung="Freigabe erteilt und verbraucht, nach offen/ verschoben")
    return {"ok": True, "ziel": "offen", "datei_neu": ziel.name,
            "wirkung": "Freigegeben. Der Auftrag steht jetzt bei den Auftraegen: " + ziel.name}


def _kopf_setzen(text, feld, wert):
    zeilen = text.splitlines(keepends=True)
    if not zeilen or zeilen[0].strip() != "---":
        return text
    ende = None
    for nr in range(1, len(zeilen)):
        if zeilen[nr].strip() == "---":
            ende = nr
            break
    if ende is None:
        return text
    umbruch = "\r\n" if zeilen[0].endswith("\r\n") else "\n"
    neue = "%-11s %s%s" % (feld + ":", wert, umbruch)
    for nr in range(1, ende):
        if zeilen[nr].partition(":")[0].strip().lower() == feld:
            zeilen[nr] = neue
            return "".join(zeilen)
    zeilen.insert(ende, neue)
    return "".join(zeilen)


def _kopf_loeschen(text, feld):
    zeilen = text.splitlines(keepends=True)
    if not zeilen or zeilen[0].strip() != "---":
        return text
    raus = [zeilen[0]]
    im_kopf = True
    for zeile in zeilen[1:]:
        if im_kopf and zeile.strip() == "---":
            im_kopf = False
        elif im_kopf and zeile.partition(":")[0].strip().lower() == feld:
            continue
        raus.append(zeile)
    return "".join(raus)


def _frei_verschieben(ordner, quelle, neuer_text):
    """Nichts ueberschreiben: ein belegter Name bekommt eine Nummer."""
    import shutil
    ordner.mkdir(parents=True, exist_ok=True)
    ziel = ordner / quelle.name
    nr = 2
    while True:
        try:
            reservierung = ziel.open("x", encoding="utf-8")
            break
        except FileExistsError:
            ziel = ordner / ("%s-%d%s" % (quelle.stem, nr, quelle.suffix))
            nr += 1
    if re.search(r"(?m)^zugang:\s*ja\s*$", neuer_text or ""):        # F-108: eine abgelegte Code-Karte traegt keinen Code mehr
        try:
            import jack_freigaben as _jf
            neuer_text = _jf._zugang_schwaerzen(neuer_text)
        except Exception:
            pass
    with reservierung:
        quelle.write_text(neuer_text, encoding="utf-8")
        shutil.move(str(quelle), str(ziel))
    return ziel


if __name__ == "__main__":
    import sys
    wurzel = Path(__file__).resolve().parent
    was = sys.argv[1] if len(sys.argv) > 1 else "anordnung"
    tabelle = {"anordnung": lambda: anordnung(wurzel),
               "marken": lambda: markenlage(wurzel),
               "agenten": lambda: agentenlage(wurzel),
               "wissen": lambda: wissenslage(wurzel),
               "freigaben": lambda: freigabenlage(wurzel)}
    if was in tabelle:
        print(json.dumps(tabelle[was](), ensure_ascii=False, indent=1))
    elif was == "steuern":
        print(json.dumps(marken_steuern(wurzel, sys.argv[2], sys.argv[3]), ensure_ascii=False))
    elif was == "entscheiden":
        print(json.dumps(freigabe_entscheiden(wurzel, sys.argv[2], sys.argv[3],
                                              von="Befehlszeile (keine Patron-Bestaetigung)"),
                         ensure_ascii=False))
    else:
        print("anordnung | marken | agenten | freigaben | steuern <marke> <befehl> | "
              "entscheiden <datei> <freigegeben|abgelehnt|warten>")
