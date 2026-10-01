#!/usr/bin/env python3
"""Zugangsschluessel im macOS-Schluesselbund (Block 10, Teil B).

Bis zum 16.09.2026 standen der Anthropic- und der ElevenLabs-Schluessel im
Klartext in SCHLUESSEL.txt und .env - in einem Ordner, der in iCloud liegt und
auf zwei Macs synchronisiert wird. Seit Block 7b funktioniert der
Schluesselbund nachweislich; hier kommen die Schluessel hinein.

Zwei Regeln, die diese Datei durchsetzt:

1. **Ein Schluessel wird nie ausgegeben.** Keine Rueckgabe in ein Protokoll,
   keine Anzeige in der Oberflaeche, kein Teilstueck. Fehler melden, dass
   etwas fehlt - nie, was drinsteht.
2. **Schreiben wird zurueckgelesen.** Die eigene verdeckte Eingabe fragt das
   Geheimnis zweimal ab. Der macOS-Befehl bekommt danach den bereits
   bestätigten Wert als festen Parameter; seine TTY-Abfrage würde eine
   Übergabe über die Prozess-Eingabe ignorieren. Danach wird der Eintrag
   aus dem Schlüsselbund zurückgelesen.
"""
import re
import subprocess

DIENST = "JACK"                 # derselbe Dienst wie fuer die Postfaecher
NAME_MUSTER = re.compile(r"[A-Z0-9_]{4,120}")

# Diese Namen holt JACK aus dem Schluesselbund. Die Liste ist bewusst fest:
# ein Tippfehler soll nichts Neues anlegen, sondern auffallen.
BEKANNT = ("ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID",
           "MOONSHOT_API_KEY", "OPENAI_API_KEY", "RUNWAYML_API_SECRET",
           "HIGGSFIELD_API_KEY")


def _pruefe_name(name):
    if not NAME_MUSTER.fullmatch(str(name or "")):
        raise ValueError("Unzulaessiger Schluesselname")
    return str(name)


def stand(name):
    """("da"|"leer"|"fehlt"|"fehler", wert, satz) - wie bei den Postfaechern.

    Ein Lesefehler ist NICHT dasselbe wie "nicht vorhanden". Wer beides
    gleich behandelt, schreibt beim naechsten Schluesselbund-Hakler den
    Klartext-Rueckfall wieder scharf.
    """
    _pruefe_name(name)
    try:
        lauf = subprocess.run(
            ["/usr/bin/security", "find-generic-password", "-s", DIENST,
             "-a", name, "-w"],
            text=True, capture_output=True, timeout=20)
    except Exception:
        return ("fehler", "", "Der Schlüsselbund war nicht erreichbar.")
    if lauf.returncode == 0:
        wert = lauf.stdout.rstrip("\n")
        return ("da", wert, "") if wert else ("leer", "", "Der Eintrag im Schlüsselbund ist leer.")
    if lauf.returncode == 44:
        return ("fehlt", "", "Für diesen Namen liegt nichts im Schlüsselbund.")
    return ("fehler", "", "Der Schlüsselbund ließ sich nicht lesen (Rückgabewert %d)."
            % lauf.returncode)


def lesen(name):
    """Der Schluessel oder "" - nie eine Ausnahme, damit Aufrufer einfach bleiben."""
    zustand, wert, _ = stand(name)
    return wert if zustand == "da" else ""


def vorhanden(name):
    return stand(name)[0] == "da"


def setzen(name, wert):
    """Legt den Schluessel ab und liest ihn zurueck. Wirft, wenn er nicht ankam."""
    _pruefe_name(name)
    if not isinstance(wert, str) or not 8 <= len(wert) <= 400:
        raise ValueError("Der Schluessel fehlt oder ist unglaubwuerdig kurz")
    lauf = subprocess.run(
        ["/usr/bin/security", "add-generic-password", "-U", "-s", DIENST,
         "-a", name, "-w", wert],
        text=True, capture_output=True, timeout=20)
    if lauf.returncode != 0:
        raise ValueError("Der Schluesselbund hat den Eintrag abgelehnt")
    if lesen(name) != wert:
        raise ValueError("Der Schluessel kam nicht im Schluesselbund an")
    return True


def uebersicht():
    """Was liegt im Tresor? Nur Namen, Zustand und Laenge - nie der Wert."""
    raus = []
    for name in BEKANNT:
        zustand, wert, satz = stand(name)
        raus.append({"name": name, "zustand": zustand,
                     "zeichen": len(wert) if zustand == "da" else 0,
                     "hinweis": satz})
    return raus


if __name__ == "__main__":
    import getpass
    import json
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "stand":
        print(json.dumps(uebersicht(), ensure_ascii=False, indent=1))
    elif len(sys.argv) == 3 and sys.argv[1] == "setzen":
        name = _pruefe_name(sys.argv[2])
        if name not in BEKANNT:
            raise SystemExit("Dieser Schlüsselname ist nicht für JACK freigegeben.")
        erster = getpass.getpass("Schlüssel verdeckt eingeben: ")
        zweiter = getpass.getpass("Schlüssel zur Kontrolle wiederholen: ")
        if erster != zweiter:
            raise SystemExit("Die beiden Eingaben stimmen nicht überein; nichts gespeichert.")
        setzen(name, erster)
        print("Schlüssel im macOS-Schlüsselbund gespeichert und zurückgelesen.")
    else:
        print("stand — zeigt Namen und Zustand, nie den Wert\n"
              "setzen NAME — fragt den freigegebenen Schlüssel verdeckt ab")
