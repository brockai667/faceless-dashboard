# -*- coding: utf-8 -*-
"""Routing: / serves the new v2 dashboard, /old keeps the legacy app.html
(comments, Spotify, Episodary tools)."""
import http.client
import threading
from http.server import ThreadingHTTPServer

import pytest

import server


@pytest.fixture
def srv(tmp_path, monkeypatch):
    (tmp_path / "v2.html").write_text("<!-- V2 -->", encoding="utf-8")
    (tmp_path / "app.html").write_text("<!-- OLD -->", encoding="utf-8")
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


@pytest.mark.parametrize("path", ["/", "/index.html", "/v2.html"])
def test_root_serves_v2(srv, path):
    status, ctype, body = _get(srv, path)
    assert status == 200
    assert ctype.startswith("text/html")
    assert "V2" in body


@pytest.mark.parametrize("path", ["/old", "/old/", "/app.html"])
def test_old_serves_legacy_app(srv, path):
    status, ctype, body = _get(srv, path)
    assert status == 200
    assert ctype.startswith("text/html")
    assert "OLD" in body


def test_old_with_query_still_legacy(srv):
    status, _, body = _get(srv, "/old?x=1")
    assert status == 200 and "OLD" in body
