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


PREV_FILE = "prev.json"   # posledne totals (delta "od posledneho obnovenia") - prezije restart cloudu


def load_prev():
    """Totals z PREDOSLEHO behu (alebo None ak vypnute/chyba)."""
    if not enabled():
        return None
    try:
        g = _req("GET")
        c = g.get("files", {}).get(PREV_FILE, {}).get("content", "")
        return json.loads(c or "{}")
    except Exception as e:
        print("[store] load_prev chyba:", e)
        return None


def save_prev(totals):
    if not enabled():
        return
    try:
        body = {"files": {PREV_FILE: {"content": json.dumps(totals, ensure_ascii=False)}}}
        _req("PATCH", json.dumps(body).encode())
    except Exception as e:
        print("[store] save_prev chyba:", e)


DONE_FILE = "done_comments.json"   # ID komentarov oznacenych ako "vybavene" -> prec z dashboardu (prezije restart)
_LOCAL_DONE = os.path.join(os.path.dirname(os.path.abspath(__file__)), DONE_FILE)


def load_done():
    """Mnozina ID vybavenych komentarov. Gist ak je nastaveny, inak lokalny subor."""
    if enabled():
        try:
            g = _req("GET")
            c = g.get("files", {}).get(DONE_FILE, {}).get("content", "")
            return set(json.loads(c or "[]"))
        except Exception as e:
            print("[store] load_done chyba:", e)
            return set()
    try:
        return set(json.load(open(_LOCAL_DONE, encoding="utf-8"))) if os.path.exists(_LOCAL_DONE) else set()
    except Exception:
        return set()


def save_done(ids):
    ids = sorted(set(ids))
    if enabled():
        try:
            body = {"files": {DONE_FILE: {"content": json.dumps(ids, ensure_ascii=False)}}}
            _req("PATCH", json.dumps(body).encode())
            return
        except Exception as e:
            print("[store] save_done chyba:", e)
    try:
        json.dump(ids, open(_LOCAL_DONE, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception as e:
        print("[store] save_done lokal chyba:", e)
