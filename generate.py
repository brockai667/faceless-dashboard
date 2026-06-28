# -*- coding: utf-8 -*-
"""
FacelessFactory — CENTRÁLA (lokálny súkromný dashboard).
Číta Buffer tokeny zo 6 fabrík + (voliteľne) YouTube Data API → generuje dashboard.html.
Spusti:  python generate.py   (alebo dvojklik run.bat)
"""
import json, os, time, urllib.request, urllib.error, datetime
from html import escape

ROOT = os.path.dirname(os.path.abspath(__file__))

# meno, niche, farba, priečinok fabriky
FACTORIES = [
    ("MindBlownDaily",   "FAKTY",      "#3b82f6", r"C:\Users\damia\FacelessFactory"),
    ("WealthMindset",    "PENIAZE",    "#d4a017", r"C:\Users\damia\WealthFactory"),
    ("UnexplainedDaily", "ZÁHADY",     "#8b5cf6", r"C:\Users\damia\MysteryFactory"),
    ("DisciplineDaily",  "MOTIVÁCIA",  "#ef4444", r"C:\Users\damia\MotivationFactory"),
    ("VitalityDaily",    "ZDRAVIE",    "#22c55e", r"C:\Users\damia\HealthFactory"),
    ("HiddenEarth",      "CESTOVANIE", "#06b6d4", r"C:\Users\damia\TravelFactory"),
    ("HistoryUntold",    "HISTÓRIA",   "#c08a3e", r"C:\Users\damia\HistoryFactory"),
    ("ColdCaseDaily",    "TRUE CRIME", "#7c92ad", r"C:\Users\damia\ColdCaseFactory"),
    ("Curio",            "VEDA & TECH","#00c8ff", r"C:\Users\damia\ScienceFactory"),
]

# YouTube channel ID per fabrika (natvrdo — nezavisle od Buffera)
YT_CHANNELS = {
    "MindBlownDaily":   "UCtSLinO4I6R9T7qyY9TNgoA",
    "WealthMindset":    "UCoFCurtPMDdJTDUsea9iCMQ",
    "UnexplainedDaily": "UCBPgjmP9s1daq5b_0w1CRlQ",
    "DisciplineDaily":  "UC4ZZ2gFL4JSNgTZOPPR16Ng",
    "VitalityDaily":    "UCkaYdBJOa1i2PwWd_hHiuKQ",
    "HiddenEarth":      "UCdjrqPNF0jq6yE5y_UZWxNw",
    "HistoryUntold":    "UC54Qa6hJiAA18ls7qUf-6qA",
    "ColdCaseDaily":    "UCngv0ibjtidFdY5ZCmRTUxQ",
    "Curio":            "UCmRfvAQKGLBRxpAF4A0b2Kw",
}

# TikTok handle (display_name) -> fabrika
HANDLE_TO_FACTORY = {
    "insideyourmind007": "MindBlownDaily",
    "wealth_mindset34": "WealthMindset",
    "unexplained_daily": "UnexplainedDaily",
    "disciplinedaily667": "DisciplineDaily",
    "vitalitydaily667": "VitalityDaily",
    "hiddenearth667": "HiddenEarth",
    "historyuntold667": "HistoryUntold",
    "coldcasedaily667": "ColdCaseDaily",
}

# Profilove handle (natvrdo) — odkazy nezavisle od Buffera
TIKTOK_HANDLE = {fac: h for h, fac in HANDLE_TO_FACTORY.items()}
IG_HANDLE = {
    "MindBlownDaily":   "th.erealspark",
    "WealthMindset":    "thewealthmindset.yt667",
    "UnexplainedDaily": "unex.plaineddaily",
    "DisciplineDaily":  "disciplinedaily667",
    "VitalityDaily":    "vitalitydaily667",
    "HiddenEarth":      "hiddenearth667",
    "HistoryUntold":    "historyuntold667",
    "ColdCaseDaily":    "coldcasedaily667",
    "Curio":            "curi.o667",
}

try:
    import tiktok as _tiktok
except Exception:
    _tiktok = None

try:
    import instagram as _instagram
except Exception:
    _instagram = None

# username IG -> fabrika (reverz IG_HANDLE)
IG_TO_FACTORY = {v: k for k, v in IG_HANDLE.items()}

def load_settings():
    p = os.path.join(ROOT, "settings.json")
    if os.path.exists(p):
        return json.load(open(p, encoding="utf-8"))
    return {}

def gql(token, query, tries=2):
    body = json.dumps({"query": query}).encode("utf-8")
    for attempt in range(tries):
        req = urllib.request.Request("https://api.buffer.com/graphql", data=body,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        try:
            d = json.loads(urllib.request.urlopen(req, timeout=30).read().decode("utf-8"))
            if "errors" in d:
                raise RuntimeError(d["errors"])
            return d["data"]
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < tries - 1:
                time.sleep(1.5)
                continue
            raise

def _posts(token, org, status, direction):
    q = (f'query{{posts(input:{{organizationId:"{org}", filter:{{status:[{status}]}}, '
         f'sort:[{{field:dueAt,direction:{direction}}}]}}){{edges{{node{{status sentAt dueAt}}}}}}}}')
    return [e['node'] for e in gql(token, q)['posts']['edges']]

def buffer_orgchan(token):
    org = gql(token, 'query{account{organizations{id}}}')['account']['organizations'][0]['id']
    ch = gql(token, f'query{{channels(input:{{organizationId:"{org}"}}){{service name displayName serviceId externalLink}}}}')['channels']
    return org, ch

def buffer_status(token, org):
    sent = _posts(token, org, 'sent', 'desc')
    sched = _posts(token, org, 'scheduled,sending', 'asc')
    errs = _posts(token, org, 'error', 'desc')
    return sent, sched, errs

def yt_stats(ids, key):
    if not key or not ids:
        return {}
    url = "https://www.googleapis.com/youtube/v3/channels?part=statistics,snippet&id=" + ",".join(ids) + "&key=" + key
    try:
        data = json.loads(urllib.request.urlopen(url, timeout=30).read().decode("utf-8"))
    except Exception as e:
        print("  [YT] chyba:", e); return {}
    out = {}
    for it in data.get("items", []):
        s = it.get("statistics", {})
        out[it["id"]] = {
            "subs": int(s.get("subscriberCount", 0)),
            "views": int(s.get("viewCount", 0)),
            "videos": int(s.get("videoCount", 0)),
            "title": it.get("snippet", {}).get("title", ""),
            "hidden": s.get("hiddenSubscriberCount", False),
        }
    return out

def _iso_dur(s):
    """ISO8601 'PT#H#M#S' -> sekundy."""
    import re as _re
    m = _re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    if not m:
        return 0
    h, mi, se = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + se


def yt_videos(channel_id, key, n=50):
    """Posledných N videí kanála + ich štatistiky (views/likes/comments)."""
    if not key or not channel_id or not channel_id.startswith("UC"):
        return []
    pl = "UU" + channel_id[2:]  # uploads playlist
    try:
        u1 = f"https://www.googleapis.com/youtube/v3/playlistItems?part=contentDetails&maxResults={n}&playlistId={pl}&key={key}"
        items = json.loads(urllib.request.urlopen(u1, timeout=30).read().decode("utf-8")).get("items", [])
        vids = [i["contentDetails"]["videoId"] for i in items]
        if not vids:
            return []
        u2 = f"https://www.googleapis.com/youtube/v3/videos?part=statistics,snippet,contentDetails&id={','.join(vids)}&key={key}"
        data = json.loads(urllib.request.urlopen(u2, timeout=30).read().decode("utf-8")).get("items", [])
    except urllib.error.HTTPError as e:
        if e.code != 404:   # 404 = kanál zatiaľ bez publikovaných videí (nové) — bez chyby
            print("  [YT videos] chyba:", e)
        return []
    except Exception as e:
        print("  [YT videos] chyba:", e); return []
    out = []
    for it in data:
        s = it.get("statistics", {})
        dur = _iso_dur(it.get("contentDetails", {}).get("duration", ""))
        out.append({
            "id": it["id"],
            "title": it.get("snippet", {}).get("title", ""),
            "views": int(s.get("viewCount", 0)),
            "likes": int(s.get("likeCount", 0)),
            "comments": int(s.get("commentCount", 0)),
            "published": it.get("snippet", {}).get("publishedAt", "")[:10],
            "duration": dur, "is_long": dur >= 120,   # >=2 min = dlhy dokument (shorts su <1 min)
        })
    return out

def profile_link(c):
    if c.get("externalLink"):
        return c["externalLink"]
    svc, name = c["service"], (c.get("name") or "").lstrip("@")
    if svc == "youtube" and c.get("serviceId"):
        return f"https://www.youtube.com/channel/{c['serviceId']}"
    if svc == "tiktok":
        return f"https://www.tiktok.com/@{name}"
    if svc == "instagram":
        return f"https://www.instagram.com/{name}"
    if svc == "youtube":
        return f"https://www.youtube.com/@{name}"
    return "#"

def main():
    settings = load_settings()
    yt_key = settings.get("youtube_api_key") or os.environ.get("YOUTUBE_API_KEY", "")
    projects = []
    _cpath = os.path.join(ROOT, "channels_cache.json")
    chan_cache = json.load(open(_cpath, encoding="utf-8")) if os.path.exists(_cpath) else {}
    buffer_down = False  # ak Buffer raz hodi 429, zvysok behu ho preskocime (rychlost)
    for name, niche, color, folder in FACTORIES:
        print("-", name)
        proj = {"name": name, "niche": niche, "color": color, "online": False, "alive": False,
                "sent": 0, "scheduled": 0, "errors": 0, "last_sent": None, "next_due": None,
                "channels": {}, "yt": None, "videos": [], "yt_recent_views": 0, "tiktok": None,
                "instagram": None}
        cfg_path = os.path.join(folder, "config.json")
        if not os.path.exists(cfg_path):
            projects.append(proj); continue
        cfg = json.load(open(cfg_path, encoding="utf-8"))
        token = cfg.get("buffer_token")
        if not token:
            projects.append(proj); continue
        cached = chan_cache.get(name)
        if isinstance(cached, list):      # starý formát (len kanály)
            cached = {"channels": cached}
        cached = cached or {}
        try:
            if buffer_down:
                raise RuntimeError("Buffer preskocený (limit tento beh)")
            org = cached.get("org")
            ch = cached.get("channels")
            if not org or not ch:          # Buffer voláme len pri prvom behu / cache-miss
                org, ch = buffer_orgchan(token)
            for c in ch:
                proj["channels"][c["service"]] = {
                    "name": c.get("displayName") or c.get("name"),
                    "link": profile_link(c),
                    "serviceId": c.get("serviceId"),
                }
            sent, sched, errs = buffer_status(token, org)   # jediné čerstvé Buffer volania (queue stav)
            proj["online"] = True
            proj["sent"], proj["scheduled"], proj["errors"] = len(sent), len(sched), len(errs)
            st = [p["sentAt"] for p in sent if p.get("sentAt")]
            du = [p["dueAt"] for p in sched if p.get("dueAt")]
            if st: proj["last_sent"] = max(st)
            if du: proj["next_due"] = min(du)
            alive = bool(du)
            if st:
                try:
                    last = datetime.datetime.fromisoformat(max(st).replace("Z", "+00:00"))
                    if (datetime.datetime.now(datetime.timezone.utc) - last).total_seconds() < 48*3600:
                        alive = True
                except Exception:
                    pass
            proj["alive"] = alive
            chan_cache[name] = {"org": org, "channels": ch, "status": {
                "sent": proj["sent"], "scheduled": proj["scheduled"], "errors": proj["errors"],
                "last_sent": proj["last_sent"], "next_due": proj["next_due"], "alive": alive}}
        except Exception as e:
            if "429" in str(e) or "Too Many" in str(e):
                buffer_down = True   # zvysok behu Buffer preskocime
            for c in cached.get("channels", []):     # kanály z cache → YouTube/TikTok fungujú ďalej
                proj["channels"].setdefault(c["service"], {
                    "name": c.get("displayName") or c.get("name"),
                    "link": profile_link(c),
                    "serviceId": c.get("serviceId"),
                })
            s = cached.get("status")
            if s:
                proj.update(online=True, stale=True, sent=s.get("sent", 0),
                            scheduled=s.get("scheduled", 0), errors=s.get("errors", 0),
                            last_sent=s.get("last_sent"), next_due=s.get("next_due"),
                            alive=s.get("alive", False))
        projects.append(proj)
        time.sleep(0.3)

    json.dump(chan_cache, open(_cpath, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    # YouTube real stats — z natvrdo mapy YT_CHANNELS (nezavisle od Buffera)
    yt_ids = [YT_CHANNELS[p["name"]] for p in projects if p["name"] in YT_CHANNELS]
    yt = yt_stats(yt_ids, yt_key)
    for p in projects:
        cid = YT_CHANNELS.get(p["name"])
        if not cid:
            continue
        ytc = p["channels"].setdefault("youtube", {})   # zabezpec YT link aj ked Buffer zlyhal
        ytc.setdefault("serviceId", cid)
        ytc.setdefault("link", f"https://www.youtube.com/channel/{cid}")
        if cid in yt:
            p["yt"] = yt[cid]
        if True:
            vids = yt_videos(cid, yt_key)
            for v in vids:
                v["factory"] = p["name"]; v["color"] = p["color"]
                v["platform"] = "YouTube"
                v["link"] = f"https://www.youtube.com/watch?v={v['id']}"
            p["videos"] = vids
            p["yt_recent_views"] = sum(v["views"] for v in vids)

    # --- TikTok (per-video + rast uctu) ---
    by_name = {p["name"]: p for p in projects}
    if _tiktok:
        try:
            tk = _tiktok.fetch_all(ROOT)
        except Exception as e:
            print("  [TikTok] fetch chyba:", e); tk = {}
        for handle, d in tk.items():
            fac = HANDLE_TO_FACTORY.get(handle) or (handle if handle in by_name else None)
            p = by_name.get(fac)
            if not p:
                print(f"  [TikTok] neznámy handle '{handle}' — pridaj do HANDLE_TO_FACTORY")
                continue
            st = d.get("stats", {})
            p["tiktok"] = {"followers": int(st.get("follower_count", 0) or 0),
                           "likes": int(st.get("likes_count", 0) or 0),
                           "videos": int(st.get("video_count", 0) or 0), "handle": handle}
            for v in d.get("videos", []):
                p["videos"].append({
                    "id": v.get("id"),
                    "title": (v.get("title") or "").strip() or "(bez titulku)",
                    "views": int(v.get("view_count", 0) or 0),
                    "likes": int(v.get("like_count", 0) or 0),
                    "comments": int(v.get("comment_count", 0) or 0),
                    "factory": p["name"], "color": p["color"], "platform": "TikTok",
                    "link": f"https://www.tiktok.com/@{handle}/video/{v.get('id')}",
                    "published": (datetime.datetime.utcfromtimestamp(v["create_time"]).strftime("%Y-%m-%d")
                                  if v.get("create_time") else ""),
                })
            p["yt_recent_views"] += sum(int(v.get("view_count", 0) or 0) for v in d.get("videos", []))

    # --- Instagram (per-prispevok + sledovatelia) cez Instagram Graph API ---
    ig = {}
    if _instagram:
        try:
            ig = _instagram.fetch_all(ROOT)
        except Exception as e:
            print("  [IG] fetch chyba:", e); ig = {}
        for uname, d in ig.items():
            fac = IG_TO_FACTORY.get(uname)
            p = by_name.get(fac)
            if not p:
                print(f"  [IG] neznámy účet '{uname}' — pridaj do IG_HANDLE")
                continue
            st = d.get("stats", {})
            p["instagram"] = {"followers": int(st.get("followers_count", 0) or 0),
                              "media": int(st.get("media_count", 0) or 0), "handle": uname}
            for m in d.get("media", []):
                cap = (m.get("caption") or "").strip().replace("\n", " ")
                p["videos"].append({
                    "id": m.get("id"),
                    "title": cap[:60] or "(bez popisu)",
                    "views": int(m.get("_views", 0) or 0),
                    "likes": int(m.get("like_count", 0) or 0),
                    "comments": int(m.get("comments_count", 0) or 0),
                    "factory": p["name"], "color": p["color"], "platform": "Instagram",
                    "link": m.get("permalink", f"https://www.instagram.com/{uname}"),
                    "published": (m.get("timestamp", "")[:10] if m.get("timestamp") else ""),
                })

    try:
        from zoneinfo import ZoneInfo
        _now = datetime.datetime.now(ZoneInfo("Europe/Bratislava"))
    except Exception:
        _now = datetime.datetime.utcnow() + datetime.timedelta(hours=2)
    gen_at = _now.strftime("%d.%m.%Y %H:%M")

    # --- data.json pre novy dashboard (app.html / server.py) ---
    def _vv(p, plat):
        return sum(v["views"] for v in p["videos"] if (v.get("platform") or "").lower() == plat)
    totals = {
        "factories": len(projects),
        "yt_subs": sum((p["yt"]["subs"] for p in projects if p["yt"]), 0),
        "yt_views": sum(_vv(p, "youtube") for p in projects),
        "tk_foll": sum((p["tiktok"]["followers"] for p in projects if p["tiktok"]), 0),
        "tk_views": sum(_vv(p, "tiktok") for p in projects),
        "tk_likes": sum((p["tiktok"]["likes"] for p in projects if p["tiktok"]), 0),
        "ig_foll": sum((p["instagram"]["followers"] for p in projects if p["instagram"]), 0),
        "ig_views": sum(_vv(p, "instagram") for p in projects),
        "ig_posts": sum((p["instagram"]["media"] for p in projects if p["instagram"]), 0),
        "videos": sum(len(p["videos"]) for p in projects),
    }
    _prev = {}            # predosle totals (z minuleho behu) -> dashboard ukaze zmenu +/-
    _dp0 = os.path.join(ROOT, "data.json")
    if os.path.exists(_dp0):
        try:
            _prev = json.load(open(_dp0, encoding="utf-8")).get("totals", {})
        except Exception:
            _prev = {}

    # IG analytika moze byt blokovana Metou ("API access blocked") -> NEUKAZUJ falosny pokles:
    # podrz posledne zname IG cisla z minuleho behu, oznac ig_blocked pre UI.
    totals["ig_videos"] = sum(1 for p in projects for v in p["videos"]
                              if (v.get("platform") or "").lower() == "instagram")
    totals["ig_blocked"] = not bool(ig)
    if totals["ig_blocked"] and _prev:
        for k in ("ig_foll", "ig_views", "ig_posts"):
            totals[k] = _prev.get(k, 0)
        prev_ig_vids = _prev.get("ig_videos", _prev.get("ig_posts", 0))
        totals["videos"] = totals["videos"] + prev_ig_vids
        totals["ig_videos"] = prev_ig_vids
        print("  [IG] API blokovane Metou -> drzim posledne zname IG cisla (ziadny falosny pokles)")

    for p in projects:    # profilove linky per platforma (pre karty fabrik)
        p["links"] = {
            "youtube": f"https://www.youtube.com/channel/{YT_CHANNELS[p['name']]}" if p["name"] in YT_CHANNELS else None,
            "tiktok": f"https://www.tiktok.com/@{TIKTOK_HANDLE[p['name']]}" if p["name"] in TIKTOK_HANDLE else None,
            "instagram": f"https://www.instagram.com/{IG_HANDLE[p['name']]}" if p["name"] in IG_HANDLE else None,
        }
    json.dump({"projects": projects, "totals": totals, "prev": _prev, "gen_at": gen_at},
              open(os.path.join(ROOT, "data.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    # --- history.json: jeden snapshot za den (pre grafy trendov + delty oproti vceru) ---
    import store
    hpath = os.path.join(ROOT, "history.json")
    hist = store.load_history()                       # cloud: trvale z Gistu
    if hist is None:
        hist = json.load(open(hpath, encoding="utf-8")) if os.path.exists(hpath) else []
    today = datetime.date.today().isoformat()
    fac_snap = {p["name"]: {
        "yf": (p["yt"]["subs"] if p["yt"] else 0), "yv": _vv(p, "youtube"),
        "tf": (p["tiktok"]["followers"] if p["tiktok"] else 0), "tv": _vv(p, "tiktok"),
        "if": (p["instagram"]["followers"] if p["instagram"] else 0), "iv": _vv(p, "instagram"),
    } for p in projects}
    snap = {"date": today, **totals, "fac": fac_snap}
    hist = [h for h in hist if h.get("date") != today] + [snap]   # nahrad dnesny
    hist = hist[-180:]                                            # drz max 180 dni
    json.dump(hist, open(hpath, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    store.save_history(hist)                           # cloud: zapis spat do Gistu

    html = build_html(projects, gen_at, bool(yt_key))
    open(os.path.join(ROOT, "dashboard.html"), "w", encoding="utf-8").write(html)
    print(f"\nHotovo: data.json + history ({len(hist)} dni) + dashboard.html")

def fmt(n):
    if n is None: return "—"
    if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
    if n >= 1_000: return f"{n/1_000:.1f}K"
    return str(n)

def ago(iso):
    if not iso: return "—"
    try:
        dt = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%d.%m %H:%M")
    except Exception:
        return iso[:16]

def _recent(d, days=3):
    try:
        return (datetime.datetime.utcnow() - datetime.datetime.strptime(d, "%Y-%m-%d")).days <= days
    except Exception:
        return False

def render_ranking(projects, platform):
    """Rebríček fabrík + tabuľka najlepších videí pre JEDNU platformu (youtube/tiktok/instagram)."""
    def isp(v): return (v.get("platform") or "").lower() == platform
    vids = sorted([v for p in projects for v in p["videos"] if isp(v)],
                  key=lambda v: v["views"], reverse=True)
    fview = {p["name"]: sum(v["views"] for v in p["videos"] if isp(v)) for p in projects}
    has = {p["name"]: any(isp(v) for v in p["videos"]) for p in projects}
    icon = "📺" if platform == "youtube" else ("🎵" if platform == "tiktok" else "📸")
    if not vids:
        if platform == "youtube":
            return '<div class="setup">📺 <b>YouTube</b> čísla sa objavia po pridaní API kľúča (návod dole).</div>'
        if platform == "tiktok":
            return '<div class="setup">🎵 <b>TikTok</b>: žiadne pripojené videá.</div>'
        return '<div class="setup">📸 <b>Instagram</b>: napojené ✅ — videá so zhliadnutiami sa objavia keď ich príspevky nazbierajú dáta.</div>'
    ranked = sorted([p for p in projects if has[p["name"]]], key=lambda p: fview[p["name"]], reverse=True)
    mx = max((fview[p["name"]] for p in ranked), default=1) or 1
    frows = "".join(
        f'<div class="frow"><span class="fname" style="color:{p["color"]}">{p["name"]}</span>'
        f'<div class="bar"><i style="width:{fview[p["name"]]/mx*100:.0f}%;background:{p["color"]}"></i></div>'
        f'<span class="fval">{fmt(fview[p["name"]])}</span></div>' for p in ranked)
    trows = "".join(
        f'<tr><td class="rk">{i+1}</td>'
        f'<td><a target="_blank" href="{v.get("link","#")}">{escape(v["title"][:60])}</a></td>'
        f'<td><span class="tag" style="background:{v["color"]}26;color:{v["color"]}">{v["factory"]}</span></td>'
        f'<td class="num">{fmt(v["views"])}</td><td class="num">{fmt(v["likes"])}</td><td class="num">{fmt(v["comments"])}</td></tr>'
        for i, v in enumerate(vids[:14]))
    return (f'<div class="rankwrap">'
            f'<div class="panel"><h2>🏆 Rebríček fabrík <small>({icon} views)</small></h2>{frows}</div>'
            f'<div class="panel"><h2>🎬 Najlepšie videá <small>{icon}</small></h2>'
            f'<table class="tv"><thead><tr><th>#</th><th>Video</th><th>Fabrika</th><th>Views</th><th>Likes</th><th>Kom.</th></tr></thead>'
            f'<tbody>{trows}</tbody></table></div></div>')

def build_html(projects, gen_at, has_yt):
    cards = []
    tot_sched = sum(p["scheduled"] for p in projects)
    tot_err = sum(p["errors"] for p in projects)
    def vid_views(p, plat):
        return sum(v["views"] for v in p["videos"] if (v.get("platform") or "").lower() == plat)
    tot_yt_views = sum(vid_views(p, "youtube") for p in projects)  # zo súčtu videí (channel viewCount neráta Shorts)
    tot_subs = sum((p["yt"]["subs"] for p in projects if p["yt"]), 0)
    tot_tk_foll = sum((p["tiktok"]["followers"] for p in projects if p["tiktok"]), 0)
    tot_tk_likes = sum((p["tiktok"]["likes"] for p in projects if p["tiktok"]), 0)
    tot_tk_views = sum(vid_views(p, "tiktok") for p in projects)
    tot_ig_foll = sum((p["instagram"]["followers"] for p in projects if p["instagram"]), 0)
    tot_ig_posts = sum((p["instagram"]["media"] for p in projects if p["instagram"]), 0)
    tot_ig_views = sum(vid_views(p, "instagram") for p in projects)

    rk_youtube = render_ranking(projects, "youtube")
    rk_tiktok = render_ranking(projects, "tiktok")
    rk_instagram = render_ranking(projects, "instagram")

    for p in projects:
        def btn(svc, label, icon):
            if svc == "youtube":
                cid = YT_CHANNELS.get(p["name"]); url = f"https://www.youtube.com/channel/{cid}" if cid else None
            elif svc == "tiktok":
                hh = TIKTOK_HANDLE.get(p["name"]); url = f"https://www.tiktok.com/@{hh}" if hh else None
            elif svc == "instagram":
                ig = IG_HANDLE.get(p["name"]); url = f"https://www.instagram.com/{ig}" if ig else None
            else:
                url = None
            if not url: return ""
            return f'<a class="lnk" target="_blank" href="{url}">{icon} {label}</a>'
        yt = p["yt"]
        yt_block = (f'<div class="stat pf pf-youtube"><span>📺 <b>{fmt(yt["subs"])}</b> odber.</span>'
                    f'<span><b>{fmt(vid_views(p, "youtube"))}</b> zhliadnutí</span>'
                    f'<span><b>{yt["videos"]}</b> videí</span></div>'
                    ) if yt else (f'<div class="stat pf pf-youtube muted">📺 YouTube: '
                                  f'{"pridaj API kľúč (dole)" if not has_yt else "kanál sa nenašiel"}</div>')
        tk = p["tiktok"]
        tk_block = (f'<div class="stat pf pf-tiktok"><span>🎵 <b>{fmt(tk["followers"])}</b> sledov.</span>'
                    f'<span><b>{fmt(tk["likes"])}</b> lajkov</span>'
                    f'<span><b>{tk["videos"]}</b> videí</span></div>'
                    if tk else '<div class="stat pf pf-tiktok muted">🎵 TikTok: nepripojené</div>')
        ig = p["instagram"]
        ig_block = (f'<div class="stat pf pf-instagram"><span>📸 <b>{fmt(ig["followers"])}</b> sledov.</span>'
                    f'<span><b>{fmt(vid_views(p, "instagram"))}</b> zhliadnutí</span>'
                    f'<span><b>{ig["media"]}</b> príspevkov</span></div>'
                    if ig else '<div class="stat pf pf-instagram muted">📸 Instagram: nepripojené</div>')
        # stav z REÁLNYCH dát videí (nezávisle od Buffera): kedy naposledy publikované
        pubs = [v["published"] for v in p["videos"] if v.get("published")]
        last_pub = max(pubs) if pubs else None
        dot = "🟢" if (last_pub and _recent(last_pub)) else "⚪"
        meta = f'{dot} naposledy publikované: {last_pub or "—"}'
        if p.get("online") and not p.get("stale") and p.get("scheduled"):
            meta += f' · v rade {p["scheduled"]}'
        st_html = f'<div class="st"><span class="muted">{meta}</span></div>'
        cards.append(f"""
        <div class="card" style="--c:{p['color']}">
          <div class="hd"><span class="nm">{p['name']}</span><span class="ni">{p['niche']}</span></div>
          {st_html}
          {yt_block}{tk_block}{ig_block}
          <div class="links">{btn('youtube','YouTube','📺')}{btn('tiktok','TikTok','🎵')}{btn('instagram','Instagram','📸')}</div>
        </div>""")

    yt_warn = "" if has_yt else """
      <div class="setup">📺 <b>YouTube reálne čísla:</b> vytvor zadarmo API kľúč
        (console.cloud.google.com → APIs &amp; Services → povoľ <i>YouTube Data API v3</i> → Credentials → API key),
        a vlož ho do súboru <code>settings.json</code> v tomto priečinku ako
        <code>{"youtube_api_key": "TVOJ_KLÚČ"}</code>, potom spusti znova <code>run.bat</code>.</div>"""

    return f"""<!doctype html><html lang="sk"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FacelessFactory — Centrála</title>
<style>
  :root{{color-scheme:dark}}
  *{{box-sizing:border-box}}
  body{{margin:0;background:#0b0f17;color:#e8edf5;font:15px/1.45 'Segoe UI',system-ui,sans-serif;padding:22px}}
  h1{{margin:0 0 2px;font-size:24px}}
  .sub{{color:#8b97a8;font-size:13px;margin-bottom:18px}}
  .summary{{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:20px}}
  .kpi{{background:#131a26;border:1px solid #1f2937;border-radius:12px;padding:12px 18px;min-width:120px}}
  .kpi b{{display:block;font-size:22px}}
  .kpi span{{color:#8b97a8;font-size:12px}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:16px}}
  .card{{background:#131a26;border:1px solid #1f2937;border-left:4px solid var(--c);border-radius:14px;padding:16px}}
  .hd{{display:flex;align-items:baseline;justify-content:space-between;margin-bottom:6px}}
  .nm{{font-size:18px;font-weight:700;color:var(--c)}}
  .ni{{font-size:11px;letter-spacing:1px;color:#8b97a8}}
  .st{{font-size:13px;margin-bottom:3px}}
  .meta{{font-size:12px;color:#8b97a8;margin-bottom:10px}}
  .err{{color:#f87171;font-weight:600}}
  .yt{{display:flex;gap:14px;background:#0e141f;border-radius:10px;padding:9px 12px;font-size:13px;margin-bottom:10px}}
  .yt b{{color:#fff;font-size:15px}} .yt.muted{{color:#6b7280;display:block}}
  .muted{{color:#6b7280}}
  .tk{{margin-bottom:10px}}
  .tkrow{{display:flex;gap:6px}}
  .tk input{{flex:1;background:#0e141f;border:1px solid #273349;color:#e8edf5;border-radius:8px;padding:6px 9px;font-size:13px}}
  .tk button{{background:var(--c);border:0;color:#06121f;font-weight:700;border-radius:8px;padding:0 12px;cursor:pointer}}
  .spark{{width:100%;height:30px;margin-top:6px;display:none}}
  .tkhist{{font-size:11px;margin-top:3px}}
  .links{{display:flex;gap:8px;flex-wrap:wrap}}
  .lnk{{flex:1;text-align:center;background:#0e141f;border:1px solid #273349;color:#cdd7e6;
        text-decoration:none;border-radius:8px;padding:7px 8px;font-size:12px}}
  .lnk:hover{{border-color:var(--c);color:#fff}}
  .setup{{background:#1a2233;border:1px solid #2b3852;border-radius:12px;padding:14px;margin-top:20px;font-size:13px;color:#aeb9c9}}
  code{{background:#0e141f;padding:1px 6px;border-radius:5px;color:#9fd0ff}}
  .rankwrap{{display:grid;grid-template-columns:1fr 1.4fr;gap:16px;margin-bottom:22px}}
  @media(max-width:820px){{.rankwrap{{grid-template-columns:1fr}}}}
  .panel{{background:#131a26;border:1px solid #1f2937;border-radius:14px;padding:16px}}
  .panel h2{{margin:0 0 12px;font-size:16px}} .panel h2 small{{color:#6b7280;font-weight:400;font-size:11px}}
  .frow{{display:flex;align-items:center;gap:10px;margin-bottom:9px}}
  .fname{{width:130px;font-weight:600;font-size:13px}}
  .bar{{flex:1;height:9px;background:#0e141f;border-radius:6px;overflow:hidden}}
  .bar i{{display:block;height:100%;border-radius:6px}}
  .fval{{width:56px;text-align:right;font-size:13px;font-weight:700}}
  .tv{{width:100%;border-collapse:collapse;font-size:12.5px}}
  .tv th{{text-align:left;color:#8b97a8;font-weight:500;padding:4px 6px;border-bottom:1px solid #1f2937}}
  .tv td{{padding:5px 6px;border-bottom:1px solid #161f2e}}
  .tv a{{color:#cdd7e6;text-decoration:none}} .tv a:hover{{color:#fff;text-decoration:underline}}
  .tv .rk{{color:#6b7280;width:18px}} .tv .num{{text-align:right;font-variant-numeric:tabular-nums}}
  .tag{{padding:1px 7px;border-radius:20px;font-size:11px;font-weight:600;white-space:nowrap}}
  .tabs{{display:flex;gap:8px;margin-bottom:18px;flex-wrap:wrap}}
  .tabs button{{background:#131a26;border:1px solid #1f2937;color:#cdd7e6;border-radius:10px;padding:9px 18px;font-size:14px;font-weight:600;cursor:pointer}}
  .tabs button.active{{background:#1d6fe0;border-color:#1d6fe0;color:#fff}}
  .stat{{display:flex;gap:14px;background:#0e141f;border-radius:10px;padding:9px 12px;font-size:13px;margin-bottom:8px}}
  .stat b{{color:#fff;font-size:15px}}
  .stat.muted{{color:#6b7280;display:block}}
  body.view-youtube .pf:not(.pf-youtube){{display:none}}
  body.view-tiktok .pf:not(.pf-tiktok){{display:none}}
  body.view-instagram .pf:not(.pf-instagram){{display:none}}
</style></head><body class="view-youtube">
  <h1>🏭 FacelessFactory — Centrála</h1>
  <div class="sub">{len(projects)} fabrík · obnovené {gen_at} · spusti <code>run.bat</code> pre čerstvé dáta</div>
  <div class="tabs">
    <button data-pf="youtube">📺 YouTube</button>
    <button data-pf="tiktok">🎵 TikTok</button>
    <button data-pf="instagram">📸 Instagram</button>
  </div>
  <div class="summary">
    <div class="kpi"><b>{len(projects)}</b><span>fabrík</span></div>
    <div class="kpi pf pf-youtube"><b>{fmt(tot_subs)}</b><span>YouTube odberateľov</span></div>
    <div class="kpi pf pf-youtube"><b>{fmt(tot_yt_views)}</b><span>YouTube zhliadnutí</span></div>
    <div class="kpi pf pf-tiktok"><b>{fmt(tot_tk_foll)}</b><span>TikTok sledovateľov</span></div>
    <div class="kpi pf pf-tiktok"><b>{fmt(tot_tk_views)}</b><span>TikTok zhliadnutí</span></div>
    <div class="kpi pf pf-tiktok"><b>{fmt(tot_tk_likes)}</b><span>TikTok lajkov</span></div>
    <div class="kpi pf pf-instagram"><b>{fmt(tot_ig_foll)}</b><span>Instagram sledovateľov</span></div>
    <div class="kpi pf pf-instagram"><b>{fmt(tot_ig_views)}</b><span>Instagram zhliadnutí</span></div>
    <div class="kpi pf pf-instagram"><b>{fmt(tot_ig_posts)}</b><span>Instagram príspevkov</span></div>
  </div>
  <div class="pf pf-youtube">{rk_youtube}</div>
  <div class="pf pf-tiktok">{rk_tiktok}</div>
  <div class="pf pf-instagram">{rk_instagram}</div>
  <div class="grid">{''.join(cards)}</div>
  {yt_warn}
<script>
function setView(pf){{
  document.body.className='view-'+pf;
  document.querySelectorAll('.tabs button').forEach(function(b){{b.classList.toggle('active', b.dataset.pf===pf);}});
  try{{localStorage.setItem('ff_view',pf);}}catch(e){{}}
}}
document.querySelectorAll('.tabs button').forEach(function(b){{b.addEventListener('click',function(){{setView(b.dataset.pf);}});}});
var _saved; try{{_saved=localStorage.getItem('ff_view');}}catch(e){{}}
setView(_saved||'youtube');
</script>
</body></html>"""

if __name__ == "__main__":
    main()
