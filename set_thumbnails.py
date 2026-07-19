# -*- coding: utf-8 -*-
"""Nastavi custom thumbnaily na nedavne YT Shorts cez YouTube Data API (thumbnails.set).
Bezi v GitHub Actions (dashboard). ENV: YT_CLIENT_ID, YT_CLIENT_SECRET, YT_ANALYTICS_TOKENS
(re-authnute so scope youtube.force-ssl). Thumbnail berie z <repo> 'thumbs' release, kam ho
nahral push_to_buffer (subor <slug>.jpg). Zosuladenie: YT titulok = "<title> #shorts" ->
odstranime hashtagy -> slugify -> <slug>.jpg. Idempotentne cez thumb_done.json.
POZOR: kanal MUSI mat zapnute custom thumbnails (Studio -> Feature eligibility -> overenie
telefonom); inak thumbnails.set vrati 403.
"""
import os, json, re, urllib.parse, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.abspath(__file__))
DONE = os.path.join(ROOT, "thumb_done.json")
CID = os.environ.get("YT_CLIENT_ID")
CSEC = os.environ.get("YT_CLIENT_SECRET")
# samostatny WRITE token secret (scope youtube.force-ssl) - nezasahuje do read-only analytics tokenov;
# fallback na analytics tokeny ak by boli re-authnute so scope.
TOKENS = json.loads(os.environ.get("YT_WRITE_TOKENS") or os.environ.get("YT_ANALYTICS_TOKENS", "{}"))
OWNER = os.environ.get("GH_OWNER", "brockai667")

# kanal (kluc v TOKENS/YT_CHANNELS) -> GitHub repo fabriky (kde su 'thumbs' release).
# Entropy/Lumora zamerne vynechane (iny typ obsahu, bez thumbnailoveho generatora).
CHANNEL_REPO = {
    "Curio": "ScienceFactory",
    "UnexplainedDaily": "UnexplainedDaily",
    "ColdCaseDaily": "coldcasedaily667",
    "WealthMindset": "WealthFactory",
    "DisciplineDaily": "MotivationFactory",
    "VitalityDaily": "HealthFactory",
    "MindBlownDaily": "FacelessFactory",
    "HiddenEarth": "HiddenEarth",
    "NextByte": "HistoryUntold",
}
# volitelne obmedzenie len na niektore kanaly (napr. validacia): ENV ONLY_CHANNELS="Curio"
ONLY = set(x.strip() for x in os.environ.get("ONLY_CHANNELS", "").split(",") if x.strip())


def slugify(t):   # MUSI sediet s pro_engine.slugify vo fabrikach
    return re.sub(r"[^a-z0-9]+", "_", str(t).lower()).strip("_")[:50] or "video"


def title_to_slug(yt_title):
    return slugify(re.sub(r"#\w+", "", str(yt_title)).strip())


def _access_token(rt):
    data = urllib.parse.urlencode({"client_id": CID, "client_secret": CSEC,
                                   "refresh_token": rt, "grant_type": "refresh_token"}).encode()
    r = urllib.request.urlopen(urllib.request.Request(
        "https://oauth2.googleapis.com/token", data=data), timeout=30)
    return json.loads(r.read().decode()).get("access_token")


def _get(url, at):
    r = urllib.request.urlopen(urllib.request.Request(
        url, headers={"Authorization": "Bearer " + at}), timeout=40)
    return json.loads(r.read().decode())


def recent_uploads(channel_id, at, n=15):
    """Poslednych N videi kanala -> [(videoId, title)]."""
    pl = "UU" + channel_id[2:]
    j = _get("https://www.googleapis.com/youtube/v3/playlistItems"
             "?part=contentDetails&maxResults=%d&playlistId=%s" % (n, pl), at)
    ids = [i["contentDetails"]["videoId"] for i in j.get("items", [])]
    if not ids:
        return []
    j2 = _get("https://www.googleapis.com/youtube/v3/videos?part=snippet&id=%s" % ",".join(ids), at)
    return [(it["id"], it.get("snippet", {}).get("title", "")) for it in j2.get("items", [])]


def fetch_thumb(repo, slug):
    url = "https://github.com/%s/%s/releases/download/thumbs/%s.jpg" % (OWNER, repo, slug)
    try:
        b = urllib.request.urlopen(urllib.request.Request(
            url, headers={"User-Agent": "thumb-setter"}), timeout=60).read()
        return b if len(b) > 5000 else None
    except Exception:
        return None


def set_thumbnail(video_id, jpg, at):
    req = urllib.request.Request(
        "https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId=" + video_id,
        data=jpg, method="POST",
        headers={"Authorization": "Bearer " + at, "Content-Type": "image/jpeg"})
    urllib.request.urlopen(req, timeout=90)


def main():
    if not (CID and CSEC and TOKENS):
        print("CHYBA: chybaju YT_CLIENT_ID/SECRET/YT_ANALYTICS_TOKENS v ENV"); return
    done = set(json.load(open(DONE)) if os.path.exists(DONE) else [])
    set_n = forbidden = 0
    for name, meta in TOKENS.items():
        if ONLY and name not in ONLY:
            continue
        repo = CHANNEL_REPO.get(name)
        cid = meta.get("channel_id"); rt = meta.get("refresh_token")
        if not (repo and cid and rt):
            continue
        try:
            at = _access_token(rt)
            vids = recent_uploads(cid, at)
        except Exception as e:
            print("  [%s] chyba nacitania videi: %s" % (name, str(e)[:120])); continue
        for vid, title in vids:
            if vid in done or not title:
                continue
            jpg = fetch_thumb(repo, title_to_slug(title))
            if not jpg:
                continue           # thumbnail este nie je hostnuty (alebo iny slug) -> skus nabuduce
            try:
                set_thumbnail(vid, jpg, at)
                done.add(vid); set_n += 1
                print("  [%s] thumbnail SET: %s" % (name, title[:46]))
            except urllib.error.HTTPError as e:
                body = e.read().decode()[:200]
                if e.code == 403:
                    forbidden += 1
                    print("  [%s] 403 (zapni custom thumbnails na kanali): %s" % (name, body[:120]))
                else:
                    print("  [%s] set zlyhal %d: %s" % (name, e.code, body))
            except Exception as e:
                print("  [%s] set chyba: %s" % (name, str(e)[:100]))
    json.dump(sorted(done), open(DONE, "w"), ensure_ascii=False, indent=0)
    print("HOTOVO: nastavenych %d thumbnailov (%d× 403 = nezapnute custom thumbnails)." % (set_n, forbidden))


if __name__ == "__main__":
    main()
