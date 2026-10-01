#!/usr/bin/env python3
"""F-85 (29.09.2026): Das Postfach zeigt ALLE Mails - wie ein Mailprogramm.

Entscheid des PM: ANZEIGEN ja, VERARBEITEN nein. Die Lehre vom 16.09. (kein
automatisches Entwerfen oder Handeln fuer Altbestand) bleibt unangetastet: dieses
Modul liest ausschliesslich KOPFZEILEN (BODY.PEEK, readonly), startet kein Modell,
legt keinen Auftrag und keinen Entwurf an und aendert nichts am Postfach.

Quelle ist der echte Mailserver (IMAP, Posteingang, letzte 30 Tage). Das Ergebnis
liegt kurz zwischengespeichert in betrieb/postfach_liste.json, damit das Dashboard
nicht bei jedem Aufruf 25 Server befragt. Was aelter ist als der zuletzt
verarbeitete Stand eines Postfachs (betrieb/postfaecher_stand.json, Feld
"altbestand"), steht in DERSELBEN Liste mit dem Kennzeichen "aelter, nicht
bearbeitet" - kein versteckter Knopf.
"""
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from email import message_from_bytes
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path

import jack_betrieb as b
import jack_postfaecher as pf
from jack_speicher import atomic_bytes

CACHE = "postfach_liste.json"
TAGE = 30                      # so weit zurueck zeigt die Liste
MAX_JE_POSTFACH = 1500         # Sicherung fuer riesige Postfaecher (Anzeige gekappt, Zaehler echt)
GUELTIG_SEK = 300              # so lange gilt der Zwischenspeicher als frisch
PARALLEL = 6
HAUFEN = 100                   # Kopfzeilen je IMAP-Abruf
MAX_ZEILEN_ANTWORT = 4000

MONAT = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

# Vier Gruppen fuer Farbmarke, Legende und Filter. Regelbasiert (pf.mailart), ohne Modell.
GRUPPE_KUNDE = "Kunde/Behörde/Partner"
GRUPPE_PLATTFORM = "Plattform"
GRUPPE_WERBUNG = "Newsletter/Werbung"
GRUPPE_SONST = "Nicht eingeordnet"
GRUPPEN = (GRUPPE_KUNDE, GRUPPE_PLATTFORM, GRUPPE_WERBUNG, GRUPPE_SONST)
_GRUPPE_VON_ART = {
    "Terminanfrage": GRUPPE_KUNDE, "Partneranfrage": GRUPPE_KUNDE, "Rueckfrage": GRUPPE_KUNDE,
    "Rechnung/Zahlung": GRUPPE_KUNDE, "Vertrag": GRUPPE_KUNDE, "Behoerde": GRUPPE_KUNDE,
    "Presse": GRUPPE_KUNDE, "Fiverr-Kundenanfrage": GRUPPE_KUNDE, "Fiverr-Auftrag": GRUPPE_KUNDE,
    "Sicherheitscode": GRUPPE_PLATTFORM, "Anbieter-Meldung": GRUPPE_PLATTFORM,
    "Fiverr-Pruefung": GRUPPE_PLATTFORM,
    "Newsletter/Werbung": GRUPPE_WERBUNG,
}
# Handlung noetig? Nur wo ein Mensch antworten oder entscheiden muss.
_HANDLUNG_ART = {"Terminanfrage", "Partneranfrage", "Rueckfrage", "Rechnung/Zahlung", "Vertrag",
                 "Behoerde", "Presse", "Fiverr-Kundenanfrage", "Fiverr-Auftrag", "Fiverr-Pruefung"}
_ARTWORT = {
    "Terminanfrage": "Terminanfrage", "Partneranfrage": "Partneranfrage", "Rueckfrage": "Rückfrage",
    "Rechnung/Zahlung": "Rechnung/Zahlung", "Vertrag": "Vertrag", "Behoerde": "Behörde",
    "Presse": "Presse", "Fiverr-Kundenanfrage": "Fiverr-Kundenanfrage", "Fiverr-Auftrag": "Fiverr-Auftrag",
    "Fiverr-Pruefung": "Fiverr zur Prüfung", "Sicherheitscode": "Sicherheitscode",
    "Anbieter-Meldung": "Meldung eines Dienstes", "Newsletter/Werbung": "Newsletter/Werbung",
    "Sonstiges": "Nachricht",
}

_sperre = threading.Lock()          # ein Abruflauf zur Zeit
_schreibsperre = threading.Lock()   # Zwischenspeicher-Schreiben
_LAUF = {"laeuft": False, "seit": 0.0, "fertig": 0, "von": 0, "letzter_fehler": ""}


def _cache_pfad(root):
    return b.area(root) / CACHE


def _cache_lesen(root):
    p = _cache_pfad(root)
    try:
        if p.is_symlink() or p.stat().st_size > 30_000_000:
            return {}
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _cache_schreiben(root, wert):
    atomic_bytes(_cache_pfad(root), json.dumps(wert, ensure_ascii=False).encode())


def _imap_datum(tage):
    d = datetime.now() - timedelta(days=tage)
    return "%d-%s-%d" % (d.day, MONAT[d.month - 1], d.year)


def _iso_lokal(datum_text):
    try:
        d = parsedate_to_datetime(datum_text)
        if d.tzinfo is not None:
            d = d.astimezone().replace(tzinfo=None)
        return d.isoformat(timespec="seconds")
    except Exception:
        return ""


def gruppe_von(art):
    return _GRUPPE_VON_ART.get(art, GRUPPE_SONST)


def satz_zu(art, betreff):
    """EIN Satz: worum es geht + Handlung ja/nein. Regelbasiert, ohne Modell."""
    thema = re.sub(r"\s+", " ", str(betreff or "")).strip() or "ohne Betreff"
    if len(thema) > 70:
        thema = thema[:67].rstrip() + "…"
    wort = _ARTWORT.get(art, "Nachricht")
    if art == "Sicherheitscode":
        handlung = "Handlung nein (Code nur nutzen, wenn du ihn angefordert hast)"
    elif art in _HANDLUNG_ART:
        handlung = "Handlung ja"
    elif art == "Sonstiges":
        handlung = "Handlung offen, bitte ansehen"
    else:
        handlung = "keine Handlung"
    return "%s: %s — %s" % (wort, thema, handlung)


def _absender_teile(roh):
    name, adr = parseaddr(roh or "")
    return (name or "").strip(), (adr or "").strip()


def _kopfzeilen_holen(verbindung, uids):
    """UID -> (Flags, Kopf-Nachricht). Nur BODY.PEEK, nichts wird als gelesen markiert."""
    raus = {}
    for i in range(0, len(uids), HAUFEN):
        satz = ",".join(str(u) for u in uids[i:i + HAUFEN])
        ok, teile = verbindung.uid(
            "fetch", satz,
            "(UID FLAGS BODY.PEEK[HEADER.FIELDS (FROM TO DATE SUBJECT LIST-UNSUBSCRIBE)])")
        if ok != "OK" or not teile:
            continue
        aktuell = None
        for stueck in teile:
            if isinstance(stueck, tuple) and len(stueck) >= 2:
                aktuell = [stueck[0].decode("utf-8", "replace"), stueck[1]]
                raus[id(aktuell)] = aktuell
            elif isinstance(stueck, (bytes, bytearray)) and aktuell is not None:
                aktuell[0] += " " + stueck.decode("utf-8", "replace")
        # (UID kann vor ODER nach dem Kopf stehen - deshalb erst nach dem Sammeln lesen)
    fertig = {}
    for meta, kopf in raus.values():
        m = re.search(r"UID (\d+)", meta)
        if not m:
            continue
        f = re.search(r"FLAGS \(([^)]*)\)", meta)
        fertig[int(m.group(1))] = (f.group(1) if f else "", message_from_bytes(kopf))
    return fertig


def _eines_abrufen(root, p, tage=TAGE):
    """Kopfzeilen der letzten `tage` Tage eines Postfachs vom Server holen."""
    adresse = p["adresse"]
    ergebnis = {"adresse": adresse, "marke": p.get("marke", ""), "ok": False, "fehler": "",
                "abgerufen": b.now().isoformat(), "server_gesamt": 0, "ungelesen": 0,
                "ungelesen_gesamt": None, "inbox_gesamt": None, "gekappt": False, "mails": []}
    zustand, geheim, grund = pf.tresor_stand(p["passwort_schluessel"])
    if zustand != "da":
        ergebnis["fehler"] = grund or "Kein Passwort hinterlegt."
        return ergebnis
    try:
        v = pf._imap(root, p, geheim)
    except Exception as fehler:
        ergebnis["fehler"] = pf._klartext(fehler, root, p.get("anbieter"))
        return ergebnis
    try:
        ok, roh = v.select("INBOX", readonly=True)
        if ok == "OK" and roh and roh[0]:
            ergebnis["inbox_gesamt"] = int(roh[0])
        ok, roh = v.uid("search", None, "SINCE", _imap_datum(tage))
        uids = sorted(int(x) for x in (roh[0].split() if ok == "OK" and roh and roh[0] else []))
        ergebnis["server_gesamt"] = len(uids)
        try:
            ok2, roh2 = v.uid("search", None, "UNSEEN")
            ergebnis["ungelesen_gesamt"] = len(roh2[0].split()) if ok2 == "OK" and roh2 and roh2[0] else 0
        except Exception:
            pass
        if len(uids) > MAX_JE_POSTFACH:
            ergebnis["gekappt"] = True
            uids = uids[-MAX_JE_POSTFACH:]
        kopf = _kopfzeilen_holen(v, uids)
        for uid in uids:
            if uid not in kopf:
                continue
            flags, k = kopf[uid]
            absender = pf._entziffern(k.get("From"))
            name, adr = _absender_teile(absender)
            betreff = pf._entziffern(k.get("Subject"))
            unsub = bool(k.get("List-Unsubscribe"))
            art, _sicher = pf.mailart(betreff, absender, "",
                                      kopfzeilen={"List-Unsubscribe": "ja"} if unsub else None)
            if unsub and art == "Sonstiges":
                # List-Unsubscribe ist das Standardzeichen einer Rundmail (Newsletter/Werbung).
                art = "Newsletter/Werbung"
            gelesen = "\\Seen" in flags
            ergebnis["mails"].append({
                "uid": uid, "absender": absender, "absender_name": name or adr,
                "absender_adresse": adr, "betreff": betreff, "zeit": _iso_lokal(k.get("Date") or ""),
                "gelesen": gelesen, "art": art, "unsub": unsub})
            if not gelesen:
                ergebnis["ungelesen"] += 1
        ergebnis["ok"] = True
    except Exception as fehler:
        ergebnis["fehler"] = pf._klartext(fehler, root, p.get("anbieter"))
    finally:
        try:
            v.logout()
        except Exception:
            pass
    return ergebnis


def aktualisieren(root, nur=None, tage=TAGE):
    """Alle (oder ein) Postfach neu vom Server lesen. Blockiert bis fertig."""
    if not _sperre.acquire(blocking=False):
        return {"ok": False, "meldung": "Ein Abruf läuft bereits."}
    try:
        daten = pf.konfiguration(root)
        ziel = [p for p in daten["postfaecher"]
                if (not nur or p["adresse"].lower() == str(nur).lower())
                and p.get("status") in ("verbunden", "netzfehler")]
        _LAUF.update({"laeuft": True, "seit": time.time(), "fertig": 0, "von": len(ziel),
                      "letzter_fehler": ""})
        cache = _cache_lesen(root)
        cache.setdefault("postfaecher", {})

        def eins(p):
            try:
                r = _eines_abrufen(root, p, tage)
            except Exception as fehler:      # nie den ganzen Lauf abbrechen
                r = {"adresse": p["adresse"], "marke": p.get("marke", ""), "ok": False,
                     "fehler": str(fehler)[:160], "abgerufen": b.now().isoformat(),
                     "server_gesamt": 0, "ungelesen": 0, "mails": [], "gekappt": False,
                     "ungelesen_gesamt": None, "inbox_gesamt": None}
            with _schreibsperre:
                alt = cache["postfaecher"].get(p["adresse"], {})
                if not r["ok"] and alt.get("mails"):
                    # Fehlschlag: alten Stand behalten, Fehler sichtbar mitfuehren.
                    alt["fehler"] = r["fehler"]
                    alt["fehler_zeit"] = r["abgerufen"]
                    cache["postfaecher"][p["adresse"]] = alt
                else:
                    cache["postfaecher"][p["adresse"]] = r
                cache["zeit"] = b.now().isoformat()
                cache["epoch"] = time.time()
                cache["tage"] = tage
                _cache_schreiben(root, cache)
                _LAUF["fertig"] += 1
            return r

        with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
            ergebnisse = list(pool.map(eins, ziel))
        return {"ok": True, "postfaecher": len(ergebnisse),
                "fehler": [r["adresse"] for r in ergebnisse if not r["ok"]]}
    finally:
        _LAUF["laeuft"] = False
        _sperre.release()


def im_hintergrund_aktualisieren(root, nur=None):
    """Startet den Abruf, ohne den Aufrufer warten zu lassen. Doppelt startet nichts."""
    if _LAUF["laeuft"]:
        return False
    threading.Thread(target=aktualisieren, args=(root, nur), daemon=True,
                     name="postfachliste").start()
    return True


def _verarbeitet(root):
    """postfach(klein) -> Menge der UIDs, die JACK im laufenden Betrieb gesehen hat."""
    raus = {}
    for z in b.records(b.area(root) / pf.EINGANG):
        try:
            raus.setdefault(str(z.get("postfach", "")).lower(), set()).add(int(z.get("uid")))
        except (TypeError, ValueError):
            continue
    return raus


def liste(root, postfach=None, marke=None, gruppe=None, nur_ungelesen=False, suche="",
          aktualisieren_erlaubt=True, hoechstens=MAX_ZEILEN_ANTWORT):
    """Die Liste aller Mails aller Postfaecher, neueste oben, plus echte Zaehler."""
    cache = _cache_lesen(root)
    alter = time.time() - float(cache.get("epoch") or 0)
    startet = False
    if aktualisieren_erlaubt and (not cache.get("postfaecher") or alter > GUELTIG_SEK):
        startet = im_hintergrund_aktualisieren(root)
    daten = pf.konfiguration(root)
    stand = pf._stand(root)
    mailstand = pf._mailstand(root)
    verarbeitet = _verarbeitet(root)
    zu_marke = {p["adresse"].lower(): p.get("marke", "") for p in daten["postfaecher"]}
    zu_weg = {p["adresse"].lower(): pf.freigabeweg(p) for p in daten["postfaecher"]}

    zeilen, kopf_pf = [], []
    for p in daten["postfaecher"]:
        adr = p["adresse"]
        c = (cache.get("postfaecher") or {}).get(adr) or {}
        grenze = int((stand.get(adr) or {}).get("altbestand", 0) or 0)
        ungelesen = 0
        gezaehlt = 0
        for m in c.get("mails", []):
            schluessel = pf._mailschluessel(adr, m["uid"])
            ms = mailstand.get(schluessel, {})
            art = ms.get("mailart") or m["art"]
            gr = gruppe_von(art)
            geoeffnet = bool(ms.get("geoeffnet"))
            gelesen = bool(m["gelesen"])
            bearbeitet = m["uid"] in verarbeitet.get(adr.lower(), set()) or bool(ms.get("zustand"))
            alt = bool(grenze and m["uid"] <= grenze and not bearbeitet)
            if not gelesen:
                ungelesen += 1
            gezaehlt += 1
            zeilen.append({
                "postfach": adr, "marke": ms.get("marke") or c.get("marke") or zu_marke.get(adr.lower(), ""),
                "uid": m["uid"], "absender": m["absender"], "absender_name": m["absender_name"],
                "betreff": m["betreff"], "zeit": m["zeit"], "gelesen": gelesen, "geoeffnet": geoeffnet,
                "art": art, "gruppe": gr, "handlung": art in _HANDLUNG_ART,
                "satz": satz_zu(art, m["betreff"]), "alt": alt,
                "zustand": ms.get("zustand", "offen"), "weg": zu_weg.get(adr.lower(), pf.GESPERRT)})
        kopf_pf.append({
            "adresse": adr, "marke": p.get("marke", ""), "status": p.get("status", ""),
            "abgerufen": c.get("abgerufen", ""), "abruf_ok": bool(c.get("ok")) and not c.get("fehler"),
            "fehler": c.get("fehler") or (p.get("letzter_fehler", "") if not c else ""),
            "server_gesamt": c.get("server_gesamt", 0), "angezeigt": gezaehlt,
            "ungelesen": ungelesen, "ungelesen_gesamt": c.get("ungelesen_gesamt"),
            "inbox_gesamt": c.get("inbox_gesamt"), "gekappt": bool(c.get("gekappt")),
            "noch_nicht_gelesen": not c})
    zeilen.sort(key=lambda z: (z["zeit"] or "", z["uid"]), reverse=True)

    zaehl_gruppe = {g: 0 for g in GRUPPEN}
    zaehl_marke = {}
    for z in zeilen:
        zaehl_gruppe[z["gruppe"]] = zaehl_gruppe.get(z["gruppe"], 0) + 1
        if z["marke"]:
            zaehl_marke[z["marke"]] = zaehl_marke.get(z["marke"], 0) + 1
    marken = []
    for p in daten["postfaecher"]:
        if p.get("marke") and p["marke"] not in marken:
            marken.append(p["marke"])

    def passt(z):
        if postfach and z["postfach"].lower() != str(postfach).lower():
            return False
        if marke and z["marke"] != marke:
            return False
        if gruppe and z["gruppe"] != gruppe:
            return False
        if nur_ungelesen and z["gelesen"]:
            return False
        if suche:
            w = str(suche).lower()
            if w not in z["betreff"].lower() and w not in z["absender"].lower():
                return False
        return True

    gefiltert = [z for z in zeilen if passt(z)]
    verbunden = sum(1 for p in kopf_pf if p["status"] == "verbunden")
    return {
        "zeit": b.now().isoformat(), "stand": cache.get("zeit", ""), "alter_s": int(alter) if cache.get("epoch") else None,
        "laeuft": bool(_LAUF["laeuft"]), "fortschritt": {"fertig": _LAUF["fertig"], "von": _LAUF["von"]},
        "startet": startet, "tage": cache.get("tage", TAGE),
        "mails": gefiltert[:hoechstens], "gezeigt": min(len(gefiltert), hoechstens), "passend": len(gefiltert),
        "gesamt": len(zeilen), "postfaecher": kopf_pf,
        "kopf": {"postfaecher": len(kopf_pf), "verbunden": verbunden,
                 "ungelesen": sum(p["ungelesen"] for p in kopf_pf),
                 "server_gesamt": sum(p["server_gesamt"] for p in kopf_pf),
                 "mit_fehler": sum(1 for p in kopf_pf if p["fehler"])},
        "gruppen": [{"wert": g, "zahl": zaehl_gruppe.get(g, 0)} for g in GRUPPEN],
        "marken": [{"wert": m, "zahl": zaehl_marke.get(m, 0)} for m in marken],
        "quelle": "Mailserver (IMAP, nur Kopfzeilen, letzte %d Tage) · betrieb/%s" % (
            cache.get("tage", TAGE), CACHE)}


# ─────────────────────────── Mail und Anhaenge einzeln holen ───────────────────────────
def _ordner_und_uid(root, postfach, uid):
    roh = str(uid or "")
    gesendet = roh.startswith("g") and roh[1:].isdigit()
    echte = roh[1:] if gesendet else roh
    ordner = "INBOX"
    if gesendet:
        ordner = pf._stand(root).get(postfach, {}).get("gesendet_ordner") or "INBOX.Sent"
    return gesendet, echte, ordner


def anhang_holen(root, postfach, uid, nr, hoechstens=25 * 1024 * 1024):
    """Ein Anhang zum Herunterladen: (ok, name, typ, bytes, meldung).

    Wird nur auf ausdruecklichen Klick des Patrons aufgerufen. JACK oeffnet, startet
    oder verarbeitet den Anhang nie selbst.
    """
    try:
        nr = int(nr)
    except (TypeError, ValueError):
        return False, "", "", b"", "Anhang nicht bestimmt."
    p = pf._postfach(root, postfach)
    zustand, geheim, grund = pf.tresor_stand(p["passwort_schluessel"])
    if zustand != "da":
        return False, "", "", b"", grund or "Kein Passwort hinterlegt."
    gesendet, echte, ordner = _ordner_und_uid(root, postfach, uid)
    try:
        v = pf._imap(root, p, geheim)
        try:
            v.select(ordner, readonly=True)
            ok, teile = v.uid("fetch", str(echte), "(BODY.PEEK[])")
            if ok != "OK" or not teile or not teile[0] or not isinstance(teile[0], tuple):
                return False, "", "", b"", "Die Nachricht liegt nicht mehr im Ordner %s." % ordner
            nachricht = message_from_bytes(teile[0][1])
        finally:
            try:
                v.logout()
            except Exception:
                pass
    except Exception as fehler:
        return False, "", "", b"", pf._klartext(fehler, root, p.get("anbieter"))
    zaehler = -1
    for teil in nachricht.walk():
        name = teil.get_filename()
        if not name:
            continue
        zaehler += 1
        if zaehler != nr:
            continue
        daten = teil.get_payload(decode=True) or b""
        if len(daten) > hoechstens:
            return False, "", "", b"", "Der Anhang ist größer als 25 MB und wird hier nicht geladen."
        sauber = re.sub(r'[\\/:*?"<>|\r\n\x00-\x1f]', "_", pf._entziffern(name)).strip() or "anhang"
        return True, sauber[:150], teil.get_content_type() or "application/octet-stream", daten, ""
    return False, "", "", b"", "Diesen Anhang gibt es in der Nachricht nicht."
