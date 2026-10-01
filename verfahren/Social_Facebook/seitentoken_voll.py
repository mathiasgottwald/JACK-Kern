#!/usr/bin/env python3
"""Einmalig: Seiten-Token PATRONOS (Seite 183068859307539) mit VOLLZUGRIFF ablegen (Strang Social, 30.09.2026).
Liest einen LANGLEBIGEN Nutzer-Token aus der Zwischenablage (Access Token Debugger > "Zugriffsschluessel verlaengern"),
leitet daraus das Seiten-Token ab (laeuft nie ab), legt es in den Schluesselbund PATRONOS_FACEBOOK_LESE/patronosai
(Name bleibt fuer den bestehenden Code) und leert die Zwischenablage. Gibt keinen Schluessel aus."""
import json, subprocess, sys, urllib.parse, urllib.request
SEITE = "183068859307539"
API = "https://graph.facebook.com/v25.0/"

def hole(pfad, **p):
    url = API + pfad + "?" + urllib.parse.urlencode(p)
    try:
        with urllib.request.urlopen(url, timeout=30) as a:
            return json.loads(a.read())
    except urllib.error.HTTPError as e:
        return {"error": json.loads(e.read() or b"{}").get("error", {"code": e.code})}

nutzer = subprocess.run(["pbpaste"], capture_output=True, text=True).stdout.strip()
if not nutzer.startswith("EAA"):
    sys.exit("ZWISCHENABLAGE ENTHAELT KEINEN META-SCHLUESSEL (LAENGE %d)" % len(nutzer))
d = hole("debug_token", input_token=nutzer, access_token=nutzer).get("data", {})
if d.get("type") != "USER" or not d.get("is_valid"):
    sys.exit("KEIN GUELTIGER NUTZER-SCHLUESSEL (TYP %s)" % d.get("type"))
seiten = hole("me/accounts", fields="id,name,access_token,instagram_business_account", limit=100, access_token=nutzer)
s = next((x for x in seiten.get("data", []) if x.get("id") == SEITE), None)
if not s:
    # Seite gehoert einem Business-Portfolio: me/accounts ist dann leer, direkter Abruf liefert das Seiten-Token
    s = hole(SEITE, fields="id,name,access_token,instagram_business_account", access_token=nutzer)
    if not s.get("access_token"):
        sys.exit("SEITE %s NICHT ERREICHBAR (%s)" % (SEITE, s.get("error", {}).get("message", "kein Token")))
tok = s["access_token"]
p = hole("debug_token", input_token=tok, access_token=tok).get("data", {})
if p.get("type") != "PAGE" or not p.get("is_valid"):
    sys.exit("SEITEN-SCHLUESSEL UNGUELTIG")
if p.get("expires_at", 0) != 0:
    sys.exit("ABBRUCH: Seiten-Schluessel laeuft ab (Nutzer-Schluessel war nicht verlaengert). Nichts gespeichert.")
r = subprocess.run(["/usr/bin/security", "add-generic-password", "-U", "-s", "PATRONOS_FACEBOOK_LESE", "-a", "patronosai",
                    "-w", tok], capture_output=True, text=True)
subprocess.run(["pbcopy"], input="", text=True)
if r.returncode != 0:
    sys.exit("SCHLUESSELBUND HAT ABGELEHNT.")
f = hole(SEITE, fields="name,followers_count", access_token=tok)
ig = (s.get("instagram_business_account") or {}).get("id", "keins")
print("OK | SEITE: %s | FOLLOWER: %s | ABLAUF: nie | INSTAGRAM: %s | RECHTE: %s" % (
    f.get("name"), f.get("followers_count"), ig, " ".join(sorted(p.get("scopes", [])))))
