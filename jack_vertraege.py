#!/usr/bin/env python3
"""Abo- und Vertragsregister (Block 8, Teil C und D).

Betriebsmodus teilautomatisiert, Entscheidung des Patrons vom 16.09.2026 nach
dem Vorbild PATRONOS 25_FINANCE_KOSTEN_KONTROLLE:

  JACK bereitet vor, rechnet, erinnert und fordert Freigabe an.
  JACK zahlt nie, kuendigt nie, schliesst nie ab.

Was JACK nicht weiss, heisst "unbekannt" - mit Quelle. Es wird nichts
geschaetzt, ohne dass danebensteht, dass es geschaetzt ist.

Nur Bordmittel.
"""
import datetime as dt
import json
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

_HIER = str(Path(__file__).resolve().parent)
if _HIER not in sys.path:
    sys.path.insert(0, _HIER)

import jack_betrieb as b
from jack_speicher import atomic_bytes

DATEI = "vertragsregister.json"
PROTOKOLL = "vertraege.jsonl"
REGISTER_MD = Path("11_Lieferanten") / "ABO_UND_VERTRAGSREGISTER.md"
BERICHTE = Path("12_Finanzen") / "Ausgaben"

SPALTEN = ("anbieter", "zweck", "marke", "preis", "intervall", "zahlungsweg",
           "beginn", "laufzeit", "kuendigungsfrist", "naechste_verlaengerung",
           "letzte_nutzung", "status", "quelle")

UNBEKANNT = "unbekannt"

STANDARD = {
    "schema": 1,
    "hinweis": ("Abos und Vertraege. GUELTIG wird eine Zeile erst, wenn der "
                "Patron den Entwurf im Freigaben-Kasten freigegeben hat. "
                "Unbekannte Felder stehen als 'unbekannt' mit Quelle - nie "
                "geraten. JACK zahlt, kuendigt und schliesst nichts ab."),
    "gueltig_seit": None,
    "zeilen": [],
    "entwurf": None,
}

# Anbieter, die JACK aus dem eigenen Betrieb kennt. Alles andere bekommt
# "unbekannt - Patron fragen" statt einer erfundenen Zahl.
BEKANNTE = {
    "anthropic.com": ("Anthropic", "Modelle fuer JACK und die Agenten", "JACK"),
    "openai.com": ("OpenAI", "unbekannt - Patron fragen", ""),
    "higgsfield.ai": ("Higgsfield", "Bild und Video", ""),
    "render.com": ("Render", "Hosting", "PATRONOS"),
    "supabase.com": ("Supabase", "Datenbank", "PATRONOS"),
    "supabase.io": ("Supabase", "Datenbank", "PATRONOS"),
    "vercel.com": ("Vercel", "Hosting und Auslieferung", "PATRONOS"),
    "tailscale.com": ("Tailscale", "Privates Netz, Handy-Zugang", "JACK"),
    "github.com": ("GitHub", "Quelltextverwaltung", ""),
    "united-domains.de": ("united-domains", "Domains und Postfaecher", "HOLDING"),
    "udag.de": ("united-domains", "Domains und Postfaecher", "HOLDING"),
    "apple.com": ("Apple", "iCloud und Geraete", ""),
    "google.com": ("Google", "Konto und Dienste", ""),
    "stripe.com": ("Stripe", "Zahlungen", ""),
    "coachy.net": ("Coachy", "Kursplattform", "MEISTERWERK"),
    "klick-tipp.com": ("Klick-Tipp", "E-Mail-Marketing", ""),
    "calendly.com": ("Calendly", "Termine", ""),
    "cloudflare.com": ("Cloudflare", "Netz und Schutz", ""),
    "notion.so": ("Notion", "Notizen", ""),
    "elevenlabs.io": ("ElevenLabs", "Stimme", "JACK"),
}

# Woran JACK erkennt, wie oft gezahlt wird. Nur eindeutige Faelle.
INTERVALL = [
    (r"j[aä]hrlich|annual|per year|/year|yearly|12 monate", "jährlich"),
    (r"monatlich|monthly|per month|/month|/mo\b", "monatlich"),
    (r"nutzungsbasiert|pay as you go|usage|verbrauch", "nutzungsbasiert"),
]
BETRAG = re.compile(r"(?:(EUR|USD|CHF|€|\$)\s?)?(\d{1,4}(?:[.,]\d{2})?)\s?(EUR|USD|CHF|€|\$)?")


def pfad(root):
    return b.area(root) / DATEI


def lesen(root):
    p = pfad(root)
    try:
        if p.is_symlink():
            raise ValueError("Register darf kein Verweis sein")
        daten = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return json.loads(json.dumps(STANDARD))
    fertig = json.loads(json.dumps(STANDARD))
    fertig.update(daten if isinstance(daten, dict) else {})
    if not isinstance(fertig.get("zeilen"), list):
        fertig["zeilen"] = []
    return fertig


def schreiben(root, daten):
    atomic_bytes(pfad(root), (json.dumps(daten, ensure_ascii=False, indent=1) + "\n").encode())
    return daten


def protokoll(root, art, **felder):
    try:
        e = {"zeit": b.now().isoformat(), "art": art}
        e.update(felder)
        with (b.area(root) / PROTOKOLL).open("a", encoding="utf-8") as d:
            d.write(json.dumps(e, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _leerzeile(anbieter, quelle):
    zeile = {s: UNBEKANNT for s in SPALTEN}
    zeile["anbieter"] = anbieter
    zeile["status"] = "pruefen"
    zeile["quelle"] = quelle
    return zeile


# ------------------------------------------------------------- Erstbefuellung
def _spuren(root):
    """Rechnungsspuren aus dem Altbestand und dem laufenden Posteingang."""
    raus = []
    for name in ("altbestand_rechnungen.jsonl", "posteingang.jsonl"):
        p = b.area(root) / name
        try:
            for zeile in p.read_text(encoding="utf-8").splitlines():
                if not zeile.strip():
                    continue
                e = json.loads(zeile)
                betreff = str(e.get("betreff") or "")
                domain = str(e.get("domain") or
                             (e.get("absender") or "").split("@")[-1].strip("> ")).lower()
                if not domain:
                    continue
                if name == "posteingang.jsonl" and not re.search(
                        r"rechnung|invoice|receipt|zahlung|payment|abo|subscription|"
                        r"verl[aä]ngerung|renewal|billing", betreff, re.I):
                    continue
                raus.append({"domain": domain, "betreff": betreff,
                             "datum": str(e.get("datum") or e.get("zeit") or "")[:60],
                             "quelle": name})
        except (OSError, ValueError):
            continue
    return raus


ABLAGE_MUSTER = re.compile(
    r"vertrag|abo|rechnung|invoice|lizenz|licence|license|subscription|"
    r"kuendig|k[uü]ndig|agb|nda|auftragsbest|verlaengerung|laufzeit", re.I)


def _ablage(root):
    """Zweite Quelle: was in der Ablage nach Vertrag oder Rechnung aussieht.

    Es wird NUR der Dateiname gelesen, nie der Inhalt. Eine Zeile aus dieser
    Quelle ist ein Hinweis, kein Befund - sie steht auf "pruefen".
    """
    raus = []
    wurzel = Path(root).parent.parent      # ... /GOTT WALD HOLDING
    for ordner in ("03_Vertraege", "11_Lieferanten", "12_Finanzen/Ausgaben"):
        p = wurzel / ordner
        if not p.is_dir():
            continue
        try:
            for datei in sorted(p.rglob("*")):
                if datei.is_dir() or datei.name.startswith("."):
                    continue
                if not ABLAGE_MUSTER.search(datei.name):
                    continue
                # Das eigene Register ist keine Quelle fuer sich selbst.
                if datei.name.upper().startswith("ABO_UND_VERTRAGSREGISTER"):
                    continue
                raus.append({"name": datei.name, "ordner": ordner,
                             "quelle": "Ablage " + ordner})
                if len(raus) >= 40:
                    return raus
        except OSError:
            continue
    return raus


def _grunddomain(domain):
    """mail.anthropic.com -> anthropic.com. Absender nutzen Unterdomains."""
    teile = [t for t in str(domain or "").lower().split(".") if t]
    return ".".join(teile[-2:]) if len(teile) >= 2 else (teile[0] if teile else "")


def _intervall_aus(text):
    for muster, wort in INTERVALL:
        if re.search(muster, text, re.I):
            return wort
    return UNBEKANNT


def entwurf_bauen(root):
    """Sammelt die Zeilen und legt sie als ENTWURF ab - nie als gueltig.

    Regelbasiert, ohne Modell. Was nicht eindeutig ableitbar ist, bleibt
    "unbekannt" und traegt die Quelle, aus der die Zeile ueberhaupt stammt.
    """
    spuren = _spuren(root)
    nach_domain = {}
    for s in spuren:
        e = nach_domain.setdefault(s["domain"], {"anzahl": 0, "betreffe": [], "letzte": ""})
        e["anzahl"] += 1
        if len(e["betreffe"]) < 6:
            e["betreffe"].append(s["betreff"])
        if s["datum"] > e["letzte"]:
            e["letzte"] = s["datum"]
        e["quelle"] = s["quelle"]
    zeilen = []
    for domain, e in sorted(nach_domain.items(), key=lambda x: -x[1]["anzahl"]):
        grund = _grunddomain(domain)
        name, zweck, marke = BEKANNTE.get(grund,
                                          BEKANNTE.get(domain,
                                          (grund or domain, UNBEKANNT + " — Patron fragen", "")))
        text = " ".join(e["betreffe"])
        zeile = _leerzeile(name, "Mail-Kopfzeilen (%s), %d Nachricht(en), zuletzt %s"
                           % (e.get("quelle", "?"), e["anzahl"], (e["letzte"] or UNBEKANNT)[:32]))
        zeile["zweck"] = zweck
        zeile["marke"] = marke or UNBEKANNT
        zeile["intervall"] = _intervall_aus(text)
        zeile["letzte_nutzung"] = _nutzung(root, grund)
        zeilen.append(zeile)
    for datei in _ablage(root):
        zeilen.append({**_leerzeile(datei["name"][:80], datei["quelle"]),
                       "zweck": "Beleg in der Ablage — Inhalt nicht gelesen",
                       "status": "pruefen"})
    daten = lesen(root)
    daten["entwurf"] = {"erstellt": b.now().isoformat(), "zeilen": zeilen,
                        "quellen": ["betrieb/altbestand_rechnungen.jsonl",
                                    "betrieb/posteingang.jsonl",
                                    "03_Vertraege", "11_Lieferanten", "12_Finanzen/Ausgaben"],
                        "status": "wartet auf Freigabe"}
    schreiben(root, daten)
    protokoll(root, "entwurf_gebaut", zeilen=len(zeilen))
    _freigabe_anfordern(root, len(zeilen))
    return daten["entwurf"]


def _nutzung(root, domain):
    """Letzte Nutzung, soweit JACK sie aus dem eigenen Betrieb kennt."""
    domain = _grunddomain(domain)
    if domain == "anthropic.com":
        try:
            import jack_kosten
            zeiten = [r.get("zeit") for r in jack_kosten.rows(root) if r.get("zeit")]
            if zeiten:
                return max(zeiten)[:10] + " (Verbrauchsbuch)"
        except Exception:
            pass
    if domain == "tailscale.com":
        p = b.area(root) / "zugriffe_handy.jsonl"
        try:
            zeilen = [z for z in p.read_text(encoding="utf-8").splitlines() if z.strip()]
            if zeilen:
                return json.loads(zeilen[-1])["zeit"][:10] + " (Handy-Zugriffe)"
        except (OSError, ValueError, KeyError):
            pass
    return UNBEKANNT + " — Patron fragen"


def _freigabe_anfordern(root, anzahl):
    """Legt den Entwurf in den Freigaben-Fluss. Ohne Ja bleibt er Entwurf.

    F-78 (29.09.2026): echte v2-Werte statt der Altform. "Unbekannte Felder stehen als 'unbekannt'"
    im Fliesstext bezieht sich auf einzelne ZELLEN der Vertragstabelle (dort ist das ausdruecklich
    erlaubt/ehrlich) - nicht auf die Pflichtfelder dieser Karte selbst, die alle echt gefuellt sind."""
    import jack_freigaben
    v2 = {
        "projekt": "Abo- und Vertragsregister", "marke": "HOLDING",
        "eingegangen": b.now().strftime("%Y-%m-%d %H:%M"), "von": "JACK-Kostenwächter",
        "an": "Patron", "art": "vertragsregister",
        "betreff": "Vertragsregister freigeben (%d Zeilen)" % anzahl,
        "kern": "Der Entwurf des Abo- und Vertragsregisters liegt vor: %d Zeilen aus "
                "Mail-Kopfzeilen und der Ablage." % anzahl,
        "frage": "Vertragsregister so freigeben?",
        "empfehlung": "FREIGEBEN übernimmt den Entwurf als gültiges Register - dabei wird nichts "
                      "gezahlt, gekündigt oder abgeschlossen.",
        "frist": "keine", "dringlichkeit": "niedrig",
        "ablauf": "FREIGEBEN übernimmt den Entwurf. Unbekannte Felder in der Tabelle stehen als "
                  "'unbekannt' - sie sind nicht geraten.",
    }
    pfad = jack_freigaben.karte_schreiben(root, v2, "\n".join([
        "## Auftrag",
        "Der Entwurf des Abo- und Vertragsregisters liegt vor: %d Zeilen aus" % anzahl,
        "Mail-Kopfzeilen und der Ablage. Erst mit FREIGEBEN gilt er.",
        "",
        "JACK hat nichts gezahlt, nichts gekuendigt und nichts abgeschlossen.",
        "Unbekannte Felder stehen als 'unbekannt' - sie sind nicht geraten.",
        "",
        "Die Tabelle steht im Freigaben-Kasten in der Vollansicht.",
        "",
    ]), herkunft="jack_vertraege._freigabe_anfordern",
       dateiname=b.now().strftime("%Y-%m-%d_%H%M%S") + "_KOSTENWAECHTER_Vertragsregister.md")
    return str(pfad) if pfad else ""


def freigeben(root):
    """Aus dem Entwurf wird das gueltige Register - erst jetzt."""
    daten = lesen(root)
    entwurf = daten.get("entwurf")
    if not entwurf or not entwurf.get("zeilen"):
        return {"ok": False, "meldung": "Es liegt kein Entwurf vor."}
    daten["zeilen"] = entwurf["zeilen"]
    daten["gueltig_seit"] = b.now().isoformat()
    daten["entwurf"] = None
    schreiben(root, daten)
    pfad_md = markdown_schreiben(root)
    protokoll(root, "register_freigegeben", zeilen=len(daten["zeilen"]), datei=pfad_md)
    return {"ok": True, "zeilen": len(daten["zeilen"]), "datei": pfad_md,
            "meldung": "Register gültig mit %d Zeilen." % len(daten["zeilen"])}


def ablehnen(root, grund=""):
    daten = lesen(root)
    if not daten.get("entwurf"):
        return {"ok": False, "meldung": "Es liegt kein Entwurf vor."}
    daten["entwurf"]["status"] = "abgelehnt: " + (str(grund)[:200] or "ohne Begründung")
    schreiben(root, daten)
    protokoll(root, "register_abgelehnt", grund=str(grund)[:200])
    return {"ok": True, "meldung": "Der Entwurf bleibt Entwurf. Nichts wurde gültig."}


def markdown_schreiben(root):
    daten = lesen(root)
    ziel = Path(root).parent.parent / REGISTER_MD
    ziel.parent.mkdir(parents=True, exist_ok=True)
    kopf = "| " + " | ".join(s.replace("_", " ").title() for s in SPALTEN) + " |"
    strich = "|" + "|".join(["---"] * len(SPALTEN)) + "|"
    zeilen = ["| " + " | ".join(str(z.get(s, UNBEKANNT)).replace("|", "/") for s in SPALTEN) + " |"
              for z in daten.get("zeilen", [])]
    text = "\n".join([
        "# Abo- und Vertragsregister — GOTT WALD HOLDING",
        "",
        "> Gültig seit: %s" % (daten.get("gueltig_seit") or "noch nicht freigegeben"),
        "> Maschinenform: `00_Marken/JACK/betrieb/vertragsregister.json`",
        "",
        "JACK bereitet dieses Register vor und hält es nach. **Er zahlt nicht,",
        "kündigt nicht und schließt nichts ab** — jede Handlung braucht die",
        "Freigabe des Patrons. Was nicht belegt ist, steht als *unbekannt* da;",
        "nichts ist geschätzt, ohne dass es dabeisteht.",
        "",
        kopf, strich, *zeilen,
        "",
        "Stand: %s" % b.now().strftime("%d.%m.%Y, %H:%M Uhr"),
        "",
    ])
    atomic_bytes(ziel, text.encode("utf-8"))
    return str(REGISTER_MD)


# ---------------------------------------------------------------- Fristen
def fristen(root, in_tagen=(30, 7)):
    """Welche Verlaengerung oder Frist steht in 30 bzw. 7 Tagen an?"""
    daten = lesen(root)
    heute = b.now().date()
    faellig = []
    for z in daten.get("zeilen", []):
        tag = str(z.get("naechste_verlaengerung") or "")
        try:
            wann = dt.date.fromisoformat(tag[:10])
        except ValueError:
            continue
        rest = (wann - heute).days
        if rest in in_tagen or (0 <= rest <= min(in_tagen)):
            faellig.append({"anbieter": z.get("anbieter"), "datum": tag[:10],
                            "in_tagen": rest, "frist": z.get("kuendigungsfrist"),
                            "preis": z.get("preis"), "quelle": z.get("quelle")})
    return {"zeit": b.now().isoformat(), "faellig": faellig,
            "hinweis": "Ohne Datum in der Zeile kann keine Frist errechnet werden."}


def kuendigungsentwurf(root, anbieter, absender=""):
    """D2: Ein Kuendigungsschreiben als ENTWURF - niemals gesendet.

    Kuendigen faellt unter die Dauersperre "Vertraege". Der Entwurf geht in den
    Freigaben-Fluss; ohne das Ja des Patrons verlaesst er den Mac nicht.
    """
    name = str(anbieter or "").strip()[:80]
    if not name:
        raise ValueError("Ohne Anbieter kein Entwurf")
    zeile = next((z for z in lesen(root).get("zeilen", [])
                  if str(z.get("anbieter")) == name), None)
    text = "\n".join([
        "Sehr geehrte Damen und Herren,",
        "",
        "hiermit kündige ich den bestehenden Vertrag zum nächstmöglichen Termin.",
        "Bitte bestätigen Sie mir den Eingang und das Vertragsende schriftlich.",
        "",
        "Anbieter: %s" % name,
        "Nächste Verlängerung laut unseren Unterlagen: %s"
        % ((zeile or {}).get("naechste_verlaengerung") or UNBEKANNT),
        "Kündigungsfrist laut unseren Unterlagen: %s"
        % ((zeile or {}).get("kuendigungsfrist") or UNBEKANNT),
        "",
        "Mit freundlichen Grüßen",
        "Mathias Gottwald, Patron",
        "GOTT WALD HOLDING LLC",
        "",
        "--",
        "ENTWURF. Von JACK vorbereitet, NICHT gesendet. Angaben mit 'unbekannt'",
        "sind nicht geraten - sie stehen so im Register.",
        "Die Empfängeradresse ist bewusst unbelegt (unbekannt@example.invalid):",
        "JACK kennt sie nicht und erfindet keine. Der Patron trägt sie ein.",
    ])
    # Eine erfundene Adresse waere schlimmer als gar keine. .invalid ist dafuer
    # reserviert und kann nirgendwohin zugestellt werden.
    pfad_entwurf = b.email_draft(root, "unbekannt@example.invalid",
                                 "Kündigung " + name, text)
    import jack_freigaben
    # F-78 (29.09.2026): echte v2-Werte statt der Altform (nur art/auftrag/marke). "an" ist bewusst
    # NICHT die Platzhalter-Mailadresse (unbekannt@example.invalid) - das waere selbst wieder ein
    # Platzhalter im Pflichtfeld; "an" bezeichnet hier den Anbieter, an den die Kündigung geht.
    v2 = {
        "projekt": "Vertragskündigung", "marke": "HOLDING",
        "eingegangen": b.now().strftime("%Y-%m-%d %H:%M"), "von": "JACK-Vertragswächter",
        "an": name, "art": "kuendigung", "betreff": "Kündigungsentwurf %s" % name,
        "kern": "Ein Kündigungsentwurf für %s liegt bereit, wurde NICHT gesendet." % name,
        "frage": "Kündigung an %s so freigeben und senden?" % name,
        "empfehlung": "Erst die Empfängeradresse eintragen (JACK kennt sie nicht und erfindet "
                      "keine), dann prüfen und freigeben.",
        "frist": "keine", "dringlichkeit": "niedrig",
        "ablauf": "Kündigungen fallen unter die Dauersperre Verträge: ohne das Ja des Patrons "
                  "verlässt nichts den Mac.",
    }
    pfad = jack_freigaben.karte_schreiben(root, v2, "\n".join([
        "## Auftrag",
        "Ein Kündigungsentwurf für %s liegt bereit. Er wurde **nicht gesendet**." % name,
        "Kündigungen fallen unter die Dauersperre Verträge: ohne das Ja des",
        "Patrons verlässt nichts den Mac.",
        "",
        "Entwurf: %s" % pfad_entwurf,
        "",
    ]), herkunft="jack_vertraege.kuendigungsentwurf",
       dateiname=b.now().strftime("%Y-%m-%d_%H%M%S") + "_KUENDIGUNG_" +
                 re.sub(r"[^A-Za-z0-9]+", "_", name)[:40] + ".md")
    protokoll(root, "kuendigungsentwurf", anbieter=name, datei=str(pfad_entwurf))
    if pfad is None:
        return {"ok": False, "anbieter": name, "entwurf": str(pfad_entwurf), "gesendet": False,
                "meldung": "Kartenkopf unvollstaendig - siehe Fehlerkarte in abnahme/pm_eingang/."}
    return {"ok": True, "anbieter": name, "entwurf": str(pfad_entwurf),
            "freigabe": str(pfad), "gesendet": False,
            "meldung": "Kündigungsentwurf für %s erstellt. NICHT gesendet — er wartet "
                       "im Freigaben-Kasten." % name}


def monatsbericht(root, monat=None, test=False):
    """Bericht am 1. des Monats: was ist angefallen, was schlaegt JACK vor."""
    import jack_kosten
    heute = b.now().date()
    if not monat:
        vormonat = heute.replace(day=1) - dt.timedelta(days=1)
        monat = vormonat.strftime("%Y-%m")
    byid = {}
    for row in jack_kosten.rows(root):
        ident = row.get("id")
        if not ident:
            continue
        byid[ident] = row if row.get("ereignis") == "ende" else byid.get(ident, row)
    summe = Decimal(0)
    je_art = {}
    for r in byid.values():
        if r.get("historisch") or r.get("usd_gemeldet") is None:
            continue
        if not str(r.get("zeit", "")).startswith(monat):
            continue
        try:
            betrag = Decimal(r["usd_gemeldet"])
        except InvalidOperation:
            continue
        summe += betrag
        je_art[r.get("art")] = je_art.get(r.get("art"), Decimal(0)) + betrag
    daten = lesen(root)
    vorschlaege = []
    for z in daten.get("zeilen", []):
        nutzung = str(z.get("letzte_nutzung") or "")
        if nutzung.startswith(UNBEKANNT):
            vorschlaege.append((z.get("anbieter"), "PRÜFEN",
                                "Letzte Nutzung unbekannt — der Patron weiß es, JACK nicht."))
        else:
            try:
                wann = dt.date.fromisoformat(nutzung[:10])
                if (heute - wann).days > 60:
                    vorschlaege.append((z.get("anbieter"), "KÜNDIGEN PRÜFEN",
                                        "Seit %d Tagen nicht genutzt (%s)."
                                        % ((heute - wann).days, nutzung)))
                else:
                    vorschlaege.append((z.get("anbieter"), "BEHALTEN",
                                        "Zuletzt genutzt %s." % nutzung))
            except ValueError:
                vorschlaege.append((z.get("anbieter"), "PRÜFEN", "Nutzungsdatum unlesbar."))
    name = ("TEST_" if test else "") + "Kostenwaechter_%s.md" % monat
    ziel = Path(root).parent.parent / BERICHTE / name
    ziel.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join([
        "# Kostenwächter %s" % monat,
        "",
        "> Erstellt am %s von JACK. **Kein Zahlungsvorgang, keine Kündigung.**"
        % b.now().strftime("%d.%m.%Y"),
        "",
        "## Gemessene Modellkosten",
        "",
        "Gesamt im Monat: **%s USD** (nur Läufe mit gemeldetem Betrag)." % _z(summe),
        "",
        *(["- %s: %s USD" % (a, _z(w)) for a, w in sorted(je_art.items())] or
          ["- keine Läufe mit gemeldetem Betrag in diesem Monat"]),
        "",
        "Abo-Gebühren und Zahlungen außerhalb der API sind hier **nicht** enthalten —",
        "sie stehen im Register, soweit sie dort belegt sind.",
        "",
        "## Vorschläge",
        "",
        *(["- **%s** — %s: %s" % (a, e, g) for a, e, g in vorschlaege] or
          ["- Das Register ist leer oder noch nicht freigegeben."]),
        "",
        "## Was JACK nicht getan hat",
        "",
        "Nichts gezahlt, nichts gekündigt, nichts abgeschlossen. Jede dieser",
        "Handlungen braucht die Freigabe des Patrons.",
        "",
    ])
    atomic_bytes(ziel, text.encode("utf-8"))
    protokoll(root, "monatsbericht", monat=monat, usd=_z(summe), datei=str(ziel.name), test=test)
    return {"ok": True, "monat": monat, "usd": _z(summe), "datei": str(ziel),
            "vorschlaege": len(vorschlaege)}


def _z(wert):
    return str(Decimal(wert).quantize(Decimal("0.01")))


def lage(root):
    """Kurzsicht fuer die Maske."""
    daten = lesen(root)
    entwurf = daten.get("entwurf")
    return {"zeit": b.now().isoformat(),
            "gueltig_seit": daten.get("gueltig_seit"),
            "zeilen": len(daten.get("zeilen", [])),
            "entwurf_zeilen": len((entwurf or {}).get("zeilen", [])) if entwurf else 0,
            "entwurf_status": (entwurf or {}).get("status") if entwurf else "",
            "entwurf": entwurf,
            "spalten": list(SPALTEN),
            "fristen": fristen(root)["faellig"],
            "register": daten.get("zeilen", []),
            "quelle": "betrieb/vertragsregister.json"}


def tick(root, at=None):
    """Haengt sich in die bestehende Fuenf-Minuten-Routine. Kein zweiter Zeitgeber.

    D1: Am 1. des Monats zwischen 08:00 und 08:59 wird der Bericht einmal
    geschrieben. D2: Fristen in 30 und 7 Tagen kommen ins Briefing.
    """
    jetzt = at or b.now()
    raus = []
    merker = b.area(root) / "kostenwaechter_stand.json"
    try:
        stand = json.loads(merker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        stand = {}
    if jetzt.day == 1 and jetzt.hour == 8:
        monat = (jetzt.date().replace(day=1) - dt.timedelta(days=1)).strftime("%Y-%m")
        if stand.get("monatsbericht") != monat:
            try:
                ergebnis = monatsbericht(root, monat)
                stand["monatsbericht"] = monat
                raus.append("Kostenwächter %s geschrieben" % monat)
                _freigabe_bericht(root, ergebnis)
            except Exception as fehler:
                protokoll(root, "monatsbericht_fehler", grund=str(fehler)[:160])
    heute = jetzt.date().isoformat()
    if stand.get("fristen_geprueft") != heute:
        stand["fristen_geprueft"] = heute
        faellig = fristen(root)["faellig"]
        if faellig:
            raus.append("%d Frist(en) stehen an" % len(faellig))
    try:
        atomic_bytes(merker, (json.dumps(stand, ensure_ascii=False, indent=1) + "\n").encode())
    except Exception:
        pass
    return raus


def _freigabe_bericht(root, ergebnis):
    # F-78 (29.09.2026): echte v2-Werte statt der Altform. "kostenbericht" ist NICHT in
    # ENTSCHEIDUNGSARTEN - reine Kenntnisnahme, kein FREIGEBEN-Weg. Das aendert F-78 nicht.
    import jack_freigaben
    v2 = {
        "projekt": "Kostenwächter", "marke": "HOLDING",
        "eingegangen": b.now().strftime("%Y-%m-%d %H:%M"), "von": "JACK-Kostenwächter",
        "an": "Patron", "art": "kostenbericht",
        "betreff": "Kostenwächter %s zur Kenntnis" % ergebnis["monat"],
        "kern": "Monatsbericht %s: %s USD gemessene Modellkosten, %d Vorschläge zu Abos und "
                "Verträgen." % (ergebnis["monat"], ergebnis["usd"], ergebnis["vorschlaege"]),
        "frage": "Zur Kenntnis genommen?",
        "empfehlung": "Bericht unter %s prüfen, keine Aktion durch JACK erforderlich." % ergebnis["datei"],
        "frist": "keine", "dringlichkeit": "niedrig",
        "ablauf": "ZUR KENNTNIS — JACK hat nichts gezahlt und nichts gekündigt.",
    }
    jack_freigaben.karte_schreiben(root, v2, "\n".join([
        "## Auftrag",
        "Der Monatsbericht liegt vor: %s USD gemessene Modellkosten," % ergebnis["usd"],
        "%d Vorschläge zu Abos und Verträgen." % ergebnis["vorschlaege"],
        "Datei: %s" % ergebnis["datei"],
        "",
        "JACK hat nichts gezahlt und nichts gekündigt.",
        "",
    ]), herkunft="jack_vertraege._freigabe_bericht",
       dateiname=b.now().strftime("%Y-%m-%d_%H%M%S") + "_KOSTENWAECHTER_Monatsbericht.md")


if __name__ == "__main__":
    wurzel = Path(__file__).resolve().parent
    was = sys.argv[1] if len(sys.argv) > 1 else "lage"
    if was == "entwurf":
        print(json.dumps(entwurf_bauen(wurzel), ensure_ascii=False, indent=1)[:4000])
    elif was == "freigeben":
        print(json.dumps(freigeben(wurzel), ensure_ascii=False))
    elif was == "bericht":
        print(json.dumps(monatsbericht(wurzel, sys.argv[2] if len(sys.argv) > 2 else None,
                                       test="--test" in sys.argv), ensure_ascii=False))
    else:
        print(json.dumps(lage(wurzel), ensure_ascii=False, indent=1)[:3000])
