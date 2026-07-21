# -*- coding: utf-8 -*-
"""Episodary analytika: zavola /api/admin/stats (Bearer CRON_SECRET, uz EXISTUJE v Episodary)
-> episodary.json + denny snapshot do episodary_history.json (trend rastu userov/aktivity).
Bezi v GitHub Actions. ENV: EPISODARY_URL (napr. https://episodary.vercel.app), EPISODARY_SECRET
(= CRON_SECRET z Episodary Vercel env). Endpoint vracia LEN agregaty (ziadne PII)."""
import datetime
import json
import os
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
URL = os.environ.get("EPISODARY_URL", "").rstrip("/")
SECRET = os.environ.get("EPISODARY_SECRET", "")


def main():
    if not (URL and SECRET):
        json.dump({"configured": False},
                  open(os.path.join(ROOT, "episodary.json"), "w", encoding="utf-8"))
        print("Episodary: chyba EPISODARY_URL/EPISODARY_SECRET -> tab ukaze 'pripoj Episodary'"); return
    req = urllib.request.Request(URL + "/api/admin/stats",
                                 headers={"Authorization": "Bearer " + SECRET})
    data = json.loads(urllib.request.urlopen(req, timeout=40).read())
    data["configured"] = True
    json.dump(data, open(os.path.join(ROOT, "episodary.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    # trend: denny snapshot -> graf rastu
    hp = os.path.join(ROOT, "episodary_history.json")
    hist = json.load(open(hp, encoding="utf-8")) if os.path.exists(hp) else []
    today = datetime.date.today().isoformat()
    hist = [h for h in hist if h.get("date") != today]
    u = data.get("users", {}); act = data.get("activity", {})
    hist.append({"date": today, "users": u.get("total", 0),
                 "library": act.get("libraryItems", 0),
                 "watched": act.get("watchedEpisodes", 0),
                 "imports": data.get("imports", {}).get("total", 0)})
    json.dump(hist[-200:], open(hp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("Episodary OK: %d userov (+%d/24h, +%d/7d), %d kniznica, %d epizod"
          % (u.get("total", 0), u.get("last24h", 0), u.get("last7d", 0),
             act.get("libraryItems", 0), act.get("watchedEpisodes", 0)))


if __name__ == "__main__":
    main()
