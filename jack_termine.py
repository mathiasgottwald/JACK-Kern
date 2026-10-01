#!/usr/bin/env python3
"""F-79 (28.09.2026): Termin-Workflow - Termin-Akte, Fahrzeit (Google Maps Routes API + Rückfall-Tabelle),
Abfahrt/Alarme, automatische Änderung durch die Gegenseite (Patron-Anordnung 18:30, siehe jack_kalender.py
Kopfkommentar). Kein eigener Schreibweg in den Kalender - baut nur die Akte/das .ics und ruft
jack_kalender.schreiben_aus_termin() bzw. schreiben() auf.

Nichts wird aus der Akte gelöscht: ein abgesagter Termin bekommt status="abgesagt", der Kalendereintrag wird
"ABGESAGT: <Titel>" umbenannt, nicht entfernt. Jede Änderung landet im memo-Verlauf (Zeit, Grund, alt→neu,
Quelle) - die Akte ist das Gedächtnis, nicht nur der Kalender.
"""
import datetime as dt
import json
import re
import shutil
import subprocess
from pathlib import Path

import jack_betrieb as b

AKTEN_ORDNER = "termine"
STANDORT_DATEI = "standort.json"
FAHRZEITEN_TABELLE = "fahrzeiten_tabelle.json"
KOSTEN_PROTOKOLL = "kosten_fahrzeit.jsonl"
PUFFER_MIN = 30
PARKEN_MIN = 10

# Zweite Opus-Endpruefung F-79 (28.09.2026, nur lesend): §4 (automatische Aenderung durch die Gegenseite)
# war NICHT freigabefaehig - B1 (stiller Fehlschlag bei RUECKGAENGIG) und B2 (Knopfbeschriftung) sind
# seither behoben (siehe abnahme/MASTERMIND/cashflow_2.md, F-79_MELDUNG). Stand M-7 (29.09.2026,
# cashflow_2.md, eigene Arbeitskopie): C1 (ungebundene Erkennung an zitiertem Ursprungstext) ist jetzt
# ebenfalls behoben (siehe _ohne_zitat). C2 (Bindung an In-Reply-To/References der konkreten Antwortmail)
# ist nur ABGESCHWAECHT, nicht vollstaendig geloest - die noetige Message-ID entsteht erst in
# jack_oberflaeche.py (kern-Datei, ausserhalb dieser Arbeitskopie), siehe Kommentar bei
# GEGENSEITE_AENDERUNG_FENSTER_TAGE. C4 (Kollision gleichtaegiger Memo-Karten) ist weiterhin offen.
# Bis C2 vollstaendig und C4 geloest sind, bleibt der Hook in jack_postfaecher._verarbeiten() ABGESCHALTET -
# der Kalender des Patrons wird nie automatisch veraendert. Der Weg ueber die Mail-Freigabe (§2, ein
# FREIGEBEN = Mail + Kalender) ist davon NICHT betroffen und bleibt aktiv. Nur der Patron/Hausherr schaltet
# dies wieder ein.
AUTOMATISCHE_AENDERUNG_AKTIV = False

TERMINZUSAGE_MUSTER = re.compile(
    r"(\d{1,2})\.(\d{1,2})\.(\d{4}).{0,20}?(\d{1,2})[:.](\d{2})\s*Uhr", re.S)
# Opus-Endprüfung F-79: "leider" ALLEIN war zu schwach (jede Ablehnung/Rückfrage enthält es oft) und loeste
# faelschlich eine Aenderung aus. Jetzt nur noch Formulierungen, die tatsaechlich eine NEUE Zeit ankuendigen.
AENDERUNG_WOERTER = re.compile(
    r"verschieben (?:auf|müssen)|stattdessen (?:um|am)|neuer Termin (?:um|am)|"
    r"geht (?:es )?(?:leider )?(?:erst |nur )?um \d", re.I)
RUECKFRAGE_MUSTER = re.compile(
    r"alternativ|welch(?:er|en) Termin|passt (?:das|es|Ihnen)|können Sie|schlagen Sie|\?", re.I)


# ------------------------------------------------------------------ Akte
def _area(root):
    return b.area(root)


def _akten_ordner(root):
    p = _area(root) / AKTEN_ORDNER
    p.mkdir(parents=True, exist_ok=True)
    return p


def akte_pfad(root, datum, kurz):
    """datum: YYYY-MM-DD oder datetime; kurz: kurzer, dateisicherer Name."""
    if hasattr(datum, "strftime"):
        datum = datum.strftime("%Y-%m-%d")
    kurz = re.sub(r"[^a-zA-Z0-9]+", "_", kurz).strip("_")[:40] or "termin"
    return _akten_ordner(root) / ("%s_%s.json" % (datum, kurz))


def akte_lesen(pfad):
    pfad = Path(pfad)
    if not pfad.is_file():
        return None
    return json.loads(pfad.read_text(encoding="utf-8"))


def akte_schreiben(pfad, akte):
    pfad = Path(pfad)
    pfad.write_text(json.dumps(akte, ensure_ascii=False, indent=2), encoding="utf-8")


def akte_anlegen(root, id_, titel, projekt, marke, gegenseite, beginn, ende, ort, quelle, datum=None, kurz=None):
    """Legt eine neue Termin-Akte an (status: vorgeschlagen). -> Pfad."""
    if isinstance(beginn, dt.datetime):
        beginn_iso = beginn.isoformat()
    else:
        beginn_iso = beginn
    pfad = akte_pfad(root, datum or beginn_iso[:10], kurz or id_)
    akte = {
        "id": id_, "titel": titel, "projekt": projekt, "marke": marke, "gegenseite": gegenseite,
        "beginn": beginn_iso, "ende": ende.isoformat() if isinstance(ende, dt.datetime) else ende,
        "ort": ort, "quelle": quelle, "status": "vorgeschlagen", "kalender_uid": None,
        "fahrzeit": None, "abfahrt": None, "alarme": [], "memo": [],
        "angelegt_am": b.now().isoformat(),
    }
    akte_schreiben(pfad, akte)
    return pfad


def _memo_anhaengen(akte, grund, alt, neu, quelle):
    akte.setdefault("memo", []).append({
        "zeit": b.now().isoformat(), "grund": grund, "alt": alt, "neu": neu, "quelle": quelle,
    })


# ------------------------------------------------------------------ Terminzusage-Erkennung
def terminzusage_erkennen(text):
    """-> (datum_dt, roh) oder None. Erkennt 'DD.MM.YYYY ... HH:MM Uhr' im Text - keine Ableitung ohne Beleg."""
    m = TERMINZUSAGE_MUSTER.search(str(text or ""))
    if not m:
        return None
    t, mo, j, h, mi = (int(x) for x in m.groups())
    try:
        return dt.datetime(j, mo, t, h, mi, tzinfo=b.ZONE), m.group(0)
    except ValueError:
        return None


_ZITAT_GRENZE = re.compile(
    r"(?:^|\n)[ \t]*Am\s.{0,60}?schrieb\s.{0,80}?:[ \t]*\n|"
    r"(?:^|\n)[ \t]*On\s.{0,60}?wrote:[ \t]*\n|"
    r"(?:^|\n)-{2,}[ \t]*Urspr(?:ü|ue)ngliche Nachricht[ \t]*-{2,}",
    re.I)


def _ohne_zitat(text):
    """M-7 (Befund Nr. 5/C1, cashflow_2.md): eine zitierte Ursprungsmail unter der eigentlichen Antwort
    enthaelt oft selbst eine Uhrzeit (die ALTE) - ohne diesen Schnitt konnte `aenderung_eindeutig` die
    zitierte alte Zeit statt der tatsaechlich neuen Zeit aus der eigentlichen Antwort lesen, oder zwei
    Treffer (neu + zitiert alt) faelschlich als 'uneindeutig' werten und die echte Aenderung verschlucken.
    Schneidet an der ersten erkannten Zitatgrenze ab und entfernt zusaetzlich einzelne '>'-Zitatzeilen."""
    text = str(text or "")
    grenze = _ZITAT_GRENZE.search(text)
    if grenze:
        text = text[:grenze.start()]
    zeilen = [z for z in text.split("\n") if not z.lstrip().startswith(">")]
    return "\n".join(zeilen)


def aenderung_eindeutig(text):
    """-> (eindeutig: bool, neuer_zeitpunkt|None). Eine Aenderung ist nur eindeutig, wenn GENAU EINE neue
    Zeit im Text steht - zwei Vorschlaege oder eine Rueckfrage der Gegenseite gelten als uneindeutig.

    M-7 (Befund Nr. 5/C1): prueft nur noch den Teil VOR einer erkannten Zitatgrenze/ohne '>'-Zeilen -
    eine mitgeschickte alte Zeit aus der zitierten Ursprungsmail zaehlt nicht mehr mit."""
    text = _ohne_zitat(text)
    treffer = list(TERMINZUSAGE_MUSTER.finditer(text))
    # "es geht um 11 Uhr" (Patron-Beispiel, F-79-Auftrag) - auch ohne Minuten gueltig, dann :00.
    zeiten_ohne_datum = list(re.finditer(r"(?<!\d)(\d{1,2})(?:[:.](\d{2}))?\s*Uhr", text))
    hinweis = bool(AENDERUNG_WOERTER.search(text))
    if not hinweis:
        return False, None
    # Opus-Endprüfung F-79: eine Rueckfrage ("koennen Sie einen anderen Termin nennen?") bleibt uneindeutig,
    # selbst wenn irgendwo eine Uhrzeit im Text steht - eine Frage ist keine feste Zusage.
    if RUECKFRAGE_MUSTER.search(text):
        return False, None
    if len(treffer) == 1:
        m = treffer[0]
        t, mo, j, h, mi = (int(x) for x in m.groups())
        try:
            return True, dt.datetime(j, mo, t, h, mi, tzinfo=b.ZONE)
        except ValueError:
            return False, None
    if len(treffer) == 0 and len(zeiten_ohne_datum) == 1:
        # "es geht um 11 Uhr" - dasselbe Datum, nur die Uhrzeit aendert sich; der Aufrufer setzt das Datum.
        h_roh, mi_roh = zeiten_ohne_datum[0].groups()
        h, mi = int(h_roh), int(mi_roh or 0)
        return True, ("UHRZEIT_NUR", h, mi)
    return False, None  # 0 oder >1 Treffer: uneindeutig, keine automatische Aenderung


# ------------------------------------------------------------------ Standort
def standort_lesen(root):
    p = _area(root) / STANDORT_DATEI
    if not p.is_file():
        return {"ort": "Neubeuern", "gesetzt_am": None, "quelle": "Standard"}
    return json.loads(p.read_text(encoding="utf-8"))


def standort_setzen(root, ort, quelle="Dashboard"):
    p = _area(root) / STANDORT_DATEI
    daten = {"ort": ort, "gesetzt_am": b.now().isoformat(), "quelle": quelle}
    p.write_text(json.dumps(daten, ensure_ascii=False, indent=2), encoding="utf-8")
    return daten


# ------------------------------------------------------------------ Fahrzeit
def _schluessel_google_maps():
    try:
        r = subprocess.run(["security", "find-generic-password", "-a", "GOTT_WALD_GOOGLE_MAPS",
                           "-s", "GOTT_WALD_GOOGLE_MAPS", "-w"], capture_output=True, text=True, timeout=10)
        return r.stdout.strip() or None
    except Exception:
        return None


def _tabelle_lesen(root):
    p = _area(root) / FAHRZEITEN_TABELLE
    if not p.is_file():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def _tabellenminuten(tabelle, start, ziel):
    """F-90 (M-Cashflow Nr. 1): der Schluessel der Tabelle ist '<Stadt>↔<Stadt>', das Ziel aber oft eine volle Adresse
    (Strasse, PLZ, Ort). Erst exakt, dann: Tabellenstadt steckt im Ziel-/Startstring."""
    for k in ("%s↔%s" % (start, ziel), "%s↔%s" % (ziel, start)):
        if tabelle.get(k) is not None:
            return tabelle[k]
    s_, z_ = str(start or "").lower(), str(ziel or "").lower()
    for schluessel, minuten in tabelle.items():
        if "↔" not in schluessel:
            continue
        a, b_ = [t.strip().lower() for t in schluessel.split("↔", 1)]
        if a and b_ and ((a in s_ and b_ in z_) or (a in z_ and b_ in s_)):
            return minuten
    return None


def fahrzeit_ermitteln(root, start, ziel, abfahrt_zeit=None, ort_bekannt=True):
    """`ort_bekannt=False` (Opus-Endprüfung F-79): das Ziel ist nur eine Annahme (z. B. "Rosenheim" als
    Rückfall, weil termin_ort fehlte) - dann NIE Google fragen (das Ergebnis waere zwar echt gemessen, aber
    fuer die falsche Adresse) und das Ergebnis bleibt ausdruecklich "geschaetzt"."""
    if not ort_bekannt:
        tabelle = _tabelle_lesen(root)
        minuten = _tabellenminuten(tabelle, start, ziel) or 60
        return {"minuten": minuten, "quelle": "ort_unbekannt_geschaetzt", "geschaetzt": True}
    return _fahrzeit_ermitteln_mit_bekanntem_ort(root, start, ziel, abfahrt_zeit)


def _fahrzeit_ermitteln_mit_bekanntem_ort(root, start, ziel, abfahrt_zeit=None):
    """-> {"minuten": int, "quelle": "google_maps"|"tabelle_geschaetzt", "geschaetzt": bool}.
    Versucht Google Maps Routes API (Schluessel im Schluesselbund); ohne Schluessel oder bei Fehler: Rueckfall
    auf betrieb/fahrzeiten_tabelle.json, IMMER als "geschaetzt" gekennzeichnet - nie als gemessen ausgegeben,
    wenn es das nicht ist."""
    schluessel = _schluessel_google_maps()
    if schluessel:
        try:
            import urllib.request
            rumpf = json.dumps({
                "origin": {"address": start}, "destination": {"address": ziel},
                "travelMode": "DRIVE", "routingPreference": "TRAFFIC_AWARE",
                "departureTime": (abfahrt_zeit or b.now()).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }).encode()
            anfrage = urllib.request.Request(
                "https://routes.googleapis.com/directions/v2:computeRoutes", data=rumpf,
                headers={"Content-Type": "application/json", "X-Goog-Api-Key": schluessel,
                         "X-Goog-FieldMask": "routes.duration"}, method="POST")
            with urllib.request.urlopen(anfrage, timeout=10) as antwort:
                daten = json.loads(antwort.read().decode())
            dauer_s = int(re.sub(r"[^0-9]", "", daten["routes"][0]["duration"]))
            minuten = round(dauer_s / 60)
            _kosten_protokollieren(root, start, ziel, "google_maps", 0.0)
            return {"minuten": minuten, "quelle": "google_maps", "geschaetzt": False}
        except Exception:
            pass  # Ruhig auf die Tabelle zurueckfallen - kein Absturz wegen einer Netz-/Schluesselstoerung.
    tabelle = _tabelle_lesen(root)
    minuten = _tabellenminuten(tabelle, start, ziel)
    if minuten is None:
        minuten = 60  # ehrliche, grobe Annahme statt Absturz - immer als geschaetzt gekennzeichnet
    return {"minuten": minuten, "quelle": "tabelle_geschaetzt", "geschaetzt": True}


def _kosten_protokollieren(root, start, ziel, quelle, usd):
    p = _area(root) / KOSTEN_PROTOKOLL
    zeile = json.dumps({"zeit": b.now().isoformat(), "start": start, "ziel": ziel,
                        "quelle": quelle, "usd": usd}, ensure_ascii=False)
    with p.open("a", encoding="utf-8") as f:
        f.write(zeile + "\n")


def abfahrt_berechnen(beginn, fahrzeit_minuten):
    """Abfahrt = Beginn - Fahrzeit - 30 Min Puffer - 10 Min Parken/Weg."""
    if isinstance(beginn, str):
        beginn = dt.datetime.fromisoformat(beginn)
    return beginn - dt.timedelta(minutes=fahrzeit_minuten + PUFFER_MIN + PARKEN_MIN)


def alarme_bauen(beginn, abfahrt, titel, standort, ort, unterlagen=""):
    """-> [(zeitpunkt, text), ...] fuer 2 VALARM: Vortag 18:00 + Abfahrtszeit."""
    if isinstance(beginn, str):
        beginn = dt.datetime.fromisoformat(beginn)
    vortag = (beginn - dt.timedelta(days=1)).replace(hour=18, minute=0, second=0, microsecond=0)
    zusatz = (" Unterlagen: " + unterlagen) if unterlagen else ""
    return [
        (vortag, "Morgen %s, Abfahrt %s ab %s.%s" % (titel, abfahrt.strftime("%H:%M"), standort, zusatz)),
        (abfahrt, "Jetzt losfahren nach %s." % ort),
    ]


# ------------------------------------------------------------------ Verknuepfung mit einer Mail-Freigabe (F-79 §2)
def termin_bei_mailfreigabe_eintragen(root, kopf, von="Patron"):
    """Wird von jack_oberflaeche._anwenden() (Zweig externemail) NACH erfolgreichem Mailversand aufgerufen,
    wenn der Kopf ein `termin:`-Feld traegt. Baut Akte (falls noch keine existiert) + .ics mit LOCATION und
    2 VALARM und schreibt ueber jack_kalender.schreiben_aus_termin() - dieselbe verbrauchte Freigabe deckt
    beides (Patron-Anordnung 28.09.2026 18:30). -> dict mit ok/meldung, wirft nie eine Exception nach oben."""
    import jack_kalender as K
    termin_iso = str(kopf.get("termin") or "").strip()
    if not termin_iso:
        return None
    try:
        beginn = dt.datetime.fromisoformat(termin_iso)
    except ValueError:
        return {"ok": False, "meldung": "termin:-Feld nicht lesbar (%s) - kein Kalendereintrag." % termin_iso[:40]}
    if beginn.tzinfo is None:
        beginn = beginn.replace(tzinfo=b.ZONE)
    ende = beginn + dt.timedelta(hours=1)
    ort = str(kopf.get("termin_ort") or "").strip()
    titel = "%s — %s" % (kopf.get("betreff") or kopf.get("titel") or "Termin", kopf.get("von") or kopf.get("an") or "")
    kurz = re.sub(r"[^a-zA-Z0-9]+", "_", str(kopf.get("auftrag") or "termin"))[:40].strip("_")
    pfad = akte_pfad(root, beginn, kurz)
    akte = akte_lesen(pfad)
    if akte is None:
        pfad_datei = akte_anlegen(root, id_=kurz, titel=titel, projekt=kopf.get("projekt", ""),
                                  marke=kopf.get("marke", ""), gegenseite={"von": kopf.get("von", ""),
                                  "an": kopf.get("an", "")}, beginn=beginn, ende=ende, ort=ort,
                                  quelle=kopf.get("auftrag", ""))
        akte = akte_lesen(pfad_datei)
        pfad = pfad_datei
    standort = standort_lesen(root)
    fahrzeit = fahrzeit_ermitteln(root, standort["ort"], ort or "Rosenheim", beginn, ort_bekannt=bool(ort))
    abfahrt = abfahrt_berechnen(beginn, fahrzeit["minuten"])
    alarme = alarme_bauen(beginn, abfahrt, titel, standort["ort"], ort)
    ics_text, uid = K._ics_bauen(titel, beginn, ende, ort=ort,
                                 beschreibung="Termin-Akte: %s. Fahrzeit %s Min (%s) ab %s." % (
                                     pfad.name, fahrzeit["minuten"], fahrzeit["quelle"], standort["ort"]),
                                 uid=akte.get("kalender_uid"), alarme=alarme)
    was = "aendern" if akte.get("kalender_uid") else "anlegen"
    ergebnis = K.schreiben_aus_termin(root, ics_text, uid, was=was, von=von,
                                      grund="Mail-Freigabe %s" % kopf.get("auftrag", ""))
    if ergebnis.get("ok"):
        alt = {"beginn": akte.get("beginn"), "fahrzeit": akte.get("fahrzeit")}
        akte["status"] = "eingetragen"
        akte["kalender_uid"] = uid
        akte["beginn"] = beginn.isoformat()
        akte["fahrzeit"] = fahrzeit
        akte["abfahrt"] = abfahrt.isoformat()
        akte["alarme"] = [{"zeit": z.isoformat(), "text": t} for z, t in alarme]
        _memo_anhaengen(akte, "Kalendereintrag über Mail-Freigabe", alt,
                        {"beginn": akte["beginn"], "fahrzeit": fahrzeit}, kopf.get("auftrag", ""))
        akte_schreiben(pfad, akte)
    return ergebnis


def _bare_adresse(roh):
    """Echte E-Mail-Adresse aus einem From-Header ODER einer gespeicherten Gegenseite-Zeichenkette -
    IMMER ueber email.utils.parseaddr (RFC-konform), NIE ein blosses Regex-Suchen im Anzeigenamen. Ein
    gefaelschter Anzeigename ("info@echt.de" <boese@fremd.de>) darf sich damit nicht als die echte Adresse
    ausgeben - parseaddr liefert die tatsaechliche Envelope-Adresse, nicht den Anzeigenamen."""
    import email.utils
    _, adresse = email.utils.parseaddr(str(roh or ""))
    return adresse.strip().lower()


# M-7 (Befund Nr. 5/C2, cashflow_2.md): eine ECHTE Bindung an die konkrete Antwortmail (In-Reply-To/
# References der gesendeten Bestaetigung) braucht eine Message-ID, die erst beim Versand entsteht
# (jack_postfaecher.senden -> "message_id") und aktuell nicht bis zu jack_termine.py durchgereicht wird -
# das Durchreichen liegt in jack_oberflaeche.py (kern-Datei, nicht Teil dieser Arbeitskopie). Bis das
# nachgezogen ist, verkleinert dieses Zeitfenster wenigstens das Risiko "jede spaetere Mail derselben
# Adresse trifft" (C2): ohne jede Aktivitaet an der Akte laenger als dieses Fenster gilt die Bindung nicht
# mehr als aktuell und die Mail faellt zur normalen Entscheidungs-Karte durch.
GEGENSEITE_AENDERUNG_FENSTER_TAGE = 45


def _letzte_aktivitaet(akte):
    zeiten = [akte.get("angelegt_am")]
    for eintrag in akte.get("memo") or []:
        zeiten.append(eintrag.get("zeit"))
    zeiten = [z for z in zeiten if z]
    ergebnisse = []
    for z in zeiten:
        try:
            ergebnisse.append(dt.datetime.fromisoformat(z))
        except (TypeError, ValueError):
            continue
    return max(ergebnisse) if ergebnisse else None


def akte_zu_absender(root, absender_roh):
    """-> Pfad einer JACK-eigenen, eingetragenen/geaenderten, noch NICHT vergangenen Termin-Akte, deren
    Gegenseite-Adresse GENAU (nicht nur Domain) zum Absender passt, sonst None. Bei mehreren Treffern gilt
    das als uneindeutig (None) - Opus-Endprüfung F-79: ein Domain-Abgleich waere bei jedem Nutzer
    desselben Freemail-Anbieters oder einer kurzen Domain als Teilstring falsch-positiv gewesen; die
    aelteste/erste Akte zu nehmen haette einen laengst vergangenen Termin getroffen statt des richtigen.

    M-7 (Befund Nr. 5/C2): zusaetzlich faellt eine Akte durch, an der laenger als
    GEGENSEITE_AENDERUNG_FENSTER_TAGE nichts mehr passiert ist (siehe Kommentar dort) - Abschwaechung
    von C2, keine vollstaendige Message-ID-Bindung (siehe Kommentar)."""
    adresse = _bare_adresse(absender_roh)
    if not adresse or "@" not in adresse:
        return None
    jetzt = b.now()
    treffer = []
    for pfad in sorted(_akten_ordner(root).glob("*.json")):
        akte = akte_lesen(pfad)
        if not akte or akte.get("status") not in ("eingetragen", "geaendert") or not akte.get("kalender_uid"):
            continue
        try:
            if dt.datetime.fromisoformat(akte["beginn"]) < jetzt:
                continue  # vergangener Termin - nie automatisch anfassen
        except (KeyError, ValueError):
            continue
        letzte = _letzte_aktivitaet(akte)
        if letzte is not None and (jetzt - letzte) > dt.timedelta(days=GEGENSEITE_AENDERUNG_FENSTER_TAGE):
            continue  # zu lange keine Aktivitaet - keine automatische Bindung mehr (Befund Nr. 5/C2)
        gegenseite_adressen = {_bare_adresse(v) for v in (akte.get("gegenseite") or {}).values()}
        if adresse in gegenseite_adressen:
            treffer.append(pfad)
    return treffer[0] if len(treffer) == 1 else None


# ------------------------------------------------------------------ Automatische Aenderung durch die Gegenseite (§4)
def aenderung_anwenden(root, akte_pfad_, neuer_zeitpunkt, quelle, von="JACK-Postfach (automatisch, F-79 §4)"):
    """NUR fuer Akten mit kalender_uid, die JACK selbst angelegt hat (status in eingetragen/geaendert).
    Sichert das alte .ics (Ruecklauf), aendert Zeit+Alarme, schreibt neu, legt eine Memo-Karte an. Gibt bei
    fremden/nicht vorhandenen Eintraegen einen klaren Fehler zurueck statt stillschweigend nichts zu tun."""
    import jack_kalender as K
    akte = akte_lesen(akte_pfad_)
    if akte is None:
        return {"ok": False, "meldung": "Termin-Akte nicht gefunden."}
    if not akte.get("kalender_uid") or akte.get("status") not in ("eingetragen", "geaendert"):
        return {"ok": False, "meldung": "Kein JACK-eigener Kalendereintrag zu dieser Akte - keine automatische Änderung."}
    if isinstance(neuer_zeitpunkt, tuple) and neuer_zeitpunkt[0] == "UHRZEIT_NUR":
        alt_beginn = dt.datetime.fromisoformat(akte["beginn"])
        _, h, mi = neuer_zeitpunkt
        neuer_zeitpunkt = alt_beginn.replace(hour=h, minute=mi)
    # Zweite Opus-Endpruefung F-79, Fund C5: "es geht um 11 Uhr los" o.ae. erkennt zwar ein Aenderungswort,
    # meint aber denselben Zeitpunkt - ohne diese Pruefung wurde die Mail geschluckt UND eine X->X-Karte
    # angelegt, ohne dass sich etwas aenderte. Bei Gleichheit: nichts tun, Mail faellt zur normalen
    # Verarbeitung durch (kein "ok": True, also kein automatisches Schlucken im Aufrufer).
    if neuer_zeitpunkt == dt.datetime.fromisoformat(akte["beginn"]):
        return {"ok": False, "meldung": "Neue Zeit ist gleich der alten - keine Änderung nötig."}
    alt_ics_sicherung = _area(root) / "termine" / (akte_pfad_.stem + "_%s.ics.vor_aenderung" % b.now().strftime("%Y%m%d_%H%M%S"))
    ende = neuer_zeitpunkt + dt.timedelta(hours=1)
    standort = standort_lesen(root)
    fahrzeit = fahrzeit_ermitteln(root, standort["ort"], akte.get("ort") or "Rosenheim", neuer_zeitpunkt,
                                  ort_bekannt=bool(akte.get("ort")))
    abfahrt = abfahrt_berechnen(neuer_zeitpunkt, fahrzeit["minuten"])
    alarme = alarme_bauen(neuer_zeitpunkt, abfahrt, akte["titel"], standort["ort"], akte.get("ort", ""))
    ics_text, uid = K._ics_bauen(akte["titel"], neuer_zeitpunkt, ende, ort=akte.get("ort", ""),
                                 beschreibung="Geändert (%s): %s" % (quelle, akte_pfad_.name),
                                 uid=akte["kalender_uid"], alarme=alarme)
    try:
        alt_ics_sicherung.write_text(json.dumps(akte, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
    ergebnis = K.schreiben_aus_termin(root, ics_text, akte["kalender_uid"], was="aendern", von=von,
                                      grund="Automatische Änderung: %s" % quelle)
    if not ergebnis.get("ok"):
        return ergebnis
    alt = {"beginn": akte["beginn"], "fahrzeit": akte.get("fahrzeit")}
    akte["status"] = "geaendert"
    akte["beginn"] = neuer_zeitpunkt.isoformat()
    akte["fahrzeit"] = fahrzeit
    akte["abfahrt"] = abfahrt.isoformat()
    akte["alarme"] = [{"zeit": z.isoformat(), "text": t} for z, t in alarme]
    _memo_anhaengen(akte, "Automatische Änderung" if not quelle.startswith("Rückgängig") else "Rückgängig gemacht",
                    alt, {"beginn": akte["beginn"], "fahrzeit": fahrzeit}, quelle)
    akte_schreiben(akte_pfad_, akte)
    # Opus-Endprüfung F-79: kein Memo-Karten-Rueckstoss fuer einen Rueckgaengig-Schritt selbst - der ist
    # bereits die Antwort auf die vorherige Karte, keine neue Kenntnisnahme noetig.
    if not quelle.startswith("Rückgängig"):
        _memo_karte_anlegen(root, akte_pfad_, akte, alt["beginn"], akte["beginn"], quelle)
    return ergebnis


def _memo_karte_anlegen(root, akte_pfad_, akte, alt_beginn, neu_beginn, quelle):
    import jack_freigaben
    kurz = re.sub(r"[^a-zA-Z0-9]+", "_", akte["id"])[:40]
    name = "%s_TERMIN_GEAENDERT_%s.md" % (b.now().strftime("%Y-%m-%d"), kurz)
    if (Path(root) / "auftraege" / "freigabe" / name).is_file():
        return
    # F-78 (29.09.2026): echte Werte statt Platzhalter - "projekt"/"marke" fehlten frueher oft in der
    # Akte und wurden dann woertlich "unbekannt" geschrieben (eine der 7 unvollstaendigen Karten); "an"
    # war sogar nur "—". projekt/marke kommen jetzt zur Not aus dem Titel, "an" ist immer "Patron"
    # (er selbst ist der Empfaenger dieser Kenntnisnahme-Karte).
    gegenseite_adresse = (akte.get("gegenseite") or {}).get("an") or (akte.get("gegenseite") or {}).get("von")
    v2 = {
        "projekt": akte.get("projekt") or akte.get("titel") or "Termin",
        "marke": akte.get("marke") or "HOLDING",
        "eingegangen": b.now().strftime("%Y-%m-%d %H:%M"),
        "von": gegenseite_adresse or "Gegenseite (Adresse nicht in der Akte hinterlegt, siehe Kern)",
        "an": "Patron",
        "art": "zurkenntnis",
        "betreff": "Termin automatisch geändert — %s" % akte["titel"],
        "kern": "Der Termin wurde automatisch geändert: %s → %s." % (alt_beginn, neu_beginn),
        "frage": "Zur Kenntnis nehmen oder rückgängig machen?",
        "empfehlung": "Zur Kenntnis nehmen, falls die neue Zeit passt.",
        "frist": "keine",
        "dringlichkeit": "mittel",
        "ablauf": "GELESEN / RÜCKGÄNGIG",
        "akte_pfad": str(akte_pfad_), "alt_beginn": str(alt_beginn),
        "gefahr": "keine", "bereiche": "kalender",
    }
    jack_freigaben.karte_schreiben(root, v2, "\n".join([
        "## Kern", "Auslöser der Änderung (%s): %s" % (akte.get("titel", ""), quelle[:300]),
        "", "## Antwort / Entwurf", "Kein Mailversand - nur Kenntnisnahme dieser automatischen Kalenderänderung.",
        "", "## Warum / Risiko",
        "Automatische Änderung nur an JACK-eigenen Einträgen (Anordnung Patron 28.09.2026 18:30). RÜCKGÄNGIG stellt den vorherigen Zeitpunkt (%s) wieder her." % alt_beginn,
        "", "## Ablauf", "GELESEN schließt die Karte. RÜCKGÄNGIG macht die Änderung rückgängig.",
        "", "## Belege", "Termin-Akte: `%s`" % akte_pfad_, "",
    ]), dateiname=name, herkunft="jack_termine._memo_karte_anlegen")


def aenderung_rueckgaengig(root, akte_pfad_, alt_beginn=None, von="Patron"):
    """Stellt einen Zeitpunkt wieder her - `alt_beginn` (ISO-Text) kommt aus der Memo-Karte selbst
    (Kopffeld `alt_beginn:`), NICHT mehr aus "dem letzten memo-Eintrag" (Opus-Endprüfung F-79: das fuehrte
    bei einem zweiten Klick zu einem Hin-und-Her-Umschalten, weil der letzte Eintrag dann der
    Rueckgaengig-Schritt selbst war). Ohne explizites alt_beginn wird NICHTS geaendert."""
    akte = akte_lesen(akte_pfad_)
    if not akte:
        return {"ok": False, "meldung": "Termin-Akte nicht gefunden."}
    if not alt_beginn:
        return {"ok": False, "meldung": "Kein vorheriger Zeitpunkt angegeben - nichts geändert."}
    ergebnis = aenderung_anwenden(root, akte_pfad_, dt.datetime.fromisoformat(alt_beginn),
                                  quelle="Rückgängig (%s)" % von, von=von)
    if ergebnis.get("ok"):
        ergebnis["meldung"] = ergebnis.get("meldung", "") + " (Rückgängig, kein zweiter Rückgängig-Schritt möglich - Karte ist jetzt erledigt.)"
    return ergebnis
