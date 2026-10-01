#!/usr/bin/env python3
"""Mitarbeiter: Register, Stammdaten, Akte, Auftraege, Waechter.

Block 21, 17.09.2026. Grundsatz dieses Moduls - derselbe wie bei den
Postfaechern: **die Datei ist die Wahrheit.**

  * Wer Mitarbeiter ist, steht in betrieb/mitarbeiter.json (Register).
  * Was ueber ihn gilt, steht in <ordner>/00_Stammdaten/stammdaten.json.
  * Was zu ihm gehoert, steht in <ordner>/akte_index.jsonl - eine Zeile je
    Vorgang, mit dem Pfad zur Datei. Die Festplatte IST die Akte; es gibt
    keine zweite Kopie.

Sensibles: Pass, Personalausweis und das Datenblatt mit Wallet und
Steuernummer liegen ausschliesslich als Datei-VERWEIS unter
ALLGEMEIN/Dokumente/Personal. Nummern, Wallet-Adresse und Steuernummer
erscheinen nie in einem Index-Kurztext, nie in einem Protokoll, nie im HTML.
Dafuer sorgt _sauber() - jeder Text, der in den Index geht, laeuft hindurch.

Nur Bordmittel. Keine neue Abhaengigkeit.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
from pathlib import Path

import jack_betrieb as b
from jack_speicher import atomic_bytes

REGISTER = "mitarbeiter.json"          # betrieb/mitarbeiter.json
PROTOKOLL = "mitarbeiter.jsonl"        # betrieb/mitarbeiter.jsonl
INDEX = "akte_index.jsonl"             # je Mitarbeiter, in seinem Ordner
STAMMDATEI = Path("00_Stammdaten") / "stammdaten.json"
QUELLORDNER = "00_Quelle"
UNZUGEORDNET = "UNZUGEORDNET"
ALLGEMEIN = "ALLGEMEIN"

# Die sechs Faecher je Projekt. Mehr gibt es nicht - was nirgends passt,
# geht nach UNZUGEORDNET und wird vom Patron per Klick umgeordnet.
FAECHER = ("Dokumente", "Fotos", "E-Mails", "WhatsApp", "Notizen", "Auftraege")

# Welches Fach zu welcher Art gehoert.
FACH_JE_ART = {"email": "E-Mails", "whatsapp": "WhatsApp", "dokument": "Dokumente",
               "foto": "Fotos", "notiz": "Notizen", "auftrag": "Auftraege",
               "bericht": "Notizen"}
ARTEN = tuple(sorted(set(FACH_JE_ART)))
RICHTUNGEN = ("ein", "aus", "intern")


# ---------------------------------------------------------------- Grundlagen
def _area(root):
    return b.area(root)


def holding(root):
    """Die Wurzel der Holding - zwei Ebenen ueber 00_Marken/JACK."""
    return Path(root).resolve().parent.parent


def _lesen(p, ersatz):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return json.loads(json.dumps(ersatz))


def _schreiben(p, wert):
    """Atomar - eine halb geschriebene Stammdatei waere schlimmer als keine."""
    atomic_bytes(Path(p), json.dumps(wert, ensure_ascii=False, indent=1).encode("utf-8"))


def protokoll(root, art, **felder):
    try:
        e = {"zeit": b.now().isoformat(), "art": art}
        e.update({k: v for k, v in felder.items() if v is not None})
        b.append(_area(root) / PROTOKOLL, e)
    except Exception:
        pass


# ──────────────── Sensibles: eine Stelle, die putzt ────────────────────────
# Lange Ziffernfolgen (Pass, Ausweis, Steuernummer) und alles, was nach einer
# Wallet-Adresse aussieht, haben in einem Index, einem Protokoll oder in der
# Maske nichts zu suchen. Die Datei selbst bleibt unangetastet - nur der Text,
# der herumgereicht wird, wird sauber gemacht.
_WALLET = re.compile(r"\b(0x[0-9a-fA-F]{40}|[13][a-km-zA-HJ-NP-Z1-9]{25,34}|"
                     r"bc1[0-9a-z]{20,60}|T[1-9A-HJ-NP-Za-km-z]{33})\b")
# Sieben und mehr Ziffern am Stueck: Pass, Ausweis, Steuernummer, Telefon.
_LANG = re.compile(r"\d{7,}")
# Gruppiert geschrieben (123-456-7890, 1234 5678 9012) - Datumsangaben wie
# 2026-09-17 haben zweistellige Gruppen und bleiben deshalb stehen.
_GRUPPIERT = re.compile(r"\b\d{3,5}[\s./-]\d{3,5}(?:[\s./-]\d{3,5})+\b")


def _sauber(text, laenge=300):
    """Jeder Text, der in Index, Protokoll oder Maske geht, laeuft hier durch."""
    s = str(text or "")
    s = _WALLET.sub("…", s)
    s = _GRUPPIERT.sub("…", s)
    s = _LANG.sub("…", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:laenge]


# ---------------------------------------------------------------- Register
def _standardregister():
    return {"schema": 1,
            "stand": b.now().strftime("%Y-%m-%d"),
            "hinweis": ("Wer Mitarbeiter ist. Die Wahrheit ueber EINEN Mitarbeiter "
                        "steht in <ordner>/00_Stammdaten/stammdaten.json - hier steht "
                        "nur, dass es ihn gibt und wo er liegt. Siehe "
                        "betrieb/README_MITARBEITER.md."),
            "mitarbeiter": []}


def register(root):
    p = _area(root) / REGISTER
    if not p.exists():
        _schreiben(p, _standardregister())
    d = _lesen(p, _standardregister())
    if not isinstance(d.get("mitarbeiter"), list):
        d["mitarbeiter"] = []
    return d


def _eintrag(root, kennung):
    for e in register(root)["mitarbeiter"]:
        if str(e.get("id", "")).lower() == str(kennung or "").lower():
            return e
    return None


def ordner(root, kennung):
    """Der Ordner eines Mitarbeiters, absolut. ValueError, wenn unbekannt."""
    e = _eintrag(root, kennung)
    if not e:
        raise ValueError("Diesen Mitarbeiter gibt es nicht: %s" % kennung)
    p = holding(root) / str(e.get("ordner", ""))
    if not p.is_dir():
        raise ValueError("Der Ordner von %s fehlt: %s" % (kennung, e.get("ordner")))
    return p


def stammdaten(root, kennung):
    """Die einzige Wahrheit je Mitarbeiter."""
    return _lesen(ordner(root, kennung) / STAMMDATEI, {})


def stammdaten_schreiben(root, kennung, daten):
    """Atomar, mit Sicherung. Ueberschreibt nie ohne Kopie daneben."""
    ziel = ordner(root, kennung) / STAMMDATEI
    if ziel.is_file():
        sicher = ziel.with_name(ziel.name + ".vor_" + b.now().strftime("%Y-%m-%d_%H%M%S"))
        if not sicher.exists():
            shutil.copy2(ziel, sicher)
    daten = dict(daten)
    daten["stand"] = b.now().strftime("%Y-%m-%d")
    _schreiben(ziel, daten)
    protokoll(root, "stammdaten_geschrieben", mitarbeiter=kennung)
    return daten


def projekte(root, kennung):
    """Die Projekt-IDs aus den Stammdaten, plus ALLGEMEIN und UNZUGEORDNET."""
    ids = [str(p.get("id")) for p in (stammdaten(root, kennung).get("projekte") or [])
           if p.get("id")]
    for fest in (ALLGEMEIN, UNZUGEORDNET):
        if fest not in ids:
            ids.append(fest)
    return ids


def fach(root, kennung, projekt, art):
    """Der Ordner fuer Projekt und Art - wird angelegt, wenn er fehlt."""
    projekt = str(projekt or UNZUGEORDNET)
    if projekt not in projekte(root, kennung):
        projekt = UNZUGEORDNET
    name = FACH_JE_ART.get(str(art), "Dokumente")
    ziel = ordner(root, kennung) / projekt / name
    ziel.mkdir(parents=True, exist_ok=True)
    return ziel


def ablage_anlegen(root, kennung):
    """Legt die Ordnerstruktur nach Teil C an. Loescht nie etwas."""
    basis = ordner(root, kennung)
    gebaut = []
    for projekt in projekte(root, kennung):
        for name in FAECHER:
            p = basis / projekt / name
            if not p.exists():
                p.mkdir(parents=True, exist_ok=True)
                gebaut.append(str(p.relative_to(basis)))
    p = basis / ALLGEMEIN / "Dokumente" / "Personal"
    if not p.exists():
        p.mkdir(parents=True, exist_ok=True)
        gebaut.append(str(p.relative_to(basis)))
    if gebaut:
        protokoll(root, "ablage_angelegt", mitarbeiter=kennung, anzahl=len(gebaut))
    return gebaut


# ---------------------------------------------------------------- Akte-Index
def indexpfad(root, kennung):
    return ordner(root, kennung) / INDEX


def index(root, kennung, projekt=None, art=None, suche="", hoechstens=2000):
    """Alle Eintraege, neueste zuerst. Filter wirken ohne Modell und ohne Kosten."""
    raus = []
    for zeile in b.records(indexpfad(root, kennung)):
        if projekt and str(zeile.get("projekt")) != str(projekt):
            continue
        if art and str(zeile.get("art")) != str(art):
            continue
        if suche:
            heu = " ".join(str(zeile.get(k, "")) for k in
                           ("kurztext", "von", "an", "pfad", "projekt"))
            if suche.lower() not in heu.lower():
                continue
        raus.append(zeile)
    raus.sort(key=lambda e: str(e.get("datum", "")), reverse=True)
    return raus[:hoechstens]


def _kennungen(root, kennung):
    """Die vergebenen Eintrags-IDs - fuer die Doppel-Sperre beim Import."""
    return {str(z.get("id")) for z in b.records(indexpfad(root, kennung)) if z.get("id")}


def eintragskennung(art, datum, von, text, zusatz=""):
    """Schluessel eines Vorgangs: Art + Zeitstempel + Absender + Text-Hash.

    Genau diese vier machen einen zweiten Import desselben oder eines spaeteren
    Exports harmlos - derselbe Vorgang bekommt denselben Schluessel und wird
    nicht noch einmal angehaengt.
    """
    roh = "|".join([str(art), str(datum), str(von), str(zusatz),
                    hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()])
    return hashlib.sha1(roh.encode("utf-8")).hexdigest()[:20]


def ablegen(root, kennung, eintrag, vorhandene=None):
    """Haengt EINEN Eintrag an den Index - oder nichts, wenn er schon da ist.

    Gibt (eintrag, neu) zurueck. Der Kurztext laeuft durch _sauber(); der
    Pfad steht relativ zum Mitarbeiterordner, damit die Akte umziehbar bleibt.
    """
    basis = ordner(root, kennung)
    pfad = str(eintrag.get("pfad") or "")
    if pfad:
        p = Path(pfad)
        if p.is_absolute():
            try:
                pfad = str(p.relative_to(basis))
            except ValueError:
                pfad = p.name
    projekt = str(eintrag.get("projekt") or UNZUGEORDNET)
    if projekt not in projekte(root, kennung):
        projekt = UNZUGEORDNET
    art = str(eintrag.get("art") or "dokument")
    richtung = str(eintrag.get("richtung") or "intern")
    if richtung not in RICHTUNGEN:
        richtung = "intern"
    fertig = {
        "id": str(eintrag.get("id") or eintragskennung(
            art, eintrag.get("datum"), eintrag.get("von"), eintrag.get("kurztext"))),
        "projekt": projekt,
        "art": art,
        "richtung": richtung,
        "von": _sauber(eintrag.get("von"), 120),
        "an": _sauber(eintrag.get("an"), 120),
        "datum": str(eintrag.get("datum") or b.now().isoformat()),
        "kurztext": _sauber(eintrag.get("kurztext"), 300),
        "pfad": pfad,
        "anhaenge": [str(a)[:160] for a in (eintrag.get("anhaenge") or [])][:40],
        "quelle": str(eintrag.get("quelle") or "")[:200],
        "erfasst": b.now().isoformat(),
    }
    if eintrag.get("sicherheit") is not None:
        fertig["sicherheit"] = float(eintrag["sicherheit"])
    if eintrag.get("sensibel"):
        fertig["sensibel"] = True
    if eintrag.get("hinweis"):
        fertig["hinweis"] = _sauber(eintrag["hinweis"], 300)
    if eintrag.get("zustand"):
        fertig["zustand"] = str(eintrag["zustand"])
    haben = _kennungen(root, kennung) if vorhandene is None else vorhandene
    if fertig["id"] in haben:
        return fertig, False
    b.append(indexpfad(root, kennung), fertig)
    if vorhandene is not None:
        vorhandene.add(fertig["id"])
    return fertig, True


def umordnen(root, kennung, eintrag_id, projekt, von="Patron"):
    """Der Patron ordnet einen Eintrag einem anderen Projekt zu.

    Die Zeile wird NICHT geloescht - der Index wird neu geschrieben, und die
    alte Fassung liegt als .vor_<Zeit> daneben. Die Datei selbst zieht mit um.
    """
    if projekt not in projekte(root, kennung):
        raise ValueError("Dieses Projekt gibt es nicht: %s" % projekt)
    p = indexpfad(root, kennung)
    zeilen = list(b.records(p))
    treffer = [z for z in zeilen if str(z.get("id")) == str(eintrag_id)]
    if not treffer:
        raise ValueError("Diesen Eintrag gibt es nicht.")
    e = treffer[0]
    alt = str(e.get("projekt"))
    basis = ordner(root, kennung)
    quelle = basis / str(e.get("pfad") or "")
    # Eine Datei aus 00_Quelle bleibt liegen, wo sie ist - Originale zieht
    # niemand um. Nur was JACK selbst abgelegt hat, wandert mit.
    if (e.get("pfad") and quelle.is_file()
            and not str(e["pfad"]).startswith(QUELLORDNER + "/")):
        ziel = fach(root, kennung, projekt, e.get("art")) / quelle.name
        if quelle.resolve() != ziel.resolve():
            if ziel.exists():
                ziel = ziel.with_name(ziel.stem + "_" + b.now().strftime("%H%M%S") + ziel.suffix)
            shutil.move(str(quelle), str(ziel))
            e["pfad"] = str(ziel.relative_to(basis))
    e["projekt"] = projekt
    e["umgeordnet"] = "%s von %s (vorher %s)" % (b.now().isoformat(), von, alt)
    sicher = p.with_name(p.name + ".vor_" + b.now().strftime("%Y-%m-%d_%H%M%S"))
    if p.is_file() and not sicher.exists():
        shutil.copy2(p, sicher)
    atomic_bytes(p, ("\n".join(json.dumps(z, ensure_ascii=False) for z in zeilen)
                     + "\n").encode("utf-8"))
    protokoll(root, "umgeordnet", mitarbeiter=kennung, eintrag=eintrag_id,
              von_projekt=alt, nach=projekt, wer=von)
    return e


# ──────────────── Auffaelligkeiten: eine Regel, kein Modell ────────────────
# Die Pruefung ist bewusst eine WORTLISTE, kein Modellaufruf. Sie kostet nichts
# und laeuft bei jeder Mail. Sie findet Anlaesse, keine Urteile - das Urteil
# faellt der Patron im Freigaben-Kasten.
AUFFAELLIG = [
 ("Zusage", r"\b(i (will|can) (do|deliver|finish)|promise|guarantee|zusage|"
            r"verspreche|garantier|commit to|deadline is|by (monday|tuesday|"
            r"wednesday|thursday|friday|saturday|sunday))\b"),
 ("Termin", r"\b(meeting|call|zoom|termin|appointment|schedule|reschedule|"
            r"calendar|einladung|invite)\b"),
 ("Geld", r"\b(invoice|payment|salary|usdc|usdt|wallet|bank|iban|rechnung|"
          r"gehalt|bezahl|betrag|refund|bonus|raise)\b"),
 ("Vertrag", r"\b(contract|agreement|nda|terms|sign|signature|vertrag|"
             r"vereinbarung|unterschrift|kuendig|resign|notice period)\b"),
 ("Firmendaten weitergegeben",
  r"\b(password|passwort|api[ _-]?key|credential|zugangsdaten|login|token|"
  r"confidential|vertraulich|figma\.com/file|drive\.google\.com|dropbox\.com)\b"),
 ("Ton", r"\b(unacceptable|angry|frustrated|disappointed|complain|sue|lawyer|"
         r"unzumutbar|beschwerde|anwalt|entt(ä|ae)uscht)\b"),
]


# ──────────────── Nachtrag 1c: die direkte Frage ───────────────────────────
# Fragt jemand geradeheraus, ob er mit einer Maschine schreibt, wird das
# WAHRHEITSGEMAESS beantwortet. JACK entwirft niemals eine Verneinung. Der Text
# steht fest im Code - er wird nicht von einem Modell geschrieben, damit er
# nicht von Lauf zu Lauf anders ausfaellt und nicht ausweichen kann.
DIREKTE_FRAGE = re.compile(
    r"(are you (an? )?(ai|a\.i\.|bot|robot|machine|human|real person|a real human)"
    r"|is this (an? )?(ai|bot|automated|a machine)"
    r"|am i (talking|writing|chatting) (to|with) (an? )?(ai|bot|machine|human|person|robot)"
    r"|who am i (talking|writing) (to|with)"
    r"|bist du (eine )?(ki|ai|maschine|mensch|ein mensch|ein bot)"
    r"|schreibe ich mit (einer|einem) (ki|ai|maschine|bot|menschen)"
    r"|sind sie (ein )?(mensch|ki|bot))", re.I)

# Die wahrheitsgemaesse Antwort. Englisch, Arbeitssprache des Mitarbeiters.
# Sie verneint nichts, erfindet nichts Menschliches und verspricht kein Telefonat.
DIREKTE_ANTWORT = """Thank you for asking directly — you deserve a straight answer.

You are corresponding with JACK. JACK is the Office of the Patron at GOTT WALD
HOLDING: a software system that handles correspondence, filing and scheduling on
behalf of Mathias Gottwald. JACK is not a person.

Nothing reaches you automatically. Every message sent from this address is read
and released by the Patron before it goes out, and everything you send here is
read by him as well.

If you would rather correspond with the Patron in his own words on a particular
matter, say so and it will be arranged."""


def direkte_frage(betreff, text):
    """Fragt der Absender geradeheraus? Dann die Fundstelle zurueckgeben."""
    heu = (str(betreff or "") + "\n" + str(text or ""))
    treffer = DIREKTE_FRAGE.search(heu)
    return treffer.group(0)[:160] if treffer else ""


# ──────────────── Teil G3: einen Arbeitsbericht erkennen ───────────────────
# Ein Bericht ist die Art "bericht" - daran haengt die Stundenzaehlung und die
# Berichtspruefung. Erkannt wird an Betreff ODER Form: eine Mail eines
# Mitarbeiters, die Stunden nennt oder sich selbst Bericht nennt.
_BERICHT_BETREFF = re.compile(
    r"\b(daily|status|work|progress|weekly)\s*(report|update)\b"
    r"|\breport\b|\bstatus\b|\bstandbericht\b|\barbeitsbericht\b|\btagesbericht\b"
    r"|\bwochenbericht\b|\bwhat i did\b|\bre:\s*your (first )?task\b", re.I)
_BERICHT_STUNDEN = re.compile(r"\d+(?:[.,]\d+)?\s*(?:h\b|hrs?\b|hours?|std|stunden)", re.I)


def ist_bericht(betreff, text):
    """Ist diese Mitarbeiter-Mail ein Arbeitsbericht? Konservativ geraten.

    Im Zweifel NEIN - eine falsch als Bericht gezaehlte Mail verfaelscht die
    Stunden, und eine uebersehene laesst sich von Hand nachtragen.
    """
    if _BERICHT_BETREFF.search(str(betreff or "")):
        return True
    roh = str(text or "")
    # Stunden genannt UND mehrere Zeilen Inhalt: das ist ein Bericht.
    # Eine einzelne Zeile wie "can we meet for 2 hours?" ist keiner.
    if _BERICHT_STUNDEN.search(roh) and len([z for z in roh.splitlines()
                                             if len(z.strip()) > 8]) >= 3:
        return True
    return False


def auffaelligkeiten(betreff, text):
    """Welche Anlaesse eine Mail beruehrt. Leere Liste = unauffaellig."""
    heu = (str(betreff or "") + "\n" + str(text or "")).lower()
    return [name for name, muster in AUFFAELLIG if re.search(muster, heu, re.I)]


# ---------------------------------------------------------------- Postfach
def zu_postfach(root, adresse):
    """Welcher Mitarbeiter haengt an diesem Postfach? Sonst None."""
    try:
        import jack_postfaecher
        pf = jack_postfaecher._postfach(root, adresse)
    except Exception:
        return None
    kennung = pf.get("mitarbeiter")
    return str(kennung) if kennung and _eintrag(root, kennung) else None


def projekt_raten(root, kennung, text):
    """Welches Projekt ein Text beruehrt - oder UNZUGEORDNET.

    Bewusst stumpf: nur die Projekt-IDs und ein paar feste Wortformen. Was
    nicht eindeutig ist, geht nach UNZUGEORDNET; der Patron ordnet um.
    """
    heu = str(text or "").lower()
    stichworte = {"YIG_CARE": ["yig.care", "yig care", "yigcare", "yig", "stephan"],
                  "PATRONOS": ["patronos", "patronos.ai", "sarah"],
                  "FAIRPLAY": ["fairplay", "fair play"],
                  ALLGEMEIN: ["contract", "salary", "payment", "invoice", "vertrag",
                              "gehalt", "passport", "nid", "onboarding", "signature",
                              "usdc", "wallet"]}
    punkte = {}
    for projekt in projekte(root, kennung):
        for wort in stichworte.get(projekt, []):
            if wort in heu:
                punkte[projekt] = punkte.get(projekt, 0) + heu.count(wort)
    if not punkte:
        return UNZUGEORDNET, 0.0
    beste = max(punkte.items(), key=lambda x: x[1])
    summe = sum(punkte.values()) or 1
    return beste[0], round(beste[1] / summe, 2)


ANHANG_MAX = 25 * 1024 * 1024        # 25 MB je Anhang - darueber nur der Name


def _kurztext(art, betreff, text, code_verdacht=False):
    """Der Kurztext eines Akteneintrags. Eine Stelle, damit die Regel haelt."""
    if art == "bericht":
        roh = ((betreff or "") + " · "
               + " ".join(_BERICHT_STUNDEN.findall(text or "")[:4])).strip(" ·")
    else:
        roh = betreff or (text or "")[:120]
    if code_verdacht:
        roh = re.sub(r"\d{4,}", "…", roh)
    return roh


def _anhaenge_mit_inhalt(nachricht):
    """Name, Typ UND Inhalt. jack_postfaecher._anhaenge liefert nur den Namen -
    fuer die Akte brauchen wir die Datei selbst."""
    raus = []
    if not nachricht.is_multipart():
        return raus
    try:
        import jack_postfaecher
        lesbar = jack_postfaecher._entziffern
    except Exception:
        lesbar = lambda x: str(x or "")
    for teil in nachricht.walk():
        name = teil.get_filename()
        if not name:
            continue
        try:
            daten = teil.get_payload(decode=True)
        except Exception:
            daten = None
        if daten is not None and len(daten) > ANHANG_MAX:
            daten = None
        raus.append({"name": lesbar(name), "typ": teil.get_content_type(),
                     "daten": daten})
    return raus


def mail_ablegen(root, kennung, postfach, uid, nachricht, richtung="ein",
                 vorhandene=None, projekt_vorgabe=None):
    """Eine Mail als .eml samt Anhaengen in die Akte legen und indizieren.

    Die .eml ist das Original - roher Mailtext, nichts umgeschrieben. Anhaenge
    liegen daneben in einem Unterordner mit derselben Kennung.
    """
    import email.utils
    absender = str(nachricht.get("From") or "")
    empfaenger = str(nachricht.get("To") or "")
    betreff = str(nachricht.get("Subject") or "")
    datum = str(nachricht.get("Date") or "")
    try:
        import jack_postfaecher
        absender = jack_postfaecher._entziffern(nachricht.get("From"))
        empfaenger = jack_postfaecher._entziffern(nachricht.get("To"))
        betreff = jack_postfaecher._entziffern(nachricht.get("Subject"))
        text = jack_postfaecher._text_aus(nachricht)
    except Exception:
        text = ""
    anhaenge = _anhaenge_mit_inhalt(nachricht)
    try:
        zeit = email.utils.parsedate_to_datetime(datum).isoformat()
    except Exception:
        zeit = b.now().isoformat()

    projekt, sicherheit = projekt_raten(root, kennung, betreff + "\n" + text)
    if projekt_vorgabe and richtung == "aus" and str(projekt_vorgabe) in projekte(root, kennung):
        projekt, sicherheit = str(projekt_vorgabe), 1.0            # F-104: eigene Ausgangsmail traegt ihr Projekt selbst (Zahlung -> ALLGEMEIN)
    von_uns = "office@gottwald.world" in absender.lower()              # F-103 Nachtrag PM 1 (5): unsere Mail liegt in SEINEM Postfach als "ein", ist aber eine Ausgangsmail
    if von_uns and ALLGEMEIN in projekte(root, kennung) and re.search(r"payment|zahlung|usdc|salary|invoice|überweisung|ueberweisung", betreff, re.I):
        projekt, sicherheit = ALLGEMEIN, 1.0                           # Zahlungsbestaetigung gehoert nach ALLGEMEIN, nicht nach dem Projekt der Signatur
    kenn = eintragskennung("email", zeit, absender, betreff, zusatz="%s#%s" % (postfach, uid))
    ziel = fach(root, kennung, projekt, "email")
    name = "%s_%s.eml" % (str(zeit)[:19].replace(":", "-"), kenn[:8])
    datei = ziel / name
    if not datei.exists():
        atomic_bytes(datei, nachricht.as_bytes())
    namen = []
    if anhaenge:
        unter = ziel / (datei.stem + "_Anhaenge")
        unter.mkdir(parents=True, exist_ok=True)
        for a in anhaenge:
            sauber_name = re.sub(r"[^A-Za-z0-9_.\- ]+", "_", str(a.get("name") or "anhang"))[:80]
            roh = a.get("daten")
            if roh is None:
                continue
            ap = unter / sauber_name
            if not ap.exists():
                atomic_bytes(ap, roh)
            namen.append(sauber_name)
    merk = auffaelligkeiten(betreff, text) if (richtung != "aus" and not von_uns) else []       # F-104: keine "Auffaellig: Geld"-Markierung fuer eigene Ausgangsmails
    # Zweiter Riegel zu Befund 1: Sieht eine Mail nach einem Sicherheitscode
    # aus, wird im Kurztext JEDE Ziffernfolge ab vier Stellen unkenntlich -
    # nicht erst ab sieben. Ein Code ist meist sechsstellig. Die .eml daneben
    # bleibt das Original; unkenntlich wird nur, was herumgereicht wird.
    code_verdacht = bool(re.search(
        r"code|pin|tan|einmal|verification|2fa|one[- ]?time|einmalpasswort",
        (betreff or "") + " " + (text or "")[:400], re.I))
    # Teil G3: Eine eingehende Mail, die ein Arbeitsbericht ist, wird als
    # "bericht" abgelegt. Nur daran haengt die Stundenzaehlung.
    art = "bericht" if (richtung == "ein" and ist_bericht(betreff, text)) else "email"
    eintrag, neu = ablegen(root, kennung, {
        "id": kenn, "projekt": projekt, "art": art, "richtung": richtung,
        "von": absender, "an": empfaenger, "datum": zeit,
        # Bei einem Bericht wandern die genannten Stunden in den Kurztext -
        # stunden_je_woche() liest genau dort. Ohne das waere die Zahl weg.
        "kurztext": _kurztext(art, betreff, text, code_verdacht),
        "pfad": str(datei), "anhaenge": namen or [a.get("name", "") for a in anhaenge][:40],
        "quelle": "Postfach %s UID %s" % (postfach, uid),
        "sicherheit": sicherheit,
        "hinweis": ("Auffällig: " + ", ".join(merk)) if merk else "",
    }, vorhandene)
    return eintrag, neu, merk


# ---------------------------------------------------------------- Auftraege
def auftraege(root, kennung, offen_nur=False):
    """Die Aufgabenliste des Mitarbeiters, aus dem Index."""
    raus = [e for e in index(root, kennung, art="auftrag")]
    if offen_nur:
        raus = [e for e in raus if str(e.get("zustand", "offen")) != "erledigt"]
    return raus


def auftrag_anlegen(root, kennung, projekt, titel, text, faellig="", von="JACK"):
    """Legt einen Arbeitsauftrag in die Akte. Versendet NICHTS.

    Der Versand geht ausschliesslich ueber den Freigaben-Kasten und von dort
    als Mail aus Patron@gottwald.world - siehe entwurf_an_mitarbeiter().
    """
    jetzt = b.now()
    ziel = fach(root, kennung, projekt, "auftrag")
    name = "%s_%s.md" % (jetzt.strftime("%Y-%m-%d_%H%M%S"),
                         re.sub(r"[^A-Za-z0-9]+", "_", str(titel))[:40].strip("_") or "auftrag")
    datei = ziel / name
    datei.write_text("\n".join([
        "---",
        "art:        mitarbeiterauftrag",
        "mitarbeiter: %s" % kennung,
        "projekt:    %s" % projekt,
        "titel:      %s" % titel,
        "erstellt:   %s" % jetzt.strftime("%Y-%m-%d %H:%M"),
        "von:        %s" % von,
        "faellig:    %s" % faellig,
        "zustand:    offen",
        "versendet:  nein",
        "---",
        "",
        str(text or ""),
        "",
    ]), encoding="utf-8")
    eintrag, _ = ablegen(root, kennung, {
        "projekt": projekt, "art": "auftrag", "richtung": "aus",
        "von": von, "an": stammdaten(root, kennung).get("rufname", kennung),
        "datum": jetzt.isoformat(), "kurztext": titel, "zustand": "offen",
        "pfad": str(datei), "quelle": "JACK"})
    protokoll(root, "auftrag_angelegt", mitarbeiter=kennung, projekt=projekt,
              titel=_sauber(titel, 120), datei=name)
    return eintrag


_STD_MUSTER = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:h\b|hrs?\b|hours?\b|std\b|stunden\b)", re.I)
_WOCHE_MUSTER = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:working\s+)?(?:hours?|hrs?|h)\b[^.\n]{0,40}\b(?:this|for the|per)\s+week|week(?:ly)?\D{0,30}(\d+(?:[.,]\d+)?)\s*(?:hours?|hrs?|h)\b", re.I)


def _bericht_text(root, kennung, e):
    """Klartext des Berichts (Mail-Datei aus der Akte, HTML entfernt); leer, wenn nicht lesbar."""
    pfad = str(e.get("pfad") or "")
    if not pfad:
        return ""
    try:
        import email, html
        from email import policy
        with open(ordner(root, kennung) / pfad, "rb") as f:
            m = email.message_from_binary_file(f, policy=policy.default)
        b_ = m.get_body(preferencelist=("plain", "html"))
        t = b_.get_content() if b_ else ""
    except Exception:
        return ""
    t = re.sub(r"<br\s*/?>|</div>|</p>|</li>|</tr>", "\n", t)
    return html.unescape(re.sub(r"<[^>]+>", "", t)).replace("\xa0", " ")


def stunden_aus_bericht(betreff, text):
    """(stunden_tag, stunden_woche): was der Bericht AUSDRUECKLICH nennt. Tagesangabe ("6 hours", "08 hours", "Approx 12 Hours") steht im Betreff
    oder im Text; eine Wochenangabe ("40 working hours for this week") wird getrennt gefuehrt und NIE als Tagesstunden gezaehlt. Nichts genannt = None."""
    t = (str(betreff or "") + "\n" + str(text or "")).replace("\xa0", " ")
    woche = None
    m = _WOCHE_MUSTER.search(t)
    if m:
        woche = float((m.group(1) or m.group(2)).replace(",", "."))
    ohne_woche = _WOCHE_MUSTER.sub(" ", t)
    tag = None
    if re.search(r"\d+\s*[-–]\s*\d+\s*(?:h|hrs?|hours?|std|stunden)\b", ohne_woche, re.I):
        return None, woche                                    # "5-6 hours": kein einzelner Wert genannt - nicht raten
    hm = re.search(r"\b(\d{1,2})\s*h\s*(\d{1,2})\s*(?:m|min)?\b|\b(\d{1,2}):(\d{2})\s*(?:h|hrs?|hours?|std|stunden)\b", ohne_woche, re.I)
    if hm and int(hm.group(2) or hm.group(4)) < 60:          # "5h30" / "5 h 30 min" / "5:30 hours" vor der einfachen Zahl-Stunden-Regel (sonst wuerde "5 h" = 5,0 gelten)
        tag = round(int(hm.group(1) or hm.group(3)) + int(hm.group(2) or hm.group(4)) / 60.0, 2)
    for zeile in ([] if tag is not None else ohne_woche.splitlines()):
        if re.search(r"working\s+since|since\s+around|Hours today|hours?\s+worked|worked\s+\d|^\s*[-*]?\s*\d+\s*(?:h|hours?)\b|Daily report", zeile, re.I) or zeile is ohne_woche.splitlines()[0]:
            m2 = _STD_MUSTER.search(zeile)
            if m2:
                tag = float(m2.group(1).replace(",", "."))
                break
    if tag is None:
        m3 = _STD_MUSTER.search(ohne_woche)
        if m3 and 0 < float(m3.group(1).replace(",", ".")) <= 16:
            tag = float(m3.group(1).replace(",", "."))
    if tag is None:
        tag = _stunden_weitere_formate(ohne_woche)
    if tag is not None and not (0 < tag <= 16):
        tag = None
    return tag, woche


_ZAHLWORT = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
             "eins": 1, "zwei": 2, "drei": 3, "vier": 4, "fuenf": 5, "fünf": 5, "sechs": 6, "sieben": 7, "acht": 8, "neun": 9, "zehn": 10, "elf": 11, "zwoelf": 12, "zwölf": 12}


def _stunden_weitere_formate(t):
    """F-103 (PM-Nacharbeit 30.09.2026): weitere AUSDRUECKLICHE Stundenformate - nie geschaetzt. Erkennt: "Hours: 6" / "Arbeitszeit = 7 Std." / Tabellenzeile "| Hours worked | 7.5 |",
    "5h30" / "5:30 hours" / "5 h 30 min", Zahlwort ("six hours", "sechs Stunden") und einen ausdruecklichen Zeitraum ("worked from 09:00 to 15:30", "09:00-15:30") in einer
    Arbeitszeile. Unklares (Bereiche wie "5-6 hours", Mehrdeutiges) bleibt None."""
    t = str(t or "")
    if re.search(r"\d+\s*[-–]\s*\d+\s*(?:h|hrs?|hours?|std|stunden)\b", t, re.I):
        return None                                       # "5-6 hours": kein einzelner Wert genannt - nicht raten
    m = re.search(r"(?:hours?(?:\s+worked)?|stunden|std\.?|arbeitszeit|time\s+spent|duration|dauer|total)\s*(?:[:=]|\|)\s*(\d+(?:[.,]\d+)?)\b", t, re.I)
    if m:
        return float(m.group(1).replace(",", "."))
    m = re.search(r"^\s*(?:std\.?|hours?|stunden)\s+(\d+(?:[.,]\d+)?)\s*$", t, re.I | re.M)       # Zeile "Std. 6"
    if m:
        return float(m.group(1).replace(",", "."))
    m = re.search(r"\b(" + "|".join(_ZAHLWORT) + r")\s+(?:full\s+)?(?:hours?|stunden)\b", t, re.I)
    if m:
        return float(_ZAHLWORT[m.group(1).lower()])
    for zeile in t.splitlines():
        if re.search(r"work|arbeit|gearbeitet|hours|stunden|time", zeile, re.I):
            r = re.search(r"\b(\d{1,2}):(\d{2})\s*(?:-|–|to|bis|until)\s*(\d{1,2}):(\d{2})\b", zeile, re.I)
            if r:
                a1, a2 = int(r.group(1)) * 60 + int(r.group(2)), int(r.group(3)) * 60 + int(r.group(4))
                if 0 < a2 - a1 <= 16 * 60:
                    return round((a2 - a1) / 60.0, 2)
    return None


def _berichtstag(e):
    """Kalendertag, auf den sich der Bericht bezieht: Datum im Betreff (2026-09-29 / September 22, 2026), sonst Versanddatum."""
    import datetime as dt
    betreff = str(e.get("kurztext") or "")
    m = re.search(r"(20\d\d-\d\d-\d\d)", betreff)
    if m:
        return dt.date.fromisoformat(m.group(1))
    m = re.search(r"([A-Z][a-z]+)\s+(\d{1,2}),\s*(20\d\d)", betreff)
    if m:
        try:
            return dt.datetime.strptime("%s %s %s" % m.groups(), "%B %d %Y").date()
        except ValueError:
            pass
    return dt.datetime.fromisoformat(str(e["datum"])[:19]).date()


def stunden_je_woche(root, kennung, wochen=8):
    """Zaehlt die gemeldeten Arbeitsstunden je Kalenderwoche aus den Berichten (Betreff UND Text der Mail).

    Gezaehlt wird nur, was ein Bericht ausdruecklich als Stunden nennt. Nie geschaetzt. Mehrere Mails zum selben Berichtstag zaehlen einmal.
    Je Woche: stunden (Summe der Tagesangaben), berichte (Berichtstage), mit_stunden (Berichtstage mit Angabe), stunden_wochenangabe
    (z. B. "40 working hours this week", getrennt, nicht in der Summe). Soll sind 40 Stunden."""
    raus, tage = {}, {}
    for e in index(root, kennung, art="bericht"):
        von = str(e.get("von") or "").lower()
        if "jack" in von or "office@" in von:
            continue                                        # unsere eigene Mail ist kein Bericht von ihm
        try:
            tag = _berichtstag(e)
        except Exception:
            continue
        h, wo = stunden_aus_bericht(e.get("kurztext"), _bericht_text(root, kennung, e))
        d = tage.setdefault(tag, {"h": None, "wo": None})
        if h is not None:
            d["h"] = h if d["h"] is None else max(d["h"], h)
        if wo is not None:
            d["wo"] = wo
    for tag, d in tage.items():
        jahr, kw, _ = tag.isocalendar()
        k = "%d-KW%02d" % (jahr, kw)
        w = raus.setdefault(k, {"woche": k, "stunden": 0.0, "berichte": 0, "mit_stunden": 0, "stunden_wochenangabe": None, "soll": 40})
        w["berichte"] += 1
        if d["h"] is not None:
            w["stunden"] += d["h"]
            w["mit_stunden"] += 1
        if d["wo"] is not None:
            w["stunden_wochenangabe"] = d["wo"]
    return sorted(raus.values(), key=lambda x: x["woche"], reverse=True)[:wochen]


# ──────────────── Nachtrag 2: die fuenf Schritte vor dem Workflow ──────────
# Der Weg mit einem neuen Mitarbeiter ist festgelegt und sichtbar. Er steht in
# betrieb/mitarbeiter_schritte.json und im Reiter UEBERSICHT seiner Akte.
SCHRITTE_DATEI = "mitarbeiter_schritte.json"
SCHRITTE = [
 (1, "CI-Mail", "Signatur und CI-Leitfaden im Anhang; erste Aufgabe: Standbericht."),
 (2, "Berichtsprüfung", "Standbericht eingegangen, geprüft und bewertet."),
 (3, "Kennenlern- und Skill-Mail", "Was er kann, was er gern macht, was er lernen will."),
 (4, "Skill-Profil vervollständigen", "Antworten auswerten, gezielt nachfragen."),
 (5, "Einteilung und Einsatzvorschlag", "Einsatzkarte, drei Optionen, Wochenplan."),
]
ZUSTAENDE = ("offen", "vorgelegt", "gesendet", "erledigt")


def schritte(root, kennung):
    """Der Stand der fuenf Schritte. Fehlt etwas, gilt 'offen' - nie geraten."""
    stand = _lesen(_area(root) / SCHRITTE_DATEI, {}).get(str(kennung), {})
    raus = []
    for nummer, titel, was in SCHRITTE:
        e = stand.get(str(nummer), {})
        raus.append({"nummer": nummer, "titel": titel, "was": was,
                     "zustand": e.get("zustand", "offen"),
                     "seit": e.get("seit", ""), "beleg": e.get("beleg", "")})
    return raus


def schritt_setzen(root, kennung, nummer, zustand, beleg=""):
    if str(zustand) not in ZUSTAENDE:
        raise ValueError("Unbekannter Zustand: %s" % zustand)
    if int(nummer) not in [s[0] for s in SCHRITTE]:
        raise ValueError("Diesen Schritt gibt es nicht: %s" % nummer)
    p = _area(root) / SCHRITTE_DATEI
    daten = _lesen(p, {})
    daten.setdefault(str(kennung), {})[str(int(nummer))] = {
        "zustand": str(zustand), "seit": b.now().isoformat(), "beleg": str(beleg)[:200]}
    _schreiben(p, daten)
    protokoll(root, "schritt", mitarbeiter=kennung, schritt=int(nummer),
              zustand=zustand, beleg=str(beleg)[:120])
    return schritte(root, kennung)


def naechster_schritt(root, kennung):
    """Der erste Schritt, der noch nicht erledigt ist."""
    for s in schritte(root, kennung):
        if s["zustand"] != "erledigt":
            return s
    return None


# ──────────────── Nachtrag 7: wie gut ist JACK? Nur fuer den Patron ────────
# Gemessen wird an dem, was der Patron tatsaechlich tut - nicht an einer
# Selbsteinschaetzung. Die Messung ist INTERN: sie geht nie an den Mitarbeiter.
MESSUNG = "mitarbeiter_messung.jsonl"
TESTPHASE_TAGE = 14


def messung_merken(root, kennung, art, **felder):
    try:
        e = {"zeit": b.now().isoformat(), "mitarbeiter": str(kennung), "art": str(art)}
        e.update({k: v for k, v in felder.items() if v is not None})
        b.append(_area(root) / MESSUNG, e)
    except Exception:
        pass


def _aehnlichkeit(alt, neu):
    """Wie stark hat der Patron den Entwurf geaendert? 0 = gar nicht, 1 = ganz."""
    import difflib
    a, n = str(alt or ""), str(neu or "")
    if not a and not n:
        return 0.0
    return round(1.0 - difflib.SequenceMatcher(None, a, n).ratio(), 3)


def messung_bewerten(root, kennung, vorlage, note, von="Patron"):
    """Der Patron vergibt 1-5 fuer einen Entwurf. Ein Klick, kein Formular."""
    note = int(note)
    if not 1 <= note <= 5:
        raise ValueError("Die Note geht von 1 bis 5.")
    messung_merken(root, kennung, "bewertung", vorlage=str(vorlage)[:120],
                   note=note, wer=von)
    return {"ok": True, "note": note,
            "meldung": "Notiert: %d von 5." % note}


def messung(root, kennung):
    """Was die Messung hergibt. Zahlen, keine Deutung."""
    import datetime as dt
    zeilen = [z for z in b.records(_area(root) / MESSUNG)
              if str(z.get("mitarbeiter")) == str(kennung)]
    entwuerfe = [z for z in zeilen if z.get("art") == "entwurf_vorgelegt"]
    gesendet = [z for z in zeilen if z.get("art") == "gesendet"]
    noten = [int(z["note"]) for z in zeilen if z.get("art") == "bewertung"]
    fragen = [z for z in zeilen if z.get("art") == "direkte_frage"]
    antworten = [z for z in zeilen if z.get("art") == "antwort_eingegangen"]
    rueckfragen = [z for z in antworten if z.get("rueckfrage")]
    aenderung = [float(z["aenderung"]) for z in gesendet if z.get("aenderung") is not None]
    stunden = [float(z["antwortzeit_h"]) for z in antworten
               if z.get("antwortzeit_h") is not None]
    beginn = zeilen[0]["zeit"][:19] if zeilen else ""
    tage = None
    if beginn:
        try:
            tage = (b.now().date() - dt.datetime.fromisoformat(beginn).date()).days
        except Exception:
            tage = None
    # Der zuletzt vorgelegte Entwurf - daran haengen die Bewertungsknoepfe.
    # Fehlt er, zeigt die Maske keine Knoepfe, statt ins Leere zu bewerten.
    letzte = (gesendet or entwuerfe)
    bewertet = {str(z.get("vorlage")) for z in zeilen if z.get("art") == "bewertung"}
    offene = [z for z in reversed(entwuerfe) if str(z.get("vorlage")) not in bewertet]
    return {
        "mitarbeiter": kennung,
        "vorlage": (offene[0]["vorlage"] if offene
                    else (letzte[-1].get("vorlage") if letzte else "")),
        "vorlage_bewertet": bool(not offene and letzte),
        "beginn": beginn,
        "tage_laufend": tage,
        "mails_vorgelegt": len(entwuerfe),
        "mails_gesendet": len(gesendet),
        "aenderung_durchschnitt": round(sum(aenderung) / len(aenderung), 3) if aenderung else None,
        "aenderung_je_mail": aenderung,
        "antwortzeit_h_median": round(sorted(stunden)[len(stunden) // 2], 1) if stunden else None,
        "rueckfragen": len(rueckfragen),
        "direkte_fragen": len(fragen),
        "noten": noten,
        "note_durchschnitt": round(sum(noten) / len(noten), 2) if noten else None,
        "testphase_tage": TESTPHASE_TAGE,
        "testphase_beendet": bool(tage is not None and tage >= TESTPHASE_TAGE),
        "quelle": "betrieb/" + MESSUNG,
        "hinweis": "Nur für den Patron. Geht nie an den Mitarbeiter.",
    }


# ---------------------------------------------------------------- Waechter
def wache(root):
    """Was der Patron wissen muss. Gibt Saetze zurueck, handelt nie selbst."""
    import datetime as dt
    raus = []
    heute = b.now().date()
    for e in register(root)["mitarbeiter"]:
        kennung = e.get("id")
        if str(e.get("status", "aktiv")) != "aktiv":
            continue
        try:
            stamm = stammdaten(root, kennung)
        except Exception:
            continue
        name = stamm.get("rufname") or kennung

        # 1. Laenger als einen Arbeitstag ohne offene Aufgabe?
        offen = auftraege(root, kennung, offen_nur=True)
        if not offen:
            letzte = auftraege(root, kennung)
            seit = None
            if letzte:
                try:
                    seit = dt.datetime.fromisoformat(str(letzte[0]["datum"])[:19]).date()
                except Exception:
                    seit = None
            elif stamm.get("start"):
                try:
                    seit = dt.date.fromisoformat(str(stamm["start"]))
                except Exception:
                    seit = None
            tage = (heute - seit).days if seit else None
            if tage is None or tage >= 1:
                raus.append({"art": "ohne_aufgabe", "mitarbeiter": kennung,
                             "dringend": True,
                             "satz": "%s hat keine offene Aufgabe%s." % (
                                 name, " — seit %d Tagen" % tage if tage else "")})

        # 2. Zahltag: drei Tage vor dem Monatsletzten erinnern. JACK zahlt nie.
        naechste = (stamm.get("verguetung") or {}).get("naechste_zahlung", "")
        m = re.match(r"(\d{4}-\d{2}-\d{2})", str(naechste))
        if m:
            try:
                tag = dt.date.fromisoformat(m.group(1))
                offen_tage = (tag - heute).days
                if 0 <= offen_tage <= 3:
                    raus.append({"art": "zahltag", "mitarbeiter": kennung,
                                 "dringend": offen_tage <= 1,
                                 "satz": "Zahltag für %s am %s (in %d Tagen). "
                                         "JACK zahlt nicht — das macht der Patron."
                                         % (name, tag.strftime("%d.%m.%Y"), offen_tage)})
                elif offen_tage < 0:
                    raus.append({"art": "zahltag", "mitarbeiter": kennung,
                                 "dringend": True,
                                 "satz": "Zahltag für %s war am %s und ist nicht "
                                         "vermerkt." % (name, tag.strftime("%d.%m.%Y"))})
            except Exception:
                pass

        # 3. Nachtrag 7: Nach 14 Tagen erinnert JACK an die Offenlegung.
        #    Das ist eine Erinnerung an den Patron, keine Handlung.
        m = messung(root, kennung)
        if m.get("testphase_beendet"):
            raus.append({"art": "testphase", "mitarbeiter": kennung, "dringend": False,
                         "satz": "Testphase beendet (%s Tage) — Offenlegung gegenüber "
                                 "%s besprechen. Das ist eine Erinnerung; JACK tut "
                                 "von sich aus nichts." % (m.get("tage_laufend"), name)})

        # 4. Arbeitsvertrag offen?
        vertrag = str((stamm.get("vertrag") or {}).get("status", ""))
        if vertrag and not vertrag.lower().startswith(("unterschrieben", "geschlossen")):
            raus.append({"art": "vertrag", "mitarbeiter": kennung, "dringend": False,
                         "satz": "Arbeitsvertrag mit %s ist offen." % name})
    return raus


# ──────────────── Nachtrag 1a: keine fremden Spuren in Dokumenten ──────────
# Ein PDF, das an einen Mitarbeiter geht, traegt den Namen des Hauses - nicht
# den des Werkzeugs, mit dem es gebaut wurde. Ersetzt wird laengengleich
# (mit Leerzeichen aufgefuellt), damit die Byte-Positionen der PDF-Tabelle
# stimmen bleiben. Ein laengerer Ersatz wuerde die Datei zerstoeren.
PDF_HAUS = "GOTT WALD HOLDING"


def pdf_metadaten_saeubern(pfad, titel=None):
    """Producer, Creator, Author und Title eines PDF neutralisieren.

    Gibt zurueck, was ersetzt wurde. Passt der Ersatz nicht in die vorhandene
    Laenge, wird das Feld GEKUERZT statt die Datei zu beschaedigen.
    """
    p = Path(pfad)
    roh = p.read_bytes()
    ersetzt = {}
    felder = {b"Producer": PDF_HAUS, b"Creator": PDF_HAUS,
              b"Author": PDF_HAUS, b"Title": str(titel or PDF_HAUS)}
    for feld, wert in felder.items():
        muster = re.compile(rb"/" + feld + rb"\s*\((?:\\.|[^()\\])*\)")
        treffer = muster.search(roh)
        if not treffer:
            continue
        ganz = treffer.group(0)
        innen_laenge = len(ganz) - len(b"/" + feld) - 3   # ohne " (" und ")"
        # Der erste Ersatz, der in die vorhandene Laenge passt. Lieber ein
        # kurzer richtiger Name als ein abgeschnittener.
        for kandidat in (wert, PDF_HAUS, "GOTT WALD", "GW"):
            roh_wert = kandidat.encode("latin-1", "replace")
            if len(roh_wert) <= innen_laenge:
                break
        neu_wert = roh_wert[:max(0, innen_laenge)]
        neu_wert = neu_wert + b" " * (innen_laenge - len(neu_wert))
        neu_ganz = b"/" + feld + b" (" + neu_wert + b")"
        if len(neu_ganz) != len(ganz):
            # Laenge passt nicht - dann lieber gar nichts anfassen.
            continue
        roh = roh.replace(ganz, neu_ganz, 1)
        ersetzt[feld.decode()] = neu_wert.decode("latin-1").strip()
    if ersetzt:
        atomic_bytes(p, roh)
    return ersetzt


# ── Der harte Riegel: SELBSTBEZUG ────────────────────────────────────────
# Nichts davon darf in einer Mitarbeiter-Mail oder ihren Anhaengen stehen.
# Das ist die Regel, die der Nachtrag schuetzen will: JACK soll sich nicht als
# Maschine zu erkennen geben und keine Werkzeugspur hinterlassen.
SELBSTBEZUG = [
 (r"Claude", re.I), (r"Anthropic", re.I), (r"OpenAI", re.I), (r"\bGPT\b", re.I),
 (r"\bgenerated by\b", re.I), (r"\bauto-?generated\b", re.I),
 (r"\bas an? (AI|A\.I\.|language model|assistant)\b", re.I),
 (r"\bI am an? (AI|A\.I\.|language model|bot|machine)\b", re.I),
 (r"\bich bin (eine )?(KI|AI|Maschine|Sprachmodell)\b", re.I),
 (r"language model", re.I), (r"Sprachmodell", re.I),
 (r"AI assistance", re.I), (r"KI-Assistenz", re.I),
 (r"artificial intelligence", re.I), (r"künstliche Intelligenz", re.I),
]

# ── Der weiche Hinweis: die blossen Woerter "AI" und "KI" ────────────────
# Sie sind NICHT verboten. Der Patron hat in Punkt 3 des Nachtrags
# ausdruecklich nach den KI-Werkzeugen des Mitarbeiters gefragt - eine Frage
# nach SEINEN Werkzeugen sagt nichts ueber JACK. Gemeldet werden sie
# trotzdem, damit niemand sie versehentlich stehen laesst.
WEICHE_SPUREN = [(r"\bAI\b", 0), (r"\bKI\b", 0), (r"\bA\.I\.", re.I)]


def spuren_pruefen(text, weich=False):
    """Welche verbotenen Spuren in einem Text stehen. Leer = sauber.

    weich=True nimmt zusaetzlich die blossen Woerter "AI" und "KI" mit.
    """
    raus = []
    for muster, schalter in SELBSTBEZUG + (WEICHE_SPUREN if weich else []):
        for m in re.finditer(muster, str(text or ""), schalter):
            raus.append(m.group(0))
    return sorted(set(raus))


# ──────────────── Nachtrag 6: das Skill-Profil ─────────────────────────────
# Es lebt in den Stammdaten - dort, wo die Wahrheit ueber einen Mitarbeiter
# steht. Zwei Einschaetzungen je Faehigkeit: seine eigene und die von JACK.
# Sie duerfen auseinandergehen; das ist der Sinn.
# Je Bereich: deutscher Name (Oberflaeche), deutsche Erklaerung, und die
# ENGLISCHE Beschriftung fuer die Mail an den Mitarbeiter.
SKILLBEREICHE_VOLL = [
 ("UX-Research", "Nutzerforschung, Interviews, Tests",
  "UX research — user interviews, testing, findings"),
 ("UI / Visual Design", "Oberflächen, Typografie, Gestaltung",
  "UI and visual design — interfaces, typography, craft"),
 ("Design-Systeme", "Bausteine, Tokens, Dokumentation",
  "Design systems — components, tokens, documentation"),
 ("Prototyping / Figma", "Klickbare Prototypen, Werkzeugsicherheit",
  "Prototyping in Figma — how fluent are you really"),
 ("Frontend-Verständnis", "HTML, CSS, React — lesen und einschätzen",
  "Front-end literacy — reading HTML, CSS and React well enough to judge feasibility"),
 ("Produktmanagement", "Anforderungen, Priorisierung, Schnitt",
  "Product thinking — requirements, priorities, scope"),
 ("KI-Werkzeuge", "Womit er arbeitet, wie sicher",
  "Tooling that speeds you up — which tools you actually use and how confidently"),
 ("Content / Social", "Texte, Beiträge, Community",
  "Content and social — copy, posts, community"),
 ("Marketing / Vertrieb / Business Development", "Markt, Kunden, Abschluss",
  "Marketing, sales and business development"),
 ("Markt- und Netzwerkzugang Bangladesch / Südasien", "Wen er kennt, wo er hinkommt",
  "Market access and network in Bangladesh and South Asia — who you know, where you get in"),
 ("Sprachen", "Welche, wie gut", "Languages"),
 ("Projektsteuerung / Werkzeuge", "Wie er Arbeit ordnet",
  "How you organise work — planning, tracking, handover"),
]
SKILLBEREICHE = [(a, b_) for a, b_, _ in SKILLBEREICHE_VOLL]
SKILL_ENGLISCH = {a: e for a, _, e in SKILLBEREICHE_VOLL}


def skillprofil(root, kennung):
    """Was in den Stammdaten steht. Was fehlt, heisst 'unbekannt' - nie geraten."""
    stamm = stammdaten(root, kennung)
    haben = {str(s.get("bereich", "")).lower(): s for s in (stamm.get("skills") or [])}
    bereiche = []
    for name, was in SKILLBEREICHE:
        s = haben.get(name.lower(), {})
        bereiche.append({
            "bereich": name, "was": was,
            "faehigkeit": s.get("faehigkeit", ""),
            "selbsteinschaetzung": s.get("selbsteinschaetzung"),
            "jack_einschaetzung": s.get("jack_einschaetzung"),
            "beleg": s.get("beleg", ""),
            "quelle": s.get("quelle", ""),
            "datum": s.get("datum", ""),
            "bekannt": bool(s)})
    # Bereiche, die der Mitarbeiter selbst genannt hat und die hier fehlen.
    fuer_sich = [s for k, s in haben.items()
                 if k not in {n.lower() for n, _ in SKILLBEREICHE}]
    gefuellt = sum(1 for x in bereiche if x["bekannt"])
    return {"bereiche": bereiche, "zusaetzlich": fuer_sich,
            "gefuellt": gefuellt, "gesamt": len(bereiche),
            "vollstaendig": gefuellt == len(bereiche),
            "sprachen": stamm.get("sprachen") or [],
            "zeitzone": stamm.get("zeitzone", ""),
            "arbeitszeiten": stamm.get("arbeitszeiten_bevorzugt", ""),
            "lernziele": stamm.get("lernziele") or [],
            "vorlieben": stamm.get("vorlieben") or {},
            "quelle": "00_Stammdaten/stammdaten.json"}


def skill_setzen(root, kennung, bereich, **felder):
    """Eine Faehigkeit eintragen oder fortschreiben. Ueberschreibt nie blind."""
    stamm = stammdaten(root, kennung)
    liste = list(stamm.get("skills") or [])
    treffer = next((s for s in liste
                    if str(s.get("bereich", "")).lower() == str(bereich).lower()), None)
    if treffer is None:
        treffer = {"bereich": str(bereich)}
        liste.append(treffer)
    for schluessel in ("faehigkeit", "selbsteinschaetzung", "jack_einschaetzung",
                       "beleg", "quelle"):
        if felder.get(schluessel) is not None:
            treffer[schluessel] = felder[schluessel]
    treffer["datum"] = b.now().strftime("%Y-%m-%d")
    stamm["skills"] = liste
    stammdaten_schreiben(root, kennung, stamm)
    protokoll(root, "skill", mitarbeiter=kennung, bereich=str(bereich)[:80])
    return skillprofil(root, kennung)


# ---------------------------------------------------------------- Lage
def _foto(root, kennung, stamm):
    name = str(stamm.get("foto") or "")
    if not name:
        return ""
    p = ordner(root, kennung) / "00_Stammdaten" / name
    return "/mitarbeiter/foto?id=" + kennung if p.is_file() else ""


def akte(root, kennung):
    """Alles, was die Maske fuer EINEN Mitarbeiter braucht. Nie eine Nummer."""
    stamm = stammdaten(root, kennung)
    eintraege = index(root, kennung)
    je_projekt = {}
    for e in eintraege:
        je_projekt.setdefault(e["projekt"], []).append(e)
    offen = auftraege(root, kennung, offen_nur=True)
    hinweise = [h for h in wache(root) if h["mitarbeiter"] == kennung]
    kontakt = dict(stamm.get("kontakt") or {})
    telefon = str(kontakt.get("telefon", ""))
    return {
        "id": kennung,
        "rufname": stamm.get("rufname") or kennung,
        "name_laut_pass": stamm.get("name_laut_pass", ""),
        "rolle": stamm.get("rolle", ""),
        "status": stamm.get("status", ""),
        "start": stamm.get("start", ""),
        "arbeitszeit": stamm.get("arbeitszeit", ""),
        "foto": _foto(root, kennung, stamm),
        "vertrag": stamm.get("vertrag") or {},
        "naechste_zahlung": (stamm.get("verguetung") or {}).get("naechste_zahlung", ""),
        "verguetung_betrag": (stamm.get("verguetung") or {}).get("betrag", ""),
        "kontakt": {"email_arbeit": kontakt.get("email_arbeit", ""),
                    "telefon": telefon,
                    "whatsapp": re.sub(r"\D", "", str(kontakt.get("whatsapp", ""))),
                    "linkedin": kontakt.get("linkedin", "")},
        "projekte": [{"id": p, "anzahl": len(je_projekt.get(p, [])),
                      "eintraege": je_projekt.get(p, [])[:400]}
                     for p in projekte(root, kennung)],
        "korrespondenz": eintraege[:400],
        "auftraege": auftraege(root, kennung)[:200],
        "offene_auftraege": len(offen),
        "stunden": stunden_je_woche(root, kennung),
        "hinweise": hinweise,
        "schritte": schritte(root, kennung),
        "naechster_schritt": naechster_schritt(root, kennung),
        "skills": skillprofil(root, kennung),
        "messung": messung(root, kennung),
        "versandsperre": versandsperre(root),
        "handlung_wartet": bool(hinweise),
        "letzte_aktivitaet": eintraege[0]["datum"] if eintraege else "",
        "offen_laut_stammdaten": stamm.get("offen_am_2026-09-17") or [],
        "quelle": "08_Mitarbeiter/%s/00_Stammdaten/stammdaten.json + akte_index.jsonl"
                  % Path(_eintrag(root, kennung).get("ordner", "")).name,
    }


def lage(root):
    """Was der Mitarbeiter-Kasten zeigt. Nie eine Nummer, nie eine Wallet."""
    leute = []
    for e in sorted(register(root)["mitarbeiter"],
                    key=lambda x: (int(x.get("rang", 99)), str(x.get("id")))):
        kennung = e.get("id")
        try:
            stamm = stammdaten(root, kennung)
            eintraege = index(root, kennung, hoechstens=1)
        except Exception:
            continue
        hinweise = [h for h in wache(root) if h["mitarbeiter"] == kennung]
        leute.append({
            "id": kennung,
            "rufname": stamm.get("rufname") or kennung,
            "name_laut_pass": stamm.get("name_laut_pass", ""),
            "rolle": stamm.get("rolle", ""),
            "status": stamm.get("status", "unbekannt"),
            "ampel": {"aktiv": "gruen", "pausiert": "gelb"}.get(
                str(stamm.get("status", "")), "grau"),
            "foto": _foto(root, kennung, stamm),
            "rang": int(e.get("rang", 99)),
            "offene_auftraege": len(auftraege(root, kennung, offen_nur=True)),
            "letzte_aktivitaet": eintraege[0]["datum"] if eintraege else "",
            "handlung_wartet": bool(hinweise),
            "hinweise": [h["satz"] for h in hinweise],
        })
    warten = sum(1 for p in leute if p["handlung_wartet"])
    return {"zeit": b.now().isoformat(), "mitarbeiter": leute,
            "anzahl": len(leute), "handlung_wartet": warten,
            "kurz": "%d Mitarbeiter%s" % (
                len(leute), " · %d braucht dich" % warten if warten else ""),
            "quelle": "betrieb/mitarbeiter.json + 08_Mitarbeiter/*/00_Stammdaten/stammdaten.json"}


TAGESMELDUNG = "mitarbeiter_tagesmeldung.json"


def tick(root, at=None):
    """Haengt sich in die Fuenf-Minuten-Routine. Meldet nur, handelt nie.

    Befund 7 der unabhaengigen Pruefung (17.09.2026): Vorher filterte diese
    Stelle auf "dringend" - der Hinweis "Vertrag offen" und die Testphase-
    Erinnerung erreichten die Routine deshalb NIE. Jetzt gilt:

      * dringende Hinweise gehen in JEDEN Takt,
      * alle uebrigen EINMAL AM TAG.

    Alle fuenf Minuten "Vertrag offen" zu melden waere Laerm; gar nicht zu
    melden war ein Fehler.
    """
    try:
        import jack_mitarbeiter_zentrum as _z      # F-103 C: unbeantwortete Mail von ihm -> genau eine Freigabe-Karte (nichts wird gesendet)
        import jack_zusagen as _zu
        for e in register(root).get("mitarbeiter", []):
            if e.get("status", "aktiv") == "aktiv":
                _z.unbeantwortete_vorlegen(root, e.get("id"), at)
                _zu.erkennen(root, e.get("id"), at)            # F-103 v2 B/K: neue Mails/Berichte auf Zusagen und Rueckfragen lesen (Vorfilter, dann Modell)
                _zu.historische_bereinigen(root, e.get("id"), at)
                _zu.erledigt_pruefen(root, e.get("id"), at)
                import jack_mitarbeiter_zentrum as _zz
                _zz.hill_erfassen(root, e.get("id"))
    except Exception as fehler:
        protokoll(root, "antwortkarten_fehler", grund=str(fehler)[:120])
    try:
        hinweise = wache(root)
    except Exception:
        return []
    raus = [h["satz"] for h in hinweise if h.get("dringend")]
    ruhige = [h for h in hinweise if not h.get("dringend")]
    if not ruhige:
        return raus
    heute = (at or b.now()).strftime("%Y-%m-%d")
    p = _area(root) / TAGESMELDUNG
    stand = _lesen(p, {})
    gemeldet = set(stand.get(heute) or [])
    neu_heute = [h for h in ruhige
                 if "%s|%s" % (h["mitarbeiter"], h["art"]) not in gemeldet]
    if neu_heute:
        gemeldet |= {"%s|%s" % (h["mitarbeiter"], h["art"]) for h in neu_heute}
        # Nur der heutige Tag bleibt stehen - die Datei waechst nicht.
        _schreiben(p, {heute: sorted(gemeldet)})
        raus += [h["satz"] for h in neu_heute]
    return raus


# ──────────────── Teil F: Kommunikation NUR per E-Mail ─────────────────────
# DIN bekommt keinen Zugang zu JACK. Alles, was ihn erreicht, geht als Mail aus
# office@gottwald.world - und JEDE dieser Mails legt der Patron erst frei.
#
# Nachtrag vom 17.09.2026 (Entscheidung des Patrons):
#   * Absender ist office@gottwald.world, nicht mehr Patron@gottwald.world.
#     Patron@ bleibt den Mails vorbehalten, die der Patron selbst unterschreibt.
#   * Gezeichnet wird ausschliesslich mit "JACK · Office of the Patron"
#     (Signaturrolle jack_office) - nie mit dem Namen der Person, der das
#     Postfach sonst gehoert.
#   * KEINE automatische Korrespondenz mit Mitarbeitern. Nie. Unabhaengig
#     davon, welchen Freigabeweg das Absenderpostfach hat, gilt immer:
#     Entwurf -> FREIGEBEN durch den Patron -> Versand. Keine Lernstufen.
#   * Ist das Postfach nicht verbunden, wird NICHT gesendet - es wird gemeldet.
ABSENDER = "office@gottwald.world"
SIGNATURROLLE = "jack_office"
VERSANDSPERRE = "mitarbeiter_versandsperre.json"


def versandsperre_setzen(root, adresse, status, fehler=""):
    """Merkt, dass eine Mitarbeiter-Mail am nicht verbundenen Postfach haengt.
    jack_postfaecher.lage() zeigt den Satz im E-Mail-Kasten."""
    _schreiben(_area(root) / VERSANDSPERRE, {
        "zeit": b.now().isoformat(), "postfach": adresse, "status": status,
        "grund": str(fehler or "")[:200],
        "satz": ("%s ist nicht verbunden — Post an Mitarbeiter kann nicht hinaus. "
                 "Bitte das Postfach verbinden." % adresse)})
    protokoll(root, "versandsperre", postfach=adresse, status=status)


def versandsperre_loeschen(root):
    p = _area(root) / VERSANDSPERRE
    if p.is_file():
        p.unlink()


def versandsperre(root):
    """Was der E-Mail-Kasten dazu zeigt. Leer, wenn alles in Ordnung ist."""
    return _lesen(_area(root) / VERSANDSPERRE, {})


def ist_mitarbeiteradresse(root, adresse):
    """Gehoert diese Adresse einem Mitarbeiter? Dann nie automatisch antworten."""
    roh = str(adresse or "").lower()
    treffer = re.findall(r"[^\s@<>,;]+@[^\s@<>,;]+", roh)
    gesucht = set(treffer) | {roh.strip()}
    for e in register(root)["mitarbeiter"]:
        try:
            kontakt = stammdaten(root, e.get("id")).get("kontakt") or {}
        except Exception:
            continue
        for wert in kontakt.values():
            w = str(wert or "").lower().strip()
            if "@" in w and w in gesucht:
                return str(e.get("id"))
    return None


def _empfaenger(root, kennung):
    adresse = str((stammdaten(root, kennung).get("kontakt") or {}).get("email_arbeit", ""))
    if not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", adresse):
        raise ValueError("Für %s ist keine Arbeitsadresse hinterlegt." % kennung)
    return adresse


def _anhangpfade(root, kennung, anhaenge):
    """Anhaenge auf Pfade RELATIV ZUR HOLDING bringen und pruefen.

    Was nicht unter der Holding liegt, keine Datei ist oder ein Symlink ist,
    wird abgewiesen - hier, nicht erst beim Senden.
    """
    wurzel = holding(root)
    basis = ordner(root, kennung)
    raus = []
    for eintrag in (anhaenge or [])[:10]:
        q = Path(str(eintrag))
        for kandidat in ((q,) if q.is_absolute() else (basis / q, wurzel / q)):
            if kandidat.is_file() and not kandidat.is_symlink():
                q = kandidat
                break
        else:
            raise ValueError("Anhang gibt es nicht: %s" % str(eintrag)[:120])
        q = q.resolve()
        try:
            raus.append(str(q.relative_to(wurzel)))
        except ValueError:
            raise ValueError("Anhang liegt ausserhalb der Holding: %s" % str(eintrag)[:120])
    return raus


def entwurf_an_mitarbeiter(root, kennung, betreff, text, anhaenge=None,
                           projekt=None, auftrag_titel="", faellig="", von="JACK",
                           worum="", schritt=None):
    """Baut EINEN Mailentwurf an den Mitarbeiter und legt ihn dem Patron vor.

    Es wird NICHTS gesendet. Der Versand geschieht ausschliesslich, wenn der
    Patron im Freigaben-Kasten FREIGEBEN drueckt - dann fuehrt
    jack_oberflaeche._anwenden() die Art "mitarbeitermail" aus.
    """
    import jack_freigaben
    import jack_postfaecher
    root = Path(root)
    absender = jack_postfaecher._postfach(root, ABSENDER)
    # Der Freigabeweg des Absenders ist hier bewusst EGAL: Mail an einen
    # Mitarbeiter geht immer und ausnahmslos ueber den Freigaben-Kasten.
    # Geprueft wird nur zweierlei - senden duerfen und verbunden sein.
    if not jack_postfaecher.darf_senden(absender):
        raise ValueError("Aus %s darf JACK nicht senden (Freigabeweg '%s')."
                         % (ABSENDER, jack_postfaecher.freigabeweg(absender)))
    # Ist das Postfach nicht verbunden, wird trotzdem ENTWORFEN - ein Entwurf
    # schadet niemandem und der Patron soll ihn lesen koennen. Gesperrt ist der
    # VERSAND: jack_postfaecher.senden() weist ein nicht verbundenes Postfach ab,
    # und der Grund steht sichtbar im E-Mail-Kasten und auf der Karte.
    nicht_verbunden = ""
    if absender.get("status") != "verbunden":
        nicht_verbunden = str(absender.get("status", "unbekannt"))
        versandsperre_setzen(root, ABSENDER, nicht_verbunden,
                             absender.get("letzter_fehler", ""))
    else:
        versandsperre_loeschen(root)
    an = _empfaenger(root, kennung)
    betreff = re.sub(r"[\r\n]+", " ", str(betreff or "")).strip()[:180]
    if not betreff:
        raise ValueError("Ohne Betreff wird nichts entworfen.")
    pfade = _anhangpfade(root, kennung, anhaenge)
    projekt = str(projekt or ALLGEMEIN)
    if projekt not in projekte(root, kennung):
        projekt = UNZUGEORDNET

    entwurf = b.draft_path(root, "mitarbeiter_" + betreff, ".md")
    entwurf.write_text("\n".join([
        "---",
        "art:        mailentwurf",
        "postfach:   %s" % ABSENDER,
        "an:         %s" % an,
        "betreff:    %s" % betreff,
        "mailart:    Mitarbeiter",
        "weg:        %s" % jack_postfaecher.freigabeweg(absender),
        "signatur:   %s" % SIGNATURROLLE,
        "mitarbeiter: %s" % kennung,
        "projekt:    %s" % projekt,
        "anhaenge:   %s" % "|".join(pfade),
        "erstellt_von: %s" % von,
        "erstellt:   %s" % b.now().strftime("%Y-%m-%d %H:%M"),
        "zustand:    wartet_auf_patron",
        "---",
        "",
        str(text or ""),
        "",
    ]), encoding="utf-8")
    # Nachtrag 7: Die Urfassung wird daneben gelegt. Nur so laesst sich spaeter
    # messen, wie viel der Patron am Entwurf geaendert hat.
    entwurf.with_suffix(".urfassung").write_text(str(text or ""), encoding="utf-8")

    ziel = root / "auftraege" / "freigabe"
    ziel.mkdir(parents=True, exist_ok=True)
    jetzt = b.now()
    kurz = re.sub(r"[^a-zA-Z0-9]+", "_", betreff)[:40].strip("_") or "mail"
    name = "%s_MITARBEITER_%s.md" % (jetzt.strftime("%Y-%m-%d_%H%M%S"), kurz)
    zeilen = [
        "---",
        "marke:      GOTT_WALD",
        "auftrag:    Mail_an_%s" % kennung,
        # Block 28: Die Ueberschrift sagt, WELCHE Mail - nicht nur an wen.
        "titel:      Mail an %s · %s" % (
            stammdaten(root, kennung).get("rufname") or kennung, betreff),
        "zustand:    %s" % WARTET,
        "erteilt:    %s" % jetzt.strftime("%Y-%m-%d %H:%M"),
        "von:        JACK-Mitarbeiter",
        "status:     freigabe",
        "freigabe:   nein",
        "gefahr:     aussen",
        "tiefe:      klein",
        "besetzung:  1",
        "versuch:    0",
        "warte_bis:  ",
        "bereiche:   mitarbeiter",
        "art:        mitarbeitermail",
        "mitarbeiter: %s" % kennung,
        "projekt:    %s" % projekt,
        "entwurf:    %s" % entwurf.name,
        "auftrag_titel: %s" % str(auftrag_titel or ""),
        "faellig:    %s" % str(faellig or ""),
        "schritt:    %s" % (str(int(schritt)) if schritt else ""),
        "---",
        "",
        "## Worum es geht",
        str(worum or "E-Mail an %s (%s)." % (
            stammdaten(root, kennung).get("rufname", kennung), an)),
        "",
        "| Feld | Wert |",
        "|---|---|",
        "| Von | %s |" % ABSENDER,
        "| An | %s |" % an,
        "| Betreff | %s |" % betreff,
        "| Projekt | %s |" % projekt,
        "| Anhänge | %s |" % (", ".join(Path(x).name for x in pfade) or "keine"),
    ]
    if auftrag_titel:
        zeilen.append("| Arbeitsauftrag | %s |" % auftrag_titel)
        zeilen.append("| Fällig | %s |" % (faellig or "offen"))
    if nicht_verbunden:
        zeilen += ["",
                   "## 🔴 Versand gesperrt",
                   "`%s` ist **nicht verbunden** (Zustand: %s). FREIGEBEN wird diese"
                   % (ABSENDER, nicht_verbunden),
                   "Mail **nicht** senden können. Bitte das Postfach zuerst im",
                   "E-Mail-Kasten verbinden — dann genügt ein zweites FREIGEBEN.",
                   "Der Entwurf bleibt bis dahin hier liegen."]
    zeilen += [
        "",
        "## Text der Mail",
        "```",
        str(text or "")[:6000],
        "```",
        "",
        "## Prüfpunkte",
        "FREIGEBEN sendet diese Mail aus %s und legt sie danach mit allen" % ABSENDER,
        "Anhängen in die Akte. ABLEHNEN verwirft sie; es geht nichts hinaus.",
        "",
    ]
    (ziel / name).write_text("\n".join(zeilen), encoding="utf-8")
    try:
        jack_freigaben.anfordern(root, name, grund="Mail an Mitarbeiter " + kennung)
    except Exception:
        pass
    if schritt:
        schritt_setzen(root, kennung, int(schritt), "vorgelegt", beleg=name)
    protokoll(root, "entwurf_vorgelegt", mitarbeiter=kennung, projekt=projekt,
              betreff=_sauber(betreff, 120), anhaenge=len(pfade), vorlage=name)
    messung_merken(root, kennung, "entwurf_vorgelegt", vorlage=name,
                   betreff=_sauber(betreff, 120), zeichen=len(str(text or "")),
                   anhaenge=len(pfade))
    return {"ok": True, "vorlage": name, "entwurf": entwurf.name,
            "an": an, "betreff": betreff, "anhaenge": pfade,
            "versand_gesperrt": nicht_verbunden,
            "meldung": ("Der Entwurf liegt im Freigaben-Kasten. Gesendet wird erst "
                        "nach FREIGEBEN." if not nicht_verbunden else
                        "Der Entwurf liegt im Freigaben-Kasten. ACHTUNG: %s ist nicht "
                        "verbunden — gesendet werden kann er erst danach." % ABSENDER)}


def direkte_frage_vorlegen(root, kennung, fundstelle, quelle_eintrag=None):
    """Legt die Antwort auf eine direkte Frage als EIGENE Karte vor.

    Der Text ist fest (DIREKTE_ANTWORT) und wahrheitsgemaess. Er wird nicht von
    einem Modell geschrieben und enthaelt nie eine Verneinung. Ohne FREIGEBEN
    geht nichts hinaus.
    """
    vorlage = entwurf_an_mitarbeiter(
        root, kennung, "Your question — a straight answer", DIREKTE_ANTWORT,
        projekt=ALLGEMEIN, von="JACK",
        worum=("**Direkte Frage.** %s hat geradeheraus gefragt, ob er mit einer "
               "Maschine schreibt. Fundstelle: „%s“. Der Antworttext steht fest im "
               "Code und ist wahrheitsgemäß — JACK entwirft hier niemals eine "
               "Verneinung. Ohne FREIGEBEN geht nichts hinaus."
               % (stammdaten(root, kennung).get("rufname", kennung), fundstelle)))
    # Die Karte bekommt ihre eigene Kennzeichnung, damit sie im Freigaben-Kasten
    # als das erscheint, was sie ist.
    datei = Path(root) / "auftraege" / "freigabe" / vorlage["vorlage"]
    text = datei.read_text(encoding="utf-8")
    text = text.replace("art:        mitarbeitermail",
                        "art:        mitarbeitermail\nvorgang:    direkte_frage\n"
                        "karte:      Direkte Frage", 1)
    text = text.replace("auftrag:    Mail_an_%s" % kennung,
                        "auftrag:    Direkte_Frage_%s" % kennung, 1)
    datei.write_text(text, encoding="utf-8")
    protokoll(root, "direkte_frage", mitarbeiter=kennung,
              fundstelle=_sauber(fundstelle, 160), vorlage=vorlage["vorlage"])
    messung_merken(root, kennung, "direkte_frage", vorlage=vorlage["vorlage"],
                   fundstelle=_sauber(fundstelle, 160))
    return vorlage


# ══════════════════════════════════════════════════════════════════════════
# Block 22 (17.09.2026): Die Freigabekette fuer Mitarbeiter-Mails.
#
# Anordnung des Patrons: An einen Mitarbeiter darf NIE eine Mail hinausgehen,
# bevor genau diese Mail als Testversand beim Patron war und der Patron danach
# freigegeben hat. Die Sperre steht HIER im Server, nicht in der Maske - eine
# Maske kann man umgehen, diesen Weg nicht.
#
# Anlass: Am 17.09.2026 um 19:10:59 ging eine Mail an Dween.Mohammad hinaus,
# ohne dass je ein Testversand stattgefunden hatte. Beleg: betrieb/
# oberflaeche.jsonl - "freigabe_entscheidung", entscheidung "freigegeben".
# Der Testversand-Weg war gar nicht beteiligt; es war der Freigabeknopf, der
# direkt neben ihm steht. Ab jetzt ist dieser Knopf ohne Testversand taub.
VERMERKE = "testversand_vermerke.json"     # betrieb/testversand_vermerke.json


def entwurfspruefsumme(pfad):
    """Pruefsumme ueber das, was wirklich hinausgeht.

    Ohne die Kopfzeile "zustand:" - die schreibt der Versand selbst fort
    ("unsicher", "gesendet"), sie sagt nichts ueber den Inhalt. Alles andere
    zaehlt: Empfaenger, Betreff, Signaturrolle, Anhaenge und der Text.
    """
    pfad = Path(pfad)
    try:
        text = pfad.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    zeilen = [z for z in text.splitlines()
              if not re.match(r"^zustand:", z.strip(), re.I)]
    return hashlib.sha256("\n".join(zeilen).encode("utf-8")).hexdigest()


def _vermerke(root):
    return _lesen(b.area(root) / VERMERKE, {})


# Block 28 (18.09.2026): Eine wartende Mitarbeiter-Karte gehoert dem Patron.
# Kein Aufraeumlauf und keine Regel darf sie raeumen, verschieben oder fuer
# gegenstandslos erklaeren. Nur FREIGEBEN oder ABLEHNEN beendet sie.
WARTET = "wartet_auf_patron"
# F-53 (25.09.2026): Die Testversand-Kette gilt fuer jede Karte, an der ein Mailentwurf haengt (Mitarbeiter, Extern/Anfrage).
MAILKARTEN = ("mitarbeitermail", "externemail", "mailantwort")  # F-82 (29.09.2026): mailantwort dazu -
# genau das fehlte, damit der TESTVERSAND-Knopf bei einer Mailantwort-Karte ueberhaupt lief.


def _kopfzeilen(pfad, grenze=60):
    kopf = {}
    try:
        zeilen = Path(pfad).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return kopf
    if not zeilen or zeilen[0].strip() != "---":
        return kopf
    for zeile in zeilen[1:grenze]:
        if zeile.strip() == "---":
            break
        k, _, w = zeile.partition(":")
        kopf[k.strip().lower()] = w.strip()
    return kopf


def karte_geschuetzt(root, pfad):
    """True, wenn die Karte eine Mitarbeiter-Mail ist, die auf den Patron wartet.

    Im Zweifel geschuetzt: fehlt der Entwurf oder ist er unlesbar, bleibt die
    Karte liegen. Frei wird sie erst, wenn der Entwurf "gesendet" ist.
    """
    kopf = _kopfzeilen(pfad)
    if kopf.get("art") not in MAILKARTEN:
        return False
    entwurf = kopf.get("entwurf", "")
    if not entwurf:
        return True
    zustand = _kopfzeilen(b.area(root) / "entwuerfe" / entwurf).get("zustand", "")
    return zustand != "gesendet"


# ══════════════════════════════════════════════════════════════════════════
# Block 27 (18.09.2026): Die Freigabe braucht einen Beweis, keinen Funktionsaufruf.
#
# Am 18.09.2026 um 07:03:51 ging eine Mail an DIN hinaus, die der Patron nicht
# freigegeben hatte. Ein Abnahmeskript hatte freigabe_vermerken(von="Patron")
# selbst aufgerufen - 1 ms nach dem Testversand. Jeder Aufrufer konnte sich so
# "Patron" nennen. Ab jetzt steht in der [TEST]-Mail an den Patron ein
# Freigabecode. Nur mit diesem Code entsteht eine Freigabe. Hier liegt nur sein
# Hash - der Code selbst steht nirgends auf der Platte und in keiner Antwort.
CODE_ZEICHEN = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_VERSUCHE = 5
BESTAETIGUNG = "freigabecode_aus_testmail"


def _code_normal(code):
    return re.sub(r"[^A-Z0-9]", "", str(code or "").upper())


def _code_hash(salz, code):
    return hashlib.sha256((str(salz) + _code_normal(code)).encode("utf-8")).hexdigest()


def _entwurf_an(root, entwurf):
    pfad = b.area(root) / "entwuerfe" / str(entwurf)
    try:
        for zeile in pfad.read_text(encoding="utf-8").splitlines()[1:40]:
            if zeile.strip() == "---":
                break
            k, _, w = zeile.partition(":")
            if k.strip().lower() == "an":
                return w.strip()
    except OSError:
        pass
    return ""


def testversand_vermerken(root, vorlage, entwurf, message_id="", code=""):
    """Haelt fest: DIESER Entwurf war in DIESER Fassung beim Patron."""
    daten = _vermerke(root)
    salz = secrets.token_hex(16)
    daten[str(vorlage)] = {
        "vorlage": str(vorlage), "entwurf": str(entwurf),
        "pruefsumme": entwurfspruefsumme(b.area(root) / "entwuerfe" / str(entwurf)),
        "empfaenger": _entwurf_an(root, entwurf),
        "zeit": b.now().isoformat(), "message_id": str(message_id)[:200],
        "an": "Gottwald.mathias@icloud.com",
        "code_salz": salz, "code_hash": _code_hash(salz, code) if code else "",
        "code_versuche": 0}
    _schreiben(b.area(root) / VERMERKE, daten)
    return {k: v for k, v in daten[str(vorlage)].items()
            if k not in ("code_salz", "code_hash")}


def testversand_gueltig(root, vorlage, entwurf=None):
    """Darf diese Karte jetzt an den Mitarbeiter hinaus? (bool, Satz)

    Drei Bedingungen, alle drei muessen stimmen:
      1. Es gibt ueberhaupt einen Testversand zu dieser Karte.
      2. Er galt demselben Entwurf.
      3. Der Entwurf ist seither unveraendert.
    Fehlt eines, bleibt der Weg gesperrt.
    """
    satz_fehlt = ("Erst Testversand an den Patron, dann Freigabe.")
    e = _vermerke(root).get(str(vorlage))
    if not e:
        return False, satz_fehlt
    if entwurf and str(e.get("entwurf", "")) != str(entwurf):
        return False, (satz_fehlt + " Der Testversand galt einem anderen Entwurf "
                       "(%s)." % str(e.get("entwurf", ""))[:120])
    pfad = b.area(root) / "entwuerfe" / str(e.get("entwurf", ""))
    if not pfad.is_file():
        return False, satz_fehlt + " Den getesteten Entwurf gibt es nicht mehr."
    jetzt = entwurfspruefsumme(pfad)
    if not jetzt or jetzt != e.get("pruefsumme"):
        return False, ("Der Entwurf hat sich seit dem Testversand geaendert - der "
                       "Testversand ist verfallen. Erst Testversand an den Patron, "
                       "dann Freigabe.")
    if not e.get("code_hash"):
        return False, ("Dieser Testversand trug noch keinen Freigabecode (vor Block 27). "
                       "Bitte einen neuen Testversand ausloesen.")
    if str(e.get("empfaenger", "")).lower() != _entwurf_an(root, e.get("entwurf", "")).lower():
        return False, ("Der Empfaenger hat sich seit dem Testversand geaendert. "
                       + satz_fehlt)
    if int(e.get("code_versuche") or 0) >= CODE_VERSUCHE:
        return False, ("Der Freigabecode wurde %d-mal falsch eingegeben und ist gesperrt. "
                       "Bitte einen neuen Testversand ausloesen." % CODE_VERSUCHE)
    return True, ("Testversand vom %s liegt vor, der Entwurf ist unveraendert. "
                  "Zum Freigeben den Freigabecode aus der [TEST]-Mail eintragen."
                  % str(e.get("zeit", ""))[:16].replace("T", " "))


def freigabe_vermerken(root, vorlage, entwurf, code=None, kennung="",
                       ausloeser="", von=None):
    """Die Freigabe des Patrons - nur mit dem Freigabecode aus der [TEST]-Mail.

    Gibt immer ein dict zurueck: {"ok": bool, "grund": Satz, ...}. Wer den Code
    nicht hat, bekommt keine Freigabe, egal wie er sich nennt ("von" wird nur
    als Ausloeser protokolliert, nie als Freigebender uebernommen).
    """
    ausloeser = str(ausloeser or von or "unbekannt")[:80]
    daten = _vermerke(root)
    e = daten.get(str(vorlage))

    def abweisen(grund):
        protokoll(root, "freigabe_abgewiesen", vorlage=str(vorlage)[:160],
                  entwurf=str(entwurf)[:160], ausloeser=ausloeser, grund=grund[:200])
        return {"ok": False, "grund": grund}

    if not e or str(e.get("entwurf", "")) != str(entwurf):
        return abweisen("Erst Testversand an den Patron, dann Freigabe.")
    ok, grund = testversand_gueltig(root, vorlage, entwurf)
    if not ok:
        return abweisen(grund)
    if (e.get("freigabe") or {}).get("verbraucht"):
        return abweisen("Diese Freigabe ist bereits verbraucht - der Entwurf ist gesendet.")
    if not _code_normal(code):
        return abweisen("Ohne Freigabecode aus der [TEST]-Mail gibt es keine Freigabe.")
    if not hmac.compare_digest(_code_hash(e.get("code_salz", ""), code),
                               str(e.get("code_hash", ""))):
        e["code_versuche"] = int(e.get("code_versuche") or 0) + 1
        _schreiben(b.area(root) / VERMERKE, daten)
        return abweisen("Der Freigabecode stimmt nicht (Versuch %d von %d)."
                        % (e["code_versuche"], CODE_VERSUCHE))
    e["freigabe"] = {
        "zeit": b.now().isoformat(), "von": "Patron", "bestaetigung": BESTAETIGUNG,
        "ausloeser": ausloeser, "kennung": str(kennung)[:64],
        "an": _entwurf_an(root, entwurf),
        "pruefsumme": entwurfspruefsumme(b.area(root) / "entwuerfe" / str(entwurf))}
    _schreiben(b.area(root) / VERMERKE, daten)
    protokoll(root, "freigabe_bestaetigt", vorlage=str(vorlage)[:160],
              entwurf=str(entwurf)[:160], an=e["freigabe"]["an"], ausloeser=ausloeser)
    return dict(e["freigabe"], ok=True, grund="Freigabecode bestaetigt.")


def _vermerk_zum_entwurf(root, entwurf):
    treffer = [e for e in _vermerke(root).values()
               if str(e.get("entwurf", "")) == str(entwurf)]
    return sorted(treffer, key=lambda x: str(x.get("zeit", "")))[-1] if treffer else None


def versand_erlaubt(root, entwurf):
    """Die harte Sperre, gefragt vom Versand selbst. (bool, Satz)

    Sie kennt nur den Entwurfsnamen - denn nur den kennt jack_postfaecher.
    Alles muss stimmen: gueltiger Testversand, Freigabe per Freigabecode,
    derselbe Empfaenger, dieselbe Pruefsumme, noch nicht verbraucht.
    """
    satz = "Erst Testversand an den Patron, dann Freigabe."
    e = _vermerk_zum_entwurf(root, entwurf)
    if not e:
        return False, satz
    ok, grund = testversand_gueltig(root, e.get("vorlage", ""), entwurf)
    if not ok:
        return False, grund
    frei = e.get("freigabe") or {}
    if not frei.get("zeit"):
        return False, (satz + " Der Testversand liegt vor, die Freigabe des "
                       "Patrons fehlt noch.")
    if frei.get("bestaetigung") != BESTAETIGUNG or frei.get("von") != "Patron":
        return False, ("Die Freigabe ist nicht mit dem Freigabecode aus der [TEST]-Mail "
                       "bestaetigt. " + satz)
    if frei.get("verbraucht"):
        return False, "Diese Freigabe ist verbraucht - der Entwurf ist bereits gesendet."
    if str(frei.get("an", "")).lower() != _entwurf_an(root, entwurf).lower():
        return False, "Der Empfaenger ist nicht der freigegebene. " + satz
    jetzt = entwurfspruefsumme(b.area(root) / "entwuerfe" / str(entwurf))
    if frei.get("pruefsumme") != jetzt:
        return False, ("Der Entwurf hat sich nach der Freigabe geaendert. " + satz)
    return True, "Testversand und Freigabe per Freigabecode liegen vor, der Entwurf ist unveraendert."


def freigabe_verbrauchen(root, entwurf, message_id=""):
    """Nach dem Versand: diese Freigabe gilt nie wieder."""
    daten = _vermerke(root)
    for e in daten.values():
        if str(e.get("entwurf", "")) == str(entwurf) and e.get("freigabe"):
            e["freigabe"]["verbraucht"] = b.now().isoformat()
            e["freigabe"]["message_id"] = str(message_id)[:200]
    _schreiben(b.area(root) / VERMERKE, daten)


def testversand(root, vorlage, von="Patron"):
    """TESTVERSAND AN PATRON — dieselbe Mail, nur an den Patron.

    Nimmt eine Mitarbeiter-Freigabekarte und schickt den daran hängenden
    Entwurf an jack_postfaecher.TESTEMPFAENGER. Der Empfänger steht fest im
    Code und wird hier nicht entgegengenommen — es gibt keinen Weg, über die
    Maske eine andere Adresse zu erreichen.

    Das ist KEINE Freigabe. Die Karte bleibt, wo sie ist, im Zustand
    "freigabe"; die Akte bleibt unberührt; Lernstufen bleiben unberührt.
    """
    import jack_postfaecher
    root = Path(root)
    if not re.fullmatch(r"[^/\\]{1,200}\.md", str(vorlage or "")):
        raise ValueError("Unzulässiger Dateiname")
    karte = root / "auftraege" / "freigabe" / str(vorlage)
    if not karte.is_file() or karte.is_symlink():
        raise ValueError("Diese Karte liegt nicht in auftraege/freigabe/")
    text = karte.read_text(encoding="utf-8")
    kopf = {}
    for zeile in text.splitlines()[1:]:
        if zeile.strip() == "---":
            break
        k, _, w = zeile.partition(":")
        kopf[k.strip().lower()] = w.strip()
    if kopf.get("art") not in MAILKARTEN:
        raise ValueError("Der Testversand gilt nur für Mail-Karten "
                         "(diese Karte ist »%s«)." % kopf.get("art", "ohne Art"))
    # F-64: eine Karte, die schon durch eine neuere Fassung ersetzt/zurueckgestellt ist, bekommt keinen Testversand mehr -
    # der Patron loeste am 27.09. versehentlich einen an einer solchen Karte aus.
    marke = str(kopf.get("wartemarke", ""))
    if re.search(r"ersetzt", marke, re.I):        # NICHT "zurueckgestellt" allein (normales WARTEN)
        raise ValueError("Diese Karte ist ersetzt (%s) - kein Testversand." % marke[:160])
    entwurf = kopf.get("entwurf", "").strip()
    if not entwurf:
        raise ValueError("An dieser Karte hängt kein Entwurf.")

    vorher = karte.read_bytes()
    # Block 27: Der Code geht NUR in die [TEST]-Mail. Er wird nicht
    # zurueckgegeben, nicht protokolliert und nur als Hash vermerkt.
    code = "-".join("".join(secrets.choice(CODE_ZEICHEN) for _ in range(4))
                    for _ in range(2))
    antwort = jack_postfaecher.senden(root, entwurf, von=von, test=True,
                                      freigabecode=code)
    # Gegenprobe: die Karte darf sich durch einen Testversand NICHT ändern.
    #
    # 18.09.2026: Hier brach ein Lauf ab, NACHDEM die Mail schon draussen war —
    # der laufende Dienst hatte die Karte in derselben Sekunde nach
    # auftraege/erledigt/ geraeumt und als "gegenstandslos" verbucht. Die Karte
    # war also nicht veraendert, sondern verschoben. Das ist ein Unterschied:
    # gefragt ist, ob der TESTVERSAND sie angefasst hat.
    #
    # Deshalb wird jetzt unterschieden. Ist sie geraeumt und dort unveraendert,
    # laeuft es weiter und der Vermerk wird geschrieben — sonst bliebe der Weg
    # zum Mitarbeiter zu, obwohl alles richtig lief. Ist sie veraendert, bricht
    # es ab wie bisher.
    if karte.is_file():
        if karte.read_bytes() != vorher:
            protokoll(root, "testversand_karte_veraendert", vorlage=str(vorlage))
            raise ValueError("Der Testversand hat die Karte verändert — das darf "
                             "nicht sein. Bitte melden.")
    else:
        geraeumt = root / "auftraege" / "erledigt" / str(vorlage)
        if geraeumt.is_file() and geraeumt.read_bytes() == vorher:
            protokoll(root, "testversand_karte_geraeumt", vorlage=str(vorlage),
                      wohin="auftraege/erledigt")
        else:
            protokoll(root, "testversand_karte_verschwunden", vorlage=str(vorlage))
            raise ValueError("Die Karte ist waehrend des Testversands verschwunden "
                             "und liegt auch nicht unveraendert in erledigt/. "
                             "Bitte melden.")
    protokoll(root, "testversand", mitarbeiter=kopf.get("mitarbeiter", ""),
              vorlage=str(vorlage), an=jack_postfaecher.TESTEMPFAENGER,
              erfolg=bool(antwort.get("ok")), wer=von)
    if antwort.get("ok"):
        if kopf.get("mitarbeiter"):
            messung_merken(root, kopf.get("mitarbeiter", ""), "testversand",
                           vorlage=str(vorlage))
        # Block 22: Erst dieser Vermerk oeffnet den Weg zum Mitarbeiter.
        v = testversand_vermerken(root, vorlage, entwurf,
                                  message_id=antwort.get("message_id", ""), code=code)
        antwort["vermerk"] = v
        antwort["meldung"] = (str(antwort.get("meldung", "")) + " Der Freigabecode "
                              "steht nur in dieser Testmail. FREIGEBEN geht nur mit "
                              "ihm — und nur, solange der Entwurf unveraendert bleibt.")
    del code
    return antwort


def notiz(root, kennung, projekt, text, ziel="intern", von="Patron", betreff=""):
    """Eine Notiz. "intern" bleibt im Haus, "an DIN" wird ein Mailentwurf."""
    text = str(text or "").strip()
    if not text:
        raise ValueError("Eine leere Notiz wird nicht abgelegt.")
    if str(ziel) not in ("intern", "an_din"):
        raise ValueError("Unbekanntes Ziel: %s" % ziel)
    jetzt = b.now()
    ordnerziel = fach(root, kennung, projekt, "notiz")
    name = "%s_%s.md" % (jetzt.strftime("%Y-%m-%d_%H%M%S"),
                         re.sub(r"[^A-Za-z0-9]+", "_", betreff or text)[:40].strip("_") or "notiz")
    datei = ordnerziel / name
    datei.write_text("\n".join([
        "---",
        "art:        notiz",
        "mitarbeiter: %s" % kennung,
        "projekt:    %s" % projekt,
        "ziel:       %s" % ziel,
        "von:        %s" % von,
        "erstellt:   %s" % jetzt.strftime("%Y-%m-%d %H:%M"),
        "---",
        "",
        text,
        "",
    ]), encoding="utf-8")
    eintrag, _ = ablegen(root, kennung, {
        "projekt": projekt, "art": "notiz",
        "richtung": "intern" if ziel == "intern" else "aus",
        "von": von, "an": "intern" if ziel == "intern"
               else stammdaten(root, kennung).get("rufname", kennung),
        "datum": jetzt.isoformat(), "kurztext": betreff or text,
        "pfad": str(datei), "quelle": "JACK-Notiz"})
    protokoll(root, "notiz", mitarbeiter=kennung, projekt=projekt, ziel=ziel)
    if ziel == "intern":
        return {"ok": True, "eintrag": eintrag,
                "meldung": "Intern abgelegt. Es geht nichts hinaus."}
    vorlage = entwurf_an_mitarbeiter(
        root, kennung, betreff or "Note from GOTT WALD HOLDING", text,
        projekt=projekt, von=von,
        worum="Notiz des Patrons an %s, als Mail." % stammdaten(root, kennung).get("rufname", kennung))
    return {"ok": True, "eintrag": eintrag, "vorlage": vorlage["vorlage"],
            "meldung": vorlage["meldung"]}


def auftrag_vorschlagen(root, kennung, projekt, titel, text, faellig="", von="JACK"):
    """JACK schlaegt den naechsten Arbeitsauftrag vor - als Freigabe.

    Erst FREIGEBEN legt den Auftrag in die Akte UND sendet ihn als Mail.
    """
    return entwurf_an_mitarbeiter(
        root, kennung, titel, text, projekt=projekt, auftrag_titel=titel,
        faellig=faellig, von=von,
        worum=("Vorschlag für den nächsten Arbeitsauftrag an %s. FREIGEBEN legt ihn "
               "in die Akte und schickt ihn als E-Mail."
               % stammdaten(root, kennung).get("rufname", kennung)))


# ──────────────── Block 21, Teil H: die erste Mail (Schritt 1) ─────────────
CI_ORDNER = "ALLGEMEIN/Dokumente/CI"


CI_PAKET = "Signature_Package_Dween_Mohammad.zip"


def ci_paket_bauen(root, kennung):
    """Das Signaturpaket als EIN ZIP - Entscheidung des Patrons 17.09.2026.

    Vorher gingen fuenf lose Anhaenge hinaus. Fuenf Anhaenge an einer Mail sind
    unuebersichtlich, und eine .md-Datei kann ein Mailprogramm nicht anzeigen.
    Jetzt sind es zwei: der CI-Leitfaden als PDF und dieses Paket.

    Im Paket: die Signatur (HTML), die Textfassung, das Logo und die
    Einbau-Anleitung als PDF. Gebaut mit zipfile - kein Systemwerkzeug, damit
    kein __MACOSX-Ordner und keine .DS_Store mit hineinrutschen.
    """
    import zipfile
    basis = ordner(root, kennung) / CI_ORDNER
    inhalt = [
        (basis / "Signatur" / "Signatur_Dween_Mohammad_DIN.html",
         "Signatur_Dween_Mohammad_DIN.html"),
        (basis / "Signatur" / "Signatur_Dween_Mohammad_DIN_TEXT.txt",
         "Signatur_Dween_Mohammad_DIN_TEXT.txt"),
        (basis / "Signatur" / "Installation_Guide.pdf",
         "Installation_Guide.pdf"),
        (basis / "Signatur" / "assets" / "gottwald-logo.png",
         "assets/gottwald-logo.png"),
    ]
    fehlen = [str(q) for q, _ in inhalt if not q.is_file()]
    if fehlen:
        raise ValueError("Für das Signaturpaket fehlen: %s" % ", ".join(fehlen))
    ziel = basis / CI_PAKET
    # Feste Zeitangabe je Datei: dasselbe Paket zweimal gebaut ist bitgleich.
    with zipfile.ZipFile(ziel, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for quelle, name in inhalt:
            eintrag = zipfile.ZipInfo(name, date_time=(2026, 9, 17, 12, 0, 0))
            eintrag.compress_type = zipfile.ZIP_DEFLATED
            eintrag.external_attr = 0o644 << 16
            z.writestr(eintrag, quelle.read_bytes())
    protokoll(root, "ci_paket_gebaut", mitarbeiter=kennung,
              datei=CI_PAKET, dateien=len(inhalt),
              groesse=ziel.stat().st_size)
    return ziel


def ci_anhaenge(root, kennung):
    """Die ZWEI Anhänge der CI-Mail, als Pfade relativ zur Holding.

    (a) der CI-Leitfaden als PDF, (b) das Signaturpaket als ZIP.
    Das Paket wird bei jedem Aufruf frisch gebaut, damit es nie hinter den
    Signaturdateien zurueckbleibt.
    """
    basis = ordner(root, kennung) / CI_ORDNER
    ci_paket_bauen(root, kennung)
    reihe = [basis / "2026-09-17_GOTT-WALD_CI-Quick-Guide_v1.pdf",
             basis / CI_PAKET]
    fehlen = [str(x) for x in reihe if not x.is_file()]
    if fehlen:
        raise ValueError("Diese CI-Dateien fehlen: %s" % ", ".join(fehlen))
    return [str(x) for x in reihe]


def ci_mail_entwurf(root, kennung, von="JACK"):
    """Schritt 1: Signatur und CI-Leitfaden, erste Aufgabe Standbericht."""
    stamm = stammdaten(root, kennung)
    name = stamm.get("rufname") or kennung
    start = stamm.get("start", "31 August 2026")
    text = """Hello %s,

thank you for your patience over the last weeks. Things were quiet on our side
for reasons that had nothing to do with you or your work. That is over, and we
are picking this up properly now.

Two things come with this mail.

FIRST — your email signature and our CI guide.
Two attachments. The ZIP holds your signature: the HTML file you install, a
plain-text fallback, the logo, and a step-by-step install guide for Apple Mail,
Gmail and Outlook. The PDF is our CI quick guide. Please save both and use them
from now on: the signature on every mail you send from
%s, and the guide whenever you name a file, pick a
colour or set type for us. It is short on purpose — everything in it is
something we will otherwise have to correct later.

One note on the signature: it carries no phone number. That is deliberate and
applies to everyone here. Contact by email only.

SECOND — your first task, as a reply to this mail.
Before we hand you the next piece of work, we need to know exactly where things
stand. Please write us a status report covering:

  1. What you have worked on since %s — including YIG.CARE.
  2. For each part: what is finished, what is half-done, what has not started.
  3. What is still open, and roughly how many hours of work you think is left.
  4. What you need from the Patron in order to continue — access, decisions,
     feedback, anything that is blocking you.

Please be plain about it. If something stalled, say so and say why; nobody here
will hold that against you. A wrong picture of where we stand costs us far more
than an uncomfortable sentence.

Length: one page is plenty. Links or files where you have them — and please
remember that we cannot open Figma without access, so attach an export or send
us access.

From here on, everything runs through email to this address. It is your work
account, it belongs to the company, and it is archived and reviewed — that is
normal for a work account and it will be stated in your contract, which is the
next thing we owe you.

Thank you,""" % (name, (stamm.get("kontakt") or {}).get("email_arbeit", ""), start)
    return entwurf_an_mitarbeiter(
        root, kennung, "Your signature, our CI guide — and your first task",
        text, anhaenge=ci_anhaenge(root, kennung), projekt=ALLGEMEIN, von=von,
        schritt=1,
        worum=("Schritt 1 von 5: Signatur und CI-Leitfaden an %s, dazu die erste "
               "Aufgabe (Standbericht als Antwort auf diese Mail). Fünf Anhänge."
               % name))


# ──────────────── Nachtrag 3: die Kennenlern- und Skill-Mail ───────────────
def skill_mail_entwurf(root, kennung, von="JACK"):
    """Schritt 3: Was kann er, was macht er gern, was will er lernen.

    Der Text ist warm und konkret und fragt NUR, was in den Stammdaten fehlt.
    Was schon bekannt ist, wird genannt statt erfragt - alles andere waere
    respektlos gegenueber jemandem, der seit dem 31.08. arbeitet.
    """
    stamm = stammdaten(root, kennung)
    name = stamm.get("rufname") or kennung
    profil = skillprofil(root, kennung)
    bekannt = []
    if stamm.get("rolle"):
        bekannt.append("your role: %s" % stamm["rolle"])
    if stamm.get("ausbildung"):
        bekannt.append("your degree: %s" % stamm["ausbildung"])
    if stamm.get("werkzeuge"):
        bekannt.append("your main tool: %s" % ", ".join(stamm["werkzeuge"]))
    if stamm.get("erfahrung"):
        bekannt.append("your background: %s" % str(stamm["erfahrung"])[:180])

    offen = [x for x in profil["bereiche"] if not x["bekannt"]]
    zeilen = ["Hello %s," % name, "",
              "you have been with us since %s and you have already done real work "
              "on YIG.CARE. Before we hand you the next piece, we want to know you "
              "properly — not just as a designer, but as the person we are working "
              "with." % (stamm.get("start", "the end of August")),
              "",
              "We already know %s. We are not asking about any of that again."
              % ("; ".join(bekannt) if bekannt else "very little about your work"),
              "",
              "What we would like from you is a short, honest self-assessment. For "
              "each area below, give us a number from 1 to 5 and — this is the part "
              "that matters — one concrete example or a link. A 2 with a good "
              "example is worth far more to us than a 5 without one.",
              "",
              "  1 = I have touched it   ·   3 = I work in it confidently   ·   "
              "5 = I could teach it",
              ""]
    for x in offen or profil["bereiche"]:
        zeilen.append("  · " + SKILL_ENGLISCH.get(x["bereich"], x["bereich"]))
    zeilen += [
     "",
     "Then four short questions, in your own words:",
     "",
     "  1. Which languages do you speak, and how well?",
     "  2. Which time zone are you in, and when do you actually like to work?",
     "  3. What do you enjoy most in this profession — and what do you not enjoy?",
     "  4. What would you like to learn in the next twelve months?",
     "",
     "And one request: send us your portfolio or two or three case studies. Not a "
     "polished presentation — the real thing, including what went wrong and what "
     "you would do differently.",
     "",
     "This should take you 30 to 45 minutes. Please do not spend longer on it. "
     "Short and honest beats long and careful.",
     "",
     "One more thing worth saying plainly: there is a market we care about that you "
     "know far better than we do — Bangladesh and South Asia. If you have contacts, "
     "an opinion on what works there, or simply a feeling about it, write it down. "
     "That is not a side note for us.",
     "",
     "Thank you,",
    ]
    return entwurf_an_mitarbeiter(
        root, kennung, "Getting to know you — a short self-assessment",
        "\n".join(zeilen), projekt=ALLGEMEIN, von=von, schritt=3,
        worum=("Schritt 3 von 5: Kennenlern- und Skill-Mail an %s. Fragt nur, was "
               "in den Stammdaten fehlt (%d von %d Bereichen). Antwortaufwand für "
               "ihn: 30–45 Minuten."
               % (name, len(offen), profil["gesamt"])))


# ──────────────── Nachtrag 4: die Berichtspruefung ─────────────────────────
# Die Pruefung ist eine REGEL, kein Modellurteil. Sie stellt fest, was
# nachpruefbar ist und was nicht - das Urteil faellt der Patron. So kostet
# jeder Bericht null und faellt nie von Lauf zu Lauf anders aus.
_LINK = re.compile(r"https?://[^\s<>\)\]]+")
_STUNDEN = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:h\b|hrs?\b|hours?|std|stunden)", re.I)
NICHT_PRUEFBAR = ("figma.com", "drive.google.com", "dropbox.com", "notion.so",
                  "miro.com", "loom.com", "wetransfer.com")


def _arbeiten_zerlegen(text):
    """Die genannten Arbeiten aus einem Bericht holen. Eine Zeile = eine Arbeit."""
    raus = []
    for zeile in str(text or "").splitlines():
        z = zeile.strip()
        if len(z) < 8:
            continue
        z = re.sub(r"^[-*\u2022\u00b7]\s*|^\d+[.)]\s*", "", z).strip()
        if len(z) < 8:
            continue
        # Anrede, Gruss und reine Zeitangaben sind keine Arbeit.
        if re.match(r"^(hi|hello|hey|dear|thanks|thank you|best|kind regards|"
                    r"regards|cheers|sincerely|hallo|liebe[rn]?|viele gr|mfg)\b",
                    z, re.I):
            continue
        ohne_zeit = _STUNDEN.sub("", z)
        if len(re.sub(r"[^A-Za-zÄÖÜäöüß]", "", ohne_zeit)) < 6:
            continue
        raus.append(z[:400])
    return raus[:40]


def bericht_pruefen(root, kennung, text, datum=None, quelle=""):
    """Prueft EINEN Arbeitsbericht. Gibt eine Karte zurueck - sendet nichts."""
    arbeiten = _arbeiten_zerlegen(text)
    basis = ordner(root, kennung)
    frueher = [e for e in index(root, kennung, art="bericht")]
    offene = auftraege(root, kennung, offen_nur=True)
    befunde = []
    for arbeit in arbeiten:
        links = _LINK.findall(arbeit)
        stand, beleg, grund = "NICHT PRÜFBAR", "", "kein Beleg genannt"
        if links:
            nicht = [l for l in links if any(d in l.lower() for d in NICHT_PRUEFBAR)]
            if nicht:
                grund = ("Link auf %s — JACK hat dort keinen Zugang"
                         % nicht[0].split("/")[2])
                beleg = nicht[0][:160]
            else:
                stand, beleg, grund = "GEPRÜFT", links[0][:160], "Link genannt"
        else:
            # Steht eine Datei aus der Akte im Satz?
            for e in index(root, kennung):
                name = Path(str(e.get("pfad") or "")).name
                if name and len(name) > 6 and name.lower() in arbeit.lower():
                    stand, beleg, grund = "GEPRÜFT", e["pfad"], "Datei liegt in der Akte"
                    break
        # Widerspruch: schon einmal als erledigt gemeldet?
        for alt_bericht in frueher:
            if arbeit[:60].lower() and arbeit[:60].lower() in \
                    str(alt_bericht.get("kurztext", "")).lower():
                stand = "WIDERSPRUCH"
                grund = ("dieselbe Arbeit war schon am %s als erledigt gemeldet"
                         % str(alt_bericht.get("datum", ""))[:10])
                beleg = alt_bericht.get("pfad", "")
                break
        bewertung = {"GEPRÜFT": "passt", "NICHT PRÜFBAR": "nachbessern",
                     "WIDERSPRUCH": "nachbessern"}[stand]
        befunde.append({"arbeit": _sauber(arbeit, 240), "stand": stand,
                        "beleg": beleg, "grund": grund, "bewertung": bewertung})

    # Was in der Aufgabenliste offen ist, im Bericht aber nicht vorkommt: FEHLT.
    heu = str(text or "").lower()
    for a in offene:
        titel = str(a.get("kurztext", ""))
        if titel and titel.lower()[:40] not in heu:
            befunde.append({"arbeit": _sauber(titel, 240), "stand": "FEHLT",
                            "beleg": a.get("pfad", ""),
                            "grund": "steht offen in der Aufgabenliste, im Bericht nicht erwähnt",
                            "bewertung": "fehlt"})

    stunden = sum(float(m.replace(",", ".")) for m in _STUNDEN.findall(str(text or "")))
    gezaehlt = {"GEPRÜFT": 0, "NICHT PRÜFBAR": 0, "WIDERSPRUCH": 0, "FEHLT": 0}
    for b_ in befunde:
        gezaehlt[b_["stand"]] += 1

    verbesserungen = []
    if gezaehlt["NICHT PRÜFBAR"]:
        verbesserungen.append(
            "Zu jeder Arbeit einen Beleg mitschicken, den JACK öffnen kann — "
            "Datei oder öffentlicher Link. %d von %d Punkten sind so nicht prüfbar."
            % (gezaehlt["NICHT PRÜFBAR"], len(befunde)))
    if any("figma.com" in str(b_["beleg"]) for b_ in befunde):
        verbesserungen.append(
            "Figma-Links laufen ins Leere, solange JACK keinen Zugang hat. "
            "Entweder Zugang einrichten oder PNG/PDF-Export anhängen.")
    if not stunden:
        verbesserungen.append(
            "Stunden nennen (zum Beispiel »6h«), sonst lässt sich die Auslastung nicht "
            "gegen die 40-Stunden-Woche halten.")
    elif stunden < 6:
        verbesserungen.append(
            "%.1f Stunden an einem Tag ist wenig gegenüber 40 in der Woche — "
            "entweder war weniger zu tun, oder es fehlt etwas im Bericht." % stunden)
    if gezaehlt["FEHLT"]:
        verbesserungen.append(
            "%d offene Aufgabe(n) kommen im Bericht nicht vor. Auch »nicht "
            "angefasst« ist eine Meldung." % gezaehlt["FEHLT"])
    if gezaehlt["WIDERSPRUCH"]:
        verbesserungen.append(
            "Eine Arbeit wurde zweimal als erledigt gemeldet. Nachfragen, was "
            "davon neu war.")
    verbesserungen = verbesserungen[:5]

    kurz = [
      "%d Punkte im Bericht: %d geprüft, %d nicht prüfbar, %d widersprüchlich, %d fehlen."
      % (len(befunde), gezaehlt["GEPRÜFT"], gezaehlt["NICHT PRÜFBAR"],
         gezaehlt["WIDERSPRUCH"], gezaehlt["FEHLT"]),
      ("%.1f Stunden genannt." % stunden) if stunden else "Keine Stunden genannt.",
      "Soll sind 40 Stunden je Woche.",
    ]
    if gezaehlt["FEHLT"]:
        kurz.append("%d offene Aufgabe(n) bleiben unerwähnt." % gezaehlt["FEHLT"])
    if not verbesserungen:
        kurz.append("Kein Nachbesserungsbedarf erkennbar.")

    return {"mitarbeiter": kennung, "datum": str(datum or b.now().isoformat()),
            "quelle": quelle, "kurzfassung": kurz[:5], "befunde": befunde,
            "stunden_genannt": stunden, "soll_stunden": 40,
            "gezaehlt": gezaehlt, "verbesserungen": verbesserungen,
            "hinweis": ("Regelbasierte Prüfung, kein Modellurteil. Sie stellt fest, "
                        "was nachprüfbar ist — das Urteil fällt der Patron.")}


# ──────────────── Nachtrag 5: Einteilung und Einsatzvorschlag ──────────────
EINSATZ = "mitarbeiter_einsatz.json"


def einsatzkarte_vorlegen(root, kennung, pruefung, einsatzkarte, optionen,
                          wochenplan, von="JACK", grund_aenderung=""):
    """Die Karte „<Name> · Bericht geprüft · Einsatzvorschlag".

    Sie SENDET NICHTS. Der Patron waehlt eine der drei Optionen; erst dann baut
    JACK den Arbeitsauftrag als zweiten Entwurf, und erst ein zweites FREIGEBEN
    schickt ihn hinaus.

    einsatzkarte: [{marke, geeignet: ja|teilweise|nein, begruendung, quelle}]
    optionen:     [{rang, marke, teil, ziel, stunden, warum_din, nutzen, risiko,
                    quelle, abschluss: bool}]
    wochenplan:   [{tag_oder_block, was, stunden}]
    """
    import jack_freigaben
    root = Path(root)
    if len(optionen) != 3:
        raise ValueError("Es müssen genau drei Optionen sein, gereiht.")
    stamm = stammdaten(root, kennung)
    name = stamm.get("rufname") or kennung
    jetzt = b.now()

    # "Abschluss vor Neuem": Gibt es offene Arbeit, MUSS Option 1 deren
    # Abschluss sein. Das wird hier geprueft, nicht nur behauptet.
    if any(o.get("abschluss") for o in optionen) and not optionen[0].get("abschluss"):
        raise ValueError("Regel »Abschluss vor Neuem«: Option 1 muss der Abschluss "
                         "der offenen Arbeit sein.")

    # Der vorherige Vorschlag bleibt nachvollziehbar - er wird nicht ueberschrieben.
    p = _area(root) / EINSATZ
    stand = _lesen(p, {})
    frueher = stand.get(str(kennung), {}).get("verlauf", [])
    nummer = len(frueher) + 1

    zeilen = [
        "---",
        "marke:      GOTT_WALD",
        "auftrag:    Einsatzvorschlag_%s_%d" % (kennung, nummer),
        "erteilt:    %s" % jetzt.strftime("%Y-%m-%d %H:%M"),
        "von:        JACK-Mitarbeiter",
        "status:     freigabe",
        "freigabe:   nein",
        "gefahr:     innen",
        "tiefe:      mittel",
        "besetzung:  1",
        "versuch:    0",
        "warte_bis:  ",
        "bereiche:   mitarbeiter",
        "art:        entscheidung",
        "vorgang:    mitarbeiter_einsatz",
        "karte:      %s · Bericht geprüft · Einsatzvorschlag" % name,
        "mitarbeiter: %s" % kennung,
        "fassung:    %d" % nummer,
        "schritt:    5",
        "---",
        "",
        "# %s · Bericht geprüft · Einsatzvorschlag" % name,
    ]
    if grund_aenderung:
        zeilen += ["", "> **Fassung %d.** Die vorherige Fassung bleibt liegen und "
                       "nachvollziehbar. Geändert, weil: %s" % (nummer, grund_aenderung)]
    zeilen += ["", "## 1 · Der Bericht, kurz", ""]
    zeilen += ["- " + z for z in (pruefung or {}).get("kurzfassung", ["(kein Bericht geprüft)"])]

    zeilen += ["", "## 2 · Jede genannte Arbeit", "",
               "| Arbeit | Stand | Beleg / Grund | Bewertung |", "|---|---|---|---|"]
    for b_ in (pruefung or {}).get("befunde", []) or [{"arbeit": "(kein Bericht)",
                                                       "stand": "—", "beleg": "",
                                                       "grund": "", "bewertung": "—"}]:
        zeilen.append("| %s | **%s** | %s | %s |" % (
            b_.get("arbeit", "")[:120], b_.get("stand", ""),
            (b_.get("beleg") or b_.get("grund", ""))[:90], b_.get("bewertung", "")))

    stunden = (pruefung or {}).get("stunden_genannt", 0)
    zeilen += ["", "**Stunden:** %s genannt, Soll 40 je Woche." % (
        ("%.1f" % stunden) if stunden else "keine")]

    verb = (pruefung or {}).get("verbesserungen", [])
    if verb:
        zeilen += ["", "## 3 · Verbesserungen (höchstens fünf, nach Wirkung)", ""]
        zeilen += ["%d. %s" % (i + 1, v) for i, v in enumerate(verb)]

    zeilen += ["", "## 4 · Einsatzkarte — wo passt %s?" % name, "",
               "| Marke / Bereich | Geeignet | Begründung | Quelle |", "|---|---|---|---|"]
    for e in einsatzkarte:
        zeilen.append("| %s | **%s** | %s | %s |" % (
            e.get("marke", ""), e.get("geeignet", "unbekannt"),
            str(e.get("begruendung", ""))[:160], str(e.get("quelle", ""))[:90]))

    zeilen += ["", "## 5 · Drei Optionen für den nächsten Projektpart", ""]
    for o in optionen:
        zeilen += [
            "### Option %s — %s · %s%s" % (o.get("rang"), o.get("marke", ""),
                                           o.get("teil", ""),
                                           "  *(Abschluss vor Neuem)*" if o.get("abschluss") else ""),
            "",
            "| Feld | Angabe |", "|---|---|",
            "| Ziel | %s |" % str(o.get("ziel", ""))[:220],
            "| Geschätzte Stunden | %s |" % o.get("stunden", "unbekannt"),
            "| Warum %s | %s |" % (name, str(o.get("warum_din", ""))[:220]),
            "| Nutzen | %s |" % str(o.get("nutzen", ""))[:220],
            "| Risiko | %s |" % str(o.get("risiko", ""))[:220],
            "| Quelle | %s |" % str(o.get("quelle", ""))[:160],
            "",
        ]

    zeilen += ["## 6 · Wochenplan für die freigegebene Option (40 Stunden)", "",
               "| Block | Was | Stunden |", "|---|---|---|"]
    summe = 0
    for w in wochenplan:
        zeilen.append("| %s | %s | %s |" % (w.get("block", ""), w.get("was", ""),
                                            w.get("stunden", "")))
        try:
            summe += float(w.get("stunden", 0))
        except (TypeError, ValueError):
            pass
    zeilen.append("| **Summe** | | **%g** |" % summe)

    zeilen += [
        "", "## Prüfpunkte", "",
        "**FREIGEBEN** wählt eine Option und baut daraus den Arbeitsauftrag als",
        "**zweiten Entwurf**. Erst ein zweites FREIGEBEN schickt ihn an %s." % name,
        "**ÄNDERN** erzeugt eine neue Fassung; diese hier bleibt liegen.",
        "**ABLEHNEN** verwirft den Vorschlag; es geht nichts hinaus.",
        "",
        "Angaben ohne Quelle sind als **ANNAHME** gekennzeichnet. Was hier nicht",
        "belegt ist, wurde nicht behauptet.",
        "",
    ]

    ziel = root / "auftraege" / "freigabe"
    ziel.mkdir(parents=True, exist_ok=True)
    dateiname = "%s_MITARBEITER_EINSATZ_%s_%d.md" % (
        jetzt.strftime("%Y-%m-%d_%H%M%S"), kennung, nummer)
    (ziel / dateiname).write_text("\n".join(zeilen), encoding="utf-8")

    frueher.append({"fassung": nummer, "datei": dateiname, "zeit": jetzt.isoformat(),
                    "grund": str(grund_aenderung)[:200],
                    "optionen": [{"rang": o.get("rang"), "marke": o.get("marke"),
                                  "teil": o.get("teil"), "ziel": o.get("ziel"),
                                  "stunden": o.get("stunden"),
                                  "abschluss": bool(o.get("abschluss"))}
                                 for o in optionen]})
    stand.setdefault(str(kennung), {})["verlauf"] = frueher
    stand[str(kennung)]["aktuell"] = dateiname
    _schreiben(p, stand)

    try:
        jack_freigaben.anfordern(root, dateiname,
                                 grund="Einsatzvorschlag für " + kennung)
    except Exception:
        pass
    schritt_setzen(root, kennung, 5, "vorgelegt", beleg=dateiname)
    ablegen(root, kennung, {
        "projekt": ALLGEMEIN, "art": "notiz", "richtung": "intern", "von": "JACK",
        "an": "Patron", "datum": jetzt.isoformat(),
        "kurztext": "Einsatzvorschlag Fassung %d — Bericht geprüft" % nummer,
        "pfad": "", "quelle": "auftraege/freigabe/" + dateiname})
    protokoll(root, "einsatzvorschlag", mitarbeiter=kennung, fassung=nummer,
              datei=dateiname)
    return {"ok": True, "vorlage": dateiname, "fassung": nummer,
            "optionen": len(optionen),
            "meldung": "Einsatzvorschlag Fassung %d liegt im Freigaben-Kasten. "
                       "Es geht nichts hinaus." % nummer}


def einsatz_verlauf(root, kennung):
    """Alle Fassungen des Einsatzvorschlags - die alten bleiben nachvollziehbar."""
    return _lesen(_area(root) / EINSATZ, {}).get(str(kennung), {})


def einsatz_option_waehlen(root, kennung, rang, von="Patron"):
    """Der Patron waehlt eine Option. Daraus wird der Arbeitsauftrag als
    ZWEITER Entwurf - gesendet wird er erst nach dem zweiten FREIGEBEN."""
    verlauf = einsatz_verlauf(root, kennung)
    if not verlauf.get("verlauf"):
        raise ValueError("Es liegt kein Einsatzvorschlag vor.")
    aktuell = verlauf["verlauf"][-1]
    gewaehlt = next((o for o in aktuell["optionen"] if str(o["rang"]) == str(rang)), None)
    if not gewaehlt:
        raise ValueError("Diese Option gibt es nicht: %s" % rang)
    stamm = stammdaten(root, kennung)
    name = stamm.get("rufname") or kennung
    titel = "%s — %s" % (gewaehlt["marke"], gewaehlt["teil"])
    text = """Hello %s,

thank you for your report. Here is your next piece of work.

WHAT
%s — %s

GOAL
%s

ESTIMATED EFFORT
%s hours. If you get there and find it is materially more or less, tell us
before you carry on rather than afterwards.

HOW WE WANT IT REPORTED
One short report per working day: what you did, a link or file we can open, what
is next, and anything blocking you. Please remember we cannot open Figma without
access — send an export or send us access.

Thank you,""" % (name, gewaehlt["marke"], gewaehlt["teil"], gewaehlt["ziel"],
                 gewaehlt.get("stunden", "—"))
    vorlage = entwurf_an_mitarbeiter(
        root, kennung, "Your next piece of work — %s" % gewaehlt["marke"], text,
        projekt=str(gewaehlt["marke"]), auftrag_titel=titel, von=von,
        worum=("Zweites FREIGEBEN: Der Patron hat Option %s gewählt. FREIGEBEN legt "
               "den Auftrag in die Akte UND schickt ihn als E-Mail an %s."
               % (rang, name)))
    protokoll(root, "einsatz_option", mitarbeiter=kennung, rang=rang,
              marke=gewaehlt["marke"], vorlage=vorlage["vorlage"])
    return {"ok": True, "option": gewaehlt, "vorlage": vorlage["vorlage"],
            "meldung": "Option %s gewählt. Der Arbeitsauftrag liegt als zweiter "
                       "Entwurf im Freigaben-Kasten — %s"
                       % (rang, vorlage["meldung"])}


def datei_ablegen(root, kennung, projekt, name, daten, art=None, von="Patron"):
    """Eine gezogene Datei in die Akte legen. Ueberschreibt nie."""
    sauber_name = re.sub(r"[^A-Za-z0-9_.\- ]+", "_", str(name or "datei"))[:100] or "datei"
    if art is None:
        art = "foto" if Path(sauber_name).suffix.lower() in (
            ".jpg", ".jpeg", ".png", ".gif", ".heic", ".webp") else "dokument"
    ziel = fach(root, kennung, projekt, art) / sauber_name
    if ziel.exists():
        ziel = ziel.with_name("%s_%s%s" % (ziel.stem, b.now().strftime("%H%M%S"), ziel.suffix))
    atomic_bytes(ziel, daten)
    eintrag, _ = ablegen(root, kennung, {
        "projekt": projekt, "art": art, "richtung": "intern", "von": von,
        "an": "", "datum": b.now().isoformat(), "kurztext": sauber_name,
        "pfad": str(ziel), "quelle": "vom Patron in die Akte gezogen"})
    protokoll(root, "datei_abgelegt", mitarbeiter=kennung, projekt=projekt,
              art=art, datei=sauber_name)
    return eintrag


def auftrag_zustand(root, kennung, eintrag_id, zustand, von="Patron"):
    """Einen Auftrag auf erledigt (oder zurueck auf offen) setzen."""
    if zustand not in ("offen", "erledigt"):
        raise ValueError("Unbekannter Zustand: %s" % zustand)
    p = indexpfad(root, kennung)
    zeilen = list(b.records(p))
    treffer = [z for z in zeilen if str(z.get("id")) == str(eintrag_id)
               and z.get("art") == "auftrag"]
    if not treffer:
        raise ValueError("Diesen Auftrag gibt es nicht.")
    treffer[0]["zustand"] = zustand
    treffer[0]["zustand_gesetzt"] = "%s von %s" % (b.now().isoformat(), von)
    datei = ordner(root, kennung) / str(treffer[0].get("pfad") or "")
    if datei.is_file() and datei.suffix == ".md":
        text = datei.read_text(encoding="utf-8")
        datei.write_text(re.sub(r"^zustand:.*$", "zustand:    " + zustand, text,
                                count=1, flags=re.M), encoding="utf-8")
    atomic_bytes(p, ("\n".join(json.dumps(z, ensure_ascii=False) for z in zeilen)
                     + "\n").encode("utf-8"))
    protokoll(root, "auftrag_zustand", mitarbeiter=kennung, eintrag=eintrag_id,
              zustand=zustand, wer=von)
    return treffer[0]


if __name__ == "__main__":
    import sys
    wurzel = Path(__file__).resolve().parent
    was = sys.argv[1] if len(sys.argv) > 1 else "lage"
    if was == "lage":
        print(json.dumps(lage(wurzel), ensure_ascii=False, indent=1))
    elif was == "akte":
        print(json.dumps(akte(wurzel, sys.argv[2]), ensure_ascii=False, indent=1))
    elif was == "wache":
        print(json.dumps(wache(wurzel), ensure_ascii=False, indent=1))
    elif was == "ablage":
        print(json.dumps(ablage_anlegen(wurzel, sys.argv[2]), ensure_ascii=False, indent=1))
    else:
        print("lage | akte <id> | wache | ablage <id>")
