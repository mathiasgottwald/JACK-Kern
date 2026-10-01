#!/usr/bin/env python3
"""F-24 Teil C (1), Patron-Freigabe 24.09.2026: kein rekursives grep / find ueber den JACK-Ordner ohne Ausschluss von
betrieb/ und abnahme/.

Warum: dort liegen Live-Protokolle und grosse Belegordner. Eine rekursive Suche darueber ist langsam, trifft
Protokollzeilen statt Code (falsche Treffer, Block 10) und kann in Wegwerf-Umleitungen Live-Dateien beruehren.
Erlaubt bleibt: rg (ripgrep) mit --glob '!betrieb/**' --glob '!abnahme/**', grep/find auf Unterordnern, und grep/find
mit beiden Ausschluessen. PreToolUse-Hook fuer Bash (Projekt 00_Marken/JACK). Ohne Befund: keine Ausgabe, Freigabe.
"""
import json
import os
import re
import shlex
import sys
from pathlib import Path

JACK = Path(__file__).resolve().parents[1]
HINWEIS = ("Rekursive Suche ueber 00_Marken/JACK ohne Ausschluss von betrieb/ und abnahme/ ist gesperrt (F-24, "
           "Live-Protokolle). Stattdessen: rg -n 'muster' --glob '!betrieb/**' --glob '!abnahme/**' <pfad> "
           "oder einen Unterordner durchsuchen.")


def _abschnitte(befehl):
    return [t for t in re.split(r"\|\||&&|[|;&\n]", befehl) if t.strip()]


def _pfade(tokens, cwd):
    return [(Path(cwd) / os.path.expanduser(t)).resolve() for t in tokens if not t.startswith("-")]


def _umfasst_jack(pfad):
    return pfad == JACK or pfad in JACK.parents


def pruefen(befehl, cwd):
    """Grund der Sperre oder None."""
    for teil in _abschnitte(befehl):
        try:
            t = shlex.split(teil)
        except ValueError:
            continue
        if t and t[0] == "rtk":
            t = t[1:]
        if not t:
            continue
        prog = os.path.basename(t[0])
        if prog in ("grep", "egrep", "fgrep"):
            optionen = [x for x in t[1:] if x.startswith("-")]
            rekursiv = any(x in ("--recursive", "--dereference-recursive") or
                           (re.fullmatch(r"-[A-Za-z]+", x) and ("r" in x or "R" in x)) for x in optionen)
            if not rekursiv:
                continue
            ausgeschlossen = {m for x in t for m in re.findall(r"--exclude-dir=['\"]?([^'\"\s]+)", x)}
            for i, x in enumerate(t):
                if x == "--exclude-dir" and i + 1 < len(t):
                    ausgeschlossen.add(t[i + 1])
            if {"betrieb", "abnahme"} <= {a.strip("/").split("/")[-1] for a in ausgeschlossen}:
                continue
            args = [x for x in t[1:] if not x.startswith("-")]
            pfade = _pfade(args[1:], cwd) or [Path(cwd).resolve()]       # erstes Nicht-Optionswort = Muster
            if any(_umfasst_jack(p) for p in pfade):
                return HINWEIS
        elif prog == "find":
            pfade = []
            for x in t[1:]:
                if x.startswith(("-", "(", "!")):
                    break
                pfade.append(x)
            pfade = _pfade(pfade, cwd) or [Path(cwd).resolve()]
            if any(_umfasst_jack(p) for p in pfade) and not ("betrieb" in teil and "abnahme" in teil):
                return HINWEIS
    return None


def main():
    try:
        ereignis = json.load(sys.stdin)
    except ValueError:
        return 0
    if ereignis.get("tool_name") != "Bash":
        return 0
    grund = pruefen(str((ereignis.get("tool_input") or {}).get("command") or ""), ereignis.get("cwd") or os.getcwd())
    if grund:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": grund}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
