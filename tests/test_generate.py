# -*- coding: utf-8 -*-
"""Data-layer tests for generate.py: number formatting, date/duration parsing,
YouTube fetch helpers, and the ranking aggregation used to build the dashboard."""
import calendar
import json
import urllib.error

import pytest

import generate
import tiktok
from conftest import make_response


# ---------------------------------------------------------------------------
# _load_json_safe() — Phase 2 hardening: a corrupt/missing JSON file (channel
# cache, per-factory config.json, settings.json) must never crash the whole
# generate.py run; it should log a warning and fall back to a default value.
# ---------------------------------------------------------------------------

def test_load_json_safe_missing_file_returns_default(tmp_path):
    assert generate._load_json_safe(str(tmp_path / "missing.json"), {"a": 1}) == {"a": 1}


def test_load_json_safe_corrupt_file_returns_default(tmp_path, capsys):
    p = tmp_path / "bad.json"
    p.write_text("{not valid json!!", encoding="utf-8")
    assert generate._load_json_safe(str(p), {}) == {}
    assert "poskodeny" in capsys.readouterr().out


def test_load_json_safe_valid_file_is_parsed(tmp_path):
    p = tmp_path / "good.json"
    p.write_text(json.dumps({"buffer_token": "abc"}), encoding="utf-8")
    assert generate._load_json_safe(str(p), {}) == {"buffer_token": "abc"}


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


# ---------------------------------------------------------------------------
# _norm_handle() + resolve_factory() — tolerantne parovanie uctov na fabriky
# (premenovane ucty, display_name s medzerami, stare kluce tokenov)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("min.dblowndaily", "mindblowndaily"),
    ("Cold Case Daily", "coldcasedaily"),
    ("  Wealth_Mindset34 ", "wealthmindset34"),
    ("Héllo-Wörld 9", "hllowrld9"),   # nie-ASCII znaky sa zahodia
    ("", ""),
    (None, ""),
])
def test_norm_handle(raw, expected):
    assert generate._norm_handle(raw) == expected


def _tk(key):
    return generate.resolve_factory(key, generate.HANDLE_TO_FACTORY, generate.FACTORY_NAMES)


def _ig(key):
    return generate.resolve_factory(key, generate.IG_LOOKUP, generate.FACTORY_NAMES)


def test_resolve_factory_exact_key():
    assert _tk("wealth_mindset34") == "WealthMindset"
    assert _tk("disciplinedaily667") == "BrainHeist"


@pytest.mark.parametrize("key", ["insideyourmind007", "min.dblowndaily", "MindBlownDaily"])
def test_resolve_factory_mindblown_aliases(key):
    assert _tk(key) == "MindBlownDaily"


def test_resolve_factory_cold_case_display_name():
    assert _tk("Cold Case Daily") == "ColdCaseDaily"
    assert _tk("coldcase_daily") == "ColdCaseDaily"


def test_resolve_factory_normalised_equal_to_mapping_key():
    assert _tk("Wealth_Mindset34") == "WealthMindset"   # ina velkost/znaky, rovnaky normalizovany tvar
    assert _tk("MIN.DBLOWNDAILY") == "MindBlownDaily"


def test_resolve_factory_normalised_equal_to_factory_name():
    assert _tk("Brain Heist") == "BrainHeist"   # nie je v mape, sedi nazov fabriky
    assert _tk("hidden-earth") == "HiddenEarth"


def test_resolve_factory_factory_name_contained_in_key():
    # kluc nie je v mape ani sa nerovna nazvu, ale obsahuje nazov fabriky (14 znakov)
    assert _tk("mindblowndaily.official") == "MindBlownDaily"
    assert _tk("MindBlownDaily_Official") == "MindBlownDaily"


def test_resolve_factory_instagram_current_and_old_username():
    assert _ig("mindblowndaily.official") == "MindBlownDaily"
    assert _ig("th.erealspark") == "MindBlownDaily"          # stare meno cez IG_ALIASES
    # bez IG_ALIASES by stare meno nikoho nenaslo -> alias naozaj robi robotu
    assert generate.resolve_factory("th.erealspark", generate.IG_TO_FACTORY, generate.FACTORY_NAMES) is None


def test_resolve_factory_unknown_and_empty_are_none():
    assert _tk("some_random_account") is None
    assert _ig("nobody.here") is None
    assert _tk("") is None
    assert _tk(None) is None
    assert _tk("...") is None   # po normalizacii prazdny retazec


def test_resolve_factory_short_factory_names_do_not_match_by_containment():
    names = generate.FACTORY_NAMES
    assert "Curio" in names                                    # 5 znakov -> pod limitom 8
    assert generate.resolve_factory("curiousmind99", {}, names) is None
    assert generate.resolve_factory("CURIO", {}, names) == "Curio"   # rovnost s nazvom ale funguje


def test_resolve_factory_containment_length_boundary():
    assert generate.resolve_factory("abcdefgxyz", {}, ["AbcdefG"]) is None            # 7 znakov -> nie
    assert generate.resolve_factory("abcdefghxyz", {}, ["Abcdefgh"]) == "Abcdefgh"    # 8 znakov -> ano


def test_resolve_factory_mapping_beats_factory_name():
    assert generate.resolve_factory("foobar", {"Foo.Bar": "X"}, ["FooBar"]) == "X"   # normalizovany kluc mapy skor
    assert generate.resolve_factory("Foo.Bar", {"Foo.Bar": "X"}, ["FooBar"]) == "X"  # presny kluc


def test_handle_maps_are_explicit_and_round_trip():
    assert generate.TIKTOK_HANDLE == {
        "MindBlownDaily": "min.dblowndaily", "WealthMindset": "wealth_mindset34",
        "UnexplainedDaily": "unexplained_daily", "BrainHeist": "disciplinedaily667",
        "VitalityDaily": "vitalitydaily667", "HiddenEarth": "hiddenearth667",
        "ColdCaseDaily": "coldcase_daily"}
    assert generate.IG_HANDLE["MindBlownDaily"] == "mindblowndaily.official"
    assert generate.IG_HANDLE["BrainHeist"] == "brainheistriddles" and generate.IG_HANDLE["NextByte"] == "nextbyte667"
    assert generate.IG_ALIASES == {"th.erealspark": "MindBlownDaily", "disciplinedaily667": "BrainHeist",
                                   "historyuntold667": "NextByte"}   # stare nazvy = kluce starych tokenov
    for old, fac in generate.IG_ALIASES.items():
        assert _ig(old) == fac
    for fac, h in generate.TIKTOK_HANDLE.items():
        assert fac in generate.FACTORY_NAMES and _tk(h) == fac
    for fac, h in generate.IG_HANDLE.items():
        assert fac in generate.FACTORY_NAMES and _ig(h) == fac


# ---------------------------------------------------------------------------
# conn_state() / account_status() / annotate_accounts() — preco platforma chyba
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("has_data,has_handle,has_token,state", [
    (True, True, True, "ok"),
    (True, False, False, "ok"),            # data maju prednost
    (False, False, True, "no_account"),    # bez handle nie je co pripajat
    (False, False, False, "no_account"),
    (False, True, True, "token_error"),    # token je, data nie
    (False, True, False, "no_token"),
])
def test_conn_state(has_data, has_handle, has_token, state):
    r = generate.conn_state(has_data, has_handle, has_token)
    assert r == {"state": state, "note": generate.CONN_NOTES[state]}


def test_conn_notes_are_the_agreed_slovak_texts():
    assert generate.CONN_NOTES == {
        "ok": "",
        "no_account": "účet nie je založený alebo sa nepoužíva",
        "token_error": "token neplatný alebo expirovaný – treba znova autorizovať",
        "no_token": "chýba autorizácia účtu pre dashboard",
    }


def test_account_status_shape_and_unlisted_platforms_omitted():
    st = generate.account_status("VitalityDaily")
    assert list(st) == ["tiktok"]                       # ostatne platformy sa vynechaju
    assert st["tiktok"]["state"] == "ban"
    assert "vitalitydaily667" in st["tiktok"]["note"]
    bh = generate.account_status("BrainHeist")
    assert set(bh) == {"tiktok", "instagram"} and bh["instagram"]["state"] == "riesit"
    assert generate.account_status("WealthMindset") == {}     # nema zaznam
    assert generate.account_status("Neznama") == {}


def test_account_status_table_is_consistent():
    for fac, plats in generate.ACCOUNT_STATUS.items():
        assert fac in generate.FACTORY_NAMES
        for plat, (state, note) in plats.items():
            assert plat in ("youtube", "tiktok", "instagram")
            assert state in ("ok", "ban", "riesit", "nepouziva")
            assert note


def _proj(name, yt=None, tk=None, ig=None):
    return {"name": name, "yt": yt, "tiktok": tk, "instagram": ig}


def test_annotate_accounts_states_per_platform():
    projects = [
        _proj("MindBlownDaily", yt={"subs": 1}, tk={"followers": 1}, ig={"followers": 1}),  # vsetko ma data
        _proj("BrainHeist", yt={"subs": 1}),          # tokeny su, data nie
        _proj("ColdCaseDaily", yt={"subs": 1}),       # handle je, token nie
        _proj("Money Glitch", yt={"subs": 1}),        # TikTok/IG nezalozene
    ]
    generate.annotate_accounts(projects, True, ["disciplinedaily667"], ["disciplinedaily667"])
    by = {p["name"]: p for p in projects}
    assert {c["state"] for c in by["MindBlownDaily"]["conn"].values()} == {"ok"}
    assert by["MindBlownDaily"]["conn"]["tiktok"]["note"] == ""
    bh = by["BrainHeist"]["conn"]
    assert bh["tiktok"]["state"] == "token_error" and bh["instagram"]["state"] == "token_error"
    assert bh["tiktok"]["note"] == generate.CONN_NOTES["token_error"]
    cc = by["ColdCaseDaily"]["conn"]
    assert cc["tiktok"]["state"] == "no_token" and cc["instagram"]["state"] == "no_token"
    mg = by["Money Glitch"]["conn"]
    assert mg["tiktok"]["state"] == "no_account" and mg["instagram"]["state"] == "no_account"


def test_annotate_accounts_old_token_labels_resolve_through_aliases():
    p = _proj("MindBlownDaily", yt={"subs": 1})
    # stary stitok TikTok tokenu + stary IG username v ig_tokens.json (ucty su medzitym premenovane)
    generate.annotate_accounts([p], True, ["insideyourmind007"], ["th.erealspark"])
    assert p["conn"]["tiktok"]["state"] == "token_error"
    assert p["conn"]["instagram"]["state"] == "token_error"
    q = _proj("MindBlownDaily", yt={"subs": 1})
    generate.annotate_accounts([q], True, ["mindblowndaily"], [])   # stitok = nazov fabriky
    assert q["conn"]["tiktok"]["state"] == "token_error"
    assert q["conn"]["instagram"]["state"] == "no_token"


def test_annotate_accounts_youtube_states():
    with_data = _proj("EyeHeist", yt={"subs": 3})
    no_key = _proj("EyeHeist")
    key_no_data = _proj("EyeHeist")
    unknown = _proj("Neznamy kanal")
    generate.annotate_accounts([with_data], True, [], [])
    generate.annotate_accounts([no_key], False, [], [])
    generate.annotate_accounts([key_no_data], True, [], [])
    generate.annotate_accounts([unknown], True, [], [])
    assert with_data["conn"]["youtube"]["state"] == "ok"
    assert no_key["conn"]["youtube"]["state"] == "no_token"
    assert key_no_data["conn"]["youtube"]["state"] == "token_error"
    assert unknown["conn"]["youtube"]["state"] == "no_account"


def test_annotate_accounts_emits_manual_status():
    projects = [_proj("VitalityDaily"), _proj("WealthMindset"), _proj("MindBlownDaily")]
    generate.annotate_accounts(projects, True, [], [])
    vit, wealth, mind = projects
    assert vit["status"]["tiktok"]["state"] == "ban"
    assert wealth["status"] == {}
    assert mind["status"]["tiktok"] == {"state": "ok", "note": "@min.dblowndaily, premenovany 27.9."}


def test_token_labels_returns_only_keys_never_values(tmp_root):
    (tmp_root / "tiktok_tokens.json").write_text(json.dumps({
        "mindblowndaily": {"access_token": "SECRET-ACCESS", "refresh_token": "SECRET-REFRESH"},
        "coldcase": {"access_token": "SECRET-OTHER"},
    }), encoding="utf-8")
    labels = tiktok.token_labels(str(tmp_root))
    assert labels == ["mindblowndaily", "coldcase"]
    assert "SECRET" not in repr(labels)


def test_token_labels_missing_file_is_empty_list(tmp_root):
    assert tiktok.token_labels(str(tmp_root)) == []

# ---------------------------------------------------------------------------
# TikTok identita: candidates (username > stitok > display_name), nove aliasy,
# opacna zhoda (kluc je casou nazvu), YouTube poznamky
# ---------------------------------------------------------------------------

def test_tiktok_candidates_order_and_dedupe():
    st = {"_username": "unexplained_daily", "_label": "mystery", "follower_count": 1}
    assert generate.tiktok_candidates("unexplained", st) == ["unexplained_daily", "mystery", "unexplained"]
    assert generate.tiktok_candidates("same", {"_username": "same", "_label": "same"}) == ["same"]   # bez duplicit
    assert generate.tiktok_candidates("DisplayOnly", {"_username": "", "_label": None}) == ["DisplayOnly"]
    assert generate.tiktok_candidates("DisplayOnly", None) == ["DisplayOnly"]
    assert generate.tiktok_candidates("", {}) == []


def test_resolve_tiktok_username_beats_label_beats_display_name():
    # username hovori BrainHeist, aj ked stitok a display_name ukazuju inam
    st = {"_username": "disciplinedaily667", "_label": "vitalitydaily667"}
    assert generate.resolve_tiktok("wealth_mindset34", st) == "BrainHeist"
    # bez username rozhoduje stitok (pred display_name)
    assert generate.resolve_tiktok("wealth_mindset34", {"_username": "", "_label": "vitalitydaily667"}) == "VitalityDaily"
    # username ani stitok nikam nesedia -> display_name
    assert generate.resolve_tiktok("Cold Case Daily", {"_username": "zzz_nothing", "_label": "acc1"}) == "ColdCaseDaily"
    assert generate.resolve_tiktok("nobody", {"_username": "x", "_label": "y"}) is None
    assert generate.resolve_tiktok("nobody", None) is None


@pytest.mark.parametrize("display,username,fac", [
    ("unexplained", "unexplained_daily", "UnexplainedDaily"),      # overene 29.9.2026
    ("DisciplineDaily", "disciplinedaily667", "BrainHeist"),
    ("Cold Case Daily", "coldcase_daily", "ColdCaseDaily"),
])
def test_resolve_tiktok_real_display_names_differ_from_usernames(display, username, fac):
    assert generate.resolve_tiktok(display, {"_username": username, "_label": ""}) == fac   # cez username
    assert generate.resolve_tiktok(display, {"_username": "", "_label": ""}) == fac         # aj len cez display_name


def test_new_tiktok_aliases_exist():
    assert generate.HANDLE_TO_FACTORY["unexplained"] == "UnexplainedDaily"
    assert generate.HANDLE_TO_FACTORY["DisciplineDaily"] == "BrainHeist"
    assert generate.HANDLE_TO_FACTORY["BrainHeist"] == "BrainHeist"
    assert _tk("unexplained") == "UnexplainedDaily" and _tk("DisciplineDaily") == "BrainHeist" and _tk("BrainHeist") == "BrainHeist"


def test_resolve_factory_reverse_containment_key_is_part_of_name():
    # kluc (>= 8 znakov) je casou nazvu fabriky alebo kluca mapy
    assert generate.resolve_factory("unexplaine", {}, generate.FACTORY_NAMES) == "UnexplainedDaily"
    assert generate.resolve_factory("hiddenearth66", generate.HANDLE_TO_FACTORY, []) == "HiddenEarth"
    assert generate.resolve_factory("dblowndaily", {}, ["MindBlownDaily"]) == "MindBlownDaily"


def test_resolve_factory_reverse_containment_needs_8_chars():
    assert generate.resolve_factory("unexpl", {}, generate.FACTORY_NAMES) is None       # 6 znakov
    assert generate.resolve_factory("abcdefg", {}, ["xxabcdefgyy"]) is None             # 7 znakov -> nie
    assert generate.resolve_factory("abcdefgh", {}, ["xxabcdefghyy"]) == "xxabcdefghyy"  # 8 znakov -> ano


def test_resolve_factory_reverse_containment_ambiguous_is_none():
    # 'daily667' je v 'disciplinedaily667' (BrainHeist) aj 'vitalitydaily667' (VitalityDaily)
    assert generate.resolve_factory("daily667", generate.HANDLE_TO_FACTORY, generate.FACTORY_NAMES) is None
    assert generate.resolve_factory("sharedpart", {"aaa_sharedpart_1": "A", "bbb_sharedpart_2": "B"}, []) is None
    # dva kluce, ale TA ISTA fabrika -> jednoznacne
    assert generate.resolve_factory("sharedpart", {"aaa_sharedpart": "A", "sharedpart_bbb": "A"}, []) == "A"
    # kluc mapy aj nazov fabriky vedu k tej istej fabrike -> jednoznacne; k roznym -> None
    assert generate.resolve_factory("unexplained", {"unexplained_daily": "UnexplainedDaily"}, ["UnexplainedDaily"]) == "UnexplainedDaily"
    assert generate.resolve_factory("unexplained", {"unexplained_daily": "Other"}, ["UnexplainedDaily"]) is None


def test_conn_state_youtube_notes_are_its_own():
    assert generate.CONN_NOTES_YT == {
        "ok": "",
        "no_account": "kanál nie je nastavený",
        "token_error": "kanál sa nepodarilo načítať z YouTube API",
        "no_token": "chýba YouTube API kľúč",
    }
    assert generate.conn_state(False, True, False, generate.CONN_NOTES_YT) == {"state": "no_token", "note": "chýba YouTube API kľúč"}
    # bez `notes` ostavaju texty pre TikTok/Instagram
    assert generate.conn_state(False, True, False)["note"] == generate.CONN_NOTES["no_token"]


def test_annotate_accounts_youtube_notes_differ_from_tiktok_instagram_notes():
    no_key = _proj("EyeHeist")
    key_no_data = _proj("EyeHeist")
    unknown = _proj("Neznamy kanal")
    generate.annotate_accounts([no_key], False, [], [])
    generate.annotate_accounts([key_no_data], True, [], [])
    generate.annotate_accounts([unknown], True, [], [])
    assert no_key["conn"]["youtube"] == {"state": "no_token", "note": "chýba YouTube API kľúč"}
    assert key_no_data["conn"]["youtube"] == {"state": "token_error", "note": "kanál sa nepodarilo načítať z YouTube API"}
    assert unknown["conn"]["youtube"] == {"state": "no_account", "note": "kanál nie je nastavený"}
    # TikTok / Instagram maju stale povodne texty o autorizacii
    assert no_key["conn"]["tiktok"]["note"] == "účet nie je založený alebo sa nepoužíva"        # EyeHeist nema TikTok
    assert no_key["conn"]["instagram"]["note"] == "chýba autorizácia účtu pre dashboard"        # handle je, token nie


def test_annotate_accounts_tolerates_junk_labels():
    p = _proj("MindBlownDaily", yt={"subs": 1})
    generate.annotate_accounts([p], True, None, None)
    assert p["conn"]["tiktok"]["state"] == "no_token" and p["conn"]["instagram"]["state"] == "no_token"


# ---------------------------------------------------------------------------
# Part 2: part2_start(), sum_views_since(), yt_videos(out_all=...)
# ---------------------------------------------------------------------------

def test_part2_start_default_env_and_invalid(monkeypatch):
    monkeypatch.delenv("DASH_HISTORY_START", raising=False)
    assert generate.part2_start() == "2026-09-28"                 # rovnaky default ako server.py
    monkeypatch.setenv("DASH_HISTORY_START", "2026-10-05")
    assert generate.part2_start() == "2026-10-05"
    for bad in ("", "garbage", "2026-13-45", "2026-9-8", "20261005"):
        monkeypatch.setenv("DASH_HISTORY_START", bad)
        assert generate.part2_start() == "2026-09-28", bad


def test_new_p2_shape():
    assert generate.new_p2("2026-09-28") == {"start": "2026-09-28", "youtube": 0, "tiktok": 0, "instagram": 0}


def test_sum_views_since_boundary_and_undated():
    vids = [{"views": 5, "published": "2026-09-27"},      # pred startom
            {"views": 7, "published": "2026-09-28"},      # presne v den startu -> pocita sa
            {"views": 11, "published": "2026-10-01"},
            {"views": 1000, "published": ""},             # bez datumu -> nepocita sa
            {"views": 2000},                              # bez `published` vobec
            {"views": None, "published": "2026-09-29"}]   # None views -> 0
    assert generate.sum_views_since(vids, "2026-09-28") == 18
    assert generate.sum_views_since([], "2026-09-28") == 0


def test_yt_videos_out_all_receives_untrimmed_list(monkeypatch):
    ids = [f"vid{i}" for i in range(6)]
    items = []
    for i, vid in enumerate(ids):     # vid0 = najnovsie; vid5 = najstarsie; vid5 je dlhy dokument
        items.append({"id": vid, "statistics": {"viewCount": str(10 * (i + 1))},
                      "snippet": {"title": vid, "publishedAt": f"2026-09-{28 - i:02d}T00:00:00Z"},
                      "contentDetails": {"duration": "PT5M" if i == 5 else "PT30S"}})
    responses = iter([make_response({"items": [{"contentDetails": {"videoId": v}} for v in ids]}),
                      make_response({"items": items})])
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: next(responses))
    full = []
    out = generate.yt_videos("UCabcdefghijklmnop", "key", n=2, deep=6, out_all=full)
    assert [v["id"] for v in out] == ["vid0", "vid1", "vid5"]        # 2 najnovsie + dlhy dokument
    assert [v["id"] for v in full] == ids                            # ale out_all ma VSETKO stiahnute
    assert generate.sum_views_since(full, "2026-09-25") == 10 + 20 + 30 + 40      # vid0..vid3 (25.-28.9.)
    assert generate.sum_views_since(out, "2026-09-25") == 10 + 20                  # orezany zoznam by zaostaval


def test_yt_videos_out_all_stays_untouched_on_errors(monkeypatch):
    def _boom(*a, **k):
        raise urllib.error.URLError("no network")
    monkeypatch.setattr("urllib.request.urlopen", _boom)
    full = []
    assert generate.yt_videos("UCabcdefghijklmnop", "key", n=2, deep=6, out_all=full) == []
    assert full == []


# ---------------------------------------------------------------------------
# main() bez siete: identita uctov, p["conn"], p["status"], p["p2"], odolnost
# ---------------------------------------------------------------------------

def _setup_main(monkeypatch, tmp_path, names):
    """Izolovany beh generate.main(): ROOT + FACTORIES v tmp, ziadny Buffer/YouTube/Gist/sleep; moduly vracaju prazdno."""
    facs = [(n, "NICHE", "#3b82f6", str(tmp_path / f"nofolder{i}")) for i, n in enumerate(names)]
    monkeypatch.setattr(generate, "ROOT", str(tmp_path))
    monkeypatch.setattr(generate, "FACTORIES", facs)
    monkeypatch.setattr("time.sleep", lambda *_: None)
    monkeypatch.setattr("store.TOKEN", None)                       # ziadny Gist
    for var in ("BUFFER_TOKENS_JSON", "YOUTUBE_API_KEY", "DASH_HISTORY_START"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(generate._tiktok, "fetch_all", lambda root, since=None: {})
    monkeypatch.setattr(generate._tiktok, "token_labels", lambda root: [])
    monkeypatch.setattr(generate._instagram, "refresh_tokens", lambda root: {})
    monkeypatch.setattr(generate._instagram, "token_status", lambda root: {})
    monkeypatch.setattr(generate._instagram, "fetch_all", lambda root, since=None: {})


def _run_main(tmp_path):
    generate.main()
    data = json.loads((tmp_path / "data.json").read_text(encoding="utf-8"))
    return {p["name"]: p for p in data["projects"]}


_TS = calendar.timegm((2026, 9, 28, 12, 0, 0))   # 28.9.2026 12:00 UTC


def _tk_acc(vid, username, label, views=30):
    return {"stats": {"follower_count": 5, "likes_count": 2, "views_total": views, "video_count": 1,
                      "_label": label, "_username": username},
            "videos": [{"id": vid, "title": "t", "view_count": views, "like_count": 1,
                        "comment_count": 0, "create_time": _TS}]}


def test_main_maps_accounts_by_username_label_and_display_name(tmp_path, monkeypatch):
    """Cely main(): display_name casto nie je username -> fabrika sa hlada podla username, stitku, az potom display_name."""
    _setup_main(monkeypatch, tmp_path, ["MindBlownDaily", "ColdCaseDaily", "BrainHeist", "UnexplainedDaily",
                                        "HiddenEarth", "Money Glitch"])
    monkeypatch.setattr(generate._tiktok, "fetch_all", lambda root, since=None: {
        "MindBlownDaily": _tk_acc("111", "min.dblowndaily", "mindblowndaily"),
        "Cold Case Daily": _tk_acc("222", "coldcase_daily", "cc"),
        "DisciplineDaily": _tk_acc("333", "disciplinedaily667", "whatever"),          # display_name != username
        "unexplained": {"stats": {"_label": "", "_username": ""}, "videos": []},        # bez videi -> alias display_name
        "Totally Unknown": _tk_acc("444", "nobody_here", "acc9"),                       # nesedi nikam -> zahodi sa
    })
    monkeypatch.setattr(generate._tiktok, "token_labels", lambda root: ["mindblowndaily", "hiddenearth667"])
    monkeypatch.setattr(generate._instagram, "token_status", lambda root: {
        "th.erealspark": {"days_left": 30.0, "expired": False},       # stary kluc premenovaneho uctu
        "disciplinedaily667": {"days_left": -3.0, "expired": True}})  # expirovany -> ziadne data
    monkeypatch.setattr(generate._instagram, "fetch_all", lambda root, since=None: {
        "mindblowndaily.official": {"stats": {"followers_count": 9, "media_count": 0}, "media": []}})
    by = _run_main(tmp_path)

    mb = by["MindBlownDaily"]
    assert mb["tiktok"]["handle"] == "MindBlownDaily"               # ostava co vratilo API
    assert mb["instagram"]["handle"] == "mindblowndaily.official"
    assert mb["conn"]["tiktok"]["state"] == "ok" and mb["conn"]["instagram"]["state"] == "ok"
    assert mb["status"]["tiktok"]["state"] == "ok"
    assert mb["links"]["tiktok"] == "https://www.tiktok.com/@min.dblowndaily"
    tt = [v for v in mb["videos"] if v["platform"] == "TikTok"][0]
    assert tt["link"] == "https://www.tiktok.com/@min.dblowndaily/video/111"   # profilove username, nie display_name
    assert tt["published"] == "2026-09-28" and tt["views"] == 30

    assert by["ColdCaseDaily"]["tiktok"]["handle"] == "Cold Case Daily"
    assert by["ColdCaseDaily"]["conn"]["tiktok"]["state"] == "ok"
    assert by["ColdCaseDaily"]["status"]["tiktok"]["state"] == "ok"      # data chodia -> rucna znacka "riesit" sa sama vyriesi

    bh = by["BrainHeist"]
    assert bh["tiktok"]["handle"] == "DisciplineDaily"              # priradene cez username zo share_url
    assert bh["conn"]["tiktok"]["state"] == "ok"
    assert bh["instagram"] is None and bh["conn"]["instagram"]["state"] == "token_error"

    assert by["UnexplainedDaily"]["tiktok"]["handle"] == "unexplained"      # cez alias display_name
    assert by["UnexplainedDaily"]["conn"]["tiktok"]["state"] == "ok"
    assert by["UnexplainedDaily"]["conn"]["instagram"]["state"] == "no_token"

    he = by["HiddenEarth"]
    assert he["tiktok"] is None and he["conn"]["tiktok"]["state"] == "token_error"   # stitok sedi, data nie

    mg = by["Money Glitch"]
    assert mg["conn"]["tiktok"]["state"] == "no_account"
    assert mg["conn"]["youtube"] == {"state": "no_token", "note": "chýba YouTube API kľúč"}   # bez API kluca
    assert mg["status"]["instagram"]["state"] == "nepouziva"
    # neznamy ucet sa nikam nepriradil
    assert sum(1 for p in by.values() for v in p["videos"] if v["platform"] == "TikTok") == 3


def test_main_emits_p2_sums_over_everything_fetched(tmp_path, monkeypatch):
    """p['p2'] = sucty zhliadnuti od startu Part 2 zo VSETKEHO stiahnuteho (nie z orezanych zoznamov videi)."""
    _setup_main(monkeypatch, tmp_path, ["MindBlownDaily", "Money Glitch"])
    monkeypatch.setenv("YOUTUBE_API_KEY", "fake-key")       # tu len priznak "kluc je"; siet je zablokovana
    cid = generate.YT_CHANNELS["MindBlownDaily"]
    monkeypatch.setattr(generate, "yt_stats", lambda ids, key: {
        cid: {"subs": 1, "views": 9, "videos": 120, "title": "t", "hidden": False}})

    def fake_yt_videos(channel_id, key, n=50, deep=0, out_all=None):
        if channel_id != cid:
            return []
        full = [{"id": f"v{i}", "title": "t", "views": 10, "likes": 0, "comments": 0,
                 "published": "2026-09-28" if i < 100 else "2026-09-01", "duration": 30, "is_long": False}
                for i in range(120)]
        if out_all is not None:
            out_all.extend(full)
        return full[:n]                                      # UI zoznam: len 50 najnovsich
    monkeypatch.setattr(generate, "yt_videos", fake_yt_videos)

    seen = {}

    def fake_tk(root, since=None):
        seen["since"] = since
        acc = _tk_acc("1", "min.dblowndaily", "mindblowndaily", views=5)
        acc["stats"].update({"views_total": 5000, "video_count": 40, "views_since": 777})   # server-side sucet cez vsetky strany
        return {"MindBlownDaily": acc}
    monkeypatch.setattr(generate._tiktok, "fetch_all", fake_tk)

    media = [{"id": f"m{i}", "caption": "c", "like_count": 0, "comments_count": 0, "_views": 4,
              "permalink": "https://example.com/m", "timestamp": "2026-09-28T10:00:00+0000"} for i in range(25)]
    media += [{"id": f"o{i}", "caption": "c", "like_count": 0, "comments_count": 0, "_views": 100,
               "permalink": "https://example.com/o", "timestamp": "2026-09-01T10:00:00+0000"} for i in range(5)]
    monkeypatch.setattr(generate._instagram, "fetch_all", lambda root, since=None: {
        "mindblowndaily.official": {"stats": {"followers_count": 9, "media_count": 30}, "media": media}})
    by = _run_main(tmp_path)

    mb = by["MindBlownDaily"]
    assert mb["p2"] == {"start": "2026-09-28", "youtube": 1000, "tiktok": 777, "instagram": 100}
    assert seen["since"] == "2026-09-28"                                  # start sa posiela do tiktok.fetch_all
    assert sum(1 for v in mb["videos"] if v["platform"] == "YouTube") == 50   # UI zoznam ostal orezany...
    assert sum(1 for v in mb["videos"] if v["platform"] == "Instagram") == 30
    assert by["Money Glitch"]["p2"] == {"start": "2026-09-28", "youtube": 0, "tiktok": 0, "instagram": 0}   # kazdy projekt ma p2


def test_main_p2_start_follows_env(tmp_path, monkeypatch):
    _setup_main(monkeypatch, tmp_path, ["MindBlownDaily"])
    monkeypatch.setenv("DASH_HISTORY_START", "2026-10-05")
    seen = {}

    def fake_tk(root, since=None):
        seen["since"] = since
        return {}
    monkeypatch.setattr(generate._tiktok, "fetch_all", fake_tk)
    by = _run_main(tmp_path)
    assert by["MindBlownDaily"]["p2"]["start"] == "2026-10-05" and seen["since"] == "2026-10-05"


def test_main_survives_missing_tiktok_and_instagram_modules(tmp_path, monkeypatch):
    """tk_labels / ig_tokens_status musia byt definovane aj ked moduly chybaju (import zlyhal)."""
    _setup_main(monkeypatch, tmp_path, ["MindBlownDaily", "Money Glitch"])
    monkeypatch.setattr(generate, "_tiktok", None)
    monkeypatch.setattr(generate, "_instagram", None)
    by = _run_main(tmp_path)
    mb = by["MindBlownDaily"]["conn"]
    assert mb["tiktok"]["state"] == "no_token" and mb["instagram"]["state"] == "no_token"
    assert by["Money Glitch"]["conn"]["tiktok"]["state"] == "no_account"
    assert by["MindBlownDaily"]["p2"]["tiktok"] == 0 and by["MindBlownDaily"]["p2"]["instagram"] == 0


def test_main_survives_raising_tiktok_and_instagram_modules(tmp_path, monkeypatch):
    _setup_main(monkeypatch, tmp_path, ["MindBlownDaily"])

    def boom(*a, **k):
        raise RuntimeError("boom")
    for mod, fn in ((generate._tiktok, "fetch_all"), (generate._tiktok, "token_labels"),
                    (generate._instagram, "refresh_tokens"), (generate._instagram, "token_status"),
                    (generate._instagram, "fetch_all")):
        monkeypatch.setattr(mod, fn, boom)
    by = _run_main(tmp_path)
    conn = by["MindBlownDaily"]["conn"]
    assert conn["tiktok"]["state"] == "no_token" and conn["instagram"]["state"] == "no_token"
    assert by["MindBlownDaily"]["status"]["tiktok"]["state"] == "ok"


def test_main_survives_bad_return_types_from_modules(tmp_path, monkeypatch):
    _setup_main(monkeypatch, tmp_path, ["MindBlownDaily"])
    monkeypatch.setattr(generate._tiktok, "token_labels", lambda root: None)
    monkeypatch.setattr(generate._instagram, "token_status", lambda root: None)
    by = _run_main(tmp_path)
    assert "conn" in by["MindBlownDaily"]


def test_main_still_writes_data_when_annotate_accounts_fails(tmp_path, monkeypatch, capsys):
    _setup_main(monkeypatch, tmp_path, ["MindBlownDaily"])

    def boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(generate, "annotate_accounts", boom)
    by = _run_main(tmp_path)
    assert "conn" not in by["MindBlownDaily"] and by["MindBlownDaily"]["p2"]["start"] == "2026-09-28"
    assert "stav pripojenia sa nepodarilo urcit" in capsys.readouterr().out


def test_effective_status_riesit_turns_ok_when_data_flows():
    manual = {"tiktok": {"state": "riesit", "note": "chyba autorizacia"}, "instagram": {"state": "riesit", "note": "token"}}
    conn = {"tiktok": {"state": "ok", "note": ""}, "instagram": {"state": "token_error", "note": "x"}}
    out = generate.effective_status(manual, conn)
    assert out["tiktok"]["state"] == "ok" and "data" in out["tiktok"]["note"]
    assert out["instagram"] == manual["instagram"]                 # bez dat ostava TREBA RIESIT


def test_effective_status_keeps_ban_and_unused_even_with_data():
    manual = {"tiktok": {"state": "ban", "note": "b"}, "instagram": {"state": "nepouziva", "note": "n"}}
    conn = {"tiktok": {"state": "ok", "note": ""}, "instagram": {"state": "ok", "note": ""}}
    assert generate.effective_status(manual, conn) == manual


def test_annotate_accounts_coldcase_tiktok_ok_after_authorisation():
    p = {"name": "ColdCaseDaily", "yt": {"subs": 1}, "tiktok": {"followers": 0}, "instagram": None}
    generate.annotate_accounts([p], True, ["Cold Case Daily"], [])
    assert p["conn"]["tiktok"]["state"] == "ok" and p["status"]["tiktok"]["state"] == "ok"
    q = {"name": "ColdCaseDaily", "yt": {"subs": 1}, "tiktok": None, "instagram": None}
    generate.annotate_accounts([q], True, [], [])
    assert q["status"]["tiktok"]["state"] == "riesit"              # bez dat ostava rucna znacka

