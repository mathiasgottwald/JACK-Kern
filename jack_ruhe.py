#!/usr/bin/python3
"""F-56 (25.09.2026): Ruhe-Regel Patron fuer ALLE Kanaele und den Waechter.

Kein Neustart (und kein anderer Eingriff, der die Seite des Patrons neu laedt), solange der Patron JACK benutzt.
Patron aktiv = in den letzten 30 Min
  1. ein Eintrag mit herkunft "patron" in betrieb/gespraeche.jsonl oder betrieb/sprachmessung.jsonl, ODER
  2. eine Sprachdiagnose-Phase ausser "seite_bereit" (betrieb/sprachdiagnose.jsonl; seite_bereit feuert bei JEDEM Laden der Seite,
     auch bei Headless-Chrome-Tests, und beweist keine Nutzung), ODER
  3. eine Freigabe-/Dashboard-Aktion des Patrons (betrieb/freigaben.jsonl, herkunft "maske*" oder ausloeser mit "Maske").
Nur lesen; ohne Modell, 0 USD. Ordner: JACK_BETRIEB_DIR (Tests), sonst <Wurzel>/betrieb.
"""
import datetime as dt
import json
import os
from pathlib import Path

WURZEL = Path(__file__).resolve().parent
MINUTEN = 30
NUTZUNGSPHASEN = frozenset({"mikro_an", "erkennung_sprechstart", "erkennung_final", "sprechpause_erkannt", "eingabe_gesendet",
                            "frage_gesendet", "stopp_angefordert", "erster_text_ab_frage", "erstes_audio_ab_frage",
                            "antwort_vollstaendig_ab_frage", "ausgabe_vollstaendig"})
QUELLEN = ("gespraeche.jsonl", "sprachmessung.jsonl", "sprachdiagnose.jsonl", "freigaben.jsonl")
LESEGRENZE = 400_000          # nur das Ende der Datei lesen


def betriebsordner(betrieb_dir=None):
    return Path(betrieb_dir or os.environ.get("JACK_BETRIEB_DIR") or WURZEL / "betrieb")


def _zeile_zeit(d):
    try:
        z = dt.datetime.fromisoformat(str(d.get("zeit")))
    except (TypeError, ValueError):
        return None
    return z if z.tzinfo else z.astimezone()


def _ende(pfad):
    try:
        with open(pfad, "rb") as f:
            f.seek(0, 2)
            n = f.tell()
            f.seek(max(0, n - LESEGRENZE))
            return f.read().decode("utf-8", errors="replace").splitlines()[1 if n > LESEGRENZE else 0:]
    except OSError:
        return []


def _zaehlt(datei, d):
    """Ist dieser Eintrag ein Zeichen, dass der Patron gerade JACK benutzt?"""
    if datei in ("gespraeche.jsonl", "sprachmessung.jsonl"):
        return str(d.get("herkunft", "")).lower() == "patron"
    if datei == "sprachdiagnose.jsonl":
        # F-100 Nachtrag 3: NUR echte Nutzung zaehlt (Mikro an, Sprechen, Frage/Antwort). Seitenladen ("seite_bereit",
        # "umgebung_standalone", "dienst_bereit" ...) und das Rauschen der automatischen Spracherkennung zaehlen nicht.
        return str(d.get("phase") or "") in NUTZUNGSPHASEN
    if datei == "freigaben.jsonl":
        return str(d.get("herkunft", "")).lower().startswith("maske") or "maske" in str(d.get("ausloeser", "")).lower()
    return False


AUFHEBEN = "ruhe_aufheben.json"      # F-100 D: Knopf "Jetzt einbauen - ich warte" (Maske) schreibt {"gueltig_bis", "herkunft"}


def ruhe_aufgehoben(betrieb_dir=None, jetzt=None):
    """True, wenn der Patron per Knopf 'Jetzt einbauen' die Ruhe-Regel fuer EINEN Neustart aufgehoben hat (15 Min gueltig,
    herkunft muss 'maske' sein, einmal verbraucht = ungueltig)."""
    jetzt = jetzt or dt.datetime.now().astimezone()
    try:
        d = json.loads((betriebsordner(betrieb_dir) / AUFHEBEN).read_text(encoding="utf-8"))
        bis = dt.datetime.fromisoformat(d["gueltig_bis"])
        if bis.tzinfo is None:
            bis = bis.astimezone()
        return d.get("herkunft") == "maske" and not d.get("verbraucht_am") and jetzt <= bis
    except (OSError, ValueError, KeyError, TypeError):
        return False


def aufheben_schreiben(betrieb_dir=None, minuten=15, jetzt=None):
    jetzt = jetzt or dt.datetime.now().astimezone()
    d = {"gueltig_bis": (jetzt + dt.timedelta(minutes=minuten)).isoformat(), "herkunft": "maske", "gesetzt_am": jetzt.isoformat()}
    (betriebsordner(betrieb_dir) / AUFHEBEN).write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return d


def aufheben_verbrauchen(betrieb_dir=None):
    p = betriebsordner(betrieb_dir) / AUFHEBEN
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        d["verbraucht_am"] = dt.datetime.now().astimezone().isoformat()
        p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    except (OSError, ValueError):
        pass


def patron_aktiv(betrieb_dir=None, jetzt=None, minuten=MINUTEN):
    """-> (bool, Satz). True, wenn in den letzten `minuten` Minuten ein Zeichen der Nutzung durch den Patron vorliegt.
    F-100 D: gueltige Aufhebung ('Jetzt einbauen - ich warte') -> (False, ...)."""
    jetzt = jetzt or dt.datetime.now().astimezone()
    if ruhe_aufgehoben(betrieb_dir, jetzt):
        return False, "Ruhe aufgehoben (Patron: Jetzt einbauen)"
    ordner = betriebsordner(betrieb_dir)
    juengste = None
    for datei in QUELLEN:
        for zeile in reversed(_ende(ordner / datei)):
            try:
                d = json.loads(zeile)
            except ValueError:
                continue
            z = _zeile_zeit(d) if isinstance(d, dict) else None
            if z is None:
                continue
            if (jetzt - z).total_seconds() > minuten * 60:
                break                      # Dateien laufen zeitlich vorwaerts: aeltere Zeilen zaehlen nicht mehr
            if _zaehlt(datei, d) and (juengste is None or z > juengste[0]):
                juengste = (z, datei)
                break
    if juengste:
        return True, "Patron aktiv: %s vor %d Min" % (juengste[1], (jetzt - juengste[0]).total_seconds() // 60)
    return False, "Patron seit mehr als %d Min nicht aktiv" % minuten


def dienst_fehlt_ganz(befund):
    """F-67 (27.09.2026): Ruhe-Ausnahme - EINE Definition fuer alle Aufrufer (jack_netzwaechter.wiederanlauf, neustart_sicher.py).
    Ist der Prozess eines Laeufers gar nicht da (nicht nur haengend/ohne Antwort), gilt die Ruhe-Regel NICHT: er wird sofort
    neu gestartet, unabhaengig davon, ob der Patron gerade arbeitet - er kann JACK sonst nicht benutzen. 'haengt'/'steht'
    (Prozess da, antwortet nur nicht) bleiben unter der Ruhe-Regel."""
    return str(befund.get("status")) == "steht" and str(befund.get("grund", "")).strip() == "Prozess fehlt"


if __name__ == "__main__":
    ok, satz = patron_aktiv()
    print(json.dumps({"patron_aktiv": ok, "grund": satz}, ensure_ascii=False))
    raise SystemExit(0 if not ok else 3)
