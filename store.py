# -*- coding: utf-8 -*-
"""Trvale ulozisko historie cez GitHub Gist (zadarmo, prezije restart cloudu).
Aktivne len ak su nastavene ENV: GH_TOKEN (PAT so scope 'gist') + GIST_ID.
Lokalne (bez ENV) je no-op -> pouzije sa lokalny history.json subor."""
import base64, hashlib, hmac, json, os, urllib.request, urllib.error

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


# --- IG tokeny: Render (free) ma docasny disk, po restarte zabudol predlzene tokeny a bral stare z ENV
# IG_TOKENS_JSON -> 27.10.2026 vsetky expirovali. Predlzene tokeny preto drzime v Giste, zasifrovane
# klucom z ig_app_secret (Gist je len "secret", nie sukromny).
IG_FILE = "ig_tokens.sealed"


def _ig_key(settings):
    sec = (settings or {}).get("ig_app_secret") or ""
    return hashlib.sha256(("ff-ig-tokens:" + sec).encode()).digest() if sec else None


def _stream(key, nonce, n):
    out, i = b"", 0
    while len(out) < n:
        out += hmac.new(key, nonce + i.to_bytes(8, "big"), hashlib.sha256).digest()
        i += 1
    return out[:n]


def seal(data, key):
    nonce = os.urandom(16)
    ct = bytes(a ^ b for a, b in zip(data, _stream(key, nonce, len(data))))
    tag = hmac.new(key, b"tag" + nonce + ct, hashlib.sha256).digest()
    return base64.b64encode(nonce + tag + ct).decode()


def unseal(s, key):
    raw = base64.b64decode(s)
    nonce, tag, ct = raw[:16], raw[16:48], raw[48:]
    if not hmac.compare_digest(tag, hmac.new(key, b"tag" + nonce + ct, hashlib.sha256).digest()):
        return None
    return bytes(a ^ b for a, b in zip(ct, _stream(key, nonce, len(ct))))


def load_ig_tokens(settings):
    """{username: token} z Gistu (alebo {} ak vypnute/chyba/iny kluc)."""
    key = _ig_key(settings)
    if not (enabled() and key):
        return {}
    try:
        c = _req("GET").get("files", {}).get(IG_FILE, {}).get("content", "")
        raw = unseal(c, key) if c else None
        return json.loads(raw.decode()) if raw else {}
    except Exception as e:
        print("[store] load_ig_tokens chyba:", type(e).__name__)
        return {}


def save_ig_tokens(tokens, settings):
    key = _ig_key(settings)
    if not (enabled() and key):
        return
    try:
        body = {"files": {IG_FILE: {"content": seal(json.dumps(tokens).encode(), key)}}}
        _req("PATCH", json.dumps(body).encode())
    except Exception as e:
        print("[store] save_ig_tokens chyba:", type(e).__name__)


def merge_ig_tokens(local, stored):
    """pre kazdy ucet novsi token (podla _refreshed_at); vrati (zlucene, zmenilo_sa)"""
    out, changed = dict(local), False
    for u, t in (stored or {}).items():
        if (t.get("_refreshed_at") or 0) > ((out.get(u) or {}).get("_refreshed_at") or 0):
            out[u], changed = t, True
    return out, changed
