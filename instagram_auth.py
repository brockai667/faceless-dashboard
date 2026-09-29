# -*- coding: utf-8 -*-
"""
Instagram OAuth (Instagram Login) — jednorazove prepojenie alebo obnovenie jedneho uctu.
Pouzitie:
    python instagram_auth.py
    ... (raz pre kazdy ucet, ktory ma v dashboarde "token neplatny / chyba autorizacia")

Potrebuje v settings.json:
    { "ig_app_id": "...", "ig_app_secret": "...", "ig_redirect_uri": "https://brockai667.github.io/ff-oauth/" }
Ucet musi byt v Meta appke pridany ako Instagram Tester (povodne ucty uz su).

Skript otvori prehliadac -> prihlas sa do daneho Instagram uctu -> Povolit ->
callback stranka ukaze KOD (alebo skopiruj celu adresu) -> vloz do terminalu.
Hesla zadavas len ty v prehliadaci. Tokeny sa ukladaju do ig_tokens.json (kluc = username)
a NIKDY sa nevypisuju. Po skonceni treba obsah ig_tokens.json vlozit do Render premennej
IG_TOKENS_JSON (Render -> Environment), inak cloud bezi dalej so starymi tokenmi.
"""
import json, os, sys, time, secrets, urllib.parse, urllib.request, urllib.error
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))
TOKENS = os.path.join(ROOT, "ig_tokens.json")
SCOPES = "instagram_business_basic,instagram_business_manage_comments,instagram_business_manage_insights"


def _json(req):
    return json.loads(urllib.request.urlopen(req, timeout=30).read().decode("utf-8"))


def _err(e):
    """Text chyby z API bez tokenov (odpoved Mety tokeny neobsahuje, ale pre istotu orez)."""
    try:
        return e.read().decode("utf-8", "replace")[:300]
    except Exception:
        return str(e)[:300]


def main():
    spath = os.path.join(ROOT, "settings.json")
    s = json.load(open(spath, encoding="utf-8")) if os.path.exists(spath) else {}
    app_id, secret, redirect = s.get("ig_app_id"), s.get("ig_app_secret"), s.get("ig_redirect_uri")
    if not app_id or not secret or not redirect:
        print("CHYBA: do settings.json daj ig_app_id, ig_app_secret a ig_redirect_uri."); return

    state = secrets.token_urlsafe(16)
    auth_url = "https://www.instagram.com/oauth/authorize?" + urllib.parse.urlencode({
        "client_id": app_id, "redirect_uri": redirect, "response_type": "code", "scope": SCOPES, "state": state})
    print("\nOtvaram prehliadac. Prihlas sa do Instagram uctu, ktory chces prepojit, a klikni Povolit.")
    print("Po povoleni ti callback stranka ukaze KOD — skopiruj ho (alebo celu adresu stranky).\n")
    try:
        webbrowser.open(auth_url)
    except Exception:
        print("Otvor manualne tento odkaz:\n", auth_url, "\n")

    code = input("Vlozit sem KOD z prehliadaca (a Enter): ").strip()
    if code.startswith("http") and "code=" in code:
        code = urllib.parse.parse_qs(urllib.parse.urlparse(code).query).get("code", [""])[0]
    code = urllib.parse.unquote(code).split("#")[0].strip()      # Instagram pridava na koniec "#_"
    if not code:
        print("Nedostal som kod."); return

    # 1) kod -> kratkodoby token
    body = urllib.parse.urlencode({"client_id": app_id, "client_secret": secret, "grant_type": "authorization_code",
                                   "redirect_uri": redirect, "code": code}).encode("utf-8")
    try:
        r = _json(urllib.request.Request("https://api.instagram.com/oauth/access_token", data=body,
                                         headers={"Content-Type": "application/x-www-form-urlencoded"}))
    except urllib.error.HTTPError as e:
        print("Vymena kodu zlyhala:", _err(e)); return
    if isinstance(r.get("data"), list) and r["data"]:             # novsi tvar odpovede: {"data": [{...}]}
        r = r["data"][0]
    short = r.get("access_token")
    if not short:
        print("Vymena kodu zlyhala: odpoved bez tokenu."); return

    # 2) kratkodoby -> dlhodoby (60 dni)
    try:
        ll = _json(urllib.request.Request("https://graph.instagram.com/access_token?" + urllib.parse.urlencode({
            "grant_type": "ig_exchange_token", "client_secret": secret, "access_token": short})))
    except urllib.error.HTTPError as e:
        print("Vymena za dlhodoby token zlyhala:", _err(e)); return
    token = ll.get("access_token")
    if not token:
        print("Vymena za dlhodoby token zlyhala: odpoved bez tokenu."); return

    # 3) username uctu (kluc v ig_tokens.json)
    try:
        me = _json(urllib.request.Request("https://graph.instagram.com/me?" + urllib.parse.urlencode({
            "fields": "user_id,username", "access_token": token})))
    except urllib.error.HTTPError as e:
        print("Citanie uctu zlyhalo:", _err(e)); return
    uname = me.get("username")
    if not uname:
        print("Citanie uctu zlyhalo: odpoved bez username."); return

    store = json.load(open(TOKENS, encoding="utf-8")) if os.path.exists(TOKENS) else {}
    uid = str(me.get("user_id") or r.get("user_id") or "")
    stale = [k for k, v in store.items() if k != uname and uid and str(v.get("user_id") or "") == uid]
    store[uname] = {"access_token": token, "expires_in": ll.get("expires_in") or 5184000,
                    "_refreshed_at": time.time(), "user_id": uid}
    for k in stale:                                               # ten isty ucet pod starym menom (premenovany)
        store.pop(k, None)
    json.dump(store, open(TOKENS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    days = (store[uname]["expires_in"] or 0) / 86400
    print(f"\nOK - ucet '{uname}' prepojeny, token plati {days:.0f} dni.")
    if stale:
        print("Odstraneny stary zaznam toho isteho uctu:", ", ".join(stale))
    print("Prepojene ucty:", ", ".join(sorted(store.keys())))
    print("\nNEZABUDNI: obsah ig_tokens.json vloz do Render premennej IG_TOKENS_JSON (Environment) a uloz.")


if __name__ == "__main__":
    main()
