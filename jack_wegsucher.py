#!/usr/bin/env python3
"""Block 32.2: Wegsucher - feste Regeln in Code, kein Modellaufruf, entscheidet
VOR jedem Start, welcher Weg (Motor) einen Auftrag ausfuehrt. Ruflo wird hier
allenfalls beraten gefragt (Block 33.2), entscheidet aber nicht mit.

Weg 0  Identischer Auftrag (Hash aus Auftragstext + Quelldatei-Hash) bereits
       erledigt: Ergebnis wiederverwenden, 0,00 USD.
Weg 1  Reine Textarbeit ohne Werkzeuge (zusammenfassen, entwerfen,
       klassifizieren, extrahieren, uebersetzen, Text pruefen): motor_direkt.
Weg 2  Braucht Dateien schreiben, Werkzeuge, mehrere Schritte, Code:
       Claude-Code-CLI mit Stufe (arbeiter.sh, bestehender Motor); Ruflo-Motor
       nur, wenn der Auftrag motor: ruflo ausdruecklich verlangt.

Auftragsfeld motor: auto ist Standard; ein ausdrueckliches motor: <wert>
uebersteuert IMMER - der Wegsucher raet dann nicht mehr.
"""
import hashlib
import json
import re
from pathlib import Path

HIER = Path(__file__).resolve().parent
CACHE_DATEI = "betrieb/wegsucher_cache.json"

# Direkte Signalwoerter aus dem Auftragstext Block 32.2 - reine Textarbeit.
TEXTARBEIT_VERBEN = (
    "zusammenfass", "fasse zusammen", "fasse ", " zusammen", "entwirf", "entwurf", "klassifizier",
    "extrahier", "übersetz", "uebersetz", "formulier",
    "prüfe den text", "pruefe den text", "prüfe diesen text", "pruefe diesen text",
)
# Signalwoerter, die Werkzeuge/Dateien/Code/mehrere Schritte verlangen - Weg 2.
WERKZEUG_VERBEN = (
    "schreibe die datei", "erstelle die datei", "lege die datei", "speichere unter",
    "ändere den code", "aendere den code", "implementier", "programmier",
    "führe aus", "fuehre aus", "installier", "deploy", " code ", "skript", "script",
    "recherchiere im web", "suche im internet", "lade herunter", "veröffentlich",
    "veroeffentlich", "sende eine mail", "erstelle mehrere dateien",
)


def _hash_datei(pfad):
    try:
        return hashlib.sha256(Path(pfad).read_bytes()).hexdigest()[:16]
    except OSError:
        return "fehlt:" + str(pfad)


def auftrag_hash(auftragstext, quelldateien=None):
    h = hashlib.sha256()
    h.update((auftragstext or "").strip().encode("utf-8"))
    for p in sorted(quelldateien or []):
        h.update(("|" + str(p) + ":" + _hash_datei(p)).encode("utf-8"))
    return h.hexdigest()[:32]


def _cache_pfad(root):
    return Path(root) / CACHE_DATEI


def cache_lesen(root):
    try:
        return json.loads(_cache_pfad(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def cache_eintragen(root, hash_, ergebnis_pfad, herkunft, zeit):
    daten = cache_lesen(root)
    daten[hash_] = {"ergebnis_pfad": str(ergebnis_pfad), "herkunft": herkunft, "zeit": zeit}
    pfad = _cache_pfad(root)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    tmp = pfad.with_suffix(".json.neu")
    tmp.write_text(json.dumps(daten, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(pfad)


def wiederverwendbar(root, hash_):
    eintrag = cache_lesen(root).get(hash_)
    if not eintrag:
        return None
    if not Path(root, eintrag["ergebnis_pfad"]).exists():
        return None
    return eintrag


def _enthaelt(text, muster):
    text = text.lower()
    return [m for m in muster if m in text]


def entscheidung(kopf, auftragstext, quelldateien=None, root="."):
    """Gibt {'weg': 'wiederverwendung'|'direkt'|'cli'|'ruflo', 'grund': str,
    'hash': str, 'wiederverwendung': eintrag-oder-None} zurueck."""
    hash_ = auftrag_hash(auftragstext, quelldateien)
    cache_treffer = wiederverwendbar(root, hash_)
    if cache_treffer:
        return {"weg": "wiederverwendung", "hash": hash_,
                "grund": "identischer Auftrag (Hash %s) bereits erledigt am %s -> 0,00 USD"
                         % (hash_, cache_treffer.get("zeit", "?")),
                "wiederverwendung": cache_treffer}

    motor_kopf = str((kopf or {}).get("motor") or "auto").strip().lower()
    if motor_kopf not in ("", "auto"):
        ziel = {"api": "cli", "ruflo": "ruflo", "direkt": "direkt", "cli": "cli"}.get(motor_kopf, "cli")
        return {"weg": ziel, "hash": hash_,
                "grund": "motor im Auftragskopf ausdruecklich gesetzt: '%s' -> Weg '%s'" % (motor_kopf, ziel),
                "wiederverwendung": None}

    if quelldateien and len(quelldateien) > 1:
        return {"weg": "cli", "hash": hash_,
                "grund": "mehr als eine Quelldatei -> mehrschrittig, Weg 2 (CLI)",
                "wiederverwendung": None}

    werkzeug_treffer = _enthaelt(auftragstext, WERKZEUG_VERBEN)
    if werkzeug_treffer:
        return {"weg": "cli", "hash": hash_,
                "grund": "Werkzeug-/Datei-/Code-Signalwoerter gefunden (%s) -> Weg 2 (CLI)"
                         % ", ".join(werkzeug_treffer[:3]),
                "wiederverwendung": None}

    text_treffer = _enthaelt(auftragstext, TEXTARBEIT_VERBEN)
    if text_treffer:
        return {"weg": "direkt", "hash": hash_,
                "grund": "reine Textarbeit erkannt (%s), keine Werkzeugsignale -> Weg 1 (direkt)"
                         % ", ".join(text_treffer[:3]),
                "wiederverwendung": None}

    return {"weg": "cli", "hash": hash_,
            "grund": "kein eindeutiges Textarbeit-Signalwort gefunden -> vorsichtshalber Weg 2 (CLI)",
            "wiederverwendung": None}


if __name__ == "__main__":
    import tempfile
    BEISPIELE = [
        ({"motor": "auto"}, "Fasse die ACTIVE_CONTEXT.md in fuenf Saetzen zusammen.", []),
        ({"motor": "auto"}, "Uebersetze diesen Absatz ins Englische.", []),
        ({"motor": "auto"}, "Schreibe die Datei Bericht.md mit dem Ergebnis.", []),
        ({"motor": "auto"}, "Implementiere eine neue Funktion in server.py fuer den Guthaben-Export.", []),
        ({"motor": "auto"}, "Klassifiziere diese 20 E-Mails nach Dringlichkeit.", []),
        ({"motor": "ruflo"}, "Recherchiere im Web nach aktuellen Preisen.", []),
    ]
    for kopf, text, quellen in BEISPIELE:
        e = entscheidung(kopf, text, quellen, root=str(HIER))
        print(e["weg"].upper().ljust(14), "-", text, "\n   Grund:", e["grund"])

    # Weg 0 (Wiederverwendung) eigens vorfuehren, in einer isolierten Test-Wurzel
    # (nicht im echten betrieb/wegsucher_cache.json, das bleibt unberuehrt).
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "auftraege" / "erledigt").mkdir(parents=True)
        ergebnis_datei = Path(tmp) / "auftraege" / "erledigt" / "BEISPIEL_wegsucher_test.md"
        ergebnis_datei.write_text("# Ergebnis (Beispiel)\n", encoding="utf-8")
        beispiel = "Fasse die MEISTERWERK-Vision in drei Saetzen zusammen."
        h = auftrag_hash(beispiel, [])
        cache_eintragen(tmp, h, "auftraege/erledigt/BEISPIEL_wegsucher_test.md", "direkt",
                         "2026-09-23T00:00:00+02:00")
        e = entscheidung({"motor": "auto"}, beispiel, [], root=tmp)
        print(e["weg"].upper().ljust(14), "-", beispiel, "\n   Grund:", e["grund"])
