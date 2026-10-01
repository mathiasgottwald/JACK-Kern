#!/usr/bin/python3
"""B-1 (26.09.2026): Tagessuche in der Jobboerse der Bundesagentur fuer den Strang "Bewerbungen". Nur lesend, 0 USD, ohne Modell.

Quelle: oeffentliche Jobsuche-API (https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs, Header X-API-Key: jobboerse-jobsuche;
die aeltere Version v4 antwortet seit 26.09.2026 mit 403, v6 mit 200). Keine Anmeldung, keine Bewerbung, kein Versand, kein LinkedIn.
Suchbegriffe kommen aus <Bewerbungen>/03_Zielberufe.md (Schwerpunkt 1-3 aktiv; 4-8 nur als Pflichttreffer markiert).
Ausgabe: <Bewerbungen>/04_Tagesliste_<Datum>.md, Rohdaten <Bewerbungen>/suche/<Datum>.json, Gesehen-Liste <Bewerbungen>/05_suche_gesehen.json.
Aufruf: bewerbungen_tagessuche.py [--datum JJJJ-MM-TT] [--neu] [--trocken]
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

JACK = Path(os.environ.get("JACK_BEWERBUNG_JACK") or Path(__file__).resolve().parents[1])
HOLDING = JACK.parents[1]
BEWERBUNGEN = Path(os.environ.get("JACK_BEWERBUNG_ORDNER") or HOLDING / "00_Marken/MATHIAS_GOTTWALD/02_Dokumente/Bewerbungen")
API = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs"
API_KEY = "jobboerse-jobsuche"
ORT, UMKREIS = "Rosenheim", 100
SEITEN, SEITENGROESSE, TAGE = 3, 50, 14
WIEDERHOLUNG = (0, 3, 10, 30)          # Sekunden Wartezeit vor Versuch 1..4
# Treffer mit diesen Woertern im Titel/Beruf sind Fuzzy-Treffer ("Trainer" -> Fitness) und werden nie gelistet
AUSSCHLUSS = ("fitness", "personal trainer", "sporttrainer", "fußball", "fussball", "yoga", "pilates", "reit", "pferd", "fahrlehrer", "fahrschul",
              "azubi", "ausbildungsplatz", "praktikum", "werkstudent", "kfz", "verkäufer", "verkaeufer", "kassierer", "lager")
LINK = "https://www.arbeitsagentur.de/jobsuche/jobdetail/"
SCHWERPUNKT = (1, 2, 3)
# Ergaenzung zur Titelzeile der Zielberufe (nur Suchwoerter, die die Jobboerse kennt); der Rest kommt aus 03_Zielberufe.md
ZUSATZ = {1: ["Business Coach", "Führungskräftecoach", "Trainer Führung"], 2: ["Interimsmanager", "Interim Manager", "Sanierungsmanager"],
          3: ["Unternehmensberater", "Unternehmensberatung KMU"], 4: ["Ausbilder AEVO", "Betrieblicher Trainer"], 5: ["Personalentwickler", "Learning Development"],
          6: ["Bereichsleiter", "Bereichsleitung"], 7: ["Vertriebsleiter", "Key Account Manager"]}
STAMM = {1: ["coach", "trainer"], 2: ["interim", "sanierung", "restrukturierung"], 3: ["berater", "beratung", "consultant"], 4: ["ausbilder", "trainer", "aevo"],
         5: ["personalentwickl", "learning", "l&d"], 6: ["bereichsleit", "führungskraft", "abteilungsleit"], 7: ["vertriebsleit", "key account"], 8: ["sachbearbeit"]}
SIGNALTEXTE = ("flexibl", "gleitzeit", "vertrauensarbeitszeit", "freie zeiteinteilung", "remote", "homeoffice", "home office", "mobiles arbeiten", "teilzeit")


class SucheFehler(Exception):
    pass


def zielberufe(pfad=None):
    """-> [{nr, titel, passung, begriffe, stamm, schwerpunkt}] aus 03_Zielberufe.md ("1. **Titel (Zusatz)** — Passung N")."""
    text = Path(pfad or BEWERBUNGEN / "03_Zielberufe.md").read_text(encoding="utf-8")
    raus = []
    for m in re.finditer(r"^(\d)\.\s+\*\*(.+?)\*\*\s+—\s+Passung\s+(\d)", text, re.M):
        nr, titel, passung = int(m.group(1)), m.group(2).strip(), int(m.group(3))
        kern = re.sub(r"\s*\(.*?\)", "", titel).strip()
        kern = re.sub(r",?\s*klassische.*$|\s+in Festanstellung", "", kern).strip()
        teile = [t.strip() for t in kern.split("/")]
        begriffe = []
        for t in teile:
            m2 = re.match(r"^(\w+)-\s*$", t)              # "Interims-" + "Sanierungsmanager" -> Interimsmanager
            if m2 and len(teile) > 1:
                rest = teile[teile.index(t) + 1]
                suffix = re.search(r"(manager|berater|trainer|leiter|entwickler)$", rest, re.I)
                t = m2.group(1) + (suffix.group(1).lower() if suffix else "")
            if t and t not in begriffe:
                begriffe.append(t)
        if nr == 8:                                  # Sachbearbeiter/Linienposition: zu unscharf fuer eine Stichwortsuche, nur Pflichttreffer-Rolle
            begriffe = []
        for b in ZUSATZ.get(nr, []):
            if b not in begriffe:
                begriffe.append(b)
        raus.append({"nr": nr, "titel": titel, "passung": passung, "begriffe": begriffe, "stamm": STAMM.get(nr, []), "schwerpunkt": nr in SCHWERPUNKT})
    return raus


def abrufen(params, opener=None):
    """Eine API-Seite -> dict. Fehler -> SucheFehler."""
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"X-API-Key": API_KEY, "Accept": "application/json"})
    letzter = None
    for versuch, warte in enumerate(WIEDERHOLUNG):          # Netz-Aussetzer (Errno 8 am 26.09.) nicht als Suchfehler zaehlen
        try:
            with (opener or urllib.request.urlopen)(req, timeout=30) as a:
                return json.loads(a.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError) as fehler:
            letzter = fehler
            if isinstance(fehler, urllib.error.HTTPError) and fehler.code in (400, 401, 403, 404):
                break                                        # sinnlos zu wiederholen
            if versuch < len(WIEDERHOLUNG) - 1:
                time.sleep(warte)
    raise SucheFehler("%s: %s" % (url, letzter))


def signale(t):
    """Homeoffice-/Teilzeit-/Flex-Signale eines Treffers -> Liste von Kurztexten."""
    s = []
    if t.get("homeofficemoeglich"):
        typ = str(t.get("homeofficetyp") or "").replace("_", " ").lower()
        s.append("Homeoffice" + (" (%s)" % typ if typ else ""))
    if any(t.get(k) for k in ("arbeitszeitTeilzeitVormittag", "arbeitszeitTeilzeitNachmittag", "arbeitszeitTeilzeitAbend", "arbeitszeitTeilzeitFlexibel")):
        s.append("Teilzeit" + (" flexibel" if t.get("arbeitszeitTeilzeitFlexibel") else ""))
    titel = str(t.get("stellenangebotsTitel") or "").lower()
    for w in SIGNALTEXTE:
        if w in titel and not any(w in x.lower() for x in s):
            s.append("im Titel: " + w)
    return s


def titel_passt(t, stamm):
    text = " ".join([str(t.get("stellenangebotsTitel") or ""), str(t.get("hauptberuf") or "")] + list(t.get("alleBerufe") or [])).lower()
    if any(w in text for w in AUSSCHLUSS):
        return False
    return any(w in text for w in stamm)


def bedingungen(t, sig):
    teile = []
    teile.append("Vollzeit" if t.get("arbeitszeitVollzeit") else "Teilzeit/andere")
    if t.get("arbeitszeitVollzeit") and any("Teilzeit" in x for x in sig):
        teile[-1] = "Vollzeit oder Teilzeit"
    teile += [x for x in sig if x.startswith("Homeoffice") or x.startswith("im Titel")]
    if t.get("gehaltsspanneVon") or t.get("gehaltsspanneBis"):
        teile.append("%s–%s €/Jahr" % (t.get("gehaltsspanneVon") or "?", t.get("gehaltsspanneBis") or "?"))
    elif t.get("verguetungsangabe") not in (None, "KEINE_ANGABEN"):
        teile.append(str(t.get("verguetungsangabe")).replace("_", " ").lower())
    else:
        teile.append("keine Gehaltsangabe")
    if str(t.get("vertragsdauer") or "").upper() == "BEFRISTET":
        teile.append("befristet")
    return ", ".join(teile)


def passung_vorschlag(beruf, t, sig):
    """Nur ein VORSCHLAG: Zielberuf-Passung, -1 ohne Homeoffice/Flex-Signal (nur Teilzeit) und -1 bei Gehalt deutlich unter dem Zielbereich (< 60 T€)."""
    p, grund = beruf["passung"], ["Zielberuf %d" % beruf["nr"]]
    if not any(x.startswith("Homeoffice") or x.startswith("im Titel") for x in sig):
        p -= 1
        grund.append("kein Homeoffice-/Flex-Signal")
    bis = t.get("gehaltsspanneBis") or t.get("gehaltsspanneVon")
    if bis and bis < 60000:
        p -= 1
        grund.append("Gehalt unter Zielbereich (~74–80 T€ brutto)")
    return max(1, p), "; ".join(grund)


def suchen(berufe, abruf=abrufen, pause=0.4, jetzt=None):
    """-> (treffer, protokoll). treffer: {referenznummer: {...roh, _beruf, _region, _signale}}; protokoll je Suche."""
    treffer, protokoll = {}, []
    for b in berufe:
        for begriff in b["begriffe"]:
            for region in ("Umkreis Rosenheim %d km" % UMKREIS, "bundesweit remote"):
                eintrag = {"beruf": b["nr"], "begriff": begriff, "region": region, "api": 0, "relevant": 0, "mit_signal": 0, "fehler": ""}
                try:
                    for seite in range(1, SEITEN + 1):
                        p = {"was": begriff, "size": SEITENGROESSE, "page": seite, "veroeffentlichtseit": TAGE}
                        if region.startswith("Umkreis"):
                            p.update(wo=ORT, umkreis=UMKREIS)
                        # bundesweit: die API kennt keinen Homeoffice-Filter (arbeitszeit=ho liefert 0), also ohne Ort suchen und
                        # unten auf homeofficemoeglich filtern
                        d = abruf(p)
                        liste = d.get("ergebnisliste") or []
                        eintrag["api_gesamt"] = d.get("maxErgebnisse")
                        eintrag["api"] += len(liste)
                        for t in liste:
                            if str(t.get("stellenangebotsart") or "ARBEIT") not in ("ARBEIT", "SELBSTAENDIGKEIT"):
                                continue
                            if not titel_passt(t, b["stamm"]):
                                continue
                            eintrag["relevant"] += 1
                            sig = signale(t)
                            if not sig:
                                continue
                            if region == "bundesweit remote" and not t.get("homeofficemoeglich"):
                                continue
                            eintrag["mit_signal"] += 1
                            # M-9 (Befund 3, MASTERMIND M-3): Referenznummer/hashId fehlen manchmal beide -
                            # dann Titel+Firma+Ort kombinieren statt nur den Titel, um Kollisionen zwischen
                            # zwei verschiedenen Treffern unter demselben Schluessel zu vermeiden.
                            ort_kollision = ((t.get("stellenlokationen") or [{}])[0].get("adresse") or {}).get("ort", "")
                            ref = t.get("referenznummer") or t.get("hashId") or "|".join(
                                str(x or "") for x in (t.get("stellenangebotsTitel"), t.get("firma"), ort_kollision))
                            alt = treffer.get(ref)
                            if alt is None or b["passung"] > alt["_beruf"]["passung"]:
                                treffer[ref] = dict(t, _beruf=b, _region=region, _signale=sig)
                        if len(liste) < SEITENGROESSE or seite * SEITENGROESSE >= (d.get("maxErgebnisse") or 0):
                            break
                        time.sleep(pause)
                except SucheFehler as fehler:
                    eintrag["fehler"] = str(fehler)[:300]
                protokoll.append(eintrag)
                time.sleep(pause)
    return treffer, protokoll


def liste_schreiben(datum, neu, protokoll, gesamt_treffer, bereits, ausgabe):
    """Tagesliste im Format der bestehenden (Tabelle Stelle/Arbeitgeber/Ort/Bedingungen/Passung + Link + Referenznummer)."""
    def zeile(i, t):
        ort = ((t.get("stellenlokationen") or [{}])[0].get("adresse") or {}).get("ort", "") or "bundesweit"
        entfernung = t.get("entfernung")
        p, grund = passung_vorschlag(t["_beruf"], t, t["_signale"])
        link = LINK + str(t.get("referenznummer", ""))
        extern = " · [Arbeitgeberseite](%s)" % t["externeURL"] if t.get("externeURL") else ""
        return "| %d | %s | %s | %s%s | %s | %d (Vorschlag: %s) | [Jobbörse](%s)%s | %s |" % (
            i, str(t.get("stellenangebotsTitel", "")).replace("|", "/"), str(t.get("firma", "(ohne Angabe)")).replace("|", "/"), ort,
            " (%s km)" % entfernung if entfernung is not None else "", bedingungen(t, t["_signale"]), p, grund, link, extern, t.get("referenznummer", ""))
    kopf = "| # | Stelle | Arbeitgeber | Ort | Bedingungen | Passung | Link | Referenznr. |\n|---|---|---|---|---|---|---|---|"
    schwer = sorted([t for t in neu if t["_beruf"]["schwerpunkt"]], key=lambda t: (-passung_vorschlag(t["_beruf"], t, t["_signale"])[0], str(t.get("firma"))))
    pflicht = [t for t in neu if not t["_beruf"]["schwerpunkt"]][:30]
    z = ["# Tagesliste — %s (automatisch, Jobbörse der Bundesagentur, nur lesend)" % dt.date.fromisoformat(datum).strftime("%d.%m.%Y"), "",
         "Erzeugt von `bin/bewerbungen_tagessuche.py` (B-1). Kein Versand, keine Bewerbung. **Die Passung ist nur ein Vorschlag** — die Bewertung macht der Bewerbungs-Chat.", "",
         "## Suchlauf (Treffer je Suchbegriff)", "", "| Zielberuf | Suchbegriff | Region | API-Treffer | passender Titel | mit Homeoffice-/Teilzeit-Signal |", "|---|---|---|---|---|---|"]
    for p in protokoll:
        z.append("| %d | %s | %s | %s | %s | %s |" % (p["beruf"], p["begriff"], p["region"], p["api_gesamt"] if p.get("api_gesamt") is not None else p["api"], p["relevant"],
                                                     ("FEHLER: " + p["fehler"][:60]) if p["fehler"] else p["mit_signal"]))
    z += ["", "Neu heute: **%d** Stellen (davon Schwerpunkt Zielberufe 1–3: %d, Pflichttreffer 4–8: %d). Schon an früheren Tagen gesehen und ausgelassen: %d. "
          "Filter: Homeoffice-, Teilzeit- oder Flex-Signal; Umkreis Rosenheim %d km plus bundesweit remote; Veröffentlichung der letzten %d Tage." % (
              len(neu), len(schwer), len(pflicht), bereits, UMKREIS, TAGE), ""]
    z += ["## Schwerpunkt (Zielberufe 1–3)", ""]
    z += [kopf] + [zeile(i, t) for i, t in enumerate(schwer, 1)] if schwer else ["Heute keine neuen Treffer mit Signal."]
    z += ["", "## Pflichttreffer (Zielberufe 4–8, nur für die AA-Nachweise, nicht aktiv verfolgen)", ""]
    z += [kopf] + [zeile(i, t) for i, t in enumerate(pflicht, 1)] if pflicht else ["Heute keine neuen Treffer mit Signal."]
    z += ["", "## Hinweis", "Rohdaten: `suche/%s.json`. Doppelte gegen Vortage: `05_suche_gesehen.json`." % datum, ""]
    Path(ausgabe).write_text("\n".join(z), encoding="utf-8")


def _json_lesen(pfad, ersatz):
    try:
        return json.loads(Path(pfad).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ersatz


def laufen(datum=None, neu_erzwingen=False, abruf=abrufen, trocken=False, pause=0.4):
    datum = datum or dt.date.today().isoformat()
    roh_pfad = BEWERBUNGEN / "suche" / (datum + ".json")
    if roh_pfad.exists() and not neu_erzwingen:
        return {"ok": True, "uebersprungen": "Suche für %s ist schon gelaufen (%s)" % (datum, roh_pfad.name)}
    berufe = zielberufe()
    treffer, protokoll = suchen(berufe, abruf=abruf, pause=pause)
    fehler = [p for p in protokoll if p["fehler"]]
    if len(fehler) == len(protokoll):
        _fehler_melden(datum, "Alle %d Suchen sind fehlgeschlagen. Erste Meldung: %s" % (len(protokoll), fehler[0]["fehler"]))
        return {"ok": False, "fehler": fehler[0]["fehler"]}
    gesehen_pfad = BEWERBUNGEN / "05_suche_gesehen.json"
    gesehen = _json_lesen(gesehen_pfad, {})
    neu = [t for ref, t in treffer.items() if ref not in gesehen or gesehen[ref].get("erstmals") == datum]      # Neulauf am selben Tag: die Treffer dieses Tages bleiben "neu"
    bereits = len(treffer) - len(neu)
    ergebnis = {"ok": True, "datum": datum, "neu": len(neu), "gesehen": bereits, "suchen": len(protokoll), "fehlgeschlagen": len(fehler)}
    if trocken:
        return dict(ergebnis, trocken=True, protokoll=protokoll)
    (BEWERBUNGEN / "suche").mkdir(parents=True, exist_ok=True)
    roh_pfad.write_text(json.dumps({"datum": datum, "suchen": protokoll, "treffer": [{k: v for k, v in t.items() if not k.startswith("_")} | {"_zielberuf": t["_beruf"]["nr"], "_region": t["_region"], "_signale": t["_signale"]} for t in treffer.values()]},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
    ziel = BEWERBUNGEN / ("04_Tagesliste_%s.md" % datum)
    if ziel.exists():
        if "(automatisch, Jobbörse der Bundesagentur" in ziel.read_text(encoding="utf-8")[:200]:      # unsere eigene Liste (Neulauf): mit Sicherung ersetzen
            import shutil
            shutil.copy2(ziel, str(ziel) + ".vor_" + dt.datetime.now().strftime("%H%M%S"))
            if roh_pfad.exists():
                shutil.copy2(roh_pfad, str(roh_pfad) + ".vor_" + dt.datetime.now().strftime("%H%M%S"))
        else:                                      # nie ueberschreiben: eine von Hand geschriebene Liste bleibt
            ziel = BEWERBUNGEN / ("04_Tagesliste_%s_auto.md" % datum)
    liste_schreiben(datum, neu, protokoll, treffer, bereits, ziel)
    for ref, t in treffer.items():
        gesehen.setdefault(ref, {"erstmals": datum, "titel": t.get("stellenangebotsTitel"), "firma": t.get("firma")})
    gesehen_pfad.write_text(json.dumps(gesehen, ensure_ascii=False, indent=1), encoding="utf-8")
    ergebnis["liste"] = str(ziel)
    return ergebnis


def _fehler_melden(datum, text):
    ziel = JACK / "abnahme" / "pm_eingang" / ("BEWERBUNGEN_SUCHE_FEHLER_%s.md" % datum)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text("# Bewerbungen-Tagessuche FEHLER %s\n\n%s\n\nKeine Liste erzeugt. Nächster Versuch: morgen 06:00 oder `bin/bewerbungen_tagessuche.py --neu`.\n" % (datum, text), encoding="utf-8")


def herzschlag(ergebnis):
    """Herzschlag-Eintrag (betrieb/herzschlag/bewerbungen_suche.json) und Stand fuer den Netz-Waechter."""
    jetzt = time.time()
    d = {"kanal": "bewerbungen_suche", "epoch": int(jetzt), "zeit": dt.datetime.fromtimestamp(jetzt).astimezone().isoformat(timespec="seconds"),
         "zustand": "ok" if ergebnis.get("ok") else "fehler", "auftrag": ("Tagessuche %s: %s neu, %s gesehen" % (ergebnis.get("datum", ""), ergebnis.get("neu"), ergebnis.get("gesehen"))) if ergebnis.get("ok") and "neu" in ergebnis else str(ergebnis.get("uebersprungen") or ergebnis.get("fehler") or "")[:160]}
    ordner = JACK / "betrieb" / "herzschlag"
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / "bewerbungen_suche.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    if ergebnis.get("ok"):
        (JACK / "betrieb" / "bewerbungen_suche_stand.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("--datum")
    a.add_argument("--neu", action="store_true", help="auch laufen, wenn heute schon gelaufen")
    a.add_argument("--trocken", action="store_true", help="suchen, aber nichts schreiben")
    args = a.parse_args()
    try:
        r = laufen(args.datum, args.neu, trocken=args.trocken)
    except Exception as fehler:                 # nie stumm: Fehlerdatei fuer den PM
        _fehler_melden(args.datum or dt.date.today().isoformat(), "Unerwarteter Fehler: %s: %s" % (type(fehler).__name__, str(fehler)[:400]))
        r = {"ok": False, "fehler": "%s: %s" % (type(fehler).__name__, fehler)}
    if not args.trocken:
        herzschlag(r)
    print(json.dumps({k: v for k, v in r.items() if k != "protokoll"}, ensure_ascii=False))
    sys.exit(0 if r.get("ok") else 1)
