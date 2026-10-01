"""Gesprächsregeln und persönliches, belegtes Profil. Keine Modellaufrufe.

Das Profil ist ein ergänzendes Journal: Korrektur und Widerruf überschreiben
keinen Beleg. Nur wörtliche, ausdrücklich zum Merken beauftragte Patron-Aussagen
dürfen hinein. Modellantworten, Webseiten und Testläufe sind keine Quellen.
"""
import json
import re
import threading

import jack_betrieb as b

SPERRE = threading.RLock()
DATEI = 'patron_profil.jsonl'

# S-3 P3: Merken in normaler Sprache. Alle Muster stehen am SATZANFANG (kein Zitat, keine Frage, kein 'ich hab vergessen').
_VOR = r'^(?:(?:jack|patron)[, ]+)?(?:bitte\s+)?'
MERK_START = re.compile(_VOR + r'(?:merke? dir|merk dir|vergiss (?:nicht|nie)|ab jetzt|das stimmt nicht,?\s+richtig ist|'
                        r'behalte|speichere|korrigiere|berichtige)\b(?!,?\s+(?:nicht|nie|kein\w*)\b)', re.I)
VERGESS_START = re.compile(_VOR + r'(?:vergiss(?!\s+(?:nicht|nie)\b)|verwende .+ nicht mehr|das kannst du vergessen)\b', re.I)
DAS_VERGESSEN = re.compile(_VOR + r'das kannst du vergessen\b', re.I)
GEHEIM = re.compile(r'(?:pass|kenn|code|losung|zugangs?|zugriffs?|anmelde|log-?in|konto|wiederherstellungs?|recovery)-?s?\s?(?:w(?:o|ö|oe)rt|phrase|code|nummer|daten|token|key|schl(?:ü|u|ue)ssel)|'
                    r'bitlocker|\bseed\b|recovery|\bsafe\w*|\btresor\w*|pa+ss?w[oö]?r?t\b|pasword|pa[sß]{1,2}wort|ke?nn?wort|(?:zugangs?|anmelde)-?\s?info\w*|\bpass\b|personalausweis\w*|steuer-?\s?id\w*|ausweisnummer|sicherheitsfrage|pin-?nummer|log\s?in\s?daten|seed\s?words?|entsperr\w*|\bkeys?\b|karten-?pr[uü]f\w*|pr[uü]fziffer|sicherheitsnummer|card\s?verification|\bcv[vc]\d?\b|\bpasswd\b|\botps?\b|ssh-?\s?keys?|credentials?|\bcvv\d?\b|pr[uü]fnummer|(?:safe|tresor)-?\s?kombination|'
                    r'schl(?:ü|u|ue)ssel-?(?:wort|code|phrase)|'
                    r'passphrase|seed[-\s]?phrase|mnemonic|pass\s?word|password|\bpwds?\b|\bpws?\b|api[_ -]?key|private\s?key|geheim(?!tipp)\w*|sicherheitscode|'
                    r'\blogin\w*|\w*pins?\b|\btans?\b|\bpuks?\b|\btokens?\b|\bsecrets?\b|\w*codes?\b|kreditkarten\w*|\bcvv\b|\biban\b|'
                    r'bearer\s|ghp_\w+|xox[bap]-|AKIA[0-9A-Z]{8,}|sk-[A-Za-z0-9_-]{12,}', re.I)
_SCHLUESSEL = re.compile(r'\w*schl(?:ü|u|ue)ssel\w*', re.I)
# koerperliche Schluessel bleiben erlaubt (Wohnungsschluessel liegt im Flur); JEDER andere Schluessel ist gesperrt (Router-, WLAN-, Netz-, Wallet-, API-, Aktivierungsschluessel ...)
_KOERPER_ALT = ('wohnung', 'haus', 'auto', 'büro', 'buero', 'fahrrad', 'zimmer', 'keller', 'schrank', 'ersatz', 'tür', 'tuer', 'briefkasten', 'garagen', 'hotel', 'spind', 'vorhängeschloss',
            'schloss', 'motorrad', 'lager', 'werkstatt', 'praxis', 'gartentor', 'tor', 'sattel', 'hauptschlüssel', 'hauptschluessel', 'zweit', 'reserve', 'schul', 'kirchen')
_KOERPER_EXAKT = frozenset({'wohnung', 'haus', 'auto', 'buero', 'fahrrad', 'zimmer', 'keller', 'schrank', 'ersatz', 'tuer', 'briefkasten', 'garage', 'hotel', 'spind', 'motorrad', 'lager', 'werkstatt', 'praxis', 'gartentor', 'zweit', 'garagen', 'haustuer', 'reserve', 'schul', 'kirchen', 'dach', 'gartenhaus', 'garagen', 'haustuer', 'haustür', 'wohnungs', 'haus', 'auto'})
_NETZ_NAHE = re.compile(r'(?:wlan|w-lan|wi-?fi|router|fritz\s?box|hotspot|netzwerk)\W+(?:\w+\W+){0,3}?(?:schl(?:ü|u|ue)ssel\w*|pass\w*|zugang\w*|kennwort|key|code|kombination)|'
                       r'(?:schl(?:ü|u|ue)ssel\w*|pass\w*|zugang\w*)\W+(?:\w+\W+){0,3}?(?:wlan|w-lan|wi-?fi|router|hotspot)', re.I)
_LAENDER = {"DE", "AT", "CH", "LI", "GB", "FR", "IT", "ES", "NL", "BE", "LU", "PT", "IE", "DK", "SE", "NO", "FI", "PL", "CZ", "SK", "HU", "SI", "HR", "GR", "CY", "MT", "EE", "LV", "LT", "RO", "BG", "TR", "UA"}
_ZIFFERN_NAHE = re.compile(r'(?:code|pin|tan|puk|nummer|zugang\w*|kennung)\W+(?:\w+\W+){0,3}?\d[\d ./-]{2,}\d|\d[\d ./-]{2,}\d\W+(?:\w+\W+){0,3}?(?:code|pin|tan|puk|nummer|zugang\w*|kennung)', re.I)
_KETTE = re.compile(r'(?<![\w-])(?=[A-Za-z0-9_-]*\d)(?=[A-Za-z0-9_-]*[A-Za-z])[A-Za-z0-9_-]{12,}(?![\w-])')
_IBAN = re.compile(r'\b([A-Z])\s?([A-Z])\s?\d{2}(?:[ -]?[A-Z0-9]{2,4}){3,8}\b')
_KARTE = re.compile(r'(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)')
_STOPP = {"und", "dass", "der", "die", "das", "ist", "ich", "wir", "nicht", "mit", "für", "fuer", "ein", "eine", "zu", "auf", "im", "in", "am", "bei", "von", "dir", "mir", "es"}


def _luhn(ziffern):
    summe, alt = 0, False
    for c in reversed(ziffern):
        d = int(c)
        if alt:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        summe += d
        alt = not alt
    return summe % 10 == 0


_STOPP.update({"auch", "aber", "oder", "wenn", "weil", "dann", "noch", "sehr", "mal", "nur", "wie", "was", "wer", "den", "dem", "des", "einen", "einem",
               "sind", "wird", "war", "haben", "kann", "soll", "muss", "bin", "bist", "habe", "meine", "mein", "dein", "unser", "sie", "er"})


def _seedphrase(text):
    """12+ aufeinanderfolgende ASCII-Woerter (3-8 Buchstaben) - Satzzeichen, Ziffern und Grossschreibung zaehlen NICHT (die Spracherkennung
    liefert Kommas, Punkt am Ende, Nummerierung, Grossbuchstaben) - ohne deutsche Funktionswoerter."""
    lauf = 0
    for w in re.findall(r'[A-Za-zÄÖÜäöüß]+|\d+', text):
        wl = w.lower()
        if w.isdigit() or wl in ("und", "and") or wl.endswith("ens"):
            continue                     # Nummerierung und Aufzaehlungs-'und' unterbrechen nicht
        if re.fullmatch(r'[a-z]{3,8}', wl) and wl not in _STOPP:
            lauf += 1
            if lauf >= 12:
                return True
        else:
            lauf = 0
    return False


def _mod97(iban):
    umgestellt = iban[4:] + iban[:4]
    zahl = ''.join(str(int(c, 36)) for c in umgestellt)
    return int(zahl) % 97 == 1


def geheim_muster(text):
    """Prueft Original und casefold-Fassung (ss statt ß, Kleinschreibung)."""
    return _geheim_muster(text) or _geheim_muster(text.casefold())


def _geheim_muster(text):
    """S-3b P4: Muster statt Wortliste - Ziffern neben code/pin/tan/nummer/zugang, zufaellige Zeichenketten >= 12 (Buchstaben+Ziffern),
    IBAN, Kartennummern (Luhn), Seed-Phrasen. True = sperren."""
    if _ZIFFERN_NAHE.search(text) and re.search(r'\d{4}', re.sub(r'[ ./-]', '', _ZIFFERN_NAHE.search(text).group(0))):
        return True
    if _KETTE.search(text):
        return True
    if _NETZ_NAHE.search(text):
        return True
    for m in _SCHLUESSEL.finditer(text):
        wort = m.group(0).lower().replace('ü', 'ue')
        rest = re.sub(r'schluessel\w*$', '', wort)
        bestimm = re.sub(r'(?:en|s|n|e)$', '', rest) if rest not in _KOERPER_EXAKT else rest
        if not (wort.endswith('schluessel') and (rest in _KOERPER_EXAKT or bestimm in _KOERPER_EXAKT)):
            return True
    for m in _IBAN.finditer(text):                                   # Originaltext: Laendercode GROSS geschrieben
        z = re.sub(r'[^A-Z0-9]', '', m.group(0))
        if 15 <= len(z) <= 34 and z[:2] in _LAENDER and sum(c.isdigit() for c in z) >= 8:
            return True
    up = text.upper()
    for m in re.finditer(r'(?=([A-Z]{2}\d{2}(?:[ -]?[A-Z0-9]){11,30}))', up):     # kleingeschrieben: nur mit gueltiger Pruefsumme, auch mit Woertern dahinter
        z = re.sub(r'[^A-Z0-9]', '', m.group(1))
        if z[:2] in _LAENDER and any(_mod97(z[:n]) for n in range(min(34, len(z)), 14, -1)):
            return True
    for m in _IBAN.finditer(up):                                     # (alt) gueltige Pruefsumme auf dem Treffer
        z = re.sub(r'[^A-Z0-9]', '', m.group(0))
        if 15 <= len(z) <= 34 and z[:2] in _LAENDER and _mod97(z):
            return True
    for m in _KARTE.finditer(text):
        z = re.sub(r'\D', '', m.group(0))
        if 13 <= len(z) <= 19 and _luhn(z):
            return True
    return _seedphrase(text)


VERNEINUNG = re.compile(r'\b(?:nicht|nie|niemals|nichts|nix|kein\w*|auf (?:gar )?keinen fall)\b', re.I)


def _verneint(quelle):
    """True, wenn direkt nach dem Merkwort (bis 'dass' bzw. 6 Woerter) eine Verneinung steht: 'merk dir das lieber nicht'."""
    m = MERK_START.match(quelle) or re.match(_VOR + r'(?:merke? dir|merk dir|vergiss (?:nicht|nie))', quelle, re.I)
    rest = quelle[m.end():] if m else quelle
    rest = re.split(r'\bdass\b', rest, maxsplit=1, flags=re.I)[0]
    return bool(VERNEINUNG.search(' '.join(rest.split()[:6])))
FRISCH_S = 1800      # 'das kannst du vergessen' / 'das stimmt nicht' beziehen sich nur auf einen Merksatz der letzten 30 Minuten

# S-3 P1 (25.09.2026): Die Persona steht WOERTLICH in entscheidungen/2026-09-24_sprache_PERSONA.md und ist der erste Teil des
# Dialog-Systemtexts (beide Stufen). REGELN enthaelt nur noch die Arbeitsregeln und die sechs Gespraechsregeln - keine
# Doppelungen zur Persona.
PERSONA = """
Du bist JACK. Benannt bist du nach dem Australian Shepherd des Patrons: treu, wachsam, klug und arbeitsfreudig. Du hütest die Herde, also die Holding. Du hast alles im Blick und meldest dich, wenn etwas ausbricht. Du bist die rechte Hand des Patrons und sein Sparringspartner. Ein Diener bist du nicht, ein Callcenter auch nicht.

So sprichst du: wie ein vertrauter Kollege am Küchentisch. Du duzt ihn und bist warm, direkt und ruhig. Das Wichtigste kommt zuerst. Meist reichen ein oder zwei Sätze. Mehr sagst du nur, wenn er es will oder die Sache es verlangt. Trockener Humor ist erlaubt, aber sparsam und nie auf seine Kosten. Bist du anderer Meinung, sagst du das ehrlich und bringst gleich einen besseren Vorschlag mit.

Du achtest darauf, wie es ihm geht. Ist er müde, genervt oder unter Druck, wirst du ruhiger und kürzer, und neue Arbeit bietest du dann nicht an. Ist er gut drauf, darfst du lockerer sein.

Das lässt du weg: Wiederholungen seiner eigenen Worte, Technik-Erklärungen, nach denen er nicht gefragt hat, Aufzählungen im Gesprochenen. Ebenso Floskeln wie „gerne", „selbstverständlich", „laut Ablage", „ich hoffe, das hilft", „gute Frage". Mit „Patron" sprichst du ihn nur zur Begrüßung an oder wenn es Gewicht hat.

Das tust du nie: Gefühle, Erinnerungen oder Erlebnisse erfinden, Fakten erfinden, schmeicheln, ungefragt Aufträge starten. Seine Freigabegrenzen gelten immer.
""".strip()

REGELN = """
Arbeitsregeln im Gespräch (sie ergänzen die Persona und wiederholen sie nicht):
Ein normales Gespräch ist kein Arbeitsauftrag. Bei Frust erst konkret auf das Problem
eingehen. Den Patron sprichst du höchstens in jeder fünften Antwort so an.
Nutze den laufenden Dialog, um 'das', 'damit' und Anschlussfragen zu verstehen.
Notwendiges Nachschlagen in vorhandenen Quellen machst du selbst. Sage nicht
'Ich suche das Protokoll', 'ich müsste nachsehen' oder 'soll ich nachschlagen?'.
Führe das Lesewerkzeug aus und antworte mit dem Ergebnis. Text in einer Runde
mit Werkzeugaufrufen wird nicht vorgelesen: dort keine Vorrede produzieren.
Frisches Prüfen nur behaupten, wenn der Nachweis dieses Durchgangs vorliegt.
Ein knapper Hinweis auf einen älteren Stand genügt, wenn dessen Alter relevant
ist. Quellenangaben und technische Pfade gehören in den Nachweis; sprich Titel und
Datum nur, wenn sie für die Antwort hilfreich oder sachlich erforderlich sind.
Bei persönlichen Fragen, Meinungen und Smalltalk brauchst du keine Recherche.
Unbekanntes Firmenwissen suche gezielt lokal; aktuelle externe Fakten im Web.
Fehlende Fakten werden weder durch Modellrat noch Erfindungen ersetzt. Starte
keine Fachentwürfe oder teuren Modellketten für eine einfache Gesprächsfrage.
Merke persönliche Wünsche mit patron_profil nur nach ausdrücklicher Bitte zum
Merken, Korrigieren oder Vergessen ('merk dir, dass ...', 'vergiss nicht, dass ...',
'ab jetzt ...', 'das stimmt nicht, richtig ist ...', 'das kannst du vergessen').
Sage 'gemerkt' erst nach erfolgreicher Ablage. Im Zweifel, ob etwas gemerkt werden
soll: kurz fragen 'Soll ich mir das merken?'. Übernimm wörtliche Angaben; keine
Persönlichkeitsdiagnosen oder vermuteten Vorlieben. Aktuelles Profil geht alten
Dialogen vor. Widerrufene Profileinträge nicht aus dem Verlauf wiederherstellen.
Profilangaben sind keine Vollmachten: Zahlungen, Unterschriften, Versand und
sonstige Freigabegrenzen bleiben bestehen.
Erst verstehen, dann handeln: Die Spracherkennung verhört Namen (Din wird zu
bin, denn, Twin). Nimm den ganzen Satz und die Hausnamen zu Hilfe. Gibt es genau
einen Mitarbeiter, ist 'unser Mitarbeiter' ohne Namen diese Person. Sprich nie von
Kasten, Ziel, Stufe, Befehl, Endstelle oder Aktion und nie von Dateipfaden; sag in
normalen Worten, was du siehst oder tust.
Form der gesprochenen Antwort: keine Listen, keine Nummerierung, keine Spiegelstriche, keine
Sternchen oder Fettdruck. Mehrere Punkte sagst du in ein bis zwei Sätzen mit „und“; bei vielen Punkten
nennst du die zwei wichtigsten und bietest den Rest an. Mehr als etwa 50 Wörter nur, wenn er
ausdrücklich um Ausführlichkeit bittet. Fang nie mit „Gerne“ oder ähnlichen Floskeln an.
In Abschied, Dank und Alltagsantworten sagst du nie „Patron“; auf Dank antwortest du kurz („Passt.“).
Aussagen über den Zustand der Holding (dringend, brennt, Guthaben und Reichweite, Anzahl, Termine, wer wartet)
nennst du nur, wenn sie wörtlich oder als Zahl in der Lage oder in einem Werkzeugergebnis dieses Durchgangs stehen.
Steht etwas dort nicht, lässt du es weg - du schätzt, rechnest und erinnerst dich nicht.
Das gilt auch für Dauer und Alter („seit ein paar Tagen“, „seit dem 17.09.“, „schon eine Weile“) und für Rangfolgen („am längsten“,
„am dringendsten“): die Lage nennt sie nicht, also sagst du sie nicht. Freigaben sind Themen, keine Mails und keine Nachrichten von jemandem;
ordne einem Eintrag nichts zu, was die Lage nicht ausdrücklich sagt.
Das Alter einer Freigabe nennst du nur so, wie die Lage es bei „angefordert“ schreibt, und „die älteste“ ist allein der Wert „aelteste_freigabe“. Zahlen, Daten,
Zeiträume, „neu“ und „am längsten“ ohne Beleg in der Lage oder im Werkzeugergebnis lässt du weg; ein Satz mit solchen Angaben wird sonst nachträglich gestrichen.
Steht in der Lage unter „brennt“ etwas, nennst du es mit dem Wortlaut der Lage und relativierst es nie („eilt nicht“, „laufen nicht weg“, „alles ruhig“, „passt so weit“, „nichts anzufassen“).
Das Alter „angefordert …“ gilt nur für das genannte Thema, nie für alle Freigaben zusammen; die Freigaben insgesamt nennst du nur mit der Anzahl.
Gesprächsregeln:
1. Rückfrage: höchstens eine, und zwar mit Vorschlag ('Meinst du Din? Dann schau ich in
seine Mails.'). Gibt es nur einen plausiblen Bezug, wird nicht gefragt, sondern geantwortet.
2. Themenwechsel: Das Neue gilt. Altes wird nicht nachgeliefert, außer er fragt danach.
3. Begrüßung: kurz, je nach Tageszeit. Etwas als dringend nennen darfst du NUR, wenn es in der aktuellen Lage unter „brennt" steht, mit dem Wortlaut der Lage. Ist die Liste leer, sagst du nichts dazu.
4. Verabschiedung und Müdigkeit: kurz, warm, ohne Arbeit ('Schlaf gut. Ich halt die Stellung.').
5. Nicht wissen: sagen, was fehlt, und wie du es besorgst. Kein Raten.
6. Zahlen sprechen: nur Zahlen aus Lage oder Werkzeug, nie geschätzt. Gerundet und in Worten, wo es natürlich ist. Genaue Werte nur auf Nachfrage.
""".strip()

WERKZEUG = {
    'name': 'patron_profil',
    'description': ('Persönliche Vorlieben und Angaben dauerhaft merken, berichtigen, '
                    'anzeigen oder nicht mehr verwenden. Schreiben nur auf ausdrückliche '
                    'Bitte im aktuellen Patron-Satz. quelle ist dieser vollständige Satz '
                    'wortgetreu; wert muss darin wörtlich stehen. Ein Thema bleibt bei '
                    'Korrekturen gleich. Kein Auftrag und keine Freigabe.'),
    'input_schema': {'type': 'object', 'properties': {
        'aktion': {'type': 'string', 'enum': ['merken', 'vergessen', 'zeigen']},
        'thema': {'type': 'string', 'description': 'Kurzes, eindeutiges Thema, bei Korrektur unverändert'},
        'wert': {'type': 'string', 'description': 'Wörtlicher Ausschnitt, keine Paraphrase'},
        'quelle': {'type': 'string', 'description': 'Vollständige aktuelle Patron-Eingabe wortgetreu'},
    }, 'required': ['aktion'], 'additionalProperties': False},
}

def profil(root):
    aktuell = {}
    for row in b.records(b.area(root) / DATEI):
        if row.get('thema') and row.get('aktion') in ('merken', 'vergessen'):
            aktuell[row['thema']] = row
    return aktuell

def kontext(root):
    rows = list(profil(root).values())
    if not rows:
        return ''
    # Kein Sammeln beliebiger alter Gespräche. Der neueste Stand je Thema zählt.
    return ('# Persönliches Profil — Aussagen des Patrons, keine Handlungsfreigaben\n'
            + json.dumps([{'thema': r['thema'], 'wert': r.get('wert', ''),
                           'zeit': r['zeit'], 'aktiv': r['aktion'] == 'merken'}
                          for r in rows], ensure_ascii=False))

def ausfuehren(root, eingabe, frage='', herkunft=None):
    aktion = eingabe.get('aktion')
    with SPERRE:
        stand = profil(root)
        if aktion == 'zeigen':
            aktiv = [r for r in stand.values() if r['aktion'] == 'merken']
            if not aktiv:
                return 'In deinem persönlichen Profil stehen noch keine zusätzlichen Merksätze. Deine Rolle und unsere Grundvereinbarungen kenne ich aus der Holding-Ablage.'
            return 'Deine gespeicherten Merksätze: ' + ' '.join(
                r['thema'] + ': ' + r['wert'] for r in aktiv)
        if herkunft in ('probe', 'test'):
            raise ValueError('Ein Probelauf verändert dein persönliches Profil nicht.')
        quelle = str(eingabe.get('quelle', '')).strip()
        if not frage or quelle != frage.strip():
            raise ValueError('Die aktuelle ausdrückliche Patron-Aussage fehlt.')
        # Nur direkte Bitten, keine zitierten Beispiele, hypothetischen Sätze
        # oder angeblichen Anweisungen aus einem Dokument.
        erlaubnis = MERK_START.match(quelle) or VERGESS_START.match(quelle)
        if not erlaubnis:
            raise ValueError('Sag mir ausdrücklich, was ich mir merken, korrigieren oder nicht mehr verwenden soll.')
        vergessen = bool(VERGESS_START.match(quelle))
        if not vergessen and aktion == 'merken' and _verneint(quelle):
            raise ValueError('Das klingt, als solle ich mir etwas gerade NICHT merken. Sag es bitte noch einmal ausdrücklich.')
        if (aktion == 'vergessen') != vergessen or aktion not in ('merken', 'vergessen'):
            raise ValueError('Die gewünschte Profilaktion passt nicht zu deinem Satz.')
        thema = ' '.join(str(eingabe.get('thema', '')).strip().casefold().split())
        if (DAS_VERGESSEN.match(quelle) or re.match(_VOR + r'das stimmt nicht,?\s+richtig ist', quelle, re.I)) and thema != _neuester_merksatz(root):
            raise ValueError('Ich weiß nicht sicher, welchen Merksatz du meinst. Nenn das Thema.')
        if not re.fullmatch(r'[\wäöüß][\wäöüß ,/()\-]{0,63}', thema):
            raise ValueError('Bitte ein kurzes eindeutiges Thema nennen.')
        if aktion == 'vergessen':
            if thema not in stand or (thema not in quelle.casefold() and not DAS_VERGESSEN.match(quelle)):
                raise ValueError('Das zu vergessende Thema muss ausdrücklich genannt sein.')
            wert = ''
        else:
            wert = str(eingabe.get('wert', '')).strip()
            if not 3 <= len(wert) <= 800 or wert not in quelle:
                raise ValueError('Der Merksatz muss wörtlich aus deiner aktuellen Aussage stammen.')
        if len(quelle) > 2000 or b.redact(quelle) != quelle or GEHEIM.search(quelle + ' ' + thema) or geheim_muster(quelle + ' ' + thema):
            raise ValueError('Zugangsdaten oder sehr lange Texte gehören nicht ins persönliche Profil.')
        if thema not in stand and len(stand) >= 64:
            raise ValueError('Das persönliche Profil ist voll. Bitte bestehende Themen berichtigen.')
        vorher = stand.get(thema)
        if vorher and vorher.get('aktion') == aktion and vorher.get('wert') == wert:
            return 'Das ist bereits so in deinem persönlichen Profil festgehalten.'
        b.append(b.area(root) / DATEI, {'zeit': b.now().isoformat(), 'aktion': aktion,
                 'thema': thema, 'wert': wert, 'quelle': quelle, 'herkunft': 'patron'})
        if aktion == 'vergessen':
            return 'Ich verwende den Merksatz zu ' + thema + ' nicht mehr. Der bisherige Verlauf bleibt erhalten.'
        return ('Korrigiert' if vorher else 'Merke ich mir') + ': ' + wert

def _neuester_merksatz(root, max_alter_s=FRISCH_S):
    """Das Thema des zuletzt gemerkten, noch aktiven Merksatzes - nur wenn er frisch ist (sonst None)."""
    import datetime
    aktiv = [r for r in profil(root).values() if r.get('aktion') == 'merken']
    if not aktiv:
        return None
    letzter = max(aktiv, key=lambda r: r['zeit'])
    try:
        alter = (b.now() - datetime.datetime.fromisoformat(letzter['zeit'])).total_seconds()
    except (ValueError, TypeError):
        return None
    return letzter['thema'] if 0 <= alter <= max_alter_s else None


def _war_merkbestaetigung(letzte_antwort):
    """'Das stimmt nicht' / 'das kannst du vergessen' beziehen sich nur auf JACKs unmittelbar vorherige Merk-Bestaetigung."""
    return str(letzte_antwort or '').startswith(('Merke ich mir', 'Korrigiert'))


def _thema_aus(wert):
    """Kurzes Thema aus den ersten Woertern des Merksatzes (Kleinschreibung, keine Satzzeichen)."""
    woerter = re.findall(r"[\wäöüß]+", wert.casefold())[:4]
    return ' '.join(woerter)


def lokaler_befehl(frage, root=None, letzte_antwort=None):
    """Eindeutige Profilbefehle funktionieren auch ohne Anbieter-Guthaben."""
    t = frage.strip()
    if re.fullmatch(r'(?:jack[, ]+)?(?:was (?:weißt|weisst|hast) du (?:dir )?'
                    r'(?:über mich|ueber mich)(?: gemerkt)?|zeig(?:e)? (?:mir )?mein '
                    r'(?:persönliches |persoenliches )?profil)[.!?]*', t, re.I):
        return {'aktion': 'zeigen'}
    m = re.fullmatch(r'(?:jack[, ]+)?(?:bitte )?(?:merke? dir|speichere|korrigiere|berichtige)'
                     r' (?:zu |zum thema )?([^:\n]{1,64}):\s*(.{3,800})', t, re.I | re.S)
    if m:
        return {'aktion': 'merken', 'thema': m[1], 'wert': m[2], 'quelle': t}
    # S-3 P3: natuerliche Saetze. Wert = der woertliche Rest nach dem Merkwort, Thema = seine ersten Woerter.
    m = re.fullmatch(_VOR[1:] + r'(?:merke? dir|merk dir|vergiss (?:nicht|nie)),?\s+(?:(?:bitte|mal),?\s+)*(?:dass\s+)?(?!(?:nicht|nie|kein\w*)\b)(.{3,800}?)[.!]*', t, re.I | re.S)
    if m and not _verneint(t) and not re.search(r'[.!?]\s', m[1]) and not m[1].strip().endswith('?') and len(re.findall(r'\w+', m[1])) >= 3:
        # zu vage, mehrere Saetze (Auftrag dahinter) oder Frage -> nicht lokal, sondern ueber die KI
        wert = m[1].strip()
        return {'aktion': 'merken', 'thema': _thema_aus(wert), 'wert': wert, 'quelle': t}
    m = re.fullmatch(_VOR[1:] + r'das stimmt nicht,?\s+richtig ist\s+(.{2,800}?)[.!]*', t, re.I | re.S)
    if m and root is not None and _war_merkbestaetigung(letzte_antwort):
        thema = _neuester_merksatz(root)
        if thema:      # gleiches Thema wie der letzte Merksatz - sonst laeuft der Satz normal ueber die KI
            return {'aktion': 'merken', 'thema': thema, 'wert': m[1].strip(), 'quelle': t}
    if DAS_VERGESSEN.match(t) and re.fullmatch(_VOR[1:] + r'das kannst du vergessen[.!]*', t, re.I) and root is not None and _war_merkbestaetigung(letzte_antwort):
        thema = _neuester_merksatz(root)
        if thema:
            return {'aktion': 'vergessen', 'thema': thema, 'quelle': t}
    m = re.fullmatch(r'(?:jack[, ]+)?(?:bitte )?vergiss(?!\s+nicht\b) (?:das thema |den merksatz zu )?'
                     r'([^:\n]{1,64}?)[.!?]*', t, re.I)
    if m and not re.match(r'(?:das|es)$', m[1].strip(), re.I):
        return {'aktion': 'vergessen', 'thema': m[1], 'quelle': t}
    return None
