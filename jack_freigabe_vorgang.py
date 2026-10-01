"""F-98 (30.09.2026): Verbundene Freigaben. Mehrere Karten, die dieselbe Sache betreffen, tragen im Kopf `vorgang: <name>`.
Genau EINE ist die fuehrende (`fuehrend: ja`, art entscheidung): sie stellt die Optionen gegenueber, empfiehlt und entscheidet.
Die uebrigen erscheinen nicht einzeln, sondern als Unterpunkte. Mit der Wahl einer Option gilt:
  * Karten der NICHT gewaehlten Optionen -> auftraege/freigabe/ersetzt/ (mit Vermerk, nichts geloescht; ihr Entwurf wird gesperrt),
  * Karten der gewaehlten Option bleiben (Mail/Termin laufen wie F-79/F-82 weiter: TESTVERSAND -> Code -> FREIGEBEN),
  * die Entwuerfe `option_<X>_dann` werden zu Karten (mailantwort, z. B. Absage an die Gegenseite) - GESENDET WIRD NICHTS.
Kopfzeilen der fuehrenden Karte (Schluessel klein geschrieben, wie im ganzen Haus gelesen):
  optionen: A, B
  option_a_titel: Kurzname            option_a_karten: <Kartendatei>, ...   option_a_dann: <Entwurfsdatei in betrieb/entwuerfe>, ...
"""
import re
from pathlib import Path

import jack_betrieb as b


def _oberflaeche():
    import jack_oberflaeche
    return jack_oberflaeche


def _liste(wert):
    return [x.strip() for x in re.split(r"[,;]", str(wert or "")) if x.strip()]


def _karten(root):
    o = _oberflaeche()
    return {f.name: (f, k, t) for f, k, t in o._auftragsdateien(root, "freigabe")}


def optionen(kopf, karten=None):
    """-> [{key, titel, karten:[datei], dann:[entwurf]}] oder [].
    F-99: Mit `karten` (Ergebnis von _karten) zaehlen auch Karten desselben Vorgangs zur Option, die im Kopf
    `gilt_bei_option: <A|B>` tragen (z. B. eine spaeter erzeugte Terminkarte)."""
    raus = []
    vg = kopf.get("vorgang", "").strip()
    for key in _liste(kopf.get("optionen")):
        k = key.lower()
        liste = _liste(kopf.get("option_%s_karten" % k))
        if karten and vg:
            for name, (_, kk, _t) in karten.items():
                if (kk.get("vorgang", "").strip() == vg and kk.get("gilt_bei_option", "").strip().lower() == k
                        and name not in liste):
                    liste.append(name)
        raus.append({"key": key.upper(), "titel": kopf.get("option_%s_titel" % k, "Option " + key.upper()),
                     "karten": liste, "dann": _liste(kopf.get("option_%s_dann" % k))})
    return raus


def _titel(kopf, datei):
    return (kopf.get("titel") or kopf.get("betreff") or kopf.get("auftrag") or Path(datei).stem).replace("_", " ")


def _entwurf_kopf(root, name):
    p = b.area(root) / "entwuerfe" / name
    kopf = {}
    try:
        for z in p.read_text(encoding="utf-8").splitlines()[1:]:
            if z.strip() == "---":
                break
            k, _, w = z.partition(":")
            kopf[k.strip().lower()] = w.strip()
    except OSError:
        pass
    return kopf


def gruppen(root):
    """-> {vorgang: {"fuehrend": datei|None, "mitglieder": [datei...]}} fuer alle Vorgaenge mit mindestens 2 Karten."""
    g = {}
    for name, (f, kopf, text) in _karten(root).items():
        v = kopf.get("vorgang", "").strip()
        if not v:
            continue
        e = g.setdefault(v, {"fuehrend": None, "mitglieder": []})
        if kopf.get("fuehrend", "").strip().lower() == "ja":
            e["fuehrend"] = name
        else:
            e["mitglieder"].append(name)
    return {v: e for v, e in g.items() if e["fuehrend"] and (e["mitglieder"] or True)}


def wirkung(root, fuehrend, option):
    """Was passiert bei Wahl `option`? -> {"erledigt":[Titel], "bleibt":[Titel], "neu":[Titel]} (fuer die Hinweiszeile)."""
    karten = _karten(root)
    if fuehrend not in karten:
        raise ValueError("Fuehrende Karte nicht gefunden")
    _, kopf, _ = karten[fuehrend]
    opts = optionen(kopf, karten)
    gew = next((o for o in opts if o["key"] == str(option).upper()), None)
    if not gew:
        raise ValueError("Unbekannte Option")
    erledigt, bleibt, neu = ["diese Entscheidungskarte"], [], []
    for o in opts:
        for k in o["karten"]:
            if k not in karten:
                continue
            t = _titel(karten[k][1], k)
            (bleibt if o["key"] == gew["key"] else erledigt).append(t)
    for d in gew["dann"]:
        dk = _entwurf_kopf(root, d)
        neu.append("%s — %s" % (dk.get("betreff", d)[:90], dk.get("an", "")[:60]))
    return {"option": gew["key"], "titel": gew["titel"], "erledigt": erledigt, "bleibt": bleibt, "neu": neu}


def lage(root):
    """Zusatzfelder fuer freigabenlage(): {datei: {...}} - Vorgang, Zaehler, Optionen mit Wirkung, Unterpunkte."""
    raus = {}
    for v, e in gruppen(root).items():
        karten = _karten(root)
        f = e["fuehrend"]
        kopf = karten[f][1]
        opts = []
        for o in optionen(kopf, karten):
            try:
                w = wirkung(root, f, o["key"])
            except ValueError:
                continue
            try:
                mails = [{"entwurf": e, "an": _entwurf_kopf(root, e).get("an", ""), "betreff": _entwurf_kopf(root, e).get("betreff", ""),
                          "offen": offene_angaben(root, e)} for e in option_entwuerfe(root, f, o["key"])]
            except Exception:
                mails = []
            opts.append({"key": o["key"], "titel": o["titel"], "erledigt": w["erledigt"], "bleibt": w["bleibt"], "neu": w["neu"], "mails": mails})
        unter = [{"datei": m, "titel": _titel(karten[m][1], m)} for m in e["mitglieder"] if m in karten]
        n = 1 + len(unter)
        titel_v = (kopf.get("vorgang_titel") or "").strip() or v.replace("_", " ")
        raus[f] = {"entschieden": kopf.get("option_gewaehlt", "").strip().upper(), "vorgang": v, "titel": titel_v, "fuehrend": True, "anzahl": n, "optionen": opts, "unterpunkte": unter}
        for u in unter:
            raus[u["datei"]] = {"vorgang": v, "titel": titel_v, "fuehrend": False, "anzahl": n, "fuehrende_karte": f}
    # F-99: Unterpunkte mit Termin zeigen den vollen Terminblock (mit wem, Ort, Abhaengigkeit, Fahrzeit) in der fuehrenden Karte.
    o = _oberflaeche()
    karten = _karten(root)
    for eintrag in list(raus.values()):
        for u in eintrag.get("unterpunkte", []):
            try:
                u["termin"] = o._terminblock(root, karten[u["datei"]][1], u["datei"], raus)
            except Exception:
                u["termin"] = None
    return raus


def _vermerk(text, satz):
    return text.rstrip("\n") + "\n\n## Erledigt durch Entscheidung\n%s\n" % satz


def abschliessen(root, fuehrend, option, von="Patron"):
    """Wendet die Wahl auf die verbundenen Karten an. Sendet NICHTS. -> Satz fuer den Patron.
    Reihenfolge: (1) Wirkung berechnen (Fehler = nichts angefasst), (2) Karten der Gegenoptionen nach ersetzt/ + Entwurf sperren,
    (3) `dann`-Entwuerfe als Karten anlegen."""
    root = Path(root)
    o = _oberflaeche()
    karten = _karten(root)
    w = wirkung(root, fuehrend, option)
    kopf = karten[fuehrend][1]
    opts = optionen(kopf, karten)
    datum = b.now().strftime("%d.%m.%Y %H:%M")
    ersetzt_ordner = root / "auftraege" / "freigabe" / "ersetzt"
    ersetzt_ordner.mkdir(parents=True, exist_ok=True)
    verschoben, neu = [], []
    for opt in opts:
        if opt["key"] == w["option"]:
            continue
        for name in opt["karten"]:
            if name not in karten:
                continue
            f, k, text = karten[name]
            satz = "erledigt durch Entscheidung %s: Option %s (%s) gewählt (Karte %s)." % (datum, w["option"], w["titel"], fuehrend)
            neu_text = o._kopf_setzen(text, "status", "erledigt")
            neu_text = o._kopf_setzen(neu_text, "erledigt_am", b.now().strftime("%Y-%m-%d %H:%M"))
            neu_text = o._kopf_setzen(neu_text, "erledigt_durch", "Entscheidung %s Option %s" % (fuehrend, w["option"]))
            ziel = o._frei_verschieben(ersetzt_ordner, f, _vermerk(neu_text, satz))
            # Der zugehoerige Entwurf darf nicht mehr hinaus: senden() weigert bei zustand ersetzt*.
            entw = k.get("entwurf", "")
            if entw:
                ep = b.area(root) / "entwuerfe" / entw
                if ep.is_file() and not ep.is_symlink():
                    et = ep.read_text(encoding="utf-8")
                    ep.write_text(o._kopf_setzen(et, "zustand", "ersetzt (Entscheidung %s Option %s)" % (fuehrend, w["option"])), encoding="utf-8")
            verschoben.append(_titel(k, name))
    import jack_freigaben
    for d in next(x for x in opts if x["key"] == w["option"])["dann"]:
        dk = _entwurf_kopf(root, d)
        if not dk:
            continue
        text = (b.area(root) / "entwuerfe" / d).read_text(encoding="utf-8").split("\n---\n", 1)[-1].strip()
        v2 = {"projekt": kopf.get("projekt") or "Vorgang " + kopf.get("vorgang", ""), "marke": kopf.get("marke") or "HOLDING",
              "eingegangen": b.now().strftime("%Y-%m-%d %H:%M"), "von": "JACK (Entscheidung %s, Option %s)" % (kopf.get("vorgang", ""), w["option"]),
              "an": dk.get("an", "unbekannt"), "art": "mailantwort", "betreff": dk.get("betreff", d),
              "kern": "Vorbereitet, weil du Option %s (%s) gewählt hast: diese Mail an %s. Es wurde nichts gesendet." % (w["option"], w["titel"], dk.get("an", "")),
              "frage": "Diese Mail so senden?",
              "empfehlung": "Ja, nach Testversand an dich und Freigabecode. Text vorher lesen und bei Bedarf anpassen.",
              "frist": "keine", "dringlichkeit": "mittel", "ablauf": "TESTVERSAND → Code → FREIGEBEN"}
        v2.update({"postfach": dk.get("postfach", ""), "entwurf": d, "mailart": dk.get("mailart", "Extern"),
                   "vorgang": kopf.get("vorgang", ""), "gefahr": "aussen", "tiefe": "klein", "status": "freigabe", "freigabe": "nein",
                   "auftrag": "Mailantwort_" + re.sub(r"\W+", "_", d)[:40], "zustand": "wartet_auf_patron", "bereiche": "postfach"})
        pfad = jack_freigaben.karte_schreiben(root, v2, "## Antwort / Entwurf\n```\n%s\n```\n\n## Ablauf\nTESTVERSAND → Code → FREIGEBEN. Nichts wird automatisch gesendet.\n" % text[:4000],
                                              herkunft="jack_freigabe_vorgang.abschliessen")
        if pfad:
            neu.append(pfad.name)
    s = "Option %s (%s) gewählt." % (w["option"], w["titel"])
    if verschoben:
        s += " Erledigt und nach ersetzt/ verschoben: %s." % ", ".join(verschoben)
    if neu:
        s += " Neue Karten zum Testversand vorbereitet (nichts gesendet): %d." % len(neu)
    b.append(b.area(root) / "vorgaenge_karten.jsonl", {"zeit": b.now().isoformat(), "fuehrend": fuehrend, "option": w["option"], "von": von,
                                                      "ersetzt": verschoben, "neu": neu})
    return s


# ---------------------------------------------------------------- F-100 C: Mails je Option ansehen / testen
def _option(root, fuehrend, key):
    karten = _karten(root)
    if fuehrend not in karten:
        raise ValueError("Fuehrende Karte nicht gefunden")
    opts = optionen(karten[fuehrend][1], karten)
    o = next((x for x in opts if x["key"] == str(key).upper()), None)
    if not o:
        raise ValueError("Unbekannte Option")
    return o, karten


def option_entwuerfe(root, fuehrend, key):
    """Entwurfsdateien, die bei dieser Option entstehen/weiterlaufen: Entwurf der bleibenden Karten + `dann`-Entwuerfe."""
    o, karten = _option(root, fuehrend, key)
    namen = []
    for k in o["karten"]:
        if k in karten:
            e = karten[k][1].get("entwurf", "").strip()
            if e and e not in namen:
                namen.append(e)
    for d in o["dann"]:
        if d not in namen:
            namen.append(d)
    return [n for n in namen if _entwurf_kopf(root, n)]


def offene_angaben(root, entwurf):
    """Liste der '[PATRON …]'-Platzhalter im Entwurf (leer = vollstaendig)."""
    import re
    try:
        text = (b.area(root) / "entwuerfe" / entwurf).read_text(encoding="utf-8")
    except OSError:
        return []
    return re.findall(r"\[PATRON[^\]]*\]", text)


def mail_vorschau(root, fuehrend, key):
    """Jede Mail der Option genau so, wie sie beim Empfaenger aussaehe (Renderer wie Versand). Sendet NICHTS."""
    import jack_postfaecher as P
    raus = []
    for n in option_entwuerfe(root, fuehrend, key):
        offen = offene_angaben(root, n)
        try:
            r = P.senden(root, n, test=True, ansicht=True)
        except Exception as fehler:
            r = {"ok": False, "meldung": str(fehler)[:160]}
        raus.append({"entwurf": n, "ok": bool(r.get("ok")), "an": r.get("an") or _entwurf_kopf(root, n).get("an", ""),
                     "von": r.get("von", ""), "betreff": r.get("betreff") or _entwurf_kopf(root, n).get("betreff", ""),
                     "html": r.get("html", ""), "text": r.get("text", ""), "meldung": r.get("meldung", ""), "offen": offen})
    return {"option": str(key).upper(), "mails": raus,
            "hinweis": "FREIGEBEN A/B verschickt nichts. Jede Mail kommt danach als eigene Karte mit TESTVERSAND → Code → FREIGEBEN."}


def option_testversand(root, fuehrend, key, von="Patron"):
    """Schickt ALLE Mails der Option NUR an die Patron-Adresse ([TEST], ohne Freigabecode, keine Karten, keine Freigabe).
    Mails mit offenen Angaben gehen nicht. -> {"gesendet": n, "an": Patron-Adresse, "ergebnisse": [...]}"""
    import jack_postfaecher as P
    ergebnisse, n = [], 0
    for e in option_entwuerfe(root, fuehrend, key):
        offen = offene_angaben(root, e)
        if offen:
            ergebnisse.append({"entwurf": e, "ok": False, "meldung": "Offene Angaben: " + "; ".join(offen)[:200]})
            continue
        r = P.senden(root, e, von=von, test=True, ohne_code=True)
        ok = bool(r.get("ok"))
        n += 1 if ok else 0
        ergebnisse.append({"entwurf": e, "ok": ok, "meldung": str(r.get("meldung", ""))[:200]})
    b.append(b.area(root) / "optionen_testversand.jsonl", {"zeit": b.now().isoformat(), "fuehrend": fuehrend, "option": str(key).upper(),
             "an": P.TESTEMPFAENGER, "gesendet": n, "entwuerfe": [x["entwurf"] for x in ergebnisse], "von": von})
    return {"gesendet": n, "an": P.TESTEMPFAENGER, "ergebnisse": ergebnisse}


# ---------------------------------------------------------------- F-100 (Nachtrag PM 2): Mails unter der Entscheidung
def offene_mailkarten(root, fuehrend):
    """Mitglieder-Karten (Mail-Karten) des Vorgangs, die noch in auftraege/freigabe/ liegen."""
    karten = _karten(root)
    if fuehrend not in karten:
        return []
    vg = karten[fuehrend][1].get("vorgang", "").strip()
    return [n for n, (_f, k, _t) in karten.items()
            if vg and n != fuehrend and k.get("vorgang", "").strip() == vg and k.get("fuehrend", "").strip().lower() != "ja"
            and k.get("art") in ("externemail", "mailantwort", "mitarbeitermail")]


def fertige_abschliessen(root):
    """Eine entschiedene fuehrende Karte (Kopf option_gewaehlt) ohne offene Mail-Karten geht nach erledigt/ (nie geloescht)."""
    o = _oberflaeche()
    root = Path(root)
    for name, (f, k, text) in list(_karten(root).items()):
        if k.get("fuehrend", "").strip().lower() != "ja" or not k.get("option_gewaehlt", "").strip():
            continue
        if offene_mailkarten(root, name):
            continue
        neu = o._kopf_setzen(text, "status", "erledigt")
        neu = o._kopf_setzen(neu, "freigabe", "ja")
        neu += "\n\n## Erledigt\nOption %s gewaehlt; alle zugehoerigen Mails sind erledigt (%s).\n" % (k["option_gewaehlt"], b.now().strftime("%d.%m.%Y %H:%M"))
        o._frei_verschieben(root / "auftraege" / "erledigt", f, neu)
        b.append(b.area(root) / "vorgaenge_karten.jsonl", {"zeit": b.now().isoformat(), "fuehrend": name, "geschlossen": True})
