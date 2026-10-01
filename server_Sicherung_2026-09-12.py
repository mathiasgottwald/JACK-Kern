#!/usr/bin/env python3
"""JACK - lokale Bruecke zwischen der Maske und dem Gedaechtnis in der Holding-Ablage.
Laeuft nur auf diesem Rechner. Kein Zugriff von aussen."""

import json, os, re, sys, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HIER = Path(__file__).resolve().parent
VAULT = HIER.parent.parent                      # .../GOTT WALD HOLDING
PORT = 8777
MODELL = "claude-sonnet-5"
MAX_ZEICHEN_JE_DATEI = 20000

def schluessel(name="ANTHROPIC_API_KEY"):
    """Liest den Schluessel aus SCHLUESSEL.txt (sichtbar) oder .env (versteckt)."""
    for datei in ("SCHLUESSEL.txt", ".env"):
        pfad = HIER / datei
        if not pfad.exists():
            continue
        for zeile in pfad.read_text(encoding="utf-8").splitlines():
            if zeile.strip().startswith(name):
                wert = zeile.split("=", 1)[1].strip().strip('"').strip("'")
                if wert and not wert.startswith("HIER_"):
                    return wert
    return os.environ.get(name, "")

STIMME_ID = {"wert": None}

def arthur_id():
    """Sucht die Stimme ARTHUR im ElevenLabs-Konto. Ergebnis wird gemerkt."""
    if STIMME_ID["wert"]:
        return STIMME_ID["wert"]
    direkt = schluessel("ELEVENLABS_VOICE_ID")
    if direkt:
        STIMME_ID["wert"] = direkt
        return direkt
    key = schluessel("ELEVENLABS_API_KEY")
    if not key:
        return None
    try:
        anfrage = urllib.request.Request("https://api.elevenlabs.io/v1/voices",
                                         headers={"xi-api-key": key})
        with urllib.request.urlopen(anfrage, timeout=30) as antwort:
            liste = json.loads(antwort.read()).get("voices", [])
        gewuenscht = schluessel("ELEVENLABS_VOICE") or "arthur"
        for stimme in liste:
            if gewuenscht.lower() in stimme.get("name", "").lower():
                STIMME_ID["wert"] = stimme["voice_id"]
                return STIMME_ID["wert"]
        if liste:
            STIMME_ID["wert"] = liste[0]["voice_id"]
            return STIMME_ID["wert"]
    except Exception:
        return None
    return None

def vorlesen(text: str):
    """Gibt MP3-Bytes zurueck, oder None wenn ElevenLabs nicht verfuegbar ist."""
    key = schluessel("ELEVENLABS_API_KEY")
    stimme = arthur_id()
    if not key or not stimme:
        return None
    daten = json.dumps({"text": text, "model_id": "eleven_multilingual_v2",
                        "voice_settings": {"stability": 0.45, "similarity_boost": 0.8}}).encode("utf-8")
    anfrage = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{stimme}", data=daten,
        headers={"xi-api-key": key, "content-type": "application/json", "accept": "audio/mpeg"})
    try:
        with urllib.request.urlopen(anfrage, timeout=120) as antwort:
            return antwort.read()
    except Exception:
        return None

def lies(pfad: Path) -> str:
    try:
        return pfad.read_text(encoding="utf-8")[:MAX_ZEICHEN_JE_DATEI]
    except Exception:
        return ""

def marken():
    ordner = VAULT / "00_Marken"
    return [p.name for p in ordner.iterdir() if p.is_dir()] if ordner.is_dir() else []

def gedaechtnis(frage: str) -> str:
    teile = ["# CLAUDE.md\n" + lies(VAULT / "CLAUDE.md"),
             "# VAULT_INDEX.md\n" + lies(VAULT / "VAULT_INDEX.md")]
    frage_klein = frage.lower()
    for marke in marken():
        schluesselwort = marke.lower().replace("_", " ")
        if schluesselwort in frage_klein or marke.lower() in frage_klein:
            ac = VAULT / "00_Marken" / marke / "ACTIVE_CONTEXT.md"
            if ac.exists():
                teile.append(f"# 00_Marken/{marke}/ACTIVE_CONTEXT.md\n" + lies(ac))
    return "\n\n---\n\n".join(t for t in teile if t.strip())

def frage_jack(frage: str) -> str:
    key = schluessel()
    if not key:
        return ("Mir fehlt der Zugangsschluessel. Traege ihn in die Datei .env im Ordner JACK ein, "
                "hinter ANTHROPIC_API_KEY, und starte mich neu.")
    system = (
        "Du bist JACK, Geschaeftsfuehrer der GOTT WALD HOLDING und rechte Hand des Patrons Mathias Gottwald. "
        "Antworte IMMER auf Deutsch, sehr kurz und gesprochen - dein Text wird vorgelesen. "
        "Keine Aufzaehlungen, keine Ueberschriften, keine Sonderzeichen. Zwei bis vier Saetze. "
        "Erst das Ergebnis, dann die Entscheidungsfrage. Trenne klar zwischen geprueft, angenommen und vermutet. "
        "Unterschreiben und Geldtransfer nie ohne ausdrueckliche Freigabe des Patrons.\n\n"
        "Dein Gedaechtnis:\n\n" + gedaechtnis(frage)
    )
    daten = json.dumps({
        "model": MODELL,
        "max_tokens": 700,
        "system": system,
        "messages": [{"role": "user", "content": frage}],
    }).encode("utf-8")
    anfrage = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=daten,
        headers={"content-type": "application/json", "x-api-key": key,
                 "anthropic-version": "2023-06-01"})
    try:
        with urllib.request.urlopen(anfrage, timeout=120) as antwort:
            ergebnis = json.loads(antwort.read())
        return "".join(b.get("text", "") for b in ergebnis.get("content", [])).strip()
    except urllib.error.HTTPError as fehler:
        text = fehler.read().decode("utf-8", "replace")[:300]
        return f"Die Verbindung wurde abgelehnt. Fehlercode {fehler.code}. {text}"
    except Exception as fehler:
        return f"Ich konnte niemanden erreichen: {fehler}"

class Handler(BaseHTTPRequestHandler):
    def _senden(self, code, typ, koerper):
        self.send_response(code)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(len(koerper)))
        self.end_headers()
        self.wfile.write(koerper)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._senden(200, "text/html; charset=utf-8", lies(HIER / "index.html").encode("utf-8"))
        elif self.path == "/status":
            zustand = {"schluessel": bool(schluessel()),
                       "stimme": bool(schluessel("ELEVENLABS_API_KEY")),
                       "marken": marken()}
            self._senden(200, "application/json", json.dumps(zustand).encode("utf-8"))
        else:
            self._senden(404, "text/plain; charset=utf-8", b"nicht gefunden")

    def do_POST(self):
        if self.path == "/stimme":
            laenge = int(self.headers.get("Content-Length", 0))
            try:
                text = json.loads(self.rfile.read(laenge)).get("text", "").strip()
            except Exception:
                text = ""
            ton = vorlesen(text) if text else None
            if ton:
                return self._senden(200, "audio/mpeg", ton)
            return self._senden(204, "text/plain; charset=utf-8", b"")
        if self.path != "/frage":
            return self._senden(404, "text/plain; charset=utf-8", b"nicht gefunden")
        laenge = int(self.headers.get("Content-Length", 0))
        try:
            frage = json.loads(self.rfile.read(laenge)).get("text", "").strip()
        except Exception:
            frage = ""
        if not frage:
            return self._senden(400, "application/json", b'{"antwort":"Ich habe nichts verstanden."}')
        antwort = frage_jack(frage)
        self._senden(200, "application/json", json.dumps({"antwort": antwort}).encode("utf-8"))

    def log_message(self, *_):
        pass

if __name__ == "__main__":
    print(f"JACK laeuft.  Maske oeffnen:  http://localhost:{PORT}")
    print(f"Gedaechtnis:  {VAULT}")
    print("Zum Beenden dieses Fenster schliessen.")
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
