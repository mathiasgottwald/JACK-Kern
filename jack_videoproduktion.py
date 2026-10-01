"""Zentrale, markengetrennte Vorbereitung von Videoauftraegen.

Dieses Modul erzeugt Briefing und Produktionsakte ausschliesslich lokal.
Es ruft keinen Medienanbieter auf, laedt nichts hoch und veroeffentlicht nichts.
"""
import datetime as dt
import json
import os
from pathlib import Path
import re
import uuid

import jack_medien

KONFIGURATION = Path("betrieb/videoproduktion.json")
AUFTRAGSORDNER = "JACK_Videoproduktion"
MAX_BRIEF = 20_000

# --- Videobetrieb Teil 2 (P04/P05): Quellenanbindung und die vier kreativen
# Verfahren 7.1/8.1/9.1/11.1. Kein zweites Auswertungssystem: diese Funktionen
# lesen ausschliesslich die bestehende Sammeldatei aus Auftrag 16.1 und,
# falls vorhanden, die Wochenberichte aus Auftrag 29.1 - beide Auftraege
# bleiben eigenstaendig und werden hier nicht nachgebaut.
VIDEOAUSWERTUNG_PFAD = "02_Dokumente/2026-09-16_Videoauswertung.md"
MUSTERFELDER_ERLAUBT = frozenset({"thema", "hook", "aufbau", "laenge_sekunden", "rhythmus", "tonfall"})
_VIDEO_HEADING = re.compile(r"^## Video (\d+)(?:\.\d+)?\s*[–-]\s*(.+)$", re.MULTILINE)
_KENNZAHL_WOERTER = re.compile(
    r"(\d[\d.,]*)\s*(Likes?|Aufrufe|Views?|Speicherungen|Teilungen|Kommentare|Abonnent\w*|Follower\w*)",
    re.IGNORECASE)
_TREND_WOERTER = re.compile(
    r"(Google\s*Trends?|Suchtrend\w*|Trend[üu]berwachung|Nachrichtenlage|Trend-\w+)", re.IGNORECASE)


def _laden(root):
    root = Path(root).absolute()
    pfad = root / KONFIGURATION
    if pfad.is_symlink() or not pfad.is_file() or pfad.stat().st_size > 200_000:
        raise ValueError("Konfiguration der Videoproduktion fehlt")
    try:
        daten = json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, ValueError) as fehler:
        raise ValueError("Konfiguration der Videoproduktion ist ungueltig") from fehler
    if (not isinstance(daten, dict) or daten.get("schema") != 1
            or not isinstance(daten.get("marken"), dict)):
        raise ValueError("Konfiguration der Videoproduktion ist ungueltig")
    return daten


def _text(wert, feld, maximum, mehrzeilig=False):
    if not isinstance(wert, str):
        raise ValueError(f"{feld} fehlt")
    wert = wert.strip()
    if not wert or len(wert) > maximum:
        raise ValueError(f"{feld} fehlt oder ist zu lang")
    if "\x00" in wert or any(ord(zeichen) < 32 and zeichen not in "\n\t" for zeichen in wert):
        raise ValueError(f"{feld} enthaelt ungueltige Zeichen")
    if not mehrzeilig and ("\n" in wert or "\r" in wert):
        raise ValueError(f"{feld} muss in einer Zeile stehen")
    return wert


def _marke(konfiguration, roh):
    roh = _text(roh, "Marke", 80)
    treffer = [name for name in konfiguration["marken"] if name.casefold() == roh.casefold()]
    if len(treffer) != 1:
        raise ValueError("Unbekannte Marke fuer die Videoproduktion")
    return treffer[0]


def _medienordner(root, konfiguration, marke):
    root = Path(root).absolute()
    vault = root.parent.parent
    eintrag = konfiguration["marken"][marke]
    ordnername = eintrag.get("ordner") if isinstance(eintrag, dict) else None
    if (not isinstance(ordnername, str) or not ordnername
            or Path(ordnername).name != ordnername or ordnername in (".", "..")):
        raise ValueError("Ungueltiges Markenziel in der Videokonfiguration")
    markenordner = vault / "00_Marken" / ordnername
    medien = markenordner / "06_Medien"
    if (markenordner.is_symlink() or medien.is_symlink() or not medien.is_dir()
            or medien.parent != markenordner):
        raise ValueError("Medienablage der Marke fehlt oder ist nicht sicher")
    return vault, medien


def verfahren(root, produktionstyp=None):
    """Empfiehlt einen vorhandenen Produktionsweg, ohne ihn zu starten."""
    konfiguration = _laden(root)
    roh = produktionstyp if produktionstyp is not None else "auto"
    typ = _text(roh, "Produktionstyp", 80)
    verfahren = konfiguration.get("verfahren")
    if not isinstance(verfahren, dict) or typ not in verfahren:
        raise ValueError("Unbekannter Produktionstyp")
    eintrag = verfahren[typ]
    if not isinstance(eintrag, dict):
        raise ValueError("Produktionsweg ist ungueltig")
    felder = ("empfehlung", "status", "kosten", "begruendung", "freigabe")
    if any(not isinstance(eintrag.get(feld), str) or not eintrag[feld] for feld in felder):
        raise ValueError("Produktionsweg ist unvollstaendig")
    return {
        "produktionstyp": typ,
        "empfehlung": eintrag["empfehlung"],
        "alternative": eintrag.get("alternative"),
        "status": eintrag["status"],
        "kosten": eintrag["kosten"],
        "begruendung": eintrag["begruendung"],
        "freigabe_noetig": eintrag["freigabe"],
        "aussenwirkung": False,
        "hinweis": "Auswahlhilfe ohne Anbieteraufruf, Upload, Kosten oder Veroeffentlichung."
    }


def _schreiben(pfad, inhalt):
    with pfad.open("x", encoding="utf-8") as datei:
        datei.write(inhalt)
        datei.flush()
        os.fsync(datei.fileno())


def vorbereiten(root, marke, titel, ziel, format, brief, produktionstyp="auto"):
    """Legt einen neuen lokalen Auftrag an, ohne eine Aussenwirkung auszulösen."""
    konfiguration = _laden(root)
    marke = _marke(konfiguration, marke)
    titel = _text(titel, "Titel", 180)
    brief = _text(brief, "Briefing", MAX_BRIEF, mehrzeilig=True)
    ziel = _text(ziel, "Ziel", 40)
    format = _text(format, "Format", 40)
    if ziel not in konfiguration.get("ziele", {}):
        raise ValueError("Unbekanntes Videoziel")
    if format not in konfiguration.get("formate", {}):
        raise ValueError("Unbekanntes Videoformat")
    weg = verfahren(root, produktionstyp)

    vault, medien = _medienordner(root, konfiguration, marke)
    basis = medien / AUFTRAGSORDNER
    if basis.exists() and (basis.is_symlink() or not basis.is_dir()):
        raise ValueError("Produktionsablage ist nicht sicher")
    basis.mkdir(mode=0o700, exist_ok=True)
    kennung = "VP-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]
    auftrag = basis / kennung
    auftrag.mkdir(mode=0o700)
    jetzt = dt.datetime.now().astimezone().isoformat()
    daten = {
        "schema": 1,
        "kennung": kennung,
        "erstellt": jetzt,
        "marke": marke,
        "markenordner": konfiguration["marken"][marke]["ordner"],
        "verantwortlich": konfiguration["marken"][marke]["ceo"],
        "steuerung": "JACK",
        "titel": titel,
        "ziel": ziel,
        "format": format,
        "produktionstyp": weg["produktionstyp"],
        "verfahren_empfehlung": weg,
        "brief": brief,
        "status": "briefing",
        "anbieter": None,
        "erzeugtes_video": None,
        "technische_pruefung": None,
        "kreative_pruefung": "offen",
        "patron_freigabe": "offen",
        "veroeffentlichung": None,
        "aussenwirkung": False,
        "kosten_gemeldet": None,
        "tore": {"tor1": None, "tor2": None},
        "hinweis": "Lokaler Produktionsauftrag. Noch kein Video erzeugt, hochgeladen oder veroeffentlicht."
    }
    _schreiben(auftrag / "auftrag.json", json.dumps(daten, ensure_ascii=False, indent=2) + "\n")
    beschreibung = (
        f"# {titel}\n\n"
        f"**Auftrag:** {kennung}  \n"
        f"**Marke:** {marke}  \n"
        f"**Verantwortlich:** {daten['verantwortlich']}  \n"
        f"**Ziel:** {konfiguration['ziele'][ziel]}  \n"
        f"**Format:** {konfiguration['formate'][format]}  \n"
        f"**Produktionsart:** {weg['produktionstyp']}  \n"
        f"**Empfohlener Weg:** {weg['empfehlung']}  \n"
        f"**Status:** Briefing  \n\n"
        "## Briefing\n\n" + brief + "\n\n"
        "## Verbindlicher Produktionsweg\n\n"
        "1. Markenführung prüft Ziel, Botschaft und Zielgruppe.\n"
        "2. Inhalt erstellt Skript und Szenenfolge.\n"
        "3. Produktion erzeugt die Medien erst über einen freigegebenen Adapter.\n"
        "4. Technische und kreative Prüfung erfolgen am tatsächlichen Export.\n"
        "5. JACK legt dem Patron die geprüfte Endfassung zur Freigabe vor.\n"
        "6. Veröffentlichung erfolgt erst nach dieser Freigabe und mit Sichtkontrolle.\n\n"
        "> Aktueller Stand: nur lokal vorbereitet. Kein Anbieteraufruf, kein Upload, keine Veröffentlichung.\n\n"
        "## Verfahrensentscheidung\n\n"
        f"**Status:** {weg['status']}  \n"
        f"**Kosten:** {weg['kosten']}  \n"
        f"**Warum:** {weg['begruendung']}  \n"
        f"**Vorher nötig:** {weg['freigabe_noetig']}\n"
    )
    _schreiben(auftrag / "BRIEFING.md", beschreibung)
    relativ = auftrag.relative_to(vault)
    return {
        "kennung": kennung,
        "marke": marke,
        "verantwortlich": daten["verantwortlich"],
        "status": "briefing",
        "produktionstyp": weg["produktionstyp"],
        "empfohlener_weg": weg["empfehlung"],
        "ablage": str(relativ),
        "aussenwirkung": False,
        "kosten_usd": 0,
        "hinweis": daten["hinweis"]
    }


def stand(root, marke=None):
    """Liest lokale Produktionsakten. Verändert keine Datei."""
    konfiguration = _laden(root)
    marken = [_marke(konfiguration, marke)] if marke is not None else list(konfiguration["marken"])
    ergebnisse = []
    for name in marken:
        try:
            vault, medien = _medienordner(root, konfiguration, name)
        except ValueError:
            continue
        basis = medien / AUFTRAGSORDNER
        if not basis.is_dir() or basis.is_symlink():
            continue
        for pfad in sorted(basis.glob("VP-*/auftrag.json"), reverse=True)[:100]:
            try:
                if pfad.is_symlink() or pfad.stat().st_size > 100_000:
                    continue
                daten = json.loads(pfad.read_text(encoding="utf-8"))
                if (not isinstance(daten, dict) or daten.get("schema") != 1
                        or daten.get("marke") != name):
                    continue
                ergebnisse.append({
                    "kennung": daten.get("kennung"),
                    "marke": name,
                    "titel": daten.get("titel"),
                    "produktionstyp": daten.get("produktionstyp", "auto"),
                    "empfohlener_weg": (daten.get("verfahren_empfehlung") or {}).get("empfehlung"),
                    "status": daten.get("status"),
                    "erstellt": daten.get("erstellt"),
                    "verantwortlich": daten.get("verantwortlich"),
                    "ablage": str(pfad.parent.relative_to(vault)),
                    "patron_freigabe": daten.get("patron_freigabe"),
                    "veroeffentlichung": daten.get("veroeffentlichung")
                })
            except (OSError, ValueError):
                continue
    ergebnisse.sort(key=lambda x: str(x.get("erstellt") or ""), reverse=True)
    return {
        "dienst": konfiguration.get("dienst"),
        "pilot": konfiguration.get("pilot"),
        "anbieter_angeschlossen": bool(konfiguration.get("anbieter_adapter")),
        "verfahren": {name: verfahren(root, name) for name in konfiguration.get("verfahren", {})},
        "automatische_veroeffentlichung": False,
        "auftraege": ergebnisse[:100],
        "hinweis": "Produktionsakten sind keine erzeugten oder veroeffentlichten Videos."
    }


def _vault(root):
    return Path(root).absolute().parent.parent


def _sichere_vaultdatei(root, relativ, max_bytes=3_000_000):
    vault = _vault(root)
    p = Path(relativ)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError("Ungueltiger Dateipfad")
    ziel = vault / p
    kette = [ziel] + [eltern for eltern in ziel.parents if eltern == vault or vault in eltern.parents]
    if any(teil.is_symlink() for teil in kette if teil != vault):
        raise ValueError("Pfad darf keinen Verweis enthalten")
    if not ziel.is_file() or ziel.stat().st_size > max_bytes:
        raise ValueError(f"Datei fehlt oder ist groesser als erlaubt: {relativ}")
    return ziel.read_text(encoding="utf-8")


def _kennzahl_klassifizieren(text):
    """Trennt gemessene Video-Kennzahlen (Plattform-Engagement mit Zahl) technisch
    von Trend-/Nachrichten-Hinweisen (P04 Punkt 2). Beide Listen bleiben getrennt;
    keine Funktion in diesem Modul darf sie zusammenfuehren."""
    gemessen = [f"{zahl.strip()} {einheit.strip()}" for zahl, einheit in _KENNZAHL_WOERTER.findall(text)]
    trend = sorted(set(t.strip() for t in _TREND_WOERTER.findall(text)))
    return {"gemessene_kennzahl": gemessen[:20], "trend_hinweis": trend[:20]}


def videoauswertung_bloecke(root, video_nummern=None):
    """Zulieferfunktion (P04.1): liest die bestehende Videoauswertung aus
    Auftrag 16.1 als Quelle fuer Hook/Aufbau/Rhythmus/Laenge/Tonfall. Baut kein
    zweites Auswertungssystem - docked an genau die eine Sammeldatei an."""
    text = _sichere_vaultdatei(root, VIDEOAUSWERTUNG_PFAD)
    treffer = list(_VIDEO_HEADING.finditer(text))
    bloecke = {}
    for i, m in enumerate(treffer):
        nummer = int(m.group(1))
        if video_nummern is not None and nummer not in video_nummern:
            continue
        ende = treffer[i + 1].start() if i + 1 < len(treffer) else len(text)
        inhalt = text[m.start():ende]
        quelle_m = re.search(r"^-\s*\*\*Quelle:\*\*\s*(.+)$", inhalt, re.MULTILINE)
        marke_m = re.search(r"^-\s*\*\*Marke:\*\*\s*(.+)$", inhalt, re.MULTILINE)
        kernaussage_m = re.search(r"^-\s*\*\*Kernaussage:\*\*\s*(.+)$", inhalt, re.MULTILINE)
        empfehlung_m = re.search(r"^-\s*\*\*Empfehlung:\*\*\s*(.+)$", inhalt, re.MULTILINE)
        kennzahlen = _kennzahl_klassifizieren(inhalt)
        bloecke[nummer] = {
            "video_nummer": nummer,
            "titel": m.group(2).strip(),
            "fundstelle_quelle": quelle_m.group(1).strip() if quelle_m else None,
            "marke": marke_m.group(1).strip() if marke_m else None,
            "kernaussage": kernaussage_m.group(1).strip() if kernaussage_m else None,
            "empfehlung": empfehlung_m.group(1).strip() if empfehlung_m else None,
            "gemessene_kennzahl": kennzahlen["gemessene_kennzahl"],
            "trend_hinweis": kennzahlen["trend_hinweis"],
            "vorlage_rohtext_fuer_musterableitung": inhalt.strip()[:4000],
            "quelle_datei": VIDEOAUSWERTUNG_PFAD
        }
    if video_nummern is not None:
        fehlend = set(video_nummern) - set(bloecke)
        if fehlend:
            raise ValueError(f"Video-Eintraege nicht gefunden: {sorted(fehlend)}")
    return bloecke


def radar_lesen(root, marke, kalenderwoche=None):
    """Zulieferfunktion (P04.1): liest, falls vorhanden, den Wochenbericht des
    Markt-/Wettbewerbs-Radars aus Auftrag 29.1
    (00_Marken/<MARKE>/05_Marketing/radar/<JJJJ-KWnn>_radar.md). 29.1 ist
    eigenstaendig und NICHT Teil dieses Auftrags - diese Funktion baut keinen
    zweiten Radar, sie liest nur, was 29.1 nach eigener Freigabe ablegt, und
    meldet ehrlich, wenn noch nichts vorliegt, statt etwas zu erfinden."""
    konfiguration = _laden(root)
    marke = _marke(konfiguration, marke)
    vault = _vault(root)
    ordner = vault / "00_Marken" / konfiguration["marken"][marke]["ordner"] / "05_Marketing" / "radar"
    if ordner.is_symlink() or not ordner.is_dir():
        return {"vorhanden": False, "marke": marke,
                "hinweis": "Auftrag 29.1 (Markt-/Wettbewerbs-Radar) hat fuer diese Marke noch keinen "
                           "Wochenbericht abgelegt; nichts wird hier ersatzweise erzeugt."}
    if kalenderwoche is not None:
        if not isinstance(kalenderwoche, str) or not re.fullmatch(r"\d{4}-KW\d{2}", kalenderwoche):
            raise ValueError("Kalenderwoche muss dem Format JJJJ-KWnn entsprechen")
        kandidaten = [ordner / f"{kalenderwoche}_radar.md"]
    else:
        kandidaten = sorted((p for p in ordner.glob("*_radar.md") if not p.is_symlink()), reverse=True)[:1]
    for pfad in kandidaten:
        if not pfad.is_file() or pfad.is_symlink() or pfad.stat().st_size > 500_000:
            continue
        return {"vorhanden": True, "marke": marke, "datei": str(pfad.relative_to(vault)),
                "inhalt": pfad.read_text(encoding="utf-8")[:20_000],
                "hinweis": "Aus 29.1 uebernommen; enthaelt laut dessen Regeln kein Fremdmaterial, "
                           "nur Beschreibung und Link."}
    return {"vorhanden": False, "marke": marke, "hinweis": "Kein lesbarer Wochenbericht des Radars gefunden."}


def musterentscheidung(vorbild, uebernahme):
    """Erzwingt die Musterregel aus 7.1 im Code (P04.3): aus einem Vorbild
    (Video-Eintrag aus 16.1 oder Fund aus 29.1) darf NUR das Muster uebernommen
    werden - Thema, Hook, Aufbau, Laenge, Rhythmus, Tonfall. Jedes andere Feld
    (Bildmaterial, Ton, Musik, Stimme, Text, Schnittfolge, Personen) wird hier
    technisch abgelehnt, nicht nur per Dokumentation untersagt."""
    if not isinstance(vorbild, dict) or not (vorbild.get("fundstelle_quelle") or vorbild.get("datei")):
        raise ValueError("Vorbild ohne belegte Fundstelle darf nicht als Muster dienen")
    if not isinstance(uebernahme, dict) or not uebernahme:
        raise ValueError("Musteruebernahme fehlt")
    unbekannt = set(uebernahme) - MUSTERFELDER_ERLAUBT
    if unbekannt:
        raise ValueError("Nur das Muster darf uebernommen werden, kein Originalmaterial: "
                         f"unzulaessige Felder {sorted(unbekannt)}")
    return {
        "schema": 1, "art": "jack_musterentscheidung",
        "quelle": vorbild.get("fundstelle_quelle") or vorbild.get("datei"),
        "muster": {feld: uebernahme[feld] for feld in MUSTERFELDER_ERLAUBT if feld in uebernahme},
        "original_material_uebernommen": False,
        "hinweis": "Nur Muster (Thema/Hook/Aufbau/Laenge/Rhythmus/Tonfall) uebernommen; kein Bild-, "
                   "Ton-, Musik-, Stimm-, Text- oder Personenmaterial des Vorbilds."
    }


def _eigenes_material(root, konfiguration, marke, raw):
    """Belegt technisch, dass ein Ausgangsmaterial aus der eigenen Medienablage
    der Marke stammt - kein Download, kein Scraper, keine Internetadresse."""
    if not isinstance(raw, str) or not raw or len(raw) > 1500 or "://" in raw:
        raise ValueError("Ausgangsmaterial muss ein lokaler Pfad ohne Internetadresse sein")
    if any(ord(c) < 32 for c in raw):
        raise ValueError("Ausgangsmaterial enthaelt ungueltige Zeichen")
    _, medien = _medienordner(root, konfiguration, marke)
    p = Path(raw)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError("Ausgangsmaterial muss relativ zur Holding liegen")
    ziel = _vault(root) / p
    kette = [ziel] + [eltern for eltern in ziel.parents if eltern == medien or medien in eltern.parents]
    if any(teil.is_symlink() for teil in kette if teil.exists()):
        raise ValueError("Ausgangsmaterial darf keinen Verweis enthalten")
    ziel = ziel.resolve()
    if medien.resolve() not in ziel.parents or not ziel.is_file():
        raise ValueError("Ausgangsmaterial muss aus der eigenen Medienablage dieser Marke stammen (06_Medien)")
    return ziel


def _stufenfreigabe_pruefen(konfiguration, verfahren_key, stufe):
    """Stufenwaechter (P05.1): Entwurf ist immer erlaubt. Die Endfassungsstufe
    schaltet nur der woertliche Konfigurationswert 'ausloesen' frei - in diesem
    Auftrag steht dort nirgends dieser Wert (siehe videoproduktion.json,
    Feld stufenfreigabe), also bleibt die Endfassungsstufe technisch gesperrt."""
    if stufe not in ("entwurf", "endfassung"):
        raise ValueError("Produktionsstufe muss 'entwurf' oder 'endfassung' sein")
    if stufe == "entwurf":
        return
    wert = (konfiguration.get("stufenfreigabe") or {}).get(verfahren_key)
    if wert != "ausloesen":
        raise ValueError(f"Endfassung fuer '{verfahren_key}' gesperrt: Stufenfreigabe steht auf "
                         f"{wert!r}, nicht auf 'ausloesen'. Kein Stufenwechsel ohne ausdrueckliche Freigabe.")


ZEICHNER_MIT_REFERENZBILD = "kling_v3_pro_bild"
ZEICHNER_OHNE_REFERENZBILD = "seedance_2_text"


def zeichner_waehlen(figurenblatt_pfad):
    """Einzige Stelle der Higgsfield-Modellwahl fuer die Verfahren: mit
    Figurenblatt das Bild-Modell, ohne das guenstigere Text-Modell. Ein
    uebergebenes, aber fehlendes oder ungueltiges Figurenblatt faellt NICHT
    still auf Text-zu-Video zurueck - es scheitert an der Materialpruefung."""
    if figurenblatt_pfad is None:
        return ZEICHNER_OHNE_REFERENZBILD
    return ZEICHNER_MIT_REFERENZBILD


def _sicherer_stopp(root, kennung, prompt, modell, dauer=5, referenzbild=None):
    """Fuehrt den echten Dry-Run-Weg (jack_higgsfield.wuerde_starten) aus, der
    bis unmittelbar vor den Netzwerkaufruf alle echten Pruefungen durchlaeuft
    und dort stoppt. Ist das angefragte Modell (noch) nicht konfiguriert,
    faengt diese Funktion den entstehenden, echten ValueError ab und liefert
    einen ebenso klaren, aber freundlichen Stopp-Nachweis - in jedem Fall wird
    kein Anbieter kontaktiert."""
    import jack_higgsfield
    try:
        ergebnis = jack_higgsfield.wuerde_starten(root, kennung, prompt, modell=modell, dauer=dauer,
                                                  referenzbild=referenzbild)
        return {"versuchtes_modell": modell, **ergebnis}
    except ValueError as fehler:
        return {"versuchtes_modell": modell, "gestoppt_vor_aufruf": True, "wuerde_aufrufen": None,
                "hinweis": f"Kein Anbieteraufruf: {fehler}"}


def verfahren_7_1_video_zu_video(root, kennung, clips, figurenblatt_pfad, ortsbild_pfad,
                                  handlung, aussage, ortsbild_beschreibung, vorbild=None,
                                  muster_uebernahme=None, cleanup_befunde=None, stufe="entwurf",
                                  dauer=5):
    """Auftrag 7.1 - Video-zu-Video-Werbeclip: eigene Aufnahme + Figuren-/Orts-
    referenz + Handlung + gewuenschte Aussage. Prueft alles lokal (15-Sekunden-
    Grenze je Ausgangsclip, eigenes Material, optional Musterregel und
    Cleanup-Pflichtpruefung), danach ausschliesslich ein Dry-Run - kein echter
    Anbieteraufruf in diesem Auftrag.

    ortsbild_beschreibung (Videobetrieb Teil 9, P08-Weg 1): das Ortsbild wirkt
    sich am eingesetzten Bild-zu-Video-Modell (siehe Teil 8) nicht als zweites
    Referenzbild aus - stattdessen fliesst hier eine Pflicht-Freitext-
    beschreibung der Umgebung tatsaechlich in den Prompt ein. ortsbild_pfad
    bleibt daneben wie bisher die lokale Beleg-/QA-Pruefung des Bildes."""
    konfiguration = _laden(root)
    import jack_higgsfield
    auftragsdaten = jack_higgsfield._lesen(jack_higgsfield._auftragspfad(root, kennung))
    marke = auftragsdaten["marke"]
    if not isinstance(clips, list) or not 1 <= len(clips) <= 20:
        raise ValueError("1 bis 20 Ausgangsclips (je hoechstens 15 Sekunden) erforderlich")
    geprueft_clips = []
    for eintrag in clips:
        if not isinstance(eintrag, dict) or not isinstance(eintrag.get("pfad"), str):
            raise ValueError("Jeder Clip braucht einen Pfad")
        ziel = _eigenes_material(root, konfiguration, marke, eintrag["pfad"])
        relativ = str(ziel.relative_to(_vault(root)))
        pruefung = jack_medien.pruefen(root, relativ, max_dauer_sekunden=15.0, ton_noetig=False)
        if not pruefung["technik_bestanden"]:
            raise ValueError(f"Ausgangsclip {relativ} nicht technisch bestanden (u. a. 15-Sekunden-Grenze)")
        geprueft_clips.append({"pfad": relativ, "nachweis": pruefung["nachweis"]})
    figurenblatt = _figurenblatt(root, konfiguration, marke, figurenblatt_pfad)
    ortsbild = str(_eigenes_material(root, konfiguration, marke, ortsbild_pfad).relative_to(_vault(root)))
    handlung = _text(handlung, "Handlung", 2000, mehrzeilig=True)
    aussage = _text(aussage, "Gewuenschte Aussage", 1000, mehrzeilig=True)
    ortsbild_beschreibung = _text(ortsbild_beschreibung, "Ortsbild-Beschreibung", 500, mehrzeilig=True)
    muster = musterentscheidung(vorbild, muster_uebernahme) if vorbild is not None else None
    cleanup = jack_medien.cleanup_pruefliste(cleanup_befunde) if cleanup_befunde is not None else None
    _stufenfreigabe_pruefen(konfiguration, "video_zu_video", stufe)
    prompt = ("Video-zu-Video-Anweisung: gleiche Handlung, bildgenau; nur Umgebung/"
              "Figuren nach Referenz aendern. Keine Schrift, keine Buchstaben, keine Zahlen, "
              "kein Logo, keine Untertitel im erzeugten Bild oder Video. "
              "Handlung: %s Aussage: %s Umgebung: %s") % (
                  handlung, aussage, ortsbild_beschreibung)
    zeichner = zeichner_waehlen(figurenblatt_pfad)
    stopp = _sicherer_stopp(root, kennung, prompt, zeichner, dauer=dauer, referenzbild=figurenblatt)
    return {
        "verfahren": "7.1_video_zu_video", "kennung": kennung, "marke": marke,
        "clips_geprueft": geprueft_clips, "figurenblatt": figurenblatt, "ortsbild": ortsbild,
        "ortsbild_beschreibung": ortsbild_beschreibung,
        "musterentscheidung": muster, "cleanup_pruefliste": cleanup, "stufe": stufe,
        "zeichner": zeichner,
        **stopp,
        "hinweis_modellgrenze": HINWEIS_ZEICHNER_7_1
    }


HINWEIS_ZEICHNER_7_1 = (
    "Zeichner-Wahl automatisch (zeichner_waehlen): mit Figurenblatt kling_v3_pro_bild "
    "(Bild-zu-Video, Figurenblatt als Referenzbild per Higgsfield-Upload), ohne Figurenblatt "
    "seedance_2_text (Text-zu-Video, guenstiger). Eigene Clips und Ortsbild werden lokal geprueft, "
    "aber von keinem der beiden Modelle an Higgsfield uebergeben - echtes Video-zu-Video ist "
    "noch nicht angebunden.")


def _figurenblatt(root, konfiguration, marke, figurenblatt_pfad):
    if figurenblatt_pfad is None:
        return None
    return str(_eigenes_material(root, konfiguration, marke, figurenblatt_pfad).relative_to(_vault(root)))


def _echtfreigabe_pruefen(konfiguration, kennung):
    """Echtfreigabe-Waechter (P06, Videobetrieb Teil 4): bindet einen ECHTEN
    Anbieteraufruf an die EXAKTE Auftragskennung, nicht an ein ganzes
    Verfahren. Anders als _stufenfreigabe_pruefen (die einen Verfahrensnamen
    global freischaltet) reicht hier niemals ein Verfahrensname und niemals
    die Freigabe eines ANDEREN Auftrags: fehlt der woertliche Wert
    'ausloesen' fuer GENAU diese VP-Kennung in echtfreigabe_je_auftrag
    (videoproduktion.json), bleibt jeder echte Aufruf gesperrt."""
    if not isinstance(kennung, str) or not kennung:
        raise ValueError("Echtfreigabe braucht eine gueltige Auftragskennung")
    zuordnung = konfiguration.get("echtfreigabe_je_auftrag")
    wert = zuordnung.get(kennung) if isinstance(zuordnung, dict) else None
    if wert != "ausloesen":
        raise ValueError(
            "Echter Anbieteraufruf fuer '%s' gesperrt: echtfreigabe_je_auftrag steht auf %r, "
            "nicht auf 'ausloesen'. Eine Freigabe fuer eine andere Kennung oder eine allgemeine "
            "Verfahrensfreigabe (stufenfreigabe) gilt hier nicht." % (kennung, wert))


def _echtfreigabe_verbrauchen(root, kennung):
    """F-8 T1 (PM-Entscheidung 24.09.2026, Punkt 2): Die Echtfreigabe ist ein Einmal-Ticket.

    Direktaufrufe von jack_runway/jack_higgsfield verbrauchen sie wie der Dienstweg
    (jack_videokette.tor): direkt nach bestandener Pruefung wird der Wert auf den Ruhewert
    'gesperrt' gesetzt und zurueckgelesen. Ein weiterer Aufruf braucht eine neue Freigabe -
    auch wenn der erste spaeter scheitert (das Ticket ist dann trotzdem verbraucht).
    Ohne Bestaetigung des Ruhewerts: laute Ausnahme, damit kein Aufruf mit offenem Ticket weiterlaeuft."""
    pfad = Path(root).absolute() / KONFIGURATION
    daten = _laden(root)
    ruhewert = (daten.get("freigabe_tor") or {}).get("ruhewert", "gesperrt")
    daten.setdefault("echtfreigabe_je_auftrag", {})[kennung] = ruhewert
    tmp = pfad.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(daten, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, pfad)
    gelesen = _laden(root).get("echtfreigabe_je_auftrag", {}).get(kennung)
    if gelesen != ruhewert:
        raise RuntimeError("Echtfreigabe konnte nicht auf '%s' gesetzt werden (gelesen: %r)" % (ruhewert, gelesen))
    return gelesen


def verfahren_7_1_video_zu_video_echt(root, kennung, clips, figurenblatt_pfad, ortsbild_pfad,
                                       handlung, aussage, ortsbild_beschreibung, vorbild=None,
                                       muster_uebernahme=None, cleanup_befunde=None, dauer=5):
    """Auftrag 7.1 (P06, Videobetrieb Teil 4) - der EINZIGE Weg zu einem
    ECHTEN Higgsfield-Aufruf in Verfahren 7.1. Von verfahren_7_1_video_zu_video
    absichtlich klar unterscheidbar - eigener Name statt eines Kippschalter-
    Parameters an der bestehenden Funktion, eigenes Ergebnisfeld
    ("7.1_video_zu_video_ECHT") - damit niemand durch einen Tippfehler oder
    einen Standardwert versehentlich echt auslöst. Kein stufe-Parameter: nur
    die Entwurfsstufe ist hier ueberhaupt erreichbar; ein Stufenwechsel zur
    Endfassung bleibt ausschliesslich ueber den bestehenden Dry-Run-Weg und
    _stufenfreigabe_pruefen moeglich.

    Ablauf:
      1. Echtfreigabe zuerst (_echtfreigabe_pruefen) - ein gesperrter Auftrag
         bezahlt nicht erst die volle lokale Pruefung (Clip-Dekodierung u. a.),
         bevor er ohnehin abgelehnt wird.
      2. Danach EXAKT dieselben lokalen Pruefungen wie im Dry-Run-Weg (Clips,
         eigenes Material, optionale Musterregel, Cleanup-Pflichtpruefung) -
         keine davon abgeschwaecht oder ausgelassen.
      3. Erst dann der tatsaechliche Aufruf ueber jack_higgsfield.starten() -
         NICHT wuerde_starten() - ohne dessen eigene Pruefungen (Zugangsformat,
         3-USD-Auftragsdeckel, Auftragsstatus) hier zu wiederholen. starten()
         selbst reserviert und loest die bestehende Budgetreservierung auf
         (jack_kosten.reservieren/reservierung_abschliessen) und schreibt das
         Ergebnis unveraendert in die Auftragsakte (auftrag.json, Felder
         erzeugtes_video/generationen)."""
    konfiguration = _laden(root)
    import jack_higgsfield
    auftragsdaten = jack_higgsfield._lesen(jack_higgsfield._auftragspfad(root, kennung))
    marke = auftragsdaten["marke"]
    _echtfreigabe_pruefen(konfiguration, kennung)
    if not isinstance(clips, list) or not 1 <= len(clips) <= 20:
        raise ValueError("1 bis 20 Ausgangsclips (je hoechstens 15 Sekunden) erforderlich")
    geprueft_clips = []
    for eintrag in clips:
        if not isinstance(eintrag, dict) or not isinstance(eintrag.get("pfad"), str):
            raise ValueError("Jeder Clip braucht einen Pfad")
        ziel = _eigenes_material(root, konfiguration, marke, eintrag["pfad"])
        relativ = str(ziel.relative_to(_vault(root)))
        pruefung = jack_medien.pruefen(root, relativ, max_dauer_sekunden=15.0, ton_noetig=False)
        if not pruefung["technik_bestanden"]:
            raise ValueError(f"Ausgangsclip {relativ} nicht technisch bestanden (u. a. 15-Sekunden-Grenze)")
        geprueft_clips.append({"pfad": relativ, "nachweis": pruefung["nachweis"]})
    figurenblatt = _figurenblatt(root, konfiguration, marke, figurenblatt_pfad)
    ortsbild = str(_eigenes_material(root, konfiguration, marke, ortsbild_pfad).relative_to(_vault(root)))
    handlung = _text(handlung, "Handlung", 2000, mehrzeilig=True)
    aussage = _text(aussage, "Gewuenschte Aussage", 1000, mehrzeilig=True)
    ortsbild_beschreibung = _text(ortsbild_beschreibung, "Ortsbild-Beschreibung", 500, mehrzeilig=True)
    muster = musterentscheidung(vorbild, muster_uebernahme) if vorbild is not None else None
    cleanup = jack_medien.cleanup_pruefliste(cleanup_befunde) if cleanup_befunde is not None else None
    prompt = ("Video-zu-Video-Anweisung: gleiche Handlung, bildgenau; nur Umgebung/"
              "Figuren nach Referenz aendern. Keine Schrift, keine Buchstaben, keine Zahlen, "
              "kein Logo, keine Untertitel im erzeugten Bild oder Video. "
              "Handlung: %s Aussage: %s Umgebung: %s") % (
                  handlung, aussage, ortsbild_beschreibung)
    zeichner = zeichner_waehlen(figurenblatt_pfad)
    ergebnis = jack_higgsfield.starten(root, kennung, prompt, modell=zeichner, dauer=dauer,
                                       referenzbild=figurenblatt)
    return {
        "verfahren": "7.1_video_zu_video_ECHT", "kennung": kennung, "marke": marke,
        "clips_geprueft": geprueft_clips, "figurenblatt": figurenblatt, "ortsbild": ortsbild,
        "ortsbild_beschreibung": ortsbild_beschreibung,
        "musterentscheidung": muster, "cleanup_pruefliste": cleanup, "stufe": "entwurf",
        "zeichner": zeichner, "echt_ausgefuehrt": True,
        **ergebnis,
    }


def verfahren_8_1_produktvideo(root, kennung, produktfoto_pfad, variante, rechteklaerung,
                                vorbild=None, muster_uebernahme=None, cleanup_befunde=None,
                                stufe="entwurf", dauer=5):
    """Auftrag 8.1 - Produktvideo aus einem Produktfoto, baut auf 7.1 auf. Vier
    Varianten: studio, lifestyle, werbeclip, explosionsansicht. Explosions-
    ansicht ist eine eigens zu testende, sperrbare Variante (Konfiguration
    produktvideo_varianten) - sie wird hier nicht als zuverlaessig behauptet."""
    konfiguration = _laden(root)
    import jack_higgsfield
    auftragsdaten = jack_higgsfield._lesen(jack_higgsfield._auftragspfad(root, kennung))
    marke = auftragsdaten["marke"]
    varianten = konfiguration.get("produktvideo_varianten", {})
    if variante not in varianten:
        raise ValueError("Unbekannte Produktvideo-Variante")
    if varianten[variante] != "frei":
        raise ValueError(f"Variante '{variante}' ist gesperrt ({varianten[variante]}) - erst als eigens "
                         "getestete Variante freischalten, nicht als zuverlaessig behaupten, bevor sie es ist.")
    if not isinstance(rechteklaerung, dict) or not isinstance(rechteklaerung.get("eigenes_foto"), bool):
        raise ValueError("Rechte-Pruefung zum Produktfoto fehlt (Pflicht vor jeder Generierung)")
    if not rechteklaerung["eigenes_foto"]:
        beleg = rechteklaerung.get("partnerprogramm_beleg")
        if not isinstance(beleg, str) or not beleg.strip():
            raise ValueError("Fremdes Produktfoto ohne belegte Nutzungserlaubnis - ohne Fundstelle des "
                             "Partnerprogramms keine Erzeugung")
    produktfoto = str(_eigenes_material(root, konfiguration, marke, produktfoto_pfad).relative_to(_vault(root)))
    muster = musterentscheidung(vorbild, muster_uebernahme) if vorbild is not None else None
    cleanup = jack_medien.cleanup_pruefliste(cleanup_befunde) if cleanup_befunde is not None else None
    _stufenfreigabe_pruefen(konfiguration, "produktvideo", stufe)
    prompt = ("Produktvideo aus Produktfoto, Variante %s. Produkt muss originalgetreu bleiben (Form, "
              "Farbe, Aufdruck, Logo); keine erfundenen Eigenschaften oder Funktionen.") % variante
    stopp = _sicherer_stopp(root, kennung, prompt, "seedance_2_text", dauer=dauer)
    return {
        "verfahren": "8.1_produktvideo", "kennung": kennung, "marke": marke,
        "variante": variante, "produktfoto": produktfoto, "rechteklaerung": rechteklaerung,
        "musterentscheidung": muster, "cleanup_pruefliste": cleanup, "stufe": stufe,
        **stopp,
        "hinweis_variante": "Explosionsansicht ist als gesondert zu testende, sperrbare Variante "
                             "markiert (siehe produktvideo_varianten in der Konfiguration).",
        "hinweis_modellgrenze": "seedance_2_text ist derzeit das einzige bepreiste Higgsfield-Modell "
                                 "fuer diesen Entwurf."
    }


def verfahren_9_1_cleanup(root, marke, clip_pfad, befunde, ersatzflaechen=None):
    """Auftrag 9.1 - Aufraeum-Schritt in 7.1 und 8.1, KEIN eigenes System.
    Erzwingt die Pflichtpruefung (Personen/Kennzeichen/Adressen/fremde Marken)
    und wendet optional bereitgestellte Ersatzflaechen NUR im belegten
    Rechteck an (jack_medien.cleanup_maske_anwenden). FFmpeg beweist dabei nur
    Schnitt/Maskierung, keine Rekonstruktion verdeckter Bildbereiche."""
    konfiguration = _laden(root)
    marke = _marke(konfiguration, marke)
    ziel = _eigenes_material(root, konfiguration, marke, clip_pfad)
    relativ = str(ziel.relative_to(_vault(root)))
    pruefliste = jack_medien.cleanup_pruefliste(befunde)
    ergebnisse = []
    if ersatzflaechen is not None:
        if not isinstance(ersatzflaechen, list) or len(ersatzflaechen) > 10:
            raise ValueError("Hoechstens 10 Ersatzflaechen je Aufraeum-Schritt")
        for e in ersatzflaechen:
            if not isinstance(e, dict):
                raise ValueError("Jede Ersatzflaeche braucht Rechteck- und Pfadangaben")
            ergebnisse.append(jack_medien.cleanup_maske_anwenden(
                root, relativ, e["ersatzflaeche_pfad"], e["x"], e["y"], e["breite"], e["hoehe"], e["zielpfad"]))
    return {
        "verfahren": "9.1_cleanup", "marke": marke, "clip": relativ,
        "pruefliste": pruefliste, "ergebnisse": ergebnisse,
        "hinweis": "Aufraeum-Schritt innerhalb von 7.1/8.1, kein eigenstaendiges System. FFmpeg-Weg "
                   "beweist nur Schnitt/Maskierung, keine Rekonstruktion verdeckter Bildbereiche."
    }


def verfahren_11_1_motion_graphics(root, kennung, bausteintyp, storyboard, markenrechte_pruefung,
                                    stufe="entwurf"):
    """Auftrag 11.1 - Baustein Motion Graphics in 7.1/8.1: bearbeitbare
    Vorlagen fuer Logo, Titel, Bauchbinde, Hinweis/CTA, Fortschrittsanzeige,
    echte UI-Elemente. Markenrechte-Pruefung ist Pflicht vor jedem Baustein."""
    BAUSTEINE = {"logo", "titel", "bauchbinde", "hinweis_cta", "fortschrittsanzeige", "ui_element"}
    konfiguration = _laden(root)
    import jack_higgsfield
    auftragsdaten = jack_higgsfield._lesen(jack_higgsfield._auftragspfad(root, kennung))
    marke = auftragsdaten["marke"]
    if bausteintyp not in BAUSTEINE:
        raise ValueError("Unbekannter Motion-Graphics-Baustein")
    storyboard = _text(storyboard, "Storyboard", 3000, mehrzeilig=True)
    if not isinstance(markenrechte_pruefung, dict):
        raise ValueError("Markenrechte-Pruefung fehlt")
    pflicht = ("farben_schrift_aus_steckbrief", "schriftlizenz_belegt",
               "logo_designrechte_geklaert", "bewegungsstil_aus_steckbrief")
    for feld in pflicht:
        wert = markenrechte_pruefung.get(feld)
        wahr = wert is True or (isinstance(wert, str) and wert.strip())
        if not wahr:
            raise ValueError(f"Markenrechte-Pruefung unvollstaendig: '{feld}' fehlt oder ist negativ")
    if bausteintyp == "ui_element" and markenrechte_pruefung.get("nur_echte_oberflaeche") is not True:
        raise ValueError("UI-Elemente nur aus echten Bildschirmfotos oder freigegebenen Entwuerfen - "
                         "keine erfundenen Funktionen, Zahlen oder Kundenlogos")
    _stufenfreigabe_pruefen(konfiguration, "motion_graphics", stufe)
    prompt = ("Motion-Graphics-Baustein %s fuer Marke %s. Storyboard (Sekunde/Element/Text/Bewegung/"
              "Uebergang): %s") % (bausteintyp, marke, storyboard)
    stopp = _sicherer_stopp(root, kennung, prompt, "video_editing")
    return {
        "verfahren": "11.1_motion_graphics", "kennung": kennung, "marke": marke,
        "bausteintyp": bausteintyp, "markenrechte_pruefung": markenrechte_pruefung, "stufe": stufe,
        **stopp,
        "hinweis_modellgrenze": "Higgsedit/video-editing ist in der Konfiguration noch nicht als "
                                 "bepreistes Higgsfield-Modell hinterlegt.",
        "ablage_hinweis": "Vorlage, Bauskript, Vorschau und Endfassung sind als versionierte Dateien "
                           "im Medienordner der Marke zu sichern, sobald ein echter Lauf freigegeben ist."
    }


def verfahren_sprachfassung_baustein(root, kennung, zielsprachen, einwilligungen, uebersetzung_freigegeben):
    """Baustein Sprachfassungen (aus 7.1 Schritt 7 / Video 19): arbeitet
    ausschliesslich aus einer bereits vom Patron freigegebenen eigenen
    Endfassung. Kein Ausloesen in diesem Auftrag, kein Zwang zu neuen
    Stimm-/Dubbing-Abos."""
    import jack_higgsfield
    pfad = jack_higgsfield._auftragspfad(root, kennung)
    daten = jack_higgsfield._lesen(pfad)
    if not daten.get("erzeugtes_video"):
        raise ValueError("Sprachfassung braucht eine bereits erzeugte eigene Endfassung")
    if daten.get("patron_freigabe") != "erteilt":
        raise ValueError("Sprachfassung nur aus einer bereits vom Patron freigegebenen eigenen Endfassung")
    if not isinstance(zielsprachen, list) or len(zielsprachen) != 1:
        raise ValueError("Erst genau eine Sprache als Probe (Auftrag 7.1 Schritt 7)")
    if not isinstance(einwilligungen, list) or not einwilligungen:
        raise ValueError("Einwilligung jeder gezeigten Person zur KI-Vertonung muss dokumentiert sein")
    for e in einwilligungen:
        if not isinstance(e, dict) or not e.get("person_bezeichnung") or not e.get("einwilligung_dokument_pfad"):
            raise ValueError("Jede Einwilligung braucht Personenbezeichnung und Beleg-Dateipfad")
    if uebersetzung_freigegeben is not True:
        raise ValueError("Uebersetzung des Sprechtexts muss vorab als Text freigegeben sein")
    prompt = "Sprachfassung (Dubbing) der freigegebenen eigenen Endfassung fuer: " + ", ".join(zielsprachen)
    stopp = _sicherer_stopp(root, kennung, prompt, "dubbing")
    return {
        "verfahren": "sprachfassung_baustein", "kennung": kennung, "zielsprachen": zielsprachen,
        "einwilligungen_dokumentiert": len(einwilligungen), "uebersetzung_freigegeben": True,
        **stopp
    }


# --- Videobetrieb Teil 3 (P07): zwei echte Prueftore, technisch an die exakte
# geprueft Version gebunden. Kein Parallelsystem zum bestehenden Tor-1/Tor-2-
# Begriff aus agenten/README_AGENTEN.md Abschnitt 3 (dort fuer den
# geschuetzten Auftragsvertrag in jack_auftrag.py) - hier dieselbe Bindungs-
# Logik fuer die Videoproduktionsakte (auftrag.json je VP-Kennung), an genau
# den Punkten der bestehenden Statusfolge, an denen sie bereits vorgesehen
# sind ("qualitaetspruefung" fuer Tor 1, vor "patron_freigabe" fuer Tor 2).
#
# Bindung wiederverwendet ausdruecklich vorhandene Mechanik statt sie neu zu
# erfinden: den kanonischen JSON-Hash aus jack_auftrag.py (_json/_hash) fuer
# den geprueften Textinhalt, und jack_medien.fingerprint() fuer jede
# geprueft Mediendatei. Jede Aenderung an Text ODER Medien nach einer
# Tor-1- oder Tor-2-Annahme aendert automatisch den neu berechneten Hash
# bzw. Fingerprint - die gespeicherte Pruefung wird dadurch beim naechsten
# Abfragen als ungueltig erkannt (_tor_gueltig), nicht durch eine manuell
# zu pflegende Markierung. Eine Ablehnung bleibt fuer ihre exakte Version
# bindend, solange sich nichts an ihr aendert (dieselbe Pruefung).
TOR_TEXTFELDER = ("titel", "marke", "verantwortlich", "ziel", "format", "produktionstyp", "brief")


def _tor_inhalt(daten):
    return {feld: daten.get(feld) for feld in TOR_TEXTFELDER}


def _tor_inhaltshash(daten):
    import jack_auftrag
    return jack_auftrag._hash(jack_auftrag._json(_tor_inhalt(daten)).encode())


def _tor_medien(root, daten, zusatzpfade=()):
    """Fingerprintet jedes zu pruefende Medium (erzeugtes_video Pflicht, plus
    optionale weitere Belege) ueber die vorhandene Funktion aus jack_medien.py."""
    video = daten.get("erzeugtes_video")
    if not isinstance(video, str) or not video:
        raise ValueError("Kein erzeugtes Video vorhanden; Tor-Pruefung braucht ein geprueftes Medium")
    vault = _vault(root).resolve()
    ergebnisse, gesehen = [], set()
    for roh in (video, *zusatzpfade):
        if roh in gesehen:
            continue
        gesehen.add(roh)
        if not isinstance(roh, str) or not roh:
            raise ValueError("Ungueltiger Medienpfad fuer die Tor-Pruefung")
        p = Path(roh)
        if p.is_absolute() or ".." in p.parts:
            raise ValueError("Tor-Medienpfad muss relativ zur Holding sein")
        ziel = vault / p
        if any(x.is_symlink() for x in [ziel, *ziel.parents] if x != vault and vault in x.parents):
            raise ValueError("Tor-Medienpfad darf keinen Verweis enthalten")
        ziel = ziel.resolve()
        if vault not in ziel.parents or not ziel.is_file():
            raise ValueError("Geprueftes Medium fehlt oder liegt ausserhalb der Holding: " + roh)
        ergebnisse.append({"pfad": roh, **jack_medien.fingerprint(ziel)})
    return ergebnisse


def _tor_gueltig(root, daten, record):
    """Rechnet Inhaltshash und Medienfingerprints JETZT neu und vergleicht sie
    mit dem gespeicherten Eintrag - keine manuell zu pflegende Markierung."""
    if not isinstance(record, dict) or record.get("schema") != 1:
        return False, "Kein gueltiger Pruefeintrag"
    geprueft = record.get("gepruefte_version")
    if not isinstance(geprueft, dict) or not isinstance(geprueft.get("medien"), list) or not geprueft["medien"]:
        return False, "Gepruefte Version fehlt im Eintrag"
    if _tor_inhaltshash(daten) != geprueft.get("inhalt_sha256"):
        return False, "Auftragsinhalt wurde seit der Pruefung veraendert"
    if daten.get("erzeugtes_video") != geprueft["medien"][0].get("pfad"):
        return False, "Erzeugtes Video wurde seit der Pruefung ausgetauscht"
    vault = _vault(root).resolve()
    for eintrag in geprueft["medien"]:
        pfad = eintrag.get("pfad")
        try:
            p = Path(pfad)
            if not isinstance(pfad, str) or p.is_absolute() or ".." in p.parts:
                return False, "Ungueltiger gepruefter Medienpfad"
            ziel = vault / p
            if any(x.is_symlink() for x in [ziel, *ziel.parents] if x != vault and vault in x.parents):
                return False, "Gepruefter Medienpfad enthaelt einen Verweis"
            ziel = ziel.resolve()
            if vault not in ziel.parents or not ziel.is_file():
                return False, "Geprueftes Medium fehlt: " + str(pfad)
            aktuell = jack_medien.fingerprint(ziel)
        except (OSError, ValueError) as fehler:
            return False, str(fehler)
        if aktuell.get("sha256") != eintrag.get("sha256") or aktuell.get("bytes") != eintrag.get("bytes"):
            return False, "Geprueftes Medium wurde seit der Pruefung veraendert: " + str(pfad)
    return True, "Pruefung ist an die aktuelle Version gebunden und gueltig"


def tore_stand(root, kennung):
    """Live neu geprueft Gueltigkeit beider Tore (P07); veraendert nichts."""
    import jack_runway
    daten = jack_runway._lesen(jack_runway._auftragspfad(root, kennung))
    tore = daten.get("tore") or {}
    ergebnis = {}
    for name in ("tor1", "tor2"):
        record = tore.get(name)
        if record is None:
            ergebnis[name] = {"vorhanden": False, "gueltig": False, "urteil": None,
                               "text": "Noch keine " + name.upper() + "-Pruefung erfasst."}
            continue
        gueltig, text = _tor_gueltig(root, daten, record)
        ergebnis[name] = {"vorhanden": True, "gueltig": gueltig, "urteil": record.get("urteil"),
                           "pruefer": record.get("pruefer"), "zeit": record.get("zeit"), "text": text}
    return ergebnis


def tor_pruefen(root, kennung, tor, pruefer, urteil, begruendung=None, zusatzmedien=()):
    """Bindet Tor 1 (zustaendiger Marken-CEO, Vollstaendigkeit) oder Tor 2
    (unabhaengiger Pruefer, Korrektheit/Rechte/Markenpassung) an die exakte
    aktuelle Text- und Medienversion. Tor 2 setzt eine noch gueltige
    Tor-1-ANNAHME voraus und braucht einen anderen Pruefer als Tor 1 und den
    Marken-CEO. Bestehende Versuchs-/Eskalationsregeln (README_AGENTEN.md
    Abschnitt 3) und Budgetgrenzen bleiben unberuehrt - diese Funktion
    zaehlt keine Versuche und veraendert keine Kostengrenze."""
    if tor not in ("tor1", "tor2"):
        raise ValueError("Tor muss 'tor1' oder 'tor2' sein")
    if urteil not in ("ANNAHME", "ABLEHNUNG"):
        raise ValueError("Urteil muss ANNAHME oder ABLEHNUNG sein")
    pruefer = _text(pruefer, "Pruefer", 120)
    if urteil == "ABLEHNUNG":
        begruendung = _text(begruendung, "Begruendung der Ablehnung", 4000, mehrzeilig=True)
    elif begruendung is not None:
        begruendung = _text(begruendung, "Begruendung", 4000, mehrzeilig=True)
    import jack_runway
    pfad = jack_runway._auftragspfad(root, kennung)
    with jack_runway._sperre(pfad):
        daten = jack_runway._lesen(pfad)
        if daten.get("status") != "qualitaetspruefung":
            raise ValueError("Tor-Pruefung ist erst im Status 'qualitaetspruefung' moeglich")
        if not daten.get("technische_pruefung"):
            raise ValueError("Technische Pruefung fehlt; keine Tor-Pruefung ohne bestandene Technik")
        if tor == "tor1" and pruefer != daten.get("verantwortlich"):
            raise ValueError("Tor 1 prueft ausschliesslich der zustaendige Marken-CEO dieses Auftrags")
        tore = dict(daten.get("tore") or {})
        if tor == "tor2":
            tor1 = tore.get("tor1")
            if not tor1:
                raise ValueError("Tor 2 setzt eine bestehende Tor-1-Pruefung voraus")
            gueltig, text = _tor_gueltig(root, daten, tor1)
            if not (gueltig and tor1.get("urteil") == "ANNAHME"):
                raise ValueError("Tor 2 setzt eine noch gueltige Tor-1-ANNAHME voraus: " + text)
            if pruefer == tor1.get("pruefer") or pruefer == daten.get("verantwortlich"):
                raise ValueError("Tor 2 braucht einen unabhaengigen Pruefer, nicht den Marken-CEO oder den Tor-1-Pruefer")
        geprueft = {"inhalt_sha256": _tor_inhaltshash(daten), "medien": _tor_medien(root, daten, zusatzmedien)}
        eintrag = {"schema": 1, "zeit": dt.datetime.now().astimezone().isoformat(),
                   "pruefer": pruefer, "urteil": urteil, "gepruefte_version": geprueft}
        if begruendung:
            eintrag["begruendung"] = begruendung
        tore[tor] = eintrag
        daten["tore"] = tore
        jack_runway._schreiben(pfad, daten)
        return {"kennung": kennung, "tor": tor, "urteil": urteil, "pruefer": pruefer,
                "gepruefte_version": geprueft,
                "hinweis": "Bindet die Pruefung an genau diese Text- und Medienversion; "
                           "jede spaetere Aenderung entwertet sie automatisch."}
