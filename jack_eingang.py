#!/usr/bin/env python3
"""F-41 (25.09.2026): Annahme einer Bildschirmaufnahme -> 00_Marken/JACK/eingang_video/. Kein Modell, 0 USD.

Nur .mov/.mp4/.m4v, hoechstens 2 GB, Streaming in Stuecken (nie ganz im Speicher), SHA-256, Name mit Zeitstempel.
Nie ueberschreiben, nie loeschen: der Name ist eindeutig; ein unvollstaendiger Upload bleibt als *.teil-Datei ausserhalb von
eingang_video/ (in betrieb/eingang_video_teil/) und wird gemeldet. Danach wird F-23 (auftraege/pm_ausgang/wartet_patron/)
mit mv -n in den Kanal kern gelegt = ausgeloest. Das Protokoll steht in betrieb/eingang_video.jsonl.

Server-Haken (siehe F-41_FRAGE): in server.py `_post`, vor der JSON-Pruefung
    if self.path.split("?")[0] == "/eingang/video": return jack_eingang.http_annehmen(self)
"""
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import urllib.parse
from pathlib import Path

HIER = Path(__file__).resolve().parent
ERLAUBT = (".mov", ".mp4", ".m4v")
MAX_BYTES = 2 * 1024 ** 3
STUECK = 1024 * 1024
# Erste Kennung im Container (Bytes 4..8): ftyp = moderne MP4/MOV; die anderen sind bei alten QuickTime-Dateien ueblich.
KENNUNGEN = (b"ftyp", b"moov", b"mdat", b"wide", b"free", b"skip", b"pnot")
F23 = "F-23_videoauswertung_rueckstand.md"


class Abgelehnt(Exception):
    def __init__(self, status, text):
        super().__init__(text)
        self.status, self.text = status, text


def groesse_text(n):
    if n >= 1024 ** 3:
        return ("%.1f GB" % (n / 1024 ** 3)).replace(".", ",")
    if n >= 1024 ** 2:
        return ("%.1f MB" % (n / 1024 ** 2)).replace(".", ",")
    return "%d KB" % max(1, round(n / 1024))


def sicherer_name(rohname):
    """Nur der Dateiname, nur harmlose Zeichen, Endung geprueft. -> (stem, endung)"""
    name = os.path.basename(urllib.parse.unquote(str(rohname or "")).replace("\\", "/"))
    stem, endung = os.path.splitext(name)
    endung = endung.lower()
    if endung not in ERLAUBT:
        raise Abgelehnt(415, "Nur .mov, .mp4 und .m4v werden angenommen.")
    stem = re.sub(r"[^\w.\- ]", "_", stem, flags=re.UNICODE).strip(" .")[:80] or "aufnahme"
    return stem, endung


def annehmen(root, rohname, lesen, laenge, herkunft="chat"):
    """lesen(n) -> bytes (wie rfile.read). -> dict(ok, name, bytes, sha256, meldung, ausgeloest). Jede Ablehnung wird protokolliert."""
    try:
        return _annehmen(Path(root), rohname, lesen, laenge, herkunft)
    except Abgelehnt as a:
        _protokoll(root, "abgelehnt", name=str(rohname)[:120], grund=a.text, status=a.status)
        raise


def _annehmen(root, rohname, lesen, laenge, herkunft):
    stem, endung = sicherer_name(rohname)
    if not isinstance(laenge, int) or laenge <= 0:
        raise Abgelehnt(400, "Leere oder unbekannte Größe.")
    if laenge > MAX_BYTES:
        raise Abgelehnt(413, "Die Aufnahme ist größer als 2 GB.")
    ziel_ordner = root / "eingang_video"
    teil_ordner = root / "betrieb" / "eingang_video_teil"
    ziel_ordner.mkdir(parents=True, exist_ok=True)
    teil_ordner.mkdir(parents=True, exist_ok=True)
    stempel = dt.datetime.now().astimezone().strftime("%Y-%m-%d_%H%M%S")
    name = "%s_%s%s" % (stempel, stem, endung)
    i = 1
    while (ziel_ordner / name).exists():
        i += 1
        name = "%s_%s_%d%s" % (stempel, stem, i, endung)
    teil = teil_ordner / (name + ".teil")
    h, rest, erste = hashlib.sha256(), laenge, b""
    try:
        with teil.open("wb") as f:
            while rest > 0:
                stueck = lesen(min(STUECK, rest))
                if not stueck:
                    break
                if len(erste) < 12:
                    erste += stueck[:12 - len(erste)]
                f.write(stueck)
                h.update(stueck)
                rest -= len(stueck)
        if rest:
            raise Abgelehnt(400, "Der Upload ist abgebrochen (%s von %s angekommen)." % (groesse_text(laenge - rest), groesse_text(laenge)))
        if len(erste) < 8 or erste[4:8] not in KENNUNGEN:
            raise Abgelehnt(415, "Das ist keine gültige MOV/MP4-Datei.")
        os.replace(str(teil), str(ziel_ordner / name))
    except OSError as fehler:
        _protokoll(root, "fehler", name=name, grund=str(fehler)[:160])
        raise Abgelehnt(503, "Die Aufnahme konnte nicht abgelegt werden.")
    ausgeloest = _f23_ausloesen(root)
    _protokoll(root, "angenommen", name=name, bytes=laenge, sha256=h.hexdigest(), herkunft=herkunft, f23_ausgeloest=ausgeloest)
    return {"ok": True, "name": name, "bytes": laenge, "groesse": groesse_text(laenge), "sha256": h.hexdigest(),
            "ausgeloest": ausgeloest,
            "meldung": "Aufnahme angekommen (%s, %s), Auswertung startet." % (name, groesse_text(laenge))}


def _f23_ausloesen(root):
    """F-23 aus wartet_patron/ in den Kanal kern (mv -n): der Arbeiter nimmt ihn in der naechsten Runde. -> True/False"""
    quelle = root / "auftraege" / "pm_ausgang" / "wartet_patron" / F23
    ziel = root / "auftraege" / "pm_ausgang" / "kern" / F23
    if not quelle.is_file() or ziel.exists():
        return False
    ziel.parent.mkdir(parents=True, exist_ok=True)
    stat = quelle.stat()
    shutil.move(str(quelle), str(ziel))
    os.utime(ziel, (stat.st_atime, stat.st_mtime))
    return True


def _protokoll(root, art, **felder):
    try:
        e = {"zeit": dt.datetime.now().astimezone().isoformat(), "art": art}
        e.update(felder)
        p = Path(root) / "betrieb" / "eingang_video.jsonl"
        with p.open("a", encoding="utf-8") as d:
            d.write(json.dumps(e, ensure_ascii=False) + "\n")
    except OSError:
        pass


def http_annehmen(handler, root=HIER):
    """Raw-Body-Route fuer server.py: POST /eingang/video?name=<Dateiname>, Content-Type video/*, Body = Datei."""
    def antwort(status, wert):
        handler._senden(status, "application/json", json.dumps(wert, ensure_ascii=False).encode("utf-8"))
    typ = handler.headers.get("Content-Type", "").split(";")[0].strip().lower()
    if not (typ.startswith("video/") or typ == "application/octet-stream"):
        return antwort(415, {"ok": False, "fehler": "Video erforderlich."})
    try:
        laenge = int(handler.headers.get("Content-Length", 0))
    except ValueError:
        return antwort(400, {"ok": False, "fehler": "Ungültige Länge."})
    abfrage = urllib.parse.parse_qs(urllib.parse.urlsplit(handler.path).query)
    rohname = (abfrage.get("name") or [handler.headers.get("X-Dateiname", "")])[0]
    try:
        handler.connection.settimeout(900)
    except (AttributeError, OSError):
        pass
    try:
        return antwort(200, annehmen(root, rohname, handler.rfile.read, laenge))
    except Abgelehnt as a:
        if a.status == 413:                      # Rest der Leitung abraeumen, damit der Browser eine saubere Antwort sieht
            _abraeumen(handler, laenge)
        return antwort(a.status, {"ok": False, "fehler": a.text})


def _abraeumen(handler, laenge, grenze=8 * 1024 ** 2):
    rest = min(laenge, grenze)
    try:
        while rest > 0:
            s = handler.rfile.read(min(65536, rest))
            if not s:
                break
            rest -= len(s)
    except OSError:
        pass
