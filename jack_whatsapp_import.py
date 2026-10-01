#!/usr/bin/env python3
"""WhatsApp-Import: einen WhatsApp-Chat-Export in die Mitarbeiter-Akte lesen.

Block 21, Teil D, 17.09.2026. Liest eine `_chat.txt` aus einem WhatsApp-Export
zeilenweise, baut daraus Akte-Eintraege (art=whatsapp, bei Anhaengen foto oder
dokument) und haengt sie ueber jack_mitarbeiter.ablegen() an den Akte-Index
des Mitarbeiters an - genau wie mail_ablegen() das fuer Post tut.

Grundsatz wie im ganzen Modul: die Datei ist die Wahrheit. Anhaenge werden
NICHT kopiert - die Originale bleiben in 00_Quelle liegen, der Index verweist
nur relativ darauf.

Idempotent: eintragskennung() macht aus Art + Zeitstempel + Absender +
Text-Hash + Zeilennummer einen stabilen Schluessel. Ein zweiter Lauf desselben
oder eines spaeter fortgesetzten Exports haengt nichts doppelt an.

Nur Bordmittel. Keine neue Abhaengigkeit.
"""
import json
import re
import shutil
import sys
from pathlib import Path

import jack_mitarbeiter as m

# Die beiden Absender, die in diesem Export vorkommen - sonst niemand.
PATRON_NAME = "GOTT WALD"
DIN_NAME = "Mohammad Dween"

# Kopfzeile einer Nachricht: [TT.MM.JJ, HH:MM:SS] Name: Text (Rest der Zeile).
# WhatsApp stellt manchmal ein unsichtbares U+200E (Links-nach-rechts-Marke)
# vor den Zeitstempel - das ist optional mitgemeint.
_KOPF = re.compile(
    r"^‎?\[(\d{2})\.(\d{2})\.(\d{2}), (\d{2}):(\d{2}):(\d{2})\] "
    r"(%s|%s): ?(.*)$" % (re.escape(PATRON_NAME), re.escape(DIN_NAME)))

# Anhang-Tag, deutsch oder englisch, irgendwo im (zusammengesetzten) Text -
# auch mitten in einer Bildunterschrift.
_ANHANG = re.compile(r"<(?:Anhang|attached):\s*([^>]+)>", re.I)

# Unsichtbare Steuerzeichen, die WhatsApp in Exporte einstreut.
_UNSICHTBAR = re.compile("[‎‏]")

FOTO_ENDUNGEN = (".jpg", ".jpeg", ".png", ".heic")
DOKUMENT_ENDUNGEN = (".pdf",)
SPRACHNACHRICHT_ENDUNGEN = (".opus",)

TRANSKRIPTIONSWERKZEUGE = ("whisper", "whisper-cli", "whisper-cpp")

# Die drei sensiblen Dokumente aus dem Datenblatt (Auftrag Teil D, Regel 4).
# Schluessel = genauer Dateiname im Export. Wert = (fester Kurztext ohne
# Nummer, Dateiname der Verweisdatei, kurze Beschreibung fuer die Verweisdatei).
SENSIBLE_DOKUMENTE = {
    "00000107-Personal Info (Dween Mohamamd).pdf": (
        "Personal-Datenblatt (sensibel)",
        "Personal-Datenblatt (sensibel).md",
        "das Personal-Datenblatt (Anstellung, Verguetung, Kontakt)"),
    "00000108-nid-7351744250 (1).pdf": (
        "Personalausweis (sensibel)",
        "Personalausweis (sensibel).md",
        "der Personalausweis (nationale ID)"),
    "00000109-Passport.pdf": (
        "Passport (sensibel)",
        "Passport (sensibel).md",
        "der Reisepass"),
}


def _wurzel():
    """Die JACK-Marke - der Ordner dieser Datei. Wie in jack_mitarbeiter.py."""
    return Path(__file__).resolve().parent


def _art_je_anhang(dateiname):
    endung = Path(dateiname).suffix.lower()
    if endung in FOTO_ENDUNGEN:
        return "foto"
    if endung in DOKUMENT_ENDUNGEN:
        return "dokument"
    return "whatsapp"


def _nachrichten(text):
    """Zerlegt den Chat-Text in einzelne Nachrichten.

    Jede Nachricht ist ein dict mit datum (ISO 8601, Europe/Vienna, +02:00 -
    laut Auftrag fuer alle Daten in diesem Export korrekt), sender, zeile
    (1-basiert, fuer eine stabile Idempotenz-Kennung) und text (alle Zeilen
    bis zur naechsten Kopfzeile, zusammengefuegt und von \\r befreit).
    """
    raus = []
    aktuelle = None
    for nr, roh in enumerate(text.split("\n"), start=1):
        zeile = roh.rstrip("\r")
        treffer = _KOPF.match(zeile)
        if treffer:
            if aktuelle is not None:
                raus.append(aktuelle)
            tt, mm, jj, hh, mi, ss, sender, rest = treffer.groups()
            datum = "20%s-%s-%sT%s:%s:%s+02:00" % (jj, mm, tt, hh, mi, ss)
            aktuelle = {"datum": datum, "sender": sender, "zeile": nr,
                        "text": [rest]}
        elif aktuelle is not None:
            aktuelle["text"].append(zeile)
        # Zeilen vor der ersten Kopfzeile kommen in diesem Export nicht vor -
        # saeh es sie doch geben, werden sie stillschweigend uebersprungen.
    if aktuelle is not None:
        raus.append(aktuelle)
    for n in raus:
        voll = "\n".join(n["text"])
        n["text"] = _UNSICHTBAR.sub("", voll).strip()
    return raus


def _transkriptionswerkzeug():
    """Erstes gefundenes Transkriptionswerkzeug - oder None. Installiert nie etwas."""
    for werkzeug in TRANSKRIPTIONSWERKZEUGE:
        if shutil.which(werkzeug):
            return werkzeug
    return None


def _verweisdatei_schreiben(root, kennung, md_name, kurztext, beschreibung,
                             exportordner_name, trockenlauf):
    """Legt die kurze Verweisdatei fuer ein sensibles Dokument an - einmalig,
    ueberschreibt nie, enthaelt ausdruecklich keine Nummer, keine
    Wallet-Adresse und keine Steuernummer."""
    ziel = m.ordner(root, kennung) / m.ALLGEMEIN / "Dokumente" / "Personal" / md_name
    if ziel.exists() or trockenlauf:
        return ziel, False
    ziel.parent.mkdir(parents=True, exist_ok=True)
    inhalt = "\n".join([
        "---",
        "art:        verweis",
        "mitarbeiter: %s" % kennung,
        "sensibel:   true",
        "---",
        "",
        "# %s" % kurztext,
        "",
        "Das Original ist %s aus dem WhatsApp-Export von DIN," % beschreibung,
        "abgelegt im Quellordner:",
        "",
        "`08_Mitarbeiter/Dween_Mohammad/00_Quelle/%s/`" % exportordner_name,
        "",
        "Diese Verweisdatei nennt bewusst keine Nummer, keine Wallet-Adresse",
        "und keine Steuernummer. Das Original liegt unveraendert im",
        "Quellordner und wird von hier nicht kopiert.",
        "",
    ])
    ziel.write_text(inhalt, encoding="utf-8")
    return ziel, True


def _eintrag_bauen(root, kennung, nachricht, exportordner, trockenlauf):
    """Baut aus EINER geparsten Nachricht den fertigen Akte-Eintrag.

    Gibt (eintrag, sprachnachricht) zurueck - das Ablegen selbst macht der
    Aufrufer, damit hier nichts geschrieben wird, was nicht auch gezaehlt wird.
    """
    text = nachricht["text"]
    sender = nachricht["sender"]
    ist_din = sender == DIN_NAME
    rufname = m.stammdaten(root, kennung).get("rufname") or "DIN"
    von, an = (rufname, "Patron") if ist_din else ("Patron", rufname)
    richtung = "ein" if ist_din else "aus"

    anhang_treffer = _ANHANG.search(text)
    anhang_name = anhang_treffer.group(1).strip() if anhang_treffer else ""
    rest_text = _ANHANG.sub("", text).strip() if anhang_treffer else text

    art = "whatsapp"
    pfad = ""
    anhaenge = []
    quelle = "WhatsApp-Export %s, Zeile %d" % (exportordner.name, nachricht["zeile"])
    kurztext = rest_text
    sensibel = False
    hinweis = ""
    sprachnachricht = False
    projekt_fest = None

    if anhang_name:
        art = _art_je_anhang(anhang_name)
        endung = Path(anhang_name).suffix.lower()
        if not (exportordner / anhang_name).is_file():
            hinweis = "Datei im Export nicht gefunden"

        if anhang_name in SENSIBLE_DOKUMENTE:
            sensibel = True
            kurztext_fix, md_name, beschreibung = SENSIBLE_DOKUMENTE[anhang_name]
            kurztext = kurztext_fix
            anhaenge = [kurztext_fix]
            projekt_fest = m.ALLGEMEIN
            # Keine Nummer im Index: pfad zeigt auf die Verweisdatei, nicht
            # auf das Original mit seinem ziffernhaltigen Dateinamen.
            _verweisdatei_schreiben(root, kennung, md_name, kurztext_fix,
                                    beschreibung, exportordner.name, trockenlauf)
            pfad = str(Path(m.ALLGEMEIN) / "Dokumente" / "Personal" / md_name)
            quelle = "WhatsApp-Export %s (sensibel, siehe Verweisdatei)" % exportordner.name
        else:
            pfad = str(Path(m.QUELLORDNER) / exportordner.name / anhang_name)
            anhaenge = [anhang_name]
            kurztext = rest_text or ("Anhang: %s" % anhang_name)

        if endung in SPRACHNACHRICHT_ENDUNGEN:
            sprachnachricht = True
            werkzeug = _transkriptionswerkzeug()
            if werkzeug:
                kurztext = ("Sprachnachricht — nicht transkribiert (Werkzeug %s "
                           "gefunden, aber nicht ausgefuehrt)" % werkzeug)
            else:
                kurztext = ("Sprachnachricht — nicht transkribiert (kein "
                           "Transkriptionswerkzeug auf diesem Rechner)")

    if projekt_fest:
        projekt, sicherheit = projekt_fest, 1.0
    else:
        projekt, sicherheit = m.projekt_raten(root, kennung, text)

    eid = m.eintragskennung(art, nachricht["datum"], von, text,
                            zusatz="whatsapp-zeile:%d" % nachricht["zeile"])
    eintrag = {
        "id": eid, "projekt": projekt, "art": art, "richtung": richtung,
        "von": von, "an": an, "datum": nachricht["datum"], "kurztext": kurztext,
        "pfad": pfad, "anhaenge": anhaenge, "quelle": quelle,
        "sicherheit": sicherheit,
    }
    if sensibel:
        eintrag["sensibel"] = True
    if hinweis:
        eintrag["hinweis"] = hinweis
    return eintrag, sprachnachricht


def importieren(root, kennung, exportordner, trockenlauf=False):
    """Liest einen WhatsApp-Export und haengt jede Nachricht an die Akte an.

    trockenlauf=True schreibt nichts (kein Index-Eintrag, keine
    Verweisdatei) - nur zaehlen, was passieren wuerde.

    Gibt zurueck: {gelesen, neu, uebersprungen, je_projekt, unzugeordnet,
    sprachnachrichten}.
    """
    root = Path(root)
    exportordner = Path(exportordner)
    chat = exportordner / "_chat.txt"
    if not chat.is_file():
        raise ValueError("Keine _chat.txt in %s" % exportordner)
    text = chat.read_text(encoding="utf-8", errors="replace")
    nachrichten = _nachrichten(text)

    # Einmal holen, nicht je Nachricht - siehe jack_mitarbeiter.ablegen().
    vorhandene = m._kennungen(root, kennung)

    ergebnis = {"gelesen": 0, "neu": 0, "uebersprungen": 0,
                "je_projekt": {}, "unzugeordnet": 0, "sprachnachrichten": 0}
    for n in nachrichten:
        eintrag, sprachnachricht = _eintrag_bauen(root, kennung, n, exportordner,
                                                   trockenlauf)
        if trockenlauf:
            neu = eintrag["id"] not in vorhandene
        else:
            _, neu = m.ablegen(root, kennung, eintrag, vorhandene=vorhandene)

        ergebnis["gelesen"] += 1
        ergebnis["neu" if neu else "uebersprungen"] += 1
        ergebnis["je_projekt"][eintrag["projekt"]] = (
            ergebnis["je_projekt"].get(eintrag["projekt"], 0) + 1)
        if sprachnachricht:
            ergebnis["sprachnachrichten"] += 1

    ergebnis["unzugeordnet"] = ergebnis["je_projekt"].get(m.UNZUGEORDNET, 0)
    return ergebnis


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Aufruf: python3 jack_whatsapp_import.py <exportordner> [--trockenlauf]")
        sys.exit(1)
    _trocken = "--trockenlauf" in sys.argv[2:]
    _ergebnis = importieren(_wurzel(), "dween-mohammad", sys.argv[1],
                            trockenlauf=_trocken)
    print(json.dumps(_ergebnis, ensure_ascii=False, indent=1))
