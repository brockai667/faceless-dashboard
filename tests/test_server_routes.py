# -*- coding: utf-8 -*-
"""Routing: / serves the v2 dashboard. The legacy app.html was archived
(archive/app.html) and its /old route removed, so it must never be served."""
import http.client
import threading
from http.server import ThreadingHTTPServer

import pytest

import server


@pytest.fixture
def srv(tmp_path, monkeypatch):
    (tmp_path / "v2.html").write_text("<!-- V2 -->", encoding="utf-8")
    # aj keby stara verzia lezala v koreni alebo v archive/, server ju neservuje
    (tmp_path / "app.html").write_text("<!-- OLD -->", encoding="utf-8")
    (tmp_path / "archive").mkdir()
    (tmp_path / "archive" / "app.html").write_text("<!-- OLD -->", encoding="utf-8")
    monkeypatch.setattr(server, "ROOT", str(tmp_path))
    monkeypatch.setattr(server, "DASH_PASS", "")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.H)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


def _get(port, path):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request("GET", path)
    r = c.getresponse()
    body = r.read().decode("utf-8")
    c.close()
    return r.status, r.getheader("Content-Type"), body


@pytest.mark.parametrize("path", ["/", "/index.html", "/v2", "/v2.html"])
def test_root_serves_v2(srv, path):
    status, ctype, body = _get(srv, path)
    assert status == 200
    assert ctype.startswith("text/html")
    assert "V2" in body


@pytest.mark.parametrize("path", ["/old", "/old/", "/old?x=1", "/app.html", "/archive/app.html"])
def test_old_version_is_not_served(srv, path):
    status, _, body = _get(srv, path)
    assert status == 404
    assert "OLD" not in body


def _v2_html():
    import os
    return open(os.path.join(os.path.dirname(server.__file__), "v2.html"), encoding="utf-8").read()


def test_v2_has_no_links_to_old_version():
    html = _v2_html()
    assert "/old" not in html
    assert "app.html" not in html


@pytest.mark.parametrize("view", ["komentare", "spotify", "episodary"])
def test_v2_has_tool_views(view):
    """Nastroje zo starej verzie ziju v v2: polozka v navigacii + vlastny view."""
    html = _v2_html()
    assert f'<a href="#{view}" data-view="{view}">' in html
    assert f'<section class="tvw" id="{view}" hidden>' in html


def test_v2_tools_use_same_endpoints():
    html = _v2_html()
    for ep in ("/api/all_comments", "/api/reply", "/api/hide", "/api/comment_done",
               "/spotify.json", "/spotify_history.json", "/episodary.json", "/episodary_history.json"):
        assert ep in html, ep
    # komentare sa nenacitaju samy: fetch len v loadComments, ktoru vola iba tlacidlo
    assert html.count("fetch('/api/all_comments')") == 1
    assert "data-ca=\"load\"" in html


@pytest.mark.parametrize("path", ["/spotify.json", "/episodary.json"])
def test_platform_json_routes_unchanged(srv, path):
    status, ctype, body = _get(srv, path)
    assert status == 200
    assert ctype.startswith("application/json")
    assert '"configured": false' in body
