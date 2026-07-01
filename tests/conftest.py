# -*- coding: utf-8 -*-
"""Shared fixtures. Adds repo root to sys.path so `import generate` etc. work
regardless of how pytest is invoked, and guarantees no test ever touches the
network or the real (secret) token/cache files on disk."""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Fail loudly if a test accidentally reaches for the real network."""
    import urllib.request

    def _boom(*a, **k):
        raise AssertionError("urllib.request.urlopen called without being mocked")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)


@pytest.fixture
def tmp_root(tmp_path):
    """An isolated fake project root with no real secrets in it."""
    return tmp_path


def make_response(payload):
    """Build a fake object mimicking what urlopen(...).read().decode() needs."""
    body = json.dumps(payload).encode("utf-8")

    class _Resp:
        def read(self):
            return body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    return _Resp()
