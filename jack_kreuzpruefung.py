"""F-97 / Auftrag 47.1 Aufgabe 11: anbieteruebergreifende Kreuzpruefung NUR bei Risikoschritten.

Claude baut -> Codex prueft (ueber codex_bruecke, nur lesend); Codex baut -> Claude prueft (guenstigste Fachkraft-Stufe).
Hoechstens 2 Runden je Vorgang, danach `an_patron`. Fable nur Endkontrolle (nie hier). Kosten je Lauf ueber jack_kosten
(codex_bruecke.review und modell_router.call buchen selbst); zusaetzlich eine Zeile in betrieb/kreuzpruefung.jsonl.
Kein Fremd-Skill, kein Netzzugriff ausser ueber diese beiden bestehenden Bruecken."""
import json
import re
from pathlib import Path

import jack_betrieb as b

RUNDEN_MAX = 2
PLAYBOOK = Path("verfahren") / "Kreuzpruefung.md"
RISIKO = {
    "Geld": r"zahlung|zahl(e|en|t)\b|ueberweis|überweis|rechnung|betrag|\busd\b|\beur\b|kauf(en|t)?\b|abo\b|kosten|guthaben|aufladen|bezahl",
    "Recht": r"vertrag|k(ü|ue)ndig|dsgvo|haftung|\bnda\b|rechts|lizenz|unterschr|datenschutz|ki-vo",
    "Sicherheit": r"passwort|schl(ü|ue)ssel|token|secret|zugang|berechtig|firewall|freigabecode|sicherheitscode|permission|bypass",
    "Livegang": r"deploy|\blive\b|produktion|release|go-live|livegang|neustart|ver(ö|oe)ffentlich|versand|senden|\bpush\b",
    "Architektur": r"architektur|datenmodell|schema\b|umbau|refactor|schnittstelle|infrastruktur",
    "Loeschen/Migration": r"l(ö|oe)sch|delete|\brm\b|migrier|migration|verschieb|archivier|umbenenn",
}


def risikoschritt(text):
    """-> (bool, [Bereiche]). Reine Regelerkennung, kein Modell."""
    t = str(text or "").lower()
    treffer = [name for name, muster in RISIKO.items() if re.search(muster, t, re.I)]
    return bool(treffer), treffer


def _vorlage(root):
    text = (Path(root) / PLAYBOOK).read_text(encoding="utf-8")
    m = re.search(r"<!--PROMPT-->\n(.*?)\n<!--/PROMPT-->", text, re.S)
    if not m:
        raise ValueError("Prompt-Vorlage im Playbook nicht gefunden")
    return m.group(1)


def _zustand_pfad(root):
    return b.area(root) / "kreuzpruefung_runden.json"


def _runden(root):
    try:
        return json.loads(_zustand_pfad(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _urteil(antwort):
    m = re.search(r"URTEIL:\s*(OK|NACHBESSERN|STOPP)", str(antwort or ""), re.I)
    return m.group(1).upper() if m else "UNKLAR"


def pruefer_claude(root, prompt):
    """Codex hat gebaut -> Claude prueft (guenstigste Fachkraft-Stufe, kind fachentwurf, Tagesdeckel gilt)."""
    import jack_modelle
    import modell_router
    import jack_postfaecher
    modell = jack_modelle.load(root)["fachkraft"]
    e = modell_router.call(lambda n="ANTHROPIC_API_KEY": jack_postfaecher._schluessel(root, n),
                           {"anbieter": "anthropic", "modell": modell}, prompt, max_tokens=500, root=root, kind="fachentwurf")
    return str(e.get("antwort") or "")


def pruefer_codex(root, prompt):
    """Claude hat gebaut -> Codex prueft (read-only ueber die bestehende Bruecke)."""
    import codex_bruecke
    return str(codex_bruecke.review(root, prompt).get("antwort") or "")


def pruefen(root, vorgang, bauer, gegenstand, art="ergebnis", pruefer=None, erzwingen=False):
    """Kreuzpruefung eines Schritts. `pruefer` (nur Tests): Funktion (root, prompt) -> Antworttext.
    -> dict mit `entscheidung`: uebersprungen | ok | nachbessern | stopp | unklar | an_patron."""
    root = Path(root)
    bauer = str(bauer).lower()
    if bauer not in ("claude", "codex"):
        raise ValueError("bauer muss claude oder codex sein")
    ist_risiko, bereiche = risikoschritt(gegenstand)
    if not ist_risiko and not erzwingen:
        return {"entscheidung": "uebersprungen", "grund": "kein Risikoschritt - der Exit-Code-Befehl genuegt", "kosten_usd": 0}
    runden = _runden(root)
    lauf = runden.get(vorgang, 0)
    if lauf >= RUNDEN_MAX:
        _buchen(root, vorgang, bauer, "-", lauf, "an_patron", "Rundendeckel erreicht")
        return {"entscheidung": "an_patron", "grund": "%d Runden sind durch - jetzt entscheidet der Patron" % RUNDEN_MAX, "runde": lauf}
    prompt = _vorlage(root).replace("{art}", str(art)).replace("{bereiche}", ", ".join(bereiche) or "Risikoschritt (erzwungen)")\
        .replace("{gegenstand}", str(gegenstand)[:8000])
    funktion = pruefer or (pruefer_codex if bauer == "claude" else pruefer_claude)
    antwort = funktion(root, prompt)
    lauf += 1
    runden[vorgang] = lauf
    _zustand_pfad(root).write_text(json.dumps(runden, ensure_ascii=False, indent=1), encoding="utf-8")
    urteil = _urteil(antwort)
    entscheidung = {"OK": "ok", "NACHBESSERN": "nachbessern", "STOPP": "stopp"}.get(urteil, "unklar")
    if entscheidung in ("nachbessern", "unklar") and lauf >= RUNDEN_MAX:
        entscheidung = "an_patron"
    _buchen(root, vorgang, bauer, "codex" if bauer == "claude" else "claude", lauf, entscheidung, str(antwort)[:600])
    return {"entscheidung": entscheidung, "runde": lauf, "pruefer": "codex" if bauer == "claude" else "claude",
            "bereiche": bereiche, "antwort": antwort, "kosten": "ueber jack_kosten gebucht"}


def _buchen(root, vorgang, bauer, pruefer, runde, entscheidung, auszug):
    b.append(b.area(root) / "kreuzpruefung.jsonl", {
        "zeit": b.now().isoformat(), "vorgang": str(vorgang)[:120], "bauer": bauer, "pruefer": pruefer,
        "runde": runde, "entscheidung": entscheidung, "auszug": b.redact(auszug)[:600]})


def auswertung(root):
    """Zwischenstand fuer den Messtest (47.1 Aufgabe 11d): wie viele Risikoschritte wurden geprueft, wie oft nachgebessert/gestoppt.
    Ein 'echter gefundener Fehler' braucht eine Bewertung des Patrons/PM je Befund - die Zaehler hier sind nur die Grundlage.
    Codex laeuft ueber das ChatGPT-Abo (kein USD je Lauf); Claude-Pruefungen stehen mit USD in jack_kosten."""
    zeilen = []
    try:
        for z in (b.area(Path(root)) / "kreuzpruefung.jsonl").read_text(encoding="utf-8").splitlines():
            try:
                zeilen.append(json.loads(z))
            except ValueError:
                pass
    except OSError:
        pass
    von = {}
    for z in zeilen:
        d = von.setdefault(z.get("pruefer", "-"), {"laeufe": 0, "ok": 0, "nachbessern": 0, "stopp": 0, "an_patron": 0, "unklar": 0})
        d["laeufe"] += 1
        d[z.get("entscheidung", "unklar")] = d.get(z.get("entscheidung", "unklar"), 0) + 1
    vorgaenge = {z.get("vorgang") for z in zeilen}
    return {"vorgaenge": len(vorgaenge), "je_pruefer": von, "messtest_bereit": len(vorgaenge) >= 10,
            "hinweis": "Messtest erst bei 10 bewerteten Risikoschritten; Bewertung 'echter Fehler ja/nein' je Befund fehlt noch."}
