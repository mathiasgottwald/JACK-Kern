"""Higgsfield-API-Adapter fuer JACKs zentrale Videoproduktion.

Dieser Dienst trennt den bereits vorhandenen Higgsfield-Plan (MCP/Chat) von
der API: API-Zugangsdaten liegen ausschliesslich im macOS-Schluesselbund.
Er erzeugt nur mit einem vorbereiteten Auftrag, einem festen Auftragsdeckel
und ohne automatische Aufladung, Upload fremder Dateien oder Veroeffentlichung.
Hochgeladen wird ausschliesslich ein Referenzbild aus 06_Medien der Auftragsmarke
(Bild-zu-Video), ueber Higgsfields eigenen Upload-Weg.
"""
from contextlib import contextmanager
import datetime as dt
from decimal import Decimal, InvalidOperation
import fcntl
import hashlib
import json
from pathlib import Path
import re
import socket
import urllib.error
import urllib.request

import jack_kosten
import jack_medien
import jack_runway
import jack_tresor
import jack_videoproduktion
import jack_vorgaenge

VERSION = "1.5.0"  # F-9 (24.09.2026): Vorgangskennung VOR dem Aufruf (Paket 3)
API = "https://api.higgsfield.ai"
KENNUNG = re.compile(r"VP-[0-9]{8}-[0-9]{6}-[a-f0-9]{8}")
REQUEST_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
TERMINAL = {"completed", "failed", "nsfw", "canceled"}
MAX_ANTWORT = 2_000_000
PREISQUELLE = "Higgsfield API-Katalog, abgerufen 2026-09-21"
ARTEN = ("text_zu_video", "bild_zu_video")
UPLOAD_WEG = "/files/generate-upload-url"
MAX_REFERENZBILD = 20_000_000
BILDTYPEN = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
PLATZHALTER_BILD_URL = "<public_url aus Schritt 1 (Higgsfield-Upload)>"
PLATZHALTER_ENDBILD_URL = "<public_url des Endbilds (gleicher Upload, wenn identisch mit dem Startbild)>"


def _konfiguration(root):
    daten = jack_videoproduktion._laden(root)
    higgsfield = daten.get("higgsfield")
    adapter = daten.get("anbieter_adapter")
    if (not isinstance(adapter, list) or "higgsfield-api@1.0.0" not in adapter
            or not isinstance(higgsfield, dict) or higgsfield.get("aktiv") is not True):
        raise ValueError("Higgsfield-Adapter ist nicht aktiv")
    return daten, higgsfield


def _zahl(wert, name):
    try:
        zahl = Decimal(str(wert))
    except (InvalidOperation, ValueError) as fehler:
        raise ValueError(name + " ist ungueltig") from fehler
    if not zahl.is_finite() or zahl < 0:
        raise ValueError(name + " ist ungueltig")
    return zahl


def _zugang(higgsfield):
    zustand, zugang, hinweis = jack_tresor.stand(higgsfield["schluesselbund"])
    if zustand != "da":
        raise ValueError("Higgsfield-API-Zugang fehlt im macOS-Schluesselbund. " + hinweis)
    if not isinstance(zugang, str) or zugang.count(":") != 1:
        raise ValueError("Higgsfield-API-Zugang im Schluesselbund hat nicht das erwartete Format.")
    teile = zugang.split(":", 1)
    if not all(teile):
        raise ValueError("Higgsfield-API-Zugang im Schluesselbund hat nicht das erwartete Format.")
    return zugang


def bereitschaft(root):
    try:
        _, higgsfield = _konfiguration(root)
        zustand, zugang, hinweis = jack_tresor.stand(higgsfield["schluesselbund"])
        bereit = zustand == "da" and isinstance(zugang, str) and zugang.count(":") == 1 and all(zugang.split(":", 1))
        return {
            "adapter": "higgsfield-api", "version": VERSION, "aktiv": True,
            "bereit": bereit, "schluessel": zustand,
            "max_usd_je_auftrag": higgsfield.get("max_usd_je_auftrag"),
            "automatische_aufladung": False, "webhooks": False,
            "modelle": sorted((higgsfield.get("modelle") or {}).keys()),
            "hinweis": ("Adapter bereit; nur Modell- und Auftragsdeckel, keine automatische Aufladung oder Veroeffentlichung."
                        if bereit else (hinweis if zustand != "da" else "Higgsfield-API-Zugang im Schluesselbund hat nicht das erwartete Format."))
        }
    except (OSError, ValueError, KeyError) as fehler:
        return {"adapter": "higgsfield-api", "version": VERSION, "aktiv": False,
                "bereit": False, "hinweis": str(fehler)[:200]}


def _auftragspfad(root, kennung):
    if not isinstance(kennung, str) or not KENNUNG.fullmatch(kennung):
        raise ValueError("Ungueltige Videoauftragskennung")
    return jack_runway._auftragspfad(root, kennung)


def _lesen(pfad):
    return jack_runway._lesen(pfad)


def _schreiben(pfad, daten):
    jack_runway._schreiben(pfad, daten)


@contextmanager
def _sperre(auftragspfad):
    pfad = auftragspfad.parent / "higgsfield.sperre"
    with pfad.open("a+") as datei:
        try:
            fcntl.flock(datei, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as fehler:
            raise ValueError("Dieser Videoauftrag wird bereits bearbeitet") from fehler
        try:
            yield
        finally:
            fcntl.flock(datei, fcntl.LOCK_UN)


def _modell(higgsfield, modell):
    modelle = higgsfield.get("modelle")
    if not isinstance(modelle, dict) or modell not in modelle:
        raise ValueError("Dieses Higgsfield-Modell ist nicht freigegeben")
    eintrag = modelle[modell]
    if not isinstance(eintrag, dict):
        raise ValueError("Higgsfield-Modell ist ungueltig")
    if (not isinstance(eintrag.get("pfad"), str) or not eintrag["pfad"].startswith("/")
            or not isinstance(eintrag.get("dauer"), list)
            or any(type(wert) is not int for wert in eintrag["dauer"])):
        raise ValueError("Higgsfield-Modell ist unvollstaendig")
    return eintrag


def _kosten(eintrag, dauer):
    if type(dauer) is not int or dauer not in eintrag["dauer"]:
        raise ValueError("Dauer ist fuer dieses Higgsfield-Modell nicht freigegeben")
    return _zahl(eintrag["preis_usd_je_sekunde_maximal"], "Higgsfield-Preis") * dauer


def _prompt(wert):
    return jack_runway._prompt(wert)


def _api(zugang, weg, methode="GET", body=None, timeout=30, opener=None):
    if not isinstance(weg, str) or not weg.startswith("/") or "//" in weg:
        raise ValueError("Higgsfield-API-Pfad ist ungueltig")
    roh = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    req = urllib.request.Request(API + weg, data=roh, method=methode, headers={
        "Authorization": "Key " + zugang,
        "Content-Type": "application/json", "Accept": "application/json",
        "User-Agent": "JACK-Higgsfield/" + VERSION})
    try:
        abruf = opener.urlopen if opener is not None else urllib.request.urlopen
        with abruf(req, timeout=timeout) as antwort:
            payload = antwort.read(MAX_ANTWORT + 1)
            if len(payload) > MAX_ANTWORT:
                raise ValueError("Higgsfield-Antwort ist zu gross")
            daten = json.loads(payload)
    except urllib.error.HTTPError as fehler:
        try:
            inhalt = json.loads(fehler.read(20_000))
            meldung = inhalt.get("detail", "") if isinstance(inhalt, dict) else ""
        except Exception:
            meldung = ""
        # F-9: 4xx = belegter Nicht-Erfolg (Anbieter hat abgelehnt); 5xx bleibt unklar.
        klasse = jack_vorgaenge.AnbieterAbgewiesen if 400 <= int(fehler.code or 0) < 500 else ValueError
        raise klasse("Higgsfield antwortet mit Fehler %s%s" %
                     (fehler.code, (": " + str(meldung)[:160]) if meldung else "")) from fehler
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as fehler:
        raise ValueError("Higgsfield war nicht erreichbar") from fehler
    if not isinstance(daten, dict):
        raise ValueError("Higgsfield-Antwort ist ungueltig")
    return daten


def _verlauf(daten):
    versuche = daten.get("generationen") or []
    if not isinstance(versuche, list) or any(not isinstance(v, dict) for v in versuche):
        raise ValueError("Generationsverlauf ist ungueltig")
    return versuche


def _preisquelle(eintrag):
    quelle, abgerufen = eintrag.get("quelle_preise"), eintrag.get("abgerufen")
    if isinstance(quelle, str) and isinstance(abgerufen, str):
        return "%s, abgerufen %s" % (quelle, abgerufen)
    return PREISQUELLE


def _art(eintrag, referenzbild):
    art = eintrag.get("art")
    if art not in ARTEN:
        raise ValueError("Dieser Adapter startet derzeit nur Text-zu-Video und Bild-zu-Video")
    if art == "text_zu_video" and referenzbild is not None:
        raise ValueError("Text-zu-Video-Modell nimmt kein Referenzbild; mit Referenzbild das Bild-Modell waehlen")
    if art == "bild_zu_video" and referenzbild is None:
        raise ValueError("Referenzbild fehlt: Bild-zu-Video braucht ein Bild aus 06_Medien der Auftragsmarke")
    return art


def _bildtyp(kopf):
    if kopf.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if kopf.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if kopf[:4] == b"RIFF" and kopf[8:12] == b"WEBP":
        return "image/webp"
    return None


def _referenzbild(root, konfiguration, daten, roh):
    """Prueft das Referenzbild vollstaendig lokal, bevor Geld reserviert wird:
    eigene Medienablage der Auftragsmarke (dieselbe Pruefung wie in 7.1), echtes
    PNG/JPEG/WebP laut Dateikopf, hoechstens 20 MB. Liefert Beleg und Inhalt."""
    marke = daten.get("marke")
    if not isinstance(marke, str) or marke not in konfiguration.get("marken", {}):
        raise ValueError("Auftragsmarke ist fuer das Referenzbild unbekannt")
    ziel = jack_videoproduktion._eigenes_material(root, konfiguration, marke, roh)
    typ = BILDTYPEN.get(ziel.suffix.lower())
    if typ is None:
        raise ValueError("Referenzbild muss PNG, JPEG oder WebP sein")
    groesse = ziel.stat().st_size
    if not 0 < groesse <= MAX_REFERENZBILD:
        raise ValueError("Referenzbild ist leer oder groesser als 20 MB")
    inhalt = ziel.read_bytes()
    if len(inhalt) != groesse or _bildtyp(inhalt[:16]) != typ:
        raise ValueError("Referenzbild ist keine gueltige Bilddatei seines Typs")
    beleg = {"pfad": str(ziel.relative_to(jack_videoproduktion._vault(root))), "content_type": typ,
             "bytes": groesse, "sha256": hashlib.sha256(inhalt).hexdigest()}
    return beleg, inhalt


def _https(wert):
    return (isinstance(wert, str) and len(wert) <= 4000 and wert.startswith("https://")
            and not any(ord(zeichen) < 33 for zeichen in wert))


def _hochladen(zugang, beleg, inhalt, opener=None, upload_opener=None):
    """Higgsfield-Upload laut docs.higgsfield.ai/docs/concepts/file-uploads.md:
    1. POST /files/generate-upload-url (mit Higgsfield-Zugang) -> upload_url,
       public_url, upload_headers.
    2. PUT der Bilddatei an upload_url NUR mit upload_headers - der
       Higgsfield-Zugang geht nie an die Speicheradresse.
    Liefert public_url fuer image_url. Keine lokale Pfadangabe verlaesst den Rechner."""
    antwort = _api(zugang, UPLOAD_WEG, "POST", {"content_type": beleg["content_type"]}, opener=opener)
    upload_url, public_url = antwort.get("upload_url"), antwort.get("public_url")
    if not _https(upload_url) or not _https(public_url):
        raise ValueError("Higgsfield hat keine gueltige Upload-Adresse geliefert")
    if antwort.get("content_type") not in (None, beleg["content_type"]):
        raise ValueError("Higgsfield hat einen anderen Bildtyp fuer den Upload vorgegeben")
    kopf = antwort.get("upload_headers") or {}
    if (not isinstance(kopf, dict) or len(kopf) > 20
            or any(not isinstance(k, str) or not isinstance(v, str) or "\n" in k + v or "\r" in k + v
                   for k, v in kopf.items())
            or any(k.lower() in ("authorization", "cookie", "proxy-authorization") for k in kopf)):
        raise ValueError("Higgsfield hat ungueltige Upload-Kopfzeilen geliefert")
    kopf = dict(kopf)
    if not any(k.lower() == "content-type" for k in kopf):
        kopf["Content-Type"] = beleg["content_type"]
    req = urllib.request.Request(upload_url, data=inhalt, method="PUT", headers=kopf)
    try:
        abruf = upload_opener.urlopen if upload_opener is not None else urllib.request.urlopen
        with abruf(req, timeout=120) as ergebnis:
            status = getattr(ergebnis, "status", 200)
    except urllib.error.HTTPError as fehler:
        raise ValueError("Referenzbild-Upload wurde abgelehnt (%s)" % fehler.code) from fehler
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as fehler:
        raise ValueError("Upload-Ziel fuer das Referenzbild war nicht erreichbar") from fehler
    if status not in (200, 201, 204):
        raise ValueError("Referenzbild-Upload nicht bestaetigt (%s)" % status)
    return public_url


def _endbild_wahl(eintrag, daten, endbild):
    """A-5: Endbild aus Parameter oder aus dem Brief (endbild_pfad). Nur Modelle mit
    "endbild": true (Higgsfield-Feld last_image_url) duerfen eines bekommen."""
    endbild = endbild if endbild is not None else daten.get("endbild_pfad")
    if endbild is None:
        return None
    if eintrag.get("art") != "bild_zu_video" or eintrag.get("endbild") is not True:
        raise ValueError("Dieses Higgsfield-Modell ist nicht fuer ein Endbild freigegeben")
    return endbild


def _endbild_laden(root, konfiguration, daten, endbild, referenzbild, start_beleg, start_url,
                   zugang=None, opener=None, upload_opener=None):
    """Endbild gleich Startbild (gleicher Pfad): derselbe Beleg und dieselbe public_url,
    kein zweiter Upload. Sonst eigene Pruefung und eigener Upload."""
    if endbild == referenzbild:
        return start_beleg, start_url
    beleg, inhalt = _referenzbild(root, konfiguration, daten, endbild)
    if zugang is None:
        return beleg, None
    return beleg, _hochladen(zugang, beleg, inhalt, opener, upload_opener)


def _body(eintrag, prompt, dauer, format_, image_url=None, end_image_url=None):
    if eintrag["art"] == "bild_zu_video":
        body = {"prompt": prompt, "image_url": image_url, "duration": dauer,
                "sound": "on" if eintrag.get("audio") else "off"}
        if end_image_url is not None:
            body["last_image_url"] = end_image_url
        return body
    return {"prompt": prompt, "resolution": eintrag["auflosung"],
            "generate_audio": bool(eintrag.get("audio")), "duration": dauer,
            "aspect_ratio": {"quer_16_9": "16:9", "short_9_16": "9:16",
                             "quadrat_1_1": "1:1"}.get(format_, "16:9")}


def starten(root, kennung, prompt, modell="seedance_2_text", dauer=5, opener=None,
            referenzbild=None, upload_opener=None, endbild=None):
    """Startet einen Entwurf mit festem Kostenrahmen: Text-zu-Video ohne Bild oder
    Bild-zu-Video mit einem Referenzbild aus 06_Medien der Auftragsmarke."""
    konfiguration, higgsfield = _konfiguration(root)
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
        if daten.get("status") not in ("briefing", "produktion_bereit"):
            raise ValueError("Videoauftrag ist nicht startbereit")
        eintrag_modell = _modell(higgsfield, modell)
        art = _art(eintrag_modell, referenzbild)
        endbild = _endbild_wahl(eintrag_modell, daten, endbild)
        versuche = _verlauf(daten)
        # F-9: ein belegt abgewiesener Aufruf (ABGEWIESEN) zaehlt nicht als bestehender Lauf; ein UNKLARER schon.
        if any(v.get("anbieter") == "higgsfield" and v.get("status") != "ABGEWIESEN" for v in versuche):
            raise ValueError("Ein Higgsfield-Lauf besteht bereits; kein doppelter Start")
        kosten = _kosten(eintrag_modell, dauer)
        if kosten > _zahl(higgsfield["max_usd_je_auftrag"], "Higgsfield-Auftragsdeckel"):
            raise ValueError("Higgsfield-Auftragsdeckel wuerde ueberschritten")
        bild, inhalt = (_referenzbild(root, konfiguration, daten, referenzbild)
                        if art == "bild_zu_video" else (None, None))
        preisquelle = _preisquelle(eintrag_modell)
        reservierung_id = jack_kosten.reservieren(root, kennung, str(kosten))
        kosten_start = None
        vg = None
        eintrag_absicht = None
        try:
            prompt = _prompt(prompt)
            zugang = _zugang(higgsfield)
            # F-9 (Paket 3, T1): Vorgangskennung VOR dem Aufruf (Journal, Akte, Kostenbuch). Offene
            # Vorgaenge ohne belegte Antwort sperren jeden weiteren Aufruf fuer diesen Videoauftrag.
            vg = jack_vorgaenge.beginnen(
                root, "higgsfield", kennung, "generation:%s:%ds" % (modell, dauer),
                {"prompt": prompt, "modell": modell, "dauer": dauer, "format": daten.get("format"),
                 "referenzbild": (bild or {}).get("sha256"), "endbild": endbild},
                freigabe="echtfreigabe:%s:%s" % (kennung, dt.datetime.now().astimezone().isoformat()))
            eintrag_absicht = {"nummer": len(versuche) + 1, "vorgang": vg,
                               "gestartet": dt.datetime.now().astimezone().isoformat(),
                               "anbieter": "higgsfield", "anbieter_lauf": None, "modell": modell, "art": art,
                               "stufe": eintrag_modell.get("stufe"), "dauer_sekunden": dauer,
                               "kosten_usd_geschaetzt_maximal": str(kosten), "status": "ABSICHT"}
            daten["generationen"] = versuche + [eintrag_absicht]
            _schreiben(pfad, daten)
            kosten_start = jack_kosten.begin(root, "video", "higgsfield", modell, vorgang=vg)
            try:
                image_url = _hochladen(zugang, bild, inhalt, opener, upload_opener) if bild else None
                end_beleg = end_url = None
                if endbild is not None:
                    end_beleg, end_url = _endbild_laden(root, konfiguration, daten, endbild, referenzbild,
                                                        bild, image_url, zugang, opener, upload_opener)
                body = _body(eintrag_modell, prompt, dauer, daten.get("format"), image_url, end_url)
            except Exception as fehler:
                fehler._vor_post = True      # Erzeugungsaufruf ging nie raus
                raise
            antwort = _api(zugang, eintrag_modell["pfad"], "POST", body, opener=opener)
            request_id = str(antwort.get("request_id") or "")
            if not REQUEST_ID.fullmatch(request_id):
                raise ValueError("Higgsfield hat keine gueltige Vorgangskennung geliefert")
        except Exception as fehler:
            # F-9: Ergebnis des Aufrufs dem Vorgang zuordnen. Vor dem POST (Upload, Pruefung) oder mit
            # Ablehnung des Anbieters = belegter Nicht-Erfolg; alles andere = unklar (Zustandspruefung).
            if vg is not None:
                belegt = isinstance(fehler, jack_vorgaenge.AnbieterAbgewiesen) or getattr(fehler, "_vor_post", False)
                (jack_vorgaenge.abgewiesen if belegt else jack_vorgaenge.unklar)(root, vg, str(fehler))
                eintrag_absicht.update({"status": "ABGEWIESEN" if belegt else "UNKLAR", "fehler": str(fehler)[:200]})
                if belegt:
                    eintrag_absicht["kosten_usd_geschaetzt_maximal"] = "0"
                _schreiben(pfad, daten)
            # Videobetrieb Teil 10: reservieren() liegt VOR _prompt()/_zugang()/
            # begin() - ein Fehler dort darf die Reservierung nicht offen lassen.
            # kosten_start existiert erst nach begin(); ohne ihn darf end() nicht
            # aufgerufen werden (begin() lief dann nie), reservierung_abschliessen()
            # aber immer.
            if kosten_start is not None:
                jack_kosten.end(root, kosten_start, status="fehler", error=type(fehler).__name__)
            jack_kosten.reservierung_abschliessen(
                root, reservierung_id, "fehler",
                kosten_start.get("id") if kosten_start is not None else None)
            raise
        jack_vorgaenge.angekommen(root, vg, request_id)
        jack_kosten.end(root, kosten_start, status="gestartet", request_id=request_id,
                        usd_estimated=str(kosten), price_source=preisquelle)
        jack_kosten.reservierung_abschliessen(root, reservierung_id, "ok", kosten_start.get("id"))
        lauf = {"nummer": len(versuche) + 1, "vorgang": vg, "gestartet": dt.datetime.now().astimezone().isoformat(),
                "anbieter": "higgsfield", "anbieter_lauf": request_id, "modell": modell, "art": art,
                "stufe": eintrag_modell.get("stufe"), "dauer_sekunden": dauer,
                "kosten_usd_geschaetzt_maximal": str(kosten), "preisquelle": preisquelle,
                "status": str(antwort.get("status") or "queued").lower(),
                "audio": bool(eintrag_modell.get("audio"))}
        if bild:
            lauf["referenzbild"] = {**bild, "public_url": image_url}
        if endbild is not None:
            lauf["endbild"] = {**end_beleg, "public_url": end_url}
        versuche.append(lauf)
        daten["generationen"] = versuche
        daten["anbieter"] = "higgsfield-api@1.0.0"
        daten["status"] = "in_produktion"
        daten["kosten_gemeldet"] = None
        daten["kosten_geschaetzt_usd"] = str(kosten)
        daten["hinweis"] = "Higgsfield-Vorgang gestartet; noch kein fertiges oder freigegebenes Video."
        _schreiben(pfad, daten)
        return {"kennung": kennung, "status": "in_produktion", "anbieter_lauf": request_id,
                "modell": modell, "art": art, "kosten_usd_geschaetzt_maximal": str(kosten),
                "referenzbild": bild["pfad"] if bild else None,
                "endbild": end_beleg["pfad"] if endbild is not None else None,
                "hinweis": "Erzeugung laeuft intern. Keine Veroeffentlichung."}


def anbieterstatus(root, request_id, opener=None):
    """F-9: nur lesende Zustandsabfrage /requests/{id}/status (fuer jack_vorgaenge.pruefen)."""
    _, higgsfield = _konfiguration(root)
    if not isinstance(request_id, str) or not REQUEST_ID.fullmatch(request_id):
        raise ValueError("Ungueltige Higgsfield-Vorgangskennung")
    return str(_api(_zugang(higgsfield), "/requests/" + request_id + "/status", opener=opener).get("status") or "").lower()


def nachtragen(root, kennung):
    """F-9: siehe jack_runway.nachtragen - Ergebnis eines angekommenen Vorgangs uebernehmen, nie neu aufrufen."""
    return jack_runway.nachtragen(root, kennung, anbieter=("higgsfield",))


def wuerde_starten(root, kennung, prompt, modell="seedance_2_text", dauer=5, referenzbild=None,
                   endbild=None):
    """Prueft und protokolliert einen Higgsfield-Start vollstaendig, OHNE die API aufzurufen.

    Fuehrt dieselben Pruefungen wie starten() aus (Auftragsstatus, Modell, Art,
    Referenzbild, Auftrags- und Globaldeckel, Zugangsformat) und liefert exakt
    die Aufrufe, die tatsaechlich gesendet wuerden - bei Bild-zu-Video
    einschliesslich der zwei Upload-Schritte. Ruft weder _api() noch
    _hochladen() auf. Der Zugangswert wird nur auf sein Format geprueft und nie
    zurueckgegeben oder protokolliert. Der Stopp wird als eigener Status im
    bestehenden Kostenprotokoll festgehalten (kein Verbrauch)."""
    konfiguration, higgsfield = _konfiguration(root)
    pfad = _auftragspfad(root, kennung)
    with _sperre(pfad):
        daten = _lesen(pfad)
        if daten.get("status") not in ("briefing", "produktion_bereit"):
            raise ValueError("Videoauftrag ist nicht startbereit")
        eintrag_modell = _modell(higgsfield, modell)
        art = _art(eintrag_modell, referenzbild)
        endbild = _endbild_wahl(eintrag_modell, daten, endbild)
        versuche = _verlauf(daten)
        kosten = _kosten(eintrag_modell, dauer)
        if kosten > _zahl(higgsfield["max_usd_je_auftrag"], "Higgsfield-Auftragsdeckel"):
            raise ValueError("Higgsfield-Auftragsdeckel wuerde ueberschritten")
        bild, _ = (_referenzbild(root, konfiguration, daten, referenzbild)
                   if art == "bild_zu_video" else (None, None))
        preisquelle = _preisquelle(eintrag_modell)
        reservierung_id = jack_kosten.reservieren(root, kennung, str(kosten))
        kosten_start = None
        try:
            prompt = _prompt(prompt)
            _zugang(higgsfield)  # nur Formatpruefung; Wert wird nicht weitergegeben
            end_beleg = None
            if endbild is not None:
                end_beleg, _ = _endbild_laden(root, konfiguration, daten, endbild, referenzbild, bild, None)
            body = _body(eintrag_modell, prompt, dauer, daten.get("format"),
                         PLATZHALTER_BILD_URL if bild else None,
                         PLATZHALTER_ENDBILD_URL if endbild is not None else None)
            vorbereitend = []
            if bild:
                vorbereitend = [
                    {"schritt": 1, "anbieter": "higgsfield", "methode": "POST", "pfad": UPLOAD_WEG,
                     "body": {"content_type": bild["content_type"]}, "mit_higgsfield_zugang": True,
                     "liefert": ["upload_url", "public_url", "upload_headers"]},
                    {"schritt": 2, "ziel": "<upload_url aus Schritt 1 (vorsignierte Speicheradresse)>",
                     "methode": "PUT", "kopfzeilen": "nur upload_headers aus Schritt 1",
                     "mit_higgsfield_zugang": False, "datei": bild}]
                if end_beleg is not None and end_beleg is not bild:
                    vorbereitend.append({"schritt": 3, "hinweis": "eigener Upload des abweichenden Endbilds",
                                         "datei": end_beleg})
            kosten_start = jack_kosten.begin(root, "video", "higgsfield", modell)
        except Exception as fehler:
            # Videobetrieb Teil 10: wuerde_starten() hatte bisher gar kein
            # try/except - ein Fehler nach reservieren() (z. B. aus _prompt()
            # bei einem zu langen Prompt oder aus _zugang() bei falschem
            # Schluesselformat) liess die Reservierung unaufgeloest haengen.
            if kosten_start is not None:
                jack_kosten.end(root, kosten_start, status="fehler", error=type(fehler).__name__)
            jack_kosten.reservierung_abschliessen(
                root, reservierung_id, "fehler",
                kosten_start.get("id") if kosten_start is not None else None)
            raise
        # usd_estimated bleibt 0, kein Verbrauch (siehe Docstring oben): sonst
        # wuerde end() den vollen Betrag als usd_geschaetzt buchen, und ein
        # einzelner Dry-Run wuerde gegen den Stunden-/Tagesdeckel zaehlen.
        jack_kosten.end(root, kosten_start, status="gestoppt_vor_aufruf",
                        usd_estimated="0", price_source=preisquelle)
        jack_kosten.reservierung_abschliessen(root, reservierung_id, "gestoppt_vor_aufruf", kosten_start.get("id"))
        return {"kennung": kennung, "gestoppt_vor_aufruf": True,
                "vorherige_laeufe": len(versuche), "art": art,
                "endbild": ({"gesetzt": True, "feld": "last_image_url", "pfad": end_beleg["pfad"],
                             "identisch_mit_startbild": end_beleg is bild}
                            if endbild is not None else {"gesetzt": False}),
                "vorbereitende_aufrufe": vorbereitend,
                "wuerde_aufrufen": {"anbieter": "higgsfield", "methode": "POST",
                                     "pfad": eintrag_modell["pfad"], "body": body},
                "kosten_usd_geschaetzt_maximal": str(kosten), "preisquelle": preisquelle,
                "hinweis": "Alle Pruefungen bestanden (Auftrag, Modell, Referenzbild, Kostendeckel, "
                           "Zugangsformat); kein Netzwerkaufruf ausgefuehrt und keiner nötig."}


def aktualisieren(root, kennung, opener=None, download_opener=None):
    """Holt nur den Status des letzten Higgsfield-Laufs und speichert fertige Exporte lokal."""
    _, higgsfield = _konfiguration(root)
    pfad = _auftragspfad(root, kennung)
    with _sperre(pfad):
        daten = _lesen(pfad)
        if daten.get("status") != "in_produktion":
            return {"kennung": kennung, "status": daten.get("status"), "hinweis": "Kein laufender Higgsfield-Vorgang."}
        versuche = _verlauf(daten)
        lauf = next((v for v in reversed(versuche) if v.get("anbieter") == "higgsfield"), None)
        if not lauf:
            raise ValueError("Kein laufender Higgsfield-Vorgang in der Akte")
        request_id = str(lauf.get("anbieter_lauf") or "")
        if not REQUEST_ID.fullmatch(request_id):
            raise ValueError("Laufender Higgsfield-Vorgang ist ungueltig")
        zugang = _zugang(higgsfield)
        antwort = _api(zugang, "/requests/" + request_id + "/status", opener=opener)
        status = str(antwort.get("status") or "").lower()
        lauf["zuletzt_geprueft"] = dt.datetime.now().astimezone().isoformat()
        lauf["status"] = status
        if status not in TERMINAL:
            _schreiben(pfad, daten)
            return {"kennung": kennung, "status": "in_produktion", "anbieter_status": status}
        if status in {"failed", "nsfw", "canceled"}:
            lauf["fehler"] = str(antwort.get("error") or "")[:300]
            daten["status"] = "produktion_bereit"
            daten["hinweis"] = "Erzeugung nicht abgeschlossen; kein automatischer Wiederholungsversuch."
            _schreiben(pfad, daten)
            return {"kennung": kennung, "status": "produktion_bereit", "anbieter_status": status,
                    "hinweis": daten["hinweis"]}
        video = antwort.get("video")
        url = video.get("url") if isinstance(video, dict) else None
        if not isinstance(url, str):
            raise ValueError("Higgsfield hat kein Video geliefert")
        ziel = pfad.parent / ("higgsfield_%02d.mp4" % lauf["nummer"])
        if ziel.exists():
            raise ValueError("Zieldatei des Higgsfield-Videos existiert bereits")
        beleg = jack_runway._download(url, ziel, opener=download_opener)
        vault = Path(root).absolute().parent.parent
        relativ = str(ziel.relative_to(vault))
        ratio = {"quer_16_9": (1280, 720), "short_9_16": (720, 1280), "quadrat_1_1": (720, 720)}
        breite, hoehe = ratio.get(daten.get("format"), (1, 1))
        pruefung = jack_medien.pruefen(root, relativ, min_breite=breite, min_hoehe=hoehe,
                                       max_dauer_sekunden=lauf["dauer_sekunden"] + 2, ton_noetig=False)
        lauf["ergebnis"] = {"pfad": relativ, **beleg}
        lauf["technische_pruefung"] = pruefung["nachweis"]
        daten["erzeugtes_video"] = relativ
        daten["technische_pruefung"] = pruefung["nachweis"]
        daten["status"] = "qualitaetspruefung" if pruefung["technik_bestanden"] else "produktion_bereit"
        daten["kreative_pruefung"] = "offen"
        daten["patron_freigabe"] = "offen"
        daten["aussenwirkung"] = False
        daten["hinweis"] = "Video lokal gespeichert und technisch geprueft; kreative Pruefung und Patron-Freigabe sind offen."
        _schreiben(pfad, daten)
        return {"kennung": kennung, "status": daten["status"], "video": relativ,
                "technische_pruefung": pruefung["nachweis"], "kreative_pruefung": "offen",
                "patron_freigabe": "offen", "veroeffentlicht": False}
