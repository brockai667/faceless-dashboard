# -*- coding: utf-8 -*-
"""TikTok data fetch pre centralu — user.info (rast uctu) + video.list (per-video).
Mapuje ucty podla realneho display_name; expirovane access tokeny sam obnovi cez refresh_token."""
import json, os, urllib.parse, urllib.request, urllib.error

OAUTH = "https://open.tiktokapis.com/v2/oauth/token/"
USERINFO = ("https://open.tiktokapis.com/v2/user/info/"
            "?fields=open_id,display_name,follower_count,likes_count,video_count")
VIDEOLIST = ("https://open.tiktokapis.com/v2/video/list/"
             "?fields=id,title,view_count,like_count,comment_count,share_count,create_time")

def _refresh(ck, cs, refresh_token):
    body = urllib.parse.urlencode({"client_key": ck, "client_secret": cs,
        "grant_type": "refresh_token", "refresh_token": refresh_token}).encode()
    req = urllib.request.Request(OAUTH, data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read().decode())

def _api(url, token, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read().decode())

def fetch_all(root):
    """Vrati {display_name: {"stats":{...}, "videos":[...]}} pre vsetky prepojene ucty."""
    tpath = os.path.join(root, "tiktok_tokens.json")
    spath = os.path.join(root, "settings.json")
    if not os.path.exists(tpath):
        return {}
    s = json.load(open(spath, encoding="utf-8")) if os.path.exists(spath) else {}
    ck, cs = s.get("tiktok_client_key"), s.get("tiktok_client_secret")
    tokens = json.load(open(tpath, encoding="utf-8"))
    out, changed = {}, False

    for label, t in list(tokens.items()):
        acc, rt = t.get("access_token"), t.get("refresh_token")
        if not acc:
            continue
        # user.info (s auto-refresh pri expiraci)
        try:
            ui = _api(USERINFO, acc)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403) and rt and ck and cs:
                try:
                    nr = _refresh(ck, cs, rt)
                except Exception:
                    continue
                if "access_token" not in nr:
                    continue
                acc = nr["access_token"]
                t["access_token"] = acc
                t["refresh_token"] = nr.get("refresh_token", rt)
                changed = True
                try:
                    ui = _api(USERINFO, acc)
                except Exception:
                    continue
            else:
                print(f"  [TikTok] {label}: chyba {e.code}")
                continue
        except Exception as e:
            print(f"  [TikTok] {label}: {e}")
            continue

        user = ui.get("data", {}).get("user", {})
        name = user.get("display_name") or label
        try:
            vl = _api(VIDEOLIST, acc, "POST", {"max_count": 20})
            vids = vl.get("data", {}).get("videos", [])
        except Exception:
            vids = []
        out[name] = {"stats": user, "videos": vids}

    if changed:
        json.dump(tokens, open(tpath, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return out
