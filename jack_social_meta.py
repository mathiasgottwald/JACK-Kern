"""Meta-Konten finden (M-16): listet Seiten + verknuepftes Instagram-Konto zu einem Token. Nur Lesen."""
import jack_social as js


def meta_konten_finden(token, name_teil="patronosai"):
    ok, erg = js._graph_get("me/accounts", {
        "fields": "id,name,instagram_business_account{id,username}", "limit": 100}, token)
    if not ok:
        return {"zustand": erg, "seiten": []}
    seiten = []
    for s in erg.get("data", []):
        ig = s.get("instagram_business_account") or {}
        text = ("%s %s" % (s.get("name", ""), ig.get("username", ""))).lower().replace(" ", "")
        if name_teil in text:
            seiten.append({"page_id": s.get("id"), "name": s.get("name"),
                           "ig_user_id": ig.get("id"), "ig_username": ig.get("username")})
    return {"zustand": "gelesen", "seiten": seiten}
