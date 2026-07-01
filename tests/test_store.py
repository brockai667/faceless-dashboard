# -*- coding: utf-8 -*-
"""Data-layer tests for store.py: Gist-backed persistence with graceful
local-file fallback when GH_TOKEN/GIST_ID aren't configured, and tolerant
error handling when the Gist API is unreachable."""
import importlib
import json
import urllib.error

import pytest

import store
from conftest import make_response


@pytest.fixture
def gist_env(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "tok")
    monkeypatch.setenv("GIST_ID", "gid123")
    importlib.reload(store)
    yield store
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GIST_ID", raising=False)
    importlib.reload(store)


def test_disabled_without_env(monkeypatch):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GIST_ID", raising=False)
    importlib.reload(store)
    assert store.enabled() is False
    assert store.load_history() is None
    assert store.load_prev() is None
    # save_* are no-ops when disabled, must not raise
    store.save_history([{"date": "2026-01-01"}])
    store.save_prev({"a": 1})


def test_load_history_parses_gist_content(gist_env, monkeypatch):
    payload = {"files": {"history.json": {"content": json.dumps([{"date": "2026-01-01"}])}}}
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: make_response(payload))
    assert gist_env.load_history() == [{"date": "2026-01-01"}]


def test_load_history_missing_file_defaults_to_empty_list(gist_env, monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: make_response({"files": {}}))
    assert gist_env.load_history() == []


def test_load_history_network_error_returns_none_not_raise(gist_env, monkeypatch):
    def _boom(*a, **k):
        raise urllib.error.URLError("gist unreachable")
    monkeypatch.setattr("urllib.request.urlopen", _boom)
    assert gist_env.load_history() is None


def test_save_history_network_error_is_swallowed(gist_env, monkeypatch):
    def _boom(*a, **k):
        raise urllib.error.HTTPError("url", 500, "err", {}, None)
    monkeypatch.setattr("urllib.request.urlopen", _boom)
    # Must not raise -- a failed persist should not crash generate.py's run.
    gist_env.save_history([{"date": "2026-01-01"}])


def test_load_prev_parses_gist_content(gist_env, monkeypatch):
    payload = {"files": {"prev.json": {"content": json.dumps({"yt_subs": 42})}}}
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: make_response(payload))
    assert gist_env.load_prev() == {"yt_subs": 42}


def test_load_done_local_fallback_when_disabled(monkeypatch, tmp_path):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GIST_ID", raising=False)
    importlib.reload(store)
    monkeypatch.setattr(store, "_LOCAL_DONE", str(tmp_path / "done_comments.json"))
    assert store.load_done() == set()
    store.save_done(["a", "b", "a"])
    assert store.load_done() == {"a", "b"}


def test_load_done_corrupt_local_file_returns_empty_set(monkeypatch, tmp_path):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GIST_ID", raising=False)
    importlib.reload(store)
    bad_file = tmp_path / "done_comments.json"
    bad_file.write_text("not json", encoding="utf-8")
    monkeypatch.setattr(store, "_LOCAL_DONE", str(bad_file))
    assert store.load_done() == set()


def test_save_done_gist_error_falls_back_to_local(gist_env, monkeypatch, tmp_path):
    def _boom(*a, **k):
        raise urllib.error.HTTPError("url", 500, "err", {}, None)
    monkeypatch.setattr("urllib.request.urlopen", _boom)
    monkeypatch.setattr(gist_env, "_LOCAL_DONE", str(tmp_path / "done_comments.json"))
    gist_env.save_done(["x"])
    assert json.loads((tmp_path / "done_comments.json").read_text(encoding="utf-8")) == ["x"]
