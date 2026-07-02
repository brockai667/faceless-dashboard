# -*- coding: utf-8 -*-
"""Denny tah REALNYCH YT cisel cez YouTube Analytics API (per kanal, den po dni).
Bezi v GitHub Actions. Cita z ENV: YT_CLIENT_ID, YT_CLIENT_SECRET, YT_ANALYTICS_TOKENS (json
{"KanalNazov": {"channel_id": "...", "refresh_token": "..."}}). Vysledok zluci do yt_daily.json:
  {"generated": ISO, "days": {"YYYY-MM-DD": {"views": N, "subs": N, "fac": {kanal:{"v":N,"s":N}}}}}
YouTube Analytics finalizuje data s ~3-dnovym oneskorenim -> tahame poslednych ~16 dni a
posledne dni sa doplnia/upresnia pri kazdom behu (× dni v grafe sa tak samy zaplnia).
"""
import os, json, datetime, urllib.parse, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "yt_daily.json")
CID = os.environ.get("YT_CLIENT_ID")
CSEC = os.environ.get("YT_CLIENT_SECRET")
TOKENS = json.loads(os.environ.get("YT_ANALYTICS_TOKENS", "{}"))
DAYS_BACK = int(os.environ.get("YT_DAYS_BACK", "16"))


def _access_token(rt):
    data = urllib.parse.urlencode({
        "client_id": CID, "client_secret": CSEC, "refresh_token": rt,
        "grant_type": "refresh_token"}).encode()
    r = urllib.request.urlopen(urllib.request.Request(
        "https://oauth2.googleapis.com/token", data=data), timeout=30)
    return json.loads(r.read().decode()).get("access_token")


def _daily(at, start, end):
    url = "https://youtubeanalytics.googleapis.com/v2/reports?" + urllib.parse.urlencode({
        "ids": "channel==MINE", "startDate": start, "endDate": end,
        "metrics": "views,subscribersGained,subscribersLost",
        "dimensions": "day", "sort": "day"})
    r = urllib.request.urlopen(urllib.request.Request(
        url, headers={"Authorization": "Bearer " + at}), timeout=40)
    return json.loads(r.read().decode()).get("rows", [])


def main():
    if not (CID and CSEC and TOKENS):
        print("CHYBA: chybaju YT_CLIENT_ID/SECRET/TOKENS v ENV"); return
    today = datetime.date.today()
    start = (today - datetime.timedelta(days=DAYS_BACK)).isoformat()
    end = today.isoformat()
    # nacitaj existujuce (merge) -> stare dni ostanu, nove/upresnene sa prepisu
    data = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {"days": {}}
    days = data.get("days", {})
    ok = 0
    for name, meta in TOKENS.items():
        rt = meta.get("refresh_token")
        if not rt:
            continue
        try:
            at = _access_token(rt)
            rows = _daily(at, start, end)
        except urllib.error.HTTPError as e:
            print(f"  [{name}] chyba {e.code}: {e.read().decode()[:120]}"); continue
        except Exception as e:
            print(f"  [{name}] chyba: {str(e)[:100]}"); continue
        for r in rows:
            d, v, sg, sl = r[0], int(r[1]), int(r[2]), int(r[3])
            day = days.setdefault(d, {"views": 0, "subs": 0, "fac": {}})
            prev = day["fac"].get(name, {"v": 0, "s": 0})
            # odpocitaj stary prispevok kanala a pripocitaj novy (idempotentne pri opakovanom behu)
            day["views"] += v - prev["v"]
            day["subs"] += (sg - sl) - prev["s"]
            day["fac"][name] = {"v": v, "s": sg - sl}
        ok += 1
        print(f"  [{name}] +{len(rows)} dni")
    data["days"] = days
    data["generated"] = datetime.datetime.utcnow().isoformat() + "Z"
    json.dump(data, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    n = len(days)
    last = max(days) if days else "-"
    print(f"HOTOVO: {ok}/{len(TOKENS)} kanalov, {n} dni (posledny realny den: {last}).")


if __name__ == "__main__":
    main()
