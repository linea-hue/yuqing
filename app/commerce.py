from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import uuid4

from .store import now


class CommerceError(RuntimeError):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _product(store, product_id: str) -> dict:
    row = next((item for item in store.products if item["id"] == product_id), None)
    if not row:
        raise CommerceError(404, "商品不存在")
    return row


def _order(store, order_id: str, buyer_id: str | None = None) -> dict:
    row = next((item for item in store.orders if item["id"] == order_id), None)
    if not row or (buyer_id and row.get("buyer_id") != buyer_id):
        raise CommerceError(404, "订单不存在或无权访问")
    return row


def _shop(store, shop_id: str) -> dict:
    return next((item for item in store.shops if item["id"] == shop_id), {"id": shop_id, "name": "甄选自营"})


def _line_id(product_id: str, variant: dict[str, str]) -> str:
    raw = product_id + "|" + "|".join(f"{key}={variant[key]}" for key in sorted(variant))
    return product_id + "-" + sha256(raw.encode("utf-8")).hexdigest()[:8]


def _variant(product: dict, selected: dict[str, str] | None) -> dict[str, str]:
    available = product.get("variants") or {}
    if not available:
        return {}
    selected = selected or {}
    result: dict[str, str] = {}
    for name, values in available.items():
        value = selected.get(name, values[0])
        if value not in values:
            raise CommerceError(422, f"无效规格：{name}={value}")
        result[name] = value
    unknown = set(selected) - set(available)
    if unknown:
        raise CommerceError(422, "商品不支持规格：" + "、".join(sorted(unknown)))
    return result


def reserved_stock(store, product_id: str) -> int:
    return sum(
        int(row.get("qty", 0))
        for rows in store.inventory_reservations.values()
        for row in rows
        if row.get("product_id") == product_id and row.get("status") == "active"
    )


def sellable_stock(store, product_id: str) -> int:
    product = _product(store, product_id)
    return max(0, int(product.get("stock", 0)) - reserved_stock(store, product_id))


def add_cart_line(store, buyer_id: str, product_id: str, qty: int, variant: dict[str, str] | None = None) -> dict:
    with store.lock:
        product = _product(store, product_id)
        if product.get("status", "在售") != "在售":
            raise CommerceError(409, "商品已下架")
        selected_variant = _variant(product, variant)
        line_id = _line_id(product_id, selected_variant)
        cart = store.carts.setdefault(buyer_id, [])
        found = next((row for row in cart if row.get("line_id", row["product_id"]) == line_id), None)
        target_qty = int(qty) + (int(found["qty"]) if found else 0)
        if target_qty > sellable_stock(store, product_id):
            raise CommerceError(409, "加入数量超过当前可售库存")
        if found:
            found.update({"qty": target_qty, "price": product["price"], "selected": True})
        else:
            cart.append({
                "line_id": line_id,
                "product_id": product_id,
                "sku_code": product.get("sku_code"),
                "shop_id": product.get("shop_id"),
                "name": product["name"],
                "image_url": product.get("image_url"),
                "price": product["price"],
                "qty": int(qty),
                "variant": selected_variant,
                "selected": True,
            })
    return cart_snapshot(store, buyer_id)


def _cart_line(store, buyer_id: str, line_or_product_id: str) -> dict:
    row = next(
        (
            item
            for item in store.carts.setdefault(buyer_id, [])
            if item.get("line_id", item["product_id"]) == line_or_product_id or item["product_id"] == line_or_product_id
        ),
        None,
    )
    if not row:
        raise CommerceError(404, "购物车中没有该商品")
    return row


def update_cart_line(store, buyer_id: str, line_or_product_id: str, qty: int | None = None, selected: bool | None = None) -> dict:
    with store.lock:
        row = _cart_line(store, buyer_id, line_or_product_id)
        if qty == 0:
            store.carts[buyer_id].remove(row)
        else:
            if qty is not None:
                if qty > sellable_stock(store, row["product_id"]):
                    raise CommerceError(409, "超过当前可售库存")
                row["qty"] = qty
            if selected is not None:
                row["selected"] = selected
    return cart_snapshot(store, buyer_id)


def remove_cart_line(store, buyer_id: str, line_or_product_id: str) -> dict:
    with store.lock:
        row = _cart_line(store, buyer_id, line_or_product_id)
        store.carts[buyer_id].remove(row)
    return cart_snapshot(store, buyer_id)


def cart_snapshot(store, buyer_id: str) -> dict:
    items = []
    for row in store.carts.setdefault(buyer_id, []):
        product = _product(store, row["product_id"])
        current = {
            **row,
            "line_id": row.get("line_id", row["product_id"]),
            "name": product["name"],
            "price": product["price"],
            "image_url": product.get("image_url"),
            "shop_id": product.get("shop_id"),
            "shop_name": _shop(store, product.get("shop_id", ""))["name"],
            "selected": row.get("selected", True),
            "available_stock": sellable_stock(store, product["id"]),
            "available": product.get("status", "在售") == "在售" and sellable_stock(store, product["id"]) >= int(row["qty"]),
        }
        items.append(current)
    return {
        "items": items,
        "selected_count": sum(int(row["qty"]) for row in items if row["selected"]),
        "subtotal": round(sum(float(row["price"]) * int(row["qty"]) for row in items if row["selected"]), 2),
    }


def _address(store, buyer_id: str, address_id: str | None, address_text: str | None) -> dict:
    rows = store.addresses.setdefault(buyer_id, [])
    if address_id:
        address = next((row for row in rows if row["id"] == address_id), None)
        if not address:
            raise CommerceError(404, "收货地址不存在")
        return deepcopy(address)
    if address_text:
        return {"id": "legacy-address", "label": "本次地址", "receiver": "收货人", "phone": "已保护", "address": address_text, "is_default": False}
    address = next((row for row in rows if row.get("is_default")), rows[0] if rows else None)
    if not address:
        raise CommerceError(422, "请先添加收货地址")
    return deepcopy(address)


def _eligible_coupon(store, buyer_id: str, coupon_id: str | None, items: list[dict]) -> tuple[dict | None, float]:
    if not coupon_id:
        return None, 0.0
    coupon = next((row for row in store.coupons.setdefault(buyer_id, []) if row["id"] == coupon_id), None)
    if not coupon:
        raise CommerceError(404, "优惠券不存在")
    if coupon.get("status") != "可使用":
        raise CommerceError(409, "优惠券当前不可使用")
    expiry = coupon.get("expires_at")
    if expiry and expiry < datetime.now(timezone.utc).date().isoformat():
        raise CommerceError(409, "优惠券已过期")
    scope = coupon.get("scope", "all")
    eligible = sum(
        float(row["price"]) * int(row["qty"])
        for row in items
        if scope == "all" or _product(store, row["product_id"]).get("category") == scope
    )
    if eligible < float(coupon.get("threshold", 0)):
        raise CommerceError(422, f"优惠券需满足 {coupon.get('threshold', 0):.0f} 元门槛")
    return coupon, round(min(float(coupon.get("amount", 0)), eligible), 2)


def quote(store, buyer_id: str, coupon_id: str | None = None, line_ids: list[str] | None = None) -> dict:
    snapshot = cart_snapshot(store, buyer_id)
    selected = [
        row
        for row in snapshot["items"]
        if (row["line_id"] in line_ids if line_ids is not None else row.get("selected", True))
    ]
    if not selected:
        raise CommerceError(400, "请至少勾选一件商品")
    for row in selected:
        if not row["available"]:
            raise CommerceError(409, f"商品不可结算或库存不足：{row['name']}")
    packages = []
    for shop_id in dict.fromkeys(row["shop_id"] for row in selected):
        package_items = [row for row in selected if row["shop_id"] == shop_id]
        subtotal = round(sum(float(row["price"]) * int(row["qty"]) for row in package_items), 2)
        shipping = 0.0 if subtotal >= 99 else 10.0
        packages.append({"shop_id": shop_id, "shop_name": _shop(store, shop_id)["name"], "items": package_items, "subtotal": subtotal, "shipping_fee": shipping})
    subtotal = round(sum(row["subtotal"] for row in packages), 2)
    shipping_fee = round(sum(row["shipping_fee"] for row in packages), 2)
    coupon, discount = _eligible_coupon(store, buyer_id, coupon_id, selected)
    return {
        "items": selected,
        "packages": packages,
        "amounts": {"subtotal": subtotal, "discount": discount, "shipping_fee": shipping_fee, "payable": round(max(0, subtotal + shipping_fee - discount), 2)},
        "coupon": deepcopy(coupon) if coupon else None,
    }


def checkout(
    store,
    buyer_id: str,
    *,
    address_id: str | None,
    address_text: str | None,
    payment_method: str,
    coupon_id: str | None,
    line_ids: list[str] | None,
    buyer_note: str,
    invoice: dict | None,
    idempotency_key: str | None,
) -> dict:
    if idempotency_key:
        remembered = store.recall_idempotency("checkout", idempotency_key)
        if remembered:
            return {"idempotent": True, **deepcopy(remembered)}
    with store.lock:
        result = quote(store, buyer_id, coupon_id, line_ids)
        address = _address(store, buyer_id, address_id, address_text)
        order_id = "o" + uuid4().hex[:12]
        created_at = now()
        order_items = []
        reservations = []
        for row in result["items"]:
            product = _product(store, row["product_id"])
            if sellable_stock(store, product["id"]) < int(row["qty"]):
                raise CommerceError(409, f"商品库存不足：{product['name']}")
            order_items.append({
                "line_id": row["line_id"], "product_id": product["id"], "sku_code": product.get("sku_code"),
                "shop_id": product.get("shop_id"), "name": product["name"], "image_url": product.get("image_url"),
                "variant": deepcopy(row.get("variant", {})), "price": product["price"], "qty": int(row["qty"]),
                "line_total": round(float(product["price"]) * int(row["qty"]), 2),
            })
            reservations.append({"id": "rs-" + uuid4().hex[:10], "order_id": order_id, "product_id": product["id"], "qty": int(row["qty"]), "status": "active", "created_at": created_at})
        packages = []
        for row in result["packages"]:
            packages.append({
                "id": "sub-" + uuid4().hex[:10], "shop_id": row["shop_id"], "shop_name": row["shop_name"],
                "item_line_ids": [item["line_id"] for item in row["items"]], "subtotal": row["subtotal"],
                "shipping_fee": row["shipping_fee"], "status": "待支付",
            })
        order = {
            "id": order_id, "buyer_id": buyer_id, "status": "待支付", "total": result["amounts"]["payable"],
            "amount_summary": result["amounts"], "items": order_items, "packages": packages,
            "address": address, "coupon": result["coupon"], "payment_method": payment_method,
            "buyer_note": buyer_note, "invoice": invoice, "logistics": "等待买家付款", "created_at": created_at,
            "close_at": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(),
            "timeline": [{"status": "订单已提交", "time": created_at, "description": "库存已预占，请在 30 分钟内完成支付"}],
        }
        store.orders.insert(0, order)
        store.inventory_reservations[order_id] = reservations
        if result["coupon"]:
            coupon = next(row for row in store.coupons[buyer_id] if row["id"] == result["coupon"]["id"])
            coupon.update({"status": "锁定", "locked_order_id": order_id})
        if invoice:
            store.invoices[order_id] = {"order_id": order_id, "status": "待开票", **invoice, "created_at": created_at}
        store.payments[order_id] = {"order_id": order_id, "status": "pending", "amount": order["total"], "method": payment_method, "created_at": created_at}
        selected_ids = {row["line_id"] for row in result["items"]}
        store.carts[buyer_id] = [row for row in store.carts[buyer_id] if row.get("line_id", row["product_id"]) not in selected_ids]
        store.audit_logs.append({"id": "audit-" + uuid4().hex[:10], "actor": buyer_id, "action": "checkout.created", "target_id": order_id, "created_at": created_at})
        response = {"order": order, "payment": store.payments[order_id], "reservation_count": len(reservations), "split_order_count": len(packages)}
        if idempotency_key:
            store.remember_idempotency("checkout", idempotency_key, deepcopy(response))
    store.add_event({"node": "Checkout", "status": "completed", "order_id": order_id, "amount": order["total"], "packages": len(packages), "trace_id": str(uuid4())})
    return response


def pay(store, order_id: str, buyer_id: str, idempotency_key: str | None = None) -> dict:
    if idempotency_key:
        remembered = store.recall_idempotency(f"payment:{order_id}", idempotency_key)
        if remembered:
            return {"idempotent": True, **deepcopy(remembered)}
    with store.lock:
        order = _order(store, order_id, buyer_id)
        payment = store.payments.get(order_id)
        if not payment:
            raise CommerceError(404, "支付单不存在")
        if payment.get("status") == "paid":
            return {"idempotent": True, "order": order, "payment": payment}
        if order.get("status") != "待支付":
            raise CommerceError(409, "订单当前状态不可支付")
        reservations = store.inventory_reservations.get(order_id, [])
        if reservations:
            for reservation in reservations:
                if reservation.get("status") != "active":
                    raise CommerceError(409, "订单库存预占已失效")
                product = _product(store, reservation["product_id"])
                if product["stock"] < reservation["qty"]:
                    raise CommerceError(409, f"库存扣减失败：{product['name']}")
            for reservation in reservations:
                product = _product(store, reservation["product_id"])
                before = product["stock"]
                product["stock"] -= reservation["qty"]
                reservation.update({"status": "consumed", "consumed_at": now()})
                store.inventory_ledger.append({"id": "il-" + uuid4().hex[:10], "product_id": product["id"], "order_id": order_id, "type": "sale", "change": -reservation["qty"], "before": before, "after": product["stock"], "created_at": now()})
        else:
            # 兼容升级前创建的演示订单。
            for item in order["items"]:
                product = _product(store, item["product_id"])
                if product["stock"] < item["qty"]:
                    raise CommerceError(409, f"库存不足：{product['name']}")
            for item in order["items"]:
                product = _product(store, item["product_id"])
                product["stock"] -= item["qty"]
        paid_at = now()
        payment.update({"status": "paid", "paid_at": paid_at, "transaction_id": "txn-" + uuid4().hex[:10]})
        order.update({"status": "待发货", "paid_at": paid_at, "logistics": "商家备货中"})
        for package in order.get("packages", []):
            package["status"] = "待发货"
        order.setdefault("timeline", []).append({"status": "支付成功", "time": paid_at, "description": f"交易流水 {payment['transaction_id']}"})
        coupon = order.get("coupon")
        if coupon:
            owned = next((row for row in store.coupons[buyer_id] if row["id"] == coupon["id"]), None)
            if owned and owned.get("locked_order_id") == order_id:
                owned.update({"status": "已使用", "used_at": paid_at})
        response = {"order": order, "payment": payment}
        if idempotency_key:
            store.remember_idempotency(f"payment:{order_id}", idempotency_key, deepcopy(response))
    store.add_event({"node": "Payment", "status": "completed", "order_id": order_id, "trace_id": str(uuid4())})
    return response


def cancel(store, order_id: str, buyer_id: str, reason: str = "买家主动取消") -> dict:
    with store.lock:
        order = _order(store, order_id, buyer_id)
        if order.get("status") == "已取消":
            return {"idempotent": True, "order": order, "payment": store.payments.get(order_id)}
        if order.get("status") != "待支付":
            raise CommerceError(409, "已支付订单请通过售后申请退款")
        cancelled_at = now()
        order.update({"status": "已取消", "logistics": "订单已取消", "cancel_reason": reason, "cancelled_at": cancelled_at})
        order.setdefault("timeline", []).append({"status": "订单已取消", "time": cancelled_at, "description": reason + "，库存与优惠券已释放"})
        for reservation in store.inventory_reservations.get(order_id, []):
            if reservation.get("status") == "active":
                reservation.update({"status": "released", "released_at": cancelled_at})
        payment = store.payments.get(order_id)
        if payment:
            payment["status"] = "cancelled"
        coupon = order.get("coupon")
        if coupon:
            owned = next((row for row in store.coupons[buyer_id] if row["id"] == coupon["id"]), None)
            if owned and owned.get("locked_order_id") == order_id:
                owned.update({"status": "可使用"})
                owned.pop("locked_order_id", None)
    store.add_event({"node": "OrderCancel", "status": "completed", "order_id": order_id, "trace_id": str(uuid4())})
    return {"order": order, "payment": payment}


def order_detail(store, order_id: str, buyer_id: str | None = None) -> dict:
    order = _order(store, order_id, buyer_id)
    payment = store.payments.get(order_id)
    shipment = store.shipments.get(order_id)
    return {**order, "payment": payment, "shipment": shipment, "invoice_record": store.invoices.get(order_id)}


def claim_coupon(store, buyer_id: str, template_id: str) -> dict:
    with store.lock:
        template = next((row for row in store.coupon_templates if row["id"] == template_id), None)
        if not template or template.get("status") != "发放中":
            raise CommerceError(404, "优惠券活动不存在或已结束")
        owned = store.coupons.setdefault(buyer_id, [])
        if any(row.get("template_id") == template_id for row in owned):
            raise CommerceError(409, "你已经领取过这张优惠券")
        if template.get("remaining", 0) <= 0:
            raise CommerceError(409, "优惠券已领完")
        template["remaining"] -= 1
        coupon = {"id": "cp-" + uuid4().hex[:8], "template_id": template_id, "title": template["title"], "amount": template["amount"], "threshold": template["threshold"], "scope": template.get("scope", "all"), "status": "可使用", "expires_at": template["expires_at"], "claimed_at": now()}
        owned.append(coupon)
    return coupon


def add_review(store, buyer_id: str, order_id: str, product_id: str, rating: int, content: str, images: list[str]) -> dict:
    with store.lock:
        order = _order(store, order_id, buyer_id)
        if order.get("status") not in {"已完成", "部分退款完成", "退款完成"}:
            raise CommerceError(409, "确认收货后才能评价")
        if not any(row["product_id"] == product_id for row in order.get("items", [])):
            raise CommerceError(422, "该商品不属于此订单")
        if any(row["order_id"] == order_id and row["product_id"] == product_id for row in store.reviews):
            raise CommerceError(409, "该订单商品已经评价")
        review = {"id": "rv-" + uuid4().hex[:10], "order_id": order_id, "product_id": product_id, "buyer_id": buyer_id, "rating": rating, "content": content, "images": images, "created_at": now(), "status": "已发布"}
        store.reviews.append(review)
        product = _product(store, product_id)
        old_count = int(product.get("review_count", 0))
        product["rating"] = round((float(product.get("rating", 5)) * old_count + rating) / (old_count + 1), 2)
        product["review_count"] = old_count + 1
    return review


def commerce_metrics(store) -> dict:
    paid_order_ids = {order_id for order_id, payment in store.payments.items() if payment.get("status") == "paid"}
    paid_orders = [row for row in store.orders if row["id"] in paid_order_ids or row.get("status") in {"待发货", "待收货", "已完成", "部分退款完成", "退款完成"}]
    gmv = round(sum(float(row.get("total", 0)) for row in paid_orders), 2)
    refunds = round(sum(float(row.get("amount", 0)) for row in store.refunds.values() if row.get("status") == "succeeded"), 2)
    created = len(store.orders)
    paid = len(paid_orders)
    sku_total = len(store.products)
    on_sale = sum(row.get("status", "在售") == "在售" for row in store.products)
    return {
        "gmv": gmv,
        "net_revenue": round(max(0, gmv - refunds), 2),
        "paid_orders": paid,
        "created_orders": created,
        "average_order_value": round(gmv / paid, 2) if paid else 0,
        "payment_conversion_rate": round(paid / created, 4) if created else 0,
        "refund_amount": refunds,
        "refund_rate": round(refunds / gmv, 4) if gmv else 0,
        "sku_total": sku_total,
        "on_sale_skus": on_sale,
        "off_sale_skus": sku_total - on_sale,
        "low_stock_skus": sum(sellable_stock(store, row["id"]) <= 10 for row in store.products),
        "reserved_units": sum(reserved_stock(store, row["id"]) for row in store.products),
        "shop_count": len(store.shops),
        "review_count": len(store.reviews),
    }
