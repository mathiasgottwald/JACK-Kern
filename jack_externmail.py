#!/usr/bin/python3
"""F-52 (25.09.2026): persoenliche Mail des Patrons an Dritte (Mailart "Extern") als Entwurf + Freigabe-Karte.

Nichts wird hier gesendet. Die Karte (Art `externemail`) traegt den vollen Mailtext; erst FREIGEBEN im Freigaben-Fenster fuehrt
`jack_oberflaeche._anwenden` aus: Pruefsumme des aktuellen Entwurfs -> `jack_postfaecher.senden(..., patron_freigabe_sha=...)`.
Seit F-53 gilt die Testversand-Pflicht wie bei jeder Mail (Knopf Testversand, Freigabecode); die Groessenpruefung (F-47) und die Rückläufer-Zuordnung (F-47) gelten.
"""
import re
from pathlib import Path

import jack_betrieb as b

ABSENDER = "office@gottwald.world"
ROLLE = "patron_persoenlich"


STANDARD_ANREDE = {"anrede_unbekannt": "Sehr geehrte Damen und Herren,", "grussformel": "Mit freundlichen Grüßen",
                   "gruss_verboten": ["vielen dank und freundliche grüße", "vielen dank und freundliche gruesse", "viele grüße", "viele gruesse",
                                      "beste grüße", "beste gruesse", "liebe grüße", "herzliche grüße", "freundliche grüße", "freundliche gruesse"]}


def anrede_pruefen(root, text):
    """F-54: Dauerregel des Patrons fuer externe Mails in seinem Namen (maildesign.json extern_anrede). Verstoss -> ValueError,
    die Karte wird dann nicht erzeugt. Eine persoenliche Anrede ('Sehr geehrter Herr ...') bleibt erlaubt."""
    import jack_postfaecher as P
    r = dict(STANDARD_ANREDE, **((P.maildesign(root) or {}).get("extern_anrede") or {}))
    zeilen = [z.strip() for z in str(text).strip().splitlines() if z.strip()]
    if not zeilen:
        raise ValueError("Leerer Mailtext.")
    erste = zeilen[0].lower()
    if not erste.startswith("sehr geehrte"):
        raise ValueError("Anrede-Regel (F-54): Die Mail beginnt mit »%s«. Erlaubt ist »%s« (oder eine persönliche Anrede »Sehr geehrter …«)." % (zeilen[0][:40], r.get("anrede_unbekannt")))
    gruss = r.get("grussformel", "Mit freundlichen Grüßen")
    if gruss not in zeilen:
        raise ValueError("Anrede-Regel (F-54): Die Zeile »%s« fehlt am Schluss." % gruss)
    for z in zeilen:
        if z.lower().rstrip(",") in [v.rstrip(",") for v in r.get("gruss_verboten", [])]:
            raise ValueError("Anrede-Regel (F-54): Grußformel »%s« ist für externe Mails des Patrons nicht zulässig." % z)


def signaturzeilen_entfernen(text):
    """F-63: Die Signatur (Name, Anschrift, Mail, Telefon) kommt aus dem Signaturblock der Rolle, nicht aus dem Mailtext. Alles NACH der
    letzten Zeile 'Mit freundlichen Grüßen' faellt weg; der Gruss bleibt. Ohne diese Zeile bleibt der Text unveraendert."""
    zeilen = str(text).rstrip().splitlines()
    idx = [i for i, z in enumerate(zeilen) if z.strip() == "Mit freundlichen Grüßen"]
    return "\n".join(zeilen[: idx[-1] + 1]) if idx else str(text).strip()


def anfrage_anlegen(root, an, betreff, text, titel, worum, warum, bei_ja, bei_nein="Nichts geht hinaus; der Entwurf bleibt in der Ablage.",
                    belege="", sammel_meldung="", von="JACK-Kern (F-52)", rolle=ROLLE, kopf_extra=None):
    """-> {'vorlage': Kartenname, 'entwurf': Entwurfsname}. Entwurf in betrieb/entwuerfe, Karte in auftraege/freigabe."""
    import jack_freigaben
    import jack_postfaecher as P
    root = Path(root)
    if rolle == ROLLE:
        if not P.signaturrollen(root).get(ROLLE, {}).get("grussformel_im_text"):
            text = signaturzeilen_entfernen(text)                 # F-63: Signaturblock der Rolle statt Signaturzeilen im Text
        anrede_pruefen(root, text)                                 # F-54: Verstoss => keine Karte (gilt fuer Mails des Patrons in seinem Namen)
    if not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", an or ""):
        raise ValueError("Ungültiger Empfänger")
    betreff = re.sub(r"[\r\n]+", " ", str(betreff or "")).strip()
    if not betreff:
        raise ValueError("Ohne Betreff wird nichts entworfen.")
    postfach = P._postfach(root, ABSENDER)
    P.signatur(root, ABSENDER, rolle=rolle)                       # prueft: Rolle vorhanden und freigegeben
    entwurf = b.draft_path(root, "extern_" + betreff, ".md")
    kopf = ["---", "art:        mailentwurf", "postfach:   %s" % ABSENDER, "an:         %s" % an, "betreff:    %s" % betreff,
            "mailart:    Extern", "weg:        %s" % P.freigabeweg(postfach), "signatur:   %s" % rolle]
    for k, w in (kopf_extra or {}).items():
        kopf.append("%s: %s" % (k.ljust(10), w))
    if belege:
        kopf.append("belege:     %s" % belege)
    if sammel_meldung:
        kopf.append("sammel_meldung: %s" % sammel_meldung)
    kopf += ["erstellt_von: %s" % von, "erstellt:   %s" % b.now().strftime("%Y-%m-%d %H:%M"), "zustand:    wartet_auf_patron", "---", "", str(text).strip(), ""]
    entwurf.write_text("\n".join(kopf), encoding="utf-8")
    entwurf.with_suffix(".urfassung").write_text(str(text).strip(), encoding="utf-8")
    jetzt = b.now()
    kurz = re.sub(r"[^a-zA-Z0-9]+", "_", titel)[:40].strip("_") or "mail"
    von_zeile = (("%s (Anzeige „Mathias Gottwald“, ohne Signatur — der Schluss steht im Text)" % ABSENDER) if rolle == ROLLE
                else ("%s (Anzeige „JACK · Office of the Patron“, mit Signatur; der KI-Hinweis steht als letzte Zeile über der Signatur)" % ABSENDER))
    # F-78 (29.09.2026): echte v2-Werte statt der Altform (nur marke/auftrag/titel, kein
    # projekt/eingegangen/kern/frage/empfehlung/frist/dringlichkeit) - aus den ohnehin uebergebenen
    # Parametern worum/warum/bei_ja/bei_nein, nichts erfunden.
    v2 = {
        "projekt": titel, "marke": "GOTT_WALD",
        "eingegangen": jetzt.strftime("%Y-%m-%d %H:%M"), "von": von_zeile, "an": an,
        "art": "externemail", "betreff": betreff,
        "kern": worum, "frage": "Soll diese Mail jetzt aus %s an %s gesendet werden?" % (ABSENDER, an),
        "empfehlung": "%s Bei Ja: %s Bei Nein: %s" % (warum, bei_ja, bei_nein),
        "frist": "keine", "dringlichkeit": "niedrig",
        "ablauf": "TESTVERSAND → Code → FREIGEBEN",
        "entwurf": entwurf.name,  # F-78-Nachbesserung: ging bei der Migration verloren - ohne dieses
                                  # Feld findet testversand()/senden() den Entwurf nicht mehr.
    }
    v2.update(kopf_extra or {})  # beliebige Zusatzfelder des Aufrufers bleiben erhalten (wie in der Altform).
    pfad = jack_freigaben.karte_schreiben(root, v2, "\n".join([
        "## Auftrag", "Soll diese Mail jetzt aus %s an %s gesendet werden?" % (ABSENDER, an), "",
        "## Worum es geht", worum, "",
        "| Feld | Wert |", "|---|---|", "| Von | %s |" % von_zeile,
        "| An | %s |" % an, "| Betreff | %s |" % betreff, "| Mailart | Extern/Anfrage (erst Testversand) |", "",
        "## Text der Mail", "```", str(text).strip(), "```", "",
        "## Empfehlung von JACK", "", "**Entscheid:** FREIGEBEN", "**Empfehlung:** Freigeben: Der Patron hat den Versand dieser Mail am 25.09.2026 im PM-Chat freigegeben; der Text ist unverändert.",
        "**Warum:** %s" % warum, "**Bei Ja:** %s" % bei_ja, "**Bei Nein:** %s" % bei_nein, "",
        "## Prüfpunkte", "Erst TESTVERSAND AN PATRON, dann den Freigabecode aus der [TEST]-Mail eintragen; erst dann sendet FREIGEBEN genau diese Mail aus %s und legt eine Kopie im Gesendet-Ordner und im Belegordner ab. ABLEHNEN verwirft sie; es geht nichts hinaus." % ABSENDER, ""
    ]), herkunft="jack_externmail.anfrage_anlegen",
       dateiname="%s_EXTERN_%s.md" % (jetzt.strftime("%Y-%m-%d_%H%M%S"), kurz))
    if pfad is None:
        return {"vorlage": "", "entwurf": entwurf.name, "titel": titel,
                "meldung": "Kartenkopf unvollstaendig - siehe Fehlerkarte in abnahme/pm_eingang/."}
    name = pfad.name
    try:
        jack_freigaben.anfordern(root, name, grund="Extern-Mail an %s" % an)
    except Exception:
        pass
    P.protokoll(root, "extern_entwurf_vorgelegt", an=an, betreff=betreff[:120], vorlage=name)
    return {"vorlage": name, "entwurf": entwurf.name, "titel": titel}
