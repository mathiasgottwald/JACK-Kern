"""Social-Media-Zentrale (Auftrag 45.1, CF-3+CF-4, Stand 28.09.2026).

Neues Modul. Schreibt nur unter `00_Marken/<MARKE>/05_Marketing/social/` (bewusst,
Auftrag 45.1 Aufgabe 8 verlangt den Bericht je Marke dort — das ist kein fremdes
JACK-Dateigebiet, sondern die vorgesehene Ablage), unter `betrieb/social/` und
`auftraege/freigabe/`. Ohne Schluessel im macOS-Schluesselbund laeuft jede
Funktion im Zustand "nicht_verbunden" — kein Absturz, kein Netzaufruf, kein
Retry-Sturm.

**Seit CF-4 gibt es einen echten Lese-Weg (Instagram, Meta-Graph-API).** Der
Veroeffentlichungsweg existiert als Code (`instagram_veroeffentlichen_aus_tagesliste`),
ist aber **GESPERRT** (`VEROEFFENTLICHEN_GESPERRT = True`, siehe dort) und liefert
IMMER `gesperrt_nach_ablehnung`, ohne jede Pruefung, ohne Netzaufruf. Grund: ZWEI
unabhaengige Opus-Endprüfungen haben das Tor am selben Tag abgelehnt — die erste,
weil eine reine Zeilennummer-Pruefung Inhalt/Marke/Kanal frei liess; die zweite,
NACH einer ersten Nachbesserung, mit zwei nachgewiesenen Umgehungen: (a) ein an
Tag 1 nie freigegebener Beitrag liess sich veroeffentlichen, indem an Tag 2 unter
derselben Nummer ein anderer Beitrag freigegeben wurde (das liegen gebliebene
Ticket von Tag 1 passte noch), (b) der Logo-Nachweis (Hausregel A6c) prüfte ein
anderes Bild als das tatsaechlich hochgeladene, weil `medium_rel` und `medien_url`
nicht aneinander gebunden sind. **Bis ein CF-5-Auftrag den vollstaendigen
11-Punkte-Katalog der zweiten Ablehnung umsetzt und eine DRITTE, unabhaengige
Pruefung besteht, bleibt der Schalter auf True** — siehe
`entscheidungen/2026-09-28_social-media-zentrale-stufe3-instagram.md` und die
CF-4-Meldung fuer die vollstaendigen Befunde. Volle Zusammenfuehrung mit dem
bestehenden, kern-eigenen Tor `jack_veroeffentlichung.py` (Paket 5, das die
noetige Strenge — Pruefsumme ueber Bytes statt URL-Text, Vorgangskennung,
Klaerfunktion bei ungewissem Ausgang — bereits vormacht) braucht zusaetzlich eine
Abstimmung mit dem Kanal kern (die Datei liegt ausserhalb dieses Dateigebiets).

**Hausregel A5 („Ich lösche nichts. Nie.“):** Dieses Modul löscht keine Zeile
automatisch. Fällige Leads werden nur GEKENNZEICHNET und als Freigabe-Karte
vorgelegt; Tickets werden nur verbraucht (umbenannt), nie gelöscht.

Quellen: CF-2-Bericht (`00_Marken/CASHFLOW_KOMPASS/05_Marketing/social/2026-09-27_Kanalinventar_Anbindung.md`),
Auftrag 45.1 Aufgaben 4-8+10, `_Hook_Playbook.md`, `jack_veroeffentlichung.py` (Vorbild fuer das Tor-Muster).
"""
import datetime as dt
import hashlib
import http.client
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("Europe/Vienna")

# jack_medien.py ist kern-eigen (README-Dateizustaendigkeit) — hier NUR gelesen
# (logo_nachweis), nichts daran geaendert, kein Schreibzugriff auf das Modul.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import jack_medien
except ImportError:
    jack_medien = None

# Auftrag 12.1 schlägt 6 Monate ohne Kontakt vor — NICHT vom Patron bestätigt
# (siehe `entscheidungen/`, keine Freigabedatei gefunden, Stand 28.09.2026).
# Die Frist läuft hier ab dem ERKENNEN des Leads, nicht ab dem letzten Kontakt
# (kein Kontakt-Neustart implementiert — das wäre eine eigene, größere Regel).
LEAD_FRIST_TAGE_VORSCHLAG = 180


def now():
    return dt.datetime.now(ZONE)


def jack_wurzel():
    return Path(os.environ.get("JACK_SOCIAL_WURZEL") or Path(__file__).resolve().parent)


def holding_wurzel(root=None):
    root = root or jack_wurzel()
    return Path(root).resolve().parents[1]


# ----------------------------------------------------------- Konfiguration
KONFIG_DATEI = "social_kanaele.json"


def lade_kanaele(root=None):
    root = root or jack_wurzel()
    pfad = Path(root) / "betrieb" / KONFIG_DATEI
    if not pfad.is_file():
        return []
    return json.loads(pfad.read_text(encoding="utf-8"))["kanaele"]


# ------------------------------------------------------- Schluesselbund (macOS)
def schluessel_lesen(schluesselbund_name):
    """Liest ein Token aus dem macOS-Schluesselbund (Muster PATRONOS-Schluesselinventur:
    `security find-generic-password -s <Dienst> -w`). Kein Name/kein Schluessel/kein
    macOS -> None, niemals eine Ausnahme nach aussen. Ein LEERER Name wird NICHT
    abgefragt (Fund Opus-Endprüfung: ein leerer Dienstname könnte sonst einen
    fremden Schlüsselbund-Eintrag treffen und den Kanal fälschlich als verbunden zählen)."""
    if not schluesselbund_name:
        return None
    try:
        r = subprocess.run(
            ["security", "find-generic-password", "-s", schluesselbund_name, "-w"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0:
            return None
        wert = r.stdout.strip()
        return wert or None
    except (OSError, subprocess.SubprocessError):
        return None


# --------------------------------------------------------- Kennzahlen-Zentrale
def kennzahlen_kanal(kanal, root=None):
    """Ein Kanal-Eintrag -> Kennzahlen-Zeile. Ohne Schluessel: Zustand 'nicht_verbunden',
    kein API-Aufruf. Fuer Instagram/CASHFLOW_KOMPASS steht seit CF-4 echter Abrufcode
    (instagram_profil_lesen/-medien_lesen); alle anderen Plattformen haben noch keinen
    Abrufcode (kein Blindflug ohne getestete, offizielle Funktion)."""
    token = schluessel_lesen(kanal.get("schluesselbund_name"))
    basis = {
        "marke": kanal["marke"], "plattform": kanal["plattform"], "handle": kanal["handle"],
        "zeit": now().isoformat(timespec="seconds"),
    }
    if token is None:
        basis.update({"zustand": "nicht_verbunden", "grund": "kein Schluessel im Schluesselbund (%s)"
                      % (kanal.get("schluesselbund_name") or "kein Name hinterlegt")})
        return basis
    if kanal["plattform"] == "Instagram" and kanal.get("ig_user_id"):  # M-16: jede Marke mit ig_user_id
        profil = instagram_profil_lesen(root, kanal)
        if profil.get("zustand") != "gelesen":
            basis.update({"zustand": profil.get("zustand", "fehler"), "grund": "Instagram-Profilabruf fehlgeschlagen"})
            return basis
        medien = instagram_medien_lesen(root, kanal)
        insights = instagram_insights_konto(root, kanal)
        # Fund Opus-Endprüfung CF-4: "gelesen" wurde vorher fest gesetzt, auch wenn
        # der Medienabruf selbst fehlschlug (falscher Zustand). Jetzt ehrlich: nur
        # wenn Profil UND Medien wirklich gelesen wurden, gilt der Kanal als "gelesen".
        basis.update({
            "zustand": "gelesen" if medien.get("zustand") == "gelesen" else "teilweise_gelesen",
            "medien_zustand": medien.get("zustand"),
            "followers_count": profil.get("followers_count"), "media_count": profil.get("media_count"),
            "anzahl_medien_30tage": len(medien.get("medien", [])),
            "insights_zustand": insights.get("zustand"), "insights_werte": insights.get("werte"),
        })
        return basis
    # M-16: Lese-Wege Facebook/YouTube/TikTok/LinkedIn (jack_social_lesen.py, nur lesend)
    import jack_social_lesen as jl
    lesen = {"Facebook": jl.facebook_seite_lesen, "YouTube": jl.youtube_lesen, "TikTok": jl.tiktok_lesen,
             "LinkedIn_Unternehmensseite": jl.linkedin_lesen}.get(kanal["plattform"])
    erg = lesen(kanal) if lesen else None
    if erg is not None:
        basis.update(erg)
        return basis
    # Alle uebrigen Plattformen: kein Abrufcode in diesem Lauf gebaut - CF-3-Grenze.
    basis.update({"zustand": "verbunden_kein_abruf_gebaut",
                  "grund": "Schluessel vorhanden, aber kein Plattform-Abrufcode in diesem Lauf gebaut"})
    return basis


def kennzahlen_tag(root=None, jetzt=None):
    """Schreibt 00_Marken/<MARKE>/05_Marketing/social/kennzahlen/<datum>.json (Tagesschnitt,
    ueberschrieben je Lauf) und haengt an .../kennzahlen.jsonl an (Verlauf, bewusst mit
    mehreren Zeilen je Tag, falls mehrfach aufgerufen — ein Zeitstempel je Zeile, nichts
    wird zusammengefasst oder verworfen). Gibt die Liste der Zeilen zurueck."""
    root = root or jack_wurzel()
    jetzt = jetzt or now()
    zeilen = [kennzahlen_kanal(k, root) for k in lade_kanaele(root)]
    je_marke = {}
    for z in zeilen:
        je_marke.setdefault(z["marke"], []).append(z)
    for marke, zeug in je_marke.items():
        ordner = holding_wurzel(root) / "00_Marken" / marke / "05_Marketing" / "social" / "kennzahlen"
        ordner.mkdir(parents=True, exist_ok=True)
        (ordner / ("%s.json" % jetzt.date())).write_text(
            json.dumps(zeug, ensure_ascii=False, indent=2), encoding="utf-8")
        with open(ordner.parent / "kennzahlen.jsonl", "a", encoding="utf-8") as f:
            for z in zeug:
                f.write(json.dumps(z, ensure_ascii=False) + "\n")
    return zeilen


def wochenbericht(marke, root=None, jetzt=None):
    """'Was funktioniert' fuer eine Marke — ehrlich 'keine Daten', solange kein Kanal
    verbunden ist. Erfindet nie ein Format/eine Uhrzeit ohne Beleg aus der Kennzahlenreihe."""
    root = root or jack_wurzel()
    jetzt = jetzt or now()
    pfad = holding_wurzel(root) / "00_Marken" / marke / "05_Marketing" / "social" / "kennzahlen.jsonl"
    zeilen = []
    if pfad.is_file():
        for z in pfad.read_text(encoding="utf-8").splitlines():
            try:
                zeilen.append(json.loads(z))
            except ValueError:
                continue
    # Fund Opus-Endprüfung CF-4: "nicht nicht_verbunden" zaehlte auch Fehlerzustaende
    # (token ungueltig, Ratenlimit) mit. Nur "gelesen" ist eine ECHTE Messung.
    gelesen = [z for z in zeilen if z.get("zustand") == "gelesen"]
    fehler = [z for z in zeilen if z.get("zustand") not in ("gelesen", "nicht_verbunden")]
    text = ["# Wochenbericht Social — %s" % marke, "", "Erstellt %s." % jetzt.strftime("%d.%m.%Y %H:%M")]
    if not gelesen and not fehler:
        text += ["", "**Keine Daten.** Kein Kanal dieser Marke ist verbunden "
                 "(Konto/Schluessel fehlt) — siehe `auftraege/freigabe/2026-09-28_KONTO_*.md`.", ""]
    elif not gelesen:
        text += ["", "**Keine Daten.** %d Versuch(e), aber kein einziger erfolgreich (letzter Zustand: %s) — "
                 "siehe `betrieb/social_kanaele.json`." % (len(fehler), fehler[-1].get("zustand")), ""]
    else:
        text += ["", "%d echte Messung(en) vorhanden. Formatauswertung ('was funktioniert') "
                 "braucht mehr Beitragszahlen mit Insights als heute vorliegen — noch keine "
                 "Aussage, um nichts zu erfinden." % len(gelesen), ""]
    return "\n".join(text)


# ------------------------------------------------ Kommentare/DMs: Sortierung + Leads
# Reihenfolge = Prüfreihenfolge bei Mehrfachtreffer. Rechtliches und Spam VOR
# Kaufinteresse (Fund Opus-Endprüfung: "Was kostet eine Abmahnung?" ist rechtlich,
# kein Lead).
_MUSTER = [
    ("rechtliches", re.compile(r"\b(abmahnung|anwalt|klage|dsgvo-beschwerde|widerspreche der (nutzung|verarbeitung))\b", re.I)),
    ("spam", re.compile(r"(https?://\S+.*https?://\S+|folge mir für folgen|crypto giveaway|kostenlos gewinnen jetzt klicken)", re.I)),
    ("kaufinteresse", re.compile(
        r"\b(wie viel kostet|was kostet|wo kaufe ich|wo kann ich das kaufen|link zum kauf|wie melde ich mich an)\b"
        r"|(?:^|\s)preis(e)?\s*\??\s*$", re.I)),
    ("kritik", re.compile(r"\b(funktioniert nicht|schlecht|enttäuscht|nie wieder|betrug|unseriös)\b", re.I)),
    ("lob", re.compile(r"\b(super|klasse|toll|danke für|hilfreich|genau das gebraucht)\b", re.I)),
    ("frage", re.compile(r"\?\s*$|^(wie|was|wann|warum|wo|wer)\b", re.I)),
]


def sortiere_kommentar(text):
    """Regelbasiert, kein Modellaufruf. Reihenfolge siehe _MUSTER (Rechtliches/Spam
    vor Kaufinteresse). Kein Treffer -> 'unklar'."""
    for kategorie, muster in _MUSTER:
        if muster.search(text or ""):
            return kategorie
    return "unklar"


def erkenne_lead(text, herkunft, marke, plattform, jetzt=None):
    """Kaufinteresse -> Lead-Zeile, sonst None. Personenbezug nur das Notwendige
    (Handle/Text/Datum), keine weiteren Merkmale. Loeschdatum ist ein VORSCHLAG
    (LEAD_FRIST_TAGE_VORSCHLAG), keine Loeschung findet hier statt."""
    if sortiere_kommentar(text) != "kaufinteresse":
        return None
    jetzt = jetzt or now()
    return {
        "marke": marke, "plattform": plattform, "herkunft_handle": herkunft, "text": text,
        "erkannt_am": jetzt.isoformat(timespec="seconds"),
        "loeschen_ab": (jetzt + dt.timedelta(days=LEAD_FRIST_TAGE_VORSCHLAG)).date().isoformat(),
        "loeschfrist_hinweis": "Vorschlag 12.1 (%d Tage ab Erkennung, kein Kontakt-Neustart) — "
                                "Patron-Freigabe aussteht" % LEAD_FRIST_TAGE_VORSCHLAG,
        "uebergabe_an": "verfahren/_Angebotsentwurf.md",
    }


def _leads_pfad(marke, root):
    ordner = holding_wurzel(root) / "00_Marken" / marke / "05_Marketing" / "social"
    return ordner, ordner / ("leads_%s.jsonl" % marke)


def leads_anhaengen(marke, leads, root=None):
    root = root or jack_wurzel()
    if not leads:
        return 0
    ordner, pfad = _leads_pfad(marke, root)
    ordner.mkdir(parents=True, exist_ok=True)
    with open(pfad, "a", encoding="utf-8") as f:
        for l in leads:
            f.write(json.dumps(l, ensure_ascii=False) + "\n")
    return len(leads)


def _leads_lesen(pfad):
    """Liest leads_<marke>.jsonl zeilenweise; eine defekte/unvollstaendige Zeile
    wird uebersprungen (mit Vermerk), bricht aber NICHT den ganzen Lauf ab
    (Fund Opus-Endprüfung)."""
    gueltig, uebersprungen = [], 0
    if not pfad.is_file():
        return gueltig, uebersprungen
    for zeile in pfad.read_text(encoding="utf-8").splitlines():
        if not zeile.strip():
            continue
        try:
            e = json.loads(zeile)
            dt.date.fromisoformat(e["loeschen_ab"])  # Pflichtfeld pruefen
        except (ValueError, KeyError, TypeError):
            uebersprungen += 1
            continue
        gueltig.append(e)
    return gueltig, uebersprungen


def leads_faellige_kennzeichnen(marke, root=None, jetzt=None):
    """A5 ('Ich lösche nichts. Nie.'): KEINE Löschung. Liest nur und gibt die Leads
    zurück, deren Löschdatum erreicht ist — zur Vorlage in einer Freigabe-Karte
    (siehe leads_loeschung_karte). Die Datei bleibt unveraendert."""
    root = root or jack_wurzel()
    jetzt = jetzt or now()
    _, pfad = _leads_pfad(marke, root)
    gueltig, uebersprungen = _leads_lesen(pfad)
    faellig = [e for e in gueltig if dt.date.fromisoformat(e["loeschen_ab"]) <= jetzt.date()]
    return faellig, uebersprungen


def leads_loeschung_karte(marke, faellige, root=None, jetzt=None):
    """Schreibt EINE Freigabe-Karte mit den fälligen Leads — der Patron entscheidet,
    ob/wann sie tatsächlich entfernt werden (A5: JACK löscht nichts von selbst).
    Ohne fällige Leads wird keine Karte geschrieben."""
    root = root or jack_wurzel()
    jetzt = jetzt or now()
    if not faellige:
        return None
    ordner = Path(root) / "auftraege" / "freigabe"
    ordner.mkdir(parents=True, exist_ok=True)
    pfad = ordner / ("%s_LEADS_LOESCHFRIST_%s.md" % (jetzt.date().isoformat(), marke))
    zeilen = ["---", "art: freigabe", "handelnder: Patron", "marke: %s" % marke,
              "kanal: cashflow (CF-3)", "datum: %s" % jetzt.date().isoformat(), "---", "",
              "# Fällige Lead-Löschfrist — %s (%s)" % (marke, jetzt.date().isoformat()), "",
              "JACK löscht nichts von selbst (Hausregel A5). Diese %d Zeile(n) haben laut "
              "Vorschlag 12.1 ihre Frist erreicht — bitte entscheiden: LÖSCHEN oder VERLÄNGERN." % len(faellige),
              "", "| Handle | Plattform | Erkannt am | Löschen ab | Entscheidung |",
              "|---|---|---|---|---|"]
    for e in faellige:
        zeilen.append("| %s | %s | %s | %s | LÖSCHEN / VERLÄNGERN |" %
                      (e["herkunft_handle"], e["plattform"], e["erkannt_am"], e["loeschen_ab"]))
    pfad.write_text("\n".join(zeilen) + "\n", encoding="utf-8")
    return pfad


# ---------------------------------------------------------------------- UTM
def baue_utm(plattform, marke, datum, nr):
    """utm_source=<plattform>&utm_medium=social&utm_campaign=<marke>_<datum>_<nr>. Reine Textbildung."""
    for feld, wert in (("plattform", plattform), ("marke", marke)):
        if not re.match(r"^[a-z0-9_-]+$", wert or "", re.I):
            raise ValueError("ungueltiges Zeichen in %s: %r" % (feld, wert))
    return "utm_source=%s&utm_medium=social&utm_campaign=%s_%s_%s" % (plattform.lower(), marke, datum, nr)


def umsatz_je_beitrag(marke, root=None):
    """Ehrlich: ohne Klick-/Kaufquelle ist nichts messbar. Schaetzt nie."""
    return {"marke": marke, "status": "nicht messbar bis Kontoanbindung (Kennzahlen) UND Shop-Livegang "
            "(CASHFLOW: an Bilanz 30.09. gekoppelt) vorliegen"}


class KarteExistiertBereits(RuntimeError):
    """Fuer Marke+Tag existiert schon eine Tagesliste-Karte — nicht ueberschreiben
    (Fund Opus-Endprüfung CF-5 Runde 3: ein stilles Ueberschreiben haette bereits
    eingetragene Entscheidungen des Patrons vernichtet, A5)."""


# --------------------------------------------------------------- Tagesliste
def tagesliste_karte(marke, beitraege, root=None, jetzt=None):
    """Schreibt EINE Freigabe-Karte je Tag UND Marke (Dateiname traegt die Marke —
    `pruefe_freigabe` verlangt genau dieses Muster). `beitraege`: Liste von
    {"nr","kanal","text_oder_skript","art":"beitrag"|"antwort"}; fuer Instagram-Zeilen
    zusaetzlich `beitrag` = {"medien_url","text","medien_typ","medium_rel"} (Ergebnis von
    `medien_bereitstellen` + das lokale Ausgangsbild). Fuer diese Zeilen gilt seit CF-5:
    - die "Kanal"-Spalte wird auf den KANONISCHEN Wert `instagram_kanal_string()` gesetzt,
      NICHT auf b["kanal"] (Punkt 5: exakter Kanal, kein frei waehlbarer Text),
    - der Text traegt zusaetzlich Bild-URL + Kurz-Pruefsumme, sichtbar fuer den Patron
      (Punkt 4),
    - `ticket_erzeugen` wird VOR jedem Schreiben der Datei aufgerufen (Punkt 3: existiert
      fuer nr+marke schon ein Ticket, bricht **TicketKonflikt** die ganze Karte ab — kein
      Teilschreiben, keine neue Karte mit einer Nummer, die schon vergeben ist).
    Runde-3-Auflage A5 (verschaerft nach der VIERTEN Opus-Ablehnung): die Vorpruefung
    laeuft jetzt VOLLSTAENDIG, bevor IRGENDEIN Ticket entsteht — doppelte Nummern in
    derselben Liste, ein Nummern-Muster-Fehler oder ein ungueltiges Bild IN EINER
    SPAETEREN Zeile duerfen fuer eine fruehere Zeile kein Ticket mehr entstehen lassen.
    Eine bestehende Karte fuer Marke+Tag wird NIE stillschweigend ueberschrieben
    (**KarteExistiertBereits**). Kein Versand, nur die Karte (+ Ticket)."""
    root = root or jack_wurzel()
    jetzt = jetzt or now()
    datum = jetzt.date().isoformat()
    ordner = Path(root) / "auftraege" / "freigabe"
    ordner.mkdir(parents=True, exist_ok=True)
    pfad = ordner / ("%s_SOCIAL_TAGESLISTE_%s.md" % (datum, marke))
    if pfad.exists():
        raise KarteExistiertBereits("Karte %s existiert schon — nicht ueberschreiben" % pfad.name)

    def _sauber(s):
        return str(s).replace("|", "/").replace("\n", " ")

    # Erster Durchgang: NUR pruefen, NICHTS anlegen. Doppelte Nummern in dieser Liste
    # SOFORT ablehnen — bevor auch nur ein Ticket existiert.
    gesehene_nr = set()
    for b in beitraege:
        nr_sauber = _sauber(b["nr"])
        if nr_sauber in gesehene_nr:
            raise ValueError("doppelte_nr_in_liste: %r" % nr_sauber)
        gesehene_nr.add(nr_sauber)
        if "Instagram" in b["kanal"] and b.get("beitrag"):
            if not _NR_MUSTER.fullmatch(str(b["nr"])):
                raise ValueError("nr_falsches_muster: %r" % (b["nr"],))
            if _medium_bytes_pruefsumme(root, b["beitrag"].get("medium_rel", "")) is None:
                raise ValueError("medium_rel_ungueltig fuer Nr. %r" % (b["nr"],))
            _bildunterschrift_pruefen(b["beitrag"].get("text", ""))
            # Runde 6, adversariale Prüfung: medien_url VOR jedem Schreiben pruefen —
            # nicht erst beim Anzeigen (siehe unten).
            _medien_url_pruefen(root, b["beitrag"].get("medien_url", ""))
            if _ticket_existiert_bereits(root, marke, b["nr"]):
                raise TicketKonflikt("Ticket fuer %s Nr. %s existiert bereits — neue Nummer verwenden" % (marke, b["nr"]))

    zeilen_inhalt = []  # (nr, kanal_spalte, art, text) — vor jedem Schreiben fertig, fuer Ticket+Karte gleich
    ticket_auftraege = []  # (nr, zeile, medium_rel) — erst NACH der Vorpruefung ALLER Zeilen angelegt
    for b in beitraege:
        ist_instagram = "Instagram" in b["kanal"]
        if ist_instagram and b.get("beitrag"):
            beleg = b["beitrag"]
            # Fund Opus-Endprüfung CF-5 Runde 3, Auflage 2: der Kanal wird jetzt aus der
            # MARKE dieser Karte abgeleitet, nicht mehr pauschal aus dem CASHFLOW-Konto.
            kanal_spalte = instagram_kanal_string(root, marke=marke)
            # Fund Runde 3, Auflage 1: die Karte zeigt jetzt GENAU den Text, der auch
            # gesendet wird (beleg["text"], die tatsaechliche Bildunterschrift) — nicht
            # mehr ein separates "text_oder_skript"-Feld, das vom Ticket abweichen konnte.
            bildunterschrift = _bildunterschrift_pruefen(beleg.get("text", ""))
            # Runde 6, adversariale Prüfung, Nachweis "Karte zeigt anderes Bild als
            # gepostet wird": medien_url UND Pruefsumme werden NIE ungeprueft vom
            # Aufrufer uebernommen — medien_url ist bereits geprueft (Vorpruefung oben),
            # die Pruefsumme wird IMMER frisch aus medium_rel berechnet, nie aus dem
            # caller-seitigen `pruefsumme_bytes` (das war frei waehlbar und stand in
            # keinem Bezug zum tatsaechlich gebundenen Bild).
            medien_url_geprueft = _medien_url_pruefen(root, beleg.get("medien_url", ""))
            pruefsumme = _medium_bytes_pruefsumme(root, beleg.get("medium_rel", ""))
            # KEIN Zeilenumbruch (die Zeile ist eine Markdown-Tabellenzeile, ein
            # Umbruch wuerde sie zerreissen) — Trenner " · " statt "\n\n".
            text = "%s · [Bild: %s · Prüfsumme %s]" % (
                _sauber(bildunterschrift), medien_url_geprueft, pruefsumme[:12])
        else:
            kanal_spalte = _sauber(b["kanal"])
            text = _sauber(b["text_oder_skript"])
        zeilen_inhalt.append((_sauber(b["nr"]), kanal_spalte, _sauber(b["art"]), text))
        if ist_instagram and b.get("beitrag"):
            beleg = b["beitrag"]
            ticket_auftraege.append((b["nr"],
                                     {"kanal": kanal_spalte, "art": _sauber(b["art"]), "text": text,
                                      "bildunterschrift": bildunterschrift, "medien_url": medien_url_geprueft},
                                     beleg["medium_rel"]))

    # Erst wenn ALLE Zeilen die Vorpruefung bestanden haben: Tickets anlegen, dann Karte schreiben.
    for nr, zeile, medium_rel in ticket_auftraege:
        ticket_erzeugen(root, marke, nr, pfad, zeile, medium_rel, jetzt)

    zeilen = ["---", "art: freigabe", "handelnder: Patron", "marke: %s" % marke,
              "kanal: cashflow (CF-3/CF-5)", "datum: %s" % datum, "---", "",
              "# Social-Tagesliste %s — %s" % (datum, marke), "",
              "Kein Beitrag/keine Antwort wird ohne dein FREIGEBEN veroeffentlicht/versendet.", "",
              "| Nr | Kanal | Art | Text/Skript | Entscheidung |", "|---|---|---|---|---|"]
    for nr, kanal_spalte, art, text in zeilen_inhalt:
        zeilen.append("| %s | %s | %s | %s | FREIGEBEN / ZURÜCK |" % (nr, kanal_spalte, art, text))
    pfad.write_text("\n".join(zeilen) + "\n", encoding="utf-8")
    return pfad


# -------------------------------------------------- Instagram Graph API (CF-4)
# Nachtrag 28.09.2026 (CF-4, Patron-Entscheidung 28.09. 15:00): echte Anbindung.
# LESEN (Profil, Medien, Insights) darf ohne weitere Freigabe laufen — der Token
# wurde genau dafür vom Patron erzeugt. VERÖFFENTLICHEN (media_publish) darf
# NUR über `instagram_veroeffentlichen_aus_tagesliste` laufen, und das liest die
# echte Tagesliste-Karte und ruft `_graph_post` ausschliesslich dann auf, wenn
# dort in der Zeile der Marke wörtlich "FREIGEBEN" steht (siehe `pruefe_freigabe`).
# Kein anderer Codepfad in dieser Datei ruft media_publish o.ä. auf.
GRAPH_BASIS = "https://graph.facebook.com/v25.0"


def _graph_fehler_zustand(http_code, antwort):
    """Bildet HTTP/Graph-Fehlercodes auf einen Zustand ab, statt eine Ausnahme
    nach aussen zu werfen — kein Retry-Sturm, kein Absturz des Kennzahlen-Laufs."""
    code = None
    try:
        code = antwort.get("error", {}).get("code")
    except AttributeError:
        pass
    if http_code == 401 or code == 190:
        return "token_abgelaufen_oder_ungueltig"
    if code in (4, 17, 32, 613):
        return "ratenlimit"
    return "fehler_%s_%s" % (http_code, code)


def _antwort_lesen(rohbytes):
    """Parst eine Erfolgsantwort robust: (ok, wert). Ungueltiges JSON oder eine
    Antwort, die kein Objekt ist, wird NICHT als Absturz nach aussen geworfen
    (Fund Opus-Endprüfung CF-4: ungueltiges JSON bei HTTP 200 liess den Lauf
    vorher abstuerzen)."""
    try:
        wert = json.loads(rohbytes.decode())
    except (ValueError, UnicodeDecodeError):
        return False, "antwort_kein_json"
    if not isinstance(wert, dict):
        return False, "antwort_unerwartete_form"
    return True, wert


_NETZFEHLER = (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException)


def _graph_get(pfad, params, token, timeout=20):
    """Reiner Lesezugriff. Gibt (True, json) oder (False, zustand) zurueck —
    wirft nie eine Ausnahme wegen einer Graph-Fehlermeldung oder einer defekten
    Antwort nach aussen (auch Verbindungsabbrueche wie IncompleteRead abgefangen —
    Fund Opus-Endprüfung CF-4)."""
    params = dict(params); params["access_token"] = token
    url = "%s/%s?%s" % (GRAPH_BASIS, pfad, urllib.parse.urlencode(params))
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=timeout) as r:
            ok, wert = _antwort_lesen(r.read())
            return (True, wert) if ok else (False, wert)
    except urllib.error.HTTPError as e:
        # Fund CF-5 (eigener Test, Punkt 9): e.read() kann selbst eine Ausnahme werfen
        # (Verbindungsabbruch beim Lesen des Fehlerkoerpers) — auch das abfangen.
        try:
            antwort = json.loads(e.read().decode())
        except (ValueError, UnicodeDecodeError, OSError, http.client.HTTPException):
            antwort = {}
        return False, _graph_fehler_zustand(e.code, antwort)
    except _NETZFEHLER:
        return False, "netz_nicht_erreichbar"


def _graph_post(pfad, daten, token, timeout=30):
    """Schreibzugriff. NUR von `instagram_veroeffentlichen_aus_tagesliste`
    aufgerufen — siehe Sperrtest in test_cf4.py, der das im Quelltext prueft."""
    daten = dict(daten); daten["access_token"] = token
    body = urllib.parse.urlencode(daten).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request("%s/%s" % (GRAPH_BASIS, pfad), data=body), timeout=timeout) as r:
            ok, wert = _antwort_lesen(r.read())
            return (True, wert) if ok else (False, wert)
    except urllib.error.HTTPError as e:
        # Fund CF-5 (eigener Test, Punkt 9): e.read() kann selbst eine Ausnahme werfen
        # (Verbindungsabbruch beim Lesen des Fehlerkoerpers) — auch das abfangen.
        try:
            antwort = json.loads(e.read().decode())
        except (ValueError, UnicodeDecodeError, OSError, http.client.HTTPException):
            antwort = {}
        return False, _graph_fehler_zustand(e.code, antwort)
    except _NETZFEHLER:
        return False, "netz_nicht_erreichbar"


def _ig_kanal(root, marke=None):
    """`marke=None`: alter Vorbelegungspfad (nur Lesen/Kennzahlen, CASHFLOW_KOMPASS) —
    unveraendert, keine Regression fuer bestehende Lesefunktionen. `marke=<Wert>`:
    liefert NUR den Kanal genau dieser Marke, oder None (Fund Opus-Endprüfung CF-5
    Runde 3: `_ig_kanal(root)` lieferte in Tor B IMMER das CASHFLOW-Konto, egal
    welche Marke auf der Karte stand — eine PATRONOS-Karte wurde still auf das
    CASHFLOW-Konto veroeffentlicht. Ab jetzt bindet Tor B den Kanal explizit an
    die Marke des Beitrags, siehe instagram_veroeffentlichen_aus_tagesliste).
    Fund Runde 3, VIERTE Ablehnung: existieren fuer eine Marke ZWEI Instagram-Kanal-
    Eintraege, gewann still der erste — ab jetzt ist das ein sicherer Fehlschlag
    (None), nicht eine stille Wahl."""
    treffer = []
    for k in lade_kanaele(root):
        if k["plattform"] != "Instagram":
            continue
        if marke is not None:
            if k["marke"] == marke:
                treffer.append(k)
        elif k["marke"] == "CASHFLOW_KOMPASS":
            return k
    if marke is None:
        return None
    return treffer[0] if len(treffer) == 1 else None


def instagram_profil_lesen(root=None, kanal=None):
    root = root or jack_wurzel()
    kanal = kanal or _ig_kanal(root)
    if not kanal:
        return {"zustand": "kein_kanal_konfiguriert"}
    token = schluessel_lesen(kanal.get("schluesselbund_name"))
    if token is None:
        return {"zustand": "nicht_verbunden"}
    ok, erg = _graph_get(kanal["ig_user_id"], {"fields": "username,followers_count,media_count,biography"}, token)
    if not ok:
        return {"zustand": erg}
    erg["zustand"] = "gelesen"
    return erg


def instagram_medien_lesen(root=None, kanal=None, tage=30):
    root = root or jack_wurzel()
    kanal = kanal or _ig_kanal(root)
    if not kanal:
        return {"zustand": "kein_kanal_konfiguriert", "medien": []}
    token = schluessel_lesen(kanal.get("schluesselbund_name"))
    if token is None:
        return {"zustand": "nicht_verbunden", "medien": []}
    seit = (now() - dt.timedelta(days=tage)).strftime("%Y-%m-%d")
    # Fund Opus-Endprüfung CF-4: das Medien-Kante-Suffix "/media" fehlte — ohne es
    # traf der Aufruf den Profil-Endpunkt, nicht die Medienliste.
    ok, erg = _graph_get(kanal["ig_user_id"] + "/media", {
        "fields": "id,caption,media_type,timestamp,permalink,like_count,comments_count",
        "since": seit,
    }, token)
    if not ok:
        return {"zustand": erg, "medien": []}
    return {"zustand": "gelesen", "medien": erg.get("data", [])}


def instagram_insights_medium(media_id, root=None, kanal=None):
    root = root or jack_wurzel()
    kanal = kanal or _ig_kanal(root)
    token = schluessel_lesen(kanal.get("schluesselbund_name")) if kanal else None
    if token is None:
        return {"zustand": "nicht_verbunden"}
    ok, erg = _graph_get(media_id + "/insights", {"metric": "reach,saved,shares"}, token)
    if not ok:
        return {"zustand": erg}
    return {"zustand": "gelesen", "werte": erg.get("data", [])}


def instagram_insights_konto(root=None, kanal=None, tage=7):
    root = root or jack_wurzel()
    kanal = kanal or _ig_kanal(root)
    if not kanal:
        return {"zustand": "kein_kanal_konfiguriert"}
    token = schluessel_lesen(kanal.get("schluesselbund_name"))
    if token is None:
        return {"zustand": "nicht_verbunden"}
    bis = now(); seit = bis - dt.timedelta(days=tage)
    # Fund CF-4b (echter Aufruf 28.09.2026, Fehler #100 belegt): "reach" verlangt
    # metric_type=time_series, "profile_views"/"accounts_engaged" verlangen
    # metric_type=total_value — Meta lehnt eine gemischte Anfrage ab. Zwei Aufrufe,
    # Ergebnis zusammengefuehrt; ein einzelner Fehler bricht den anderen nicht ab.
    zeitfenster = {"period": "day", "since": int(seit.timestamp()), "until": int(bis.timestamp())}
    ok1, erg1 = _graph_get(kanal["ig_user_id"] + "/insights",
                           dict(zeitfenster, metric="reach", metric_type="time_series"), token)
    ok2, erg2 = _graph_get(kanal["ig_user_id"] + "/insights",
                           dict(zeitfenster, metric="profile_views,accounts_engaged", metric_type="total_value"), token)
    if not ok1 and not ok2:
        return {"zustand": erg1}
    werte = (erg1.get("data", []) if ok1 else []) + (erg2.get("data", []) if ok2 else [])
    zustand = "gelesen" if (ok1 and ok2) else "teilweise_gelesen"
    return {"zustand": zustand, "werte": werte,
            "reach_zustand": "gelesen" if ok1 else erg1, "profil_zustand": "gelesen" if ok2 else erg2}


# ------------------------------------------------------ Medienspeicher (CF-5) ---
# Supabase Storage, Projekt gott-wald-holding (eu-central-1/Frankfurt) — Patron-
# Entscheidung 28.09.2026: bestehendes Projekt, KEIN neuer Dienst. Konfiguration in
# betrieb/social_kanaele.json -> "medienspeicher". OHNE Dienstschluessel
# (Schluesselbund GOTT_WALD_SUPABASE_HOLDING_DIENST, fehlte am 28.09.2026 — siehe
# CF-5_FRAGE.md) laeuft alles im Zustand 'nicht_verbunden', kein Netzaufruf. Alle
# drei Funktionen hier sind NUR gegen eine Attrappe getestet (kein echtes Supabase-
# Projekt erreichbar in diesem Lauf) — vor dem ersten echten Einsatz einmal echt
# pruefen (Upload+Download+Archiv eines Testbildes).
def _medienspeicher_konfig(root=None):
    root = root or jack_wurzel()
    pfad = Path(root) / "betrieb" / KONFIG_DATEI
    if not pfad.is_file():
        return {}
    return json.loads(pfad.read_text(encoding="utf-8")).get("medienspeicher") or {}


def _supabase_dienstschluessel(root=None):
    cfg = _medienspeicher_konfig(root)
    name = cfg.get("schluesselbund_name")
    return schluessel_lesen(name) if name else None


def _supabase_fehler_zustand(http_code, rohtext):
    if http_code in (401, 403):
        return "supabase_recht_fehlt"
    if http_code == 404:
        return "supabase_ziel_fehlt"
    return "fehler_%s" % http_code


def _supabase_upload(cfg, bucket, objektpfad, inhalt, schluessel, content_type, timeout=30):
    url = "https://%s.supabase.co/storage/v1/object/%s/%s" % (cfg.get("projekt_ref"), bucket, objektpfad)
    req = urllib.request.Request(url, data=inhalt, method="POST", headers={
        "Authorization": "Bearer %s" % schluessel, "apikey": schluessel, "Content-Type": content_type})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ok, wert = _antwort_lesen(r.read())
            return (True, wert) if ok else (False, wert)
    except urllib.error.HTTPError as e:
        try:
            roh = e.read().decode()
        except (OSError, UnicodeDecodeError, http.client.HTTPException):
            roh = ""
        return False, _supabase_fehler_zustand(e.code, roh)
    except _NETZFEHLER:
        return False, "netz_nicht_erreichbar"


def _herunterladen(url, timeout=30):
    """Nur https. Fund Opus-Endprüfung CF-5 Runde 3 (Nachweis E): ohne Schema-
    Pruefung nahm urlopen() auch `file://` an — ein lokaler Pfad haette so als
    'medien_url' durchgehen koennen. Jetzt: alles ausser https scheitert sicher,
    ohne jeden Zugriffsversuch."""
    if urllib.parse.urlparse(url).scheme != "https":
        return False, None
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return True, r.read()
    except (urllib.error.URLError,) + _NETZFEHLER:
        return False, None


def _erwarteter_medien_praefix(root):
    """Die einzige URL-Vorsilbe, die als medien_url akzeptiert wird: der konfigurierte
    OEFFENTLICHE Supabase-Bucket dieser Holding, https. None, wenn kein Medienspeicher
    konfiguriert ist (Auflage A3: Fund Runde 3, medien_url war an keinen Host/kein
    Schema gebunden — ein fremder Server haette geprüfte Bytes liefern koennen, waehrend
    Meta ein anderes Bild abruft)."""
    cfg = _medienspeicher_konfig(root)
    ref = cfg.get("projekt_ref")
    if not ref:
        return None
    bucket = cfg.get("bucket_oeffentlich", "social-medien")
    return "https://%s.supabase.co/storage/v1/object/public/%s/" % (ref, bucket)


_MEDIEN_URL_REST_MUSTER = re.compile(r"\A[A-Za-z0-9/_.-]+\.jpe?g\Z")


def _medien_url_pruefen(root, medien_url):
    """Auflage (Runde 6, adversariale Prüfung, Nachweis 'Freigabe ganz ohne den
    Patron'): `medien_url` landet UNGEFILTERT in der Freigabe-Karte (Markdown-Tabelle)
    — vorher lief sie NICHT durch `_sauber()`, ein `|` + Zeilenumbruch darin konnte eine
    zusaetzliche, bereits als 'FREIGEBEN' markierte Tabellenzeile einschleusen, ganz
    ohne Zutun des Patrons. Jetzt: `medien_url` MUSS auf den konfigurierten Supabase-
    Bucket zeigen (derselbe Praefix wie beim Veroeffentlichen) und danach nur aus einem
    sicheren Zeichensatz bestehen (kein '|', kein Zeilenumbruch, kein Leerzeichen).
    Wird VOR jedem Kartenschreiben und VOR jedem Ticket-Anlegen geprueft (kein
    Teilschreiben mit einer noch ungeprueften medien_url). Fund enge Nachprüfung
    (Runde 6, Auflage B): '..' oder '//' NACH dem Praefix zusaetzlich verboten — das
    Zeichenmuster allein liess Pfad-Segmente wie '../../' zu (kein Ausbruch aus dem
    eigenen Bucket-Server, aber die Zusage 'zeigt auf DIESEN Bucket' stimmte damit
    nicht mehr streng)."""
    praefix = _erwarteter_medien_praefix(root)
    if not isinstance(medien_url, str) or not praefix or not medien_url.startswith(praefix):
        raise ValueError("medien_url_ausserhalb_speicher: %r" % (medien_url,))
    rest = medien_url[len(praefix):]
    if not _MEDIEN_URL_REST_MUSTER.match(rest) or ".." in rest or "//" in rest:
        raise ValueError("medien_url_unsicheres_muster: %r" % (medien_url,))
    return medien_url


def medien_bereitstellen(marke, medium_rel, nr, root=None, jetzt=None):
    """Laedt eine lokale Bilddatei (muss im Vault liegen, kein Symlink) in den
    oeffentlichen Bucket und bestaetigt per Rueck-Download BYTEGLEICHHEIT (CF-5-Punkt
    7: 'medien_url liefert dieselben Bytes wie medium_rel'). Ohne Dienstschluessel/
    Konfiguration: zustand='nicht_verbunden'/'medienspeicher_nicht_konfiguriert',
    kein Netzaufruf."""
    root = root or jack_wurzel(); jetzt = jetzt or now()
    schluessel = _supabase_dienstschluessel(root)
    if schluessel is None:
        return {"zustand": "nicht_verbunden"}
    cfg = _medienspeicher_konfig(root)
    if not cfg.get("projekt_ref"):
        return {"zustand": "medienspeicher_nicht_konfiguriert"}
    vault = holding_wurzel(root)
    roh = vault / medium_rel
    # Fund CF-5 (eigener Test): is_symlink() NACH .resolve() prueft das aufgeloeste
    # Ziel, nie den Symlink selbst — deshalb zuerst auf dem unaufgeloesten Pfad pruefen.
    if roh.is_symlink():
        return {"zustand": "medium_ungueltig"}
    quelle = roh.resolve()
    if vault not in quelle.parents or not quelle.is_file():
        return {"zustand": "medium_ungueltig"}
    inhalt = quelle.read_bytes()
    pruefsumme = hashlib.sha256(inhalt).hexdigest()
    bucket = cfg.get("bucket_oeffentlich", "social-medien")
    objektpfad = "%s/%s/%02d/%s_%s_%s%s" % (marke, jetzt.year, jetzt.month, jetzt.date().isoformat(),
                                            nr, pruefsumme[:12], quelle.suffix.lower())
    ok, erg = _supabase_upload(cfg, bucket, objektpfad, inhalt, schluessel, "image/jpeg")
    if not ok:
        return {"zustand": erg}
    url = "https://%s.supabase.co/storage/v1/object/public/%s/%s" % (cfg["projekt_ref"], bucket, objektpfad)
    ok2, geladen = _herunterladen(url)
    if not ok2 or hashlib.sha256(geladen).hexdigest() != pruefsumme:
        return {"zustand": "bytes_nachweis_fehlgeschlagen", "url": url}
    return {"zustand": "bereitgestellt", "url": url, "pruefsumme_bytes": pruefsumme,
            "bucket": bucket, "objektpfad": objektpfad}


def medien_archivieren(bucket, objektpfad, root=None):
    """Kopiert das Objekt in den PRIVATEN Archiv-Bucket (A5: nur kopieren, nie
    loeschen — auch das Original im oeffentlichen Bucket bleibt bestehen; eine
    automatische Entfernung dort braucht eine eigene Freigabe-Entscheidung, siehe
    CF-5-Meldung). Download+Upload statt eines Supabase-'copy'-Aufrufs, weil dafuer
    keine echten Zugangsdaten zum Testen vorlagen — mit denselben, bereits geprueften
    Bausteinen (_herunterladen/_supabase_upload)."""
    root = root or jack_wurzel()
    schluessel = _supabase_dienstschluessel(root)
    if schluessel is None:
        return {"zustand": "nicht_verbunden"}
    cfg = _medienspeicher_konfig(root)
    quelle_url = "https://%s.supabase.co/storage/v1/object/public/%s/%s" % (cfg.get("projekt_ref"), bucket, objektpfad)
    ok, inhalt = _herunterladen(quelle_url)
    if not ok:
        return {"zustand": "quelle_nicht_lesbar"}
    archiv = cfg.get("bucket_archiv", "social-medien-archiv")
    ok2, erg = _supabase_upload(cfg, archiv, objektpfad, inhalt, schluessel, "image/jpeg")
    if not ok2:
        return {"zustand": erg}
    return {"zustand": "archiviert", "bucket": archiv, "objektpfad": objektpfad,
            "pruefsumme_bytes": hashlib.sha256(inhalt).hexdigest()}


# ---------------------------------------------------- Veröffentlichen (Tor B) ---
# ZWEITER kompletter Neubau nach ZWEI Opus-ABLEHNUNGEN (28.09.2026). CF-4-Fassung
# (Tor A) band nur den Zeileninhalt an ein Ticket, aber weder an das genaue Datum/
# den Kartenpfad noch an die Bytes des tatsaechlich hochgeladenen Bildes — zwei
# nachgewiesene Umgehungen (siehe entscheidungen/2026-09-28_…). Diese Fassung
# (CF-5) setzt den vollstaendigen 11-Punkte-Katalog um:
#  1. Kartenpfad exakt (kein Symlink, muss real in auftraege/freigabe/ liegen)
#  2. Ticket = Datum+Kartenpfad+Nr+Pruefsumme der ganzen Kartenzeile (Inhaltsspalten)
#  3. ticket_erzeugen bricht LAUT ab, wenn fuer nr+marke schon ein Ticket existiert
#  4. Karte zeigt Bild-URL+Kurz-Pruefsumme (in der Text-Spalte, siehe tagesliste_karte)
#  5. Kanal EXAKT ("Instagram <handle>", kein Teilstring-Treffer)
#  6. Nr. nur nach festem Muster ^\d{1,4}$
#  7. Ticket-Pruefsumme UND Publish-Zeitpunkt pruefen dieselben BILDBYTES (medium_rel
#     UND ein frischer Download von medien_url muessen beide zur Ticket-Pruefsumme passen)
#  8. _bereits_veroeffentlicht prueft Kartenpfad+Nr, nicht nur Nr
#  9. e.read() im Fehlerzweig abgesichert (siehe _graph_get/_graph_post oben)
# 10. Klaerfunktion instagram_zustand_klaeren fuer 'ungewiss' (Vorbild zustand_pruefen)
# 11. Ein-Rechner-Sperre (Hostname-Abgleich, siehe VEROEFFENTLICHEN_ERLAUBTER_RECHNER)
#
# Nachtrag Runde 3 (nach der DRITTEN Opus-Prüfung, ABLEHNUNG mit 7 Auflagen —
# siehe entscheidungen/2026-09-28_...): die Kette selbst war dicht, prüfte aber
# das Falsche. Sieben zusätzliche Bindungen:
#  A1. Ticket bindet zusätzlich die BILDUNTERSCHRIFT (bildunterschrift_pruefsumme) —
#      vorher war nur die Anzeige-Zeile der Karte gebunden, nicht der tatsächlich
#      gesendete `beitrag["text"]`.
#  A2. Kanal/Konto wird aus der MARKE der Karte abgeleitet (_ig_kanal(root, marke)),
#      nicht mehr pauschal aus dem CASHFLOW-Konto.
#  A3. medien_url muss auf den konfigurierten Supabase-Bucket zeigen UND https sein
#      (_erwarteter_medien_praefix, _herunterladen lehnt jedes andere Schema ab).
#  A4. http.client.HTTPException beim Lesen eines Fehlerkörpers zusätzlich abgefangen.
#  A5. ticket_erzeugen prüft Nr.- UND Marken-Muster, bevor ein Dateiname gebaut wird;
#      tagesliste_karte prüft ALLE Zeilen auf TicketKonflikt, bevor sie IRGENDEIN
#      Ticket anlegt (kein verwaistes Ticket mehr bei einem Konflikt in Zeile 2).
#  A6. Freigabe verfällt (FREIGABE_GUELTIG_TAGE) — das Kartendatum steht jetzt im
#      Dateinamen-Muster und wird geprüft.
#  A7. Testreihe erweitert (siehe test_cf5.py) um genau diese Fälle.
_TAGESLISTE_NAME = re.compile(r"^(?P<datum>\d{4}-\d{2}-\d{2})_SOCIAL_TAGESLISTE_(?P<marke>.+)\.md$")
# Runde 5, Auflage 3: \d faengt auch nicht-lateinische Ziffern, $ erlaubt ein
# angehaengtes \n vor dem Zeilenende — beides ersetzt durch [0-9] + \A/\Z
# (ueber .fullmatch() an jeder Aufrufstelle statt .match()).
_NR_MUSTER = re.compile(r"[0-9]{1,4}")
_MARKE_MUSTER = re.compile(r"[A-Za-z0-9_]{1,64}")
FREIGABE_GUELTIG_TAGE = 2


class TicketKonflikt(RuntimeError):
    """Fuer marke+nr existiert bereits ein Ticket (verbraucht oder nicht) — Punkt 3."""


def _ticket_existiert_bereits(root, marke, nr):
    """True, wenn fuer marke+nr IRGENDEINE Ticket-Form vorliegt: unverbraucht
    (.ticket), verbraucht (.verbraucht) ODER eine Kollisionsvariante (.2.verbraucht,
    .3.verbraucht, ...). Fund Runde 3: die alte Pruefung (nur .ticket/.verbraucht)
    uebersah die Kollisionsvarianten aus _ticket_verbrauchen."""
    pfad = ticket_pfad(root, marke, nr)
    if pfad.is_file() or pfad.with_suffix(".verbraucht").is_file():
        return True
    if not pfad.parent.is_dir():
        return False
    praefix = pfad.stem + "."
    for p in pfad.parent.iterdir():
        if p.name.startswith(praefix) and p.name.endswith(".verbraucht"):
            return True
    return False


def _zeilen_pruefsumme(nr, kanal_spalte, art, text):
    kern = json.dumps({"nr": str(nr), "kanal": kanal_spalte, "art": art, "text": text},
                      sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(kern.encode()).hexdigest()


def _als_reinen_text_pruefen(wert, feldname):
    """`type(wert) is str` — bewusst KEIN `isinstance()`, das wuerde jede str-
    Unterklasse durchlassen (Fund Opus-Abschlussprüfung Runde 8, siehe
    instagram_veroeffentlichen_aus_tagesliste)."""
    if type(wert) is not str:
        raise ValueError("beitrag_feld_kein_reiner_text: %s (Typ %s)" % (feldname, type(wert).__name__))
    return wert


def _bildunterschrift_pruefsumme(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


_BILDUNTERSCHRIFT_VERBOTENE_ZEICHEN = frozenset("<\r  $[]`\\")
_BILDUNTERSCHRIFT_VERBOTENE_MUSTER = ("%%", "&#")
# Fund enge Nachprüfung (Runde 6, Auflage C): benannte HTML-Zeichenreferenzen wie
# '&ZeroWidthSpace;'/'&shy;' liefen an '&#' vorbei — jetzt zusaetzlich per Muster erfasst.
_BILDUNTERSCHRIFT_ENTITAET_MUSTER = re.compile(r"&[A-Za-z][A-Za-z0-9]*;")


def _bildunterschrift_pruefen(text):
    """Auflage (Runde 3/4/5, nach der VIERTEN, FUENFTEN UND SECHSTEN Opus-Prüfung): die
    Bildunterschrift muss ein ECHTER Text (str) sein — vorher sendete ein fehlendes
    `text`-Feld woertlich das Wort 'None'. Kein '<' (HTML-Kommentar) und kein '%%'
    (Obsidian-Kommentar, dieser Vault ist ein Obsidian-Vault — Fund Runde 5: ein
    Obsidian-Kommentar wuerde in der Kartenansicht vermutlich unsichtbar sein, aber
    unveraendert an Meta gesendet). Zusaetzlich (Runde 5) jedes Steuer-/Format-Zeichen
    (Unicode-Kategorie Cc/Cf, z.B. Leserichtungs- oder Nullbreiten-Zeichen) UND die
    Zeilentrenner \\r/\\u2028/\\u2029 ausgeschlossen — nur normales \\n bleibt erlaubt.
    Fund Runde 6 (adversariale Prüfung): zusaetzlich '$'/'['/']'/'`'/'\\' (Obsidian-
    Mathe-Blöcke, Markdown-Links mit verstecktem Ziel, Inline-Code) und '&#' (HTML-
    Zeichenreferenzen wie '&#8203;') ausgeschlossen. Als Sperrliste statt Positivliste
    umgesetzt, weil Bildunterschriften international (Umlaute, Emoji, andere
    Schriftsysteme) bleiben muessen; eine echte Positivliste waere fuer diesen Zweck
    zu eng."""
    if not isinstance(text, str):
        raise ValueError("bildunterschrift_kein_text: %r" % (text,))
    for muster in _BILDUNTERSCHRIFT_VERBOTENE_MUSTER:
        if muster in text:
            raise ValueError("bildunterschrift_enthaelt_verbotenes_muster: %r" % muster)
    if _BILDUNTERSCHRIFT_ENTITAET_MUSTER.search(text):
        raise ValueError("bildunterschrift_enthaelt_html_zeichenreferenz")
    for ch in text:
        if ch == "\n":
            continue
        if ch in _BILDUNTERSCHRIFT_VERBOTENE_ZEICHEN or unicodedata.category(ch) in ("Cc", "Cf"):
            raise ValueError("bildunterschrift_enthaelt_verstecktes_zeichen: %r" % ch)
    return text


def _medium_bytes_pruefsumme(root, medium_rel):
    """None, wenn die Datei nicht im Vault liegt/eine Verknuepfung ist/fehlt."""
    vault = holding_wurzel(root)
    roh = vault / medium_rel
    if roh.is_symlink():  # vor .resolve() pruefen, siehe medien_bereitstellen
        return None
    quelle = roh.resolve()
    if vault not in quelle.parents or not quelle.is_file():
        return None
    return hashlib.sha256(quelle.read_bytes()).hexdigest()


def instagram_kanal_string(root=None, kanal=None, marke=None):
    root = root or jack_wurzel()
    kanal = kanal or _ig_kanal(root, marke)
    return "Instagram %s" % kanal["handle"] if kanal else "Instagram (kein Kanal fuer diese Marke)"


def pruefe_freigabe(tagesliste_pfad, marke, nr, root=None, jetzt=None):
    """(ok, ergebnis). Bei Erfolg: (True, {"kanal","art","text"} — die drei Inhalts-
    spalten, wie sie tatsaechlich auf der Karte stehen). Bei Misserfolg: (False, grund).
    ALLE Punkte 1/4(teilweise)/5/6 des 11-Punkte-Katalogs, plus Auflage A2 (Kanal
    exakt fuer DIESE Marke) und A6 (Freigabe verfaellt nach FREIGABE_GUELTIG_TAGE).
    `jetzt` ist NUR fuer Protokoll-/Anzeigezwecke des Aufrufers gedacht — die Frist
    selbst prueft IMMER gegen die echte Uhr (Auflage Runde 5: ein Aufrufer, der
    `jetzt` selbst setzt, konnte vorher beide Fristen aushebeln, indem er ein
    altes `jetzt` mitgab, gegen das eine alte Karte frisch aussah)."""
    root = root or jack_wurzel()
    jetzt = jetzt or now()
    echte_uhr = now()
    if not _NR_MUSTER.fullmatch(str(nr)):
        return False, "nr_falsches_muster"
    pfad = Path(tagesliste_pfad)
    if pfad.is_symlink():
        return False, "karte_ist_verknuepfung"
    erwarteter_ordner = (Path(root) / "auftraege" / "freigabe").resolve()
    if not pfad.is_file():
        return False, "karte_fehlt"
    if pfad.resolve().parent != erwarteter_ordner:
        return False, "karte_liegt_nicht_in_freigabe"
    treffer_name = _TAGESLISTE_NAME.match(pfad.name)
    if not treffer_name or treffer_name.group("marke") != marke:
        return False, "karte_marke_stimmt_nicht"
    try:
        kartendatum = dt.date.fromisoformat(treffer_name.group("datum"))
    except ValueError:
        # Fund Runde 3, VIERTE Ablehnung: ein ungueltiges Datum (z.B. 2026-13-45) liess
        # dt.date.fromisoformat() vorher unbehandelt abstuerzen — sauberer Zustand statt.
        return False, "kartendatum_ungueltig"
    # Fund Runde 3, VIERTE Ablehnung: ein Datum weit in der Zukunft (z.B. 2099-01-01)
    # hebelte die Frist vollstaendig aus, sie verfaellt dann nie. Hoechstens ein Tag
    # voraus ist erlaubt (fruehzeitig vorbereitete Karte); alles Weitere abgelehnt.
    # Runde 5: gegen echte_uhr, NICHT gegen das aufrufer-gesteuerte `jetzt`.
    if kartendatum > echte_uhr.date() + dt.timedelta(days=1):
        return False, "kartendatum_zu_weit_in_der_zukunft"
    if (echte_uhr.date() - kartendatum).days > FREIGABE_GUELTIG_TAGE:
        return False, "freigabe_abgelaufen"
    zeilen = [z for z in pfad.read_text(encoding="utf-8").splitlines() if z.startswith("| %s |" % nr)]
    if len(zeilen) != 1:
        return False, "zeile_nicht_eindeutig"
    spalten = [s.strip() for s in zeilen[0].strip("|").split("|")]
    if len(spalten) != 5:
        return False, "spaltenzahl_falsch"
    _nr, kanal_spalte, art, text, entscheidung = spalten
    kanal = _ig_kanal(root, marke)
    if kanal is None:
        return False, "kein_kanal_fuer_marke"
    if kanal_spalte != instagram_kanal_string(root, kanal=kanal):
        return False, "kanal_stimmt_nicht"
    if entscheidung != "FREIGEBEN":
        return False, "nicht_freigegeben"
    return True, {"kanal": kanal_spalte, "art": art, "text": text}


def ticket_pfad(root, marke, nr):
    return Path(root) / "auftraege" / "freigabe" / ("INSTAGRAM_VEROEFFENTLICHEN_%s_%s.ticket" % (marke, nr))


def ticket_erzeugen(root, marke, nr, tagesliste_pfad, zeile, medium_rel, jetzt=None):
    """Legt ein UNVERBRAUCHTES Ticket an: Datum+Kartenpfad+Nr+Pruefsumme der Karten-
    zeile (kanal/art/text) UND Pruefsumme der Bildbytes UND Pruefsumme der tatsaech-
    lichen Bildunterschrift (Auflage A1). `zeile` = {"kanal","art","text",
    "bildunterschrift"} — "bildunterschrift" ist der Wert, der spaeter WOERTLICH als
    `beitrag["text"]` gesendet wird (siehe instagram_veroeffentlichen_aus_tagesliste).
    Existiert fuer nr+marke bereits EINE Ticket-Form (unverbraucht, verbraucht oder
    eine Kollisionsvariante — Auflage A5): **TicketKonflikt**, KEIN stilles
    Weiterlaufen (Fund 2. Ablehnung: ein liegen gebliebenes Ticket von einem
    Vortag deckte einen ganz anderen, nie freigegebenen Beitrag). Nr. UND Marke
    werden VOR jedem Dateipfad-Bau gegen ein festes Muster geprueft (Auflage A5:
    Fund Runde 3, ein ungeprueftes `nr`/`marke` konnte den Ticket-Dateinamen aus
    dem Freigabe-Ordner heraus lenken). Fund Runde 3, VIERTE Ablehnung: das Ticket
    bindet jetzt zusaetzlich Kontonummer (`ig_user_id`) UND Handle des zum
    Freigabe-Zeitpunkt fuer diese Marke konfigurierten Kanals — aendert sich die
    Kontonummer in `social_kanaele.json` NACH der Freigabe, erkennt das
    `instagram_veroeffentlichen_aus_tagesliste` (Nachweis: Konto liess sich sonst
    nach der Freigabe stillschweigend austauschen). Fund Runde 6 (adversariale
    Prüfung, Nachweis "Ticket nach der Freigabe mit fremder Bildunterschrift"):
    `zeile["text"]` (was der Patron auf der Karte sieht und freigibt) und
    `zeile["bildunterschrift"]` (was tatsaechlich gesendet wird) waren zwei
    UNABHAENGIGE Felder — ein Aufrufer konnte `ticket_erzeugen` mit einem Text
    aufrufen, der zur echten Kartenzeile passt, aber einer voellig anderen
    Bildunterschrift. Jetzt wird `zeile["text"]` GENAU aus `bildunterschrift`,
    `medien_url` und der Bild-Pruefsumme REKONSTRUIERT und muss exakt uebereinstimmen
    — die beiden Felder koennen nicht mehr auseinanderlaufen, unabhaengig vom Aufrufer."""
    jetzt = jetzt or now()
    if not _NR_MUSTER.fullmatch(str(nr)):
        raise ValueError("nr_falsches_muster: %r" % (nr,))
    if not _MARKE_MUSTER.fullmatch(str(marke)):
        raise ValueError("marke_falsches_muster: %r" % (marke,))
    if _ticket_existiert_bereits(root, marke, nr):
        raise TicketKonflikt("Ticket fuer %s Nr. %s existiert bereits — neue Nummer verwenden" % (marke, nr))
    kanal = _ig_kanal(root, marke)
    if kanal is None:
        raise ValueError("kein_eindeutiger_kanal_fuer_marke: %r" % (marke,))
    pfad = ticket_pfad(root, marke, nr)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    bild_pruefsumme = _medium_bytes_pruefsumme(root, medium_rel)
    if bild_pruefsumme is None:
        raise ValueError("medium_rel liegt nicht im Vault oder ist keine Datei: %s" % medium_rel)
    bildunterschrift = _bildunterschrift_pruefen(zeile.get("bildunterschrift", ""))
    medien_url = _medien_url_pruefen(root, zeile.get("medien_url", ""))
    erwarteter_text = "%s · [Bild: %s · Prüfsumme %s]" % (
        bildunterschrift.replace("|", "/").replace("\n", " "), medien_url, bild_pruefsumme[:12])
    if zeile.get("text") != erwarteter_text:
        raise ValueError("zeile_text_bildunterschrift_inkonsistent")
    pfad.write_text(
        "marke: %s\nnr: %s\nkarte: %s\ndatum: %s\nzeilen_pruefsumme: %s\nbild_pruefsumme: %s\n"
        "bildunterschrift_pruefsumme: %s\nmedien_url: %s\nkontonummer: %s\nhandle: %s\nerstellt: %s\n" % (
            marke, nr, Path(tagesliste_pfad).resolve(), jetzt.date().isoformat(),
            _zeilen_pruefsumme(nr, zeile["kanal"], zeile["art"], zeile["text"]), bild_pruefsumme,
            _bildunterschrift_pruefsumme(bildunterschrift), medien_url,
            kanal["ig_user_id"], kanal["handle"],
            jetzt.isoformat(timespec="seconds")),
        encoding="utf-8")
    return pfad


def _ticket_lesen(pfad):
    if not pfad.is_file():
        return None
    werte = {}
    for zeile in pfad.read_text(encoding="utf-8").splitlines():
        if ":" in zeile:
            k, v = zeile.split(":", 1)
            werte[k.strip()] = v.strip()
    return werte


def _ticket_verbrauchen(pfad):
    """Einmal-Ticket: umbenennen in .verbraucht, NIE loeschen (A5, Muster
    `jack_veroeffentlichung.py:_ticket_verbrauchen`)."""
    ziel = pfad.with_suffix(".verbraucht")
    n = 2
    while ziel.exists():
        ziel = pfad.with_name("%s.%d.verbraucht" % (pfad.stem, n)); n += 1
    os.rename(pfad, ziel)
    if pfad.exists() or not ziel.is_file():
        raise RuntimeError("Ticket konnte nicht verbraucht werden — kein Aufruf")
    return ziel


def _format_pruefen(beitrag):
    """Formatpruefung. Diese Fassung sendet ausschliesslich EINZELBILD (`image_url`) —
    Karussell/Reel sind NICHT gebaut, klarer Zustand statt falsch gesendeter Beitrag."""
    art = beitrag.get("medien_typ")
    url = beitrag.get("medien_url", "")
    if art in ("REEL", "KARUSSELL"):
        return False, "medientyp_noch_nicht_gebaut (%s): nur BILD ist in diesem Lauf implementiert" % art
    if art != "BILD":
        return False, "unbekannter medien_typ: %r" % art
    if not url.lower().endswith((".jpg", ".jpeg")):
        return False, "Bild verlangt JPEG, Datei ist: %s" % url
    return True, ""


def _protokoll_pfad(root, marke):
    ordner, _ = _leads_pfad(marke, root)
    return ordner, ordner / ("veroeffentlicht_%s.jsonl" % marke)


def _protokoll_anhaengen(root, marke, eintrag):
    ordner, pfad = _protokoll_pfad(root, marke)
    ordner.mkdir(parents=True, exist_ok=True)
    with open(pfad, "a", encoding="utf-8") as f:
        f.write(json.dumps(eintrag, ensure_ascii=False) + "\n")


def _protokoll_lesen(root, marke):
    _, pfad = _protokoll_pfad(root, marke)
    if not pfad.is_file():
        return []
    zeilen = []
    for z in pfad.read_text(encoding="utf-8").splitlines():
        try:
            zeilen.append(json.loads(z))
        except ValueError:
            continue
    return zeilen


def _bereits_veroeffentlicht(root, marke, nr, tagesliste_pfad):
    """Prueft Kartenpfad+Nr (Fund 2. Ablehnung: reine Nr.-Pruefung meldete faelschlich
    'bereits veroeffentlicht' fuer einen neuen, nie geposteten Beitrag unter derselben
    Nummer an einem anderen Tag)."""
    karte = str(Path(tagesliste_pfad).resolve())
    for e in _protokoll_lesen(root, marke):
        if e.get("nr") == nr and e.get("tagesliste") == karte and e.get("zustand") == "veroeffentlicht":
            return e
    return None


def instagram_zustand_klaeren(marke, nr, beitrag, root=None, anzahl=10):
    """Klaerfunktion bei 'ungewiss' (Vorbild `jack_veroeffentlichung.zustand_pruefen`):
    sucht in den letzten `anzahl` Beitraegen des Kontos nach einem, dessen Text GENAU
    dem freigegebenen Beitrag entspricht. Loest NIE automatisch etwas aus, kein
    zweiter Post — nur eine Einschaetzung fuer einen Menschen. Fund Runde 3, VIERTE
    Ablehnung: durchsuchte vorher IMMER das CASHFLOW-Konto, egal welche `marke`
    uebergeben wurde — fuer eine andere Marke waere das Konto falsch gewesen und
    haette faelschlich 'vermutlich_nicht_angekommen' gemeldet (Risiko: Doppelpost)."""
    root = root or jack_wurzel()
    kanal = _ig_kanal(root, marke)
    if kanal is None:
        return {"zustand": "klaerung_nicht_moeglich", "grund": "kein_kanal_fuer_marke"}
    medien = instagram_medien_lesen(root, kanal=kanal, tage=3)
    if medien.get("zustand") not in ("gelesen", "teilweise_gelesen"):
        return {"zustand": "klaerung_nicht_moeglich", "grund": medien.get("zustand")}
    for m in medien.get("medien", [])[:anzahl]:
        if (m.get("caption") or "") == beitrag.get("text", ""):
            return {"zustand": "vermutlich_angekommen", "media_id": m.get("id"),
                    "permalink": m.get("permalink"),
                    "hinweis": "Text stimmt überein — bitte von Hand bestätigen, kein zweiter Post."}
    return {"zustand": "vermutlich_nicht_angekommen",
            "hinweis": "Kein Beitrag mit diesem Text in den letzten %d Medien gefunden — "
                       "bitte trotzdem von Hand im Konto nachsehen, bevor neu versucht wird." % anzahl}


# Ein-Rechner-Sperre (Punkt 11): iCloud synchronisiert nicht atomar — zwei Macs
# koennten sonst gleichzeitig dasselbe Ticket verbrauchen wollen. Name kommt aus
# social_kanaele.json -> "erlaubter_rechner_instagram"; leer/fehlend = gesperrt
# (sicherer Fehlschlag statt stillschweigend erlaubt).
def _dieser_rechner_ist_erlaubt(root):
    kanaele_pfad = Path(root) / "betrieb" / KONFIG_DATEI
    if not kanaele_pfad.is_file():
        return False
    erlaubt = json.loads(kanaele_pfad.read_text(encoding="utf-8")).get("erlaubter_rechner_instagram")
    if not erlaubt:
        return False
    import platform
    return platform.node() == erlaubt


# SPERRSCHALTER (28.09.2026, nach ZWEI Opus-ABLEHNUNGEN in Folge; CF-5 baut das
# Tor komplett neu, siehe Kommentarblock oben). Bleibt auf True, bis DREI
# unabhaengige Pruefungen (2× Opus in CF-5 + die urspruengliche CF-4-Endprüfung
# zaehlt NICHT mit, da sie sich gegen die alte Fassung richtete) ANNAHME sagen —
# siehe entscheidungen/2026-09-28_social-media-zentrale-stufe3-instagram.md.
VEROEFFENTLICHEN_GESPERRT = True


def instagram_veroeffentlichen_aus_tagesliste(marke, nr, beitrag, tagesliste_pfad, root=None, jetzt=None,
                                              warte_sekunden=3, hoechstversuche=20):
    """EINZIGER Weg zum Veroeffentlichen in dieser Datei. **GESPERRT** (siehe
    VEROEFFENTLICHEN_GESPERRT) — liefert IMMER sofort zustand='gesperrt_nach_ablehnung',
    ohne jede weitere Pruefung, ohne Netzaufruf. Reihenfolge, sobald entsperrt:
      -1. `beitrag` wird EINMALIG in reine Text-Werte kopiert (`_als_reinen_text_pruefen`,
          `type(x) is str`) — jede str-Unterklasse (koennte bei Pruefung/Versand
          unterschiedliche Bytes liefern) fuehrt zu 'beitrag_feld_unsicher' (Fund
          Opus-Abschlussprüfung Runde 8).
      0. Dieser Rechner ist der erlaubte Rechner (Punkt 11).
      1. Bereits veroeffentlicht? (Kartenpfad+Nr, Punkt 8) -> abbrechen, nie doppelt.
      2. `pruefe_freigabe`: Kartenpfad exakt+Marke+Kanal exakt fuer DIESE Marke+
         Freigabe noch gueltig+Nr-Muster+Entscheidung (Punkte 1/5/6, Auflagen A2/A6).
      3. Ticket vorhanden, unverbraucht, Zeilen-Pruefsumme == tatsaechliche Kartenzeile,
         Bildunterschrift-Pruefsumme == beitrag['text'] (Auflage A1), Bild-Pruefsumme
         == Bytes von medium_rel (Punkte 2/7).
      4. Logo-Nachweis (A6c) fuer medium_rel.
      5. Formatpruefung.
      6. medien_url muss auf den konfigurierten Supabase-Bucket zeigen (Auflage A3),
         danach frischer Download: Bytes == Ticket-Bild-Pruefsumme (Punkt 7, zweite
         Haelfte — verhindert, dass ein anderes Bild als das gepruefte am Ziel liegt).
      Erst DANACH: Konto aus DIESER Marke ableiten (Auflage A2), Ticket verbrauchen
      (VOR jedem Netzaufruf) + Pending-Protokollzeile, dann Container -> Status ->
      media_publish, Ergebnis anhaengen (A5: nur anhaengen)."""
    if VEROEFFENTLICHEN_GESPERRT:
        return {"zustand": "gesperrt_nach_ablehnung",
                "grund": "Tor zweimal von Opus abgelehnt (28.09.2026) — siehe CF-5-Auftrag/-Meldung"}
    root = root or jack_wurzel()
    jetzt = jetzt or now()

    # Fund Runde 6 (enge Nachprüfung), Auflage A: `beitrag` GENAU EINMAL in einfache
    # Text-Werte kopieren und danach AUSSCHLIESSLICH diese Kopie verwenden — nie erneut
    # `beitrag.get(...)`/`beitrag[...]` aufrufen. Vorher wurde `medien_url`/`text` an
    # mehreren Stellen separat aus `beitrag` gelesen; ein praepariertes Objekt (eigene
    # __getitem__/get-Implementierung) haette bei zwei Zugriffen unterschiedliche Werte
    # liefern koennen — geprueft wurde der eine, gesendet der andere.
    # Fund Opus-Abschlussprüfung Runde 8: `str(x)` ist KEINE echte Kopie — eine
    # str-Unterklasse, deren `__str__` `self` zurueckgibt, bleibt dieselbe Instanz mit
    # eigenem `encode()`/`__eq__()`/... Nachgewiesen: `.encode()` beim Pruefen und
    # beim tatsaechlichen Senden (urlencode) riefen zwei VERSCHIEDENE Methoden auf
    # demselben Objekt auf und konnten so unterschiedliche Bytes liefern. Einzige
    # echte Garantie: `type(x) is str` (kein `isinstance`, das laesst Unterklassen
    # durch) — alles andere ist ein sicherer Fehlschlag, kein Netzaufruf.
    try:
        medien_url = _als_reinen_text_pruefen(beitrag.get("medien_url", ""), "medien_url")
        bildunterschrift_gesendet = _als_reinen_text_pruefen(beitrag.get("text", ""), "text")
        medium_rel = beitrag.get("medium_rel")
        if medium_rel is not None:
            medium_rel = _als_reinen_text_pruefen(medium_rel, "medium_rel")
        medien_typ = beitrag.get("medien_typ")
        if medien_typ is not None:
            medien_typ = _als_reinen_text_pruefen(medien_typ, "medien_typ")
    except ValueError as fehler:
        return {"zustand": "beitrag_feld_unsicher", "grund": str(fehler)}
    beitrag = {"medien_url": medien_url, "text": bildunterschrift_gesendet,
               "medium_rel": medium_rel, "medien_typ": medien_typ}

    if not _dieser_rechner_ist_erlaubt(root):
        return {"zustand": "falscher_rechner"}

    schon = _bereits_veroeffentlicht(root, marke, nr, tagesliste_pfad)
    if schon:
        return {"zustand": "bereits_veroeffentlicht", "media_id": schon.get("media_id")}

    ok, ergebnis = pruefe_freigabe(tagesliste_pfad, marke, nr, root, jetzt)
    if not ok:
        return {"zustand": "wartet_auf_freigabe", "grund": ergebnis}

    tpfad = ticket_pfad(root, marke, nr)
    ticket = _ticket_lesen(tpfad)
    if ticket is None:
        return {"zustand": "kein_ticket", "grund": "kein unverbrauchtes Ticket %s" % tpfad.name}
    if ticket.get("karte") != str(Path(tagesliste_pfad).resolve()) or ticket.get("nr") != str(nr):
        return {"zustand": "ticket_karte_stimmt_nicht"}
    if ticket.get("zeilen_pruefsumme") != _zeilen_pruefsumme(nr, ergebnis["kanal"], ergebnis["art"], ergebnis["text"]):
        return {"zustand": "ticket_zeile_stimmt_nicht", "grund": "Kartenzeile weicht vom Ticket ab"}
    # Auflage A1 (Fund Runde 3, Nachweis A): die tatsaechlich zu sendende Bildunterschrift
    # muss WORTWOERTLICH der beim Freigeben gezeigten entsprechen — nicht nur die Zeile
    # der Karte als Anzeige-Text.
    if ticket.get("bildunterschrift_pruefsumme") != _bildunterschrift_pruefsumme(beitrag.get("text", "")):
        return {"zustand": "ticket_bildunterschrift_stimmt_nicht",
                "grund": "beitrag['text'] weicht von der freigegebenen Bildunterschrift ab"}
    medium_rel = beitrag.get("medium_rel")
    if not medium_rel or _medium_bytes_pruefsumme(root, medium_rel) != ticket.get("bild_pruefsumme"):
        return {"zustand": "ticket_bild_stimmt_nicht", "grund": "medium_rel-Bytes weichen vom Ticket ab"}

    # Auflage (Runde 3, VIERTE Ablehnung, Nachweis "Konto nicht gebunden"): Konto/Handle
    # aus dem TICKET (zum Freigabe-Zeitpunkt gebunden) muessen zum JETZT konfigurierten
    # Kanal passen — sonst koennte die Kontonummer NACH der Freigabe in
    # social_kanaele.json ausgetauscht werden, ohne dass eine Pruefung das bemerkt.
    kanal = _ig_kanal(root, marke)
    if not kanal:
        return {"zustand": "kein_kanal_konfiguriert"}
    if ticket.get("kontonummer") != kanal["ig_user_id"] or ticket.get("handle") != kanal["handle"]:
        return {"zustand": "ticket_konto_stimmt_nicht"}

    # Zusaetzliche Frist auf den Ticket-ERSTELLUNGSZEITPUNKT selbst (nicht nur das
    # Kartendatum) — ein Ticket, das laenger als FREIGABE_GUELTIG_TAGE still herumliegt,
    # wird ebenfalls abgelehnt, auch wenn die Karte selbst (z.B. per manipuliertem
    # Dateinamen) juenger wirkt. Auflage Runde 5: IMMER gegen die echte Uhr (now()),
    # nicht gegen das aufrufer-gesteuerte `jetzt` — sonst liesse sich diese Frist genau
    # wie die Kartenfrist per selbst gewaehltem `jetzt` aushebeln. Ein Zeitstempel ohne
    # Zeitzone (Fund Runde 5: fuehrte vorher zu einem unbehandelten TypeError beim
    # Vergleich aware-naiv) gilt als ungueltig, kein Absturz.
    try:
        erstellt = dt.datetime.fromisoformat(ticket.get("erstellt", ""))
        if erstellt.tzinfo is None:
            raise ValueError("erstellt ohne Zeitzone")
    except ValueError:
        return {"zustand": "ticket_zeitstempel_ungueltig"}
    if (now() - erstellt).days > FREIGABE_GUELTIG_TAGE:
        return {"zustand": "ticket_abgelaufen"}

    if jack_medien is None:
        return {"zustand": "logo_nachweis_werkzeug_fehlt"}
    logo_ok, logo_grund = jack_medien.logo_nachweis(root, medium_rel)
    if not logo_ok:
        return {"zustand": "logo_nachweis_fehlt", "grund": logo_grund}

    ok, warum = _format_pruefen(beitrag)
    if not ok:
        return {"zustand": "format_fehler", "grund": warum}

    # Auflage A3 (Fund Runde 3, Nachweis E): medien_url muss auf den konfigurierten
    # Supabase-Bucket dieser Holding zeigen — sonst koennte ein fremder Server uns
    # geprüfte Bytes liefern, waehrend Meta unter derselben URL etwas anderes abruft.
    medien_url = beitrag.get("medien_url", "")
    praefix = _erwarteter_medien_praefix(root)
    if not praefix or not medien_url.startswith(praefix):
        return {"zustand": "medien_url_ausserhalb_speicher"}

    # Fund Runde 6 (adversariale Prüfung): die auf der Karte GEZEIGTE medien_url ist
    # jetzt fest im Ticket gebunden (siehe ticket_erzeugen) — die tatsaechlich
    # gesendete medien_url muss EXAKT dieselbe sein, nicht nur irgendeine URL mit
    # passenden Bytes im selben Bucket.
    if medien_url != ticket.get("medien_url"):
        return {"zustand": "ticket_medien_url_stimmt_nicht"}

    # Punkt 7, zweite Haelfte: das tatsaechliche Ziel (medien_url) muss JETZT dieselben
    # Bytes liefern wie das geprüfte Ausgangsbild — nicht nur zum Ticket-Zeitpunkt.
    ok_dl, geladen = _herunterladen(medien_url)
    if not ok_dl or hashlib.sha256(geladen).hexdigest() != ticket.get("bild_pruefsumme"):
        return {"zustand": "medien_url_bytes_stimmen_nicht"}

    # kanal ist oben bereits aus DIESER Marke abgeleitet (Auflage A2) und gegen das
    # Ticket geprueft — hier nur noch der Token dazu.
    token = schluessel_lesen(kanal.get("schluesselbund_name_voll") or "")
    if token is None:
        return {"zustand": "recht_fehlt", "grund": "kein VOLL-Token (instagram_content_publish) im Schluesselbund"}

    # Auflage (Runde 3, VIERTE Ablehnung): das Konto zusaetzlich per ECHTEM Abruf
    # bestaetigen (nicht nur dem lokal konfigurierten Handle-String vertrauen) — bevor
    # irgendetwas verbraucht wird. Ein GET, kein Schreibzugriff.
    ok_konto, konto_antwort = _graph_get(kanal["ig_user_id"], {"fields": "username"}, token)
    if not ok_konto:
        return {"zustand": "konto_nicht_bestaetigt", "grund": konto_antwort}
    if (konto_antwort.get("username") or "").lstrip("@") != kanal["handle"].lstrip("@"):
        return {"zustand": "konto_handle_stimmt_nicht"}

    # Ab hier: Ticket wird verbraucht, DANACH erst der erste Netzaufruf mit Seitenwirkung.
    verbraucht = _ticket_verbrauchen(tpfad)
    _protokoll_anhaengen(root, marke, {"marke": marke, "nr": nr, "tagesliste": str(Path(tagesliste_pfad).resolve()),
                                       "zeit": jetzt.isoformat(timespec="seconds"), "zustand": "versucht",
                                       "ticket": str(verbraucht)})

    ok, erg = _graph_post(kanal["ig_user_id"] + "/media", {
        "image_url": beitrag["medien_url"], "caption": beitrag.get("text", ""),
    }, token)
    if not ok:
        _protokoll_anhaengen(root, marke, {"marke": marke, "nr": nr, "tagesliste": str(Path(tagesliste_pfad).resolve()),
                                           "zeit": now().isoformat(timespec="seconds"), "zustand": erg})
        return {"zustand": erg}
    container_id = erg.get("id")
    if not container_id:
        _protokoll_anhaengen(root, marke, {"marke": marke, "nr": nr, "tagesliste": str(Path(tagesliste_pfad).resolve()),
                                           "zeit": now().isoformat(timespec="seconds"), "zustand": "container_ohne_id"})
        return {"zustand": "container_ohne_id"}

    for _ in range(hoechstversuche):
        ok, stand = _graph_get(container_id, {"fields": "status_code"}, token)
        if not ok:
            _protokoll_anhaengen(root, marke, {"marke": marke, "nr": nr, "tagesliste": str(Path(tagesliste_pfad).resolve()),
                                               "zeit": now().isoformat(timespec="seconds"), "zustand": stand,
                                               "container_id": container_id})
            return {"zustand": stand, "container_id": container_id}
        status = stand.get("status_code")
        if status in ("FINISHED", "PUBLISHED"):
            break
        if status in ("ERROR", "EXPIRED"):
            _protokoll_anhaengen(root, marke, {"marke": marke, "nr": nr, "tagesliste": str(Path(tagesliste_pfad).resolve()),
                                               "zeit": now().isoformat(timespec="seconds"),
                                               "zustand": "container_%s" % status.lower(), "container_id": container_id})
            return {"zustand": "container_%s" % status.lower(), "container_id": container_id}
        time.sleep(warte_sekunden)
    else:
        _protokoll_anhaengen(root, marke, {"marke": marke, "nr": nr, "tagesliste": str(Path(tagesliste_pfad).resolve()),
                                           "zeit": now().isoformat(timespec="seconds"),
                                           "zustand": "container_zeitueberschreitung", "container_id": container_id})
        return {"zustand": "container_zeitueberschreitung", "container_id": container_id}

    ok, erg = _graph_post(kanal["ig_user_id"] + "/media_publish", {"creation_id": container_id}, token)
    if not ok:
        _protokoll_anhaengen(root, marke, {"marke": marke, "nr": nr, "tagesliste": str(Path(tagesliste_pfad).resolve()),
                                           "zeit": now().isoformat(timespec="seconds"), "zustand": "veroeffentlichen_ungewiss",
                                           "grund": erg, "container_id": container_id})
        return {"zustand": "veroeffentlichen_ungewiss", "grund": erg, "container_id": container_id}

    _protokoll_anhaengen(root, marke, {"marke": marke, "nr": nr, "tagesliste": str(Path(tagesliste_pfad).resolve()),
                                       "zeit": now().isoformat(timespec="seconds"), "zustand": "veroeffentlicht",
                                       "media_id": erg.get("id")})
    return {"zustand": "veroeffentlicht", "media_id": erg.get("id")}


# ---------------------------------------------------------------- Morgenbericht
def morgenbericht_abschnitt(root=None, jetzt=None):
    """Fertiger Markdown-Abschnitt fuer den BESTEHENDEN JACK-Tagesbericht (kein eigener
    zweiter Bericht). Die Einbindung selbst (jack_betrieb.py) liegt ausserhalb des
    Dateigebiets dieses Kanals (Zustaendigkeit sprache/) - siehe Meldung CF-3, Abschnitt
    'offen'. Diese Funktion liefert nur den fertigen Text."""
    root = root or jack_wurzel()
    jetzt = jetzt or now()
    kanaele = lade_kanaele(root)
    # Fund Opus-Endprüfung CF-4: "Schluessel vorhanden" wurde als "verbunden" gemeldet,
    # obwohl der Token ungueltig sein kann. Ehrlicher Wortlaut: "Schlüssel hinterlegt"
    # ist keine Aussage ueber Gueltigkeit — die steht nur im Wochenbericht (echter Abruf).
    hinterlegt = sum(1 for k in kanaele if k.get("schluesselbund_name") and schluessel_lesen(k["schluesselbund_name"]) is not None)
    zeilen = ["### Social", "", "- Kanäle mit hinterlegtem Schlüssel: %d von %d (keine Aussage über Gültigkeit — "
              "siehe Wochenbericht je Marke für echte Abrufe)" % (hinterlegt, len(kanaele)),
              "- Neue Leads: 0 (kein Kanal verbunden)" if hinterlegt == 0 else "- Neue Leads: siehe leads_<marke>.jsonl je Marke",
              "- Umsatz je Beitrag: nicht messbar bis Kontoanbindung und Shop-Livegang",
              "- Offene Freigaben: siehe `auftraege/freigabe/*_SOCIAL_TAGESLISTE_*.md`", ""]
    return "\n".join(zeilen)
