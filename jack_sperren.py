#!/usr/bin/env python3
"""Bereichssperren fuer den Parallelbetrieb (Block 2, Aufgabe 1).

Statt einer globalen Sperre auf arbeiter.sh wird nur noch das gesperrt, was
tatsaechlich geschuetzt werden muss: der Bereich, den ein Auftrag anfasst.
Zwei Auftraege mit ueberschneidenden Bereichen laufen nacheinander, alle
anderen gleichzeitig.

Eine Sperre ist eine Datei unter betrieb/sperren/<bereich>.json. Sie wird mit
O_CREAT|O_EXCL angelegt - das ist auf einem Dateisystem unteilbar, zwei
Bewerber koennen nie beide gewinnen. In der Datei steht, WER sie haelt und
SEIT WANN, und bis wann sie gilt.
"""
import errno
import json
import os
import re
import time
from pathlib import Path

import jack_betrieb as betrieb

# Bereiche, die immer exklusiv sind - hier darf nie parallel gearbeitet werden.
STEUERBEREICHE = frozenset({"steuerung"})

# Diese Dateien gelten als Steuerdateien. Wer sie anfasst, braucht "steuerung".
STEUERDATEIEN = (
    "modellwahl.json", "arbeiter_agenten.json", "agenten/BESETZUNG.md",
    "agenten/README_AGENTEN.md", "betrieb/betriebsgrenzen.json",
    # F-4 (24.09.2026): das Faehigkeitsregister legt erlaubte Ausweichwege und
    # Anbieter fest. Ein Arbeiter darf es nie schreiben (Pfadwaechter arbeiter.sh:
    # unter betrieb/ nur entwuerfe/); wer es nennt, braucht "steuerung".
    "betrieb/faehigkeitsregister.json",
)

BEREICH_MUSTER = re.compile(r"^[a-z0-9_]+(:[A-Za-z0-9_.\-]+)?$")
STANDARDFRIST = 2700          # 45 Minuten; laengster gemessener Lauf war 25,2 min


def ordner(root) -> Path:
    p = betrieb.area(root) / "sperren"
    p.mkdir(exist_ok=True)
    return p


def gueltig(bereich: str) -> bool:
    return bool(BEREICH_MUSTER.match(bereich)) and len(bereich) <= 64


def _lesen(pfad: Path):
    try:
        return json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def abgelaufen(eintrag, jetzt=None) -> bool:
    """Eine Sperre verfaellt nach ihrer Frist - ein abgestuerzter Lauf darf
    nicht alles blockieren."""
    if not eintrag:
        return True
    jetzt = jetzt or time.time()
    bis = eintrag.get("bis_epoch")
    if not isinstance(bis, (int, float)):
        return True
    if jetzt > bis:
        return True
    # Lebt der Halter noch? Ein toter Halter gibt sofort frei, nicht erst nach Frist.
    pid = eintrag.get("pid")
    if isinstance(pid, int) and pid > 0:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            pass
    return False


def _anhaengen(pfad: Path, eintrag: dict) -> bool:
    """Legt die Sperre unteilbar UND vollstaendig an. True, wenn gewonnen."""
    tmp = pfad.with_name(pfad.name + "." + str(os.getpid()) + "." + str(time.time_ns()) + ".neu")
    try:
        tmp.write_text(json.dumps(eintrag, ensure_ascii=False), encoding="utf-8")
        try:
            os.link(tmp, pfad)          # scheitert mit EEXIST, wenn schon belegt
            return True
        except OSError as fehler:
            if fehler.errno != errno.EEXIST:
                raise
            return False
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def nehmen(root, bereiche, auftrag: str, frist: int = STANDARDFRIST, pid: int = None):
    """Nimmt ALLE Bereiche oder keinen. Gibt (True, []) oder (False, [belegte])."""
    bereiche = sorted(set(bereiche))          # feste Reihenfolge verhindert Verklemmung
    for b in bereiche:
        if not gueltig(b):
            raise ValueError("Ungueltiger Bereich: " + str(b)[:40])
    ziel = ordner(root)
    pid = pid or os.getpid()
    jetzt = time.time()
    genommen = []
    belegt = []
    for b in bereiche:
        pfad = ziel / (b.replace(":", "__") + ".json")
        eintrag = {"bereich": b, "auftrag": auftrag, "pid": pid,
                   "seit": betrieb.now().isoformat(), "seit_epoch": jetzt,
                   "bis_epoch": jetzt + frist, "frist_s": frist}
        # WICHTIG: erst den vollstaendigen Inhalt daneben schreiben, dann mit
        # os.link unteilbar an den Platz haengen. os.link scheitert, wenn dort
        # schon etwas liegt - genau wie O_EXCL, aber die Datei ist NIE leer.
        #
        # Der Umweg ist kein Schmuck. Mit O_CREAT|O_EXCL plus spaeterem Schreiben
        # gibt es ein Zeitfenster, in dem die Sperrdatei existiert, aber leer ist.
        # Ein zweiter Bewerber liest dann nichts, haelt die Sperre fuer verwaist
        # und nimmt sie weg - beide sind gleichzeitig drin. Am 16.09.2026 im Test
        # nachgewiesen: 23 von 200 Schreibvorgaengen gingen so verloren.
        if not _anhaengen(pfad, eintrag):
            alt = _lesen(pfad)
            if alt is None:
                # Datei fehlt oder ist gerade nicht lesbar. NICHT blind wegnehmen:
                # inzwischen koennte sie ein anderer frisch genommen haben. Nur
                # noch einmal sauber versuchen.
                if not _anhaengen(pfad, eintrag):
                    belegt.append({"bereich": b, "haelt": "unbekannt"})
                    break
            elif alt.get("art") == "reservierung" and alt.get("auftrag") == auftrag:
                # F-9: die eigene Fortsetzungsreservierung geht nahtlos in die Laufsperre ueber.
                if _lesen(pfad) == alt:
                    try:
                        pfad.unlink()
                    except OSError:
                        pass
                if not _anhaengen(pfad, eintrag):
                    belegt.append({"bereich": b, "haelt": alt.get("auftrag", "?")})
                    break
            elif abgelaufen(alt, jetzt):
                # Verwaiste Sperre uebernehmen - aber nur, wenn dort immer noch
                # GENAU dieser abgelaufene Eintrag steht. Sonst hat sie schon
                # jemand anders frisch genommen und wir wuerden ihn verdraengen.
                if _lesen(pfad) == alt:
                    try:
                        pfad.unlink()
                    except OSError:
                        pass
                if not _anhaengen(pfad, eintrag):
                    belegt.append({"bereich": b, "haelt": alt.get("auftrag", "?")})
                    break
            else:
                belegt.append({"bereich": b, "haelt": alt.get("auftrag", "?"),
                               "seit": alt.get("seit", "?")})
                break
        genommen.append(pfad)
    if belegt:
        for p in genommen:                   # alles zurueckgeben, nichts halb halten
            try:
                p.unlink()
            except OSError:
                pass
        return False, belegt
    return True, []


def reservieren(root, bereiche, auftrag: str, frist: int = STANDARDFRIST):
    """F-9 (Paket 3, T5): Bereiche eines unterbrochenen Auftrags bis zu seiner Fortsetzung reservieren.

    Die Reservierung haengt an keinem Prozess (pid fehlt), nur an der Frist - der abgebrochene Lauf ist
    ja tot. Kein anderer Auftrag bekommt den Bereich, solange sie gilt; die Fortsetzung desselben
    Auftrags uebernimmt sie in nehmen(). Eine bestehende eigene Reservierung wird erneuert, eine fremde
    Sperre nie verdraengt. Gibt (True, []) oder (False, [belegte]) zurueck."""
    bereiche = sorted(set(bereiche))
    for b in bereiche:
        if not gueltig(b):
            raise ValueError("Ungueltiger Bereich: " + str(b)[:40])
    ziel = ordner(root)
    jetzt = time.time()
    genommen, belegt = [], []
    for b in bereiche:
        pfad = ziel / (b.replace(":", "__") + ".json")
        eintrag = {"bereich": b, "auftrag": auftrag, "pid": None, "art": "reservierung",
                   "seit": betrieb.now().isoformat(), "seit_epoch": jetzt,
                   "bis_epoch": jetzt + frist, "frist_s": frist}
        alt = _lesen(pfad)
        if alt is not None and not abgelaufen(alt, jetzt) and alt.get("auftrag") != auftrag:
            belegt.append({"bereich": b, "haelt": alt.get("auftrag", "?"), "seit": alt.get("seit", "?")})
            break
        if alt is not None and _lesen(pfad) == alt:
            try:
                pfad.unlink()
            except OSError:
                pass
        if not _anhaengen(pfad, eintrag):
            belegt.append({"bereich": b, "haelt": (_lesen(pfad) or {}).get("auftrag", "?")})
            break
        genommen.append(pfad)
    if belegt:
        for p in genommen:
            if (_lesen(p) or {}).get("art") == "reservierung" and (_lesen(p) or {}).get("auftrag") == auftrag:
                try:
                    p.unlink()
                except OSError:
                    pass
        return False, belegt
    return True, []


def reservierungen(root):
    """{auftrag: [bereiche]} aller gueltigen Fortsetzungsreservierungen."""
    raus = {}
    jetzt = time.time()
    for pfad in sorted(ordner(root).glob("*.json")):
        e = _lesen(pfad)
        if e and e.get("art") == "reservierung" and not abgelaufen(e, jetzt):
            raus.setdefault(e.get("auftrag"), []).append(e.get("bereich"))
    return raus


def geben(root, bereiche, auftrag: str = None):
    """Gibt Sperren frei. Gibt nur frei, was diesem Auftrag gehoert."""
    ziel = ordner(root)
    frei = []
    for b in sorted(set(bereiche)):
        pfad = ziel / (b.replace(":", "__") + ".json")
        eintrag = _lesen(pfad)
        if eintrag is None:
            continue
        if auftrag and eintrag.get("auftrag") != auftrag:
            continue
        try:
            pfad.unlink()
            frei.append(b)
        except OSError:
            pass
    return frei


def stand(root):
    """Wer haelt welche Sperre seit wann - fuer die Auftragstafel."""
    ziel = ordner(root)
    jetzt = time.time()
    raus = []
    for pfad in sorted(ziel.glob("*.json")):
        e = _lesen(pfad)
        if e is None:
            continue
        alt = abgelaufen(e, jetzt)
        raus.append({"bereich": e.get("bereich"), "auftrag": e.get("auftrag"),
                     "pid": e.get("pid"), "seit": e.get("seit"),
                     "haelt_s": round(jetzt - e.get("seit_epoch", jetzt)),
                     "abgelaufen": alt, "art": e.get("art") or "lauf"})
    return raus


def aufraeumen(root):
    """Entfernt abgelaufene und verwaiste Sperren. Gibt die Namen zurueck."""
    ziel = ordner(root)
    jetzt = time.time()
    weg = []
    for pfad in sorted(ziel.glob("*.json")):
        e = _lesen(pfad)
        if abgelaufen(e, jetzt):
            try:
                pfad.unlink()
                weg.append((e or {}).get("bereich") or pfad.stem)
            except OSError:
                pass
    return weg


def bereiche_aus_kopf(text: str):
    """Liest 'bereiche:' aus dem Auftragskopf. Ohne Angabe gilt der Auftrag als
    allumfassend - das ist die sichere Seite, nicht die schnelle."""
    m = re.search(r"^bereiche:\s*(.+)$", text, re.M)
    if not m:
        return ["alles"]
    roh = [t.strip().lower() for t in re.split(r"[,\s]+", m.group(1)) if t.strip()]
    gute = [b for b in roh if gueltig(b)]
    return gute or ["alles"]


def kollidiert(a, b) -> bool:
    """'alles' kollidiert mit allem. Sonst zaehlt die Schnittmenge."""
    sa, sb = set(a), set(b)
    if "alles" in sa or "alles" in sb:
        return True
    return bool(sa & sb)
