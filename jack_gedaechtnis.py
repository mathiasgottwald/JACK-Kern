#!/usr/bin/env python3
"""Block 33.1/33.5: Gedaechtnis ueber Laeufe hinweg.

Vault = einzige Wahrheit (fixierte Entscheidung des Patrons). Jeder erledigte
Lauf bekommt eine Kurzfassung (hoechstens 120 Woerter) an ZWEI Orten:
  1. Im Vault selbst: 00_Marken/<MARKE>/ACTIVE_CONTEXT.md, Abschnitt
     "## Letzte Laeufe" (rollierend, hoechstens 10 Zeilen, Verweis auf
     ergebnis.md).
  2. Bei Ruflo (memory_store, CLI `ruflo memory store`) - reiner Cache,
     jederzeit aus dem Vault neu aufbaubar (siehe gedaechtnis_neu_aufbauen.py).

Vor jedem Lauf holt der Verteiler die 3 passendsten Treffer (memory_search,
hoechstens 600 Woerter) und gibt sie als Kontext mit.

Ruflos CLI (nicht MCP) wird verwendet, weil sie ohne laufende MCP-Sitzung aus
einem einfachen Python-Unterprozess aufrufbar ist - dasselbe Bordmittel-Prinzip
wie beim Rest von JACK. Jeder Aufruf ist zeitbegrenzt und schlaegt niemals den
Planer lahm: Fehler werden geschluckt und protokolliert, nie geworfen.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

HIER = Path(__file__).resolve().parent
HOLDING = HIER.parent.parent
RUFLO_ZEITLIMIT = 45  # Sekunden - das Laden des Embedding-Modells dauert real ca. 15-20s.


def _protokoll(art, **felder):
    try:
        print("JACK-GEDAECHTNIS " + json.dumps({"art": art, **felder}, ensure_ascii=False), flush=True)
    except Exception:
        pass


def _ruflo(argv):
    """Ruft `npx ruflo@latest <argv...>` auf, gibt (ok, stdout) zurueck. Wirft
    nie - ein nicht erreichbares Ruflo darf den Betrieb nie anhalten."""
    try:
        r = subprocess.run(["npx", "-y", "ruflo@latest"] + argv, cwd=str(HIER),
                            capture_output=True, text=True, timeout=RUFLO_ZEITLIMIT)
        return r.returncode == 0, r.stdout + r.stderr
    except (OSError, subprocess.SubprocessError) as fehler:
        return False, str(fehler)


def _kuerzen_woerter(text, hoechstens):
    woerter = (text or "").split()
    if len(woerter) <= hoechstens:
        return " ".join(woerter)
    return " ".join(woerter[:hoechstens]) + " […]"


def kurzfassung_erzeugen(ergebnistext, hoechstens_woerter=120):
    """Keine Modellzusammenfassung (kostet Geld, Block 33 will billig) - reine
    Kuerzung auf die ersten Woerter. Leerzeichen/Ueberschriften normalisiert."""
    text = re.sub(r"^#+\s*.*$", "", ergebnistext or "", flags=re.M)
    text = re.sub(r"\s+", " ", text).strip()
    return _kuerzen_woerter(text, hoechstens_woerter)


def aktiv_context_pfad(marke):
    return HOLDING / "00_Marken" / marke / "ACTIVE_CONTEXT.md"


def vault_eintragen(marke, auftragsnummer_oder_name, kurzfassung, verweis):
    """Traegt eine Zeile in 00_Marken/<MARKE>/ACTIVE_CONTEXT.md ein, Abschnitt
    "## Letzte Laeufe", rollierend hoechstens 10 Zeilen (aelteste faellt raus).
    Legt den Abschnitt an, wenn er fehlt. Keine bestehende Zeile wird geloescht
    ausserhalb dieser Rollierung - nur die eigene Liste rotiert."""
    pfad = aktiv_context_pfad(marke)
    if not pfad.is_file():
        return False, "ACTIVE_CONTEXT.md fehlt fuer Marke %s" % marke
    text = pfad.read_text(encoding="utf-8")
    zeile = "- **%s** (%s): %s — %s" % (auftragsnummer_oder_name,
                                        __import__("jack_betrieb").now().date().isoformat(),
                                        kurzfassung, verweis)
    marker = "## Letzte Läufe"
    if marker in text:
        vor, rest = text.split(marker, 1)
        kopf_rest, *danach = rest.split("\n\n", 1)
        bestehende = [z for z in kopf_rest.splitlines() if z.strip().startswith("- ")]
        neue = ([zeile] + bestehende)[:10]
        neuer_abschnitt = marker + "\n" + "\n".join(neue) + "\n"
        neuer_text = vor + neuer_abschnitt + ("\n\n" + danach[0] if danach else "\n")
    else:
        neuer_text = text.rstrip("\n") + "\n\n" + marker + "\n" + zeile + "\n"
    pfad.write_text(neuer_text, encoding="utf-8")
    return True, "eingetragen"


def lauf_ablegen(marke, auftragsnummer_oder_name, ergebnistext, verweis):
    """Block 33.1: Vault ZUERST (Wahrheit), Ruflo danach (Cache, darf scheitern)."""
    kurz = kurzfassung_erzeugen(ergebnistext, 120)
    vault_ok, vault_grund = vault_eintragen(marke, auftragsnummer_oder_name, kurz, verweis)
    schluessel = "laeufe/%s/%s" % (marke, auftragsnummer_oder_name)
    ruflo_ok, ruflo_ausgabe = _ruflo(["memory", "store", "-k", schluessel, "-v", kurz,
                                       "--namespace", "jack-laeufe"])
    _protokoll("gespeichert", marke=marke, schluessel=schluessel,
               vault_ok=vault_ok, vault_grund=vault_grund, ruflo_ok=ruflo_ok)
    return {"vault_ok": vault_ok, "ruflo_ok": ruflo_ok, "kurzfassung": kurz, "schluessel": schluessel}


def treffer_holen(anfrage, hoechstens_treffer=3, hoechstens_woerter=600):
    """Block 33.1: bis zu 3 passendste Gedaechtnistreffer vor einem Lauf, als
    Liste von Texten. Leere Liste bei jedem Fehler - kein Blockieren."""
    ok, ausgabe = _ruflo(["memory", "search", "-q", anfrage, "--namespace", "jack-laeufe",
                          "--limit", str(hoechstens_treffer), "--format", "json"])
    if not ok:
        _protokoll("suche_fehlgeschlagen", anfrage=anfrage[:80])
        return []
    # Die CLI schreibt "[INFO] ..."-Zeilen VOR dem eigentlichen JSON-Objekt -
    # ein naives Suchen nach der ersten "[" trifft faelschlich das "[INFO]".
    # Das JSON beginnt zuverlaessig auf einer eigenen Zeile mit "{".
    m = re.search(r"^\{.*^\}\s*$", ausgabe, re.S | re.M)
    if not m:
        _protokoll("suche_kein_json", anfrage=anfrage[:80])
        return []
    try:
        daten = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    treffer = []
    gesamt_woerter = 0
    for eintrag in daten.get("results", [])[:hoechstens_treffer]:
        # "search" liefert nur eine gekuerzte "preview" - der volle Text
        # kommt aus einem zweiten Aufruf "retrieve" ueber denselben Schluessel.
        text = ""
        schluessel = eintrag.get("key")
        if schluessel:
            ok2, ausgabe2 = _ruflo(["memory", "retrieve", "-k", schluessel,
                                    "--namespace", "jack-laeufe", "--format", "json"])
            if ok2:
                m2 = re.search(r"^\{.*^\}\s*$", ausgabe2, re.S | re.M)
                if m2:
                    try:
                        text = str(json.loads(m2.group(0)).get("content") or "")
                    except json.JSONDecodeError:
                        text = ""
        if not text:
            text = str(eintrag.get("value") or eintrag.get("preview") or "")
        woerter = text.split()
        if gesamt_woerter + len(woerter) > hoechstens_woerter:
            woerter = woerter[:max(0, hoechstens_woerter - gesamt_woerter)]
        gesamt_woerter += len(woerter)
        if woerter:
            treffer.append(" ".join(woerter))
        if gesamt_woerter >= hoechstens_woerter:
            break
    return treffer


def speichern_roh(schluessel, text, namespace="jack-laeufe"):
    """Bordmittel-Baustein fuer den Wiederaufbau (Block 33.1): legt einen
    Eintrag ohne Vault-Schreibzugriff bei Ruflo ab - der Vault-Eintrag ist ja
    bereits die Quelle, aus der dieser Aufruf stammt."""
    ok, ausgabe = _ruflo(["memory", "store", "-k", schluessel, "-v", text, "--namespace", namespace])
    return ok


def abrufen_roh(schluessel, namespace="jack-laeufe"):
    """Direkter Abruf ueber den exakten Schluessel (kein Suchranking) - fuer
    die Gegenprobe nach einem Wiederaufbau die zuverlaessigste Pruefung."""
    ok, ausgabe = _ruflo(["memory", "retrieve", "-k", schluessel, "--namespace", namespace, "--format", "json"])
    if not ok:
        return None
    m = re.search(r"^\{.*^\}\s*$", ausgabe, re.S | re.M)
    if not m:
        return None
    try:
        return json.loads(m.group(0)).get("content")
    except json.JSONDecodeError:
        return None


def export_marke(root, marke, hoechstens_woerter=300):
    """Block 33.5: kompakte Marken-Sicht aus betrieb/gedaechtnis.sqlite3 nach
    betrieb/gedaechtnis_export/<MARKE>.md exportieren. Ein Lauf bekommt nur
    diese Datei mitgegeben - die Datenbank selbst oeffnet ausschliesslich
    dieser Exporter, nie ein Arbeiter- oder Motor-Prozess."""
    import sqlite3
    db_pfad = Path(root) / "betrieb" / "gedaechtnis.sqlite3"
    ziel_ordner = Path(root) / "betrieb" / "gedaechtnis_export"
    ziel_ordner.mkdir(exist_ok=True)
    ziel = ziel_ordner / (marke + ".md")
    if not db_pfad.is_file():
        ziel.write_text("# Gedaechtnis-Export " + marke + "\n\n(keine Datenbank gefunden)\n", encoding="utf-8")
        return str(ziel)
    zeilen, budget = [], hoechstens_woerter
    try:
        con = sqlite3.connect(str(db_pfad))
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        muster = "%" + marke + "%"
        try:
            cur.execute("SELECT frage, antwort, zeit FROM themen WHERE themen MATCH ? "
                        "ORDER BY zeit DESC LIMIT 10", (marke,))
            treffer = cur.fetchall()
        except sqlite3.OperationalError:
            cur.execute("SELECT frage, antwort, zeit FROM themen WHERE frage LIKE ? OR antwort LIKE ? "
                        "ORDER BY zeit DESC LIMIT 10", (muster, muster))
            treffer = cur.fetchall()
        for r in treffer:
            satz = "- %s: F: %s A: %s" % (str(r["zeit"])[:10], str(r["frage"])[:200], str(r["antwort"])[:200])
            woerter = satz.split()
            if budget - len(woerter) < 0:
                break
            zeilen.append(satz)
            budget -= len(woerter)
        con.close()
    except sqlite3.Error as fehler:
        zeilen = ["(Export fehlgeschlagen: %s)" % type(fehler).__name__]
    text = "# Gedaechtnis-Export " + marke + "\n\n" + ("\n".join(zeilen) if zeilen else "(keine Treffer)") + "\n"
    ziel.write_text(text, encoding="utf-8")
    return str(ziel)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "ablegen":
        print(json.dumps(lauf_ablegen(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]), ensure_ascii=False))
    elif len(sys.argv) > 1 and sys.argv[1] == "suchen":
        print(json.dumps(treffer_holen(sys.argv[2]), ensure_ascii=False))
    elif len(sys.argv) > 2 and sys.argv[1] == "export":
        print(export_marke(str(HIER), sys.argv[2]))
    else:
        print("Nutzung: jack_gedaechtnis.py ablegen <marke> <id> <ergebnistext> <verweis>")
        print("      oder jack_gedaechtnis.py suchen <anfrage>")
