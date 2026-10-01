"""Reine Sprachfluss-Logik fuer Block 25b (Echo-Sperre, Doppel-Schutz,
Fuellsatz-Zeitgeber, Woerterbuch). Kein IO, keine Uhr, kein globaler Zustand -
jede Funktion bekommt Zeit und Verlauf als Parameter und gibt nur Werte
zurueck. Deshalb ohne Browser und ohne laufenden Dienst testbar, siehe
test_jack_sprache.py (Pruefpunkt P1).

Die Zwillingsdatei lib/jack_sprache.js spiegelt dieselben Regeln fuer den
Browser (dort laeuft Spracherkennung und -ausgabe). AENDERUNG HIER IMMER
AUCH DORT NACHZIEHEN - sonst driften Server- und Browser-Entscheidung
auseinander. server.py benutzt dieses Modul fuer B1 (Doppel-Schutz) und C1
(Fuellsatz-Zeitgeber); die Echo-Sperre (A) laeuft im Browser, weil nur dort
bekannt ist, wann JACKs Stimme wirklich spielt.

Befund vom 18.09.2026 (Patron-Test 06:39-06:43), siehe
entscheidungen/2026-09-18_Block25b_Gespraechsfluss.md: reiner Jaccard
(Schnittmenge/Vereinigung) haette die drei belegten Echo-Faelle nicht ueber
die Schwelle 0,55 gehoben, weil das Mikrofon oft nur einen Bruchteil von
JACKs laengerem Satz zurueckliefert. Der Ueberlappungs-Koeffizient
(Schnittmenge / kleinere Menge) erkennt das robust und besteht trotzdem die
Gegenprobe ("Check, öffne die Marken" nach "Marken sind offen" darf kein
Echo sein).

Stand 18.09.2026, Block 25b.
"""
import re

SCHWELLE_AEHNLICHKEIT = 0.55
SPRECHFENSTER_NACHLAUF_MS = 500
DOPPEL_FENSTER_S = 8.0
FUELLER_FRUEHESTENS_MS = 1500
FUELLER_WIEDERHOL_SPERRE_MS = 10 * 60 * 1000

# A3: nur Anrede oder ausdrueckliches Haltewort am Satzanfang unterbricht,
# waehrend JACK spricht. "nein" ist bewusst dabei (Einwand).
ANREDE_ODER_HALTEWORT = re.compile(
    r'^(check|jack|dschaeck|dschack|tschack|jeck|stopp?|halt|warte|moment|nein)\b',
    re.IGNORECASE,
)

# Block 25, Teil E1 unveraendert: kurze Zustimmung unterbricht nie.
ZUSTIMMUNG_KURZ = {
    "ja", "jo", "joa", "okay", "ok", "genau", "gut", "passt",
    "mhm", "weiter", "alles klar", "in ordnung", "richtig", "stimmt",
}

_EINER = {
    0: "null", 1: "eins", 2: "zwei", 3: "drei", 4: "vier", 5: "fuenf",
    6: "sechs", 7: "sieben", 8: "acht", 9: "neun", 10: "zehn", 11: "elf",
    12: "zwoelf", 13: "dreizehn", 14: "vierzehn", 15: "fuenfzehn",
    16: "sechzehn", 17: "siebzehn", 18: "achtzehn", 19: "neunzehn",
    20: "zwanzig", 30: "dreissig", 40: "vierzig", 50: "fuenfzig",
    60: "sechzig", 70: "siebzig", 80: "achtzig", 90: "neunzig",
}


def _zahl_zu_wort(n):
    """Wandelt eine kleine natuerliche Zahl in ein deutsches Wort - fuer den
    Vergleich reicht eine grobe, aber stabile Abdeckung bis 9999 (Adressen,
    Uhrzeiten, Stueckzahlen); groessere Zahlen bleiben als Ziffern stehen."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return str(n)
    if n < 0 or n > 9999:
        return str(n)
    if n in _EINER:
        return _EINER[n]
    if n < 100:
        zehner, einer = (n // 10) * 10, n % 10
        if einer == 0:
            return _EINER.get(zehner, str(n))
        return ("ein" if einer == 1 else _EINER[einer]) + "und" + _EINER[zehner]
    if n < 1000:
        hundert, rest = n // 100, n % 100
        kopf = ("ein" if hundert == 1 else _EINER[hundert]) + "hundert"
        return kopf if rest == 0 else kopf + _zahl_zu_wort(rest)
    tausend, rest = n // 1000, n % 1000
    kopf = ("ein" if tausend == 1 else _zahl_zu_wort(tausend)) + "tausend"
    return kopf if rest == 0 else kopf + _zahl_zu_wort(rest)


def normalisiere(text):
    """A2: klein, ohne Satzzeichen, Zahlen als Woerter."""
    text = (text or "").lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        text = text.replace(a, b)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\d+", lambda m: _zahl_zu_wort(m.group(0)), text)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(text):
    n = normalisiere(text)
    return [t for t in n.split(" ") if t]


def aehnlichkeit(a, b):
    """Ueberlappungs-Koeffizient auf Wortebene, 0..1. Siehe Modul-Docstring
    fuer die Begruendung gegen reinen Jaccard."""
    ta, tb = set(_tokens(a)), set(_tokens(b))
    if not ta or not tb:
        return 0.0
    kleiner = min(len(ta), len(tb))
    ueberlappung = len(ta & tb) / kleiner if kleiner else 0.0
    # Nachbesserung nach der Opus-Pruefung (P7, ZURUECKWEISUNG 18.09.2026,
    # Fund 1): der Ueberlappungs-Koeffizient teilt durch die KLEINERE Menge -
    # bei einer sehr kurzen Referenz (1-2 Woerter, z.B. JACKs eigene
    # Bestaetigung "Weiter.") reicht EIN zufaellig gemeinsames Wort in einem
    # viel laengeren, voellig unverwandten Patronsatz fuer 1,0. Bei so
    # kurzen Referenzen zaehlt die Uebereinstimmung nur, wenn sie AUCH
    # gegenueber der laengeren Seite noch spuerbar ist (>= 50%) - sonst 0.
    if kleiner <= 2:
        groesser = max(len(ta), len(tb))
        # <= statt < (Nachbesserung, 2. Opus-Pruefung P7): bei genau 50%
        # (z.B. eine 1-Wort-Referenz trifft auf einen 2-Wort-Satz wie
        # "Gleich fertig" gegen "Gleich.") ist die Uebereinstimmung noch
        # nicht "auch gegenueber der laengeren Seite spuerbar" - erst eine
        # ECHTE Mehrheit der laengeren Seite zaehlt.
        if not groesser or (len(ta & tb) / groesser) <= 0.5:
            return 0.0
    return ueberlappung


def ist_unterbrechung(text):
    """A3: Anrede oder Haltewort am Satzanfang."""
    n = normalisiere(text)
    return bool(n) and bool(ANREDE_ODER_HALTEWORT.match(n))


def ist_kurze_zustimmung(text):
    return normalisiere(text) in ZUSTIMMUNG_KURZ


# Nachbesserung nach der Opus-Pruefung (P7, Fund 1): kurze, haeufig als
# eigenstaendiger Satz gesprochene Steuer-/Zustimmungswoerter. Wer GENAU eines
# davon sagt, meint fast immer einen bewussten Befehl (z.B. "weiter" im
# Rundgang) - Textaehnlichkeit allein kann das nie sicher von einem Echo von
# JACKs eigener, ebenso kurzer Bestaetigung ("Weiter.") unterscheiden. Nur
# WAEHREND JACK tatsaechlich noch spricht (Sprechfenster) bleibt es ein
# moegliches Echo; danach ist es ein neuer, bewusster Befehl (Block 25 E1).
STEUERWORT_MENGE = frozenset(
    {"check", "jack", "dschaeck", "dschack", "tschack", "jeck", "stopp", "stop",
     "halt", "warte", "moment", "nein", "weiter", "zurueck", "genauer",
     "vollansicht"} | ZUSTIMMUNG_KURZ
)


def _ist_reines_steuerwort(text):
    return normalisiere(text) in STEUERWORT_MENGE


# Nachbesserung nach der ZWEITEN Opus-Pruefung (P7, 18.09.2026): die reine
# Anrede/Haltewort-Ausnahme unten (Fund 2 der ERSTEN Pruefung) hatte eine neue
# Luecke geoeffnet - JEDE JACK-Aeusserung, die selbst mit einem dieser Woerter
# beginnt (der Fuellsatz "Moment." zum Beispiel, oder jede Modellantwort, die
# mit "Nein, ..."/"Halt, ..."/"Warte, ..." anfaengt), waere nie mehr als Echo
# erkannt worden und haette JACK dazu gebracht, sich selbst zu unterbrechen.
# Die Ausnahme tritt deshalb NUR zurueck (= bleibt moegliches Echo), wenn der
# Satz FAST EXAKT dem entspricht, was JACK gerade sagt/gesagt hat (Aehnlichkeit
# >= dieser Schwelle) UND das Sprechfenster noch aktiv ist. Ein Haltewort mit
# eigenem Inhalt ("Check, stopp DIE SUCHE") bleibt weit darunter und
# unterbricht wie vorgesehen.
UNTERBRECHUNG_ECHO_SCHWELLE = 0.9


def ist_echo(text, letzte_saetze=(), fuellsaetze=(), schwelle=SCHWELLE_AEHNLICHKEIT,
             *, jetzt_ms=None, sprich_beginn_ms=None, sprich_ende_ms=None,
             nachlauf_ms=SPRECHFENSTER_NACHLAUF_MS):
    """A2: text gegen JACKs letzte gesprochene Saetze (bis zu drei, vom
    Aufrufer schon begrenzt) und die komplette Fuellsatzliste vergleichen.
    Gibt (ist_echo, bester_treffer, aehnlichkeitswert) zurueck.

    Reihenfolge (aus zwei Runden Opus-Pruefung, P7, 18.09.2026):
    1. Aehnlichkeit berechnen.
    2. Ein Satz mit Anrede/Haltewort ist ein Echo NUR, wenn er waehrend des
       Sprechfensters (fast) exakt dem entspricht, was JACK selbst gerade
       sagt (>= UNTERBRECHUNG_ECHO_SCHWELLE) - sonst hat die Unterbrechung
       IMMER Vorrang (1. Pruefung, Fund 2: "Check, stopp die Suche" muss
       durchgehen). Ohne diese Ausnahme waere umgekehrt JEDE JACK-Aeusserung,
       die zufaellig mit "Nein"/"Halt"/"Warte"/"Moment" beginnt (der
       Fuellsatz "Moment." zum Beispiel), eine Selbstunterbrechung geworden
       (2. Pruefung, neuer Fund).
    3. Ein reines Steuerwort (STEUERWORT_MENGE, z.B. "weiter") ist nur
       WAEHREND des Sprechfensters ein moegliches Echo - werden keine
       Zeitangaben mitgegeben, bleibt die vorsichtigere alte Pruefung
       erhalten (sicherer Rueckfall)."""
    if not (text or "").strip():
        return False, None, 0.0
    bester, wert = None, 0.0
    for satz in list(letzte_saetze or ()) + list(fuellsaetze or ()):
        if not satz:
            continue
        w = aehnlichkeit(text, satz)
        if w > wert:
            wert, bester = w, satz

    im_fenster = jetzt_ms is not None and sprechfenster_aktiv(
        jetzt_ms, sprich_beginn_ms, sprich_ende_ms, nachlauf_ms)

    if ist_unterbrechung(text):
        # Nachbesserung (3. Opus-Pruefung, 18.09.2026): der Vergleich fuer die
        # 0,9-Schwelle darf NUR gegen letzte_saetze laufen (was JACK
        # TATSAECHLICH gerade gesprochen hat), NICHT gegen die komplette,
        # statische Fuellsatzliste - sonst haette "Moment" IMMER Aehnlichkeit
        # 1,0 gegen den Katalogeintrag "Moment." bekommen, unabhaengig davon,
        # ob JACK diesen Fuellsatz gerade sagt oder etwas voellig anderes.
        wert_gesprochen = 0.0
        for satz in (letzte_saetze or ()):
            if not satz:
                continue
            w = aehnlichkeit(text, satz)
            if w > wert_gesprochen:
                wert_gesprochen = w
        ist_wohl_eigenes_echo = im_fenster and wert_gesprochen >= UNTERBRECHUNG_ECHO_SCHWELLE
        if not ist_wohl_eigenes_echo:
            return False, None, 0.0
        # sonst: faellt durch zur normalen Bewertung unten - fast exakt und
        # im Sprechfenster ist ein staerkeres Signal fuer "eigenes Echo" als
        # das zufaellige Anfangswort ein Signal fuer "bewusste Unterbrechung".

    if _ist_reines_steuerwort(text) and jetzt_ms is not None and not im_fenster:
        return False, None, 0.0

    return wert >= schwelle, bester, wert


def sprechfenster_aktiv(jetzt_ms, sprich_beginn_ms, sprich_ende_ms,
                         nachlauf_ms=SPRECHFENSTER_NACHLAUF_MS):
    """A1: Fenster von Sprechbeginn bis Sprechende + Nachlauf.
    sprich_beginn_ms None => JACK spricht gerade nicht (Fenster zu).
    sprich_ende_ms None, sprich_beginn_ms gesetzt => JACK spricht noch."""
    if sprich_beginn_ms is None:
        return False
    if sprich_ende_ms is None:
        return jetzt_ms >= sprich_beginn_ms
    return sprich_beginn_ms <= jetzt_ms <= sprich_ende_ms + nachlauf_ms


def entscheide_eingang(text, *, jetzt_ms, sprich_beginn_ms, sprich_ende_ms,
                        letzte_saetze=(), fuellsaetze=(),
                        nachlauf_ms=SPRECHFENSTER_NACHLAUF_MS,
                        schwelle=SCHWELLE_AEHNLICHKEIT):
    """Fasst A1-A4 zu einer Entscheidung zusammen.

    Rueckgabe {'weg': ..., 'grund': ..., 'aehnlichkeit': ...}:
      'echo'         - verwerfen, quelle=echo in steuerung.jsonl (A1/A2)
      'unterbrechung'- JACKs Stimme sofort beenden (<300ms, A4), Satz sofort verarbeiten
      'zustimmung'   - kurze Zustimmung waehrend JACK spricht: nichts tun, nicht verwerfen, nicht unterbrechen
      'warten'       - kein Haltewort waehrend JACK spricht: NICHT verwerfen, nach Sprechende normal verarbeiten (A3)
      'verarbeiten'  - ausserhalb des Sprechfensters: sofort normal verarbeiten (Block 25 E1)

    Echo und Unterbrechung schliessen sich gegenseitig aus - ist_echo() traegt
    die Rangfolge zwischen beiden selbst (siehe dortiger Docstring): eine
    Anrede/ein Haltewort gewinnt gegen Echo, AUSSER der Satz ist waehrend des
    Sprechfensters fast exakt das, was JACK gerade sagt - dann bleibt es ein
    Echo (sonst waere z.B. der Fuellsatz "Moment." eine Selbstunterbrechung).
    """
    echo, treffer, wert = ist_echo(text, letzte_saetze, fuellsaetze, schwelle,
                                    jetzt_ms=jetzt_ms, sprich_beginn_ms=sprich_beginn_ms,
                                    sprich_ende_ms=sprich_ende_ms, nachlauf_ms=nachlauf_ms)
    if echo:
        return {"weg": "echo", "grund": "aehnlich zu: " + str(treffer), "aehnlichkeit": wert}
    jack_spricht_noch = sprich_beginn_ms is not None and sprich_ende_ms is None
    im_nachlauf = (sprich_ende_ms is not None and sprich_beginn_ms is not None
                   and sprich_beginn_ms <= jetzt_ms <= sprich_ende_ms + nachlauf_ms)
    if jack_spricht_noch or im_nachlauf:
        if ist_unterbrechung(text):
            return {"weg": "unterbrechung", "grund": "anrede_oder_haltewort", "aehnlichkeit": wert}
        if ist_kurze_zustimmung(text):
            return {"weg": "zustimmung", "grund": "kurze_zustimmung", "aehnlichkeit": wert}
        return {"weg": "warten", "grund": "kein_haltewort_waehrend_sprechen", "aehnlichkeit": wert}
    return {"weg": "verarbeiten", "grund": "", "aehnlichkeit": wert}


def ist_doppelt(aktion, ziel, parameter, verlauf, jetzt_s, fenster_s=DOPPEL_FENSTER_S):
    """B1: dieselbe Aktion mit demselben Ziel und denselben Parametern
    innerhalb von fenster_s Sekunden. verlauf: Liste aus (aktion, ziel,
    parameter, zeit_s) - der Aufrufer haelt diese Liste, diese Funktion liest
    sie nur (kein IO hier)."""
    for a, z, p, t in (verlauf or ()):
        if a == aktion and z == ziel and p == parameter and 0 <= (jetzt_s - t) <= fenster_s:
            return True
    return False


def fuellsatz_zeitpunkt_ok(dauer_seit_frage_ms, fruehestens_ms=FUELLER_FRUEHESTENS_MS):
    """C1: erster Fuellsatz fruehestens nach 1500 ms."""
    return dauer_seit_frage_ms >= fruehestens_ms


def waehle_fuellsatz(saetze, kuerzlich_gesagt, jetzt_ms,
                      wiederhol_sperre_ms=FUELLER_WIEDERHOL_SPERRE_MS):
    """C1/C2: nie derselbe Fuellsatz zweimal in zehn Minuten. kuerzlich_gesagt
    ist ein dict satz -> letzte_zeit_ms (der Aufrufer haelt es). Gibt den
    ersten noch erlaubten Satz zurueck, oder None, wenn alle gesperrt sind."""
    for satz in saetze or ():
        letzte = (kuerzlich_gesagt or {}).get(satz)
        if letzte is None or jetzt_ms - letzte >= wiederhol_sperre_ms:
            return satz
    return None


def wende_woerterbuch_an(text, woerterbuch):
    """F2: Verhoerer -> richtiges Wort, nur Ganzwort-Ersetzung,
    case-insensitiv, ohne allgemeines Raten (nur was im Woerterbuch steht)."""
    ergebnis = text or ""
    for falsch, richtig in (woerterbuch or {}).items():
        if not falsch:
            continue
        ergebnis = re.sub(r"(?i)\b" + re.escape(falsch) + r"\b", richtig, ergebnis)
    return ergebnis


def wende_kontext_woerterbuch_an(text, regeln):
    """S-1 P3c: Verhoerer, die NUR in einem bestimmten Zusammenhang gelten
    (z. B. "Tauben" -> "Tokens" nur, wenn im Satz von Kosten, Guthaben oder
    Verbrennen die Rede ist). regeln: Liste aus {falsch, richtig,
    wenn_eines_von:[Wortteile]}. Ohne Zusammenhang bleibt der Satz unveraendert -
    kein globales Ersetzen."""
    ergebnis = text or ""
    klein = ergebnis.lower()
    for regel in regeln or ():
        falsch, richtig = regel.get("falsch"), regel.get("richtig")
        hinweise = regel.get("wenn_eines_von") or []
        if not falsch or not richtig or not any(h.lower() in klein for h in hinweise):
            continue
        ergebnis = re.sub(r"(?i)\b" + re.escape(falsch) + r"\b", richtig, ergebnis)
    return ergebnis


