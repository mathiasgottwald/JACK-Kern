#!/usr/bin/env python3
"""Block 32.1: Motor "direkt" - ruft die Anthropic-API unmittelbar auf, ohne
Claude-Code-Sitzung, ohne Werkzeugvorspann, ohne Dateilesungen durch den
Agenten selbst. Fuer reine Textarbeit (Wegsucher Weg 1): zusammenfassen,
entwerfen, klassifizieren, extrahieren, uebersetzen, Text pruefen.

Kontext hoechstens 6000 Token: Auftrag + harte Regeln (CLAUDE.md Abschnitt 7,
Kurzfassung) + Rollenabschnitt + Quelle + bis zu 3 Gedaechtnistreffer (Block 33).

Drei unabhaengige direkte Aufrufe, kein Werkzeugzugriff fuer die Fachkraft:
  1. Fachkraft (Haiku=Stufe 1 oder Sonnet=Stufe 2) - erledigt den Auftrag.
  2. Tor 1 (Abteilungsmanager, gleiche Stufe) - nur "Ist der Auftrag erfuellt?".
  3. Tor 2 (Pruefer, IMMER Sonnet, nie gespart) - sieht nur Auftrag, Ergebnis,
     Quelle, Pruefregeln; verlangt einen Beleg je Aussage.

Abgrenzung (bewusst, siehe Bericht Block 32): fuer GEBUNDENE Auftraege (Kopf
traegt vertrag:/vertrag_sha256:, siehe jack_auftrag.py) bleibt die bestehende
Vertrags-/Schnappschuss-Pruefung von arbeiter.sh/jack_auftrag.py die einzige
Abschlussquelle - motor_direkt ruehrt sie nicht an und schliesst gebundene
Auftraege nicht selbst ab. Fuer alle anderen (einfachen) Auftraege schreibt
motor_direkt einen eigenen Tor-2-Zettel mit eigener, leichter Pruefung: der
komplette Roh-Antworttext des Pruefers wird nebenan gespeichert, sein Hash
steht im Zettel - jede spaetere Pruefung kann den Zettel gegen die
gespeicherte Rohantwort nachrechnen, ohne ein geschuetztes Werkzeugprotokoll
(das es bei einem reinen API-Aufruf ohne Sitzung nicht gibt).
"""
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER))

import jack_betrieb as b
import jack_kosten
import jack_tresor

MODELLE = {1: "claude-haiku-4-5-20251001", 2: "claude-sonnet-5"}
TOR2_MODELL = "claude-sonnet-5"  # Tor 2 wird nie gespart - immer die starke Fachkraft.
KONTEXT_HOECHSTGRENZE_ZEICHEN = 6000 * 4  # grobe Zeichen-Naeherung fuer 6000 Token.

HARTE_REGELN = (
    "Harte Regeln (Kurzfassung aus CLAUDE.md Abschnitt 7, verbindlich):\n"
    "- Nichts loeschen. Keine Aussenwirkung (keine Mail, kein Deploy, keine Installation, kein Kauf).\n"
    "- Keine Schluessel oder Zugangsdaten in der Ausgabe.\n"
    "- Fehler melden statt glaetten. Kein Beschoenigen.\n"
    "- Annahmen nie als Fakten ausgeben: klar trennen geprueft / angenommen / vermutet.\n"
    "- Deutsch, sachlich, ohne Bewertung, sofern nicht ausdruecklich anders verlangt."
)


def _kuerzen(text, hoechstens_zeichen):
    text = text or ""
    if len(text) <= hoechstens_zeichen:
        return text
    return text[:hoechstens_zeichen] + "\n[...gekuerzt, Kontext-Deckel motor_direkt (6000 Token)...]"


def _api(system, nachricht, modell, max_tokens):
    payload = {"model": modell, "max_tokens": max_tokens,
               "system": [{"type": "text", "text": system}],
               "messages": [{"role": "user", "content": nachricht}]}
    anfrage = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json", "x-api-key": jack_tresor.lesen("ANTHROPIC_API_KEY"),
                 "anthropic-version": "2023-06-01"})
    with urllib.request.urlopen(anfrage, timeout=120) as antwort:
        return json.loads(antwort.read())


def _text(ergebnis):
    teile = ergebnis.get("content") or []
    return "".join(t.get("text", "") for t in teile if t.get("type") == "text")


def lauf(root, marke, stufe, auftragstext, quelle_text="", rolle_zusatz="",
         gedaechtnistreffer=None, kind="fachentwurf", teil_von=None, max_tokens_fachkraft=1200):
    """Fuehrt Fachkraft + Tor 1 + Tor 2 aus. Gibt ein Ergebnis-Dict zurueck,
    bucht jeden der drei Aufrufe einzeln mit echten Token im Verbrauchsbuch."""
    modell = MODELLE.get(int(stufe or 1), MODELLE[1])
    gedaechtnis_text = ""
    if gedaechtnistreffer:
        gedaechtnis_text = ("\n\nGedaechtnis (bis zu 3 Treffer, hoechstens 600 Woerter, Block 33):\n"
                             + "\n---\n".join(str(t) for t in gedaechtnistreffer[:3])[:4000])

    # --- 1. Fachkraft ---
    system_fach = _kuerzen(
        HARTE_REGELN + "\n\nDu bist eine Fachkraft der Marke " + str(marke) + ". "
        + str(rolle_zusatz) + gedaechtnis_text, 3000)
    nachricht_fach = _kuerzen(
        "## Auftrag\n" + auftragstext + "\n\n## Quelle\n" + (quelle_text or "(keine Quelldatei mitgegeben)"),
        KONTEXT_HOECHSTGRENZE_ZEICHEN)
    start = jack_kosten.begin(root, kind, "anthropic", modell, teil_von=teil_von)
    try:
        antwort = _api(system_fach, nachricht_fach, modell, max_tokens_fachkraft)
    except urllib.error.HTTPError as fehler:
        jack_kosten.end(root, start, status="fehler", error="HTTP" + str(fehler.code))
        raise
    jack_kosten.end(root, start, verbrauch=antwort.get("usage"), request_id=antwort.get("id"))
    ergebnis_text = _text(antwort)

    # --- 2. Tor 1: Abteilungsmanager ---
    system_tor1 = _kuerzen(
        HARTE_REGELN + "\n\nDu bist der Abteilungsmanager (Tor 1). Du pruefst NUR die grobe "
        "Vollstaendigkeit - NICHT die inhaltliche Richtigkeit gegen die Quelle (das macht "
        "unabhaengig Tor 2, dem du die Quelle nicht wegnimmst). Dir liegt die Quelle "
        "ABSICHTLICH NICHT vor. Pruefe ausschliesslich: hat die Fachkraft ueberhaupt "
        "geantwortet (nicht leer, keine Weigerung), und entspricht die Antwort der im "
        "Auftrag verlangten FORM (z. B. verlangte Anzahl Saetze, verlangte Sprache, "
        "verlangtes Format)? Antworte in der ersten Zeile ausschliesslich mit "
        "\"ERFUELLT\" oder \"NICHT ERFUELLT\", danach in Kuerze warum.", 2000)
    nachricht_tor1 = _kuerzen("## Auftrag\n" + auftragstext + "\n\n## Ergebnis der Fachkraft\n" + ergebnis_text, 3000)
    start_tor1 = jack_kosten.begin(root, kind, "anthropic", modell, teil_von=teil_von)
    antwort_tor1 = _api(system_tor1, nachricht_tor1, modell, 300)
    jack_kosten.end(root, start_tor1, verbrauch=antwort_tor1.get("usage"), request_id=antwort_tor1.get("id"))
    tor1_text = _text(antwort_tor1)
    tor1_erfuellt = tor1_text.strip().upper().startswith("ERFUELLT")

    # --- 3. Tor 2: Pruefer (immer Sonnet) ---
    system_tor2 = _kuerzen(
        HARTE_REGELN + "\n\nDu bist der Pruefer (Tor 2). Du siehst ausschliesslich Auftrag, "
        "Ergebnis, Quelle und diese Pruefregeln - nichts sonst. Belege JEDE tragende Aussage "
        "im Ergebnis gegen die Quelle. Schreibe als ERSTE Zeile genau "
        "\"urteil: ANNAHME\" oder \"urteil: ZURUECKWEISUNG\". Danach je Aussage eine Zeile "
        "\"beleg: <Aussage> -> <Fundstelle in der Quelle oder FEHLT>\". Eine unbelegte "
        "tragende Aussage fuehrt zur Zurueckweisung.", 2500)
    nachricht_tor2 = _kuerzen(
        "## Auftrag\n" + auftragstext + "\n\n## Ergebnis\n" + ergebnis_text
        + "\n\n## Quelle\n" + (quelle_text or "(keine)"), KONTEXT_HOECHSTGRENZE_ZEICHEN)
    start_tor2 = jack_kosten.begin(root, kind, "anthropic", TOR2_MODELL, teil_von=teil_von)
    # 1500 schnitt reale Pruefertexte ab (laengster gemessen: 2394 Token) und wies dann faelschlich zurueck.
    antwort_tor2 = _api(system_tor2, nachricht_tor2, TOR2_MODELL, 4000)
    jack_kosten.end(root, start_tor2, verbrauch=antwort_tor2.get("usage"), request_id=antwort_tor2.get("id"))
    tor2_text = _text(antwort_tor2)
    tor2_hash = hashlib.sha256(tor2_text.encode("utf-8")).hexdigest()
    tor2_angenommen = tor2_text.strip().lower().startswith("urteil: annahme")

    return {
        "modell": modell, "tor2_modell": TOR2_MODELL,
        "ergebnis_text": ergebnis_text,
        "tor1_text": tor1_text, "tor1_erfuellt": tor1_erfuellt,
        "tor2_text": tor2_text, "tor2_hash": tor2_hash, "tor2_angenommen": tor2_angenommen,
        "verbrauch": {"fachkraft": antwort.get("usage"), "tor1": antwort_tor1.get("usage"),
                      "tor2": antwort_tor2.get("usage")},
    }


def tor2_zettel_schreiben(root, auftragsname, ergebnis, hinweis=""):
    """Schreibt den Tor-2-Zettel nach abnahme/tor2/ mit Herkunft "motor: direkt"
    und speichert den vollen Roh-Antworttext des Pruefers daneben - der Hash im
    Zettel laesst sich jederzeit gegen diese Datei nachrechnen (Block 32.1)."""
    ordner = Path(root) / "abnahme" / "tor2"
    ordner.mkdir(parents=True, exist_ok=True)
    zeit = b.now()
    stempel = zeit.strftime("%Y-%m-%d_%H%M")
    stamm = stempel + "_" + Path(auftragsname).stem + "__motor_direkt"
    roh_pfad = ordner / (stamm + "__rohtext.txt")
    roh_pfad.write_text(ergebnis["tor2_text"], encoding="utf-8")
    urteil = "ANNAHME" if ergebnis["tor2_angenommen"] else "ZURUECKWEISUNG"
    zettel_text = (
        "auftrag: " + Path(auftragsname).name + "\n"
        "zeit: " + zeit.isoformat() + "\n"
        "herkunft: motor: direkt\n"
        "modell: " + ergebnis["tor2_modell"] + "\n"
        "urteil: " + urteil + "\n"
        "roh_antwort_datei: " + str(roh_pfad.relative_to(root)) + "\n"
        "roh_antwort_sha256: " + ergebnis["tor2_hash"] + "\n"
        "\n## Pruefertext (Original, unveraendert)\n\n" + ergebnis["tor2_text"]
        + ("\n\n## Hinweis\n" + hinweis if hinweis else "")
    )
    zettel_pfad = ordner / (stamm + ".md")
    zettel_pfad.write_text(zettel_text, encoding="utf-8")
    return zettel_pfad, roh_pfad


def zettel_pruefen(zettel_pfad, root=None):
    """Abnahme-Gegenprobe fuer motor:direkt-Zettel (Block 32.1): der im Zettel
    genannte Hash muss zur tatsaechlich gespeicherten Rohantwort passen. Ohne
    Uebereinstimmung ist der Zettel nicht vertrauenswuerdig - unabhaengig vom
    behaupteten Urteil."""
    zettel_pfad = Path(zettel_pfad)
    root = Path(root) if root else HIER
    text = zettel_pfad.read_text(encoding="utf-8")
    import re
    m_datei = re.search(r"^roh_antwort_datei:\s*(.+)$", text, re.M)
    m_hash = re.search(r"^roh_antwort_sha256:\s*([0-9a-f]{64})$", text, re.M)
    m_herkunft = re.search(r"^herkunft:\s*motor:\s*direkt\s*$", text, re.M)
    if not (m_datei and m_hash and m_herkunft):
        return {"ok": False, "grund": "Zettel traegt nicht die erwarteten motor:direkt-Felder"}
    roh_pfad = root / m_datei[1].strip()
    try:
        roh_text = roh_pfad.read_text(encoding="utf-8")
    except OSError:
        return {"ok": False, "grund": "Rohantwort-Datei fehlt: " + m_datei[1].strip()}
    echter_hash = hashlib.sha256(roh_text.encode("utf-8")).hexdigest()
    if echter_hash != m_hash[1]:
        return {"ok": False, "grund": "Hash im Zettel stimmt nicht mit der gespeicherten Rohantwort ueberein"}
    return {"ok": True, "grund": "Rohantwort-Hash bestaetigt"}


def _kopf(text):
    import re
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    raus = {}
    if not m:
        return raus
    for zeile in m.group(1).splitlines():
        if ":" in zeile:
            k, v = zeile.split(":", 1)
            raus[k.strip().lower()] = v.strip()
    return raus


def _rumpf(text):
    import re
    m = re.match(r"^---\s*\n.*?\n---\s*\n", text, re.S)
    return text[m.end():] if m else text


def _quelldateien_finden(root, text):
    """Heuristik (Block 32.1): sucht rueckwaertskompatibel nach Dateipfaden in
    Backticks, die tatsaechlich existieren, und liest bis zu drei davon
    (grosszuegig begrenzt - lauf() kuerzt ohnehin auf den Kontext-Deckel)."""
    import re
    kandidaten = re.findall(r"`([0-9A-Za-z_./-]+\.(?:md|txt|json))`", text)
    gefunden, texte = [], []
    for k in kandidaten:
        for basis in (Path(root), Path(root).parent.parent):
            pfad = basis / k
            if pfad.is_file():
                try:
                    texte.append("### " + k + "\n" + pfad.read_text(encoding="utf-8", errors="replace"))
                    gefunden.append(str(pfad))
                except OSError:
                    pass
                break
        if len(gefunden) >= 3:
            break
    return gefunden, "\n\n".join(texte)


def verarbeite_auftrag(root, auftragspfad):
    """Volle Lebensdauer eines Auftrags ueber Motor direkt (Block 32.1): lesen,
    Fachkraft+Tor1+Tor2, Ergebnis + Zettel schreiben, Auftrag nach erledigt/
    oder problem/ verschieben, im Wegsucher-Cache fuer Weg 0 eintragen."""
    import jack_wegsucher
    pfad = Path(auftragspfad)
    original_text = pfad.read_text(encoding="utf-8")
    kopf = _kopf(original_text)
    rumpf = _rumpf(original_text)
    marke = kopf.get("marke", "HOLDING")
    import modell_router
    datenklasse = modell_router.datenklasse_aus_kopf(kopf.get("datenklasse"))
    stufe = int(kopf.get("stufe") or 1) if str(kopf.get("stufe") or "1").isdigit() else 1
    quelldateien, quelle_text = _quelldateien_finden(root, rumpf)

    gedaechtnistreffer = []
    try:
        import jack_gedaechtnis
        gedaechtnistreffer = jack_gedaechtnis.treffer_holen(rumpf[:300])
    except Exception:
        pass  # Block 33.1: Gedaechtnis ist Kontext, kein Startvoraussetzung - Fehler weglassen.
    # Block 33.5: Marken-Sicht aus dem JACK-Gedaechtnis, falls der Verteiler sie
    # exportiert hat (JACK_GEDAECHTNIS_EXPORT). Kommt als eigener Treffer dazu.
    export_pfad = os.environ.get("JACK_GEDAECHTNIS_EXPORT")
    if export_pfad and Path(export_pfad).is_file():
        try:
            gedaechtnistreffer.append(Path(export_pfad).read_text(encoding="utf-8")[:2000])
        except OSError:
            pass

    ergebnis = lauf(root, marke, stufe, rumpf, quelle_text=quelle_text,
                     rolle_zusatz="Arbeite genau auf den Auftrag hin, ohne Umschweife.",
                     gedaechtnistreffer=gedaechtnistreffer, kind="fachentwurf")
    zettel_pfad, roh_pfad = tor2_zettel_schreiben(root, pfad.name, ergebnis)
    erfolg = ergebnis["tor1_erfuellt"] and ergebnis["tor2_angenommen"]

    stamm = pfad.stem
    ergebnis_ordner = Path(root) / "auftraege" / "erledigt" / stamm
    ergebnis_ordner.mkdir(parents=True, exist_ok=True)
    ergebnis_datei = ergebnis_ordner / "ergebnis.md"
    ergebnis_datei.write_text(
        "# Ergebnis (Motor direkt, Block 32.1)\n\nModell: " + ergebnis["modell"]
        + "\n\n## Ergebnis der Fachkraft\n" + ergebnis["ergebnis_text"]
        + "\n\n## Tor 1 (Abteilungsmanager)\n" + ergebnis["tor1_text"]
        + "\n\n## Tor 2 (Pruefer, " + ergebnis["tor2_modell"] + ")\nZettel: "
        + str(zettel_pfad.relative_to(root)) + "\nUrteil: "
        + ("ANNAHME" if ergebnis["tor2_angenommen"] else "ZURUECKWEISUNG") + "\n",
        encoding="utf-8")

    vermerk = ("\n\n## Ergebnis (Motor direkt, Block 32.1)\n"
               "- Ergebnisdatei: `%s`\n- Tor-2-Zettel: `%s`\n- Tor 1 erfuellt: %s\n"
               "- Tor 2 Urteil: %s\n- Quelldateien: %s\n- Datenklasse: %s\n"
               % (ergebnis_datei.relative_to(root), zettel_pfad.relative_to(root),
                  ergebnis["tor1_erfuellt"], "ANNAHME" if ergebnis["tor2_angenommen"] else "ZURUECKWEISUNG",
                  ", ".join(quelldateien) or "(keine gefunden)", datenklasse))
    ziel_ordner = "erledigt" if erfolg else "problem"
    ziel = Path(root) / "auftraege" / ziel_ordner / pfad.name
    ziel.write_text(original_text + vermerk, encoding="utf-8")
    pfad.unlink()

    if erfolg:
        hash_ = jack_wegsucher.auftrag_hash(original_text, [])
        jack_wegsucher.cache_eintragen(root, hash_, str(ergebnis_datei.relative_to(root)),
                                        "direkt", b.now().isoformat())
    return {"erfolg": erfolg, "ziel": str(ziel), "ergebnis_datei": str(ergebnis_datei),
            "zettel": str(zettel_pfad), "datenklasse": datenklasse}


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--auftrag":
        ausgang = verarbeite_auftrag(str(HIER), sys.argv[2])
        print(json.dumps(ausgang, ensure_ascii=False))
    else:
        # Kleiner Selbsttest ohne Modellaufruf: prueft nur die Zettel-Schreib-/
        # Pruefmechanik mit einem erfundenen Ergebnis (kein API-Aufruf, keine Kosten).
        root = str(HIER)
        fake = {"tor2_modell": TOR2_MODELL, "tor2_text": "urteil: ANNAHME\nbeleg: Test -> Test",
                "tor2_hash": hashlib.sha256(b"urteil: ANNAHME\nbeleg: Test -> Test").hexdigest(),
                "tor2_angenommen": True}
        zettel, roh = tor2_zettel_schreiben(root, "SELBSTTEST_ohne_kosten.md", fake, hinweis="Selbsttest, kein Modellaufruf")
        print(json.dumps(zettel_pruefen(zettel, root=root), ensure_ascii=False))
