"""Test doubles: fake HTTP session, fake clock, fake Woo client."""
from __future__ import annotations

class FakeResp:
    def __init__(self, status=200, text="", headers=None, json_data=None):
        self.status_code = status
        self.text = text
        self.content = text.encode()
        self.headers = headers or {}
        self._json = json_data

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


class FakeSession:
    """routes: url -> FakeResp | list[FakeResp | Exception] (consumed in order, last repeats)."""

    def __init__(self, routes):
        self.routes = {k: (list(v) if isinstance(v, list) else [v]) for k, v in routes.items()}
        self.calls = []

    def get(self, url, headers=None, timeout=None, **kw):
        self.calls.append(url)
        seq = self.routes.get(url)
        if seq is None:
            return FakeResp(404)
        item = seq.pop(0) if len(seq) > 1 else seq[0]
        if isinstance(item, Exception):
            raise item
        return item


class FakeClock:
    def __init__(self):
        self.t = 1000.0
        self.sleeps = []

    def time(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


class FakeWoo:
    """Scripted Woo client. script: list of (status, data|None); None data => echo success."""

    def __init__(self, script=None):
        self.script = list(script or [])
        self.calls = []  # (kind, parent, items)

    def _respond(self, items):
        if self.script:
            status, data = self.script.pop(0)
            if data is not None or status >= 400:
                return status, data or {}
        return 200, {"update": [{"id": i["id"]} for i in items]}

    def batch_products(self, items):
        self.calls.append(("products", None, items))
        return self._respond(items)

    def batch_variations(self, product_id, items):
        self.calls.append(("variations", product_id, items))
        return self._respond(items)
