# -*- coding: utf-8 -*-
"""S-3b P2 / S-3c P4: deterministischer Sprechfilter - NUR Formkorrektur, kein Inhalt, kein Modell.
Angewendet auf den gesprochenen UND den angezeigten Text (beide Dialogstufen), satzweise im Strom (Satzfilter) und auf den Endtext (filtere).
Regeln:
 (a) 'Gerne,' / 'Gern,' / 'Sehr gerne' am Satzanfang entfernen, Grossschreibung korrigieren. 'Gern geschehen' bleibt.
 (b) Anrede ', Patron' am Satzende und 'Patron, ' am Satzanfang entfernen - ausser in einer echten Begruessung am Gesprächsbeginn
     (anfang=True: erste Antwort einer Sitzung, Satz beginnt mit Guten Morgen/Morgen/Hallo/Moin/Servus/Guten Tag/Guten Abend).
     'des Patrons', 'der Patron hat ...' (Substantiv) bleiben.
 (c) Aufzaehlungszeichen (- * •) und Nummerierungen am Zeilenanfang werden Fliesstext: jeder Punkt ein eigener Satz; Fettdruck-Sterne fallen weg.
     S-3c: eine Nummer zaehlt NUR als Liste, wenn mindestens zwei aufeinanderfolgende Zeilen fortlaufend nummeriert sind (1./2.);
     '3. Quartal ...' und '1. FC Koeln' bleiben.
 (d) 'laut Ablage' entfernen (mitten im Satz samt Komma; am Satzanfang mit Komma weg, ohne Komma 'Nach meinem Stand' - gleiche Grammatik).
Unveraendert bleiben: Text in Anfuehrungszeichen, Zahlen, Markennamen.
 S-3c: ein Satz, der nach dem Filtern nur noch aus Anrede/Floskel besteht ('Sehr gerne, Patron.'), faellt ganz weg, wenn danach noch Inhalt
 folgt; folgt nichts mehr, wird er zu 'Mach ich.'. Der Strom (Satzfilter) und der Endtext (filtere) sind dieselbe Maschine."""
import re

_ZITAT = re.compile(r'„[^“”]*[“”]|‚[^‘’]*[‘’]|"[^"]*"|“[^”“]*[”“]|[«»][^«»]*[«»]|[‹›][^‹›]*[‹›]')
_ABK = ("z.b", "d.h", "u.a", "ca", "nr", "bzw", "usw", "etc", "vgl", "dr", "prof", "u.v.m", "s.o", "o.ä", "evtl", "ggf")
_MARKER = re.compile(r'^(?:[-*•–—]|\d{1,2}[.)])\s+')
_MONAT = re.compile(r'^\d{1,2}\.\s+(?:januar|februar|märz|maerz|april|mai|juni|juli|august|september|oktober|november|dezember|jan|feb|mär|apr|jun|jul|aug|sep|okt|nov|dez)\b', re.I)
_BEGRUESSUNG = re.compile(r'^\W*(?:guten\s+(?:morgen|tag|abend)|morgen|moin|servus|hallo|hi|hey)\b', re.I)
_GERNE = re.compile(r'^(?:sehr\s+)?gerne?\b(?!\s+geschehen)\s*[,.!–—-]*\s*', re.I)
_PATRON_ENDE = re.compile(r',\s*\bPatron\b(?=\s*[.!?…]|\s*$)')     # NUR mit Komma (Anrede); 'entscheidet der Patron.' bleibt
_PATRON_ANFANG = re.compile(r'^Patron\s*,\s*')
_ABLAGE = re.compile(r'\blaut\s+Ablage\b', re.I)


def _ende(text, i):
    """True, wenn text[i] ('.', '!' oder '?') ein Satzende ist (nicht Ordnungszahl/Abkuerzung)."""
    c = text[i]
    if c == '.':
        wort = re.search(r'([\wäöüÄÖÜß.]+)$', text[:i])
        w = (wort.group(1) if wort else '').lower().strip('.')
        if w.isdigit() or w in _ABK or len(w) == 1 and w.isalpha():
            return False
    return True


def zerlege(text):
    """Liefert [(einheit, trenner)]: Trenner = Leerraum nach dem Satzende bzw. Zeilenumbruch. Jeder Text ergibt sich wieder aus der Verkettung."""
    teile, start, i, n, zitat = [], 0, 0, len(text), False
    while i < n:
        c = text[i]
        if c in '„‚':
            zitat = True
        elif c in '”‘’':
            zitat = False
        elif c in '“«»‹›"':
            zitat = not zitat
        if zitat:
            i += 1
            continue
        if c == '\n':
            j = i
            while j < n and text[j] in ' \t\r\n':
                j += 1
            teile.append((text[start:i], text[i:j])); start = i = j
            continue
        if c in '.!?' and i + 1 < n and text[i + 1] in ' \t\r\n' and _ende(text, i):
            j = i + 1
            while j < n and text[j] in ' \t\r\n':
                j += 1
            teile.append((text[start:i + 1], text[i + 1:j])); start = i = j
            continue
        i += 1
    if start < n:
        teile.append((text[start:], ''))
    return teile


def _sep(sep):
    """Ein einzelner Zeilenumbruch im gesprochenen Text ist ein Leerzeichen; Absaetze (>= 2 Umbrueche) bleiben."""
    return ' ' if sep.count('\n') == 1 else sep


def _gross(s):
    return s[:1].upper() + s[1:] if s else s


def _einheit(u, zeilenanfang, erste, anfang, liste=False):
    """Filtert eine Einheit; liefert (Text, entfernt). Geschuetzte Zitate werden vorher maskiert. liste=True: Marker am Zeilenanfang entfernen."""
    if not u.strip():
        return u, False
    zitate = []

    def maske(m):
        zitate.append(m.group(0)); return '\u0000%d\u0000' % (len(zitate) - 1)
    t = _ZITAT.sub(maske, u)
    lead = t[:len(t) - len(t.lstrip())]
    t = t.lstrip()
    entfernt = False
    if zeilenanfang:                                 # (c)
        m = _MARKER.match(t)
        if m and (liste or not m.group(0).strip()[:1].isdigit()) and not _MONAT.match(t):
            t = t[m.end():]
            if t and t[-1] not in '.!?…:;':
                t += '.'
    t = re.sub(r'\*\*|__', '', t)                    # Fettdruck
    t, n_ = _GERNE.subn('', t, count=1)              # (a)
    if n_:
        t = _gross(t)
        entfernt = True
    gruss = bool(anfang and erste and _BEGRUESSUNG.match(t))
    if not gruss:                                    # (b)
        t, n1 = _PATRON_ANFANG.subn('', t)
        t, n2 = _PATRON_ENDE.subn('', t)
        if n1:
            t = _gross(t)
        entfernt = entfernt or bool(n1 or n2)
    # (d)
    if _ABLAGE.match(t):
        rest = _ABLAGE.sub('', t, count=1)
        t = _gross(rest.lstrip(' ,')) if rest.lstrip().startswith(',') else 'Nach meinem Stand' + rest
        entfernt = True
    t = re.sub(r',\s*laut\s+Ablage\s*,', ' ', t, flags=re.I)
    t = re.sub(r',?\s*\blaut\s+Ablage\b', '', t, flags=re.I)
    t = re.sub(r'\s{2,}', ' ', t).strip()
    t = re.sub(r'\s+([,.!?])', r'\1', t)
    if not re.search(r'\w', re.sub(r'\u0000\d+\u0000', 'x', t)) and not zitate:
        return '', entfernt
    t = re.sub(r'\u0000(\d+)\u0000', lambda m: zitate[int(m.group(1))], t)
    return lead + t, entfernt


_NUR_ANREDE = re.compile(r'^\W*Patron\W*$')
_NR = re.compile(r'^\s*(\d{1,2})[.)]\s+')


def _nummer(u, zeilenanfang):
    """Nummer einer nummerierten Zeile (ohne Datum) oder None."""
    if not zeilenanfang:
        return None
    m = _NR.match(u)
    return int(m.group(1)) if m and not _MONAT.match(u.lstrip()) else None


class Satzfilter:
    """Strom: feed(delta) liefert fertige, gefilterte Saetze; flush() den Rest. Verkettung == filtere(gesamter Text) (filtere ist derselbe Weg)."""

    def __init__(self, anfang=False):
        self.anfang, self.puffer, self.k, self.zeilenanfang, self.roh = anfang, '', 0, True, ''
        self.q = []                 # fertige Einheiten, die auf ihre Nachbarn warten: (u, sep, zeilenanfang, k, nummer)
        self.vor_nummer = None      # Nummer der vorigen Zeile, wenn sie unmittelbar davor stand
        self.emittiert = False
        self.mach_ich = False       # eine Einheit bestand nur aus Anrede/Floskel und es kam seither kein Inhalt

    def _ausgeben(self, u, sep, zl, k, liste):
        r, entfernt = _einheit(u, zl, k == 0, self.anfang, liste=liste)
        if not r.strip() or (entfernt and _NUR_ANREDE.match(r)):
            if entfernt:
                self.mach_ich = True    # nur Anrede/Floskel: faellt weg (Inhalt danach) oder wird 'Mach ich.'
            return ''                   # sonst (z. B. nur Emoji/Trennlinie): einfach weglassen, nichts erfinden
        self.mach_ich = False
        self.emittiert = True
        self.je_emittiert = True
        return r + _sep(sep)

    def _queue(self, final):
        aus = ''
        while self.q:
            u, sep, zl, k, nr = self.q[0]
            if nr is not None and len(self.q) < 2 and not final:
                break                                        # Nachbar noch unbekannt
            liste = False
            if nr is not None:
                nach = self.q[1] if len(self.q) > 1 else None
                nach_nr = nach[4] if nach else None
                liste = ((self.vor_nummer is not None and self.vor_nummer + 1 == nr) or (nach_nr is not None and nach_nr == nr + 1 and '\n' in sep))
            self.vor_nummer = nr if (nr is not None and '\n' in sep) else None
            self.q.pop(0)
            aus += self._ausgeben(u, sep, zl, k, liste)
        return aus

    def _abarbeiten(self, final):
        text, ausgabe = self.puffer, ''
        while True:
            teile = zerlege(text)
            if not teile:
                break
            u, sep = teile[0]
            rest = text[len(u) + len(sep):]
            if not sep or (not rest and not final):
                break
            self.q.append((u, sep, self.zeilenanfang, self.k, _nummer(u, self.zeilenanfang)))
            self.k += 1
            self.zeilenanfang = '\n' in sep
            text = rest
        self.puffer = text
        if final and self.puffer:
            self.q.append((self.puffer, '', self.zeilenanfang, self.k, _nummer(self.puffer, self.zeilenanfang)))
            self.k += 1
            self.puffer = ''
        ausgabe += self._queue(final)
        if final and self.mach_ich and not getattr(self, 'je_emittiert', False):     # S-10: nach echtem Inhalt wird die Floskel einfach weggelassen, nie zur Zusage
            ausgabe += ('' if not ausgabe or ausgabe[-1:].isspace() or not self.emittiert else ' ') + 'Mach ich.'
            self.mach_ich = False
        return ausgabe

    def feed(self, delta):
        self.roh += delta
        self.puffer += delta
        return self._abarbeiten(False)

    def flush(self):
        return self._abarbeiten(True)


def filtere(text, anfang=False):
    """Endtext filtern (dieselbe Maschine wie im Strom). anfang=True: erste Antwort einer Sitzung (echte Begruessung darf 'Patron' behalten)."""
    if not text:
        return text
    sf = Satzfilter(anfang=anfang)
    erg = (sf.feed(text) + sf.flush()).strip()
    return erg if erg else text
