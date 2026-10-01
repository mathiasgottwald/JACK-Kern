"""Block 25, Teil F: JACK darf oeffnen und anzeigen, was dem Patron hilft -
Karten, Kalender, Browser, Finder, Obsidian, Dateien/Ordner der Holding.
NUR OEFFNEN. Sendet, kauft, bestellt, abonniert, loescht, meldet nie an,
installiert nie, liest keine Schluessel.

Sicherheit (F1/F3, verschaerft nach der Sicherheitspruefung vom 18.09.2026 -
siehe abnahme/Block25_2026-09-18/F3_sicherheitspruefung_ergebnis.md):
  - /usr/bin/open wird ausschliesslich mit argv-Parametern aufgerufen
    (subprocess ohne shell=True) - der Sprachsatz/Parameter wird NIE in einen
    Shell-Text eingesetzt, sondern immer als eigenes Listenelement uebergeben.
  - Apps kommen aus einer FESTEN Liste (kein "oeffne irgendein Programm X"
    mit freiem App-Namen); Dateien/Ordner werden ausschliesslich ueber
    jack_erweiterungen.path() aufgeloest, die absolute Pfade, ".." und
    Symlinks verweigert - das Ziel bleibt zwingend innerhalb des uebergebenen
    Wurzelordners (die Holding).
  - NUR Dateien mit einer Endung aus ERLAUBTE_ENDUNGEN werden geoeffnet, UND
    nur, wenn die Datei nicht ausfuehrbar ist. Grund (Fund der Pruefung):
    /usr/bin/open reicht sonst z.B. eine .sh-Datei an ihren Standard-Handler
    weiter - der sie unter macOS AUSFUEHRT statt nur anzuzeigen. Ordner
    duerfen weiterhin uneingeschraenkt geoeffnet werden (nur ein Finder-
    Fenster, keine Ausfuehrung).
  - Nur https-URLs, keine file://, javascript:, data: oder andere Schemata;
    zusaetzlich Laengengrenze, keine Zugangsdaten im Host-Teil (kein "@") und
    ein nicht-leerer Hostname - sonst waere "oeffnen" ein stiller Weg, um
    Text (z.B. aus einer manipulierten Mail) als Abfrageparameter an eine
    fremde Adresse zu schicken (zweiter Fund der Pruefung).
  - Jeder Aufruf wird ueber den Rueckgabewert protokolliert (Programm, Ziel,
    Herkunft) - das Schreiben ins Protokoll macht der Aufrufer (server.py),
    damit dieses Modul frei von Seiteneffekten ausser dem eigentlichen Oeffnen
    bleibt und einzeln testbar ist.

Stand 18.09.2026 - nach ZURUECKWEISUNG der ersten Fassung nachgebessert.
"""
import os
import subprocess
import urllib.parse
from pathlib import Path

import jack_erweiterungen

ZEITLIMIT_S = 8
URL_MAX = 300
QUERY_MAX = 80
PFAD_MAX = 120
FRAGMENT_MAX = 0
HOST_MAX = 60

# Feste Liste: Name, wie ihn Stufe 0/Modell benutzen -> /usr/bin/open -a <App>.
# Nur bereits auf dem Mac vorhandene Standard-Apps; keine freie Eingabe.
APPS = {
    "kalender": "Calendar", "calendar": "Calendar",
    "erinnerungen": "Reminders", "reminders": "Reminders",
    "kontakte": "Contacts", "contacts": "Contacts",
    "finder": "Finder",
    "notizen": "Notes", "notes": "Notes",
    "vorschau": "Preview", "preview": "Preview",
    "obsidian": "Obsidian",
    "mail": "Mail",
    "browser": "Safari", "safari": "Safari",
}

KARTEN_WOERTER = ("karten", "maps", "landkarte", "route", "navigation")

# Datei-Endungen, die JACK ohne Rueckfrage anzeigen darf - reine Anzeige-/
# Dokumentformate, kein Skript, kein Programm, kein Installationspaket.
# .svg bewusst NICHT dabei - kann im Browser Skript ausfuehren/nachladen.
ERLAUBTE_ENDUNGEN = {
    ".md", ".markdown", ".txt", ".pdf", ".csv", ".json", ".jsonl",
    ".png", ".jpg", ".jpeg", ".gif", ".heic", ".webp",
    ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".rtf",
}

# Unter macOS sind Programmbuendel VERZEICHNISSE (is_dir() == True), keine
# Dateien - ein Ordner-Ziel mit einer dieser Endungen ist trotzdem ein
# ausfuehrbares/aktives Objekt und wird wie eine ausfuehrbare Datei behandelt.
# Fund der zweiten Sicherheitspruefung vom 18.09.2026.
BUENDEL_ENDUNGEN = {".app", ".workflow", ".pkg", ".mpkg", ".scpt", ".scptd",
                    ".rtfd", ".download", ".prefpane", ".qlgenerator", ".plugin",
                    ".bundle", ".kext", ".command"}


class AussenwaltFehler(ValueError):
    pass


def _open(argv):
    """Ein einziger, enger Aufrufpunkt fuer /usr/bin/open - argv, nie Text."""
    try:
        ergebnis = subprocess.run(["/usr/bin/open"] + list(argv),
                                  capture_output=True, text=True, timeout=ZEITLIMIT_S)
    except (OSError, subprocess.SubprocessError) as fehler:
        raise AussenwaltFehler(str(fehler)[:200])
    if ergebnis.returncode != 0:
        raise AussenwaltFehler((ergebnis.stderr or "open ist fehlgeschlagen").strip()[:200])


def _https_pruefen(url):
    url = str(url or "").strip()
    if not url or len(url) > URL_MAX:
        raise AussenwaltFehler("Adresse fehlt oder ist zu lang (Grenze %d Zeichen)." % URL_MAX)
    teile = urllib.parse.urlsplit(url)
    if teile.scheme.lower() != "https":
        raise AussenwaltFehler("Nur https-Adressen werden geöffnet.")
    if not teile.hostname:
        raise AussenwaltFehler("Adresse ohne gültigen Hostnamen.")
    if teile.username or teile.password or "@" in (teile.netloc or ""):
        raise AussenwaltFehler("Adressen mit Zugangsdaten werden nicht geöffnet.")
    # Zweite Sicherheitspruefung (18.09.2026): eine Laengengrenze allein auf
    # dem Query-String liess Pfad, Fragment und Hostname als stillen
    # Ausleitungskanal offen (bis zu ~250 Zeichen). Jetzt sind alle drei
    # Teile einzeln begrenzt.
    if (len(teile.query) > QUERY_MAX or len(teile.path) > PFAD_MAX
            or len(teile.fragment) > FRAGMENT_MAX or len(teile.hostname) > HOST_MAX):
        raise AussenwaltFehler("Diese Adresse ist zu lang oder zu verschachtelt - "
                               "nur kurze, wörtlich vom Patron genannte Adressen.")
    return url


def oeffnen(vault, ziel, parameter=None):
    """Gibt (beschreibung, protokoll_details) zurueck oder wirft AussenwaltFehler.

    vault: die Holding-Wurzel (GOTT WALD HOLDING), NICHT der JACK-Ordner -
           Dateiziele werden dagegen geprueft.
    ziel:  ein Wort aus einer festen Kategorie - Appname, 'karten', 'browser',
           'ordner'/'datei'. Kein freier Programmname.
    """
    parameter = dict(parameter or {})
    ziel_norm = str(ziel or "").strip().lower()

    # 1) Karten mit Adresse - Apple Maps ueber eine reine Such-URL, kein
    #    Aufruf der Karten-App mit einem Dateiobjekt. Ohne Adresse (Block 25b,
    #    Teil E1) oeffnet nur die App, damit Stufe 0 nach dem Ziel fragen kann,
    #    statt lokal zu raten oder abzulehnen.
    if ziel_norm in KARTEN_WOERTER:
        adresse = str(parameter.get("adresse") or parameter.get("ort") or "").strip()
        if not adresse:
            _open(["-a", "Maps"])
            return "Karten geöffnet.", {"programm": "Karten", "ziel": ""}
        if len(adresse) > 200:
            raise AussenwaltFehler("Diese Adresse ist zu lang.")
        url = "https://maps.apple.com/?q=" + urllib.parse.quote(adresse)
        _open([url])
        return "Karten geöffnet: " + adresse, {"programm": "Karten", "ziel": adresse}

    # 2) https-Adresse (Browser). Nur das Schema https, gepruefter Host,
    #    keine Zugangsdaten, kurze Abfrageparameter (siehe _https_pruefen).
    if ziel_norm in ("seite", "webseite", "url") or (ziel_norm in APPS and APPS[ziel_norm] == "Safari"):
        url = _https_pruefen(parameter.get("url"))
        _open([url])
        return "Seite geöffnet: " + url, {"programm": "Browser", "ziel": url}

    # 3) Feste App-Liste.
    if ziel_norm in APPS:
        app = APPS[ziel_norm]
        obsidian_notiz = parameter.get("notiz") if ziel_norm == "obsidian" else None
        if obsidian_notiz:
            # obsidian://open?vault=...&file=... ist eine reine URL (kein
            # Programmaufruf mit Text) - trotzdem ueber /usr/bin/open, argv.
            notiz = str(obsidian_notiz).strip()
            if not notiz or len(notiz) > 200 or "\x00" in notiz or ".." in notiz or "/" in notiz:
                raise AussenwaltFehler("Ungültiger Notizname.")
            url = "obsidian://open?vault=" + urllib.parse.quote(vault_name(vault)) \
                  + "&file=" + urllib.parse.quote(notiz)
            _open([url])
            return "Obsidian geöffnet bei: " + notiz, {"programm": "Obsidian", "ziel": notiz}
        _open(["-a", app])
        return app + " geöffnet.", {"programm": app, "ziel": ""}

    # 4) Datei oder Ordner innerhalb der Holding. Ordner sind ungefaehrlich
    #    (nur ein Finder-Fenster); Dateien nur mit erlaubter Endung UND nicht
    #    ausfuehrbar - sonst reicht open sie an ihren Standardhandler weiter,
    #    der ein Skript unter macOS AUSFUEHRT statt nur anzuzeigen.
    pfad_rel = str(parameter.get("pfad") or "").strip()
    if ziel_norm in ("ordner", "datei", "finder") or pfad_rel:
        if not pfad_rel:
            raise AussenwaltFehler("Kein Pfad angegeben.")
        try:
            ziel_pfad = jack_erweiterungen.path(vault, pfad_rel)
        except ValueError:
            raise AussenwaltFehler("Dieser Pfad liegt außerhalb der Holding oder ist ungültig.")
        try:
            existiert = ziel_pfad.exists()
            ist_ordner = existiert and ziel_pfad.is_dir()
            ist_datei = existiert and ziel_pfad.is_file()
            ausfuehrbar = ist_datei and os.access(ziel_pfad, os.X_OK)
        except OSError:
            raise AussenwaltFehler("Nicht lesbar: " + pfad_rel)
        if not existiert:
            raise AussenwaltFehler("Nicht gefunden: " + pfad_rel)
        # Zweite Sicherheitspruefung (18.09.2026): .app/.workflow/.pkg/... sind
        # unter macOS VERZEICHNISSE - ohne diese Prüfung wären sie als "Ordner"
        # durchgerutscht, obwohl open sie startet/ausfuehrt.
        if ziel_pfad.suffix.lower() in BUENDEL_ENDUNGEN:
            raise AussenwaltFehler("Programmbündel wird nicht geöffnet: " + pfad_rel)
        if ist_datei:
            if ausfuehrbar:
                raise AussenwaltFehler("Ausführbare Datei wird nicht geöffnet: " + pfad_rel)
            if ziel_pfad.suffix.lower() not in ERLAUBTE_ENDUNGEN:
                raise AussenwaltFehler("Dieser Dateityp wird nicht geöffnet: " + pfad_rel)
        elif not ist_ordner:
            raise AussenwaltFehler("Weder Datei noch Ordner: " + pfad_rel)
        _open([str(ziel_pfad)])
        return "Geöffnet: " + pfad_rel, {"programm": "Finder/Standardprogramm", "ziel": pfad_rel}

    raise AussenwaltFehler("Unbekanntes oder nicht erlaubtes Ziel: " + str(ziel))


def vault_name(vault):
    return Path(vault).name
