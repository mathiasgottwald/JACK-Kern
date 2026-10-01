"""Vorberechnete Lage fuer den Dialog (S-2b P1, 25.09.2026).

Statt bei jeder Frage eine Kette von Werkzeugaufrufen zu fahren, liegt eine kompakte Lage-Datei bereit
(betrieb/sprache_lage.json, hoechstens ~2.000 Token). Sie wird alle 2 Minuten im Serverprozess neu geschrieben
(lagefaden in server.py) und bei Bedarf beim Fragen aufgefrischt. Nur Daten aus bestehenden Endstellen, KEINE
KI-Aufrufe. Inhalt: Freigaben, Auftraege, je Hausname (Mitarbeiter) die letzten 5 Mails mit 1-Satz-Kern, Termine
heute/morgen, Guthaben, "brennt"-Liste. Kennzeichnung "Stand <Zeit>".

Die Lage verlaesst den Mac nur als Teil des normalen Dialogaufrufs (wie heute die Werkzeugergebnisse).
"""
import datetime as dt
import email
import email.policy
import json
import re
import threading
import time
from pathlib import Path

import jack_betrieb as b

DATEI = "sprache_lage.json"
VERSION = 5     # erhoehen, wenn sich das Format aendert - eine Lage-Datei anderer Version wird sofort neu berechnet
MAX_ZEICHEN = 6500          # ~2.000 Token
KURZ_ZEICHEN = 700          # Lage-Kurzfassung fuer die schnelle Stufe
MAX_ALTER_S = 120           # Takt
DIALOG_MAX_ALTER_S = 300    # aelter: Werkzeuge nutzen
_LOCK = threading.Lock()


def _jetzt():
    return b.now()


def _kuerzen(text, n):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _wann(zeit_iso):
    """Relative Angabe gegen JETZT: 'heute 15:53', 'gestern 15:53', 'vor 3 Tagen (21.09. 15:53)' - das Modell soll
    nie 'heute' sagen, wenn die Mail von gestern ist (Opus-Stichprobe S-2b)."""
    try:
        t = dt.datetime.fromisoformat(str(zeit_iso)).astimezone(_jetzt().tzinfo)
    except (TypeError, ValueError):
        return str(zeit_iso)[:16]
    tage = (_jetzt().date() - t.date()).days
    uhr = t.strftime("%H:%M")
    if tage <= 0:
        return "heute " + uhr
    if tage == 1:
        return "gestern " + uhr
    return "vor %d Tagen (%s %s)" % (tage, t.strftime("%d.%m."), uhr)


def _titel_aus_datei(name):
    t = re.sub(r"^\d{4}-\d{2}-\d{2}(_\d{4,6})?_", "", str(name))
    t = re.sub(r"\.md$", "", t)
    t = re.sub(r"_ENTWURF$", "", t)
    return _kuerzen(t.replace("_", " ").replace("-", " "), 70)


def _freigaben(root):
    """S-10: je Thema das ECHTE Alter (aus `angefordert`), gleiche Themen zusammengelegt ('2 Mal'), aelteste Freigabe als fertiger Wert -
    das Modell soll Alter und Rangfolge nicht mehr erfinden muessen."""
    try:
        import jack_freigaben
        offen = jack_freigaben.offene(root)
    except Exception:
        return {"anzahl": None, "themen": []}
    gruppen, reihenfolge, gruende = {}, [], {}
    offen_alle, offen = offen, [e for e in offen if e.get("status") != "erteilt"]     # nur wirklich wartende (nicht 'erteilt')
    for e in offen:                                   # offene() ist nach 'angefordert' aufsteigend sortiert
        titel = _titel_aus_datei(e.get("datei", ""))
        if titel not in gruppen:
            gruppen[titel] = []
            reihenfolge.append(titel)
        gruppen[titel].append(e.get("angefordert"))
        if e.get("grund") and titel not in gruende:
            gruende[titel] = _kuerzen(e["grund"], 60)
    themen = []
    for titel in reihenfolge[:8]:
        zeiten = gruppen[titel]
        grund = gruende.get(titel)
        text = "%s (%sangefordert %s" % (titel, (grund + "; ") if grund else "", _wann(zeiten[0]))
        if not zeiten[0]:
            text = "%s (%s" % (titel, grund or "ohne Zeitangabe")
        elif len(zeiten) > 1:
            text = "%s (%s%d Mal angefordert, zuerst %s, zuletzt %s" % (titel, (grund + "; ") if grund else "", len(zeiten), _wann(zeiten[0]), _wann(zeiten[-1]))
        themen.append(text + ")")
    aus = {"anzahl": len(offen_alle), "themen": themen}
    if offen and offen[0].get("angefordert"):
        aus["aelteste_freigabe"] = "%s, angefordert %s" % (_titel_aus_datei(offen[0].get("datei", "")), _wann(offen[0].get("angefordert")))
    return aus


def _auftraege(root):
    aus = {}
    for ordner in ("offen", "laeuft", "freigabe", "problem"):
        p = Path(root) / "auftraege" / ordner
        try:
            namen = sorted(x.name for x in p.glob("*.md") if not x.name.lower().startswith("readme"))
        except OSError:
            namen = []
        aus[ordner] = {"anzahl": len(namen), "beispiele": [_titel_aus_datei(n) for n in namen[:3]] if ordner != "freigabe" else []}
    return aus


def _kern_aus_eml(root, kennung, pfad):
    """Erster inhaltlicher Satz der Mail (ohne KI), hoechstens 110 Zeichen."""
    try:
        import jack_mitarbeiter
        datei = jack_mitarbeiter.ordner(root, kennung) / pfad
        if not datei.is_file() or datei.stat().st_size > 400_000:
            return ""
        msg = email.message_from_bytes(datei.read_bytes(), policy=email.policy.default)
        teil = msg.get_body(preferencelist=("plain", "html"))
        text = teil.get_content() if teil else ""
        if teil is not None and teil.get_content_type() == "text/html":
            import html as _html
            text = re.sub(r"(?is)<(style|script|head)[^>]*>.*?</\1>", " ", text)
            text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h\d>|</li>", "\n", text)
            text = _html.unescape(re.sub(r"<[^>]+>", " ", text))
    except Exception:
        return ""
    zeilen = [z.strip() for z in str(text).splitlines() if z.strip() and not z.strip().startswith((">", "--", "On ", "Am ", "Von:", "From:"))]
    zeilen = [z for z in zeilen if not re.fullmatch(r"(hi|hallo|hello|dear|guten tag)[^.!?]{0,30}[,!.]?", z, re.I)]
    if not zeilen:
        return ""
    satz = re.split(r"(?<=[.!?])\s", " ".join(zeilen[:3]))[0]
    return _kuerzen(satz, 110)


def _mails_je_mitarbeiter(root):
    aus = []
    try:
        import jack_hausnamen
        import jack_mitarbeiter
        import jack_postfaecher
        personen = jack_hausnamen.hausnamen(root)["mitarbeiter"]
    except Exception:
        return aus
    for m in personen:
        try:
            r = jack_postfaecher.posteingang(root, mitarbeiter=m["id"], hoechstens=300)
            alle = r.get("mails", [])
            mails = alle[:5]
            idx = jack_mitarbeiter.index(root, m["id"], hoechstens=600)
        except Exception:
            continue
        nach_quelle = {}
        for e in idx:
            q = str(e.get("quelle") or "")
            mm = re.search(r"UID (\d+)", q)
            if mm:
                nach_quelle[(q.split(" UID")[0].replace("Postfach ", "").strip(), mm.group(1))] = e
        liste = []
        for x in mails:
            e = nach_quelle.get((str(x.get("postfach")), str(x.get("uid"))))
            liste.append({"von": _kuerzen((re.sub(r"<.*?>", "", x.get("absender", "")).strip() or str(x.get("absender", "")).strip("<> ")), 40),
                          "betreff": _kuerzen(x.get("betreff"), 70), "wann": _wann(x.get("zeit", "")),
                          "kern": _kern_aus_eml(root, m["id"], e["pfad"]) if e and e.get("pfad") else ""})
        aus.append({"name": m["anzeige"], "mails_insgesamt": len(alle), "neueste_mail": (liste[0]["wann"] if liste else None), "letzte": liste,
                    "hinweis": "nur die letzten 5; aeltere Mails nur ueber Werkzeug, nie 'das ist alles' sagen"})
    return aus


def _termine(root):
    try:
        import jack_kalender
        u = jack_kalender.uebersicht(root)
    except Exception:
        return {"heute": [], "morgen": [], "stand": "Kalender nicht lesbar"}
    heute = _jetzt().date()
    morgen = heute + dt.timedelta(days=1)

    def tag(ev):
        s = str(ev.get("beginn", ""))[:8]
        try:
            return dt.datetime.strptime(s, "%Y%m%d").date()
        except ValueError:
            return None

    def zeile(ev):
        s = str(ev.get("beginn", ""))
        uhr = (s[9:11] + ":" + s[11:13]) if len(s) >= 13 and not ev.get("ganztaegig") else "ganztägig"
        return uhr + " " + _kuerzen(ev.get("titel"), 50)
    alle = list(u.get("heute") or []) + [e for e in (u.get("sieben_tage") or [])]
    gesehen, h, mo = set(), [], []
    for e in alle:
        key = (e.get("uid"), e.get("beginn"))
        if key in gesehen:
            continue
        gesehen.add(key)
        d = tag(e)
        if d == heute:
            h.append(zeile(e))
        elif d == morgen:
            mo.append(zeile(e))
    return {"heute": h[:6], "morgen": mo[:6]}


def _guthaben(root):
    try:
        import jack_guthaben
        s = jack_guthaben.stand(root) or {}
        g = {"rest_usd": s.get("rest_usd"), "ampel": s.get("ampel"), "satz": _kuerzen(s.get("satz"), 160)}
        if isinstance(s.get("reichweite_tage"), int):        # S-3c P2: fertige Zahl aus der bestehenden Endstelle, das Modell rechnet nicht
            g["reichweite_tage"] = s["reichweite_tage"]
        return g
    except Exception:
        return {"rest_usd": None, "ampel": None, "satz": ""}


def _brennt(freigaben, auftraege, guthaben, termine):
    liste = []
    if auftraege.get("problem", {}).get("anzahl"):
        liste.append("%d Auftrag/Aufträge im Problem: %s" % (auftraege["problem"]["anzahl"], "; ".join(auftraege["problem"]["beispiele"])))
    if (freigaben.get("anzahl") or 0) >= 15:
        liste.append("%d Freigaben warten auf den Patron" % freigaben["anzahl"])
    if guthaben.get("ampel") in ("rot", "gelb"):
        liste.append("Guthaben " + str(guthaben.get("ampel")) + ": " + str(guthaben.get("satz")))
    if termine.get("heute"):
        liste.append("Termine heute: " + "; ".join(termine["heute"][:3]))
    return liste[:6]


def bauen(root):
    jetzt = _jetzt()
    freigaben, auftraege, guthaben, termine = _freigaben(root), _auftraege(root), _guthaben(root), _termine(root)
    lage = {"version": VERSION, "stand": jetzt.isoformat(), "stand_kurz": jetzt.strftime("%d.%m. %H:%M"),
            "heute_ist": jetzt.strftime("%A, %d.%m.%Y").replace("Monday", "Montag").replace("Tuesday", "Dienstag").replace("Wednesday", "Mittwoch").replace("Thursday", "Donnerstag").replace("Friday", "Freitag").replace("Saturday", "Samstag").replace("Sunday", "Sonntag"),
            "hinweis": "Vorberechnet aus lokalen Daten, keine KI. Volltexte und Details nur ueber Werkzeuge.",
            "freigaben": freigaben, "auftraege": auftraege, "mitarbeiter": _mails_je_mitarbeiter(root),
            "termine": termine, "guthaben": guthaben}
    lage["brennt"] = _brennt(freigaben, auftraege, guthaben, termine)
    # auf das Token-Limit bringen: erst Kerne und Themen einkuerzen, dann Mails
    text = json.dumps(lage, ensure_ascii=False)
    while len(text) > MAX_ZEICHEN:
        gekuerzt = False
        for m in lage["mitarbeiter"]:
            if any(x.get("kern") for x in m["letzte"]):
                for x in reversed(m["letzte"]):
                    if x.get("kern"):
                        x["kern"] = ""
                        gekuerzt = True
                        break
                if gekuerzt:
                    break
        if not gekuerzt:
            for m in lage["mitarbeiter"]:
                if len(m["letzte"]) > 1:
                    m["letzte"].pop()
                    gekuerzt = True
                    break
        if not gekuerzt and len(lage["freigaben"]["themen"]) > 2:
            lage["freigaben"]["themen"].pop()
            gekuerzt = True
        if not gekuerzt:
            break
        text = json.dumps(lage, ensure_ascii=False)
    return lage


def schreiben(root):
    with _LOCK:
        lage = bauen(root)
        ziel = b.area(root) / DATEI
        tmp = ziel.with_suffix(".tmp")
        tmp.write_text(json.dumps(lage, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(ziel)
    return lage


def lesen(root):
    try:
        return json.loads((b.area(root) / DATEI).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def alter_s(lage):
    try:
        return (_jetzt() - dt.datetime.fromisoformat(lage["stand"])).total_seconds()
    except (KeyError, TypeError, ValueError):
        return 1e9


def frisch(root, max_alter_s=MAX_ALTER_S):
    """Liest die Lage; ist sie aelter als max_alter_s, wird sie jetzt neu berechnet (lokal, schnell)."""
    lage = lesen(root)
    if lage is None or lage.get("version") != VERSION or alter_s(lage) > max_alter_s:
        try:
            lage = schreiben(root)
        except Exception:
            pass
    return lage


def dialog_text(root, kurz=False):
    """Text fuer den Systemtext. kurz=True: Lage-Kurzfassung fuer die schnelle Stufe (ohne Mailkerne)."""
    lage = frisch(root)
    if not lage:
        return ""
    alter = alter_s(lage)
    if kurz:
        f, a, g = lage["freigaben"], lage["auftraege"], lage["guthaben"]
        teile = ["Lage (Stand %s): %s Freigaben warten" % (lage["stand_kurz"], f.get("anzahl")),
                 "%s Aufträge offen/laufend" % (a["offen"]["anzahl"] + a["laeuft"]["anzahl"])]
        if g.get("rest_usd"):
            teile.append("Guthaben rechnerisch %s USD" % g["rest_usd"] + (", Reichweite %d Tage" % g["reichweite_tage"] if g.get("reichweite_tage") is not None else ""))
        if lage.get("brennt"):
            teile.append("brennt: " + "; ".join(lage["brennt"][:2]))
        return _kuerzen(". ".join(teile), KURZ_ZEICHEN)
    kopf = ("# Lage (vorberechnet, Stand %s)\nReicht diese Lage für die Antwort, antworte direkt ohne Werkzeugaufruf. "
            "Werkzeuge nur für Details, Volltexte oder Dinge, die hier nicht stehen. "
            "Sprich trotzdem kurz: höchstens drei Sätze, unter 60 Wörter, nur das Wichtigste, keine Aufzählung aller Mails oder Freigaben "
            "(es sei denn, der Patron bittet ausdrücklich um Ausführlichkeit). "
            "Zeitangaben genau wie in der Lage nennen („gestern“, „vor 2 Tagen“); nie „heute“ sagen, wenn dort „gestern“ oder älter steht. " % lage["stand_kurz"])
    if alter > DIALOG_MAX_ALTER_S:
        kopf += "ACHTUNG: Die Lage ist älter als 5 Minuten - prüfe mit Werkzeugen nach.\n"
    else:
        kopf += "\n"
    return kopf + json.dumps({k: v for k, v in lage.items() if k not in ("hinweis", "stand")}, ensure_ascii=False)


def tick(root, at=None):
    """Fuer den Betriebstakt/lagefaden: schreibt die Lage neu. Gibt eine Liste geschriebener Dateien zurueck."""
    schreiben(root)
    return []
