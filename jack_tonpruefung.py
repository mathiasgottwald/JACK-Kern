"""S-3 P2: maschinelle Floskel- und Tonpruefung fuer GESPROCHENE Antworten. Kein Modell, kein Netz, 0 USD.
Aufruf: pruefe(antwort, frage='') -> Liste von (regel, fundstelle). Leere Liste = sauber.
Gilt fuer Testlaeufe (Persona-Regeln: entscheidungen/2026-09-24_sprache_PERSONA.md)."""
import re

FLOSKELN = re.compile(r"\b(laut ablage|gerne|selbstverständlich|selbstverstaendlich|ich hoffe|gute frage)\b", re.I)
AUFZAEHLUNG = re.compile(
    r"(?m)^\s*(?:[-*•–—]\s+|\d+\s*[.)]\s+)|\b(?:erstens|zweitens|drittens)\b|\(\d\)", re.I)
BEGRUESSUNG = re.compile(
    r"^\W*(?:guten\s+(?:morgen|tag|abend)|morgen|moin|servus|hallo|hi|hey)\b[^.!?]{0,40}", re.I)
AUSFUEHRLICH = re.compile(
    r"ausführlich|ausfuehrlich|im detail|genau(?:er)?\b|erklär|erklaer|erzähl|erzaehl|alles|zusammenfass|"
    r"beschreib|schritt für schritt|schritt fuer schritt|listet|liste|überblick|ueberblick|warum|wie funktioniert|"
    r"was steht|\blies\b|vorlesen|bericht", re.I)
INTERN = re.compile(r"\b(?:Kasten|Endstelle|Stufe 0|Befehl erkannt)\b|/Users/|\.(?:md|py|json|jsonl)\b")
PATRON = re.compile(r"\bpatron\b", re.I)


def woerter(text):
    return len(re.findall(r"\S+", text or ""))


def patron_ausserhalb_begruessung(antwort):
    """True, wenn 'Patron' vorkommt und NICHT in einer Begruessung am Anfang steht."""
    if not PATRON.search(antwort):
        return False
    m = BEGRUESSUNG.match(antwort)
    rest = antwort[m.end():] if m else antwort
    return bool(PATRON.search(rest))


def pruefe(antwort, frage=""):
    fehler = []
    if patron_ausserhalb_begruessung(antwort):
        fehler.append(("patron", "Patron außerhalb einer Begrüßung"))
    for m in FLOSKELN.finditer(antwort):
        fehler.append(("floskel", m.group(0)))
    for m in AUFZAEHLUNG.finditer(antwort):
        fehler.append(("aufzaehlung", m.group(0).strip()))
    if woerter(antwort) > 60 and not AUSFUEHRLICH.search(frage or ""):
        fehler.append(("laenge", "%d Wörter ohne Bitte um Ausführlichkeit" % woerter(antwort)))
    for m in INTERN.finditer(antwort):
        fehler.append(("intern", m.group(0)))
    return fehler


def auswerten(paare):
    """paare: [(frage, antwort)] -> dict mit Treffern je Regel, Trefferquote und Patron-Quote."""
    treffer, je_regel, patron = [], {}, 0
    for frage, antwort in paare:
        f = pruefe(antwort, frage)
        if PATRON.search(antwort):
            patron += 1
        if f:
            treffer.append({"frage": frage, "antwort": antwort, "fehler": f})
            for regel, _ in f:
                je_regel[regel] = je_regel.get(regel, 0) + 1
    n = len(paare)
    return {"antworten": n, "mit_treffer": len(treffer), "treffer_quote": (len(treffer) / n) if n else 0.0,
            "patron_quote": (patron / n) if n else 0.0, "je_regel": je_regel, "treffer": treffer}
