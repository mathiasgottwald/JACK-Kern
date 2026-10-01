#!/usr/bin/env python3
"""Planer fuer den echten Parallelbetrieb (Block 2).

Was unabhaengig ist, laeuft gleichzeitig. Nur wer dieselbe Sache anfasst,
stellt sich an. Der Planer
  - liest die Auftragskoepfe (bereiche, haengt_an, dringlichkeit, test),
  - erkennt Ringschluesse und meldet sie,
  - haelt die Obergrenze und den Budgetdeckel ein,
  - nimmt die Bereichssperren und startet je Auftrag genau einen Lauf,
  - fuehrt Buch fuer die Auftragstafel.

TESTAUFTRAEGE (Praefix TEST_, Kopf test: ja) laufen gegen eine Wegwerf-Aufgabe
OHNE Modellaufruf. Kein Anbieterlauf, keine Kosten. So verlangt es der Patron.
"""
import contextlib
import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

import jack_betrieb as betrieb
import jack_grenzen
import jack_guthaben
import jack_sperren as sperren
import jack_auftrag
import jack_faehigkeiten

HIER = Path(__file__).resolve().parent
AUF = HIER / "auftraege"
ZUSTAND = "laufende.json"
PROTOKOLL = "planer.jsonl"
FORTSCHRITT = "fortschritt"
DRINGLICH = {"hoch": 0, "normal": 1, "niedrig": 2}
# Solange diese Fahne liegt, startet der Planer AUSSCHLIESSLICH Testauftraege.
# Sie schuetzt die echten Auftraege des Patrons waehrend der Messungen.
# Der Name traegt TEST_, damit die Abschlussreinigung sie mit entfernt.
TESTFAHNE = "TEST_NUR_TESTBETRIEB.flag"
# Block 10, Auftrag 2.1 Punkt 2: Schleifenschutz. Wird derselbe Auftrag mehr
# als dreimal in Folge gestartet, ohne dass sich sein Fortschritt geaendert
# hat, laeuft er in einer Schleife. Der vierte Start findet nicht statt.
SCHLEIFE_MAX = 3


def nur_testbetrieb() -> bool:
    return (betrieb.area(HIER) / TESTFAHNE).exists()


# ----------------------------------------------------------------- Auftragskopf
def kopf(text: str) -> dict:
    """Liest den YAML-artigen Kopf zwischen den drei Strichen."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    raus = {}
    if not m:
        return raus
    for zeile in m.group(1).splitlines():
        if ":" in zeile:
            k, v = zeile.split(":", 1)
            raus[k.strip().lower()] = v.strip()
    return raus


def _datenklasse(k: dict) -> str:
    import modell_router
    return modell_router.datenklasse_aus_kopf((k or {}).get("datenklasse"))


def ist_test(name: str, k: dict) -> bool:
    return name.startswith("TEST_") or str(k.get("test", "")).lower() in ("ja", "true", "yes")


def auftraege(ordner="offen"):
    """Alle Auftraege eines Ordners mit ihrem Kopf."""
    ziel = AUF / ordner
    raus = []
    if not ziel.is_dir():
        return raus
    for f in sorted(ziel.glob("*.md")):
        if f.is_symlink() or f.name.lower().startswith("readme"):
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        k = kopf(text)
        qualitaet = jack_auftrag.kurzstand(HIER, f)
        bereiche = sperren.bereiche_aus_kopf(text)
        # Steuerdateien bleiben exklusiv geschuetzt. Wer eine von ihnen nennt,
        # bekommt den Bereich "steuerung" zwingend dazu - auch wenn er ihn
        # nicht angegeben hat. Das ist keine Bequemlichkeit, sondern die Regel
        # aus dem Auftrag: diese Dateien werden nie parallel angefasst.
        if any(s.lower() in text.lower() for s in sperren.STEUERDATEIEN):
            if "steuerung" not in bereiche:
                bereiche = sorted(set(bereiche) | {"steuerung"})
        raus.append({
            "datei": f.name, "pfad": str(f), "ordner": ordner, "kopf": k,
            "bereiche": bereiche,
            "haengt_an": [x.strip() for x in re.split(r"[,\s]+", k.get("haengt_an", "")) if x.strip()],
            "dringlichkeit": (k.get("dringlichkeit") or "normal").lower(),
            "erteilt": k.get("erteilt", ""), "marke": k.get("marke", "-"),
            "motor": (k.get("motor") or "api").lower(),
            "datenklasse": _datenklasse(k),
            "versuch": int(k.get("versuch") or 0) if str(k.get("versuch") or 0).isdigit() else 0,
            "titel": k.get("auftrag", f.stem)[:70],
            "test": ist_test(f.name, k),
            "qualitaet": qualitaet,
        })
    return raus


# ----------------------------------------------------------------- Ringschluss
def ringschluesse(liste):
    """Findet A->B->A. Wird gemeldet, nicht stillschweigend geparkt."""
    kanten = {a["datei"]: [h for h in a["haengt_an"]] for a in liste}
    gefunden, zustand = [], {}

    def geh(k, pfad):
        zustand[k] = 1
        for n in kanten.get(k, []):
            if zustand.get(n) == 1:
                ring = pfad[pfad.index(n):] + [n] if n in pfad else [n, k, n]
                if ring not in gefunden:
                    gefunden.append(ring)
            elif zustand.get(n, 0) == 0 and n in kanten:
                geh(n, pfad + [n])
        zustand[k] = 2

    for k in kanten:
        if zustand.get(k, 0) == 0:
            geh(k, [k])
    return gefunden


def erledigte_namen():
    namen = set()
    for ordner in ("erledigt",):
        ziel = AUF / ordner
        if ziel.is_dir():
            namen |= {f.name for f in ziel.glob("*.md")
                      if not f.is_symlink() and jack_auftrag.ist_erfolgreich(HIER, f)}
    return namen


# ----------------------------------------------------------------- Zustand
@contextlib.contextmanager
def planersperre(warten=True):
    """Nur EIN Takt zur Zeit. Sonst ueberschreiben sich zwei Planer die
    Zustandsdatei - am 16.09.2026 im Messlauf aufgetreten: der Serverfaden und
    das Messskript liefen gleichzeitig, und gestartete Laeufe gingen verloren.
    fcntl.flock ist vom Betriebssystem geschuetzt und faellt beim Prozessende
    von selbst weg."""
    pfad = betrieb.area(HIER) / "planer.sperre"
    datei = open(pfad, "a+")
    try:
        try:
            fcntl.flock(datei, fcntl.LOCK_EX if warten else (fcntl.LOCK_EX | fcntl.LOCK_NB))
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(datei, fcntl.LOCK_UN)
    finally:
        datei.close()


def zustand_pfad():
    return betrieb.area(HIER) / ZUSTAND


def zustand_lesen():
    p = zustand_pfad()
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"laeufe": {}, "nummern": {}, "naechste_nummer": 1, "alles_pausiert": False}


def zustand_schreiben(z):
    p = zustand_pfad()
    tmp = p.with_suffix(".json.neu")
    tmp.write_text(json.dumps(z, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def protokoll(art, **felder):
    try:
        e = {"zeit": betrieb.now().isoformat(), "art": art}
        e.update(felder)
        with (betrieb.area(HIER) / PROTOKOLL).open("a", encoding="utf-8") as d:
            d.write(json.dumps(e, ensure_ascii=False) + "\n")
    except Exception:
        pass


def nummer_fuer(z, datei):
    """Jeder Auftrag bekommt eine feste Nummer, die ihm bleibt."""
    if datei not in z["nummern"]:
        z["nummern"][datei] = z["naechste_nummer"]
        z["naechste_nummer"] += 1
    return z["nummern"][datei]


# ----------------------------------------------------------------- Fortschritt
def fortschritt_pfad(datei):
    p = betrieb.area(HIER) / FORTSCHRITT
    p.mkdir(exist_ok=True)
    return p / (datei.replace("/", "_") + ".json")


def fortschritt_lesen(datei):
    try:
        return json.loads(fortschritt_pfad(datei).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def fortschritt_setzen(datei, geplant=None, erledigt=None, schritt=None):
    """Der Balken kommt aus erledigten/geplanten Teilaufgaben, nie aus einer
    Schaetzung. Kommen Teilaufgaben dazu, waechst der Nenner und der Balken
    laeuft zurueck - das ist ehrlich und ausdruecklich erwuenscht."""
    f = fortschritt_lesen(datei) or {"geplant": None, "erledigt": 0, "schritt": "",
                                     "verlauf": []}
    if geplant is not None:
        f["geplant"] = int(geplant)
    if erledigt is not None:
        f["erledigt"] = int(erledigt)
    if schritt is not None:
        f["schritt"] = str(schritt)[:200]
    f["zeit"] = betrieb.now().isoformat()
    if f.get("geplant"):
        f["prozent"] = round(100.0 * f["erledigt"] / f["geplant"], 1)
    else:
        f["prozent"] = None
    f["verlauf"] = (f.get("verlauf") or [])[-19:] + [
        {"zeit": f["zeit"], "erledigt": f["erledigt"], "geplant": f["geplant"],
         "prozent": f["prozent"]}]
    p = fortschritt_pfad(datei)
    tmp = p.with_suffix(".json.neu")
    tmp.write_text(json.dumps(f, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)
    return f


# ------------------------------------------------------------ Schleifenschutz
def _fingerabdruck(datei):
    """Woran man erkennt, dass sich wirklich etwas bewegt hat.

    Genommen wird der Fortschritt, nicht die Uhrzeit: erledigte Teilaufgaben,
    geplante Teilaufgaben und der Text des aktuellen Schritts. Bleibt das
    ueber mehrere Starts gleich, hat der Lauf nichts erreicht - egal wie lange
    er lief und wie viele Tokens er verbraucht hat.
    """
    f = fortschritt_lesen(datei) or {}
    schritt = str(f.get("schritt") or "")
    # "gestartet" setzt der Planer selbst beim Start. Das ist kein Ergebnis des
    # Laufs - wuerde es mitzaehlen, waere der erste Start immer eine
    # Veraenderung, und der Schutz griffe einen Start zu spaet.
    if schritt == "gestartet":
        schritt = ""
    return "%s|%s|%s" % (f.get("erledigt", 0), f.get("geplant"), schritt)


def schleife_pruefen(z, datei):
    """Darf dieser Auftrag starten? (True, "") oder (False, Grund).

    Zaehlt die Starts OHNE neues Ergebnis. Beim vierten wird angehalten und
    als PROBLEM gemeldet - einmal, nicht in jedem Takt.
    """
    s = z.setdefault("schleife", {})
    e = s.get(datei) or {}
    if e.get("angehalten"):
        return False, e.get("grund", "Schleifenschutz: Auftrag angehalten")
    finger = _fingerabdruck(datei)
    if e.get("finger") == finger:
        starts = int(e.get("starts", 0)) + 1
    else:
        starts = 1
    e.update({"finger": finger, "starts": starts,
              "zuletzt": betrieb.now().isoformat()})
    s[datei] = e
    if starts > SCHLEIFE_MAX:
        grund = ("PROBLEM Schleifenschutz: %d Starts ohne neues Ergebnis "
                 "(Fortschritt unveraendert bei \"%s\"). Auftrag angehalten, "
                 "wartet auf die Entscheidung des Patrons." % (starts - 1, finger))
        e["angehalten"] = True
        e["grund"] = grund
        e["angehalten_seit"] = betrieb.now().isoformat()
        protokoll("problem_schleife", auftrag=datei, starts=starts - 1,
                  fingerabdruck=finger, wirkung="angehalten")
        return False, grund
    return True, ""


def schleife_freigeben(datei):
    """Der Patron hebt die Schleifensperre auf. Nur er, nie der Planer selbst."""
    z = zustand_lesen()
    e = (z.get("schleife") or {}).get(datei)
    if not e:
        return {"ok": False, "wirkung": "Fuer diesen Auftrag liegt keine Schleifensperre"}
    z["schleife"].pop(datei, None)
    zustand_schreiben(z)
    protokoll("schleife_freigegeben", auftrag=datei, von="Patron")
    return {"ok": True, "wirkung": "Schleifensperre aufgehoben; der Auftrag darf wieder starten"}


def zurueckholen(datei):
    """Einen Auftrag aus zurueckgestellt/ nach offen/ zurueckholen, Kopf normalisieren.

    Block 36 (23.09.2026): der Kopf einer zurueckgestellten Kopie darf beim
    Zurueckholen keine Reste tragen (alter "hinweis:"-Verweis, alter Status,
    verbrauchter Versuchszaehler) - genau das liess die Schleifensperre bisher
    faelschlich wegen eines veralteten Kopfes statt wegen echten
    Wiederholungsverhaltens greifen (Block 35, MEISTERWERK/PATRONOS-NACHHER).
    Die zurueckgestellte Kopie selbst bleibt unveraendert liegen (Beleg,
    Grundregel "nichts loeschen"); zurueckgeholt wird eine frisch
    normalisierte Fassung nach offen/, und die alte Schleifensperre dieses
    Dateinamens wird zusammen damit aufgehoben - der veraltete Kopf war ihre
    Ursache, kein echtes Wiederholungsverhalten des neuen Versuchs."""
    quelle = AUF / "zurueckgestellt" / datei
    if not quelle.is_file() or quelle.is_symlink():
        raise ValueError("Kein zurueckgestellter Auftrag mit diesem Namen")
    text = quelle.read_text(encoding="utf-8")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not m:
        raise ValueError("Auftragskopf fehlt oder ist ungueltig")
    aussen_schluessel = {z.split(":", 1)[0].strip().lower()
                          for z in m.group(1).splitlines() if ":" in z}
    rumpf = text[m.end():]
    # Die Zurueckstellung (Block 31-34) legt den echten Kopf oft NICHT in
    # diesen ersten Block, sondern haengt ihn als zweiten "---...---"-Block
    # in den Rumpf - der erste Block traegt dann nur die Zurueckstell-Notiz.
    # Wird das nicht erkannt, normalisiert zurueckholen() den falschen
    # (leeren) Kopf und verwirft den echten Auftragskopf als Fliesstext.
    innen = re.match(r"^\s*---\s*\n(.*?)\n---\s*\n", rumpf, re.S)
    if innen and aussen_schluessel <= {"hinweis", "zurueckgestellt_am", "zurueckgestellt_grund"}:
        kopfblock, rumpf = innen.group(1), rumpf[innen.end():]
    else:
        kopfblock = m.group(1)
    kopf_vorher = {}
    for zeile in kopfblock.splitlines():
        if ":" in zeile:
            k, _, v = zeile.partition(":")
            kopf_vorher[k.strip().lower()] = v.strip()

    neu, gesehen = [], set()
    for zeile in kopfblock.splitlines():
        if ":" not in zeile:
            continue
        schluessel, _, _ = zeile.partition(":")
        s = schluessel.strip().lower()
        if s in ("hinweis", "zurueckgestellt_am", "zurueckgestellt_grund"):
            continue  # Reste der Zurueckstellung, keine gueltigen Kopffelder mehr
        if s == "status":
            neu.append("status: offen"); gesehen.add("status"); continue
        if s == "versuch":
            neu.append("versuch: 1"); gesehen.add("versuch"); continue
        neu.append(zeile)
        gesehen.add(s)
    if "status" not in gesehen:
        neu.append("status: offen")
    if "versuch" not in gesehen:
        neu.append("versuch: 1")
    neu.append("zurueckgeholt_am: " + betrieb.now().isoformat())
    neuer_text = "---\n" + "\n".join(neu) + "\n---\n" + rumpf

    ziel = AUF / "offen" / datei
    ziel.parent.mkdir(parents=True, exist_ok=True)
    tmp = ziel.with_suffix(".md.neu")
    tmp.write_text(neuer_text, encoding="utf-8")
    os.replace(tmp, ziel)

    z = zustand_lesen()
    hatte_sperre = bool((z.get("schleife") or {}).pop(datei, None))
    if hatte_sperre:
        zustand_schreiben(z)
    protokoll("zurueckgeholt", auftrag=datei, quelle="zurueckgestellt",
              schleife_zurueckgesetzt=hatte_sperre)

    sperre_danach = (zustand_lesen().get("schleife") or {}).get(datei)
    return {"kopf_vorher": kopf_vorher, "kopf_nachher": kopf(neuer_text),
            "schleife_zurueckgesetzt": hatte_sperre,
            "sperre_frei": not (sperre_danach and sperre_danach.get("angehalten"))}


def schleifen_stand():
    """Alle angehaltenen Auftraege - fuer die Tafel und den Freigaben-Kasten."""
    z = zustand_lesen()
    raus = []
    for datei, e in (z.get("schleife") or {}).items():
        if e.get("angehalten"):
            raus.append({"datei": datei, "grund": e.get("grund", ""),
                         "starts": e.get("starts"), "seit": e.get("angehalten_seit")})
    return raus


# ----------------------------------------------------------------- Starten
def _schrittzeile(f):
    """Klartext neben dem Balken. Nie eine erfundene Zahl, nie ueber das Ziel hinaus."""
    erledigt = f.get("erledigt", 0)
    geplant = f.get("geplant")
    was = f.get("schritt") or "laeuft"
    if not geplant:
        return "Umfang unbekannt - Schritt %d: %s" % (erledigt + 1, was)
    if erledigt >= geplant:
        return "Alle %d Teilaufgaben bearbeitet; Abschlussprüfung steht gesondert" % geplant
    return "Schritt %d von %d: %s" % (erledigt + 1, geplant, was)


def lebt(pid, datei=None) -> bool:
    """Lebt dieser Lauf noch?

    Die Prozessnummer allein reicht nicht: stirbt ein Lauf und vergibt das
    System die Nummer neu, haelt der Planer einen fremden Prozess fuer seinen
    eigenen und blockiert damit alles. Am 16.09.2026 genau so aufgetreten.
    Deshalb wird zusaetzlich geprueft, ob in der Befehlszeile dieses Prozesses
    der Auftragsname steht."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        if not datei:
            return True                  # fremder Prozess, aber er lebt
    if not datei:
        return True
    try:
        befehl = subprocess.run(["/bin/ps", "-o", "command=", "-p", str(pid)],
                                capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return True                      # im Zweifel als lebend behandeln
    return datei in befehl


def _wiederverwendung_abschliessen(a, treffer, grund):
    """Block 32.2, Weg 0: kein Modellaufruf, kein Prozess, 0,00 USD. Der
    Auftrag bekommt einen Verweis auf das wiederverwendete Ergebnis und geht
    direkt nach erledigt/ - wie jeder andere fertige Lauf auf der Tafel."""
    quelle = Path(a["pfad"])
    try:
        text = quelle.read_text(encoding="utf-8")
    except OSError:
        return False
    vermerk = ("\n\n## Ergebnis (Wiederverwendung, Block 32.2 Wegsucher)\n"
               "Identischer Auftrag bereits erledigt - kein neuer Modellaufruf, 0,00 USD.\n"
               "- Wiederverwendetes Ergebnis: `%s`\n- Herkunft: %s\n- Zeit des Originals: %s\n- Grund: %s\n"
               % (treffer.get("ergebnis_pfad", "?"), treffer.get("herkunft", "?"),
                  treffer.get("zeit", "?"), grund))
    ziel = AUF / "erledigt" / a["datei"]
    try:
        ziel.write_text(text + vermerk, encoding="utf-8")
        quelle.unlink()
    except OSError:
        return False
    protokoll("wiederverwendung", auftrag=a["datei"], quelle=treffer.get("ergebnis_pfad", "?"))
    return True


NETZ_FRISCH_S = 300


def _netz_halt():
    """F-28: Grund, warum gerade nichts starten soll (Netz weg laut Netz-Waechter), sonst ''. Ein veralteter oder
    fehlender Netzstand haelt nichts an - der Waechter koennte selbst stehen, dann soll der Betrieb nicht einfrieren."""
    import datetime
    try:
        n = json.loads((betrieb.area(HIER) / "netz.json").read_text(encoding="utf-8"))
        alter = (betrieb.now() - datetime.datetime.fromisoformat(n["zeit"])).total_seconds()
    except (OSError, ValueError, KeyError, TypeError):
        return ""
    if n.get("online") is False and 0 <= alter <= NETZ_FRISCH_S:
        return ("Netz weg seit %s - Start geparkt, laeuft automatisch weiter, sobald das Netz wieder da ist"
                % str(n.get("seit") or n["zeit"])[11:16])
    return ""


def _netz_parken(datei, grund):
    """Vermerk in betrieb/wartend/ (der Auftrag selbst bleibt in offen/); beim naechsten Start wird er als fortgesetzt markiert."""
    import hashlib
    ordner = betrieb.area(HIER) / "wartend"
    ordner.mkdir(exist_ok=True)
    p = ordner / (hashlib.sha256(datei.encode("utf-8")).hexdigest()[:24] + ".json")
    if not p.exists():
        p.write_text(json.dumps({"datei": datei, "grund": grund, "seit": betrieb.now().isoformat()}, ensure_ascii=False))
        protokoll("netz_geparkt", auftrag=datei)


def _netz_fortsetzen(datei):
    import hashlib
    p = betrieb.area(HIER) / "wartend" / (hashlib.sha256(datei.encode("utf-8")).hexdigest()[:24] + ".json")
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not d.get("fortgesetzt"):
        d["fortgesetzt"] = betrieb.now().isoformat()
        p.write_text(json.dumps(d, ensure_ascii=False))
        protokoll("netz_fortgesetzt", auftrag=datei)


def starte(a, z, frist, weg=None):
    """Startet genau einen Auftrag. Testauftraege laufen OHNE Modellaufruf.

    weg (Block 32.2, vom Wegsucher VOR dem Aufruf entschieden): 'direkt' laesst
    motor_direkt.py laufen (reine Textarbeit, kein Werkzeugzugriff), alles
    andere bleibt der bestehende Motor (arbeiter.sh mit Stufe/Ruflo)."""
    ok, belegt = sperren.nehmen(HIER, a["bereiche"], a["datei"], frist=frist)
    if not ok:
        return None, belegt
    nummer = nummer_fuer(z, a["datei"])
    protokolldatei = betrieb.area(HIER) / "laeufe" / (a["datei"] + ".log")
    protokolldatei.parent.mkdir(exist_ok=True)
    if a["test"]:
        # Wegwerf-Aufgabe: Dateien zaehlen und kurz warten. Kein Anbieter, keine Kosten.
        befehl = [sys.executable, "-I", str(HIER / "jack_probelauf.py"), a["pfad"]]
    elif weg == "direkt":
        befehl = [sys.executable, "-I", str(HIER / "motor_direkt.py"), "--auftrag", a["pfad"]]
    else:
        befehl = ["/bin/bash", str(HIER / "arbeiter.sh"), "--nur", a["datei"]]
    # Block 33.5: kompakte Marken-Sicht aus dem JACK-Gedaechtnis exportieren
    # und dem Lauf ueber eine Umgebungsvariable mitgeben - die Datenbank
    # selbst bekommt kein Lauf zu Gesicht, nur diese kleine Exportdatei.
    umgebung = dict(os.environ)
    umgebung["JACK_DATENKLASSE"] = a.get("datenklasse") or "intern"
    try:
        import jack_gedaechtnis
        export_pfad = jack_gedaechtnis.export_marke(str(HIER), a["marke"])
        umgebung["JACK_GEDAECHTNIS_EXPORT"] = export_pfad
        protokoll("gedaechtnis_export", auftrag=a["datei"], marke=a["marke"], pfad=export_pfad)
    except Exception as fehler:
        protokoll("gedaechtnis_export_fehler", auftrag=a["datei"], fehler=type(fehler).__name__)
    if not a["test"]:
        try:
            import jack_berater
            auftragstext = Path(a["pfad"]).read_text(encoding="utf-8", errors="replace")
            eigene_stufe = int((a.get("kopf") or {}).get("stufe") or 1) \
                if str((a.get("kopf") or {}).get("stufe") or "1").isdigit() else 1
            beratung = jack_berater.frage(auftragstext, eigene_stufe, a["datei"])
            protokoll("berater", auftrag=a["datei"], ok=beratung.get("ok"),
                      empfehlung=beratung.get("empfehlung"), vergleich=beratung.get("vergleich"))
        except Exception as fehler:
            protokoll("berater_fehler", auftrag=a["datei"], fehler=type(fehler).__name__)
    _messpunkt_pickup(a)
    with protokolldatei.open("a", encoding="utf-8") as ausgabe:
        proc = subprocess.Popen(befehl, stdout=ausgabe, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, cwd=str(HIER),
                                start_new_session=True, env=umgebung)
    z["laeufe"][a["datei"]] = {
        "nummer": nummer, "datei": a["datei"], "titel": a["titel"], "marke": a["marke"],
        "bereiche": a["bereiche"], "pid": proc.pid, "start": betrieb.now().isoformat(),
        "start_epoch": time.time(), "zustand": "laeuft", "test": a["test"],
        "motor": (weg if weg == "direkt" else a["motor"]), "protokoll": str(protokolldatei),
        "weg": weg or ("test" if a["test"] else "cli"),
        "stufe": (a.get("kopf") or {}).get("stufe", ""),
    }
    fortschritt_setzen(a["datei"], schritt="gestartet")
    _netz_fortsetzen(a["datei"])          # F-28: war der Start wegen Netzausfall geparkt, jetzt als fortgesetzt vermerken
    protokoll("start", auftrag=a["datei"], nummer=nummer, pid=proc.pid,
              bereiche=a["bereiche"], test=a["test"], weg=weg or ("test" if a["test"] else "cli"),
              datenklasse=a.get("datenklasse") or "intern")
    return proc.pid, []


def ernten(z):
    """Beendete Laeufe abraeumen und ihre Sperren freigeben."""
    fertig = []
    for datei, lauf in list(z["laeufe"].items()):
        if lauf.get("zustand") in ("pausiert",):
            continue
        if not lebt(lauf.get("pid"), datei):
            sperren.geben(HIER, lauf.get("bereiche", []), datei)
            lauf["zustand"] = "fertig"
            lauf["ende"] = betrieb.now().isoformat()
            lauf["dauer_s"] = round(time.time() - lauf.get("start_epoch", time.time()))
            protokoll("ende", auftrag=datei, nummer=lauf.get("nummer"),
                      dauer_s=lauf["dauer_s"])
            fertig.append(datei)
            del z["laeufe"][datei]
            # F-9 (Paket 3): Liegt die Datei nach dem Prozessende noch in laeuft/, endete der Lauf ohne
            # Abschluss (Dienst-Neustart, Absturz, Unterbrechung). Bisher blieb sie dort liegen und niemand
            # holte sie ab. Jetzt: nach problem/ mit Abbruchgrund, Bereiche fuer die Fortsetzung reserviert.
            try:
                _abbruch_sichern(datei, lauf)
            except Exception as fehler:
                protokoll("abbruch_sichern_fehler", auftrag=datei, fehler=type(fehler).__name__)
            _gedaechtnis_ablegen_falls_erfolgreich(datei, lauf)
            _zettel_schreiben(datei, lauf)
            _lernen_nachfuehren(datei, lauf)
    return fertig


def _lernen_nachfuehren(datei, lauf):
    """F-20 (Paket 6): nach jedem Laufende Fehlerkatalog nachfuehren und die Wirkung der Lernregeln pruefen
    (verschlechtert bei n >= 3 je Seite -> Regel ruht, Meldung in den Montagsbericht). Ohne Modell, 0 USD.
    Fehler werden nur protokolliert - der Planer haelt dafuer nie an."""
    try:
        if lauf.get("test"):
            return None
        import jack_lernen
        neu = jack_lernen.katalog_aktualisieren(HIER)
        aenderungen = jack_lernen.wirkung_pruefen(HIER)
        protokoll("lernen", auftrag=datei, nummer=lauf.get("nummer"), katalog_neu=neu,
                  ruht=[a["regel"] for a in aenderungen if a["art"] == "ruht"])
        return neu
    except Exception as fehler:
        protokoll("lernen_fehler", auftrag=datei, fehler=type(fehler).__name__, text=str(fehler)[:200])
        return None


def _zettel_schreiben(datei, lauf):
    """F-11 (Paket 4, P01): nach jedem Laufende schreibt der PLANER den Abnahmezettel abnahme/<Nr>_zettel.md
    (Kurz- oder Vollzettel). Kein Lauf darf ihn schreiben (Pfadwaechter). Wegwerf-Testauftraege ohne Modell
    bekommen keinen. Fehler werden nur protokolliert - der Planer haelt dafuer nie an."""
    try:
        if lauf.get("test"):
            return None
        import jack_abnahmezettel
        erg = jack_abnahmezettel.schreiben(HIER, datei)
        protokoll("abnahmezettel", auftrag=datei, nummer=lauf.get("nummer"), pfad=Path(erg["pfad"]).name,
                  zettel=erg["art"], status=erg["status"], geaendert=erg["geaendert"])
        return erg
    except Exception as fehler:
        protokoll("abnahmezettel_fehler", auftrag=datei, fehler=type(fehler).__name__, text=str(fehler)[:200])
        return None


UNTERBRECHUNGEN = "unterbrechungen"


def _unterbrechung_pfad(datei):
    import hashlib
    p = betrieb.area(HIER) / UNTERBRECHUNGEN
    p.mkdir(exist_ok=True)
    return p / (hashlib.sha256(datei.encode("utf-8")).hexdigest() + ".json")


def _reservierungsfrist():
    grenzen = jack_grenzen.lesen(HIER)
    for feld in ("fortsetzung_sperrfrist_sekunden", "sperrfrist_sekunden"):
        try:
            wert = int(grenzen.get(feld))
            if 60 <= wert <= 7 * 86400:
                return wert
        except (TypeError, ValueError):
            continue
    return sperren.STANDARDFRIST


def _abbruch_sichern(datei, lauf):
    """F-9: toter Lauf, Datei noch in laeuft/ -> problem/ mit Abbruchgrund; Bereiche reservieren.
    Nichts wird geloescht, nichts neu gestartet. Der Grund steht im Problemabschnitt (fuer fortsetzen())."""
    quelle = AUF / "laeuft" / datei
    if not quelle.is_file() or quelle.is_symlink():
        return None
    marke = None
    mp = _unterbrechung_pfad(datei)
    try:
        marke = json.loads(mp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        marke = None
    if marke and marke.get("pid") == lauf.get("pid"):
        grund = "PROBLEM: Abbruch: %s (%s, von %s); Prozess beendet ohne Abschluss. Vorhandene Arbeit bleibt erhalten." % (
            marke.get("grund", "Unterbrechung"), marke.get("zeit", "?")[:19], marke.get("von", "?"))
    else:
        grund = ("PROBLEM: Abbruch: Prozess beendet ohne Abschluss (Dienst-Neustart oder Absturz, Prozess %s). "
                 "Vorhandene Arbeit bleibt erhalten." % lauf.get("pid"))
    ziel = AUF / "problem" / datei
    if ziel.exists():
        protokoll("abbruch_sichern_fehler", auftrag=datei, fehler="problem/ belegt")
        return None
    ziel.parent.mkdir(parents=True, exist_ok=True)
    text = quelle.read_text(encoding="utf-8")
    text += "\n## Problem (%s)\n%s\n" % (betrieb.now().strftime("%Y-%m-%d %H:%M"), grund)
    tmp = quelle.with_name("." + datei + ".abbruch")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, quelle)
    try:
        _kopf_zeilen_setzen(quelle, {"status": "problem"})
    except ValueError:
        pass
    os.replace(quelle, ziel)
    ok, belegt = sperren.reservieren(HIER, lauf.get("bereiche") or ["alles"], datei, frist=_reservierungsfrist())
    protokoll("abbruch_gesichert", auftrag=datei, pid=lauf.get("pid"), grund=grund[:200],
              reserviert=ok, belegt=[b.get("bereich") for b in belegt])
    return {"grund": grund, "reserviert": ok}


def unterbrechen(datei, grund="Dienst-Neustart", von="JACK"):
    """F-9: einen laufenden Auftrag ABSICHTLICH unterbrechen (Dienst-Neustart, Betriebs-STOPP, Abnahme).

    Anders als der Patron-STOPP (Abbruch bleibt Abbruch, Datei nach erledigt/) bleibt der Auftrag
    fortsetzbar: der Grund wird VOR dem Signal vermerkt, der Lauf bekommt SIGTERM (claude wird ueber
    arbeiter_api_start.py mitbeendet und seine Kosten gebucht), den Rest erledigt ernten()."""
    z = zustand_lesen()
    lauf = z["laeufe"].get(datei)
    if not lauf or not lebt(lauf.get("pid"), datei):
        return {"ok": False, "wirkung": "Kein lebender Lauf mit diesem Namen"}
    mp = _unterbrechung_pfad(datei)
    mp.write_text(json.dumps({"auftrag": datei, "grund": str(grund)[:120], "von": str(von)[:80],
                              "zeit": betrieb.now().isoformat(), "pid": lauf.get("pid")},
                             ensure_ascii=False), encoding="utf-8")
    protokoll("unterbrechung", auftrag=datei, grund=grund, von=von, pid=lauf.get("pid"))
    try:
        if lauf.get("zustand") == "pausiert":
            os.killpg(os.getpgid(lauf["pid"]), signal.SIGCONT)
        os.killpg(os.getpgid(lauf["pid"]), signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError) as fehler:
        return {"ok": False, "wirkung": "Signal fehlgeschlagen: %s" % type(fehler).__name__}
    for _ in range(300):
        if not lebt(lauf["pid"], datei):
            break
        time.sleep(0.1)
    return {"ok": True, "wirkung": "Auftrag %s unterbrochen (%s); fortsetzbar" % (lauf.get("nummer"), grund)}


def _gedaechtnis_ablegen_falls_erfolgreich(datei, lauf):
    """Block 33.1/33.5: ein erfolgreich erledigter Lauf bekommt eine
    Kurzfassung im Vault UND bei Ruflo. Scheitert Ruflo oder fehlt die
    Ergebnisdatei, wird nur protokolliert - der Planer haelt dafuer nie an."""
    try:
        if lauf.get("test"):
            return  # Wegwerf-Aufgaben ohne Modellaufruf gehoeren nicht ins Gedaechtnis.
        ziel = AUF / "erledigt" / datei
        if not ziel.is_file():
            return
        text = ziel.read_text(encoding="utf-8", errors="replace")
        ergebnis_start = text.find("## Ergebnis")
        ergebnistext = text[ergebnis_start:] if ergebnis_start >= 0 else text
        import jack_gedaechtnis
        jack_gedaechtnis.lauf_ablegen(lauf.get("marke", "HOLDING"),
                                       str(lauf.get("nummer") or datei),
                                       ergebnistext, "auftraege/erledigt/" + datei)
    except Exception as fehler:
        protokoll("gedaechtnis_fehler", auftrag=datei, fehler=type(fehler).__name__)


# ----------------------------------------------------------------- Takt
def _messpunkt_takt(z, t0, offen_anzahl, bericht):
    """A1 (24.09.2026): Messpunkt 'takt' fuer die Pickup-Latenz. NUR Messung, keine Ursachenanalyse.
    Nur bei offenen Auftraegen; entprellt: geschrieben wird, wenn sich (offen, gestartet, wartend)
    aendert oder seit dem letzten Messpunkt 300 s vergangen sind - sonst laeuft die Datei voll."""
    try:
        if not offen_anzahl:
            return
        sig = [offen_anzahl, len(bericht.get("gestartet", [])), len(bericht.get("wartend", []))]
        alt = z.get("messpunkt_takt") or {}
        jetzt = time.time()
        if alt.get("sig") == sig and jetzt - float(alt.get("epoch", 0)) < 300:
            return
        z["messpunkt_takt"] = {"sig": sig, "epoch": jetzt}
        protokoll("messpunkt", punkt="takt", epoch=round(jetzt, 3), takt_beginn_epoch=round(t0, 3),
                  takt_dauer_ms=int((jetzt - t0) * 1000), offen=offen_anzahl,
                  gestartet=sig[1], wartend=sig[2],
                  wartend_gruende=sorted({str(w.get("grund", ""))[:80] for w in bericht.get("wartend", [])})[:5])
    except Exception:
        pass


def _messpunkt_offen(z, offen, bericht):
    """A7 (24.09.2026): Zusatz-Messpunkt fuer die ungeklaerte ~2-h-Wartezeit vom 23.09.2026.
    Damals hielt eine Vorab-Sperre (vor dem Wegsucher) die Auftraege an, ohne je einen Grund zu
    protokollieren - oder die Datei lag noch gar nicht in offen/. Beides trennt dieser Punkt:
    'offen_gesehen' beim ersten Sehen einer Datei (mit mtime und Entstehungszeit der Datei, damit
    eine verspaetet eintreffende Datei - z. B. iCloud - auffaellt), 'offen_grund' bei jedem Wechsel
    des Wartegrunds je Datei. Nur bei Aenderung geschrieben, nicht in jedem Takt. Nur Messung."""
    try:
        gesehen = z.setdefault("offen_gesehen", {})
        jetzt = time.time()
        gruende = {w.get("datei"): str(w.get("grund", ""))[:120] for w in bericht.get("wartend", [])}
        gestartet = {g.get("datei") for g in bericht.get("gestartet", [])}
        namen = set()
        for a in offen:
            namen.add(a["datei"])
            if a["datei"] in z["laeufe"] and a["datei"] not in gestartet:
                continue
            grund = "gestartet" if a["datei"] in gestartet else gruende.get(
                a["datei"], "kein Wartegrund gemeldet (nicht im Bericht)")
            alt = gesehen.get(a["datei"])
            if alt and alt.get("grund") == grund:
                continue
            if not alt:
                st = os.stat(a["pfad"])
                geburt = getattr(st, "st_birthtime", None)
                protokoll("messpunkt", punkt="offen_gesehen", auftrag=a["datei"], epoch=round(jetzt, 3),
                          grund=grund, datei_mtime_epoch=round(st.st_mtime, 3),
                          datei_birth_epoch=round(geburt, 3) if geburt else None,
                          abstand_mtime_s=int(jetzt - st.st_mtime),
                          abstand_birth_s=int(jetzt - geburt) if geburt else None,
                          erteilt=a.get("erteilt"))
            else:
                protokoll("messpunkt", punkt="offen_grund", auftrag=a["datei"], epoch=round(jetzt, 3),
                          grund=grund, vorher=alt.get("grund"),
                          seit_erstsicht_s=int(jetzt - float(alt.get("erst", jetzt))))
            gesehen[a["datei"]] = {"erst": alt.get("erst", jetzt) if alt else jetzt, "grund": grund}
        for datei in list(gesehen):
            if datei not in namen:
                del gesehen[datei]
    except Exception:
        pass


# F-8 T1 (PM-Entscheidung 24.09.2026, Punkt 1): Die Tagesroutine laeuft einmal taeglich ueber den
# Planer-Takt (erster Takt ab TAGESROUTINE_AB_STUNDE), nicht mehr beim Arbeiterstart (dort kostete sie
# je Abholung 18-42 s). Der Takt wartet nicht darauf: die Routine startet im Hintergrund.
TAGESROUTINE_AB_STUNDE = 6


def _tagesroutine_falls_faellig(z, jetzt=None, starten=None):
    """Startet betrieb_routine.py hoechstens einmal je Kalendertag (Zeitzone Wien) im Hintergrund.

    Der Tag wird VOR dem Start im Planerzustand vermerkt: auch ein Fehlstart wiederholt sich am
    selben Tag nicht (die 5-Minuten-Routine des Dienstes bleibt das Netz). Gibt True zurueck,
    wenn dieser Aufruf die Routine gestartet hat. `jetzt` und `starten` sind fuer Tests austauschbar."""
    jetzt = jetzt or betrieb.now()
    heute = jetzt.date().isoformat()
    if jetzt.hour < TAGESROUTINE_AB_STUNDE or z.get("tagesroutine_tag") == heute:
        return False
    z["tagesroutine_tag"] = heute
    try:
        if starten is None:
            def starten():
                with (HIER / "betrieb_routine.log").open("a", encoding="utf-8") as ausgabe:
                    return subprocess.Popen([sys.executable, "-I", str(HIER / "betrieb_routine.py")],
                                            stdout=ausgabe, stderr=subprocess.STDOUT,
                                            stdin=subprocess.DEVNULL, cwd=str(HIER),
                                            start_new_session=True).pid
        pid = starten()
        protokoll("tagesroutine", tag=heute, pid=pid, quelle="planer_takt")
        return True
    except Exception as fehler:
        protokoll("tagesroutine_fehler", tag=heute, fehler=type(fehler).__name__)
        return False


def _messpunkt_pickup(a):
    """A1: Messpunkt 'planer_start' unmittelbar vor dem Popen des Motors. Zeitbasis fuer die Latenz:
    Auftragsdatei-mtime (Annahme: ungefaehr Ablagezeit in offen/) und Kopffeld 'erteilt'."""
    try:
        jetzt = time.time()
        mtime = os.stat(a["pfad"]).st_mtime
        protokoll("messpunkt", punkt="planer_start", auftrag=a["datei"], epoch=round(jetzt, 3),
                  datei_mtime_epoch=round(mtime, 3), wartezeit_seit_mtime_s=int(jetzt - mtime),
                  erteilt=a.get("erteilt"))
    except Exception:
        pass


def takt(nur_pruefen=False, nur_test=False):
    with planersperre() as dran:
        if not dran:
            return {"gestartet": [], "wartend": [], "fertig": [],
                    "ringschluesse": [], "deckel": "Ein anderer Takt laeuft gerade",
                    "verwaiste_sperren": []}
        return _takt(nur_pruefen, nur_test)


def _takt(nur_pruefen=False, nur_test=False):
    """Ein Durchgang: aufraeumen, ernten, so viel starten wie erlaubt.

    nur_test=True startet AUSSCHLIESSLICH Testauftraege. Das schuetzt die
    echten Auftraege des Patrons waehrend der Messungen - sie werden dann
    nicht angefasst, wie er es festgelegt hat. Liegt die Testfahne, gilt das
    unabhaengig vom Aufrufer."""
    nur_test = nur_test or nur_testbetrieb()
    takt_t0 = time.time()  # A1 Messpunkt (24.09.2026), nur Zeitstempel, keine Logik
    grenzen = jack_grenzen.lesen(HIER)
    frist = int(grenzen.get("sperrfrist_sekunden") or sperren.STANDARDFRIST)
    z = zustand_lesen()
    verwaist = sperren.aufraeumen(HIER)
    if verwaist:
        protokoll("sperren_aufgeraeumt", bereiche=verwaist)
    fertig = ernten(z)
    # F-39: Problemkarten mit angenommenem Nachfolger schliessen sich selbst (mv -n, nichts loeschen).
    if not (nur_pruefen or nur_test or os.environ.get("JACK_BETRIEB_DIR")):
        try:
            import jack_problemkarten
            for e in jack_problemkarten.schliessen(HIER):
                protokoll("problemkarte_geschlossen", **e)
        except Exception as fehler:
            protokoll("problemkarte_schliessen_fehler", fehler=type(fehler).__name__)
    # F-44: freigegebene Gespraechs-Entwuerfe (betrieb/auftrag_entwurf/*.json, von S-8) werden zu Auftragsdateien.
    if not (nur_pruefen or nur_test or os.environ.get("JACK_BETRIEB_DIR")):
        try:
            import jack_auftragsschreiber
            for e in jack_auftragsschreiber.verarbeiten(HIER):
                protokoll("auftrag_entwurf_verarbeitet", **{k: v for k, v in e.items() if k in ("kennung", "kanal", "datei", "abgelehnt", "grund")})
        except Exception as fehler:
            protokoll("auftrag_entwurf_fehler", fehler=type(fehler).__name__)
    # F-9 (Paket 3, T4): ausgebliebene Anbieterantworten im Takt pruefen (Zeitbudget je Anbieter).
    if not nur_pruefen:
        try:
            import jack_vorgaenge
            for p in jack_vorgaenge.takt(HIER):
                protokoll("vorgang_pruefung", **{k: v for k, v in p.items() if k in ("vg", "ergebnis", "beleg", "meldung")})
        except Exception as fehler:
            protokoll("vorgang_pruefung_fehler", fehler=type(fehler).__name__)
    # F-8 T1: nie in Pruef-/Testtakten und nicht unter der Test-Umleitung (kein Fremdlauf im Testbetrieb).
    if not (nur_pruefen or nur_test or os.environ.get("JACK_BETRIEB_DIR")):
        _tagesroutine_falls_faellig(z)

    offen = auftraege("offen")
    ringe = ringschluesse(offen)
    if ringe:
        protokoll("ringschluss", ringe=ringe)

    erledigt = erledigte_namen()
    gesperrt, grund = jack_grenzen.deckel_erreicht(HIER, grenzen)
    bericht = {"gestartet": [], "wartend": [], "fertig": fertig, "ringschluesse": ringe,
               "deckel": grund if gesperrt else "", "verwaiste_sperren": verwaist}
    # hartgesperrt (Block 31.1, Fund beim Testen): anders als der GELD-Deckel
    # (gesperrt), der Testauftraege absichtlich durchlaesst, weil sie nichts
    # kosten, meinen die Notbremse UND die STOPP-Datei "wirklich nichts Neues"
    # - auch keine Testauftraege. Ohne eigene Fahne rutschte ein TEST_-Auftrag
    # an beiden vorbei, weil er unten am gleichen "gesperrt and a['test']"-
    # Zweig haengt, der fuer den Geld-Deckel richtig, hier aber falsch ist.
    hartgesperrt = False

    if z.get("alles_pausiert"):
        bericht["deckel"] = "Notbremse: ALLES PAUSIERT. Keine neuen Laeufe."
        gesperrt = True
        hartgesperrt = True

    # Block 31.1: dateibasierter Stopp-Schalter, leichter als die Notbremse -
    # nur neue Starts werden angehalten, laufende Auftraege enden regulaer
    # (anders als "alles_pausiert", das laufende Prozesse per SIGSTOP haelt).
    if (betrieb.area(HIER) / "STOPP").exists():
        bericht["deckel"] = "STOPP-Datei gesetzt: keine neuen Laeufe. Laufende Auftraege enden regulaer."
        gesperrt = True
        hartgesperrt = True

    # Block 31.2: Guthaben-Warnung hoechstens einmal je Schwelle, nie den
    # Takt gefaehrden.
    try:
        jack_guthaben.warnung_pruefen(HIER)
    except Exception:
        pass

    im_ring = {d for r in ringe for d in r}
    api_halt = jack_guthaben.api_sperre(HIER) if any(
        not a['test'] and a['motor'] in ('api', 'ruflo') for a in offen) else ''
    netz_halt = _netz_halt()          # F-28: bei Netzausfall startet nichts Neues, weiter sobald das Netz wieder da ist
    # Block 5, 16.09.2026: Der Patron kann eine ganze Marke stoppen. Dann startet
    # hier nichts Neues mehr fuer sie. Laufende Auftraege beendet die Marken-
    # steuerung selbst und sauber; dieser Wachposten haelt nur NEUE Starts an.
    try:
        import jack_oberflaeche
        markensperren = jack_oberflaeche.sperren_lesen(HIER)
    except Exception:
        markensperren = {}
    # Reihenfolge: Dringlichkeit, dann Eingang. Wer lange wartet, rueckt vor.
    def rang(a):
        alter = 0
        try:
            import datetime as dt
            alter = (betrieb.now() - dt.datetime.fromisoformat(
                a["erteilt"].replace(" ", "T")).replace(tzinfo=betrieb.ZONE)).total_seconds()
        except Exception:
            alter = 0
        stufe = DRINGLICH.get(a["dringlichkeit"], 1)
        # Alterungsbonus: je volle 6 Stunden Wartezeit eine Stufe hoeher.
        stufe = max(0, stufe - int(alter // 21600))
        return (stufe, a["erteilt"], a["datei"])

    try:
        reserviert = sperren.reservierungen(HIER)
    except Exception:
        reserviert = {}
    for a in sorted(offen, key=rang):
        if a["datei"] in z["laeufe"]:
            continue
        if nur_test and not a["test"]:
            continue
        if a.get("qualitaet", {}).get("fehler"):
            bericht['wartend'].append({'datei': a['datei'], 'grund': a['qualitaet']['text']})
            continue
        if a.get('qualitaet', {}).get('gebunden'):
            bereit = jack_faehigkeiten.vorpruefung(HIER, a['qualitaet'].get('ablauf', 'arbeit'), motor=a['motor'])
            if not bereit['ausfuehrbar']:
                bericht['wartend'].append({'datei':a['datei'], 'grund':bereit['text']})
                continue
        if api_halt and not a['test'] and a['motor'] in ('api', 'ruflo'):
            bericht['wartend'].append({'datei': a['datei'], 'grund': api_halt})
            continue
        if netz_halt and not a['test']:
            bericht['wartend'].append({'datei': a['datei'], 'grund': netz_halt})
            _netz_parken(a['datei'], netz_halt)
            continue
        # Auftraege mit verbrauchten Versuchen NICHT erneut starten. Ohne diese
        # Sperre startet der Planer sie im Takt neu, der Arbeiter bricht sofort
        # ab, und das Fehlerprotokoll laeuft voll - am 16.09.2026 alle 20
        # Sekunden geschehen. Sie brauchen die Entscheidung des Patrons.
        # F-6: Eine gueltige Fortsetzung (Beleg + Vertrag + Kopfzeile) ist kein neuer Versuch.
        if versuche_verbraucht(a):
            bericht["wartend"].append({"datei": a["datei"],
                "grund": "Versuche verbraucht (%d) - wartet auf Entscheidung des Patrons" % a["versuch"]})
            continue
        if a["datei"] in im_ring:
            bericht["wartend"].append({"datei": a["datei"], "grund": "Ringschluss gemeldet"})
            continue
        sperre = markensperren.get(a["marke"] or "HOLDING", {})
        if sperre.get("zustand") in ("gestoppt", "pausiert"):
            wort = "gestoppt" if sperre["zustand"] == "gestoppt" else "pausiert"
            bericht["wartend"].append({"datei": a["datei"],
                "grund": "Marke %s ist vom Patron %s (seit %s)"
                         % (a["marke"], wort, str(sperre.get("seit", ""))[:16])})
            continue
        offene_vorgaenger = [h for h in a["haengt_an"] if h not in erledigt]
        if offene_vorgaenger:
            bericht["wartend"].append({"datei": a["datei"],
                                       "grund": "wartet auf " + ", ".join(offene_vorgaenger)})
            continue
        # 17.09.2026, Block 14: Der Deckel ist ein GELD-Deckel. Ein Testauftrag
        # laeuft ueber jack_probelauf.py - Dateien zaehlen und warten, kein
        # Anbieter, kein Modell, kein Cent. Ihn zu sperren ist derselbe Fehler,
        # den der Patron am 16.09. beim Gespraech korrigiert hat: gesperrt wird,
        # was Geld kostet, nicht was gerade da ist.
        if hartgesperrt:
            bericht["wartend"].append({"datei": a["datei"], "grund": bericht["deckel"]})
            continue
        if gesperrt and not a["test"]:
            bericht["wartend"].append({"datei": a["datei"], "grund": bericht["deckel"]})
            continue
        if gesperrt and a["test"]:
            protokoll("deckel_uebersprungen", auftrag=a["datei"],
                      grund="Testauftrag ohne Modellaufruf - Geld-Deckel gilt nicht")
        art = "probe" if a["test"] else ('api' if a['motor'] == 'ruflo' else a['motor'])
        laufend_gesamt = len(z["laeufe"])
        laufend_art = sum(1 for l in z["laeufe"].values()
                          if ("probe" if l.get("test") else ('api' if l.get('motor') == 'ruflo' else l.get("motor"))) == art)
        if laufend_gesamt >= int(grenzen.get("gleichzeitig_gesamt", 8)):
            bericht["wartend"].append({"datei": a["datei"], "grund": "Obergrenze gleichzeitig erreicht"})
            continue
        if laufend_art >= int((grenzen.get("gleichzeitig_je_art") or {}).get(art, 8)):
            bericht["wartend"].append({"datei": a["datei"], "grund": "Obergrenze fuer Art %s erreicht" % art})
            continue
        kollision = None
        for lauf in z["laeufe"].values():
            if sperren.kollidiert(a["bereiche"], lauf.get("bereiche", [])):
                kollision = lauf
                break
        # F-9 (T5): Bereiche eines unterbrochenen Auftrags bleiben bis zu seiner Fortsetzung reserviert.
        fremd = [halter for halter, bs in reserviert.items()
                 if halter != a["datei"] and sperren.kollidiert(a["bereiche"], bs)]
        if fremd:
            bericht["wartend"].append({"datei": a["datei"],
                "grund": "Bereich reserviert fuer die Fortsetzung von " + ", ".join(fremd)})
            continue
        if kollision:
            bericht["wartend"].append({"datei": a["datei"],
                "grund": "Bereich belegt von Auftrag %s" % kollision.get("nummer")})
            continue
        if nur_pruefen:
            bericht["gestartet"].append({"datei": a["datei"], "probe": True})
            continue
        # Block 32.2: Wegsucher entscheidet VOR jedem Start, welcher Weg laeuft.
        # Testauftraege und Ringschluesse/Sonderfaelle oben sind bereits
        # abgehandelt; hier geht es nur um echte, startbereite Auftraege.
        weg_info = None
        if not a["test"]:
            try:
                import jack_wegsucher
                auftragstext = Path(a["pfad"]).read_text(encoding="utf-8", errors="replace")
                weg_info = jack_wegsucher.entscheidung(a.get("kopf") or {}, auftragstext, [], root=str(HIER))
            except Exception as fehler:
                weg_info = {"weg": "cli", "grund": "Wegsucher nicht auswertbar (%s) - vorsichtshalber CLI" % type(fehler).__name__}
            protokoll("wegsucher", auftrag=a["datei"], weg=weg_info["weg"], grund=weg_info["grund"])
            if weg_info["weg"] == "wiederverwendung":
                treffer = weg_info["wiederverwendung"]
                jack_wegsucher_ok = _wiederverwendung_abschliessen(a, treffer, weg_info["grund"])
                if jack_wegsucher_ok:
                    bericht["fertig"].append(a["datei"])
                    continue
                # Wiederverwendung fehlgeschlagen (z.B. Zieldatei zwischenzeitlich weg) -
                # normal weiterlaufen lassen, kein stiller Abbruch.
                weg_info = {"weg": "cli", "grund": "Wiederverwendung fehlgeschlagen, regulaer weiter"}
        # Block 10: Schleifenschutz. Erst hier, damit ein Auftrag, der nur auf
        # einen freien Platz wartet, keinen Start angerechnet bekommt.
        darf, schleifengrund = schleife_pruefen(z, a["datei"])
        if not darf:
            bericht["wartend"].append({"datei": a["datei"], "grund": schleifengrund})
            bericht.setdefault("probleme", []).append(
                {"datei": a["datei"], "grund": schleifengrund})
            continue
        pid, belegt = starte(a, z, frist, weg=(weg_info or {}).get("weg"))
        if pid:
            bericht["gestartet"].append({"datei": a["datei"], "pid": pid,
                                         "nummer": z["laeufe"][a["datei"]]["nummer"],
                                         "weg": (weg_info or {}).get("weg")})
        else:
            bericht["wartend"].append({"datei": a["datei"],
                "grund": "Sperre belegt: " + ", ".join(b["bereich"] for b in belegt)})
    if not nur_pruefen:
        _wartegruende_merken(z, bericht)
        _vorgangsbuecher_schreiben(z, offen)
    _messpunkt_takt(z, takt_t0, len(offen), bericht)
    _messpunkt_offen(z, offen, bericht)
    zustand_schreiben(z)
    return bericht


def _wartegruende_merken(z, bericht):
    """F-9 (Vorlage 3.2/5): EINE Quelle fuer Wartegruende - der Takt. Die Tafel liest sie hier.
    'seit' bleibt stehen, solange der Grund gleich bleibt."""
    try:
        import jack_vorgaenge
        alt = z.get("wartegruende") or {}
        neu = {}
        for w in bericht.get("wartend", []):
            d, g = w.get("datei"), str(w.get("grund", ""))
            vorher = alt.get(d) or {}
            seit = vorher.get("seit") if vorher.get("text") == g[:300] else betrieb.now().isoformat()
            neu[d] = jack_vorgaenge.wartegrund(g, seit=seit, quelle="takt")
        z["wartegruende"] = neu
    except Exception as fehler:
        protokoll("wartegruende_fehler", fehler=type(fehler).__name__)


def _vorgangsbuecher_schreiben(z, offen):
    """F-9 (M1/M3): Vorgangsbuch je Auftrag - nur der Planer schreibt es, abgeleitet aus Belegen."""
    try:
        import jack_vorgaenge
        ziele = [(a["datei"], AUF / "offen" / a["datei"], "offen") for a in offen]
        ziele += [(d, AUF / "laeuft" / d, "laeuft") for d in z["laeufe"]]
        ziele += [(p.name, p, "problem") for p in sorted((AUF / "problem").glob("*.md")) if not p.is_symlink()]
        for datei, pfad, ordner in ziele[:40]:
            if not pfad.is_file():
                continue
            buch = jack_vorgaenge.buch_ableiten(HIER, pfad, ordner=ordner, laeuft=ordner == "laeuft",
                                                wartegrund=(z.get("wartegruende") or {}).get(datei))
            jack_vorgaenge.buch_schreiben(HIER, buch)
    except Exception as fehler:
        protokoll("vorgangsbuch_fehler", fehler=type(fehler).__name__)


# ----------------------------------------------------------------- Steuerung
def _gestoppt_ablegen(datei, lauf):
    """Die Auftragsdatei nach erledigt/ legen, mit Vermerk. Gibt einen Satz zurueck."""
    jetzt = betrieb.now().strftime("%Y-%m-%d %H:%M")
    for gruppe in ("laeuft", "offen"):
        quelle = AUF / gruppe / datei
        if not quelle.is_file() or quelle.is_symlink():
            continue
        try:
            text = quelle.read_text(encoding="utf-8")
            text = re.sub(r"^status:.*$", "status:     gestoppt", text, count=1, flags=re.M)
            text += ("\n\n## Vom Patron gestoppt am %s\n"
                     "Der Lauf wurde in der Auftragstafel beendet (Prozess %s). "
                     "Nichts geloescht - die Datei liegt vollstaendig in "
                     "auftraege/erledigt/ und kann jederzeit neu erteilt werden.\n"
                     % (jetzt, lauf.get("pid", "?")))
            ziel = AUF / "erledigt" / datei
            n = 1
            while ziel.exists():
                ziel = AUF / "erledigt" / ("%s_%d%s" % (ziel.stem, n, ziel.suffix))
                n += 1
            ziel.write_text(text, encoding="utf-8")
            quelle.unlink()
            protokoll("gestoppt_abgelegt", auftrag=datei, ziel=ziel.name)
            _zettel_schreiben(ziel.name, lauf)  # F-11: auch ein Stopp bekommt seinen Zettel (Status blockiert)
            return " · Datei nach erledigt/ verschoben (%s)" % ziel.name
        except OSError as fehler:
            return " · Datei konnte nicht verschoben werden: %s" % type(fehler).__name__
    return " · keine Auftragsdatei zum Verschieben gefunden"


def steuern(befehl, datei=None, von="Patron", nur_test=False):
    with planersperre() as dran:
        if not dran:
            return {"ok": False, "wirkung": "Ein anderer Vorgang laeuft gerade"}
        return _steuern(befehl, datei, von, nur_test)


def _kopf_zeilen_setzen(pfad, werte):
    """Kopffelder setzen (bestehende ersetzen, neue anhaengen), Rest byte-gleich.
    Atomar ueber eine Temporaerdatei im selben Ordner."""
    text = Path(pfad).read_text(encoding="utf-8")
    zeilen = text.splitlines(keepends=True)
    if not zeilen or zeilen[0].strip() != "---":
        raise ValueError("Auftragskopf fehlt")
    ende = next((i for i in range(1, len(zeilen)) if zeilen[i].strip() == "---"), None)
    if ende is None:
        raise ValueError("Auftragskopf ist nicht abgeschlossen")
    rest = dict(werte)
    for i in range(1, ende):
        schluessel = zeilen[i].partition(":")[0].strip()
        if schluessel in rest:
            zeilen[i] = (schluessel + ":").ljust(12) + rest.pop(schluessel) + "\n"
    zeilen[ende:ende] = [(k + ":").ljust(12) + v + "\n" for k, v in rest.items()]
    tmp = Path(pfad).with_name("." + Path(pfad).name + ".fortsetzung")
    tmp.write_text("".join(zeilen), encoding="utf-8")
    os.replace(tmp, pfad)


def versuche_verbraucht(a, root=None):
    """F-6/F-7: True, wenn der Auftrag seine Versuche verbraucht hat und der Planer ihn NICHT starten darf.

    Eine gueltige Fortsetzung (Beleg + Vertrag + Kopfzeile) ist kein neuer Versuch. Ohne diese
    Ausnahme hielt der Planer die Fortsetzung von Nr. 123 im Echtlauf an (F-6)."""
    root = Path(root) if root else HIER
    return (a["versuch"] >= a.get("qualitaet", {}).get("max_versuche", 2)
            and not jack_auftrag.fortsetzung_kopf(root, a["pfad"]))


def fortsetzen(datei, root=None, budget_usd="0.60", tor2_nachlauf=None):
    """F-6 (24.09.2026): Auftrag aus problem/ am letzten sicheren Schritt fortsetzen.

    Nur wenn der Abbruchgrund die Zeitgrenze war und die Fachkraft-Ausgabe formal
    vollstaendig vorliegt (jack_auftrag.fortsetzung_vorbereiten). Der Auftrag geht
    nach offen/ mit Kopf `fortsetzung`, `letzter_sicherer_schritt: fachkraft_fertig`.
    `versuch` bleibt unveraendert: Fortsetzen ist kein neuer Versuch. Keine Fachkraft
    wird neu gestartet (Waechter in arbeiter.sh sperrt sie im Fortsetzungslauf).

    Idempotent: liegt der Auftrag schon in offen/ oder laeuft/, aendert ein zweiter
    Aufruf nichts (kein zweiter Beleg, keine zweite Ausfuehrung). Nach einem weiteren
    Abbruch verweigert jack_auftrag.fortsetzung_vorbereiten (Grenze FORTSETZUNG_MAX)."""
    root = Path(root) if root else HIER
    auf = root / "auftraege"
    name = Path(datei).name
    quelle = auf / "problem" / name
    # F-9: Abbruch bleibt Abbruch - ein vom Patron gestoppter Auftrag wird nie fortgesetzt.
    gestoppt = auf / "erledigt" / name
    if (not quelle.is_file() and gestoppt.is_file() and not gestoppt.is_symlink()
            and re.search(r"^## Vom Patron gestoppt", gestoppt.read_text(encoding="utf-8"), re.M)):
        raise ValueError("Abbruch bleibt Abbruch: der Patron hat diesen Auftrag gestoppt; er wird nie "
                         "fortgesetzt, nur neu erteilt")
    if not quelle.is_file() or quelle.is_symlink():
        beleg = jack_auftrag.fortsetzung_lesen(root, name)
        for ordner in ("offen", "laeuft"):
            liegt = auf / ordner / name
            if beleg is not None and liegt.is_file() and not liegt.is_symlink():
                if ordner == "offen" and not kopf(liegt.read_text(encoding="utf-8")).get("fortsetzung"):
                    _kopf_zeilen_setzen(liegt, {"fortsetzung": beleg["kennung"],
                                                "letzter_sicherer_schritt": beleg["letzter_sicherer_schritt"]})
                return {"ok": True, "bereits": True, "ordner": ordner, "kennung": beleg["kennung"],
                        "wirkung": "Fortsetzung liegt schon vor (%s/); keine zweite Ausfuehrung" % ordner}
        raise ValueError("Kein Auftrag in problem/ mit diesem Namen")
    vorher = jack_auftrag.fortsetzung_lesen(root, name)
    if vorher is not None and vorher.get("tor2_nachlauf") and not tor2_nachlauf:
        # F-7: Startfehler vor jeder Bezahlung -> derselbe Nachlauf-Beleg, genau einmal wieder aufnehmen
        beleg = jack_auftrag.nachlauf_startfehler_wiederaufnahme(root, quelle)
        ziel = auf / "offen" / name
        ziel.parent.mkdir(parents=True, exist_ok=True)
        if ziel.exists():
            raise ValueError("In offen/ liegt schon ein Auftrag mit diesem Namen")
        os.replace(quelle, ziel)
        _kopf_zeilen_setzen(ziel, {"status": "offen", "fortsetzung": beleg["kennung"],
                                   "letzter_sicherer_schritt": beleg["letzter_sicherer_schritt"]})
        try:
            protokoll("fortsetzung", auftrag=name, kennung=beleg["kennung"], schritt="startfehler_wiederaufnahme",
                      versuch=beleg["versuch"], ursprungslauf=beleg["ursprungslauf_id"], budget_usd=beleg["budget_usd"])
        except Exception:
            pass
        return {"ok": True, "bereits": False, "ordner": "offen", "kennung": beleg["kennung"],
                "wirkung": "Tor-2-Nachlauf nach Startfehler ohne Kosten wieder aufgenommen; Rahmen %s USD" % beleg["budget_usd"]}
    budget_usd = _fortsetzung_budget(root, quelle, budget_usd)
    if _schema1_weg(root, quelle, vorher, tor2_nachlauf):
        beleg = jack_auftrag.fortsetzung_vorbereiten(root, quelle, budget_usd, tor2_nachlauf=tor2_nachlauf)
    else:
        beleg = jack_auftrag.fortsetzung_vorbereiten_2(root, quelle, budget_usd)
    ziel = auf / "offen" / name
    ziel.parent.mkdir(parents=True, exist_ok=True)
    if ziel.exists():
        raise ValueError("In offen/ liegt schon ein Auftrag mit diesem Namen")
    os.replace(quelle, ziel)
    _kopf_zeilen_setzen(ziel, {"status": "offen", "fortsetzung": beleg["kennung"],
                               "letzter_sicherer_schritt": beleg["letzter_sicherer_schritt"]})
    reserviert = None
    if root.resolve() == HIER.resolve():
        # F-9 (T5): Bereiche bleiben bis zum Start der Fortsetzung reserviert (Frist erneuert).
        try:
            reserviert, _ = sperren.reservieren(HIER, sperren.bereiche_aus_kopf(ziel.read_text(encoding="utf-8")),
                                                name, frist=_reservierungsfrist())
        except Exception:
            reserviert = False
    try:
        protokoll("fortsetzung", auftrag=name, kennung=beleg["kennung"], schritt=beleg["letzter_sicherer_schritt"],
                  versuch=beleg["versuch"], ursprungslauf=beleg["ursprungslauf_id"], budget_usd=beleg["budget_usd"],
                  schema=beleg.get("schema"), grund=beleg.get("grund"), reserviert=reserviert)
    except Exception:
        pass
    return {"ok": True, "bereits": False, "ordner": "offen", "kennung": beleg["kennung"],
            "schema": beleg.get("schema"), "grund": beleg.get("grund"),
            "wirkung": "Fortgesetzt am Schritt %s; versuch bleibt %s; Rahmen %s USD"
                       % (beleg["letzter_sicherer_schritt"], beleg["versuch"], beleg["budget_usd"])}


def _schema1_weg(root, quelle, vorher, tor2_nachlauf):
    """F-9: Der F-6/F-7-Weg bleibt unveraendert (Rueckweg der Vorlage M7): Tor-2-Nachlauf, ein Auftrag mit
    Schema-1-Beleg, oder Zeitgrenze mit formal vollstaendiger Ausgabe ohne bisherigen Beleg. Alles andere
    (Deckel, Anbieterfehler, Dienst-Neustart, STOPP, Zeitgrenze mitten im Fachkraft-Schritt) -> Schema 2."""
    if tor2_nachlauf:
        return True
    if vorher is not None:
        return vorher.get("schema") != jack_auftrag.FORTSETZUNG_SCHEMA_2
    text = quelle.read_text(encoding="utf-8")
    if jack_auftrag.abbruch_klasse(jack_auftrag.abbruchgrund(text)) != "zeitgrenze":
        return False
    try:
        check = jack_auftrag.lokale_vorpruefung(root, quelle, protokollieren=False)
    except Exception:
        return True
    return bool(check.get("ok") and check.get("gebunden"))


def _fortsetzung_budget(root, quelle, budget_usd):
    """F-9 (M8): Kopffeld kostenrahmen_usd deckelt die Fortsetzung auf den Rest des Auftragsrahmens."""
    from decimal import Decimal, InvalidOperation
    try:
        rahmen = kopf(quelle.read_text(encoding="utf-8")).get("kostenrahmen_usd")
        if not rahmen:
            return budget_usd
        k = jack_auftrag.kosten(root, quelle.name)
        rest = Decimal(str(rahmen)) - Decimal(k["gemeldet_usd"]) - Decimal(k["geschaetzt_usd"])
        if rest <= Decimal("0.05"):
            raise ValueError("Kostenrahmen des Auftrags (%s USD) ist verbraucht; keine Fortsetzung" % rahmen)
        return str(min(Decimal(str(budget_usd)), rest.quantize(Decimal("0.01"))))
    except (InvalidOperation, TypeError):
        return budget_usd


def _steuern(befehl, datei=None, von="Patron", nur_test=False):
    """START, PAUSE, WEITER, STOPP und die Notbremse. Jeder Klick wird
    mit Zeit, Auftrag und Wirkung protokolliert."""
    z = zustand_lesen()
    wirkung = ""
    if befehl == "alles_pausieren":
        z["alles_pausiert"] = True
        betroffen = []
        for d, l in z["laeufe"].items():
            if l.get("zustand") == "laeuft" and lebt(l.get("pid"), d):
                try:
                    os.killpg(os.getpgid(l["pid"]), signal.SIGSTOP)
                    l["zustand"] = "pausiert"
                    l["pausiert_seit"] = betrieb.now().isoformat()
                    betroffen.append(l.get("nummer"))
                except (ProcessLookupError, PermissionError, OSError):
                    pass
        wirkung = "Notbremse: %d Laeufe angehalten, keine neuen Starts" % len(betroffen)
    elif befehl == "alles_weiter":
        z["alles_pausiert"] = False
        betroffen = []
        for d, l in z["laeufe"].items():
            if l.get("zustand") == "pausiert" and lebt(l.get("pid"), d):
                try:
                    os.killpg(os.getpgid(l["pid"]), signal.SIGCONT)
                    l["zustand"] = "laeuft"
                    l.pop("pausiert_seit", None)
                    betroffen.append(l.get("nummer"))
                except (ProcessLookupError, PermissionError, OSError):
                    pass
        wirkung = "Notbremse geloest: %d Laeufe fortgesetzt" % len(betroffen)
    elif befehl == "weiter" and datei and not z["laeufe"].get(datei) and (AUF / "problem" / Path(datei).name).is_file():
        # F-9 (T2/T3): WEITER an einem unterbrochenen Auftrag = am letzten sicheren Schritt fortsetzen.
        try:
            erg = fortsetzen(datei)
            wirkung = erg["wirkung"]
        except ValueError as fehler:
            wirkung = "Nicht fortsetzbar: %s" % fehler
    elif befehl in ("pause", "weiter", "stopp"):
        lauf = z["laeufe"].get(datei)
        if not lauf:
            wirkung = "Kein laufender Auftrag mit diesem Namen"
        elif befehl == "pause":
            try:
                os.killpg(os.getpgid(lauf["pid"]), signal.SIGSTOP)
                lauf["zustand"] = "pausiert"
                lauf["pausiert_seit"] = betrieb.now().isoformat()
                # Die Sperren BLEIBEN beim pausierten Auftrag - sonst koennte ein
                # anderer Lauf in denselben Bereich schreiben, waehrend dieser
                # mitten in einer Aenderung steht. So steht es in der Betriebsordnung.
                wirkung = "Auftrag %s angehalten; Sperren bleiben gehalten" % lauf.get("nummer")
            except (ProcessLookupError, PermissionError, OSError) as f:
                wirkung = "Anhalten fehlgeschlagen: %s" % type(f).__name__
        elif befehl == "weiter":
            try:
                os.killpg(os.getpgid(lauf["pid"]), signal.SIGCONT)
                lauf["zustand"] = "laeuft"
                lauf.pop("pausiert_seit", None)
                wirkung = "Auftrag %s laeuft genau dort weiter, wo er stand" % lauf.get("nummer")
            except (ProcessLookupError, PermissionError, OSError) as f:
                wirkung = "Fortsetzen fehlgeschlagen: %s" % type(f).__name__
        else:
            try:
                if lauf.get("zustand") == "pausiert":
                    os.killpg(os.getpgid(lauf["pid"]), signal.SIGCONT)
                os.killpg(os.getpgid(lauf["pid"]), signal.SIGTERM)
                for _ in range(30):
                    if not lebt(lauf["pid"], datei):
                        break
                    time.sleep(0.1)
                if lebt(lauf["pid"], datei):
                    os.killpg(os.getpgid(lauf["pid"]), signal.SIGKILL)
                wirkung = "Auftrag %s beendet" % lauf.get("nummer")
            except (ProcessLookupError, PermissionError, OSError) as f:
                wirkung = "Beenden fehlgeschlagen: %s" % type(f).__name__
            sperren.geben(HIER, lauf.get("bereiche", []), datei)
            lauf["zustand"] = "gestoppt"
            lauf["ende"] = betrieb.now().isoformat()
            z["laeufe"].pop(datei, None)
            # Block 13 (B2): Ein gestoppter Auftrag bleibt nicht in offen/ oder
            # laeuft/ liegen - sonst holt ihn der naechste Takt sofort wieder.
            # Er geht mit Vermerk nach erledigt/. Nichts wird geloescht.
            wirkung += _gestoppt_ablegen(datei, lauf)
    elif befehl == "stopp_setzen":
        # Block 31.1: leichter, dateibasierter Schalter - nur neue Starts
        # werden angehalten (ueber _takt()/jack_auftragsstart.py geprueft),
        # laufende Auftraege enden regulaer. Anders als die Notbremse oben,
        # die per SIGSTOP sofort eingreift.
        pfad = betrieb.area(HIER) / "STOPP"
        pfad.write_text("Gesetzt " + betrieb.now().isoformat() + " von " + str(von)[:80] + "\n",
                         encoding="utf-8")
        wirkung = "STOPP gesetzt: keine neuen Laeufe mehr, laufende enden regulaer"
    elif befehl == "stopp_aufheben":
        pfad = betrieb.area(HIER) / "STOPP"
        if pfad.exists():
            pfad.unlink()
            wirkung = "STOPP aufgehoben: neue Laeufe sind wieder erlaubt"
        else:
            wirkung = "STOPP war nicht gesetzt"
    elif befehl == "start":
        wirkung = "Sofortstart angefordert"
    else:
        wirkung = "Unbekannter Befehl"
    zustand_schreiben(z)
    protokoll("steuerung", befehl=befehl, auftrag=datei, von=von, wirkung=wirkung)
    if befehl == "start" and datei:
        b = _takt(nur_test=nur_test)
        gestartet = [g for g in b["gestartet"] if g["datei"] == datei]
        wirkung = ("Auftrag gestartet" if gestartet
                   else "Noch nicht startbar: " +
                        next((w["grund"] for w in b["wartend"] if w["datei"] == datei), "unbekannt"))
        protokoll("steuerung_ergebnis", befehl=befehl, auftrag=datei, wirkung=wirkung)
    return {"ok": True, "wirkung": wirkung}


# ----------------------------------------------------------------- Tafel
def _kosten_seit(start, auftrag=None):
    """Was hat dieser Lauf bisher gekostet? None, wenn nichts gemeldet ist.

    Block 13 (B1): Der Patron soll beim STOPP wissen, worauf er drueckt. Es
    wird NICHTS geschaetzt, was der Anbieter nicht gemeldet hat - "noch nichts
    gemeldet" ist eine ehrlichere Auskunft als eine erfundene Zahl.
    """
    if not start or not auftrag:
        return None
    try:
        from decimal import Decimal
        from datetime import datetime
        import jack_kosten
        beginn = datetime.fromisoformat(str(start))
        if beginn.tzinfo is None:
            beginn = beginn.replace(tzinfo=betrieb.now().tzinfo)
        summe, gefunden = Decimal(0), False
        latest = {r['id']:r for r in jack_kosten.rows(HIER)
                  if r.get('id') and r.get('auftrag') == auftrag}
        for zeile in latest.values():
            try:
                zeit = datetime.fromisoformat(str(zeile.get('zeit') or ''))
                if zeit.tzinfo is None:
                    zeit = zeit.replace(tzinfo=beginn.tzinfo)
                if zeit < beginn or zeile.get('usd_gemeldet') is None:
                    continue
                betrag = Decimal(str(zeile['usd_gemeldet']))
                if not betrag.is_finite() or betrag < 0:
                    continue
                summe += betrag; gefunden = True
            except (ValueError, ArithmeticError):
                continue
        return float(summe) if gefunden else None
    except Exception:
        return None


_BUCH_CACHE = {}


def _buch(datei, pfad, ordner, laeuft=False, wartegrund=None):
    """F-9 (T2): Plan, Zwischenergebnisse, naechster Schritt je Auftrag fuer die Tafel (abgeleitet, mit Cache
    auf Dateistand von Auftrag, Werkzeugprotokoll und Tor-2-Ordner). Fehler -> None, Tafel bleibt lesbar."""
    try:
        import jack_vorgaenge
        sig = []
        for q in (pfad, HIER / "arbeiter_zugriffe.jsonl", HIER / "abnahme" / "tor2",
                  betrieb.area(HIER) / "aussenvorgaenge.jsonl"):
            try:
                st = os.stat(q)
                sig.append((st.st_mtime_ns, st.st_size))
            except OSError:
                sig.append(None)
        schluessel = (str(pfad), ordner, laeuft, json.dumps(wartegrund, sort_keys=True, default=str))
        treffer = _BUCH_CACHE.get(schluessel)
        if treffer and treffer[0] == sig:
            return treffer[1]
        buch = jack_vorgaenge.buch_ableiten(HIER, pfad, ordner=ordner, laeuft=laeuft, wartegrund=wartegrund)
        if len(_BUCH_CACHE) > 200:
            _BUCH_CACHE.clear()
        _BUCH_CACHE[schluessel] = (sig, buch)
        return buch
    except Exception:
        return None


def _buchfelder(buch):
    if not buch:
        return {"plan": None, "zwischenergebnisse": None, "naechster_schritt": None,
                "fortschritt_schritte": None, "aussenvorgaenge": []}
    return {k: buch.get(k) for k in ("plan", "zwischenergebnisse", "naechster_schritt",
                                      "fortschritt_schritte", "aussenvorgaenge", "fortsetzung")}


def fortsetzbar(pfad):
    """(ja/nein, Grund) fuer die Tafel - dieselbe Pruefung wie fortsetzen(), ohne etwas zu schreiben."""
    try:
        text = Path(pfad).read_text(encoding="utf-8")
        grund = jack_auftrag.abbruchgrund(text)
        klasse = jack_auftrag.abbruch_klasse(grund)
        if klasse not in jack_auftrag.FORTSETZBAR:
            return False, klasse, "Abbruchgrund %s ist nicht fortsetzbar" % klasse
        return True, klasse, grund[:200]
    except (OSError, ValueError):
        return False, "unbekannt", "nicht lesbar"


def tafel():
    """Echte Zustaende aus den Betriebsdateien, nie eine geratene Anzeige."""
    z = zustand_lesen()
    grenzen = jack_grenzen.lesen(HIER)
    offen = auftraege("offen")
    erledigt = erledigte_namen()
    ringe = ringschluesse(offen)
    im_ring = {d for r in ringe for d in r}
    jetzt = time.time()

    laufend = []
    for datei, l in sorted(z["laeufe"].items(), key=lambda x: x[1].get("nummer", 0)):
        f = fortschritt_lesen(datei) or {}
        laufend.append({
            "nummer": l.get("nummer"), "datei": datei, "titel": l.get("titel"),
            "marke": l.get("marke"), "bereiche": l.get("bereiche", []),
            "zustand": l.get("zustand", "laeuft"), "test": bool(l.get("test")),
            "laufzeit_s": round(jetzt - l.get("start_epoch", jetzt)),
            "prozent": f.get("prozent"),
            "geplant": f.get("geplant"), "erledigt_teile": f.get("erledigt", 0),
            "schritt": _schrittzeile(f),
            "start": l.get("start", ""),
            "kosten_usd": _kosten_seit(l.get("start"), datei),
            "lebt": lebt(l.get("pid"), datei),
            "qualitaet": jack_auftrag.kurzstand(HIER, AUF / 'laeuft' / datei),
            # Block 33.4: Schwarm-Sicht - Weg/Motor und Stufe je laufendem Auftrag,
            # damit die Tafel zeigt, WOMIT gerade gearbeitet wird, nicht nur WAS.
            "weg": l.get("weg") or l.get("motor"), "motor": l.get("motor"),
            "stufe": l.get("stufe") or "",
            # F-9 (T2): Plan, Zwischenergebnisse, naechster Schritt; Wartegrund nur beim Pausieren
            "wartegrund": (_wartegrund_struktur("Vom Patron pausiert (Sperren bleiben gehalten)",
                                                l.get("pausiert_seit")) if l.get("zustand") == "pausiert" else None),
            **_buchfelder(_buch(datei, AUF / "laeuft" / datei, "laeuft", laeuft=True)),
            "zettel": _zettelstand(datei, "laeuft"),
        })

    # Block 13 (B1): Was in problem/ liegt, wird gezeigt - nicht gestartet.
    probleme = []
    for a in auftraege("problem"):
        ja, klasse, text = fortsetzbar(a["pfad"])
        wg = _wartegrund_struktur("Abbruch (%s) - wartet auf deine Entscheidung: WEITER setzt am letzten sicheren "
                                  "Schritt fort" % klasse if ja else
                                  "Abnahmeproblem oder Versuchsgrenze erreicht - wartet auf deine Entscheidung")
        if wg:
            wg["art"] = "patron"
        probleme.append({"nummer": z["nummern"].get(a["datei"]), "datei": a["datei"],
                         "titel": a["titel"], "marke": a["marke"],
                         "grund": "Abnahmeproblem oder Versuchsgrenze erreicht — wartet auf deine Entscheidung",
                         "versuch": a["versuch"],
                         "abbruch": klasse, "abbruch_text": text, "fortsetzbar": ja, "wartegrund": wg,
                         **_buchfelder(_buch(a["datei"], Path(a["pfad"]), "problem", wartegrund=wg)),
                         "zettel": _zettelstand(a["datei"], "problem", a["pfad"])})

    wartend = []
    for a in sorted(offen, key=lambda x: (DRINGLICH.get(x["dringlichkeit"], 1), x["erteilt"])):
        if a["datei"] in z["laeufe"]:
            continue
        if a["datei"] in im_ring:
            grund = "RINGSCHLUSS - gemeldet, nicht stillschweigend geparkt"
        else:
            fehlt = [h for h in a["haengt_an"] if h not in erledigt]
            schleife = (z.get("schleife") or {}).get(a["datei"]) or {}
            if a.get('qualitaet', {}).get('fehler'):
                grund = a['qualitaet']['text']
            elif schleife.get("angehalten"):
                grund = schleife.get("grund", "PROBLEM Schleifenschutz")
            elif a["versuch"] >= a.get("qualitaet", {}).get("max_versuche", 2):
                grund = "VERSUCHE VERBRAUCHT (%d) - wartet auf Entscheidung des Patrons" % a["versuch"]
            elif fehlt:
                grund = "wartet auf " + ", ".join(fehlt)
            else:
                grund = "wartet auf einen freien Platz"
                if a.get('qualitaet', {}).get('gebunden'):
                    bereit = jack_faehigkeiten.vorpruefung(HIER, a['qualitaet'].get('ablauf', 'arbeit'), motor=a['motor'])
                    if not bereit['ausfuehrbar']:
                        grund = bereit['text']
        # F-9: eine Quelle - der zuletzt im Takt gemerkte Grund hat Vorrang (mit 'seit'), sonst der hier berechnete
        takt_grund = (z.get("wartegruende") or {}).get(a["datei"])
        wg = takt_grund or _wartegrund_struktur(grund)
        wartend.append({"nummer": z["nummern"].get(a["datei"]), "datei": a["datei"],
                        "titel": a["titel"], "marke": a["marke"],
                        "bereiche": a["bereiche"], "dringlichkeit": a["dringlichkeit"],
                        "test": a["test"], "grund": grund, "qualitaet": a.get('qualitaet', {}),
                        "wartegrund": wg,
                        **_buchfelder(_buch(a["datei"], Path(a["pfad"]), "offen", wartegrund=wg)),
                        "zettel": _zettelstand(a["datei"], "offen", a["pfad"])})

    # B1: "ERLEDIGT heute" - was heute fertig wurde, in einer kurzen Liste.
    heute = betrieb.now().date().isoformat()
    erledigt_heute = []
    gestoppt_heute = []
    for p in sorted((AUF / "erledigt").glob("*.md"), reverse=True):
        try:
            if betrieb.now().fromtimestamp(p.stat().st_mtime).date().isoformat() != heute:
                continue
        except Exception:
            continue
        if p.is_symlink():
            continue
        try:
            inhalt = p.read_text(encoding='utf-8')
        except (OSError, UnicodeError):
            continue
        # F-29: der echte Auftragstitel aus dem Kopf, nicht der Dateiname (die Tafel zeigte "2026-09-24 1900 JACK paket6 ...")
        eintrag = {"datei": p.name, "titel": (kopf(inhalt).get("auftrag") or p.stem.replace("_", " "))[:70],
                   'qualitaet': jack_auftrag.kurzstand(HIER, p),
                   "zettel": _zettelstand(p.name, "erledigt", p)}
        if kopf(inhalt).get('status') == 'gestoppt' or re.search(r'^## Vom Patron gestoppt', inhalt, re.M):
            if len(gestoppt_heute) < 12:
                gestoppt_heute.append(eintrag)
        elif p.name in erledigt and len(erledigt_heute) < 12:
            erledigt_heute.append(eintrag)

    return {"zeit": betrieb.now().isoformat(),
            "laufend": laufend, "wartend": wartend,
            "probleme": probleme, "erledigt_heute": erledigt_heute, "gestoppt_heute": gestoppt_heute,
            "sperren": sperren.stand(HIER),
            "budget": jack_grenzen.stand_fuer_tafel(HIER),
            "grenzen": {"gleichzeitig_gesamt": grenzen.get("gleichzeitig_gesamt"),
                        "gleichzeitig_je_art": grenzen.get("gleichzeitig_je_art")},
            "alles_pausiert": bool(z.get("alles_pausiert")),
            "stopp_aktiv": (betrieb.area(HIER) / "STOPP").exists(),
            "schleifenschutz": [{"datei": d, "grund": e.get("grund", ""),
                                 "starts": e.get("starts"),
                                 "seit": e.get("angehalten_seit")}
                                for d, e in (z.get("schleife") or {}).items()
                                if e.get("angehalten")],
            "ringschluesse": ringe,
            "aussenvorgaenge_offen": _aussen_offen()}


def _zettelstand(datei, ordner, pfad=None):
    """F-11 (Paket 4, P07): Zettelstatus je Auftrag fuer die Tafel - Status nach Regel, Zettelart, Pfad."""
    try:
        import jack_abnahmezettel
        return jack_abnahmezettel.fuer_tafel(HIER, datei, ordner, pfad)
    except Exception:
        return None


def _wartegrund_struktur(text, seit=None):
    try:
        import jack_vorgaenge
        return jack_vorgaenge.wartegrund(text, seit=seit, quelle="tafel")
    except Exception:
        return None


def _aussen_offen():
    try:
        import jack_vorgaenge
        return [{"vg": v["vg"], "kanal": v.get("kanal"), "bezug": v.get("bezug"), "auftrag": v.get("auftrag"),
                 "zustand": v["zustand"], "seit": v.get("absicht_zeit"),
                 "wartegrund": jack_vorgaenge.wartegrund(
                     ("Antwort des Anbieters %s ausgeblieben - Zustandspruefung laeuft" if v["zustand"] != "nicht_pruefbar"
                      else "Anbieter %s nicht pruefbar - der Patron klaert") % v.get("kanal"),
                     seit=v.get("absicht_zeit"), worauf=v["vg"])}
                for v in jack_vorgaenge.offene(HIER)]
    except Exception:
        return []


if __name__ == "__main__":
    was = sys.argv[1] if len(sys.argv) > 1 else "takt"
    if was == "takt":
        print(json.dumps(takt(nur_test="--nur-test" in sys.argv), ensure_ascii=False, indent=1))
    elif was == "tafel":
        print(json.dumps(tafel(), ensure_ascii=False, indent=1))
    elif was == "steuern":
        print(json.dumps(steuern(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None,
                                 nur_test="--nur-test" in sys.argv), ensure_ascii=False))
    elif was == "schleife":
        if len(sys.argv) > 2 and sys.argv[2] == "frei" and len(sys.argv) > 3:
            print(json.dumps(schleife_freigeben(sys.argv[3]), ensure_ascii=False))
        else:
            print(json.dumps(schleifen_stand(), ensure_ascii=False, indent=1))
    elif was == "fortsetzen" and len(sys.argv) > 2:
        print(json.dumps(fortsetzen(sys.argv[2]), ensure_ascii=False))
    elif was == "unterbrechen" and len(sys.argv) > 2:
        print(json.dumps(unterbrechen(sys.argv[2], " ".join(sys.argv[3:]) or "Dienst-Neustart"), ensure_ascii=False))
    elif was == "fortschritt":
        print(json.dumps(fortschritt_setzen(sys.argv[2],
              geplant=int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3] != "-" else None,
              erledigt=int(sys.argv[4]) if len(sys.argv) > 4 and sys.argv[4] != "-" else None,
              schritt=sys.argv[5] if len(sys.argv) > 5 else None), ensure_ascii=False))
    else:
        print("takt | tafel | steuern <befehl> [datei] | schleife [frei <datei>] | "
              "fortschritt <datei> <geplant> <erledigt> <schritt>")
