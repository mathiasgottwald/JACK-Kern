#!/usr/bin/env python3
"""Arbeiterlauf mit Ruflo als Begleitschicht.

Ruflo fuehrt KEINE Modellarbeit aus (Beleg: ruflo/00_BESTAND.md, Abschnitt 6.3).
Es stellt gemeinsames Gedaechtnis und Koordination als MCP-Werkzeuge bereit.
Dieser Ausfuehrer startet deshalb denselben claude-Lauf wie arbeiter_api_start.py
und haengt ihm den laufenden Ruflo-Server als MCP-Quelle an.

Was hier bleibt, weil es in JACK bleiben muss:
  - die Kette und beide Tore (stehen in der Anweisung, die arbeiter.sh baut)
  - die Kostenstufe (ruflo/stufen.json, Kopffeld "stufe:")
  - der Tagesdeckel (arbeiter.sh fragt ihn vor dem Start ab)
  - die Buchung von Token und USD (jack_kosten, Art "arbeiter_ruflo")

Rueckgabewerte - gleich wie arbeiter_api_start.py, damit arbeiter.sh nichts
Neues lernen muss:
  0  Lauf erfolgreich
  1  Lauf fachlich fehlgeschlagen
  3  nicht erreichbar (Ruflo-Server oder API) - kein fachlicher Fehler
"""
import datetime
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import jack_modelle
import jack_kosten

STANDARD_STUFEN = {
    "klein": {"budget_usd": 0.75, "aufwand": "low"},
    "mittel": {"budget_usd": 2.00, "aufwand": "medium"},
    "gross": {"budget_usd": 4.00, "aufwand": "high"},
}


def stufen_laden():
    """Budget und Aufwand je Tiefe - dieselbe Quelle wie beim API-Lauf."""
    pfad = ROOT / "betrieb" / "betriebsgrenzen.json"
    try:
        grenzen = json.loads(pfad.read_text(encoding="utf-8"))
        stufen = grenzen.get("api_lauf_je_tiefe")
        if isinstance(stufen, dict) and all(t in stufen for t in STANDARD_STUFEN):
            return stufen
    except (OSError, ValueError):
        pass
    return STANDARD_STUFEN


def kostenstufen():
    return json.loads((ROOT / "ruflo" / "stufen.json").read_text(encoding="utf-8"))


def modell_der_stufe(stufe):
    """(Modell, Fehlertext). Eine gesperrte Stufe wird NICHT stillschweigend
    hochgestuft - sonst kostet ein Auftrag mehr, als der Patron bestellt hat."""
    tabelle = kostenstufen()
    eintrag = (tabelle.get("stufen") or {}).get(str(stufe))
    if not isinstance(eintrag, dict):
        return None, "Unbekannte Kostenstufe " + str(stufe)
    if not eintrag.get("verfuegbar"):
        return None, ("Kostenstufe " + str(stufe) + " ist nicht verfuegbar: "
                      + str(eintrag.get("grund") or "kein Grund hinterlegt"))
    modell = eintrag.get("modell")
    if not isinstance(modell, str) or not modell:
        return None, "Kostenstufe " + str(stufe) + " hat kein Modell hinterlegt"
    return modell, None


def api_key():
    """Schluesselbund zuerst. .env enthaelt seit Block 10 keinen Schluessel mehr."""
    try:
        import jack_tresor
        aus_tresor = jack_tresor.lesen('ANTHROPIC_API_KEY')
        if aus_tresor:
            return aus_tresor
    except Exception:
        pass
    for name in ('SCHLUESSEL.txt', '.env'):
        p = ROOT / name
        if not p.is_file():
            continue
        for line in p.read_text().splitlines():
            key, sep, value = line.partition('=')
            if sep and key.strip() == 'ANTHROPIC_API_KEY':
                value = value.strip().strip('"').strip("'")
                if value and not value.startswith('HIER_'):
                    return value
    return ''


def ruflo_laufzeit():
    """(Port, Endpunkt) des laufenden Servers oder (None, Fehlertext)."""
    pfad = ROOT / "ruflo" / "laufzeit.json"
    try:
        daten = json.loads(pfad.read_text(encoding="utf-8"))
        port = int(daten["port"])
    except (OSError, ValueError, KeyError, TypeError):
        return None, "ruflo/laufzeit.json fehlt oder ist unlesbar - laeuft der Ruflo-Server?"
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/health" % port, timeout=5) as antwort:
            if json.loads(antwort.read().decode("utf-8")).get("status") == "ok":
                return port, "http://localhost:%d/mcp" % port
    except Exception as fehler:
        return None, ("Ruflo-Server auf Port %d antwortet nicht (%s)"
                      % (port, type(fehler).__name__))
    return None, "Ruflo-Server auf Port %d meldet nicht ok" % port


def werkzeugliste():
    try:
        daten = json.loads((ROOT / "ruflo" / "werkzeuge.json").read_text(encoding="utf-8"))
        erlaubt = [w for w in daten.get("erlaubt", []) if isinstance(w, str)]
        return erlaubt
    except (OSError, ValueError):
        return []


def wert_ersetzen(args, name, wert):
    """--name <wert> setzen oder anhaengen; der Aufrufer behaelt die Hoheit."""
    if name in args:
        i = args.index(name)
        if i + 1 < len(args):
            args[i + 1] = wert
            return args
        args[i + 1:i + 1] = [wert]
        return args
    return args + [name, wert]


def protokoll_schreiben(auftrag, stufe, modell, port, ergebnis, usd, verbrauch,
                        dauer, status, text):
    ordner = ROOT / "ruflo" / "protokolle"
    ordner.mkdir(parents=True, exist_ok=True)
    jetzt = datetime.datetime.now().astimezone()
    kurz = (auftrag or "ohne_nummer").replace("/", "_")
    if kurz.endswith(".md"):
        kurz = kurz[:-3]
    # Auftragsnamen beginnen selbst mit dem Datum. Ohne diese Zeile hiesse das
    # Protokoll 2026-09-20_2026-09-20_... (Befund aus dem ersten Live-Lauf).
    if len(kurz) > 11 and kurz[:10] == jetzt.strftime("%Y-%m-%d") and kurz[10] == "_":
        kurz = kurz[11:]
    ziel = ordner / ("%s_%s.md" % (jetzt.strftime("%Y-%m-%d"), kurz))
    zeilen = [
        "# Ruflo-Lauf — %s" % kurz,
        "",
        "| Feld | Wert |",
        "|---|---|",
        "| Zeit | %s |" % jetzt.isoformat(),
        "| Auftrag | %s |" % (auftrag or "unbekannt"),
        "| Kostenstufe | %s |" % stufe,
        "| Modell | %s |" % modell,
        "| Ruflo-Port | %s |" % (port if port else "—"),
        "| Dauer | %.1f Sekunden |" % dauer,
        "| Status | %s |" % status,
        "| USD gemeldet | %s |" % (usd if usd is not None else "— (aus Token berechnet, siehe Verbrauchsbuch)"),
        "| Token | %s |" % (json.dumps(verbrauch, ensure_ascii=False) if verbrauch else "—"),
        "",
        "## Ergebnis des Laufs",
        "",
        (text or "(kein Text)").strip(),
        "",
        "## Hinweis",
        "",
        "Ruflo hat diesen Lauf begleitet, nicht gerechnet. Gerechnet hat das oben",
        "genannte Anthropic-Modell. Die Zahlen stammen aus dem Abschlussprotokoll",
        "des Laufs, nicht aus `ruflo providers usage` — diese Anzeige liefert feste",
        "Beispielwerte (Beleg: ruflo/00_BESTAND.md, Abschnitt 6.4).",
        "",
        "Die verbindliche Fassung von Ergebnis und Nachweis steht in der",
        "Auftragsdatei selbst. Dieses Protokoll ist der Beleg des Laufs.",
    ]
    ziel.write_text("\n".join(zeilen) + "\n", encoding="utf-8")
    return ziel


def main():
    args = sys.argv[1:]

    tiefe = "klein"
    if "--tiefe" in args:
        i = args.index("--tiefe")
        if i + 1 >= len(args):
            raise ValueError("--tiefe braucht einen Wert")
        tiefe = args[i + 1] if args[i + 1] in STANDARD_STUFEN else "klein"
        del args[i:i + 2]

    stufe = str(kostenstufen().get("standardstufe", "2"))
    if "--stufe" in args:
        i = args.index("--stufe")
        if i + 1 >= len(args):
            raise ValueError("--stufe braucht einen Wert")
        stufe = str(args[i + 1])
        del args[i:i + 2]

    auftrag = ""
    if "--auftrag" in args:
        i = args.index("--auftrag")
        if i + 1 >= len(args):
            raise ValueError("--auftrag braucht einen Wert")
        auftrag = str(args[i + 1])
        del args[i:i + 2]

    budget = stufen_laden().get(tiefe, STANDARD_STUFEN[tiefe])
    budget_usd = budget.get("budget_usd", STANDARD_STUFEN[tiefe]["budget_usd"])
    aufwand = budget.get("aufwand", STANDARD_STUFEN[tiefe]["aufwand"])

    modell, fehler = modell_der_stufe(stufe)
    if fehler:
        print("PROBLEM: " + fehler)
        return 1

    # Die Modellauswahl muss gueltig bleiben; eine kaputte Konfiguration haelt
    # jeden Lauf an, genau wie beim API-Ausfuehrer.
    try:
        jack_modelle.load(ROOT)
    except Exception:
        print("PROBLEM: Modellkonfiguration ungueltig; kein Ruflo-Start.")
        return 1

    port, endpunkt = ruflo_laufzeit()
    if port is None:
        print("RUFLO NICHT ERREICHBAR: " + endpunkt)
        return 3

    key = api_key()
    if not key:
        print("API NICHT ERREICHBAR: kein API-Zugang hinterlegt.")
        return 3

    env = os.environ.copy()
    for name in ("ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_BASE_URL",
                 "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY"):
        env.pop(name, None)
    env["ANTHROPIC_API_KEY"] = key
    env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
    env["CLAUDE_FLOW_SECURITY_MODE"] = "strict"
    env["CLAUDE_FLOW_MEMORY_PATH"] = "./.claude-flow.nosync/data"

    # Die Kostenstufe schlaegt das Modell, das arbeiter.sh mitgibt. Das ist der
    # einzige Ort, an dem das passieren darf - und er ist hier, weil der Patron
    # die Stufe im Auftragskopf bestellt.
    args = wert_ersetzen(args, "--model", modell)

    # Ruflo als einzige MCP-Quelle. --strict-mcp-config bleibt stehen: nur was
    # hier steht, ist erreichbar; die globale Konfiguration bleibt aussen vor.
    #
    # ANGESCHLOSSEN WIRD UEBER stdio, NICHT UEBER HTTP. Der HTTP-Server laeuft
    # und meldet sich gesund, nimmt aber keine Werkzeugaufrufe an: tools/call
    # antwortet mit -32002 "Server not initialized", einen Sitzungskopf gibt er
    # nicht heraus, und auf notifications/initialized antwortet er gar nicht
    # (geprueft 20.09.2026). Ueber stdio laufen dieselben Werkzeuge einwandfrei
    # - memory_store und memory_retrieve wurden durchgemessen. Der Auftrag sieht
    # diesen Ersatzweg ausdruecklich vor (S5). Beide Wege benutzen dasselbe
    # Gedaechtnis unter CLAUDE_FLOW_MEMORY_PATH; der HTTP-Server bleibt als
    # Lebenszeichen und fuer spaetere Fassungen bestehen.
    #
    # Der Server wird ueber /bin/sh mit gewechseltem Arbeitsverzeichnis gestartet.
    # Grund, gemessen am 20.09.2026: Ruflo legt neben dem Gedaechtnis auch einen
    # Ordner .claude-flow/ in SEINEM Arbeitsverzeichnis an - unabhaengig von
    # CLAUDE_FLOW_MEMORY_PATH. Weil claude aus der Holding-Wurzel startet, ist
    # dort um 18:01 ein echter .claude-flow/ in iCloud entstanden. Mit dem
    # Wechsel nach .claude-flow.nosync/ bleibt auch dieser Ordner ausserhalb
    # der iCloud-Spiegelung.
    daten = ROOT / ".claude-flow.nosync"
    mcp = {"mcpServers": {"ruflo": {
        "command": "/bin/sh",
        "args": ["-c", "cd %s && exec /opt/homebrew/bin/ruflo mcp start" % shlex.quote(str(daten))],
        "env": {"CLAUDE_FLOW_SECURITY_MODE": "strict",
                "CLAUDE_FLOW_MEMORY_PATH": str(daten / "data")}}}}
    args = wert_ersetzen(args, "--mcp-config", json.dumps(mcp))
    if "--strict-mcp-config" not in args:
        args.append("--strict-mcp-config")

    # Werkzeuge: die Hausliste plus die Auswahl aus ruflo/werkzeuge.json.
    # Ohne Auswahl waeren es 357 Ruflo-Werkzeuge in jedem Lauf.
    erlaubt = werkzeugliste()
    if "--tools" in args:
        i = args.index("--tools")
        if i + 1 < len(args):
            vorhanden = [t for t in args[i + 1].split(",") if t]
            args[i + 1] = ",".join(vorhanden + [t for t in erlaubt if t not in vorhanden])

    command = ["/opt/homebrew/bin/claude", *args,
               "--effort", aufwand, "--max-budget-usd", str(budget_usd),
               "--output-format", "json"]

    beginn = datetime.datetime.now()
    with jack_kosten.track(ROOT, "arbeiter_ruflo", "anthropic", modell) as cost:
        cost["status"] = "fehler"
        process = subprocess.Popen(command, cwd=ROOT.parents[1], env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, start_new_session=True)
        try:
            output, error = process.communicate(timeout=480)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                output, error = process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                output, error = process.communicate()
            try:
                teil = json.loads(output)
                cost.update(verbrauch=jack_kosten.cli_usage(teil), usd=teil.get("total_cost_usd"),
                            request_id=teil.get("session_id"))
            except (ValueError, AttributeError):
                pass
            print("PROBLEM: Ruflo-Lauf nach acht Minuten beendet; vorhandene Arbeit bleibt erhalten.")
            return 1

        try:
            result = json.loads(output)
        except ValueError:
            zusammen = ((output or "") + " " + (error or "")).lower()
            nicht_erreichbar = any(wort in zusammen for wort in (
                "connection", "network", "timed out", "timeout", "unreachable",
                "econnrefused", "enotfound", "getaddrinfo", "authentication",
                "invalid api key", "unauthorized", "401", "403", "429",
                "overloaded", "529", "service unavailable", "503"))
            if nicht_erreichbar:
                print("API NICHT ERREICHBAR: " + (error or output or "")[:300])
                cost.update(status="fehler", error="api_nicht_erreichbar")
                return 3
            print("PROBLEM: Ruflo-Lauf lieferte kein gueltiges Abschlussprotokoll.")
            return 1

        dauer = (datetime.datetime.now() - beginn).total_seconds()
        verbrauch = jack_kosten.cli_usage(result)
        usd = jack_kosten.amount(result.get("total_cost_usd"))

        # S6 des Auftrags: nie schaetzen. Erst der gemeldete Betrag, dann die
        # Rechnung aus den gemeldeten Token und den BELEGTEN Listenpreisen
        # (betrieb/modellpreise.json). Fehlt beides, bricht der Lauf ab.
        if usd is None and not verbrauch:
            cost.update(status="fehler", error="kein_verbrauchsnachweis")
            protokoll_schreiben(auftrag, stufe, modell, port, "abgebrochen", None,
                                None, dauer, "abgebrochen: kein Verbrauchsnachweis",
                                result.get("result") or "")
            print("PROBLEM: Der Lauf hat weder einen Geldbetrag noch Token gemeldet. "
                  "Es wird nicht geschaetzt; der Lauf gilt als nicht gebucht und damit "
                  "als nicht erfuellt.")
            return 1

        fehlgeschlagen = bool(process.returncode) or bool(result.get("is_error"))
        cost.update(verbrauch=jack_kosten.cli_usage(result), usd=result.get("total_cost_usd"),
                    request_id=result.get("session_id"),
                    status="fehler" if fehlgeschlagen else "ok")

        satz = {k: result.get(k) for k in ("session_id", "subtype", "is_error",
                                           "total_cost_usd", "usage", "modelUsage",
                                           "num_turns", "result")}
        satz["zeit"] = datetime.datetime.now().astimezone().isoformat()
        satz["tiefe"] = tiefe
        satz["stufe"] = stufe
        satz["modell"] = modell
        satz["ruflo_port"] = port
        satz["budget_usd"] = budget_usd
        satz["aufwand"] = aufwand
        satz["dauer_s"] = round(dauer, 1)
        satz["auftrag"] = auftrag
        with (ROOT / "ruflo_laeufe.jsonl").open("a") as strom:
            strom.write(json.dumps(satz, ensure_ascii=False) + "\n")

        text = result.get("result") or ("PROBLEM: Ruflo-Lauf ohne Ergebnis ("
                                        + str(result.get("subtype")) + ")")
        ziel = protokoll_schreiben(auftrag, stufe, modell, port,
                                   "fehler" if fehlgeschlagen else "ok",
                                   usd, verbrauch, dauer,
                                   "fehler" if fehlgeschlagen else "ok", text)
        # Reihenfolge ist Pflicht: arbeiter.sh liest die LETZTE nicht leere
        # Zeile und erwartet dort FERTIG oder PROBLEM. Der Protokollhinweis
        # steht deshalb davor (Befund aus dem ersten Live-Lauf, 20.09.2026).
        print("RUFLO-PROTOKOLL: " + str(ziel.relative_to(ROOT)))
        print(text)
        return 1 if fehlgeschlagen else 0


if __name__ == "__main__":
    raise SystemExit(main())
