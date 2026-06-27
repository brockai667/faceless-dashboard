# -*- coding: utf-8 -*-
"""Instagram data fetch pre centralu cez Instagram Graph API (Instagram Login).
Cita ig_tokens.json (dlhodobe tokeny per ucet) -> {username: {"stats":{...}, "media":[...]}}.
Dlhodoby token sam predlzi (ig_refresh_token) ak sa bliz koniec platnosti."""
import json, os, time, urllib.parse, urllib.request, urllib.error

GRAPH = "https://graph.instagram.com"


def _get(path, params):
    url = f"{GRAPH}/{path}?" + urllib.parse.urlencode(params)
    return json.loads(urllib.request.urlopen(urllib.request.Request(url), timeout=30).read().decode())


def _media_views(mid, token):
    """Pocet videni pre reel/video cez insights — tolerantne (0 ak nedostupne)."""
    try:
        ins = _get(f"{mid}/insights", {"metric": "views", "access_token": token})
        for row in ins.get("data", []):
            if "total_value" in row:
                return int(row["total_value"].get("value", 0) or 0)
            vals = row.get("values") or []
            if vals:
                return int(vals[0].get("value", 0) or 0)
    except Exception:
        pass
    return 0


def fetch_all(root):
    tpath = os.path.join(root, "ig_tokens.json")
    if not os.path.exists(tpath):
        return {}
    tokens = json.load(open(tpath, encoding="utf-8"))
    out, changed = {}, False
    now = time.time()

    for uname, t in list(tokens.items()):
        tok = t.get("access_token")
        if not tok:
            continue
        # auto-refresh dlhodobeho tokenu ak ostava < 10 dni (alebo neznamy cas)
        try:
            exp_at = t.get("_refreshed_at", 0) + (t.get("expires_in") or 0)
            if not t.get("_refreshed_at") or exp_at - now < 10 * 86400:
                rr = _get("refresh_access_token", {"grant_type": "ig_refresh_token", "access_token": tok})
                if rr.get("access_token"):
                    tok = rr["access_token"]
                    t["access_token"] = tok
                    t["expires_in"] = rr.get("expires_in", t.get("expires_in"))
                    t["_refreshed_at"] = now
                    changed = True
        except Exception:
            pass  # refresh nie je kriticky; skusame dalej s aktualnym tokenom

        try:
            me = _get("me", {"fields": "username,followers_count,media_count", "access_token": tok})
        except urllib.error.HTTPError as e:
            print(f"  [IG] {uname}: chyba {e.code}"); continue
        except Exception as e:
            print(f"  [IG] {uname}: {e}"); continue

        try:
            ml = _get("me/media", {
                "fields": "id,caption,like_count,comments_count,media_type,media_product_type,permalink,timestamp",
                "limit": "15", "access_token": tok})
            media = ml.get("data", [])
        except Exception:
            media = []

        for m in media:
            is_video = (m.get("media_product_type") in ("REELS", "VIDEO")) or m.get("media_type") == "VIDEO"
            m["_views"] = _media_views(m["id"], tok) if is_video else 0

        out[me.get("username", uname)] = {"stats": me, "media": media}

    if changed:
        json.dump(tokens, open(tpath, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return out
