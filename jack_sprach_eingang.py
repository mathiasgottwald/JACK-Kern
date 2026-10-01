"""Lokale Sprachaufnahme fuer JACK.

Audiodaten leben nur in einem TemporaryDirectory. Der Browser liefert eine
abgeschlossene Aeußerung; ffmpeg normalisiert sie und whisper.cpp erkennt den
Text auf diesem Mac. Es gibt keine Cloud-Transkription und keine Audioablage.
"""
from __future__ import annotations

import atexit
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
import uuid
import wave

import jack_hausnamen


MODELL_HASH = "1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b"
MODELL_BYTES = 487_601_967
VAD_HASH = "2aa269b785eeb53a82983a20501ddf7c1d9c48e33ab63a41391ac6c9f7fb6987"
VAD_BYTES = 885_098
MAX_AUDIO_BYTES = 12 * 1024 * 1024
MAX_AUDIO_SEKUNDEN = 90
# Grundvorgabe fuer whisper.cpp; S-1 P3a haengt die Hausnamen aus der Ablage an
# (Mitarbeiter, Marken, Partner, haeufige Absender - jack_hausnamen.whisper_prompt).
PROMPT_BASIS = "JACK, Patron, Mathias Gottwald, GOTT WALD Holding, PATRONOS, CASHFLOW KOMPASS, Fiverr."
_LOCK = threading.Lock()
_PRUEFUNG = {"pfad": None, "mtime": None, "ok": False, "zeit": None}


def _pfade(root: Path) -> tuple[Path, Path, Path, Path]:
    basis = Path(root) / "lokal.nosync" / "whisper.cpp"
    return (basis / "build" / "bin" / "whisper-cli",
            basis / "models" / "ggml-small-verified.bin",
            basis / "models" / "ggml-silero-v6.2.0.bin",
            Path("/opt/homebrew/bin/ffmpeg"))


def _modell_gueltig(modell: Path) -> bool:
    """Prueft die Datei nach einem Wechsel einmal, nicht bei jeder Anfrage."""
    try:
        st = modell.stat()
    except OSError:
        return False
    if st.st_size != MODELL_BYTES:
        return False
    marker = (str(modell), st.st_mtime_ns)
    if _PRUEFUNG["pfad"] == marker[0] and _PRUEFUNG["mtime"] == marker[1]:
        return bool(_PRUEFUNG["ok"])
    digest = hashlib.sha256()
    with modell.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    _PRUEFUNG.update(pfad=marker[0], mtime=marker[1], ok=digest.hexdigest() == MODELL_HASH,
                     zeit=time.time())
    return bool(_PRUEFUNG["ok"])


def _vad_gueltig(vad: Path) -> bool:
    try:
        if vad.stat().st_size != VAD_BYTES:
            return False
        digest = hashlib.sha256(vad.read_bytes()).hexdigest()
        return digest == VAD_HASH
    except OSError:
        return False


def status(root: Path) -> dict:
    cli, modell, vad, ffmpeg = _pfade(Path(root))
    vorhanden = cli.is_file() and modell.is_file() and vad.is_file() and ffmpeg.is_file()
    geprueft = _PRUEFUNG.get("pfad") == str(modell) and _PRUEFUNG.get("mtime") == (
        modell.stat().st_mtime_ns if modell.is_file() else None
    )
    return {
        "anbieter": "whisper.cpp-small-lokal",
        "lokal": True,
        "bereit": bool(vorhanden and geprueft and _PRUEFUNG.get("ok") and _vad_gueltig(vad)),
        "zustand": "bereit" if vorhanden and geprueft and _PRUEFUNG.get("ok") and _vad_gueltig(vad)
                    else ("wird geprueft" if vorhanden else "Laufzeit oder Modell fehlt"),
        "audio_ablage": False,
    }


def vorbereiten(root: Path) -> dict:
    """Verifiziert bewusst vor Aktivierung; das kann einmalig einige Sekunden dauern."""
    _cli, modell, vad, _ffmpeg = _pfade(Path(root))
    _modell_gueltig(modell)
    _vad_gueltig(vad)
    return status(root)


def aufwaermen(root: Path) -> None:
    """Laedt das Modell vor dem ersten echten Satz mit einer lokalen Stilleprobe."""
    pcm = io.BytesIO()
    with wave.open(pcm, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(b"\0\0" * 16000)
    ergebnis = transkribieren(Path(root), pcm.getvalue(), "audio/wav")
    if ergebnis.get("text"):
        raise RuntimeError("Die Aufwaermprobe enthielt unerwarteten Text.")


# ------------------------------------------------------------------ S-2 P2: dauerhaft geladenes whisper.cpp
# Vorher wurde whisper-cli je Aeusserung neu gestartet und das 488-MB-Modell neu geladen (Erkennung im Schnitt
# 1,06 s). Jetzt haelt ein lokaler whisper-server (nur 127.0.0.1, zufaelliger Port, kein Netz) das Modell dauerhaft
# geladen; die Erkennung dauert etwa 0,2 bis 0,45 s. Erhalten bleiben: Pruefsummenpruefung von Modell und VAD,
# Stille-Verwurf (VAD), Hausnamen-Prompt (beim Start aus der frisch erzeugten Hausnamenliste gebaut).
# Metal (GPU) laeuft nach erneuter Pruefung am 24.09.2026 stabil; bricht der Server ab, startet er beim naechsten
# Aufruf einmal auf der CPU neu (-ng). Faellt auch das aus, greift der bisherige Einzelaufruf von whisper-cli.
_SERVER = {"proc": None, "port": None, "gpu": True, "fehlstarts": 0, "prompt": None}
_SERVER_LOCK = threading.Lock()


def _server_pfad(cli: Path) -> Path:
    return cli.with_name("whisper-server")


def _freier_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _verwaiste_server_beenden(modell: Path) -> None:
    """Ein frueher hart beendeter Dienst kann einen whisper-server als Waisen (Elternprozess 1) hinterlassen."""
    try:
        aus = subprocess.run(["/bin/ps", "-axo", "pid=,ppid=,command="], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return
    for zeile in aus.splitlines():
        teile = zeile.split(None, 2)
        if len(teile) == 3 and teile[1] == "1" and "whisper-server" in teile[2] and str(modell) in teile[2]:
            try:
                os.kill(int(teile[0]), 15)
            except (OSError, ValueError):
                pass


def _server_beenden() -> None:
    proc = _SERVER.get("proc")
    _SERVER.update(proc=None, port=None)
    if proc and proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except (OSError, subprocess.SubprocessError):
            try:
                proc.kill()
            except OSError:
                pass


atexit.register(_server_beenden)


def _server_starten(root: Path) -> bool:
    """Startet den Server (mit Sperre gerufen). True, wenn er antwortet."""
    cli, modell, vad, _ffmpeg = _pfade(Path(root))
    exe = _server_pfad(cli)
    if not exe.is_file():
        return False
    _server_beenden()
    _verwaiste_server_beenden(modell)
    port = _freier_port()
    argv = [str(exe)]
    if not _SERVER["gpu"]:
        argv.append("-ng")
    # -bs 5 -bo 5: wie der bisherige Einzelaufruf (whisper-cli) mit fuenf Suchvarianten; ohne sie (-bs -1) erkannte der
    # Server "von ihm" als "von EAM" (Opus-Pruefung S-2).
    prompt = jack_hausnamen.whisper_prompt(root, PROMPT_BASIS)
    argv += ["-t", "4", "-bs", "5", "-bo", "5", "-m", str(modell), "-l", "de", "-nt", "--vad", "--vad-model", str(vad),
             "--vad-min-silence-duration-ms", "450", "--prompt", prompt,
             "--host", "127.0.0.1", "--port", str(port)]
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return False
    ende = time.monotonic() + 40
    while time.monotonic() < ende:
        if proc.poll() is not None:
            return False
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                _SERVER.update(proc=proc, port=port, prompt=prompt)
                return True
        except OSError:
            time.sleep(0.15)
    proc.kill()
    return False


def _server_port(root: Path):
    with _SERVER_LOCK:
        proc = _SERVER["proc"]
        if proc is not None and proc.poll() is None and _SERVER["port"]:
            # S-2b P4: Hausnamen geaendert (neuer Mitarbeiter/Absender)? Dann startet der Server mit dem neuen Prompt neu,
            # bevor diese Aeusserung erkannt wird - kein Dienstneustart noetig.
            try:
                if jack_hausnamen.whisper_prompt(root, PROMPT_BASIS) != _SERVER.get("prompt"):
                    if _server_starten(root):
                        return _SERVER["port"]
                    return None
            except Exception:
                pass
            return _SERVER["port"]
        if _SERVER["fehlstarts"] >= 3:
            return None
        if proc is not None:            # abgestuerzt: einmal auf der CPU neu (Metal-Abbruch war frueher belegt)
            _SERVER["gpu"] = False
        if _server_starten(root):
            return _SERVER["port"]
        _SERVER["fehlstarts"] += 1
        if _SERVER["gpu"]:
            _SERVER["gpu"] = False
            if _server_starten(root):
                return _SERVER["port"]
        return None


def _server_text(root: Path, wav_bytes: bytes):
    """Text vom dauerhaft geladenen Server, oder None (dann greift der Einzelaufruf)."""
    port = _server_port(root)
    if not port:
        return None
    grenze = uuid.uuid4().hex
    teile = []
    for name, wert in (("response_format", "json"), ("temperature", "0.0")):
        teile.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (grenze, name, wert)).encode())
    teile.append(("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"eingabe.wav\"\r\n"
                  "Content-Type: audio/wav\r\n\r\n" % grenze).encode() + wav_bytes + b"\r\n")
    teile.append(("--%s--\r\n" % grenze).encode())
    anfrage = urllib.request.Request("http://127.0.0.1:%d/inference" % port, data=b"".join(teile),
                                     headers={"Content-Type": "multipart/form-data; boundary=" + grenze})
    try:
        with urllib.request.urlopen(anfrage, timeout=45) as antwort:
            daten = json.loads(antwort.read())
    except (OSError, ValueError):
        return None
    if not isinstance(daten, dict) or "text" not in daten:
        return None
    return " ".join(str(daten["text"]).replace("\n", " ").split())


def server_status() -> dict:
    proc = _SERVER.get("proc")
    return {"dauerhaft_geladen": bool(proc is not None and proc.poll() is None), "gpu": _SERVER["gpu"],
            "fehlstarts": _SERVER["fehlstarts"]}


def _suffix(inhaltstyp: str) -> str:
    typ = (inhaltstyp or "").split(";", 1)[0].strip().lower()
    return {
        "audio/webm": ".webm", "audio/ogg": ".ogg", "audio/mp4": ".m4a",
        "audio/mpeg": ".mp3", "audio/wav": ".wav",
    }.get(typ, "")


def transkribieren(root: Path, daten: bytes, inhaltstyp: str) -> dict:
    if not isinstance(daten, bytes) or not 400 <= len(daten) <= MAX_AUDIO_BYTES:
        raise ValueError("Die Sprachaufnahme ist zu kurz oder zu groß.")
    suffix = _suffix(inhaltstyp)
    if not suffix:
        raise ValueError("Dieses Audioformat wird nicht unterstützt.")
    cli, modell, vad, ffmpeg = _pfade(Path(root))
    if not cli.is_file() or not ffmpeg.is_file() or not _modell_gueltig(modell) or not _vad_gueltig(vad):
        raise RuntimeError("Die lokale Spracherkennung ist nicht geprüft bereit.")
    if not _LOCK.acquire(blocking=False):
        raise RuntimeError("Die vorherige Sprachaufnahme wird noch verarbeitet.")
    start = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix="jack-sprache-") as tmp:
            basis = Path(tmp)
            # Bei WAV darf Quelle nicht mit dem normalisierten Ziel identisch
            # sein; ffmpeg verweigert eine Umwandlung auf dieselbe Datei.
            quelle = basis / ("roh" + suffix)
            wav = basis / "eingabe.wav"
            ziel = basis / "text"
            quelle.write_bytes(daten)
            subprocess.run([
                str(ffmpeg), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(quelle), "-vn", "-ac", "1", "-ar", "16000", "-t",
                str(MAX_AUDIO_SEKUNDEN), "-c:a", "pcm_s16le", str(wav),
            ], check=True, timeout=20, capture_output=True)
            # S-2 P2: zuerst der dauerhaft geladene Server (Metal), sonst der bisherige Einzelaufruf
            text = _server_text(Path(root), wav.read_bytes())
            weg = "server"
            if text is None:
                weg = "einzelaufruf"
                subprocess.run([
                    # Rueckfall: CPU/Accelerate, wie bis S-1 (der Einzelaufruf laedt das Modell jedes Mal neu).
                    str(cli), "-ng", "-m", str(modell), "-l", "de", "-t", "4", "-nt", "-np",
                    "--vad", "--vad-model", str(vad), "--vad-min-silence-duration-ms", "450",
                    "-otxt", "-of", str(ziel), "--prompt",
                    jack_hausnamen.whisper_prompt(root, PROMPT_BASIS),
                    "-f", str(wav),
                ], check=True, timeout=45, capture_output=True, text=True)
                textdatei = ziel.with_suffix(".txt")
                text = textdatei.read_text(encoding="utf-8").replace("\n", " ").strip() if textdatei.is_file() else ""
        text = " ".join(text.split())
        return {"text": text, "dauer_ms": round((time.monotonic() - start) * 1000),
                "anbieter": "whisper.cpp-small-lokal", "weg": weg}
    except subprocess.TimeoutExpired as fehler:
        raise RuntimeError("Die lokale Spracherkennung hat ihr Zeitlimit überschritten.") from fehler
    except subprocess.CalledProcessError as fehler:
        raise ValueError("Die Sprachaufnahme konnte nicht gelesen werden.") from fehler
    finally:
        _LOCK.release()
