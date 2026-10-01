"""Runway-Dev-Adapter fuer den freigegebenen PATRONOS-Video-Pilot.

Startet ausschliesslich interne Erzeugungslaeufe unter dem Auftrags- und
Tagesdeckel. Es gibt keine automatische Aufladung und keine Veroeffentlichung.
"""
import base64
from contextlib import contextmanager
import datetime as dt
from decimal import Decimal, InvalidOperation
import fcntl
import hashlib
import ipaddress
import json
import mimetypes
import os
from pathlib import Path
import re
import socket
import urllib.error
import urllib.request
from urllib.parse import urlsplit

import jack_kosten
import jack_medien
import jack_speicher
import jack_tresor
import jack_videoproduktion
import jack_vorgaenge

VERSION = "1.2.0"  # F-9 (24.09.2026): Vorgangskennung VOR dem Aufruf (Paket 3)
API = "https://api.dev.runwayml.com/v1"
KENNUNG = re.compile(r"VP-[0-9]{8}-[0-9]{6}-[a-f0-9]{8}")
TASK_ID = re.compile(r"[A-Za-z0-9_-]{8,160}")
MAX_ANTWORT = 2_000_000
MAX_VIDEO = 2 * 1024 * 1024 * 1024
PREISQUELLE = "Runway Dev pricing, abgerufen 2026-09-21"


def _konfiguration(root):
    daten = jack_videoproduktion._laden(root)
    runway = daten.get("runway")
    adapter = daten.get("anbieter_adapter")
    if ((adapter != "runway-dev@1.0.0" and
         (not isinstance(adapter, list) or "runway-dev@1.0.0" not in adapter))
            or not isinstance(runway, dict) or runway.get("aktiv") is not True):
        raise ValueError("Runway-Adapter ist nicht aktiv")
    return daten, runway


def bereitschaft(root):
    try:
        _, runway = _konfiguration(root)
        schluessel, _, hinweis = jack_tresor.stand(runway["schluesselbund_name"])
        return {"adapter": "runway-dev", "version": VERSION,
                "aktiv": True, "bereit": schluessel == "da",
                "pilot": runway.get("pilot_marke"),
                "max_usd_je_auftrag": runway.get("max_usd_je_auftrag"),
                "automatische_aufladung": False, "veroeffentlichung": False,
                "schluessel": schluessel,
                "hinweis": hinweis if schluessel != "da" else
                "Adapter bereit; jeder Lauf bleibt unter den Kosten- und Auftragsgrenzen."}
    except (OSError, ValueError, KeyError) as fehler:
        return {"adapter": "runway-dev", "version": VERSION, "aktiv": False,
                "bereit": False, "hinweis": str(fehler)[:200]}


def _auftragspfad(root, kennung):
    if not isinstance(kennung, str) or not KENNUNG.fullmatch(kennung):
        raise ValueError("Ungueltige Videoauftragskennung")
    cfg = jack_videoproduktion._laden(root)
    treffer = []
    for marke in cfg["marken"]:
        try:
            _, medien = jack_videoproduktion._medienordner(root, cfg, marke)
        except ValueError:
            continue
        pfad = medien / jack_videoproduktion.AUFTRAGSORDNER / kennung / "auftrag.json"
        if pfad.is_file() and not pfad.is_symlink() and not pfad.parent.is_symlink():
            treffer.append(pfad)
    if len(treffer) != 1:
        raise ValueError("Videoauftrag nicht eindeutig gefunden")
    return treffer[0]


def _lesen(pfad):
    if pfad.stat().st_size > 500_000:
        raise ValueError("Videoauftrag ist zu gross")
    daten = json.loads(pfad.read_text(encoding="utf-8"))
    if not isinstance(daten, dict) or daten.get("schema") != 1:
        raise ValueError("Videoauftrag ist ungueltig")
    return daten


def _schreiben(pfad, daten):
    jack_speicher.atomic_bytes(
        pfad, (json.dumps(daten, ensure_ascii=False, indent=2) + "\n").encode())


@contextmanager
def _sperre(auftragspfad):
    pfad = auftragspfad.parent / "runway.sperre"
    with pfad.open("a+") as datei:
        try:
            fcntl.flock(datei, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as fehler:
            raise ValueError("Dieser Videoauftrag wird bereits bearbeitet") from fehler
        try:
            yield
        finally:
            fcntl.flock(datei, fcntl.LOCK_UN)


def _zahl(wert, name):
    try:
        zahl = Decimal(str(wert))
    except (InvalidOperation, ValueError):
        raise ValueError(name + " ist ungueltig")
    if not zahl.is_finite() or zahl < 0:
        raise ValueError(name + " ist ungueltig")
    return zahl


def _kosten(runway, modell, dauer):
    modelle = runway.get("modelle") or {}
    if modell not in modelle:
        raise ValueError("Dieses Runway-Modell ist nicht freigegeben")
    if type(dauer) is not int or dauer not in (5, 10):
        raise ValueError("Dauer muss 5 oder 10 Sekunden sein")
    return _zahl(modelle[modell]["usd_je_sekunde"], "Modellpreis") * dauer


def _prompt(wert):
    if not isinstance(wert, str):
        raise ValueError("Videoprompt fehlt")
    wert = wert.strip()
    if not 10 <= len(wert) <= 1000 or "\x00" in wert:
        raise ValueError("Videoprompt muss 10 bis 1000 Zeichen enthalten")
    return wert


def _startbild(root, daten, roh):
    if roh in (None, ""):
        return None
    if not isinstance(roh, str) or len(roh) > 1200:
        raise ValueError("Startbildpfad ist ungueltig")
    vault = Path(root).absolute().parent.parent
    p = Path(roh)
    if (p.is_absolute() or ".." in p.parts
            or p.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp")):
        raise ValueError("Startbild muss lokal und relativ zur Holding sein")
    rohziel = (vault / p).absolute()
    markenwurzel = vault / "00_Marken" / daten["markenordner"] / "06_Medien"
    pruefpfade = [rohziel] + [eltern for eltern in rohziel.parents
                             if markenwurzel in eltern.parents or eltern == markenwurzel]
    if any(element.is_symlink() for element in pruefpfade):
        raise ValueError("Startbildpfad darf keinen Verweis enthalten")
    ziel = rohziel.resolve()
    if markenwurzel.resolve() not in ziel.parents or not ziel.is_file():
        raise ValueError("Startbild muss aus der Medienablage dieser Marke stammen")
    if not 0 < ziel.stat().st_size <= 3_300_000:
        raise ValueError("Startbild ist leer oder fuer den sicheren Direktupload zu gross")
    mime = mimetypes.guess_type(ziel.name)[0]
    if mime not in ("image/jpeg", "image/png", "image/webp"):
        raise ValueError("Startbildformat nicht unterstuetzt")
    return "data:" + mime + ";base64," + base64.b64encode(ziel.read_bytes()).decode("ascii")


def _api(schluessel, api_version, weg, methode="GET", body=None, timeout=30, opener=None):
    roh = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    req = urllib.request.Request(API + weg, data=roh, method=methode, headers={
        "Authorization": "Bearer " + schluessel,
        "X-Runway-Version": api_version,
        "Content-Type": "application/json", "Accept": "application/json",
        "User-Agent": "JACK-Runway/" + VERSION})
    try:
        abruf = opener.urlopen if opener is not None else urllib.request.urlopen
        with abruf(req, timeout=timeout) as antwort:
            payload = antwort.read(MAX_ANTWORT + 1)
            if len(payload) > MAX_ANTWORT:
                raise ValueError("Runway-Antwort ist zu gross")
            daten = json.loads(payload)
    except urllib.error.HTTPError as fehler:
        try:
            inhalt = json.loads(fehler.read(20_000))
            meldung = inhalt.get("error", "") if isinstance(inhalt, dict) else ""
        except Exception:
            meldung = ""
        # F-9: 4xx = Anbieter hat geantwortet und abgelehnt (belegter Nicht-Erfolg); 5xx bleibt unklar.
        klasse = jack_vorgaenge.AnbieterAbgewiesen if 400 <= int(fehler.code or 0) < 500 else ValueError
        raise klasse("Runway antwortet mit Fehler %s%s" %
                     (fehler.code, (": " + str(meldung)[:160]) if meldung else ""))
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as fehler:
        raise ValueError("Runway war nicht erreichbar") from fehler
    if not isinstance(daten, dict):
        raise ValueError("Runway-Antwort ist ungueltig")
    return daten


def starten(root, kennung, prompt, modell="gen4_turbo", dauer=5,
            startbild=None, opener=None):
    konfiguration, runway = _konfiguration(root)
    pfad = _auftragspfad(root, kennung)
    with _sperre(pfad):
        daten = _lesen(pfad)
        # A-7 T4 (24.09.2026): Der Adapter prueft das Freigabe-Tor SELBST, unabhaengig vom
        # Dienstweg (jack_videokette.tor). Ohne woertlich 'ausloesen' fuer GENAU diese Kennung
        # kein Aufruf, keine Reservierung, keine Kosten. Kennung prueft _auftragspfad, Deckel
        # pruefen Auftragsdeckel unten und jack_kosten.reservieren (Stunde/Tag).
        jack_videoproduktion._echtfreigabe_pruefen(konfiguration, kennung)
        # F-8 T1 (24.09.2026): Einmal-Ticket - der Direktaufruf verbraucht die Freigabe wie jack_videokette.tor.
        jack_videoproduktion._echtfreigabe_verbrauchen(root, kennung)
        if daten.get("marke") != runway.get("pilot_marke"):
            raise ValueError("Runway ist vorerst nur fuer den PATRONOS-Pilot freigegeben")
        if daten.get("status") not in ("briefing", "produktion_bereit"):
            raise ValueError("Videoauftrag ist nicht startbereit")
        versuche = daten.get("generationen") or []
        if not isinstance(versuche, list) or any(not isinstance(v, dict) for v in versuche):
            raise ValueError("Generationsverlauf ist ungueltig")
        stufe = runway["modelle"].get(modell, {}).get("stufe")
        if stufe not in ("entwurf", "endfassung"):
            raise ValueError("Dieses Runway-Modell ist nicht freigegeben")
        limit = (runway["max_entwuerfe_je_szene"] if stufe == "entwurf"
                 else runway["max_endfassungen_je_szene"])
        if sum(1 for v in versuche if v.get("stufe") == stufe) >= limit:
            raise ValueError("Versuchsgrenze fuer diese Produktionsstufe erreicht")
        kosten = _kosten(runway, modell, dauer)
        bisher = sum((_zahl(v.get("kosten_usd_geschaetzt", "0"), "Auftragskosten")
                      for v in versuche), Decimal(0))
        if bisher + kosten > _zahl(runway["max_usd_je_auftrag"], "Auftragsdeckel"):
            raise ValueError("Deckel von 3,00 USD fuer diesen Videoauftrag wuerde ueberschritten")
        reservierung_id = jack_kosten.reservieren(root, kennung, str(kosten))
        prompt = _prompt(prompt)
        bild = _startbild(root, daten, startbild)
        key_state, schluessel, hinweis = jack_tresor.stand(runway["schluesselbund_name"])
        if key_state != "da":
            raise ValueError("Runway-Schluessel fehlt im macOS-Schluesselbund. " + hinweis)
        ratio = {"quer_16_9": "1280:720", "short_9_16": "720:1280"}.get(daten.get("format"))
        if not ratio:
            raise ValueError("Der Pilot erzeugt zunaechst nur 16:9 oder 9:16")
        body = {"model": modell, "promptText": prompt, "ratio": ratio, "duration": dauer}
        if bild:
            body["promptImage"] = bild
        # F-9 (Paket 3, T1): Vorgangskennung VOR dem Aufruf - im Journal, in der Akte und im Kostenbuch.
        # Ist ein frueherer Aufruf fuer diesen Videoauftrag ohne belegte Antwort, sperrt beginnen() jeden
        # weiteren Aufruf, bis eine Zustandspruefung oder der Patron den Zustand geklaert hat.
        try:
            vg = jack_vorgaenge.beginnen(root, "runway", kennung, "generation:%s:%s:%ds" % (stufe, modell, dauer),
                                         {k: v for k, v in body.items() if k != "promptImage"} | {"startbild": bool(bild)},
                                         freigabe="echtfreigabe:%s:%s" % (kennung, dt.datetime.now().astimezone().isoformat()))
        except Exception:
            jack_kosten.reservierung_abschliessen(root, reservierung_id, "gestoppt_vor_aufruf")
            raise
        eintrag = {"nummer": len(versuche) + 1, "vorgang": vg,
                   "gestartet": dt.datetime.now().astimezone().isoformat(),
                   "anbieter": "runway", "anbieter_lauf": None,
                   "modell": modell, "stufe": stufe,
                   "dauer_sekunden": dauer, "ratio": ratio,
                   "kosten_usd_geschaetzt": str(kosten),
                   "preisquelle": PREISQUELLE, "status": "ABSICHT",
                   "startbild_gesendet": bool(bild)}
        versuche.append(eintrag)
        daten["generationen"] = versuche
        _schreiben(pfad, daten)
        kosten_start = jack_kosten.begin(root, "video", "runway", modell, vorgang=vg)
        try:
            antwort = _api(schluessel, runway["api_version"],
                           "/image_to_video", "POST", body, opener=opener)
            task = antwort.get("id")
            if not isinstance(task, str) or not TASK_ID.fullmatch(task):
                raise ValueError("Runway hat keine gueltige Vorgangskennung geliefert")
        except Exception as fehler:
            belegt = isinstance(fehler, jack_vorgaenge.AnbieterAbgewiesen)
            (jack_vorgaenge.abgewiesen if belegt else jack_vorgaenge.unklar)(root, vg, str(fehler))
            eintrag["status"] = "ABGEWIESEN" if belegt else "UNKLAR"
            eintrag["fehler"] = str(fehler)[:200]
            if belegt:
                eintrag["kosten_usd_geschaetzt"] = "0"
            _schreiben(pfad, daten)
            jack_kosten.end(root, kosten_start, status="fehler", error=type(fehler).__name__)
            jack_kosten.reservierung_abschliessen(root, reservierung_id, "fehler", kosten_start.get("id"))
            raise
        jack_vorgaenge.angekommen(root, vg, task)
        jack_kosten.end(root, kosten_start, status="gestartet", request_id=task,
                        usd_estimated=str(kosten), price_source=PREISQUELLE)
        jack_kosten.reservierung_abschliessen(root, reservierung_id, "ok", kosten_start.get("id"))
        eintrag.update({"anbieter_lauf": task, "status": "PENDING"})
        daten["anbieter"] = "runway-dev@1.0.0"
        daten["status"] = "in_produktion"
        daten["kosten_gemeldet"] = None
        daten["kosten_geschaetzt_usd"] = str(bisher + kosten)
        daten["hinweis"] = "Runway-Vorgang gestartet; noch kein fertiges oder freigegebenes Video."
        _schreiben(pfad, daten)
        return {"kennung": kennung, "status": "in_produktion",
                "anbieter_lauf": task, "modell": modell,
                "kosten_usd_geschaetzt": str(kosten),
                "auftragskosten_usd_geschaetzt": str(bisher + kosten),
                "hinweis": "Erzeugung laeuft intern. Keine Veroeffentlichung."}


def anbieterstatus(root, task, opener=None):
    """F-9: nur lesende Zustandsabfrage GET /v1/tasks/{id} (fuer jack_vorgaenge.pruefen)."""
    _, runway = _konfiguration(root)
    if not isinstance(task, str) or not TASK_ID.fullmatch(task):
        raise ValueError("Ungueltige Runway-Vorgangskennung")
    key_state, schluessel, hinweis = jack_tresor.stand(runway["schluesselbund_name"])
    if key_state != "da":
        raise ValueError("Runway-Schluessel fehlt im macOS-Schluesselbund. " + hinweis)
    return str(_api(schluessel, runway["api_version"], "/tasks/" + task, opener=opener).get("status") or "").upper()


def nachtragen(root, kennung, anbieter=("runway", "higgsfield")):
    """F-9: Ist ein Vorgang laut Journal (Antwort oder Zustandspruefung) angekommen, die Akte kennt ihn aber
    nur als ABSICHT/UNKLAR (Absturz zwischen Antwort und Aktenvermerk), wird das Ergebnis UEBERNOMMEN -
    kein zweiter Aufruf. Belegter Nicht-Erfolg wird als ABGEWIESEN vermerkt. Liefert die Aenderungen."""
    pfad = _auftragspfad(root, kennung)
    daten = _lesen(pfad)
    stand = jack_vorgaenge.stand(root)
    geaendert = []
    for eintrag in daten.get("generationen") or []:
        v = stand.get(eintrag.get("vorgang") or "")
        if not v or eintrag.get("anbieter") not in anbieter or eintrag.get("status") not in ("ABSICHT", "UNKLAR"):
            continue
        if v["zustand"] == "angekommen" and v.get("anbieter_kennung"):
            eintrag.update({"anbieter_lauf": v["anbieter_kennung"],
                            "status": "PENDING" if eintrag["anbieter"] == "runway" else "queued",
                            "nachgetragen": dt.datetime.now().astimezone().isoformat()})
            daten["status"] = "in_produktion"
            geaendert.append({"vorgang": v["vg"], "uebernommen": v["anbieter_kennung"]})
        elif v["zustand"] == "nicht_angekommen":
            eintrag.update({"status": "ABGEWIESEN", "kosten_usd_geschaetzt": "0"})
            geaendert.append({"vorgang": v["vg"], "nicht_angekommen": True})
    if geaendert:
        _schreiben(pfad, daten)
    return geaendert


def wuerde_starten(root, kennung, prompt, modell="gen4_turbo", dauer=5, startbild=None):
    """Prueft und protokolliert einen Runway-Start vollstaendig, OHNE die API aufzurufen.

    Spiegelt starten() bis unmittelbar vor _api(): Pilot-Marke, Auftragsstatus,
    Versuchsgrenze je Stufe, Auftrags- und Globaldeckel, Prompt, Startbild und
    Schluesselformat werden geprueft. Der Schluesselwert selbst wird nie
    zurueckgegeben. Der Stopp wird im bestehenden Kostenprotokoll vermerkt."""
    _, runway = _konfiguration(root)
    pfad = _auftragspfad(root, kennung)
    with _sperre(pfad):
        daten = _lesen(pfad)
        if daten.get("marke") != runway.get("pilot_marke"):
            raise ValueError("Runway ist vorerst nur fuer den PATRONOS-Pilot freigegeben")
        if daten.get("status") not in ("briefing", "produktion_bereit"):
            raise ValueError("Videoauftrag ist nicht startbereit")
        versuche = daten.get("generationen") or []
        if not isinstance(versuche, list) or any(not isinstance(v, dict) for v in versuche):
            raise ValueError("Generationsverlauf ist ungueltig")
        stufe = runway["modelle"].get(modell, {}).get("stufe")
        if stufe not in ("entwurf", "endfassung"):
            raise ValueError("Dieses Runway-Modell ist nicht freigegeben")
        limit = (runway["max_entwuerfe_je_szene"] if stufe == "entwurf"
                 else runway["max_endfassungen_je_szene"])
        if sum(1 for v in versuche if v.get("stufe") == stufe) >= limit:
            raise ValueError("Versuchsgrenze fuer diese Produktionsstufe erreicht")
        kosten = _kosten(runway, modell, dauer)
        bisher = sum((_zahl(v.get("kosten_usd_geschaetzt", "0"), "Auftragskosten")
                      for v in versuche), Decimal(0))
        if bisher + kosten > _zahl(runway["max_usd_je_auftrag"], "Auftragsdeckel"):
            raise ValueError("Deckel von 3,00 USD fuer diesen Videoauftrag wuerde ueberschritten")
        reservierung_id = jack_kosten.reservieren(root, kennung, str(kosten))
        prompt = _prompt(prompt)
        bild = _startbild(root, daten, startbild)
        key_state, _, hinweis = jack_tresor.stand(runway["schluesselbund_name"])
        if key_state != "da":
            raise ValueError("Runway-Schluessel fehlt im macOS-Schluesselbund. " + hinweis)
        ratio = {"quer_16_9": "1280:720", "short_9_16": "720:1280"}.get(daten.get("format"))
        if not ratio:
            raise ValueError("Der Pilot erzeugt zunaechst nur 16:9 oder 9:16")
        body = {"model": modell, "promptText": prompt, "ratio": ratio, "duration": dauer}
        if bild:
            body["promptImage"] = "<lokales Startbild, base64, hier nicht protokolliert>"
        kosten_start = jack_kosten.begin(root, "video", "runway", modell)
        # usd_estimated bleibt 0, kein Verbrauch: sonst wuerde end() den vollen
        # Betrag als usd_geschaetzt buchen, und ein einzelner Dry-Run wuerde
        # gegen den Stunden-/Tagesdeckel zaehlen.
        jack_kosten.end(root, kosten_start, status="gestoppt_vor_aufruf",
                        usd_estimated="0", price_source=PREISQUELLE)
        jack_kosten.reservierung_abschliessen(root, reservierung_id, "gestoppt_vor_aufruf", kosten_start.get("id"))
        return {"kennung": kennung, "gestoppt_vor_aufruf": True,
                "stufe": stufe, "vorherige_laeufe_dieser_stufe":
                    sum(1 for v in versuche if v.get("stufe") == stufe),
                "wuerde_aufrufen": {"anbieter": "runway", "methode": "POST",
                                     "pfad": "/image_to_video", "body": body},
                "kosten_usd_geschaetzt": str(kosten),
                "auftragskosten_usd_geschaetzt_mit_diesem_lauf": str(bisher + kosten),
                "hinweis": "Alle Pruefungen bestanden; kein Netzwerkaufruf ausgefuehrt und keiner nötig."}


def _oeffentliche_url(url):
    if not isinstance(url, str) or len(url) > 3000:
        raise ValueError("Runway-Ergebnisadresse ist ungueltig")
    teile = urlsplit(url)
    if (teile.scheme != "https" or not teile.hostname or teile.username
            or teile.password or teile.port not in (None, 443)):
        raise ValueError("Runway-Ergebnisadresse ist nicht sicher")
    try:
        infos = socket.getaddrinfo(teile.hostname, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as fehler:
        raise ValueError("Runway-Ergebnisadresse ist nicht aufloesbar") from fehler
    if not infos or any(not ipaddress.ip_address(i[4][0]).is_global for i in infos):
        raise ValueError("Runway-Ergebnisadresse liegt nicht im oeffentlichen Netz")
    return url


class _SichereUmleitung(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _oeffentliche_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _download(url, ziel, opener=None):
    url = _oeffentliche_url(url)
    req = urllib.request.Request(url, headers={
        "User-Agent": "JACK-Runway/" + VERSION,
        "Accept": "video/mp4,video/*;q=0.9"})
    temp = ziel.with_suffix(ziel.suffix + ".part")
    if temp.exists():
        raise ValueError("Unvollstaendiger frueherer Download muss geprueft werden")
    total = 0
    hashwert = hashlib.sha256()
    try:
        oeffner = opener or urllib.request.build_opener(_SichereUmleitung())
        with oeffner.open(req, timeout=60) as antwort, temp.open("xb") as datei:
            _oeffentliche_url(antwort.geturl())
            typ = (antwort.headers.get_content_type() or "").lower()
            if not typ.startswith("video/") and typ != "application/octet-stream":
                raise ValueError("Runway-Ergebnis ist keine Videodatei")
            while True:
                block = antwort.read(1024 * 1024)
                if not block:
                    break
                total += len(block)
                if total > MAX_VIDEO:
                    raise ValueError("Runway-Video ueberschreitet 2 GiB")
                hashwert.update(block)
                datei.write(block)
            datei.flush(); os.fsync(datei.fileno())
        if total == 0:
            raise ValueError("Runway-Ergebnis ist leer")
        os.replace(temp, ziel)
    finally:
        if temp.exists():
            fehlerziel = ziel.parent / ("download_fehler_" +
                dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".part")
            os.replace(temp, fehlerziel)
    return {"bytes": total, "sha256": hashwert.hexdigest()}


def aktualisieren(root, kennung, opener=None, download_opener=None):
    _, runway = _konfiguration(root)
    pfad = _auftragspfad(root, kennung)
    with _sperre(pfad):
        daten = _lesen(pfad)
        if daten.get("status") != "in_produktion":
            return {"kennung": kennung, "status": daten.get("status"),
                    "hinweis": "Kein laufender Runway-Vorgang."}
        versuche = daten.get("generationen") or []
        lauf = versuche[-1] if versuche else {}
        task = str(lauf.get("anbieter_lauf") or "")
        if not TASK_ID.fullmatch(task):
            raise ValueError("Laufender Runway-Vorgang ist ungueltig")
        key_state, schluessel, hinweis = jack_tresor.stand(runway["schluesselbund_name"])
        if key_state != "da":
            raise ValueError("Runway-Schluessel fehlt im macOS-Schluesselbund. " + hinweis)
        antwort = _api(schluessel, runway["api_version"], "/tasks/" + task, opener=opener)
        status = str(antwort.get("status") or "").upper()
        lauf["zuletzt_geprueft"] = dt.datetime.now().astimezone().isoformat()
        lauf["status"] = status
        if status in ("PENDING", "RUNNING", "THROTTLED"):
            _schreiben(pfad, daten)
            return {"kennung": kennung, "status": "in_produktion",
                    "anbieter_status": status}
        if status in ("FAILED", "CANCELED"):
            lauf["fehlercode"] = str(antwort.get("failureCode") or "")[:120]
            daten["status"] = "produktion_bereit"
            daten["hinweis"] = "Erzeugung nicht abgeschlossen; kein automatischer Wiederholungsversuch."
            _schreiben(pfad, daten)
            return {"kennung": kennung, "status": "produktion_bereit",
                    "anbieter_status": status, "hinweis": daten["hinweis"]}
        if status != "SUCCEEDED":
            raise ValueError("Unbekannter Runway-Auftragsstatus")
        ausgaben = antwort.get("output")
        if not isinstance(ausgaben, list) or len(ausgaben) != 1:
            raise ValueError("Runway hat nicht genau ein Video geliefert")
        ziel = pfad.parent / ("runway_%02d.mp4" % lauf["nummer"])
        if ziel.exists():
            raise ValueError("Zieldatei des Runway-Videos existiert bereits")
        beleg = _download(ausgaben[0], ziel, opener=download_opener)
        vault = Path(root).absolute().parent.parent
        relativ = str(ziel.relative_to(vault))
        breite, hoehe = ((1280, 720) if lauf["ratio"] == "1280:720" else (720, 1280))
        pruefung = jack_medien.pruefen(
            root, relativ, min_breite=breite, min_hoehe=hoehe,
            max_dauer_sekunden=lauf["dauer_sekunden"] + 2, ton_noetig=False)
        lauf["ergebnis"] = {"pfad": relativ, **beleg}
        lauf["technische_pruefung"] = pruefung["nachweis"]
        daten["erzeugtes_video"] = relativ
        daten["technische_pruefung"] = pruefung["nachweis"]
        daten["status"] = ("qualitaetspruefung" if pruefung["technik_bestanden"]
                           else "produktion_bereit")
        daten["kreative_pruefung"] = "offen"
        daten["patron_freigabe"] = "offen"
        daten["aussenwirkung"] = False
        daten["hinweis"] = ("Video lokal gespeichert und technisch geprueft; "
                            "kreative Pruefung und Patron-Freigabe sind offen.")
        _schreiben(pfad, daten)
        return {"kennung": kennung, "status": daten["status"], "video": relativ,
                "technische_pruefung": pruefung["nachweis"],
                "kreative_pruefung": "offen", "patron_freigabe": "offen",
                "veroeffentlicht": False}


def offene_aktualisieren(root, limit=2):
    stand = bereitschaft(root)
    if not stand.get("bereit"):
        return {"geprueft": 0, "aktualisiert": []}
    cfg = jack_videoproduktion._laden(root)
    _, medien = jack_videoproduktion._medienordner(root, cfg, stand["pilot"])
    basis = medien / jack_videoproduktion.AUFTRAGSORDNER
    aktualisiert = []
    if basis.is_dir() and not basis.is_symlink():
        for manifest in sorted(basis.glob("VP-*/auftrag.json")):
            if len(aktualisiert) >= limit:
                break
            try:
                daten = _lesen(manifest)
                if daten.get("status") == "in_produktion":
                    aktualisiert.append(aktualisieren(root, daten["kennung"]))
            except (OSError, ValueError):
                continue
    return {"geprueft": len(aktualisiert), "aktualisiert": aktualisiert}
