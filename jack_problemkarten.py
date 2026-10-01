#!/usr/bin/env python3
"""F-39 (25.09.2026): Problemkarten schliessen sich selbst, wenn ein Nachfolger angenommen ist.

Regel: Liegt in auftraege/problem/ ein Auftrag und in auftraege/erledigt/ ein spaeterer Auftrag mit DEMSELBEN
Titel (Kopffeld "auftrag"), dessen Abnahmezettel den Status "geprueft" hat (Tor 2 unabhaengig ANNAHME, Quittung
gueltig), dann wird die Problemkarte NICHT geloescht, sondern mit mv -n nach abnahme/freigaben_erledigt/ verschoben
und im Register REGISTER_PROBLEMKARTEN.md eingetragen ("geschlossen durch <Nachfolger>"). Kein Modellaufruf, 0 USD.
Rueckweg je Datei: mv abnahme/freigaben_erledigt/<Datei> auftraege/problem/
"""
import json
import os
import re
import shutil
from pathlib import Path

import jack_auftrag

HIER = Path(__file__).resolve().parent
ERLEDIGT_ORDNER = Path("abnahme") / "freigaben_erledigt"
REGISTER = "REGISTER_PROBLEMKARTEN.md"


def _titel(pfad):
    try:
        return re.sub(r"\s+", " ", jack_auftrag.kopf(Path(pfad).read_text(encoding="utf-8")).get("auftrag", "")).strip().casefold()
    except (OSError, ValueError):
        return ""


def _erteilt(pfad):
    try:
        return jack_auftrag.kopf(Path(pfad).read_text(encoding="utf-8")).get("erteilt", "")
    except (OSError, ValueError):
        return ""


def _zettelwort(root, name, ordner):
    import jack_abnahmezettel
    return (jack_abnahmezettel.fuer_tafel(root, name, ordner) or {}).get("status")


def nachfolger_finden(root, problem, zettelwort=None):
    """-> Pfad des angenommenen Nachfolgers oder None."""
    zettelwort = zettelwort or _zettelwort
    titel = _titel(problem)
    if not titel:
        return None
    ordner = Path(root) / "auftraege" / "erledigt"
    if not ordner.is_dir():
        return None
    erteilt = _erteilt(problem)
    for kandidat in sorted(ordner.glob("*.md")):
        if kandidat.is_symlink() or kandidat.name == Path(problem).name or _titel(kandidat) != titel:
            continue
        if _erteilt(kandidat) and erteilt and _erteilt(kandidat) < erteilt:
            continue   # nur SPAETERE Auftraege zaehlen als Nachfolger
        if zettelwort(root, kandidat.name, "erledigt") == "geprüft":
            return kandidat
    return None


def schliessen(root=HIER, trocken=False, zettelwort=None):
    """Schliesst alle Problemkarten mit angenommenem Nachfolger. -> Liste der Eintraege (auch im Trockenlauf)."""
    root = Path(root)
    problemordner = root / "auftraege" / "problem"
    raus = []
    if not problemordner.is_dir():
        return raus
    for karte in sorted(problemordner.glob("*.md")):
        if karte.is_symlink():
            continue
        nachfolger = nachfolger_finden(root, karte, zettelwort)
        if not nachfolger:
            continue
        ziel_ordner = root / ERLEDIGT_ORDNER
        ziel = ziel_ordner / karte.name
        eintrag = {"karte": karte.name, "geschlossen_durch": nachfolger.name, "ziel": str(ziel.relative_to(root)), "trocken": trocken}
        if ziel.exists():
            eintrag["uebersprungen"] = "Ziel existiert schon (mv -n)"
            raus.append(eintrag)
            continue
        if not trocken:
            ziel_ordner.mkdir(parents=True, exist_ok=True)
            stat = karte.stat()
            shutil.move(str(karte), str(ziel))
            os.utime(ziel, (stat.st_atime, stat.st_mtime))
            register = ziel_ordner / REGISTER
            neu = not register.exists()
            with register.open("a", encoding="utf-8") as f:
                if neu:
                    f.write("# Problemkarten, die sich selbst geschlossen haben (F-39)\n\n"
                            "Regel: Ein spaeterer Auftrag mit gleichem Titel ist in `auftraege/erledigt/` und sein Abnahmezettel "
                            "hat den Status „geprüft“ (Tor 2 ANNAHME). Nichts wird geloescht; die Karte wird mit `mv -n` hierher "
                            "verschoben. Rueckweg: `mv abnahme/freigaben_erledigt/<Datei> auftraege/problem/` (im JACK-Ordner).\n\n"
                            "| Zeit | Karte | geschlossen durch | Beleg |\n|---|---|---|---|\n")
                import datetime as dt
                f.write("| %s | `%s` | `%s` | Zettelstatus des Nachfolgers: geprüft (Tor 2 ANNAHME) |\n" % (
                    dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M"), karte.name, nachfolger.name))
        raus.append(eintrag)
    return raus


if __name__ == "__main__":
    import sys
    print(json.dumps(schliessen(HIER, trocken="--trocken" in sys.argv), ensure_ascii=False, indent=1))
