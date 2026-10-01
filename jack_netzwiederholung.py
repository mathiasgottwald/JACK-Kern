"""S-2c: Netzaufrufe mit Zeitlimit und Wiederholung (3x nach 2/5/15 s). Ist das Netz laut betrieb/netz.json weg,
wird nicht wiederholt, sondern gewartet (geparkt) und danach fortgesetzt. Wiederholt wird NUR, solange noch keine
Antwort da ist - so entsteht nie eine doppelte Buchung im Kostenbuch."""
import json, socket, ssl, time, http.client
from pathlib import Path

PAUSEN = (2, 5, 15)
NETZ_FRISCH_S = 300
PARK_MAX_S = 45          # so lange wartet ein Sprachgespraech auf das Netz, dann klare Meldung statt Fehler
PARK_TAKT_S = 3
VERSUCH_MAX_S = 10        # so lange dauert ein Versuch hoechstens (Verbindungs-Zeitlimit)
GESAMT_MAX_S = 45         # S-3c: ein Sprachgespraech haengt nie laenger als 45 s im Netz-Teil (Versuche + Pausen + Parken)
NETZFEHLER = (OSError, socket.timeout, ssl.SSLError, http.client.RemoteDisconnected,
              http.client.CannotSendRequest, http.client.IncompleteRead, http.client.BadStatusLine)


class AntwortZeit(Exception):
    """Zeitlimit NACH dem Senden: die Anfrage kann schon laufen und bezahlt sein - deshalb keine Wiederholung."""


class Abgebrochen(Exception):
    """Der Patron hat gestoppt (auch waehrend einer Wartepause)."""


class NetzWeg(Exception):
    """Netz ist laut Waechter weg und kam innerhalb der Parkzeit nicht zurueck."""


def netz_weg(root, jetzt=time.time):
    """True nur, wenn der Netz-Waechter frisch (<=300 s) 'online=false' meldet. Fehlender/alter Stand haelt nichts an."""
    import datetime
    try:
        n = json.loads((Path(root) / "betrieb" / "netz.json").read_text(encoding="utf-8"))
        alter = jetzt() - datetime.datetime.fromisoformat(n["zeit"]).timestamp()
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return n.get("online") is False and 0 <= alter <= NETZ_FRISCH_S


def _schlafen(sekunden, schlafen, abgebrochen=None, scheibe=0.5):
    """Schlaeft in Scheiben und prueft dazwischen den Stopp (S-3c P5a)."""
    rest = float(sekunden)
    while rest > 0:
        if abgebrochen is not None and abgebrochen():
            raise Abgebrochen()
        schritt = min(scheibe, rest)
        schlafen(schritt)
        rest -= schritt
    if abgebrochen is not None and abgebrochen():
        raise Abgebrochen()


def parken(root, schlafen=None, jetzt=time.time, max_s=PARK_MAX_S, abgebrochen=None):
    """Wartet, bis das Netz wieder da ist. True = fortsetzen, False = Parkzeit abgelaufen. Stopp wird in den Pausen geprueft."""
    schlafen = schlafen or time.sleep
    ende = jetzt() + max_s
    while netz_weg(root, jetzt):
        if jetzt() >= ende:
            return False
        _schlafen(max(0.1, min(PARK_TAKT_S, ende - jetzt())), schlafen, abgebrochen)
    return True


def mit_wiederholung(aufruf, root, schlafen=None, pausen=PAUSEN, jetzt=time.time, max_park_s=PARK_MAX_S, max_gesamt_s=GESAMT_MAX_S, abgebrochen=None,
                     versuch_max_s=VERSUCH_MAX_S):
    """Ruft aufruf() auf; bei Netzfehler vor der Antwort bis zu len(pausen) Wiederholungen - aber ein Aufruf haengt nie laenger als
    max_gesamt_s (45 s) in Versuchen, Pausen und Parken zusammen (S-3c P5a; vor jedem weiteren Versuch wird versuch_max_s eingerechnet, damit die Summe hoechstens 45 s bleibt, solange ein Versuch hoechstens versuch_max_s dauert); der Stopp wird auch in den Pausen geprueft.
    Andere Fehler (auch HTTP-Fehlercodes) werden nie wiederholt. Netz weg -> parken statt Fehler."""
    schlafen = schlafen or time.sleep
    start = jetzt()
    versuch = 0
    while True:
        if abgebrochen is not None and abgebrochen():
            raise Abgebrochen()
        if netz_weg(root, jetzt) and not parken(root, schlafen, jetzt, min(max_park_s, max(0, max_gesamt_s - versuch_max_s - (jetzt() - start))), abgebrochen):
            raise NetzWeg("Das Netz ist gerade weg. Ich mache weiter, sobald es wieder da ist.")
        try:
            return aufruf()
        except NETZFEHLER:
            if versuch >= len(pausen) or (jetzt() - start) + pausen[versuch] + versuch_max_s > max_gesamt_s:
                raise
            _schlafen(pausen[versuch], schlafen, abgebrochen)
            versuch += 1
