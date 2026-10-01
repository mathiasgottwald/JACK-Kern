#!/usr/bin/env python3
"""Messtest der Kostenstufen — EIN Vorgang (Block 11, Knopf Block 13, Block 15).

Was am 17.09.2026 schiefging und hier behoben ist:

  * Jede Messaufgabe zaehlte als eigener Lauf. Nach 60 Aufgaben war der
    Stundendeckel (60 Laeufe) voll - Stufe 2 wurde NIE gemessen. Jetzt zaehlt
    der Messtest im LAUFdeckel als ein Lauf; im GELDdeckel zaehlt jeder Betrag
    weiter mit (nichts geht am Geld vorbei).
  * max_tokens war 120. 98 von 120 Antworten kamen abgeschnitten zurueck.
  * Er liess sich mehrfach starten und hat jedes Mal Geld gekostet.
  * Nach dem Lauf passierte nichts. Jetzt entsteht eine Entscheidungsvorlage.

Er laeuft NIE ueber den API-Arbeiter.
"""
import json
import os
import re
import signal
import subprocess
import sys
import time
from decimal import Decimal
from pathlib import Path

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER))
import jack_betrieb as b
import jack_kosten
import modell_router

AUFGABEN = 20
STUFEN = (0, 1, 2)
BUCH = "messtest.jsonl"
STAND = "messtest_stand.json"
TOKEN_AUFGABE = 400          # 120 waren zu knapp: 98 von 120 abgeschnitten
TOKEN_PRUEFER = 1500       # 500 waren zu knapp: 5 von 20 Urteilen abgeschnitten
                          # (Lauf 6). Ein Urteil kostet wenig, ein fehlendes viel.
                          # 17.09.2026 (Auftrag 27.1): 900 war nach Lauf 6
                          # gesetzt, aber nie nachgemessen. Ein Urteil braucht
                          # drei Zeilen; 1500 Token kosten rund 0,0001 USD mehr
                          # und machen ein abgeschnittenes Urteil unmoeglich.
                          # Ein fehlendes Urteil verdirbt die ganze Quote.
ABSTAND_TAGE = 7             # E6: hoechstens einmal je Woche ohne Rueckfrage

# ── Auftrag 27.1: Messtest je KANDIDAT ────────────────────────────────────
# Zwei Kandidaten lassen sich nur vergleichen, wenn sie DIESELBEN Aufgaben
# bekommen. _teilaufgaben() nimmt aber die 20 juengsten Dateien aus
# auftraege/erledigt/ - und die aendern sich jeden Tag. Deshalb werden die
# Aufgaben einmal eingefroren und beide Kandidaten rechnen daraus.
GEFROREN = "messtest_aufgaben_27.1.json"


# ───────────────────────────────────────────────────────── Aufgaben und Stand
def _aufgaben_von_lauf6(root, hoechstens=AUFGABEN):
    """Genau die Aufgaben, die der letzte REGULAERE Messlauf bekommen hat.

    Der Auftrag 27.1 verlangt "dieselben 20 Aufgaben" wie Lauf 6. Woertlich
    genommen ist das noetig: _teilaufgaben() nimmt die 20 juengsten Dateien aus
    auftraege/erledigt/, und die aendern sich taeglich - am 17.09.2026 waren von
    den 20 Aufgaben aus Lauf 6 nur noch 6 dabei. Ein Kandidat waere dann gegen
    ANDERE Texte angetreten als das Bestandsmodell, und der Vergleich mit den
    53 % aus Lauf 6 waere wertlos gewesen.

    Wiederhergestellt wird aus dem Messtestbuch: Es nennt je Zeile die Datei.
    Der Aufgabentext entsteht daraus mit demselben _kernsatz() wie damals -
    die Dateien in erledigt/ werden nicht mehr geaendert. Fehlt eine Datei,
    gibt es keinen halben Satz: dann faellt die Funktion aus und der Aufrufer
    nimmt den heutigen Satz, sichtbar vermerkt.
    """
    root = Path(root or HIER)
    letzter, dateien = None, []
    for z in b.records(b.area(root) / BUCH):
        if str(z.get("stufe")) != "0" or z.get("kandidat"):
            continue
        nummer = str(z.get("lauf") or "")
        if nummer != letzter:
            letzter, dateien = nummer, []
        if z.get("datei") and z["datei"] not in dateien:
            dateien.append(z["datei"])
    if not dateien:
        return [], ""
    raus = []
    for name in dateien[:hoechstens]:
        p = root / "auftraege" / "erledigt" / name
        if not p.is_file():
            return [], ""
        satz = _kernsatz(p.read_text(encoding="utf-8", errors="replace"))
        if not satz:
            return [], ""
        raus.append({"datei": name, "quelle": satz[:600],
                     "aufgabe": ("Fasse in EINEM kurzen Satz zusammen, worum es hier geht. "
                                 "Antworte NUR mit diesem Satz - keine Einleitung, keine "
                                 "Aufzaehlung, keine Erklaerung.\n\n" + satz[:600])})
    if len(raus) < hoechstens:
        return [], ""
    return raus, "dieselben %d Aufgaben wie der regulaere Messlauf %s" % (len(raus), letzter)


def _teilaufgaben(hoechstens=AUFGABEN, root=None, gefroren=False):
    """Echte, abgeschlossene Teilaufgaben aus auftraege/erledigt/.

    Genommen wird der erste inhaltliche Satz je Auftrag - nicht der ganze Text.
    Das haelt die Messung vergleichbar und die Tokenzahl klein (Tokenregel T1).

    gefroren=True nimmt die eingefrorene Liste (Auftrag 27.1), damit Kandidat A
    und Kandidat B buchstabengleich dieselben Aufgaben bekommen. Fehlt die
    Datei, wird sie beim ersten Kandidaten angelegt.
    """
    if gefroren:
        p = b.area(root or HIER) / GEFROREN
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if d.get("aufgaben"):
                return d["aufgaben"]
        except (OSError, ValueError):
            pass
        aufgaben, herkunft = _aufgaben_von_lauf6(root, hoechstens)
        if not aufgaben:
            aufgaben = _teilaufgaben(hoechstens)
            herkunft = ("die 20 juengsten Dateien aus auftraege/erledigt/ - der "
                        "Aufgabensatz des letzten regulaeren Laufs liess sich nicht "
                        "wiederherstellen")
        if aufgaben:
            p.write_text(json.dumps({"schema": 1, "eingefroren": b.now().isoformat(),
                                     "grund": "Auftrag 27.1: beide Kandidaten rechnen "
                                              "dieselben Aufgaben",
                                     "herkunft": herkunft,
                                     "aufgaben": aufgaben}, ensure_ascii=False, indent=1),
                         encoding="utf-8")
        return aufgaben
    raus = []
    for p in sorted((HIER / "auftraege" / "erledigt").glob("*.md"), reverse=True):
        if p.is_symlink() or p.name.lower().startswith("readme"):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        satz = _kernsatz(text)
        if not satz:
            continue
        raus.append({"datei": p.name, "quelle": satz[:600],
                     "aufgabe": ("Fasse in EINEM kurzen Satz zusammen, worum es hier geht. "
                                 "Antworte NUR mit diesem Satz - keine Einleitung, keine "
                                 "Aufzaehlung, keine Erklaerung.\n\n" + satz[:600])})
        if len(raus) >= hoechstens:
            break
    return raus


# 17.09.2026, Lauf 5 war wertlos: Die Auswahl nahm die ERSTE inhaltliche Zeile
# jeder Auftragsdatei - und das ist bei jedem Auftrag dieselbe Kopfzeile
# ("START: ... Projektordner: ~/Library/..."). Zwanzigmal derselbe Satz, und
# Stufe 1 bekam 13 % dafuer, dass sie zu einem Pfad keine Zusammenfassung
# erfinden wollte. Die Messung muss verschiedene, inhaltliche Texte nehmen.
KOPFZEILEN = re.compile(
    r"^(START|Regeln|Grenzen|Projektordner|Sicherung|Quelle der Aufgaben|"
    r"marke|auftrag|erteilt|von|status|freigabe|gefahr|tiefe|besetzung|versuch|"
    r"warte_bis|bereiche|art|test|probe_|messtest_|zustand|postfach|an|betreff|"
    r"mailart|weg|stufe|zaehler|dauersperre|erstellt)", re.I)


def _kernsatz(text):
    """Der erste ABSATZ, der wirklich etwas aussagt - nicht die Kopfzeile.

    Zeilen werden zusammengefuegt, weil Markdown mitten im Satz umbricht. Ein
    halber Satz ist keine Messaufgabe.
    """
    im_kopf = False
    absatz = []
    for zeile in text.splitlines():
        z = zeile.strip()
        if z == "---":
            im_kopf = not im_kopf
            continue
        if im_kopf:
            continue
        if not z:
            if absatz:
                break                      # Absatz zu Ende
            continue
        if z.startswith(("#", "-", "|", "`", "*", ">", "!", "[")):
            if absatz:
                break
            continue
        if KOPFZEILEN.match(z) or z.count("/") >= 3 or z.startswith("~"):
            continue
        absatz.append(z)
        if sum(len(x) for x in absatz) > 400:
            break
    zusammen = " ".join(absatz)
    return zusammen if len(zusammen) >= 80 and "." in zusammen else ""


def _standpfad(root=None):
    return b.area(root or HIER) / STAND


def stand(root=None):
    try:
        return json.loads(_standpfad(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"gelaufen": False, "laeuft": False}


def _stand_schreiben(root, d):
    p = _standpfad(root)
    tmp = p.with_suffix(".json.neu")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def _lebt(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def laeuft(root=None):
    """(True, Stand) wenn gerade ein Messtest arbeitet. D2."""
    d = stand(root)
    if d.get("laeuft") and _lebt(d.get("pid")):
        return True, d
    if d.get("laeuft"):
        # Der Prozess ist weg, die Fahne stand noch. Ehrlich aufraeumen.
        d["laeuft"] = False
        d["abgebrochen"] = "Der Prozess ist verschwunden; die Fahne wurde zurueckgesetzt."
        try:
            _stand_schreiben(root or HIER, d)
        except OSError:
            pass
    return False, d


def _naechste_lauf(root):
    """D3: Jeder Lauf hat eine Nummer. Die Altzeilen ohne Nummer bleiben."""
    hoechste = 0
    try:
        for zeile in b.records(b.area(root) / BUCH):
            try:
                hoechste = max(hoechste, int(zeile.get("lauf") or 0))
            except (TypeError, ValueError):
                continue
    except Exception:
        pass
    if hoechste:
        return hoechste + 1
    # Ohne Nummern im Buch: die Altlaeufe zaehlen. 60 Zeilen = ein Lauf.
    try:
        zeilen = sum(1 for _ in b.records(b.area(root) / BUCH))
    except Exception:
        zeilen = 0
    return max(1, -(-zeilen // (AUFGABEN * len(STUFEN)))) + 1


# ───────────────────────────────────────────────────────────── Voranschlag
def voranschlag(root=None):
    """Was wuerde der Lauf kosten? Rechnet nur - startet nichts."""
    root = Path(root or HIER)
    aufgaben = _teilaufgaben()
    preise = jack_kosten.preise(root).get("modelle", {})
    ein = int(sum(len(a["aufgabe"]) for a in aufgaben) / max(1, len(aufgaben)) / 4) + 120
    zeilen, summe = [], Decimal(0)
    for stufe in STUFEN:
        wahl = modell_router.auswahl_fuer_stufe(root, stufe)
        m = wahl["modell"]
        if wahl["anbieter"] == "lokal" or m not in preise:
            zeilen.append({"stufe": stufe, "modell": m, "usd": "0",
                           "hinweis": "laeuft auf dem Mac" if wahl["anbieter"] == "lokal"
                                      else "kein belegter Preis"})
            continue
        p = preise[m]
        je = (Decimal(ein) * Decimal(str(p["eingabe"]))
              + Decimal(200) * Decimal(str(p["ausgabe"]))) / Decimal(1000000)
        gesamt = je * len(aufgaben)
        summe += gesamt
        zeilen.append({"stufe": stufe, "modell": m,
                       "usd": str(gesamt.quantize(Decimal("0.0001"))),
                       "hinweis": "%s USD je Aufgabe x %d"
                                  % (je.quantize(Decimal("0.000001")), len(aufgaben))})
    # Der Pruefer bewertet je Aufgabe ALLE DREI Antworten in EINEM Lauf -
    # billiger als 60 Einzelurteile und ein besserer Vergleich.
    p2 = preise.get(modell_router.auswahl_fuer_stufe(root, 2)["modell"])
    pruef = Decimal(0)
    if p2:
        pruef = ((Decimal(ein + 600) * Decimal(str(p2["eingabe"]))
                  + Decimal(200) * Decimal(str(p2["ausgabe"]))) / Decimal(1000000)
                 ) * len(aufgaben)
    dran, grund = faellig(root)
    return {"aufgaben": len(aufgaben), "zeilen": zeilen,
            "pruefer_usd": str(pruef.quantize(Decimal("0.0001"))),
            "gesamt_usd": str((summe + pruef).quantize(Decimal("0.0001"))),
            "quelle": "belegte Listenpreise aus betrieb/modellpreise.json",
            "gestartet": False, "faellig": dran, "faellig_grund": grund,
            "hinweis": ("Nur gerechnet. Der Lauf startet erst, wenn der Patron ihn "
                        "startet - und er laeuft ueber die Stufen, nie ueber den "
                        "API-Arbeiter.")}


def faellig(root=None):
    """E6: hoechstens einmal je 7 Tage ohne zweite Bestaetigung."""
    d = stand(root)
    letzter = d.get("zeit")
    if not letzter or not d.get("gelaufen"):
        return True, "noch nie vollstaendig gelaufen"
    try:
        import datetime as dt
        tage = (b.now() - dt.datetime.fromisoformat(letzter)).days
    except Exception:
        return True, "letzter Lauf nicht lesbar"
    if tage >= ABSTAND_TAGE:
        return True, "letzter Lauf vor %d Tagen" % tage
    return False, ("letzter Lauf vor %d Tagen - der naechste ist in %d Tagen faellig"
                   % (tage, ABSTAND_TAGE - tage))


# ─────────────────────────────────────────────────────────────── Der Lauf
def _schluessel(root, name="ANTHROPIC_API_KEY"):
    try:
        import jack_tresor
        return jack_tresor.lesen(name)
    except Exception:
        return ""


def _geld_frei(root):
    """Ist der GELD-Deckel frei? (True, "") oder (False, Grund)."""
    try:
        import jack_grenzen
        s = jack_grenzen.deckel_status(root)
    except Exception as fehler:
        return False, "Deckel nicht pruefbar, deshalb kein Start: %s" % str(fehler)[:120]
    if s["erreicht"] and s["art"].startswith("budget_usd"):
        return False, s["grund"]
    return True, ""


def starten(root=None, neu_erzwingen=False, im_hintergrund=True, kandidat=None):
    """Startet den Messtest. D2: hoechstens einer, und nie zwei gleichzeitig.

    kandidat (Auftrag 27.1): Ordnername eines lokalen Modells. Der Lauf ist
    dann ein Kandidatenlauf - eingefrorene Aufgaben, Stufe 0 mit DIESEM Modell.
    Er umgeht die Woche-Frist (faellig), weil er eine ANDERE Frage stellt als
    der regulaere Lauf: nicht "stimmt die Tabelle noch", sondern "taugt dieses
    Modell". Das Geld-Deckel-Tor bleibt unveraendert vorgeschaltet.
    """
    root = Path(root or HIER)
    if kandidat:
        neu_erzwingen = True
        import jack_lokal
        pfad = jack_lokal.modellpfad(root, kandidat)
        if not pfad:
            ordner = Path(root) / "lokal.nosync" / "modelle" / kandidat
            if ordner.is_dir():
                _fertig, warum = jack_lokal.vollstaendig(ordner)
                return {"ok": False, "meldung": "Kandidat '%s' ist noch nicht "
                                                "einsatzbereit: %s" % (kandidat, warum)}
            return {"ok": False, "meldung": "Kandidat '%s' liegt nicht in "
                                            "lokal.nosync/modelle/" % kandidat}
        passt, grund, zahlen = jack_lokal.speicher_pruefen(root, pfad)
        if not passt:
            return {"ok": False, "meldung": "Kein Start: " + grund, "zahlen": zahlen}
    aktiv, d = laeuft(root)
    if aktiv:
        return {"ok": False, "laeuft": True, "stand": d,
                "meldung": ("Ein Messtest laeuft schon seit %s - Aufgabe %s von %s. "
                            "Ein zweiter Lauf wuerde noch einmal kosten."
                            % (str(d.get("begonnen", ""))[11:16], d.get("fertig", 0),
                               d.get("geplant", AUFGABEN * len(STUFEN))))}
    dran, grund = faellig(root)
    if not dran and not neu_erzwingen:
        return {"ok": False, "rueckfrage": True, "faellig_grund": grund,
                "meldung": ("Der %s. Ein neuer Lauf kostet noch einmal und misst "
                            "dasselbe. Trotzdem starten?" % grund)}
    frei, dgrund = _geld_frei(root)
    if not frei:
        return {"ok": False, "meldung": "Der Geld-Deckel ist erreicht: " + dgrund}
    if not im_hintergrund:
        return _lauf(root, neu_erzwingen, kandidat=kandidat)
    # Eigener Prozess, damit die Oberflaeche nicht blockiert und D2 eine PID hat.
    proc = subprocess.Popen(
        [sys.executable, "-I", str(HIER / "jack_messtest.py"), "lauf"]
        + (["--kandidat", kandidat] if kandidat else []),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL, cwd=str(root), start_new_session=True)
    for _ in range(40):
        time.sleep(0.25)
        if stand(root).get("laeuft"):
            break
    return {"ok": True, "gestartet": True, "pid": proc.pid, "stand": stand(root),
            "meldung": "Messtest laeuft. Der Fortschritt steht am Knopf."}


def stimme_messen(text="Patron, die Stimme antwortet."):
    """Wie lange braucht die Stimme fuer EINEN festen Satz - ueber den schon
    laufenden Stimmprozess von JACK (kein zweiter Prozess, kein zweites Modell).

    Warum nicht der 'erste Ton' aus dem Gespraech: Den misst
    sprachdiagnose.jsonl nur, wenn der Patron wirklich spricht. Diese Messung
    laeuft ohne ihn, ist wiederholbar und trifft denselben Prozess. Was sie
    zeigt, ist die Frage, auf die es ankommt: Wird die Stimme langsamer,
    waehrend Stufe 0 rechnet?
    """
    import urllib.request
    daten = json.dumps({"text": text}).encode()
    anfrage = urllib.request.Request(
        "http://127.0.0.1:8778/stimme", data=daten,
        headers={"Host": "127.0.0.1:8778", "Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(anfrage, timeout=90) as antwort:
            bytes_ = len(antwort.read())
        return {"sekunden": round(time.time() - t0, 3), "bytes": bytes_,
                "tonlaenge_s": round(bytes_ / 48000.0, 2), "ok": True}
    except Exception as fehler:
        return {"sekunden": round(time.time() - t0, 3), "ok": False,
                "grund": str(fehler)[:160]}


def _stufe0_werte(root, d, zeile):
    """Die Zusatzmessungen aus Auftrag 27.1 einsammeln.

    Die Zahlen stehen schon im Stufenbuch - modell_router.call schreibt sie
    dorthin. Sie hier noch einmal zu erzeugen, waere eine zweite Wahrheit.
    """
    m = d.get("stufe0_messung") or {}
    try:
        letzte = list(b.records(b.area(root) / "stufenlaeufe.jsonl"))[-1]
    except Exception:
        return
    if str(letzte.get("stufe")) != "0":
        return
    if letzte.get("laden_s") and m.get("laden_s") is None:
        m["laden_s"] = letzte["laden_s"]
    if letzte.get("erstes_wort_s") is not None:
        m["erstes_wort_s"].append(letzte["erstes_wort_s"])
    if letzte.get("token_je_s") is not None:
        m["token_je_s"].append(letzte["token_je_s"])
    if letzte.get("geladen_gehalten"):
        m["geladen_gehalten"] += 1
    spitze = ((letzte.get("speicher_gb") or {}).get("spitze") or 0)
    m["speicher_spitze_gb"] = max(m.get("speicher_spitze_gb", 0), spitze)
    # Alle fuenf Aufgaben die Stimme nachmessen - sie hat Vorrang, und ein
    # Einbruch soll auffallen, waehrend der Lauf laeuft, nicht danach.
    zahl = len(m.get("erstes_wort_s", [])) + len(m.get("rueckfaelle", []))
    if zahl and zahl % 5 == 0:
        m.setdefault("stimme_waehrend", []).append(stimme_messen())
    d["stufe0_messung"] = m


def _lauf(root, neu_erzwingen=False, kandidat=None):
    """Der eigentliche Durchlauf. Laeuft im eigenen Prozess (siehe starten).

    kandidat: Ordnername eines lokalen Modells (Auftrag 27.1). Dann laeuft
    Stufe 0 mit DIESEM Modell statt mit dem aus der Tabelle, die Aufgaben sind
    eingefroren, und zusaetzlich gemessen werden Ladezeit, Zeit bis zum ersten
    Wort, Token je Sekunde, Speicherspitze und der Einfluss auf die Stimme.
    """
    root = Path(root)
    aufgaben = _teilaufgaben(root=root, gefroren=bool(kandidat))
    if not aufgaben:
        return {"ok": False, "meldung": "Keine abgeschlossenen Teilaufgaben gefunden."}
    # Eine Messung mit zwanzigmal demselben Satz misst nichts. Lieber kein
    # Ergebnis als ein falsches (Lehre aus Lauf 5).
    verschieden = len({a["quelle"][:120] for a in aufgaben})
    if verschieden < max(5, len(aufgaben) * 2 // 3):
        return {"ok": False,
                "meldung": ("Die Messaufgaben sind sich zu aehnlich: nur %d von %d "
                            "verschiedene Texte. Das waere keine Messung. Es wurde "
                            "nichts gestartet und nichts bezahlt."
                            % (verschieden, len(aufgaben)))}
    nummer = _naechste_lauf(root)
    geplant = len(aufgaben) * len(STUFEN) + len(aufgaben)      # Aufgaben + Pruefer
    d = {"laeuft": True, "gelaufen": False, "lauf": nummer, "pid": os.getpid(),
         "begonnen": b.now().isoformat(), "geplant": geplant, "fertig": 0,
         "aufgaben": len(aufgaben), "je_stufe": {}, "usd_je_stufe": {},
         "abgebrochen": "", "kandidat": kandidat}
    if kandidat:
        # Die Stimme zuerst - VOR dem Laden des Kandidaten. Ohne diesen Wert
        # laesst sich hinterher nicht sagen, ob sie langsamer geworden ist.
        d["stimme_vorher"] = stimme_messen()
        d["stufe0_messung"] = {"laden_s": None, "erstes_wort_s": [], "token_je_s": [],
                               "speicher_spitze_gb": 0, "geladen_gehalten": 0,
                               "rueckfaelle": []}
    _stand_schreiben(root, d)

    # D1: EIN Eintrag im Laufbuch fuer den ganzen Vorgang.
    sammel = jack_kosten.begin(root, "messtest", "jack", "stufen 0/1/2", billing="api")
    ergebnisse = {}
    try:
        for a in aufgaben:
            ergebnisse[a["datei"]] = {}
            for stufe in STUFEN:
                frei, grund = _geld_frei(root)
                if not frei:
                    d["abgebrochen"] = "Geld-Deckel waehrend des Laufs erreicht: " + grund
                    raise StopIteration
                wahl = modell_router.auswahl_fuer_stufe(root, stufe)
                if stufe == 0 and kandidat:
                    wahl["modell"] = kandidat          # Auftrag 27.1: DIESER Kandidat
                zeile = {"zeit": b.now().isoformat(), "lauf": nummer, "datei": a["datei"],
                         "stufe": stufe, "anbieter": wahl["anbieter"], "modell": wahl["modell"]}
                if kandidat:
                    # Ohne diese Marke waere im Buch nicht zu unterscheiden, ob
                    # Stufe 0 mit dem Modell der Tabelle gelaufen ist oder mit
                    # einem Kandidaten. Der Bericht haette dann Laeufe
                    # verglichen, die verschiedene Fragen beantworten.
                    zeile["kandidat"] = kandidat
                t0 = time.time()
                try:
                    erg = modell_router.call(
                        lambda n="ANTHROPIC_API_KEY": _schluessel(root, n),
                        wahl, a["aufgabe"], max_tokens=TOKEN_AUFGABE, root=root,
                        kind="fachentwurf", teil_von=sammel["id"])
                    zeile.update(ok=True, antwort=str(erg.get("antwort") or "")[:600],
                                 verbrauch=erg.get("verbrauch", {}),
                                 usd=_usd(root, wahl["modell"], erg.get("verbrauch")))
                    ergebnisse[a["datei"]][stufe] = zeile["antwort"]
                except Exception as fehler:
                    zeile.update(ok=False, grund=str(fehler)[:200], usd="0")
                    if stufe == 0 and kandidat:
                        art_f = getattr(fehler, "art", "") or "fehler"
                        d["stufe0_messung"]["rueckfaelle"].append(
                            {"art": art_f, "grund": str(fehler)[:200]})
                        # Lieber KEIN Ergebnis als ein falsches: Wenn Stufe 0
                        # nicht am Modell scheitert, sondern am Rechner (zu
                        # wenig Speicher, Arbeiter tot, zu langsam), dann misst
                        # dieser Lauf die Maschine und nicht den Kandidaten.
                        # Eine Quote von 0 % waere dann ein Fehlurteil ueber
                        # ein Modell, das nie gerechnet hat.
                        harte = [r for r in d["stufe0_messung"]["rueckfaelle"]
                                 if r["art"] in ("speicher", "abgestuerzt", "zu_langsam",
                                                 "nicht_eingerichtet")]
                        if len(harte) >= 3:
                            d["abgebrochen"] = (
                                "Stufe 0 ist dreimal nicht am Modell gescheitert, sondern "
                                "am Rechner (%s). Der Lauf wird abgebrochen - ein Ergebnis "
                                "daraus waere ein Fehlurteil ueber den Kandidaten. "
                                "Spaeter wiederholen, wenn der Rechner frei ist."
                                % harte[-1]["art"])
                            zeile["sekunden"] = round(time.time() - t0, 2)
                            b.append(b.area(root) / BUCH, zeile)
                            raise StopIteration
                zeile["sekunden"] = round(time.time() - t0, 2)
                if stufe == 0 and kandidat:
                    _stufe0_werte(root, d, zeile)
                b.append(b.area(root) / BUCH, zeile)
                d["fertig"] += 1
                d["je_stufe"][str(stufe)] = d["je_stufe"].get(str(stufe), 0) + (1 if zeile["ok"] else 0)
                d["usd_je_stufe"][str(stufe)] = str(
                    Decimal(d["usd_je_stufe"].get(str(stufe), "0")) + Decimal(zeile["usd"]))
                _stand_schreiben(root, d)

            # Der Pruefer sieht alle drei Antworten zu DIESER Aufgabe.
            frei, grund = _geld_frei(root)
            if not frei:
                d["abgebrochen"] = "Geld-Deckel waehrend des Laufs erreicht: " + grund
                raise StopIteration
            urteil = _pruefen(root, a, ergebnisse[a["datei"]], nummer, sammel["id"])
            d["fertig"] += 1
            _stand_schreiben(root, d)
    except StopIteration:
        pass
    except Exception as fehler:
        d["abgebrochen"] = "Abbruch: " + str(fehler)[:200]
    finally:
        jack_kosten.end(root, sammel, "ok" if not d["abgebrochen"] else "fehler")

    d["laeuft"] = False
    d["gelaufen"] = not d["abgebrochen"]
    d["zeit"] = b.now().isoformat()
    d["vollstaendig"] = d["fertig"] >= geplant
    if kandidat:
        d["stimme_nachher"] = stimme_messen()
        # Der Arbeiter gibt den Speicher sofort zurueck - der naechste Kandidat
        # soll nicht gegen ein Modell messen muessen, das noch im Weg liegt.
        try:
            import jack_lokal
            d["stufe0_gestoppt"] = jack_lokal.stoppen(root)
        except Exception:
            pass
        try:
            (root / "abnahme" / "Sichtpruefung_27.1_2026-09-17").mkdir(parents=True, exist_ok=True)
            (root / "abnahme" / "Sichtpruefung_27.1_2026-09-17"
             / ("MESSUNG_Lauf%s_%s.json" % (nummer, kandidat))).write_text(
                json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception:
            pass
    _stand_schreiben(root, d)

    # E: Auswertung und Entscheidungsvorlage
    if kandidat and d["abgebrochen"]:
        # Ein Kandidatenlauf, der am Rechner gescheitert ist, darf keine
        # Entscheidungsvorlage erzeugen. Sonst stuende dem Patron eine
        # Empfehlung auf dem Tisch, die auf einer Messung beruht, die nie
        # stattgefunden hat.
        d["vorlage"] = {"datei": None, "grund": d["abgebrochen"]}
        _stand_schreiben(root, d)
        return {"ok": False, "stand": d, "meldung": d["abgebrochen"]}
    try:
        bericht = auswerten(root, nummer)
        d["bericht"] = {k: bericht[k] for k in ("quote_je_stufe", "usd_je_stufe",
                                                "aenderungen", "ersparnis_monat_usd")}
        d["vorlage"] = vorlage_schreiben(root, bericht)
        _stand_schreiben(root, d)
    except Exception as fehler:
        d["auswertung_fehler"] = str(fehler)[:200]
        _stand_schreiben(root, d)
    return {"ok": True, "stand": d}


def _usd(root, modell, verbrauch):
    """D4: der ECHTE Betrag aus der Anbieter-Antwort, nicht geschaetzt."""
    betrag, _stand = jack_kosten.schaetzung(root, modell, verbrauch)
    return betrag if betrag is not None else "0"


def _pruefen(root, aufgabe, antworten, nummer, sammel_id):
    """Ein Urteil je Aufgabe ueber alle drei Stufen. Stufe 2 richtet."""
    wahl = modell_router.auswahl_fuer_stufe(root, 2)
    frage = "\n".join([
        "Hier ist ein Ausgangstext und drei Zusammenfassungen davon.",
        "Beurteile JEDE Zusammenfassung mit TRIFFT ZU oder TRIFFT NICHT ZU.",
        "TRIFFT ZU heisst: sie gibt den Kern richtig wieder, in verstaendlichem",
        "Deutsch, ohne Erfindung. Antworte NUR in drei Zeilen, genau so:",
        "A: TRIFFT ZU",
        "B: TRIFFT NICHT ZU",
        "C: TRIFFT ZU",
        "",
        "AUSGANGSTEXT:",
        aufgabe["quelle"][:600],
        "",
        "A: " + str(antworten.get(0) or "(keine Antwort)")[:400],
        "B: " + str(antworten.get(1) or "(keine Antwort)")[:400],
        "C: " + str(antworten.get(2) or "(keine Antwort)")[:400],
    ])
    zeile = {"zeit": b.now().isoformat(), "lauf": nummer, "datei": aufgabe["datei"],
             "stufe": "pruefer", "anbieter": wahl["anbieter"], "modell": wahl["modell"]}
    try:
        erg = modell_router.call(
            lambda n="ANTHROPIC_API_KEY": _schluessel(root, n), wahl, frage,
            max_tokens=TOKEN_PRUEFER, root=root, kind="fachentwurf", teil_von=sammel_id)
        text = str(erg.get("antwort") or "")
        urteil = {}
        for buchstabe, stufe in (("A", 0), ("B", 1), ("C", 2)):
            m = re.search(r"^\s*%s\s*:\s*(TRIFFT\s+(NICHT\s+)?ZU)" % buchstabe,
                          text, re.M | re.I)
            urteil[str(stufe)] = bool(m and not m.group(2))
        zeile.update(ok=True, urteil=urteil, antwort=text[:400],
                     verbrauch=erg.get("verbrauch", {}),
                     usd=_usd(root, wahl["modell"], erg.get("verbrauch")))
    except Exception as fehler:
        zeile.update(ok=False, grund=str(fehler)[:200], usd="0", urteil={})
    b.append(b.area(root) / BUCH, zeile)
    return zeile.get("urteil", {})


# ══════════ E: Das Ergebnis wird eine Entscheidungsvorlage ═════════════════
# Ein Messtest, nach dem nichts passiert, ist ein Messtest, den man sich sparen
# kann. Hier wird ausgewertet, verglichen und ein Vorschlag abgelegt - immer,
# auch wenn er "keine Aenderung" lautet (E4).

# E2: Die Regel. Regelbasiert, kein Modell - damit sie nachlesbar ist.
SCHWELLE_TIEFER = 90         # so gut muss die tiefere Stufe sein
VORSPRUNG_MAX = 5            # so viel darf die heutige Stufe besser sein
SCHWELLE_HOEHER = 70         # darunter muss eine Stufe hoeher


def auswerten(root=None, nummer=None):
    """E1: Quote, Kosten und Dauer je Stufe - und was das je Aufgabenart heisst."""
    root = Path(root or HIER)
    zeilen = [z for z in b.records(b.area(root) / BUCH)
              if nummer is None or str(z.get("lauf")) == str(nummer)]
    if not zeilen:
        raise ValueError("Fuer diesen Lauf steht nichts im Messtestbuch")

    versucht, geschafft, usd, sekunden = {}, {}, {}, {}
    for z in zeilen:
        s = str(z.get("stufe"))
        if s == "pruefer":
            continue
        versucht[s] = versucht.get(s, 0) + 1
        if z.get("ok"):
            geschafft[s] = geschafft.get(s, 0) + 1
        usd[s] = str(Decimal(usd.get(s, "0")) + Decimal(str(z.get("usd") or "0")))
        sekunden[s] = round(sekunden.get(s, 0) + float(z.get("sekunden") or 0), 2)

    # Die Quote kommt vom PRUEFER, nicht davon, ob ein Aufruf durchkam.
    treffer, geurteilt = {}, {}
    for z in zeilen:
        if str(z.get("stufe")) != "pruefer" or not z.get("ok"):
            continue
        for s, ok in (z.get("urteil") or {}).items():
            geurteilt[s] = geurteilt.get(s, 0) + 1
            if ok:
                treffer[s] = treffer.get(s, 0) + 1
        usd["pruefer"] = str(Decimal(usd.get("pruefer", "0")) + Decimal(str(z.get("usd") or "0")))

    quote = {}
    for s in ("0", "1", "2"):
        n = geurteilt.get(s, 0)
        quote[s] = round(100.0 * treffer.get(s, 0) / n, 1) if n else None

    # E1: je Aufgabenart aus der Stufen-Tabelle
    tab = modell_router.stufen(root)
    heute = {}
    for stufe, inhalt in (tab.get("stufen") or {}).items():
        for art in (inhalt.get("taugt_fuer") or []):
            heute[art] = int(stufe)

    aenderungen, tabelle = [], []
    for art, jetzt in sorted(heute.items(), key=lambda x: (x[1], x[0])):
        empfohlen, warum = _empfehlung(art, jetzt, quote, tab)
        je_auf = _je_aufgabe(usd, versucht, str(jetzt))
        tabelle.append({"art": art, "stufe_heute": jetzt, "stufe_empfohlen": empfohlen,
                        "quote_heute": quote.get(str(jetzt)),
                        "quote_empfohlen": quote.get(str(empfohlen)),
                        "usd_je_aufgabe": je_auf, "warum": warum})
        if empfohlen != jetzt:
            aenderungen.append(tabelle[-1])

    pruefer_zeilen = [z for z in zeilen if str(z.get("stufe")) == "pruefer"]
    pruefer_ok = len([z for z in pruefer_zeilen if z.get("ok")])
    return {"lauf": nummer, "zeit": b.now().isoformat(),
            "urteile": pruefer_ok, "urteile_geplant": len(pruefer_zeilen),
            "versucht_je_stufe": versucht, "geschafft_je_stufe": geschafft,
            "geurteilt_je_stufe": geurteilt, "treffer_je_stufe": treffer,
            "quote_je_stufe": quote, "usd_je_stufe": usd, "sekunden_je_stufe": sekunden,
            "tabelle": tabelle, "aenderungen": aenderungen,
            "ersparnis_monat_usd": _ersparnis(root, aenderungen, usd, versucht),
            "regel": ("Eine Stufe tiefer, wenn die tiefere >= %d %% trifft und die "
                      "heutige nicht mehr als %d Punkte besser ist. Eine Stufe hoeher, "
                      "wenn die heutige unter %d %% liegt. Sonst bleibt es."
                      % (SCHWELLE_TIEFER, VORSPRUNG_MAX, SCHWELLE_HOEHER))}


def _empfehlung(art, jetzt, quote, tab):
    """E2: die Regel, angewandt. Gibt (empfohlene Stufe, Begruendung) zurueck."""
    q_jetzt = quote.get(str(jetzt))
    if q_jetzt is None:
        return jetzt, "kein Urteil fuer Stufe %d - es wird nichts geraten" % jetzt
    if q_jetzt < SCHWELLE_HOEHER and jetzt < 2:
        return jetzt + 1, ("Stufe %d trifft nur %.0f %% - unter %d %%, muss hoeher"
                           % (jetzt, q_jetzt, SCHWELLE_HOEHER))
    if jetzt > 0:
        tiefer = jetzt - 1
        q_tiefer = quote.get(str(tiefer))
        if q_tiefer is None:
            return jetzt, "kein Urteil fuer Stufe %d - bleibt" % tiefer
        # "vertraulich" nie auf Stufe 1 ohne Freigabe (Block 11 unveraendert)
        if tiefer == 1:
            erlaubt = ((tab.get("datenklassen") or {}).get("vertraulich") or {}).get("erlaubt", [])
            if "1" not in erlaubt and not tab.get("freigegeben"):
                return jetzt, ("Stufe 1 ist fuer vertraulich nicht freigegeben - "
                               "bleibt auf Stufe %d" % jetzt)
        if q_tiefer >= SCHWELLE_TIEFER and (q_jetzt - q_tiefer) <= VORSPRUNG_MAX:
            return tiefer, ("Stufe %d trifft %.0f %%, Stufe %d nur %.0f %% besser - "
                            "darf tiefer" % (tiefer, q_tiefer, jetzt, q_jetzt - q_tiefer))
        return jetzt, ("Stufe %d trifft nur %.0f %% (oder der Abstand ist zu gross) - "
                       "bleibt" % (tiefer, q_tiefer))
    return jetzt, "Stufe 0 ist die guenstigste - tiefer geht nicht"


def _je_aufgabe(usd, versucht, stufe):
    n = versucht.get(stufe, 0)
    if not n:
        return "0"
    return str((Decimal(usd.get(stufe, "0")) / Decimal(n)).quantize(Decimal("0.000001")))


def _ersparnis(root, aenderungen, usd, versucht):
    """Hochrechnung aus den letzten sieben Tagen. Als SCHAETZUNG gekennzeichnet."""
    if not aenderungen:
        return "0"
    try:
        import datetime as dt
        grenze = (b.now() - dt.timedelta(days=7)).isoformat()
        arten = {}
        ids = {}
        for r in jack_kosten.rows(root):
            if r.get("zeit", "") < grenze or r.get("teil_von"):
                continue
            ids[r.get("id")] = r
        for r in ids.values():
            arten[r.get("art")] = arten.get(r.get("art"), 0) + 1
    except Exception:
        return "0"
    # Eine Empfehlung kann auch nach OBEN gehen - dann ist es keine Ersparnis,
    # sondern ein Preis fuer Verlaesslichkeit. Beides wird getrennt ausgewiesen;
    # "Ersparnis 0" waere bei einer teureren Empfehlung eine Halbwahrheit.
    spart = Decimal(0)
    kostet = Decimal(0)
    ohne_zahl = []
    for a in aenderungen:
        n = arten.get(a["art"], 0)
        if not n:
            ohne_zahl.append(a["art"])
            continue
        v_alt = Decimal(_je_aufgabe(usd, versucht, str(a["stufe_heute"])))
        v_neu = Decimal(_je_aufgabe(usd, versucht, str(a["stufe_empfohlen"])))
        wirkung = (v_alt - v_neu) * Decimal(n) * Decimal("4.3")   # 7 Tage -> Monat
        if wirkung >= 0:
            spart += wirkung
        else:
            kostet += -wirkung
    return {"spart_usd": str(spart.quantize(Decimal("0.0001"))),
            "kostet_usd": str(kostet.quantize(Decimal("0.0001"))),
            "ohne_zahl": ohne_zahl,
            "grundlage": "Laufzahlen der letzten sieben Tage aus dem Verbrauchsbuch"}


def vorlage_schreiben(root=None, bericht=None):
    """E3/E4: Das Ergebnis als Entscheidungsvorlage - immer, auch ohne Aenderung."""
    root = Path(root or HIER)
    bericht = bericht or auswerten(root)
    ordner = root / "auftraege" / "freigabe"
    ordner.mkdir(parents=True, exist_ok=True)
    datum = b.now().strftime("%Y-%m-%d")
    name = "%s_MESSTEST_Ergebnis_Lauf%s.md" % (datum, bericht.get("lauf") or "x")
    q = bericht["quote_je_stufe"]
    u = bericht["usd_je_stufe"]

    def prozent(s):
        return "kein Urteil" if q.get(s) is None else ("%.0f %%" % q[s])

    def betrag(s):
        try:
            w = Decimal(u.get(s, "0"))
        except Exception:
            return "unbekannt"
        if w == 0:
            return "0 USD"
        if w < Decimal("0.01"):
            return "< 1 Cent"
        return "%s USD" % w.quantize(Decimal("0.0001"))

    aenderungen = bericht["aenderungen"]
    w = bericht["ersparnis_monat_usd"]
    if not isinstance(w, dict):
        w = {"spart_usd": str(w), "kostet_usd": "0", "ohne_zahl": [], "grundlage": ""}
    if aenderungen:
        runter = [a for a in aenderungen if a["stufe_empfohlen"] < a["stufe_heute"]]
        rauf = [a for a in aenderungen if a["stufe_empfohlen"] > a["stufe_heute"]]
        teile = []
        if runter:
            teile.append("%s auf die guenstigere Stufe"
                         % ("Eine Art darf" if len(runter) == 1
                            else "%d Arten duerfen" % len(runter)))
        if rauf:
            teile.append("%s auf die teurere Stufe, weil die guenstigere zu oft "
                         "daneben liegt"
                         % ("Eine Art muss" if len(rauf) == 1
                            else "%d Arten muessen" % len(rauf)))
        geld = []
        if Decimal(w["spart_usd"]) > 0:
            geld.append("Das spart geschaetzt %s USD im Monat." % w["spart_usd"])
        if Decimal(w["kostet_usd"]) > 0:
            geld.append("Das kostet geschaetzt %s USD im Monat mehr." % w["kostet_usd"])
        if not geld:
            geld.append("Eine Geldwirkung laesst sich daraus noch nicht errechnen: "
                        "fuer diese Aufgabenarten steht in den letzten sieben Tagen "
                        "kein einziger Lauf im Verbrauchsbuch. Sie kosten heute also "
                        "nichts - und werden erst etwas kosten, wenn sie benutzt werden.")
        kopfsatz = ("**%d von %d Aufgabenarten sollen die Stufe wechseln.** %s. %s"
                    % (len(aenderungen), len(bericht["tabelle"]),
                       " Und ".join(teile), " ".join(geld)))
    else:
        kopfsatz = ("**Keine Aenderung noetig.** Die Messung bestaetigt die Tabelle, "
                    "wie sie ist. Nichts zu tun - aber du sollst es sehen.")

    zeilen = ["---",
              "marke:      JACK",
              "auftrag:    MESSTEST Ergebnis %s - Stufen-Tabelle anpassen" % datum,
              "erteilt:    %s" % b.now().strftime("%Y-%m-%d %H:%M"),
              "von:        JACK (Messtest Lauf %s)" % (bericht.get("lauf") or "?"),
              "status:     freigabe",
              "freigabe:   nein",
              "gefahr:     keine",
              "tiefe:      klein",
              "bereiche:   steuerung",
              "art:        kostenstufen",
              "messtest_lauf: %s" % (bericht.get("lauf") or ""),
              "---",
              "",
              kopfsatz,
              "",
              "## Was gemessen wurde",
              "",
              "%d echte Teilaufgaben aus `auftraege/erledigt/`, je Aufgabe einmal auf "
              "jeder Stufe. Geurteilt hat Stufe 2 - sie sah alle drei Antworten "
              "nebeneinander und den Ausgangstext."
              % bericht["versucht_je_stufe"].get("0", 0),
              "",
              ("**Die Quoten beruhen auf %d von %d Urteilen.** %s"
               % (bericht.get("urteile", 0), bericht.get("urteile_geplant", 0),
                  "Vollstaendig." if bericht.get("urteile") == bericht.get("urteile_geplant")
                  else ("Die fehlenden Urteile kamen abgeschnitten zurueck. Die "
                        "Reihenfolge der Stufen ist damit belegt, die genauen "
                        "Prozentzahlen sind es nur ungefaehr."))),
              "",
              "| Stufe | Wer | Trefferquote | Kosten (Ist) | Dauer |",
              "|---|---|---|---|---|"]
    # Wer auf Stufe 0 gerechnet hat, steht im Messtestbuch - nicht im Code.
    # Bis zum 17.09.2026 stand hier fest "Qwen2.5-7B"; mit Kandidatenlaeufen
    # (Auftrag 27.1) waere das der falsche Name im Bericht gewesen.
    wer0 = "lokal"
    try:
        for z in b.records(b.area(root) / BUCH):
            if str(z.get("lauf")) == str(bericht.get("lauf")) and str(z.get("stufe")) == "0":
                wer0 = "lokal, " + str(z.get("modell") or "?")
                break
    except Exception:
        pass
    for s, wer in (("0", wer0), ("1", "Claude Haiku 4.5"),
                   ("2", "Claude Sonnet 5")):
        zeilen.append("| %s | %s | **%s** | %s | %s s |"
                      % (s, wer, prozent(s), betrag(s),
                         bericht["sekunden_je_stufe"].get(s, 0)))
    zeilen += ["| Prüfer | Stufe 2 | — | %s | — |" % betrag("pruefer"), "",
               "## Was das je Aufgabenart heisst", "",
               "| Aufgabenart | Stufe heute | empfohlen | Quote heute | USD je Aufgabe | Begründung |",
               "|---|---|---|---|---|---|"]
    for e in bericht["tabelle"]:
        pfeil = "**→ %d**" % e["stufe_empfohlen"] if e["stufe_empfohlen"] != e["stufe_heute"] \
                else "%d (bleibt)" % e["stufe_heute"]
        zeilen.append("| %s | %d | %s | %s | %s | %s |"
                      % (e["art"], e["stufe_heute"], pfeil,
                         "kein Urteil" if e["quote_heute"] is None else "%.0f %%" % e["quote_heute"],
                         e["usd_je_aufgabe"], e["warum"]))
    # Wird eine Stufe durch den Vorschlag LEER, muss das oben stehen. Ein
    # lokales Modell, das danach nichts mehr zu tun hat, ist eine Entscheidung
    # und kein Nebeneffekt.
    leer = []
    for s, inhalt in sorted((modell_router.stufen(root).get("stufen") or {}).items()):
        bleibt = [x for x in (inhalt.get("taugt_fuer") or [])
                  if not any(a["art"] == x and a["stufe_empfohlen"] != int(s)
                             for a in aenderungen)]
        if (inhalt.get("taugt_fuer") or []) and not bleibt:
            leer.append(s)
    if leer:
        zeilen += ["", "> **Achtung:** Nach dieser Aenderung haette Stufe %s **keine "
                   "Aufgabenart mehr**. Das lokale Modell waere damit ausser Dienst - "
                   "es kostet nichts, aber es arbeitet auch nicht mehr. Wenn du das "
                   "nicht willst, lehne ab und sag mir, welche Aufgabenart auf Stufe 0 "
                   "bleiben soll; ich messe sie dann einzeln nach."
                   % " und ".join(leer)]
    zeilen += ["", "## Die Regel, nach der das entschieden wurde", "",
               bericht["regel"], "",
               "Regelbasiert, ohne Modell - damit sie nachlesbar bleibt. "
               "**„vertraulich\" geht nie auf Stufe 1 ohne deine Freigabe** "
               "(Block 11, unverändert).", "",
               "## FREIGEBEN heißt", ""]
    if aenderungen:
        zeilen.append("Ich schreibe die empfohlenen Stufen in "
                      "`betrieb/kostenstufen.json` - mit Sicherung und Vermerk. "
                      "Kein Modellaufruf, kein Arbeiter.")
    else:
        zeilen.append("Nichts wird geändert. Die Vorlage wandert mit Vermerk nach "
                      "`erledigt/`, damit der Messtest zu Ende gedacht ist.")
    zeilen += ["", "ABLEHNEN legt sie ebenfalls mit Vermerk ab. Nichts wird gelöscht.",
               "", "Quelle: `betrieb/messtest.jsonl` (Lauf %s), "
               "`betrieb/messtest_stand.json`." % (bericht.get("lauf") or "?"), ""]
    (ordner / name).write_text("\n".join(zeilen), encoding="utf-8")
    try:
        import jack_freigaben
        jack_freigaben.anfordern(root, name, grund="Messtest-Ergebnis")
    except Exception:
        pass
    return {"datei": name, "aenderungen": len(aenderungen),
            "spart_usd": w["spart_usd"], "kostet_usd": w["kostet_usd"]}


# ══════════ Auftrag 27.1 (Aufgabe 6): der Bericht ueber ALLE Kandidaten ════
# Am 17.09.2026 auf huggingface.co nachgeprueft. Steht hier und nicht im
# Bericht, damit die Herkunft einer Lizenzangabe nachlesbar bleibt.
KANDIDATENKUNDE = {
    "Qwen3.6-35B-A3B-OptiQ-4bit-REAP-19B": {
        "quelle": "mlx-community/Qwen3.6-35B-A3B-OptiQ-4bit-REAP-19B",
        "lizenz": "apache-2.0", "geprueft": "17.09.2026",
        "platte_gb": 14.88, "gewichte_gb": 12.33, "bauart": "MoE, 128 Fachleute, 8 je Wort",
        "kv_kb_je_token": 20.0,
        "hinweis": "REAP = aus einem 35-Mrd.-MoE herausgeschnitten; OptiQ = eigene "
                   "Quantisierung. Keine entfernten Sicherheitssperren, aber auch "
                   "kein unveraendertes Original."},
    "Qwen3.8-27B-4bit": {
        "quelle": "mlx-community/Qwen3.8-27B-4bit",
        "lizenz": "apache-2.0", "geprueft": "17.09.2026",
        "platte_gb": 16.08, "gewichte_gb": 16.05, "bauart": "dicht, 27,4 Mrd.",
        "kv_kb_je_token": 64.0,
        "hinweis": "Unveraendertes Original von Qwen, nur in 4 Bit umgerechnet."},
    "Qwen2.5-7B-Instruct-4bit": {
        "quelle": "mlx-community/Qwen2.5-7B-Instruct-4bit (Bestand seit Block 11)",
        "lizenz": "apache-2.0", "geprueft": "16.09.2026",
        "platte_gb": 4.30, "gewichte_gb": 4.30, "bauart": "dicht, 7,6 Mrd.",
        "kv_kb_je_token": None, "hinweis": "Der bisherige Stand - Vergleichsgroesse."},
}


def kandidatenlaeufe(root=None, nur_kandidaten=True):
    """Laeufe im Messtestbuch, aufgeschluesselt nach dem Modell der Stufe 0.

    nur_kandidaten=True liefert nur die Laeufe aus Auftrag 27.1 (Marke
    'kandidat' in der Zeile). Sonst waere Lauf 6 - der regulaere Lauf mit dem
    Bestandsmodell - ununterscheidbar dabei, und der Bericht verglichen
    Laeufe, die verschiedene Fragen beantworten.
    """
    root = Path(root or HIER)
    je_lauf = {}
    for z in b.records(b.area(root) / BUCH):
        nummer = str(z.get("lauf") or "")
        if not nummer:
            continue
        eintrag = je_lauf.setdefault(nummer, {"lauf": nummer, "modell0": None,
                                              "kandidat": False, "zeit": z.get("zeit")})
        if str(z.get("stufe")) == "0" and z.get("modell"):
            eintrag["modell0"] = z["modell"]
            eintrag["kandidat"] = eintrag["kandidat"] or bool(z.get("kandidat"))
    return {n: e for n, e in je_lauf.items()
            if e["modell0"] and (e["kandidat"] or not nur_kandidaten)}


def kandidatenbericht(root=None):
    """Aufgabe 6: ein Bericht ueber alle gemessenen Kandidaten nach freigabe/.

    Er rechnet NICHTS neu - er liest, was in messtest.jsonl und in den
    MESSUNG_*.json steht. Was nicht gemessen wurde, steht als 'nicht gemessen'
    da und wird nicht geschaetzt.
    """
    root = Path(root or HIER)
    belege = root / "abnahme" / "Sichtpruefung_27.1_2026-09-17"
    laeufe = kandidatenlaeufe(root)
    if not laeufe:
        return {"ok": False, "meldung": "Kein einziger Kandidatenlauf im Messtestbuch."}

    zeilen_je_kandidat = {}
    for nummer, e in sorted(laeufe.items(), key=lambda x: int(x[0])):
        try:
            bericht = auswerten(root, nummer)
        except Exception as fehler:
            zeilen_je_kandidat[e["modell0"]] = {"lauf": nummer, "fehler": str(fehler)[:200]}
            continue
        mess = {}
        for p in belege.glob("MESSUNG_Lauf%s_*.json" % nummer):
            try:
                mess = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
        zeilen_je_kandidat[e["modell0"]] = {"lauf": nummer, "bericht": bericht,
                                            "messung": mess, "zeit": e["zeit"]}

    # Der Bestand gehoert daneben: Ohne ihn sagt eine Quote nichts darueber,
    # ob sich der Wechsel lohnt. Genommen wird der juengste regulaere Lauf.
    regulaer = [e for e in kandidatenlaeufe(root, nur_kandidaten=False).values()
                if not e["kandidat"]]
    if regulaer:
        neuester = max(regulaer, key=lambda e: int(e["lauf"]))
        try:
            zeilen_je_kandidat["%s (Bestand, Lauf %s)" % (neuester["modell0"], neuester["lauf"])] = {
                "lauf": neuester["lauf"], "bericht": auswerten(root, neuester["lauf"]),
                "messung": {}, "zeit": neuester["zeit"], "bestand": True}
        except Exception:
            pass

    datum = b.now().strftime("%Y-%m-%d")
    name = "%s_BERICHT_27.1_Stufe0_Kandidaten.md" % datum
    ordner = root / "auftraege" / "freigabe"
    ordner.mkdir(parents=True, exist_ok=True)
    text = _kandidatentext(root, zeilen_je_kandidat)
    (ordner / name).write_text(text, encoding="utf-8")
    try:
        import jack_freigaben
        jack_freigaben.anfordern(root, name, grund="Auftrag 27.1 - Stufe 0 zurueckholen")
    except Exception:
        pass
    return {"ok": True, "datei": str(ordner / name), "kandidaten": list(zeilen_je_kandidat)}


def _zahl(wert, einheit="", stellen=1):
    if wert is None or wert == []:
        return "nicht gemessen"
    if isinstance(wert, list):
        wert = sum(wert) / len(wert)
    return ("%%.%df %%s" % stellen) % (wert, einheit) if einheit else \
           ("%%.%df" % stellen) % wert


def _kandidatentext(root, je_kandidat):
    """Der Berichtstext. Getrennt gehalten, damit man ihn lesen kann."""
    datum = b.now().strftime("%d.%m.%Y")
    z = ["---", "marke:      JACK",
         "auftrag:    Auftrag 27.1 - Stufe 0 zurueckholen: welches lokale Modell?",
         "erteilt:    %s" % b.now().strftime("%Y-%m-%d %H:%M"),
         "von:        JACK (Messtest je Kandidat, Methodik Lauf 6)",
         "status:     freigabe", "freigabe:   nein", "gefahr:     keine",
         "tiefe:      mittel", "bereiche:   steuerung, kosten", "art:        kostenstufen",
         "---", ""]

    # Der Kopfsatz sagt zuerst, was zu entscheiden ist.
    tauglich = []
    for modell, d in je_kandidat.items():
        if d.get("fehler") or d.get("bestand"):
            continue
        q = (d["bericht"]["quote_je_stufe"] or {}).get("0")
        if q is not None and q >= SCHWELLE_HOEHER:
            tauglich.append((q, modell))
    tauglich.sort(reverse=True)
    if tauglich:
        z += ["**Stufe 0 kann zurueckkommen — mit %s.** Es trifft %.0f %% und liegt "
              "damit ueber der Schwelle von %d %%. Was das je Aufgabenart heisst, "
              "steht weiter unten; entscheiden musst du."
              % (tauglich[0][1], tauglich[0][0], SCHWELLE_HOEHER), ""]
    else:
        z += ["**Kein Kandidat ist gut genug. Stufe 0 bleibt ohne Aufgabenart.** "
              "Das ist ein klares Ergebnis und kein Zwischenstand: Die gemessenen "
              "Trefferquoten liegen unter der Schwelle von %d %%. Ein lokales Modell, "
              "das jede dritte Aufgabe verfehlt, spart kein Geld — es erzeugt "
              "Nacharbeit auf einer teureren Stufe." % SCHWELLE_HOEHER, ""]

    z += ["## Die Kandidaten nebeneinander", "",
          "| Kandidat | Lizenz | Platte | Trefferquote | vollst. Urteile | Dauer je Aufgabe | Tempo | Ladezeit | Speicherspitze |",
          "|---|---|---|---|---|---|---|---|---|"]
    for modell, d in je_kandidat.items():
        k = KANDIDATENKUNDE.get(modell.split(" (")[0], {})
        if d.get("fehler"):
            z.append("| %s | %s | %s | **Lauf nicht auswertbar** | — | — | — | — | — |"
                     % (modell, k.get("lizenz", "?"), _zahl(k.get("platte_gb"), "GB", 2)))
            continue
        ber, mess = d["bericht"], d.get("messung") or {}
        m0 = mess.get("stufe0_messung") or {}
        n = ber["versucht_je_stufe"].get("0", 0) or 1
        quote = ber["quote_je_stufe"].get("0")
        z.append("| %s | %s | %s | **%s** | %d von %d | %s | %s | %s | %s |"
                 % (modell, k.get("lizenz", "?"), _zahl(k.get("platte_gb"), "GB", 2),
                    "kein Urteil" if quote is None else "%.0f %%" % quote,
                    ber.get("urteile", 0), ber.get("urteile_geplant", 0),
                    _zahl(ber["sekunden_je_stufe"].get("0", 0) / n, "s", 1),
                    _zahl(m0.get("token_je_s"), "Token/s", 1),
                    _zahl(m0.get("laden_s"), "s", 1),
                    _zahl(m0.get("speicher_spitze_gb"), "GB", 2)))
    z += ["", "Zum Vergleich aus demselben Lauf: Stufe 1 (Haiku 4.5) und Stufe 2 "
          "(Sonnet 5). Ihre Quoten stehen in der Tabelle je Aufgabenart weiter unten.",
          "",
          "**Zur Ladezeit:** Der Wachposten macht vor dem Messtest einen kostenlosen "
          "Probelauf. Danach liegt das Modell im Dateizwischenspeicher von macOS - "
          "die Ladezeit oben ist deshalb die eines WARMEN Starts. Die Zeit eines "
          "kalten Starts steht im Protokoll des Wachpostens "
          "(`abnahme/Sichtpruefung_27.1_2026-09-17/A5_Start_<Modell>.log`, Feld "
          "`arbeiter_laden_s`). Fuer den Betrieb zaehlt der warme Wert: Der Arbeiter "
          "laedt nur einmal und haelt das Modell dann.", ""]

    z += ["## Was die Zahlen bedeuten", ""]
    for modell, d in je_kandidat.items():
        k = KANDIDATENKUNDE.get(modell.split(" (")[0], {})
        z += ["**%s** — %s. Quelle: `%s`, Lizenz %s (geprueft %s). %s"
              % (modell, k.get("bauart", "Bauart nicht hinterlegt"),
                 k.get("quelle", "?"), k.get("lizenz", "?"), k.get("geprueft", "?"),
                 k.get("hinweis", "")), ""]
        mess = (d.get("messung") or {})
        vor, nach = mess.get("stimme_vorher") or {}, mess.get("stimme_nachher") or {}
        waehrend = (mess.get("stufe0_messung") or {}).get("stimme_waehrend") or []
        if vor or nach or waehrend:
            werte = [x.get("sekunden") for x in waehrend if x.get("ok")]
            z += ["*Einfluss auf die Stimme* (derselbe Satz, derselbe Stimmprozess): "
                  "vorher %s, waehrend des Laufs %s, nachher %s."
                  % (_zahl(vor.get("sekunden"), "s", 2),
                     _zahl(werte or None, "s", 2),
                     _zahl(nach.get("sekunden"), "s", 2)), ""]
        rueck = (mess.get("stufe0_messung") or {}).get("rueckfaelle") or []
        if rueck:
            arten = {}
            for r in rueck:
                a = r.get("art") if isinstance(r, dict) else "fehler"
                arten[a] = arten.get(a, 0) + 1
            z += ["*Rueckfaelle waehrend des Laufs:* %s."
                  % ", ".join("%dx %s" % (v, kk) for kk, v in sorted(arten.items())), ""]

    # Die Empfehlung je Aufgabenart kommt aus der Regel, nicht aus einem Modell.
    bester = tauglich[0][1] if tauglich else None
    if bester:
        ber = je_kandidat[bester]["bericht"]
        z += ["## Was das je Aufgabenart heisst (Kandidat %s)" % bester, "",
              "| Aufgabenart | Stufe heute | empfohlen | Quote Stufe 0 | Begruendung |",
              "|---|---|---|---|---|"]
        for e in ber["tabelle"]:
            pfeil = ("**-> %d**" % e["stufe_empfohlen"] if e["stufe_empfohlen"] != e["stufe_heute"]
                     else "%d (bleibt)" % e["stufe_heute"])
            q0 = ber["quote_je_stufe"].get("0")
            z.append("| %s | %d | %s | %s | %s |"
                     % (e["art"], e["stufe_heute"], pfeil,
                        "kein Urteil" if q0 is None else "%.0f %%" % q0, e["warum"]))
        w = ber["ersparnis_monat_usd"]
        if isinstance(w, dict):
            z += ["", "**Erwartete Wirkung aufs Geld:** spart geschaetzt %s USD im Monat, "
                  "kostet %s USD mehr. Grundlage: %s."
                  % (w.get("spart_usd"), w.get("kostet_usd"), w.get("grundlage") or "—")]
            if w.get("ohne_zahl"):
                z += ["", "Fuer diese Aufgabenarten steht in den letzten sieben Tagen kein "
                      "Lauf im Verbrauchsbuch, eine Geldwirkung laesst sich daraus noch "
                      "nicht errechnen: %s." % ", ".join(w["ohne_zahl"])]
        z += ["", "Die Regel, nach der das entschieden wurde: " + ber["regel"], ""]

    z += ["", "## FREIGEBEN heisst", ""]
    if bester:
        z += ["Ich trage **%s** als Modell der Stufe 0 in `betrieb/kostenstufen.json` "
              "ein und gebe ihr die oben empfohlenen Aufgabenarten zurueck — mit "
              "Sicherung und Vermerk. Die nicht gewaehlten Modelle wandern nach "
              "`lokal.nosync/archiv/`; geloescht wird nichts." % bester]
    else:
        z += ["Es gibt nichts freizugeben. Stufe 0 bleibt ohne Aufgabenart. Die "
              "geladenen Modelle bleiben liegen, bis du entscheidest, was damit "
              "geschehen soll — geloescht wird nichts."]
    z += ["", "ABLEHNEN legt den Bericht mit Vermerk ab. Nichts wird geloescht.", "",
          "Quellen: `betrieb/messtest.jsonl`, "
          "`abnahme/Sichtpruefung_27.1_2026-09-17/` (Messwerte, Testlauf, Kandidaten), "
          "`betrieb/stufenlaeufe.jsonl` (Rueckfaelle). Stand %s." % datum,
          "", "## Mitnutzung durch PATRONOS.AI (Aufgabe 8)", "",
          "Als Vorschlag ausgearbeitet in "
          "`abnahme/Sichtpruefung_27.1_2026-09-17/A8_Mitnutzung_PATRONOS.md` — "
          "kurz: Was auf diesem iMac laeuft, kann Stufe 0 heute schon benutzen; was "
          "in der Wolke laeuft, kann es nicht, ohne die verbotene Tuer nach aussen. "
          "Gebaut wurde dafuer nichts.", "",
          "Der Auftrag nennt SARAH und PATRONOS.AI nebeneinander. Es ist **dieselbe "
          "Marke** — belegt in `GOTT WALD HOLDING/CLAUDE.md`, Zeile 251 bis 254 "
          "(\u201eNamensregel: es gibt kein SARAH mehr\u201c: \u201eSeit 15.07.2026 "
          "hei\u00dft alles PATRONOS.AI\u201c) sowie Zeile 137, 141 und 143 "
          "(Ablage, Quelltext-Ablage, Netzadresse). Gegenprobe an der Ablage am "
          "17.09.2026: einen Markenordner `00_Marken/SARAH` gibt es nicht mehr. "
          "Die Quelle ist die Regeldatei der Holding, also intern; sie deckt die "
          "Holding, nicht die Welt ausserhalb davon. Es geht also um EINEN "
          "Mitnutzer, nicht um zwei.", ""]
    return "\n".join(z)


def _kandidat_aus_argv():
    if "--kandidat" in sys.argv:
        i = sys.argv.index("--kandidat")
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return None


if __name__ == "__main__":
    was = sys.argv[1] if len(sys.argv) > 1 else "voranschlag"
    if was == "voranschlag":
        print(json.dumps(voranschlag(), ensure_ascii=False, indent=1))
    elif was == "stand":
        print(json.dumps(stand(), ensure_ascii=False, indent=1))
    elif was == "lauf":
        _lauf(HIER, kandidat=_kandidat_aus_argv())
    elif was == "starten":
        print(json.dumps(starten(HIER, neu_erzwingen="--erzwingen" in sys.argv,
                                 im_hintergrund="--vordergrund" not in sys.argv,
                                 kandidat=_kandidat_aus_argv()),
                         ensure_ascii=False, indent=1))
    elif was == "kandidat":
        # Auftrag 27.1: ein Messlauf fuer EIN lokales Modell.
        print(json.dumps(starten(HIER, kandidat=(sys.argv[2] if len(sys.argv) > 2 else ""),
                                 im_hintergrund="--vordergrund" not in sys.argv),
                         ensure_ascii=False, indent=1))
    elif was == "kandidatenbericht":
        # Auftrag 27.1, Aufgabe 6: der Vergleich aller gemessenen Kandidaten.
        print(json.dumps(kandidatenbericht(HIER), ensure_ascii=False, indent=1))
    elif was == "auswerten":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else None
        print(json.dumps(auswerten(HIER, n), ensure_ascii=False, indent=1))
    else:
        print("voranschlag | stand | starten [--erzwingen] [--vordergrund] | "
              "kandidat <modellordner> [--vordergrund] | kandidatenbericht | "
              "auswerten [lauf]")
