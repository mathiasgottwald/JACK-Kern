#!/usr/bin/env python3
"""M-14 (30.09.2026): Zusagen-Erkennung fuer das Mitarbeiter-Kontrollzentrum (F-103, Abschnitte B/K,
Kanal kern). Zuarbeit des Kanals cashflow - dieses Modul wird von kern eingebunden, nicht selbst in
die Oberflaeche gehaengt.

Erkennt in einer Mail/einem Bericht Selbstverpflichtungen ("I'll send…", "ich werde…"), Fristsprache
("by Friday", "EOD", "bis Freitag") und Rueckfragen ("Should I…?", "können Sie…?") - vor jeder Zeile
ein Vorfilter aus Signalwoertern (0 USD, reines Python), NUR Vorfilter-Treffer gehen an die guenstigste
erlaubte Modellstufe (`modell_router.draft`, Vorbild: bestehende Aufrufe in jack_postfaecher.py).
Ohne Modellzugriff (kein `root`/`keys` uebergeben, kein Schluessel, Deckel voll, Netzfehler) faellt
die Erkennung STILL auf eine rein regelbasierte Auswertung desselben Vorfilter-Treffers zurueck -
nie ein Absturz, nie eine verlorene Zusage nur weil ein Modell gerade nicht erreichbar ist.

Persistenz: <mitarbeiter_ordner>/zusagen.jsonl - append-only (Vorbild jack_termine.py Termin-Akte /
jack_betrieb.append): nichts wird geloescht oder ueberschrieben, ein Status-Wechsel haengt eine neue
Zeile mit derselben `id` an; der aktuelle Stand ist immer die JEWEILS LETZTE Zeile je `id`.
"""
import datetime as dt
import hashlib
import json
import re
from pathlib import Path

import jack_betrieb as b

DATEI = "zusagen.jsonl"

# ------------------------------------------------------------------ Vorfilter (0 USD, Deutsch/Englisch)
SIGNALWOERTER = re.compile(
    r"\bI['’]ll\b|\bI will\b|\bI can\b|\bwill send\b|\bwill deliver\b|\bwill have\b|\bwill finish\b|"
    r"\bby (?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|tomorrow|end of day|"
    r"end of (?:the )?week|next week)\b|\bEOD\b|\bASAP\b|\bplease\s+\w+|\bcan confirm\b|"
    r"\bshould I\b|\bdo you want\b|\bwould you like\b|\bcould you\b|\bcan you\b|\bneed(?:s|ed)? (?:you|from you)\b|"
    r"\bich werde\b|\bwerde ich\b|\bschicke (?:ich )?(?:dir|Ihnen)\b|\bsende (?:ich )?(?:dir|Ihnen)\b|"
    r"\bbis (?:Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag|morgen|Ende der Woche|"
    r"n(?:a|ä)chste Woche)\b|\bbitte\s+\w+|\bk(?:oe|ö)nnen Sie\b|\bkannst du\b|\bsoll ich\b",
    re.I)

RUECKFRAGE_MUSTER = re.compile(
    r"\?\s*$|\bshould I\b|\bdo you want\b|\bwould you like\b|\bcould you\b(?!.{0,40}\bI['’]ll\b)|"
    r"\bplease confirm\b|\bsoll ich\b|\bk(?:oe|ö)nnen Sie\b.{0,40}\?", re.I)

WOCHENTAGE = {"monday": 0, "montag": 0, "tuesday": 1, "dienstag": 1, "wednesday": 2, "mittwoch": 2,
              "thursday": 3, "donnerstag": 3, "friday": 4, "freitag": 4, "saturday": 5, "samstag": 5,
              "sunday": 6, "sonntag": 6}
WOCHENTAG_MUSTER = re.compile(r"\b(?:by|bis)\s+(" + "|".join(WOCHENTAGE) + r")\b", re.I)
FRIST_WOERTER = [
    (re.compile(r"\bEOD\b|\bend of day\b", re.I), lambda basis: basis.replace(hour=18, minute=0, second=0)),
    (re.compile(r"\btomorrow\b|\bmorgen\b", re.I), lambda basis: basis + dt.timedelta(days=1)),
    (re.compile(r"\bASAP\b", re.I), lambda basis: basis + dt.timedelta(days=1)),
    (re.compile(r"end of (?:the )?week|Ende der Woche", re.I), lambda basis: _naechster_wochentag(basis, 4)),
    (re.compile(r"next week|n(?:a|ä)chste Woche", re.I), lambda basis: basis + dt.timedelta(days=7)),
]

_STOPWOERTER = {"dass", "sein", "wird", "wurde", "haben", "werden", "diese", "dieser", "dieses",
                "that", "this", "have", "will", "with", "from", "your", "please", "thanks", "about"}


def _naechster_wochentag(basis, ziel_index):
    tage = (ziel_index - basis.weekday()) % 7
    tage = tage or 7
    return basis + dt.timedelta(days=tage)


def _frist_aus_text(text, basis):
    treffer = WOCHENTAG_MUSTER.search(text)
    if treffer:
        return _naechster_wochentag(basis, WOCHENTAGE[treffer.group(1).lower()])
    for muster, funktion in FRIST_WOERTER:
        if muster.search(text):
            return funktion(basis)
    return None


def arbeitstage_addieren(basis, tage):
    """Standardfrist (F-103 B.2): ohne eigenen Termin gelten 2 Arbeitstage als ANNAHME."""
    ergebnis = basis
    hinzugefuegt = 0
    while hinzugefuegt < tage:
        ergebnis = ergebnis + dt.timedelta(days=1)
        if ergebnis.weekday() < 5:
            hinzugefuegt += 1
    return ergebnis


_MAX_SATZLAENGE = 400
_HTML_ERKENNUNG = re.compile(r"<html\b|<div\b|<span\b|<body\b|<br\s*/?>", re.I)
_HTML_TAG = re.compile(r"<[^>]+>")
_HTML_ENTITAET = {"&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'"}


def _html_entfernen(text):
    """Eigener Testlauf (M-14) gegen die echten DIN-Mails zeigte: manche Mails liefern selbst ueber
    jack_postfaecher._text_aus() (den text/plain-Teil) noch rohes HTML statt echtem Klartext - der
    Absender hat den Teil falsch deklariert, keine Ausnahme, kein Einzelfall in diesem Postfach. Statt
    darauf zu vertrauen, dass jeder Aufrufer sauberen Text liefert, erkennt dieses Modul HTML selbst
    (grobe Tag-Erkennung) und entfernt Tags/gaengige Entities, bevor irgendetwas geprueft wird."""
    text = str(text or "")
    if not _HTML_ERKENNUNG.search(text):
        return text
    text = _HTML_TAG.sub(" ", text)
    for roh, ersatz in _HTML_ENTITAET.items():
        text = text.replace(roh, ersatz)
    return text


_ZITAT_GRENZE = re.compile(
    r"(?:^|\n)[ \t]*Am\s.{0,60}?schrieb\s.{0,80}?:[ \t]*\n|"
    r"(?:^|\n)[ \t]*On\s.{0,60}?wrote:[ \t]*\n|"
    r"(?:^|\n)-{2,}[ \t]*Original Message[ \t]*-{2,}|"
    r"(?:^|\n)-{2,}[ \t]*Urspr(?:ü|ue)ngliche Nachricht[ \t]*-{2,}",
    re.I)


def _ohne_zitat(text):
    """Lehre aus F-79/M-7 (jack_termine._ohne_zitat, derselbe Fund): eine zitierte Ursprungsmail unter
    der eigentlichen Antwort enthaelt oft dieselben Saetze noch einmal - ohne diesen Schnitt zaehlt/
    doppelt jede zitierte Zusage mit UND die Zuordnung 'wer' kann sich auf die zitierte, nicht die
    neue Nachricht beziehen (`richtung` gilt nur fuer die aktuelle Mail, nicht fuer das Zitat darin)."""
    grenze = _ZITAT_GRENZE.search(text)
    return text[:grenze.start()] if grenze else text


def _saetze(text):
    """Zeilenweise, dann satzweise splitten - reine Regex-Satzsplittung an "[.!?]\\s+" allein reicht bei
    echten Mails nicht (lange Absaetze ohne verlaessliche Grossschreibung nach dem Punkt, HTML-Reste,
    Signaturbloecke); ohne die Zeilen-Vorstufe entstehen sehr lange 'Saetze' und damit unnoetig grosse/
    teure Modellaufrufe (Fund im eigenen Testlauf gegen die echten DIN-Mails, M-14). Eine harte
    Notbremse schneidet jeden verbleibenden Rest auf hoechstens `_MAX_SATZLAENGE` Zeichen."""
    text = _html_entfernen(text)
    text = _ohne_zitat(text)
    text = re.sub(r"[ \t]+", " ", str(text or "")).strip()
    saetze = []
    for zeile in text.split("\n"):
        zeile = zeile.strip()
        if not zeile or zeile.startswith(">"):
            continue
        for teil in re.split(r"(?<=[.!?])\s+", zeile):
            teil = teil.strip()
            while len(teil) > _MAX_SATZLAENGE:
                saetze.append(teil[:_MAX_SATZLAENGE])
                teil = teil[_MAX_SATZLAENGE:].strip()
            if len(teil) > 3:
                saetze.append(teil)
    return saetze


def _wer(richtung, satz):
    """Wer die Zusage schuldet: bei einer Selbstverpflichtung (\"I'll…\") der ABSENDER der Nachricht;
    bei einer Bitte/Frage an die Gegenseite (\"can you…\", \"please send…\") der EMPFAENGER - deshalb
    dreht sich die Zuordnung je nach Muster UND `richtung` (F-103 K.5: ein Auftrag/eine Bitte an DIN
    erzeugt eine Zusage DINs, keine Zusage von uns)."""
    if re.search(r"\bI['’]ll\b|\bI will\b|\bI can\b|\bich werde\b|\bwerde ich\b|"
                 r"\bschicke ich\b|\bsende ich\b", satz, re.I):
        return "DIN" if richtung == "ein" else "Patron/JACK"
    if re.search(r"\bcan you\b|\bcould you\b|\bplease (?:send|confirm|share|provide)\b|"
                 r"\bk(?:oe|ö)nnen Sie\b|\bkannst du\b|\bsoll ich\b|\bbitte (?:schicken|senden|bis)\b",
                 satz, re.I):
        return "Patron/JACK" if richtung == "ein" else "DIN"
    return "DIN" if richtung == "ein" else "Patron/JACK"


def _regelbasiert(satz, richtung, datum_dt):
    frist = _frist_aus_text(satz, datum_dt)
    annahme = frist is None
    if frist is None:
        frist = arbeitstage_addieren(datum_dt, 2)
    return {"wer": _wer(richtung, satz), "was": satz[:280], "faellig": frist.isoformat(),
            "annahme": annahme, "modell": "regelbasiert"}


def _modell_extrahieren(root, keys, satz, richtung, datum_dt):
    """Ein Versuch ueber die guenstigste erlaubte Modellstufe; JEDER Fehler faellt lautlos auf
    `_regelbasiert` zurueck (siehe Modul-Kommentar) - der Aufrufer merkt den Unterschied nur am
    Feld 'modell' im Ergebnis."""
    if root is None or keys is None:
        return None
    try:
        import modell_router
        frage = (
            "Lies genau diesen einen Satz aus einer Mail zwischen einem Mitarbeiter (DIN) und dem "
            "Patron. Antworte NUR mit einem JSON-Objekt, keine Erklaerung, kein Codeblock: "
            '{"ist_zusage": true oder false (false = reine Hoeflichkeit/Formalie/Signatur/'
            'Zitat ohne echte Selbstverpflichtung, Frist oder Bitte um eine konkrete Handlung), '
            '"wer": "DIN oder Patron/JACK", "was": "kurze Zusammenfassung, hoechstens 20 Woerter", '
            '"faellig": "JJJJ-MM-TT oder leer, wenn kein Datum/keine Frist genannt ist"}. '
            "Richtung dieser Nachricht: %s (ein = von DIN an uns, aus = von uns an DIN). "
            "Satz: %s" % (richtung, satz[:500]))
        ergebnis = modell_router.draft(root, keys, frage, role="fachkraft",
                                       art="klassifizieren", datenklasse="intern")
        antwort = ergebnis.get("antwort", "") if isinstance(ergebnis, dict) else ""
        treffer = re.search(r"\{.*\}", antwort, re.S)
        if not treffer:
            return None
        daten = json.loads(treffer.group(0))
        if daten.get("ist_zusage") is False:
            return {"verwerfen": True}
        wer = daten.get("wer") or _wer(richtung, satz)
        was = str(daten.get("was") or satz)[:280]
        faellig_roh = str(daten.get("faellig") or "").strip()
        annahme = not faellig_roh
        frist = None
        if faellig_roh:
            try:
                frist = dt.datetime.fromisoformat(faellig_roh)
                if frist.tzinfo is None:
                    frist = frist.replace(tzinfo=datum_dt.tzinfo)
            except ValueError:
                frist = None
                annahme = True
        if frist is None:
            frist = arbeitstage_addieren(datum_dt, 2)
        return {"wer": wer, "was": was, "faellig": frist.isoformat(), "annahme": annahme,
                "modell": ergebnis.get("modell", "unbekannt")}
    except Exception:
        return None


_AUTOMATISCHE_MAIL_MUSTER = re.compile(
    r"undelivered mail returned|mail delivery (?:failed|system)|delivery status notification|"
    r"returned mail|failure notice|undeliverable|mailer-daemon|postmaster|"
    r"automatically by Microsoft Outlook|zustellung fehlgeschlagen", re.I)


def erkennen(text, richtung, datum, quelle, root=None, keys=None):
    """-> Liste von Zusage-Dicts: wer/was/faellig/quelle/status/annahme/typ/modell/erkannt_am.
    `richtung` in ('ein', 'aus'); `datum` als ISO-String oder datetime (Zeitpunkt der Mail/des
    Berichts - Basis fuer relative Fristen und die Standardfrist); `quelle` frei (z. B. Mail-ID/Pfad).
    `root`/`keys` optional: nur mit BEIDEN wird die guenstigste Modellstufe versucht (siehe
    `_modell_extrahieren`), sonst laeuft alles regelbasiert - die Signatur bleibt ohne sie gueltig.

    Automatische System-/Bounce-Mails (Mailer-Daemon, Outlook-Testmails - Vorbild `_DSN_BETREFF` in
    jack_postfaecher.py) liefern nie eine Zusage: der eigene Testlauf (M-14) fand hier den einzigen
    echten Fehlalarm-Typ (\"please send mail to postmaster\" u.ae. wurde faelschlich als Bitte erkannt)."""
    if _AUTOMATISCHE_MAIL_MUSTER.search(str(text or "")[:400]):
        return []
    if isinstance(datum, str):
        try:
            datum_dt = dt.datetime.fromisoformat(datum)
        except ValueError:
            datum_dt = b.now()
    elif isinstance(datum, dt.datetime):
        datum_dt = datum
    else:
        datum_dt = b.now()
    if datum_dt.tzinfo is None:
        datum_dt = datum_dt.replace(tzinfo=b.ZONE)

    ergebnisse = []
    for satz in _saetze(text):
        if not SIGNALWOERTER.search(satz):
            continue
        typ = "rueckfrage" if RUECKFRAGE_MUSTER.search(satz) else "zusage"
        modell_ergebnis = _modell_extrahieren(root, keys, satz, richtung, datum_dt)
        if modell_ergebnis is not None and modell_ergebnis.get("verwerfen"):
            continue  # Modell hat geurteilt: reine Hoeflichkeit/Formalie, keine echte Zusage/Bitte
        basis = modell_ergebnis or _regelbasiert(satz, richtung, datum_dt)
        eintrag = {
            "id": hashlib.sha256(("%s|%s|%s" % (quelle, satz, basis["was"])).encode()).hexdigest()[:16],
            "wer": basis["wer"], "was": basis["was"], "faellig": basis["faellig"],
            "quelle": quelle, "status": "vorgeschlagen", "annahme": basis["annahme"],
            "typ": typ, "modell": basis["modell"], "erkannt_am": b.now().isoformat(),
            "satz": satz[:400],
        }
        ergebnisse.append(eintrag)
    return ergebnisse


# --------------------------------------------------------------------- Erledigt-Pruefung (F-103 B.3)
def erledigt_pruefen(zusage, spaetere_eintraege):
    """-> (vermutlich_erledigt: bool, beleg: dict|None). Reiner Stichwort-Abgleich aus dem Feld 'was'
    gegen 'kurztext'/'text' spaeterer Akte-Eintraege (z. B. aus jack_mitarbeiter.index()) - NUR ein
    Vorschlag fuer den Patron, NIE eine automatische Erledigt-Markierung ohne dass der Beleg-Eintrag
    mitgeliefert wird (F-103 B.3: 'ohne Beleg bleibt unbestaetigt')."""
    stichworte = [w for w in re.findall(r"[A-Za-zÄÖÜäöüß]{4,}", zusage.get("was", ""))
                 if w.lower() not in _STOPWOERTER][:6]
    if not stichworte:
        return False, None
    noetig = max(2, len(stichworte) // 2)
    for eintrag in spaetere_eintraege:
        text = str(eintrag.get("kurztext") or eintrag.get("text") or "")
        treffer = sum(1 for w in stichworte if w.lower() in text.lower())
        if treffer >= noetig:
            return True, eintrag
    return False, None


# ------------------------------------------------------------------------------------- Persistenz
def zusagen_pfad(mitarbeiter_ordner):
    return Path(mitarbeiter_ordner) / DATEI


def anhaengen(mitarbeiter_ordner, zusage):
    """Haengt GENAU EINE Zeile an - nie loeschen, nie ueberschreiben (append-only, wie jack_betrieb.append
    es fuer jedes JACK-Protokoll vorschreibt)."""
    b.append(zusagen_pfad(mitarbeiter_ordner), dict(zusage))
    return zusage


def laden(mitarbeiter_ordner):
    """Alle Zeilen roh, aelteste zuerst - fuer den vollen Verlauf. Fuer den AKTUELLEN Stand siehe
    `stand(mitarbeiter_ordner)`."""
    return b.records(zusagen_pfad(mitarbeiter_ordner))


def stand(mitarbeiter_ordner):
    """-> {id: juengste Zeile}. Ein Status-Wechsel haengt eine neue Zeile mit derselben `id` an; das
    hier ist immer die LETZTE Zeile je `id` - der aktuelle Stand ohne den vollen Verlauf lesen zu muessen."""
    aktuell = {}
    for zeile in laden(mitarbeiter_ordner):
        kennung = zeile.get("id")
        if kennung:
            aktuell[kennung] = zeile
    return aktuell


def status_setzen(mitarbeiter_ordner, zusage_id, neuer_status, grund="", von="Patron"):
    """Haengt eine neue Zeile mit demselben `id` und dem neuen Status an (Status-Verlauf, siehe
    Modul-Kommentar). `neuer_status` in ('offen', 'erledigt', 'ueberfaellig', 'verschoben', 'verfallen',
    'verworfen') - F-103 B.4/B.2."""
    bisherige = stand(mitarbeiter_ordner).get(zusage_id)
    if bisherige is None:
        raise ValueError("Unbekannte Zusagen-ID: %s" % zusage_id)
    neue_zeile = dict(bisherige)
    neue_zeile["status"] = neuer_status
    neue_zeile["status_grund"] = grund
    neue_zeile["status_von"] = von
    neue_zeile["status_zeit"] = b.now().isoformat()
    return anhaengen(mitarbeiter_ordner, neue_zeile)
