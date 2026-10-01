#!/usr/bin/env python3
"""Freigaben, die an einen konkreten Vorgang gebunden sind (Block 3, P0-03).

Bisher galt eine Freigabe, sobald im Auftragskopf "freigabe: nein" und
"status: freigabe" stand - und das Modell konnte beides selbst schreiben.
Die Freigabe haftete an Text, nicht an einer Entscheidung des Patrons.

Ab jetzt gilt:
  - Der Server vergibt je freigabepflichtigem Vorgang eine eigene KENNUNG und
    haelt sie AUSSERHALB der Auftragsdatei vor, mit Pruefsumme des Vorgangs,
    Zeit und Ablauf.
  - Erteilt wird eine Freigabe nur ueber den Weg des Patrons (/freigabe/erteilen),
    nie aus Modelltext, nie aus dem Dateikopf, nie aus einer gelesenen Datei.
  - Aendert sich der Inhalt des Vorgangs, verfaellt die Freigabe.
  - Nach einer festen Frist verfaellt sie ebenfalls.
  - Jede Freigabe kann genau EINMAL verbraucht werden.
  - Erteilen, Verbrauchen und Verfallen werden mit Herkunft protokolliert.
"""
import hashlib
import json
import os
import re
import secrets
import time
from pathlib import Path

import jack_betrieb as betrieb

BUCH = "freigaben.jsonl"      # Verlauf, unveraenderlich angehaengt
STAND = "freigaben.json"      # aktueller Stand je Kennung
FRIST = 3600                  # eine Stunde; danach ist die Freigabe ungueltig


def _stand_pfad(root):
    return betrieb.area(root) / STAND


def _lesen(root):
    try:
        return json.loads(_stand_pfad(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _schreiben(root, daten):
    p = _stand_pfad(root)
    tmp = p.with_suffix(".json.neu")
    tmp.write_text(json.dumps(daten, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def buchen(root, art, **felder):
    """Jede Regung wird mit Herkunft protokolliert."""
    try:
        e = {"zeit": betrieb.now().isoformat(), "art": art}
        e.update(felder)
        with (betrieb.area(root) / BUCH).open("a", encoding="utf-8") as d:
            d.write(json.dumps(e, ensure_ascii=False) + "\n")
    except Exception:
        pass


_GEN_EMPFEHLUNG_RE = re.compile(r"\n*## Empfehlung von JACK\s*\n\s*\*\*Entscheid:\*\*.*?_Erzeugt [^\n]*_[ \t]*\n?", re.S)
_GEN_HINWEIS_RE = re.compile(r"\n*## Hinweis JACK — keine automatische Empfehlung moeglich.*?(?=\n## |\Z)", re.S)


def vorgangspruefsumme_alt(pfad: Path) -> str:
    """Die fruehere Pruefsumme (ganzer Rumpf ohne Kopf). Bleibt, damit vor F-100 angeforderte Freigaben gueltig bleiben."""
    try:
        text = pfad.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    m = re.match(r"^---\s*\n.*?\n---\s*\n", text, re.S)
    rumpf = text[m.end():] if m else text
    return hashlib.sha256(rumpf.encode("utf-8")).hexdigest()


def vorgangspruefsumme(pfad: Path) -> str:
    """Pruefsumme ueber das, was der Patron SIEHT (F-100 / F-99 J): die Pflichtfelder des Kartenkopfs (v2) und den
    Auftragstext - OHNE automatisch angehaengte Nachtraege (Abschnitt 'Empfehlung von JACK' der Stufe 1, 'Hinweis JACK'),
    ohne Zaehler, Zeitstempel, Status und Nummer. Ein Nachtrag im Hintergrund entwertet damit keine Freigabe mehr."""
    try:
        text = pfad.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    kopf = {}
    if m:
        for z in m.group(1).splitlines():
            k, _, w = z.partition(":")
            kopf[k.strip().lower()] = w.strip()
    rumpf = text[m.end():] if m else text
    rumpf = _GEN_EMPFEHLUNG_RE.sub("\n", rumpf)
    rumpf = _GEN_HINWEIS_RE.sub("\n", rumpf)
    rumpf = re.sub(r"\s+", " ", rumpf).strip()
    felder = "|".join("%s=%s" % (f, kopf.get(f, "")) for f in V2_PFLICHTFELDER)
    return hashlib.sha256(("v2\n" + felder + "\n" + rumpf).encode("utf-8")).hexdigest()


KARTE_AKTUALISIERT = "Diese Karte wurde gerade aktualisiert — bitte noch einmal ansehen."


def _summe_passt(pfad: Path, gespeichert: str) -> bool:
    return bool(gespeichert) and gespeichert in (vorgangspruefsumme(pfad), vorgangspruefsumme_alt(pfad))


def anfordern(root, datei: str, grund: str = "", frist: int = FRIST):
    """Legt eine Freigabe-Anfrage an und gibt die Kennung zurueck."""
    pfad = Path(root) / "auftraege" / "freigabe" / datei
    if not pfad.is_file():
        return None, "Der Vorgang liegt nicht in auftraege/freigabe/"
    daten = _lesen(root)
    # Eine offene Anfrage zum selben Vorgang und Inhalt wird wiederverwendet.
    summe = vorgangspruefsumme(pfad)
    for kennung, e in daten.items():
        if e.get("datei") == datei and e.get("pruefsumme") == summe and \
           e.get("status") in ("wartet", "erteilt") and time.time() < e.get("laeuft_ab_epoch", 0):
            return kennung, "vorhanden"
    kennung = secrets.token_hex(16)
    jetzt = time.time()
    daten[kennung] = {
        "kennung": kennung, "datei": datei, "pruefsumme": summe,
        "angefordert": betrieb.now().isoformat(), "angefordert_epoch": jetzt,
        "laeuft_ab_epoch": jetzt + frist, "frist_s": frist,
        "status": "wartet", "grund": str(grund)[:300],
    }
    _schreiben(root, daten)
    buchen(root, "angefordert", kennung=kennung, datei=datei, pruefsumme=summe,
           frist_s=frist, herkunft="server")
    return kennung, "neu"


def _verfallen(e, jetzt=None) -> bool:
    return (jetzt or time.time()) > e.get("laeuft_ab_epoch", 0)


def erteilen(root, kennung: str, von: str = "Patron", herkunft: str = "maske"):
    """NUR ueber den Weg des Patrons. Nie aus Modelltext."""
    daten = _lesen(root)
    e = daten.get(kennung)
    if not e:
        buchen(root, "erteilen_abgewiesen", kennung=kennung, grund="unbekannte Kennung",
               herkunft=herkunft)
        return False, "Diese Kennung gibt es nicht."
    if e["status"] == "verbraucht":
        return False, "Diese Freigabe ist bereits verbraucht."
    if _verfallen(e):
        e["status"] = "verfallen"
        _schreiben(root, daten)
        buchen(root, "verfallen", kennung=kennung, datei=e["datei"], herkunft=herkunft)
        return False, "Diese Freigabe ist abgelaufen. Bitte neu anfordern."
    pfad = Path(root) / "auftraege" / "freigabe" / e["datei"]
    jetzige = vorgangspruefsumme(pfad)
    if not _summe_passt(pfad, e["pruefsumme"]):
        e["status"] = "ungueltig"
        e["grund_ungueltig"] = "Inhalt des Vorgangs hat sich geaendert"
        _schreiben(root, daten)
        buchen(root, "ungueltig", kennung=kennung, datei=e["datei"],
               erwartet=e["pruefsumme"], gefunden=jetzige, herkunft=herkunft)
        return False, KARTE_AKTUALISIERT
    e["status"] = "erteilt"
    e["erteilt"] = betrieb.now().isoformat()
    e["erteilt_von"] = von
    e["erteilt_herkunft"] = herkunft
    _schreiben(root, daten)
    buchen(root, "erteilt", kennung=kennung, datei=e["datei"], von=von, herkunft=herkunft)
    return True, "Freigabe erteilt fuer %s" % e["datei"]


def pruefen(root, kennung: str, datei: str):
    """Darf dieser Vorgang jetzt laufen? Ohne zu verbrauchen."""
    daten = _lesen(root)
    e = daten.get(kennung)
    if not e:
        return False, "Keine Freigabe mit dieser Kennung."
    if e.get("datei") != datei:
        return False, "Die Freigabe gehoert zu einem anderen Vorgang."
    if e["status"] == "verbraucht":
        return False, "Diese Freigabe wurde bereits verbraucht."
    if e["status"] != "erteilt":
        return False, "Diese Freigabe ist nicht erteilt (Stand: %s)." % e["status"]
    if _verfallen(e):
        return False, "Diese Freigabe ist abgelaufen."
    pfad = Path(root) / "auftraege" / "freigabe" / datei
    if not _summe_passt(pfad, e["pruefsumme"]):
        return False, KARTE_AKTUALISIERT
    return True, "gueltig"


def verbrauchen(root, kennung: str, datei: str, herkunft: str = "arbeiter"):
    """Genau einmal. Danach ist die Freigabe weg."""
    ok, grund = pruefen(root, kennung, datei)
    if not ok:
        buchen(root, "verbrauch_abgewiesen", kennung=kennung, datei=datei,
               grund=grund, herkunft=herkunft)
        return False, grund
    daten = _lesen(root)
    e = daten[kennung]
    e["status"] = "verbraucht"
    e["verbraucht"] = betrieb.now().isoformat()
    e["verbraucht_herkunft"] = herkunft
    _schreiben(root, daten)
    buchen(root, "verbraucht", kennung=kennung, datei=datei, herkunft=herkunft)
    return True, "Freigabe verbraucht."


def aufraeumen(root):
    """Abgelaufene Anfragen als verfallen kennzeichnen und protokollieren."""
    daten = _lesen(root)
    jetzt = time.time()
    geaendert = []
    for kennung, e in daten.items():
        if e["status"] not in ("wartet", "erteilt"):
            continue
        # Block 28: Eine wartende Mitarbeiter-Karte verfaellt nicht durch Zeit.
        # Die Anfrage wird verlaengert, die Karte bleibt beim Patron.
        karte = Path(root) / "auftraege" / "freigabe" / e.get("datei", "")
        if _verfallen(e, jetzt) and e["status"] == "wartet" and karte.is_file():
            try:
                import jack_mitarbeiter
                geschuetzt = jack_mitarbeiter.karte_geschuetzt(root, karte)
            except Exception:
                geschuetzt = True
            if geschuetzt:
                e["laeuft_ab_epoch"] = jetzt + e.get("frist_s", FRIST)
                geaendert.append(kennung)
                buchen(root, "frist_verlaengert", kennung=kennung, datei=e.get("datei"),
                       herkunft="aufraeumen",
                       grund="wartende Mitarbeiter-Karte (Block 28) - nicht verfallen")
                continue
        if _verfallen(e, jetzt):
            e["status"] = "verfallen"
            geaendert.append(kennung)
            buchen(root, "verfallen", kennung=kennung, datei=e.get("datei"),
                   herkunft="aufraeumen")
            continue
        # Der Vorgang ist weg: die Freigabe kann sich auf nichts mehr beziehen.
        if not (Path(root) / "auftraege" / "freigabe" / e.get("datei", "")).is_file():
            e["status"] = "gegenstandslos"
            geaendert.append(kennung)
            buchen(root, "gegenstandslos", kennung=kennung, datei=e.get("datei"),
                   herkunft="aufraeumen")
    if geaendert:
        _schreiben(root, daten)
    return geaendert


_FRISTFELDER = ("frist", "faellig", "zahlungsziel", "termin")


def _kartenkopf(root, datei):
    kopf = {}
    try:
        zeilen = (Path(root) / "auftraege" / "freigabe" / str(datei)).read_text(encoding="utf-8").splitlines()
    except OSError:
        return kopf
    if zeilen and zeilen[0].strip() == "---":
        for z in zeilen[1:60]:
            if z.strip() == "---":
                break
            k, _, w = z.partition(":")
            kopf[k.strip().lower()] = w.strip()
    return kopf


def _naechster_montag(iso, jetzt=None):
    """F-56: Kopffeld `wiederholung: woechentlich_montag` - solange die Karte offen ist, ist die Frist der naechste Montag ab heute
    (erste Faelligkeit = das Datum im Kartenkopf). Ohne Aenderung an der Karte, ohne Zeitgeber."""
    import datetime as _dt
    jetzt = jetzt or _dt.datetime.now()
    f = _dt.datetime.fromisoformat(iso)
    if f >= jetzt:
        return iso
    tage = (7 - jetzt.weekday()) % 7
    naechster = (jetzt + _dt.timedelta(days=tage)).replace(hour=f.hour, minute=f.minute, second=0, microsecond=0)
    if naechster < jetzt:
        naechster += _dt.timedelta(days=7)
    return naechster.strftime("%Y-%m-%dT%H:%M:00")


def _frist_iso(kopf, jetzt=None):
    """F-55: echte Frist der Sache (Faelligkeit, Zahlungsziel, Termin) als ISO-Text, sonst None - nie die Kennungsdauer."""
    iso = _frist_roh(kopf)
    if iso and str(kopf.get("wiederholung") or "").strip().lower() == "woechentlich_montag":
        return _naechster_montag(iso, jetzt)
    return iso


def _frist_roh(kopf):
    for feld in _FRISTFELDER:
        w = str(kopf.get(feld) or "").strip()
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?", w)
        if m:
            j, mo, t, h, mi = m.groups()
            return "%s-%s-%sT%s:%s:00" % (j, mo, t, h or "23", mi or "59")
        m = re.match(r"(\d{1,2})\.(\d{1,2})\.(\d{4})(?:\s+(\d{1,2}):(\d{2}))?", w)
        if m:
            t, mo, j, h, mi = m.groups()
            return "%s-%02d-%02dT%02d:%s:00" % (j, int(mo), int(t), int(h or 23), mi or "59")
    return None


def _warte_bis_dt(kopf, jetzt=None):
    """F-66: warte_bis (YYYY-MM-DD HH:MM, aus dem Klick 'Warten') als datetime, sonst None."""
    import datetime as _dt
    w = str(kopf.get("warte_bis") or "").strip()
    if not w:
        return None
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})", w)
    if not m:
        return None
    try:
        return _dt.datetime(*(int(g) for g in m.groups()))
    except ValueError:
        return None


def offene(root, inkl_wiedervorlage=False):
    """Was wartet auf den Patron - fuer die Maske.

    F-55 (25.09.2026): `kennung_laeuft_ab_in_s` ist nur die technische Lebensdauer der Freigabe-Kennung (wird stuendlich
    erneuert, sagt nichts ueber Dringlichkeit). `frist` ist die echte Frist der Sache (ISO oder None), `thema` der Vorgang
    der Karte (Vorgang, sonst Art, sonst "allgemein"), `marke` die Marke."""
    aufraeumen(root)
    daten = _lesen(root)
    jetzt = time.time()
    raus = []
    jetzt_dt = None
    for e in daten.values():
        if e["status"] not in ("wartet", "erteilt"):
            continue
        kopf = _kartenkopf(root, e["datei"])
        # F-66: eine Karte mit "Warten bis <Datum>" bleibt bis dahin aus der Liste - sie zaehlt trotzdem als offen
        # (Kennung/Buch unveraendert), nur diese Ausgabe blendet sie aus, solange kein inkl_wiedervorlage verlangt ist.
        wbis = _warte_bis_dt(kopf)
        faellig = wbis is not None and wbis <= (jetzt_dt or __import__("datetime").datetime.now())
        if wbis is not None and not faellig and not inkl_wiedervorlage:
            continue
        raus.append({"kennung": e["kennung"], "datei": e["datei"], "status": e["status"],
                     "angefordert": e["angefordert"], "grund": e.get("grund", ""),
                     "kennung_laeuft_ab_in_s": max(0, round(e["laeuft_ab_epoch"] - jetzt)),
                     "frist": _frist_iso(kopf),
                     "thema": kopf.get("vorgang") or kopf.get("art") or "allgemein",
                     "marke": kopf.get("marke") or "",
                     "warte_bis": wbis.strftime("%Y-%m-%d %H:%M") if wbis else None,
                     "wiedervorlage_faellig": faellig if wbis else False})
    return sorted(raus, key=lambda x: x["angefordert"])


def ist_sicherung(name):
    """F-33: Sicherungskopien (`.bak`, `.vor_...`) sind nie Karten, auch wenn sie auf `.md` enden."""
    return re.search(r"\.(bak|vor_[^.]*)(\.|$)", str(name), re.I) is not None


def anfragen_anlegen(root):
    """Fuer jeden wartenden Vorgang in auftraege/freigabe/ eine Anfrage anlegen."""
    ordner = Path(root) / "auftraege" / "freigabe"
    neu = []
    if not ordner.is_dir():
        return neu
    for f in sorted(ordner.glob("*.md")):
        if f.is_symlink() or f.name.lower().startswith("readme") or ist_sicherung(f.name):
            continue
        kennung, art = anfordern(root, f.name)
        if art == "neu":
            neu.append((f.name, kennung))
    return neu


# ═══ F-78 (29.09.2026): EINE zentrale Schreibstelle fuer Freigabekarten ════════════════════════════
# Wurzel-Fix zu F-77: F-77 baute Anzeige + Pflichtfelder, aber jeder Erzeuger schrieb seine Karte
# weiterhin von Hand - deshalb entstanden seit dem 28.09. Karten im Altformat oder mit "unbekannt"
# statt echten Werten. Ab jetzt schreibt JEDER Erzeuger nur noch ueber karte_schreiben() - sie
# verweigert das Schreiben, wenn ein Pflichtfeld leer oder woertlich "unbekannt" ist, und legt statt
# der kaputten Karte eine Fehlerkarte in abnahme/pm_eingang/ an. Der Patron sieht dann nie eine
# unvollstaendige Karte, PM sieht sofort, welcher Kanal nachbessern muss.
V2_PFLICHTFELDER = ["projekt", "marke", "eingegangen", "von", "an", "art", "betreff", "kern", "frage",
                    "empfehlung", "frist", "dringlichkeit", "ablauf"]

# Reine Betriebsfelder (Freigabemechanik) - jeder Erzeuger darf sie ueberschreiben, aber sie werden
# NICHT auf "leer/unbekannt" geprueft, weil sie technische Standardwerte mit fester Bedeutung sind.
_BETRIEBSFELDER_STANDARD = {
    "status": "freigabe", "freigabe": "nein", "gefahr": "aussen", "tiefe": "klein",
    "besetzung": "1", "versuch": "0", "warte_bis": "", "bereiche": "postfach",
}


class UnvollstaendigeKarte(ValueError):
    """Ein Erzeuger hat versucht, eine Karte mit leerem oder woertlich 'unbekannt' gefuelltem
    Pflichtfeld zu schreiben. karte_schreiben() faengt das ab (kein Absturz), aber ein Erzeuger,
    der die Fehlerkarte selbst auswerten will, kann diese Klasse fangen."""


def feld_ungueltig(wert):
    w = str(wert if wert is not None else "").strip()
    # F-78: "—"/"-"/"n/a" sind in Tabellenzeilen ein legitimes "kein Wert", aber in einem PFLICHTFELD
    # des Kartenkopfs genau der Platzhalter, den diese Pruefung fangen soll (Fund: jack_termine.py
    # schrieb "an: —" statt eines echten Empfaengers).
    return not w or w.lower() in ("unbekannt", "—", "-", "–", "n/a", "keine angabe")


# Rueckwaertskompatibler Name (F-78 hat die Pruefung zuerst als "privat" angelegt).
_feld_ungueltig = feld_ungueltig


# ═══ F-100 A: feste Freigabe-Nummer (FR-0001, fortlaufend, nie wiederverwendet) ══════════════════════
ZAEHLER = "freigabe_zaehler.json"


def naechste_nummer(root):
    """Atomar hochzaehlen (Sperre auf der Zaehlerdatei); -> 'FR-0001'. Die Nummer wird nie zurueckgesetzt."""
    import fcntl
    pfad = Path(betrieb.area(root)) / ZAEHLER
    pfad.parent.mkdir(parents=True, exist_ok=True)
    with pfad.open("a+", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        try:
            n = int(json.loads(f.read() or "{}").get("letzte", 0))
        except (ValueError, TypeError):
            n = 0
        n += 1
        f.seek(0); f.truncate()
        f.write(json.dumps({"letzte": n, "format": "FR-%04d"}))
        f.flush(); os.fsync(f.fileno())
    return "FR-%04d" % n


def _kopfnummer(text):
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    if not m:
        return ""
    for z in m.group(1).splitlines():
        k, _, w = z.partition(":")
        if k.strip().lower() == "nummer":
            return w.strip()
    return ""


def _kopf_wert(text, feld):
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    if not m:
        return ""
    for z in m.group(1).splitlines():
        k, _, w = z.partition(":")
        if k.strip().lower() == feld:
            return w.strip()
    return ""


def _bekannte_nummer(root, datei, text):
    """Hat dieser Vorgang schon eine Nummer? Suche: Sicherungen derselben Datei (.vor_*), dann Karten mit gleichem `auftrag:` (offen, ersetzt, erledigt)."""
    for sich in sorted(datei.parent.glob(datei.name + ".vor_*")):
        try:
            n = _kopfnummer(sich.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if n:
            return n
    auftrag = _kopf_wert(text, "auftrag")
    if not auftrag:
        return ""
    basis = Path(root) / "auftraege" / "freigabe"
    for ordner in (basis, basis / "ersetzt", basis / "erledigt", Path(root) / "auftraege" / "erledigt"):
        if not ordner.is_dir():
            continue
        for f in ordner.glob("*"):
            if f == datei or not f.is_file() or f.suffix not in (".md",) and ".vor_" not in f.name:
                continue
            try:
                t = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if _kopf_wert(t, "auftrag") == auftrag and _kopfnummer(t):
                return _kopfnummer(t)
    return ""


def nachnummerieren(root, sicherung="vor_F100"):
    """Gibt jeder offenen Karte ohne Nummer (auftraege/freigabe/*.md) eine, aelteste zuerst. Sicherung <datei>.<sicherung>.
    Aendert nur den Kopf (die Pruefsumme laeuft ueber den Rumpf). -> Liste (datei, nummer)."""
    import jack_oberflaeche as O
    ordner = Path(root) / "auftraege" / "freigabe"
    neu = []
    kandidaten = []
    for f in sorted(ordner.glob("*.md"), key=lambda x: (x.stat().st_mtime, x.name)):
        if f.is_symlink() or f.name.startswith("_") or f.name.lower().startswith("readme") or re.search(r"\.(bak|vor_[^.]*)(\.|$)", f.name, re.I):
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        if text.startswith("---") and not _kopfnummer(text):
            kandidaten.append((f, text))
    for f, text in kandidaten:
        nr = _bekannte_nummer(root, f, text) or naechste_nummer(root)      # Nachtrag PM 7: die Nummer haengt am Vorgang (auftrag:), nicht am Dateiinhalt
        sich = f.with_name(f.name + "." + sicherung)
        if not sich.exists():
            sich.write_text(text, encoding="utf-8")
        f.write_text(O._kopf_setzen(text, "nummer", nr), encoding="utf-8")
        neu.append((f.name, nr))
    return neu


def karte_per_nummer(root, eingabe):
    """'Freigabe 123', 'FR-0123', '123' -> Pfad der Karte (offen, sonst ersetzt/erledigt) oder None."""
    m = re.search(r"(\d{1,6})\s*$", str(eingabe or "").strip())
    if not m:
        return None
    ziel = "FR-%04d" % int(m.group(1))
    for unter in ("", "ersetzt", "erledigt", "abgelehnt"):
        ordner = Path(root) / "auftraege" / "freigabe" / unter if unter else Path(root) / "auftraege" / "freigabe"
        if not ordner.is_dir():
            continue
        for f in sorted(ordner.glob("*.md")):
            try:
                if _kopfnummer(f.read_text(encoding="utf-8", errors="replace")) == ziel:
                    return f
            except OSError:
                continue
    return None


# NACHT KERN 4 (PM 30.09. 23:57, Antwort 1): Karten, die nur den Patron betreffen, bekommen `an: Patron` als Vorgabe, wenn `an` leer oder ein
# Platzhalter ist. Nicht fuer Mails (externemail, mailantwort, mitarbeitermail, mailentwurf): dort ist `an` der Empfaenger und muss echt sein.
AN_PATRON_ARTEN = ("entscheidung", "anleitung", "zurkenntnis", "erinnerung", "uebersicht", "social_tagesliste", "netzwaechter")


def an_vorgabe(kopf):
    """-> Kopie des Kopfes mit `an: Patron`, falls `an` fehlt/Platzhalter ist und die Kartenart nur den Patron betrifft; sonst unveraendert."""
    k = dict(kopf)
    if feld_ungueltig(k.get("an")) and str(k.get("art") or "").strip().lower() in AN_PATRON_ARTEN:
        k["an"] = "Patron"
    return k


def v2_kopfzeilen(felder):
    """NACHT KERN 4 (PM-Nachtrag 00:12): Erzeuger automatischer Karten (Postfach-Mails, Funktions-Disziplin) schreiben den Kartenkopf v2 gleich vollstaendig.
    `felder` = dict mit allen V2_PFLICHTFELDERN (echte Werte, `an` bei reinen Patron-Karten notfalls per Vorgabe) -> Liste der Kopfzeilen in fester Reihenfolge.
    ValueError, wenn ein Feld fehlt oder ein Platzhalter ist - ein Erzeuger darf so nie wieder eine unvollstaendige Karte schreiben."""
    k = an_vorgabe(felder)
    fehlt = [f for f in V2_PFLICHTFELDER if feld_ungueltig(k.get(f))]
    if fehlt:
        raise ValueError("Kartenkopf v2 unvollstaendig: " + ", ".join(fehlt))
    return [_kopfzeile(f, " ".join(str(k[f]).split())) for f in V2_PFLICHTFELDER]


def kopf_vollstaendig(kopf):
    """True, wenn ALLE V2_PFLICHTFELDER als Schluessel vorhanden UND mit einem echten Wert gefuellt
    sind (kein leerer String, kein 'unbekannt'/'—'). F-78: das ist strenger als die reine F-77-
    Pruefung "Schluessel vorhanden" - eine Karte mit `an: —` galt dort faelschlich als vollstaendig."""
    return all(f in kopf and not feld_ungueltig(kopf.get(f)) for f in V2_PFLICHTFELDER)


def _kopfzeile(schluessel, wert):
    return "%-15s %s" % (schluessel + ":", str(wert if wert is not None else ""))


def karte_schreiben(root, kopf, rumpf, dateiname=None, herkunft="", unterordner=None):
    """DER EINE Weg, auf dem eine Freigabekarte (auftraege/freigabe/*.md) entsteht (F-78).

    `kopf` ist ein dict mit MINDESTENS allen `V2_PFLICHTFELDER` echt gefuellt (kein leerer String,
    kein woertliches "unbekannt", Groß-/Kleinschreibung egal). Fehlt eines, wird NICHTS in
    auftraege/freigabe/ geschrieben - stattdessen eine Fehlerkarte in abnahme/pm_eingang/, die
    `herkunft` (welcher Erzeuger/Kanal) und die fehlenden Felder wortgleich benennt.

    `rumpf` ist der Text unterhalb des Kopfes (Markdown, ohne "---").
    `dateiname` ist optional - fehlt er, wird er aus Zeit+Betreff gebildet (wie bisher ueberall).
    `unterordner` erlaubt z.B. dateiname-Kollisionsvermeidung fuer besondere Faelle - normalerweise
    None (dann landet die Karte direkt in auftraege/freigabe/).

    -> Path der geschriebenen Karte, oder None (dann: keine Karte, Grund in der Fehlerkarte)."""
    kopf = an_vorgabe(kopf)
    fehlende = [f for f in V2_PFLICHTFELDER if _feld_ungueltig(kopf.get(f))]
    if fehlende:
        _fehlerkarte_schreiben(root, kopf, rumpf, fehlende, herkunft)
        buchen(root, "karte_verweigert", herkunft=str(herkunft)[:80], fehlende_felder=fehlende)
        return None
    ziel = Path(root) / "auftraege" / "freigabe"
    if unterordner:
        ziel = ziel / unterordner
    ziel.mkdir(parents=True, exist_ok=True)
    if not dateiname:
        jetzt = betrieb.now()
        kurz = re.sub(r"[^a-zA-Z0-9]+", "_", str(kopf.get("betreff") or kopf.get("art") or "vorgang"))[:40].strip("_")
        dateiname = "%s_%s.md" % (jetzt.strftime("%Y-%m-%d_%H%M%S"), kurz or "vorgang")
    pfad = ziel / dateiname
    nr = 2
    while pfad.exists():
        pfad = ziel / (re.sub(r"\.md$", "", dateiname) + "-%d.md" % nr)
        nr += 1
    voll = dict(_BETRIEBSFELDER_STANDARD)
    voll.update(kopf)
    if not str(voll.get("nummer") or "").strip():
        # F-100 A: feste, nie neu vergebene Nummer; Neufassung desselben Vorgangs (gleicher auftrag:) behaelt sie (Nachtrag PM 7)
        bekannt = ""
        if voll.get("auftrag"):
            probe = "---\nauftrag: %s\n---\n" % voll["auftrag"]
            bekannt = _bekannte_nummer(root, Path(root) / "auftraege" / "freigabe" / "_neu.md", probe)
        voll["nummer"] = bekannt or naechste_nummer(root)
    geschrieben = set()
    zeilen = ["---"]
    for f in V2_PFLICHTFELDER:                 # feste Reihenfolge zuerst - die Maske liest darauf.
        zeilen.append(_kopfzeile(f, voll[f]))
        geschrieben.add(f)
    for k, v in voll.items():                  # danach alles Weitere (Betriebsfelder, Erzeuger-eigene).
        if k not in geschrieben:
            zeilen.append(_kopfzeile(k, v))
    zeilen += ["---", "", str(rumpf or "").rstrip(), ""]
    pfad.write_text("\n".join(zeilen), encoding="utf-8")
    buchen(root, "karte_geschrieben", datei=pfad.name, herkunft=str(herkunft)[:80], kartenart=voll.get("art", ""))
    return pfad


def _fehlerkarte_schreiben(root, kopf, rumpf, fehlende, herkunft):
    """F-78: statt einer kaputten Karte beim Patron - eine Fehlerkarte an PM, die genau benennt,
    welcher Erzeuger welches Feld vergessen hat. Landet NIE in auftraege/freigabe/."""
    ziel = Path(root) / "abnahme" / "pm_eingang"
    ziel.mkdir(parents=True, exist_ok=True)
    jetzt = betrieb.now()
    kurz = re.sub(r"[^a-zA-Z0-9]+", "_", str(herkunft or kopf.get("art") or "erzeuger"))[:40].strip("_")
    pfad = ziel / ("%s_KARTE_UNVOLLSTAENDIG_%s.md" % (jetzt.strftime("%Y-%m-%d_%H%M%S"), kurz or "erzeuger"))
    nr = 2
    while pfad.exists():
        pfad = ziel / (re.sub(r"\.md$", "", pfad.name) + "-%d.md" % nr)
        nr += 1
    pfad.write_text("\n".join([
        "# Karte nicht geschrieben — Pflichtfeld fehlt oder ist \"unbekannt\" (F-78)",
        "",
        "**Erzeuger/Kanal:** %s" % (herkunft or "nicht angegeben"),
        "**Fehlende/ungültige Felder:** %s" % ", ".join(fehlende),
        "**Vorgesehene Art:** %s  ·  **Betreff:** %s" % (kopf.get("art", ""), kopf.get("betreff", "")),
        "",
        "## Übergebener Kopf (zur Fehlersuche, roh)",
        "```",
        "\n".join("%s: %s" % (k, v) for k, v in kopf.items()),
        "```",
        "",
        "## Übergebener Rumpf (zur Fehlersuche, roh, gekürzt)",
        "```",
        str(rumpf or "")[:1500],
        "```",
        "",
        "Diese Karte ist KEINE Freigabekarte — sie liegt bewusst in abnahme/pm_eingang/, nicht in "
        "auftraege/freigabe/. PM/Kanal muss den Erzeuger nachbessern, damit das fehlende Feld einen "
        "echten Wert bekommt (F-78, kein Platzhalter, kein woertliches \"unbekannt\").",
    ]), encoding="utf-8")
    return pfad


if __name__ == "__main__":
    import sys
    root = Path(__file__).resolve().parent
    was = sys.argv[1] if len(sys.argv) > 1 else "offene"
    if was == "anlegen":
        print(json.dumps(anfragen_anlegen(root), ensure_ascii=False, indent=1))
    elif was == "offene":
        print(json.dumps(offene(root), ensure_ascii=False, indent=1))
    elif was == "erteilen":
        # Block 27: Die Befehlszeile ist kein Beweis fuer den Patron.
        print(erteilen(root, sys.argv[2],
                       von="Befehlszeile (keine Patron-Bestaetigung): "
                           + (sys.argv[3] if len(sys.argv) > 3 else "ohne Angabe"),
                       herkunft="befehlszeile"))
    elif was == "pruefen":
        print(pruefen(root, sys.argv[2], sys.argv[3]))
    elif was == "verbrauchen":
        print(verbrauchen(root, sys.argv[2], sys.argv[3]))
    else:
        print("anlegen | offene | erteilen <kennung> | pruefen <kennung> <datei> | verbrauchen <kennung> <datei>")


# ---------------------------------------------------------------- F-108: Zugangskarten (Code-Mails)
ZUGANG_LEBENSDAUER_MIN = 30
_ZUGANG_SCHWARZ = "••••••"


def _zugang_schwaerzen(text):
    """Code und Mail-Volltext aus einer Zugangskarte entfernen (Karte verfallen/erledigt)."""
    m = re.search(r"(?m)^zugang_code:\s*(.+?)\s*$", text)
    code = (m.group(1).strip() if m else "")
    if len(code) >= 3:
        text = text.replace(code, _ZUGANG_SCHWARZ)
    text = re.sub(r"(?s)(## Volltext der Mail\n).*$", r"\1(entfernt, Code-Karte abgelaufen)\n", text)
    return text


def zugangskarten_aufraeumen(root, jetzt=None):
    """Zugangskarten (`zugang: ja`) verfallen nach 30 Min: Code wird geschwaerzt, Karte -> freigabe/ersetzt/.
    Erledigte Zugangskarten (VERWENDET/NEU ANFORDERN) werden nach 30 Min ebenfalls geschwaerzt. Gibt die Zahl verschobener Karten zurueck."""
    import datetime as _dt
    basis = Path(root) / "auftraege" / "freigabe"
    jetzt = jetzt or betrieb.now()
    n = 0
    for f in sorted(basis.glob("*_ZUGANG_*.md")):
        try:
            text = f.read_text(encoding="utf-8")
            m = re.search(r"(?m)^verfaellt:\s*(\S+)", text)
            if not re.search(r"(?m)^zugang:\s*ja\s*$", text) or not m:
                continue
            frist = _dt.datetime.fromisoformat(m.group(1))
            if frist.tzinfo is None:
                frist = frist.replace(tzinfo=jetzt.tzinfo)
            if jetzt < frist:
                continue
            neu = _zugang_schwaerzen(text)
            ziel = basis / "ersetzt"
            ziel.mkdir(parents=True, exist_ok=True)
            zf = ziel / f.name
            zf.write_text(neu, encoding="utf-8")
            f.unlink()
            buchen(root, "zugangskarte_verfallen", datei=f.name)
            n += 1
        except Exception:
            continue
    ordner = Path(root) / "auftraege" / "erledigt"
    try:
        for f in ordner.glob("*_ZUGANG_*.md"):
            if time.time() - f.stat().st_mtime < ZUGANG_LEBENSDAUER_MIN * 60:
                continue
            text = f.read_text(encoding="utf-8")
            if "zugang_code:" in text and _ZUGANG_SCHWARZ not in text:
                f.write_text(_zugang_schwaerzen(text), encoding="utf-8")
    except Exception:
        pass
    return n
