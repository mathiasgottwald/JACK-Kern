#!/usr/bin/env python3
"""Stufe 0: der Arbeiter, der das lokale Textmodell GELADEN HAELT (Auftrag 27.1).

Warum es diesen Prozess gibt: Bis heute startete jeder Aufruf von Stufe 0 einen
eigenen Python-Prozess und las das Modell vollstaendig neu von der Platte. Bei
4,3 GB (Qwen2.5-7B) waren das rund 0,5 s; bei 12 bis 16 GB waere es ein
Vielfaches - je Aufgabe. Ein Modell, das dauernd neu geladen wird, ist bei
dieser Groesse nicht benutzbar.

Vorbild ist jack_qwen_worker.py (die lokale Stimme): ein langlebiger Prozess,
Zeilen-Protokoll ueber stdin/stdout, kein Netz, kein Port. Uebernommen sind
auch die Wachen: Laengengrenzen auf jeder Eingabe, Abbruch je Auftrag, Ende
mit dem Elternprozess.

Vier Dinge kann dieser Arbeiter, die der alte Weg nicht konnte:
  * Warteschlange    - Auftraege stehen an, statt sich zu ueberholen (Stufe 0
                       rechnet immer nur EINEN Auftrag; Parallelitaet 1).
  * Abbruch          - 'stopp' beendet einen laufenden Auftrag zwischen zwei
                       Woertern, nicht erst nach dem letzten.
  * Gesundheitspruefung - 'puls' wird vom LESE-Faden beantwortet und kommt
                       deshalb auch dann zurueck, wenn gerade gerechnet wird.
                       Genau so erkennt der Aufrufer "belegt" statt "tot".
  * Entladen         - nach einstellbarer Leerlaufzeit gibt der Arbeiter das
                       Modell frei. Der Speicher gehoert dann wieder der
                       Stimme. Der naechste Auftrag laedt neu.

Die Stimme hat Vorrang: Dieser Prozess laedt nichts, solange der Aufrufer
(jack_lokal.py) nicht genug freien Arbeitsspeicher gemessen hat, und er gibt
den Speicher im Leerlauf von selbst wieder her.

Offline: HF_HUB_OFFLINE=1 und TRANSFORMERS_OFFLINE=1, nur der lokale Ordner.
Kein Schluessel, keine Verbindung nach aussen, kein offener Port.
"""
import gc
import json
import os
import signal
import sys
import threading
import time
from collections import deque
from pathlib import Path

EINSTELLUNG = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                  HF_HUB_DISABLE_TELEMETRY="1", HF_HUB_DISABLE_IMPLICIT_TOKEN="1",
                  TOKENIZERS_PARALLELISM="false",
                  HF_HOME=str(Path(EINSTELLUNG["modell"]).parent.parent / "hf"))

ELTERN = os.getppid()
SPERRE = threading.RLock()
WACHE = threading.Condition()
WARTESCHLANGE = deque()
ABGEBROCHEN = set()
SCHLUSS = threading.Event()

# Grenzen. Sie stehen hier und nicht in der Einstellung, damit eine falsche
# Einstellung den Arbeiter nicht sprengen kann.
ZEILE_MAX = 64000            # eine Protokollzeile
AUFGABE_MAX = 12000          # Zeichen, wie bisher in jack_lokal.antwort()
WARTESCHLANGE_MAX = 8
TOKEN_MAX = 4000

MODELL = {"modell": None, "zerleger": None, "geladen_seit": None, "laden_s": None}
LETZTE_ARBEIT = [time.monotonic()]
RECHNET = [None]             # die id des Auftrags, der gerade rechnet - oder None
LEERLAUF_S = max(60, int(EINSTELLUNG.get("leerlauf_s") or 900))
KONTEXT = max(2048, int(EINSTELLUNG.get("kontext_grenze") or 16384))


def melden(zeile):
    with SPERRE:
        print(json.dumps(zeile, ensure_ascii=False), flush=True)


def ist_id(wert):
    return (isinstance(wert, str) and len(wert) == 32
            and all(z in "0123456789abcdef" for z in wert))


def lesen():
    """Der Lese-Faden. Er nimmt Auftraege an und beantwortet 'puls' SOFORT.

    'puls' darf nicht in der Warteschlange landen: Eine Gesundheitspruefung,
    die erst nach dem laufenden Auftrag antwortet, misst die Warteschlange und
    nicht die Gesundheit.
    """
    try:
        for zeile in iter(lambda: sys.stdin.readline(ZEILE_MAX), ""):
            if len(zeile) >= ZEILE_MAX or not zeile.endswith("\n"):
                raise ValueError("Zeilengrenze")
            satz = json.loads(zeile)
            art, kennung = satz.get("typ"), satz.get("id")
            if not ist_id(kennung):
                raise ValueError("Auftragskennung")
            if art == "puls":
                melden({"typ": "puls_ok", "id": kennung, "geladen": MODELL["modell"] is not None,
                        "rechnet": RECHNET[0], "warteschlange": len(WARTESCHLANGE),
                        "leerlauf_s": round(time.monotonic() - LETZTE_ARBEIT[0], 1),
                        "speicher_gb": speicher_gb(), "kontext_grenze": KONTEXT})
                continue
            with WACHE:
                if art == "frage":
                    aufgabe = satz.get("aufgabe")
                    system = satz.get("system") or ""
                    hoechstens = int(satz.get("hoechstens") or 700)
                    if not isinstance(aufgabe, str) or not 0 < len(aufgabe) <= AUFGABE_MAX:
                        raise ValueError("Aufgabengrenze")
                    if not isinstance(system, str) or len(system) > AUFGABE_MAX:
                        raise ValueError("Vorgabengrenze")
                    if not 1 <= hoechstens <= TOKEN_MAX:
                        raise ValueError("Tokengrenze")
                    if len(WARTESCHLANGE) >= WARTESCHLANGE_MAX:
                        raise ValueError("Warteschlange voll")
                    WARTESCHLANGE.append((kennung, system, aufgabe, hoechstens))
                elif art == "stopp":
                    ABGEBROCHEN.add(kennung)
                elif art == "entladen":
                    # Nur die Leerlaufuhr zuruecksetzen. Einen laufenden Auftrag
                    # bricht 'entladen' NICHT ab - dafuer gibt es 'stopp'. Zwei
                    # Bedeutungen in einem Befehl waeren eine Falle.
                    LETZTE_ARBEIT[0] = time.monotonic() - LEERLAUF_S - 1
                else:
                    raise ValueError("Auftragsart")
                WACHE.notify_all()
    except Exception:
        melden({"typ": "prozess_fehler", "grund": "eingabe"})
    finally:
        SCHLUSS.set()
        with WACHE:
            WACHE.notify_all()


def eltern_beobachten():
    """Stirbt JACK, stirbt der Arbeiter. Sonst haelt ein Waisenprozess 13 GB."""
    while not SCHLUSS.wait(0.5):
        if os.getppid() != ELTERN:
            os._exit(0)


def speicher_gb():
    """Was das Modell in diesem Prozess wirklich belegt - aus mlx, nicht geraten."""
    try:
        import mlx.core as mx
        return {"aktiv": round(mx.get_active_memory() / 1e9, 2),
                "spitze": round(mx.get_peak_memory() / 1e9, 2),
                "puffer": round(mx.get_cache_memory() / 1e9, 2)}
    except Exception:
        return {}


def laden():
    """Einmal laden, dann liegen lassen. Die Ladezeit wird gemeldet, weil sie
    der Beleg dafuer ist, dass der zweite Aufruf sie NICHT mehr hat."""
    from mlx_lm import load
    import mlx.core as mx
    t0 = time.time()
    modell, zerleger = load(EINSTELLUNG["modell"])
    # mlx laedt faul: ohne mx.eval stuende die halbe Ladezeit spaeter beim
    # ersten Wort und die gemessene Ladezeit waere geschoent.
    mx.eval(modell.parameters())
    MODELL.update(modell=modell, zerleger=zerleger, laden_s=round(time.time() - t0, 2),
                  geladen_seit=time.time())
    return MODELL["laden_s"]


def entladen(grund):
    """Speicher zurueckgeben. Die Stimme hat Vorrang - im Leerlauf gehoert ihr
    der Arbeitsspeicher, nicht einem Modell, das gerade nichts tut."""
    if MODELL["modell"] is None:
        return
    MODELL.update(modell=None, zerleger=None, geladen_seit=None)
    gc.collect()
    try:
        import mlx.core as mx
        mx.clear_cache()
    except Exception:
        pass
    melden({"typ": "entladen", "grund": grund, "speicher_gb": speicher_gb()})


def leerlauf_beobachten():
    while not SCHLUSS.wait(5):
        # Pruefen UND entladen unter derselben Sperre. Sonst koennte der
        # Hauptfaden zwischen Pruefung und Entladen einen Auftrag annehmen und
        # dann mitten im Rechnen ohne Zerleger dastehen.
        with WACHE:
            if (not WARTESCHLANGE and RECHNET[0] is None
                    and MODELL["modell"] is not None
                    and time.monotonic() - LETZTE_ARBEIT[0] > LEERLAUF_S):
                entladen("leerlauf")


def rechnen(kennung, system, aufgabe, hoechstens):
    """Ein Auftrag. Gemessen wird, was der Bericht braucht: Ladezeit (nur beim
    ersten Mal), Zeit bis zum ersten Wort, Token je Sekunde, Speicherspitze."""
    import mlx.core as mx
    from mlx_lm import stream_generate
    laden_s = 0.0
    if MODELL["modell"] is None:
        laden_s = laden()
    zerleger = MODELL["zerleger"]
    eingabe = zerleger.apply_chat_template(
        [{"role": "system", "content": system}, {"role": "user", "content": aufgabe}],
        add_generation_prompt=True)
    # Nichts still abschneiden: Passt die Aufgabe nicht ins Kontextfenster,
    # ist das ein ehrlicher Fehler und kein halb gelesener Auftrag.
    if len(eingabe) + hoechstens > KONTEXT:
        raise ValueError("Aufgabe und Antwort passen nicht in das Kontextfenster "
                         "(%d + %d > %d)" % (len(eingabe), hoechstens, KONTEXT))
    mx.reset_peak_memory()
    t0 = time.time()
    erstes = None
    stuecke = []
    anzahl = 0
    for antwort in stream_generate(MODELL["modell"], zerleger, prompt=eingabe,
                                   max_tokens=hoechstens, max_kv_size=KONTEXT):
        if erstes is None:
            erstes = round(time.time() - t0, 2)
        stuecke.append(antwort.text)
        anzahl += 1
        with WACHE:
            if kennung in ABGEBROCHEN or SCHLUSS.is_set():
                raise InterruptedError("abgebrochen")
    dauer = time.time() - t0
    return {"antwort": "".join(stuecke), "laden_s": laden_s,
            "rechnen_s": round(dauer, 2), "erstes_wort_s": erstes,
            "token_ein": len(eingabe), "token_aus": anzahl,
            "token_je_s": round(anzahl / dauer, 2) if dauer > 0 else None,
            "speicher_gb": speicher_gb(), "kontext_grenze": KONTEXT}


def main():
    signal.signal(signal.SIGTERM, lambda *a: SCHLUSS.set())
    threading.Thread(target=lesen, daemon=True).start()
    threading.Thread(target=eltern_beobachten, daemon=True).start()
    threading.Thread(target=leerlauf_beobachten, daemon=True).start()
    try:
        laden_s = laden()
    except Exception as fehler:
        melden({"typ": "prozess_fehler", "grund": str(fehler)[:300]})
        return
    melden({"typ": "prozess_bereit", "laden_s": laden_s, "modell": Path(EINSTELLUNG["modell"]).name,
            "speicher_gb": speicher_gb(), "kontext_grenze": KONTEXT,
            "leerlauf_s": LEERLAUF_S})
    while not SCHLUSS.is_set():
        with WACHE:
            if not WARTESCHLANGE:
                WACHE.wait(timeout=0.5)
            if not WARTESCHLANGE:
                continue
            kennung, system, aufgabe, hoechstens = WARTESCHLANGE.popleft()
            if kennung in ABGEBROCHEN:
                ABGEBROCHEN.discard(kennung)
                melden({"typ": "abgebrochen", "id": kennung})
                continue
            RECHNET[0] = kennung
        try:
            ergebnis = rechnen(kennung, system, aufgabe, hoechstens)
            ergebnis.update(typ="antwort", id=kennung)
            melden(ergebnis)
        except InterruptedError:
            melden({"typ": "abgebrochen", "id": kennung})
        except Exception as fehler:
            melden({"typ": "fehler", "id": kennung, "grund": str(fehler)[:300]})
        finally:
            with WACHE:
                RECHNET[0] = None
                ABGEBROCHEN.discard(kennung)
            LETZTE_ARBEIT[0] = time.monotonic()
    entladen("ende")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        melden({"typ": "prozess_fehler", "grund": "start"})
