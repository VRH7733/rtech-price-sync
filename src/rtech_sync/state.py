"""data/latest.json: what we last published per SKU (the bot's memory)."""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from .models import PriceState


def load_state(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        return {"version": 1, "items": {}}
    data = json.loads(p.read_text(encoding="utf-8"))
    data.setdefault("items", {})
    return data


def get_price_state(state: dict, sku: str) -> PriceState:
    item = state["items"].get(sku)
    if not item:
        return PriceState()
    return PriceState(
        price=Decimal(item["price"]) if item.get("price") not in (None, "") else None,
        last_ok=date.fromisoformat(item["last_ok"]) if item.get("last_ok") else None,
        hidden=bool(item.get("hidden", False)),
        first_seen=date.fromisoformat(item["first_seen"]) if item.get("first_seen") else None,
    )


def set_item(state: dict, sku: str, **fields) -> None:
    item = state["items"].setdefault(sku, {})
    for k, v in fields.items():
        item[k] = str(v) if isinstance(v, Decimal) else v


def save_state(path: str | Path, state: dict, today: date) -> None:
    state["updated"] = today.isoformat()
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(p)
