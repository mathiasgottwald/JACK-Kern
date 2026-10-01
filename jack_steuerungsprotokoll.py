"""Protokoll fuer die Sprachsteuerung (Block 25, Teil A1/A3/H2). Reine
Seiteneffekte: schreibt jede ausgeloeste Aktion mit ihrer Quittung nach
betrieb/steuerung.jsonl, und nicht erkannte Saetze nach
betrieb/steuerung_unbekannt.jsonl. Keine Erkennung und keine Aktionslogik -
die bleibt in jack_steuerung.py (Erkennung) bzw. server.py (Ausfuehrung).

Stand 18.09.2026, Block 25.
"""
import jack_betrieb as b


def herkunft_kennzeichen(herkunft):
    """S-1 P5: patron (echtes Gespraech), test oder probe - nie leer."""
    wert = str(herkunft or "").lower()
    return wert if wert in b.PROBE_ARTEN else "patron"


def merken(root, *, zeit, quelle, satz, stufe, aktion, ziel, dauer_ms, ok, grund, usd, herkunft=None):
    eintrag = {
        "zeit": zeit, "quelle": quelle, "satz": (satz or "")[:300], "stufe": stufe,
        "aktion": aktion, "ziel": ziel, "dauer_ms": dauer_ms, "ok": bool(ok),
        "grund": (grund or "")[:300], "usd": usd, "herkunft": herkunft_kennzeichen(herkunft),
    }
    try:
        b.append(b.area(root) / "steuerung.jsonl", eintrag)
    except OSError:
        pass
    return eintrag


def unbekannt(root, satz, quelle, herkunft=None):
    try:
        b.append(b.area(root) / "steuerung_unbekannt.jsonl",
                 {"zeit": b.now().isoformat(), "satz": (satz or "")[:300], "quelle": quelle,
                  "herkunft": herkunft_kennzeichen(herkunft)})
    except OSError:
        pass


# Block 25b, Teil G1: sechs Arten je Vorgang, unabhaengig von steuerung.jsonl
# (das bleibt die Aktionsspur mit Ziel/Parameter). sprachmessung.jsonl ist die
# schlanke Zeitspur ueber ALLE Wege (Stufe 0 UND Modell), plus die drei neuen
# Gespraechsfluss-Zaehler.
MESSUNG_ARTEN = frozenset(
    {"befehl_stufe0", "modell", "echo_verworfen", "unterbrechung", "doppelt", "fuellsatz"})


def messung(root, art, dauer_ms, quelle, herkunft=None):
    if art not in MESSUNG_ARTEN:
        return None
    eintrag = {"zeit": b.now().isoformat(), "art": art,
               "dauer_ms": max(0, int(dauer_ms or 0)), "quelle": (quelle or "")[:100],
               "herkunft": herkunft_kennzeichen(herkunft)}
    try:
        b.append(b.area(root) / "sprachmessung.jsonl", eintrag)
    except OSError:
        pass
    return eintrag


def _sprachfluss_zaehler(root, tag):
    zeilen = [z for z in b.records(b.area(root) / "sprachmessung.jsonl")
              if str(z.get("zeit", ""))[:10] == tag]
    zaehler = {}
    for z in zeilen:
        art = z.get("art")
        zaehler[art] = zaehler.get(art, 0) + 1
    return zaehler


def tagesauszug(root, tag=None):
    """Block 25, Teil H1: Tageskennzahlen aus steuerung.jsonl fuer den Kasten
    Wissen und das Morgenbriefing. dauer_ms ist die Zeit zwischen Aussenden
    der Aktion und Quittung durch die Oberflaeche - eine Rueckmeldezeit, NICHT
    dieselbe Messung wie das gesonderte "erstes Wort" in sprachmessung.jsonl
    (Teil E2/P8); die beiden Zahlen werden bewusst nicht vermischt."""
    tag = tag or b.now().strftime("%Y-%m-%d")
    zeilen = [z for z in b.records(b.area(root) / "steuerung.jsonl")
              if str(z.get("zeit", ""))[:10] == tag]
    n = len(zeilen)
    # Block 25b, Teil G1: "Echo verworfen n · Unterbrechungen n · doppelt n"
    # kommt aus sprachmessung.jsonl, nicht aus steuerung.jsonl - die drei
    # Zaehler gehoeren an die Tageszeile, auch an einem Tag ohne einen
    # einzigen ausgefuehrten Befehl (nur Echos abgewehrt zaehlt auch).
    mz = _sprachfluss_zaehler(root, tag)
    fluss_suffix = " · Echo verworfen %d · Unterbrechungen %d · doppelt %d" % (
        mz.get("echo_verworfen", 0), mz.get("unterbrechung", 0), mz.get("doppelt", 0))
    if n == 0:
        return {"text": "Sprachsteuerung heute: noch keine Befehle." + fluss_suffix, "anzahl": 0,
                "quelle": "betrieb/steuerung.jsonl"}
    ohne_modell = sum(1 for z in zeilen if z.get("stufe") == 0)
    rueckfaelle = sum(1 for z in zeilen if "rueckfall" in str(z.get("aktion") or ""))
    dauern = sorted(z["dauer_ms"] for z in zeilen if isinstance(z.get("dauer_ms"), (int, float)))
    median = dauern[len(dauern) // 2] if dauern else None
    kosten = sum(float(z.get("usd") or 0) for z in zeilen)
    anteil = round(100 * ohne_modell / n)
    text = ("Sprachsteuerung heute: %d Befehle · %d%% ohne Modell (Stufe 0) · "
            "%d Rückfälle · Median Rückmeldezeit %s · Kosten %.2f USD%s" % (
                n, anteil, rueckfaelle,
                (str(median) + " ms" if median is not None else "unbekannt"), kosten, fluss_suffix))
    return {"text": text, "anzahl": n, "ohne_modell_pct": anteil, "rueckfaelle": rueckfaelle,
            "median_ms": median, "kosten_usd": round(kosten, 4),
            "echo_verworfen": mz.get("echo_verworfen", 0), "unterbrechungen": mz.get("unterbrechung", 0),
            "doppelt": mz.get("doppelt", 0),
            "quelle": "betrieb/steuerung.jsonl"}
