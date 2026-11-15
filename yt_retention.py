# -*- coding: utf-8 -*-
"""Udrzanie divakov po videach (YouTube Analytics API, dimenzia video). Bezi v GitHub Actions hned po
yt_analytics_daily.py. Cita z ENV: YT_CLIENT_ID, YT_CLIENT_SECRET, YT_ANALYTICS_TOKENS (rovnake ako denny tah).
Vysledok zluci do yt_retention.json (verejny subor, citaju ho fabriky pri tyzdennom audite):
  {"generated": ISO, "window_days": N,
   "videos": {"<videoId>": {"ch": kanal, "v": pozretia, "avd": priemerny cas v s, "avp": priemerne % videa, "seen": "YYYY-MM-DD"}}}
Cisla su sucet za okno (poslednych N dni). Analytics meska ~2-3 dni, cerstve video sa preto objavi az neskor.
Video, ktore API uz nevracia, v subore ostava 120 dni od posledneho videnia.
"""
import datetime
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "yt_retention.json")
CID = os.environ.get("YT_CLIENT_ID")
CSEC = os.environ.get("YT_CLIENT_SECRET")
TOKENS = json.loads(os.environ.get("YT_ANALYTICS_TOKENS", "{}"))
WINDOW = int(os.environ.get("YT_RETENTION_DAYS", "45"))
KEEP = 120


def _access_token(rt):
    data = urllib.parse.urlencode({"client_id": CID, "client_secret": CSEC, "refresh_token": rt,
                                   "grant_type": "refresh_token"}).encode()
    r = urllib.request.urlopen(urllib.request.Request("https://oauth2.googleapis.com/token", data=data), timeout=30)
    return json.loads(r.read().decode()).get("access_token")


def _by_video(at, start, end):
    url = "https://youtubeanalytics.googleapis.com/v2/reports?" + urllib.parse.urlencode({
        "ids": "channel==MINE", "startDate": start, "endDate": end,
        "metrics": "views,averageViewDuration,averageViewPercentage",
        "dimensions": "video", "sort": "-views", "maxResults": 200})
    r = urllib.request.urlopen(urllib.request.Request(url, headers={"Authorization": "Bearer " + at}), timeout=40)
    return json.loads(r.read().decode()).get("rows", [])


def main():
    if not (CID and CSEC and TOKENS):
        print("CHYBA: chybaju YT_CLIENT_ID/SECRET/TOKENS v ENV")
        return
    today = datetime.date.today()
    start = (today - datetime.timedelta(days=WINDOW)).isoformat()
    data = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
    vids = data.get("videos", {})
    ok = 0
    for name, meta in TOKENS.items():
        rt = meta.get("refresh_token")
        if not rt:
            continue
        try:
            rows = _by_video(_access_token(rt), start, today.isoformat())
        except urllib.error.HTTPError as e:
            print(f"  [{name}] chyba {e.code}: {e.read().decode()[:160]}")
            continue
        except Exception as e:
            print(f"  [{name}] chyba: {str(e)[:100]}")
            continue
        for vid, views, avd, avp in rows:
            vids[vid] = {"ch": name, "v": int(views), "avd": round(float(avd), 1), "avp": round(float(avp), 1),
                         "seen": today.isoformat()}
        ok += 1
        print(f"  [{name}] {len(rows)} videi")
    limit = (today - datetime.timedelta(days=KEEP)).isoformat()
    vids = {k: v for k, v in vids.items() if v.get("seen", "") >= limit}
    json.dump({"generated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"), "window_days": WINDOW,
               "videos": dict(sorted(vids.items()))}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"HOTOVO: {ok}/{len(TOKENS)} kanalov, {len(vids)} videi.")
    if ok == 0 and TOKENS:
        print("CHYBA: 0 kanalov -> tokeny mozno vyprsali.")
        sys.exit(1)


if __name__ == "__main__":
    main()
