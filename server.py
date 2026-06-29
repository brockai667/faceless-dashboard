# -*- coding: utf-8 -*-
"""Lokalny dashboard server (len Python stdlib, ziadne instalacie).
Spusti:  python server.py   -> otvori http://localhost:8765
- servuje app.html + data.json + history.json
- /api/refresh        -> znova zozbiera data (spusti generate.py)
- /api/comments?user= -> IG prispevky + komentare daneho uctu
- POST /api/reply      -> odpovie na IG komentar
- POST /api/hide       -> skryje/odkryje IG komentar
Pozn.: Instagram API NEumoznuje 'lajkovat' komentare (nie je endpoint) — len odpoved/skryt/zmazat.
"""
import base64, json, os, socket, subprocess, sys, threading, time
import urllib.parse, urllib.request, urllib.error, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80)); ip = s.getsockname()[0]; s.close()
        return ip
    except Exception:
        return "127.0.0.1"

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("PORT", "8765"))          # cloud host nastavi PORT
GRAPH = "https://graph.instagram.com"
DASH_PASS = os.environ.get("DASH_PASS", "")          # ak je nastavene -> vyzaduje heslo (cloud)
CLOUD = bool(os.environ.get("PORT"))                 # bezime v cloude?


def bootstrap_secrets():
    """V cloude prides tajomstva ako ENV premenne (JSON) — tu ich zapiseme do suborov,
    aby zvysok kodu (generate.py / instagram.py / tiktok.py) fungoval bez zmeny."""
    for env_key, fname in [("SETTINGS_JSON", "settings.json"),
                           ("IG_TOKENS_JSON", "ig_tokens.json"),
                           ("TIKTOK_TOKENS_JSON", "tiktok_tokens.json")]:
        val = os.environ.get(env_key)
        if val:
            try:
                json.loads(val)   # over ze je to platny JSON
                open(os.path.join(ROOT, fname), "w", encoding="utf-8").write(val)
            except Exception as e:
                print(f"[bootstrap] {env_key} nie je platny JSON: {e}")


def run_generate():
    try:
        subprocess.run([sys.executable, os.path.join(ROOT, "generate.py")],
                       cwd=ROOT, timeout=240, capture_output=True)
    except Exception as e:
        print("[refresh] chyba:", e)


def auto_refresh_loop():
    """V cloude nemame run.bat — obnovuj data automaticky kazdych N hodin."""
    hrs = float(os.environ.get("REFRESH_HOURS", "3"))
    if not os.path.exists(os.path.join(ROOT, "data.json")):
        run_generate()
    while True:
        time.sleep(hrs * 3600)
        run_generate()


def ig_tokens():
    p = os.path.join(ROOT, "ig_tokens.json")
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}


def ig_get(path, params):
    url = f"{GRAPH}/{path}?" + urllib.parse.urlencode(params)
    return json.loads(urllib.request.urlopen(urllib.request.Request(url), timeout=30).read().decode())


def ig_post(path, params):
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(f"{GRAPH}/{path}", data=data, method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=30).read().decode())


def fetch_comments(user):
    """Vrati poslednych ~8 prispevkov s komentarmi pre dany IG ucet."""
    toks = ig_tokens()
    t = toks.get(user)
    if not t or not t.get("access_token"):
        return {"error": f"ucet '{user}' nema token"}
    tok = t["access_token"]
    media = ig_get("me/media", {
        "fields": "id,caption,permalink,media_type,comments_count,timestamp",
        "limit": "8", "access_token": tok}).get("data", [])
    out = []
    for m in media:
        comments = []
        if int(m.get("comments_count", 0) or 0) > 0:
            try:
                cs = ig_get(f"{m['id']}/comments", {
                    "fields": "id,text,username,timestamp,like_count,replies{id,text,username}",
                    "access_token": tok}).get("data", [])
                comments = cs
            except Exception:
                comments = []
        out.append({
            "id": m["id"], "caption": (m.get("caption") or "")[:120],
            "permalink": m.get("permalink"), "type": m.get("media_type"),
            "comments_count": m.get("comments_count", 0), "comments": comments,
        })
    return {"user": user, "media": out}


def _settings():
    p = os.path.join(ROOT, "settings.json")
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}


def fetch_youtube_comments():
    """Komentare z YouTube videi (read-only, cez ten isty API kluc co generate.py).
    Cita video ID + pocty komentarov z data.json (uz vygenerovane)."""
    key = _settings().get("youtube_api_key") or os.environ.get("YOUTUBE_API_KEY", "")
    dp = os.path.join(ROOT, "data.json")
    if not key or not os.path.exists(dp):
        return []
    try:
        data = json.load(open(dp, encoding="utf-8"))
    except Exception:
        return []
    out = []
    for p in data.get("projects", []):
        for v in p.get("videos", []):
            if (v.get("platform") or "").lower() != "youtube":
                continue
            if int(v.get("comments", 0) or 0) <= 0:
                continue
            try:
                url = ("https://www.googleapis.com/youtube/v3/commentThreads?part=snippet"
                       "&maxResults=30&order=time&textFormat=plainText&videoId=%s&key=%s"
                       % (urllib.parse.quote(str(v.get("id"))), key))
                items = json.loads(urllib.request.urlopen(url, timeout=30).read().decode()).get("items", [])
            except Exception:
                continue
            comments = []
            for c in items:
                sn = c.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
                comments.append({"id": c.get("id"), "text": sn.get("textDisplay", ""),
                                 "username": sn.get("authorDisplayName", ""),
                                 "timestamp": sn.get("publishedAt", ""),
                                 "like_count": sn.get("likeCount", 0)})
            if comments:
                out.append({"id": v.get("id"), "caption": (v.get("title") or "")[:120],
                            "permalink": v.get("link"), "type": "youtube",
                            "comments_count": v.get("comments", 0), "comments": comments,
                            "user": p.get("name"), "platform": "youtube"})
    return out


def fetch_all_comments():
    """Komentare zo VSETKYCH uctov naraz — Instagram (odpoved/skrytie) + YouTube (read-only)."""
    out = []
    for user in ig_tokens().keys():
        try:
            r = fetch_comments(user)
        except Exception:
            continue
        for m in r.get("media", []):
            if m.get("comments"):
                m["user"] = user
                m["platform"] = "instagram"
                out.append(m)
    try:
        out.extend(fetch_youtube_comments())   # + YouTube komentare (napr. Entropy)
    except Exception:
        pass
    return {"media": out}


def reply_comment(user, comment_id, message):
    toks = ig_tokens()
    t = toks.get(user)
    if not t:
        return {"error": "neznamy ucet"}
    try:
        r = ig_post(f"{comment_id}/replies", {"message": message, "access_token": t["access_token"]})
        return {"ok": True, "id": r.get("id")}
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode()[:300]}
    except Exception as e:
        return {"error": str(e)}


def hide_comment(user, comment_id, hide=True):
    toks = ig_tokens()
    t = toks.get(user)
    if not t:
        return {"error": "neznamy ucet"}
    try:
        ig_post(f"{comment_id}", {"hide": "true" if hide else "false", "access_token": t["access_token"]})
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)}


class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        b = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _file(self, name, ctype):
        p = os.path.join(ROOT, name)
        if not os.path.exists(p):
            return self._send(404, json.dumps({"error": "not found"}))
        self._send(200, open(p, "rb").read(), ctype)

    def log_message(self, *a):
        pass  # ticho

    def _auth(self):
        """HTTP Basic heslo — aktivne len ak je nastavene DASH_PASS (cloud). Lokalne vypnute."""
        if not DASH_PASS:
            return True
        h = self.headers.get("Authorization", "")
        if h.startswith("Basic "):
            try:
                _, pw = base64.b64decode(h[6:]).decode().split(":", 1)
                if pw == DASH_PASS:
                    return True
            except Exception:
                pass
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="FacelessFactory"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def do_GET(self):
        if not self._auth():
            return
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path in ("/", "/index.html", "/app.html"):
            return self._file("app.html", "text/html; charset=utf-8")
        if u.path == "/data.json":
            return self._file("data.json", "application/json; charset=utf-8")
        if u.path == "/history.json":
            if not os.path.exists(os.path.join(ROOT, "history.json")):
                return self._send(200, "[]")
            return self._file("history.json", "application/json; charset=utf-8")
        if u.path == "/api/refresh":
            try:
                subprocess.run([sys.executable, os.path.join(ROOT, "generate.py")],
                               cwd=ROOT, timeout=180, capture_output=True)
                return self._send(200, json.dumps({"ok": True}))
            except Exception as e:
                return self._send(200, json.dumps({"error": str(e)}))
        if u.path == "/api/comments":
            user = (q.get("user") or [""])[0]
            return self._send(200, json.dumps(fetch_comments(user), ensure_ascii=False))
        if u.path == "/api/all_comments":
            return self._send(200, json.dumps(fetch_all_comments(), ensure_ascii=False))
        return self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        if not self._auth():
            return
        ln = int(self.headers.get("Content-Length", 0) or 0)
        body = json.loads(self.rfile.read(ln).decode() or "{}") if ln else {}
        u = urllib.parse.urlparse(self.path)
        if u.path == "/api/reply":
            return self._send(200, json.dumps(reply_comment(
                body.get("user"), body.get("comment_id"), body.get("message", "")), ensure_ascii=False))
        if u.path == "/api/hide":
            return self._send(200, json.dumps(hide_comment(
                body.get("user"), body.get("comment_id"), body.get("hide", True)), ensure_ascii=False))
        return self._send(404, json.dumps({"error": "not found"}))


if __name__ == "__main__":
    bootstrap_secrets()                 # cloud: ENV tajomstva -> subory
    if CLOUD:
        print(f"Cloud dashboard na porte {PORT} (heslo {'ANO' if DASH_PASS else 'NIE — nastav DASH_PASS!'})")
        threading.Thread(target=auto_refresh_loop, daemon=True).start()
    else:
        ip = lan_ip()
        print("=" * 52)
        print("  Dashboard bezi:")
        print(f"   - tu na PC:   http://localhost:{PORT}")
        print(f"   - na mobile:  http://{ip}:{PORT}   (rovnaka WiFi)")
        print("  (Ctrl+C pre ukoncenie)")
        print("=" * 52)
        try:
            webbrowser.open(f"http://localhost:{PORT}")
        except Exception:
            pass
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
