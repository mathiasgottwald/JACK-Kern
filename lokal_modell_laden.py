#!/usr/bin/env python3
"""Ein lokales Modell holen - der EINZIGE Vorgang in Stufe 0, der ins Netz geht.

Auftrag 27.1, Aufgabe 2. Warum es dieses Skript gibt und nicht ein Befehl von
Hand: Die Quelle muss begrenzt sein. Erlaubt sind nur `mlx-community/` und das
offizielle Konto `Qwen/` - alles andere wird abgewiesen, bevor ein Byte
fliesst. Unzensierte, "abliterated" oder "refusal-removed" Fassungen kommen
hier nicht durch, weil sie in diesen Konten nicht liegen; und wer sie von
woanders holen will, muss dieses Skript aendern und damit eine Entscheidung
treffen, die man sieht.

Geladen wird DIREKT nach `lokal.nosync/modelle/<Name>/` (`local_dir`), nicht
ueber den Zwischenspeicher von Hugging Face - sonst laege jedes Modell zweimal
auf der Platte, einmal mit 15 GB. `*.nosync` wird von iCloud nicht uebertragen.

Aufruf:
    lokal.nosync/python/bin/python lokal_modell_laden.py mlx-community/<Modell>

Im Hintergrund (ein Modell braucht rund eine Stunde):
    nohup lokal.nosync/python/bin/python lokal_modell_laden.py \\
        mlx-community/Qwen3.8-27B-4bit > lokal.nosync/laden.log 2>&1 &

Der Fortschritt laesst sich jederzeit ablesen:
    python3 jack_lokal.py stand
Solange dort `fertig: false` steht, ruehrt Stufe 0 das Modell nicht an.
"""
import os
import sys
import time
from pathlib import Path

HIER = Path(__file__).resolve().parent
ZIEL = HIER / "lokal.nosync" / "modelle"
ERLAUBTE_KONTEN = ("mlx-community/", "Qwen/")


def laden(repo):
    if not repo.startswith(ERLAUBTE_KONTEN):
        raise SystemExit("Abgewiesen: '%s'. Erlaubt sind nur %s"
                         % (repo, " und ".join(ERLAUBTE_KONTEN)))
    os.environ["HF_HOME"] = str(HIER / "lokal.nosync" / "hf")
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    from huggingface_hub import snapshot_download
    ordner = ZIEL / repo.split("/", 1)[1]
    t0 = time.time()
    pfad = snapshot_download(repo_id=repo, local_dir=str(ordner), max_workers=4)
    groesse = sum(f.stat().st_size for f in Path(pfad).rglob("*")
                  if f.is_file() and ".cache" not in f.parts)
    return {"repo": repo, "pfad": pfad, "gigabyte": round(groesse / 1e9, 2),
            "sekunden": round(time.time() - t0)}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Aufruf: lokal_modell_laden.py <konto>/<modell>")
    d = laden(sys.argv[1])
    print("FERTIG %(repo)s | %(gigabyte)s GB | %(sekunden)s s | %(pfad)s" % d)
