# -*- coding: utf-8 -*-
"""S-6: Handy-Auszug der Gehirn-Karte. Die volle Karte (/gehirn/karte, ~3,4 MB, ~15.600 Knoten) ist fuer ein Handy zu schwer;
am Handy (User-Agent iPhone/Android/Mobile) liefert der Server einen Auszug: die am staerksten verknuepften Ordner und Notizen
(hoechstens MAX_KNOTEN), samt den Kanten dazwischen. Mit ?voll=1 gibt es immer die volle Karte. Kein Modell, nur Lesen."""
import re

MAX_KNOTEN = 2500
_HANDY = re.compile(r"iPhone|Android|Mobile", re.I)


def ist_handy(user_agent):
    return bool(_HANDY.search(str(user_agent or "")))


def auszug(karte, max_knoten=MAX_KNOTEN):
    """karte: Antwort von jack_gehirn.karte(). knoten = [Name, Gruppe, 0=Ordner|1=Notiz, x, y, Pfad, Zweck]; kanten = [von, nach, Art]."""
    knoten, kanten = karte["knoten"], karte["kanten"]
    if len(knoten) <= max_knoten:
        return dict(karte, handy_auszug=False)
    grad = [0] * len(knoten)
    for v, n, _ in kanten:
        grad[v] += 1
        grad[n] += 1
    # Rangfolge nach Verknuepfungsgrad; Ordner zaehlen 3 mehr (sie halten die Karte zusammen)
    rang = sorted(range(len(knoten)), key=lambda i: (-(grad[i] + (3 if knoten[i][2] == 0 else 0)), i))
    behalten = sorted(rang[:max_knoten])
    neu = {alt: nr for nr, alt in enumerate(behalten)}
    k2 = [knoten[i] for i in behalten]
    e2 = [[neu[v], neu[n], a] for v, n, a in kanten if v in neu and n in neu]
    zaehler = {}
    gruppen = karte.get("gruppen") or []
    for k in k2:
        name = gruppen[k[1]] if isinstance(k[1], int) and k[1] < len(gruppen) else str(k[1])
        zaehler[name] = zaehler.get(name, 0) + 1
    aus = dict(karte)
    aus.update(knoten=k2, kanten=e2, anzahl_knoten=len(k2), anzahl_kanten=len(e2), gruppen_zaehler=zaehler, handy_auszug=True,
               handy_weggelassen_knoten=len(knoten) - len(k2), hinweis=str(karte.get("hinweis", "")) + " Handy-Auszug: die am staerksten verknuepften Ordner und Notizen; vollstaendig mit ?voll=1.")
    return aus
