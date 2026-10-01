#!/usr/bin/env python3
"""Einmalige YouTube-Leseanmeldung fuer JACK (Strang Social, 30.09.2026).
Nimmt client_id/client_secret aus dem Schluesselbund (PATRONOS/YOUTUBE_OAUTH, Projekt gott-wald-youtube),
holt per Google-Anmeldung einen dauerhaften Lese-Zugang (youtube.readonly + yt-analytics.readonly)
und legt ihn als JSON in den Schluesselbund-Eintrag PATRONOS_YOUTUBE_LESE. Gibt keinen Schluessel aus."""
import os, http.server, json, subprocess, sys, threading, urllib.parse, urllib.request

SCOPES = ["https://www.googleapis.com/auth/youtube.readonly", "https://www.googleapis.com/auth/yt-analytics.readonly"]
TOKEN = "https://oauth2.googleapis.com/token"

def sb_lesen(args):
    r = subprocess.run(["/usr/bin/security", "find-generic-password", *args, "-w"], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None

import glob, os
roh = sb_lesen(["-s", "PATRONOS", "-a", "YOUTUBE_OAUTH"])
if not roh:
    dateien = sorted(glob.glob(os.path.expanduser("~/Downloads/client_secret_*.json")), key=os.path.getmtime)
    if not dateien:
        sys.exit("CLIENT FEHLT: weder Schluesselbund PATRONOS/YOUTUBE_OAUTH noch ~/Downloads/client_secret_*.json")
    inst = json.load(open(dateien[-1])).get("installed") or {}
    roh = json.dumps({"client_id": inst.get("client_id"), "client_secret": inst.get("client_secret")})
    r0 = subprocess.run(["/usr/bin/security", "add-generic-password", "-U", "-s", "PATRONOS", "-a", "YOUTUBE_OAUTH",
                         "-w", roh], capture_output=True, text=True)
    if r0.returncode != 0:
        sys.exit("SCHLUESSELBUND HAT CLIENT ABGELEHNT.")
    for d in dateien:
        os.remove(d)
    print("Client aus Download uebernommen, Download-Datei geloescht.")
z = json.loads(roh)
cid, cs = z.get("client_id"), z.get("client_secret")
if not cid or not cs:
    sys.exit("CLIENT UNVOLLSTAENDIG im Schluesselbund.")

code = {}
class Empfang(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        code["wert"] = (q.get("code") or [""])[0]; code["fehler"] = (q.get("error") or [""])[0]
        self.send_response(200); self.send_header("Content-Type", "text/plain; charset=utf-8"); self.end_headers()
        self.wfile.write("JACK: YouTube-Lesezugang empfangen. Dieses Fenster kann geschlossen werden.".encode())
    def log_message(self, *a): pass

srv = http.server.HTTPServer(("127.0.0.1", 0), Empfang)
ruf = "http://127.0.0.1:%d/" % srv.server_port
url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
    "client_id": cid, "redirect_uri": ruf, "response_type": "code", "scope": " ".join(SCOPES),
    "access_type": "offline", "prompt": "consent"})
t = threading.Thread(target=srv.handle_request, daemon=True); t.start()
URLDATEI = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".anmelde_url.txt")
open(URLDATEI, "w").write(url)
print("Anmeldung ist bereit. JACK/Claude oeffnet sie in Chrome und bestaetigt. Bitte warten ...")
t.join(timeout=900); srv.server_close()
try:
    os.remove(URLDATEI)
except OSError:
    pass
if not code.get("wert"):
    sys.exit("KEINE ANMELDUNG EMPFANGEN (%s)" % (code.get("fehler") or "Zeit abgelaufen"))
body = urllib.parse.urlencode({"code": code["wert"], "client_id": cid, "client_secret": cs,
                               "redirect_uri": ruf, "grant_type": "authorization_code"}).encode()
with urllib.request.urlopen(urllib.request.Request(TOKEN, data=body, method="POST"), timeout=30) as a:
    antwort = json.loads(a.read())
if not antwort.get("refresh_token"):
    sys.exit("GOOGLE LIEFERTE KEINEN DAUERZUGANG (refresh_token).")
wert = json.dumps({"client_id": cid, "client_secret": cs, "refresh_token": antwort["refresh_token"]})
r = subprocess.run(["/usr/bin/security", "add-generic-password", "-U", "-s", "PATRONOS_YOUTUBE_LESE", "-a", "patronosai",
                    "-w", wert], capture_output=True, text=True)
if r.returncode != 0:
    sys.exit("SCHLUESSELBUND HAT ABGELEHNT.")
req = urllib.request.Request("https://www.googleapis.com/youtube/v3/channels?part=snippet,statistics&mine=true",
                             headers={"Authorization": "Bearer " + antwort["access_token"]})
with urllib.request.urlopen(req, timeout=30) as a:
    k = json.loads(a.read()).get("items", [{}])[0]
print("OK | KANAL: %s | ID: %s | ABONNENTEN: %s | VIDEOS: %s | RECHTE: nur lesen" % (
    k.get("snippet", {}).get("title"), k.get("id"), k.get("statistics", {}).get("subscriberCount"),
    k.get("statistics", {}).get("videoCount")))
