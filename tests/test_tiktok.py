# -*- coding: utf-8 -*-
"""Data-layer tests for tiktok.py: token loading, 401/403 auto-refresh flow,
and aggregation of user info + video list into fetch_all()'s output."""
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
