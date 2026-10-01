#!/usr/bin/env python3
"""Guthaben-Wache (Block 8, Teil A und B).

Anthropic liefert **keinen** Kontostand ueber eine Schnittstelle. Es wird
deshalb auch keiner abgerufen - wer einen erfindet, erfindet Geld. Stattdessen
traegt der Patron ein, was er aufgeladen hat; JACK zieht jeden gemessenen
API-Lauf davon ab und sagt, wie weit es noch reicht.

Grundsatz aus PATRONOS 25, vom Patron am 16.09.2026 uebernommen:
Unbekannt heisst "unbekannt" mit Quelle - nie geschaetzt ohne Kennzeichnung.

Nur Bordmittel. Keine neue Abhaengigkeit.
"""
import datetime as dt
import json
import sys
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

_HIER = str(Path(__file__).resolve().parent)
if _HIER not in sys.path:
    sys.path.insert(0, _HIER)

import jack_betrieb as b
import jack_kosten

DATEI = "guthaben.json"
FENSTER_TAGE = 7          # Zeitraum fuer den Durchschnittsverbrauch

STANDARD = {
    "schema": 1,
    "hinweis": ("Was der Patron beim Anbieter aufgeladen hat. Anthropic gibt "
                "keinen Kontostand heraus; dies ist die einzige Quelle. Jeder "
                "Eintrag: betrag_usd, datum (JJJJ-MM-TT), notiz. JACK zieht die "
                "gemessenen API-Laeufe ab dem Datum des LETZTEN Eintrags ab. "
                "Schwellen sind Anteile des letzten Aufladebetrags."),
    "aufladungen": [],
    "schwellen": {"warnung": 0.20, "dringend": 0.10},
}


def pfad(root):
    return b.area(root) / DATEI


def lesen(root):
    p = pfad(root)
    try:
        if p.is_symlink():
            raise ValueError("Guthabendatei darf kein Verweis sein")
        daten = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(STANDARD)
    if not isinstance(daten, dict):
        return dict(STANDARD)
    fertig = dict(STANDARD)
    fertig.update(daten)
    if not isinstance(fertig.get("aufladungen"), list):
        fertig["aufladungen"] = []
    return fertig


def schreiben(root, daten):
    from jack_speicher import atomic_bytes
    atomic_bytes(pfad(root),
                 (json.dumps(daten, ensure_ascii=False, indent=1) + "\n").encode())
    return daten


def aufladen(root, betrag_usd, datum=None, notiz=""):
    """Der Patron traegt ein, was er aufgeladen hat. JACK erfindet nie etwas."""
    try:
        betrag = Decimal(str(betrag_usd))
    except (InvalidOperation, TypeError):
        raise ValueError("Betrag ist keine Zahl")
    if not betrag.is_finite() or betrag <= 0 or betrag > Decimal("100000"):
        raise ValueError("Betrag ist unglaubwuerdig")
    tag = str(datum or b.now().date())
    try:
        dt.date.fromisoformat(tag)
    except ValueError:
        raise ValueError("Datum muss JJJJ-MM-TT sein")
    daten = lesen(root)
    daten["aufladungen"] = (daten.get("aufladungen") or []) + [
        {"betrag_usd": str(betrag), "datum": tag, "notiz": str(notiz or "")[:200],
         "eingetragen": b.now().isoformat()}]
    schreiben(root, daten)
    protokoll(root, "guthaben_eingetragen", betrag_usd=str(betrag), datum=tag)
    return stand(root)


def kontostand_abgleichen(root, betrag_usd, beobachtet, quelle, notiz=""):
    """Abgelesener USD-Kontostand, keine Zahlung und keine Umrechnung."""
    try:
        betrag = Decimal(str(betrag_usd))
        zeit = dt.datetime.fromisoformat(str(beobachtet))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("Betrag oder Beobachtungszeit ungueltig")
    if not betrag.is_finite() or betrag < 0 or betrag > Decimal("100000"):
        raise ValueError("Betrag ist unglaubwuerdig")
    if zeit.tzinfo is None or zeit > b.now():
        raise ValueError("Beobachtungszeit braucht Zeitzone und darf nicht in der Zukunft liegen")
    if not isinstance(quelle, str) or not quelle.strip():
        raise ValueError("Ein abgelesener Kontostand braucht eine Quelle")
    daten = lesen(root)
    eintrag = {"art": "kontostand", "betrag_usd": str(betrag),
               "datum": zeit.astimezone(b.now().tzinfo).date().isoformat(),
               "beobachtet": zeit.isoformat(), "quelle": quelle[:300],
               "notiz": str(notiz or "")[:300], "eingetragen": b.now().isoformat()}
    # Dieselbe Beobachtung darf bei einer Wiederholung nicht doppelt auftauchen.
    if not any(r.get("art") == "kontostand" and r.get("beobachtet") == eintrag["beobachtet"]
               and r.get("betrag_usd") == str(betrag) and r.get("quelle") == eintrag["quelle"]
               for r in daten.get("aufladungen", [])):
        daten["aufladungen"] = (daten.get("aufladungen") or []) + [eintrag]
        schreiben(root, daten)
        protokoll(root, "kontostand_abgeglichen", betrag_usd=str(betrag),
                  beobachtet=zeit.isoformat(), quelle=quelle[:300])
    return stand(root)


def _nach_beobachtung(zeit, beobachtet):
    if not beobachtet:
        return True
    try:
        wert = dt.datetime.fromisoformat(str(zeit))
        return wert.tzinfo is not None and wert > dt.datetime.fromisoformat(beobachtet)
    except (TypeError, ValueError):
        return False


def _vergleichszeit(zeit):
    try:
        wert = dt.datetime.fromisoformat(str(zeit))
        if wert.tzinfo is not None:
            return wert.astimezone(dt.timezone.utc).isoformat()
    except (TypeError, ValueError):
        pass
    return str(zeit or "")


def protokoll(root, art, **felder):
    try:
        e = {"zeit": b.now().isoformat(), "art": art}
        e.update(felder)
        with (b.area(root) / "guthaben.jsonl").open("a", encoding="utf-8") as d:
            d.write(json.dumps(e, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ------------------------------------------------------------------ Verbrauch
def _betraege_ab(root, ab_tag, beobachtet=None):
    """Alle gemeldeten Betraege ab einem Tag, je Kalendertag.

    Gezaehlt wird aus dem zentralen Verbrauchsbuch UND aus dem Arbeiterbuch;
    je Tag zaehlt das hoehere der beiden - dieselbe Regel wie beim Tagesdeckel.
    Die Buecher ueberschneiden sich; Summieren wuerde doppelt zaehlen.
    """
    zentral, arbeiter = {}, {}
    byid = {}
    for row in jack_kosten.rows(root):
        ident = row.get("id")
        if not ident:
            continue
        if row.get("ereignis") == "start":
            byid.setdefault(ident, row)
        else:
            byid[ident] = row
    for r in byid.values():
        if r.get("historisch") or r.get('abrechnung') != 'api' or r.get('anbieter') != 'anthropic':
            continue
        tag = str(r.get("zeit", ""))[:10]
        if tag < ab_tag or not _nach_beobachtung(r.get("ende") or r.get("zeit"), beobachtet):
            continue
        wert = r.get('usd_gemeldet')
        if wert is None:
            wert = r.get('usd_geschaetzt')
        if wert is None:
            wert, _ = jack_kosten.schaetzung(root, r.get('modell'), r.get('verbrauch'))
        if wert is None:
            continue
        try:
            wert = Decimal(str(wert))
            if wert.is_finite() and wert >= 0:
                zentral[tag] = zentral.get(tag, Decimal(0)) + wert
        except InvalidOperation:
            continue
    quelle = Path(root) / "arbeiter_api_laeufe.jsonl"
    try:
        for zeile in quelle.read_text(encoding="utf-8").splitlines():
            if not zeile.strip():
                continue
            r = json.loads(zeile)
            tag = str(r.get("zeit") or "")[:10]
            if (not tag or tag < ab_tag or r.get("total_cost_usd") is None
                    or not _nach_beobachtung(r.get("zeit"), beobachtet)):
                continue
            wert = Decimal(str(r["total_cost_usd"]))
            if wert.is_finite() and wert >= 0:
                arbeiter[tag] = arbeiter.get(tag, Decimal(0)) + wert
    except (OSError, ValueError):
        pass
    tage = {}
    for tag in set(zentral) | set(arbeiter):
        tage[tag] = max(zentral.get(tag, Decimal(0)), arbeiter.get(tag, Decimal(0)))
    return tage


def stand(root):
    """Reststand, Verbrauch der letzten sieben Tage, Reichweite in Tagen."""
    daten = lesen(root)
    aufladungen = daten.get("aufladungen") or []
    heute = b.now().date()
    if not aufladungen:
        return {"zeit": b.now().isoformat(), "bekannt": False, "ampel": "weiss",
                "satz": ("Kein Guthaben eingetragen. Anthropic gibt keinen "
                         "Kontostand heraus - ohne Eintrag ist der Reststand "
                         "unbekannt, nicht null."),
                "aufgeladen_usd": None, "verbraucht_usd": None, "rest_usd": None,
                "verbrauch_7_tage_usd": None, "je_tag_usd": None,
                "reichweite_tage": None, "quelle": "betrieb/guthaben.json (leer)"}
    letzte = sorted(aufladungen, key=lambda a: (str(a.get("datum", "")),
                                               _vergleichszeit(a.get("beobachtet") or a.get("eingetragen"))))[-1]
    ab_tag = str(letzte.get("datum") or "")
    try:
        dt.date.fromisoformat(ab_tag)
    except ValueError:
        # Kein (lesbares) Aufladedatum: unbekannt, deshalb wie heute behandeln.
        protokoll(root, "guthaben_ohne_datum", eintrag_eingetragen=letzte.get("eingetragen"),
                  warnung="Aufladung ohne lesbares Feld datum - Aufladedatum unbekannt, wie heute behandelt")
        ab_tag = heute.isoformat()
    try:
        betrag = Decimal(str(letzte["betrag_usd"]))
        if not betrag.is_finite():
            raise ValueError
    except (KeyError, InvalidOperation, ValueError):
        # Ohne Betrag gibt es keinen Ausgangspunkt: Rest unbekannt, nicht null.
        protokoll(root, "guthaben_ohne_betrag", eintrag_eingetragen=letzte.get("eingetragen"),
                  warnung="Aufladung ohne lesbaren betrag_usd - Reststand unbekannt")
        return {"zeit": b.now().isoformat(), "bekannt": False, "ampel": "weiss",
                "satz": "Eingetragene Aufladung ohne lesbaren Betrag - Reststand unbekannt, nicht null.",
                "aufgeladen_usd": None, "verbraucht_usd": None, "rest_usd": None,
                "verbrauch_7_tage_usd": None, "je_tag_usd": None,
                "reichweite_tage": None, "quelle": "betrieb/guthaben.json (Betrag fehlt)"}
    beobachtet = letzte.get("beobachtet") if letzte.get("art") == "kontostand" else None
    tage = _betraege_ab(root, ab_tag, beobachtet=beobachtet)
    verbraucht = sum(tage.values(), Decimal(0))
    rest = betrag - verbraucht
    grenze = (heute - dt.timedelta(days=FENSTER_TAGE - 1)).isoformat()
    fenster = sum((wert for tag, wert in tage.items() if tag >= grenze), Decimal(0))
    # Nur volle Tage seit dem Aufladen zaehlen, mindestens einer.
    seit = max(1, (heute - dt.date.fromisoformat(ab_tag)).days + 1)
    tage_im_fenster = min(FENSTER_TAGE, seit)
    je_tag = (fenster / tage_im_fenster) if tage_im_fenster else Decimal(0)
    reichweite = None
    if je_tag > 0:
        reichweite = int(max(Decimal(0), rest) / je_tag)
    schwellen = daten.get("schwellen") or STANDARD["schwellen"]
    anteil = (rest / betrag) if betrag else Decimal(0)
    if rest <= 0:
        ampel = "rot"
        satz = ("Rechnerischer Rest aufgebraucht: %s von %s USD verbraucht. "
                "Bitte den echten Kontostand beim Anbieter pruefen."
                % (_z(verbraucht), _z(betrag)))
    elif anteil <= Decimal(str(schwellen.get("dringend", 0.10))):
        ampel = "rot"
        satz = ("Rechnerischer Rest %s USD (%d %%). Reichweite %s. Kontostand pruefen."
                % (_z(rest), int(anteil * 100), _reichweite(reichweite)))
    elif anteil <= Decimal(str(schwellen.get("warnung", 0.20))):
        ampel = "gelb"
        satz = ("Rechnerischer Rest %s USD (%d %%). Reichweite %s."
                % (_z(rest), int(anteil * 100), _reichweite(reichweite)))
    else:
        ampel = "gruen"
        satz = ("Rechnerischer Rest %s USD von %s USD, Reichweite %s."
                % (_z(rest), _z(betrag), _reichweite(reichweite)))
    if beobachtet:
        satz += " Ausgangspunkt: abgelesener Kontostand vom %s; nur danach erfasster Verbrauch abgezogen." % beobachtet
    return {"zeit": b.now().isoformat(), "bekannt": True, "ampel": ampel, "satz": satz,
            "aufgeladen_usd": _z(betrag), "aufgeladen_am": ab_tag,
            "verbraucht_usd": _z(verbraucht), "rest_usd": _z(rest),
            "anteil_rest": float(round(anteil, 4)),
            "verbrauch_7_tage_usd": _z(fenster), "je_tag_usd": _z(je_tag),
            "reichweite_tage": reichweite, "schwellen": schwellen,
            "konto_bestaetigt": False,
            "ausgangsart": "kontostand" if beobachtet else "aufladung",
            "kontostand_beobachtet": beobachtet,
            "kontostand_quelle": letzte.get("quelle") if beobachtet else None,
            "hinweis": "Rechnerischer Rest aus eingetragenem Guthaben und erfassten Kosten einschliesslich Schaetzungen; kein bestaetigter Anbieterkontostand.",
            "quelle": "betrieb/guthaben.json + kostenlaeufe.jsonl + arbeiter_api_laeufe.jsonl"}


def _z(wert):
    return str(Decimal(wert).quantize(Decimal("0.01")))


def _reichweite(tage):
    if tage is None:
        return "unbekannt (noch kein gemessener Verbrauch)"
    if tage == 0:
        return "unter einem Tag"
    return "%d Tag%s" % (tage, "" if tage == 1 else "e")


# ------------------------------------------------- Abo-Kontingent und Guthaben-Fehler
GUTHABEN_FEHLER = ("credit balance is too low", "insufficient credit",
                   "billing", "quota exceeded")
ABO_ABWEISUNG = ("usage limit", "rate limit", "kontingent", "too many requests",
                 "overloaded")


def abweisungen(root, tage=3):
    """Zaehlt, wie oft Anthropic zuletzt abgewiesen hat - Geld oder Kontingent.

    Quelle sind die Ergebnistexte der Arbeiterlaeufe. Es wird nichts geraten:
    steht nichts da, wird nichts gemeldet.
    """
    grenze = (b.now().date() - dt.timedelta(days=tage - 1)).isoformat()
    geld, kontingent, letzte_geld, letzte_kontingent = 0, 0, None, None
    quellen = [Path(root) / name for name in ('arbeiter_api_laeufe.jsonl', 'ruflo_laeufe.jsonl')]
    try:
        for zeile in (line for quelle in quellen if quelle.exists()
                      for line in quelle.read_text(encoding='utf-8').splitlines()):
            if not zeile.strip():
                continue
            r = json.loads(zeile)
            zeit = str(r.get("zeit") or "")
            if zeit[:10] < grenze:
                continue
            text = (str(r.get("result") or "") + " " + str(r.get("subtype") or "")).lower()
            if not r.get("is_error") and not text.strip():
                continue
            if any(m in text for m in GUTHABEN_FEHLER):
                geld += 1
                letzte_geld = max(letzte_geld or '', zeit)
            elif any(m in text for m in ABO_ABWEISUNG):
                kontingent += 1
                letzte_kontingent = max(letzte_kontingent or '', zeit)
    except (OSError, ValueError):
        pass
    return {"geld": geld, "geld_zuletzt": letzte_geld,
            "kontingent": kontingent, "kontingent_zuletzt": letzte_kontingent,
            "tage": tage, "quelle": "arbeiter_api_laeufe.jsonl + ruflo_laeufe.jsonl"}


def usd_zahl(wert):
    """F-31 (A9): Geldzahl fuer Saetze - zwei Nachkommastellen, deutsches Komma ("9,14", "10,00").
    Eine Rohzahl wie 9.14426219999999975 gehoert nie in einen Satz; die genaue Zahl bleibt in den Buechern."""
    try:
        return format(Decimal(str(wert)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f").replace(".", ",")
    except (InvalidOperation, ValueError, TypeError):
        return str(wert)


def api_sperre(root):
    """Belegtes leeres Guthaben verhindert Wiederholungen ohne neue Information."""
    fehlt, wieder_frei = '', ''
    for name in ('arbeiter_api_laeufe.jsonl', 'ruflo_laeufe.jsonl'):
        path = Path(root)/name
        if not path.exists():
            continue
        try:
            for r in b.records(path):
                zeit = _vergleichszeit(r.get('zeit'))
                text = str(r.get('result') or '').lower()
                if r.get('is_error') and any(w in text for w in ('credit balance is too low', 'insufficient credit')):
                    fehlt = max(fehlt, zeit)
                elif r.get('is_error') is False and r.get('subtype') == 'success':
                    wieder_frei = max(wieder_frei, zeit)
        except (OSError, ValueError):
            return 'Anbieterstatus nicht zuverlaessig lesbar; keine neuen API-Auftraege.'
    for r in lesen(root).get('aufladungen', []):
        if r.get('art') == 'kontostand':
            try:
                betrag = Decimal(str(r.get('betrag_usd')))
                zeit = _vergleichszeit(r.get('beobachtet'))
                if betrag.is_finite() and betrag > 0:
                    wieder_frei = max(wieder_frei, zeit)
                elif betrag == 0:
                    fehlt = max(fehlt, zeit)
            except (InvalidOperation, TypeError):
                pass
        else:
            wieder_frei = max(wieder_frei, _vergleichszeit(r.get('eingetragen')))
    if fehlt and fehlt > wieder_frei:
        return ('Anthropic meldet fehlendes Guthaben seit ' + fehlt
                + '. Nach einer Aufladung den Betrag im Kostenwaechter eintragen; kein weiterer kostenpflichtiger Start.')
    # Block 31.2: eigene, vorausschauende Grenze - unabhaengig von einer
    # Anbieter-Fehlermeldung. Der rechnerische Rest kommt aus unserem eigenen
    # Buch (stand()), nicht vom Anbieter, deshalb ein eigener Grund "Guthaben".
    g = stand(root)
    if g.get("bekannt") and g.get("rest_usd") is not None:
        try:
            if Decimal(str(g["rest_usd"])) <= Decimal("1.00"):
                return ('Guthaben: rechnerischer Rest nur noch %s USD (Grenze 1,00 USD) - '
                        'kein weiterer kostenpflichtiger Start, bis der Patron auflaedt oder '
                        'einen neuen Kontostand eintraegt.' % g["rest_usd"])
        except (InvalidOperation, TypeError):
            pass
    return ''


# ------------------------------------------------------------- macOS-Mitteilung
def _mitteilung(titel, text):
    """Bordmittel osascript; fehlt es oder schlaegt es fehl, wird geschwiegen -
    eine Warnung darf den Betrieb nie zum Stehen bringen."""
    import shutil
    import subprocess
    if not shutil.which('osascript'):
        return False
    skript = ('display notification %s with title %s' %
              (json.dumps(str(text)[:500]), json.dumps(str(titel)[:120])))
    try:
        subprocess.run(['osascript', '-e', skript], timeout=5,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def warnung_pruefen(root):
    """Block 31.2: macOS-Mitteilung bei 20 % Rest und bei jedem Unterschreiten
    eines 5-USD-Schritts. Merkt sich die letzte gemeldete Stufe in
    guthaben.json, damit nicht bei jedem Takt erneut gemeldet wird."""
    g = stand(root)
    if not g.get("bekannt") or g.get("rest_usd") is None:
        return {"gemeldet": False, "grund": "Guthaben unbekannt"}
    daten = lesen(root)
    warn = daten.get("warnungen") or {}
    rest = Decimal(str(g["rest_usd"]))
    anteil = g.get("anteil_rest")
    gemeldet = []
    schwelle_warnung = Decimal(str((g.get("schwellen") or {}).get("warnung", 0.20)))
    war_unter_schwelle = bool(warn.get("anteil_unter_schwelle"))
    ist_unter_schwelle = anteil is not None and Decimal(str(anteil)) <= schwelle_warnung
    if ist_unter_schwelle and not war_unter_schwelle:
        text = "Rechnerischer Rest %s USD (%d %%). %s" % (
            g["rest_usd"], int((anteil or 0) * 100), g.get("satz", ""))
        if _mitteilung("JACK Kostenwaechter: Guthaben knapp", text):
            gemeldet.append("20-prozent-schwelle")
    warn["anteil_unter_schwelle"] = ist_unter_schwelle
    stufe = int(rest // Decimal("5")) if rest >= 0 else -1
    letzte_stufe = warn.get("letzte_5usd_stufe")
    if letzte_stufe is None:
        warn["letzte_5usd_stufe"] = stufe
    elif stufe < letzte_stufe:
        text = "Rechnerischer Rest %s USD - naechste 5-USD-Schwelle unterschritten." % g["rest_usd"]
        if _mitteilung("JACK Kostenwaechter: Guthaben-Schritt", text):
            gemeldet.append("5usd-schritt")
        warn["letzte_5usd_stufe"] = stufe
    elif stufe > letzte_stufe:
        # Aufladung: Stufe steigt wieder - keine Meldung, nur Stand nachziehen.
        warn["letzte_5usd_stufe"] = stufe
    if gemeldet:
        daten["warnungen"] = warn
        schreiben(root, daten)
        protokoll(root, "guthaben_warnung", stufen=gemeldet, rest_usd=g["rest_usd"])
    elif warn != (daten.get("warnungen") or {}):
        daten["warnungen"] = warn
        schreiben(root, daten)
    return {"gemeldet": bool(gemeldet), "stufen": gemeldet, "rest_usd": g["rest_usd"]}


def lage(root):
    """Alles, was der Kostenwaechter ueber Geld weiss - fuer Maske und Briefing."""
    import jack_grenzen
    g = stand(root)
    ab = abweisungen(root)
    try:
        deckel_stand = jack_grenzen.verbrauch(root)
        grenzen = jack_grenzen.lesen(root)
        erreicht, deckelgrund = jack_grenzen.deckel_erreicht(root, grenzen, deckel_stand)
    except Exception as fehler:
        deckel_stand, grenzen, erreicht = {}, {}, False
        deckelgrund = "Deckel nicht pruefbar: " + str(fehler)[:120]
    # Block 30: Wirksam ist der Grundwert PLUS die Freigaben des Patrons von heute.
    tagesdeckel = (grenzen or {}).get("budget_usd_je_tag")
    tagesbilanz = {}
    try:
        _grund, _summe, _wirksam = jack_grenzen.tagesdeckel(root, grenzen)
        if _wirksam is not None:
            tagesdeckel = str(_wirksam)
        tagesbilanz = jack_grenzen.stand_fuer_tafel(root).get("tagesbilanz", {})
    except Exception:
        tagesbilanz = {}
    anteil = None
    if tagesdeckel:
        try:
            anteil = float(Decimal(deckel_stand.get("tag_usd", "0")) / Decimal(str(tagesdeckel)))
        except (InvalidOperation, ZeroDivisionError):
            anteil = None
    deckel = {"grenze_usd": tagesdeckel, "heute_usd": deckel_stand.get("tag_usd"),
              "anteil": anteil, "erreicht": erreicht, "satz": deckelgrund,
              "quellen": deckel_stand.get("tag_quellen", {}),
              "ampel": "rot" if erreicht else ("gelb" if (anteil or 0) >= 0.8 else "gruen"),
              "tagesbilanz": tagesbilanz}
    if not erreicht and (anteil or 0) >= 0.8:
        deckel["satz"] = ("Tagesdeckel zu %d %% ausgeschöpft: %s von %s USD."
                          % (int((anteil or 0) * 100), usd_zahl(deckel_stand.get("tag_usd")), usd_zahl(tagesdeckel)))
    return {"zeit": b.now().isoformat(), "guthaben": g, "deckel": deckel,
            "abweisungen": ab,
            "hinweis": ("JACK zahlt nie und lädt nie auf. Er rechnet, warnt und "
                        "legt vor - entschieden wird vom Patron.")}


if __name__ == "__main__":
    wurzel = Path(__file__).resolve().parent
    if len(sys.argv) > 2 and sys.argv[1] == "aufladen":
        print(json.dumps(aufladen(wurzel, sys.argv[2],
                                  sys.argv[3] if len(sys.argv) > 3 else None),
                         ensure_ascii=False, indent=1))
    else:
        print(json.dumps(lage(wurzel), ensure_ascii=False, indent=1))
