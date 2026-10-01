#!/usr/bin/env python3
"""Obergrenzen und Budgetdeckel (Block 2, Aufgabe 3).

Die Steuerdatei betrieb/betriebsgrenzen.json haelt fest, wie viele Laeufe
gleichzeitig erlaubt sind und wie viel Geld je Zeitfenster ausgegeben werden
darf. Sie ist eine Steuerdatei und wird ueber den Bereich "steuerung"
exklusiv geschuetzt.

Deckel erreicht heisst: keine NEUEN Laeufe. Laufende werden zu Ende gebracht.
Es wird nichts automatisch angehoben.
"""
import datetime as dt
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

# ════════ 16.09.2026: Warum diese drei Zeilen hier stehen ═══════════════════
# Der Arbeiter fragt den Deckel mit `python3 -I jack_grenzen.py --deckel` ab.
# Der Schalter -I nimmt den Ordner des Skripts aus dem Suchpfad; damit schlug
# `import jack_betrieb` fehl, das Skript stuerzte ab, und der Arbeiter las den
# Absturz als "Deckel nicht erreicht" und startete den Lauf. Der Deckel war
# dadurch von Anfang an wirkungslos. Diese Zeilen machen die Datei unter -I
# lauffaehig, ohne die Isolation aufzuweichen.
_HIER = str(Path(__file__).resolve().parent)
if _HIER not in sys.path:
    sys.path.insert(0, _HIER)

import jack_betrieb as betrieb
import jack_kosten

DATEI = "betriebsgrenzen.json"

# Herleitung der Obergrenze steht in der Datei selbst, damit sie nicht verloren geht.
VORGABE = {
    "gleichzeitig_gesamt": 8,
    "gleichzeitig_je_art": {"claude": 8, "api": 4, "probe": 16},
    "budget_usd_je_stunde": None,
    "budget_usd_je_tag": None,
    "vorschlag_usd_je_stunde": "1.50",
    "vorschlag_usd_je_tag": "12.00",
    # Ein Geld-Deckel kann nur greifen, soweit der Anbieter Betraege meldet.
    # Am 16.09.2026 meldete er zu KEINEM der 263 Laeufe einen Betrag. Deshalb
    # gibt es zusaetzlich einen Deckel auf die ZAHL der Laeufe - der wirkt immer.
    "laeufe_je_stunde": None,
    "laeufe_je_tag": None,
    "vorschlag_laeufe_je_stunde": 60,
    "vorschlag_laeufe_je_tag": 400,
    "sperrfrist_sekunden": 2700,
    "zeitgrenze_minuten": {"arbeit": 8, "recherche": 20, "content": 12, "video": 15,
                           "software": 15, "veroeffentlichen": 8},
    "herleitung": (
        "Apple M4, 10 Kerne (4 Leistung, 6 Effizienz), 32 GB. Ein claude-Lauf "
        "belegt gemessen 350 bis 950 MB und wartet die meiste Zeit auf den "
        "Anbieter, belastet also kaum einen Kern. Acht gleichzeitige Laeufe "
        "brauchen rund 4 GB. Die Vorgabe des Patrons von acht ist damit "
        "getragen; die Messung steht in betrieb/parallelmessung.json."),
    "budget_herleitung": (
        "Gemessen am 16.09.2026: ein echter Wortwechsel im Dialog kostet "
        "0,02332 USD, ein Auftragslauf im Mittel deutlich mehr. Der Vorschlag "
        "von 1,50 USD je Stunde traegt acht gleichzeitige Laeufe rund eine "
        "Stunde lang. 12,00 USD je Tag entspricht acht solchen Stunden. "
        "Die Hoehe legt der Patron fest; bis dahin ist kein Deckel gesetzt."),
}


def pfad(root) -> Path:
    return betrieb.area(root) / DATEI


# ════════ Termin-Schutz (F-3, 24.09.2026) ═══════════════════════════════════
# Fund aus F-2: Ein Termin ohne Feld "wert" (angelegt am 23.09.2026 im Auftrag
# 17.1 mit den Feldern von/auf/hinweis statt wert) setzte am 24.09. 07:50 den
# Tagesdeckel auf null - also auf "kein Deckel". Ein Termin darf eine
# Betriebsgrenze nie leeren. Ungueltige Termine werden uebersprungen, in
# termine_abgelehnt aufgehoben (nie geloescht), gemeldet und nicht erneut geprueft.
DECKEL_FELDER = ("budget_usd_je_tag", "budget_usd_je_stunde",
                 "vorschlag_usd_je_tag", "vorschlag_usd_je_stunde")
DECKEL_MIN = Decimal("0.50")
DECKEL_MAX = Decimal("50.00")
ENTSCHEIDUNGEN = "ENTSCHEIDUNGEN_FUER_DEN_PATRON.md"

# ════════ Zeitgrenze je Ablauf (F-6, 24.09.2026) ════════════════════════════
# Bis F-5 stand die Zeitgrenze des API-Laufs fest im Code (480 Sekunden). Nr. 123
# (Ablauf recherche) lief nach 8 Minuten in diese Grenze, obwohl die Arbeit
# gut voranging. Jetzt steht sie je Ablauf in betriebsgrenzen.json unter
# zeitgrenze_minuten. Fehlt der Eintrag oder ist er ungueltig, gilt 8 - eine
# kaputte Zahl darf die Grenze nie aufheben (gleiche Haltung wie der Termin-Schutz).
ZEITGRENZE_STANDARD = 8
ZEITGRENZE_MIN = 3
ZEITGRENZE_MAX = 60
ZEITGRENZE_FELD = "zeitgrenze_minuten"
ZEITGRENZE_VORGABE = {"arbeit": 8, "recherche": 20, "content": 12, "video": 15,
                      "software": 15, "veroeffentlichen": 8}


def _zeitgrenze_wert(wert):
    """Gibt die Minuten als int zurueck oder None, wenn der Wert nicht 3 bis 60 ist."""
    if isinstance(wert, bool) or not isinstance(wert, (int, float)):
        return None
    if isinstance(wert, float) and (not wert.is_integer()):
        return None
    wert = int(wert)
    return wert if ZEITGRENZE_MIN <= wert <= ZEITGRENZE_MAX else None


def zeitgrenze_minuten(root, ablauf, daten=None):
    """Zeitgrenze des API-Laufs in Minuten fuer diesen Ablauf (F-6).

    Standard 8 bei fehlender Datei, fehlendem Feld, fehlendem Ablauf-Eintrag
    oder einem Wert ausserhalb 3 bis 60. Ungueltiges wird nie geraten oder
    geklemmt, sondern ersetzt."""
    if daten is None:
        try:
            daten = json.loads(pfad(root).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return ZEITGRENZE_STANDARD
    tabelle = daten.get(ZEITGRENZE_FELD) if isinstance(daten, dict) else None
    if not isinstance(tabelle, dict):
        return ZEITGRENZE_STANDARD
    wert = _zeitgrenze_wert(tabelle.get(ablauf))
    return ZEITGRENZE_STANDARD if wert is None else wert


# F-12 (PM-Entscheidung 3, 24.09.2026): die Zeitgrenze aus dem AUFTRAGSKOPF (zeitgrenze_minuten) ist auf
# zeitgrenze_max_auftragskopf gedeckelt (Standard 30, nur ueber betriebsgrenzen.json veraenderbar, 3 bis 60).
# Werte darueber werden gekappt - nie still ignoriert - und der Zettel vermerkt die Kappung.
ZEITGRENZE_KOPF_MAX_STANDARD = 30


def zeitgrenze_auftragskopf(root, wert, daten=None):
    """(minuten oder None, gekappt: bool, obergrenze). None = kein/ungueltiger Kopfwert (unter 3 oder keine Zahl)."""
    if daten is None:
        try:
            daten = json.loads(pfad(root).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            daten = {}
    obergrenze = _zeitgrenze_wert((daten or {}).get("zeitgrenze_max_auftragskopf")) if isinstance(daten, dict) else None
    obergrenze = obergrenze or ZEITGRENZE_KOPF_MAX_STANDARD
    try:
        zahl = int(str(wert).strip())
    except (TypeError, ValueError):
        return None, False, obergrenze
    if zahl < ZEITGRENZE_MIN:
        return None, False, obergrenze
    if zahl > obergrenze:
        return obergrenze, True, obergrenze
    return zahl, False, obergrenze


def _termin_pruefen(eintrag, daten):
    """Gibt (ok, wert_oder_grund) zurueck. Nie eine Ausnahme."""
    if not isinstance(eintrag, dict):
        return False, "Termin ist kein Objekt"
    if not str(eintrag.get("feld") or "").strip():
        return False, "Feld feld fehlt oder ist leer"
    if not str(eintrag.get("ab_datum") or "").strip():
        return False, "Feld ab_datum fehlt oder ist leer"
    feld = str(eintrag["feld"])
    if "wert" not in eintrag:
        return False, "Feld wert fehlt"
    wert = eintrag["wert"]
    if wert is None or isinstance(wert, bool):
        return False, "wert ist null oder kein Zahlenwert"
    if isinstance(wert, (str, list, dict)) and not wert:
        return False, "wert ist leer"
    if feld in DECKEL_FELDER:
        try:
            zahl = Decimal(str(wert).strip().replace(",", "."))
        except Exception:
            return False, "wert %r ist keine Zahl" % (wert,)
        if not zahl.is_finite():
            return False, "wert %r ist keine endliche Zahl" % (wert,)
        if not (DECKEL_MIN <= zahl <= DECKEL_MAX):
            return False, "wert %s liegt ausserhalb %s bis %s USD" % (zahl, DECKEL_MIN, DECKEL_MAX)
        return True, "%.2f" % zahl
    if feld == ZEITGRENZE_FELD or feld.startswith(ZEITGRENZE_FELD + "."):
        # F-6: nur einzelne Ablaeufe (zeitgrenze_minuten.<ablauf>), nur 3 bis 60 Minuten.
        ablauf = feld.partition(".")[2]
        if not ablauf:
            return False, "Zeitgrenze-Termin braucht ein Feld zeitgrenze_minuten.<ablauf>"
        if _zeitgrenze_wert(wert) is None:
            return False, "wert %r liegt ausserhalb %d bis %d Minuten" % (wert, ZEITGRENZE_MIN, ZEITGRENZE_MAX)
        return True, int(wert)
    bisher = daten.get(feld)
    if isinstance(bisher, int) and not isinstance(bisher, bool):
        if not isinstance(wert, int) or wert <= 0:
            return False, "wert %r ist keine positive Ganzzahl" % (wert,)
    return True, wert


def _termin_melden(root, eintrag, grund):
    """Warnzeile ins Fehlerprotokoll und Vermerk fuer den Patron. Best effort, nie werfen."""
    feld = eintrag.get("feld") if isinstance(eintrag, dict) else None
    ab = eintrag.get("ab_datum") if isinstance(eintrag, dict) else None
    zeit = betrieb.now().isoformat()
    try:
        betrieb.append(betrieb.area(root) / "beobachtung_fehler.jsonl", {
            "zeit": zeit, "quelle": "jack_grenzen._termine_anwenden",
            "fehler": "Termin uebersprungen (Betriebsgrenze bleibt unveraendert): "
                      "feld=%s ab_datum=%s - %s" % (feld, ab, grund)})
    except Exception:
        pass
    try:
        datei = betrieb.area(root) / ENTSCHEIDUNGEN
        kopf = "" if datei.is_file() else "# Entscheidungen fuer den Patron\n"
        text = (kopf + "\n---\n\n## %s - Termin abgelehnt: Betriebsgrenze bleibt unveraendert\n\n"
                "Ein Termin in `betrieb/betriebsgrenzen.json` war ungueltig und wurde NICHT angewandt "
                "(Feld `%s`, ab `%s`). Grund: %s. Der Termin liegt unveraendert unter `termine_abgelehnt` "
                "in derselben Datei. **Der Patron entscheidet**, ob ein korrigierter Termin gesetzt wird.\n"
                % (zeit[:16].replace("T", " "), feld, ab, grund))
        with datei.open("a", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        pass


def _termine_anwenden(root, daten):
    """Angekuendigte Werte schalten sich zum Stichtag selbst um.

    Block 10, 16.09.2026: Der Patron hatte den Tagesdeckel fuer EINEN Tag auf
    20,00 USD angehoben und 10,00 USD ab dem 17.09. als Dauerwert festgelegt.
    Das stand nur als Satz in der Datei - am 17.09. um 00:00 waere die
    Anhebung stillschweigend zum Dauerzustand geworden. Ein Deckel, an den
    sich jemand erinnern muss, ist kein Deckel.

    Ein faelliger Termin wird genau einmal angewandt, in der Datei vermerkt
    und aus der Liste genommen. Es wird nie automatisch ERHOEHT, nur das
    umgesetzt, was der Patron datiert festgelegt hat.

    F-3, 24.09.2026: Ein Termin ohne gueltigen Wert wird uebersprungen (siehe
    _termin_pruefen), Deckel nur zwischen 0,50 und 50,00 USD.
    """
    termine = daten.get("termine") or []
    if not isinstance(termine, list) or not termine:
        return daten, False
    heute = betrieb.now().date().isoformat()
    offen, geschaltet, abgelehnt = [], [], []
    for eintrag in termine:
        try:
            ab = str(eintrag["ab_datum"])
            str(eintrag["feld"])
        except (TypeError, KeyError):
            abgelehnt.append((eintrag, "Feld feld oder ab_datum fehlt"))
            continue
        if ab > heute:
            offen.append(eintrag)
            continue
        ok, wert = _termin_pruefen(eintrag, daten)
        if not ok:
            abgelehnt.append((eintrag, wert))
            continue
        feld = str(eintrag["feld"])
        if feld.startswith(ZEITGRENZE_FELD + "."):
            ablauf = feld.partition(".")[2]
            tabelle = daten.get(ZEITGRENZE_FELD)
            if not isinstance(tabelle, dict):
                tabelle = daten[ZEITGRENZE_FELD] = {}
            alt_wert = tabelle.get(ablauf)
            tabelle[ablauf] = wert
        else:
            alt_wert = daten.get(feld)
            daten[feld] = wert
        geschaltet.append({"zeit": betrieb.now().isoformat(), "feld": feld,
                           "von": alt_wert, "auf": wert,
                           "ab_datum": ab, "quelle": eintrag.get("quelle", "")})
    if not geschaltet and not abgelehnt:
        return daten, False
    for eintrag, grund in abgelehnt:
        _termin_melden(root, eintrag, grund)
    daten["termine"] = offen
    if geschaltet:
        daten["termine_geschaltet"] = (daten.get("termine_geschaltet") or [])[-9:] + geschaltet
    if abgelehnt:
        daten["termine_abgelehnt"] = (daten.get("termine_abgelehnt") or []) + [
            {"zeit": betrieb.now().isoformat(), "grund": grund, "termin": eintrag}
            for eintrag, grund in abgelehnt]
    return daten, True


def lesen(root) -> dict:
    p = pfad(root)
    if not p.is_file():
        schreiben(root, VORGABE)
        return dict(VORGABE)
    try:
        daten = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(VORGABE)
    for k, v in VORGABE.items():
        daten.setdefault(k, v)
    daten, geaendert = _termine_anwenden(root, daten)
    if geaendert:
        try:
            schreiben(root, daten)
        except OSError:
            pass
    return daten


def schreiben(root, daten: dict):
    """Unteilbar schreiben: erst daneben, dann umbenennen. Nie halb."""
    p = pfad(root)
    tmp = p.with_suffix(".json.neu")
    tmp.write_text(json.dumps(daten, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)
    return p


# ════════ Was zaehlt als Ausgabe? (Block 10, 16.09.2026) ═══════════════════
# Dies ist ein GELD-Deckel. Gezaehlt wird nur, was beim Anbieter wirklich Geld
# kostet - also Laeufe mit abrechnung "api". Laeufe ueber das Claude-Abo
# ("claude_abo") und ueber den Codex-Zugang ("codex_zugang") sind mit dem
# Monatsbeitrag bezahlt; sie in den Geld-Deckel zu rechnen wuerde den Deckel
# schliessen, ohne dass ein Cent geflossen ist.
#
# WICHTIG UND UNBEQUEM: Das Gespraech laeuft in dieser Fassung NICHT ueber das
# Abo. server.py ruft api.anthropic.com mit dem API-Schluessel auf und bucht es
# als abrechnung "api" - es kostet also Geld und zaehlt hier mit. Dass das
# Gespraech trotzdem nie gesperrt wird, ist die ausdrueckliche Anweisung des
# Patrons vom 16.09.2026; gezaehlt werden muss es dennoch, sonst deckelt der
# Deckel den kleineren Teil der Ausgaben.
GELD_ABRECHNUNG = frozenset({"api"})


def _laeufe(root):
    """Alle Laeufe mit Zeit, Betrag und Art - aus dem Verbrauchsbuch.

    Rueckgabe je Lauf: (Zeitpunkt, Betrag oder None, Art, Abrechnung).
    Laeufe ohne Geldabrechnung sind hier schon aussortiert.
    """
    byid = {}
    for row in jack_kosten.rows(root):
        ident = row.get("id")
        if not ident:
            continue
        if row.get("ereignis") == "start":
            byid.setdefault(ident, row)
        else:
            byid[ident] = row
    raus = []
    for r in byid.values():
        if r.get("historisch"):
            continue
        if str(r.get("abrechnung") or "api") not in GELD_ABRECHNUNG:
            continue
        zeit = r.get("zeit")
        if zeit is None:
            continue
        try:
            t = dt.datetime.fromisoformat(zeit)
        except ValueError:
            continue
        # Block 10: Erst der gemeldete Betrag. Fehlt er, die SCHAETZUNG aus
        # belegten Listenpreisen - getrennt gefuehrt, damit man jederzeit
        # sieht, was Rechnung und was Rechnung-mit-Sternchen ist.
        teil = bool(r.get("teil_von"))
        gemeldet = r.get("usd_gemeldet")
        if gemeldet is not None:
            raus.append((t, Decimal(gemeldet), str(r.get("art") or "unbekannt"),
                         str(r.get("abrechnung") or "api"), "gemeldet", teil))
            continue
        geschaetzt = r.get("usd_geschaetzt")
        if geschaetzt is None:
            geschaetzt, _stand = jack_kosten.schaetzung(root, r.get("modell"),
                                                        r.get("verbrauch"))
        if geschaetzt is not None:
            raus.append((t, Decimal(str(geschaetzt)), str(r.get("art") or "unbekannt"),
                         str(r.get("abrechnung") or "api"), "geschaetzt", teil))
            continue
        raus.append((t, None, str(r.get("art") or "unbekannt"),
                     str(r.get("abrechnung") or "api"), "ohne", teil))
    return raus


def _teillaeufe(root):
    """Welche Laeufe sind TEIL eines groesseren Vorgangs? (Block 15, D1)

    Ihr Geld zaehlt, ihre ZAHL nicht - der uebergeordnete Vorgang ist schon
    als ein Lauf gebucht. Ohne diese Unterscheidung war ein Messtest mit 60
    Aufgaben nach 60 Aufgaben am Stundendeckel.
    """
    raus = set()
    for row in jack_kosten.rows(root):
        if row.get("teil_von"):
            raus.add(row.get("id"))
    return raus


def _betraege(root):
    """Alte Form, weiter benutzbar: nur Zeit und Betrag."""
    return [(t, b) for t, b, _art, _ab, _h, _teil in _laeufe(root)]


def _tag_aus_buechern(root, tag_ab):
    """Alle Buecher, nicht nur das zentrale.

    Gezaehlt wird das MEISTE, was irgendein Buch fuer den Kalendertag ausweist,
    nie das wenigste. Die Buecher ueberschneiden sich - die Arbeiterlaeufe
    stehen sowohl in ihrem eigenen Buch als auch im zentralen Verbrauchsbuch.
    Ein Aufsummieren wuerde sie doppelt zaehlen, ein Ignorieren koennte sie
    ganz verlieren. Das Hoechste ist die sichere Seite.
    """
    quellen = {}
    tag = tag_ab.date().isoformat()

    def zahl(wert):
        try:
            return Decimal(str(wert))
        except Exception:
            return Decimal(0)

    for name, datei, feld in (
            ("arbeiter_api_laeufe", Path(root) / "arbeiter_api_laeufe.jsonl", "total_cost_usd"),
            # 20.09.2026: Ruflo-Laeufe fuehren ein eigenes Buch. Ohne diese Zeile
            # saehe der Deckel sie nur im zentralen Verbrauchsbuch - und wenn dort
            # einmal etwas fehlt, waeren sie unsichtbar.
            ("ruflo_laeufe", Path(root) / "ruflo_laeufe.jsonl", "total_cost_usd"),
            ("modelllaeufe", betrieb.area(root) / "modelllaeufe.jsonl", "usd"),
            ("ratslaeufe", betrieb.area(root) / "ratslaeufe.jsonl", "usd")):
        summe = Decimal(0)
        try:
            for zeile in datei.read_text(encoding="utf-8").splitlines():
                if not zeile.strip():
                    continue
                r = json.loads(zeile)
                zeit = str(r.get("zeit") or r.get("beendet") or "")
                if zeit.startswith(tag) and r.get(feld) is not None:
                    summe += zahl(r[feld])
        except (OSError, ValueError):
            continue
        quellen[name] = summe
    return quellen


def verbrauch(root):
    """Was ist in der laufenden Stunde und am laufenden Tag angefallen?

    WICHTIG UND EHRLICH: Der Anbieter meldet zu vielen Laeufen keinen
    Geldbetrag. Diese Laeufe werden GEZAEHLT, nicht beziffert. Ein Deckel auf
    Geld kann daher nur greifen, soweit Betraege gemeldet sind; die Zahl der
    Laeufe ohne Betrag wird immer mitgefuehrt.
    """
    jetzt = betrieb.now()
    stunde_ab = jetzt.replace(minute=0, second=0, microsecond=0)
    tag_ab = jetzt.replace(hour=0, minute=0, second=0, microsecond=0)
    s_usd = t_usd = Decimal(0)
    s_n = t_n = s_ohne = t_ohne = 0
    s_arten, t_arten = {}, {}
    s_gem = t_gem = Decimal(0)
    s_gesch = t_gesch = Decimal(0)
    t_n_gesch = 0
    # Block 15 (D1): Das GELD jedes Laufs zaehlt. Die ZAHL der Laeufe zaehlt
    # nur fuer eigenstaendige Laeufe - ein Teillauf gehoert zu einem Vorgang,
    # der schon als einer gebucht ist.
    for zeit, betrag, art, _ab, herkunft, teil in _laeufe(root):
        if zeit >= tag_ab:
            if not teil:
                t_n += 1
                t_arten[art] = t_arten.get(art, 0) + 1
            if betrag is None:
                if not teil:
                    t_ohne += 1
            else:
                t_usd += betrag
                if herkunft == "gemeldet":
                    t_gem += betrag
                else:
                    t_gesch += betrag
                    t_n_gesch += 1
        if zeit >= stunde_ab:
            if not teil:
                s_n += 1
                s_arten[art] = s_arten.get(art, 0) + 1
            if betrag is None:
                if not teil:
                    s_ohne += 1
            else:
                s_usd += betrag
                if herkunft == "gemeldet":
                    s_gem += betrag
                else:
                    s_gesch += betrag
    # Alle Buecher gegenrechnen; das hoechste zaehlt.
    quellen = {"kostenlaeufe": t_usd}
    quellen.update(_tag_aus_buechern(root, tag_ab))
    t_usd = max(quellen.values())
    return {"stunde_ab": stunde_ab.isoformat(), "tag_ab": tag_ab.isoformat(),
            "stunde_usd": str(s_usd), "stunde_laeufe": s_n, "stunde_ohne_betrag": s_ohne,
            "tag_usd": str(t_usd), "tag_laeufe": t_n, "tag_ohne_betrag": t_ohne,
            "stunde_arten": dict(sorted(s_arten.items(), key=lambda x: -x[1])),
            "tag_arten": dict(sorted(t_arten.items(), key=lambda x: -x[1])),
            "stunde_usd_gemeldet": str(s_gem), "stunde_usd_geschaetzt": str(s_gesch),
            "tag_usd_gemeldet": str(t_gem), "tag_usd_geschaetzt": str(t_gesch),
            "tag_laeufe_geschaetzt": t_n_gesch,
            "preisquelle": (jack_kosten.preise(root).get("quelle", "")
                            + " · abgerufen " + jack_kosten.preise(root).get("abgerufen", "")),
            "tag_quellen": {k: str(v) for k, v in quellen.items()}}


MELDUNGEN = "kostendeckel_gemeldet.json"
DECKELBUCH = "kostendeckel.jsonl"
FREIGABEBUCH = "deckel_freigaben.jsonl"
FREIGABE_SCHRITT = Decimal("10.00")


# ════════ Tagesdeckel mit Freigabe (Block 30, 20.09.2026) ═══════════════════
# Entscheidung des Patrons vom 20.09.2026: Der Tagesdeckel von 10,00 USD bleibt
# ein KONTROLLINSTRUMENT, keine Mauer. Ist er erreicht, wird gemeldet - und der
# Patron kann fuer den laufenden Tag weitere 10,00 USD freigeben, so oft er will.
#
# Drei Regeln, die das dicht halten:
#   1. Eine Freigabe hebt den Deckel um GENAU 10,00 USD. Kein anderer Betrag.
#   2. Sie gilt bis Mitternacht. Am Folgetag zaehlt nur der Grundwert aus
#      betriebsgrenzen.json - eine Freigabe schleicht sich nie in den Dauerwert.
#   3. Ausloesen kann sie nur der Patron. Kein Agent, kein Arbeiterlauf, keine
#      Routine ruft diese Funktion; der Pfadwaechter laesst den Arbeiter ohnehin
#      nicht nach betrieb/ schreiben.
def freigaben(root, tag=None):
    """Die heutigen Freigaben des Patrons: (Anzahl, Summe, Liste)."""
    tag = tag or betrieb.now().date().isoformat()
    liste = []
    for zeile in betrieb.records(betrieb.area(root) / FREIGABEBUCH):
        if str(zeile.get("tag")) != tag:
            continue
        # Eine Freigabe aus einem Pruefstand ist keine Freigabe des Patrons.
        # Sie bleibt im Buch stehen - geloescht wird nichts - zaehlt aber nicht
        # auf den Deckel. Sonst haette der Deckeltest vom 20.09.2026 den echten
        # Tagesdeckel stillschweigend auf 20,00 USD gehoben.
        if zeile.get("pruefstand"):
            continue
        try:
            zeile["betrag"] = Decimal(str(zeile.get("betrag_usd")))
        except Exception:
            continue
        liste.append(zeile)
    return len(liste), sum((z["betrag"] for z in liste), Decimal(0)), liste


def tagesdeckel(root, grenzen=None):
    """(Grundwert, Freigabesumme, wirksamer Deckel) - alle drei als Decimal oder None."""
    grenzen = grenzen or lesen(root)
    roh = grenzen.get("budget_usd_je_tag")
    if roh in (None, "", 0):
        return None, Decimal(0), None
    try:
        basis = Decimal(str(roh))
    except Exception:
        return None, Decimal(0), None
    _, summe, _ = freigaben(root)
    return basis, summe, basis + summe


def freigabe_erteilen(root, weg, betrag=None, pruefstand=False):
    """Der Patron hebt den Deckel des LAUFENDEN Tages um 10,00 USD.

    weg: "knopf", "sprache" oder "text" - damit im Buch steht, wie er es getan
    hat. Rueckgabe: der neue wirksame Tagesdeckel als Text.
    """
    weg = str(weg or "")[:40]
    if weg not in ("knopf", "sprache", "text"):
        raise ValueError("Unbekannter Weg der Freigabe: erlaubt sind knopf, sprache, text")
    schritt = Decimal(str(betrag)) if betrag is not None else FREIGABE_SCHRITT
    if schritt != FREIGABE_SCHRITT:
        raise ValueError("Eine Freigabe hebt den Deckel um genau %s USD" % FREIGABE_SCHRITT)
    jetzt = betrieb.now()
    basis, vorher, _ = tagesdeckel(root)
    betrieb.append(betrieb.area(root) / FREIGABEBUCH,
                   {"zeit": jetzt.isoformat(), "tag": jetzt.date().isoformat(),
                    "betrag_usd": str(schritt), "weg": weg,
                    "von": "Pruefstand" if pruefstand else "Patron",
                    "pruefstand": bool(pruefstand),
                    "deckel_vorher": str((basis or Decimal(0)) + vorher),
                    "deckel_nachher": str((basis or Decimal(0)) + vorher + schritt),
                    "gilt_bis": "Mitternacht; am Folgetag gilt wieder der Grundwert"})
    # Die Meldesperre des Fensters aufheben: wird der neue Deckel spaeter wieder
    # erreicht, soll der Patron das erneut erfahren und nicht stillschweigend
    # ausgesperrt werden.
    try:
        (betrieb.area(root) / MELDUNGEN).unlink()
    except OSError:
        pass
    _, _, neu = tagesdeckel(root)
    return str(neu)


def _arten_satz(arten):
    """Woher kam der Verbrauch? Ein kurzer Satz, keine Tabelle."""
    if not arten:
        return ""
    teile = ["%s %d" % (k, v) for k, v in list(arten.items())[:4]]
    return " Davon: " + ", ".join(teile) + "."


def deckel_status(root, grenzen=None, stand=None):
    """Welcher Deckel ist erreicht - und in welchem Zeitfenster?

    Die Kennung ist wichtig: Sie erlaubt GENAU EINE Meldung je Deckel und
    Zeitfenster. Ohne sie schrieb jeder blockierte Lauf eine eigene Zeile, und
    der Patron bekam dieselbe Nachricht dreissig Mal (Auftrag 2.1, Punkt 3).
    """
    grenzen = grenzen or lesen(root)
    stand = stand or verbrauch(root)
    fenster_stunde = str(stand.get("stunde_ab", ""))[:13]
    fenster_tag = str(stand.get("tag_ab", ""))[:10]
    for feld, wert_feld, name, fenster, arten_feld in (
            ("budget_usd_je_stunde", "stunde_usd", "Stundendeckel", fenster_stunde, "stunde_arten"),
            ("budget_usd_je_tag", "tag_usd", "Tagesdeckel", fenster_tag, "tag_arten")):
        deckel = grenzen.get(feld)
        if deckel in (None, "", 0):
            continue
        try:
            d = Decimal(str(deckel))
        except Exception:
            continue
        # Block 30: Auf den Tagesdeckel wirken die Freigaben des Patrons.
        zusatz = Decimal(0)
        if feld == "budget_usd_je_tag":
            _, zusatz, wirksam = tagesdeckel(root, grenzen)
            if wirksam is not None:
                d = wirksam
        ist = Decimal(stand[wert_feld])
        if ist >= d:
            gem = stand.get(wert_feld + "_gemeldet", "0")
            gesch = stand.get(wert_feld + "_geschaetzt", "0")
            return {"erreicht": True, "art": feld, "name": name, "fenster": fenster,
                    "kennung": "%s|%s" % (feld, fenster),
                    "freigaben_usd": str(zusatz),
                    "grund": ("%s erreicht: %s von %s USD (%s gemeldet, %s geschätzt "
                              "aus belegten Listenpreisen)%s. Keine neuen Laeufe; "
                              "laufende werden zu Ende gebracht.%s"
                              % (name, ist, d, gem, gesch,
                                 (" — darin %s USD bereits vom Patron freigegeben" % zusatz)
                                 if zusatz else "",
                                 _arten_satz(stand.get(arten_feld))))}
    for feld, wert_feld, name, fenster, arten_feld in (
            ("laeufe_je_stunde", "stunde_laeufe", "Stunden-Laufdeckel", fenster_stunde, "stunde_arten"),
            ("laeufe_je_tag", "tag_laeufe", "Tages-Laufdeckel", fenster_tag, "tag_arten")):
        deckel = grenzen.get(feld)
        if deckel in (None, "", 0):
            continue
        try:
            d = int(deckel)
        except (TypeError, ValueError):
            continue
        ist = int(stand[wert_feld])
        if ist >= d:
            return {"erreicht": True, "art": feld, "name": name, "fenster": fenster,
                    "kennung": "%s|%s" % (feld, fenster),
                    "grund": ("%s erreicht: %d von %d Laeufen mit Geldabrechnung. "
                              "Keine neuen Laeufe; laufende werden zu Ende gebracht.%s"
                              % (name, ist, d, _arten_satz(stand.get(arten_feld))))}
    return {"erreicht": False, "art": "", "name": "", "fenster": "",
            "kennung": "", "grund": ""}


def deckel_erreicht(root, grenzen=None, stand=None):
    """Gibt (True, Grund) zurueck, wenn keine neuen Laeufe starten duerfen."""
    s = deckel_status(root, grenzen, stand)
    return s["erreicht"], s["grund"]


def _meldungen_lesen(root):
    try:
        return json.loads((betrieb.area(root) / MELDUNGEN).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def meldung_faellig(root, kennung):
    """True genau EINMAL je Deckel und Zeitfenster.

    Der Aufrufer sperrt trotzdem jeden Lauf - nur die MELDUNG kommt einmal.
    Faellt das Schreiben aus, wird lieber gemeldet als verschluckt.
    """
    if not kennung:
        return False
    p = betrieb.area(root) / MELDUNGEN
    daten = _meldungen_lesen(root)
    if daten.get("kennung") == kennung:
        return False
    daten = {"kennung": kennung, "zeit": betrieb.now().isoformat()}
    try:
        tmp = p.with_suffix(".json.neu")
        tmp.write_text(json.dumps(daten, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, p)
    except OSError:
        pass
    return True


def _mitteilung(titel, text):
    """Eine macOS-Mitteilung. Schlaegt sie fehl, ist das kein Grund, den Lauf
    abzubrechen - die Karte in der Oberflaeche bleibt der verlaessliche Weg."""
    import subprocess
    sauber = lambda s: str(s).replace('"', "'").replace("\\", "")[:240]
    try:
        subprocess.run(["/usr/bin/osascript", "-e",
                        'display notification "%s" with title "%s" sound name "Submarine"'
                        % (sauber(text), sauber(titel))],
                       capture_output=True, timeout=10)
        return True
    except Exception:
        return False


STIMMSPUR = "stimme_stand.json"
STIMME_FRISCH_MINUTEN = 15


def stimme_laeuft(root):
    """Hat die Sprachausgabe in den letzten 15 Minuten gearbeitet?

    Es gibt keinen Schalter "Stimme an" - die Stimme entsteht, wenn die
    Oberflaeche sie abruft. server.py hinterlaesst dabei eine Spur; nur wenn
    die frisch ist, redet JACK von sich aus. Sonst bliebe die Ansage ein
    Selbstgespraech im leeren Zimmer.
    """
    try:
        spur = json.loads((betrieb.area(root) / STIMMSPUR).read_text(encoding="utf-8"))
        zuletzt = dt.datetime.fromisoformat(str(spur["zuletzt"]))
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return (betrieb.now() - zuletzt).total_seconds() <= STIMME_FRISCH_MINUTEN * 60


def _ansagen(root, satz):
    """Sagt den Satz an, WENN die Sprachausgabe gerade laeuft - sonst nicht."""
    import subprocess
    if not stimme_laeuft(root):
        return False
    try:
        subprocess.run(["/usr/bin/say", "-v", "Anna", "--", str(satz)[:300]],
                       capture_output=True, timeout=30)
        return True
    except Exception:
        return False


def deckel_melden(root, weg, status):
    """Schreibt die Deckelmeldung - einmal je Deckel und Zeitfenster.

    Rueckgabe: True, wenn diese Meldung neu war (dann gehoert sie dem Patron
    vorgelegt), False, wenn derselbe Deckel im selben Fenster schon gemeldet ist.
    """
    if not status.get("erreicht"):
        return False
    neu = meldung_faellig(root, status.get("kennung"))
    if not neu:
        return False
    # Block 30: Beim TAGESdeckel bekommt der Patron zusaetzlich eine
    # macOS-Mitteilung und - wenn die Sprachausgabe laeuft - einen Satz.
    # Kein Mailversand; so hat es der Patron am 20.09.2026 festgelegt.
    gemeldet = {"mitteilung": False, "gesprochen": False}
    if status.get("art") == "budget_usd_je_tag":
        _, _, wirksam = tagesdeckel(root)
        satz = ("Tagesdeckel erreicht: %s USD. Ich starte nichts Neues mehr. "
                "Du kannst für heute weitere %s USD freigeben."
                % (wirksam if wirksam is not None else "?", FREIGABE_SCHRITT))
        gemeldet["mitteilung"] = _mitteilung("JACK — Tagesdeckel erreicht", satz)
        gemeldet["gesprochen"] = _ansagen(root, satz)
    try:
        betrieb.append(betrieb.area(root) / DECKELBUCH,
                       {"zeit": betrieb.now().isoformat(), "weg": weg,
                        "entscheidung": "nicht gestartet",
                        "deckel": status.get("art"), "fenster": status.get("fenster"),
                        "meldung": "erste und einzige in diesem Fenster",
                        "mitteilung_gezeigt": gemeldet["mitteilung"],
                        "angesagt": gemeldet["gesprochen"],
                        "grund": status.get("grund")})
    except Exception:
        pass
    return True


def stand_fuer_tafel(root):
    """Budgetstand als Anteil und als Betrag - fuer die Auftragstafel."""
    g = lesen(root)
    v = verbrauch(root)
    raus = {"grenzen": g, "verbrauch": v}
    def zwei(betrag):
        return ("%.4f" % betrag).rstrip("0").rstrip(".") or "0"

    for feld, wert_feld, name in (("budget_usd_je_stunde", "stunde_usd", "stunde"),
                                  ("budget_usd_je_tag", "tag_usd", "tag")):
        deckel = g.get(feld)
        if feld == "budget_usd_je_tag":
            _, _, wirksam = tagesdeckel(root, g)
            if wirksam is not None:
                deckel = str(wirksam)
        ist = Decimal(v[wert_feld])
        gem = Decimal(v.get(wert_feld + "_gemeldet", "0"))
        gesch = Decimal(v.get(wert_feld + "_geschaetzt", "0"))
        # Block 10: Immer sichtbar, was Rechnung ist und was Schaetzung.
        herkunft = "%s USD gemeldet + %s USD geschätzt" % (zwei(gem), zwei(gesch))
        if deckel in (None, "", 0):
            raus[name] = {"deckel": None, "usd": zwei(ist), "anteil": None,
                          "gemeldet": zwei(gem), "geschaetzt": zwei(gesch),
                          "text": "%s USD (%s); kein Deckel gesetzt" % (zwei(ist), herkunft)}
        else:
            d = Decimal(str(deckel))
            anteil = float(ist / d) if d else None
            raus[name] = {"deckel": str(d), "usd": zwei(ist),
                          "gemeldet": zwei(gem), "geschaetzt": zwei(gesch),
                          "anteil": round(anteil, 4) if anteil is not None else None,
                          "text": "%s von %s USD (%.0f %%) · %s"
                                  % (zwei(ist), d, (anteil or 0) * 100, herkunft)}
    for feld, wert_feld, name in (("laeufe_je_stunde", "stunde_laeufe", "stunde_laeufe"),
                                  ("laeufe_je_tag", "tag_laeufe", "tag_laeufe")):
        deckel = g.get(feld)
        ist = int(v[wert_feld])
        if deckel in (None, "", 0):
            raus[name] = {"deckel": None, "laeufe": ist, "anteil": None,
                          "text": "%d Laeufe; kein Deckel gesetzt" % ist}
        else:
            d = int(deckel)
            raus[name] = {"deckel": d, "laeufe": ist, "anteil": round(ist / d, 4) if d else None,
                          "text": "%d von %d Laeufen (%.0f %%)" % (ist, d, 100 * ist / d if d else 0)}
    raus["geld_belastbar"] = v["stunde_ohne_betrag"] == 0 and v["tag_ohne_betrag"] == 0
    raus["preisquelle"] = v.get("preisquelle", "")
    raus["geld_hinweis"] = (
        "Zu %d von %d Laeufen des Tages meldet der Anbieter keinen Geldbetrag. "
        "Fuer %d davon rechnet JACK den Betrag aus dem Tokenverbrauch und den "
        "belegten Listenpreisen — das ist eine SCHAETZUNG, keine Rechnung "
        "(Quelle: %s). Fuer die restlichen %d liegt kein belegter Preis vor; "
        "sie bleiben unbeziffert und werden nur gezaehlt."
        % (v["tag_ohne_betrag"] + v["tag_laeufe_geschaetzt"], v["tag_laeufe"],
           v["tag_laeufe_geschaetzt"], v.get("preisquelle", "ohne Quelle"),
           v["tag_ohne_betrag"]))
    status = deckel_status(root, g, v)
    erreicht, grund = status["erreicht"], status["grund"]
    raus["gesperrt"] = erreicht
    raus["grund"] = grund
    # Nur der TAGESdeckel laesst sich freigeben. Ein erreichter Stundendeckel
    # geht von selbst vorbei, wenn die Stunde vorbei ist - dafuer braucht es
    # keine Freigabe, und eine Karte dafuer waere eine Falschmeldung.
    tag_erreicht = status.get("art") == "budget_usd_je_tag"
    # Block 30: Die Tagesbilanz zeigt Deckel, Verbrauch, Freigaben und die
    # Auftraege, die wegen des Deckels warten.
    basis, summe, wirksam = tagesdeckel(root, g)
    anzahl, _, liste = freigaben(root)
    wartend = []
    try:
        ordner = Path(root) / "auftraege" / "offen"
        wartend = sorted(d.name for d in ordner.glob("*.md"))
    except OSError:
        wartend = []
    raus["tagesbilanz"] = {
        "deckel_grund_usd": str(basis) if basis is not None else None,
        "freigaben_anzahl": anzahl,
        "freigaben_usd": str(summe),
        "freigaben": [{"zeit": f.get("zeit", ""), "weg": f.get("weg", ""),
                       "betrag_usd": f.get("betrag_usd", "")} for f in liste],
        "deckel_wirksam_usd": str(wirksam) if wirksam is not None else None,
        "verbrauch_usd": v["tag_usd"],
        "wartende_auftraege": len(wartend),
        "wartende_namen": wartend[:12],
        "schritt_usd": str(FREIGABE_SCHRITT),
        "tagesdeckel_erreicht": tag_erreicht,
        "satz": ("Tagesdeckel erreicht. %d Auftrag/Aufträge warten. Der Patron kann für "
                 "heute weitere %s USD freigeben." % (len(wartend), FREIGABE_SCHRITT))
                if tag_erreicht else ""}
    return raus


def setzen(root, **felder):
    """Aendert die Steuerdatei. Nur benannte Felder, alles andere bleibt."""
    daten = lesen(root)
    daten.update({k: v for k, v in felder.items() if v is not None})
    schreiben(root, daten)
    return daten


if __name__ == "__main__":
    import sys
    root = Path(__file__).resolve().parent
    if "--deckel" in sys.argv:
        # Fuer den Arbeiter. DREI Rueckgabewerte, nicht zwei:
        #   0 = Deckel erreicht, Grund steht auf der Ausgabe -> nicht starten
        #   1 = frei, es darf gestartet werden
        #   2 = die Pruefung selbst ist fehlgeschlagen -> NICHT starten
        # Der dritte Fall ist der wichtige: Bis zum 16.09.2026 stuerzte diese
        # Pruefung unter -I ab, und der Absturz galt als "frei". Ein Deckel,
        # der bei einer Stoerung oeffnet, ist kein Deckel.
        try:
            erreicht, grund = deckel_erreicht(root)
        except Exception as fehler:
            print("Deckelpruefung fehlgeschlagen: %s" % fehler, file=sys.stderr)
            raise SystemExit(2)
        if erreicht:
            print(grund)
            raise SystemExit(0)
        raise SystemExit(1)
    if "--freigabe-patron" in sys.argv:
        # Der lange, unbequeme Name ist Absicht: diese Zeile tippt der Patron
        # oder sie kommt aus dem Knopf der Oberflaeche - nie aus einer Routine.
        weg = "text"
        for arg in sys.argv[sys.argv.index("--freigabe-patron") + 1:]:
            if arg in ("knopf", "sprache", "text"):
                weg = arg
        pruefstand = "--pruefstand" in sys.argv
        try:
            neu = freigabe_erteilen(root, weg, pruefstand=pruefstand)
        except ValueError as fehler:
            print(str(fehler), file=sys.stderr)
            raise SystemExit(2)
        print(json.dumps({"freigabe": "erteilt", "weg": weg, "pruefstand": pruefstand,
                          "schritt_usd": str(FREIGABE_SCHRITT),
                          "tagesdeckel_neu_usd": neu,
                          "gilt_bis": "Mitternacht"}, ensure_ascii=False))
        raise SystemExit(0)
    if "--setzen" in sys.argv:
        paare = {}
        for arg in sys.argv[sys.argv.index("--setzen") + 1:]:
            if "=" in arg:
                k, v = arg.split("=", 1)
                paare[k] = None if v in ("", "-") else (int(v) if v.isdigit() else v)
        print(json.dumps(setzen(root, **paare), ensure_ascii=False, indent=2))
        raise SystemExit(0)
    print(json.dumps(stand_fuer_tafel(root), ensure_ascii=False, indent=2))
