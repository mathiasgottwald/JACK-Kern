#!/usr/bin/env python3
"""Veroeffentlichungsweg (Paket 5, Etappe 1: YouTube, Auftrag F-15, 24.09.2026).

PM-Entscheidungen (entscheidungen/2026-09-24_paket5_veroeffentlichung_VORLAGE.md, Fragen 1-3 JA):
  - YouTube ueber die offizielle Data API v3, Upload IMMER privat, keine Browser-Automatik.
  - Tor: "persoenlich abgenommen" (Datei auftraege/freigabe/ABGENOMMEN_<Kennung>.md, Pruefsumme = Datei-Hash)
    + Einmal-Ticket je Beitrag und Kanal (auftraege/freigabe/VEROEFFENTLICHEN_<Kennung>_<kanal>.ticket, beim
    Verbrauch umbenannt in .verbraucht) + Vorgangskennung vor dem Aufruf (Paket 3), keine automatische
    Wiederholung - bleibt die Antwort aus, folgt die Zustandspruefung, nie ein zweiter Upload.
  - Sichtbarkeit unlisted/public ist ein eigener Tor-Schritt mit eigenem Ticket
    (SICHTBARKEIT_<Kennung>_<kanal>_<unlisted|public>.ticket). Zurueck auf privat geht ohne Ticket (Rueckweg);
    Loeschen braucht ZURUECKZIEHEN_<Kennung>_<kanal>.ticket.
  - Vor dem Upload: belegte Logo-Einblendung (jack_medien.logo_nachweis) und Kostendeckel.

Beitrag = (Kennung, Medium). Kennung ist eine Planer-Nummer (Auftrag mit Abnahmezettel, Paket 4) oder eine
Videoakten-Kennung VP-... (Videostrecke). Fuer eine Auftragsnummer gilt die Paket-4-Regel (Zettelstatus
"persoenlich abgenommen" UND das Medium ist hash-gleich Teil des angenommenen Ergebnisstands); fuer eine
VP-Kennung muss die Zeile "pruefsumme:" der Abnahmedatei den SHA-256 des Mediums tragen (mind. 12 Zeichen).

Zugang YouTube: nur aus dem macOS-Schluesselbund, Dienst PATRONOS, Konto YOUTUBE_OAUTH (JSON mit client_id,
client_secret, refresh_token). Rechte (scopes) aus betrieb/veroeffentlichung.json, Standard youtube.upload +
youtube.readonly (PM). ACHTUNG (Google-Doku, geprueft 24.09.2026): videos.update und videos.delete brauchen
youtube oder youtube.force-ssl - mit den Standardrechten gehen Umschalten und Loeschen nur von Hand im
YouTube Studio. Kein Schluessel erscheint je in einem Protokoll.

Kein Anbieteraufruf ohne Tor. Tests und Gegenproben laufen nur mit der Attrappe (0 USD, kein Netz).
"""
import datetime as dt
import hashlib
import http.server
import json
import os
import re
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER))
import jack_betrieb as betrieb  # noqa: E402
import jack_vorgaenge  # noqa: E402

KANAELE = ("youtube", "attrappe")
SICHTBARKEITEN = ("private", "unlisted", "public")
SCHLUESSELBUND = ("PATRONOS", "YOUTUBE_OAUTH")
SCOPES_STANDARD = ["https://www.googleapis.com/auth/youtube.upload",
                   "https://www.googleapis.com/auth/youtube.readonly"]
SCOPES_AENDERN = ("https://www.googleapis.com/auth/youtube", "https://www.googleapis.com/auth/youtube.force-ssl",
                  "https://www.googleapis.com/auth/youtubepartner")
KONFIG = "veroeffentlichung.json"
PROTOKOLL = "veroeffentlichungen.jsonl"
BELEGORDNER = "veroeffentlichungen"
KOSTENHINWEIS = "YouTube Data API: Upload kostenlos (eigenes Kontingent); 0 USD"
_VP = re.compile(r"VP-\d{8}-\d{6}-[0-9a-f]{8}")
_NR = re.compile(r"\d{1,6}")


class Gesperrt(ValueError):
    """Das Tor laesst den Schritt nicht zu - es wurde NICHTS aufgerufen."""


# ------------------------------------------------------------------ Hilfen
def _jetzt():
    return betrieb.now().isoformat(timespec="seconds")


def _sha(pfad):
    h = hashlib.sha256()
    with open(pfad, "rb") as f:
        for teil in iter(lambda: f.read(1 << 20), b""):
            h.update(teil)
    return h.hexdigest()


def _vault(root):
    return Path(root).resolve().parent.parent


def _protokoll(root, **eintrag):
    try:
        betrieb.append(betrieb.area(root) / PROTOKOLL, {"zeit": _jetzt(), **eintrag})
    except Exception:
        pass


def konfig(root):
    try:
        d = json.loads((betrieb.area(root) / KONFIG).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def scopes(root):
    s = konfig(root).get("youtube_scopes")
    return list(s) if isinstance(s, list) and s else list(SCOPES_STANDARD)


def darf_aendern(root):
    return any(s in SCOPES_AENDERN for s in scopes(root))


def _freigabe(root):
    return Path(root) / "auftraege" / "freigabe"


def ticket_pfad(root, art, kennung, kanal, zusatz=None):
    name = "%s_%s_%s%s.ticket" % (art, kennung, kanal, ("_" + zusatz) if zusatz else "")
    return _freigabe(root) / name


def _ticket_verbrauchen(root, pfad):
    """Einmal-Ticket: umbenennen in .verbraucht (nie loeschen). Gelingt das nicht, gibt es keinen Aufruf."""
    ziel = pfad.with_suffix(".verbraucht")
    n = 2
    while ziel.exists():
        ziel = pfad.with_name("%s.%d.verbraucht" % (pfad.stem, n))
        n += 1
    os.rename(pfad, ziel)
    if pfad.exists() or not ziel.is_file():
        raise Gesperrt("Ticket konnte nicht verbraucht werden - kein Aufruf")
    return ziel


# ------------------------------------------------------------------ Beitrag und Tor
def _akte(root, kennung):
    for p in (_vault(root) / "00_Marken").glob("*/06_Medien/JACK_Videoproduktion/%s/auftrag.json" % kennung):
        try:
            return p, json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return p, None
    return None, None


def _auftrag_zu_nummer(root, nr):
    try:
        z = json.loads((betrieb.area(root) / "laufende.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return next((d for d, n in (z.get("nummern") or {}).items() if str(n) == str(nr)), None)


def beitrag(root, kennung, medium_rel):
    kennung = str(kennung)
    if not (_VP.fullmatch(kennung) or _NR.fullmatch(kennung)):
        raise Gesperrt("Kennung muss eine Planer-Nummer oder eine VP-Kennung sein")
    vault = _vault(root)
    medium = (vault / medium_rel).resolve()
    if vault not in medium.parents or not medium.is_file() or medium.is_symlink():
        raise Gesperrt("Medium liegt nicht als Datei in der Holding: %s" % medium_rel)
    akte_pfad, akte = _akte(root, kennung) if _VP.fullmatch(kennung) else (None, None)
    return {"kennung": kennung, "medium": medium.relative_to(vault).as_posix(), "pfad": medium,
            "sha256": _sha(medium), "bytes": medium.stat().st_size,
            "auftrag": _auftrag_zu_nummer(root, kennung) if _NR.fullmatch(kennung) else None,
            "akte_pfad": akte_pfad, "akte": akte}


def abnahme_pruefen(root, b):
    """(ok, grund): persoenlich abgenommen UND an den Hash des Mediums gebunden."""
    datei = _freigabe(root) / ("ABGENOMMEN_%s.md" % b["kennung"])
    if not datei.is_file() or datei.is_symlink():
        return False, "keine persoenliche Abnahme des Patrons (%s fehlt)" % datei.name
    if b["auftrag"]:
        import jack_abnahmezettel as Z
        import jack_auftrag as A
        ordner, pfad = Z.finden(root, b["auftrag"])
        if not pfad:
            return False, "Auftrag zu Nr. %s nicht gefunden" % b["kennung"]
        geprueft = A.pruefe_auftrag(root, pfad)
        q = (A.quittung(root, geprueft[0]) if geprueft else None) or {}
        summe = (q.get("ergebnisstand") or {}).get("sha256")          # dieselbe Pruefsumme wie der Zettel (Paket 4)
        st = Z.status_bestimmen(root, pfad, ordner, b["kennung"], summe)
        if st.get("wort") != "persönlich abgenommen":
            return False, "Nr. %s ist nicht 'persönlich abgenommen' (%s: %s)" % (b["kennung"], st.get("wort"), st.get("grund", "")[:120])
        dateien = {d["pfad"]: d["sha256"] for d in (q.get("ergebnisstand") or {}).get("dateien", [])}
        if dateien.get(b["medium"]) != b["sha256"]:
            return False, "Medium ist nicht hash-gleich Teil des abgenommenen Ergebnisstands"
        return True, "Zettel Nr. %s persönlich abgenommen; Medium hash-gebunden" % b["kennung"]
    m = re.search(r"^pruefsumme:[ \t]*([0-9a-f]{12,64})[ \t]*$", datei.read_text(encoding="utf-8"), re.M)
    if not m:
        return False, "%s ohne Zeile 'pruefsumme: <SHA-256 des Mediums>'" % datei.name
    if not b["sha256"].startswith(m.group(1)):
        return False, "Prüfsumme in %s passt nicht zum Medium (Datei geändert oder anderes Medium)" % datei.name
    return True, "%s: Prüfsumme = SHA-256 des Mediums" % datei.name


def _upload_vorgang(root, kanal, kennung):
    """Letzter Upload-Vorgang dieses Beitrags auf diesem Kanal (oder None)."""
    kandidaten = [v for v in jack_vorgaenge.stand(root).values()
                  if v.get("kanal") == "veroeffentlichung" and v.get("bezug") == "%s:%s" % (kanal, kennung)
                  and v.get("schritt") == "upload"]
    return sorted(kandidaten, key=lambda v: str(v.get("absicht_zeit") or ""))[-1] if kandidaten else None


def vorbereiten(root, kennung, medium_rel, kanal, adapter_obj=None):
    """Alle Tor-Bedingungen VOR dem Upload - ohne etwas zu verbrauchen oder aufzurufen. Liefert (beitrag, gruende)."""
    if kanal not in KANAELE:
        raise Gesperrt("Unbekannter Kanal: %s" % kanal)
    b = beitrag(root, kennung, medium_rel)
    gruende = []
    ok, grund = abnahme_pruefen(root, b)
    if not ok:
        gruende.append("Abnahme: " + grund)
    import jack_medien
    ok, grund = jack_medien.logo_nachweis(root, b["medium"], b["akte"])
    if not ok:
        gruende.append("Wort-Bild-Marke: " + grund)
    try:
        import jack_grenzen
        erreicht, grund = jack_grenzen.deckel_erreicht(root)   # (bool, Grund) - nicht als Wahrheitswert nehmen
        if erreicht:
            gruende.append("Kostendeckel erreicht - keine Veröffentlichung (%s)" % grund)
    except Exception as fehler:
        gruende.append("Kostendeckel nicht prüfbar (%s)" % type(fehler).__name__)
    if not ticket_pfad(root, "VEROEFFENTLICHEN", b["kennung"], kanal).is_file():
        gruende.append("Einmal-Ticket fehlt: auftraege/freigabe/%s" % ticket_pfad(root, "VEROEFFENTLICHEN", b["kennung"], kanal).name)
    alt = _upload_vorgang(root, kanal, b["kennung"])
    if alt and alt["zustand"] in ("angekommen", "absicht", "unklar", "nicht_pruefbar"):
        gruende.append("Upload-Vorgang %s ist %s - kein zweiter Upload (erst Zustandsprüfung/Patron)" % (alt["vg"], alt["zustand"]))
    a = adapter_obj or adapter(root, kanal)
    gruende += ["Adapter: " + g for g in a.vorbereiten(b)]
    return b, gruende


# ------------------------------------------------------------------ Schritte
def hochladen(root, kennung, medium_rel, kanal, titel, beschreibung="", adapter_obj=None):
    """Genau ein Upload, immer privat. Wirft Gesperrt, wenn das Tor nicht offen ist (dann wurde nichts aufgerufen)."""
    a = adapter_obj or adapter(root, kanal)
    b, gruende = vorbereiten(root, kennung, medium_rel, kanal, a)
    if gruende:
        _protokoll(root, ereignis="gesperrt", kennung=b["kennung"], kanal=kanal, gruende=gruende)
        raise Gesperrt("; ".join(gruende))
    titel = str(titel or "").strip()[:100]
    if not titel:
        raise Gesperrt("Titel fehlt")
    ticket = _ticket_verbrauchen(root, ticket_pfad(root, "VEROEFFENTLICHEN", b["kennung"], kanal))
    vg = jack_vorgaenge.beginnen(root, "veroeffentlichung", "%s:%s" % (kanal, b["kennung"]), "upload",
                                 {"sha256": b["sha256"], "titel": titel}, auftrag=b["auftrag"], freigabe=ticket.name)
    import jack_kosten
    start = jack_kosten.begin(root, "veroeffentlichung", kanal, "data-api")
    text = (str(beschreibung or "").strip() + "\n\nJACK-Vorgang: " + vg).strip()[:4900]
    try:
        video_id = a.hochladen(b, titel, text, vg)
    except jack_vorgaenge.AnbieterAbgewiesen as fehler:
        jack_vorgaenge.abgewiesen(root, vg, str(fehler))
        jack_kosten.end(root, start, "fehler", error="abgewiesen", usd_estimated=0, price_source=KOSTENHINWEIS)
        _protokoll(root, ereignis="abgewiesen", kennung=b["kennung"], kanal=kanal, vg=vg, medium=b["medium"], grund=str(fehler)[:200])
        return {"status": "abgewiesen", "vg": vg, "grund": str(fehler)[:300]}
    except Exception as fehler:
        jack_vorgaenge.unklar(root, vg, "%s: %s" % (type(fehler).__name__, str(fehler)[:200]))
        jack_kosten.end(root, start, "fehler", error="antwort_unklar", usd_estimated=0, price_source=KOSTENHINWEIS)
        _protokoll(root, ereignis="unklar", kennung=b["kennung"], kanal=kanal, vg=vg, medium=b["medium"], grund=type(fehler).__name__)
        return {"status": "unklar", "vg": vg,
                "hinweis": "Antwort nicht belegt - KEIN zweiter Upload. Nächster Schritt: zustand_pruefen()"}
    jack_vorgaenge.angekommen(root, vg, video_id)
    jack_kosten.end(root, start, "ok", usd_estimated=0, price_source=KOSTENHINWEIS)
    nachweis = nachweis_erstellen(root, b, kanal, vg, video_id, a)
    _protokoll(root, ereignis="hochgeladen", kennung=b["kennung"], kanal=kanal, vg=vg, medium=b["medium"], video_id=video_id,
               sichtbarkeit=nachweis["sichtbarkeit"])
    return {"status": "hochgeladen", "vg": vg, "video_id": video_id, "nachweis": nachweis}


def nachweis_erstellen(root, b, kanal, vg, video_id, a):
    """P04: Video-ID, Link, Sichtbarkeit, Zeit, Hash, Vorschaubild-Abruf -> Vorgang (sichtkontrolle), Belegdatei,
    Videoakte (neue Datei daneben, die Akte selbst bleibt unberuehrt)."""
    st = a.status(video_id)
    sichtbarkeit = st.get("sichtbarkeit") or "unbekannt"
    erreichbar = bool(a.erreichbar(video_id)) if sichtbarkeit in ("unlisted", "public") else False
    vorschau = a.vorschau(video_id)
    nachweis = {"schema": 1, "zeit": _jetzt(), "kennung": b["kennung"], "kanal": kanal, "vg": vg,
                "video_id": video_id, "link": a.link(video_id), "studio": a.studio_link(video_id),
                "sichtbarkeit": sichtbarkeit, "upload_status": st.get("upload_status"), "titel": st.get("titel"),
                "erreichbar_oeffentlich": erreichbar, "medium": b["medium"], "medium_sha256": b["sha256"],
                "medium_bytes": b["bytes"], "vorschau": vorschau,
                "hinweis": ("privat: nur im Kanal sichtbar - ein Upload ist noch keine Veröffentlichung (Zwischenstand)"
                            if sichtbarkeit == "private" else "")}
    jack_vorgaenge.sichtkontrolle(root, vg, sichtbarkeit, erreichbar, nachweis["link"], video_id, b["sha256"],
                                  "Status laut Anbieter: %s / %s" % (sichtbarkeit, st.get("upload_status")))
    ordner = betrieb.area(root) / BELEGORDNER
    ordner.mkdir(exist_ok=True)
    ziel = ordner / ("%s_%s_%s.json" % (b["kennung"], kanal, dt.datetime.now().strftime("%Y%m%d_%H%M%S")))
    ziel.write_text(json.dumps(nachweis, ensure_ascii=False, indent=1), encoding="utf-8")
    nachweis["beleg"] = str(ziel)
    if b["akte_pfad"]:
        seite = Path(b["akte_pfad"]).with_name(ziel.name.replace(b["kennung"] + "_", "veroeffentlichung_"))
        if not seite.exists():
            seite.write_text(json.dumps(nachweis, ensure_ascii=False, indent=1), encoding="utf-8")
            nachweis["videoakte"] = str(seite)
    return nachweis


def zustand_pruefen(root, kennung, kanal, adapter_obj=None):
    """Bleibt die Antwort aus: beim Anbieter nachsehen (Suche nach der Vorgangskennung in der Beschreibung).
    Nie ein zweiter Upload. Gefunden -> angekommen (Nachweis wird nachgetragen)."""
    a = adapter_obj or adapter(root, kanal)
    v = _upload_vorgang(root, kanal, str(kennung))
    if not v:
        return {"ergebnis": "kein_vorgang"}

    def pruefer(_root, vorgang):
        gefunden = a.suchen_nach_vorgang(vorgang["vg"])
        if gefunden:
            return {"ergebnis": "angekommen", "anbieter_kennung": gefunden,
                    "beleg": "Video %s trägt die Vorgangskennung in der Beschreibung" % gefunden}
        return {"ergebnis": "nicht_angekommen", "beleg": "Kein Video mit dieser Vorgangskennung im Kanal"}
    erg = jack_vorgaenge.pruefen(root, v["vg"], pruefer)
    if erg.get("ergebnis") == "angekommen" and erg.get("anbieter_kennung"):
        try:
            b = beitrag(root, kennung, _medium_aus_vorgang(root, v))
            erg["nachweis"] = nachweis_erstellen(root, b, kanal, v["vg"], erg["anbieter_kennung"], a)
        except Exception as fehler:
            erg["nachweis_fehler"] = str(fehler)[:200]
    _protokoll(root, ereignis="zustand", kennung=str(kennung), kanal=kanal, vg=v["vg"], ergebnis=erg.get("ergebnis"))
    return erg


def _medium_aus_vorgang(root, v):
    for z in reversed(_jsonl(betrieb.area(root) / PROTOKOLL)):
        if z.get("vg") == v["vg"] and z.get("medium"):
            return z["medium"]
    for p in sorted((betrieb.area(root) / BELEGORDNER).glob("*.json"), reverse=True):
        d = json.loads(p.read_text(encoding="utf-8"))
        if d.get("kennung") == v["bezug"].split(":", 1)[1]:
            return d["medium"]
    raise ValueError("Medium zum Vorgang nicht gefunden")


def _jsonl(pfad):
    try:
        return [json.loads(z) for z in pfad.read_text(encoding="utf-8").splitlines() if z.strip()]
    except (OSError, ValueError):
        return []


def _video_id(root, kanal, kennung):
    v = _upload_vorgang(root, kanal, str(kennung))
    if not v or v["zustand"] != "angekommen" or not v.get("anbieter_kennung"):
        raise Gesperrt("Kein angekommener Upload für %s auf %s" % (kennung, kanal))
    return v


def sichtbarkeit_setzen(root, kennung, kanal, stufe, adapter_obj=None):
    """P03: unlisted/public nur mit eigenem Ticket; zurueck auf private jederzeit (Rueckweg)."""
    if stufe not in SICHTBARKEITEN:
        raise Gesperrt("Sichtbarkeit muss private, unlisted oder public sein")
    a = adapter_obj or adapter(root, kanal)
    v = _video_id(root, kanal, kennung)
    ticket = None
    if stufe != "private":
        pfad = ticket_pfad(root, "SICHTBARKEIT", kennung, kanal, stufe)
        if not pfad.is_file():
            raise Gesperrt("Ticket fehlt: auftraege/freigabe/%s" % pfad.name)
        ticket = _ticket_verbrauchen(root, pfad)
    a.sichtbarkeit(v["anbieter_kennung"], stufe)
    b = beitrag(root, kennung, _medium_aus_vorgang(root, v))
    nachweis = nachweis_erstellen(root, b, kanal, v["vg"], v["anbieter_kennung"], a)
    _protokoll(root, ereignis="sichtbarkeit", kennung=str(kennung), kanal=kanal, stufe=stufe,
               ticket=ticket.name if ticket else None, video_id=v["anbieter_kennung"])
    return nachweis


def zurueckziehen(root, kennung, kanal, loeschen=False, adapter_obj=None):
    """P05: auf privat setzen (ohne Ticket) oder loeschen (nur mit ZURUECKZIEHEN_<Kennung>_<kanal>.ticket)."""
    a = adapter_obj or adapter(root, kanal)
    v = _video_id(root, kanal, kennung)
    if not loeschen:
        a.sichtbarkeit(v["anbieter_kennung"], "private")
        _protokoll(root, ereignis="zurueckgezogen", kennung=str(kennung), kanal=kanal, art="privat",
                   video_id=v["anbieter_kennung"])
        return {"status": "privat", "video_id": v["anbieter_kennung"]}
    pfad = ticket_pfad(root, "ZURUECKZIEHEN", kennung, kanal)
    if not pfad.is_file():
        raise Gesperrt("Löschen braucht ein Ticket: auftraege/freigabe/%s" % pfad.name)
    ticket = _ticket_verbrauchen(root, pfad)
    a.loeschen(v["anbieter_kennung"])
    jack_vorgaenge.sichtkontrolle(root, v["vg"], "geloescht", False, "", v["anbieter_kennung"], "", "gelöscht mit " + ticket.name)
    _protokoll(root, ereignis="zurueckgezogen", kennung=str(kennung), kanal=kanal, art="geloescht",
               ticket=ticket.name, video_id=v["anbieter_kennung"])
    return {"status": "geloescht", "video_id": v["anbieter_kennung"]}


# ------------------------------------------------------------------ Adapter
class Attrappe:
    """Kanal ohne Netz (Tests, Gegenproben). modus: ok | antwort_verloren (Upload kommt an, Antwort nicht) |
    abgewiesen | netzfehler (nichts kommt an)."""

    def __init__(self, root, modus="ok"):
        self.root, self.modus = Path(root), modus
        self.pfad = betrieb.area(root) / "veroeffentlichung_attrappe.json"

    def _lesen(self):
        try:
            return json.loads(self.pfad.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"videos": {}}

    def _schreiben(self, d):
        self.pfad.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")

    def vorbereiten(self, b):
        return [] if b["bytes"] > 0 else ["Medium ist leer"]

    def hochladen(self, b, titel, beschreibung, vg):
        if self.modus == "abgewiesen":
            raise jack_vorgaenge.AnbieterAbgewiesen("Attrappe: HTTP 400")
        if self.modus == "netzfehler":
            raise ConnectionError("Attrappe: keine Verbindung")
        d = self._lesen()
        vid = "att%06d" % (len(d["videos"]) + 1)
        d["videos"][vid] = {"titel": titel, "beschreibung": beschreibung, "sichtbarkeit": "private",
                            "sha256": b["sha256"], "zeit": _jetzt()}
        self._schreiben(d)
        if self.modus == "antwort_verloren":
            raise TimeoutError("Attrappe: Antwort verloren nach dem Upload")
        return vid

    def status(self, vid):
        v = self._lesen()["videos"].get(vid) or {}
        return {"sichtbarkeit": v.get("sichtbarkeit"), "upload_status": "processed" if v else None, "titel": v.get("titel")}

    def suchen_nach_vorgang(self, vg):
        return next((vid for vid, v in self._lesen()["videos"].items() if vg in (v.get("beschreibung") or "")), None)

    def sichtbarkeit(self, vid, stufe):
        d = self._lesen()
        d["videos"][vid]["sichtbarkeit"] = stufe
        self._schreiben(d)

    def loeschen(self, vid):
        d = self._lesen()
        d["videos"][vid]["sichtbarkeit"] = "geloescht"
        self._schreiben(d)

    def erreichbar(self, vid):
        return (self._lesen()["videos"].get(vid) or {}).get("sichtbarkeit") in ("unlisted", "public")

    def vorschau(self, vid):
        return {"abgerufen": False, "grund": "Attrappe ohne Vorschaubild"}

    def link(self, vid):
        return "attrappe://video/" + vid

    def studio_link(self, vid):
        return "attrappe://studio/" + vid

    def anzahl(self):
        return len(self._lesen()["videos"])


class YouTube:
    """YouTube Data API v3 mit urllib (keine neue Abhaengigkeit). Zugang nur aus dem Schluesselbund."""
    TOKEN = "https://oauth2.googleapis.com/token"
    API = "https://www.googleapis.com/youtube/v3"
    UPLOAD = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"

    def __init__(self, root, oeffner=None, zugang=None):
        self.root = root
        self.oeffner = oeffner or urllib.request.urlopen
        self._zugang = zugang
        self._token = None

    def zugang(self):
        if self._zugang is None:
            lauf = subprocess.run(["/usr/bin/security", "find-generic-password", "-s", SCHLUESSELBUND[0],
                                   "-a", SCHLUESSELBUND[1], "-w"], text=True, capture_output=True, timeout=20)
            try:
                self._zugang = json.loads(lauf.stdout) if lauf.returncode == 0 else {}
            except ValueError:
                self._zugang = {}
        return self._zugang

    def vorbereiten(self, b):
        g = []
        z = self.zugang()
        if not all(z.get(k) for k in ("client_id", "client_secret", "refresh_token")):
            g.append("Zugang fehlt im Schlüsselbund (PATRONOS/YOUTUBE_OAUTH mit client_id, client_secret, refresh_token) "
                     "- Anleitung: entscheidungen/2026-09-24_youtube_oauth_ANLEITUNG.md")
        if not str(b["medium"]).lower().endswith((".mp4", ".mov", ".m4v", ".webm")):
            g.append("Kein Videoformat")
        return g

    def _anfrage(self, url, daten=None, methode="GET", kopf=None, roh=None):
        if not self._token:
            z = self.zugang()
            body = urllib.parse.urlencode({"client_id": z.get("client_id", ""), "client_secret": z.get("client_secret", ""),
                                           "refresh_token": z.get("refresh_token", ""), "grant_type": "refresh_token"}).encode()
            with self.oeffner(urllib.request.Request(self.TOKEN, data=body, method="POST"), timeout=30) as a:
                self._token = json.loads(a.read())["access_token"]
        k = {"Authorization": "Bearer " + self._token, **(kopf or {})}
        if daten is not None:
            roh = json.dumps(daten).encode()
            k.setdefault("Content-Type", "application/json; charset=UTF-8")
        try:
            antwort = self.oeffner(urllib.request.Request(url, data=roh, method=methode, headers=k), timeout=600)
        except urllib.error.HTTPError as fehler:
            if 400 <= fehler.code < 500:
                raise jack_vorgaenge.AnbieterAbgewiesen("YouTube HTTP %d" % fehler.code) from None
            raise
        with antwort as a:
            text = a.read()
            return (json.loads(text) if text else {}), dict(a.headers or {})

    def hochladen(self, b, titel, beschreibung, vg):
        meta = {"snippet": {"title": titel, "description": beschreibung, "categoryId": "22"},
                "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False}}
        _, kopf = self._anfrage(self.UPLOAD, meta, "POST", {"X-Upload-Content-Type": "video/mp4",
                                                            "X-Upload-Content-Length": str(b["bytes"])})
        ziel = kopf.get("Location") or kopf.get("location")
        if not ziel:
            raise ValueError("Kein Upload-Ziel (Location) erhalten")
        antwort, _ = self._anfrage(ziel, None, "PUT", {"Content-Type": "video/mp4"}, roh=Path(b["pfad"]).read_bytes())
        return antwort["id"]

    def status(self, vid):
        d, _ = self._anfrage(self.API + "/videos?part=status,snippet&id=" + urllib.parse.quote(vid))
        item = (d.get("items") or [{}])[0]
        return {"sichtbarkeit": (item.get("status") or {}).get("privacyStatus"),
                "upload_status": (item.get("status") or {}).get("uploadStatus"),
                "titel": (item.get("snippet") or {}).get("title")}

    def suchen_nach_vorgang(self, vg):
        d, _ = self._anfrage(self.API + "/channels?part=contentDetails&mine=true")
        liste = (((d.get("items") or [{}])[0].get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads")
        if not liste:
            return None
        p, _ = self._anfrage(self.API + "/playlistItems?part=snippet&maxResults=50&playlistId=" + urllib.parse.quote(liste))
        for item in p.get("items") or []:
            s = item.get("snippet") or {}
            if vg in (s.get("description") or ""):
                return (s.get("resourceId") or {}).get("videoId")
        return None

    def sichtbarkeit(self, vid, stufe):
        if not darf_aendern(self.root):
            raise Gesperrt("Umschalten braucht das Recht youtube.force-ssl (betrieb/veroeffentlichung.json youtube_scopes) "
                           "- bis dahin im YouTube Studio von Hand: " + self.studio_link(vid))
        self._anfrage(self.API + "/videos?part=status", {"id": vid, "status": {"privacyStatus": stufe}}, "PUT")

    def loeschen(self, vid):
        if not darf_aendern(self.root):
            raise Gesperrt("Löschen braucht das Recht youtube.force-ssl - bis dahin im YouTube Studio: " + self.studio_link(vid))
        self._anfrage(self.API + "/videos?id=" + urllib.parse.quote(vid), None, "DELETE")

    def erreichbar(self, vid):
        url = "https://www.youtube.com/oembed?format=json&url=" + urllib.parse.quote(self.link(vid), safe="")
        try:
            with self.oeffner(url, timeout=20) as a:
                return a.status == 200
        except Exception:
            return False

    def vorschau(self, vid):
        url = "https://i.ytimg.com/vi/%s/hqdefault.jpg" % vid
        try:
            with self.oeffner(url, timeout=20) as a:
                roh = a.read()
            return {"abgerufen": True, "url": url, "sha256": hashlib.sha256(roh).hexdigest(), "bytes": len(roh)}
        except Exception as fehler:
            return {"abgerufen": False, "url": url, "grund": type(fehler).__name__ + " (bei privaten Videos üblich)"}

    def link(self, vid):
        return "https://www.youtube.com/watch?v=" + vid

    def studio_link(self, vid):
        return "https://studio.youtube.com/video/%s/edit" % vid


def adapter(root, kanal, **kw):
    if kanal == "youtube":
        return YouTube(root, **kw)
    if kanal == "attrappe":
        return Attrappe(root, **kw)
    raise Gesperrt("Unbekannter Kanal: %s" % kanal)


# ------------------------------------------------------------------ einmalige Anmeldung (Patron)
def anmelden(root):
    """Einmaliger Login (Anleitung): liest client_id/client_secret aus dem Schluesselbund, oeffnet die Google-
    Anmeldeseite, empfaengt den Code auf 127.0.0.1 und legt den refresh_token dazu ab. Gibt nie einen Schluessel aus."""
    y = YouTube(root)
    z = dict(y.zugang())
    if not z.get("client_id") or not z.get("client_secret"):
        raise SystemExit("Im Schlüsselbund PATRONOS/YOUTUBE_OAUTH fehlen client_id/client_secret (Anleitung Schritt 2).")
    code = {}

    class Empfang(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            code["wert"] = (q.get("code") or [""])[0]
            code["fehler"] = (q.get("error") or [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("JACK: Anmeldung empfangen. Dieses Fenster kann geschlossen werden.".encode())

        def log_message(self, *a):
            pass
    server = http.server.HTTPServer(("127.0.0.1", 0), Empfang)
    ruf = "http://127.0.0.1:%d/" % server.server_port
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": z["client_id"], "redirect_uri": ruf, "response_type": "code", "scope": " ".join(scopes(root)),
        "access_type": "offline", "prompt": "consent"})
    faden = threading.Thread(target=server.handle_request, daemon=True)
    faden.start()
    print("Browser öffnet die Google-Anmeldung. Falls nicht, diese Adresse öffnen:\n" + url)
    webbrowser.open(url)
    faden.join(timeout=300)
    server.server_close()
    if not code.get("wert"):
        raise SystemExit("Keine Anmeldung empfangen (%s)." % (code.get("fehler") or "Zeit abgelaufen"))
    body = urllib.parse.urlencode({"code": code["wert"], "client_id": z["client_id"], "client_secret": z["client_secret"],
                                   "redirect_uri": ruf, "grant_type": "authorization_code"}).encode()
    with urllib.request.urlopen(urllib.request.Request(YouTube.TOKEN, data=body, method="POST"), timeout=30) as a:
        antwort = json.loads(a.read())
    if not antwort.get("refresh_token"):
        raise SystemExit("Google hat keinen refresh_token geliefert (Zugriff im Google-Konto entfernen und erneut anmelden).")
    z["refresh_token"] = antwort["refresh_token"]
    lauf = subprocess.run(["/usr/bin/security", "add-generic-password", "-U", "-s", SCHLUESSELBUND[0], "-a",
                           SCHLUESSELBUND[1], "-w", json.dumps(z)], capture_output=True, text=True, timeout=20)
    if lauf.returncode != 0:
        raise SystemExit("Schlüsselbund hat den Eintrag abgelehnt.")
    print("Angemeldet. Rechte: %s. Der Zugang liegt im Schlüsselbund (PATRONOS/YOUTUBE_OAUTH)." % ", ".join(scopes(root)))


if __name__ == "__main__":
    args = sys.argv[1:]
    wurzel = HIER
    try:
        if args[:1] == ["anmelden"]:
            anmelden(wurzel)
        elif args[:1] == ["vorbereiten"] and len(args) == 4:
            b, g = vorbereiten(wurzel, args[1], args[2], args[3])
            print(json.dumps({"kennung": b["kennung"], "medium": b["medium"], "sha256": b["sha256"],
                              "bereit": not g, "gruende": g}, ensure_ascii=False, indent=1))
        elif args[:1] == ["hochladen"] and len(args) >= 5:
            print(json.dumps(hochladen(wurzel, args[1], args[2], args[3], args[4], " ".join(args[5:])), ensure_ascii=False, indent=1))
        elif args[:1] == ["zustand"] and len(args) == 3:
            print(json.dumps(zustand_pruefen(wurzel, args[1], args[2]), ensure_ascii=False, indent=1))
        elif args[:1] == ["sichtbarkeit"] and len(args) == 4:
            print(json.dumps(sichtbarkeit_setzen(wurzel, args[1], args[2], args[3]), ensure_ascii=False, indent=1))
        elif args[:1] == ["zurueckziehen"] and len(args) in (3, 4):
            print(json.dumps(zurueckziehen(wurzel, args[1], args[2], loeschen=args[3:] == ["loeschen"]), ensure_ascii=False, indent=1))
        else:
            print("anmelden | vorbereiten <Kennung> <Medium> <kanal> | hochladen <Kennung> <Medium> <kanal> <Titel> [Beschreibung] | "
                  "zustand <Kennung> <kanal> | sichtbarkeit <Kennung> <kanal> <private|unlisted|public> | "
                  "zurueckziehen <Kennung> <kanal> [loeschen]")
    except Gesperrt as sperre:
        print("GESPERRT: " + str(sperre))
        sys.exit(2)
