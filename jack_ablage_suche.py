"""Wissensleiter, Sprosse 2 (Block 25, Teil D2/D4): Volltextsuche ueber die
bereits vorhandene Ablage-Karte (betrieb/gehirn.json) und die gespeicherten
Gespraeche (betrieb/gedaechtnis.sqlite3, FTS5-Tabelle 'themen'). Beides
existierte schon; hier kommt nur eine einfache, schnelle Suche dazu - kein
neuer Index, kein Modellaufruf, unter 2 Sekunden (in der Praxis unter 200 ms,
weil die Knotenliste im Prozess zwischengespeichert wird und nur bei
Aenderung von gehirn.json neu gelesen wird - Auftrag D4).

Stand 18.09.2026, Block 25.
"""
import json
import sqlite3
from pathlib import Path

_CACHE = {"mtime": None, "eintraege": None}


def _laden(root):
    pfad = Path(root) / "betrieb" / "gehirn.json"
    try:
        mtime = pfad.stat().st_mtime
    except OSError:
        return []
    if _CACHE["mtime"] != mtime or _CACHE["eintraege"] is None:
        try:
            daten = json.loads(pfad.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return _CACHE["eintraege"] or []
        eintraege = []
        for n in daten.get("nodes", []):
            label = str(n.get("label") or "")
            weg = str(n.get("pfad") or "")
            zweck = str(n.get("zweck") or "")
            blob = (label + " " + weg + " " + zweck).lower()
            eintraege.append((label, weg, zweck, blob))
        _CACHE["mtime"] = mtime
        _CACHE["eintraege"] = eintraege
    return _CACHE["eintraege"]


def suche(root, begriffe, hoechstens=10):
    """Teilstring-Suche ueber Titel, Pfad und Zweck jedes Knotens. Alle
    Woerter aus `begriffe` muessen vorkommen (unscharfe UND-Suche)."""
    woerter = [w.lower() for w in str(begriffe or "").split() if w.strip()]
    if not woerter:
        return []
    treffer = []
    for label, weg, zweck, blob in _laden(root):
        if all(w in blob for w in woerter):
            treffer.append({"titel": label, "pfad": weg, "zweck": zweck})
            if len(treffer) >= hoechstens:
                break
    return treffer


def suche_gespraeche(root, begriffe, hoechstens=5):
    """FTS5-Suche ueber vergangene Dialoge (Tabelle 'themen', bereits vorhanden)."""
    woerter = [w.strip() for w in str(begriffe or "").split() if w.strip()]
    if not woerter:
        return []
    pfad = Path(root) / "betrieb" / "gedaechtnis.sqlite3"
    if not pfad.exists():
        return []
    anfrage = " ".join('"%s"' % w.replace('"', '""') for w in woerter)
    try:
        con = sqlite3.connect(str(pfad))
        try:
            cur = con.cursor()
            cur.execute(
                "SELECT frage, antwort, zeit FROM themen WHERE themen MATCH ? "
                "ORDER BY rank LIMIT ?", (anfrage, hoechstens))
            zeilen = cur.fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return []
    return [{"frage": f, "antwort": a, "zeit": z} for f, a, z in zeilen]
