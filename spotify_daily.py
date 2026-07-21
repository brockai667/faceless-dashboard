# -*- coding: utf-8 -*-
"""Spotify analytika (Lumora) cez client-credentials (ziadny user login):
artist followers/popularity/genres + top tracky + albumy -> spotify.json
+ denny snapshot do spotify_history.json (trend followerov). Bezi v GitHub Actions.
ENV: SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, SPOTIFY_ARTIST_ID (Lumora artist id).
POZOR: verejne API nedava presne streamy (to je len Spotify for Artists, bez API) -
ukazujeme followers + popularity (0-100) + katalog, co su jedine verejne signaly."""
import base64
import datetime
import json
import os
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
CID = os.environ.get("SPOTIFY_CLIENT_ID")
CSEC = os.environ.get("SPOTIFY_CLIENT_SECRET")
ARTIST = os.environ.get("SPOTIFY_ARTIST_ID", "").strip()
MARKET = os.environ.get("SPOTIFY_MARKET", "US")


def _token():
    auth = base64.b64encode(f"{CID}:{CSEC}".encode()).decode()
    req = urllib.request.Request(
        "https://accounts.spotify.com/api/token",
        data=urllib.parse.urlencode({"grant_type": "client_credentials"}).encode(),
        headers={"Authorization": "Basic " + auth,
                 "Content-Type": "application/x-www-form-urlencoded"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())["access_token"]


def _get(url, tok):
    return json.loads(urllib.request.urlopen(urllib.request.Request(
        url, headers={"Authorization": "Bearer " + tok}), timeout=30).read())


def _write(obj):
    json.dump(obj, open(os.path.join(ROOT, "spotify.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)


def main():
    if not (CID and CSEC):
        _write({"configured": False})
        print("Spotify: chybaju SPOTIFY_CLIENT_ID/SECRET -> tab ukaze 'pripoj Spotify'"); return
    tok = _token()
    aid = ARTIST
    if not aid:
        # zaloha: skus najst Lumora (preferuj New Age/Ambient); presnejsie = zadaj SPOTIFY_ARTIST_ID
        r = _get("https://api.spotify.com/v1/search?q=%s&type=artist&limit=10"
                 % urllib.parse.quote("Lumora"), tok)
        cands = r.get("artists", {}).get("items", [])
        pick = next((a for a in cands if any(("age" in g.lower() or "ambient" in g.lower()
                     or "new age" in g.lower()) for g in a.get("genres", []))), None) \
            or (cands[0] if cands else None)
        if not pick:
            _write({"configured": True, "found": False}); print("Lumora nenajdena"); return
        aid = pick["id"]
        print("Lumora auto-najdena:", pick["name"], aid, "(radsej zadaj SPOTIFY_ARTIST_ID)")

    art = _get("https://api.spotify.com/v1/artists/" + aid, tok)
    top = _get("https://api.spotify.com/v1/artists/%s/top-tracks?market=%s" % (aid, MARKET), tok).get("tracks", [])
    albs = _get("https://api.spotify.com/v1/artists/%s/albums?include_groups=album,single&limit=50&market=%s"
                % (aid, MARKET), tok).get("items", [])

    def img(o, last=True):
        ims = o.get("images") or [{}]
        return (ims[-1] if last else ims[0]).get("url", "")

    out = {
        "configured": True, "found": True,
        "generated": datetime.datetime.utcnow().isoformat() + "Z",
        "artist": {
            "id": aid, "name": art.get("name", "Lumora"),
            "followers": art.get("followers", {}).get("total", 0),
            "popularity": art.get("popularity", 0),
            "genres": art.get("genres", []),
            "image": img(art, last=False),
            "url": art.get("external_urls", {}).get("spotify", ""),
        },
        "top_tracks": [{
            "name": t.get("name", ""), "popularity": t.get("popularity", 0),
            "album": t.get("album", {}).get("name", ""),
            "url": t.get("external_urls", {}).get("spotify", ""),
            "image": img(t.get("album", {})),
        } for t in top],
        "albums": [{
            "name": a.get("name", ""), "type": a.get("album_type", ""),
            "release": a.get("release_date", ""), "tracks": a.get("total_tracks", 0),
            "url": a.get("external_urls", {}).get("spotify", ""),
            "image": img(a),
        } for a in albs],
    }
    _write(out)
    # trend
    hp = os.path.join(ROOT, "spotify_history.json")
    hist = json.load(open(hp, encoding="utf-8")) if os.path.exists(hp) else []
    today = datetime.date.today().isoformat()
    hist = [h for h in hist if h.get("date") != today]
    hist.append({"date": today, "followers": out["artist"]["followers"],
                 "popularity": out["artist"]["popularity"]})
    json.dump(hist[-160:], open(hp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("Spotify OK: %s | %d followers | pop %d | %d top | %d albumov"
          % (out["artist"]["name"], out["artist"]["followers"], out["artist"]["popularity"],
             len(top), len(albs)))


if __name__ == "__main__":
    try:
        main()
    except Exception as _e:
        _write({"configured": True, "found": False, "error": str(_e)[:180]})
        print("Spotify CHYBA:", str(_e)[:180])
