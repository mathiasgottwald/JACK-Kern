#!/usr/bin/env python3
"""iCloud-Kalender über CalDAV — lesen und, nach Freigabe, schreiben.

Block 6 Teil F, 16.09.2026. Dasselbe Apple-App-Passwort wie für das
iCloud-Postfach öffnet den Kalender; EIN Verbinden genügt für beides.

Nur Bordmittel: http.client, xml.etree, uuid, datetime. Keine neue
Abhängigkeit, kein caldav-Paket.

Harte Regel: **Der Kalender lernt nicht.** Jeder Eintrag, jede Änderung und
jedes Löschen geht durch den Freigaben-Fluss des Patrons — auch auf Stufe 3.
Es gibt in dieser Datei keinen Weg, der daran vorbeiführt: `schreiben()` prüft
zuerst, ob eine gültige serverseitige Freigabe (Block 3) verbraucht wurde.

Ausnahme (F-79, Anordnung Patron 28.09.2026 18:30): `schreiben_aus_termin()`
schreibt den Kalendereintrag im selben Zug wie eine bereits verbrauchte
Mail-Freigabe (`art: externemail`/`mailantwort` mit `termin:`-Feld) — KEINE
zweite, separate Kalender-Freigabekarte nötig, weil der Patron das FREIGEBEN
der Mail ausdrücklich auch als Freigabe des verknüpften Termins gelten
lässt ("dieselbe verbrauchte Freigabe deckt beides"). Der Aufrufer
(`jack_oberflaeche._anwenden`, Zweig `externemail`) hat die volle
Freigabekette (Testversand, Freigabecode, Patron-Klick) bereits geprüft,
BEVOR diese Funktion aufgerufen wird — das ist kein Weg VORBEI am
Freigaben-Fluss, sondern ein zweiter, hier ausdrücklich erlaubter Auslöser
desselben Flusses. Für automatische Änderungen durch die Gegenseite
(§4 desselben Auftrags, ebenfalls 28.09.2026 18:30) siehe `jack_termine.py`
(`aenderung_anwenden`) — auch dort: nur an JACK-eigenen Einträgen, nie an
fremden, mit Memo-Karte und Rückgängig-Weg.
"""
import datetime as dt
import http.client, socket
import jack_netzwiederholung
import json
import re
import ssl
import uuid
import xml.etree.ElementTree as ET
from base64 import b64encode
from pathlib import Path

import jack_betrieb as b
from jack_speicher import atomic_bytes

SERVER = "caldav.icloud.com"
PORT = 443
ZONE = "Europe/Berlin"   # F-99: Patron-Vorgabe; gleiche Regeln wie Wien, die .ics tragen die Berliner Zeitzone
POSTFACH = "Gottwald.mathias@icloud.com"
STAND = "kalender_stand.json"
AENDERUNGEN = "kalender_aenderungen.jsonl"
ABBILD = "kalender_abbild.ics"
WARTEZEIT = 25
NS = {"d": "DAV:", "c": "urn:ietf:params:xml:ns:caldav"}


def _area(root):
    return b.area(root)


def protokoll(root, art, **felder):
    try:
        e = {"zeit": b.now().isoformat(), "art": art}
        e.update(felder)
        with (_area(root) / AENDERUNGEN).open("a", encoding="utf-8") as d:
            d.write(json.dumps(e, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------- Verbindung
def _zugang(root):
    import jack_postfaecher
    postfach = None
    for p in jack_postfaecher.konfiguration(root)["postfaecher"]:
        if p["adresse"].lower() == POSTFACH.lower():
            postfach = p
    if not postfach:
        raise ValueError("Das iCloud-Postfach steht nicht in postfaecher.json")
    geheim = jack_postfaecher.tresor_lesen(postfach["passwort_schluessel"])
    if not geheim:
        raise ValueError("Für den Kalender fehlt das iCloud-App-Passwort.")
    return postfach["adresse"], geheim


def _anfrage(root, methode, pfad, rumpf=None, kopf=None):
    benutzer, geheim = _zugang(root)
    marke = b64encode(("%s:%s" % (benutzer, geheim)).encode()).decode()
    kopfzeilen = {"Authorization": "Basic " + marke,
                  "User-Agent": "JACK/1.0 (lokal, nur nach Freigabe)"}
    kopfzeilen.update(kopf or {})
    import jack_netzwiederholung
    lesend = methode in ("PROPFIND", "REPORT", "GET", "OPTIONS", "HEAD")

    def einmal():
        verbindung = http.client.HTTPSConnection(
            SERVER, PORT, timeout=WARTEZEIT, context=ssl.create_default_context())
        try:
            verbindung.connect()
            try:
                verbindung.request(methode, pfad, body=rumpf, headers=kopfzeilen)
                antwort = verbindung.getresponse()
                daten = antwort.read()
            except jack_netzwiederholung.NETZFEHLER as fehler:
                if lesend:
                    raise
                # Schreibend und schon verbunden: die Anfrage kann angekommen sein - nicht noch einmal senden.
                raise jack_netzwiederholung.AntwortZeit(str(fehler)) from fehler
            return antwort.status, daten.decode("utf-8", errors="replace")
        finally:
            verbindung.close()
    # S-2c: 3 Wiederholungen (2/5/15 s) bei Netzfehlern (schreibend nur beim Verbinden); Netz weg -> parken.
    # Kalender ist kein Sprachgespraech: eigenes, groesseres Zeitbudget (Versuch bis WARTEZEIT s)
    return jack_netzwiederholung.mit_wiederholung(einmal, root, max_gesamt_s=4 * WARTEZEIT + 22, versuch_max_s=WARTEZEIT)


KLARTEXT = [
    (r"^40[13]$", "Passwort abgelehnt. Bitte ein neues App-Passwort bei Apple erzeugen."),
    (r"^404$", "Der Kalender wurde nicht gefunden."),
    (r"^5\d\d$", "Apple antwortet gerade nicht."),
]


def _klartext(status):
    for muster, satz in KLARTEXT:
        if re.match(muster, str(status)):
            return satz
    return "Der Kalender antwortet mit einem unerwarteten Ergebnis (%s)." % status


def verbinden(root):
    """Prüft die Kalenderanmeldung. Ändert nichts."""
    try:
        benutzer, _ = _zugang(root)
    except ValueError as fehler:
        return {"ok": False, "ampel": "grau", "meldung": str(fehler)}
    kopf = {"Depth": "0", "Content-Type": "application/xml"}
    ns = 'xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"'
    try:
        # Apple nennt den Kalenderpfad erst nach dem Konto-Pfad (current-user-principal).
        status, text = _anfrage(root, "PROPFIND", "/",
                                '<d:propfind %s><d:prop><d:current-user-principal/></d:prop>'
                                '</d:propfind>' % ns, kopf)
        principal = ""
        if status in (207, 200):
            for knoten in ET.fromstring(text).iter("{DAV:}current-user-principal"):
                for href in knoten.iter("{DAV:}href"):
                    principal = href.text or ""
            if principal:
                status, text = _anfrage(root, "PROPFIND", principal,
                                        '<d:propfind %s><d:prop><c:calendar-home-set/></d:prop>'
                                        '</d:propfind>' % ns, kopf)
    except ET.ParseError:
        principal, status, text = "", 200, ""
    except Exception as fehler:
        return {"ok": False, "ampel": "rot",
                "meldung": "Server nicht erreichbar. Besteht eine Internetverbindung?"}
    if status not in (207, 200):
        satz = _klartext(status)
        protokoll(root, "verbinden_fehlgeschlagen", status=status, grund=satz)
        return {"ok": False, "ampel": "rot", "meldung": satz}
    heim = ""
    try:
        baum = ET.fromstring(text)
        for knoten in baum.iter("{urn:ietf:params:xml:ns:caldav}calendar-home-set"):
            for href in knoten.iter("{DAV:}href"):
                heim = href.text or ""
    except ET.ParseError:
        pass
    # Apple liefert eine volle Adresse auf einem anderen Server; gebraucht wird nur der Pfad.
    heim = re.sub(r"^https?://[^/]+", "", heim)
    if not heim:
        protokoll(root, "verbinden_fehlgeschlagen", status=status,
                  grund="Kein Kalenderpfad von Apple erhalten")
        return {"ok": False, "ampel": "gelb",
                "meldung": "Angemeldet, aber Apple nennt keinen Kalenderpfad."}
    daten = _lesen_stand(root)
    daten["heim"] = heim
    daten["status"] = "verbunden"
    daten["geprueft"] = b.now().isoformat()
    _schreiben_stand(root, daten)
    protokoll(root, "verbunden", heim=heim)
    return {"ok": True, "ampel": "gruen", "heim": heim,
            "meldung": "Kalender verbunden."}


def _lesen_stand(root):
    p = _area(root) / STAND
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "nicht_verbunden", "kalender": [], "termine": []}


def _schreiben_stand(root, wert):
    atomic_bytes(_area(root) / STAND,
                 (json.dumps(wert, ensure_ascii=False, indent=1) + "\n").encode())


# ---------------------------------------------------------------- Lesen
def kalenderliste(root):
    stand = _lesen_stand(root)
    heim = stand.get("heim")
    if not heim:
        raise ValueError("Der Kalender ist noch nicht verbunden.")
    rumpf = ('<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
             '<d:prop><d:displayname/><d:resourcetype/>'
             '<c:supported-calendar-component-set/></d:prop></d:propfind>')
    status, text = _anfrage(root, "PROPFIND", heim, rumpf,
                            {"Depth": "1", "Content-Type": "application/xml"})
    if status not in (207, 200):
        raise ValueError(_klartext(status))
    raus = []
    for antwort in ET.fromstring(text).iter("{DAV:}response"):
        href = antwort.find("{DAV:}href")
        name = antwort.iter("{DAV:}displayname")
        art = [k.get("name") for k in
               antwort.iter("{urn:ietf:params:xml:ns:caldav}comp")]
        if href is None or "VEVENT" not in art:
            continue
        raus.append({"pfad": href.text, "name": next((n.text for n in name if n.text), href.text)})
    return raus


def _ics_lesen(text):
    """Nur die Felder, die JACK zeigt. Kein vollständiger iCalendar-Parser."""
    termine = []
    for block in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", text, re.S):
        block = block.replace("\r\n ", "").replace("\n ", "")   # Faltung auflösen
        hol = lambda f: (re.search(r"^" + f + r"[^:\n]*:(.*)$", block, re.M) or [None, ""])[1].strip()
        beginn = hol("DTSTART")
        if not beginn:
            continue
        termine.append({
            "uid": hol("UID"), "titel": hol("SUMMARY") or "ohne Titel",
            "beginn": beginn, "ende": hol("DTEND"), "ort": hol("LOCATION"),
            "beschreibung": hol("DESCRIPTION")[:400],
            "ganztaegig": "VALUE=DATE" in (re.search(r"^DTSTART[^:\n]*", block, re.M) or [""])[0],
        })
    return termine


def _zeitpunkt(roh):
    roh = (roh or "").strip()
    for form in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M%SZ", "%Y%m%d"):
        try:
            gelesen = dt.datetime.strptime(roh, form)
            if form.endswith("Z"):
                gelesen = gelesen.replace(tzinfo=dt.timezone.utc).astimezone(b.ZONE)
            else:
                gelesen = gelesen.replace(tzinfo=b.ZONE)
            return gelesen
        except ValueError:
            continue
    return None


def abrufen(root, tage=40):
    """Holt die Termine und legt ein lokales Abbild an. Für die Fünf-Minuten-Routine."""
    stand = _lesen_stand(root)
    von = b.now() - dt.timedelta(days=1)
    bis = b.now() + dt.timedelta(days=tage)
    rumpf = ('<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
             '<d:prop><c:calendar-data/></d:prop>'
             '<c:filter><c:comp-filter name="VCALENDAR">'
             '<c:comp-filter name="VEVENT"><c:time-range start="%s" end="%s"/>'
             '</c:comp-filter></c:comp-filter></c:filter></c:calendar-query>'
             % (von.strftime("%Y%m%dT%H%M%SZ"), bis.strftime("%Y%m%dT%H%M%SZ")))
    alle = []
    for kalender in kalenderliste(root):
        status, text = _anfrage(root, "REPORT", kalender["pfad"], rumpf,
                                {"Depth": "1", "Content-Type": "application/xml"})
        if status not in (207, 200):
            continue
        for termin in _ics_lesen(text):
            termin["kalender"] = kalender["name"]
            termin["kalender_pfad"] = kalender["pfad"]
            alle.append(termin)
    stand.update(kalender=kalenderliste(root), termine=alle,
                 abgerufen=b.now().isoformat(), status="verbunden")
    _schreiben_stand(root, stand)
    return {"termine": len(alle), "zeit": stand["abgerufen"]}


def uebersicht(root):
    """Was die Oberfläche und das Briefing zeigen — aus dem lokalen Abbild."""
    stand = _lesen_stand(root)
    jetzt = b.now()
    heute, woche, monat = [], [], []
    for termin in stand.get("termine", []):
        beginn = _zeitpunkt(termin.get("beginn"))
        if not beginn:
            continue
        # strftime("%a") spricht Englisch - der Patron liest Deutsch.
        tag = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")[beginn.weekday()]
        eintrag = dict(termin,
                       beginn_lesbar="%s %s" % (tag, beginn.strftime("%d.%m. %H:%M")),
                       beginn_iso=beginn.isoformat())
        tage = (beginn.date() - jetzt.date()).days
        if tage == 0:
            heute.append(eintrag)
        if 0 <= tage <= 7:
            woche.append(eintrag)
        if 0 <= tage <= 30:
            monat.append(eintrag)
    schluessel = lambda x: x["beginn_iso"]
    heute.sort(key=schluessel); woche.sort(key=schluessel); monat.sort(key=schluessel)
    naechster = next((t for t in monat if t["beginn_iso"] >= jetzt.isoformat()), None)
    return {"zeit": jetzt.isoformat(), "status": stand.get("status", "nicht_verbunden"),
            "abgerufen": stand.get("abgerufen", ""),
            "kalender": [k.get("name") for k in stand.get("kalender", [])],
            "heute": heute, "sieben_tage": woche, "dreissig_tage": monat,
            "naechster": naechster,
            "satz": _satz(heute, naechster),
            "quelle": "betrieb/kalender_stand.json (alle fünf Minuten aufgefrischt)"}


def _satz(heute, naechster):
    if heute:
        teil = "Heute %d Termin%s: %s." % (
            len(heute), "" if len(heute) == 1 else "e",
            ", ".join("%s um %s" % (t["titel"], t["beginn_lesbar"].split()[-1]) for t in heute[:3]))
    else:
        teil = "Heute kein Termin."
    if naechster:
        teil += " Als Nächstes: %s am %s." % (naechster["titel"], naechster["beginn_lesbar"])
    return teil


# ---------------------------------------------------------------- Vorschlag
def _ics_bauen(titel, beginn, ende, ort="", beschreibung="", teilnehmer="", uid=None, alarme=None):
    """Baut das .ics mit ausdrücklicher Zeitzone Europe/Vienna.

    F-79: `alarme` ist eine Liste von (zeitpunkt_dt, beschreibung) - je einer wird ein VALARM mit absoluter
    Zeit (Zeitzone Europe/Vienna, kein relativer Trigger - vermeidet Fehler bei ganztaegig/Verschiebung)."""
    uid = uid or (uuid.uuid4().hex + "@jack.gottwald.world")
    form = lambda x: x.strftime("%Y%m%dT%H%M%S")
    zeilen = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//JACK//GOTT WALD HOLDING//DE",
        "CALSCALE:GREGORIAN",
        "BEGIN:VTIMEZONE", "TZID:" + ZONE,
        "BEGIN:STANDARD", "DTSTART:19701025T030000",
        "RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU",
        "TZOFFSETFROM:+0200", "TZOFFSETTO:+0100", "TZNAME:CET", "END:STANDARD",
        "BEGIN:DAYLIGHT", "DTSTART:19700329T020000",
        "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU",
        "TZOFFSETFROM:+0100", "TZOFFSETTO:+0200", "TZNAME:CEST", "END:DAYLIGHT",
        "END:VTIMEZONE",
        "BEGIN:VEVENT",
        "UID:" + uid,
        "DTSTAMP:" + b.now().strftime("%Y%m%dT%H%M%SZ"),
        "DTSTART;TZID=%s:%s" % (ZONE, form(beginn)),
        "DTEND;TZID=%s:%s" % (ZONE, form(ende)),
        "SUMMARY:" + str(titel).replace("\n", " "),
    ]
    if ort:
        zeilen.append("LOCATION:" + str(ort).replace("\n", " "))
    if beschreibung:
        zeilen.append("DESCRIPTION:" + str(beschreibung).replace("\n", "\\n")[:900])
    for wer in [x.strip() for x in str(teilnehmer or "").split(",") if x.strip()]:
        zeilen.append("ATTENDEE;CN=%s:mailto:%s" % (wer, wer))
    for zeitpunkt, alarmtext in (alarme or []):
        if zeitpunkt.tzinfo is None:
            zeitpunkt = zeitpunkt.replace(tzinfo=b.ZONE)
        zeilen += ["BEGIN:VALARM", "ACTION:DISPLAY",
                   "DESCRIPTION:" + str(alarmtext).replace("\n", " ")[:250],
                   "TRIGGER;VALUE=DATE-TIME:" + zeitpunkt.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
                   "END:VALARM"]
    zeilen += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(zeilen) + "\r\n", uid


def vorschlag(root, titel, beginn, ende=None, ort="", beschreibung="",
              teilnehmer="", kalender="", was="anlegen", uid=None, von="JACK", kontext=None):
    """Legt einen Terminvorschlag in den Freigaben-Kasten. Schreibt NICHTS.

    F-99: `kontext` (dict, optional) macht daraus eine vollstaendige Terminkarte: projekt, marke, mit_wem,
    anlass, abhaengigkeit, vorgang, gilt_bei_option, gegenueber (Adresse), betreff_voll, empfehlung_text.
    Mit `kontext` gilt: Pflichtinhalt (mit_wem, ort, anlass) sonst KEINE Karte (Fehlerkarte an PM);
    Dublette (gleicher Beginn + gleiches Gegenueber) -> keine zweite Karte."""
    import jack_freigaben
    if isinstance(beginn, str):
        beginn = dt.datetime.fromisoformat(beginn)
    if beginn.tzinfo is None:
        beginn = beginn.replace(tzinfo=b.ZONE)
    if not ende:
        ende = beginn + dt.timedelta(hours=1)
    elif isinstance(ende, str):
        ende = dt.datetime.fromisoformat(ende)
    if ende.tzinfo is None:
        ende = ende.replace(tzinfo=b.ZONE)
    kontext = kontext or {}
    if kontext:
        fehlt = [f for f, w in (("mit_wem", kontext.get("mit_wem")), ("ort", ort), ("anlass", kontext.get("anlass")))
                 if jack_freigaben.feld_ungueltig(w)]
        if fehlt:
            jack_freigaben._fehlerkarte_schreiben(root, {"art": "kalender", "betreff": titel, "projekt": kontext.get("projekt", "")},
                                                  "Terminkarte UNVOLLSTAENDIG (F-99): Pflichtinhalt fehlt.", fehlt,
                                                  "jack_kalender.vorschlag")
            protokoll(root, "vorschlag_unvollstaendig", titel=titel, fehlt=fehlt)
            return {"ok": False, "unvollstaendig": fehlt, "meldung": "Terminkarte unvollstaendig: " + ", ".join(fehlt)}
        vorhandene = dublette_finden(root, beginn, kontext.get("gegenueber", ""))
        if vorhandene:
            protokoll(root, "vorschlag_dublette", titel=titel, beginn=beginn.isoformat(), vorhandene=vorhandene)
            return {"ok": True, "dublette": vorhandene, "meldung": "Fuer diesen Termin liegt schon eine Karte: " + vorhandene}
    alarme = None
    fahrt = None
    if kontext and ort:
        try:
            import jack_termine as T
            standort = T.standort_lesen(root)["ort"]
            fz = T.fahrzeit_ermitteln(root, standort, ort, beginn, ort_bekannt=True)
            abfahrt = T.abfahrt_berechnen(beginn, fz["minuten"])
            alarme = T.alarme_bauen(beginn, abfahrt, titel, standort, ort)
            fahrt = {"min": fz["minuten"], "geschaetzt": bool(fz.get("geschaetzt")), "abfahrt": abfahrt, "von": standort,
                     "alarme": [(z.strftime("%d.%m. %H:%M"), t) for z, t in alarme]}
        except Exception as fehler:
            protokoll(root, "vorschlag_fahrzeit_fehler", grund=b.redact(str(fehler))[:160])
    text, kennung = _ics_bauen(titel, beginn, ende, ort, beschreibung, teilnehmer, uid, alarme)
    ablage = _area(root) / "kalender_vorschlaege"
    ablage.mkdir(exist_ok=True)
    datei = ablage / (b.now().strftime("%Y-%m-%d_%H%M%S_") +
                      re.sub(r"[^a-zA-Z0-9]+", "-", titel)[:40].strip("-") + ".ics")
    datei.write_text(text, encoding="utf-8")

    kurz = re.sub(r"[^a-zA-Z0-9]+", "_", titel)[:40].strip("_") or "termin"
    was_wort = {"anlegen": "eintragen", "aendern": "ändern", "loeschen": "löschen"}.get(was, was)
    # F-78 (29.09.2026): ueber die zentrale karte_schreiben() mit echten v2-Pflichtfeldern statt der
    # frueheren Altform (nur was/ics/uid/kalender, kein projekt/kern/frage/empfehlung).
    v2 = {
        "projekt": kontext.get("projekt") or "Kalender",
        "marke": kontext.get("marke") or "HOLDING",
        "eingegangen": b.now().strftime("%Y-%m-%d %H:%M"),
        "von": von,
        "an": kalender or "Standardkalender",
        "art": "kalender",
        "betreff": "Termin %s: %s" % (was_wort, titel),
        "kern": "%s am %s, %s bis %s Uhr%s." % (titel,
                beginn.strftime("%d.%m.%Y"), beginn.strftime("%H:%M"), ende.strftime("%H:%M"),
                (" in %s" % ort) if ort else ""),
        "frage": "Termin so %s?" % was_wort,
        "empfehlung": kontext.get("empfehlung_text") or "FREIGEBEN trägt den Termin in iCloud ein.",
        "frist": "keine",
        "dringlichkeit": "niedrig",
        "ablauf": "FREIGEBEN trägt den Termin in iCloud ein. ÄNDERN öffnet die Felder. "
                  "ABLEHNEN verwirft ihn. Ohne Freigabe wird nichts geschrieben.",
        # F-78-Nachbesserung: diese drei technischen Felder liest schreiben() beim FREIGEBEN direkt aus
        # der Karte (kopf.get("ics"/"was"/"uid")) - gingen bei der Migration verloren und haetten
        # sonst die falsche .ics gesucht, immer "anlegen" statt aendern/loeschen angenommen und beim
        # Aendern/Loeschen eine neue UID statt der echten verwendet (doppelte/falsche Kalendereintraege).
        "was": was, "ics": datei.name, "uid": kennung,
    }
    if kontext:
        # F-99: Kalendereintrag geht nicht nach aussen (keine Mail) -> INTERN; Terminfelder fuer Anzeige, Dublettenpruefung, Vorgang.
        v2.update({"gefahr": "keine", "label": "INTERN", "termin": beginn.isoformat(), "termin_ort": ort,
                   "termin_mit": kontext.get("mit_wem", ""), "termin_anlass": kontext.get("anlass", ""),
                   "gegenueber": kontext.get("gegenueber", ""), "zeitzone": ZONE})
        if kontext.get("abhaengigkeit"):
            v2["abhaengigkeit"] = kontext["abhaengigkeit"]
        if kontext.get("vorgang"):
            v2["vorgang"] = kontext["vorgang"]
            v2["fuehrend"] = "nein"
        if kontext.get("gilt_bei_option"):
            v2["gilt_bei_option"] = kontext["gilt_bei_option"]
        if fahrt:
            v2.update({"fahrzeit_min": str(fahrt["min"]), "fahrzeit_quelle": "geschaetzt" if fahrt["geschaetzt"] else "gemessen",
                       "abfahrt": fahrt["abfahrt"].isoformat(), "abfahrt_von": fahrt["von"]})
        if kontext.get("betreff_voll"):
            v2["betreff"] = "Termin %s: %s" % (was_wort, kontext["betreff_voll"])
    pfad = jack_freigaben.karte_schreiben(root, v2, "\n".join([
        "## Auftrag",
        "Termin %s: **%s**" % (was_wort, titel),
        "",
        "| Feld | Wert |",
        "|---|---|",
        "| Datum | %s, %s |" % (("Montag","Dienstag","Mittwoch","Donnerstag",
                                 "Freitag","Samstag","Sonntag")[beginn.weekday()],
                                beginn.strftime("%d.%m.%Y")),
        "| Uhrzeit | %s bis %s Uhr |" % (beginn.strftime("%H:%M"), ende.strftime("%H:%M")),
        "| Dauer | %d Minuten |" % round((ende - beginn).total_seconds() / 60),
        "| Ort | %s |" % (ort or "—"),
        "| Teilnehmer | %s |" % (teilnehmer or "—"),
        "| Kalender | %s |" % (kalender or "Standardkalender"),
        "| Zeitzone | %s |" % ZONE,
    ] + ([
        "| Mit wem | %s |" % kontext.get("mit_wem", ""),
        "| Anlass | %s |" % kontext.get("anlass", ""),
        "| Abhängigkeit | %s |" % (kontext.get("abhaengigkeit") or "keine offene Entscheidung"),
        "| Fahrzeit | %s |" % (("%d Min ab %s (%s) — Abfahrt %s" % (fahrt["min"], fahrt["von"], "geschätzt" if fahrt["geschaetzt"] else "gemessen",
                                fahrt["abfahrt"].strftime("%H:%M"))) if fahrt else "—"),
        "| Alarme | %s |" % ("; ".join("%s: %s" % a for a in fahrt["alarme"]) if fahrt else "—"),
        "| Label | INTERN — nichts geht nach aussen |",
    ] if kontext else []) + [
        "",
        "## Prüfpunkte",
        "FREIGEBEN trägt den Termin in iCloud ein. ÄNDERN öffnet die Felder. "
        "ABLEHNEN verwirft ihn. Ohne Freigabe wird nichts geschrieben.",
        "",
    ] + (_empfehlung_abschnitt(beginn, ort, kontext, fahrt) if kontext else [])), herkunft="jack_kalender.vorschlag", unterordner=None,
       dateiname="%s_KALENDER_%s_%s.md" % (b.now().strftime("%Y-%m-%d_%H%M%S"), was, kurz))
    if pfad is None:
        return {"ok": False, "meldung": "Kartenkopf unvollstaendig - siehe Fehlerkarte in abnahme/pm_eingang/."}
    name = pfad.name
    try:
        jack_freigaben.anfordern(root, name, grund="Terminvorschlag: " + titel)
    except Exception:
        pass
    protokoll(root, "vorschlag", was=was, titel=titel, uid=kennung,
              beginn=beginn.isoformat(), datei=name, von=von)
    return {"ok": True, "datei": name, "ics": datei.name, "uid": kennung,
            "beginn": beginn.isoformat(), "ende": ende.isoformat(),
            "meldung": "Liegt zur Freigabe."}


# ---------------------------------------------------------------- F-99: nur echte Termine, mit Kontext
def _adresse(roh):
    import email.utils
    return email.utils.parseaddr(str(roh or ""))[1].strip().lower()


def ist_testmail(kopf, text=""):
    """True bei '[TEST]' im Betreff, dem Testhinweis von JACK im Text, einem Kopf `testversand:` oder einem
    eigenen Absender (Patron-Testadresse / gottwald.world). Daraus entsteht nie eine Terminkarte."""
    betreff = str((kopf or {}).get("betreff") or "")
    if re.search(r"\[test\]", betreff, re.I):
        return True
    if "TESTVERSAND — diese Mail ging NUR an dich" in str(text or ""):
        return True
    if str((kopf or {}).get("testversand") or "").strip():
        return True
    adr = _adresse((kopf or {}).get("absender"))
    return bool(adr) and (adr == "gottwald.mathias@icloud.com" or adr.endswith("@gottwald.world") or adr.endswith(".gottwald.world"))


def _kartenkoepfe(root):
    """-> [(dateiname, kopf, text)] der offenen Freigabekarten (nicht ersetzt/, keine Sicherungen)."""
    import jack_oberflaeche as O
    return [(f.name, k, t) for f, k, t in O._auftragsdateien(root, "freigabe")]


def dublette_finden(root, beginn, gegenueber=""):
    """Dateiname einer offenen Karte mit demselben Beginn (Datum+Uhrzeit) und demselben Gegenueber, sonst ''.
    Ist das Gegenueber unbekannt, genuegt gleicher Beginn."""
    adr = _adresse(gegenueber) or str(gegenueber or "").strip().lower()
    for name, k, _t in _kartenkoepfe_sicher(root):
        roh = k.get("termin", "").strip()
        if not roh:
            continue
        try:
            fremd = dt.datetime.fromisoformat(roh)
        except ValueError:
            continue
        if fremd.tzinfo is None:
            fremd = fremd.replace(tzinfo=b.ZONE)
        if fremd != beginn:
            continue
        if not adr:
            return name
        felder = " ".join(str(k.get(f, "")) for f in ("von", "an", "gegenueber", "termin_mit")).lower()
        if adr in felder or adr.split("@")[-1] in felder:
            return name
    return ""


def _kartenkoepfe_sicher(root):
    try:
        return _kartenkoepfe(root)
    except Exception:
        return []


def kontext_aus_karten(root, absender, beginn=None):
    """Sucht die offene Karte desselben Gegenuebers (Adresse in von/an/gegenueber) und uebernimmt projekt, marke,
    vorgang, Ort. Abhaengigkeit als Satz, wenn der Vorgang eine offene Auswahl (fuehrende Karte mit Optionen) hat."""
    adr = _adresse(absender)
    treffer = None
    for name, k, _t in _kartenkoepfe_sicher(root):
        if k.get("art", "") == "kalender" or not adr:
            continue
        if adr in " ".join(str(k.get(f, "")) for f in ("von", "an", "gegenueber")).lower():
            treffer = (name, k)
            if k.get("vorgang"):
                break
    kontext = {"gegenueber": adr}
    if not treffer:
        return kontext
    name, k = treffer
    kontext["projekt"] = k.get("projekt", "")
    kontext["marke"] = k.get("marke", "")
    kontext["ort_karte"] = k.get("termin_ort", "")
    kontext["firma"] = k.get("firma", "")
    vg = k.get("vorgang", "").strip()
    if vg:
        kontext["vorgang"] = vg
        try:
            import jack_freigabe_vorgang as V
            karten = V._karten(root)
            fuehr = next((n for n, (_f, kk, _t) in karten.items()
                          if kk.get("vorgang", "").strip() == vg and kk.get("fuehrend", "").strip().lower() == "ja"), None)
            if fuehr:
                kopf_f = karten[fuehr][1]
                opts = V.optionen(kopf_f, karten)
                eigene = next((o for o in opts if name in o["karten"]), None)
                titel_f = V._titel(kopf_f, fuehr)
                if eigene:
                    kontext["gilt_bei_option"] = eigene["key"]
                    kontext["abhaengigkeit"] = "Gilt nur, wenn %s gewählt wird (offene Entscheidung: %s)." % (eigene["titel"], titel_f)
                else:
                    kontext["abhaengigkeit"] = "Hängt an der offenen Entscheidung: %s." % titel_f
        except Exception:
            pass
    return kontext


def _empfehlung_abschnitt(beginn, ort, kontext, fahrt):
    """Empfehlung NUR aus geprueften Kopffeldern - kein Modelltext, keine erfundenen Rollen (F-99 Punkt F)."""
    warum = "Datum %s %s Uhr, Ort %s, Gegenüber %s stehen so in der Quelle." % (
        beginn.strftime("%d.%m.%Y"), beginn.strftime("%H:%M"), ort, kontext.get("mit_wem", ""))
    abh = kontext.get("abhaengigkeit")
    return [
        "## Empfehlung von JACK",
        "",
        "**Entscheid:** %s" % ("WARTEN" if abh else "FREIGEBEN"),
        "**Empfehlung:** %s" % (("Erst die offene Entscheidung treffen; danach den Termin eintragen. " + abh) if abh
                                 else "Termin eintragen."),
        "**Warum:** %s" % warum,
        "**Bei Ja:** Der Termin steht als INTERN im iCloud-Kalender%s. Es geht keine Mail hinaus." % (
            (" mit Alarm am Vortag 18:00 und zur Abfahrt (%s)" % fahrt["abfahrt"].strftime("%H:%M")) if fahrt else ""),
        "**Bei Nein:** Kein Kalendereintrag; die Karte wird verworfen.",
        "",
        "_Aus geprüften Kopffeldern, ohne Modell erzeugt (F-99)._",
        "",
    ]


_ORT_RE = re.compile(r"(?:Ort|Adresse|Treffpunkt)\s*:\s*(.+)|(\S[^\n,]{2,60}\d{1,3}[a-z]?,\s*\d{5}\s+[A-ZÄÖÜ][\w\-\.äöüß ]{2,30})")


def vorschlag_aus_mail(root, kopf, text, nachricht=None):
    """Terminanfrage oder .ics im Anhang → Vorschlag für den Patron. F-99: nie aus Testmails, nie doppelt,
    immer mit Kontext (Projekt/Marke/Gegenüber/Ort/Abhängigkeit/Fahrzeit)."""
    if ist_testmail(kopf, text):
        protokoll(root, "vorschlag_testmail_uebersprungen", betreff=str(kopf.get("betreff", ""))[:120])
        return None
    beginn = None
    titel = None
    roh_ort = ""
    if nachricht is not None and nachricht.is_multipart():
        for teil in nachricht.walk():
            name = (teil.get_filename() or "").lower()
            if name.endswith(".ics"):
                try:
                    roh = teil.get_payload(decode=True).decode("utf-8", errors="replace")
                    gefunden = _ics_lesen(roh)
                    if gefunden:
                        beginn = _zeitpunkt(gefunden[0]["beginn"])
                        titel = gefunden[0]["titel"]
                        roh_ort = str(gefunden[0].get("ort", "") or "")
                        if beginn:
                            break
                except Exception:
                    beginn = None
    if not beginn:
        treffer = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4}).{0,12}?(\d{1,2})[:.](\d{2})", str(text or ""))
        if treffer:
            t, m, j, st, mi = (int(x) for x in treffer.groups())
            try:
                beginn = dt.datetime(j, m, t, st, mi, tzinfo=b.ZONE)
            except ValueError:
                beginn = None
    if not beginn:
        return None
    absender = str(kopf.get("absender", ""))
    kontext = kontext_aus_karten(root, absender, beginn)
    ort = roh_ort.strip()
    if not ort:
        gefunden_ort = _ORT_RE.search(str(text or ""))
        if gefunden_ort:
            ort = (gefunden_ort.group(1) or gefunden_ort.group(2) or "").strip()
    ort = ort or kontext.get("ort_karte", "")
    import email.utils
    anzeige = email.utils.parseaddr(absender)[0].strip() or _adresse(absender)
    kontext["mit_wem"] = anzeige + ((" — " + kontext["firma"]) if kontext.get("firma") else "")
    betreff = str(kopf.get("betreff") or "Termin")              # F-99: Betreff nie kuerzen
    kontext["anlass"] = betreff
    kontext["betreff_voll"] = betreff
    if not kontext.get("projekt"):
        kontext.pop("projekt", None)
        kontext.pop("marke", None)
    return vorschlag(root, titel or betreff, beginn, ort=ort,
                     beschreibung="Aus Mail von " + absender, von=_adresse(absender) or absender, kontext=kontext)


# ---------------------------------------------------------------- Schreiben
def _ics_felder_stehen(vorschlag, kalender_text):
    """True, wenn DTSTART, DTEND und SUMMARY des Vorschlags wortgleich im Kalendertext stehen (Nachweis fuer 'aendern')."""
    def felder(t):
        aus = {}
        for zeile in str(t).replace("\r", "").split("\n"):
            k, _, w = zeile.partition(":")
            k = k.split(";")[0].strip().upper()
            if k in ("DTSTART", "DTEND", "SUMMARY", "SEQUENCE"):
                aus[k] = zeile.strip()
        return aus
    soll, ist = felder(vorschlag), felder(kalender_text)
    pruef = [k for k in ("DTSTART", "DTEND", "SUMMARY") if k in soll]
    return bool(pruef) and all(ist.get(k) == soll[k] for k in pruef)


def schreiben(root, freigabedatei, von="Patron"):
    """Trägt einen FREIGEGEBENEN Vorschlag in iCloud ein.

    Diese Funktion ist der EINZIGE Weg, auf dem JACK in den Kalender schreibt.
    Sie verlangt eine Freigabedatei aus auftraege/ und prüft deren Kopf. Ohne
    diesen Weg gibt es keinen Schreibzugriff — auch nicht auf Lernstufe 3.
    """
    kopf = _freigabekopf(root, freigabedatei)
    if kopf.get("art") != "kalender":
        raise ValueError("Das ist kein Terminvorschlag")
    if kopf.get("freigabe") != "ja":
        return {"ok": False, "meldung": "Dieser Termin ist noch nicht freigegeben."}
    ics = _area(root) / "kalender_vorschlaege" / kopf.get("ics", "")
    was = kopf.get("was", "anlegen")
    stand = _lesen_stand(root)
    kalender = stand.get("kalender") or []
    if not kalender:
        return {"ok": False, "meldung": "Kein Kalender verbunden. "
                                        "Der Termin bleibt als Vorschlag liegen."}
    pfad = kalender[0]["pfad"].rstrip("/") + "/" + kopf.get("uid", uuid.uuid4().hex) + ".ics"
    try:
        if was == "loeschen":
            status, _ = _anfrage(root, "DELETE", pfad)
        else:
            status, _ = _anfrage(root, "PUT", pfad, ics.read_text(encoding="utf-8"),
                                 {"Content-Type": "text/calendar; charset=utf-8"})
    except jack_netzwiederholung.AntwortZeit:
        # S-3c P5c: Zeitlimit NACH dem Senden - der Termin kann angekommen sein. Nicht "Nichts geaendert" melden, nicht erneut schreiben:
        # lesend nachsehen.
        try:
            g_status, g_text = _anfrage(root, "GET", pfad)
        except Exception:
            return {"ok": False, "unklar": True, "meldung": "Ich weiß nicht sicher, ob der Termin angekommen ist. Ich konnte gerade auch nicht nachsehen - bitte in ein paar Minuten noch einmal fragen; ich schreibe nichts ein zweites Mal."}
        if was == "loeschen":
            angekommen = (g_status == 404)
        elif was == "aendern":
            # GET 200 beweist bei 'aendern' nur, dass der ALTE Termin existiert: die Kernfelder des Vorschlags muessen im Kalender stehen
            angekommen = (g_status == 200) and _ics_felder_stehen(ics.read_text(encoding="utf-8"), g_text)
        else:
            angekommen = (g_status == 200)
        if not angekommen:
            return {"ok": False, "unklar": True, "meldung": "Ich weiß nicht sicher, ob der Termin angekommen ist, ich habe nachgesehen: er steht nicht im Kalender. Ich habe nichts ein zweites Mal geschrieben - sag Bescheid, dann versuche ich es erneut."}
        status = 201            # nachgeprueft angekommen: weiter wie bei Erfolg
    except Exception:
        return {"ok": False, "meldung": "Apple war nicht erreichbar. Nichts geändert."}
    if status not in (200, 201, 204):
        return {"ok": False, "meldung": _klartext(status)}
    protokoll(root, was, uid=kopf.get("uid"), von=von, datei=freigabedatei,
              kalender=kalender[0]["name"])
    try:
        abrufen(root)
    except Exception:
        pass
    return {"ok": True, "meldung": "Termin %s." % {"anlegen": "eingetragen",
            "aendern": "geändert", "loeschen": "gelöscht"}.get(was, was)}


def _ics_sichern(root, uid, roh_ics):
    """M-7 (Befund Nr. 7, cashflow_2.md): vor jedem Ueberschreiben eines JACK-eigenen Kalendereintrags das
    aktuell LIVE im Kalender stehende .ics wegsichern - falls der Patron den Eintrag von Hand geaendert
    hat (Ort, Uhrzeit, eigene Notiz), ginge das sonst stillschweigend beim naechsten automatischen
    Ueberschreiben verloren. Reiner Best-Effort: ein Fehler hier bricht den eigentlichen Schreibvorgang nie."""
    try:
        ordner = _area(root) / "kalender_sicherung"
        ordner.mkdir(parents=True, exist_ok=True)
        zeit = b.now().strftime("%Y%m%d_%H%M%S")
        ziel = ordner / ("%s_%s.ics" % (uid, zeit))
        ziel.write_text(roh_ics, encoding="utf-8")
        protokoll(root, "termin_ics_gesichert", uid=uid, sicherung=str(ziel))
    except Exception as fehler:
        protokoll(root, "termin_ics_sicherung_fehlgeschlagen", uid=uid, grund=str(fehler)[:160])


def schreiben_aus_termin(root, ics_text, uid, was="anlegen", von="Patron", grund="Mail-Freigabe (F-79)"):
    """F-79-Ausnahme (siehe Kopfkommentar): schreibt einen bereits gebauten .ics-Text (mit LOCATION + VALARM,
    aus jack_termine.py) direkt, OHNE eigene Kalender-Freigabekarte - der Aufrufer hat die Freigabekette der
    verknuepften Mail-Karte bereits geprueft. Sonst identisch zu schreiben(): derselbe CalDAV-PUT, dieselbe
    Fehlerbehandlung, dasselbe Protokoll.

    M-7 (Befund Nr. 7): bei `was="aendern"` wird das aktuell LIVE gespeicherte .ics VOR dem Ueberschreiben
    per GET gelesen und unter betrieb/kalender_sicherung/ abgelegt - vorher gab es keine Sicherung des
    tatsaechlich im Kalender stehenden Standes, nur (beim automatischen Aenderungsweg in jack_termine.py)
    eine Kopie der eigenen Akte, was Patron-Handaenderungen direkt IM Kalender nicht erfasst haette."""
    stand = _lesen_stand(root)
    kalender = stand.get("kalender") or []
    if not kalender:
        return {"ok": False, "meldung": "Kein Kalender verbunden. Der Termin bleibt nur in der Akte."}
    pfad = kalender[0]["pfad"].rstrip("/") + "/" + uid + ".ics"
    if was == "aendern":
        try:
            g_status, g_text = _anfrage(root, "GET", pfad)
            if g_status == 200 and g_text:
                _ics_sichern(root, uid, g_text)
        except Exception:
            pass  # Sicherung ist Best-Effort - ein Fehler hier darf die eigentliche Aenderung nie blockieren.
    try:
        status, _ = _anfrage(root, "PUT", pfad, ics_text, {"Content-Type": "text/calendar; charset=utf-8"})
    except jack_netzwiederholung.AntwortZeit:
        try:
            g_status, g_text = _anfrage(root, "GET", pfad)
        except Exception:
            return {"ok": False, "unklar": True, "meldung": "Ich weiß nicht sicher, ob der Termin angekommen ist. Nichts ein zweites Mal geschrieben."}
        angekommen = (g_status == 200) and _ics_felder_stehen(ics_text, g_text)
        if not angekommen:
            return {"ok": False, "unklar": True, "meldung": "Ich weiß nicht sicher, ob der Termin angekommen ist, ich habe nachgesehen: er steht nicht (oder anders) im Kalender."}
        status = 201
    except Exception:
        return {"ok": False, "meldung": "Apple war nicht erreichbar. Nichts geändert."}
    if status not in (200, 201, 204):
        return {"ok": False, "meldung": _klartext(status)}
    protokoll(root, "termin_" + was, uid=uid, von=von, grund=grund, kalender=kalender[0]["name"])
    try:
        abrufen(root)
    except Exception:
        pass
    return {"ok": True, "meldung": "Termin %s (mit der Mail-Freigabe, F-79)." % {
        "anlegen": "eingetragen", "aendern": "geändert"}.get(was, was)}


def _freigabekopf(root, datei):
    for ordner in ("freigabe", "offen", "erledigt"):
        p = Path(root) / "auftraege" / ordner / str(datei)
        if p.is_file() and not p.is_symlink():
            kopf = {}
            for zeile in p.read_text(encoding="utf-8").splitlines()[1:]:
                if zeile.strip() == "---":
                    break
                k, _, w = zeile.partition(":")
                kopf[k.strip().lower()] = w.strip()
            return kopf
    raise ValueError("Diese Freigabedatei gibt es nicht")


def tick(root, at=None):
    """Hängt sich in die bestehende Fünf-Minuten-Routine ein."""
    stand = _lesen_stand(root)
    if stand.get("status") != "verbunden":
        return []
    try:
        abrufen(root)
    except Exception:
        pass
    return []


if __name__ == "__main__":
    import sys
    wurzel = Path(__file__).resolve().parent
    was = sys.argv[1] if len(sys.argv) > 1 else "uebersicht"
    if was == "uebersicht":
        print(json.dumps(uebersicht(wurzel), ensure_ascii=False, indent=1))
    elif was == "verbinden":
        print(json.dumps(verbinden(wurzel), ensure_ascii=False))
    elif was == "vorschlag":
        print(json.dumps(vorschlag(wurzel, sys.argv[2], sys.argv[3]), ensure_ascii=False))
    else:
        print("uebersicht | verbinden | vorschlag <titel> <iso-beginn>")
