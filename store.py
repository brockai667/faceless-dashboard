# -*- coding: utf-8 -*-
"""Trvale ulozisko historie cez GitHub Gist (zadarmo, prezije restart cloudu).
Aktivne len ak su nastavene ENV: GH_TOKEN (PAT so scope 'gist') + GIST_ID.
Lokalne (bez ENV) je no-op -> pouzije sa lokalny history.json subor."""
import json, os, urllib.request, urllib.error

TOKEN = os.environ.get("GH_TOKEN")
GIST = os.environ.get("GIST_ID")
FILE = "history.json"


def enabled():
    return bool(TOKEN and GIST)


def _req(method, data=None):
    req = urllib.request.Request(
        f"https://api.github.com/gists/{GIST}", data=data, method=method,
        headers={"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json",
                 "User-Agent": "ff-dashboard"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read().decode())


def load_history():
    """Vrati zoznam snapshotov z Gistu (alebo None ak vypnute/chyba)."""
    if not enabled():
        return None
    try:
        g = _req("GET")
        c = g.get("files", {}).get(FILE, {}).get("content", "")
        return json.loads(c or "[]")
    except Exception as e:
        print("[store] load chyba:", e)
        return None


def save_history(hist):
    if not enabled():
        return
    try:
        body = {"files": {FILE: {"content": json.dumps(hist, ensure_ascii=False, indent=2)}}}
        _req("PATCH", json.dumps(body).encode())
    except Exception as e:
        print("[store] save chyba:", e)
