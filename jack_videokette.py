"""Freigabe-Tor und Nachbearbeitung der Videokette (Strang A-6, 24.09.2026).

Jeder Echtaufruf eines Videoauftrags laeuft durch tor(). Reihenfolge:
  1. Auftrag startbereit? Modell aus der Tabelle modelltabelle (videoproduktion.json)
     - Entwurfsregel: erster Echtlauf immer das guenstigste freigegebene Entwurfsmodell,
     Hochqualitaet nur als Folgeauftrag nach Patron-Freigabe.
  2. Kostenschaetzung (Preis/s x Dauer) und Deckelpruefung (Auftrags-, Stunden-, Tagesdeckel
     inkl. offener Reservierungen) - rein lesend.
  3. Steht echtfreigabe_je_auftrag[Kennung] NICHT woertlich auf 'ausloesen': Halt.
     Status 'wartet_auf_freigabe', kein Aufruf, keine Datei, keine Kosten.
  4. Nur mit 'ausloesen': Deckel muss reichen, dann EIN Aufruf ueber den Adapter. In jedem
     Fall (Erfolg, Fehler, Deckel) springt die Freigabe danach auf 'gesperrt' zurueck und
     wird zurueckgelesen.
Setzen kann den Wert nur der Patron/PM (Datei betrieb/videoproduktion.json); dieses Modul
hat bewusst keinen Weg, ihn zu oeffnen.

aktualisieren() holt das Ergebnis und stoesst die Nachbearbeitung an (Loop-Pruefung,
Standbilder, echtes Logo nur ueber jack_medien.logo_einblenden). Tor 1/Tor 2 bleiben
die bestehenden Tore in jack_videoproduktion.tor_pruefen; die E1-Pruefpunkte stehen
in der Konfiguration (freigabe_tor.tor2_pruefpunkte_e1) und werden in die Akte kopiert.
"""
import datetime as dt
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import re
import subprocess

import jack_higgsfield
import jack_kosten
import jack_medien
import jack_runway
import jack_videoproduktion

VERSION = "1.1.0"  # A-7 (24.09.2026): Ergebnisbeleg-Abgleich (Groesse+Hash aus einer Datei)
KENNUNG = re.compile(r"VP-[0-9]{8}-[0-9]{6}-[a-f0-9]{8}")
ANBIETER = ("higgsfield", "runway")
STARTBEREIT = ("briefing", "produktion_bereit")
PROTOKOLL = "betrieb/videokette.jsonl"


def _zahl(wert, name):
    try:
        zahl = Decimal(str(wert))
    except (InvalidOperation, ValueError) as fehler:
        raise ValueError(name + " ist ungueltig") from fehler
    if not zahl.is_finite() or zahl < 0:
        raise ValueError(name + " ist ungueltig")
    return zahl


def _konfig_pfad(root):
    return Path(root) / "betrieb" / "videoproduktion.json"


def _konfiguration(root):
    daten = jack_videoproduktion._laden(root)
    tor = daten.get("freigabe_tor")
    tabelle = (daten.get("modelltabelle") or {}).get("modelle")
    if not isinstance(tor, dict) or not isinstance(tabelle, list) or not tabelle:
        raise ValueError("Freigabe-Tor oder Modelltabelle fehlt in videoproduktion.json")
    return daten, tor, tabelle


def _akte(root, kennung):
    if not isinstance(kennung, str) or not KENNUNG.fullmatch(kennung):
        raise ValueError("Ungueltige Videoauftragskennung")
    pfad = jack_higgsfield._auftragspfad(root, kennung)
    return pfad, jack_higgsfield._lesen(pfad)


def _freigabewert(daten, kennung):
    zuordnung = daten.get("echtfreigabe_je_auftrag")
    return zuordnung.get(kennung) if isinstance(zuordnung, dict) else None


# ---------------------------------------------------------------- Modellwahl

def _startbild(akte):
    blatt = akte.get("figurenblatt")
    pfad = blatt.get("pfad") if isinstance(blatt, dict) else None
    return pfad if isinstance(pfad, str) and pfad else None


def entwurfsmodell(tabelle, anbieter, mit_startbild, mit_endbild):
    """Guenstigstes freigegebenes Entwurfsmodell, das die Anforderung erfuellt."""
    art = "bild_zu_video" if mit_startbild else "text_zu_video"
    zeilen = [z for z in tabelle
              if z.get("anbieter") == anbieter and z.get("freigabe") == "freigegeben"
              and z.get("stufe") == "entwurf" and z.get("art") in (art, "beides")
              and (not mit_endbild or z.get("endbild") is True)]
    if not zeilen:
        raise ValueError("Kein freigegebenes Entwurfsmodell fuer diese Anforderung (%s, %s%s)" % (
            anbieter, art, ", Endbild" if mit_endbild else ""))
    return min(zeilen, key=lambda z: _zahl(z["preis_usd_je_sekunde"], "Preis je Sekunde"))


def _hochqualitaet_frei(akte):
    freigabe = akte.get("hochqualitaet_freigabe")
    return (isinstance(freigabe, dict) and all(isinstance(freigabe.get(f), str) and freigabe[f]
                                               for f in ("patron", "zeit", "folgeauftrag_von"))
            and KENNUNG.fullmatch(freigabe["folgeauftrag_von"]) is not None)


def _modellwahl(tabelle, akte, kennung, anbieter, modell):
    mit_start, mit_end = _startbild(akte) is not None, bool(akte.get("endbild_pfad"))
    if modell is None:
        return entwurfsmodell(tabelle, anbieter, mit_start, mit_end)
    zeile = next((z for z in tabelle if z.get("anbieter") == anbieter and z.get("modell") == modell), None)
    if zeile is None:
        raise ValueError("Modell '%s' steht nicht in der Modelltabelle" % modell)
    if zeile.get("freigabe") != "freigegeben":
        raise ValueError("Modell '%s' ist in der Modelltabelle 'nicht freigegeben'" % modell)
    entwurf = entwurfsmodell(tabelle, anbieter, mit_start, mit_end)
    if zeile.get("stufe") == "hochqualitaet":
        if not _hochqualitaet_frei(akte):
            raise ValueError("Hochqualitaet ('%s') nur als eigener Folgeauftrag nach Patron-Freigabe "
                             "(Feld hochqualitaet_freigabe mit patron, zeit, folgeauftrag_von fehlt)" % modell)
        if akte["hochqualitaet_freigabe"]["folgeauftrag_von"] == kennung:
            raise ValueError("Hochqualitaet braucht einen eigenen Folgeauftrag, nicht denselben Auftrag")
        return zeile
    if zeile["modell"] != entwurf["modell"]:
        raise ValueError("Entwurfsregel: der erste Echtlauf nimmt das guenstigste passende Modell '%s', "
                         "nicht '%s'" % (entwurf["modell"], modell))
    return zeile


def _adapterpreis(daten, anbieter, modell):
    if anbieter == "higgsfield":
        return daten["higgsfield"]["modelle"][modell]["preis_usd_je_sekunde_maximal"], daten["higgsfield"]["max_usd_je_auftrag"]
    return daten["runway"]["modelle"][modell]["usd_je_sekunde"], daten["runway"]["max_usd_je_auftrag"]


# ------------------------------------------------------------ Kosten / Deckel

def _deckelrest(root, kosten):
    """Rein lesend (keine Meldung, keine Reservierung): Rest bis Stunden- und Tagesdeckel."""
    import jack_grenzen
    stand = jack_grenzen.verbrauch(root)
    grenzen = jack_grenzen.lesen(root)
    offen = sum((Decimal(str(o["betrag_usd"])) for o in jack_kosten._offene_reservierungen(root, jack_kosten.b.now())),
                Decimal(0))
    tagesdeckel = jack_grenzen.tagesdeckel(root, grenzen)[2]
    ergebnis, ok = {"offene_reservierungen_usd": str(offen)}, True
    for name, deckel, ist in (("stunde", grenzen.get("budget_usd_je_stunde"), stand.get("stunde_usd", "0")),
                              ("tag", tagesdeckel, stand.get("tag_usd", "0"))):
        if deckel in (None, "", 0):
            ergebnis[name] = {"deckel": None, "rest_usd": None, "reicht": True}
            continue
        rest = Decimal(str(deckel)) - Decimal(str(ist)) - offen
        ergebnis[name] = {"deckel": str(deckel), "verbraucht_usd": str(ist), "rest_usd": str(rest),
                          "reicht": rest >= kosten}
        ok = ok and rest >= kosten
    ergebnis["reicht"] = ok
    return ergebnis


def schaetzung(root, kennung, anbieter="higgsfield", modell=None, dauer=None):
    """Modellwahl nach Regel + Kostenschaetzung + Deckelpruefung. Schreibt nichts."""
    if anbieter not in ANBIETER:
        raise ValueError("Anbieter muss higgsfield oder runway sein")
    daten, _tor, tabelle = _konfiguration(root)
    _pfad, akte = _akte(root, kennung)
    if akte.get("status") not in STARTBEREIT:
        raise ValueError("Videoauftrag ist nicht startbereit (Status: %s)" % akte.get("status"))
    zeile = _modellwahl(tabelle, akte, kennung, anbieter, modell)
    dauer = dauer if dauer is not None else akte.get("dauer_sekunden", 5)
    if type(dauer) is not int or dauer <= 0:
        raise ValueError("Dauer muss eine ganze Sekundenzahl sein")
    preis = _zahl(zeile["preis_usd_je_sekunde"], "Preis je Sekunde")
    adapter_preis, auftragsdeckel = _adapterpreis(daten, anbieter, zeile["modell"])
    if preis != _zahl(adapter_preis, "Adapterpreis"):
        raise ValueError("Preis in modelltabelle (%s) weicht vom Adapter-Eintrag (%s) ab; Tor bleibt zu" % (preis, adapter_preis))
    kosten = preis * dauer
    auftrag_ok = kosten <= _zahl(auftragsdeckel, "Auftragsdeckel")
    deckel = _deckelrest(root, kosten)
    return {"kennung": kennung, "anbieter": anbieter, "modell": zeile["modell"], "stufe": zeile["stufe"],
            "dauer_sekunden": dauer, "preis_usd_je_sekunde": str(preis),
            "kosten_usd_geschaetzt_maximal": str(kosten),
            "auftragsdeckel": {"deckel_usd": str(auftragsdeckel), "reicht": auftrag_ok},
            "stunden_und_tagesdeckel": deckel, "deckel_reicht": bool(auftrag_ok and deckel["reicht"])}


def status(root, kennung):
    """Abgeleiteter Tor-Stand; schreibt nichts."""
    daten, _tor, _t = _konfiguration(root)
    _pfad, akte = _akte(root, kennung)
    wert = _freigabewert(daten, kennung)
    if akte.get("status") in STARTBEREIT:
        zustand = "bereit_zum_aufruf" if wert == "ausloesen" else "wartet_auf_freigabe"
    else:
        zustand = akte.get("status")
    return {"kennung": kennung, "zustand": zustand, "echtfreigabe": wert if wert is not None else "gesperrt (fehlend)"}


# ------------------------------------------------------------- Freigabe-Rueckstellung

def _freigabe_zuruecksetzen(root, kennung):
    """Setzt den Wert auf 'gesperrt' und liest ihn zurueck. Ohne Bestaetigung: laute Ausnahme."""
    pfad = _konfig_pfad(root)
    daten = json.loads(pfad.read_text(encoding="utf-8"))
    ruhewert = (daten.get("freigabe_tor") or {}).get("ruhewert", "gesperrt")
    daten.setdefault("echtfreigabe_je_auftrag", {})[kennung] = ruhewert
    tmp = pfad.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(daten, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, pfad)
    gelesen = json.loads(pfad.read_text(encoding="utf-8"))["echtfreigabe_je_auftrag"].get(kennung)
    if gelesen != ruhewert:
        raise RuntimeError("Freigabe konnte nicht auf '%s' zurueckgesetzt werden (gelesen: %r)" % (ruhewert, gelesen))
    return gelesen


def _protokoll(root, **feld):
    zeile = {"zeit": dt.datetime.now().astimezone().isoformat(), **feld}
    with (Path(root) / PROTOKOLL).open("a", encoding="utf-8") as datei:
        datei.write(json.dumps(zeile, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------- das Tor

def tor(root, kennung, prompt=None, modell=None, dauer=None, anbieter="higgsfield", startbild=None,
        trocken=False):
    """Das Freigabe-Tor. Siehe Modulkopf. trocken=True ruft in keinem Fall an."""
    plan = schaetzung(root, kennung, anbieter, modell, dauer)
    daten, tor_konfig, _t = _konfiguration(root)
    wert = _freigabewert(daten, kennung)
    if wert != tor_konfig.get("freigabewert", "ausloesen") or trocken:
        return {**plan, "status": "wartet_auf_freigabe" if wert != "ausloesen" else "bereit_zum_aufruf",
                "aufruf_ausgefuehrt": False, "kosten_wirkung_usd": 0, "echtfreigabe": wert or "gesperrt",
                "hinweis": ("Kein Anbieteraufruf. Der Patron/PM gibt frei, indem er echtfreigabe_je_auftrag['%s'] "
                            "auf 'ausloesen' setzt; danach genau ein Aufruf, dann automatisch wieder 'gesperrt'." % kennung)
                           if wert != "ausloesen" else "Trockenlauf: Freigabe steht auf 'ausloesen', es wurde nichts aufgerufen."}
    # Ab hier: ausdrueckliche Freigabe fuer GENAU diese Kennung. Sie ist in jedem Fall verbraucht.
    ergebnis, fehler = None, None
    try:
        _protokoll(root, ereignis="freigabe_genutzt", kennung=kennung, anbieter=anbieter, modell=plan["modell"],
                   dauer=plan["dauer_sekunden"], kosten_usd_geschaetzt_maximal=plan["kosten_usd_geschaetzt_maximal"])
        if not plan["deckel_reicht"]:
            raise ValueError("Deckel reicht nicht fuer %s USD (Auftrag/Stunde/Tag); kein Aufruf. "
                             "Freigabe ist verbraucht und muss neu gesetzt werden." % plan["kosten_usd_geschaetzt_maximal"])
        _pfad, akte = _akte(root, kennung)
        text = prompt if prompt is not None else akte.get("prompt")
        bild = startbild if startbild is not None else _startbild(akte)
        if anbieter == "higgsfield":
            ergebnis = jack_higgsfield.starten(root, kennung, text, modell=plan["modell"], dauer=plan["dauer_sekunden"],
                                               referenzbild=bild)
        else:
            ergebnis = jack_runway.starten(root, kennung, text, modell=plan["modell"], dauer=plan["dauer_sekunden"],
                                           startbild=bild)
    except Exception as ausnahme:
        fehler = ausnahme
    finally:
        danach = _freigabe_zuruecksetzen(root, kennung)
        _protokoll(root, ereignis="freigabe_zurueck", kennung=kennung, echtfreigabe=danach,
                   ergebnis="fehler" if fehler is not None else "gestartet")
    if fehler is not None:
        raise fehler
    return {**plan, **ergebnis, "status": "in_produktion", "aufruf_ausgefuehrt": True,
            "echtfreigabe": danach, "hinweis": "Genau ein Aufruf gestartet; Freigabe wieder 'gesperrt'. "
            "Ergebnis mit aktualisieren() holen; danach automatische Nachbearbeitung, dann Tor 1 und Tor 2."}


# ------------------------------------------------------------ Nachbearbeitung

def _ff(name):
    pfad = Path(getattr(jack_medien, name))
    if not pfad.is_file():
        raise ValueError("Lokale Medienbearbeitung ist nicht installiert")
    return str(pfad)


def loop_abstand(video, breite=320, hoehe=180):
    """Mittlere absolute Grauwertabweichung (0-255) zwischen erstem und letztem Frame."""
    env = {"PATH": "/usr/bin:/bin", "LANG": "C"}
    groesse = breite * hoehe

    def frame(letzter):
        vor = ["-sseof", "-0.2"] if letzter else []
        lauf = subprocess.run([_ff("FFMPEG"), "-nostdin", "-v", "error", *vor, "-i", str(video), "-vf",
                               "scale=%d:%d,format=gray" % (breite, hoehe), "-f", "rawvideo", "-"],
                              capture_output=True, timeout=120, env=env)
        if len(lauf.stdout) < groesse:
            raise ValueError("Frame nicht lesbar")
        return lauf.stdout[-groesse:] if letzter else lauf.stdout[:groesse]

    a, b = frame(False), frame(True)
    return sum(abs(x - y) for x, y in zip(a, b)) / float(groesse)


def _standbild(video, sekunde, ziel):
    if ziel.exists():
        return
    lauf = subprocess.run([_ff("FFMPEG"), "-nostdin", "-v", "error", "-ss", "%.2f" % sekunde, "-i", str(video),
                           "-frames:v", "1", str(ziel)], capture_output=True, timeout=120,
                          env={"PATH": "/usr/bin:/bin", "LANG": "C"})
    if lauf.returncode != 0 or not ziel.is_file():
        raise ValueError("Standbild nicht erzeugt")


def ergebnisbeleg_abgleichen(root, kennung):
    """A-7 T5 (24.09.2026): Groesse und Hash des erzeugten Videos kommen aus EINEM Lesevorgang
    derselben Datei (jack_medien.fingerprint) und werden gegen den Eintrag in generationen[].ergebnis
    gehalten. Anlass: VP-20260923-191915-3eea05fe trug bytes 4404019 (= 4,2 MiB aus 'ls -h', von Hand
    uebertragen), die Datei hat 4354564 Bytes; der Hash stimmte. Regeln:
      - Hash gleich, Groesse falsch: die Datei IST die gehashte - Groesse wird aus der Datei gesetzt,
        der alte Wert bleibt mit Vermerk in ergebnis.bytes_vorher stehen.
      - Hash verschieden: die Datei ist nicht die belegte - nichts wird ueberschrieben, laute Ausnahme.
    Liefert den Abgleich; schreibt nur im ersten Fall."""
    pfad, akte = _akte(root, kennung)
    relativ = akte.get("erzeugtes_video")
    lauf = next((g for g in reversed(akte.get("generationen") or [])
                 if isinstance(g, dict) and isinstance(g.get("ergebnis"), dict)
                 and g["ergebnis"].get("pfad") == relativ), None)
    if not isinstance(relativ, str) or lauf is None:
        return {"kennung": kennung, "abgleich": "kein Ergebnisbeleg zum erzeugten Video"}
    video = jack_videoproduktion._vault(root) / relativ
    datei = jack_medien.fingerprint(video)
    beleg = lauf["ergebnis"]
    if beleg.get("sha256") != datei["sha256"]:
        raise ValueError("Erzeugtes Video %s passt nicht zum Hash im Ergebnisbeleg; nichts geaendert" % relativ)
    if beleg.get("bytes") == datei["bytes"]:
        return {"kennung": kennung, "abgleich": "stimmt", **datei}
    with jack_higgsfield._sperre(pfad):
        neu = jack_higgsfield._lesen(pfad)
        ziel = next(g for g in reversed(neu["generationen"])
                    if isinstance(g, dict) and isinstance(g.get("ergebnis"), dict) and g["ergebnis"].get("pfad") == relativ)
        ziel["ergebnis"]["bytes_vorher"] = ziel["ergebnis"].get("bytes")
        ziel["ergebnis"]["bytes"] = datei["bytes"]
        ziel["ergebnis"]["beleg_quelle"] = ("jack_medien.fingerprint: Groesse und SHA-256 aus einem Lesevorgang, "
                                            "korrigiert %s (A-7)" % dt.datetime.now().astimezone().isoformat())
        jack_higgsfield._schreiben(pfad, neu)
    return {"kennung": kennung, "abgleich": "groesse_korrigiert", "bytes_vorher": beleg.get("bytes"), **datei}


def nachbearbeiten(root, kennung):
    """Loop-Pruefung, Standbilder, Logo (nur echte Marken-Wort-Bild-Marke, nur hier eingefuegt)."""
    daten, tor_konfig, _t = _konfiguration(root)
    einstellung = tor_konfig.get("nachbearbeitung") or {}
    pfad, akte = _akte(root, kennung)
    relativ = akte.get("erzeugtes_video")
    if akte.get("status") != "qualitaetspruefung" or not isinstance(relativ, str):
        raise ValueError("Nachbearbeitung erst mit erzeugtem Video im Status 'qualitaetspruefung'")
    vault = jack_videoproduktion._vault(root)
    video = vault / relativ
    ordner = video.parent
    ergebnis = {"schema": 1, "zeit": dt.datetime.now().astimezone().isoformat(),
                "ergebnisbeleg": ergebnisbeleg_abgleichen(root, kennung)}
    if einstellung.get("loop_pruefung", True):
        schwelle = float(einstellung.get("loop_schwelle", 2.0))
        abstand = round(loop_abstand(video), 3)
        ergebnis["loop"] = {"bildabstand_mittel_0_255": abstand, "schwelle": schwelle, "nahtlos": abstand < schwelle}
    if einstellung.get("logo_einblenden", True):
        logo = ((daten.get("ci_pflicht") or {}).get("marken_logo_pfade") or {}).get(akte.get("marke"), {})
        wbm = logo.get("wort_bild_marke") if isinstance(logo, dict) else None
        if not isinstance(wbm, dict) or wbm.get("status") != "gefunden" or not wbm.get("pfad"):
            raise ValueError("Keine geprueftes echtes Logo (Wort-Bild-Marke) fuer diese Marke; kein Logo erfunden")
        ziel = video.with_name(video.stem + "_final" + video.suffix)
        if ziel.exists():
            ergebnis["logo"] = {"ergebnis": str(ziel.relative_to(vault)), "hinweis": "war bereits vorhanden"}
        else:
            # F-27: Fassung nach Helligkeit der Logo-Ecke (heller/dunkler Grund), sonst wie bisher wbm["pfad"]
            fassungen = {k: wbm.get("pfad_" + k) for k in ("heller_grund", "dunkler_grund") if wbm.get("pfad_" + k)}
            beleg = jack_medien.logo_einblenden(root, relativ, wbm["pfad"], str(ziel.relative_to(vault)),
                                                fassungen=fassungen or None)
            ergebnis["logo"] = {"ergebnis": beleg["ergebnis"], "logo": beleg["logo"], "parameter": beleg["parameter"],
                                "fassung": beleg.get("fassung")}
        final = ziel
        ergebnis["standbilder"] = []
        dauer = float(akte.get("dauer_sekunden") or 8)
        for name, sekunde in (("standbild_00s.png", 0.0), ("standbild_mitte.png", dauer / 2.0),
                              ("standbild_ende.png", max(0.0, dauer - 0.1))):
            _standbild(final, sekunde, ordner / name)
            ergebnis["standbilder"].append(str((ordner / name).relative_to(vault)))
    ergebnis["tor2_pruefpunkte_e1"] = list(tor_konfig.get("tor2_pruefpunkte_e1") or [])
    with jack_higgsfield._sperre(pfad):
        neu = jack_higgsfield._lesen(pfad)
        neu["nachbearbeitung"] = ergebnis
        jack_higgsfield._schreiben(pfad, neu)
    return ergebnis


def aktualisieren(root, kennung, anbieter="higgsfield"):
    """Holt das Ergebnis; bei fertigem Video automatisch Nachbearbeitung. Kein Aufruf, der Geld kostet."""
    if anbieter not in ANBIETER:
        raise ValueError("Anbieter muss higgsfield oder runway sein")
    modul = jack_higgsfield if anbieter == "higgsfield" else jack_runway
    ergebnis = modul.aktualisieren(root, kennung)
    if ergebnis.get("status") == "qualitaetspruefung" and ergebnis.get("video"):
        try:
            ergebnis["nachbearbeitung"] = nachbearbeiten(root, kennung)
        except (ValueError, OSError, subprocess.SubprocessError) as fehler:
            ergebnis["nachbearbeitung_fehler"] = str(fehler)[:300]
    return ergebnis
