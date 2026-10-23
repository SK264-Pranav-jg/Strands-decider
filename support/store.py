"""In-memory mock data for Acme Electronics, a fictional online store.

Every query and mutation takes the signed-in customer's id, so one customer can never read
or change another customer's orders. Each session gets its own copy of the seed data, so a
cancel or return in one session does not affect another.

The demo has one signed-in customer. The other customers can't sign in: their orders are
there so that asking for one (A-1050, A-1033, A-1060) shows the tools can't reach it.
"""

import copy
from datetime import date, timedelta

RETURN_WINDOW_DAYS = 30

SIGNED_IN_CUSTOMER_ID = "C-1001"

CUSTOMERS = {
    "C-1001": {"id": "C-1001", "name": "Priya Nair", "city": "Bengaluru"},
    "C-1002": {"id": "C-1002", "name": "Arjun Mehta", "city": "Pune"},
    "C-1003": {"id": "C-1003", "name": "Sara Thomas", "city": "Kochi"},
}

PRODUCTS = {
    "HP-200": {"name": "Acme Pulse ANC headphones", "category": "audio", "price": 7999, "stock": 14,
               "description": "Over-ear wireless headphones with active noise cancelling and 40 hour battery."},
    "EB-110": {"name": "Acme Buds Lite earbuds", "category": "audio", "price": 2499, "stock": 0, "restock_in_days": 6,
               "description": "Compact true wireless earbuds with a charging case."},
    "MN-270": {"name": "Vista 27-inch 4K monitor", "category": "monitors", "price": 24990, "stock": 5,
               "description": "27 inch 4K IPS monitor with USB-C 65W charging and height adjustable stand."},
    "MN-240": {"name": "Vista 24-inch FHD monitor", "category": "monitors", "price": 11490, "stock": 22,
               "description": "24 inch full HD IPS monitor, 75Hz, HDMI and DisplayPort."},
    "KB-87": {"name": "Keyflow mechanical keyboard", "category": "accessories", "price": 5499, "stock": 9,
              "description": "Tenkeyless mechanical keyboard with hot swappable switches."},
    "MS-30": {"name": "Glide wireless mouse", "category": "accessories", "price": 1799, "stock": 40,
              "description": "Silent wireless mouse with USB-C charging."},
    "LP-14": {"name": "Acme Book 14 laptop", "category": "laptops", "price": 64990, "stock": 3,
              "description": "14 inch laptop, 16GB RAM, 512GB SSD, 1.3kg."},
    "PB-20": {"name": "Volt 20000mAh power bank", "category": "accessories", "price": 2999, "stock": 18,
              "description": "20000mAh power bank with 22.5W fast charging."},
    "SW-5": {"name": "Pace smartwatch", "category": "wearables", "price": 12999, "stock": 0, "restock_in_days": 14,
             "description": "Fitness smartwatch with GPS, heart rate and 7 day battery."},
    "CH-65": {"name": "65W USB-C charger", "category": "accessories", "price": 1999, "stock": 30,
              "description": "Compact 65W GaN charger for laptops and phones."},
}


def _seed(today: date) -> dict:
    """Orders and returns with dates relative to `today`, so the return window stays meaningful."""
    d = lambda days: (today - timedelta(days=days)).isoformat()  # noqa: E731
    later = lambda days: (today + timedelta(days=days)).isoformat()  # noqa: E731
    orders = {
        "A-1042": {"customer_id": "C-1001", "status": "shipped", "placed": d(3), "items": [("MN-270", 1)],
                   "shipment": {"carrier": "BlueDart", "tracking": "BD7731904IN", "eta": later(2),
                                "events": [(d(3), "Order placed"), (d(2), "Packed at Bengaluru warehouse"),
                                           (d(1), "In transit to Bengaluru hub")]}},
        "A-1057": {"customer_id": "C-1001", "status": "processing", "placed": d(0),
                   "items": [("KB-87", 1), ("MS-30", 1)]},
        "A-1031": {"customer_id": "C-1001", "status": "delivered", "placed": d(14), "delivered": d(10),
                   "items": [("HP-200", 1), ("PB-20", 1)]},
        "A-0988": {"customer_id": "C-1001", "status": "delivered", "placed": d(50), "delivered": d(45),
                   "items": [("LP-14", 1)]},
        "A-1012": {"customer_id": "C-1001", "status": "delivered", "placed": d(30), "delivered": d(25),
                   "items": [("CH-65", 1)]},
        "A-1050": {"customer_id": "C-1002", "status": "shipped", "placed": d(2), "items": [("SW-5", 1)],
                   "shipment": {"carrier": "Delhivery", "tracking": "DL55120387", "eta": later(3),
                                "events": [(d(2), "Order placed"), (d(1), "Shipped from Pune warehouse")]}},
        "A-1033": {"customer_id": "C-1002", "status": "delivered", "placed": d(8), "delivered": d(5),
                   "items": [("EB-110", 2)]},
        "A-1060": {"customer_id": "C-1003", "status": "processing", "placed": d(1), "items": [("MN-240", 1)]},
    }
    returns = {
        "R-501": {"order_id": "A-1012", "sku": "CH-65", "reason": "Stopped working", "status": "refunded",
                  "created": d(20), "refund_amount": 1999, "refunded_on": d(16)},
        "R-502": {"order_id": "A-1031", "sku": "PB-20", "reason": "Does not hold charge", "status": "refund_processing",
                  "created": d(4), "refund_amount": 2999, "refund_eta": later(3)},
    }
    return {"orders": orders, "returns": returns, "products": copy.deepcopy(PRODUCTS)}


class Store:
    def __init__(self, today: date | None = None):
        self.today = today or date.today()
        data = _seed(self.today)
        self.orders: dict = data["orders"]
        self.returns: dict = data["returns"]
        self.products: dict = data["products"]

    # ---- orders ----

    def _order(self, customer_id: str, order_id: str) -> dict | None:
        order = self.orders.get(order_id)
        # another customer's order looks exactly like one that doesn't exist
        return order if order and order["customer_id"] == customer_id else None

    def _items(self, order: dict) -> list[dict]:
        return [{"sku": sku, "name": self.products[sku]["name"], "qty": qty, "price": self.products[sku]["price"]}
                for sku, qty in order["items"]]

    def _summary(self, order_id: str, order: dict) -> dict:
        items = self._items(order)
        out = {"order_id": order_id, "status": order["status"], "placed": order["placed"],
               "items": items, "total": sum(i["price"] * i["qty"] for i in items)}
        if "delivered" in order:
            out["delivered"] = order["delivered"]
        return out

    def list_orders(self, customer_id: str) -> list[dict]:
        found = [self._summary(oid, o) for oid, o in self.orders.items() if o["customer_id"] == customer_id]
        return sorted(found, key=lambda o: o["placed"], reverse=True)

    def get_order(self, customer_id: str, order_id: str) -> dict:
        order_id = order_id.strip().upper()
        order = self._order(customer_id, order_id)
        if not order:
            return {"error": f"No order {order_id} found for this customer."}
        out = self._summary(order_id, order)
        out["returns"] = [{"return_id": rid, **r} for rid, r in self.returns.items() if r["order_id"] == out["order_id"]]
        return out

    def track_shipment(self, customer_id: str, order_id: str) -> dict:
        order_id = order_id.strip().upper()
        order = self._order(customer_id, order_id)
        if not order:
            return {"error": f"No order {order_id} found for this customer."}
        if order["status"] == "processing":
            return {"order_id": order_id, "status": "processing", "note": "Not shipped yet. It usually ships within 1 to 2 days."}
        if order["status"] in ("delivered", "cancelled"):
            return {"order_id": order_id, "status": order["status"], "delivered": order.get("delivered")}
        s = order["shipment"]
        return {"order_id": order_id, "status": order["status"], "carrier": s["carrier"], "tracking": s["tracking"],
                "eta": s["eta"], "events": [{"date": d, "event": e} for d, e in s["events"]]}

    def cancel_order(self, customer_id: str, order_id: str) -> dict:
        order_id = order_id.strip().upper()
        order = self._order(customer_id, order_id)
        if not order:
            return {"error": f"No order {order_id} found for this customer."}
        if order["status"] != "processing":
            return {"error": f"Order {order_id} is {order['status']} and can no longer be cancelled. "
                             "Once delivered it can be returned instead."}
        order["status"] = "cancelled"
        total = sum(i["price"] * i["qty"] for i in self._items(order))
        return {"order_id": order_id, "status": "cancelled", "refund_amount": total,
                "note": "Refund goes back to the original payment method in 3 to 5 business days."}

    # ---- returns and refunds ----

    def return_eligibility(self, customer_id: str, order_id: str, sku: str) -> dict:
        order_id = order_id.strip().upper()
        sku = sku.strip().upper()
        order = self._order(customer_id, order_id)
        if not order:
            return {"eligible": False, "reason": f"No order {order_id} found for this customer."}
        if sku not in dict(order["items"]):
            return {"eligible": False, "reason": f"{sku} is not part of order {order_id}."}
        if order["status"] != "delivered":
            return {"eligible": False, "reason": f"Order {order_id} is {order['status']}; only delivered items can be returned."}
        if any(r["order_id"] == order_id and r["sku"] == sku for r in self.returns.values()):
            return {"eligible": False, "reason": f"A return for {sku} on order {order_id} already exists."}
        age = (self.today - date.fromisoformat(order["delivered"])).days
        if age > RETURN_WINDOW_DAYS:
            return {"eligible": False, "reason": f"Delivered {age} days ago, outside the {RETURN_WINDOW_DAYS} day return window."}
        return {"eligible": True, "days_left": RETURN_WINDOW_DAYS - age, "refund_amount": self.products[sku]["price"]}

    def create_return(self, customer_id: str, order_id: str, sku: str, reason: str) -> dict:
        order_id, sku = order_id.strip().upper(), sku.strip().upper()
        check = self.return_eligibility(customer_id, order_id, sku)
        if not check["eligible"]:
            return {"error": check["reason"]}
        return_id = f"R-{501 + len(self.returns)}"
        self.returns[return_id] = {
            "order_id": order_id, "sku": sku, "reason": reason,
            "status": "pickup_scheduled", "created": self.today.isoformat(),
            "refund_amount": check["refund_amount"],
            "pickup_date": (self.today + timedelta(days=2)).isoformat(),
        }
        return {"return_id": return_id, **self.returns[return_id],
                "note": "Refund is issued within 5 business days of pickup."}

    def refund_status(self, customer_id: str, order_id: str) -> dict:
        order_id = order_id.strip().upper()
        order = self._order(customer_id, order_id)
        if not order:
            return {"error": f"No order {order_id} found for this customer."}
        found = [{"return_id": rid, **r} for rid, r in self.returns.items() if r["order_id"] == order_id]
        if not found:
            return {"order_id": order_id, "refunds": [], "note": "No returns or refunds on this order."}
        return {"order_id": order_id, "refunds": found}

    # ---- catalogue (not customer specific) ----

    def search_products(self, query: str, max_price: int | None = None) -> list[dict]:
        words = [w for w in query.lower().split() if len(w) > 2]
        hits = []
        for sku, p in self.products.items():
            text = f"{p['name']} {p['category']} {p['description']}".lower()
            score = sum(w.rstrip("s") in text for w in words)
            if (score or not words) and (max_price is None or p["price"] <= max_price):
                hits.append((score, {"sku": sku, "name": p["name"], "price": p["price"], "in_stock": p["stock"] > 0}))
        return [h for _, h in sorted(hits, key=lambda h: -h[0])][:5]

    def get_product(self, sku: str) -> dict:
        sku = sku.strip().upper()
        p = self.products.get(sku)
        return {"sku": sku, **p} if p else {"error": f"No product with SKU {sku}."}

    def check_stock(self, sku: str) -> dict:
        sku = sku.strip().upper()
        p = self.products.get(sku)
        if not p:
            return {"error": f"No product with SKU {sku}."}
        out = {"sku": sku, "in_stock": p["stock"] > 0, "units": p["stock"]}
        if p["stock"] == 0 and "restock_in_days" in p:
            out["expected_restock"] = (self.today + timedelta(days=p["restock_in_days"])).isoformat()
        return out
