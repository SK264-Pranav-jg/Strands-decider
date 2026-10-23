from datetime import date

import pytest

from support.store import Store

ME, OTHER = "C-1001", "C-1002"


@pytest.fixture
def store():
    return Store(today=date(2026, 10, 23))


def test_list_orders_only_returns_own_orders(store):
    ids = {o["order_id"] for o in store.list_orders(ME)}
    assert ids == {"A-1042", "A-1057", "A-1031", "A-0988", "A-1012"}


def test_other_customers_order_looks_missing(store):
    for call in (store.get_order, store.track_shipment, store.cancel_order, store.refund_status):
        assert "error" in call(ME, "A-1050")
    assert store.return_eligibility(ME, "A-1033", "EB-110")["eligible"] is False
    assert store.orders["A-1050"]["status"] == "shipped"


def test_ids_are_normalised(store):
    assert store.get_order(ME, " a-1042 ")["order_id"] == "A-1042"
    assert store.check_stock("hp-200")["in_stock"] is True


def test_cancel_only_before_shipping(store):
    assert store.cancel_order(ME, "A-1057")["status"] == "cancelled"
    assert store.orders["A-1057"]["status"] == "cancelled"
    assert "error" in store.cancel_order(ME, "A-1057")
    assert "error" in store.cancel_order(ME, "A-1042")


def test_return_window_and_duplicates(store):
    assert store.return_eligibility(ME, "A-1031", "HP-200")["eligible"] is True
    assert "outside" in store.return_eligibility(ME, "A-0988", "LP-14")["reason"]
    assert "already exists" in store.return_eligibility(ME, "A-1031", "PB-20")["reason"]
    assert "not part" in store.return_eligibility(ME, "A-1031", "MN-270")["reason"]
    assert "only delivered" in store.return_eligibility(ME, "A-1042", "MN-270")["reason"]


def test_create_return_then_refund_status(store):
    created = store.create_return(ME, "A-1031", "HP-200", "stopped charging")
    assert created["status"] == "pickup_scheduled" and created["refund_amount"] == 7999
    assert "error" in store.create_return(ME, "A-1031", "HP-200", "again")
    skus = {r["sku"] for r in store.refund_status(ME, "A-1031")["refunds"]}
    assert skus == {"HP-200", "PB-20"}


def test_sessions_do_not_share_data():
    a, b = Store(), Store()
    a.cancel_order(ME, "A-1057")
    assert b.orders["A-1057"]["status"] == "processing"


def test_search_products(store):
    hits = store.search_products("27 inch monitor", max_price=25000)
    assert hits[0]["sku"] == "MN-270"
    assert all(h["price"] <= 25000 for h in hits)
    assert store.check_stock("EB-110")["expected_restock"] == "2026-10-29"
