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
URL = os.environ.get("EPISODARY_URL", "").strip().rstrip("/")
SECRET = os.environ.get("EPISODARY_SECRET", "").strip()   # .strip() = odstrani trailing newline z GitHub secretu (castá príčina 401)


def main():
    if not (URL and SECRET):
        json.dump({"configured": False},
                  open(os.path.join(ROOT, "episodary.json"), "w", encoding="utf-8"))
        print("Episodary: chyba EPISODARY_URL/EPISODARY_SECRET -> tab ukaze 'pripoj Episodary'"); return
    try:
        req = urllib.request.Request(URL + "/api/admin/stats",
                                     headers={"Authorization": "Bearer " + SECRET})
        data = json.loads(urllib.request.urlopen(req, timeout=40).read())
    except Exception as e:
        msg = str(e)
        if "401" in msg:
            msg = ("401 Unauthorized - EPISODARY_SECRET nesedi s CRON_SECRET "
                   "(redeployol si Episodary po zmene tajomstva?)")
        elif "404" in msg:
            msg = "404 - endpoint /api/admin/stats nenajdeny (zla EPISODARY_URL?)"
        json.dump({"configured": False, "error": msg[:180]},
                  open(os.path.join(ROOT, "episodary.json"), "w", encoding="utf-8"), ensure_ascii=False)
        print("Episodary CHYBA:", msg[:180]); return
    data["configured"] = True
    json.dump(data, open(os.path.join(ROOT, "episodary.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    # trend: denny snapshot -> graf rastu (users + aktivni + instalacie)
    hp = os.path.join(ROOT, "episodary_history.json")
    hist = json.load(open(hp, encoding="utf-8")) if os.path.exists(hp) else []
    today = datetime.date.today().isoformat()
    hist = [h for h in hist if h.get("date") != today]
    u = data.get("users", {}); ac = data.get("active", {}); pf = data.get("platform", {})
    hist.append({"date": today, "users": u.get("total", 0),
                 "mau": ac.get("mau", 0), "wau": ac.get("wau", 0),
                 "installs": pf.get("installs", 0)})
    json.dump(hist[-200:], open(hp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("Episodary OK: %d userov (+%d/24h, +%d/7d) | aktivni MAU %d / WAU %d / DAU %d | %d instalacii"
          % (u.get("total", 0), u.get("new24h", 0), u.get("new7d", 0),
             ac.get("mau", 0), ac.get("wau", 0), ac.get("dau", 0), pf.get("installs", 0)))


if __name__ == "__main__":
    main()
