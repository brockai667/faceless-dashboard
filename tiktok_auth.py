# -*- coding: utf-8 -*-
"""
TikTok OAuth — jednorazove prepojenie jedneho uctu.
Pouzitie:
    python tiktok_auth.py mindblowndaily
    ... (raz pre kazdy z 6 uctov; nazov si zvolis lubovolne)

Potrebuje v settings.json:
    {
      "tiktok_client_key": "...",
      "tiktok_client_secret": "...",
      "tiktok_redirect_uri": "https://brockai667.github.io/ff-oauth/"
    }
Skript otvori prehliadac -> prihlas sa do daneho TikTok uctu -> Authorize ->
callback stranka ti ukaze KOD -> skopiruj ho a vlozit sem do terminalu.
Hesla nikdy nezadavam ja — prihlasenie+Authorize robis ty v prehliadaci.
"""
import json, os, sys, secrets, urllib.parse, urllib.request, urllib.error
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))
SCOPES = "user.info.basic,user.info.stats,video.list"
TOKENS = os.path.join(ROOT, "tiktok_tokens.json")

def main():
    if len(sys.argv) < 2:
        print("Pouzitie: python tiktok_auth.py <nazov_uctu>   (napr. mindblowndaily)"); return
    label = sys.argv[1].strip()
    spath = os.path.join(ROOT, "settings.json")
    s = json.load(open(spath, encoding="utf-8")) if os.path.exists(spath) else {}
    ck = s.get("tiktok_client_key"); cs = s.get("tiktok_client_secret")
    redirect = s.get("tiktok_redirect_uri")
    if not ck or not cs or not redirect:
        print("CHYBA: do settings.json daj tiktok_client_key, tiktok_client_secret a tiktok_redirect_uri."); return

    state = secrets.token_urlsafe(16)
    auth_url = "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode({
        "client_key": ck, "scope": SCOPES, "response_type": "code",
        "redirect_uri": redirect, "state": state})

    print(f"\nOtvaram prehliadac. Prihlas sa do uctu '{label}' a klikni Authorize.")
    print("Po Authorize ti callback stranka ukaze KOD — skopiruj ho.\n")
    try:
        webbrowser.open(auth_url)
    except Exception:
        print("Otvor manualne tento odkaz:\n", auth_url, "\n")

    code = input("Vlozit sem KOD z prehliadaca (a Enter): ").strip()
    # ak vlozi cely redirect URL, vytiahnem code z neho
    if code.startswith("http") and "code=" in code:
        code = urllib.parse.parse_qs(urllib.parse.urlparse(code).query).get("code", [""])[0]
    code = urllib.parse.unquote(code)
    if not code:
        print("Nedostal som kod."); return

    body = urllib.parse.urlencode({
        "client_key": ck, "client_secret": cs, "code": code,
        "grant_type": "authorization_code", "redirect_uri": redirect}).encode("utf-8")
    req = urllib.request.Request("https://open.tiktokapis.com/v2/oauth/token/", data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        tok = json.loads(urllib.request.urlopen(req, timeout=30).read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print("Vymena tokenu zlyhala:", e.read().decode("utf-8", "replace")); return
    if "access_token" not in tok:
        print("Vymena tokenu zlyhala:", tok); return

    # zisti realny TikTok handle a uloz pod nim (label je len docasny nazov)
    handle = label
    try:
        ureq = urllib.request.Request(
            "https://open.tiktokapis.com/v2/user/info/?fields=display_name",
            headers={"Authorization": f"Bearer {tok['access_token']}"})
        ui = json.loads(urllib.request.urlopen(ureq, timeout=20).read().decode("utf-8"))
        handle = ui.get("data", {}).get("user", {}).get("display_name") or label
    except Exception:
        pass

    store = json.load(open(TOKENS, encoding="utf-8")) if os.path.exists(TOKENS) else {}
    store[handle] = {
        "access_token": tok["access_token"],
        "refresh_token": tok.get("refresh_token"),
        "open_id": tok.get("open_id"),
        "scope": tok.get("scope"),
    }
    json.dump(store, open(TOKENS, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\nOK - ucet '{handle}' prepojeny a ulozeny.")
    print("Prepojene ucty:", ", ".join(store.keys()))

if __name__ == "__main__":
    main()
