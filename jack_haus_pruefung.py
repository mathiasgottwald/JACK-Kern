# -*- coding: utf-8 -*-
"""S-10 (25.09.2026): Nachpruefung gegen erfundene Hausangaben.
Die starke Stufe fuellt im Gespraech manchmal Luecken (Alter, Rangfolge, Zuordnung, Zahlen, 'alles ruhig'). Regeln im Prompt reichen nicht (S-3c: 4 von 60).
Diese Pruefung laeuft NACH der Modellantwort, ohne Modellaufruf: jeder Satz mit einer Hausangabe (Zahl+Haus-Nomen, Datum, Uhrzeit, Dauer/Alter, Rangfolge,
'neu', 'brennt/dringend/alles ruhig') muss in den QUELLEN dieses Durchgangs stehen (Werte der Lage, Werkzeugergebnisse dieses Durchgangs, Frage und
fruehere Aeusserungen des PATRONS - nie JACKs eigene Antworten). Was nicht belegt ist, wird als SATZ entfernt; bleibt nichts uebrig, sagt JACK ehrlich, dass er es nicht belegen kann.
Grenze (offen gesagt): Muster, keine Garantie. Zuordnungsfehler ohne Zahl/Alter/Rang ('Mails von Din' statt 'Freigaben') und freie Umschreibungen erkennt sie nur teilweise.
"""
import json
import re

FALLBACK = "Dazu habe ich gerade keine belegte Angabe. Sag Bescheid, dann prüfe ich es."

_ZAHLWOERTER = {"null": 0, "zwei": 2, "drei": 3, "vier": 4, "fünf": 5, "fuenf": 5, "sechs": 6, "sieben": 7, "acht": 8, "neun": 9, "zehn": 10, "elf": 11, "zwölf": 12, "zwoelf": 12,
                "dreizehn": 13, "vierzehn": 14, "fünfzehn": 15, "fuenfzehn": 15, "sechzehn": 16, "siebzehn": 17, "achtzehn": 18, "neunzehn": 19,
                "zwanzig": 20, "dreißig": 30, "dreissig": 30, "vierzig": 40, "fünfzig": 50, "fuenfzig": 50, "sechzig": 60, "siebzig": 70, "achtzig": 80, "neunzig": 90, "hundert": 100}
_EINER = {"ein": 1, "eins": 1, "zwei": 2, "drei": 3, "vier": 4, "fünf": 5, "fuenf": 5, "sechs": 6, "sieben": 7, "acht": 8, "neun": 9}
_ZEHNER = {k: v for k, v in _ZAHLWOERTER.items() if v in (20, 30, 40, 50, 60, 70, 80, 90)}
_MONATE = {"januar": 1, "februar": 2, "maerz": 3, "märz": 3, "april": 4, "mai": 5, "juni": 6, "juli": 7, "august": 8, "september": 9, "oktober": 10, "november": 11, "dezember": 12}


def _unter_hundert(w):
    if w in _ZAHLWOERTER and _ZAHLWOERTER[w] < 100:
        return _ZAHLWOERTER[w]
    m = re.fullmatch(r"(ein|zwei|drei|vier|fünf|fuenf|sechs|sieben|acht|neun)und(zwanzig|dreißig|dreissig|vierzig|fünfzig|fuenfzig|sechzig|siebzig|achtzig|neunzig)", w)
    if m:
        return _EINER[m.group(1)] + _ZEHNER[m.group(2)]
    return None


def _zahlwort(wort):
    """'zwei' -> 2, 'vierunddreissig' -> 34, 'hundertzwanzig' -> 120, 'zweihundert' -> 200; sonst None. 'ein/eine' ist ein Artikel und zaehlt nicht."""
    w = wort.lower()
    z = _unter_hundert(w)
    if z is not None:
        return z
    m = re.fullmatch(r"(?:(ein|zwei|drei|vier|fünf|fuenf|sechs|sieben|acht|neun))?hundert(?:und)?(.*)", w)
    if m:
        basis = (_EINER[m.group(1)] if m.group(1) else 1) * 100
        rest = m.group(2)
        if not rest:
            return basis
        r = _unter_hundert(rest) if rest not in ("ein", "eins") else 1
        return basis + r if r is not None else None
    return None


def norm(text):
    t = str(text or "").lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        t = t.replace(a, b)
    return re.sub(r"[\s ]+", " ", t)


def _mit_ziffern(text):
    """Zahlwoerter durch Ziffern ersetzen ('zwei Mails' -> '2 mails'), ISO-Daten auch als 'TT.MM.' und Dezimalkomma als Punkt - fuer Antwort UND Quellen gleich."""
    t = norm(text)
    t = re.sub(r"\b(\d{4})-(\d{2})-(\d{2})(?!\d)", lambda m: "%s-%s-%s %s.%s." % (m.group(1), m.group(2), m.group(3), m.group(3), m.group(2)), t)
    t = re.sub(r"(\d),(\d)", r"\1.\2", t)

    def ersetze(m):
        z = _zahlwort(m.group(0))
        return str(z) if z is not None else m.group(0)
    return re.sub(r"[a-z]+", ersetze, t)


NOMEN = {
    "freigabe": r"freigaben?|genehmigungen?",
    "mail": r"[\w-]*mails?|nachrichten?",
    "auftrag": r"auftr(?:ae|ä)ge?n?",
    "termin": r"termine?n?",
    "tag": r"tage?n?",
    "dollar": r"dollar|usd|euro|prozent",
    "stunde": r"stunden?",
    "minute": r"minuten?",
    "woche": r"wochen?",
    "thema": r"themen|sachen|dinge|punkte|rechnungen|monate?n?",
}
_NOM = "|".join("(?P<%s>%s)" % (k, v) for k, v in NOMEN.items())
_ZAHL_NOMEN = re.compile(r"\b(\d+(?:\.\d+)?)\s+(?:[a-z-]+\s+){0,2}?(" + _NOM + r")\b")
_NOMEN_ZAHL = re.compile(r"\b(" + _NOM + r")\W{1,3}(\d+(?:\.\d+)?)\b")
_KEIN = re.compile(r"\bkein(?:e|en|em|er|es)?\s+(?:[a-z-]+\s+){0,2}?(" + _NOM + r")\b")
_NUR_EINE = re.compile(r"\b(?:nur|genau|erst|noch|einzige[nrms]?)\s+(?:eine?n?|einzige[nrms]?)\s+(?:[a-z-]+\s+){0,2}?(" + _NOM + r")\b")

VAGE = re.compile(
    r"\bein paar (?:tage|tagen|stunden|wochen)\b|\b(?:eine|ne) weile\b|\bschon (?:wieder )?(?:lange|laenger|ewig|eine weile)\b|\bseit (?:tagen|wochen|langem|laengerem|geraumer zeit|ewigkeiten)\b|"
    r"\bseit (?:ueber |mehr als |etwa |fast )?(?:einer|einem|einen) (?:woche|monat|tag)\b|\b(?:ueber|mehr als) (?:eine woche|einen monat)\b|\b(?:mehrere|einige) (?:tage|tagen|wochen)\b|"
    r"\b(?:seit|vor) (?:kurzem|langem)\b|\bliegen geblieben\b|\bziemlich lange\b|\bueberfaellig\b|\bseit ewigkeiten\b|\bvorgestern\b|\bletzte woche\b|\bletzten monat\b|\bneulich\b|\bletztens\b|\bliegt schon\b")
RANG = re.compile(r"\b(?:am (?:laengsten|dringendsten|aeltesten|wichtigsten)|aeltere[nrms]?|neuere[nrms]?|aelteste[nrms]?|laengste[nrms]?|dringendste[nrms]?|wichtigste[nrms]?|neueste[nrms]?|hoechste[nrs]? prioritaet|zuerst kam)\b")
DATUM = re.compile(r"\b(\d{1,2})\.\s?(\d{1,2})\.?(?:\s?(\d{2,4}))?(?![\d:])(?!\s?uhr)", re.I)
MONATSDATUM = re.compile(r"\b(\d{1,2})\.?\s+(januar|februar|maerz|april|mai|juni|juli|august|september|oktober|november|dezember)\b", re.I)
UHR = re.compile(r"\b(\d{1,2})(?:[:.](\d{2}))?\s*uhr\b|\bum (\d{1,2})[:.](\d{2})\b")
DAUER = re.compile(r"\b(?:seit|vor)\s+(?:dem\s+|den\s+|ueber\s+|etwa\s+|ca\.?\s+)?(\d+)\s+(tag|tagen|stunde|stunden|woche|wochen|minute|minuten|monat|monaten)\b")
GESTERN = re.compile(r"\b(?:seit|von)\s+(gestern|vorgestern|heute|montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag)\b")
MENGE_VAGE = re.compile(r"\b(?:groesstenteils|meistenteils|ueberwiegend|hauptsaechlich|zum grossen teil|die meisten|fast alle)\b")
HAUS_NOMEN = re.compile(r"\b(?:" + NOMEN["freigabe"] + "|" + NOMEN["mail"] + "|" + NOMEN["auftrag"] + r"|themen|sachen)\b")
NEU = re.compile(r"\bneue[nrms]?\s+(?:[a-z-]+\s+)?(?:mails?|nachrichten?|freigaben?|auftr(?:ae)ge?)\b")
BRENNT_JA = re.compile(r"\b(?:brennt|brennen|brennend\w*|dringend\w*|brenzlig|eilig\w*|feuer)\b")
RUHIG = re.compile(r"\b(?:eilt (?:nichts|nicht)|eilen nicht|keine eile|nicht eilig|nichts eilig\w*|alles (?:im )?(?:gruenen|ruhig|entspannt|in ordnung|klar (?:hier|bei|so weit|soweit))|sonst ruhig|ruhig hier|"
                   r"ruhige lage|laeuft (?:alles )?ruhig|nichts akut\w*|nichts anbrennt|kein stress|nichts,? (?:das|was) (?:dich )?aufhaelt|nicht dringend|gruener bereich|nichts dringend\w*|"
                   r"laufen (?:dir )?nicht weg|laeuft (?:dir )?nicht weg|warten (?:geduldig|einfach|ruhig)\b|eilen? aber nicht|(?:nichts (?:liegt|steht) (?:hier |gerade |jetzt )?an|(?:liegt|steht) (?:gerade |jetzt |hier )?nichts an)|nichts,? (?:was|das) (?:du )?(?:jetzt |noch )?(?:anschieben|anfassen|erledigen|tun) (?:musst|muesstest)|"
                   r"passt so weit|passt soweit|nichts weiter auf dem tisch|nichts neues|sonst ist(?:'s| es) ruhig|nichts,? was (?:du )?(?:heute |jetzt )?(?:noch )?(?:von dir )?(?:gemacht werden muss|zu tun ist)|alles (?:gut|in ordnung) hier|der rest laeuft|nichts anzufassen|nichts anzuschieben|kein handlungsbedarf|nichts eilt|nichts dringend\w*|nichts,? was (?:du )?(?:jetzt )?noch (?:anfassen|anschieben))")
VERNEINT = re.compile(r"\b(?:nichts|nix|kein\w*|nirgends|niemand)\b")
BEDINGT = re.compile(r"\b(?:wenn|falls|sobald|sollte|solltest|ausser)\b")
_STOP = {"dringend", "dringendes", "brennt", "brennen", "eilig", "nichts", "keine", "gerade", "aktuell", "gerne", "sonst", "warten", "liegt", "bleibt", "steht", "geht", "dieser", "diese", "dieses", "haben", "werden", "wurde", "kannst", "willst"}

_ABK = re.compile(r"(?:\bz\.\s?B\.|\bca\.|\bNr\.|\bd\.\s?h\.|\bu\.\s?a\.|\bvgl\.|\bbzw\.|\busw\.)$", re.I)
_DATUM_ENDE = re.compile(r"\b(?:am|seit|dem|vom|bis|ab|den|zum|vor|nach|um|ueber|fuer)\s+\d{1,2}\.(?:\d{1,2}\.)?$", re.I)
_PRONOMEN = {"Er", "Sie", "Es", "Das", "Die", "Der", "Ich", "Du", "Wir", "Sonst", "Alles", "Nichts", "Man", "Dann", "Aber", "Und", "Sag", "Soll", "Willst", "Wenn", "Falls", "Ihr", "Ein", "Eine", "Bei", "Ansonsten"}


def saetze(text):
    """Satzweise teilen; ein Punkt nach Abkuerzung oder Datum mit Praeposition ('seit dem 17.09.') beendet keinen Satz, wenn danach klein weiterging oder kein Pronomen folgt.
    'Offen sind genau 10. Die wartet ...' bleibt zwei Saetze."""
    teile, aus = [t for t in re.split(r"(?<=[.!?])\s+", str(text or "").strip()) if t], []
    for t in teile:
        vorher = aus[-1] if aus else ""
        erstes = re.match(r"[\wÄÖÜäöüß]+", t)
        wort = erstes.group(0) if erstes else ""
        if aus and (_ABK.search(vorher) or (_DATUM_ENDE.search(vorher) and (wort[:1].islower() or wort[:1].isdigit() or wort not in _PRONOMEN))):
            aus[-1] += " " + t
        else:
            aus.append(t)
    return aus


def _werte(o):
    """Alle WERTE (nie die Schluessel) einer verschachtelten Lage als Text."""
    if isinstance(o, dict):
        return " ".join(_werte(v) for v in o.values())
    if isinstance(o, (list, tuple)):
        return " ".join(_werte(v) for v in o)
    return "" if o is None else str(o)


class Quellen:
    """Belegte Fakten dieses Durchgangs. lage: dict (jack_sprach_lage) oder None; texte: Frage des Patrons, fruehere Patron-Aeusserungen, Werkzeugergebnisse."""

    def __init__(self, lage=None, texte=(), ruhig_erlaubt=None):
        self.lage = lage if isinstance(lage, dict) else {}
        self.hat_lage = bool(self.lage)
        self.tools = _mit_ziffern(" ".join(str(t) for t in texte))
        self.lage_text = _mit_ziffern(_werte(self.lage))
        self.text = (self.lage_text + " " + self.tools).strip()
        self.fakten = _fakten(self.lage)
        self.aus_texten = _zahlen_je_nomen(self.tools)
        self.zahlen_alle = set(re.findall(r"(?<![\d.])\d+(?:\.\d+)?(?!\d)", self.text))
        # S-11: 'nichts eilt / alles ruhig' ist nur erlaubt, wenn die Daten es zeigen (jack_sprach_zahlen.ruhig_erlaubt); sonst gilt die Lage-Liste 'brennt'
        self.brennt = (not ruhig_erlaubt) if ruhig_erlaubt is not None else bool(self.lage.get("brennt"))
        self.brennt_text = _mit_ziffern(_werte(self.lage.get("brennt")))
        self.abschnitt = {"freigabe": _mit_ziffern(_werte(self.lage.get("freigaben")) + " " + _werte((self.lage.get("auftraege") or {}).get("freigabe"))) + " " + self.tools,
                          "mail": _mit_ziffern(_werte(self.lage.get("mitarbeiter"))) + " " + self.tools,
                          "termin": _mit_ziffern(_werte(self.lage.get("termine"))) + " " + self.tools,
                          "guthaben": _mit_ziffern(_werte(self.lage.get("guthaben"))) + " " + self.tools}

    def bereich(self, satz_norm):
        """Der Lage-Abschnitt, um den es im Satz geht (sonst alles)."""
        for k, wort in (("freigabe", "freigabe"), ("mail", "mail"), ("mail", "din"), ("termin", "termin"), ("guthaben", "guthaben"), ("guthaben", "dollar")):
            if wort in satz_norm:
                return self.abschnitt[k]
        return self.text


def _zahlen_je_nomen(text):
    f = {k: set() for k in NOMEN}
    for m in _ZAHL_NOMEN.finditer(text):
        klasse = next(k for k in NOMEN if m.group(k))
        f[klasse].add(m.group(1))
    for m in _NOMEN_ZAHL.finditer(text):
        klasse = next(k for k in NOMEN if m.group(k))
        f[klasse].add(m.group(next(i for i in range(1, m.re.groups + 1) if m.group(i) and re.fullmatch(r"\d+(?:\.\d+)?", m.group(i)))))
    return f


def _fakten(lage):
    """Erlaubte Zahlen je Nomen-Klasse aus den strukturierten Werten der Lage."""
    f = {k: set() for k in NOMEN}
    try:
        fr = lage.get("freigaben") or {}
        if isinstance(fr.get("anzahl"), int):
            f["freigabe"].add(fr["anzahl"])
        a = lage.get("auftraege") or {}
        for k, v in a.items():
            if isinstance(v, dict) and isinstance(v.get("anzahl"), int):
                f["auftrag"].add(v["anzahl"])
                if k == "freigabe":
                    f["freigabe"].add(v["anzahl"])
        for m in lage.get("mitarbeiter") or []:
            if isinstance(m.get("mails_insgesamt"), int):
                f["mail"].add(m["mails_insgesamt"])
            if m.get("letzte"):
                f["mail"].add(len(m["letzte"]))
        t = lage.get("termine") or {}
        for k in ("heute", "morgen"):
            if isinstance(t.get(k), list):
                f["termin"].add(len(t[k]))
        g = lage.get("guthaben") or {}
        if isinstance(g.get("reichweite_tage"), int):
            f["tag"].add(g["reichweite_tage"])
        try:
            r = float(str(g.get("rest_usd")).replace(",", "."))
            f["dollar"].update({int(r), round(r)})
        except (TypeError, ValueError):
            pass
    except AttributeError:
        pass
    return f


def _zahl_ok(zahl_text, klasse, q):
    try:
        z = float(zahl_text)
    except ValueError:
        return True
    ganz = int(z) if z == int(z) else None
    if ganz is not None and ganz in q.fakten.get(klasse, set()):
        return True
    if klasse == "dollar" and (int(z) in q.fakten["dollar"] or round(z) in q.fakten["dollar"]):
        return True
    for beleg in q.aus_texten.get(klasse, ()):                    # Werkzeugergebnis/Patron nennt dieselbe Zahl mit demselben Nomen
        try:
            if float(beleg) == z:
                return True
        except ValueError:
            pass
    if klasse in ("tag", "stunde", "minute", "woche") and re.search(r"\b%s\s+%s" % (re.escape(zahl_text), NOMEN[klasse]), q.text):
        return True                                                # 'vor 2 Tagen' steht als Text in der Lage
    if klasse == "thema":
        return zahl_text in q.zahlen_alle
    return False


def _rang_ok(kern, satz_n, q):
    if "aeltest" in kern and re.search(r"freigabe|thema|sache|angefordert|wartet|liegt", satz_n) and q.lage.get("freigaben", {}).get("aelteste_freigabe"):
        return True
    if "neuest" in kern and ("mail" in satz_n or "din" in satz_n) and any(m.get("neueste_mail") for m in q.lage.get("mitarbeiter") or []):
        return True
    return kern in q.tools


def unbelegt(satz, q):
    """Liste der Gruende, warum ein Satz eine unbelegte Hausangabe enthaelt (leer = ok)."""
    n = norm(satz)
    z = _mit_ziffern(satz)
    gruende = []
    if not q.hat_lage and not q.tools:
        return gruende          # ohne jede Quelle wird nicht geprueft
    bereich = q.bereich(n)
    for m in _ZAHL_NOMEN.finditer(z):
        klasse = next(k for k in NOMEN if m.group(k))
        if not _zahl_ok(m.group(1), klasse, q):
            gruende.append("Zahl %s %s" % (m.group(1), klasse))
    for m in _NOMEN_ZAHL.finditer(z):
        klasse = next(k for k in NOMEN if m.group(k))
        zahl = next(m.group(i) for i in range(1, m.re.groups + 1) if m.group(i) and re.fullmatch(r"\d+(?:\.\d+)?", m.group(i)))
        if not _zahl_ok(zahl, klasse, q):
            gruende.append("Zahl %s %s" % (zahl, klasse))
    for m in _KEIN.finditer(z):
        klasse = next(k for k in NOMEN if m.group(k))
        erlaubt = set(q.fakten.get(klasse) or ())
        if klasse == "termin":                                      # 'morgen'/'heute' im Satz -> nur die Zahl dieses Tages
            tag = "morgen" if "morgen" in n else "heute" if "heute" in n else None
            if tag and isinstance((q.lage.get("termine") or {}).get(tag), list):
                erlaubt = {len(q.lage["termine"][tag])}
        if erlaubt and 0 not in erlaubt and "0" not in q.aus_texten.get(klasse, ()) and klasse in ("freigabe", "termin", "auftrag", "mail"):
            gruende.append("'keine %s', aber die Lage nennt welche" % klasse)
    for m in _NUR_EINE.finditer(z):
        klasse = next(k for k in NOMEN if m.group(k))
        if klasse in ("freigabe", "termin", "auftrag", "mail") and q.fakten.get(klasse) and 1 not in q.fakten[klasse] and "1" not in q.aus_texten.get(klasse, ()):
            gruende.append("'nur eine %s', aber die Lage nennt eine andere Zahl" % klasse)
    for m in VAGE.finditer(n):
        if m.group(0) not in q.text:
            gruende.append("vage Dauer: " + m.group(0))
    for m in RANG.finditer(n):
        if not _rang_ok(m.group(0), n, q):
            gruende.append("Rangfolge: " + m.group(0))
    for m in DAUER.finditer(z):
        if not re.search(r"\b%s\s+%s" % (m.group(1), re.escape(m.group(2)[:4])), bereich):
            gruende.append("Dauer: " + m.group(0))
    uhrzeiten = [u for u in re.findall(r"\b(\d{1,2})[:.](\d{2})\b", z)]
    for m in GESTERN.finditer(n):
        if uhrzeiten and all(re.search(r"\b0?%d[:.]%s\b" % (int(h_), mm), q.text) for h_, mm in uhrzeiten) and m.group(1) in q.text:
            continue                                              # 'seit heute frueh 06:26' - genau diese Zeit steht in der Lage
        if m.group(1) not in bereich and m.group(0) not in q.text:
            gruende.append("Zeit: " + m.group(0))
    for m in DATUM.finditer(satz):
        tag, mon = int(m.group(1)), int(m.group(2))
        if 1 <= tag <= 31 and 1 <= mon <= 12 and not re.search(r"\b0?%d\.\s?0?%d\b" % (tag, mon), q.text):
            gruende.append("Datum %d.%d." % (tag, mon))
    for m in MONATSDATUM.finditer(n):
        tag, mon = int(m.group(1)), _MONATE[m.group(2)]
        if not re.search(r"\b0?%d\.\s?0?%d\b" % (tag, mon), q.text):
            gruende.append("Datum %d. %s" % (tag, m.group(2)))
    for m in UHR.finditer(n):
        std = m.group(1) or m.group(3)
        if not re.search(r"\b0?%s(?:[:.]\d\d| uhr)" % int(std), q.text):
            gruende.append("Uhrzeit %s" % m.group(0))
    if MENGE_VAGE.search(n) and HAUS_NOMEN.search(n):
        gruende.append("vage Mengenangabe: " + MENGE_VAGE.search(n).group(0))
    # Alter der aeltesten Freigabe auf ALLE uebertragen: '19 Freigaben warten seit heute frueh 06:26'
    ges = q.lage.get("freigaben", {}).get("anzahl") if q.hat_lage else None
    if isinstance(ges, int):
        for m in re.finditer(r"\b(\d+)\s+(?:[a-z-]+\s+)?(?:freigaben?|sachen|themen)\b([^.!?]*)", z):
            if int(m.group(1)) == ges and re.search(r"\bseit\b|\bangefordert\b", m.group(2)) and not re.search(r"aelteste|erste[rns]?\b|davon|darunter|unter anderem", z):
                gruende.append("Alter der aeltesten Freigabe auf alle %d uebertragen" % ges)
    for m in NEU.finditer(n):
        if m.group(0) not in q.text:
            gruende.append("'neu': " + m.group(0))
    if True:
        teile = re.split(r"\s*[,;\u2013\u2014]\s*|\s-\s", n)
        for i, teil in enumerate(teile):                                       # je Teilsatz: ein 'wenn ...'-Teil macht den Rest des Satzes nicht unpruefbar
            if not teil or BEDINGT.search(teil):
                continue
            if satz.rstrip().endswith("?") and (len(teile) <= 2 or i == len(teile) - 1):
                continue                                                       # eine Frage behauptet nichts (nur der Teilsatz, der die Frage IST)
            gefunden = BRENNT_JA.search(teil)
            if gefunden:
                inhalt = {w for w in re.findall(r"[a-z]{5,}", teil) if w not in _STOP}
                if VERNEINT.search(n):                                    # 'Nichts, was brennt': die Verneinung steht im Nachbar-Teilsatz
                    if q.brennt:
                        gruende.append("'brennt' verneint, aber die Lage nennt etwas")
                elif not q.brennt or not (inhalt & set(re.findall(r"[a-z]{5,}", q.brennt_text))):
                    gruende.append("'%s' ohne Beleg in der Lage" % gefunden.group(0))
        if q.brennt and not (satz.rstrip().endswith("?") and len(teile) <= 2) and not re.search(r"\bhalt\w*\b[^.]{0,20}\balles\b", n):      # 'ich halt alles ruhig' ist eine Zusage, keine Lagebehauptung
            for m in RUHIG.finditer(n):
                vor = re.split(r"\s*[;\u2013\u2014]\s*|\s-\s|,\s", n[:m.start()])[-1]
                nach = re.split(r"\s*[,;\u2013\u2014]\s*|\s-\s", n[m.end():])[0]
                if not BEDINGT.search(vor + " " + m.group(0) + " " + nach):
                    gruende.append("'alles ruhig' verneint, aber die Lage nennt etwas: " + m.group(0))
                    break
    return gruende


def pruefe(antwort, q, ersatz=None):
    """-> (text, entfernt): entfernt = Liste (Satz, Gruende). Nur Saetze mit unbelegten Hausangaben fallen weg.
    S-11: ein Satz mit unbelegter Ruhe-Aussage ('nichts eilt', 'alles ruhig', 'kein Handlungsbedarf') wird durch `ersatz` (lokaler Lagesatz) ersetzt - einmal, an seiner Stelle."""
    behalten, entfernt, ersetzt = [], [], False
    for s in saetze(antwort):
        g = unbelegt(s, q)
        if g:
            entfernt.append((s, g))
            if ersatz and not ersetzt and any(x.startswith(("'alles ruhig'", "'brennt' verneint")) for x in g):
                behalten.append(ersatz)
                ersetzt = True
        else:
            behalten.append(s)
    if not entfernt:
        return antwort, []
    return (" ".join(behalten) if behalten else FALLBACK), entfernt
