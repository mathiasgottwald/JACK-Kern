#!/usr/bin/env python3
"""Paket 6 "Lernen" (F-20, 24.09.2026; PM-Entscheidungen 1-3 aus entscheidungen/2026-09-24_paket6_lernen_VORLAGE.md).

Kette: belegter Fehler -> Fehlerkatalog -> Regel (freigegebene Liste) -> hoechstens 3 Lernhinweise im
Auftragsvertrag -> Pruefer prueft sie mit -> Wirkung vorher/nachher gemessen -> schadende Regel ruht.

Sicherheitsregeln (Injektionsabwehr):
- Der Fehlerkatalog speichert NIE Text aus Ergebnissen, Fehlermeldungen oder Webseiten. Er speichert nur eine
  Fehlerart aus einer festen Liste (FEHLERARTEN, hier im Code), Marke, Ablauf, Auftrag, Lauf, Fundstelle und
  SHA-256 der Fundstelle.
- Ein Lernhinweis ist IMMER der woertliche Hinweistext einer freigegebenen Regel aus betrieb/lernregeln.json
  (PM-Freigabe je Regel, freigabe_sha256 ueber den freigegebenen Teil, hoechstens 160 Zeichen, feste Zeichenmenge).
  Eine Regel mit veraendertem Hinweis ohne passende Freigabe-Pruefsumme wird verworfen.
- Automatisch aendert sich an einer Regel nur status (aktiv -> ruht), status_grund, status_seit und wirkung.

Zaehlregel: ein Fehler zaehlt je (Lauf, Fehlerart) einmal. Verfall: eine Regel speist nur, wenn ihr Fehler
in derselben Marke und demselben Ablauf mindestens mindest_haeufigkeit-mal (verschiedene Laeufe) belegt ist
UND der letzte Beleg hoechstens 30 Tage alt ist.

Aufruf: /usr/bin/python3 jack_lernen.py katalog | hinweise <MARKE> <ablauf> | wirkung | bericht | gelegenheiten
"""
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import sys
from pathlib import Path

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER))
import jack_betrieb as betrieb  # noqa: E402

SCHEMA = 1
REGELN = "lernregeln.json"
KATALOG = "fehlerkatalog.jsonl"
WIRKUNG = "lernwirkung.jsonl"
GELEGENHEITEN = "gelegenheiten.jsonl"
GEGENPROBEN_LAEUFE = "gegenproben_laeufe.jsonl"
VERLAUF = "lernregeln_verlauf"
VERFALL_TAGE = 30
MAX_HINWEISE = 3
HINWEIS_MAX = 160
MIN_N = 3                      # PM-Frage 3: Wirkung erst ab >= 3 vergleichbaren Auftraegen je Seite
TOLERANZ = 0.10                # verschlechtert = nachher > vorher * 1,10 UND ueber der Mindestdifferenz
MINDESTDIFFERENZ = {"korrekturrunden": 0.2, "tor2_zurueckweisungen": 0.2, "kosten_je_annahme_usd": 0.05,
                    "zeit_bis_annahme_min": 2.0}
KENNZAHLEN = (("korrekturrunden", "Korrekturrunden Tor 1 je Auftrag"),
              ("tor2_zurueckweisungen", "Zurückweisungen Tor 2 je Auftrag"),
              ("kosten_je_annahme_usd", "Kosten je angenommenem Ergebnis"),
              ("zeit_bis_annahme_min", "Zeit bis Annahme (min)"))
GELEGENHEITEN_JE_WOCHE = 3
GELEGENHEIT_MIN_N = 3
HINWEIS_ZEICHEN = re.compile(r"[A-Za-z0-9ÄÖÜäöüß ,.;:()/%+\-–„“]+")
REGEL_KENNUNG = re.compile(r"R\d{2}|S\d{3}")                     # S = Stilregel des Patrons (F-21)
FREIGABE = re.compile(r"PM \d{2}\.\d{2}\.( \(F-\d+\))?")
FREIGABE_PATRON = re.compile(r"Patron \d{2}\.\d{2}\. \(Mail\)")   # Stilregel: Freigabe ist die eigene Aenderung des Patrons
STIL = "stil_patron"
# F-21 (PM, Vorlage B3): Rang = Haeufigkeit x Folgekosten. Gewicht je Regel: Tor-1/Tor-2-Fehler 3, Planer-Abbruch 2,
# Waechter-Sperre ohne Folge 1. Fehlt das Feld, gilt 1.
GEWICHTE = (1, 2, 3)

# Feste Fehlerarten. Nur diese Namen koennen im Katalog stehen.
FEHLERARTEN = {
    "pflichtpunkte": "Abschlusspruefung: Pflichtpunkt nicht belegt",
    "ergebnisstand": "Ergebnis nach der Pruefung veraendert",
    "sicherung": "Sicherung vor dem Schreiben fehlgeschlagen",
    "belegpfad": "Beleg ausserhalb der Holding oder Verweis",
    "zahl_messung": "Tor 1: Zahl weicht von der lokalen Messung ab (P04/G07)",
    "wortgrenze": "Tor 1: Wortgrenze ueberschritten",
    "wortregel_beleg": "Tor 1: Wortregel-Datei nicht als Beleg genannt",
    "abschnitt_leer": "Tor 1: Lauf/Ergebnis/Nachweis nicht ausgefuellt",
    "recherche_objekt": "Tor 1: Recherche-Objekt fehlt oder unvollstaendig",
    "tor2_teilbelege": "Tor 2: zusammengesetzter Pflichtpunkt ohne Teilbelege",
    "tor2_pflichtzeile": "Tor 2: Pflichtzeile/Zettelformat unvollstaendig",
    "tor2_zurueckweisung": "Tor 2: Zurueckweisung durch den unabhaengigen Pruefer",
    "suchpfad": "Waechter: Suche/Pfad verlaesst die Holding oder trifft Schluesseldateien",
    "pfad_verschachtelt": "Waechter: verschachtelter JACK-Pfad",
    "befehl_gesperrt": "Waechter: nicht erlaubter Shell-Befehl",
    "schreibort": "Waechter: Schreiben an geschuetztem Ort",
    "abbruch_ohne_abschluss": "Planer: Lauf endete ohne Abschluss (Abbruch gesichert)",
    "logo_beleg": "Veroeffentlichung: Logo-/Wort-Bild-Marken-Beleg fehlt",
}
FEHLERARTEN.update({"gegenprobe_G%02d" % i: "Gegenprobe G%02d nicht bestanden" % i for i in range(1, 14)})

# Erkennung auf Systemmeldungen (erste passende Art gewinnt je Teilmeldung). Tor 1 = "Lokale Vorpruefung gesperrt".
TOR1 = (("zahl_messung", ("ZAHL WEICHT VON DER MESSUNG AB",)),
        ("wortgrenze", ("Woerter/Bloecke, erlaubt",)),
        ("wortregel_beleg", ("Wortregel-Datei fehlt als Pflichtpunktbeleg",)),
        ("abschnitt_leer", ("ist noch nicht ausgefuellt",)),
        ("recherche_objekt", ("Recherche-Objekt",)),
        ("pflichtpunkte", ("Pflichtpunkt",)))
WAECHTER = (("tor2_teilbelege", ("Annahme unwirksam: zusammengesetzte Pflichtpunkte",)),
            ("tor2_pflichtzeile", ("Pruefer muss jeden Pflichtpunkt ausdruecklich", "TOR-2-FORMAT KORREKTURRUNDE")),
            ("ergebnisstand", ("Ergebnisstand stimmt nicht", "seit der technischen Pruefung veraendert")),
            ("sicherung", ("Sicherung konnte nicht", "keine Dateiaenderung", "Datei hat sich waehrend der Sicherung")),
            ("belegpfad", ("Beleg liegt ausserhalb", "Belegpfad darf keinen Verweis", "Schluesseldatei ist kein")),
            ("logo_beleg", ("Logo-Beleg", "Wort-Bild-Marke")),
            ("suchpfad", ("Suche enthaelt einen Verweis nach ausserhalb", "Suchmuster darf die Holding nicht verlassen",
                          "Suche enthaelt Schluesseldateien", "Pfad liegt ausserhalb der Holding")),
            ("pfad_verschachtelt", ("Verschachtelter JACK-Pfad",)),
            ("befehl_gesperrt", ("Erlaubt ist ausschliesslich:",)),
            ("schreibort", ("Betriebscode und eigene Protokolle", "Betriebsordnung und feste Kontrollrollen",
                            "Der Arbeiter darf seine eigenen Grenzen")),
            ("pflichtpunkte", ("Pflichtpunkt",)))


def _jetzt():
    return dt.datetime.now().astimezone()


def _zeit(wert, bezug=None):
    try:
        z = dt.datetime.fromisoformat(str(wert))
    except (TypeError, ValueError):
        return None
    if z.tzinfo is None:
        z = z.replace(tzinfo=(bezug or _jetzt()).tzinfo)
    return z


def _sha(daten):
    return hashlib.sha256(daten if isinstance(daten, bytes) else str(daten).encode("utf-8")).hexdigest()


def _datei_sha(pfad):
    try:
        return _sha(Path(pfad).read_bytes())
    except OSError:
        return None


def _jsonl(pfad):
    """(Zeilennummer, Rohbytes, Objekt) je gueltiger Zeile."""
    pfad = Path(pfad)
    if not pfad.is_file() or pfad.is_symlink():
        return
    with pfad.open("rb") as f:
        for nr, roh in enumerate(f, 1):
            try:
                obj = json.loads(roh)
            except ValueError:
                continue
            if isinstance(obj, dict):
                yield nr, roh, obj


def _anhaengen(pfad, zeilen):
    if not zeilen:
        return
    if pfad.is_symlink():
        raise ValueError("Protokoll darf kein Symlink sein")
    with pfad.open("a", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        for z in zeilen:
            f.write(json.dumps(z, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def _rel(root, pfad):
    try:
        return Path(pfad).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return str(pfad)


# ------------------------------------------------------------------ Regelliste
def hinweis_gueltig(text):
    """Ein Lernhinweis: eine Zeile, 1-160 Zeichen, nur feste Zeichenmenge (kein Link, kein Markdown, keine Befehle)."""
    return (isinstance(text, str) and 0 < len(text) <= HINWEIS_MAX and HINWEIS_ZEICHEN.fullmatch(text) is not None
            and "http" not in text.lower())


def freigabe_teil(regel):
    """Der vom PM freigegebene Teil einer Regel (alles ausser status/wirkung)."""
    return {k: regel.get(k) for k in ("kennung", "fehlerarten", "geltung", "mindest_haeufigkeit", "hinweis",
                                      "gegenprobe", "freigabe", "gewicht", "kategorie", "beleg_sha256")}


def freigabe_sha(regel):
    return _sha(json.dumps(freigabe_teil(regel), ensure_ascii=False, sort_keys=True))


def regel_pruefen(regel):
    """Liste der Gruende, warum eine Regel NICHT speisen darf (leer = gueltig)."""
    g = []
    if not isinstance(regel, dict):
        return ["keine Regel"]
    stil = regel.get("kategorie") == STIL
    if not REGEL_KENNUNG.fullmatch(str(regel.get("kennung", ""))) or str(regel.get("kennung", "")).startswith("S") != stil:
        g.append("Kennung ungueltig")
    if regel.get("kategorie") not in (None, STIL):
        g.append("Kategorie unbekannt")
    arten = regel.get("fehlerarten")
    if stil:
        if arten != [STIL] or not re.fullmatch(r"[0-9a-f]{64}", str(regel.get("beleg_sha256") or "")):
            g.append("Stilregel ohne Beleg-Hash der Mail")
    elif not isinstance(arten, list) or not arten or any(a not in FEHLERARTEN for a in arten):
        g.append("Fehlerart nicht in der festen Liste")
    if regel.get("gewicht") is not None and regel.get("gewicht") not in GEWICHTE:
        g.append("Gewicht muss 1, 2 oder 3 sein")
    geltung = regel.get("geltung")
    if (not isinstance(geltung, dict) or not all(isinstance(geltung.get(k), list) and geltung.get(k)
                                                  and all(isinstance(x, str) for x in geltung[k])
                                                  for k in ("marken", "ablaeufe"))):
        g.append("Geltung ungueltig")
    if type(regel.get("mindest_haeufigkeit")) is not int or regel["mindest_haeufigkeit"] < (1 if stil else 2):
        g.append("mindest_haeufigkeit muss >= 2 sein")
    if not hinweis_gueltig(regel.get("hinweis")):
        g.append("Hinweis ungueltig (Laenge/Zeichen)")
    if not (FREIGABE_PATRON if stil else FREIGABE).fullmatch(str(regel.get("freigabe", ""))):
        g.append("ohne PM-Freigabe" if not stil else "ohne Patron-Freigabe")
    if regel.get("freigabe_sha256") != freigabe_sha(regel):
        g.append("freigegebener Teil veraendert (freigabe_sha256 passt nicht)")
    if regel.get("status") not in ("aktiv", "ruht"):
        g.append("Status ungueltig")
    return g


def regeln_laden(root):
    """{'regeln': [...], 'verworfen': [(kennung, gruende)]}. Fehlende Datei = keine Regeln."""
    pfad = betrieb.area(root) / REGELN
    try:
        daten = json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"regeln": [], "verworfen": [], "datei": None}
    regeln, verworfen, gesehen = [], [], set()
    for r in (daten.get("regeln") or []) if isinstance(daten, dict) else []:
        gruende = regel_pruefen(r)
        if isinstance(r, dict) and r.get("kennung") in gesehen:
            gruende.append("Kennung doppelt")
        if gruende:
            verworfen.append((str(r.get("kennung") if isinstance(r, dict) else "?"), gruende))
            continue
        gesehen.add(r["kennung"])
        regeln.append(r)
    return {"regeln": regeln, "verworfen": verworfen, "datei": pfad, "roh": daten}


@contextlib.contextmanager
def _sperre(root):
    """Eine Schreibsperre fuer lernregeln.json (Planer, Montagsroutine und Mail-Stilregel schreiben nie gleichzeitig)."""
    with (betrieb.area(root) / "lernregeln.sperre").open("a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def _regeln_schreiben(root, daten, grund):
    """Nur fuer status/wirkung. Alter Stand wird vorher nach betrieb/lernregeln_verlauf/ kopiert."""
    pfad = betrieb.area(root) / REGELN
    verlauf = betrieb.area(root) / VERLAUF
    verlauf.mkdir(exist_ok=True)
    if pfad.is_file():
        (verlauf / ("%s_%s.json" % (_jetzt().strftime("%Y%m%d_%H%M%S_%f"), grund))).write_bytes(pfad.read_bytes())
    tmp = pfad.with_name(pfad.name + ".neu")
    tmp.write_text(json.dumps(daten, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, pfad)


def _gilt(regel, marke, ablauf):
    g = regel["geltung"]
    return ("*" in g["marken"] or marke in g["marken"]) and ("*" in g["ablaeufe"] or ablauf in g["ablaeufe"])


# ------------------------------------------------------------------ Fehlerkatalog
def _klassifizieren(grund, tabelle):
    for art, tokens in tabelle:
        if any(t in grund for t in tokens):
            return art
    return None


class _Auftraege:
    """Marke/Ablauf je Auftragsdatei: zuerst geschuetzter Vertrag, sonst Auftragskopf (bindung 'kopf')."""

    def __init__(self, root):
        self.root, self.cache = Path(root), {}

    def __call__(self, name):
        if name in self.cache:
            return self.cache[name]
        info = None
        try:
            import jack_auftrag
            v = jack_auftrag.lesen(self.root, name)
            if v:
                info = {"marke": v[0]["marke"], "ablauf": v[0]["ablauf"], "bindung": "vertrag"}
        except (OSError, ValueError, KeyError):
            info = None
        if info is None:
            try:
                import jack_auftrag
                jack_auftrag._dateiname(name)
                for o in ("erledigt", "problem", "laeuft", "offen", "zurueckgestellt", "freigabe"):
                    p = self.root / "auftraege" / o / name
                    if p.is_file() and not p.is_symlink():
                        k = jack_auftrag.kopf(p.read_text(encoding="utf-8", errors="replace"))
                        if k.get("marke"):
                            info = {"marke": k["marke"], "ablauf": k.get("ablauf") or "arbeit", "bindung": "kopf"}
                        break
            except (OSError, ValueError):
                info = None
        self.cache[name] = info
        return info


def _zettel_zu(root, name):
    try:
        import jack_abnahmezettel
        p = jack_abnahmezettel.zettelpfad(root, name)
        return _rel(root, p) if p.is_file() else None
    except Exception:
        return None


def _zeile(root, info, name, lauf, art, quelle, beleg, beleg_sha, zeit, zettel=None):
    kennung = _sha("|".join((quelle, str(lauf), art, name)))[:32]
    return {"schema": SCHEMA, "kennung": kennung, "zeit": zeit, "fehlerart": art, "marke": info["marke"],
            "ablauf": info["ablauf"], "bindung": info["bindung"], "auftrag": name, "lauf_id": lauf,
            "quelle": quelle, "beleg": beleg, "beleg_sha256": beleg_sha, "zettel": zettel}


def katalog_quellen(root):
    """Alle belegten Fehler aus den Primaerquellen (ohne zu schreiben). Je (Quelle, Lauf, Fehlerart, Auftrag) eine Zeile."""
    root = Path(root).resolve()
    auftraege = _Auftraege(root)
    raus, tor2_lauf = {}, {}

    def neu(z):
        raus.setdefault(z["kennung"], z)

    # 1 Waechter (Werkzeugprotokoll): Tor 1 (Korrekturen), Tor-2-Formfehler, Pfad-/Befehlssperren
    for nr, roh, rec in _jsonl(root / "arbeiter_zugriffe.jsonl") or ():
        lauf = str(rec.get("lauf_id") or "")
        if not re.fullmatch(r"[0-9a-f]{32}", lauf):
            continue
        if (rec.get("entscheidung") == "allow" and rec.get("tool") == "Write"
                and "/abnahme/tor2/" in str(rec.get("pfad") or "")):
            tor2_lauf[Path(rec["pfad"]).name] = lauf
            continue
        if rec.get("entscheidung") != "deny":
            continue
        name = str(rec.get("auftrag") or "")
        info = auftraege(name) if name else None
        if not info:
            continue
        grund = str(rec.get("grund") or "")
        if grund.startswith("Lokale Vorpruefung gesperrt:"):
            teile, tabelle, quelle = re.split(r";\s+", grund[len("Lokale Vorpruefung gesperrt:"):]), TOR1, "tor1"
        else:
            teile, tabelle, quelle = [grund], WAECHTER, "waechter"
        for teil in teile:
            art = _klassifizieren(teil, tabelle)
            if art:
                neu(_zeile(root, info, name, lauf, art, quelle, "arbeiter_zugriffe.jsonl:%d" % nr, _sha(roh),
                           rec.get("zeit"), _zettel_zu(root, name) if quelle == "tor1" else None))
    # 2 Lernsignale der Abschlusspruefung (bestehende Schleife, merken())
    for nr, roh, rec in _jsonl(betrieb.area(root) / "lernsignale.jsonl") or ():
        lauf, name, art = str(rec.get("lauf_id") or ""), str(rec.get("auftrag") or ""), rec.get("fehlerart")
        info = auftraege(name) if name else None
        if info and re.fullmatch(r"[0-9a-f]{32}", lauf) and art in FEHLERARTEN:
            neu(_zeile(root, info, name, lauf, art, "lernsignal", "betrieb/lernsignale.jsonl:%d" % nr, _sha(roh),
                       rec.get("zeit")))
    # 3 Tor-2-Zurueckweisungen (Pruefer-Zettel; nur das Urteil wird gelesen, nie der Text)
    ordner = root / "abnahme" / "tor2"
    for z in sorted(ordner.glob("*.md")) if ordner.is_dir() else ():
        if z.is_symlink() or "__" not in z.name or z.name.endswith("__rohtext.txt"):
            continue
        try:
            kopf = z.read_text(encoding="utf-8", errors="replace")[:4000]
        except OSError:
            continue
        if not re.search(r"^urteil:[ \t]*ZURUECKWEISUNG[ \t]*$", kopf, re.M):
            continue
        name = z.name.split("__", 1)[0] + ".md"
        info = auftraege(name)
        if not info:
            continue
        sha = _datei_sha(z)
        lauf = tor2_lauf.get(z.name) or ("zettel-" + sha[:25])
        zeit = dt.datetime.fromtimestamp(z.stat().st_mtime).astimezone().isoformat()
        m = re.search(r"^zeit:[ \t]*(\S+)", kopf, re.M)
        if m and _zeit(m[1]):
            zeit = m[1]
        neu(_zeile(root, info, name, lauf, "tor2_zurueckweisung", "tor2", _rel(root, z), sha, zeit,
                   _zettel_zu(root, name)))
    # 4 Planer: Lauf endete ohne Abschluss
    for nr, roh, rec in _jsonl(betrieb.area(root) / "planer.jsonl") or ():
        if rec.get("art") != "abbruch_gesichert":
            continue
        name = str(rec.get("auftrag") or "")
        info = auftraege(name) if name else None
        if info:
            lauf = str(rec.get("lauf_id") or "") or ("planer-" + _sha(roh)[:26])
            neu(_zeile(root, info, name, lauf, "abbruch_ohne_abschluss", "planer", "betrieb/planer.jsonl:%d" % nr,
                       _sha(roh), rec.get("zeit"), _zettel_zu(root, name)))
    # 5 Gegenproben (nur CLI-Laeufe schreiben gegenproben_laeufe.jsonl; nicht bestanden = belegter Kern-Fehler)
    for nr, roh, rec in _jsonl(betrieb.area(root) / GEGENPROBEN_LAEUFE) or ():
        k = str(rec.get("kennung") or "")
        if rec.get("bestanden") is False and ("gegenprobe_" + k) in FEHLERARTEN:
            info = {"marke": "JACK", "ablauf": "betrieb", "bindung": "gegenprobe"}
            neu(_zeile(root, info, "gegenprobe_" + k + ".md", "gp-" + _sha(roh)[:29], "gegenprobe_" + k, "gegenprobe",
                       "betrieb/%s:%d" % (GEGENPROBEN_LAEUFE, nr), _sha(roh), rec.get("zeit")))
    return sorted(raus.values(), key=lambda z: str(z.get("zeit")))


def katalog_lesen(root):
    return [rec for _nr, _roh, rec in _jsonl(betrieb.area(root) / KATALOG) or () if rec.get("schema") == SCHEMA
            and rec.get("fehlerart") in FEHLERARTEN]


def katalog_aktualisieren(root):
    """Neue belegte Fehler an betrieb/fehlerkatalog.jsonl anhaengen (nur anhaengen, nie aendern). -> Anzahl neu."""
    pfad = betrieb.area(root) / KATALOG
    vorhanden = {z.get("kennung") for z in katalog_lesen(root)}
    jetzt = _jetzt().isoformat()
    neu = [dict(z, erfasst=jetzt) for z in katalog_quellen(root) if z["kennung"] not in vorhanden]
    _anhaengen(pfad, neu)
    return len(neu)


# ------------------------------------------------------------------ Lernhinweise
def hinweise(root, marke, ablauf, an=None, katalog=None, regeln=None):
    """Hoechstens 3 Lernhinweise fuer (Marke, Ablauf). -> {'hinweise': [...], 'gekappt': [...], 'verfallen': [...]}"""
    an = an or _jetzt()
    katalog = katalog_lesen(root) if katalog is None else katalog
    regeln = regeln_laden(root)["regeln"] if regeln is None else regeln
    passend = [z for z in katalog if z.get("marke") == marke and z.get("ablauf") == ablauf]
    kandidaten, verfallen = [], []
    for r in regeln:
        if r.get("status") != "aktiv" or r.get("kategorie") == STIL or not _gilt(r, marke, ablauf):
            continue
        zeilen = [z for z in passend if z["fehlerart"] in r["fehlerarten"] and _zeit(z.get("zeit"), an)
                  and _zeit(z["zeit"], an) <= an]
        laeufe = {}
        for z in zeilen:
            laeufe.setdefault(z["lauf_id"], []).append(z)       # eine Regel zaehlt je Lauf einmal
        if len(laeufe) < r["mindest_haeufigkeit"]:
            continue
        letzter = max(_zeit(z["zeit"], an) for z in zeilen)
        if (an - letzter).total_seconds() > VERFALL_TAGE * 86400:
            verfallen.append(r["kennung"])
            continue
        belege = sorted(zeilen, key=lambda z: str(z["zeit"]), reverse=True)
        gewicht = r.get("gewicht") or 1
        kandidaten.append({"regel": r["kennung"], "hinweis": r["hinweis"], "n": len(laeufe), "gewicht": gewicht,
                           "rang": len(laeufe) * gewicht, "letzter": letzter.date().isoformat(),
                           "belege": [z["kennung"] for z in belege[:3]], "_letzter": letzter})
    # F-21: Haeufigkeit x Folgekosten; bei Gleichstand zuerst der teurere Fehler, dann der haeufigere, dann der juengere
    kandidaten.sort(key=lambda k: (-k["rang"], -k["gewicht"], -k["n"], -k["_letzter"].timestamp(), k["regel"]))
    for k in kandidaten:
        del k["_letzter"]
    return {"hinweise": kandidaten[:MAX_HINWEISE], "gekappt": [k["regel"] for k in kandidaten[MAX_HINWEISE:]],
            "verfallen": verfallen}


def fuer_vertrag(root, marke, ablauf, an=None):
    """Feld 'lernhinweise' fuer einen neuen Auftragsvertrag (L1..L3, auch leer). None = keine Regelliste.
    Der Katalog wird vorher nachgefuehrt."""
    if regeln_laden(root)["datei"] is None:
        return None                     # keine Regelliste: kein Feld im Vertrag (Altverhalten)
    try:
        katalog_aktualisieren(root)
    except (OSError, ValueError):
        pass
    liste = hinweise(root, marke, ablauf, an)["hinweise"]
    return [{"kennung": "L%d" % i, "regel": h["regel"], "hinweis": h["hinweis"], "n": h["n"],
             "letzter": h["letzter"], "belege": h["belege"]} for i, h in enumerate(liste, 1)]


def abschnitt_text(lernhinweise):
    """Abschnitt '## Lernhinweise' im Auftrag (eine Quelle: jack_auftrag.lernhinweise_abschnitt)."""
    import jack_auftrag
    return jack_auftrag.lernhinweise_abschnitt(lernhinweise)


# ------------------------------------------------------------------ Stilregeln des Patrons (F-21)
def _stiltext(text):
    """Nur die freigegebene Zeichenmenge; alles andere wird Leerzeichen."""
    sauber = "".join(z if HINWEIS_ZEICHEN.fullmatch(z) else " " for z in str(text or ""))
    return " ".join(sauber.split())


def stilregel_aus_aenderung(root, marke, alt, neu, mail_kennung, an=None):
    """Aus einer Aenderung des Patrons an einem Mail-Entwurf wird eine Regel der Kategorie stil_patron in
    lernregeln.json. Uebernommen wird NUR, was der Patron selbst geschrieben hat (neue Zeilen), nie der
    urspruengliche Entwurf. Ohne Mail-Kennung (Beleg) entsteht keine Regel. -> Regel oder None."""
    import difflib
    if not mail_kennung or not str(marke or "").strip():
        return None
    neue = [z[1:] for z in difflib.unified_diff((alt or "").splitlines(), (neu or "").splitlines(), lineterm="", n=0)
            if z.startswith("+") and not z.startswith("+++")]
    text = _stiltext(" / ".join(x.strip() for x in neue if x.strip()))
    if not text:
        return None
    marke = re.sub(r"[^A-Za-z0-9_-]", "", str(marke))
    kopf = "Mail-Stil %s: so schreibt der Patron: " % marke.replace("_", " ")
    platz = HINWEIS_MAX - len(kopf) - 2
    hinweis = kopf + "„" + (text if len(text) <= platz else text[:platz - 1].rstrip() + ".") + "“"
    if not hinweis_gueltig(hinweis):
        return None
    an = an or _jetzt()
    with _sperre(root):
        pfad = betrieb.area(root) / REGELN
        try:
            daten = json.loads(pfad.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            daten = {"schema": 1, "regeln": []}
        regeln = daten.setdefault("regeln", [])
        if any(r.get("kategorie") == STIL and r.get("hinweis") == hinweis for r in regeln if isinstance(r, dict)):
            return None
        nr = 1 + max([int(r["kennung"][1:]) for r in regeln if isinstance(r, dict)
                      and re.fullmatch(r"S\d{3}", str(r.get("kennung", "")))] or [0])
        regel = {"kennung": "S%03d" % nr, "kategorie": STIL, "fehlerarten": [STIL],
                 "geltung": {"marken": [marke], "ablaeufe": ["mail"]}, "mindest_haeufigkeit": 1, "hinweis": hinweis,
                 "gegenprobe": None, "freigabe": "Patron %s (Mail)" % an.strftime("%d.%m."), "gewicht": None,
                 "beleg_sha256": _sha(str(mail_kennung))}
        regel["freigabe_sha256"] = freigabe_sha(regel)
        regel.update({"herkunft": "Patron-Aenderung an Mail-Entwurf (jack_postfaecher.stilregel_lernen)",
                      "status": "aktiv", "status_grund": "", "status_seit": None, "wirkung": {}})
        if regel_pruefen(regel):
            return None
        regeln.append(regel)
        _regeln_schreiben(root, daten, "stilregel")
    return regel


def stilregeln(root, marke):
    """Aktive Stilregeln des Patrons fuer eine Marke (fuer Mail-Entwuerfe)."""
    return [r["hinweis"] for r in regeln_laden(root)["regeln"]
            if r.get("kategorie") == STIL and r.get("status") == "aktiv" and _gilt(r, marke, "mail")]


# ------------------------------------------------------------------ Wirkungsmessung
def _vertraege(root):
    import jack_auftrag
    ordner = Path(root) / "betrieb" / "auftragsvertraege"
    raus = []
    for p in sorted(ordner.glob("*.json")) if ordner.is_dir() else ():
        try:
            name = json.loads(p.read_text(encoding="utf-8")).get("datei")
            v = jack_auftrag.lesen(root, name) if isinstance(name, str) else None
        except (OSError, ValueError, TypeError):
            continue
        if v:
            raus.append(v[0])
    return raus


def _korrekturen_tor1(root):
    je = {}
    for _nr, _roh, rec in _jsonl(Path(root) / "arbeiter_zugriffe.jsonl") or ():
        if (rec.get("entscheidung") == "deny" and rec.get("tool") == "Agent"
                and str(rec.get("grund") or "").startswith("Lokale Vorpruefung gesperrt:")):
            je[rec.get("auftrag")] = je.get(rec.get("auftrag"), 0) + 1
    return je


def kennzahlen_auftrag(root, vertrag, korrekturen=None):
    """Kennzahlen eines ABGESCHLOSSENEN Auftrags (erledigt/ oder problem/), sonst None."""
    import jack_abnahmezettel as Z
    import jack_auftrag
    name = vertrag["datei"]
    ordner, _pfad = Z.finden(root, name)
    if ordner not in ("erledigt", "problem"):
        return None
    korrekturen = _korrekturen_tor1(root) if korrekturen is None else korrekturen
    zurueck = 0
    for z in Z._tor2_zettel(root, name):
        try:
            if re.search(r"^urteil:[ \t]*ZURUECKWEISUNG[ \t]*$", z.read_text(encoding="utf-8", errors="replace"), re.M):
                zurueck += 1
        except OSError:
            continue
    kosten = 0.0
    for r in Z._kosten(root, name):
        wert = r.get("usd_gemeldet") if r.get("usd_gemeldet") is not None else r.get("usd_geschaetzt")
        try:
            kosten += float(wert or 0)
        except (TypeError, ValueError):
            pass
    q = jack_auftrag.quittung(root, vertrag)
    minuten = None
    if q:
        a, b = _zeit(vertrag.get("zeit")), _zeit(q.get("zeit"))
        if a and b:
            minuten = round((b - a).total_seconds() / 60.0, 1)
    return {"auftrag": name, "marke": vertrag["marke"], "ablauf": vertrag["ablauf"], "zeit": vertrag.get("zeit"),
            "regeln": [h.get("regel") for h in vertrag.get("lernhinweise") or []],
            "korrekturrunden": korrekturen.get(name, 0), "tor2_zurueckweisungen": zurueck,
            "kosten_usd": round(kosten, 4), "angenommen": bool(q), "zeit_bis_annahme_min": minuten}


def _seite(auftraege):
    n = len(auftraege)
    if not n:
        return {"n": 0}
    angenommen = [a for a in auftraege if a["angenommen"]]
    zeiten = [a["zeit_bis_annahme_min"] for a in angenommen if a["zeit_bis_annahme_min"] is not None]
    return {"n": n, "angenommen": len(angenommen),
            "korrekturrunden": round(sum(a["korrekturrunden"] for a in auftraege) / n, 3),
            "tor2_zurueckweisungen": round(sum(a["tor2_zurueckweisungen"] for a in auftraege) / n, 3),
            "kosten_je_annahme_usd": round(sum(a["kosten_usd"] for a in auftraege) / len(angenommen), 4) if angenommen else None,
            "zeit_bis_annahme_min": round(sum(zeiten) / len(zeiten), 1) if zeiten else None,
            "auftraege": [a["auftrag"] for a in auftraege]}


def vergleich(regel, alle):
    """Vorher/nachher fuer eine Regel. nachher = abgeschlossene Auftraege mit diesem Lernhinweis im Vertrag;
    vorher = abgeschlossene Auftraege derselben Marke/desselben Ablaufs ohne ihn, erteilt in den 30 Tagen vor
    dem ersten 'nachher'-Auftrag (ohne 'nachher': die letzten 30 Tage)."""
    nachher = [a for a in alle if regel["kennung"] in a["regeln"]]
    paare = {(a["marke"], a["ablauf"]) for a in nachher}
    if nachher:
        grenze = min(_zeit(a["zeit"]) for a in nachher if _zeit(a["zeit"]))
    else:
        grenze = _jetzt()
    vorher = [a for a in alle if regel["kennung"] not in a["regeln"] and (a["marke"], a["ablauf"]) in paare
              and _zeit(a["zeit"]) and 0 <= (grenze - _zeit(a["zeit"])).total_seconds() <= VERFALL_TAGE * 86400]
    v, n = _seite(vorher), _seite(nachher)
    auswertbar = v["n"] >= MIN_N and n["n"] >= MIN_N
    schlechter, besser = [], []
    if auswertbar:
        for k, _titel in KENNZAHLEN:
            a, b = v.get(k), n.get(k)
            if a is None or b is None:
                continue
            if b > a * (1 + TOLERANZ) and b - a > MINDESTDIFFERENZ[k]:
                schlechter.append(k)
            elif b < a * (1 - TOLERANZ) and a - b > MINDESTDIFFERENZ[k]:
                besser.append(k)
    return {"vorher": v, "nachher": n, "auswertbar": auswertbar, "verschlechtert": schlechter, "verbessert": besser}


def wirkung_pruefen(root, an=None, alle=None):
    """Je Regel Kennzahlen vorher/nachher; verschlechtert (n >= 3 je Seite) -> Status 'ruht' + Meldung.
    Schreibt lernregeln.json nur, wenn sich status/wirkung aendert. -> Liste der Aenderungen."""
    an = an or _jetzt()
    if alle is None and not regeln_laden(root)["regeln"]:
        return []
    if alle is None:
        korrekturen = _korrekturen_tor1(root)
        alle = [k for k in (kennzahlen_auftrag(root, v, korrekturen) for v in _vertraege(root)) if k]
    with _sperre(root):
        return _wirkung_schreiben(root, an, alle)


def _wirkung_schreiben(root, an, alle):
    geladen = regeln_laden(root)
    if not geladen["regeln"]:
        return []
    daten = geladen["roh"]
    gueltig = {r["kennung"] for r in geladen["regeln"] if r.get("kategorie") != STIL}
    aenderungen, meldungen = [], []
    for r in daten.get("regeln") or []:
        if not isinstance(r, dict) or r.get("kennung") not in gueltig:
            continue
        erg = vergleich(r, alle)
        wirkung = {"stand": an.isoformat(), "n_vorher": erg["vorher"]["n"], "n_nachher": erg["nachher"]["n"],
                   "auswertbar": erg["auswertbar"], "verschlechtert": erg["verschlechtert"],
                   "verbessert": erg["verbessert"],
                   "kennzahlen": {k: {"vorher": erg["vorher"].get(k), "nachher": erg["nachher"].get(k)}
                                  for k, _t in KENNZAHLEN}}
        alt = dict(r.get("wirkung") or {}, stand=None)
        if dict(wirkung, stand=None) != alt:
            r["wirkung"] = wirkung
            aenderungen.append({"regel": r["kennung"], "art": "wirkung"})
        if r.get("status") == "aktiv" and erg["auswertbar"] and erg["verschlechtert"]:
            r["status"], r["status_seit"] = "ruht", an.isoformat()
            r["status_grund"] = ("automatisch: verschlechtert %s (n vorher %d, nachher %d)"
                                 % (", ".join(erg["verschlechtert"]), erg["vorher"]["n"], erg["nachher"]["n"]))
            aenderungen.append({"regel": r["kennung"], "art": "ruht"})
            meldungen.append({"zeit": an.isoformat(), "art": "ruht", "regel": r["kennung"],
                              "verschlechtert": erg["verschlechtert"], "n_vorher": erg["vorher"]["n"],
                              "n_nachher": erg["nachher"]["n"], "kennzahlen": wirkung["kennzahlen"],
                              "gemeldet_im_montagsbericht": False})
    if aenderungen:
        _regeln_schreiben(root, daten, "ruht" if meldungen else "wirkung")
        _anhaengen(betrieb.area(root) / WIRKUNG, meldungen)
    return aenderungen


# ------------------------------------------------------------------ Montagsbericht "Lernwirkung"
def _zahl(k, wert):
    if wert is None:
        return "–"
    if k == "kosten_je_annahme_usd":
        import jack_abnahmezettel
        return jack_abnahmezettel.betrag_text(wert)
    return ("%.2f" % wert).replace(".", ",")


def bericht_abschnitt(root, an=None):
    """Abschnitt '## Lernwirkung' fuer die Montag-09:00-Karte (keine neue Automation)."""
    an = an or _jetzt()
    zeilen = ["## Lernwirkung (Paket 6)", ""]
    try:
        neu = katalog_aktualisieren(root)
    except (OSError, ValueError) as fehler:
        neu = "nicht erfasst (%s)" % type(fehler).__name__
    try:
        wirkung_pruefen(root, an)
    except Exception as fehler:
        zeilen.append("Wirkungsmessung nicht gelaufen: %s" % type(fehler).__name__)
    geladen = regeln_laden(root)
    katalog = katalog_lesen(root)
    woche = [z for z in katalog if _zeit(z.get("zeit"), an) and 0 <= (an - _zeit(z["zeit"], an)).days < 7]
    zeilen.append("Fehlerkatalog `betrieb/fehlerkatalog.jsonl`: %d belegte Fehler gesamt, %d in den letzten 7 Tagen, "
                  "%s neu erfasst. Regelliste `betrieb/lernregeln.json`: %d aktiv, %d ruhend, %d verworfen." % (
                      len(katalog), len(woche), neu, sum(r["status"] == "aktiv" for r in geladen["regeln"]),
                      sum(r["status"] == "ruht" for r in geladen["regeln"]), len(geladen["verworfen"])))
    zeilen += ["", "Wirkung erst ab %d vergleichbaren Aufträgen je Seite (PM-Entscheidung 3); darunter steht "
               "„zu wenig Daten“ statt einer Zahl." % MIN_N, "",
               "| Regel | Status | vorher n | nachher n | %s | Empfehlung |" % " | ".join(t for _k, t in KENNZAHLEN),
               "|---|---|---|---|" + "---|" * len(KENNZAHLEN) + "---|"]
    for r in geladen["regeln"]:
        if r.get("kategorie") == STIL:
            continue                # Stilregeln (Mail) werden nicht ueber Fehlerkennzahlen gemessen
        w = r.get("wirkung") or {}
        kz = w.get("kennzahlen") or {}
        if not w.get("n_nachher"):
            if r["status"] == "aktiv":
                continue            # nie eingespeist: keine Zeile, Zusammenfassung unten
        if w.get("auswertbar"):
            werte = " | ".join("%s → %s" % (_zahl(k, (kz.get(k) or {}).get("vorher")), _zahl(k, (kz.get(k) or {}).get("nachher")))
                               for k, _t in KENNZAHLEN)
            empfehlung = ("ruht – verschlechtert: " + ", ".join(w.get("verschlechtert") or []) if r["status"] == "ruht"
                          else "behalten" + (" (besser: %s)" % ", ".join(w["verbessert"]) if w.get("verbessert") else ""))
        else:
            werte = " | ".join("zu wenig Daten" for _k in KENNZAHLEN)
            empfehlung = "weiter beobachten" if r["status"] == "aktiv" else "ruht – " + str(r.get("status_grund") or "")
        zeilen.append("| %s | %s | %s | %s | %s | %s |" % (r["kennung"], r["status"], w.get("n_vorher", 0),
                                                          w.get("n_nachher", 0), werte, empfehlung))
    nie = [r["kennung"] for r in geladen["regeln"] if r["status"] == "aktiv" and r.get("kategorie") != STIL
           and not (r.get("wirkung") or {}).get("n_nachher")]
    zeilen += ["", "Noch in keinem abgeschlossenen Auftrag eingespeist: %s." % (", ".join(nie) or "keine")]
    meldungen, rest = [], []
    pfad = betrieb.area(root) / WIRKUNG
    for _nr, _roh, rec in _jsonl(pfad) or ():
        (meldungen if rec.get("art") == "ruht" and not rec.get("gemeldet_im_montagsbericht") else rest).append(rec)
    if meldungen:
        zeilen += ["", "**Neu ruhend (automatisch, Kennzahl verschlechtert):**"]
        for m in meldungen:
            zeilen.append("- %s seit %s: %s (n %d → %d)" % (m["regel"], str(m["zeit"])[:16], ", ".join(m["verschlechtert"]),
                                                            m["n_vorher"], m["n_nachher"]))
        _anhaengen(pfad, [{"zeit": an.isoformat(), "art": "gemeldet", "regeln": [m["regel"] for m in meldungen]}])
    if geladen["verworfen"]:
        zeilen += ["", "**Verworfene Regeln (speisen nicht):** " + "; ".join(
            "%s: %s" % (k, ", ".join(g)) for k, g in geladen["verworfen"])]
    zeilen.append("")
    return "\n".join(zeilen)


# ------------------------------------------------------------------ Gelegenheiten (nur Vorschlaege, kein Start)
def _zustaendig(root, marke):
    if marke == "JACK":
        return "jack (JACK-Kern)"
    try:
        konf = json.loads((Path(root) / "betrieb" / "videoproduktion.json").read_text(encoding="utf-8"))
        ceo = ((konf.get("marken") or {}).get(marke) or {}).get("ceo")
        if ceo and (Path(root) / "agenten" / "00_Vorstand" / (ceo + ".md")).is_file():
            return ceo
    except (OSError, ValueError):
        pass
    return "jack (für %s ist keine Marken-CEO-Rolle hinterlegt)" % marke


def _radar_alarme(root):
    """Marktradar (Auftrag 29.1): nur Fundstellen von Zeilen, die mit 'ALARM' beginnen - nie deren Text."""
    vault = Path(root).resolve().parent.parent
    raus = []
    for datei in sorted(vault.glob("00_Marken/*/05_Marketing/radar/*_radar.md")):
        if datei.is_symlink() or not datei.is_file() or datei.stat().st_size > 500_000:
            continue
        try:
            zeilen = datei.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for nr, z in enumerate(zeilen, 1):
            if re.match(r"\s*(?:[-*]\s*)?\**ALARM\b", z, re.I):
                raus.append({"marke": datei.parts[-4], "datei": datei.relative_to(vault).as_posix(), "zeile": nr,
                             "sha256": _sha(z.encode("utf-8"))})
    return raus


def gelegenheiten_kandidaten(root, an=None):
    import jack_abnahmezettel as Z
    an = an or _jetzt()
    katalog = [z for z in katalog_lesen(root) if _zeit(z.get("zeit"), an)
               and 0 <= (an - _zeit(z["zeit"], an)).total_seconds() <= VERFALL_TAGE * 86400]
    gruppen = {}
    for z in katalog:
        gruppen.setdefault((z["marke"], z["fehlerart"]), {}).setdefault(z["lauf_id"], z)
    raus = []
    for (marke, art), laeufe in gruppen.items():
        if len(laeufe) < GELEGENHEIT_MIN_N:
            continue
        auftraege = sorted({z["auftrag"] for z in laeufe.values()})
        kosten = []
        for name in auftraege:
            summe = 0.0
            for r in Z._kosten(root, name):
                wert = r.get("usd_gemeldet") if r.get("usd_gemeldet") is not None else r.get("usd_geschaetzt")
                try:
                    summe += float(wert or 0)
                except (TypeError, ValueError):
                    pass
            if summe:
                kosten.append(summe)
        schnitt = sum(kosten) / len(kosten) if kosten else None
        raus.append({"art": "fehler", "marke": marke, "fehlerart": art, "n": len(laeufe), "auftraege": auftraege,
                     "belege": sorted(laeufe.values(), key=lambda z: str(z["zeit"]))[-3:],
                     "kosten_schnitt_usd": schnitt,
                     "nutzen_usd_monat": round(schnitt * len(laeufe), 4) if schnitt else None,
                     "schluessel": _sha("fehler|%s|%s" % (marke, art))[:32]})
    for a in _radar_alarme(root):
        raus.append({"art": "radar", "marke": a["marke"], "fehlerart": None, "n": 1, "auftraege": [],
                     "belege": [a], "kosten_schnitt_usd": None, "nutzen_usd_monat": None,
                     "schluessel": _sha("radar|%s|%s" % (a["datei"], a["sha256"]))[:32]})
    raus.sort(key=lambda g: (-(g["nutzen_usd_monat"] or 0), -g["n"], g["marke"], str(g["fehlerart"])))
    return raus


def gelegenheiten_schreiben(root, an=None):
    """Hoechstens 3 Vorschlagskarten je Woche nach auftraege/freigabe/; nichts startet ohne FREIGEBEN des Patrons.
    Dieselbe Gelegenheit (Marke+Fehlerart bzw. Radar-Fundstelle) hoechstens einmal je 30 Tage."""
    import jack_abnahmezettel as Z
    an = an or _jetzt()
    log = betrieb.area(root) / GELEGENHEITEN
    frueher = [rec for _nr, _roh, rec in _jsonl(log) or ()]
    sperre = {rec["schluessel"] for rec in frueher if _zeit(rec.get("zeit"), an)
              and (an - _zeit(rec["zeit"], an)).total_seconds() <= VERFALL_TAGE * 86400}
    kw = "%d-KW%02d" % an.isocalendar()[:2]
    diese_woche = sum(1 for rec in frueher if rec.get("kw") == kw)
    geschrieben = []
    for g in gelegenheiten_kandidaten(root, an):
        if diese_woche + len(geschrieben) >= GELEGENHEITEN_JE_WOCHE:
            break
        if g["schluessel"] in sperre:
            continue
        zustaendig = _zustaendig(root, g["marke"])
        if g["art"] == "fehler":
            titel = "Wiederkehrender Fehler %s bei %s" % (g["fehlerart"], g["marke"])
            was = ("Ursache der Fehlerart %s (%s) in Marke %s prüfen und einen Behebungsvorschlag mit Aufwand machen. "
                   "Nichts umsetzen, nur Vorschlag." % (g["fehlerart"], FEHLERARTEN[g["fehlerart"]], g["marke"]))
            nutzen = ("vermutet, Obergrenze: %d belegte Läufe in 30 Tagen × Ø %s Kosten je betroffenem Auftrag = %s "
                      "im Monat; die echte Ersparnis ist kleiner (nur der Anteil der Fehlversuche und Korrekturen)" % (
                          g["n"], Z.betrag_text(g["kosten_schnitt_usd"]), Z.betrag_text(g["nutzen_usd_monat"]))
                      if g["nutzen_usd_monat"] else
                      "vermutet: %d vermiedene Fehlläufe im Monat; Kosten je Lauf nicht im Kostenbuch beziffert (offen)" % g["n"])
            belege = ["`%s` (SHA-256 `%s`, Lauf `%s`)" % (b["beleg"], (b.get("beleg_sha256") or "")[:16], b["lauf_id"])
                      for b in g["belege"]]
        else:
            b = g["belege"][0]
            titel = "Marktradar-Alarm %s" % g["marke"]
            was = "Radar-Alarm an der Fundstelle sichten und über eine Reaktion entscheiden. Nichts veröffentlichen."
            nutzen = "offen: ohne Sichtung nicht schätzbar (der Alarmtext wird bewusst nicht übernommen)"
            belege = ["`%s:%d` (SHA-256 `%s`)" % (b["datei"], b["zeile"], b["sha256"][:16])]
        datei = Path(root) / "auftraege" / "freigabe" / ("%s_GELEGENHEIT_%s_%s.md" % (
            an.strftime("%Y-%m-%d"), re.sub(r"[^A-Za-z0-9_-]", "", g["marke"]), g["schluessel"][:8]))
        if datei.exists():
            continue
        text = "\n".join([
            "---", "marke:      %s" % g["marke"], "auftrag:    Gelegenheit_%s" % g["schluessel"][:8],
            "erteilt:    %s" % an.strftime("%Y-%m-%d %H:%M"), "von:        JACK-Lernen (Paket 6)",
            "status:     freigabe", "freigabe:   nein", "gefahr:     keine", "tiefe:      klein",
            "bereiche:   betrieb", "art:        gelegenheit", "zustaendig: %s" % zustaendig, "---", "",
            "## Auftrag", was, "", "## Gelegenheit", "- Titel: " + titel, "- Zuständigkeit: " + zustaendig,
            "- Nutzenabschätzung: " + nutzen, "- Quelle: " + ("Fehlerkatalog betrieb/fehlerkatalog.jsonl"
                                                           if g["art"] == "fehler" else "Marktradar (Auftrag 29.1)"),
            "- Belege:"] + ["  - " + b for b in belege] + [
            "", "## Prüfpunkte",
            "Nur ein Vorschlag. Diese Karte startet nichts von selbst; erst FREIGEBEN durch den Patron macht daraus "
            "einen Auftrag für die zuständige Rolle. Keine Außenwirkung, keine neuen Rechte.", ""])
        datei.write_text(text, encoding="utf-8")
        rec = {"zeit": an.isoformat(), "kw": kw, "schluessel": g["schluessel"], "art": g["art"], "marke": g["marke"],
               "fehlerart": g["fehlerart"], "n": g["n"], "zustaendig": zustaendig, "datei": _rel(root, datei)}
        _anhaengen(log, [rec])
        geschrieben.append(rec)
    return geschrieben


def gelegenheiten_abschnitt(root, an=None):
    try:
        neu = gelegenheiten_schreiben(root, an)
    except Exception as fehler:
        return "## Gelegenheiten (Paket 6)\n\nNicht erstellt: %s\n" % type(fehler).__name__
    zeilen = ["## Gelegenheiten (Paket 6)", "",
              "Höchstens %d Vorschlagskarten je Woche in `auftraege/freigabe/`, jede mit Zuständigkeit und "
              "Nutzenabschätzung. Keine startet von selbst." % GELEGENHEITEN_JE_WOCHE, ""]
    zeilen += ["- `%s` – %s, zuständig %s" % (g["datei"], g["fehlerart"] or "Radar-Alarm", g["zustaendig"]) for g in neu] \
        or ["- keine neue Gelegenheit diese Woche"]
    return "\n".join(zeilen) + "\n"


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["katalog"]:
        print(json.dumps({"neu": katalog_aktualisieren(HIER), "gesamt": len(katalog_lesen(HIER))}))
    elif args[:1] == ["hinweise"] and len(args) == 3:
        katalog_aktualisieren(HIER)
        print(json.dumps(hinweise(HIER, args[1], args[2]), ensure_ascii=False, indent=1))
    elif args[:1] == ["wirkung"]:
        print(json.dumps(wirkung_pruefen(HIER), ensure_ascii=False))
    elif args[:1] == ["bericht"]:
        print(bericht_abschnitt(HIER))
    elif args[:1] == ["gelegenheiten"]:
        print(json.dumps(gelegenheiten_kandidaten(HIER), ensure_ascii=False, indent=1, default=str)[:6000])
    else:
        raise SystemExit(__doc__)
