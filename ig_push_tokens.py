# -*- coding: utf-8 -*-
"""Po instagram_auth.py: posle tokeny z ig_tokens.json zasifrovane do Gistu dashboardu (cez prihlasene `gh`).
Cloud si ich vezme pri dalsom starte, Render premennu IG_TOKENS_JSON uz netreba menit. Tokeny sa nevypisuju.
Pouzitie:  python ig_push_tokens.py [priecinok s ig_tokens.json a settings.json]"""
import json, os, subprocess, sys

import store

GIST = "6a469813654be8dec6bca174ba558b6b"     # Gist dashboardu (history.json, prev.json, done_comments.json)
root = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
settings = json.load(open(os.path.join(root, "settings.json"), encoding="utf-8"))
tokens = json.load(open(os.path.join(root, "ig_tokens.json"), encoding="utf-8"))
key = store._ig_key(settings)
if not key:
    sys.exit("CHYBA: v settings.json chyba ig_app_secret")
body = json.dumps({"files": {store.IG_FILE: {"content": store.seal(json.dumps(tokens).encode(), key)}}})
r = subprocess.run(["gh", "api", "--method", "PATCH", f"gists/{GIST}", "--input", "-", "--silent"],
                   input=body.encode(), capture_output=True)
print(f"OK: {len(tokens)} IG uctov v Giste" if r.returncode == 0 else f"CHYBA gh: {r.stderr.decode()[:200]}")
