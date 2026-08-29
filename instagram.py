# -*- coding: utf-8 -*-
"""Instagram data fetch pre centralu cez Instagram Graph API (Instagram Login).
Cita ig_tokens.json (dlhodobe tokeny per ucet) -> {username: {"stats":{...}, "media":[...]}}.
Dlhodoby token sam predlzi (ig_refresh_token) ak sa bliz koniec platnosti."""
import json, os, time, urllib.parse, urllib.request, urllib.error

GRAPH = "https://graph.instagram.com"


def _get(path, params):
    url = f"{GRAPH}/{path}?" + urllib.parse.urlencode(params)
    return json.loads(urllib.request.urlopen(urllib.request.Request(url), timeout=30).read().decode())


def _media_views(mid, token):
    """Pocet videni pre reel/video cez insights — tolerantne (0 ak nedostupne)."""
    try:
        ins = _get(f"{mid}/insights", {"metric": "views", "access_token": token})
        for row in ins.get("data", []):
            if "total_value" in row:
                return int(row["total_value"].get("value", 0) or 0)
            vals = row.get("values") or []
            if vals:
                return int(vals[0].get("value", 0) or 0)
    except Exception:
        pass
    return 0


# Predlzenie tokenov je ZAMERNE oddelene od stahovania analytiky.
#
# Preco: 26.8.2026 expirovali vsetky tokeny naraz a Buffer stratil pravo
# publikovat na 9 IG kanaloch. Priciny boli dve a obe su tu opravene:
#
#   1. Obnova bola zabalena vnutri fetch_all(). Ked sa pouzil denny cache
#      alebo ked Meta zablokovala citanie analytiky, obnova sa vobec
#      nespustila — zivotnost tokenu visela na uplne inej veci.
#   2. Chybu obnovy prehltol `except Exception: pass` bez jedineho logu,
#      takze token 60 dni ticho dojazdil k expiracii a nikto sa nedozvedel.
#
# Preto: vola sa samostatne, kazdy vysledok sa loguje a stav sa vracia von,
# aby ho dashboard vedel ukazat.

REFRESH_BEFORE_DAYS = 20  # bolo 10 — pri dennom behu je to malo istoty


def token_status(root):
    """Stav kazdeho tokenu: kolko dni zostava. Necita siet."""
    tpath = os.path.join(root, "ig_tokens.json")
    if not os.path.exists(tpath):
        return {}
    try:
        tokens = json.load(open(tpath, encoding="utf-8"))
    except Exception as e:
        print(f"  [IG] ig_tokens.json sa neda precitat: {e}")
        return {}
    now, out = time.time(), {}
    for uname, t in tokens.items():
        ref, exp_in = t.get("_refreshed_at"), t.get("expires_in")
        if not ref or not exp_in:
            out[uname] = {"days_left": None, "expired": None}
            continue
        days = (ref + exp_in - now) / 86400.0
        out[uname] = {"days_left": round(days, 1), "expired": days <= 0}
    return out


def refresh_tokens(root, force=False):
    """Predlzi tokeny, ktorym zostava menej nez REFRESH_BEFORE_DAYS.

    Vracia {username: "ok"|"skipped"|"expired"|"chyba ..."}. Expirovany token
    UZ NEJDE predlzit — Meta na obnovu vyzaduje este platny token, takze potom
    zostava iba rucne prihlasenie (Buffer: Refresh channel)."""
    tpath = os.path.join(root, "ig_tokens.json")
    if not os.path.exists(tpath):
        return {}
    try:
        tokens = json.load(open(tpath, encoding="utf-8"))
    except Exception as e:
        print(f"  [IG] ig_tokens.json sa neda precitat: {e}")
        return {}

    now, result, changed = time.time(), {}, False
    for uname, t in list(tokens.items()):
        tok = t.get("access_token")
        if not tok:
            result[uname] = "chyba: ziadny access_token"
            continue

        exp_at = (t.get("_refreshed_at") or 0) + (t.get("expires_in") or 0)
        days_left = (exp_at - now) / 86400.0 if t.get("_refreshed_at") else -1

        if days_left <= 0:
            # Uz je neskoro — hlas to nahlas, mlcanie tuto chybu sposobilo.
            result[uname] = "expired"
            print(f"  [IG] !! {uname}: TOKEN EXPIROVAL pred {abs(days_left):.0f} dnami "
                  f"— predlzit sa UZ NEDA, treba rucny reconnect (Buffer + dashboard)")
            continue

        if days_left > REFRESH_BEFORE_DAYS and not force:
            result[uname] = "skipped"
            continue

        try:
            rr = _get("refresh_access_token",
                      {"grant_type": "ig_refresh_token", "access_token": tok})
        except Exception as e:
            # Toto miesto bolo predtym `pass`. Uz nie.
            result[uname] = f"chyba: {e}"
            print(f"  [IG] !! {uname}: obnova ZLYHALA ({e}) — zostava {days_left:.0f} dni")
            continue

        if not rr.get("access_token"):
            result[uname] = f"chyba: odpoved bez tokenu ({rr})"
            print(f"  [IG] !! {uname}: obnova vratila odpoved bez tokenu — zostava {days_left:.0f} dni")
            continue

        t["access_token"] = rr["access_token"]
        t["expires_in"] = rr.get("expires_in", t.get("expires_in"))
        t["_refreshed_at"] = now
        changed = True
        result[uname] = "ok"
        print(f"  [IG] {uname}: token predlzeny o {(rr.get('expires_in') or 0)/86400:.0f} dni")

    if changed:
        try:
            json.dump(tokens, open(tpath, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        except Exception as e:
            print(f"  [IG] !! tokeny sa NEPODARILO ulozit: {e}")

    bad = [u for u, r in result.items() if r not in ("ok", "skipped")]
    if bad:
        print(f"  [IG] !! POZOR: {len(bad)} z {len(result)} uctov ma problem s tokenom: {', '.join(bad)}")
    return result


def fetch_all(root):
    tpath = os.path.join(root, "ig_tokens.json")
    if not os.path.exists(tpath):
        return {}
    tokens = json.load(open(tpath, encoding="utf-8"))
    out = {}
    now = time.time()

    for uname, t in list(tokens.items()):
        tok = t.get("access_token")
        if not tok:
            continue
        # Obnovu tokenu tu uz nerobime — bezi samostatne v refresh_tokens(),
        # aby ju nezhodilo to, ze citanie analytiky prave zlyhava.

        try:
            me = _get("me", {"fields": "username,followers_count,media_count", "access_token": tok})
        except urllib.error.HTTPError as e:
            print(f"  [IG] {uname}: chyba {e.code}"); continue
        except Exception as e:
            print(f"  [IG] {uname}: {e}"); continue

        try:
            ml = _get("me/media", {
                "fields": "id,caption,like_count,comments_count,media_type,media_product_type,permalink,timestamp",
                "limit": "15", "access_token": tok})
            media = ml.get("data", [])
        except Exception:
            media = []

        for m in media:
            is_video = (m.get("media_product_type") in ("REELS", "VIDEO")) or m.get("media_type") == "VIDEO"
            m["_views"] = _media_views(m["id"], tok) if is_video else 0

        out[me.get("username", uname)] = {"stats": me, "media": media}

    # Zamerne tu ig_tokens.json NEZAPISUJEME: subor vlastni refresh_tokens().
    # Dva zapisovatelia = riziko, ze sa cerstvy token prepise starym z pamate.
    return out
