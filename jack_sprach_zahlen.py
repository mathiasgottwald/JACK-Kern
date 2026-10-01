# -*- coding: utf-8 -*-
"""S-5 P1: Stufe 0 fuer ZAEHLFRAGEN - der Chat rechnet nicht mehr selbst. Feste Muster, 0 USD, sofort; die Zahlen kommen aus denselben
Quellen wie das Dashboard (jack_freigaben.offene, jack_grenzen.verbrauch/tagesdeckel, Auftragsordner, PM-Postfach). Kein Modell, keine geratene Zahl.
antwort_fuer(root, frage) -> (text, quelle) oder None."""
import datetime as _dt
import re
from pathlib import Path

_FUELL = r"(?:jack |bitte |mal |denn |eigentlich |so |gerade |aktuell |jetzt |im moment |noch |eigentlich )*"


def _falten(t):
    t = str(t or "").lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        t = t.replace(a, b)
    return " ".join(re.findall(r"[a-z0-9]+", t))


MUSTER = {
    "freigaben": [r"wie viele freigaben( warten| liegen| stehen| gibt es| haben wir| sind offen| sind es| sind da| liegen an| warten auf mich| warten gerade)*( auf mich| offen| noch| jetzt| aktuell| gerade)*"],
    "ausgaben": [r"(was|wie viel|wieviel) haben wir heute (ausgegeben|verbraucht|bezahlt)", r"(was|wie viel|wieviel) hab ich heute (ausgegeben|verbraucht)",
                 r"wie hoch sind (die )?(kosten|ausgaben) (von )?heute", r"was kostet(en)? uns (das )?heute( bisher| schon)?", r"(die )?(heutigen|tages) ?(kosten|ausgaben)",
                 r"was haben wir bisher heute (ausgegeben|verbraucht)", r"wie viel geld haben wir heute (ausgegeben|verbraucht)"],
    "laeuft": [r"was laeuft( denn)?( gerade| aktuell| im moment| jetzt)?( so)?", r"woran wird( gerade| aktuell| jetzt)? gearbeitet", r"was ist gerade in arbeit"],
    "lage": [r"was liegt an", r"was steht an", r"was ist los", r"was gibt es neues", r"was gibts neues", r"was gibt s neues", r"gibt es (was|etwas) neues", r"gibt s (was|etwas) neues", r"gibts (was|etwas) neues",
             r"was ist neu", r"eilt (was|etwas)", r"brennt (was|etwas)", r"ist (was|etwas|irgendwas|irgendetwas) dringend", r"gibt es (was|etwas|irgendwas) dringendes", r"gibt s (was|etwas|irgendwas) dringendes",
             r"gibts (was|etwas|irgendwas) dringendes", r"wie ist die lage", r"wie sieht die lage aus", r"wie sieht es aus", r"wie sieht s aus", r"was ist die lage", r"lagebericht", r"lage bitte", r"ist alles ruhig",
             r"gibt es probleme", r"gibt s probleme", r"gibts probleme", r"ist irgendwas los", r"ist was los", r"was liegt bei uns an", r"was steht bei uns an"],
    "wartet": [r"was wartet( gerade| aktuell| jetzt)?( denn)? auf mich", r"was liegt( gerade| aktuell)? fuer mich an", r"was muss ich( heute| jetzt| noch)? (freigeben|entscheiden)",
               r"was steht( gerade| aktuell)? bei mir an"],
}


def erkennen(frage):
    t = _falten(frage)
    t = re.sub(r"^(?:jack |hey jack |hallo jack |also |sag mal |sag |kannst du mir sagen |weisst du |ich wuerde gern wissen |sag mir )+", "", t)
    for art, muster in MUSTER.items():
        for m in muster:
            if re.fullmatch(_FUELL + m + r"(?: bitte| mal| jack| denn)*", t):
                return art
    return None


def _de(zahl):
    return ("%.2f" % float(zahl)).replace(".", ",")


def _freigaben(root):
    import jack_sprach_lage as L
    f = L._freigaben(root)
    return f["anzahl"], f["themen"]


def _satz_freigaben(root, mit_themen=False):
    n, themen = _freigaben(root)
    if n is None:
        return "Die Freigabe-Liste kann ich gerade nicht lesen.", "Freigaben-Liste nicht lesbar"
    if n == 0:
        return "Keine Freigabe wartet.", "jack_freigaben.offene: 0"
    kopf = ("Eine Freigabe wartet auf dich." if n == 1 else "%d Freigaben warten auf dich." % n)
    zeig = [re.sub(r"\s*\(.*$", "", t) for t in themen[:2] if t] if mit_themen else []      # S-10: Themen tragen jetzt Alter in Klammern; gesprochen wird nur der Titel
    return kopf + ((" Zuoberst: " + "; ".join(zeig) + ".") if zeig else ""), "jack_freigaben.offene: %d" % n


def _satz_ausgaben(root):
    import jack_grenzen as g
    v = g.verbrauch(root)
    tag = v.get("tag_usd")
    try:
        deckel = g.tagesdeckel(root)[2]
    except Exception:
        deckel = None
    text = "Heute stehen %s Dollar in den Büchern, bei %s Läufen." % (_de(tag), v.get("tag_laeufe", 0))
    if deckel is not None:
        text += " Der Tagesdeckel liegt bei %s Dollar." % _de(deckel)
    text += " Das ist der gebuchte Stand - noch nicht nachgebuchte Testläufe fehlen darin."
    return text, "jack_grenzen.verbrauch: tag_usd %s" % tag


def _postfach(root):
    aus = {}
    basis = Path(root) / "auftraege" / "pm_ausgang"
    try:
        for ordner in sorted(p for p in basis.iterdir() if p.is_dir() and p.name != "erledigt"):
            n = len([x for x in ordner.glob("*.md") if not x.name.lower().startswith("readme")])
            if n:
                aus[ordner.name] = n
    except OSError:
        pass
    return aus


def _satz_laeuft(root):
    import jack_sprach_lage as L
    a = L._auftraege(root)
    laeuft, offen = a["laeuft"]["anzahl"], a["offen"]["anzahl"]
    teile = []
    teile.append("Im Auftragsordner laufen gerade %d Aufträge, %d warten auf den Start." % (laeuft, offen) if (laeuft or offen) else "Im Auftragsordner läuft gerade nichts.")
    pf = _postfach(root)
    if pf:
        teile.append("Im PM-Postfach liegen %d Aufträge: %s." % (sum(pf.values()), ", ".join("%s %d" % kv for kv in pf.items())))
    return " ".join(teile), "Auftragsordner + PM-Postfach"


def _satz_wartet(root):
    import jack_sprach_lage as L
    satz, quelle = _satz_freigaben(root, mit_themen=True)
    a = L._auftraege(root)
    extra = []
    if a["problem"]["anzahl"]:
        extra.append("%d Auftrag%s im Problem-Status." % (a["problem"]["anzahl"], "" if a["problem"]["anzahl"] == 1 else "e hängen"))
    return " ".join([satz] + extra), quelle + " + Problem-Aufträge"


# ------------------------------------------------------------------ S-11: Lage-/Dringlichkeitsantworten NUR aus Daten
def _netz(root):
    import json
    import jack_betrieb
    try:
        return json.loads((jack_betrieb.area(root) / "netz.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _laeufername(k):
    return re.sub(r"\s+", " ", str(k).replace("postfach_", "Postfach ").replace("_", " ")).strip().capitalize() if not str(k).startswith("postfach_") else "Postfach " + str(k)[9:].replace("_", " ").capitalize()


def _frist_wort(t, jetzt):
    if t < jetzt:
        return "überfällig"
    tage = (t.date() - jetzt.date()).days
    return "Frist heute" if tage <= 0 else "Frist morgen"


_DATUM_KARTE = re.compile(r"(?:frist|faellig|fällig|zahlungsziel|termin|bis)\W{0,4}(?:\d{1,2}\.\d{1,2}\.(?:\d{2,4})?|\d{4}-\d{2}-\d{2})", re.I)


def _patron_punkte(root):
    """(alle, mit Datum): Karten in wartet_patron/. 'Mit Datum' = Kartenkopf nennt eine Frist/Faelligkeit mit Datum."""
    p = Path(root) / "auftraege" / "pm_ausgang" / "wartet_patron"
    if not p.is_dir():
        return 0, 0
    karten = [x for x in p.glob("*.md") if not x.name.lower().startswith("readme")]
    mit = 0
    for k in karten:
        try:
            kopf = "\n".join(k.read_text(encoding="utf-8", errors="replace").splitlines()[:30])
        except OSError:
            continue
        if _DATUM_KARTE.search(kopf):
            mit += 1
    return len(karten), mit


def lage_fakten(root):
    """Alle Fakten fuer 'was liegt an / eilt was' aus den Endstellen: Freigaben (jack_freigaben.offene), Laeufer (betrieb/netz.json), Patron-Ordner
    (wartet_patron/), Kalender + Guthaben (Lage), Problem-Auftraege. Fehlt eine Quelle, steht sie in `luecken` - dann ist Ruhe nie erlaubt."""
    import jack_sprach_lage as L
    f = {"freigaben": 0, "themen": 0, "fristen": [], "aelteste": None, "laeufer_rot": [], "patron_wartet": 0, "patron_mit_datum": 0, "probleme": 0, "termine_heute": [], "ampel": None, "reichweite": None, "luecken": []}
    try:
        import jack_freigaben
        offen = [e for e in jack_freigaben.offene(root) if e.get("status") != "erteilt"]
        f["freigaben"] = len(offen)
        f["themen"] = len({str(e.get("thema") or "allgemein") for e in offen})
        # S-12: 'dringend' NUR aus einer echten Frist (frist innerhalb 24 h oder ueberschritten) - nie aus dem Ablauf der Kennung (F-55)
        jetzt = _dt.datetime.now().astimezone()
        for e in offen:
            fr = e.get("frist")
            if not fr:
                continue
            try:
                t = _dt.datetime.fromisoformat(str(fr))
                t = t if t.tzinfo else t.astimezone()
            except ValueError:
                continue
            if t <= jetzt + _dt.timedelta(hours=24):
                f["fristen"].append((str(e.get("thema") or "allgemein"), _frist_wort(t, jetzt)))
        zeiten = [e.get("angefordert") for e in offen if e.get("angefordert")]
        f["aelteste"] = L._wann(min(zeiten)) if zeiten else None
    except Exception:
        f["luecken"].append("Freigaben")
    n = _netz(root)
    if n is None:
        f["luecken"].append("Läufer")
    else:
        if n.get("online") is False:
            f["laeufer_rot"].append("Netz (offline)")
        for k, v in (n.get("laeufer") or {}).items():
            if isinstance(v, dict) and v.get("status") != "ok":
                f["laeufer_rot"].append("%s (%s)" % (_laeufername(k), str(v.get("status")).replace("_", " ")))
    try:
        f["patron_wartet"], f["patron_mit_datum"] = _patron_punkte(root)
    except OSError:
        f["luecken"].append("Patron-Ordner")
    try:
        f["probleme"] = L._auftraege(root)["problem"]["anzahl"]
    except Exception:
        f["luecken"].append("Aufträge")
    lage = L.lesen(root) or {}
    t = lage.get("termine")
    if isinstance(t, dict) and not t.get("stand"):
        f["termine_heute"] = list(t.get("heute") or [])
    else:
        f["luecken"].append("Kalender")
    g = lage.get("guthaben") or L._guthaben(root)
    f["ampel"], f["reichweite"] = g.get("ampel"), g.get("reichweite_tage")
    if not f["ampel"]:
        f["luecken"].append("Kostenwächter")
    return f


def ruhig_erlaubt(f):
    """'Nichts eilt / nichts Neues / alles ruhig' ist NUR erlaubt: keine offene Freigabe UND kein Laeufer rot UND kein Patron-Wartepunkt
    (dazu: keine Problem-Auftraege, kein gelbes/rotes Guthaben, keine Termine heute, keine Datenluecke)."""
    return (f["freigaben"] == 0 and not f["laeufer_rot"] and f["patron_wartet"] == 0 and f["probleme"] == 0
            and f["ampel"] not in ("gelb", "rot") and not f["termine_heute"] and not f["luecken"])


def dringend_liste(f):
    """Was heute wirklich dringend ist: Freigaben mit echter Frist (<= 24 h), rote Laeufer, Patron-Punkte mit Datum."""
    d = ["%s (%s)" % (thema, wort) for thema, wort in f["fristen"]]
    d += ["Läufer %s" % x for x in f["laeufer_rot"]]
    if f["patron_mit_datum"]:
        d.append("%d Punkt%s im Patron-Ordner mit Datum" % (f["patron_mit_datum"], "" if f["patron_mit_datum"] == 1 else "e"))
    return d


def lagesatz(f):
    """Der lokale Lagesatz (feste Bausteine, keine Modellformulierung, keine Liste)."""
    if ruhig_erlaubt(f):
        return "Nichts wartet: keine Freigabe, kein Läufer rot, nichts im Patron-Ordner, heute keine Termine. Guthaben %s%s." % (
            f["ampel"], (", Reichweite %d Tage" % f["reichweite"]) if isinstance(f["reichweite"], int) else "")
    teile = []
    dr = dringend_liste(f)
    if f["freigaben"]:
        n, m = f["freigaben"], f["themen"]
        kopf = ("Eine Freigabe zu %s Thema" % ("einem" if m == 1 else m)) if n == 1 else "%d Freigaben zu %s" % (n, "einem Thema" if m == 1 else "%d Themen" % m)
        if dr:
            satz = "%s %s; davon %d dringend (%s)" % (kopf, "wartet" if n == 1 else "warten", len(dr), "; ".join(dr[:3]))
        else:
            satz = "%s %s, nichts davon mit Frist" % (kopf, "wartet" if n == 1 else "warten")
        if f["aelteste"]:
            satz += "; die älteste ist von %s" % f["aelteste"]
        teile.append(satz + ".")
    elif dr:
        teile.append("Dringend: %s." % "; ".join(dr[:3]))
    if f["laeufer_rot"] and f["freigaben"]:
        teile.append("Nicht in Ordnung: %s." % "; ".join(f["laeufer_rot"][:3]))
    if f["patron_wartet"] and not (f["patron_mit_datum"] and not f["freigaben"]):
        teile.append("Im Patron-Ordner %s." % ("liegt ein Punkt" if f["patron_wartet"] == 1 else "liegen %d Punkte" % f["patron_wartet"]))
    if f["probleme"]:
        teile.append("%d Auftrag%s im Problem-Status." % (f["probleme"], "" if f["probleme"] == 1 else "e hängen"))
    if f["termine_heute"]:
        teile.append("Heute: %s." % "; ".join(f["termine_heute"][:3]))
    if f["ampel"] in ("gelb", "rot"):
        teile.append("Das Guthaben steht auf %s." % f["ampel"])
    if f["luecken"]:
        teile.append("Nicht lesbar: %s." % ", ".join(f["luecken"]))
    return " ".join(teile)


def _satz_lage(root):
    f = lage_fakten(root)
    return lagesatz(f), "lage_fakten: Freigaben %d, Läufer rot %d, Patron-Ordner %d" % (f["freigaben"], len(f["laeufer_rot"]), f["patron_wartet"])


def antwort_fuer(root, frage):
    art = erkennen(frage)
    if art is None:
        return None
    fn = {"freigaben": _satz_freigaben, "ausgaben": _satz_ausgaben, "laeuft": _satz_laeuft, "wartet": _satz_wartet, "lage": _satz_lage}[art]
    text, quelle = fn(root)
    return text, quelle
