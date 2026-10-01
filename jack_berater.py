#!/usr/bin/env python3
"""Block 33.2: Stufen-Berater. Fragt Ruflos Modell-Router (`hooks model-route`,
lokale Heuristik, KEIN Modellaufruf, kostet nichts) vor einem Lauf um eine
Empfehlung und protokolliert sie. JACK entscheidet weiterhin ausschliesslich
nach seinen eigenen Kostenstufen-Regeln (A6b/betrieb/kostenstufen.json) - der
Berater beraet, er entscheidet nicht mit.

Ist Ruflo nicht erreichbar, wird das weggelassen und protokolliert, nicht
erfunden (Grundsatz "Unbekannt heisst unbekannt").
"""
import json
import os
import re
import subprocess
from pathlib import Path

HIER = Path(__file__).resolve().parent
# F-8 T2: unter der Test-Umleitung (JACK_BETRIEB_DIR + JACK_BETRIEB_FUER = diese Wurzel) schreibt auch der Berater dorthin.
_UMGELEITET = (os.environ.get("JACK_BETRIEB_DIR") and os.environ.get("JACK_BETRIEB_FUER")
               and Path(os.environ["JACK_BETRIEB_FUER"]).resolve() == HIER)
PROTOKOLL = (Path(os.environ["JACK_BETRIEB_DIR"]) if _UMGELEITET else HIER / "betrieb") / "berater_protokoll.jsonl"


def _protokoll_anhaengen(zeile):
    PROTOKOLL.parent.mkdir(exist_ok=True)
    with PROTOKOLL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(zeile, ensure_ascii=False) + "\n")


def frage(auftragstext, eigene_stufe, auftragsname="", zeit=None):
    """Fragt den Ruflo-Modell-Router, protokolliert Empfehlung vs. eigene
    Entscheidung. Gibt {'ok':bool, 'empfehlung':str|None, ...} zurueck."""
    import jack_betrieb as b
    eintrag = {"zeit": (zeit or b.now().isoformat()), "auftrag": auftragsname,
               "eigene_stufe": eigene_stufe, "ok": False, "empfehlung": None,
               "vergleich": None}
    # Ruflos CLI-Parser bricht an einem fuehrenden "---" (YAML-Kopf) mit
    # "task.slice is not a function" - der Kopf ist ohnehin nicht der Auftrag,
    # deshalb wird er vor der Frage entfernt (gefunden beim Testen, 23.09.2026).
    text_ohne_kopf = re.sub(r"^---\s*\n.*?\n---\s*\n", "", auftragstext or "", count=1, flags=re.S).strip()
    try:
        r = subprocess.run(["npx", "-y", "ruflo@latest", "hooks", "model-route",
                            "-t", (text_ohne_kopf or auftragstext)[:300]],
                           cwd=str(HIER), capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            eintrag["grund"] = "Ruflo nicht erreichbar oder Fehler (rc=%d)" % r.returncode
            _protokoll_anhaengen(eintrag)
            return eintrag
        text = r.stdout
        m = re.search(r"Selected Model:\s*\S*\s*([A-Z]+)", text)
        empfehlung = m.group(1).lower() if m else None
        eintrag["ok"] = True
        eintrag["empfehlung"] = empfehlung
        eigene_stufe_name = {1: "haiku", 2: "sonnet"}.get(int(eigene_stufe or 1), "haiku")
        guenstiger = {"haiku": 1, "sonnet": 2, "opus": 3}
        if empfehlung in guenstiger and empfehlung != eigene_stufe_name:
            if guenstiger[empfehlung] < guenstiger.get(eigene_stufe_name, 1):
                eintrag["vergleich"] = "ruflo_guenstiger"
            else:
                eintrag["vergleich"] = "ruflo_teurer"
        else:
            eintrag["vergleich"] = "gleich"
    except (OSError, subprocess.SubprocessError) as fehler:
        eintrag["grund"] = "Ausnahme: " + type(fehler).__name__
    _protokoll_anhaengen(eintrag)
    return eintrag


def auswertung(hoechstens=10):
    """Block 33.2: Uebereinstimmung ueber die letzten N protokollierten
    Anfragen - wo Ruflo guenstiger gewesen waere als JACKs eigene Stufe."""
    if not PROTOKOLL.is_file():
        return {"anzahl": 0, "text": "Kein Berater-Protokoll vorhanden."}
    zeilen = [json.loads(z) for z in PROTOKOLL.read_text(encoding="utf-8").splitlines() if z.strip()]
    letzte = zeilen[-hoechstens:]
    ok = [z for z in letzte if z.get("ok")]
    guenstiger = [z for z in ok if z.get("vergleich") == "ruflo_guenstiger"]
    gleich = [z for z in ok if z.get("vergleich") == "gleich"]
    teurer = [z for z in ok if z.get("vergleich") == "ruflo_teurer"]
    return {"anzahl": len(letzte), "beantwortet": len(ok),
            "uebereinstimmung": len(gleich), "ruflo_waere_guenstiger": len(guenstiger),
            "ruflo_waere_teurer": len(teurer),
            "text": ("%d von %d Anfragen beantwortet. Übereinstimmung bei %d, "
                     "Ruflo hätte %d mal eine günstigere Stufe vorgeschlagen, "
                     "%d mal eine teurere." % (len(ok), len(letzte), len(gleich),
                                               len(guenstiger), len(teurer)))}


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2 and sys.argv[1] == "frage":
        print(json.dumps(frage(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 1), ensure_ascii=False))
    elif len(sys.argv) > 1 and sys.argv[1] == "auswertung":
        print(json.dumps(auswertung(), ensure_ascii=False, indent=1))
    else:
        print("Nutzung: jack_berater.py frage <auftragstext> <eigene_stufe> | jack_berater.py auswertung")
