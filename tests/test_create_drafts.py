"""tools/create_drafts.py: only drafts, never touches existing products, plan-only by default."""
import pytest

from create_drafts import create_drafts, draft_payload
from rtech_sync.models import Row
from rtech_sync.publisher import WooClient


class FakeShop:
    def __init__(self, existing=None, create_status=201):
        self.existing = existing or {}
        self.create_status = create_status
        self.calls = []

    def get(self, path, params=None):
        self.calls.append(("get", path, params))
        sku = params["sku"]
        return 200, ([{"id": self.existing[sku]}] if sku in self.existing else [])

    def create_product(self, payload):
        self.calls.append(("create", payload["sku"], payload))
        if self.create_status >= 400:
            return self.create_status, {}
        return self.create_status, {"id": 900 + len(self.calls), "status": payload["status"]}


def rows():
    return [Row(sku="RT-POLY-001", title="Polycab Optima+ house wire 1 sq mm Red 90 m", publish="pending_review"),
            Row(sku="RT-POLY-002", title="Polycab Etira house wire 1 sq mm Red 90 m", wc_product_id=55),
            Row(sku="RT-POLY-003", title="Polycab Primma house wire 1 sq mm Red 90 m")]


def test_payload_is_a_hidden_unpriced_draft():
    p = draft_payload(rows()[0])
    assert p["status"] == "draft" and p["regular_price"] == "" and p["stock_status"] == "outofstock"
    assert p["sku"] == "RT-POLY-001" and p["name"].startswith("Polycab Optima+")


def test_plan_only_makes_no_shop_calls():
    shop, rs = FakeShop(), rows()
    out = create_drafts(rs, ["RT-POLY-001", "RT-POLY-002", "RT-X"], shop, apply=False, sleep=lambda s: None)
    assert out == [("RT-POLY-001", "would_create_draft", None), ("RT-POLY-002", "already_linked", 55),
                   ("RT-X", "not_in_catalogue", None)]
    assert shop.calls == [] and rs[0].wc_product_id is None


def test_apply_creates_drafts_and_links_existing_skus_without_changing_them():
    shop, rs = FakeShop(existing={"RT-POLY-003": 77}), rows()
    out = create_drafts(rs, ["RT-POLY-001", "RT-POLY-003"], shop, apply=True, sleep=lambda s: None)
    assert out[0][1] == "created_draft" and rs[0].wc_product_id == out[0][2]
    assert out[1] == ("RT-POLY-003", "exists_in_shop_linked", 77) and rs[2].wc_product_id == 77
    creates = [c for c in shop.calls if c[0] == "create"]
    assert [c[1] for c in creates] == ["RT-POLY-001"] and creates[0][2]["status"] == "draft"


def test_failed_create_leaves_the_row_unlinked():
    shop, rs = FakeShop(create_status=429), rows()
    out = create_drafts(rs, ["RT-POLY-001"], shop, apply=True, sleep=lambda s: None)
    assert out == [("RT-POLY-001", "create_failed_http_429", None)] and rs[0].wc_product_id is None


def test_client_refuses_anything_but_a_draft():
    c = WooClient("https://shop.example", "k", "s", session=object())
    with pytest.raises(ValueError):
        c.create_product({"sku": "X", "status": "publish"})
