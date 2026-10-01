#!/usr/bin/python3
"""B-2 (28.09.2026): Erweiterte Tagessuche fuer den Strang "Bewerbungen" - Auftraege/Mandate (Freelance/Interim/Beratung)
und oeffentliche Ausschreibungen, zusaetzlich zur Festanstellungs-Suche aus bin/bewerbungen_tagessuche.py (B-1, wird
NICHT veraendert). Nur lesend, 0 USD, ohne Modellaufruf, kein Login-Scraping, robots.txt wird beachtet.

Ehrlicher Umfang (Stand 28.09.2026, nach Pruefung von robots.txt und Live-Abruf je Quelle):
  Auftraege/Mandate:
    - freelancermap.de   AUTOMATISIERT. robots.txt erlaubt alles, Projektlisten (/projekte/<kategorie>) sind ohne
                          Login/JS als reines HTML ausgeliefert. Kategorie "consulting" wird abgerufen, Titel per
                          Keyword aus 03_Zielberufe gefiltert, AUSSCHLUSS_AUFTRAG filtert IT/SAP-Rauschen raus
                          (M-9, MASTERMIND-Befund 8: Kategorie "it-jobs" entfernt, war Hauptquelle der Fehltreffer).
    - GULP (gulp.de)      NICHT automatisiert. Oeffentlich indexierte Freelancer-*Profile* bestaetigen das Themenfeld,
                          die Projektboerse selbst laedt Treffer per JavaScript/nach Login -> manuelle Pruefung noetig.
    - Malt (malt.de)      NICHT automatisiert. Cloudflare-Challenge auch auf robots.txt (bestaetigt 28.09.2026) ->
                          jeder automatisierte Abruf wird geblockt. Malt ist ohnehin primaer ein
                          Freelancer-Profil-Marktplatz (Kunden suchen Profile), keine offene Projekt-Ausschreibungsliste.
    - Hays/Randstad Freelance  NICHT automatisiert. "Contracting"-Projektboerse erfordert Login zur Ergebnisliste.
    - LinkedIn-Projekte    NICHT automatisiert (Nutzervereinbarung/Login-Pflicht fuer den Dienstleistungsmarktplatz;
                          gilt ohnehin: nie automatisch bewerben, nur lesend pruefen).
  Ausschreibungen:
    - service.bund.de     NICHT automatisiert. robots.txt sperrt exakt den Suchpfad
                          (Disallow: /Content/DE/Ausschreibungen/Suche/) -> Skript darf ihn nicht abrufen,
                          Pruefung bleibt manuell (WebFetch/Browser, wie am 28.09.2026 im Auftrag B-2 geschehen).
    - Bayern-Vergabeportal / DTVP / evergabe   NICHT automatisiert. auftraege.bayern.de leitet auf eine
                          JS-Anwendung (deutsche-evergabe.de) weiter, DTVP-Suche ist ebenfalls JS-basiert -> ohne
                          Login zwar grundsaetzlich einsehbar (bestaetigt), aber nicht mit einfachem HTTP-Abruf lesbar.
    - Landkreis Rosenheim/Traunstein   TEILAUTOMATISIERT. landkreis-rosenheim.de/ausschreibungen/ und
                          aumass.de/ausschreibungen/<ort> sind erreichbar, liefern aber Marketing-/Landingpage-Text,
                          keine Rohliste einzelner Vergaben (Ergebnisliste liegt hinter der eVergabe-Anwendung) ->
                          Skript meldet nur "Seite erreichbar, keine strukturierte Liste", keine Falschtreffer.
  Konsequenz: Diese nicht automatisierbaren Quellen bleiben eine WOECHENTLICHE manuelle Pruefung (WebFetch/Browser,
  im Bewerbungen-Kanal), keine taegliche Skript-Pflicht. Das Skript selbst faellt nie auf Rateergebnisse zurueck.

Ausgabe: <Bewerbungen>/suche/<Datum>_auftraege.json, <Bewerbungen>/suche/<Datum>_ausschreibungen.json,
Abschnitte "Auftrag" und "Ausschreibung" werden an <Bewerbungen>/04_Tagesliste_<Datum>.md angehaengt (die
Festanstellungs-Abschnitte von B-1 bleiben unveraendert stehen). Nutzt <Bewerbungen>/05_suche_gesehen.json weiter
(gemeinsame Dublettenliste ueber alle drei Suchfelder). Herzschlag: <JACK>/betrieb/herzschlag/bewerbungen_suche.json
(dieselbe Datei wie B-1, wird nach jedem Lauf ueberschrieben).
Aufruf: bewerbungen_suche_erweitert.py [--datum JJJJ-MM-TT] [--trocken]
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

JACK = Path(os.environ.get("JACK_BEWERBUNG_JACK") or Path(__file__).resolve().parents[1])
HOLDING = JACK.parents[1]
BEWERBUNGEN = Path(os.environ.get("JACK_BEWERBUNG_ORDNER") or HOLDING / "00_Marken/MATHIAS_GOTTWALD/02_Dokumente/Bewerbungen")
HERZSCHLAG = JACK / "betrieb/herzschlag/bewerbungen_suche.json"
UA = "Mozilla/5.0 (compatible; JACK-Bewerbungen-Suche/1.0; nur lesend, oeffentliche Seiten, robots.txt beachtet)"

# Keywords aus 03_Zielberufe.md (Schwerpunkt 1-3: Coaching, Interim, Unternehmensberatung KMU) + Mandat-Themen
KEYWORDS_AUFTRAG = ("coach", "coaching", "berater", "beratung", "consultant", "consulting", "interim", "sanierung",
                     "restrukturierung", "ki-berat", "ki berat", "künstliche intelligenz", "ai consult", "change management",
                     "transformation", "projektentwicklung", "projektleitung", "organisationsentwicklung")
# M-9 (Befund 8, MASTERMIND M-3): "berater"/"consultant" allein sind zu generisch (28.09.: 9/9 Treffer IT/SAP-lastig,
# keiner mit guter Passung zu den Zielberufen 1-3). Diese rein technischen IT/SAP-Rollen werden jetzt ausgeschlossen,
# auch wenn ein KEYWORDS_AUFTRAG-Wort zufaellig mit vorkommt (z.B. "SAP ... Consultant").
AUSSCHLUSS_AUFTRAG = ("sap ", "abap", "databricks", "devops", "java ", "python entwickler", "full stack", "fullstack",
                       "react", "angular", "aws ", "azure ", "kubernetes", "docker", "microsoft fabric", "tableau",
                       "power bi", "salesforce", "netzwerk", "administrator", "system engineer", "cloud engineer",
                       "data engineer", "software engineer", "entwickler", "developer", "ibp", "s/4hana", "s4hana", "hana")
FREELANCERMAP_KATEGORIEN = {"consulting": "https://www.freelancermap.de/projekte/consulting"}
# "it-jobs"-Kategorie (M-9): entfernt - war am 28.09. die Hauptquelle der IT/SAP-Fehltreffer, "consulting" deckt
# das Mandats-Thema (Unternehmensberatung/KI-Beratung/Coaching/Interim) naeher ab.

AUSSCHREIBUNG_LANDING = {
    "Landkreis Rosenheim": "https://www.landkreis-rosenheim.de/ausschreibungen/",
    "aumass Rosenheim": "https://www.aumass.de/ausschreibungen/rosenheim",
    # Landkreis Traunstein: am 28.09.2026 keine eigene Ausschreibungsseite mit stabiler URL gefunden
    # (landkreis-traunstein.de/ausschreibungen/ = 404, aumass.de kennt "traunstein" nicht als eigene Ortsseite).
    # Traunstein laeuft ueber DTVP/Bayern-Vergabeportal -> siehe NICHT_AUTOMATISIERT_AUSSCHREIBUNG, manuell pruefen.
}

NICHT_AUTOMATISIERT_AUFTRAG = [
    {"quelle": "GULP (gulp.de)", "grund": "Projektliste laedt per JS/Login, nur Profile oeffentlich indexiert"},
    {"quelle": "Malt (malt.de)", "grund": "Cloudflare-Challenge, auch auf robots.txt; primaer Profil- statt Projektmarktplatz"},
    {"quelle": "Hays/Randstad Freelance", "grund": "Contracting-Projektboerse erfordert Login zur Ergebnisliste"},
    {"quelle": "LinkedIn-Projekte", "grund": "Dienstleistungsmarktplatz erfordert Login; nur lesend pruefen laut Mandat"},
]
NICHT_AUTOMATISIERT_AUSSCHREIBUNG = [
    {"quelle": "service.bund.de", "grund": "robots.txt: Disallow /Content/DE/Ausschreibungen/Suche/ (Skript haelt sich daran)"},
    {"quelle": "Bayern-Vergabeportal (auftraege.bayern.de)", "grund": "leitet auf JS-Anwendung deutsche-evergabe.de weiter"},
    {"quelle": "DTVP (dtvp.de)", "grund": "Suchoberflaeche JS-basiert, ohne Login zwar einsehbar aber nicht per HTTP-GET lesbar"},
]


class SucheFehler(Exception):
    pass


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def _gesehen_laden():
    p = BEWERBUNGEN / "05_suche_gesehen.json"
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


def _gesehen_speichern(gesehen, trocken):
    if trocken:
        return
    p = BEWERBUNGEN / "05_suche_gesehen.json"
    p.write_text(json.dumps(gesehen, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def freelancermap_suche():
    """-> [{titel, link, quelle, gesehen_key}] aus den freelancermap-Kategorielisten, nach KEYWORDS_AUFTRAG gefiltert."""
    treffer = []
    for kategorie, url in FREELANCERMAP_KATEGORIEN.items():
        try:
            html = _get(url)
        except (urllib.error.URLError, TimeoutError) as e:
            treffer.append({"fehler": f"{kategorie}: {e}"})
            continue
        for slug in sorted(set(re.findall(r'/projekt/([a-z0-9\-]+)', html))):
            titel_lesbar = slug.replace("-", " ")
            if not any(kw in titel_lesbar for kw in KEYWORDS_AUFTRAG):
                continue
            if any(a in titel_lesbar for a in AUSSCHLUSS_AUFTRAG):     # M-9 (Befund 8): IT/SAP-Rauschen raus
                continue
            treffer.append({
                "titel": titel_lesbar, "link": f"https://www.freelancermap.de/projekt/{slug}",
                "quelle": f"freelancermap.de/{kategorie}", "gesehen_key": f"fm:{slug}",
            })
        time.sleep(1)  # freundlich zur Quelle, keine Stossabrufe
    return treffer


def ausschreibung_landingpages_pruefen():
    """Prueft nur Erreichbarkeit (HTTP 200) der Ausschreibungs-Landingpages, extrahiert KEINE Einzelvergaben
    (die liegen hinter einer JS-Anwendung, siehe Docstring) - vermeidet Falschtreffer."""
    ergebnis = []
    for name, url in AUSSCHREIBUNG_LANDING.items():
        try:
            html = _get(url)
            ergebnis.append({"quelle": name, "url": url, "status": "erreichbar (keine strukturierte Liste, manuell pruefen)",
                              "laenge_zeichen": len(html)})
        except (urllib.error.URLError, TimeoutError) as e:
            ergebnis.append({"quelle": name, "url": url, "status": f"fehler: {e}"})
        time.sleep(1)
    return ergebnis


def tagesliste_abschnitte(datum, auftrag_treffer, ausschreibung_ergebnis):
    neue_auftraege = [t for t in auftrag_treffer if "fehler" not in t]
    zeilen = ["", "## Auftrag / Mandat (Freelance, Interim, Beratung)", "",
              "Automatisiert nur freelancermap.de (robots.txt erlaubt, ohne Login lesbar). "
              "GULP, Malt, Hays/Randstad Freelance, LinkedIn-Projekte: nicht automatisierbar (Login/JS/Cloudflare), "
              "woechentliche manuelle Pruefung noetig — siehe Meldung B-2.", ""]
    if neue_auftraege:
        zeilen.append("| # | Titel (aus Projekt-Kurzlink) | Quelle | Link |")
        zeilen.append("|---|---|---|---|")
        for i, t in enumerate(neue_auftraege, 1):
            zeilen.append(f"| {i} | {t['titel']} | {t['quelle']} | [Projekt]({t['link']}) |")
    else:
        zeilen.append("Heute keine neuen Treffer mit Zielberuf-Schlagwort auf freelancermap.de.")
    zeilen += ["", "## Ausschreibung (öffentliche Vergabe)", "",
               "service.bund.de: robots.txt sperrt die Suche für Skripte (Disallow /Content/DE/Ausschreibungen/Suche/), "
               "Bayern-Vergabeportal/DTVP: JS-Anwendung — beide nur manuell (WebFetch/Browser) prüfbar. "
               "Landkreis-Seiten unten nur auf Erreichbarkeit geprüft, keine Einzelvergaben extrahiert.", "",
               "| Quelle | Status |", "|---|---|"]
    for e in ausschreibung_ergebnis:
        zeilen.append(f"| {e['quelle']} | {e['status']} |")
    zeilen.append("")
    return "\n".join(zeilen)


def lauf(datum, trocken):
    gesehen = _gesehen_laden()
    auftrag_treffer_roh = freelancermap_suche()
    neu, alt = [], 0
    for t in auftrag_treffer_roh:
        if "fehler" in t:
            neu.append(t)
            continue
        key = t["gesehen_key"]
        if key in gesehen:
            alt += 1
            continue
        gesehen[key] = datum
        neu.append(t)

    ausschreibung_ergebnis = ausschreibung_landingpages_pruefen()

    suche_dir = BEWERBUNGEN / "suche"
    if not trocken:
        suche_dir.mkdir(exist_ok=True)
        (suche_dir / f"{datum}_auftraege.json").write_text(
            json.dumps({"datum": datum, "neu": neu, "schon_gesehen": alt,
                        "nicht_automatisiert": NICHT_AUTOMATISIERT_AUFTRAG}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        (suche_dir / f"{datum}_ausschreibungen.json").write_text(
            json.dumps({"datum": datum, "landingpages": ausschreibung_ergebnis,
                        "nicht_automatisiert": NICHT_AUTOMATISIERT_AUSSCHREIBUNG}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        _gesehen_speichern(gesehen, trocken)

        tagesliste = BEWERBUNGEN / f"04_Tagesliste_{datum}.md"
        abschnitt = tagesliste_abschnitte(datum, neu, ausschreibung_ergebnis)
        if tagesliste.is_file():
            bisher = tagesliste.read_text(encoding="utf-8")
            if "## Auftrag / Mandat" not in bisher:
                tagesliste.write_text(bisher.rstrip("\n") + "\n" + abschnitt, encoding="utf-8")
        else:
            tagesliste.write_text(f"# Tagesliste — {datum} (Suchfeld erweitert, B-2)\n" + abschnitt, encoding="utf-8")

    # M-9 (Befund 1, MASTERMIND M-3): Herzschlag-Zustand jetzt auch von Ausschreibungs-Fehlern abhaengig,
    # nicht nur von den Auftrag/Mandat-Treffern.
    auftrag_fehler = [t for t in neu if "fehler" in t]
    ausschreibung_fehler = [e for e in ausschreibung_ergebnis if str(e.get("status", "")).startswith("fehler")]
    alle_auftrag_fehlgeschlagen = bool(auftrag_fehler) and len(auftrag_fehler) == len(neu)
    alle_ausschreibung_fehlgeschlagen = bool(ausschreibung_ergebnis) and len(ausschreibung_fehler) == len(ausschreibung_ergebnis)
    if not auftrag_fehler and not ausschreibung_fehler:
        zustand = "ok"
    elif alle_auftrag_fehlgeschlagen and alle_ausschreibung_fehlgeschlagen:
        zustand = "fehler"
    else:
        zustand = "teilweise_fehler"
    # M-9 (Befund 2, MASTERMIND M-3): Totalausfall (wie B-1s _fehler_melden) auch fuer B-2 - der PM wird
    # aktiv benachrichtigt statt dass der Ausfall nur still in Tagesliste/JSON steht.
    if not trocken and alle_auftrag_fehlgeschlagen and alle_ausschreibung_fehlgeschlagen:
        _fehler_melden(datum, "Alle Quellen sind fehlgeschlagen. Auftrag/Mandat: %s. Ausschreibungen: %s." % (
            auftrag_fehler[0].get("fehler", "unbekannt") if auftrag_fehler else "-",
            ausschreibung_fehler[0].get("status", "unbekannt") if ausschreibung_fehler else "-"))
    HERZSCHLAG.parent.mkdir(parents=True, exist_ok=True)
    HERZSCHLAG.write_text(json.dumps({
        "kanal": "bewerbungen_suche", "epoch": int(time.time()),
        "zeit": dt.datetime.now().astimezone().isoformat(),
        "zustand": zustand,
        "auftrag": f"Erweiterte Suche {datum}: {len([t for t in neu if 'fehler' not in t])} neue Auftraege/Mandate, "
                    f"{alt} schon gesehen, Ausschreibungs-Landingpages geprueft: {len(ausschreibung_ergebnis)}"
                    f"{' (Ausschreibungs-Fehler: ' + str(len(ausschreibung_fehler)) + ')' if ausschreibung_fehler else ''}",
    }, ensure_ascii=False), encoding="utf-8")
    return neu, ausschreibung_ergebnis


def _fehler_melden(datum, text):
    ziel = JACK / "abnahme" / "pm_eingang" / ("BEWERBUNGEN_SUCHE_ERWEITERT_FEHLER_%s.md" % datum)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text("# Bewerbungen erweiterte Suche (B-2) FEHLER %s\n\n%s\n\n"
                     "Keine Auftrag/Mandat- oder Ausschreibungs-Ergebnisse erzeugt. "
                     "Naechster Versuch: manuell `bin/bewerbungen_suche_erweitert.py --datum %s`.\n" % (
                         datum, text, datum), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--datum", default=dt.date.today().isoformat())
    ap.add_argument("--trocken", action="store_true")
    a = ap.parse_args()
    try:
        neu, ausschr = lauf(a.datum, a.trocken)
    except Exception as e:                      # nie stumm: Fehlerdatei fuer den PM (wie B-1)
        if not a.trocken:
            _fehler_melden(a.datum, "Unerwarteter Fehler: %s: %s" % (type(e).__name__, str(e)[:400]))
        print(f"Fehler: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Auftrag/Mandat-Treffer: {len(neu)}, Ausschreibungs-Landingpages geprueft: {len(ausschr)}")


if __name__ == "__main__":
    main()
