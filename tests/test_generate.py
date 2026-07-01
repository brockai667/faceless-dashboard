# -*- coding: utf-8 -*-
"""Data-layer tests for generate.py: number formatting, date/duration parsing,
YouTube fetch helpers, and the ranking aggregation used to build the dashboard."""
import json
import urllib.error

import pytest

import generate
from conftest import make_response


# ---------------------------------------------------------------------------
# fmt() — number formatting used everywhere in the legacy HTML + totals
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("n,expected", [
    (None, "—"),
    (0, "0"),
    (999, "999"),
    (1000, "1.0K"),
    (1500, "1.5K"),
    (999_999, "1000.0K"),  # documents actual (slightly odd but real) boundary behavior
    (1_000_000, "1.0M"),
    (2_340_000, "2.3M"),
])
def test_fmt(n, expected):
    assert generate.fmt(n) == expected


# ---------------------------------------------------------------------------
# ago() — relative/absolute date formatting for "last sent" timestamps
# ---------------------------------------------------------------------------

def test_ago_empty():
    assert generate.ago(None) == "—"
    assert generate.ago("") == "—"


def test_ago_valid_iso():
    assert generate.ago("2026-01-15T10:30:00Z") == "15.01 10:30"


def test_ago_malformed_falls_back_to_raw_slice():
    # Not a valid ISO string -> should not raise, falls back to first 16 chars
    assert generate.ago("not-a-date") == "not-a-date"


# ---------------------------------------------------------------------------
# _iso_dur() — ISO8601 PT#H#M#S -> seconds (YouTube contentDetails.duration)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("s,expected", [
    ("PT1H2M3S", 3723),
    ("PT45S", 45),
    ("PT5M", 300),
    ("PT2H", 7200),
    ("", 0),
    (None, 0),
    ("garbage", 0),
])
def test_iso_dur(s, expected):
    assert generate._iso_dur(s) == expected


# ---------------------------------------------------------------------------
# _recent() — "published within N days" used for the online/offline dot
# ---------------------------------------------------------------------------

def test_recent_today_is_recent():
    import datetime
    today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    assert generate._recent(today) is True


def test_recent_far_past_is_not_recent():
    assert generate._recent("2000-01-01") is False


def test_recent_malformed_date_is_false():
    assert generate._recent("not-a-date") is False


# ---------------------------------------------------------------------------
# profile_link() — derives a canonical profile URL per service
# ---------------------------------------------------------------------------

def test_profile_link_prefers_external_link():
    c = {"externalLink": "https://example.com/mine", "service": "tiktok", "name": "@foo"}
    assert generate.profile_link(c) == "https://example.com/mine"


def test_profile_link_youtube_with_service_id():
    c = {"service": "youtube", "serviceId": "UCabc123", "name": "Foo"}
    assert generate.profile_link(c) == "https://www.youtube.com/channel/UCabc123"


def test_profile_link_youtube_without_service_id_falls_back_to_handle():
    c = {"service": "youtube", "name": "@foo"}
    assert generate.profile_link(c) == "https://www.youtube.com/@foo"


def test_profile_link_tiktok_strips_at_prefix():
    c = {"service": "tiktok", "name": "@foo"}
    assert generate.profile_link(c) == "https://www.tiktok.com/@foo"


def test_profile_link_instagram():
    c = {"service": "instagram", "name": "foo"}
    assert generate.profile_link(c) == "https://www.instagram.com/foo"


def test_profile_link_unknown_service_returns_hash():
    c = {"service": "mastodon", "name": "foo"}
    assert generate.profile_link(c) == "#"


# ---------------------------------------------------------------------------
# yt_stats() / yt_videos() — YouTube Data API aggregation, network mocked
# ---------------------------------------------------------------------------

def test_yt_stats_no_key_or_no_ids_short_circuits():
    assert generate.yt_stats([], "key") == {}
    assert generate.yt_stats(["UCabc"], "") == {}


def test_yt_stats_parses_statistics(monkeypatch):
    payload = {"items": [{
        "id": "UCabc",
        "statistics": {"subscriberCount": "1234", "viewCount": "99999", "videoCount": "10"},
        "snippet": {"title": "My Channel"},
    }]}
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: make_response(payload))
    out = generate.yt_stats(["UCabc"], "key")
    assert out["UCabc"] == {
        "subs": 1234, "views": 99999, "videos": 10, "title": "My Channel", "hidden": False,
    }


def test_yt_stats_network_error_returns_empty(monkeypatch):
    def _boom(*a, **k):
        raise urllib.error.URLError("no network")
    monkeypatch.setattr("urllib.request.urlopen", _boom)
    assert generate.yt_stats(["UCabc"], "key") == {}


def test_yt_videos_no_key_or_channel_short_circuits():
    assert generate.yt_videos(None, "key") == []
    assert generate.yt_videos("UCabc", "") == []
    assert generate.yt_videos("not-a-channel-id", "key") == []


def test_yt_videos_happy_path(monkeypatch):
    responses = [
        make_response({"items": [{"contentDetails": {"videoId": "vid1"}}]}),
        make_response({"items": [{
            "id": "vid1",
            "statistics": {"viewCount": "500", "likeCount": "20", "commentCount": "3"},
            "snippet": {"title": "Vid One", "publishedAt": "2026-02-01T00:00:00Z"},
            "contentDetails": {"duration": "PT3M"},
        }]}),
    ]
    calls = iter(responses)
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: next(calls))
    out = generate.yt_videos("UCabcdefghijklmnop", "key")
    assert len(out) == 1
    v = out[0]
    assert v["id"] == "vid1"
    assert v["views"] == 500
    assert v["duration"] == 180
    assert v["is_long"] is True
    assert v["published"] == "2026-02-01"


def test_yt_videos_empty_playlist_short_circuits(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: make_response({"items": []}))
    assert generate.yt_videos("UCabcdefghijklmnop", "key") == []


def test_yt_videos_404_is_treated_as_no_videos_yet(monkeypatch):
    def _boom(*a, **k):
        raise urllib.error.HTTPError("url", 404, "not found", {}, None)
    monkeypatch.setattr("urllib.request.urlopen", _boom)
    assert generate.yt_videos("UCabcdefghijklmnop", "key") == []


def test_yt_videos_other_http_error_is_swallowed_and_returns_empty(monkeypatch, capsys):
    def _boom(*a, **k):
        raise urllib.error.HTTPError("url", 500, "server error", {}, None)
    monkeypatch.setattr("urllib.request.urlopen", _boom)
    assert generate.yt_videos("UCabcdefghijklmnop", "key") == []


# ---------------------------------------------------------------------------
# render_ranking() — aggregates videos across factories into a leaderboard
# ---------------------------------------------------------------------------

def _project(name, color, videos):
    return {"name": name, "color": color, "videos": videos}


def test_render_ranking_empty_youtube_shows_setup_hint():
    html = generate.render_ranking([_project("A", "#111", [])], "youtube")
    assert "API kľúča" in html


def test_render_ranking_empty_tiktok_shows_setup_hint():
    html = generate.render_ranking([_project("A", "#111", [])], "tiktok")
    assert "žiadne pripojené videá" in html


def test_render_ranking_sorts_by_views_descending():
    videos = [
        {"platform": "YouTube", "views": 10, "likes": 1, "comments": 0, "title": "low", "factory": "A", "color": "#111", "link": "#"},
        {"platform": "YouTube", "views": 999, "likes": 5, "comments": 1, "title": "high", "factory": "A", "color": "#111", "link": "#"},
    ]
    html = generate.render_ranking([_project("A", "#111", videos)], "youtube")
    assert html.index("high") < html.index("low")


def test_render_ranking_ignores_other_platforms():
    videos = [
        {"platform": "TikTok", "views": 500, "likes": 1, "comments": 0, "title": "tt", "factory": "A", "color": "#111", "link": "#"},
    ]
    html = generate.render_ranking([_project("A", "#111", videos)], "youtube")
    assert "API kľúča" in html  # still treated as "no youtube videos"


def test_render_ranking_escapes_html_in_title():
    videos = [
        {"platform": "YouTube", "views": 5, "likes": 0, "comments": 0,
         "title": "<script>alert(1)</script>", "factory": "A", "color": "#111", "link": "#"},
    ]
    html = generate.render_ranking([_project("A", "#111", videos)], "youtube")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
