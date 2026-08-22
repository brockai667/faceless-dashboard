# -*- coding: utf-8 -*-
"""Nastavi channel-level keywords (brandingSettings.channel.keywords) vsetkym kanalom
cez YouTube Data API channels.update. Novym/malym kanalom to pomaha algoritmu pochopit,
komu obsah ukazovat (tip z virality: New vs Pro YouTuber).
Bezi v GitHub Actions (dashboard). ENV: YT_CLIENT_ID, YT_CLIENT_SECRET,
YT_WRITE_TOKENS (scope youtube.force-ssl, preferovane) + YT_ANALYTICS_TOKENS (fallback,
ak boli re-authnute so scope). Vysledok zapise do channel_keywords_result.json (bez tokenov).
Idempotentne - opakovany beh nastavi tie iste keywords.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "channel_keywords_result.json")
CID = os.environ.get("YT_CLIENT_ID")
CSEC = os.environ.get("YT_CLIENT_SECRET")

# per-nika keywords; viacslovne v uvodzovkach (YouTube limit ~500 znakov celkovo)
KEYWORDS = {
    # --- prerobene fabriky (8/2026): novy styl videi -> nove keywords ---
    # DisciplineDaily -> BrainHeist (denne riddle/logicke hadanky)
    "DisciplineDaily": 'riddles "riddles with answers" "brain teasers" "logic puzzles" "hard riddles" "math riddles" "can you solve it" "puzzle shorts" "iq test" shorts',
    "BrainHeist": 'riddles "riddles with answers" "brain teasers" "logic puzzles" "hard riddles" "math riddles" "can you solve it" "puzzle shorts" "iq test" shorts',
    # Entropy -> EyeHeist (2-kolove vizualne puzzle / eye testy na cas)
    "Entropy": '"eye test" "visual puzzle" "spot the difference" "find the odd one out" "brain teaser" "observation test" "can you spot it" "iq test" shorts',
    "EyeHeist": '"eye test" "visual puzzle" "spot the difference" "find the odd one out" "brain teaser" "observation test" "can you spot it" "iq test" shorts',
    # Lumora -> Money Glitch (deadpan satira o schemach na zbohatnutie)
    "Lumora Music": '"money glitch" "get rich quick" "money hacks" "finance satire" "money memes" "financial loophole" "comedy shorts" "deadpan comedy" shorts',
    "Lumora": '"money glitch" "get rich quick" "money hacks" "finance satire" "money memes" "financial loophole" "comedy shorts" "deadpan comedy" shorts',
    "Money Glitch": '"money glitch" "get rich quick" "money hacks" "finance satire" "money memes" "financial loophole" "comedy shorts" "deadpan comedy" shorts',
    "UnexplainedDaily": '"unexplained mysteries" "unsolved mysteries" paranormal "strange phenomena" "creepy facts" "mystery shorts" "ancient mysteries" "declassified files" shorts',
    "coldcasedaily667": '"true crime" "cold case" "unsolved cases" "true crime shorts" "missing persons" "crime stories" investigation detective shorts',
    "WealthMindset": '"personal finance" "money mindset" "wealth building" investing "financial freedom" "money facts" "passive income" success shorts',
    "VitalityDaily": '"health tips" wellness nutrition "healthy habits" "human body" longevity "fitness facts" "health shorts" shorts',
    "MindBlownDaily": '"amazing facts" "mind blowing facts" "did you know" "interesting facts" "fun facts" trivia "random facts" shorts',
    "HiddenEarth667": '"hidden places" travel "amazing places" geography "natural wonders" "earth facts" exploration "travel shorts" shorts',
    "NextByte": '"tech news" "ai news" technology "artificial intelligence" gadgets "future tech" innovation "tech shorts" shorts',
    "Curio": '"science facts" space astronomy physics "science explained" "how it works" "science explainer" "science shorts" biology shorts',
    "ColdCaseLong": '"true crime documentary" "cold case" "true crime stories" "crime documentary" "unsolved cases" investigation',
}

# brandingSettings.channel: pri update posielame len mutovatelne polia (image/hints su
# deprecated a title sa cez API nemeni) - inak channels.update vie vratit 400
_CHANNEL_FIELDS = ("description", "defaultLanguage", "country",
                   "trackingAnalyticsAccountId", "unsubscribedTrailer")


def _access_token(rt):
    data = urllib.parse.urlencode({"client_id": CID, "client_secret": CSEC,
                                   "refresh_token": rt, "grant_type": "refresh_token"}).encode()
    r = urllib.request.urlopen(urllib.request.Request(
        "https://oauth2.googleapis.com/token", data=data), timeout=30)
    return json.loads(r.read().decode()).get("access_token")


def _api(url, at, body=None, method="GET"):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode() if body is not None else None, method=method,
        headers={"Authorization": "Bearer " + at, "Content-Type": "application/json"})
    r = urllib.request.urlopen(req, timeout=40)
    return json.loads(r.read().decode())


def set_keywords(cid, at, kw):
    """GET brandingSettings -> prepis keywords -> PUT -> vrati (ok, keywords_po_update)."""
    j = _api("https://www.googleapis.com/youtube/v3/channels?part=brandingSettings&id=" + cid, at)
    items = j.get("items", [])
    if not items:
        return False, "kanal nenajdeny (token nepatri kanalu?)"
    cur = (items[0].get("brandingSettings") or {}).get("channel") or {}
    ch = {k: cur[k] for k in _CHANNEL_FIELDS if cur.get(k)}
    ch["keywords"] = kw
    upd = _api("https://www.googleapis.com/youtube/v3/channels?part=brandingSettings", at,
               body={"id": cid, "brandingSettings": {"channel": ch}}, method="PUT")
    got = ((upd.get("brandingSettings") or {}).get("channel") or {}).get("keywords", "")
    return got == kw, got


def main():
    if not (CID and CSEC):
        print("CHYBA: chybaju YT_CLIENT_ID/YT_CLIENT_SECRET"); return
    write_t = json.loads(os.environ.get("YT_WRITE_TOKENS") or "{}")
    ana_t = json.loads(os.environ.get("YT_ANALYTICS_TOKENS") or "{}")
    tokens = {n: dict(m, _src="analytics") for n, m in ana_t.items()}
    tokens.update({n: dict(m, _src="write") for n, m in write_t.items()})
    # ten isty kanal moze byt pod starym aj novym menom (premenovane kanaly:
    # DisciplineDaily->BrainHeist, Entropy->EyeHeist, Lumora->Money Glitch).
    # Nechaj len jeden zaznam per channel_id, write token ma prednost.
    best = {}
    for n, m in tokens.items():
        cid = m.get("channel_id")
        if not cid:
            best[n] = m
            continue
        cur = best.get(cid)
        if cur is None or (cur[1]["_src"] != "write" and m["_src"] == "write"):
            best[cid] = (n, m)
    tokens = {n: m for k, v in best.items() for n, m in ([v] if isinstance(v, tuple) else [(k, v)])}
    if not tokens:
        print("CHYBA: ziadne tokeny v ENV"); return
    result = {}
    for name in sorted(tokens):
        meta = tokens[name]
        kw = KEYWORDS.get(name)
        cid, rt, src = meta.get("channel_id"), meta.get("refresh_token"), meta["_src"]
        if not kw:
            result[name] = {"status": "SKIP: nemam keyword sadu pre tento nazov"}
            print("  [%s] SKIP - nemam keyword sadu (dopln do KEYWORDS)" % name); continue
        if not (cid and rt):
            result[name] = {"status": "SKIP: token bez channel_id/refresh_token"}; continue
        try:
            ok, got = set_keywords(cid, _access_token(rt), kw)
            result[name] = {"status": "OK" if ok else "MISMATCH", "source": src, "keywords": got}
            print("  [%s] %s (token=%s): %s" % (name, "OK" if ok else "MISMATCH", src, str(got)[:70]))
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:300]
            need = "NEEDS-REAUTH (chyba write scope)" if e.code == 403 else ("HTTP %d" % e.code)
            result[name] = {"status": need, "source": src, "detail": body[:160]}
            print("  [%s] %s: %s" % (name, need, body[:120]))
        except Exception as e:
            result[name] = {"status": "ERR", "source": src, "detail": str(e)[:160]}
            print("  [%s] ERR: %s" % (name, str(e)[:120]))
    chybaju = [n for n in KEYWORDS if n not in tokens]
    if chybaju:
        result["_bez_tokenu"] = chybaju
        print("Kanaly s keyword sadou ale BEZ tokenu v secrets: %s" % ", ".join(chybaju))
    json.dump(result, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    oks = sum(1 for v in result.values() if isinstance(v, dict) and v.get("status") == "OK")
    print("HOTOVO: keywords nastavene na %d kanaloch." % oks)


if __name__ == "__main__":
    main()
