# -*- coding: utf-8 -*-
"""merge_tokens.py - zlucenie tokenov (Render + lokalne) bez siete a bez schranky."""
import time

import merge_tokens as m

NOW = time.time()
D = 86400


def ig(tok, refreshed_days_ago, uid=None, days=60):
    v = {"access_token": tok, "_refreshed_at": NOW - refreshed_days_ago * D, "expires_in": days * D}
    if uid:
        v["user_id"] = uid
    return v


def test_ig_adds_new_account_and_keeps_render_ones():
    out, src = m.merge_ig({"wealth": ig("r1", 10)}, {"curi.o667": ig("l1", 0)})
    assert set(out) == {"wealth", "curi.o667"}
    assert src["wealth"] == "Render" and src["curi.o667"].startswith("lokalny (novy")


def test_ig_same_account_later_expiry_wins_both_directions():
    out, src = m.merge_ig({"acc": ig("render_old", 50)}, {"acc": ig("local_new", 0)})
    assert out["acc"]["access_token"] == "local_new" and "cerstvejsi" in src["acc"]
    out, src = m.merge_ig({"acc": ig("render_new", 1)}, {"acc": ig("local_old", 70)})   # lokalny je stary/expirovany
    assert out["acc"]["access_token"] == "render_new" and src["acc"] == "Render"


def test_ig_missing_refreshed_at_never_beats_known_expiry():
    out, _ = m.merge_ig({"acc": ig("render", 5)}, {"acc": {"access_token": "local_unknown", "expires_in": 60 * D}})
    assert out["acc"]["access_token"] == "render"


def test_ig_renamed_account_same_user_id_keeps_fresher_only():
    out, src = m.merge_ig({"th.erealspark": ig("old", 40, uid="17")}, {"mindblowndaily.official": ig("new", 0, uid="17")})
    assert list(out) == ["mindblowndaily.official"]
    assert "th.erealspark" in src["mindblowndaily.official"]


def tk(acc, ref, oid):
    return {"access_token": acc, "refresh_token": ref, "open_id": oid, "scope": "x"}


def test_tiktok_new_account_added_without_question():
    asked = []
    out, src = m.merge_tiktok({"MindBlownDaily": tk("a", "b", "o1")}, {"Cold Case Daily": tk("c", "d", "o2")},
                              lambda q: asked.append(q) or False)
    assert set(out) == {"MindBlownDaily", "Cold Case Daily"} and not asked
    assert src["Cold Case Daily"].startswith("lokalny (novy")


def test_tiktok_identical_entry_is_silent_and_conflict_asks():
    asked = []
    same = tk("a", "b", "o1")
    out, _ = m.merge_tiktok({"x": same}, {"x": dict(same)}, lambda q: asked.append(q) or True)
    assert out["x"] == same and not asked
    out, src = m.merge_tiktok({"x": tk("old", "old", "o1")}, {"x": tk("new", "new", "o1")}, lambda q: asked.append(q) or True)
    assert out["x"]["access_token"] == "new" and len(asked) == 1 and "znova" in src["x"]
    out, src = m.merge_tiktok({"x": tk("old", "old", "o1")}, {"x": tk("new", "new", "o1")}, lambda q: False)
    assert out["x"]["access_token"] == "old" and src["x"] == "Render"


def test_tiktok_same_open_id_under_new_label_replaces_old_label_when_confirmed():
    out, src = m.merge_tiktok({"insideyourmind007": tk("old", "old", "o1")}, {"MindBlownDaily": tk("new", "new", "o1")},
                              lambda q: True)
    assert list(out) == ["MindBlownDaily"] and "insideyourmind007" in src["MindBlownDaily"]


def test_summary_never_contains_token_values(capsys, monkeypatch, tmp_path):
    import json
    monkeypatch.setattr(m, "ROOT", str(tmp_path))
    (tmp_path / "ig_tokens.json").write_text(json.dumps({"curi.o667": ig("SECRET_LOCAL_TOKEN", 0)}), encoding="utf-8")
    box = {}
    monkeypatch.setattr(m, "clip_get", lambda: json.dumps({"wealth": ig("SECRET_RENDER_TOKEN", 3)}))
    monkeypatch.setattr(m, "clip_set", lambda t: box.update(v=t))
    monkeypatch.setattr(m.sys, "argv", ["merge_tokens.py", "ig"])
    assert m.main() == 0
    printed = capsys.readouterr().out
    assert "SECRET" not in printed and "curi.o667" in printed and "wealth" in printed
    assert set(json.loads(box["v"])) == {"wealth", "curi.o667"}
