#!/usr/bin/env python3
"""Abnahmezettel je Ergebnis (Paket 4 "Qualitaet fuer jedes Ergebnis", F-11, 24.09.2026).

PM-Entscheidungen 24.09.2026 (Vorlage entscheidungen/2026-09-24_paket4_qualitaet_VORLAGE.md):
  1. Den Zettel schreibt NUR der Planer (Pfadwaechter arbeiter.sh sperrt abnahme/*_zettel.md fuer jeden Lauf).
     Der Tor-2-Zettel des Pruefers bleibt unveraendert und wird nur wortgetreu uebernommen und verlinkt.
     Das Pruefurteil ANNAHME heisst im Zettel-Status "geprueft".
  2. Kurzzettel (7 Felder) fuer jedes Ergebnis; Vollzettel (15 Felder) bei Tiefe mittel/gross, Code oder
     Aussenwirkung.
  3. Kosten eines abgebrochenen Laufs: Kostenrahmen als Obergrenze, gekennzeichnet "geschaetzt".

Die 15 Felder (verbindlich, PM): Ausgangszustand, vollstaendiger Auftrag, Pflichtpunkte, Aenderungen,
Sicherungen, reale Ausloesung, erwartetes Ergebnis, beobachtetes Ergebnis, Kosten, unabhaengige Pruefung,
Belegpfad, Zeitpunkt, Pruefsumme, Rueckweg, eindeutiger Status.
F-12 (PM-Entscheidung 4): dazu das Feld "Korrekturen (Tor 1)" - jede Sperre des Prueferstarts durch die lokale
Vorpruefung (z. B. Zahl gegen Messung, 84 -> 96) mit Grund, Korrektur und Wiederanlauf; der Vollzettel hat damit
16 Felder. F-12 (Entscheidung 3): eine gekappte Zeitgrenze aus dem Auftragskopf steht im Feld "Reale Ausloesung".

Statuswoerter (verbindlich): geprueft, umgesetzt, veroeffentlicht, persoenlich abgenommen, offen, blockiert,
angenommen, vermutet.
  - Der STATUS eines Ergebnisses (Feld 15) ist genau eines von: offen, blockiert, umgesetzt, geprueft,
    veroeffentlicht, persoenlich abgenommen. Gesetzt vom Planer nach Regel (status_bestimmen), nie aus
    Selbstauskunft eines Laufs.
  - "angenommen" und "vermutet" sind KENNZEICHEN an einzelnen Feldern (eine Annahme bzw. Vermutung im Inhalt,
    z. B. geschaetzte Kosten) - nie der Status eines Ergebnisses.
  - "persoenlich abgenommen" setzt nur der Patron: Datei auftraege/freigabe/ABGENOMMEN_<Nr>.md mit der Zeile
    "pruefsumme: <mind. 12 Zeichen der Pruefsumme dieses Zettels>". Kein Lauf kann sie schreiben (Waechter),
    der Planer legt sie nie an. Aendert sich das Ergebnis, passt die Pruefsumme nicht mehr - die Abnahme
    verfaellt.
  - "veroeffentlicht" verlangt einen angekommenen Veroeffentlichungsvorgang MIT Sichtkontrolle (Paket 5).
    Einen solchen Adapter gibt es heute nicht; der Status wird deshalb derzeit nie erreicht.

Automatische Felder (Kosten, Zeit, Pruefsumme SHA-256, Belegpfad) kommen aus Kostenbuch und Dateisystem;
die Prueferfelder aus dem Tor-2-Zettel. Automatisch heisst: Herkunft und Unveraendertheit sind belegt,
nicht die fachliche Richtigkeit - die belegt allein Tor 2.

Kein Modell, kein Netz. Nichts wird geloescht; eine geaenderte Fassung legt die alte unter
abnahme/zettel_verlauf/ ab, bevor sie ersetzt wird.
"""
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER))
import jack_auftrag  # noqa: E402
import jack_betrieb as betrieb  # noqa: E402

SCHEMA = 1
FELDER_VOLL = (
    ("ausgangszustand", "Ausgangszustand"),
    ("auftrag", "Vollständiger Auftrag"),
    ("pflichtpunkte", "Pflichtpunkte"),
    ("aenderungen", "Änderungen"),
    ("sicherungen", "Sicherungen"),
    ("ausloesung", "Reale Auslösung"),
    ("erwartet", "Erwartetes Ergebnis"),
    ("beobachtet", "Beobachtetes Ergebnis"),
    ("korrekturen", "Korrekturen (Tor 1)"),
    ("kosten", "Kosten"),
    ("pruefung", "Unabhängige Prüfung"),
    ("belegpfad", "Belegpfad"),
    ("zeitpunkt", "Zeitpunkt"),
    ("pruefsumme", "Prüfsumme"),
    ("rueckweg", "Rückweg"),
    ("status", "Eindeutiger Status"),
)
FELDER_KURZ = ("auftrag", "aenderungen", "kosten", "zeitpunkt", "pruefsumme", "belegpfad", "status")
STATUS = ("offen", "blockiert", "umgesetzt", "geprüft", "veröffentlicht", "persönlich abgenommen")
KENNZEICHEN = ("angenommen", "vermutet", "offen")
STATUSWOERTER = ("geprüft", "umgesetzt", "veröffentlicht", "persönlich abgenommen", "offen", "blockiert",
                 "angenommen", "vermutet")
GRUPPEN = ("offen", "laeuft", "freigabe", "erledigt", "problem", "zurueckgestellt")
CODE_ENDUNGEN = (".py", ".sh", ".js", ".mjs", ".ts", ".tsx", ".html", ".css", ".swift")
VERLAUF = "zettel_verlauf"


# ------------------------------------------------------------------ Hilfen
def betrag_text(usd):
    """Wie betragText() der Oberflaeche (Hausregel A9): unter 1 USD in Cent, sonst '1,38 USD'."""
    try:
        wert = Decimal(str(usd))
    except (InvalidOperation, ValueError, TypeError):
        return "unbekannt"
    if wert < Decimal("0.01"):
        return "0 Cent" if wert == 0 else "< 1 Cent"
    if wert < 1:
        return "%d Cent" % int((wert * 100).quantize(Decimal("1")))
    return ("%.2f USD" % wert).replace(".", ",")


def _exakt(usd):
    try:
        return (str(Decimal(str(usd)).quantize(Decimal("0.0001"))) + " USD").replace(".", ",")
    except (InvalidOperation, ValueError, TypeError):
        return "?"


def _vault(root):
    return Path(root).resolve().parent.parent


def _rel(root, pfad):
    try:
        return Path(pfad).resolve().relative_to(_vault(root)).as_posix()
    except (ValueError, OSError):
        return str(pfad)


def _sha(pfad):
    try:
        h = hashlib.sha256()
        with open(pfad, "rb") as f:
            for teil in iter(lambda: f.read(1 << 20), b""):
                h.update(teil)
        return h.hexdigest()
    except OSError:
        return None


def _jsonl(pfad, filter_text=None):
    raus = []
    try:
        with open(pfad, encoding="utf-8") as f:
            for zeile in f:
                if filter_text and filter_text not in zeile:
                    continue
                try:
                    wert = json.loads(zeile)
                except ValueError:
                    continue
                if isinstance(wert, dict):
                    raus.append(wert)
    except OSError:
        pass
    return raus


def _kurz(text, n):
    text = str(text or "").strip()
    return text if len(text) <= n else text[:n].rstrip() + " … (gekürzt)"


def finden(root, name):
    """(ordner, pfad) der Auftragsdatei oder (None, None)."""
    for gruppe in GRUPPEN:
        p = Path(root) / "auftraege" / gruppe / name
        if p.is_file() and not p.is_symlink():
            return gruppe, p
    return None, None


def nummer(root, name):
    try:
        z = json.loads((betrieb.area(root) / "laufende.json").read_text(encoding="utf-8"))
        return (z.get("nummern") or {}).get(name)
    except (OSError, ValueError):
        return None


def zettelpfad(root, name, nr=None):
    nr = nr if nr is not None else nummer(root, name)
    return Path(root) / "abnahme" / ("%s_zettel.md" % (nr if nr is not None else "ohneNr-" + Path(name).stem))


# ------------------------------------------------------------------ Quellen je Auftrag
def _zugriffe(root, name):
    return [r for r in _jsonl(Path(root) / "arbeiter_zugriffe.jsonl", name) if r.get("auftrag") == name]


def _kosten(root, name):
    """Je Lauf-id die letzte Zeile (Start < Ende < Nachbuchung) aus dem Kostenbuch dieses Auftrags."""
    import jack_kosten
    je = {}
    for r in jack_kosten.rows(root):
        if r.get("auftrag") != name or not r.get("id"):
            continue
        if r.get("ereignis") == "start":
            je.setdefault(r["id"], r)
        else:
            je[r["id"]] = r
    return sorted(je.values(), key=lambda r: str(r.get("zeit")))


def _tor2_zettel(root, name):
    return sorted((Path(root) / "abnahme" / "tor2").glob(Path(name).stem + "__pruefung*.md"))


def _korrekturen(root, lauf_ids):
    raus = []
    for lauf in sorted(lauf_ids):
        p = betrieb.area(root) / "tor2_korrekturen" / (lauf + ".json")
        try:
            raus.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return raus


def _planer(root, name):
    return [r for r in _jsonl(betrieb.area(root) / "planer.jsonl", name)
            if r.get("auftrag") == name and r.get("art") in ("start", "ende", "unterbrechung", "abbruch_gesichert",
                                                             "fortsetzung", "gestoppt")]


def _hook_sicherungen(root, lauf_ids):
    if not lauf_ids:
        return []
    return [r for r in _jsonl(Path(root) / "betrieb" / "sicherungen_hook.jsonl")
            if r.get("lauf_id") in lauf_ids and r.get("status") == "ok"]


def _aussenvorgaenge(root, name):
    try:
        import jack_vorgaenge
        return [v for v in jack_vorgaenge.stand(root, jetzt_pid_pruefen=False).values() if v.get("auftrag") == name]
    except Exception:
        return []


def _korrekturen_tor1(root, name, zugriffe):
    """(Text, Herkunft, Kennzeichen, Grund) fuer das Feld 'Korrekturen (Tor 1)' aus dem Werkzeugprotokoll:
    jeder abgewiesene Prueferstart (lokale Vorpruefung gesperrt), die folgende Korrektur des Auftrags und der
    naechste zugelassene Prueferstart."""
    herkunft = "automatisch (Werkzeugprotokoll arbeiter_zugriffe.jsonl, Waechter der lokalen Vorpruefung)"
    zeilen = []
    for i, r in enumerate(zugriffe):
        if not (r.get("tool") == "Agent" and r.get("agent_typ") == "jack-pruefer" and r.get("entscheidung") == "deny"):
            continue
        rest = zugriffe[i + 1:]
        korrektur = next((x for x in rest if x.get("tool") in ("Edit", "Write") and x.get("entscheidung") == "allow"
                          and str(x.get("pfad") or "").endswith("/" + name) and not x.get("agent_id")), None)
        wieder = next((x for x in rest if x.get("tool") == "Agent" and x.get("agent_typ") == "jack-pruefer"
                       and x.get("entscheidung") == "allow"), None)
        grund = re.sub(r"^Lokale Vorpruefung gesperrt:\s*", "", str(r.get("grund") or ""))
        grund = re.split(r"\. Zahl im Auftrag korrigieren|\s+Vermerk:", grund)[0]
        zeilen.append("- %s Prüferstart **gesperrt**: %s\n  - Korrektur: %s\n  - Wiederanlauf: %s" % (
            str(r.get("zeit", ""))[11:19], _kurz(grund, 400),
            ("%s Auftragsdatei vom CEO geändert" % str(korrektur.get("zeit", ""))[11:19]) if korrektur else "keine protokolliert",
            ("%s Prüferstart zugelassen (Tor 1 bestanden)" % str(wieder.get("zeit", ""))[11:19]) if wieder
            else "kein zugelassener Prüferstart danach"))
    if not zeilen:
        return "Keine Korrektur nötig: Tor 1 beim ersten Prüferstart bestanden (oder kein Prüferstart protokolliert).", herkunft, "", ""
    offen = any("kein zugelassener" in z for z in zeilen)
    return ("\n".join(zeilen), herkunft, "offen" if offen else "",
            "Korrektur ohne erfolgreichen Wiederanlauf" if offen else "")


# ------------------------------------------------------------------ Regeln
def zettelart(kopf, vertrag=None, geaenderte=(), aussen=()):
    """('voll'|'kurz', Begruendung). Voll bei Tiefe mittel/gross, Code oder Aussenwirkung (PM-Entscheidung 2)."""
    v = vertrag or {}
    tiefe = kopf.get("tiefe") or v.get("tiefe") or ""
    ablauf = v.get("ablauf") or kopf.get("ablauf") or ""
    gefahr = v.get("gefahr") or kopf.get("gefahr") or ""
    gruende = []
    if tiefe in ("mittel", "gross"):
        gruende.append("Tiefe " + tiefe)
    code = [p for p in geaenderte if str(p).lower().endswith(CODE_ENDUNGEN)]
    if ablauf == "software" or code:
        gruende.append("Code" + (" (Ablauf software)" if ablauf == "software" else " (%d Code-Datei(en) geändert)" % len(code)))
    aussen_gruende = []
    if ablauf in ("video", "veroeffentlichen"):
        aussen_gruende.append("Ablauf " + ablauf)
    if gefahr and gefahr not in ("keine", "-"):
        aussen_gruende.append("Gefahr " + gefahr)
    if str(kopf.get("freigabe", "")).strip().lower() == "ja":
        aussen_gruende.append("freigabepflichtig")
    if aussen:
        aussen_gruende.append("%d Außenvorgang/-vorgänge" % len(aussen))
    if aussen_gruende:
        gruende.append("Außenwirkung (" + ", ".join(aussen_gruende) + ")")
    if gruende:
        return "voll", "; ".join(gruende)
    return "kurz", "Tiefe %s, kein Code, keine Außenwirkung" % (tiefe or "klein")


def persoenlich_abgenommen(root, nr, pruefsumme):
    """(ja, pfad, hinweis). Nur eine Datei des Patrons in auftraege/freigabe/ zaehlt - gebunden an die Pruefsumme."""
    if nr is None:
        return False, None, "keine Auftragsnummer"
    p = Path(root) / "auftraege" / "freigabe" / ("ABGENOMMEN_%s.md" % nr)
    if not p.is_file() or p.is_symlink():
        return False, None, "keine persönliche Abnahme des Patrons abgelegt"
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return False, p, "Abnahmedatei nicht lesbar"
    m = re.search(r"^pruefsumme:[ \t]*([0-9a-f]{12,64})[ \t]*$", text, re.M)
    if not m:
        return False, p, "Abnahmedatei ohne Zeile 'pruefsumme: <mind. 12 Zeichen>' – nicht gebunden, zählt nicht"
    if not pruefsumme or not pruefsumme.startswith(m[1]):
        return False, p, "Abnahmedatei nennt eine andere Prüfsumme – das Ergebnis hat sich seitdem geändert, Abnahme verfallen"
    return True, p, "persönlich abgenommen (%s)" % _rel(root, p)


def _veroeffentlicht(aussen):
    """F-15: veroeffentlicht = Veroeffentlichungsvorgang angekommen UND Sichtkontrolle mit erreichbarer, nicht privater
    Sichtbarkeit (unlisted/public). Ein privater Upload ist ein Zwischenstand ("Upload angenommen"), keine
    Veroeffentlichung (Ausbauplan Paket 5)."""
    for v in aussen:
        s = v.get("sichtkontrolle") or {}
        if (v.get("kanal") == "veroeffentlichung" and v.get("zustand") == "angekommen" and s.get("erreichbar")
                and s.get("sichtbarkeit") in ("unlisted", "public")):
            return True
    return False


def status_bestimmen(root, pfad, ordner, nr=None, pruefsumme=None, aussen=None):
    """{'wort', 'grund', 'gesetzt_von'} - Regel, nie Selbstauskunft. Siehe Moduldokumentation."""
    regel = "Planer (Regel, jack_abnahmezettel.status_bestimmen)"
    try:
        text = Path(pfad).read_text(encoding="utf-8")
    except OSError:
        return {"wort": "offen", "grund": "Auftragsdatei nicht lesbar", "gesetzt_von": regel}
    k = jack_auftrag.kopf(text)
    if k.get("status") == "gestoppt" or re.search(r"^## Vom Patron gestoppt", text, re.M):
        return {"wort": "blockiert", "gesetzt_von": regel,
                "grund": "Vom Patron gestoppt – Abbruch bleibt Abbruch; weiter nur mit neuer Entscheidung des Patrons"}
    if ordner == "problem":
        grund = jack_auftrag.abbruchgrund(text) or "Abnahmeproblem oder Versuchsgrenze"
        return {"wort": "blockiert", "gesetzt_von": regel,
                "grund": "liegt in problem/ (%s) – entscheidet: Patron" % _kurz(grund, 200)}
    if ordner == "freigabe":
        return {"wort": "blockiert", "gesetzt_von": regel, "grund": "wartet auf die Freigabe des Patrons"}
    if ordner == "zurueckgestellt":
        return {"wort": "blockiert", "gesetzt_von": regel, "grund": "zurückgestellt – entscheidet: Patron"}
    if ordner in ("offen", "laeuft"):
        return {"wort": "offen", "gesetzt_von": regel,
                "grund": "in Arbeit" if ordner == "laeuft" else "wartet auf Start oder Vorgänger"}
    try:
        gebunden = jack_auftrag.pruefe_auftrag(root, pfad) is not None
    except (OSError, ValueError) as fehler:
        return {"wort": "offen", "gesetzt_von": regel, "grund": "Auftragsbindung nicht prüfbar: " + _kurz(fehler, 160)}
    if not gebunden:
        return {"wort": "umgesetzt", "gesetzt_von": regel,
                "grund": "Altauftrag ohne geschützte Pflichtpunkte – eine gebundene unabhängige Annahme ist nicht "
                         "belegbar; höher als 'umgesetzt' nicht einstufbar"}
    if not jack_auftrag.ist_erfolgreich(root, pfad):
        vp = jack_auftrag.lokale_vorpruefung(root, pfad, protokollieren=False)
        if vp.get("ok"):
            return {"wort": "umgesetzt", "gesetzt_von": regel,
                    "grund": "Tor 1 (lokale Vorprüfung) bestanden, aber keine gültige Tor-2-Annahme "
                             "(fehlt oder durch spätere Änderung entwertet)"}
        return {"wort": "offen", "gesetzt_von": regel, "grund": "Tor 1 nicht bestanden: " + _kurz(vp.get("text"), 200)}
    wort, grund = "geprüft", "Tor 2 unabhängig ANNAHME; Annahme an den unveränderten Ergebnisstand gebunden (Quittung gültig)"
    if _veroeffentlicht(aussen or []):
        wort, grund = "veröffentlicht", "Veröffentlichung angekommen und sichtkontrolliert"
    ja, _, hinweis = persoenlich_abgenommen(root, nr, pruefsumme)
    if ja:
        return {"wort": "persönlich abgenommen", "grund": hinweis + "; darunter: " + grund,
                "gesetzt_von": "Patron (Datei im Freigabe-Ordner)"}
    return {"wort": wort, "grund": grund + ("" if hinweis.startswith("keine") else "; Hinweis: " + hinweis),
            "gesetzt_von": regel}


# ------------------------------------------------------------------ Felder
def _feld(wert, herkunft, kennzeichen="", grund=""):
    return {"wert": wert, "herkunft": herkunft, "kennzeichen": kennzeichen, "kennzeichen_grund": grund}


def bauen(root, name, jetzt=None):
    """Alle Daten des Zettels (ohne zu schreiben)."""
    root = Path(root).resolve()
    ordner, pfad = finden(root, name)
    if pfad is None:
        raise ValueError("Auftrag nicht gefunden: " + name)
    text = pfad.read_text(encoding="utf-8")
    k = jack_auftrag.kopf(text)
    nr = nummer(root, name)
    try:
        geprueft = jack_auftrag.pruefe_auftrag(root, pfad)
    except (OSError, ValueError):
        geprueft = None
    vertrag, digest = (geprueft[0], geprueft[1]) if geprueft else (None, None)
    zugriffe = _zugriffe(root, name)
    lauf_ids = {r.get("lauf_id") for r in zugriffe if re.fullmatch(r"[0-9a-f]{32}", str(r.get("lauf_id") or ""))}
    kosten = _kosten(root, name)
    lauf_ids |= {r.get("auftragslauf") for r in kosten if r.get("auftragslauf")}
    geschrieben = []
    for r in zugriffe:
        if r.get("tool") in ("Write", "Edit") and r.get("entscheidung") == "allow" and r.get("pfad"):
            if "/abnahme/tor2/" in r["pfad"]:
                continue
            # Die Auftragsdatei selbst wandert (laeuft/ -> erledigt/ ...): auf ihren heutigen Ort abbilden
            if Path(r["pfad"]).name == name and Path(r["pfad"]).parent.name in GRUPPEN:
                r = dict(r, pfad=str(pfad))
            if r["pfad"] not in [g["pfad"] for g in geschrieben]:
                geschrieben.append({"pfad": r["pfad"], "erste_sicherung": r.get("sicherung"), "zeit": r.get("zeit"),
                                    "agent_id": r.get("agent_id")})
    aussen = _aussenvorgaenge(root, name)
    tor2 = _tor2_zettel(root, name)
    quittung = jack_auftrag.quittung(root, vertrag) if vertrag else None
    try:
        stand = jack_auftrag.snapshot(root, pfad) if vertrag else None
    except (OSError, ValueError):
        stand = None
    ergebnisdateien = [d["pfad"] for d in (stand or {}).get("dateien", [])]
    art, art_grund = zettelart(k, vertrag, [g["pfad"] for g in geschrieben] + ergebnisdateien, aussen)
    if quittung:
        pruefsumme, pruefsumme_quelle = quittung["ergebnisstand"]["sha256"], "Ergebnisstand der Tor-2-Annahme (Quittung)"
    elif stand:
        pruefsumme, pruefsumme_quelle = stand["sha256"], "aktueller Ergebnisstand (noch ohne Tor-2-Annahme)"
    else:
        pruefsumme, pruefsumme_quelle = _sha(pfad), "Auftragsdatei (kein gebundener Ergebnisstand)"
    status = status_bestimmen(root, pfad, ordner, nr, pruefsumme, aussen)
    vp = None
    if vertrag:
        try:
            vp = jack_auftrag.lokale_vorpruefung(root, pfad, protokollieren=False)
        except (OSError, ValueError):
            vp = None
    if vp and vp.get("zahlen_abweichungen") and status["wort"] in ("geprüft", "veröffentlicht", "persönlich abgenommen"):
        # Altannahme vor P04: der Status folgt der gueltigen Quittung, die Abweichung steht offen daneben.
        status = dict(status, grund=status["grund"] + "; ACHTUNG: nach heutiger Regel (F-11 P04) waere diese Annahme "
                                                      "gesperrt - eine entscheidungstragende Zahl weicht von der Messung ab "
                                                      "(Feld Beobachtetes Ergebnis)")
    rahmen = (lambda feld: jack_auftrag.rahmen_abschnitt(vertrag, feld)) if vertrag and vertrag.get("schema") == 2 else (lambda feld: None)

    F = {}
    # 1 Ausgangszustand
    zeilen = []
    if rahmen("ausgangslage"):
        zeilen.append("Ausgangslage laut Vertrag: " + _kurz(rahmen("ausgangslage"), 600))
    for g in geschrieben:
        if g["erste_sicherung"]:
            zeilen.append("- `%s`: vorher vorhanden – Stand vor dem ersten Schreiben gesichert (`%s`)"
                          % (_rel(root, g["pfad"]), g["erste_sicherung"]))
        else:
            zeilen.append("- `%s`: vorher nicht vorhanden (Neuanlage; der Wächter sichert jede bestehende Datei vor dem "
                          "Schreiben, hier gab es keine)" % _rel(root, g["pfad"]))
    F["ausgangszustand"] = _feld("\n".join(zeilen) or "Kein Schreibzugriff im Werkzeugprotokoll.",
                                 "automatisch (Vertrag, Werkzeugprotokoll arbeiter_zugriffe.jsonl)",
                                 "" if zeilen else "offen", "" if zeilen else "kein Lauf protokolliert")
    # 2 Vollstaendiger Auftrag
    if vertrag:
        wert = ("**%s** · Marke %s · Ablauf %s · Tiefe %s · Gefahr %s\n\nVertrag `%s` (SHA-256 `%s`), Quelle `%s`\n\n"
                "Originalauftrag: %s\n\nAuftrag: %s" % (
                    vertrag.get("auftrag"), vertrag.get("marke"), vertrag.get("ablauf"), vertrag.get("tiefe"),
                    vertrag.get("gefahr"), vertrag.get("kennung"), digest, k.get("vertragsquelle"),
                    _kurz(vertrag.get("original"), 500), _kurz(vertrag.get("beschreibung"), 1500)))
        # F-20 (Paket 6): Lernhinweise stehen im Vertrag (Text nur aus der freigegebenen Regelliste)
        if "lernhinweise" in vertrag:
            wert += ("\n\nLernhinweise (Vertrag; Regelliste betrieb/lernregeln.json, höchstens 3):\n"
                     + jack_auftrag.lernhinweise_abschnitt(vertrag["lernhinweise"]))
        else:
            wert += "\n\nLernhinweise: keine im Vertrag (Vertrag vor Paket 6 angelegt)"
        F["auftrag"] = _feld(wert, "automatisch (geschützter Auftragsvertrag)")
    else:
        F["auftrag"] = _feld("**%s** · Marke %s (Altauftrag ohne geschützten Vertrag)\n\n%s" % (
            k.get("auftrag") or name, k.get("marke"), _kurz(jack_auftrag._abschnitt_oder_leer(text, "Auftrag"), 1500)),
            "automatisch (Auftragsdatei)", "angenommen", "ohne Vertrag ist der Wortlaut nicht gegen Änderung geschützt")
    # 3 Pflichtpunkte
    teilbelege = {}
    for z in tor2:
        try:
            for zeile in re.findall(r"^teilbeleg:[ \t]*(.*?)\s*$", z.read_text(encoding="utf-8"), re.M):
                teilbelege.setdefault(zeile.split(".", 1)[0].strip(), []).append(_kurz(zeile, 240))
        except OSError:
            continue
    if vertrag:
        nachweise = {p["kennung"]: p for p in (stand or {}).get("pflichtpunkte", [])}
        zeilen = []
        for p in vertrag["pflichtpunkte"]:
            n = nachweise.get(p["kennung"]) or {}
            zeilen.append("- **%s**: %s\n  - Nachweis: %s\n  - Belege: %s%s" % (
                p["kennung"], p["text"], _kurz(n.get("ergebnis") or "(kein Nachweis)", 400),
                ", ".join("`%s`" % b for b in n.get("belege", [])) or "–",
                "".join("\n  - Tor 2: " + t for t in teilbelege.get(p["kennung"], []))))
        F["pflichtpunkte"] = _feld("\n".join(zeilen), "automatisch (Vertrag, Pflichtpunktnachweise) · Prüfer (Tor-2-Teilbelege)",
                                   "" if nachweise else "offen", "" if nachweise else "Nachweise fehlen oder unvollständig")
    else:
        F["pflichtpunkte"] = _feld("Keine geschützten Pflichtpunkte (Altauftrag).", "automatisch", "offen",
                                   "ohne Pflichtpunkte kein Einzelbeleg")
    # 4 Aenderungen
    zeilen = []
    for g in geschrieben:
        p = Path(g["pfad"])
        sha = _sha(p)
        zeilen.append("- `%s` – jetzt SHA-256 `%s`%s" % (_rel(root, p), (sha or "fehlt")[:16],
                                                         "" if sha else " (Datei nicht mehr vorhanden)"))
    for d in (stand or {}).get("dateien", []):
        if not any(_rel(root, g["pfad"]) == d["pfad"] for g in geschrieben):
            zeilen.append("- `%s` – Ergebnisdatei, SHA-256 `%s`, %d Bytes" % (d["pfad"], d["sha256"][:16], d["bytes"]))
    F["aenderungen"] = _feld("\n".join(zeilen) or "Keine Dateiänderung protokolliert.",
                             "automatisch (Werkzeugprotokoll, Dateisystem)")
    # 5 Sicherungen
    zeilen = ["- `%s` (vor dem ersten Schreiben von `%s`)" % (g["erste_sicherung"], _rel(root, g["pfad"]))
              for g in geschrieben if g["erste_sicherung"]]
    zeilen += ["- Hook: `%s`" % _rel(root, r.get("sicherung")) for r in _hook_sicherungen(root, lauf_ids)]
    fb = jack_auftrag.fortsetzung_pfad(root, name)
    if fb.is_file():
        zeilen.append("- Fortsetzungsbeleg (hash-gebundener Zwischenstand): `%s`" % _rel(root, fb))
    F["sicherungen"] = _feld("\n".join(zeilen) or "Keine nötig: nur neue Dateien angelegt, keine bestehende überschrieben.",
                             "automatisch (Werkzeugprotokoll, Sicherungs-Hook, Fortsetzungsbeleg)")
    # 6 Reale Ausloesung
    planer = _planer(root, name)
    zeilen = ["Erteilt: %s von %s" % (k.get("erteilt", "?"), k.get("von", "?"))]
    if vertrag and vertrag.get("original"):
        zeilen.append("Wortlaut der Auslösung: " + _kurz(vertrag.get("original"), 300))
    for r in planer:
        if r.get("art") == "start":
            zusatz = " (Nr. %s, Prozess %s)" % (r.get("nummer"), r.get("pid"))
        elif r.get("art") == "ende":
            zusatz = " (Dauer %s s)" % r.get("dauer_s")
        else:
            zusatz = " – " + _kurz(r.get("grund") or r.get("schritt") or "", 120)
        zeilen.append("- Planer %s %s%s" % (r.get("art"), str(r.get("zeit", ""))[:19], zusatz))
    if k.get("zeitgrenze_minuten"):
        import jack_grenzen
        minuten, gekappt, obergrenze = jack_grenzen.zeitgrenze_auftragskopf(root, k.get("zeitgrenze_minuten"))
        if gekappt:
            zeilen.append("Zeitgrenze laut Auftragskopf %s Minuten – **gekappt** auf %d Minuten "
                          "(zeitgrenze_max_auftragskopf, F-12)" % (k.get("zeitgrenze_minuten"), obergrenze))
        elif minuten is not None:
            zeilen.append("Zeitgrenze laut Auftragskopf: %d Minuten" % minuten)
        else:
            zeilen.append("Zeitgrenze laut Auftragskopf ungültig (%s) – Ablaufgrenze gilt" % k.get("zeitgrenze_minuten"))
    for v in aussen:   # F-15: Aussenvorgaenge (Veroeffentlichung, Versand, Video) mit Sichtkontrolle
        sk = v.get("sichtkontrolle") or {}
        zeilen.append("- Außenvorgang `%s` (%s, %s): %s%s%s" % (
            v.get("vg"), v.get("kanal"), v.get("bezug"), v.get("zustand"),
            (" – Anbieterkennung " + str(v.get("anbieter_kennung"))) if v.get("anbieter_kennung") else "",
            (" – Sichtkontrolle %s, %s, %s" % (sk.get("sichtbarkeit"), "erreichbar" if sk.get("erreichbar") else "nicht öffentlich erreichbar",
                                              sk.get("link"))) if sk else ""))
    echt = [r for r in kosten if r.get("abrechnung") == "api" and not r.get("historisch")]
    zeilen.append("Echter Modelllauf: " + ("ja – %d bezahlte(r) Lauf/Läufe im Kostenbuch" % len(echt) if echt
                                           else "kein bezahlter Lauf im Kostenbuch"))
    F["ausloesung"] = _feld("\n".join(zeilen), "automatisch (Auftragskopf, Vertrag, Planerprotokoll, Kostenbuch)",
                            "" if planer or echt else "vermutet", "" if planer or echt else "keine Planer-/Kostenspur gefunden")
    # 7 Erwartetes Ergebnis
    zeilen = []
    if vertrag:
        zeilen.append("%d Pflichtpunkte (Feld Pflichtpunkte), je einzeln belegt und unabhängig angenommen." % len(vertrag["pflichtpunkte"]))
        for feld, titel in (("pruefkriterien", "Prüfkriterien"), ("qualitaetsmassstab", "Qualitätsmaßstab"), ("ablageort", "Ablageort")):
            if rahmen(feld):
                zeilen.append("%s: %s" % (titel, _kurz(rahmen(feld), 400)))
        for regel in vertrag.get("lokale_pruefungen") or []:
            zeilen.append("Lokale Regel: %s – `%s` höchstens %s Wörter" % (regel.get("pflichtpunkt"), regel.get("datei"),
                                                                          regel.get("max_woerter")))
    else:
        zeilen.append(_kurz(jack_auftrag._abschnitt_oder_leer(text, "Prüfpunkte"), 800) or "(keine Prüfpunkte)")
    F["erwartet"] = _feld("\n".join(zeilen), "automatisch (Vertrag)")
    # 8 Beobachtetes Ergebnis
    zeilen = ["Gemeldetes Ergebnis: " + _kurz(jack_auftrag._abschnitt_oder_leer(text, "Ergebnis") or "(leer)", 1200)]
    kz, kz_grund = "", ""
    if vp:
        zeilen.append("Lokale Messung (Tor 1, ohne Modell): " + ("bestanden" if vp.get("ok") else "GESPERRT"))
        for c in vp.get("wortzahlen") or []:
            zeilen.append("- %s: %d von höchstens %d Wörtern gemessen (`%s`)" % (c["pflichtpunkt"], c["ist"], c["max_woerter"], c["datei"]))
        for a in vp.get("zahlen_abweichungen") or []:
            zeilen.append("- **Entscheidungstragende Zahl weicht ab:** " + a["text"])
        for v in vp.get("vermerke") or []:
            zeilen.append("- Vermerk: " + v["text"])
        if not vp.get("ok"):
            zeilen.append("- Sperrgrund: " + _kurz(vp.get("text"), 500))
        if vp.get("zahlen_abweichungen"):
            kz, kz_grund = "offen", "gemeldete Zahl widerspricht der Messung (P04)"
    F["beobachtet"] = _feld("\n".join(zeilen), "automatisch (Auftragsdatei, lokale Vorprüfung)", kz, kz_grund)
    # 8b Korrekturen (Tor 1) - F-12
    F["korrekturen"] = _feld(*_korrekturen_tor1(root, name, zugriffe))
    # 9 Kosten
    zeilen, gemeldet, geschaetzt, ohne, obergrenze = [], Decimal(0), Decimal(0), 0, False
    for r in kosten:
        if r.get("ereignis") == "start":
            zeilen.append("- %s %s %s – **Lauf ohne Ende-Zeile** (offen)" % (str(r.get("zeit"))[:19], r.get("art"), r.get("modell")))
            ohne += 1
            continue
        if r.get("usd_gemeldet") is not None:
            gemeldet += Decimal(str(r["usd_gemeldet"]))
            betrag = "%s gemeldet (%s)" % (betrag_text(r["usd_gemeldet"]), _exakt(r["usd_gemeldet"]))
        elif r.get("usd_geschaetzt") is not None:
            geschaetzt += Decimal(str(r["usd_geschaetzt"]))
            ist_ober = r.get("betrag_art") == "obergrenze"
            obergrenze = obergrenze or ist_ober
            betrag = "%s **geschätzt**%s (%s)" % (betrag_text(r["usd_geschaetzt"]),
                                                  " – Obergrenze Kostenrahmen, Abbruch ohne gemeldeten Betrag" if ist_ober else
                                                  (" – nachgebucht" if r.get("ereignis") == "nachbuchung" else " – aus Verbrauch und Listenpreis"),
                                                  _exakt(r["usd_geschaetzt"]))
        else:
            ohne += 1
            betrag = "**ohne Betrag** (Kostenlücke)"
        zeilen.append("- %s %s %s %s%s – %s" % (str(r.get("zeit"))[:19], r.get("art"), r.get("modell"), r.get("status"),
                                                (" (" + r["fehlerart"] + ")") if r.get("fehlerart") else "", betrag))
    rahmen_usd = k.get("kostenrahmen_usd")
    zeilen.append("Summe: %s gemeldet · %s geschätzt%s" % (betrag_text(gemeldet), betrag_text(geschaetzt),
                                                          (" · Rahmen %s" % betrag_text(rahmen_usd)) if rahmen_usd else ""))
    if not kosten:
        zeilen = ["Kein Lauf dieses Auftrags im Kostenbuch."]
    kz = "offen" if ohne else ("angenommen" if geschaetzt else "")
    F["kosten"] = _feld("\n".join(zeilen), "automatisch (Kostenbuch betrieb/kostenlaeufe.jsonl)", kz,
                        "%d Lauf/Läufe ohne Betrag" % ohne if ohne else
                        ("enthält geschätzte Beträge%s" % (" (Obergrenze)" if obergrenze else "") if geschaetzt else ""))
    # 10 Unabhaengige Pruefung
    zeilen = []
    for z in tor2:
        try:
            inhalt = z.read_text(encoding="utf-8")
        except OSError:
            continue
        urteil = re.search(r"^urteil:[ \t]*(.*?)\s*$", inhalt, re.M)
        pp = re.search(r"^pflichtpunkte:[ \t]*(.*?)\s*$", inhalt, re.M)
        punkte = re.search(r"^pruefpunkte:[ \t]*(.*?)\s*$", inhalt, re.M)
        wer = next((r.get("agent_id") for r in zugriffe if r.get("tool") == "Write" and r.get("entscheidung") == "allow"
                    and str(r.get("pfad") or "").endswith("/" + z.name)), None)
        zeilen.append("- `%s` (SHA-256 `%s`): **urteil: %s** · pflichtpunkte: %s · Prüfer-Unteragent %s\n  - pruefpunkte (wörtlich): %s"
                      % (_rel(root, z), (_sha(z) or "")[:16], urteil[1] if urteil else "?", pp[1] if pp else "–",
                         wer or "nicht im Protokoll", _kurz(punkte[1] if punkte else "", 700)))
        # F-20: Lernhinweise als zusaetzliche Pruefpunkte - je Hinweis die Zeile des Pruefers (woertlich, gekuerzt)
        if vertrag and vertrag.get("lernhinweise"):
            vermerke = re.findall(r"^lernhinweis:[ \t]*(.*?)\s*$", inhalt, re.M)
            for h in vertrag["lernhinweise"]:
                treffer = [v for v in vermerke if re.match(re.escape(h["kennung"]) + r"\b", v)]
                zeilen.append("  - Lernhinweis %s: %s" % (h["kennung"], _kurz(treffer[0], 240) if treffer
                                                             else "vom Prüfer nicht vermerkt"))
    for kr in _korrekturen(root, lauf_ids):
        zeilen.append("- Korrekturrunde(n) im Lauf `%s`: %s Formfehler%s" % (
            kr.get("lauf_id"), kr.get("formfehler"), (" – " + _kurz("; ".join(kr.get("meldungen") or []), 300)) if kr.get("meldungen") else ""))
    if quittung:
        zeilen.append("- Abschlussquittung vom %s (Lauf `%s`)" % (str(quittung.get("zeit"))[:19], quittung.get("lauf_id")))
    F["pruefung"] = _feld("\n".join(zeilen) or "Kein Tor-2-Zettel.", "Prüfer (Tor-2-Zettel, wörtlich übernommen, unverändert)",
                          "" if tor2 else "offen", "" if tor2 else "keine unabhängige Prüfung")
    # 11 Belegpfad
    belege = ["Auftrag: `%s`" % _rel(root, pfad)]
    if vertrag:
        belege.append("Vertrag: `%s`" % k.get("vertragsquelle"))
    if quittung:
        belege.append("Quittung: `%s`" % _rel(root, Path(root) / "betrieb/auftragsabschluesse" /
                                              (vertrag["kennung"] + "_" + quittung["lauf_id"] + ".json")))
    belege += ["Tor-2-Zettel: `%s`" % _rel(root, z) for z in tor2]
    belege += ["Ergebnis: `%s`" % d for d in ergebnisdateien]
    if fb.is_file():
        belege.append("Fortsetzungsbeleg: `%s`" % _rel(root, fb))
    belege += ["Kostenbuch: `00_Marken/JACK/betrieb/kostenlaeufe.jsonl#id=%s`" % r["id"] for r in kosten]
    belege.append("Werkzeugprotokoll: `00_Marken/JACK/arbeiter_zugriffe.jsonl` (%d Einträge dieses Auftrags)" % len(zugriffe))
    F["belegpfad"] = _feld("\n".join("- " + b for b in belege), "automatisch (Dateisystem)")
    # 12 Zeitpunkt
    zeilen = ["- erteilt: %s" % k.get("erteilt", "?")]
    for r in kosten:
        dauer = r.get("dauer_s") if isinstance(r.get("dauer_s"), dict) else {}
        zeilen.append("- Lauf %s: %s bis %s%s" % (str(r.get("auftragslauf") or r.get("id"))[:8], str(r.get("zeit"))[11:19],
                                                  str(r.get("ende") or "?")[11:19],
                                                  (" · Dauer je Rolle (s): " + ", ".join("%s %s" % (a, b) for a, b in dauer.items())) if dauer else ""))
    if quittung:
        zeilen.append("- Tor-2-Annahme quittiert: %s" % str(quittung.get("zeit"))[:19])
    jetzt = jetzt or betrieb.now()
    zeilen.append("- Zettel erstellt: %s" % jetzt.isoformat(timespec="seconds"))
    F["zeitpunkt"] = _feld("\n".join(zeilen), "automatisch (Auftragskopf, Kostenbuch, Quittung)")
    # 13 Pruefsumme
    zeilen = ["Gesamt (%s): `%s`" % (pruefsumme_quelle, pruefsumme)]
    if quittung:
        zeilen.append("Nachgerechnet: %s" % ("unverändert – Annahme gilt" if status["wort"] in ("geprüft", "veröffentlicht", "persönlich abgenommen")
                                             else "ABWEICHUNG oder Annahme ungültig"))
    zeilen += ["- `%s`: `%s`" % (d["pfad"], d["sha256"]) for d in (stand or {}).get("dateien", [])]
    zeilen.append("- Auftragsdatei: `%s`" % _sha(pfad))
    zeilen += ["- Tor-2-Zettel `%s`: `%s`" % (z.name, _sha(z)) for z in tor2]
    F["pruefsumme"] = _feld("\n".join(zeilen), "automatisch (SHA-256 aus dem Dateisystem, Quittung)")
    # 14 Rueckweg
    zeilen = []
    if rahmen("rueckweg"):
        zeilen.append("Laut Vertrag: " + _kurz(rahmen("rueckweg"), 400))
    gesichert = [g for g in geschrieben if g["erste_sicherung"]]
    if gesichert:
        zeilen.append("Zurück zum Ausgangszustand: die Sicherungen aus Feld Sicherungen an ihren Ort zurückkopieren.")
    neu = [g for g in geschrieben if not g["erste_sicherung"]]
    if neu:
        zeilen.append("Neu angelegte Dateien (%d): nichts löschen – unbeachtet lassen oder nur mit Freigabe nach "
                      "99_Archiv/_Papierkorb_zur_Pruefung/." % len(neu))
    F["rueckweg"] = _feld("\n".join(zeilen) or "Kein Eingriff protokolliert – nichts zurückzunehmen.",
                          "automatisch (Vertrag, Sicherungen)")
    # 15 Status
    F["status"] = _feld("**%s** – %s\n\nGesetzt von: %s" % (status["wort"], status["grund"], status["gesetzt_von"]),
                        status["gesetzt_von"])
    return {"schema": SCHEMA, "name": name, "nummer": nr, "ordner": ordner, "art": art, "art_grund": art_grund,
            "status": status, "pruefsumme": pruefsumme, "titel": (vertrag or {}).get("auftrag") or k.get("auftrag") or name,
            "felder": F, "erstellt": jetzt.isoformat(timespec="seconds")}


def text(daten):
    felder = FELDER_VOLL if daten["art"] == "voll" else tuple(f for f in FELDER_VOLL if f[0] in FELDER_KURZ)
    kopf = ["---", "art:        abnahmezettel", "schema:     %d" % daten["schema"],
            "zettel:     %s" % daten["art"], "nummer:     %s" % daten["nummer"], "auftrag:    %s" % daten["name"],
            "ordner:     %s" % daten["ordner"], "status:     %s" % daten["status"]["wort"],
            "status_von: %s" % daten["status"]["gesetzt_von"], "pruefsumme: %s" % daten["pruefsumme"],
            "erstellt:   %s" % daten["erstellt"], "---", "",
            "# Abnahmezettel Nr. %s – %s" % (daten["nummer"], daten["titel"]), "",
            "**%s** (%d Felder) – %s. Geschrieben vom Planer, nie von einem Lauf. Der Tor-2-Zettel bleibt unverändert "
            "und ist hier nur wörtlich übernommen und verlinkt. Automatische Felder belegen Herkunft und "
            "Unveränderlichkeit, nicht die fachliche Richtigkeit – die belegt Tor 2."
            % ("Vollzettel" if daten["art"] == "voll" else "Kurzzettel", len(felder), daten["art_grund"]), ""]
    for nr, (schluessel, titel) in enumerate(felder, 1):
        f = daten["felder"][schluessel]
        kopf += ["## %d. %s" % (nr, titel), "", f["wert"].rstrip(), "",
                 "_Herkunft: %s%s_" % (f["herkunft"], (" · **Kennzeichen: %s** – %s" % (f["kennzeichen"], f["kennzeichen_grund"]))
                                        if f["kennzeichen"] else ""), ""]
    return "\n".join(kopf).rstrip() + "\n"


def _ohne_zeitstempel(inhalt):
    inhalt = re.sub(r"^erstellt:.*$", "", inhalt, flags=re.M)
    return re.sub(r"^- Zettel erstellt:.*$", "", inhalt, flags=re.M)


def schreiben(root, name, jetzt=None):
    """Zettel schreiben (nur Planer). Unveraenderter Inhalt -> nichts tun. Geaendert -> alte Fassung nach
    abnahme/zettel_verlauf/, dann ersetzen. Nichts wird geloescht."""
    root = Path(root).resolve()
    daten = bauen(root, name, jetzt)
    ziel = zettelpfad(root, name, daten["nummer"])
    neu = text(daten)
    if ziel.is_file():
        alt = ziel.read_text(encoding="utf-8")
        if _ohne_zeitstempel(alt) == _ohne_zeitstempel(neu):
            return {"pfad": str(ziel), "art": daten["art"], "status": daten["status"]["wort"], "geaendert": False}
        verlauf = ziel.parent / VERLAUF
        verlauf.mkdir(parents=True, exist_ok=True)
        stempel = (jetzt or betrieb.now()).strftime("%Y%m%d_%H%M%S")
        kopie = verlauf / ("%s_%s.md" % (ziel.stem, stempel))
        n = 2
        while kopie.exists():
            kopie = verlauf / ("%s_%s_%d.md" % (ziel.stem, stempel, n))
            n += 1
        shutil.copy2(ziel, kopie)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    tmp = ziel.with_name("." + ziel.name + ".neu")
    tmp.write_text(neu, encoding="utf-8")
    os.replace(tmp, ziel)
    return {"pfad": str(ziel), "art": daten["art"], "status": daten["status"]["wort"], "geaendert": True}


def fuer_tafel(root, name, ordner, pfad=None):
    """Kurzer Zettelstand fuer die Auftragstafel (P07): Status nach Regel, Zettelart, Pfad falls geschrieben."""
    try:
        pfad = Path(pfad) if pfad else Path(root) / "auftraege" / ordner / name
        nr = nummer(root, name)
        ziel = zettelpfad(root, name, nr)
        vorhanden = ziel.is_file()
        pruefsumme = None
        if vorhanden:
            m = re.search(r"^pruefsumme:[ \t]*(\S+)", ziel.read_text(encoding="utf-8")[:2000], re.M)
            pruefsumme = m[1] if m else None
        status = status_bestimmen(root, pfad, ordner, nr, pruefsumme)
        k = jack_auftrag.kopf(pfad.read_text(encoding="utf-8"))
        art, _ = zettelart(k)
        return {"status": status["wort"], "grund": status["grund"][:200], "gesetzt_von": status["gesetzt_von"],
                "art": art, "pfad": _rel(root, ziel) if vorhanden else None, "nummer": nr}
    except Exception as fehler:
        return {"status": None, "fehler": type(fehler).__name__}


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] in ("schreiben", "zeigen", "status"):
        wurzel = HIER
        if sys.argv[1] == "schreiben":
            print(json.dumps(schreiben(wurzel, sys.argv[2]), ensure_ascii=False))
        elif sys.argv[1] == "zeigen":
            print(text(bauen(wurzel, sys.argv[2])))
        else:
            o, p = finden(wurzel, sys.argv[2])
            print(json.dumps(fuer_tafel(wurzel, sys.argv[2], o, p), ensure_ascii=False))
    else:
        print("schreiben|zeigen|status <Auftragsdatei-Name>")
