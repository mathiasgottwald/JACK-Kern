#!/usr/bin/env python3
"""Vorgangsbuch und Vorgangskennungen (Paket 3 "Durchfuehrung und Wiederaufnahme", F-9, 24.09.2026).

Zwei Teile, beide nur vom Dienst/Planer geschrieben (der Arbeiter darf betrieb/ ausser entwuerfe/ nie
schreiben, Pfadwaechter arbeiter.sh):

1. AUSSENVORGAENGE (betrieb/aussenvorgaenge.jsonl, nur anhaengen, fsync):
   Jede Aussenaktion (Runway, Higgsfield, Mail, kuenftige Veroeffentlichung, Attrappe) bekommt VOR dem
   Aufruf eine Vorgangskennung vg_<sha256(kanal|bezug|schritt|inhalts-hash)[:24]> und einen Eintrag
   `absicht`. Erst danach geht der Aufruf raus. Die Antwort wird der Kennung zugeordnet (`angekommen`,
   `abgewiesen` = belegter Nicht-Erfolg, `unklar`). Eine `absicht` ohne Ergebnis heisst: die Antwort ist
   ausgeblieben (Absturz, Zeitueberschreitung). Dann ist JEDER weitere Aufruf desselben Kanals fuer
   denselben Bezug gesperrt, bis eine Zustandspruefung beim Anbieter (`pruefen`) oder der Patron
   (`klaeren`) den Zustand belegt hat. Wiederholregel (Vorlage M6):
     angekommen        -> nie wiederholen, Ergebnis uebernehmen
     nicht_angekommen  -> hoechstens EINE Wiederholung mit DERSELBEN Kennung und NEUER Freigabe
     nicht_pruefbar    -> Stopp, Meldung an den Patron, nie automatisch
   Versand und Veroeffentlichung haben nie einen automatischen Wiederholweg.

2. VORGANGSBUCH je Auftrag (betrieb/vorgaenge/<sha256(Auftrag)>.json): Plan (Fachkraft -> CEO -> Tor 1
   -> Tor 2 -> Nachbearbeitung -> Freigabe-Tor), Zwischenergebnisse mit SHA-256, strukturierter Wartegrund
   und naechster ausfuehrbarer Schritt. Der Stand wird ABGELEITET (Werkzeugprotokoll, Vertrag,
   Fortsetzungsbeleg, Tor-2-Zettel, Abschlussquittung) - nie vom Lauf selbst erklaert.

Kein Modell, kein Netz in diesem Modul selbst. Anbieterabfragen laufen ueber die Adapter.
"""
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import time
from pathlib import Path

import jack_betrieb as betrieb

JOURNAL = "aussenvorgaenge.jsonl"
BUCHORDNER = "vorgaenge"
KANAELE = ("runway", "higgsfield", "mail", "veroeffentlichung", "attrappe", "attrappe_versand")
# Versand und Veroeffentlichung: nie automatisch wiederholen, auch nicht nach belegtem Nicht-Erfolg
# ohne ausdrueckliche neue Freigabe des Patrons.
VERSANDKANAELE = ("mail", "veroeffentlichung", "attrappe_versand")
WIEDERHOLUNG_MAX = 1
# Zeitbudget je Anbieter (Sekunden) fuer die Zustandspruefung im Takt; betriebsgrenzen.json
# "vorgang_zeitbudget_s" ueberschreibt. Danach: nicht_pruefbar -> Patron.
ZEITBUDGET_STANDARD = {"runway": 900, "higgsfield": 900, "mail": 600, "veroeffentlichung": 900,
                       "attrappe": 30, "attrappe_versand": 30}
PRUEFTAKT_STANDARD_S = 60
# Eine absicht ohne Ergebnis gilt als "laeuft", solange der aufrufende Prozess lebt und die
# Antwortfrist nicht verstrichen ist; danach als unklar.
ANTWORTFRIST_S = 120
ZUSTAENDE = ("absicht", "angekommen", "nicht_angekommen", "unklar", "nicht_pruefbar")


class VorgangGesperrt(ValueError):
    """Ein Aufruf wuerde eine doppelte Aussenaktion riskieren und wird NICHT ausgefuehrt."""


class AnbieterAbgewiesen(ValueError):
    """Der Anbieter hat geantwortet und den Aufruf NICHT angenommen (belegter Nicht-Erfolg)."""


# ------------------------------------------------------------------ Kennung
def inhalt_hash(inhalt) -> str:
    if isinstance(inhalt, bytes):
        roh = inhalt
    elif isinstance(inhalt, str):
        roh = inhalt.encode("utf-8")
    else:
        roh = json.dumps(inhalt, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(roh).hexdigest()


def kennung(kanal, bezug, schritt, inhalts_hash) -> str:
    """vg_<sha256(kanal|bezug|schritt|inhalts-hash)[:24]> (Vorlage M4). Gleicher Inhalt = gleiche Kennung."""
    if kanal not in KANAELE:
        raise ValueError("Unbekannter Kanal: " + str(kanal)[:40])
    for teil in (bezug, schritt, inhalts_hash):
        if not isinstance(teil, str) or not teil or "|" in teil or len(teil) > 300:
            raise ValueError("Vorgangskennung braucht Bezug, Schritt und Inhalts-Hash ohne '|'")
    return "vg_" + hashlib.sha256("|".join((kanal, bezug, schritt, inhalts_hash)).encode()).hexdigest()[:24]


# ------------------------------------------------------------------ Journal
def _journalpfad(root) -> Path:
    return betrieb.area(root) / JOURNAL


@contextlib.contextmanager
def _sperre(root):
    pfad = betrieb.area(root) / "aussenvorgaenge.sperre"
    with pfad.open("a+") as datei:
        fcntl.flock(datei, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(datei, fcntl.LOCK_UN)


def _jetzt():
    return betrieb.now().isoformat()


def _anhaengen(root, eintrag):
    p = _journalpfad(root)
    fd = os.open(p, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(json.dumps(eintrag, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    return eintrag


def ereignisse(root):
    p = _journalpfad(root)
    if not p.is_file():
        return []
    raus = []
    with p.open(encoding="utf-8") as f:
        for zeile in f:
            try:
                e = json.loads(zeile)
            except ValueError:
                continue
            if isinstance(e, dict) and str(e.get("vg", "")).startswith("vg_"):
                raus.append(e)
    return raus


def _pid_lebt(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _alter_s(zeit):
    try:
        z = dt.datetime.fromisoformat(str(zeit))
        if z.tzinfo is None:
            z = z.replace(tzinfo=betrieb.ZONE)
        return (betrieb.now() - z).total_seconds()
    except (TypeError, ValueError):
        return 1e9


def stand(root, jetzt_pid_pruefen=True):
    """{vg: Datensatz} - abgeleitet aus dem Journal, nie gespeichert."""
    vorgaenge = {}
    for e in ereignisse(root):
        vg = e["vg"]
        v = vorgaenge.setdefault(vg, {"vg": vg, "kanal": e.get("kanal"), "bezug": e.get("bezug"),
                                      "schritt": e.get("schritt"), "auftrag": e.get("auftrag"),
                                      "inhalts_hash": e.get("inhalts_hash"), "versuche": 0,
                                      "zustand": None, "anbieter_kennung": None, "freigaben": [],
                                      "pruefungen": 0, "verlauf": []})
        art = e.get("ereignis")
        v["verlauf"].append({"zeit": e.get("zeit"), "ereignis": art,
                             "text": str(e.get("grund") or e.get("ergebnis") or "")[:160]})
        v["verlauf"] = v["verlauf"][-12:]
        if art == "absicht":
            v["versuche"] += 1
            v.update(zustand="absicht", absicht_zeit=e.get("zeit"), pid=e.get("pid"),
                     freigabe=e.get("freigabe"), wiederholung_frei=False)
            if e.get("freigabe"):
                v["freigaben"].append(e.get("freigabe"))
            for k in ("kanal", "bezug", "schritt", "auftrag", "inhalts_hash"):
                v[k] = e.get(k, v.get(k))
            if e.get("message_id"):
                v["bezug_message_id"] = e["message_id"]
        elif art == "angekommen":
            v.update(zustand="angekommen", anbieter_kennung=e.get("anbieter_kennung"), ergebnis_zeit=e.get("zeit"))
        elif art == "abgewiesen":
            v.update(zustand="nicht_angekommen", beleg=e.get("grund"), ergebnis_zeit=e.get("zeit"))
        elif art == "unklar":
            v.update(zustand="unklar", grund=e.get("grund"))
        elif art == "pruefung":
            v["pruefungen"] += 1
            v["letzte_pruefung"] = e.get("zeit")
            erg = e.get("ergebnis")
            if erg == "angekommen":
                v.update(zustand="angekommen", anbieter_kennung=e.get("anbieter_kennung") or v.get("anbieter_kennung"))
            elif erg == "nicht_angekommen":
                v.update(zustand="nicht_angekommen", beleg=e.get("beleg"))
            elif erg == "nicht_pruefbar":
                v.update(zustand="nicht_pruefbar", grund=e.get("beleg"))
            elif erg == "laeuft" and v.get("zustand") in ("absicht", "unklar"):
                v["zustand"] = "unklar"
        elif art == "geklaert":
            erg = e.get("ergebnis")
            if erg in ("angekommen", "nicht_angekommen"):
                v.update(zustand=erg, beleg=e.get("beleg"), geklaert_von=e.get("von"),
                         anbieter_kennung=e.get("anbieter_kennung") or v.get("anbieter_kennung"))
        elif art == "wiederholung_frei":
            v["wiederholung_frei"] = True
            v["wiederholung_freigabe"] = e.get("freigabe")
        elif art == "sichtkontrolle":
            # F-15 (Paket 5): Nachweis nach der Veroeffentlichung (Sichtbarkeit, Erreichbarkeit, Hash, Zeit).
            v["sichtkontrolle"] = {k: e.get(k) for k in ("zeit", "sichtbarkeit", "erreichbar", "link", "video_id",
                                                         "medium_sha256", "beleg")}
    for v in vorgaenge.values():
        if v["zustand"] == "absicht":
            lebt = _pid_lebt(v.get("pid")) if jetzt_pid_pruefen else True
            if not lebt or _alter_s(v.get("absicht_zeit")) > ANTWORTFRIST_S:
                v["zustand"] = "unklar"
                v.setdefault("grund", "Antwort ausgeblieben (Aufrufer beendet oder Antwortfrist verstrichen)")
            else:
                v["laeuft"] = True
    return vorgaenge


def zustand(root, vg):
    return (stand(root).get(vg) or {}).get("zustand")


def offene(root, auftrag=None, kanal=None, bezug=None):
    """Vorgaenge ohne belegten Endzustand (absicht/unklar/nicht_pruefbar) - sie sperren weitere Aufrufe."""
    raus = []
    for v in stand(root).values():
        if v["zustand"] not in ("absicht", "unklar", "nicht_pruefbar"):
            continue
        if auftrag and v.get("auftrag") != auftrag:
            continue
        if kanal and v.get("kanal") != kanal:
            continue
        if bezug and v.get("bezug") != bezug:
            continue
        raus.append(v)
    return raus


# ------------------------------------------------------------------ Schreiben-vor-Aufruf
def beginnen(root, kanal, bezug, schritt, inhalt, auftrag=None, freigabe=None, pid=None, message_id=None):
    """Schreibt `absicht` BEVOR der Aufruf rausgeht und liefert die Vorgangskennung.

    Wirft VorgangGesperrt, wenn (a) fuer denselben Kanal und Bezug ein Vorgang ohne belegten Endzustand
    offen ist (Antwort ausgeblieben -> erst Zustandspruefung), (b) derselbe Vorgang schon angekommen ist,
    (c) derselbe Vorgang belegt nicht angekommen ist, aber keine NEUE Freigabe vorliegt oder die eine
    Wiederholung verbraucht ist. Nichts wird aufgerufen, solange diese Funktion nicht zurueckkehrt."""
    ih = inhalt if (isinstance(inhalt, str) and re.fullmatch(r"[0-9a-f]{64}", inhalt)) else inhalt_hash(inhalt)
    vg = kennung(kanal, bezug, schritt, ih)
    auftrag = auftrag if auftrag is not None else (os.environ.get("JACK_AUFTRAG_DATEI") or None)
    with _sperre(root):
        alle = stand(root)
        for v in alle.values():
            if v["vg"] == vg or v.get("kanal") != kanal or v.get("bezug") != bezug:
                continue
            if v["zustand"] in ("absicht", "unklar", "nicht_pruefbar"):
                raise VorgangGesperrt(
                    "Vorgang %s (%s, %s) ist %s: die Antwort des Anbieters ist nicht belegt. Kein weiterer "
                    "Aufruf, bis eine Zustandspruefung oder der Patron den Zustand geklaert hat."
                    % (v["vg"], kanal, bezug, v["zustand"]))
        alt = alle.get(vg)
        wiederholung = 0
        if alt:
            if alt["zustand"] == "angekommen":
                raise VorgangGesperrt("Vorgang %s ist bereits angekommen (Anbieterkennung %s); kein zweiter "
                                      "Aufruf, Ergebnis uebernehmen." % (vg, alt.get("anbieter_kennung") or "?"))
            if alt["zustand"] in ("absicht", "unklar", "nicht_pruefbar"):
                raise VorgangGesperrt("Vorgang %s ist %s: erst Zustandspruefung, nie blind wiederholen."
                                      % (vg, alt["zustand"]))
            # nicht_angekommen (belegt): hoechstens eine Wiederholung, nur mit neuer Freigabe
            wiederholung = alt["versuche"]
            if wiederholung > WIEDERHOLUNG_MAX:
                raise VorgangGesperrt("Vorgang %s: die eine erlaubte Wiederholung ist verbraucht." % vg)
            if not freigabe or freigabe in alt["freigaben"]:
                raise VorgangGesperrt("Vorgang %s ist belegt nicht angekommen; eine Wiederholung braucht eine "
                                      "NEUE Freigabe (Einmal-Ticket)." % vg)
            if kanal in VERSANDKANAELE and not alt.get("wiederholung_frei"):
                raise VorgangGesperrt("Versand/Veroeffentlichung %s wird nie automatisch wiederholt; der Patron "
                                      "muss die Wiederholung ausdruecklich freigeben (wiederholung_freigeben)." % vg)
        _anhaengen(root, {"zeit": _jetzt(), "ereignis": "absicht", "vg": vg, "kanal": kanal, "bezug": bezug,
                          "schritt": schritt, "inhalts_hash": ih, "auftrag": auftrag,
                          "freigabe": (str(freigabe)[:200] if freigabe else None),
                          "wiederholung": wiederholung, "pid": pid or os.getpid(),
                          # F-11 (P06): die Message-ID steht VOR dem SMTP-Aufruf im Journal (Zustandspruefung)
                          **({"message_id": str(message_id)[:300]} if message_id else {})})
    return vg


def _ereignis(root, vg, art, **felder):
    with _sperre(root):
        if vg not in stand(root, jetzt_pid_pruefen=False):
            raise ValueError("Unbekannter Vorgang: " + str(vg)[:40])
        return _anhaengen(root, {"zeit": _jetzt(), "ereignis": art, "vg": vg, **felder})


def sichtkontrolle(root, vg, sichtbarkeit, erreichbar, link, video_id, medium_sha256, beleg):
    """F-15: Nachweis nach der Veroeffentlichung an den Vorgang haengen (nur anhaengen)."""
    return _ereignis(root, vg, "sichtkontrolle", sichtbarkeit=str(sichtbarkeit)[:20], erreichbar=bool(erreichbar),
                     link=str(link)[:300], video_id=str(video_id)[:80], medium_sha256=str(medium_sha256)[:64],
                     beleg=str(beleg)[:300])


def angekommen(root, vg, anbieter_kennung, **info):
    """Antwort des Anbieters der Kennung zuordnen."""
    return _ereignis(root, vg, "angekommen", anbieter_kennung=str(anbieter_kennung)[:200],
                     **{k: (v if isinstance(v, (int, float, bool)) or v is None else str(v)[:300])
                        for k, v in info.items()})


def abgewiesen(root, vg, grund):
    """Belegter Nicht-Erfolg: der Anbieter hat geantwortet und NICHT angenommen (z. B. HTTP 4xx)."""
    return _ereignis(root, vg, "abgewiesen", grund=str(grund)[:300])


def unklar(root, vg, grund):
    """Aufruf ohne belegte Antwort (Netzfehler, Zeitueberschreitung, 5xx)."""
    return _ereignis(root, vg, "unklar", grund=str(grund)[:300])


def klaeren(root, vg, ergebnis, beleg, von="Patron", anbieter_kennung=None):
    """Der Patron belegt den Zustand von Hand (z. B. Anbieter-Oberflaeche nachgesehen)."""
    if ergebnis not in ("angekommen", "nicht_angekommen"):
        raise ValueError("Ergebnis muss angekommen oder nicht_angekommen sein")
    if not isinstance(beleg, str) or len(beleg.strip()) < 5:
        raise ValueError("Eine Klaerung braucht einen Beleg (was wurde wo nachgesehen)")
    return _ereignis(root, vg, "geklaert", ergebnis=ergebnis, beleg=beleg.strip()[:300], von=str(von)[:80],
                     anbieter_kennung=anbieter_kennung)


def wiederholung_freigeben(root, vg, freigabe, von="Patron"):
    """Nur fuer Versand/Veroeffentlichung noetig: ausdrueckliche Freigabe EINER Wiederholung nach belegtem
    Nicht-Erfolg. Aendert nichts an der Regel 'hoechstens eine Wiederholung'."""
    v = stand(root).get(vg)
    if not v or v["zustand"] != "nicht_angekommen":
        raise ValueError("Wiederholung nur nach belegtem Nicht-Erfolg")
    return _ereignis(root, vg, "wiederholung_frei", freigabe=str(freigabe)[:200], von=str(von)[:80])


def ausfuehren(root, kanal, bezug, schritt, inhalt, aufruf, auftrag=None, freigabe=None):
    """Rahmen fuer eine Aussenaktion: absicht -> aufruf(vg) -> angekommen/abgewiesen/unklar.

    aufruf(vg) liefert die Anbieterkennung (str) oder wirft. AnbieterAbgewiesen = belegter Nicht-Erfolg;
    jede andere Ausnahme = unklar (Antwort nicht belegt). Ein Absturz zwischen Aufruf und Vermerk laesst
    die absicht offen - der naechste Versuch sieht sie und ruft NICHT erneut auf."""
    vg = beginnen(root, kanal, bezug, schritt, inhalt, auftrag=auftrag, freigabe=freigabe)
    try:
        anbieter_kennung = aufruf(vg)
    except AnbieterAbgewiesen as fehler:
        abgewiesen(root, vg, str(fehler))
        raise
    except Exception as fehler:
        unklar(root, vg, "%s: %s" % (type(fehler).__name__, str(fehler)[:200]))
        raise
    angekommen(root, vg, anbieter_kennung)
    return vg, anbieter_kennung


# ------------------------------------------------------------------ Zustandspruefung
def _grenzen(root):
    try:
        import jack_grenzen
        return jack_grenzen.lesen(root) or {}
    except Exception:
        return {}


def zeitbudget_s(root, kanal):
    werte = _grenzen(root).get("vorgang_zeitbudget_s")
    try:
        wert = int((werte or {}).get(kanal))
        if 10 <= wert <= 86400:
            return wert
    except (TypeError, ValueError, AttributeError):
        pass
    return ZEITBUDGET_STANDARD.get(kanal, 900)


def prueftakt_s(root):
    try:
        wert = int(_grenzen(root).get("vorgang_prueftakt_s"))
        if 10 <= wert <= 3600:
            return wert
    except (TypeError, ValueError):
        pass
    return PRUEFTAKT_STANDARD_S


def _pruefer_video(anbieter):
    def pruefen(root, v):
        # Geprueft 24.09.2026 (docs.dev.runwayml.com/api, docs.higgsfield.ai): Runway bietet nur
        # GET/DELETE /v1/tasks/{id}, Higgsfield nur /requests/{id}/status und /cancel. Es gibt weder eine
        # Liste noch einen Idempotenzschluessel. Ohne Anbieterkennung ist der Zustand daher nicht pruefbar.
        if not v.get("anbieter_kennung"):
            return {"ergebnis": "nicht_pruefbar",
                    "beleg": "%s bietet keine Suche ohne Anbieterkennung (nur Abfrage per Kennung, geprueft "
                             "24.09.2026); die Antwort mit der Kennung ist ausgeblieben. Patron sieht in der "
                             "Anbieter-Oberflaeche nach und klaert." % anbieter}
        import importlib
        modul = importlib.import_module("jack_runway" if anbieter == "runway" else "jack_higgsfield")
        status = modul.anbieterstatus(root, v["anbieter_kennung"])
        return {"ergebnis": "angekommen", "anbieter_kennung": v["anbieter_kennung"],
                "beleg": "Anbieterstatus %s" % status}
    return pruefen


def mail_gesendet_ordner(ordner):
    """Leser fuer eine Gesendet-Ablage (Ordner mit .eml-Dateien): liefert die Menge der Message-IDs.
    Nur lesend. Fuer den echten Postfachabgleich per IMAP ist ein eigener Leser noetig (nicht Teil von F-9)."""
    def lesen():
        ids = set()
        for p in sorted(Path(ordner).glob("*.eml")):
            try:
                kopf = p.read_text(encoding="utf-8", errors="replace").split("\n\n", 1)[0]
            except OSError:
                continue
            m = re.search(r"^Message-ID:\s*(<[^>\s]+>)", kopf, re.M | re.I)
            if m:
                ids.add(m.group(1))
        return ids
    return lesen


def pruefer_mail(leser):
    def pruefen(root, v):
        message_id = v.get("anbieter_kennung") or v.get("bezug_message_id") or _message_id_aus(v)
        if not message_id:
            return {"ergebnis": "nicht_pruefbar", "beleg": "Keine Message-ID im Vorgang"}
        try:
            ids = leser()
        except Exception as fehler:
            return {"ergebnis": "nicht_pruefbar", "beleg": "Gesendet-Ablage nicht lesbar: " + type(fehler).__name__}
        if message_id in ids:
            return {"ergebnis": "angekommen", "anbieter_kennung": message_id,
                    "beleg": "Message-ID %s in der Gesendet-Ablage gefunden" % message_id}
        return {"ergebnis": "nicht_angekommen",
                "beleg": "Message-ID %s NICHT in der Gesendet-Ablage (%d Eintraege geprueft)" % (message_id, len(ids))}
    return pruefen


def _message_id_aus(v):
    m = re.search(r"(<[^>\s]+>)", str(v.get("schritt") or ""))
    return m.group(1) if m else None


def _standardpruefer(kanal):
    if kanal in ("runway", "higgsfield"):
        return _pruefer_video(kanal)
    if kanal in ("attrappe", "attrappe_versand"):
        import jack_kanal_attrappe
        return jack_kanal_attrappe.pruefen
    return None


def pruefen(root, vg, pruefer=None):
    """Zustandspruefung eines Vorgangs ohne belegtes Ergebnis. Schreibt `pruefung` ins Journal."""
    v = stand(root).get(vg)
    if not v:
        raise ValueError("Unbekannter Vorgang")
    if v["zustand"] in ("angekommen", "nicht_angekommen"):
        return {"ergebnis": v["zustand"], "beleg": "bereits belegt", "neu": False}
    if v.get("laeuft"):
        return {"ergebnis": "laeuft", "beleg": "Aufrufer wartet noch auf die Antwort", "neu": False}
    pruefer = pruefer or _standardpruefer(v.get("kanal"))
    if pruefer is None:
        ergebnis = {"ergebnis": "nicht_pruefbar", "beleg": "Fuer Kanal %s gibt es keine Zustandsabfrage" % v.get("kanal")}
    else:
        try:
            ergebnis = pruefer(root, v)
        except Exception as fehler:
            # Abfrage selbst gescheitert: Zustand bleibt unklar, spaeter erneut (bis Zeitbudget)
            ergebnis = {"ergebnis": "laeuft", "beleg": "Zustandsabfrage gescheitert: %s" % str(fehler)[:160]}
    if ergebnis.get("ergebnis") not in ("angekommen", "nicht_angekommen", "nicht_pruefbar", "laeuft"):
        ergebnis = {"ergebnis": "nicht_pruefbar", "beleg": "Pruefer lieferte kein gueltiges Ergebnis"}
    _ereignis(root, vg, "pruefung", ergebnis=ergebnis["ergebnis"], beleg=str(ergebnis.get("beleg", ""))[:300],
              anbieter_kennung=ergebnis.get("anbieter_kennung"))
    return dict(ergebnis, neu=True)


def takt(root, pruefer=None, jetzt_epoch=None):
    """Zustandspruefung im Takt: jeder unklare Vorgang wird hoechstens alle prueftakt_s geprueft, bis sein
    Zeitbudget (je Anbieter) verbraucht ist; danach nicht_pruefbar -> Meldung an den Patron."""
    raus = []
    takt_s = prueftakt_s(root)
    for v in list(stand(root).values()):
        if v["zustand"] != "unklar":
            continue
        if v.get("letzte_pruefung") and _alter_s(v["letzte_pruefung"]) < takt_s:
            continue
        if _alter_s(v.get("absicht_zeit")) > zeitbudget_s(root, v.get("kanal")):
            _ereignis(root, v["vg"], "pruefung", ergebnis="nicht_pruefbar",
                      beleg="Zeitbudget %d s fuer %s verbraucht; der Patron entscheidet"
                            % (zeitbudget_s(root, v.get("kanal")), v.get("kanal")))
            raus.append({"vg": v["vg"], "ergebnis": "nicht_pruefbar", "meldung": "patron"})
            continue
        erg = pruefen(root, v["vg"], (pruefer or {}).get(v.get("kanal")) if isinstance(pruefer, dict) else pruefer)
        raus.append({"vg": v["vg"], **erg})
    return raus


# ------------------------------------------------------------------ Vorgangsbuch je Auftrag
PLAN = (("fachkraft", "Fachkraft liefert das Ergebnis", "intern"),
        ("ceo", "Chefpruefung fuellt Lauf, Ergebnis, Nachweis und Pflichtpunktnachweise", "intern"),
        ("tor1", "Tor 1: lokale Vorpruefung aller Pflichtpunkte", "intern"),
        ("tor2", "Tor 2: unabhaengiger Pruefer schreibt seinen Zettel", "intern"),
        ("nachbearbeitung", "Nachbearbeitung: Abschlussquittung und Ablage", "intern"),
        ("freigabe", "Freigabe-Tor des Patrons (nur bei Aussenwirkung)", "aussen"))
FACHKRAFT_TYPEN = ("jack-fachkraft", "jack-fachkraft-stark")


def buchpfad(root, name):
    return betrieb.area(root) / BUCHORDNER / (hashlib.sha256(Path(name).name.encode("utf-8")).hexdigest() + ".json")


def _sha(pfad):
    try:
        h = hashlib.sha256()
        with open(pfad, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        return h.hexdigest()
    except OSError:
        return None


def fachkraft_stand(root, name, zugriffe=None):
    """Aus dem Werkzeugprotokoll: je Lauf die Fachkraft-Delegation, ihre agent_id(s), die von ihr
    geschriebenen Dateien (ohne die Auftragsdatei) und ob der CEO danach weitergearbeitet hat
    (= Fachkraft ist zurueckgekehrt). Liefert den juengsten Lauf mit Fachkraft oder None."""
    import jack_auftrag
    zugriffe = zugriffe if zugriffe is not None else jack_auftrag._zugriffe_des_auftrags(root, name)
    laeufe = {}
    for r in zugriffe:
        lid = r.get("lauf_id")
        if lid:
            laeufe.setdefault(lid, []).append(r)
    bester = None
    for lid, zeilen in laeufe.items():
        start = None
        for i, r in enumerate(zeilen):
            if r.get("tool") == "Agent" and r.get("entscheidung") == "allow" and r.get("agent_typ") in FACHKRAFT_TYPEN:
                start = i
                break
        if start is None:
            continue
        ids, dateien, zurueck, letzte_fk = [], [], False, start
        for j in range(start + 1, len(zeilen)):
            r = zeilen[j]
            aid = r.get("agent_id")
            if aid:
                if not ids:
                    ids.append(aid)
                if aid in ids:
                    letzte_fk = j
                    if r.get("tool") in ("Write", "Edit") and r.get("entscheidung") == "allow" and r.get("pfad"):
                        if Path(str(r["pfad"])).name != Path(name).name and r["pfad"] not in dateien:
                            dateien.append(r["pfad"])
                    continue
                # ein anderer Unteragent nach der Fachkraft: sie ist zurueckgekehrt
                zurueck = True
                break
            if ids and r.get("tool") and j > letzte_fk:
                zurueck = True          # der CEO (ohne agent_id) arbeitet weiter
                break
        eintrag = {"lauf_id": lid, "agent_ids": ids, "dateien": dateien, "zurueck": zurueck,
                   "zeit": zeilen[start].get("zeit")}
        if bester is None or str(eintrag["zeit"]) >= str(bester["zeit"]):
            bester = eintrag
    return bester


def _zettel(root, name):
    stamm = Path(name).stem
    raus = []
    for p in sorted((Path(root) / "abnahme" / "tor2").glob(stamm + "__pruefung*.md")):
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        m = re.search(r"^urteil:[ \t]*(ANNAHME|ZURUECKWEISUNG)[ \t]*$", text, re.M)
        raus.append({"pfad": str(p), "urteil": m.group(1) if m else "?", "sha256": _sha(p)})
    return raus


def _abschnitt_gefuellt(text, titel):
    m = re.search(r"^## " + re.escape(titel) + r"\s*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    body = m.group(1).strip() if m else ""
    return bool(body) and not body.startswith(("(füllt", "(Dateien,"))


def buch_ableiten(root, pfad, ordner=None, laeuft=False, wartegrund=None):
    """Plan, Zwischenergebnisse, naechster Schritt fuer einen Auftrag - nur aus Belegen abgeleitet."""
    import jack_auftrag
    root = Path(root)
    pfad = Path(pfad)
    name = pfad.name
    try:
        text = pfad.read_text(encoding="utf-8")
    except OSError:
        return None
    kopfwerte = jack_auftrag.kopf(text)
    gebunden = False
    try:
        gebunden = jack_auftrag.pruefe_auftrag(root, pfad) is not None
    except (OSError, ValueError):
        gebunden = False
    beleg = None
    try:
        beleg = jack_auftrag.fortsetzung_lesen(root, name)
    except (OSError, ValueError):
        beleg = None
    fk = fachkraft_stand(root, name)
    vault = root.parent.parent
    schritte = {k: {"schritt": k, "titel": t, "art": a, "status": "offen"} for k, t, a in PLAN}
    zwischen = []
    # Fachkraft
    fk_dateien = []
    if beleg and kopfwerte.get("fortsetzung") == beleg.get("kennung"):
        fk_dateien = [{"pfad": d["pfad"], "sha256": d["sha256"],
                       "unveraendert": _sha(vault / d["pfad"]) == d["sha256"]} for d in beleg.get("dateien", [])]
        schritte["fachkraft"]["status"] = "fertig" if all(d["unveraendert"] for d in fk_dateien) else "gebrochen"
        schritte["fachkraft"]["quelle"] = "Fortsetzungsbeleg " + beleg["kennung"]
    elif fk:
        for d in fk["dateien"]:
            p = Path(d)
            rel = str(p.resolve().relative_to(vault.resolve())) if vault.resolve() in p.resolve().parents else d
            fk_dateien.append({"pfad": rel, "sha256": _sha(p)})
        if fk["zurueck"] and fk_dateien:
            schritte["fachkraft"]["status"] = "fertig"
        elif laeuft:
            schritte["fachkraft"]["status"] = "laeuft"
        else:
            schritte["fachkraft"]["status"] = "abgebrochen" if fk_dateien else "offen"
        schritte["fachkraft"]["quelle"] = "Werkzeugprotokoll Lauf " + fk["lauf_id"][:8]
    if fk_dateien:
        zwischen.append({"schritt": "fachkraft", "dateien": fk_dateien})
    # CEO
    if all(_abschnitt_gefuellt(text, t) for t in ("Lauf", "Ergebnis", "Nachweis")):
        schritte["ceo"]["status"] = "fertig"
    elif schritte["fachkraft"]["status"] == "fertig" and laeuft:
        schritte["ceo"]["status"] = "laeuft"
    # Tor 1
    if gebunden:
        try:
            vp = jack_auftrag.lokale_vorpruefung(root, pfad, protokollieren=False)
        except Exception:
            vp = {"ok": False, "gebunden": True}
        if vp.get("ok") and vp.get("gebunden"):
            schritte["tor1"]["status"] = "fertig"
            if vp.get("ergebnisstand_sha256"):
                zwischen.append({"schritt": "tor1", "ergebnisstand_sha256": vp["ergebnisstand_sha256"]})
    else:
        schritte["tor1"]["status"] = "entfaellt"
    # Tor 2
    zettel = _zettel(root, name)
    if zettel:
        letzter = zettel[-1]
        schritte["tor2"]["status"] = "fertig" if letzter["urteil"] == "ANNAHME" else "zurueckgewiesen"
        zwischen.append({"schritt": "tor2", "dateien": [{"pfad": letzter["pfad"], "sha256": letzter["sha256"],
                                                         "urteil": letzter["urteil"]}]})
    # Nachbearbeitung
    if ordner == "erledigt" and jack_auftrag.ist_erfolgreich(root, pfad):
        schritte["nachbearbeitung"]["status"] = "fertig"
        for k in ("fachkraft", "ceo", "tor1", "tor2"):
            if schritte[k]["status"] in ("offen", "laeuft"):
                schritte[k]["status"] = "fertig"
    # Freigabe-Tor
    if kopfwerte.get("gefahr") != "aussen":
        schritte["freigabe"]["status"] = "entfaellt"
    elif kopfwerte.get("freigabe") == "ja":
        schritte["freigabe"]["status"] = "fertig"
    elif ordner == "freigabe":
        schritte["freigabe"]["status"] = "wartet"
    plan = [schritte[k] for k, _, _ in PLAN]
    relevant = [s for s in plan if s["status"] != "entfaellt"]
    fertig = sum(1 for s in relevant if s["status"] == "fertig")
    naechster = next((s for s in plan if s["status"] not in ("fertig", "entfaellt")), None)
    if ordner == "freigabe" and schritte["freigabe"]["status"] == "wartet":
        naechster = schritte["freigabe"]
    ausfuehrbar = bool(naechster) and not wartegrund and ordner in ("offen", "laeuft")
    return {"schema": 1, "auftrag": name, "ordner": ordner, "zeit": betrieb.now().isoformat(),
            "plan": plan, "zwischenergebnisse": zwischen,
            "fortschritt_schritte": {"erledigt": fertig, "gesamt": len(relevant),
                                     "prozent": round(100.0 * fertig / len(relevant), 1) if relevant else None},
            "naechster_schritt": ({"schritt": naechster["schritt"], "titel": naechster["titel"],
                                   "ausfuehrbar": ausfuehrbar} if naechster else None),
            "warten": wartegrund,
            "fortsetzung": ({"kennung": beleg.get("kennung"), "schema": beleg.get("schema"),
                             "letzter_sicherer_schritt": beleg.get("letzter_sicherer_schritt"),
                             "fortsetzungen": beleg.get("fortsetzungen")} if beleg else None),
            "aussenvorgaenge": [{"vg": v["vg"], "kanal": v.get("kanal"), "zustand": v["zustand"]}
                                for v in offene(root, auftrag=name)]}


def buch_schreiben(root, buch):
    """Nur Planer/Dienst. Atomar; Inhalt ohne Zeitfeld unveraendert -> nicht neu schreiben."""
    if not buch:
        return None
    p = buchpfad(root, buch["auftrag"])
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        alt = json.loads(p.read_text(encoding="utf-8"))
        if {k: v for k, v in alt.items() if k != "zeit"} == {k: v for k, v in buch.items() if k != "zeit"}:
            return p
    except (OSError, ValueError):
        pass
    tmp = p.with_name("." + p.name + ".neu")
    tmp.write_text(json.dumps(buch, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)
    return p


def buch_lesen(root, name):
    try:
        return json.loads(buchpfad(root, name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ------------------------------------------------------------------ Wartegruende strukturiert
_WARTEARTEN = (
    ("stopp", re.compile(r"STOPP-Datei", re.I)),
    ("notbremse", re.compile(r"Notbremse|ALLES PAUSIERT", re.I)),
    ("stundendeckel", re.compile(r"Stunden(?:-Lauf)?deckel", re.I)),
    ("deckel", re.compile(r"Tages(?:-Lauf)?deckel|Deckel", re.I)),
    ("guthaben", re.compile(r"Guthaben|Anbieterstatus|API-Auftraege", re.I)),
    ("anbieter", re.compile(r"Anbieter|Vorgang vg_|Antwort des Anbieters", re.I)),
    ("zeitgrenze", re.compile(r"Zeitgrenze|Minuten beendet", re.I)),
    ("freigabe", re.compile(r"Freigabe", re.I)),
    ("fortsetzung", re.compile(r"reserviert fuer die Fortsetzung", re.I)),
    ("patron", re.compile(r"Schleifenschutz|VERSUCHE VERBRAUCHT|Versuche verbraucht|Entscheidung des Patrons|RINGSCHLUSS|Ringschluss", re.I)),
    ("marke", re.compile(r"Marke .* vom Patron", re.I)),
    ("vorgaenger", re.compile(r"^wartet auf (?!einen freien Platz)", re.I)),
    ("platz", re.compile(r"freien Platz|Obergrenze", re.I)),
    ("sperre", re.compile(r"Bereich belegt|Sperre belegt", re.I)),
)


def wartegrund(text, seit=None, bis=None, worauf=None, quelle="planer"):
    """Freitext-Grund -> {art, text, seit, bis, worauf, quelle}. Arten: stopp, notbremse, stundendeckel,
    deckel, guthaben, anbieter, zeitgrenze, freigabe, fortsetzung, patron, marke, vorgaenger, platz,
    sperre, vorpruefung (Rest)."""
    if not text:
        return None
    art = "vorpruefung"
    for name, muster in _WARTEARTEN:
        if muster.search(str(text)):
            art = name
            break
    return {"art": art, "text": str(text)[:300], "seit": seit, "bis": bis, "worauf": worauf, "quelle": quelle}


if __name__ == "__main__":
    import sys
    wurzel = Path(__file__).resolve().parent
    was = sys.argv[1] if len(sys.argv) > 1 else "stand"
    if was == "stand":
        print(json.dumps(list(stand(wurzel).values()), ensure_ascii=False, indent=1))
    elif was == "offen":
        print(json.dumps(offene(wurzel), ensure_ascii=False, indent=1))
    elif was == "pruefen" and len(sys.argv) > 2:
        print(json.dumps(pruefen(wurzel, sys.argv[2]), ensure_ascii=False))
    elif was == "klaeren" and len(sys.argv) > 4:
        print(json.dumps(klaeren(wurzel, sys.argv[2], sys.argv[3], " ".join(sys.argv[4:])), ensure_ascii=False))
    else:
        print("stand | offen | pruefen <vg> | klaeren <vg> angekommen|nicht_angekommen <Beleg>")
