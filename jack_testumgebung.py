#!/usr/bin/env python3
"""Gemeinsame Test-Fixture: Betriebsablage der Tests in ein Wegwerf-Verzeichnis umleiten (F-8 T2, 24.09.2026).

Bisher schrieben Tests, die mit der echten JACK-Wurzel arbeiten, in die LIVE-Protokolle
(betrieb/planer.jsonl, steuerung.jsonl, sprachmessung.jsonl, werkzeugeinsatz.jsonl ...).
Alle Schreibwege gehen ueber jack_betrieb.area(root); mit den Umgebungsvariablen
JACK_BETRIEB_DIR (Ziel) und JACK_BETRIEB_FUER (die echte Wurzel) liegt die Ablage der echten Wurzel in einem temporaeren Ordner,
befuellt mit einer Kopie des heutigen betrieb/ (damit Tests, die Konfiguration lesen,
weiter denselben Stand sehen). Eigene Wurzeln der Tests bleiben unberuehrt.

Verwendung in einer Testdatei (zwei Zeilen):
    import jack_testumgebung
    setUpModule, tearDownModule = jack_testumgebung.modul_fixture()

Oder als Kontext:  with jack_testumgebung.betriebsumleitung() as ordner: ...
Die Gesamtsuite (abnahme/Kern_F8_2026-09-24/suite_isoliert.py) setzt die Variable fuer jeden Testprozess.
"""
import contextlib
import os
import shutil
import tempfile
from pathlib import Path

HIER = Path(__file__).resolve().parent
VARIABLE = "JACK_BETRIEB_DIR"
VARIABLE_FUER = "JACK_BETRIEB_FUER"
# Nur Kopfdaten ausschliessen, die ein Test nie braucht und die gross oder fluechtig sind.
_AUSLASSEN = shutil.ignore_patterns("gedaechtnis_export", "*.sqlite3", "*.sqlite3-*", "*.lock", "*.sock")


def umgebung(ordner, basis=None):
    """Umgebungsvariablen fuer einen Testprozess (beide Schalter zusammen)."""
    return dict(basis if basis is not None else os.environ, **{VARIABLE: str(ordner), VARIABLE_FUER: str(HIER)})


def kopie_anlegen(ziel=None):
    """Kopiert betrieb/ (ohne Sperr-/Datenbankdateien) nach `ziel` oder in ein neues Temp-Verzeichnis."""
    ziel = Path(ziel) if ziel else Path(tempfile.mkdtemp(prefix="jack_betrieb_test_"))
    shutil.copytree(HIER / "betrieb", ziel, ignore=_AUSLASSEN, dirs_exist_ok=True)
    return ziel


@contextlib.contextmanager
def betriebsumleitung(ziel=None):
    vorher = {k: os.environ.get(k) for k in (VARIABLE, VARIABLE_FUER)}
    ordner = kopie_anlegen(ziel)
    os.environ[VARIABLE], os.environ[VARIABLE_FUER] = str(ordner), str(HIER)
    try:
        yield ordner
    finally:
        for k, v in vorher.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(ordner, ignore_errors=True)


def modul_fixture():
    """Liefert (setUpModule, tearDownModule) fuer unittest."""
    stand = {}

    def hoch():
        stand["ctx"] = betriebsumleitung()
        stand["ordner"] = stand["ctx"].__enter__()

    def runter():
        stand["ctx"].__exit__(None, None, None)

    return hoch, runter
