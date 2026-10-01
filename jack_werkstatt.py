#!/usr/bin/env python3
"""F-100 Nachtrag PM 8 (30.09.2026): Kachel "Werkstatt" - was wird gerade gebaut, wann ist es da. Nur Lesen.
Quellen: betrieb/herzschlag/<kanal>.json, auftraege/pm_ausgang/<kanal>/, abnahme/pm_eingang/*MELDUNG*, betrieb/neustarts.log, jack_ruhe.
Keine Dateinamen und kein Fachjargon in der Ausgabe."""
import datetime as dt
import json
import re
import time
from pathlib import Path

import jack_ruhe

KANAELE = [("kern", "Dashboard & Freigaben"), ("sprache", "Sprache"), ("patronos", "PATRONOS.AI"), ("cashflow", "Cashflow"), ("gruendung", "Gründung"),
           ("bewerbungen", "Bewerbungen"), ("inhalt", "Inhalt"), ("social", "Social")]
TAKT_MIN = 15


def _lesen(p, ersatz=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ersatz


def _klar(t):
    t = re.sub(r"`[^`]*`", "", str(t or ""))
    t = re.sub(r"[\w./-]+\.(md|json|jsonl|py|mjs|html|png)\b", "", t)
    t = re.sub(r"\b(F-\d{2,3}|FR-\d{4})\b", "", t)
    t = re.sub(r"\*\*|__|^#+\s*", "", t, flags=re.M)
    return re.sub(r"\s+", " ", t).strip(" —-:·")


def _neustarts(root):
    """{kanal: letzter Neustart datetime} und {kanal: (zeit, grund) der letzten Verschiebung}"""
    letzte, verschoben = {}, {}
    try:
        zeilen = (Path(root) / "betrieb" / "neustarts.log").read_text(encoding="utf-8", errors="replace").splitlines()[-400:]
    except OSError:
        return letzte, verschoben
    for z in zeilen:
        t = z.split("\t")
        if len(t) < 3 or not t[1].startswith("Kanal "):
            continue
        kanal = t[1][6:].strip()
        try:
            zeit = dt.datetime.strptime(t[0], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        if "verschoben" in z:
            verschoben[kanal] = (zeit, z)
        elif "PID" in z:
            letzte[kanal] = zeit
            verschoben.pop(kanal, None)
    return letzte, verschoben


def _titel(datei):
    try:
        z = Path(datei).read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for x in z[:12]:
        if x.startswith("#"):
            return _klar(x.split("—", 1)[-1] if "—" in x else x)[:80]
    return ""


def _meldung(root, nr):
    """Neueste Meldung zum Auftrag `nr` (F-xxx): (mtime, Kurzfassung max. 5 Saetze/Zeilen)"""
    if not nr:
        return None
    dateien = sorted((p for p in (Path(root) / "abnahme" / "pm_eingang").glob("%s*MELDUNG*.md" % nr) if ".vor_" not in p.name), key=lambda p: p.stat().st_mtime)
    if not dateien:
        return None
    p = dateien[-1]
    zeilen = [x for x in (_klar(z) for z in p.read_text(encoding="utf-8", errors="replace").splitlines()) if x][:5]
    return dt.datetime.fromtimestamp(p.stat().st_mtime), zeilen


AUFTRAGSSTAND_AB = 103


def auftragsstand(root):
    """NACHT KERN 3 Nr. 4: Stand der Auftraege ab F-103 - abgeleitet, nichts Handgepflegtes ausser `betrieb/werkstatt_stand.json` ("extra": Eintraege
    ohne Auftragsdatei). fertig = Datei in erledigt/; in Arbeit = Datei in einem Kanal oder im Herzschlag; wartet auf Patron = offene FRAGE in pm_eingang."""
    root = Path(root)
    aus = root / "auftraege" / "pm_ausgang"
    stand = {}

    def nr_von(name):
        m = re.match(r"([FM])-(\d{1,3})", name)
        return (m.group(1) + "-" + m.group(2), int(m.group(2)), m.group(1)) if m else None

    def setzen(nr, titel, zustand):
        rang = {"fertig": 0, "in Arbeit": 1, "wartet auf Patron": 2}
        if nr not in stand or rang[zustand] >= rang[stand[nr]["zustand"]]:
            stand[nr] = {"nr": nr, "titel": titel or stand.get(nr, {}).get("titel", ""), "zustand": zustand}
    for p in sorted((aus / "erledigt").glob("*.md")):
        n = nr_von(p.name)
        if n and n[2] == "F" and n[1] >= AUFTRAGSSTAND_AB and "_ABGENOMMEN" not in p.name and "_NACHTRAG" not in p.name and "_FREISCHALTUNG" not in p.name and ".vor_" not in p.name:
            setzen(n[0], _titel(p), "fertig")
    for kanal, _name in KANAELE:
        ordner = aus / kanal
        for p in (sorted(ordner.glob("*.md")) if ordner.is_dir() else []):
            n = nr_von(p.name)
            if n and (n[2] == "M" or n[1] >= AUFTRAGSSTAND_AB) and "_ABGENOMMEN" not in p.name and "_NACHTRAG" not in p.name:
                setzen(n[0], _titel(p), "in Arbeit")
    for p in sorted((root / "abnahme" / "pm_eingang").glob("*_FRAGE.md")):
        n = nr_von(p.name)
        if n and (n[2] == "M" or n[1] >= AUFTRAGSSTAND_AB) and stand.get(n[0], {}).get("zustand") != "fertig":
            setzen(n[0], stand.get(n[0], {}).get("titel") or _titel(p), "wartet auf Patron")
    extra = (_lesen(root / "betrieb" / "werkstatt_stand.json", {}) or {}).get("extra") or []
    for x in extra:
        if x.get("nr") and x.get("zustand") in ("fertig", "in Arbeit", "wartet auf Patron"):
            stand[x["nr"]] = {"nr": x["nr"], "titel": str(x.get("titel") or "")[:90], "zustand": x["zustand"]}
    for x in stand.values():
        x["titel"] = re.sub(r"^nach \)\s*—\s*", "", x["titel"])
    return sorted(stand.values(), key=lambda s: (s["nr"][0] != "F", int(s["nr"].split("-")[1])))


def werkstatt(root, jetzt=None):
    root = Path(root)
    j = (jetzt or dt.datetime.now()).replace(tzinfo=None)
    letzte, verschoben = _neustarts(root)
    aktiv, warum = jack_ruhe.patron_aktiv(root / "betrieb")
    m = re.search(r"vor (\d+) Min", warum)
    ruhe_in = max(0, 30 - int(m.group(1))) if (aktiv and m) else (30 if aktiv else 0)
    raus = []
    for kanal, name in KANAELE:
        herz = _lesen(root / "betrieb" / "herzschlag" / (kanal + ".json"), {}) or {}
        ordner = root / "auftraege" / "pm_ausgang" / kanal
        offen = sorted((p for p in ordner.glob("F-*.md")), key=lambda p: p.name) if ordner.is_dir() else []
        nr = str(herz.get("auftrag") or "")
        nr = nr if re.fullmatch(r"[A-Z]{1,3}-\d{1,3}", nr) else (re.match(r"F-\d{2,3}", offen[0].name).group(0) if offen else "")
        titel = _titel(offen[0]) if offen else ""
        if not titel and nr:
            t = next((p for p in (root / "auftraege" / "pm_ausgang" / "erledigt").glob(nr + "_*.md")), None)
            titel = _titel(t) if t else ""
        mel = _meldung(root, nr)
        zustand_herz = str(herz.get("zustand") or "")
        try:
            herz_alt = time.time() - float(herz.get("epoch", 0))
        except (TypeError, ValueError):
            herz_alt = 1e9
        if not herz or herz_alt > 900 and not offen:
            zustand, satz = "unbekannt", "Kein Lebenszeichen"
        elif zustand_herz == "arbeitet" or offen:
            zustand, satz = "baut", ("baut gerade" if (nr or offen) else "arbeitet gerade")
            if mel and letzte.get(kanal) and mel[0] > letzte[kanal]:
                zustand, satz = "gebaut", "gebaut, wartet auf Einbau"
            elif mel and letzte.get(kanal) and mel[0] <= letzte[kanal] and not offen:
                zustand, satz = "eingebaut", "eingebaut um %s" % letzte[kanal].strftime("%H:%M")
        else:
            zustand, satz = "wartet", "wartet auf einen Auftrag"
            if mel and letzte.get(kanal) and mel[0] <= letzte[kanal]:
                zustand, satz = "eingebaut", "eingebaut um %s" % letzte[kanal].strftime("%H:%M")
        naechster = ""
        if zustand == "gebaut":
            v = verschoben.get(kanal)
            takt = (letzte[kanal] + dt.timedelta(minutes=TAKT_MIN)) if kanal in letzte else j
            fruehestens = max(j + dt.timedelta(minutes=ruhe_in), takt, j)
            naechster = ("frühestens %s Uhr" % fruehestens.strftime("%H:%M")) + (" (sobald du 30 Min nichts tippst oder sagst)" if aktiv else "") + ("" if v else " — Einbau ist noch nicht beauftragt")
        raus.append({"kanal": kanal, "name": name, "auftrag": titel or ("Auftrag " + nr if nr else ("Nachtbetrieb, kein fester Auftrag" if zustand == "baut" else "kein Auftrag")), "zustand": zustand, "zustand_text": satz,
                     "naechster_einbau": naechster, "merkst_du": (_klar(mel[1][0]) if mel and mel[1] else "")[:140], "kurzfassung": (mel[1] if mel else [])[:5],
                     "eingebaut_um": letzte[kanal].strftime("%H:%M") if kanal in letzte else ""})
    return {"zeit": j.isoformat(timespec="minutes"), "patron_aktiv": aktiv, "ruhe_noch_min": ruhe_in, "kanaele": raus, "auftragsstand": auftragsstand(root),
            "kurz": next(("%s: %s" % (k["name"], k["zustand_text"]) for k in raus if k["zustand"] == "baut"), "Nichts wird gerade gebaut.")}
