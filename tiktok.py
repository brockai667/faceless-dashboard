# -*- coding: utf-8 -*-
"""TikTok data fetch pre centralu — user.info (rast uctu) + video.list (per-video).
Kluc vysledku je display_name (nie username!) — preto stats nesie aj `_label` a `_username`, podla ktorych
generate.py priradi fabriku. Expirovane access tokeny sam obnovi cez refresh_token."""
import calendar, json, os, re, time, urllib.parse, urllib.request, urllib.error

OAUTH = "https://open.tiktokapis.com/v2/oauth/token/"
USERINFO = ("https://open.tiktokapis.com/v2/user/info/"
            "?fields=open_id,display_name,follower_count,likes_count,video_count")
VIDEOLIST = ("https://open.tiktokapis.com/v2/video/list/"
             "?fields=id,title,view_count,like_count,comment_count,share_count,create_time,share_url")
_SHARE_USER = re.compile(r"tiktok\.com/(?:@|%40)([^/?#\s]+)", re.I)

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

def token_labels(root):
    """Len KLUCE (stitky uctov) z tiktok_tokens.json — nikdy hodnoty tokenov. Prazdny zoznam ak subor chyba."""
    tpath = os.path.join(root, "tiktok_tokens.json")
    if not os.path.exists(tpath):
        return []
    with open(tpath, encoding="utf-8") as f:
        tokens = json.load(f)
    return list(tokens.keys()) if isinstance(tokens, dict) else []

def _username_from_videos(videos):
    """Username uctu zo share_url prveho videa (tiktok.com/@<username>/...); '' ak nie je ziadne video/URL."""
    for v in videos or []:
        m = _SHARE_USER.search(str(v.get("share_url") or ""))
        if m:
            return m.group(1)
    return ""

def _since_epoch(since):
    """'YYYY-MM-DD' (UTC pulnoc) -> unix sekundy; None/neplatne -> None (= stare spravanie bez views_since)."""
    if not since:
        return None
    try:
        return calendar.timegm(time.strptime(str(since), "%Y-%m-%d"))
    except ValueError:
        return None

def fetch_all(root, since=None):
    """Vrati {display_name: {"stats":{...}, "videos":[...]}} pre vsetky prepojene ucty.
    stats navyse: `_label` (kluc tokenu v tiktok_tokens.json), `_username` (zo share_url; '' bez videi) a, ak je
    zadane `since` ('YYYY-MM-DD', UTC), `views_since` = sucet view_count videi od toho dna cez VSETKY strany
    (bez `since` sa spravanie nemeni)."""
    since_ep = _since_epoch(since)
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
        # Paginuj cez VSETKY videa -> sucet view_count = realne ZHLIADNUTIA (lifetime).
        # Do 'videos' nechaj len prvych 20 (na winners/zobrazenie), zvysok len scitaj.
        vids, views_total, views_since, cursor = [], 0, 0, None
        for _pg in range(40):   # bezpecnostny strop: 40 * 20 = 800 videi
            body = {"max_count": 20}
            if cursor is not None:
                body["cursor"] = cursor
            try:
                vl = _api(VIDEOLIST, acc, "POST", body)
            except Exception:
                break
            data = vl.get("data", {}) or {}
            page = data.get("videos", []) or []
            if not page:
                break
            if len(vids) < 20:
                vids.extend(page[:20 - len(vids)])
            views_total += sum(int(v.get("view_count", 0) or 0) for v in page)
            if since_ep is not None:   # Part-2 sucet: len videa od `since` (bez `create_time` sa nepocitaju), cez vsetky strany
                views_since += sum(int(v.get("view_count", 0) or 0) for v in page
                                   if int(v.get("create_time", 0) or 0) >= since_ep)
            if not data.get("has_more"):
                break
            cursor = data.get("cursor")
            if cursor is None:
                break
        stats = {**user, "views_total": views_total, "_label": label, "_username": _username_from_videos(vids)}
        if since_ep is not None:
            stats["views_since"] = views_since
        out[name] = {"stats": stats, "videos": vids}

    if changed:
        json.dump(tokens, open(tpath, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return out
