"""Hausnamen fuer die Sprache (S-1, P3, 24.09.2026).

Die Liste der Namen, die JACK im Alltag hoert, wird AUTOMATISCH aus der Ablage
erzeugt und bei jedem Dienststart neu gebaut - nie von Hand gepflegt:
  - Mitarbeiter mit Rufname, Name laut Pass, Sprachvarianten (Twin, Twinn) und
    den Hoervarianten aus betrieb/sprache_woerterbuch.json ("hoervarianten")
  - Marken (Ordner in 00_Marken), Partner und Kunden (09_Partner, 10_Kunden)
  - haeufige Absender aus betrieb/posteingang.jsonl

Drei Verwendungen:
  (a) whisper_prompt(): Starthilfe fuer die lokale Spracherkennung.
  (b) pruefe_name(): kontextabhaengige Zuordnung - NUR dort aufgerufen, wo eine
      Absicht einen Namen braucht (Mail, Mitarbeiter). Ein gehoerter Name, der
      unbekannt ist, wird ueber Hoervarianten, Kölner Phonetik und Editier-
      abstand dem naechsten bekannten Namen zugeordnet. Ein Wort wie "bin" wird
      NIE global ersetzt: "ich bin müde" bleibt "ich bin müde".
  (c) namenblock(): Namensliste mit Hoervarianten fuer den Systemtext des
      Gespraechsmodells (dort entscheidet der ganze Satz mit).

Kein Modell, kein Netz. Lesend gegenueber der Ablage; geschrieben wird nur
betrieb/sprache_hausnamen.json (Diagnose der zuletzt erzeugten Liste).
"""
import json
import re
import threading
import time
from pathlib import Path

import jack_betrieb as b

_LOCK = threading.RLock()
_STAND = {"root": None, "zeit": 0.0, "daten": None, "sig": None}
# Sicherheitsnetz: falls der Dienststart die Liste nie neu gebaut hat, wird sie
# spaetestens nach dieser Zeit beim naechsten Zugriff neu erzeugt.
MAX_ALTER_S = 15 * 60

# Woerter, die in einem Namensrest nie der Name sind.
FUELLWOERTER = frozenset(
    "der die das dem den des ein eine einem einen einer von vom zum zur zu an auf "
    "mir mich uns dir ihm ihn ihr ihnen unser unsere unserem unseren unserer mal kurz "
    "bitte doch noch nur alle alles ganzen ganze neuen neue neuen aktuellen aktuelle "
    "offenen offene mails mail email emails e-mail e-mails post nachricht nachrichten "
    "mitarbeiter mitarbeiterin kollege kollegin und oder mit betreff raus rein".split())
# Absender-Anzeigenamen, die kein Name sind.
_JUNK = frozenset(
    "noreply no reply donotreply info service team support news newsletter mail mailer "
    "hello hallo kontakt office admin post notifications benachrichtigung".split())


def _falten(text):
    text = str(text or "").lower()
    for a, c in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        text = text.replace(a, c)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _woerter(text):
    return [w for w in _falten(text).split(" ") if w]


def _ohne_doppel(wort):
    return re.sub(r"(.)\1+", r"\1", wort)


def editierabstand(a, c):
    a, c = _ohne_doppel(a), _ohne_doppel(c)
    if a == c:
        return 0
    if not a or not c:
        return max(len(a), len(c))
    zeile = list(range(len(c) + 1))
    for i, x in enumerate(a, 1):
        neu = [i]
        for j, y in enumerate(c, 1):
            neu.append(min(neu[j - 1] + 1, zeile[j] + 1, zeile[j - 1] + (x != y)))
        zeile = neu
    return zeile[-1]


def koelner(wort):
    """Kölner Phonetik. Gleich klingende Woerter ergeben denselben Code
    (Din/Denn = 26). Kein Ersatz fuer die Hoervarianten, sondern Zusatz."""
    w = _falten(wort).replace(" ", "")
    if not w:
        return ""
    codes = []
    for i, z in enumerate(w):
        vor = w[i - 1] if i else ""
        nach = w[i + 1] if i + 1 < len(w) else ""
        if z in "aeijouy":
            c = "0"
        elif z == "h":
            continue
        elif z == "b":
            c = "1"
        elif z == "p":
            c = "3" if nach == "h" else "1"
        elif z in "dt":
            c = "8" if nach in ("c", "s", "z") else "2"
        elif z in "fvw":
            c = "3"
        elif z in "gkq":
            c = "4"
        elif z == "c":
            if not vor:
                c = "4" if nach in "ahkloqrux" and nach else "8"
            else:
                c = "4" if nach in "ahkoqux" and nach and vor not in "sz" else "8"
        elif z == "x":
            c = "8" if vor in ("c", "k", "q") else "48"
        elif z == "l":
            c = "5"
        elif z in "mn":
            c = "6"
        elif z == "r":
            c = "7"
        elif z in "sz":
            c = "8"
        else:
            continue
        codes.append(c)
    roh = "".join(codes)
    kompakt = ""
    for z in roh:
        if not kompakt or kompakt[-1] != z:
            kompakt += z
    return kompakt[:1] + kompakt[1:].replace("0", "")


def _anzeige(name):
    name = str(name or "").strip()
    return name.capitalize() if name.isupper() and len(name) > 1 else name


def _woerterbuch_hoervarianten(root):
    try:
        daten = json.loads((Path(root) / "betrieb" / "sprache_woerterbuch.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    roh = daten.get("hoervarianten") or {}
    return {_falten(k): [_falten(v) for v in vs if _falten(v)]
            for k, vs in roh.items() if isinstance(vs, list)}


def _mitarbeiter(root):
    liste = []
    try:
        import jack_mitarbeiter
        eintraege = jack_mitarbeiter.register(root).get("mitarbeiter", [])
    except Exception:
        return liste
    hoer = _woerterbuch_hoervarianten(root)
    for e in eintraege:
        if e.get("status") not in ("aktiv", "", None):
            continue
        try:
            stamm = jack_mitarbeiter.stammdaten(root, e.get("id"))
        except Exception:
            stamm = {}
        rufname = str(stamm.get("rufname") or "").strip()
        vollname = str(stamm.get("name_laut_pass") or "").strip()
        kennung = str(e.get("id") or "").strip()
        anzeige = _anzeige(rufname or (vollname.split(" ")[0] if vollname else kennung))
        adresse = str((stamm.get("kontakt") or {}).get("email_arbeit") or "")
        namen = set()
        for quelle in (rufname, vollname, kennung.replace("-", " "), adresse.split("@", 1)[0].replace(".", " ")):
            namen.update(w for w in _woerter(quelle) if len(w) >= 2)
        varianten = stamm.get("sprachvarianten") or []
        if isinstance(varianten, str):
            varianten = [varianten]
        alias = {w for v in varianten if isinstance(v, str) for w in _woerter(v)}
        hoervarianten = set()
        for schluessel in {_falten(rufname), _falten(anzeige), _falten(kennung)}:
            hoervarianten.update(hoer.get(schluessel, []))
        liste.append({"id": kennung, "anzeige": anzeige, "suchname": rufname or anzeige, "vollname": vollname,
                      "namen": namen | alias, "alias": alias, "hoervarianten": hoervarianten})
    return liste


def _ordnernamen(pfad):
    try:
        return sorted(p.name for p in Path(pfad).iterdir()
                      if p.is_dir() and not p.name.startswith((".", "_")) and p.name not in ("99_Archiv",))
    except OSError:
        return []


def _absender(root, limit=2500):
    """Anzeigenamen und Domainnamen aus dem Posteingang, haeufigste zuerst."""
    zaehler = {}
    try:
        zeilen = b.records(b.area(root) / "posteingang.jsonl", limit=limit)
    except Exception:
        return [], {}
    for z in zeilen:
        roh = str(z.get("absender") or "")
        anzeige = re.sub(r"<.*?>", "", roh).strip(' "\'')
        adresse = re.search(r"[\w.+-]+@([\w.-]+)", roh)
        teile = []
        if anzeige and "@" not in anzeige:
            teile.append(anzeige)
        if adresse:
            lokal = adresse.group(0).split("@", 1)[0]
            domain = adresse.group(1).split(".")
            if len(domain) >= 2:
                teile.append(domain[-2])
            if _falten(lokal) not in _JUNK:
                teile.append(lokal.replace(".", " "))
        for t in teile:
            worte = [w for w in _woerter(t) if len(w) >= 3 and w not in _JUNK and not w.isdigit()]
            if worte:
                zaehler[" ".join(worte)] = zaehler.get(" ".join(worte), 0) + 1
    rangfolge = sorted(zaehler.items(), key=lambda kv: (-kv[1], kv[0]))
    tokens = {}
    for name, n in rangfolge:
        for w in name.split(" "):
            tokens[w] = tokens.get(w, 0) + n
    return [n for n, _ in rangfolge], tokens


def erzeuge(root):
    """Baut die Hausnamenliste frisch aus der Ablage."""
    root = Path(root)
    vault = root.parents[1] if len(root.parents) > 1 else root.parent
    marken = _ordnernamen(root.parent)
    partner = _ordnernamen(vault / "09_Partner") + _ordnernamen(vault / "10_Kunden")
    absender_liste, absender_tokens = _absender(root)
    return {
        "erzeugt": b.now().isoformat(),
        "mitarbeiter": _mitarbeiter(root),
        "marken": marken,
        "partner": partner,
        "absender": absender_liste,
        "absender_tokens": absender_tokens,
    }


def _signatur(root):
    """S-2b P4: Aenderungen an den Quellen (Register, Stammdaten, Woerterbuch, Postfach, Marken-/Partnerordner) ohne Neustart
    erkennen - nur Dateistatus, keine Inhalte lesen."""
    root = Path(root)
    pfade = [b.area(root) / "mitarbeiter.json", b.area(root) / "posteingang.jsonl", root / "betrieb" / "sprache_woerterbuch.json",
             root.parent]
    try:
        vault = root.parents[1]
        pfade += [vault / "09_Partner", vault / "10_Kunden"]
    except IndexError:
        pass
    try:
        import jack_mitarbeiter
        for e in jack_mitarbeiter.register(root).get("mitarbeiter", []):
            pfade.append(jack_mitarbeiter.ordner(root, e.get("id")) / "00_Stammdaten" / "stammdaten.json")
    except Exception:
        pass
    sig = []
    for p in pfade:
        try:
            st = p.stat()
            sig.append((str(p), st.st_mtime_ns, st.st_size))
        except OSError:
            sig.append((str(p), 0, 0))
    return tuple(sig)


def neu_erzeugen(root, schreiben=True):
    """Dienststart: Liste neu bauen, merken und als Diagnose ablegen."""
    daten = erzeuge(root)
    with _LOCK:
        _STAND.update(root=str(Path(root).resolve()), zeit=time.time(), daten=daten, sig=_signatur(root))
    if schreiben:
        try:
            ziel = b.area(root) / "sprache_hausnamen.json"
            oeffentlich = {
                "erzeugt": daten["erzeugt"],
                "hinweis": "Wird bei jedem Dienststart automatisch aus der Ablage neu erzeugt (jack_hausnamen.py). Nicht von Hand pflegen.",
                "mitarbeiter": [{"anzeige": m["anzeige"], "namen": sorted(m["namen"]),
                                 "hoervarianten": sorted(m["hoervarianten"])} for m in daten["mitarbeiter"]],
                "marken": daten["marken"], "partner": daten["partner"],
                "haeufige_absender": daten["absender"][:25],
            }
            ziel.write_text(json.dumps(oeffentlich, ensure_ascii=False, indent=1), encoding="utf-8")
        except (OSError, ValueError):
            pass
    return daten


def hausnamen(root):
    aktuell = str(Path(root).resolve())
    with _LOCK:
        if (_STAND["daten"] is None or _STAND["root"] != aktuell
                or time.time() - _STAND["zeit"] > MAX_ALTER_S
                or _STAND["sig"] != _signatur(root)):
            pass
        else:
            return _STAND["daten"]
    return neu_erzeugen(root, schreiben=False)


# ------------------------------------------------------------------ (a) Whisper
def whisper_prompt(root, basis="", maxzeichen=440):
    """Starthilfe fuer whisper.cpp: bekannte Namen, kurz gehalten (das Modell
    liest nur etwa 220 Token Vorgabe)."""
    try:
        d = hausnamen(root)
    except Exception:
        return basis
    namen = []
    for m in d["mitarbeiter"]:
        # Nur die richtigen Namen - Verhoerer/Alias (Twin, bin) wuerden die Erkennung erst darauf lenken.
        namen.append(m["anzeige"])
        if m.get("vollname"):
            namen.append(m["vollname"])
    namen.extend(n.replace("_", " ") for n in d["marken"])
    namen.extend(n.replace("_", " ") for n in d["partner"][:12])
    namen.extend(n.title() for n in d["absender"][:8])
    text, gesehen = basis.rstrip(" ."), {_falten(w) for w in re.split(r"[ ,]+", basis)}
    for n in namen:
        if not n or _falten(n) in gesehen:
            continue
        if len(text) + len(n) + 2 > maxzeichen:
            break
        text += (", " if text else "") + n
        gesehen.add(_falten(n))
    return text + "."


# ------------------------------------------------------------------ (b) Zuordnung
def _ohne_genitiv(wort):
    """'Dins' -> 'din' (Genitiv-s); kurze Woerter bleiben unveraendert."""
    return wort[:-1] if len(wort) > 3 and wort.endswith("s") else wort


def _rest_tokens(roh):
    tokens = [w for w in _woerter(roh) if w not in FUELLWOERTER]
    return [_ohne_genitiv(w) for w in tokens]


def _kandidaten_personen(d, wort):
    """Personen, deren Name dem gehoerten Wort lautaehnlich ist."""
    treffer = []
    code = koelner(wort)
    for m in d["mitarbeiter"]:
        nah = False
        for t in m["namen"]:
            if len(t) < 3 or len(wort) < 3:
                continue
            if editierabstand(wort, t) <= 1 or (code and code == koelner(t) and len(code) >= 2):
                nah = True
                break
        if nah:
            treffer.append(m)
    return treffer


def pruefe_name(root, roh, art="absender"):
    """Bewertet einen aus dem Satz gezogenen Namensrest.

    art: 'mitarbeiter' (nur Mitarbeiterliste) oder 'absender' (Mitarbeiter,
         Absender im Postfach, Marken, Partner).
    Rueckgabe {'status': ..., 'name': ..., 'vorschlag': ...}
      'leer'      - nach dem Entfernen von Fuellwoertern bleibt kein Name
      'bekannt'   - Name steht in der Liste (Mitarbeiter inkl. Alias, Absender, Marke, Partner);
                    'name' ist der Suchname (bei Personen der Rufname)
      'sicher'    - gehoerte Hoervariante (z. B. bin/denn -> Din) im Namenskontext
      'unsicher'  - nur lautaehnlich: Rueckfrage mit 'vorschlag'
      'unbekannt' - nichts Passendes: nicht raten
    """
    d = hausnamen(root)
    tokens = _rest_tokens(roh)
    if not tokens:
        return {"status": "leer", "name": ""}
    # 1. exakter Name/Alias einer Person
    for m in d["mitarbeiter"]:
        if any(t in m["namen"] for t in tokens):
            return {"status": "bekannt", "name": m["suchname"], "anzeige": m["anzeige"]}
    if art != "mitarbeiter":
        # 2. Absender, Marken, Partner
        andere = set(d["absender_tokens"])
        for n in d["marken"] + d["partner"]:
            andere.update(_woerter(n))
        if any(t in andere for t in tokens):
            return {"status": "bekannt", "name": " ".join(tokens), "anzeige": " ".join(tokens)}
    # 3. Hoervarianten im Namenskontext
    for m in d["mitarbeiter"]:
        # nur wenn der GANZE Namensrest Name oder Hoervariante ist - ein weiteres fremdes Wort ("denn Kunden") macht es unsicher
        if any(t in m["hoervarianten"] for t in tokens) and all(t in m["hoervarianten"] or t in m["namen"] for t in tokens):
            return {"status": "sicher", "name": m["suchname"], "anzeige": m["anzeige"]}
    # 4. Lautaehnlichkeit: nur ein eindeutiger Treffer, nur als Rueckfrage
    gefunden = {}
    for t in tokens:
        for m in _kandidaten_personen(d, t):
            gefunden[m["id"]] = m
    if len(gefunden) == 1:
        m = next(iter(gefunden.values()))
        return {"status": "unsicher", "name": m["suchname"], "anzeige": m["anzeige"],
                "vorschlag": m["anzeige"]}
    return {"status": "unbekannt", "name": " ".join(tokens)}


def ist_pronomen(roh):
    return _falten(roh) in {"ihm", "ihn", "ihr", "ihnen", "dem mitarbeiter", "unserem mitarbeiter",
                            "ihm denn", "ihm hier"}


# ------------------------------------------------------------------ (c) Modell
def namenblock(root):
    """Kurzer Text fuer den Systemtext des Gespraechsmodells."""
    try:
        d = hausnamen(root)
    except Exception:
        return ""
    zeilen = []
    for m in d["mitarbeiter"]:
        gehoert = sorted(m["hoervarianten"] | m["alias"])
        zusatz = (" — wird oft verhört als: " + ", ".join(gehoert)) if gehoert else ""
        voll = (" (" + m["vollname"] + ")") if m.get("vollname") and m["vollname"].lower() != m["anzeige"].lower() else ""
        zeilen.append("- Mitarbeiter " + m["anzeige"] + voll + zusatz)
    if d["marken"]:
        zeilen.append("- Marken: " + ", ".join(n.replace("_", " ") for n in d["marken"]))
    if not zeilen:
        return ""
    return ("Hausnamen (aus der Ablage): Die Spracherkennung verhört Namen oft. Passt ein unbekanntes Wort "
            "im Satz lautlich zu einem dieser Namen und der Zusammenhang stimmt, meine den bekannten Namen; "
            "bei echtem Zweifel frage einmal kurz „Meinst du Din?“ (mit dem passenden Namen). "
            "Das Wort „bin“ in „ich bin …“ ist nie ein Name.\n" + "\n".join(zeilen))


def routing_woerter(root):
    """Kleingeschriebene Namensteile fuer die gestufte Dialogwahl (S-2 P3): alles, was auf Nachschlagen hindeutet -
    Mitarbeiter samt Alias und Hoervarianten, Marken (auch zusammengeschrieben: 'analogwerke'), Partner, Absender."""
    try:
        d = hausnamen(root)
    except Exception:
        return []
    woerter = set()
    for m in d["mitarbeiter"]:
        woerter |= {w for w in (m["namen"] | m["alias"]) if len(w) >= 3}
        woerter |= {w for w in m["hoervarianten"] if len(w) >= 4}
    for n in d["marken"] + d["partner"]:
        teile = [t for t in _woerter(n) if len(t) >= 4]
        woerter |= set(teile)
        if len(teile) > 1:
            woerter.add("".join(teile))
    woerter |= {w for w in d["absender_tokens"] if len(w) >= 5}
    return sorted(woerter)

