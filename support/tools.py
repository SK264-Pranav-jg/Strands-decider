"""Specialist tools, bound to one session's store and its signed-in customer.

The customer id is captured in the closure, never taken from the model, so no prompt can
make a tool read or change another customer's data.
"""

from strands import tool

from support.store import Store


def build_tools(store: Store, customer_id: str) -> dict[str, list]:
    """The tool list for each specialist, keyed by specialist name."""

    @tool
    def list_my_orders() -> list[dict]:
        """List the signed-in customer's orders, newest first, with status, items and totals."""
        return store.list_orders(customer_id)

    @tool
    def get_order(order_id: str) -> dict:
        """Get one of the customer's orders with its items, status and any returns.

        Args:
            order_id: Order id such as A-1042.
        """
        return store.get_order(customer_id, order_id)

    @tool
    def track_shipment(order_id: str) -> dict:
        """Get the carrier, tracking number, expected delivery date and tracking events of an order.

        Args:
            order_id: Order id such as A-1042.
        """
        return store.track_shipment(customer_id, order_id)

    @tool
    def cancel_order(order_id: str) -> dict:
        """Cancel an order that has not shipped yet. Only call this when the customer asked to cancel.

        Args:
            order_id: Order id such as A-1057.
        """
        return store.cancel_order(customer_id, order_id)

    @tool
    def check_return_eligibility(order_id: str, sku: str) -> dict:
        """Check whether an item from an order can be returned (delivered, within 30 days, not already returned).

        Args:
            order_id: Order id such as A-1031.
            sku: Product SKU of the item, such as HP-200.
        """
        return store.return_eligibility(customer_id, order_id, sku)

    @tool
    def create_return(order_id: str, sku: str, reason: str) -> dict:
        """Open a return and schedule a pickup. Only call this when the customer asked to return the item.

        Args:
            order_id: Order id such as A-1031.
            sku: Product SKU of the item, such as HP-200.
            reason: The customer's reason for the return, in a few words.
        """
        return store.create_return(customer_id, order_id, sku, reason)

    @tool
    def get_refund_status(order_id: str) -> dict:
        """Get the returns and refunds on an order and where each refund stands.

        Args:
            order_id: Order id such as A-1012.
        """
        return store.refund_status(customer_id, order_id)

    @tool
    def search_products(query: str, max_price: int | None = None) -> list[dict]:
        """Search the catalogue by keywords. Returns up to 5 products with SKU, price in rupees and stock.

        Args:
            query: Keywords such as "27 inch monitor" or "noise cancelling headphones".
            max_price: Optional highest price in rupees.
        """
        return store.search_products(query, max_price)

    @tool
    def get_product(sku: str) -> dict:
        """Get the full details of a product.

        Args:
            sku: Product SKU such as MN-270.
        """
        return store.get_product(sku)

    @tool
    def check_stock(sku: str) -> dict:
        """Check whether a product is in stock and, if not, when it is expected back.

        Args:
            sku: Product SKU such as EB-110.
        """
        return store.check_stock(sku)

    return {
        "orders_agent": [list_my_orders, get_order, track_shipment, cancel_order],
        "returns_agent": [get_order, check_return_eligibility, create_return, get_refund_status],
        "products_agent": [search_products, get_product, check_stock],
    }
