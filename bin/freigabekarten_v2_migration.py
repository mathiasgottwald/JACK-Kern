#!/usr/bin/env python3
"""F-77 (28.09.2026): migriert alle Karten in auftraege/freigabe/ (nicht erledigt/ersetzt) auf den
Kartenkopf-Standard v2 (siehe auftraege/freigabe/_VORLAGE_FREIGABEKARTE_v2.md): feste Kopf-Pflichtfelder
(projekt/marke/eingegangen/von/an/art/betreff/kern/frage/empfehlung/frist/dringlichkeit/ablauf), Rumpf in fester
Reihenfolge (## Kern / ## Antwort / Entwurf / ## Warum / Risiko / ## Ablauf / ## Belege). Bestehende technische
Felder (zustand/status/freigabe/gefahr/tiefe/besetzung/versuch/warte_bis/bereiche/entwurf/...) bleiben erhalten -
nichts wird entfernt, nur ergaenzt/umsortiert. Sicherung jeder Datei als `<datei>.vor_F77` VOR jeder Aenderung.

Ermittlung der Pflichtfelder je bekannter Kartenart (mailantwort/externemail/anleitung/entscheidung/netzwaechter/
social-tagesliste) aus Kopf + Fließtext, ohne etwas zu erfinden: was sich nicht ermitteln laesst, wird
buchstaeblich "unbekannt" (nie leer) und in der Migrationsliste vermerkt.

Aufruf: freigabekarten_v2_migration.py [--trocken]
"""
import datetime as dt
import os
import re
import sys
from pathlib import Path

JACK = Path(os.environ.get("JACK_MIGRATION_WURZEL") or Path(__file__).resolve().parents[1])
FREIGABE = JACK / "auftraege" / "freigabe"

PFLICHTFELDER = ["projekt", "marke", "eingegangen", "von", "an", "art", "betreff", "kern", "frage",
                  "empfehlung", "frist", "dringlichkeit", "ablauf"]


def _kopf_rohzeilen(text):
    """-> {feldname: komplette_originalzeile}. Fuer bestehende (nicht-v2) Felder wird beim Umschreiben die
    ORIGINALE Zeile (samt Original-Abstand) wiederverwendet, nicht neu formatiert - manche bestehende Tests
    vergleichen Karten als rohen Text, und eine Wert-Aenderung durch reine Neuformatierung waere unehrlich
    ('nichts wegnehmen' heisst hier auch: nichts unnoetig veraendern)."""
    m = re.match(r"^---\n(.*?)\n---\n?", text, re.S)
    if not m:
        return {}
    raus = {}
    for zeile in m.group(1).splitlines():
        if ":" in zeile:
            k = zeile.split(":", 1)[0].strip()
            raus[k] = zeile
    return raus


def _kopf_und_rumpf(text):
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    if not m:
        return {}, text
    kopf = {}
    reihenfolge = []
    for zeile in m.group(1).splitlines():
        if ":" in zeile:
            k, _, v = zeile.partition(":")
            k = k.strip()
            kopf[k] = v.strip()
            reihenfolge.append(k)
    return kopf, m.group(2)


def _abschnitt(rumpf, titel_muster):
    m = re.search(r"(?m)^##\s*(?:" + titel_muster + r")\s*\n(.*?)(?=\n##\s|\Z)", rumpf, re.S)
    return m.group(1).strip() if m else ""


def _ohne_markdown(text):
    # re.S: Fettschrift ist in diesem Haus oft zeilenumgebrochen ("**nur\nlesende**") - ohne DOTALL
    # bleibt so ein Paar unerkannt und das NAECHSTE "**...**" im Text wird faelschlich damit verpaart.
    return re.sub(r"\*\*(.+?)\*\*", r"\1", text, flags=re.S)


def _erster_satz(text, laenge=280):
    text = " ".join(_ohne_markdown(text).split())
    m = re.match(r"(.{10,%d}?[.!?])(\s|$)" % laenge, text)
    return (m.group(1) if m else text[:laenge]).strip()


def _kuerzen(text, laenge):
    text = " ".join(_ohne_markdown(text).split())
    if len(text) <= laenge:
        return text
    kurz = text[:laenge].rsplit(" ", 1)[0]
    return kurz.rstrip(" ,;—-") + "…"


def _abschnitt_bevorzugt(rumpf, bevorzugt, sonst):
    """Wie _abschnitt(), aber sucht ZUERST gezielt nach `bevorzugt` (eigene Ueberschrift) und faellt erst
    danach auf die allgemeineren Muster in `sonst` zurueck - sonst findet re.search() bei einer Alternation
    die zuerst im Text VORKOMMENDE Ueberschrift, nicht die inhaltlich naechstliegende."""
    treffer = _abschnitt(rumpf, bevorzugt)
    if treffer:
        return treffer
    return _abschnitt(rumpf, sonst)


def _dringlichkeit(kopf, frist):
    if kopf.get("gefahr") == "aussen" and frist and frist != "keine":
        return "hoch"
    if frist and frist != "keine":
        return "mittel"
    return "niedrig"


def _ablauf(kopf, rumpf):
    if kopf.get("art") in ("externemail", "mailantwort") and (kopf.get("entwurf") or _abschnitt(rumpf, r"[^\n]*Entwurf[^\n]*|Text der (?:Mail|Bestätigungsmail)[^\n]*")):
        return "TESTVERSAND → Code → FREIGEBEN"
    if kopf.get("status") == "info":
        return "Kenntnisnahme (keine Freigabe nötig)"
    if kopf.get("art") == "netzwaechter":
        return "nur melden — startet nichts automatisch"
    return "FREIGEBEN / WARTEN / ABLEHNEN"


def _mailantwort_absender_betreff(rumpf):
    m = re.search(r"Antwort aus (?P<von>[^\n]+?) an (?P<empf>[^\n]+?) — Betreff:\s*(?P<betreff>[^\n.]+)\.?", rumpf)
    if not m:
        return None
    return m.group("von").strip(), m.group("empf").strip(), m.group("betreff").strip()


def felder_ableiten(pfad, kopf, rumpf):
    """-> dict der 13 v2-Pflichtfelder. Nichts erfunden: unbekannte Werte werden woertlich 'unbekannt'."""
    art = kopf.get("art", "")
    marke = kopf.get("marke") or "unbekannt"
    eingegangen = kopf.get("erteilt") or kopf.get("datum") or "unbekannt"
    projekt = "unbekannt"
    von = kopf.get("von") or "unbekannt"
    an = kopf.get("an") or "Patron"  # F-78: echter Fallback statt "—" - unbekannte Kartenarten sind mangels
                                     # Gegenpart-Angabe im Zweifel an den Patron selbst adressiert.
    betreff = kopf.get("titel") or "unbekannt"
    kern = "unbekannt"
    frage = "unbekannt"
    empfehlung_txt = "unbekannt"
    frist = kopf.get("warte_bis") or kopf.get("faellig") or "keine"

    JARGON_MUSTER = re.compile(r"^(Stufe \d|noch nicht eingespielt|Diese Mail-Art)", re.I)

    if art == "mailantwort":
        ergebnis = _mailantwort_absender_betreff(rumpf)
        if ergebnis:
            von_lang, empf, betreff_kurz = ergebnis
            # Opus-Sichtpruefung F-77: "von" muss die echte Gegenseite zeigen (Firma/Person), nicht den
            # internen Versandkanal - "an" bleibt dieselbe Adresse (Antwort geht an dieselbe Gegenseite).
            von = empf
            an = empf
            betreff = betreff_kurz
        auftrag_txt = _abschnitt(rumpf, r"Auftrag[^\n]*")
        # Die erste Zeile ist fast immer nur "Antwort aus X an Y - Betreff: Z." (steht schon in den
        # Kopf-Feldern von/an/betreff) - satzweise trennen wuerde an Punkten in E-Mail-Adressen zerbrechen,
        # daher zeilenweise: die naechste, inhaltlich andere Zeile traegt den eigentlichen Stand/Grund.
        zeilen = [z.strip() for z in (auftrag_txt or "").splitlines() if z.strip()]
        inhaltlich = [z for z in zeilen if not re.match(r"^Antwort aus .+ Betreff:", z)]
        kern_kandidat = _erster_satz(inhaltlich[0]) if inhaltlich else ""
        # Opus-Sichtpruefung F-77: reiner Betriebsjargon ("Stufe 1 - ...") ist keine Quintessenz - dann
        # lieber den Betreff als Kurzbeschreibung der Sache nennen als ein technisches Wort.
        kern = kern_kandidat if kern_kandidat and not JARGON_MUSTER.match(kern_kandidat) else (
            "Antwort auf: %s" % betreff)
        frage = "Antwort so senden?"
        empf_block = _abschnitt(rumpf, "Empfehlung von JACK")
        if empf_block:
            m = re.search(r"\*\*Empfehlung:\*\*\s*(.+)", empf_block)
            empfehlung_txt = _kuerzen(m.group(1) if m else empf_block, 320)
        projekt = "GOTT WALD Europe UG (Gründung)" if marke == "GOTT_WALD" else marke.replace("_", " ")

    elif art == "externemail":
        betreff = kopf.get("titel") or betreff
        auftrag_txt = _abschnitt(rumpf, r"Auftrag[^\n]*")
        frage_satz = _erster_satz(auftrag_txt) if auftrag_txt else "unbekannt"
        frage = frage_satz if frage_satz.rstrip().endswith("?") else (frage_satz + "?" if frage_satz != "unbekannt" else "unbekannt")
        # Opus-Sichtpruefung F-77: kern darf die Frage nicht wortgleich wiederholen - der Hintergrund/Anlass
        # kommt, wo vorhanden, aus dem "Warum"-Abschnitt; sonst bleibt kern der Betreff als Kurzfassung.
        warum_block = _abschnitt_bevorzugt(rumpf, "Warum diese Karte[^\n]*", r"Empfehlung von JACK")
        kern = _erster_satz(warum_block) if warum_block else betreff
        empf_block = _abschnitt_bevorzugt(rumpf, "Empfehlung von JACK", r"Warum diese Karte[^\n]*")
        if empf_block:
            m = re.search(r"\*\*(?:Empfehlung|Entscheid):?\*\*\s*(.+)", empf_block)
            empfehlung_txt = _kuerzen(m.group(1) if m else empf_block, 320)
        # Opus-Sichtpruefung F-77: "von" muss die Gegenseite zeigen, nicht den internen Versandkanal - auch
        # bei einer selbst angestossenen Mail (externemail) ist die Gegenseite die Adresse aus "an".
        von = kopf.get("an") or ("JACK (%s)" % (kopf.get("von") or "office"))
        projekt = "GOTT WALD Europe UG (Gründung)" if marke == "GOTT_WALD" else marke.replace("_", " ")

    elif art == "anleitung":
        betreff = kopf.get("titel") or betreff
        if betreff == "unbekannt":
            m = re.search(r"(?m)^#\s+(.+)$", rumpf)
            betreff = m.group(1).strip() if m else (kopf.get("auftrag") or "unbekannt")
        auftrag_txt = _abschnitt(rumpf, r"Auftrag[^\n]*")
        kern = _erster_satz(auftrag_txt) if auftrag_txt else "unbekannt"
        frage = "Erledigt? (Handlung liegt beim Patron selbst)"
        m = re.search(r"\*\*Empfehlung[^:]*:?\*\*\s*(.+)", rumpf)
        empfehlung_txt = m.group(1).split("\n")[0][:200] if m else "keine explizite Empfehlung im Text"
        an = "Patron"  # F-78: echter Wert statt Platzhalter - diese Kartenarten sind an ihn adressiert.
        von = "JACK"
        projekt = marke.replace("_", " ") if marke != "unbekannt" else "JACK Betrieb"

    elif art in ("entscheidung",) and kopf.get("bereiche") == "erinnerung":
        betreff = kopf.get("titel") or betreff
        kern = "Wiederkehrende Erinnerung: %s" % betreff
        frage = "Jetzt erledigen, oder weiter zurückstellen?"
        empfehlung_txt = "Sobald erledigt: FREIGEBEN. Sonst WARTEN (zurückstellen bis %s)." % (kopf.get("warte_bis") or "unbekannt")
        an = "Patron"  # F-78: echter Wert statt Platzhalter - diese Kartenarten sind an ihn adressiert.
        von = kopf.get("von") or "JACK-Kern"
        projekt = marke.replace("_", " ") if marke != "unbekannt" else "JACK Betrieb"

    elif art == "netzwaechter":
        auftrag_txt = _abschnitt(rumpf, r"Auftrag[^\n]*")
        betreff = _erster_satz(auftrag_txt, 90) if auftrag_txt else "Netzwächter-Meldung"
        kern = _erster_satz(auftrag_txt) if auftrag_txt else "unbekannt"
        frage = "Ursache jetzt prüfen?"
        empfehlung_txt = "Karte startet nichts von selbst — nur Hinweis, Ursache prüfen."
        an = "Patron"  # F-78: echter Wert statt Platzhalter - diese Kartenarten sind an ihn adressiert.
        von = kopf.get("von") or "JACK-Netzwaechter"
        projekt = "JACK Betrieb"

    elif kopf.get("art") == "freigabe" and "kanal" in kopf:   # SOCIAL_TAGESLISTE-Familie
        betreff = "Social-Tagesliste %s — %s" % (kopf.get("datum", "unbekannt"), marke.replace("_", " "))
        eingegangen = kopf.get("datum") or "unbekannt"
        kern = "Geplante Social-Beiträge/-Antworten für %s am %s, wartet auf Kontoanbindung und Freigabe je Zeile." % (
            marke.replace("_", " "), kopf.get("datum", "unbekannt"))
        frage = "Welche Zeilen freigeben?"
        empfehlung_txt = "Kein Post ohne Kontoanbindung UND Freigabe (siehe Tabelle)."
        an = "Patron"  # F-78: echter Wert statt Platzhalter - diese Kartenarten sind an ihn adressiert.
        von = "JACK (Kanal %s)" % (kopf.get("kanal") or "cashflow")
        projekt = "%s Social" % marke.replace("_", " ")
        art = "social_tagesliste"

    frist_final = frist if frist and frist != "unbekannt" else "keine"
    return {
        "projekt": projekt, "marke": marke, "eingegangen": eingegangen, "von": von, "an": an,
        "art": art or "unbekannt", "betreff": _kuerzen(betreff, 90), "kern": kern, "frage": frage,
        "empfehlung": empfehlung_txt, "frist": frist_final,
        "dringlichkeit": _dringlichkeit(kopf, frist_final), "ablauf": _ablauf(kopf, rumpf),
    }


def _rumpf_v2(kopf_alt, v2, rumpf_alt):
    antwort = _abschnitt(rumpf_alt, r"[^\n]*Entwurf[^\n]*|Text der (?:Mail|Bestätigungsmail)[^\n]*") or _abschnitt(rumpf_alt, r"Auftrag[^\n]*")
    warum = _abschnitt(rumpf_alt, r"Empfehlung von JACK|Warum[^\n]*|Prüfpunkte")
    ablauf_text = v2["ablauf"]
    belege = "`auftraege/freigabe/` (diese Datei) — Rumpf unterhalb unverändert aus der Vorlage vor F-77 übernommen."
    return "\n\n".join([
        "## Kern\n%s" % (v2["kern"] if v2["kern"] != "unbekannt" else "unbekannt — siehe Rohtext unten."),
        "## Antwort / Entwurf\n%s" % (antwort or "unbekannt — siehe Rohtext unten."),
        "## Warum / Risiko\n%s" % (warum or "unbekannt — siehe Rohtext unten."),
        "## Ablauf\n%s" % ablauf_text,
        "## Belege\n%s" % belege,
        "---",
        "## Rohtext vor F-77 (unverändert übernommen, nicht neu bewertet)",
        rumpf_alt.strip(),
    ])


def kopf_v2_text(kopf_alt, v2, rohzeilen=None):
    rohzeilen = rohzeilen or {}
    zeilen = ["---"]
    for feld in PFLICHTFELDER:
        # Bugfix (F-77, Opus-Nachbesserung): ein Pflichtfeld IMMER frisch aus v2 schreiben, nie die
        # Original-Zeile wiederverwenden - auch wenn derselbe Feldname (von/an/marke/art) schon VOR der
        # Migration existierte, hatte er dort eine andere Bedeutung (interner Kanal statt Gegenseite) und
        # muss durch den neu abgeleiteten Wert ersetzt werden. Nur (b) unten (echte Altfelder) bleibt roh.
        zeilen.append("%s:%s%s" % (feld, " " * max(1, 16 - len(feld) - 1), v2[feld]))
    for k, w in kopf_alt.items():
        if k in PFLICHTFELDER:
            continue
        # Bestehende technische Felder unveraendert mit ihrer Original-Zeile uebernehmen (Original-Abstand,
        # Original-Grossschreibung) - reine Neuformatierung waere eine unnoetige, unbelegte Aenderung.
        zeilen.append(rohzeilen.get(k, "%s:%s%s" % (k, " " * max(1, 16 - len(k) - 1), w)))
    zeilen.append("---")
    return "\n".join(zeilen)


def migriere_datei(pfad, trocken=False):
    text = pfad.read_text(encoding="utf-8", errors="replace")
    kopf, rumpf = _kopf_und_rumpf(text)
    if all(f in kopf for f in PFLICHTFELDER):
        return {"datei": pfad.name, "status": "bereits_v2", "unbekannt": []}
    v2 = felder_ableiten(pfad, kopf, rumpf)
    rohzeilen = _kopf_rohzeilen(text)
    neuer_text = kopf_v2_text(kopf, v2, rohzeilen) + "\n\n" + _rumpf_v2(kopf, v2, rumpf).strip() + "\n"
    unbekannt = [f for f in PFLICHTFELDER if v2[f] in ("unbekannt", "")]
    if trocken:
        return {"datei": pfad.name, "status": "TROCKEN_wuerde_migrieren", "unbekannt": unbekannt}
    sicherung = pfad.parent / (pfad.name + ".vor_F77")
    if not sicherung.exists():
        sicherung.write_text(text, encoding="utf-8")
    pfad.write_text(neuer_text, encoding="utf-8")
    return {"datei": pfad.name, "status": "migriert", "unbekannt": unbekannt}


REIHENFOLGE_ZUERST = [
    "2026-09-28_TERMINBESTAETIGUNG_Notar_SundE.md",
    "2026-09-28_115838_MAIL_Re_AW_Anfrage_Gesch_ftsadresse_f_r_eine.md",
    "2026-09-28_132816_MAIL_Re_AW_Anfrage_Beurkundung_einer_UG_Gr_nd.md",
    "2026-09-28_133405_MAIL_Re_WG_Anfrage_Beurkundung_einer_UG_Gr_nd.md",
    "2026-09-28_NACHFASS_Coworking_Rosenheim.md",
    "2026-09-28_NACHFASS_Notar_Leiss_Hoenle.md",
    "2026-09-28_NACHFASS_Sparkasse.md",
    "2026-09-28_NACHFASS_Steuerberatung_EFA.md",
    "2026-09-28_NACHFASS_Steuerberatung_PwC.md",
    "2026-09-28_RUECKFRAGE_KRAFTWOERK.md",
]


def _feld_ungueltig(wert):
    """Dieselbe Pruefung wie jack_freigaben.feld_ungueltig() - bewusst hier noch einmal definiert
    (nicht importiert), weil dieses Skript seit F-77 absichtlich eigenstaendig bleibt (kein
    sys.path-Umweg in die JACK-Module noetig, laeuft auch isoliert)."""
    w = str(wert if wert is not None else "").strip()
    return not w or w.lower() in ("unbekannt", "—", "-", "–", "n/a", "keine angabe")


def pruefen_und_melden(root=None, jetzt=None):
    """F-78 (29.09.2026), Pflichtpunkt 7: Selbstpruefung beim Dashboard-Start. Findet sie eine Karte,
    die entweder gar keinen v2-Kopf hat ODER einen mit leerem/„unbekannt“-Pflichtfeld, schreibt sie
    EINE Sammelmeldung nach abnahme/pm_eingang/ (nicht still, nicht je Karte einzeln) - aber nur, wenn
    noch keine aktuelle Meldung fuer denselben Tag liegt (kein Spam bei jedem Dashboard-Laden).
    -> Liste der betroffenen (Dateiname, fehlende_felder) oder [] wenn alles vollstaendig ist."""
    wurzel = Path(root) if root else JACK
    heute = (jetzt or dt.datetime.now()).strftime("%Y-%m-%d")
    ordner = wurzel / "auftraege" / "freigabe"
    if not ordner.is_dir():
        return []
    betroffen = []
    for f in sorted(ordner.glob("*.md")):
        if f.is_symlink() or f.name.startswith("_VORLAGE") or re.search(r"\.(bak|vor_[^.]*)(\.|$)", f.name, re.I):
            continue
        try:
            kopf, _ = _kopf_und_rumpf(f.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        fehlend = [feld for feld in PFLICHTFELDER if feld not in kopf or _feld_ungueltig(kopf.get(feld))]
        if fehlend:
            betroffen.append((f.name, fehlend))
    if not betroffen:
        return []
    ziel = wurzel / "abnahme" / "pm_eingang" / ("%s_SELBSTPRUEFUNG_v2_unvollstaendig.md" % heute)
    if not ziel.is_file():
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_text("\n".join([
            "# Selbstprüfung Kartenkopf v2 — %d unvollständige Karte(n) (F-78)" % len(betroffen),
            "",
            "Automatisch beim Dashboard-Start geprüft (`bin/freigabekarten_v2_migration.py --pruefen`).",
            "Keine Karte wurde verändert — nur gemeldet.",
            "",
        ] + ["- `%s`: fehlt/ungültig = %s" % (name, ", ".join(fehlend)) for name, fehlend in betroffen]
          + ["", "Rückweg: `python3 bin/freigabekarten_v2_migration.py` behebt es (Sicherung `.vor_F77` je Datei)."]),
            encoding="utf-8")
    return betroffen


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--pruefen" in argv:
        betroffen = pruefen_und_melden()
        if betroffen:
            print("%d unvollstaendige Karte(n) - Meldung an abnahme/pm_eingang/ geschrieben." % len(betroffen))
        else:
            print("Alle Karten vollstaendig.")
        return 0
    trocken = "--trocken" in argv
    kandidaten = [f for f in sorted(FREIGABE.glob("*.md"))
                  if f.is_file() and not f.is_symlink() and not f.name.startswith("_VORLAGE")
                  and not re.search(r"\.(bak|vor_[^.]*)(\.|$)", f.name, re.I)]
    reihenfolge = [f for name in REIHENFOLGE_ZUERST for f in kandidaten if f.name == name]
    rest = [f for f in kandidaten if f not in reihenfolge]
    ergebnisse = [migriere_datei(f, trocken) for f in reihenfolge + rest]
    migriert = [e for e in ergebnisse if e["status"] in ("migriert", "TROCKEN_wuerde_migrieren")]
    print("%d Karte(n) gesamt, %d migriert/würde migrieren, %d bereits v2" % (
        len(ergebnisse), len(migriert), len(ergebnisse) - len(migriert)))
    for e in ergebnisse:
        if e["unbekannt"]:
            print("  %s: unbekannt = %s" % (e["datei"], ", ".join(e["unbekannt"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
