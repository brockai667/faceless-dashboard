# -*- coding: utf-8 -*-
"""Data-layer tests for tiktok.py: token loading, 401/403 auto-refresh flow,
and aggregation of user info + video list into fetch_all()'s output."""
import calendar
import json
import urllib.error

import pytest

import tiktok
from conftest import make_response


def _write(tmp_root, name, payload):
    (tmp_root / name).write_text(json.dumps(payload), encoding="utf-8")


def test_fetch_all_missing_token_file_returns_empty(tmp_root):
    assert tiktok.fetch_all(str(tmp_root)) == {}


def test_fetch_all_skips_accounts_without_access_token(tmp_root):
    _write(tmp_root, "tiktok_tokens.json", {"label": {}})
    assert tiktok.fetch_all(str(tmp_root)) == {}


def test_fetch_all_happy_path(tmp_root, monkeypatch):
    _write(tmp_root, "tiktok_tokens.json", {"label": {"access_token": "tok", "refresh_token": "rt"}})

    def fake_api(url, token, method="GET", body=None):
        if "user/info" in url:
            return {"data": {"user": {"display_name": "RealName", "follower_count": 100,
                                       "likes_count": 200, "video_count": 3}}}
        if "video/list" in url:
            return {"data": {"videos": [
                {"id": "v1", "title": "Hello", "view_count": 10, "like_count": 2,
                 "comment_count": 1, "share_count": 0, "create_time": 1_700_000_000},
            ]}}
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(tiktok, "_api", fake_api)
    out = tiktok.fetch_all(str(tmp_root))
    assert "RealName" in out
    assert out["RealName"]["stats"]["follower_count"] == 100
    assert len(out["RealName"]["videos"]) == 1


def test_fetch_all_401_triggers_refresh_and_retries(tmp_root, monkeypatch):
    _write(tmp_root, "tiktok_tokens.json", {"label": {"access_token": "expired", "refresh_token": "rt"}})
    _write(tmp_root, "settings.json", {"tiktok_client_key": "ck", "tiktok_client_secret": "cs"})

    calls = {"user_info": 0}

    def fake_api(url, token, method="GET", body=None):
        if "user/info" in url:
            calls["user_info"] += 1
            if calls["user_info"] == 1:
                raise urllib.error.HTTPError(url, 401, "expired", {}, None)
            assert token == "new-token"
            return {"data": {"user": {"display_name": "RealName", "follower_count": 5,
                                       "likes_count": 0, "video_count": 0}}}
        if "video/list" in url:
            return {"data": {"videos": []}}
        raise AssertionError(f"unexpected url: {url}")

    def fake_refresh(ck, cs, refresh_token):
        assert (ck, cs, refresh_token) == ("ck", "cs", "rt")
        return {"access_token": "new-token", "refresh_token": "new-refresh"}

    monkeypatch.setattr(tiktok, "_api", fake_api)
    monkeypatch.setattr(tiktok, "_refresh", fake_refresh)
    out = tiktok.fetch_all(str(tmp_root))

    assert out["RealName"]["stats"]["follower_count"] == 5
    saved = json.loads((tmp_root / "tiktok_tokens.json").read_text(encoding="utf-8"))
    assert saved["label"]["access_token"] == "new-token"
    assert saved["label"]["refresh_token"] == "new-refresh"


def test_fetch_all_401_without_refresh_credentials_skips_account(tmp_root, monkeypatch):
    """No client key/secret configured -> can't refresh -> account must be
    skipped gracefully rather than raising."""
    _write(tmp_root, "tiktok_tokens.json", {"label": {"access_token": "expired", "refresh_token": "rt"}})

    def fake_api(url, token, method="GET", body=None):
        raise urllib.error.HTTPError(url, 401, "expired", {}, None)

    monkeypatch.setattr(tiktok, "_api", fake_api)
    assert tiktok.fetch_all(str(tmp_root)) == {}


def test_fetch_all_refresh_failure_skips_account(tmp_root, monkeypatch):
    _write(tmp_root, "tiktok_tokens.json", {"label": {"access_token": "expired", "refresh_token": "rt"}})
    _write(tmp_root, "settings.json", {"tiktok_client_key": "ck", "tiktok_client_secret": "cs"})

    def fake_api(url, token, method="GET", body=None):
        raise urllib.error.HTTPError(url, 401, "expired", {}, None)

    def fake_refresh(ck, cs, refresh_token):
        raise urllib.error.URLError("refresh endpoint down")

    monkeypatch.setattr(tiktok, "_api", fake_api)
    monkeypatch.setattr(tiktok, "_refresh", fake_refresh)
    assert tiktok.fetch_all(str(tmp_root)) == {}


def test_fetch_all_video_list_failure_still_returns_stats(tmp_root, monkeypatch):
    _write(tmp_root, "tiktok_tokens.json", {"label": {"access_token": "tok"}})

    def fake_api(url, token, method="GET", body=None):
        if "user/info" in url:
            return {"data": {"user": {"display_name": "RealName", "follower_count": 1,
                                       "likes_count": 0, "video_count": 0}}}
        raise urllib.error.URLError("boom")

    monkeypatch.setattr(tiktok, "_api", fake_api)
    out = tiktok.fetch_all(str(tmp_root))
    assert out["RealName"]["videos"] == []
    assert out["RealName"]["stats"]["follower_count"] == 1


def test_fetch_all_other_http_error_skips_account_without_refresh_attempt(tmp_root, monkeypatch):
    _write(tmp_root, "tiktok_tokens.json", {"label": {"access_token": "tok", "refresh_token": "rt"}})
    _write(tmp_root, "settings.json", {"tiktok_client_key": "ck", "tiktok_client_secret": "cs"})

    def fake_api(url, token, method="GET", body=None):
        raise urllib.error.HTTPError(url, 500, "server error", {}, None)

    def fake_refresh(*a, **k):
        raise AssertionError("should not attempt refresh on non-401/403 errors")

    monkeypatch.setattr(tiktok, "_api", fake_api)
    monkeypatch.setattr(tiktok, "_refresh", fake_refresh)
    assert tiktok.fetch_all(str(tmp_root)) == {}


# ---------------------------------------------------------------------------
# `_label` / `_username` (identita uctu) a `views_since` (Part-2 sucet cez VSETKY strany)
# ---------------------------------------------------------------------------

def _paged_api(pages, display_name="RealName"):
    """Fake tiktok._api: user/info + video/list rozdelene na strany (cursor = index dalsej strany)."""
    def fake_api(url, token, method="GET", body=None):
        if "user/info" in url:
            return {"data": {"user": {"display_name": display_name, "follower_count": 1,
                                       "likes_count": 0, "video_count": 3}}}
        if "video/list" in url:
            cur = (body or {}).get("cursor")
            idx = 0 if cur is None else int(cur)
            return {"data": {"videos": pages[idx], "has_more": idx < len(pages) - 1, "cursor": idx + 1}}
        raise AssertionError(f"unexpected url: {url}")
    return fake_api


def test_video_list_requests_share_url_field():
    fields = tiktok.VIDEOLIST.split("fields=")[1].split(",")
    assert "share_url" in fields and "create_time" in fields and "view_count" in fields


def test_fetch_all_adds_label_and_username_from_share_url(tmp_root, monkeypatch):
    _write(tmp_root, "tiktok_tokens.json", {"my_label": {"access_token": "tok"}})
    vids = [{"id": "1", "view_count": 1, "create_time": 1_700_000_000,
             "share_url": "https://www.tiktok.com/@coldcase_daily/video/123?utm_campaign=tt4d&utm_source=x"}]
    monkeypatch.setattr(tiktok, "_api", _paged_api([vids], display_name="Cold Case Daily"))
    out = tiktok.fetch_all(str(tmp_root))
    assert list(out) == ["Cold Case Daily"]                      # kluc vysledku ostava display_name
    st = out["Cold Case Daily"]["stats"]
    assert st["_label"] == "my_label" and st["_username"] == "coldcase_daily"
    assert st["follower_count"] == 1                             # povodne polia ostavaju


def test_fetch_all_username_is_empty_without_videos(tmp_root, monkeypatch):
    _write(tmp_root, "tiktok_tokens.json", {"my_label": {"access_token": "tok"}})
    monkeypatch.setattr(tiktok, "_api", _paged_api([[]]))
    st = tiktok.fetch_all(str(tmp_root))["RealName"]["stats"]
    assert st["_username"] == "" and st["_label"] == "my_label"


def test_fetch_all_username_uses_first_parsable_share_url(tmp_root, monkeypatch):
    _write(tmp_root, "tiktok_tokens.json", {"lbl": {"access_token": "tok"}})
    vids = [{"id": "1", "view_count": 1},                                                        # bez share_url
            {"id": "2", "view_count": 1, "share_url": "https://vm.tiktok.com/ZMabc123/"},         # kratky odkaz -> bez username
            {"id": "3", "view_count": 1, "share_url": "https://www.tiktok.com/@min.dblowndaily/video/3"},
            {"id": "4", "view_count": 1, "share_url": "https://www.tiktok.com/@somebody_else/video/4"}]
    monkeypatch.setattr(tiktok, "_api", _paged_api([vids]))
    assert tiktok.fetch_all(str(tmp_root))["RealName"]["stats"]["_username"] == "min.dblowndaily"
    monkeypatch.setattr(tiktok, "_api", _paged_api([[vids[0], vids[1]]]))
    assert tiktok.fetch_all(str(tmp_root))["RealName"]["stats"]["_username"] == ""


def test_fetch_all_without_since_keeps_old_behaviour(tmp_root, monkeypatch):
    _write(tmp_root, "tiktok_tokens.json", {"lbl": {"access_token": "tok"}})
    monkeypatch.setattr(tiktok, "_api", _paged_api([[{"id": "1", "view_count": 7, "create_time": 1_700_000_000}]]))
    st = tiktok.fetch_all(str(tmp_root))["RealName"]["stats"]
    assert "views_since" not in st and st["views_total"] == 7
    for bad in ("garbage", "2026-13-45", ""):                     # neplatne `since` = ako None
        st = tiktok.fetch_all(str(tmp_root), since=bad)["RealName"]["stats"]
        assert "views_since" not in st, bad


def test_fetch_all_views_since_sums_all_pages(tmp_root, monkeypatch):
    _write(tmp_root, "tiktok_tokens.json", {"lbl": {"access_token": "tok"}})
    start = calendar.timegm((2026, 9, 28, 0, 0, 0))               # 28.9.2026 00:00 UTC
    page1 = [{"id": "a", "view_count": 10, "create_time": start + 5},
             {"id": "b", "view_count": 20, "create_time": start},           # presne o polnoci -> pocita sa
             {"id": "c", "view_count": 400, "create_time": start - 1}]      # o sekundu skor -> nie
    page2 = [{"id": "d", "view_count": 5, "create_time": start + 86400},
             {"id": "e", "view_count": 700},                                # bez create_time -> nie
             {"id": "f", "view_count": 1000, "create_time": start - 86400}]
    page3 = [{"id": "g", "view_count": 3, "create_time": start + 10}]       # aj 3. strana sa scita
    monkeypatch.setattr(tiktok, "_api", _paged_api([page1, page2, page3]))
    st = tiktok.fetch_all(str(tmp_root), since="2026-09-28")["RealName"]["stats"]
    assert st["views_since"] == 10 + 20 + 5 + 3
    assert st["views_total"] == 10 + 20 + 400 + 5 + 700 + 1000 + 3


def test_fetch_all_views_since_is_not_capped_by_the_20_video_list(tmp_root, monkeypatch):
    _write(tmp_root, "tiktok_tokens.json", {"lbl": {"access_token": "tok"}})
    start = calendar.timegm((2026, 9, 28, 0, 0, 0))
    pages = [[{"id": f"{p}-{i}", "view_count": 2, "create_time": start + 1} for i in range(20)] for p in range(3)]
    monkeypatch.setattr(tiktok, "_api", _paged_api(pages))
    acc = tiktok.fetch_all(str(tmp_root), since="2026-09-28")["RealName"]
    assert len(acc["videos"]) == 20                               # zoznam videi ostava orezany na 20...
    assert acc["stats"]["views_since"] == 60 * 2                  # ...ale sucet zahrna vsetkych 60
