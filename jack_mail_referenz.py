#!/usr/bin/env python3
"""F-104 (30.09.2026): Referenz-Aufmachung fuer Mails an einen abgenommenen Empfaenger (heute: DIN, Mailart Mitarbeiter).

Der Patron hat die Zahlungsbestaetigung vom 30.09. 13:03 als Referenz abgenommen. Fuer GENAU diese Mailart an GENAU diesen Empfaenger gilt
danach: Vorschau in der Karte -> FREIGEBEN (kein Testversand, kein Code) - solange die Aufmachung (Kopf, Rahmen, Signatur, Logo) der
eingefrorenen Referenz entspricht. Weicht sie ab, ist der Versand gesperrt ("Aufmachung abweichend - Testversand noetig").
Alles andere (andere Mailart, anderer Empfaenger) behaelt TESTVERSAND -> Code -> FREIGEBEN. Kein globaler Schalter: `testpflicht_alle` bleibt true.
Regeln stehen in maildesign.json -> versand.ohne_test (Liste)."""
import datetime as dt
import email.utils
import hashlib
import json
import re
from pathlib import Path

import jack_betrieb as b

REFERENZORDNER = "mail_referenz"


def _pfad_maildesign(root):
    import jack_postfaecher as P
    return Path(root).parent.parent / P.MAILDESIGN


def regeln(root):
    import jack_postfaecher as P
    return list(((P.maildesign(root) or {}).get("versand") or {}).get("ohne_test") or [])


def regel_fuer(root, kopf):
    """Die passende Regel fuer diesen Entwurfskopf (Mailart + Empfaenger) oder None."""
    art = str(kopf.get("mailart") or "").strip().lower()
    an = [a.lower() for _, a in email.utils.getaddresses([str(kopf.get("an") or "")]) if a]
    if not art or len(an) != 1:
        return None                                   # genau EIN Empfaenger, sonst nie
    for r in regeln(root):
        if str(r.get("mailart", "")).strip().lower() == art and str(r.get("an", "")).strip().lower() == an[0]:
            return r
    return None


def _ohne_fliesstext(html):
    """Aufmachung ohne den Fliesstext: der Block `<div class="gw-text ...">...</div>` wird durch einen Platzhalter ersetzt."""
    start = html.find('<div class="gw-text')
    if start < 0:
        return html
    tiefe, i = 0, start
    for m in re.finditer(r"<(/?)div\b[^>]*>", html[start:]):
        tiefe += -1 if m.group(1) else 1
        if tiefe == 0:
            i = start + m.end()
            break
    return html[:start] + "<!--FLIESSTEXT-->" + html[i:]


def rahmen_pruefsumme(html):
    roh = re.sub(r"\s+", " ", _ohne_fliesstext(str(html or ""))).strip()
    # Datums-/Zufallsanteile duerfen die Aufmachung nicht veraendern
    roh = re.sub(r"data:image/[a-z+]+;base64,[A-Za-z0-9+/=]+", lambda m: "IMG:" + hashlib.sha256(m.group(0).encode()).hexdigest()[:16], roh)
    return hashlib.sha256(roh.encode("utf-8")).hexdigest()


def einfrieren(root, entwurf_datei, dateiname, abgenommen, quelle):
    """Rendert den Entwurf wie beim Versand, speichert das HTML als Referenz, traegt die Regel (mit Rahmen-Pruefsumme) in maildesign.json ein
    (mit Sicherung). -> Regel-dict."""
    import jack_postfaecher as P
    kopf, _ = P._entwurf_zerlegen(root, entwurf_datei)
    r = P.senden(root, entwurf_datei, test=True, ansicht=True)
    if not r.get("ok"):
        raise ValueError("Referenz nicht renderbar: " + str(r.get("meldung")))
    ziel = Path(b.area(root)) / REFERENZORDNER
    ziel.mkdir(parents=True, exist_ok=True)
    (ziel / dateiname).write_text(r["html"], encoding="utf-8")
    an = [a for _, a in email.utils.getaddresses([kopf.get("an", "")]) if a][0]
    regel = {"mailart": kopf.get("mailart", ""), "an": an, "abgenommen": abgenommen, "quelle": quelle,
             "referenz": "betrieb/%s/%s" % (REFERENZORDNER, dateiname), "rahmen_pruefsumme": rahmen_pruefsumme(r["html"]),
             "signatur": kopf.get("signatur", ""), "entwurf_der_referenz": str(entwurf_datei)}
    pfad = _pfad_maildesign(root)
    daten = json.loads(pfad.read_text(encoding="utf-8"))
    sicher = pfad.with_name(pfad.name + ".vor_F104")
    if not sicher.exists():
        sicher.write_text(pfad.read_text(encoding="utf-8"), encoding="utf-8")
    liste = [x for x in (daten.setdefault("versand", {}).get("ohne_test") or []) if not (str(x.get("mailart")).lower() == str(regel["mailart"]).lower() and str(x.get("an")).lower() == an.lower())]
    liste.append(regel)
    daten["versand"]["ohne_test"] = liste
    pfad.write_text(json.dumps(daten, ensure_ascii=False, indent=2), encoding="utf-8")
    return regel


def aufmachung_passt(regel, html):
    """(bool, Satz). Vergleicht die Rahmen-Pruefsumme des frisch gerenderten HTML mit der Referenz."""
    if rahmen_pruefsumme(html) == regel.get("rahmen_pruefsumme"):
        return True, "Aufmachung entspricht der abgenommenen Referenz (%s)." % regel.get("abgenommen", "")
    return False, "Aufmachung abweichend — Testversand nötig."


def abweichung_melden(root, entwurf, regel):
    """Meldung an PM (Datei in abnahme/pm_eingang/), einmal je Entwurf."""
    ordner = Path(root) / "abnahme" / "pm_eingang"
    ordner.mkdir(parents=True, exist_ok=True)
    name = ordner / ("F-104_AUFMACHUNG_ABWEICHEND_%s.md" % re.sub(r"[^\w.-]+", "_", str(entwurf))[:80])
    if not name.exists():
        name.write_text("# Aufmachung abweichend (F-104)\n\nDer Versand von `%s` an %s (%s) wurde gesperrt: Kopf/Rahmen/Signatur weichen von der abgenommenen Referenz %s ab. "
                        "Der Patron muss TESTVERSAND → Code → FREIGEBEN nutzen, oder PM prüft die Änderung an der Vorlage.\n" % (entwurf, regel.get("an"), regel.get("mailart"), regel.get("referenz")), encoding="utf-8")
