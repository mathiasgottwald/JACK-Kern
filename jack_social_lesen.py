"""Lese-Abrufe fuer Facebook-Seite, Instagram, YouTube, TikTok, LinkedIn (M-16, 30.09.2026).

Stand M-16-VOLL (30.09.2026): Die Tokens tragen Vollzugriff (Patron-Freigabe), DIESES Modul liest aber nur — es enthaelt bewusst keinen einzigen
schreibenden Aufruf (kein POST ausser dem Token-Tausch bei Google/TikTok, der nur
ein kurzlebiges Zugriffstoken holt). Ohne Schluessel im macOS-Schluesselbund:
Zustand 'nicht_verbunden', kein Netzaufruf. Fehler werden als Zustand
zurueckgegeben, nie als Ausnahme. Tokens werden nie geloggt oder zurueckgegeben.

Schluesselbund-Inhalt (Eingabe nur durch den Patron, siehe verfahren/_Social_*.md):
  Facebook/Instagram : langlebiger Meta-Nutzer-Token (Text)
  YouTube            : JSON {"client_id","client_secret","refresh_token"}
  TikTok             : JSON {"client_key","client_secret","refresh_token"}
  LinkedIn           : Zugriffstoken (Text); Register-Feld `org_id` = Zahl der Organisation
"""
import datetime as dt
import json
import urllib.error
import urllib.parse
import urllib.request

import jack_social as js

YT_API = "https://www.googleapis.com/youtube/v3"
YT_ANALYTICS = "https://youtubeanalytics.googleapis.com/v2/reports"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
TIKTOK_API = "https://open.tiktokapis.com/v2"
LINKEDIN_API = "https://api.linkedin.com/rest"
LINKEDIN_VERSION = "202609"  # 202510 endet 15.10.2026 (Microsoft Learn, 30.09.2026)


def _http_json(url, headers=None, daten=None, timeout=20):
    """(ok, dict) | (False, zustand). Kein Ausnahme-Durchschlag."""
    req = urllib.request.Request(url, headers=headers or {},
                                 data=urllib.parse.urlencode(daten).encode() if daten is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return js._antwort_lesen(r.read())
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return False, "token_abgelaufen_oder_ungueltig" if e.code == 401 else "keine_berechtigung"
        if e.code == 429:
            return False, "ratenlimit"
        return False, "fehler_%s" % e.code
    except js._NETZFEHLER:
        return False, "netz_nicht_erreichbar"


def _json_schluessel(name, pflicht):
    roh = js.schluessel_lesen(name)
    if roh is None:
        return None
    try:
        wert = json.loads(roh)
    except ValueError:
        return {}
    return wert if isinstance(wert, dict) and all(wert.get(k) for k in pflicht) else {}


# ------------------------------------------------------------ Facebook-Seite
def _seitentoken(page_id, token):
    """Nutzer-Token: Seitentoken ueber me/accounts ableiten. Liegt schon ein Seiten-Token im
    Schluesselbund (me/accounts scheitert oder kennt die Seite nicht), gilt es direkt."""
    ok, erg = js._graph_get("me/accounts", {"fields": "id,access_token", "limit": 100}, token)
    if ok:
        for s in erg.get("data", []):
            if s.get("id") == page_id and s.get("access_token"):
                return s["access_token"], None
    return token, None


def facebook_seite_lesen(kanal, tage=7):
    token = js.schluessel_lesen(kanal.get("schluesselbund_name"))
    if token is None:
        return {"zustand": "nicht_verbunden"}
    page_id = str(kanal.get("page_id") or "")
    if not page_id:
        return {"zustand": "kein_page_id_im_register"}
    seitentoken, fehler = _seitentoken(page_id, token)
    if seitentoken is None:
        return {"zustand": fehler}
    ok, seite = js._graph_get(page_id, {"fields": "name,fan_count,followers_count"}, seitentoken)
    if not ok:
        return {"zustand": seite}
    ok2, posts = js._graph_get(page_id + "/posts", {"fields": "id,message,created_time,permalink_url", "limit": 3}, seitentoken)
    bis = js.now(); seit = bis - dt.timedelta(days=tage)
    ok3, ins = js._graph_get(page_id + "/insights", {"metric": "page_media_view", "period": "day",
                                                     "since": int(seit.timestamp()), "until": int(bis.timestamp())}, seitentoken)
    return {
        "zustand": "gelesen" if (ok2 and ok3) else "teilweise_gelesen",
        "name": seite.get("name"), "fan_count": seite.get("fan_count"), "followers_count": seite.get("followers_count"),
        "letzte_beitraege": posts.get("data", []) if ok2 else [], "beitraege_zustand": "gelesen" if ok2 else posts,
        "insights_werte": ins.get("data", []) if ok3 else None, "insights_zustand": "gelesen" if ok3 else ins,
    }


# ------------------------------------------------------------------- YouTube
def youtube_lesen(kanal, tage=7):
    cfg = _json_schluessel(kanal.get("schluesselbund_name"), ("client_id", "client_secret", "refresh_token"))
    if cfg is None:
        return {"zustand": "nicht_verbunden"}
    if not cfg:
        return {"zustand": "schluessel_unvollstaendig"}
    ok, t = _http_json(GOOGLE_TOKEN, daten={"client_id": cfg["client_id"], "client_secret": cfg["client_secret"],
                                            "refresh_token": cfg["refresh_token"], "grant_type": "refresh_token"})
    if not ok or not t.get("access_token"):
        return {"zustand": t if not ok else "kein_zugriffstoken"}
    kopf = {"Authorization": "Bearer " + t["access_token"]}
    kid = kanal.get("kanal_id")
    if not kid:
        return {"zustand": "kein_kanal_id_im_register"}
    q = urllib.parse.urlencode({"part": "snippet,statistics,contentDetails", "id": kid})
    ok, k = _http_json("%s/channels?%s" % (YT_API, q), kopf)
    if not ok:
        return {"zustand": k}
    items = k.get("items") or []
    if not items:
        return {"zustand": "kanal_nicht_gefunden_oder_nicht_inhaber"}
    c = items[0]; st = c.get("statistics", {})
    hochgeladen = c.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
    videos = []; v_zustand = "keine_uploads_playlist"
    if hochgeladen:
        ok, p = _http_json("%s/playlistItems?%s" % (YT_API, urllib.parse.urlencode(
            {"part": "snippet", "playlistId": hochgeladen, "maxResults": 3})), kopf)
        v_zustand = "gelesen" if ok else p
        if ok:
            videos = [{"id": i["snippet"]["resourceId"]["videoId"], "titel": i["snippet"].get("title"),
                       "datum": i["snippet"].get("publishedAt")} for i in p.get("items", [])]
    bis = js.now().date(); seit = bis - dt.timedelta(days=tage)
    ok, a = _http_json("%s?%s" % (YT_ANALYTICS, urllib.parse.urlencode(
        {"ids": "channel==MINE", "startDate": seit.isoformat(), "endDate": bis.isoformat(),
         "metrics": "views,estimatedMinutesWatched,subscribersGained"})), kopf)
    return {
        "zustand": "gelesen" if (v_zustand == "gelesen" and ok) else "teilweise_gelesen",
        "titel": c.get("snippet", {}).get("title"),
        "abonnenten": st.get("subscriberCount"), "videos_gesamt": st.get("videoCount"), "aufrufe_gesamt": st.get("viewCount"),
        "letzte_videos": videos, "videos_zustand": v_zustand,
        "analytics_7tage": (a.get("rows") or [[None]])[0] if ok else None,
        "analytics_zustand": "gelesen" if ok else a,
    }


# -------------------------------------------------------------------- TikTok
def tiktok_lesen(kanal):
    cfg = _json_schluessel(kanal.get("schluesselbund_name"), ("client_key", "client_secret", "refresh_token"))
    if cfg is None:
        return {"zustand": "nicht_verbunden"}
    if not cfg:
        return {"zustand": "schluessel_unvollstaendig"}
    ok, t = _http_json(TIKTOK_API + "/oauth/token/", {"Content-Type": "application/x-www-form-urlencoded"},
                       daten={"client_key": cfg["client_key"], "client_secret": cfg["client_secret"],
                              "grant_type": "refresh_token", "refresh_token": cfg["refresh_token"]})
    if not ok or not t.get("access_token"):
        return {"zustand": t if not ok else "kein_zugriffstoken"}
    kopf = {"Authorization": "Bearer " + t["access_token"]}
    ok, u = _http_json(TIKTOK_API + "/user/info/?fields=" + urllib.parse.quote(
        "open_id,display_name,follower_count,following_count,likes_count,video_count"), kopf)
    if not ok:
        return {"zustand": u}
    profil = (u.get("data") or {}).get("user") or {}
    req = urllib.request.Request(
        TIKTOK_API + "/video/list/?fields=id,title,create_time,view_count,like_count,comment_count,share_count",
        data=json.dumps({"max_count": 3}).encode(), headers=dict(kopf, **{"Content-Type": "application/json"}))
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            ok2, v = js._antwort_lesen(r.read())
    except urllib.error.HTTPError as e:
        ok2, v = False, "fehler_%s" % e.code
    except js._NETZFEHLER:
        ok2, v = False, "netz_nicht_erreichbar"
    return {
        "zustand": "gelesen" if ok2 else "teilweise_gelesen",
        "anzeigename": profil.get("display_name"), "follower": profil.get("follower_count"),
        "likes_gesamt": profil.get("likes_count"), "videos_gesamt": profil.get("video_count"),
        "letzte_videos": (v.get("data") or {}).get("videos", []) if ok2 else [], "videos_zustand": "gelesen" if ok2 else v,
    }


# ------------------------------------------------------------------ LinkedIn
def linkedin_lesen(kanal):
    token = js.schluessel_lesen(kanal.get("schluesselbund_name"))
    if token is None:
        return {"zustand": "nicht_verbunden"}
    org = str(kanal.get("org_id") or "")
    if not org.isdigit():
        return {"zustand": "kein_org_id_im_register"}
    urn = "urn:li:organization:" + org
    kopf = {"Authorization": "Bearer " + token, "Linkedin-Version": LINKEDIN_VERSION,
            "X-Restli-Protocol-Version": "2.0.0"}
    ok, n = _http_json("%s/networkSizes/%s?edgeType=COMPANY_FOLLOWED_BY_MEMBER" % (LINKEDIN_API, urllib.parse.quote(urn, safe="")), kopf)
    if not ok:
        return {"zustand": n}
    ok2, p = _http_json("%s/posts?author=%s&q=author&count=3" % (LINKEDIN_API, urllib.parse.quote(urn, safe="")), kopf)
    return {
        "zustand": "gelesen" if ok2 else "teilweise_gelesen",
        "follower": n.get("firstDegreeSize"),
        "letzte_beitraege": [{"id": e.get("id"), "datum_ms": e.get("publishedAt"), "text": (e.get("commentary") or "")[:120]}
                             for e in p.get("elements", [])] if ok2 else [],
        "beitraege_zustand": "gelesen" if ok2 else p,
    }


# ---------------------------------------------------------------- Instagram (Seiten-Token)
def instagram_lesen(kanal, tage=7):
    """PATRONOS: Seiten-Token (Schluesselbund) + ig_user_id aus dem Register, kein me/accounts."""
    token = js.schluessel_lesen(kanal.get("schluesselbund_name"))
    if token is None:
        return {"zustand": "nicht_verbunden"}
    ig = str(kanal.get("ig_user_id") or "")
    if not ig:
        return {"zustand": "kein_ig_user_id_im_register"}
    ok, p = js._graph_get(ig, {"fields": "username,name,followers_count,media_count"}, token)
    if not ok:
        return {"zustand": p}
    ok2, m = js._graph_get(ig + "/media", {"fields": "id,timestamp,media_type,permalink,like_count,comments_count", "limit": 3}, token)
    bis = js.now(); seit = bis - dt.timedelta(days=tage)
    zf = {"period": "day", "since": int(seit.timestamp()), "until": int(bis.timestamp())}
    ok3, r = js._graph_get(ig + "/insights", dict(zf, metric="reach", metric_type="time_series"), token)
    ok4, t = js._graph_get(ig + "/insights", dict(zf, metric="profile_views,accounts_engaged", metric_type="total_value"), token)
    return {
        "zustand": "gelesen" if (ok2 and ok3 and ok4) else "teilweise_gelesen",
        "username": p.get("username"), "name": p.get("name"),
        "followers_count": p.get("followers_count"), "media_count": p.get("media_count"),
        "letzte_medien": m.get("data", []) if ok2 else [], "medien_zustand": "gelesen" if ok2 else m,
        "insights_werte": (r.get("data", []) if ok3 else []) + (t.get("data", []) if ok4 else []),
        "insights_zustand": "gelesen" if (ok3 and ok4) else (r if not ok3 else t),
    }


LESER = {"Facebook": facebook_seite_lesen, "Instagram": instagram_lesen, "YouTube": youtube_lesen, "TikTok": tiktok_lesen,
         "LinkedIn_Unternehmensseite": linkedin_lesen}


# --- Kompatibilitaets-Schicht (30.09.2026, ttys011): jack_social.py und abnahme/M16_2026-09-30/test_m16.py
# (Terminal ttys008) rufen `lese_kanal(kanal)` auf; `organisation_id` ist Alias fuer `org_id`.
def lese_kanal(kanal):
    leser = LESER.get(kanal.get("plattform"))
    if leser is None:
        return None
    if kanal.get("organisation_id") and not kanal.get("org_id"):
        kanal = dict(kanal, org_id=kanal["organisation_id"])
    return leser(kanal)
