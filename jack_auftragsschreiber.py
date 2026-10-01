#!/usr/bin/env python3
"""F-44 (25.09.2026): JACK als Auftraggeber - Auftragsschreiber und Rueckmeldung. Kein Modellaufruf, 0 USD.

S-8 (Kanal sprache) legt einen vom Patron FREIGEGEBENEN Entwurf als JSON nach betrieb/auftrag_entwurf/ (Format:
betrieb/README_AUFTRAG_ENTWURF.md). Dieses Modul macht daraus eine Auftragsdatei im PM-Schema
(auftraege/pm_ausgang/<kanal>/<KENNUNG>_<kurz>.md), waehlt den Kanal (betrieb/kanaele.json), vergibt die Kennung
fortlaufend und kollisionsfrei und erzeugt spaeter aus der Meldung zwei Saetze fuer das Gespraech.

Sicherheitsregeln: ohne freigegeben=true und Freigabe-Beleg nie ein Auftrag; ohne Kostenzahl 0 USD; ueber der Kostengrenze
oder bei unklarem Kanal geht der Auftrag nach pm_pruefung/ (PM CHECK liest dort zuerst). Nichts wird geloescht oder ueberschrieben.
"""
import datetime as dt
import fcntl
import json
import os
import re
import shutil
import unicodedata
from decimal import Decimal, InvalidOperation
from pathlib import Path

HIER = Path(__file__).resolve().parent
ENTWURF = Path("betrieb") / "auftrag_entwurf"
MODELLE = ("Haiku", "Sonnet", "Opus")
AUFWAND = ("low", "medium", "high", "xhigh")
REGELN = ("Regeln: Deutsch, minimal-invasiv, Sicherung vor jeder Dateiänderung, nichts löschen/verschieben, kein Echtversand, "
          "keine neuen kostenpflichtigen Dienste, Neustart-Regel aus README_PM_POSTFACH.md, Suite ohne neue rote. Annahmen kennzeichnen. "
          "Unterschrift und Geldtransfer nie ohne „freigegeben“ des Patrons.")


MARKE_PUNKTE = 3         # F-51 (Vorschlag aus S-8): die Marke wiegt so viel wie drei Stichworte - Gleichstand mit Stichworten wird durch die Marke entschieden


class Abgelehnt(Exception):
    pass


# ------------------------------------------------------------------ Konfiguration und Kanalwahl
def konfiguration(root):
    p = Path(root) / "betrieb" / "kanaele.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise Abgelehnt("betrieb/kanaele.json fehlt oder ist kaputt")


def _wortanfang(stichwort, text):
    return re.search(r"(?<!\w)" + re.escape(stichwort.casefold()), text) is not None


def kanal_waehlen(entwurf, konf):
    """-> (kanal, grund). Regel: 1. Feld 'kanal', 2. Punkte aus Marke (+3, F-51) und Stichworten (je 1), 3. Gleichstand/null -> pm_pruefung."""
    kanaele = konf["kanaele"]
    unklar = konf.get("unklar_kanal", "pm_pruefung")
    wunsch = str(entwurf.get("kanal") or "").strip()
    if wunsch:
        if wunsch in kanaele:
            return wunsch, "Kanal im Entwurf genannt"
        return unklar, "Kanal '%s' im Entwurf unbekannt" % wunsch
    text = " ".join([str(entwurf.get(k) or "") for k in ("titel", "ziel", "thema", "ausgangslage")] +
                    [str(x) for x in entwurf.get("punkte") or []]).casefold()
    punkte = {}
    for name, k in kanaele.items():
        n = sum(1 for s in k.get("stichworte") or [] if _wortanfang(s, text))
        if n:
            punkte[name] = n
    marke = str(entwurf.get("marke") or "").strip()
    if marke in (konf.get("marke_zu_kanal") or {}):
        ziel = konf["marke_zu_kanal"][marke]
        punkte[ziel] = punkte.get(ziel, 0) + MARKE_PUNKTE
    if not punkte:
        return unklar, "kein Stichwort und keine Marke passt"
    rang = sorted(punkte.items(), key=lambda x: -x[1])
    if len(rang) > 1 and rang[0][1] == rang[1][1]:
        return unklar, "Gleichstand %s/%s (%d Treffer)" % (rang[0][0], rang[1][0], rang[0][1])
    return rang[0][0], "%d Treffer (Marke %s)" % (rang[0][1], marke or "-")


# ------------------------------------------------------------------ Kennungen
def _kennungen_vorhanden(root, praefix):
    """Alle bereits benutzten ganzen Nummern dieses Praefixes (Dateinamen in allen Kanaelen, erledigt/, pm_eingang/)."""
    root = Path(root)
    orte = [root / "auftraege" / "pm_ausgang", root / "abnahme" / "pm_eingang"]
    muster = re.compile(r"^" + re.escape(praefix) + r"(\d+)")
    nummern = set()
    for ort in orte:
        if not ort.is_dir():
            continue
        for p in ort.rglob("*") if ort.name == "pm_ausgang" else ort.iterdir():
            if p.is_file():
                m = muster.match(p.name)
                if m:
                    nummern.add(int(m.group(1)))
    return nummern


def kennung_naechste(root, praefix):
    n = _kennungen_vorhanden(root, praefix)
    return praefix + str(max(n) + 1 if n else 1)


def _slug(text, maximal=48):
    t = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("ascii")
    t = re.sub(r"[^A-Za-z0-9]+", "_", t).strip("_").lower()
    return (t[:maximal].rstrip("_")) or "auftrag"


# ------------------------------------------------------------------ Pruefen und Schreiben
def _kosten(entwurf, konf):
    roh = entwurf.get("kostenrahmen_usd")
    if roh in (None, ""):
        return Decimal("0"), False
    try:
        wert = Decimal(str(roh).replace(",", ".").strip())
    except InvalidOperation:
        raise Abgelehnt("kostenrahmen_usd ist keine Zahl: %r" % (roh,))
    if wert < 0:
        raise Abgelehnt("kostenrahmen_usd ist negativ")
    grenze = Decimal(str(konf.get("max_kostenrahmen_usd", "5.00")))
    return wert, wert > grenze


def _euro(d):
    return ("%.2f" % d).replace(".", ",")


GESPRAECHE = Path("betrieb") / "gespraeche.jsonl"
GESPRAECHE_MAX_BYTES = 8 * 1024 * 1024         # nur das Ende der Datei lesen (neueste Zeilen)


def sitzung_pruefen(root, entwurf):
    """F-51: Nur ein Entwurf aus einer ECHTEN Sitzung wird zum Auftrag (S-9 Prueflinien 3 und 4).
    Sitzung = {quelle: stimme|text, zeit, gespraech_id}; die gespraech_id muss in betrieb/gespraeche.jsonl in einer Zeile
    mit "herkunft": "patron" vorkommen (Tests und Proben schreiben "probe"), sonst abgelehnt."""
    s = entwurf.get("sitzung")
    if not (isinstance(s, dict) and s.get("quelle") in ("stimme", "text") and str(s.get("gespraech_id") or "").strip() and s.get("zeit")):
        raise Abgelehnt("keine echte Sitzung")
    gid = str(s["gespraech_id"]).strip()
    if not re.fullmatch(r"[0-9a-fA-F]{8,64}", gid):
        raise Abgelehnt("keine echte Sitzung: gespraech_id ist keine Kennung")
    datei = Path(root) / GESPRAECHE
    try:
        groesse = datei.stat().st_size
        with datei.open("rb") as f:
            f.seek(max(0, groesse - GESPRAECHE_MAX_BYTES))
            zeilen = f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        raise Abgelehnt("keine echte Sitzung: betrieb/gespraeche.jsonl nicht lesbar")
    for zeile in zeilen:
        if gid in zeile:
            try:
                if json.loads(zeile).get("herkunft") == "patron":
                    return
            except ValueError:
                continue
    raise Abgelehnt("keine echte Sitzung: gespraech_id nicht in gespraeche.jsonl mit Herkunft patron")


def pruefen(entwurf):
    if not isinstance(entwurf, dict):
        raise Abgelehnt("Entwurf ist kein JSON-Objekt")
    if entwurf.get("probe"):
        raise Abgelehnt("Probe-Entwurf: nie in einen Kanal")               # F-51 (S-9 Zeile 2)
    if entwurf.get("schema") != 1:
        raise Abgelehnt("schema muss 1 sein")
    if entwurf.get("freigegeben") is not True:
        raise Abgelehnt("nicht freigegeben (freigegeben ist nicht true) - ohne Freigabe des Patrons entsteht kein Auftrag")
    for feld in ("freigabe_zeit", "freigabe_satz", "titel", "ziel"):
        if not str(entwurf.get(feld) or "").strip():
            raise Abgelehnt("Pflichtfeld fehlt: " + feld)
    punkte = entwurf.get("punkte")
    if not isinstance(punkte, list) or not [p for p in punkte if str(p).strip()]:
        raise Abgelehnt("Pflichtfeld fehlt: punkte (mindestens ein Punkt)")
    if entwurf.get("modell") and str(entwurf["modell"]).capitalize() not in MODELLE:
        raise Abgelehnt("modell muss Haiku, Sonnet oder Opus sein")
    if entwurf.get("aufwand") and str(entwurf["aufwand"]).lower() not in AUFWAND:
        raise Abgelehnt("aufwand muss low, medium, high oder xhigh sein")


def _zeittext(iso):
    try:
        return dt.datetime.fromisoformat(str(iso)).strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return str(iso)


def auftragstext(entwurf, kennung, kanal, kosten, ueber_grenze, kanal_grund):
    modell = str(entwurf.get("modell") or "Sonnet").capitalize()
    aufwand = str(entwurf.get("aufwand") or "medium").lower()
    rahmen = ("%s USD (vom Patron im Gespräch freigegeben)" % _euro(kosten)) if kosten > 0 else "0 USD (nur lokale Arbeit)"
    titel = str(entwurf["titel"]).strip()
    herkunft = "Gespräch mit dem Patron %s, freigegeben %s" % (
        _zeittext(entwurf.get("gespraech_zeit") or entwurf["freigabe_zeit"]), _zeittext(entwurf["freigabe_zeit"]))
    punkte = [str(p).strip() for p in entwurf["punkte"] if str(p).strip()]
    z = ["AUFTRAG %s — %s — %s" % (kennung, titel.upper(), ("Rahmen " if kosten > 0 else "") + rahmen.split(" (")[0]),
         "Modell: %s, Aufwand %s. Kanal: %s. Erteilt: %s." % (modell, aufwand, kanal, dt.datetime.now().astimezone().strftime("%d.%m.%Y %H:%M")),
         "Herkunft: %s. Freigabe-Satz des Patrons: „%s“" % (herkunft, str(entwurf["freigabe_satz"]).strip()),
         "Kostenrahmen: %s." % rahmen]
    if ueber_grenze:
        z.append("PM-PRÜFUNG NÖTIG: der Kostenrahmen liegt über der Grenze in betrieb/kanaele.json; erst nach Prüfung durch PM CHECK verteilen.")
    if kanal == "pm_pruefung":
        z.append("PM-PRÜFUNG NÖTIG: Kanal nicht eindeutig (%s). PM CHECK wählt den Kanal und verschiebt die Datei." % kanal_grund)
    z += ["", "Ziel: " + str(entwurf["ziel"]).strip()]
    if str(entwurf.get("ausgangslage") or "").strip():
        z += ["", "Ausgangslage: " + str(entwurf["ausgangslage"]).strip()]
    z += ["", "Aufgabe:"] + ["%d. %s" % (i, p) for i, p in enumerate(punkte, 1)]
    ausschluss = [str(a).strip() for a in entwurf.get("ausschluesse") or [] if str(a).strip()]
    if ausschluss:
        z += ["", "Nicht Teil des Auftrags:"] + ["- " + a for a in ausschluss]
    z += ["", "Prüfpunkte:"] + ["P%02d Punkt %d ist erledigt; Beleg (Pfad oder Zahl) steht in der Meldung." % (i, i) for i in range(1, len(punkte) + 1)]
    if kosten > 0:
        z.append("P%02d Kosten gemeldet und höchstens %s USD." % (len(punkte) + 1, _euro(kosten)))
    z += ["", REGELN,
          "Meldung abnahme/pm_eingang/%s_MELDUNG.md: Ergebnis je Punkt mit Beleg, Kosten, Annahmen, offene Frage (falls eine Entscheidung nötig ist). "
          "Danach nach erledigt/." % kennung, ""]
    return "\n".join(z)


def schreiben(root, entwurf):
    """Freigegebener Entwurf (dict) -> Auftragsdatei. -> dict(kennung, kanal, datei, ...)."""
    root = Path(root)
    pruefen(entwurf)
    sitzung_pruefen(root, entwurf)                                          # F-51: nur echte Sitzung
    konf = konfiguration(root)
    kosten, ueber = _kosten(entwurf, konf)
    kanal, grund = kanal_waehlen(entwurf, konf)
    if ueber and kanal != konf.get("unklar_kanal", "pm_pruefung"):
        grund = "Kostenrahmen %s USD über der Grenze; ursprünglich %s" % (_euro(kosten), kanal)
        kanal = konf.get("unklar_kanal", "pm_pruefung")
    praefix = konf["kanaele"][kanal]["praefix"]
    ordner = root / "auftraege" / "pm_ausgang" / kanal
    ordner.mkdir(parents=True, exist_ok=True)
    kurz = _slug(entwurf.get("kurzname") or entwurf["titel"])
    (root / "betrieb").mkdir(exist_ok=True)
    # Sperrdatei: Kennung suchen UND Datei anlegen sind EIN Schritt (zwei gleichzeitige Entwuerfe bekommen nie dieselbe Kennung).
    with open(str(root / "betrieb" / "auftragsschreiber.sperre"), "a") as sperre:
        fcntl.flock(sperre, fcntl.LOCK_EX)
        for _ in range(50):                   # Zusatz: O_EXCL, nie ueberschreiben
            kennung = kennung_naechste(root, praefix)
            ziel = ordner / ("%s_%s.md" % (kennung, kurz))
            text = auftragstext(entwurf, kennung, kanal, kosten, ueber, grund)
            try:
                fd = os.open(str(ziel), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            except FileExistsError:
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
            return {"kennung": kennung, "kanal": kanal, "datei": str(ziel.relative_to(root)), "grund_kanal": grund,
                    "kostenrahmen_usd": str(kosten), "zeit": dt.datetime.now().astimezone().isoformat()}
    raise Abgelehnt("keine freie Kennung gefunden")


def verarbeiten(root=HIER):
    """Alle Entwuerfe in betrieb/auftrag_entwurf/*.json abarbeiten. -> Liste der Ergebnisse (auch Ablehnungen)."""
    root = Path(root)
    ordner = root / ENTWURF
    ergebnisse = []
    if not ordner.is_dir():
        return ergebnisse
    for datei in sorted(ordner.glob("*.json")):
        if datei.name.endswith(".ergebnis.json") or datei.is_symlink():
            continue
        try:
            entwurf = json.loads(datei.read_text(encoding="utf-8"))
            ergebnis = schreiben(root, entwurf)
            ziel_ordner, endung = ordner / "verarbeitet", ".ergebnis.json"
        except (Abgelehnt, ValueError, OSError) as fehler:
            ergebnis = {"abgelehnt": True, "grund": str(fehler)[:300], "datei": datei.name}
            ziel_ordner, endung = ordner / "abgelehnt", ".grund.txt"
        ziel_ordner.mkdir(exist_ok=True)
        ziel = ziel_ordner / datei.name
        if ziel.exists():                     # nie ueberschreiben
            ziel = ziel_ordner / (datei.stem + "_" + dt.datetime.now().strftime("%H%M%S") + datei.suffix)
        shutil.move(str(datei), str(ziel))
        if endung == ".grund.txt":
            ziel.with_name(ziel.stem + ".grund.txt").write_text(ergebnis["grund"] + "\n", encoding="utf-8")
        else:
            ziel.with_name(ziel.stem + ".ergebnis.json").write_text(json.dumps(ergebnis, ensure_ascii=False, indent=1), encoding="utf-8")
        ergebnisse.append(ergebnis)
    return ergebnisse


# ------------------------------------------------------------------ Rueckmeldung
def _meldung_finden(root, kennung):
    ordner = Path(root) / "abnahme" / "pm_eingang"
    if not ordner.is_dir():
        return None
    treffer = sorted(p for p in ordner.glob("%s_MELDUNG*.md" % kennung) if p.is_file())
    return treffer[-1] if treffer else None


def _erster_satz(text, maximal=220):
    text = re.sub(r"\s+", " ", re.sub(r"[`*_#]", "", text)).strip()
    m = re.search(r"^(.+?[.!?])(\s|$)", text)
    s = (m.group(1) if m else text)[:maximal].strip()
    return s if s.endswith((".", "!", "?")) else s + "."


def _ergebnissatz(zeile):
    """'# F-42 — Marken-Ansicht: nur die 11 echten Marken: ERLEDIGT (25.09.2026, 05:20)' -> 'Erledigt: Marken-Ansicht: nur die 11 echten Marken.'"""
    z = re.sub(r"^#+\s*", "", zeile).strip()
    z = re.sub(r"\s*\([^)]*\)\s*$", "", z)
    z = re.sub(r"^[A-Za-z]+-[\d.]+[a-z]?\s*[—–-]\s*", "", z)
    m = re.match(r"^(.*?):\s*([A-ZÄÖÜ][A-ZÄÖÜ .,/-]{3,})$", z)
    if m:
        status, titel = m.group(2).strip().capitalize(), m.group(1).strip()
        return "%s: %s." % (status, titel)
    return z.rstrip(".") + "."


def _entscheidungsfrage(text):
    """Erste Frage in einem Abschnitt, der eine Entscheidung verlangt (Frage/Offen/Entscheidung/Für den Patron)."""
    abschnitt = None
    for zeile in text.splitlines():
        if zeile.startswith("#"):
            abschnitt = re.search(r"frage|offen|entscheid|für den patron|fuer den patron|zu beachten", zeile, re.I) is not None
            continue
        if abschnitt and "?" in zeile:
            m = re.search(r"([^.!?]*\?)", zeile)
            if m:
                s = re.sub(r"[`*_]", "", m.group(1)).strip(" -•|")
                if len(s) > 12:
                    return s
    return None


def rueckmeldung(root, kennung, karte_anlegen=True):
    """Aus der Meldung zur Kennung zwei Saetze fuer das Gespraech. -> dict(gefunden, saetze, pm_geprueft, text, karte)."""
    root = Path(root)
    p = _meldung_finden(root, kennung)
    if not p:
        return {"gefunden": False, "saetze": [], "pm_geprueft": False, "text": "", "karte": None}
    text = p.read_text(encoding="utf-8", errors="replace")
    erste = next((z for z in text.splitlines() if z.startswith("#")), p.stem)
    saetze = [_ergebnissatz(erste)]
    frage = _entscheidungsfrage(text)
    if frage:
        saetze.append(frage)
    geprueft = "_geprueft" in p.name
    karte = None
    if frage and karte_anlegen:
        karte = _karte(root, kennung, frage, saetze[0], p)
    return {"gefunden": True, "meldung": str(p.relative_to(root)), "saetze": saetze, "pm_geprueft": geprueft,
            "text": " ".join(saetze) + " PM geprüft: %s." % ("ja" if geprueft else "nein"), "karte": karte}


def _karte(root, kennung, frage, ergebnis, meldung):
    name = "%s_RUECKMELDUNG_%s.md" % (dt.datetime.now().strftime("%Y-%m-%d"), kennung)
    if (Path(root) / "auftraege" / "freigabe" / name).exists():
        return name
    # F-78 (29.09.2026): echte v2-Werte statt der Altform (nur marke/auftrag, kein
    # projekt/eingegangen/an/kern/empfehlung/frist/dringlichkeit).
    import jack_freigaben
    v2 = {
        "projekt": "Kennung %s" % kennung, "marke": "JACK",
        "eingegangen": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "von": "JACK-Auftragsschreiber (F-44)",
        "an": "Patron", "art": "rueckmeldung", "betreff": "Rückmeldung %s" % kennung,
        "kern": ergebnis, "frage": frage,
        "empfehlung": "Meldung %s prüfen und Frage beantworten." % meldung.name,
        "frist": "keine", "dringlichkeit": "niedrig", "ablauf": "Antwort im Gespräch/Chat, keine Freigabe-Mechanik.",
    }
    pfad = jack_freigaben.karte_schreiben(root, v2, "\n".join([
        "## Auftrag", frage, "",
        "## Worum es geht", "%s Die Meldung dazu steht in %s." % (ergebnis, meldung.name), ""
    ]), herkunft="jack_auftragsschreiber._karte", dateiname=name)
    return pfad.name if pfad else ""


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2 and sys.argv[1] == "rueckmeldung":
        print(json.dumps(rueckmeldung(HIER, sys.argv[2], karte_anlegen="--karte" in sys.argv), ensure_ascii=False, indent=1))
    else:
        print(json.dumps(verarbeiten(HIER), ensure_ascii=False, indent=1))
