# -*- coding: utf-8 -*-
"""Regression tests for server.py's data-loading resilience (Phase 2): a
corrupted/missing JSON file must degrade gracefully instead of crashing the
request, and a failed Instagram API call inside fetch_comments must return an
error payload rather than raising and killing the HTTP handler thread."""
import json
import urllib.error

import pytest

import server


def test_load_json_safe_missing_file_returns_default(tmp_path):
    assert server._load_json_safe(str(tmp_path / "nope.json"), {"x": 1}) == {"x": 1}


def test_load_json_safe_corrupt_file_returns_default(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not valid json", encoding="utf-8")
    assert server._load_json_safe(str(p), {}) == {}


def test_ig_tokens_corrupt_file_does_not_raise(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "ROOT", str(tmp_path))
    (tmp_path / "ig_tokens.json").write_text("not json at all", encoding="utf-8")
    assert server.ig_tokens() == {}


def test_ig_tokens_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "ROOT", str(tmp_path))
    assert server.ig_tokens() == {}


def test_settings_corrupt_file_does_not_raise(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "ROOT", str(tmp_path))
    (tmp_path / "settings.json").write_text("{{{", encoding="utf-8")
    assert server._settings() == {}


def test_fetch_comments_unknown_user_returns_error_without_network(monkeypatch):
    monkeypatch.setattr(server, "ig_tokens", lambda: {})
    out = server.fetch_comments("nobody")
    assert "error" in out


def test_fetch_comments_media_api_http_error_is_graceful(monkeypatch):
    monkeypatch.setattr(server, "ig_tokens", lambda: {"acct": {"access_token": "tok"}})

    def boom(path, params):
        raise urllib.error.HTTPError("url", 400, "bad token", {}, None)

    monkeypatch.setattr(server, "ig_get", boom)
    out = server.fetch_comments("acct")
    assert "error" in out
    assert "media" not in out


def test_fetch_comments_media_api_network_error_is_graceful(monkeypatch):
    monkeypatch.setattr(server, "ig_tokens", lambda: {"acct": {"access_token": "tok"}})

    def boom(path, params):
        raise urllib.error.URLError("dns failure")

    monkeypatch.setattr(server, "ig_get", boom)
    out = server.fetch_comments("acct")
    assert "error" in out


def test_fetch_all_comments_survives_corrupt_ig_tokens(tmp_path, monkeypatch):
    """Regression for the original bug: fetch_all_comments() iterated
    ig_tokens().keys() with no guard, so a corrupt ig_tokens.json used to
    propagate an uncaught JSONDecodeError all the way out of the endpoint."""
    monkeypatch.setattr(server, "ROOT", str(tmp_path))
    (tmp_path / "ig_tokens.json").write_text("{corrupt", encoding="utf-8")
    monkeypatch.setattr(server, "fetch_youtube_comments", lambda: [])
    out = server.fetch_all_comments()
    assert out == {"media": []}
