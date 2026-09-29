# -*- coding: utf-8 -*-
"""Data-layer tests for instagram.py: token loading, auto-refresh, and the
aggregation of profile + media + view-count insights into fetch_all()'s output."""
import json
import urllib.error

import pytest

import instagram
from conftest import make_response


def _write_tokens(tmp_root, tokens):
    (tmp_root / "ig_tokens.json").write_text(json.dumps(tokens), encoding="utf-8")


def test_fetch_all_missing_token_file_returns_empty(tmp_root):
    assert instagram.fetch_all(str(tmp_root)) == {}


def test_fetch_all_skips_accounts_without_access_token(tmp_root, monkeypatch):
    _write_tokens(tmp_root, {"acct": {}})
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("should not call network")))
    assert instagram.fetch_all(str(tmp_root)) == {}


def test_fetch_all_happy_path_aggregates_media_and_views(tmp_root, monkeypatch):
    _write_tokens(tmp_root, {"acct": {
        "access_token": "tok", "_refreshed_at": 9_999_999_999, "expires_in": 5_184_000,
    }})

    responses = {
        "me?": {"username": "realname", "followers_count": 1000, "media_count": 5},
    }

    def fake_urlopen(req, timeout=30):
        url = req.full_url if hasattr(req, "full_url") else req
        if "me/media" in url:
            return make_response({"data": [
                {"id": "m1", "media_type": "VIDEO", "media_product_type": "REELS",
                 "caption": "hi", "like_count": 3, "comments_count": 1,
                 "permalink": "https://instagram.com/p/m1", "timestamp": "2026-01-01T00:00:00Z"},
                {"id": "m2", "media_type": "IMAGE", "media_product_type": "IMAGE",
                 "caption": "photo", "like_count": 2, "comments_count": 0,
                 "permalink": "https://instagram.com/p/m2", "timestamp": "2026-01-02T00:00:00Z"},
            ]})
        if "insights" in url:
            return make_response({"data": [{"total_value": {"value": 42}}]})
        if url.rstrip("?").endswith("/me") or "/me?" in url:
            return make_response(responses["me?"])
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    out = instagram.fetch_all(str(tmp_root))

    assert "realname" in out
    stats = out["realname"]["stats"]
    assert stats["followers_count"] == 1000
    media = out["realname"]["media"]
    assert len(media) == 2
    video = next(m for m in media if m["id"] == "m1")
    assert video["_views"] == 42
    photo = next(m for m in media if m["id"] == "m2")
    assert photo["_views"] == 0  # non-video media never queries insights


def test_media_views_returns_zero_on_api_error(monkeypatch):
    def _boom(*a, **k):
        raise urllib.error.HTTPError("url", 400, "bad request", {}, None)
    monkeypatch.setattr("urllib.request.urlopen", _boom)
    assert instagram._media_views("m1", "tok") == 0


def test_media_views_handles_values_list_shape(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen",
                         lambda *a, **k: make_response({"data": [{"values": [{"value": 7}]}]}))
    assert instagram._media_views("m1", "tok") == 7


def test_fetch_all_me_http_error_skips_account_gracefully(tmp_root, monkeypatch):
    """If the IG API rejects the token (e.g. expired/blocked), fetch_all must not
    raise — it should skip that account and return whatever else succeeded."""
    _write_tokens(tmp_root, {"acct": {
        "access_token": "tok", "_refreshed_at": 9_999_999_999, "expires_in": 5_184_000,
    }})

    def fake_urlopen(req, timeout=30):
        raise urllib.error.HTTPError("url", 400, "Unusual activity", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    out = instagram.fetch_all(str(tmp_root))
    assert out == {}


def test_fetch_all_media_fetch_failure_still_returns_stats(tmp_root, monkeypatch):
    """If me/media fails after me succeeded, the account should still show up
    with stats and an empty media list rather than being dropped entirely."""
    _write_tokens(tmp_root, {"acct": {
        "access_token": "tok", "_refreshed_at": 9_999_999_999, "expires_in": 5_184_000,
    }})

    def fake_urlopen(req, timeout=30):
        url = req.full_url if hasattr(req, "full_url") else req
        if "me/media" in url:
            raise urllib.error.URLError("network blip")
        return make_response({"username": "realname", "followers_count": 10, "media_count": 0})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    out = instagram.fetch_all(str(tmp_root))
    assert out["realname"]["media"] == []
    assert out["realname"]["stats"]["followers_count"] == 10


def test_refresh_tokens_refreshes_token_near_expiry(tmp_root, monkeypatch):
    """Obnova tokenov je od commitu 620d797 v refresh_tokens() (nie vo fetch_all); token s 5 dnami do konca sa predlzi."""
    import time
    tokens = {"acct": {"access_token": "old", "_refreshed_at": time.time() - 55 * 86400, "expires_in": 60 * 86400}}
    _write_tokens(tmp_root, tokens)

    def fake_urlopen(req, timeout=30):
        url = req.full_url if hasattr(req, "full_url") else req
        if "refresh_access_token" in url:
            return make_response({"access_token": "new", "expires_in": 5_184_000})
        if "me/media" in url:
            return make_response({"data": []})
        return make_response({"username": "realname", "followers_count": 1, "media_count": 0})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    assert instagram.refresh_tokens(str(tmp_root)) == {"acct": "ok"}

    saved = json.loads((tmp_root / "ig_tokens.json").read_text(encoding="utf-8"))
    assert saved["acct"]["access_token"] == "new"


def test_fetch_all_requests_50_media_per_account(tmp_root, monkeypatch):
    """Zoznam prispevkov (z neho sa pocita Part-2 sucet) uz nie je orezany na 15 — limit je 50."""
    assert instagram.MEDIA_LIMIT == 50
    _write_tokens(tmp_root, {"acct": {
        "access_token": "tok", "_refreshed_at": 9_999_999_999, "expires_in": 5_184_000,
    }})
    seen = []

    def fake_urlopen(req, timeout=30):
        url = req.full_url if hasattr(req, "full_url") else req
        seen.append(url)
        if "me/media" in url:
            return make_response({"data": []})
        return make_response({"username": "realname", "followers_count": 1, "media_count": 0})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    instagram.fetch_all(str(tmp_root))
    media_urls = [u for u in seen if "/me/media?" in u]
    assert len(media_urls) == 1 and "limit=50" in media_urls[0]


def test_fetch_all_insights_only_for_newest_and_since(tmp_path, monkeypatch):
    """Zhliadnutia (insights) sa citaju len pre najnovsich 15 videi + videa od 'since' (Part 2)."""
    import json
    import instagram
    (tmp_path / "ig_tokens.json").write_text(
        json.dumps({"acc": {"access_token": "t", "expires_in": 5184000, "_refreshed_at": 1}}), encoding="utf-8")
    media = [{"id": f"m{i}", "media_type": "VIDEO", "media_product_type": "REELS",
              "timestamp": "2026-09-29T10:00:00+0000" if i in (2, 20, 30) else "2026-09-01T10:00:00+0000"}
             for i in range(40)]

    def fake_get(path, params):
        if path == "me":
            return {"username": "acc", "followers_count": 1, "media_count": 40}
        if path == "me/media":
            return {"data": [dict(m) for m in media]}
        raise AssertionError(path)

    calls = []
    monkeypatch.setattr(instagram, "_get", fake_get)
    monkeypatch.setattr(instagram, "_media_views", lambda mid, tok: (calls.append(mid), 7)[1])
    out = instagram.fetch_all(str(tmp_path), since="2026-09-28")
    got = {m["id"]: m["_views"] for m in out["acc"]["media"]}
    assert sorted(calls) == sorted([f"m{i}" for i in range(15)] + ["m20", "m30"])
    assert got["m20"] == 7 and got["m30"] == 7 and got["m16"] == 0
    calls.clear()
    instagram.fetch_all(str(tmp_path))                     # bez since = len najnovsich 15
    assert len(calls) == 15

