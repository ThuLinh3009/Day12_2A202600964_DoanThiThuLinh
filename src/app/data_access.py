from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.tools import tool


class ShoppingDataStore:
    """Mock-data lookup store with in-memory indexes."""

    def __init__(self, json_path: Path) -> None:
        raw = json.loads(json_path.read_text(encoding="utf-8"))
        self.metadata = raw.get("metadata", {})
        self._customers: list[dict] = raw.get("customers", [])
        self._orders: list[dict] = raw.get("orders", [])
        self._vouchers: list[dict] = raw.get("vouchers", [])

        # Build indexes
        self._customer_by_id: dict[str, dict] = {c["customer_id"]: c for c in self._customers}
        self._order_by_id: dict[str, dict] = {str(o["order_id"]): o for o in self._orders}
        self._orders_by_customer: dict[str, list[dict]] = {}
        for o in self._orders:
            cid = o.get("customer_id", "")
            self._orders_by_customer.setdefault(cid, []).append(o)
        self._vouchers_by_customer: dict[str, list[dict]] = {}
        for v in self._vouchers:
            cid = v.get("customer_id", "")
            self._vouchers_by_customer.setdefault(cid, []).append(v)

    def get_customer_by_id(self, customer_id: str) -> dict[str, Any]:
        customer = self._customer_by_id.get(customer_id.strip().upper())
        if customer is None:
            return {"status": "not_found", "customer_id": customer_id}
        return {"status": "ok", "customer": customer}

    def get_orders_by_customer_id(self, customer_id: str, limit: int = 10) -> dict[str, Any]:
        cid = customer_id.strip().upper()
        orders = self._orders_by_customer.get(cid, [])
        if not orders:
            return {"status": "not_found", "customer_id": cid}
        sorted_orders = sorted(orders, key=lambda o: o.get("created_at", ""), reverse=True)
        return {"status": "ok", "customer_id": cid, "orders": sorted_orders[:limit]}

    def get_order_detail_by_order_id(self, order_id: str) -> dict[str, Any]:
        order = self._order_by_id.get(str(order_id).strip())
        if order is None:
            return {"status": "not_found", "order_id": order_id}
        return {"status": "ok", "order": order}

    def get_vouchers_by_customer_id(
        self,
        customer_id: str,
        only_active: bool = False,
    ) -> dict[str, Any]:
        cid = customer_id.strip().upper()
        vouchers = self._vouchers_by_customer.get(cid, [])
        if only_active:
            vouchers = [v for v in vouchers if v.get("status") == "active" and v.get("remaining_uses", 0) > 0]
        if not vouchers:
            return {"status": "not_found", "customer_id": cid}
        return {"status": "ok", "customer_id": cid, "vouchers": vouchers}


def build_data_tools(store: ShoppingDataStore) -> list:
    @tool
    def get_customer_by_id(customer_id: str) -> str:
        """Tra cứu thông tin khách hàng theo customer_id (ví dụ: C001).
        Trả về thông tin tier, hạn mức voucher, tổng đơn hàng."""
        result = store.get_customer_by_id(customer_id)
        return json.dumps(result, ensure_ascii=False)

    @tool
    def get_orders_by_customer_id(customer_id: str) -> str:
        """Lấy danh sách đơn hàng gần nhất của khách hàng theo customer_id (ví dụ: C001).
        Trả về tối đa 10 đơn hàng mới nhất, bao gồm trạng thái và thông tin giao hàng."""
        result = store.get_orders_by_customer_id(customer_id)
        return json.dumps(result, ensure_ascii=False)

    @tool
    def get_order_detail_by_order_id(order_id: str) -> str:
        """Lấy chi tiết một đơn hàng cụ thể theo order_id (ví dụ: 1971, 2058).
        Trả về trạng thái đơn, thời gian giao hàng, khả năng hoàn trả, thông tin vận chuyển."""
        result = store.get_order_detail_by_order_id(order_id)
        return json.dumps(result, ensure_ascii=False)

    @tool
    def get_vouchers_by_customer_id(customer_id: str) -> str:
        """Lấy danh sách voucher của khách hàng theo customer_id (ví dụ: C001).
        Trả về tất cả voucher bao gồm trạng thái, loại giảm giá và số lần sử dụng còn lại."""
        result = store.get_vouchers_by_customer_id(customer_id)
        return json.dumps(result, ensure_ascii=False)

    return [get_customer_by_id, get_orders_by_customer_id, get_order_detail_by_order_id, get_vouchers_by_customer_id]
