# -*- coding: utf-8 -*-
"""S-8 (25.09.2026): JACK als Auftraggeber, Teil sprache.
Modus 'Auftrag entwickeln' -> Zusammenfassung (<= 6 Saetze + 'Freigeben?') -> Freigabe ja/aendere/nein
-> JSON nach betrieb/auftrag_entwurf/<zeit>.json (Schema 1, README_AUFTRAG_ENTWURF.md; F-44 jack_auftragsschreiber.py liest).

Regeln:
- Freigabe NUR durch ein ganzes, eindeutiges 'ja' des Patrons auf die Zusammenfassung (lokale Muster, kein Modell); alles Unklare fragt erneut.
- Die vorgelesene Zusammenfassung wird LOKAL aus den Feldern gebaut (immer <= 6 Saetze, keine Liste); das Modell liefert nur die Felder.
- Zahlung/Unterschrift gehoert nie in einen Auftrag: jeder Entwurf traegt den Ausschluss 'Keine Zahlung und keine Unterschrift ohne Freigabe des Patrons.'
- Nichts wird geloescht; verworfene Gespraeche stehen in betrieb/auftrag_gespraech_verworfen.jsonl.
"""
import datetime as dt
import json
import os
import re
import threading
from pathlib import Path

ZUSTAND = "betrieb/auftrag_gespraech.json"
VERWORFEN = "betrieb/auftrag_gespraech_verworfen.jsonl"
ENTWURF = "betrieb/auftrag_entwurf"
STALE_S = 4 * 3600            # ein liegengebliebenes Gespraech endet nach 4 Stunden ohne Antwort
SPERRE = threading.RLock()
KEIN_GELD = "Keine Zahlung und keine Unterschrift ohne Freigabe des Patrons."

START = re.compile(
    r"(?:ich h(?:ä|ae)tte da (?:was|etwas|noch was)|ich habe da (?:was|etwas|eine idee)|gib (?:mal )?einen auftrag|"
    r"gib (?:mal )?(?:den |einen )?auftrag|erteile? (?:mal )?einen auftrag|k(?:ü|ue)mmere dich (?:mal )?um|kümmer dich (?:mal )?um|"
    r"ich will (?:mal )?einen auftrag (?:entwickeln|besprechen)|neuer auftrag|f(?:ü|ue)r [\wäöüß.-]+ h(?:ä|ae)tte ich (?:da )?(?:was|etwas|eine idee)|"
    r"lass uns (?:einen )?auftrag (?:entwickeln|besprechen|durchgehen))", re.I)
ZUSAMMEN = re.compile(
    r"(?:fassen wir (?:das )?zusammen|fass (?:das )?(?:mal )?zusammen|mach (?:mal )?(?:eine|die) zusammenfassung|zusammenfassung(?: bitte)?|"
    r"das war(?:'s|s| es)(?: dann| so)?|mehr (?:ist es )?nicht|sonst nichts|nichts mehr|das ist alles|das w(?:ä|ae)r(?:'s|s| es)(?: dann| so)?|"
    r"das reicht(?: so)?|gehen wir es durch)", re.I)
ABBRUCH = re.compile(r"(?:vergiss den auftrag|lass den auftrag|auftrag abbrechen|abbrechen|doch nicht|vergiss es|lassen wir das)", re.I)
JA = re.compile(r"(?:jack[, ]+)?(?:ja|jawohl|ja bitte|ja,? bitte|ja,? freigegeben|ja,? gib (?:ihn|es|den auftrag) frei|ja,? mach (?:das|es)(?: so)?|freigegeben|"
                r"ja,? passt|passt,? freigegeben|ja,? so (?:machen|passt)|ja,? genau so|so (?:ist es )?freigegeben)[.! ]*", re.I)
NEIN = re.compile(r"(?:jack[, ]+)?(?:nein|nee|nö|noe|nicht freigeben|nein,? (?:danke|lass (?:es|das))|lass (?:es|das) (?:bleiben|sein)|verwirf(?:e)?(?: (?:ihn|es|das|den auftrag))?|"
                  r"abbrechen|vergiss (?:es|den auftrag))[.! ]*", re.I)
AENDERN = re.compile(r"(?:jack[, ]+)?(?:(?:ä|ae)nder(?:e|n)?|nimm|nimm noch|streich(?:e)?|f(?:ü|ue)ge?|erg(?:ä|ae)nze|mach (?:das )?(?:lieber|anders)|statt|aber|noch|zus(?:ä|ae)tzlich|au(?:ß|ss)erdem|"
                     r"der kostenrahmen|das budget|nicht f(?:ü|ue)r|nur f(?:ü|ue)r)\b", re.I)


def _p(root, name):
    """Pfade unter betrieb/ laufen ueber jack_betrieb.area(): unter der Test-Umleitung (JACK_BETRIEB_DIR) liegt alles in einem Wegwerf-Ordner (S-9)."""
    import jack_betrieb
    teile = Path(name).parts
    return jack_betrieb.area(root).joinpath(*teile[1:]) if teile[0] == "betrieb" else Path(root) / name


def _jetzt():
    return dt.datetime.now().astimezone()


def zustand(root):
    try:
        z = json.loads(_p(root, ZUSTAND).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"modus": "aus"}
    try:
        alt = (_jetzt() - dt.datetime.fromisoformat(z.get("zeit"))).total_seconds()
    except (TypeError, ValueError):
        alt = 0
    if z.get("modus") in ("sammeln", "freigabe") and alt > STALE_S:
        _verwerfen(root, z, "abgelaufen (4 Stunden ohne Antwort)")
        return {"modus": "aus"}
    return z if isinstance(z, dict) and z.get("modus") in ("sammeln", "freigabe") else {"modus": "aus"}


def _speichern(root, z):
    z = dict(z, zeit=_jetzt().isoformat())
    ziel = _p(root, ZUSTAND)
    ziel.parent.mkdir(exist_ok=True)
    tmp = ziel.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(z, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(str(tmp), str(ziel))


def _verwerfen(root, z, grund):
    p = _p(root, VERWORFEN)
    p.parent.mkdir(exist_ok=True)
    with open(str(p), "a", encoding="utf-8") as f:
        f.write(json.dumps({"zeit": _jetzt().isoformat(), "grund": grund, "punkte": z.get("punkte", []), "entwurf": z.get("entwurf")}, ensure_ascii=False) + "\n")
    _speichern(root, {"modus": "aus"})


def aktiv(root):
    return zustand(root).get("modus") in ("sammeln", "freigabe")


# ------------------------------------------------------------------ Systemblock fuer den Sammelmodus
SAMMEL_BLOCK = """
Auftragsmodus (nur in diesem Gespräch): Der Patron entwickelt gerade einen Auftrag mit dir. Du sammelst mit, du gibst ihn nicht selbst frei.
Frage gezielt nach, was noch fehlt: Ziel, Umfang, was ausdrücklich nicht getan wird, Kostenrahmen, Marke oder Kanal. Höchstens eine Frage je Antwort.
Bring je Runde höchstens eine eigene Idee und ein Bedenken ein, jeweils mit einem Satz. Wiederhole nicht, was er gesagt hat, und fasse nicht selbst zusammen.
Hat er drei oder mehr Punkte genannt und es kommt nichts Neues, biete einmal an: „Sollen wir zusammenfassen?“.
Sprich nie von Rahmenfeldern, Tiefe, Formularen oder Kanälen, sondern in normalen Worten. Du legst hier nichts an, erteilst keinen Auftrag und rufst kein Werkzeug dafür auf; die Freigabe kommt erst nach der Zusammenfassung von ihm.
""".strip()


def sammel_block(root):
    return SAMMEL_BLOCK if zustand(root).get("modus") == "sammeln" else ""


# ------------------------------------------------------------------ Felder aus dem Gespraech
FELDER_ANWEISUNG = """
Du bekommst die Aussagen des Patrons zu einem neuen Auftrag (und ggf. einen bisherigen Entwurf mit einer Änderung).
Antworte AUSSCHLIESSLICH mit einem JSON-Objekt, ohne Text davor oder danach, mit diesen Feldern:
"titel": kurzer Titel (max. 8 Wörter), "ziel": ein bis zwei Sätze, "punkte": Liste von Aufgaben (je ein prüfbarer kurzer Satz, 1 bis 6),
"ausschluesse": Liste (was ausdrücklich nicht getan wird; leer, wenn er nichts nannte), "kostenrahmen_usd": Zahl oder null (nur wenn er einen Betrag nannte),
"marke": Markenname in Großbuchstaben mit Unterstrich (z. B. CASHFLOW_KOMPASS, PATRONOS, JACK) oder null, "kanal": null (rate keinen Kanal),
"rueckmeldung": ein kurzer Satz, was er als Ergebnis erwartet (oder null).
Erfinde nichts: nur was der Patron gesagt hat oder ausdrücklich zugestimmt hat. Fehlendes bleibt leer oder null.
Zahlungen, Überweisungen und Unterschriften gehören nie in "punkte".
""".strip()


def _json_aus(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise ValueError("kein JSON")
    return json.loads(m.group(0))


def _liste(v, maximal=6):
    if not isinstance(v, list):
        return []
    return [re.sub(r"\s+", " ", str(x)).strip()[:240] for x in v if str(x).strip()][:maximal]


def felder_bereinigen(roh):
    """Modellantwort -> saubere Felder. Wirft ValueError ohne Titel, Ziel oder Punkte."""
    if not isinstance(roh, dict):
        raise ValueError("kein Objekt")
    titel = re.sub(r"\s+", " ", str(roh.get("titel") or "")).strip()[:80]
    ziel = re.sub(r"\s+", " ", str(roh.get("ziel") or "")).strip()[:400]
    punkte = _liste(roh.get("punkte"))
    if not (titel and ziel and punkte):
        raise ValueError("Titel, Ziel und mindestens ein Punkt fehlen")
    ausschluesse = _liste(roh.get("ausschluesse"))
    if KEIN_GELD not in ausschluesse:
        ausschluesse.append(KEIN_GELD)
    kosten = roh.get("kostenrahmen_usd")
    try:
        kosten = None if kosten in (None, "", "null") else round(float(str(kosten).replace(",", ".")), 2)
        if kosten is not None and (kosten < 0 or kosten > 10000):
            kosten = None
    except ValueError:
        kosten = None
    marke = roh.get("marke")
    marke = re.sub(r"[^A-Z0-9_]", "", str(marke).upper().replace(" ", "_").replace("-", "_"))[:40] if marke else None
    rueck = re.sub(r"\s+", " ", str(roh.get("rueckmeldung") or "")).strip()[:200] or None
    return {"titel": titel, "ziel": ziel, "punkte": punkte, "ausschluesse": ausschluesse, "kostenrahmen_usd": kosten, "marke": marke or None,
            "rueckmeldung": rueck}


# ------------------------------------------------------------------ Zusammenfassung (lokal gebaut, <= 6 Saetze)
def _satz(t):
    t = re.sub(r"\s+", " ", str(t)).strip()
    return t if t.endswith((".", "!", "?")) else t + "."


def _ein(t):
    """Ein Text ohne innere Satzenden (sonst waeren es mehr als ein Satz)."""
    t = re.sub(r"\s+", " ", str(t)).strip()
    t = re.sub(r"\s*[.!?]+\s+([A-ZÄÖÜ])([a-zäöüß])", lambda m: "; " + m.group(1).lower() + m.group(2), t)     # 'Er dient' -> '; er dient'
    return re.sub(r"\s*[.!?]+\s+", "; ", t).rstrip(".!?; ")


def _und(liste):
    liste = [_ein(x) for x in liste]
    return liste[0] if len(liste) == 1 else ", ".join(liste[:-1]) + " und " + liste[-1]


def _kosten_text(k):
    if k is None:
        return "Kostenrahmen: nur lokale Arbeit, 0 Dollar."
    zahl = ("%.2f" % k).replace(".", ",").replace(",00", "")
    return "Kostenrahmen: höchstens %s Dollar." % zahl


def zusammenfassung(e):
    """Vorlesetext: Ziel, was gemacht wird, was nicht, Kostenrahmen, Marke/Kanal, Rueckmeldung + 'Freigeben?'. Nie mehr als 6 Saetze im Text vor der Frage."""
    ausschl = [a for a in e.get("ausschluesse", []) if a != KEIN_GELD]
    saetze = [_satz("Ziel: " + _ein(e["ziel"])), _satz("Gemacht wird: " + _und(e["punkte"]))]
    saetze.append(_satz("Nicht gemacht wird: " + _und(ausschl + ["Zahlungen und Unterschriften"])) )
    saetze.append(_kosten_text(e.get("kostenrahmen_usd")))
    saetze.append(_satz("Marke: " + _ein(e["marke"].replace("_", " "))) if e.get("marke") else "Marke: keine genannt, der Kanal richtet sich nach dem Thema.")
    if e.get("rueckmeldung"):
        saetze.append(_satz("Rückmeldung: " + _ein(e["rueckmeldung"])))
    return " ".join(saetze[:6]) + " Freigeben?"


def _saetze_zaehlen(text):
    return len([s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s])


# ------------------------------------------------------------------ Modellaufruf (einspritzbar)
def _marken(root):
    try:
        import jack_auftragsschreiber as sch
        return sorted((sch.konfiguration(root).get("marke_zu_kanal") or {}))
    except Exception:
        return []


def _marke_passend(marke, marken):
    """Modell-Marke -> genau ein Schluessel aus marke_zu_kanal (sonst None; nie raten bei Mehrdeutigkeit)."""
    if not marke or not marken:
        return marke
    if marke in marken:
        return marke
    treffer = [m for m in marken if m.startswith(marke + "_") or marke.startswith(m + "_")]
    return treffer[0] if len(treffer) == 1 else None


def _modell_felder(modell, punkte, entwurf=None, aenderung=None, marken=()):
    """modell(system:str, nachricht:str) -> Text. Zwei Versuche, dann ValueError."""
    if entwurf is not None:
        nachricht = "Bisheriger Entwurf:\n%s\n\nÄnderung des Patrons: %s\n\nGib den geänderten Entwurf vollständig als JSON aus." % (json.dumps(entwurf, ensure_ascii=False), aenderung)
    else:
        nachricht = "Aussagen des Patrons, der Reihe nach:\n" + "\n".join("- " + p for p in punkte)
    letzter = None
    for _ in range(2):
        try:
            f = felder_bereinigen(_json_aus(modell(FELDER_ANWEISUNG + ("\nFür \"marke\" nimm genau einen dieser Namen oder null: " + ", ".join(marken) if marken else ""), nachricht)))
            f["marke"] = _marke_passend(f.get("marke"), list(marken))
            return f
        except (ValueError, TypeError) as fehler:
            letzter = fehler
    raise ValueError(str(letzter))


# ------------------------------------------------------------------ Schreiben
QUELLEN = ("stimme", "text")


def _umgeleitet(root):
    """True, wenn die Betriebsablage dieser Wurzel unter der Test-Umleitung in einem Wegwerf-Ordner liegt."""
    d, f = os.environ.get("JACK_BETRIEB_DIR"), os.environ.get("JACK_BETRIEB_FUER")
    return bool(d and f and Path(root).resolve() == Path(f).resolve())


def sitzung_echt(sitzung):
    """Nur eine echte Sitzung (Stimme/Text des Patrons, nicht Probe/Test) darf freigeben (S-9)."""
    return (isinstance(sitzung, dict) and sitzung.get("quelle") in QUELLEN and str(sitzung.get("gespraech_id") or "").strip() != ""
            and str(sitzung.get("herkunft") or "").lower() not in ("probe", "test"))


def entwurf_schreiben(root, e, freigabe_satz, gespraech_zeit=None, sitzung=None, probe=None):
    """Freigegebene Felder -> betrieb/auftrag_entwurf/<zeit>.json (erst .tmp, dann Umbenennen). -> Pfad.
    S-9: ohne echte `sitzung` wird nichts geschrieben (ValueError); unter der Test-Umleitung oder bei Probe/Test steht `probe: true` und die Datei
    liegt in auftrag_entwurf/probe/ - nie dort, wo F-44 sie zu einem Auftrag macht."""
    if not sitzung_echt(sitzung):
        raise ValueError("keine echte Sitzung - kein Entwurf")
    jetzt = _jetzt()
    if probe is None:
        probe = _umgeleitet(root) or str(sitzung.get("herkunft") or "").lower() in ("probe", "test")
    obj = {"schema": 1, "freigegeben": True, "freigabe_zeit": jetzt.isoformat(timespec="seconds"), "freigabe_satz": str(freigabe_satz)[:300],
           "gespraech_zeit": gespraech_zeit or jetzt.isoformat(timespec="seconds"), "titel": e["titel"], "ziel": e["ziel"], "punkte": e["punkte"],
           "ausschluesse": e["ausschluesse"], "sitzung": {"quelle": sitzung["quelle"], "zeit": jetzt.isoformat(timespec="seconds"), "gespraech_id": str(sitzung["gespraech_id"])},
           "ausgangslage": "Gesprächsentwurf des Patrons mit JACK (S-8); Aussagen wörtlich in den Punkten, Annahmen keine."}
    if e.get("kostenrahmen_usd") is not None:
        obj["kostenrahmen_usd"] = e["kostenrahmen_usd"]
    if e.get("marke"):
        obj["marke"] = e["marke"]
    if e.get("rueckmeldung"):
        obj["ausgangslage"] += " Erwartete Rückmeldung: " + e["rueckmeldung"]
    ordner = _p(root, ENTWURF)
    if probe:
        obj["probe"] = True
        ordner = ordner / "probe"
    ordner.mkdir(parents=True, exist_ok=True)
    name = jetzt.strftime("%Y-%m-%d_%H%M%S")
    ziel = ordner / (name + ".json")
    n = 1
    while ziel.exists() or (ordner / "verarbeitet" / ziel.name).exists() or (ordner / "abgelehnt" / ziel.name).exists():
        n += 1
        ziel = ordner / ("%s_%d.json" % (name, n))
    tmp = ziel.with_name(ziel.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(str(tmp), str(ziel))
    return ziel


def _kanal_vorschau(root, obj):
    """Nur Vorschau (schreibt nichts)."""
    try:
        import jack_auftragsschreiber as s
        kanal, _grund = s.kanal_waehlen(obj, s.konfiguration(root))
        return kanal
    except Exception:
        return None


# ------------------------------------------------------------------ Hauptweg
def verarbeite(root, frage, modell, sitzung=None):
    """Vor dem normalen Dialog aufrufen. -> None (normaler Weg; im Sammelmodus mit sammel_block) oder {'antwort', 'notiz'}.
    modell(system, nachricht) -> Text (Sonnet, ohne Werkzeuge); in Tests eine Attrappe."""
    t = re.sub(r"\s+", " ", frage or "").strip()
    with SPERRE:
        z = zustand(root)
        modus = z.get("modus", "aus")
        if modus == "aus":
            if not START.search(t):
                return None
            _speichern(root, {"modus": "sammeln", "punkte": [t], "start": _jetzt().isoformat(timespec="seconds")})
            return None                       # die erste Aeusserung geht in den normalen Dialog (mit Sammelblock)
        if modus == "sammeln":
            if ABBRUCH.search(t) and len(t.split()) <= 6:
                _verwerfen(root, z, "Patron hat abgebrochen")
                return {"antwort": "Alles klar, ich lasse den Auftrag fallen. Das Gespräch bleibt im Verlauf.", "notiz": "Auftragsmodus beendet (verworfen)"}
            if ZUSAMMEN.search(t) and len(t.split()) <= 8:
                return _zusammenfassen(root, z, modell)
            z["punkte"] = (z.get("punkte") or []) + [t]
            _speichern(root, z)
            return None
        # modus == "freigabe"
        if JA.fullmatch(t):
            e = z["entwurf"]
            if not sitzung_echt(sitzung):
                return {"antwort": "Ohne echte Sitzung gebe ich nichts frei.", "notiz": "Freigabe abgelehnt: keine echte Sitzung", "fehler": True, "lokal": True}
            kanal = _kanal_vorschau(root, dict(e, titel=e["titel"], punkte=e["punkte"]))
            wohin = " an den Kanal %s" % kanal if kanal else ""

            def schreiben():
                """Vom Server NACH dem Gespraechsprotokoll gerufen (das Protokoll traegt dieselbe gespraech_id)."""
                with SPERRE:
                    pfad = entwurf_schreiben(root, e, t, z.get("start"), sitzung)
                    _speichern(root, {"modus": "aus", "letzter_entwurf": pfad.name})
                    return pfad
            return {"antwort": "Freigegeben. Der Auftrag ist unterwegs%s. Die Kennung vergibt der Auftragsschreiber, das Ergebnis melde ich dir in zwei Sätzen." % wohin,
                    "notiz": "Auftragsentwurf freigegeben" + (" · Kanal " + kanal if kanal else ""), "schreiben": schreiben}
        if NEIN.fullmatch(t):
            _verwerfen(root, z, "Patron hat nicht freigegeben")
            return {"antwort": "Verworfen. Es geht nichts raus, das Gespräch bleibt im Verlauf.", "notiz": "Auftragsentwurf verworfen"}
        if AENDERN.match(t) or re.match(r"(?:jack[, ]+)?ja,?\s+aber\b", t, re.I):
            try:
                e = _modell_felder(modell, [], z["entwurf"], t, _marken(root))
            except (ValueError, OSError):
                return {"antwort": "Die Änderung habe ich nicht sauber übernehmen können. Sag sie bitte noch einmal in einem Satz.", "notiz": "Änderung nicht übernommen", "fehler": True}
            z.update(entwurf=e, punkte=(z.get("punkte") or []) + ["Änderung: " + t])
            _speichern(root, z)
            return {"antwort": zusammenfassung(e), "notiz": "Auftrag neu zusammengefasst (Änderung)", "lokal": True}
        return {"antwort": "Freigeben? Sag ja, nein oder was ich ändern soll.", "notiz": "Freigabe unklar, erneut gefragt", "lokal": True}


def _zusammenfassen(root, z, modell):
    try:
        e = _modell_felder(modell, z.get("punkte") or [], marken=_marken(root))
    except (ValueError, OSError):
        return {"antwort": "Dafür habe ich noch zu wenig. Sag mir Ziel und was gemacht werden soll, dann fasse ich zusammen.", "notiz": "Zusammenfassung nicht möglich", "fehler": True}
    z.update(modus="freigabe", entwurf=e)
    _speichern(root, z)
    text = zusammenfassung(e)
    return {"antwort": text, "notiz": "Auftrag zusammengefasst, wartet auf Freigabe", "lokal": True}


# ------------------------------------------------------------------ Rueckmeldung (F-44)
def rueckmeldung(root, frage):
    """'Was ist aus dem Auftrag geworden?' / 'Stand von F-45' -> zwei Saetze aus jack_auftragsschreiber.rueckmeldung, sonst None."""
    t = (frage or "").strip()
    m = re.search(r"\b([A-Z]{1,3}-\d{1,4})\b", t)
    if not re.search(r"(?:ergebnis|stand|geworden|was ist mit|wie weit)", t, re.I) or not re.search(r"auftrag|\b[A-Z]{1,3}-\d{1,4}\b", t, re.I):
        return None
    try:
        import jack_auftragsschreiber as s
        kennung = m.group(1) if m else None
        if not kennung:
            erg = sorted((_p(root, ENTWURF) / "verarbeitet").glob("*.ergebnis.json"))
            if not erg:
                return None
            kennung = json.loads(erg[-1].read_text(encoding="utf-8")).get("kennung")
        r = s.rueckmeldung(root, kennung)
        if not r.get("gefunden"):
            return {"antwort": "Zu %s liegt noch keine Meldung vor." % kennung, "notiz": "Rückmeldung F-44: keine Meldung"}
        return {"antwort": r["text"], "notiz": "Rückmeldung F-44 " + kennung}
    except Exception:
        return None
