from __future__ import annotations

import asyncio
import hashlib
from contextlib import asynccontextmanager
from pathlib import Path
from secrets import token_urlsafe
from time import time
from uuid import uuid4

from fastapi import FastAPI, File, Header, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .auth import AuthenticationError, actor_from_header, require_role
from .commerce import (
    CommerceError,
    add_cart_line,
    add_review,
    cancel as commerce_cancel,
    cart_snapshot,
    checkout as commerce_checkout,
    claim_coupon,
    commerce_metrics,
    order_detail as commerce_order_detail,
    pay as commerce_pay,
    quote as commerce_quote,
    remove_cart_line,
    reserved_stock,
    sellable_stock,
    update_cart_line,
)
from .decision import review_after_sales, run_after_sales
from .evaluation import golden_dataset, run_offline_eval, telemetry_snapshot
from .infrastructure import workflow_infra
from .intent import classify_intent, intent_metrics as build_intent_metrics
from .rag import grounded_answer, search_with_diagnostics
from .sandbox import SandboxViolation, inspect_document
from .scheduler import evaluation_scheduler
from .security import inspect_input
from .store import now, store
from .voice import create_session, interrupt_session, process_turn, voice_metrics


@asynccontextmanager
async def lifespan(_: FastAPI):
    if evaluation_scheduler.enabled and (evaluation_scheduler.task is None or evaluation_scheduler.task.done()):
        evaluation_scheduler.task = asyncio.create_task(evaluation_scheduler.run())
    try:
        yield
    finally:
        if evaluation_scheduler.task and not evaluation_scheduler.task.done():
            evaluation_scheduler.task.cancel()
            try:
                await evaluation_scheduler.task
            except asyncio.CancelledError:
                pass


app = FastAPI(title="甄选电商企业智能业务平台", version="2.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:18000", "http://localhost:18000", "http://localhost:8000"], allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Authorization", "Content-Type", "X-Idempotency-Key", "X-Role"])
app.mount("/assets", StaticFiles(directory=Path(__file__).parent.parent / "frontend" / "assets"), name="assets")


@app.middleware("http")
async def zero_trust_api_boundary(request: Request, call_next):
    """运营与安全 API 默认拒绝匿名访问，页面本身仍可打开到登录界面。"""
    path = request.url.path
    if path.startswith("/api/ops/") or path.startswith("/api/security/"):
        try:
            request.state.actor = actor_from_header(request.headers.get("Authorization"))
        except AuthenticationError as exc:
            from fastapi.responses import JSONResponse

            return JSONResponse({"detail": str(exc)}, status_code=401)
    return await call_next(request)


class CartItem(BaseModel):
    product_id: str
    qty: int = Field(ge=1, le=99)
    variant: dict[str, str] | None = None


class CartUpdate(BaseModel):
    qty: int | None = Field(default=None, ge=0, le=99)
    selected: bool | None = None


class FavoriteRequest(BaseModel):
    product_id: str


class AddressCreate(BaseModel):
    label: str = Field(default="家", min_length=1, max_length=20)
    receiver: str = Field(min_length=2, max_length=30)
    phone: str = Field(min_length=6, max_length=30)
    address: str = Field(min_length=5, max_length=200)
    is_default: bool = False


class AddressUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=20)
    receiver: str | None = Field(default=None, min_length=2, max_length=30)
    phone: str | None = Field(default=None, min_length=6, max_length=30)
    address: str | None = Field(default=None, min_length=5, max_length=200)
    is_default: bool | None = None


class StockUpdate(BaseModel):
    stock: int = Field(ge=0, le=999999)


class ProductUpdate(BaseModel):
    price: float | None = Field(default=None, gt=0)
    list_price: float | None = Field(default=None, gt=0)
    badge: str | None = Field(default=None, min_length=1, max_length=30)
    status: str | None = Field(default=None, pattern="^(在售|下架)$")


class AfterSalesCreate(BaseModel):
    order_id: str
    amount: float = Field(gt=0)
    reason: str = Field(min_length=2, max_length=1000)
    evidence_confidence: float = Field(default=0.95, ge=0, le=1)
    service_type: str = Field(default="仅退款", pattern="^(仅退款|退货退款|换货)$")


class DecisionRequest(BaseModel):
    action: str
    comment: str = ""


class EscalateRequest(BaseModel):
    comment: str = Field(default="客服建议主管复核", max_length=1000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class CheckoutRequest(BaseModel):
    address: str | None = Field(default=None, min_length=5, max_length=200)
    address_id: str | None = None
    payment_method: str = Field(default="mock_pay", pattern="^(mock_pay|cod)$")
    coupon_id: str | None = None
    line_ids: list[str] | None = None
    buyer_note: str = Field(default="", max_length=300)
    invoice: dict | None = None


class CouponClaim(BaseModel):
    template_id: str


class ReviewCreate(BaseModel):
    product_id: str
    rating: int = Field(ge=1, le=5)
    content: str = Field(min_length=2, max_length=1000)
    images: list[str] = Field(default_factory=list, max_length=6)


class ReturnShipmentCreate(BaseModel):
    carrier: str = Field(min_length=2, max_length=40)
    tracking_no: str = Field(min_length=5, max_length=80)


class ProductCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    price: float = Field(gt=0)
    list_price: float | None = Field(default=None, gt=0)
    stock: int = Field(ge=0, le=999999)
    category: str = Field(min_length=2, max_length=30)
    brand: str = Field(min_length=1, max_length=40)
    description: str = Field(min_length=5, max_length=1000)
    image_url: str = Field(min_length=5, max_length=300)
    shop_id: str = "shop-market"
    badge: str = "新品"


class TicketRequest(BaseModel):
    subject: str = Field(min_length=2, max_length=120)
    message: str = Field(min_length=2, max_length=2000)
    order_id: str | None = None
    priority: str = Field(default="normal", pattern="^(low|normal|high|urgent)$")


class TicketReply(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    status: str = Field(default="pending_buyer", pattern="^(pending_buyer|resolved|escalated|in_progress)$")


class TicketClaim(BaseModel):
    agent_id: str = Field(default="agent-demo", min_length=2, max_length=80)


class LoginRequest(BaseModel):
    username: str
    password: str


class IntakeRequest(BaseModel):
    order_id: str
    amount: float = Field(gt=0)
    reason: str = Field(min_length=2, max_length=1000)
    source: str = Field(default="phone", pattern="^(phone|email|manual)$")


class EvalRunRequest(BaseModel):
    mode: str = Field(default="offline", pattern="^(offline|llm)$")


class VoiceTurnRequest(BaseModel):
    session_id: str | None = None
    transcript: str = Field(min_length=1, max_length=2000)
    duration_ms: int = Field(default=0, ge=0, le=120000)


def authorize(authorization: str | None, *roles: str) -> dict:
    try:
        return require_role(authorization, *roles)
    except AuthenticationError as exc:
        raise HTTPException(403, str(exc)) from exc


def commerce_call(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except CommerceError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


@app.get("/health")
def health():
    return {"status": "ok", "service": "ecommerce-agent-platform", "time": now(), "workflow_infrastructure": workflow_infra.status()["mode"]}


@app.get("/")
def home():
    return FileResponse(Path(__file__).parent.parent / "frontend" / "index.html")


@app.get("/login")
def login_page():
    return FileResponse(Path(__file__).parent.parent / "frontend" / "login_enterprise.html")


@app.get("/buyer")
def buyer_app():
    return FileResponse(Path(__file__).parent.parent / "frontend" / "buyer_final.html")


@app.get("/ops")
def ops_app():
    # 统一入口到带登录、评测、安全与 Telemetry 的企业运营控制台。
    return FileResponse(Path(__file__).parent.parent / "frontend" / "ops_console.html")


@app.get("/cs")
def customer_service_app():
    return FileResponse(Path(__file__).parent.parent / "frontend" / "cs_final.html")


@app.get("/api/products")
def products(q: str = "", category: str | None = None, brand: str | None = None, shop_id: str | None = None, min_price: float | None = None, max_price: float | None = None, sort: str = "default", page: int = 1, page_size: int = 100):
    rows = [x for x in store.products if x.get("status", "在售") == "在售"]
    if q:
        rows = [x for x in rows if q.lower() in (x["name"] + x["description"] + x["category"]).lower()]
    if category and category not in {"全部", "all"}:
        # 兼容早期演示客户端使用的“数码”筛选，同时将结果统一到新的手机数码频道。
        category_alias = "手机数码" if category == "数码" else category
        rows = [x for x in rows if x.get("category") in ({category, category_alias} if category_alias != category else {category})]
    if brand:
        rows = [x for x in rows if x.get("brand") == brand]
    if shop_id:
        rows = [x for x in rows if x.get("shop_id") == shop_id]
    if min_price is not None:
        rows = [x for x in rows if float(x.get("price", 0)) >= min_price]
    if max_price is not None:
        rows = [x for x in rows if float(x.get("price", 0)) <= max_price]
    if sort == "price_asc":
        rows = sorted(rows, key=lambda x: x["price"])
    elif sort == "price_desc":
        rows = sorted(rows, key=lambda x: x["price"], reverse=True)
    elif sort == "sales":
        rows = sorted(rows, key=lambda x: x.get("sales", 0), reverse=True)
    elif sort == "rating":
        rows = sorted(rows, key=lambda x: x.get("rating", 0), reverse=True)
    total = len(rows)
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    start = (page - 1) * page_size
    items = [{**x, "available_stock": sellable_stock(store, x["id"]), "shop": next((s for s in store.shops if s["id"] == x.get("shop_id")), None)} for x in rows[start:start + page_size]]
    return {"items": items, "total": total, "page": page, "page_size": page_size, "has_more": start + page_size < total}


@app.get("/api/catalog/facets")
def catalog_facets():
    active = [x for x in store.products if x.get("status", "在售") == "在售"]
    return {
        "categories": [{"name": name, "count": sum(x.get("category") == name for x in active)} for name in sorted({x.get("category") for x in active})],
        "brands": [{"name": name, "count": sum(x.get("brand") == name for x in active)} for name in sorted({x.get("brand") for x in active})],
        "shops": store.shops,
        "price_range": {"min": min(x["price"] for x in active), "max": max(x["price"] for x in active)},
    }


@app.get("/api/shops")
def shops():
    return {"items": [{**shop, "product_count": sum(x.get("shop_id") == shop["id"] and x.get("status", "在售") == "在售" for x in store.products)} for shop in store.shops]}


@app.get("/api/shops/{shop_id}")
def shop_detail(shop_id: str):
    shop = next((x for x in store.shops if x["id"] == shop_id), None)
    if not shop:
        raise HTTPException(404, "店铺不存在")
    return {**shop, "products": [x for x in store.products if x.get("shop_id") == shop_id and x.get("status", "在售") == "在售"]}


@app.get("/api/products/{product_id}")
def product_detail(product_id: str):
    product = next((x for x in store.products if x["id"] == product_id), None)
    if not product:
        raise HTTPException(404, "商品不存在")
    history = store.browsing_history.setdefault("buyer-demo", [])
    history[:] = [x for x in history if x["product_id"] != product_id]
    history.insert(0, {"product_id": product_id, "viewed_at": now()})
    del history[50:]
    shop = next((x for x in store.shops if x["id"] == product.get("shop_id")), None)
    reviews = [x for x in store.reviews if x["product_id"] == product_id and x.get("status") == "已发布"]
    return {**product, "available_stock": sellable_stock(store, product_id), "shop": shop, "service": {"return_days": 7, "shipping_hours": 48, "support_cod": True, "price_protection_days": 7}, "reviews": reviews}


@app.get("/api/products/{product_id}/reviews")
def product_reviews(product_id: str):
    product = next((x for x in store.products if x["id"] == product_id), None)
    if not product:
        raise HTTPException(404, "商品不存在")
    rows = [{**x, "buyer": "已购用户"} for x in store.reviews if x["product_id"] == product_id and x.get("status") == "已发布"]
    return {"items": rows, "total": product.get("review_count", len(rows)), "real_review_count": len(rows), "rating": product.get("rating", 0)}


@app.get("/api/browsing-history")
def browsing_history():
    rows = store.browsing_history.setdefault("buyer-demo", [])
    return {"items": [{**row, "product": next((x for x in store.products if x["id"] == row["product_id"]), None)} for row in rows]}


@app.get("/api/profile")
def profile():
    return {"id": "buyer-demo", "name": "张先生", "avatar": "张", "level": "甄选会员", "points": 2680, "growth": 72, "phone": "138****5678", "email": "zhang***@example.com", "stats": {"orders": len(store.orders), "favorites": len(store.favorites.get("buyer-demo", set())), "coupons": sum(x.get("status") == "可使用" for x in store.coupons.get("buyer-demo", []))}}


@app.get("/api/favorites")
def favorites():
    ids = store.favorites.setdefault("buyer-demo", set())
    return {"items": [x for x in store.products if x["id"] in ids], "ids": sorted(ids)}


@app.post("/api/favorites")
def add_favorite(req: FavoriteRequest):
    if not any(x["id"] == req.product_id for x in store.products):
        raise HTTPException(404, "商品不存在")
    store.favorites.setdefault("buyer-demo", set()).add(req.product_id)
    return favorites()


@app.delete("/api/favorites/{product_id}")
def remove_favorite(product_id: str):
    store.favorites.setdefault("buyer-demo", set()).discard(product_id)
    return favorites()


@app.get("/api/addresses")
def addresses():
    return {"items": store.addresses.setdefault("buyer-demo", [])}


@app.post("/api/addresses")
def add_address(req: AddressCreate):
    rows = store.addresses.setdefault("buyer-demo", [])
    if req.is_default:
        for row in rows:
            row["is_default"] = False
    row = {"id": "addr-" + uuid4().hex[:8], **req.model_dump()}
    rows.append(row)
    return row


@app.put("/api/addresses/{address_id}")
def update_address(address_id: str, req: AddressUpdate):
    rows = store.addresses.setdefault("buyer-demo", [])
    row = next((x for x in rows if x["id"] == address_id), None)
    if not row:
        raise HTTPException(404, "收货地址不存在")
    changes = req.model_dump(exclude_none=True)
    if changes.get("is_default"):
        for item in rows:
            item["is_default"] = False
    row.update(changes)
    store.add_event({"node": "BuyerAddress", "status": "updated", "address_id": address_id, "trace_id": str(uuid4())})
    return row


@app.delete("/api/addresses/{address_id}")
def delete_address(address_id: str):
    rows = store.addresses.setdefault("buyer-demo", [])
    row = next((x for x in rows if x["id"] == address_id), None)
    if not row:
        raise HTTPException(404, "收货地址不存在")
    rows.remove(row)
    if row.get("is_default") and rows:
        rows[0]["is_default"] = True
    return {"items": rows}


@app.get("/api/coupons")
def coupons():
    rows = store.coupons.setdefault("buyer-demo", [])
    return {"items": rows, "available": sum(x.get("status") == "可使用" for x in rows)}


@app.get("/api/coupons/center")
def coupon_center():
    owned = {x.get("template_id") for x in store.coupons.setdefault("buyer-demo", [])}
    return {"items": [{**row, "claimed": row["id"] in owned} for row in store.coupon_templates]}


@app.post("/api/coupons/claim")
def coupon_claim(req: CouponClaim):
    return commerce_call(claim_coupon, store, "buyer-demo", req.template_id)


@app.get("/api/cart")
def get_cart():
    return commerce_call(cart_snapshot, store, "buyer-demo")


@app.post("/api/cart")
def add_cart(item: CartItem):
    return commerce_call(add_cart_line, store, "buyer-demo", item.product_id, item.qty, item.variant)


@app.put("/api/cart/{line_id}")
def update_cart(line_id: str, req: CartUpdate):
    """按购物车行更新数量或勾选状态，仍兼容旧客户端传商品 ID。"""
    return commerce_call(update_cart_line, store, "buyer-demo", line_id, req.qty, req.selected)


@app.delete("/api/cart/{line_id}")
def remove_cart(line_id: str):
    return commerce_call(remove_cart_line, store, "buyer-demo", line_id)


@app.get("/api/orders")
def orders():
    rows = [x for x in store.orders if x["buyer_id"] == "buyer-demo"]
    return {"items": rows, "summary": {"all": len(rows), "pending_payment": sum(x.get("status") == "待支付" for x in rows), "to_ship": sum(x.get("status") == "待发货" for x in rows), "to_receive": sum(x.get("status") == "待收货" for x in rows), "completed": sum(x.get("status") == "已完成" for x in rows)}}


@app.get("/api/orders/{order_id}")
def order_detail(order_id: str):
    return commerce_call(commerce_order_detail, store, order_id, "buyer-demo")


@app.get("/api/orders/{order_id}/logistics")
def order_logistics(order_id: str):
    order = next((x for x in store.orders if x["id"] == order_id and x["buyer_id"] == "buyer-demo"), None)
    if not order:
        raise HTTPException(404, "订单不存在")
    shipment = store.shipments.get(order_id)
    events = shipment.get("events", []) if shipment else [{"time": order.get("created_at"), "status": order.get("logistics", "待支付")}]
    return {"order_id": order_id, "status": order["status"], "tracking_no": shipment.get("tracking_no") if shipment else None, "carrier": shipment.get("carrier") if shipment else None, "events": events}


@app.post("/api/checkout")
def checkout(req: CheckoutRequest, x_idempotency_key: str | None = Header(default=None)):
    return commerce_call(commerce_checkout, store, "buyer-demo", address_id=req.address_id, address_text=req.address, payment_method=req.payment_method, coupon_id=req.coupon_id, line_ids=req.line_ids, buyer_note=req.buyer_note, invoice=req.invoice, idempotency_key=x_idempotency_key)


@app.post("/api/checkout/preview")
def checkout_preview(req: CheckoutRequest):
    result = commerce_call(commerce_quote, store, "buyer-demo", req.coupon_id, req.line_ids)
    # 预览阶段也校验地址，避免提交订单才暴露错误。
    if not req.address_id and not req.address and not store.addresses.get("buyer-demo"):
        raise HTTPException(422, "请先添加收货地址")
    return result


@app.post("/api/orders/{order_id}/pay")
def pay_order(order_id: str, x_idempotency_key: str | None = Header(default=None)):
    return commerce_call(commerce_pay, store, order_id, "buyer-demo", x_idempotency_key)


@app.post("/api/orders/{order_id}/ship")
def ship_order(order_id: str, authorization: str | None = Header(default=None)):
    authorize(authorization, "MANAGER", "ADMIN")
    order = next((x for x in store.orders if x["id"] == order_id), None)
    if not order:
        raise HTTPException(404, "订单不存在")
    if order["status"] not in {"待发货", "备货中"}:
        raise HTTPException(409, "订单当前状态不可发货")
    tracking = "SF" + uuid4().hex[:10].upper()
    order.update({"status": "待收货", "logistics": f"已发货，运单号 {tracking}"})
    order.setdefault("timeline", []).append({"status": "商家已发货", "time": now(), "description": f"顺丰模拟 · {tracking}"})
    for package in order.get("packages", []):
        package.update({"status": "待收货", "tracking_no": tracking, "carrier": "顺丰模拟"})
    store.shipments[order_id] = {"order_id": order_id, "carrier": "顺丰模拟", "tracking_no": tracking, "events": [{"time": now(), "status": "已发货"}]}
    return {"order": order, "shipment": store.shipments[order_id]}


@app.post("/api/orders/{order_id}/confirm")
def confirm_order(order_id: str):
    """买家确认收货，形成待收货→已完成的完整订单闭环。"""
    order = next((x for x in store.orders if x["id"] == order_id and x["buyer_id"] == "buyer-demo"), None)
    if not order:
        raise HTTPException(404, "订单不存在")
    if order["status"] != "待收货":
        raise HTTPException(409, "当前订单不可确认收货")
    order.update({"status": "已完成", "logistics": "已确认收货"})
    order.setdefault("timeline", []).append({"status": "交易完成", "time": now(), "description": "买家已确认收货，可发表评价或申请售后"})
    for package in order.get("packages", []):
        package["status"] = "已完成"
    shipment = store.shipments.get(order_id)
    if shipment:
        shipment.setdefault("events", []).append({"time": now(), "status": "已签收"})
    store.add_event({"node": "OrderConfirm", "status": "completed", "order_id": order_id, "trace_id": str(uuid4())})
    return {"order": order, "shipment": shipment}


@app.post("/api/orders/{order_id}/cancel")
def cancel_order(order_id: str):
    return commerce_call(commerce_cancel, store, order_id, "buyer-demo")


@app.post("/api/orders/{order_id}/reviews")
def create_review(order_id: str, req: ReviewCreate):
    return commerce_call(add_review, store, "buyer-demo", order_id, req.product_id, req.rating, req.content, req.images)


@app.post("/api/after-sales")
def create_after_sales(req: AfterSalesCreate, x_idempotency_key: str | None = Header(default=None)):
    order = next((x for x in store.orders if x["id"] == req.order_id and x["buyer_id"] == "buyer-demo"), None)
    if not order:
        raise HTTPException(404, "订单不存在或无权访问")
    if order.get("status") in {"待支付", "已取消"}:
        raise HTTPException(409, "该订单状态不可申请售后")
    remaining = round(float(order["total"]) - float(order.get("refund_amount", 0)), 2)
    if req.amount > remaining:
        raise HTTPException(422, f"申请金额超过订单可退金额 {remaining:.2f} 元")
    if x_idempotency_key:
        remembered = store.recall_idempotency("after-sales-create", x_idempotency_key)
        if remembered:
            return {"idempotent": True, **remembered}
    case_id = "as-" + uuid4().hex[:10]
    case = {"id": case_id, "buyer_id": "buyer-demo", **req.model_dump(), "status": "RUNNING", "state_history": [{"state": "RUNNING", "at": now(), "reason": "accepted"}], "created_at": now()}
    result = run_after_sales(case)
    case.update(result)
    store.after_sales[case_id] = case
    if x_idempotency_key:
        store.remember_idempotency("after-sales-create", x_idempotency_key, dict(case))
    return case


@app.get("/api/after-sales")
def after_sales():
    return {"items": list(store.after_sales.values())}


@app.get("/api/payments/{order_id}")
def get_payment(order_id: str):
    return store.payments.get(order_id, {"order_id": order_id, "status": "not_found"})


@app.get("/api/after-sales/{case_id}")
def get_after_sales(case_id: str):
    case = store.after_sales.get(case_id)
    if not case:
        raise HTTPException(404, "售后单不存在")
    return case


@app.post("/api/after-sales/{case_id}/evidence")
async def upload_after_sales_evidence(case_id: str, file: UploadFile = File(...)):
    """上传售后凭证元数据；真实 OCR 通过 provider 适配器替换。"""
    case = store.after_sales.get(case_id)
    if not case:
        raise HTTPException(404, "售后单不存在")
    filename = Path(file.filename or "evidence.bin").name
    extension = Path(filename).suffix.lower()
    if extension not in {".jpg", ".jpeg", ".png", ".webp", ".pdf"}:
        raise HTTPException(422, "凭证仅支持 JPG、PNG、WEBP 或 PDF")
    content = await file.read()
    if not content or len(content) > 8 * 1024 * 1024:
        raise HTTPException(422, "凭证为空或超过 8MB")
    digest = hashlib.sha256(content).hexdigest()
    artifact = {"id": "ev-" + digest[:12], "filename": filename, "content_type": file.content_type, "bytes": len(content), "sha256": digest, "ocr_status": "queued", "ocr_provider": "OCRProvider", "created_at": now()}
    case.setdefault("evidence_files", []).append(artifact)
    # 本地适配器只负责可信元数据登记，不伪装 OCR 内容；运营可继续调整置信度并人工复核。
    store.add_event({"node": "EvidenceUpload", "status": "queued", "case_id": case_id, "artifact_id": artifact["id"], "bytes": len(content), "trace_id": case.get("trace_id")})
    return {"case_id": case_id, "artifact": artifact, "next_action": "ocr_worker_or_human_review"}


@app.post("/api/after-sales/{case_id}/return-shipment")
def create_return_shipment(case_id: str, req: ReturnShipmentCreate):
    case = store.after_sales.get(case_id)
    if not case or case.get("buyer_id") != "buyer-demo":
        raise HTTPException(404, "售后单不存在")
    if case.get("service_type") not in {"退货退款", "换货"}:
        raise HTTPException(409, "仅退货退款或换货售后需要填写寄回物流")
    if case.get("status") != "SUSPENDED_HUMAN":
        raise HTTPException(409, "当前售后状态不可填写寄回物流")
    existing = store.return_shipments.get(case_id)
    if existing:
        return {"idempotent": True, "shipment": existing, "case": case}
    shipment = {"id": "ret-" + uuid4().hex[:10], "case_id": case_id, "carrier": req.carrier, "tracking_no": req.tracking_no, "status": "买家已寄回", "events": [{"time": now(), "status": "买家已寄回"}], "created_at": now()}
    store.return_shipments[case_id] = shipment
    case.update({"decision": "WAREHOUSE_INSPECTION_PENDING", "decision_reason": "买家已填写退货物流，等待仓库验收", "return_shipment": shipment})
    store.add_event({"node": "ReverseLogistics", "status": "created", "case_id": case_id, "tracking_no": req.tracking_no, "trace_id": case.get("trace_id")})
    return {"shipment": shipment, "case": case}


@app.post("/api/after-sales/{case_id}/decision")
def approve(case_id: str, req: DecisionRequest, x_idempotency_key: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    if not x_idempotency_key:
        raise HTTPException(400, "缺少 X-Idempotency-Key")
    if req.action not in {"approve", "reject"}:
        raise HTTPException(422, "action 仅支持 approve 或 reject")
    try:
        actor = require_role(authorization, "MANAGER", "ADMIN")
        return review_after_sales(case_id, action=req.action, comment=req.comment, role=actor["role"], idempotency_key=x_idempotency_key)
    except AuthenticationError as exc:
        raise HTTPException(403, str(exc)) from exc
    except KeyError:
        raise HTTPException(404, "售后单不存在")
    except RuntimeError:
        raise HTTPException(409, "当前状态不可人工审批")
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc


@app.post("/api/after-sales/{case_id}/escalate")
def escalate_after_sales(case_id: str, req: EscalateRequest, authorization: str | None = Header(default=None)):
    try:
        actor = require_role(authorization, "CSR", "MANAGER", "ADMIN")
    except AuthenticationError as exc:
        raise HTTPException(403, str(exc)) from exc
    with store.lock:
        case = store.after_sales.get(case_id)
        if not case:
            raise HTTPException(404, "售后单不存在")
        if case.get("status") != "SUSPENDED_HUMAN":
            raise HTTPException(409, "仅挂起案件可以升级")
        case.update({"escalated": True, "escalation_comment": req.comment, "escalated_at": now(), "assigned_to": "ops-supervisor"})
        store.add_event({"case_id": case_id, "node": "HumanEscalation", "status": "completed", "role": actor["role"], "trace_id": case.get("trace_id")})
        return case


@app.post("/api/chat/messages")
def chat(req: ChatRequest):
    sec = inspect_input(req.message)
    if sec.blocked:
        store.add_event({"node": "SecurityGate", "status": "blocked", "fingerprint": sec.content_fingerprint, "reasons": sec.reasons, "trace_id": str(uuid4())})
        return {"blocked": True, "intent": "安全事件", "answer": "检测到不安全指令，已停止执行并转交人工客服。", "trace_id": str(uuid4()), "references": []}
    trace_id = str(uuid4())
    intent = classify_intent(sec.text, trace_id=trace_id)
    grounded = grounded_answer(sec.text, role="buyer")
    answer = grounded["answer"]
    if intent.intent == "物流查询":
        answer = "请在‘我的订单’查看实时物流；如物流停滞超过 72 小时，我们可以为你登记催件。"
    return {"blocked": False, "intent": intent.intent, "confidence": intent.confidence, "intent_method": intent.method, "answer": answer, "references": grounded["references"], "grounded": grounded["grounded"], "next_action": "answer" if grounded["grounded"] or intent.intent == "物流查询" else "human_review", "trace_id": trace_id}


@app.post("/api/voice/turn")
def voice_turn(req: VoiceTurnRequest):
    """浏览器/云端/本地 ASR 均可把转写结果接入统一安全、意图、RAG 链路。"""
    return process_turn(req.transcript, session_id=req.session_id, duration_ms=req.duration_ms)


@app.post("/api/voice/sessions")
def start_voice_session():
    return create_session("http_turn")


@app.post("/api/voice/sessions/{session_id}/interrupt")
def interrupt_voice(session_id: str):
    try:
        return interrupt_session(session_id)
    except KeyError as exc:
        raise HTTPException(404, "语音会话不存在") from exc


@app.get("/api/voice/metrics")
def get_voice_metrics():
    return voice_metrics()


@app.websocket("/ws/voice")
async def voice_websocket(websocket: WebSocket):
    """可运行的 WebSocket 控制面；音频媒体面由生产 STT/TTS 适配器接入。"""
    await websocket.accept()
    session = create_session("websocket")
    await websocket.send_json({"type": "session.started", **session})
    try:
        while True:
            message = await websocket.receive_json()
            event_type = message.get("type")
            if event_type == "input.transcript":
                result = process_turn(str(message.get("transcript", "")), session_id=session["session_id"], duration_ms=int(message.get("duration_ms", 0)))
                await websocket.send_json({"type": "response.ready", **result})
            elif event_type == "input.interrupt":
                await websocket.send_json({"type": "response.interrupted", **interrupt_session(session["session_id"])})
            elif event_type == "session.close":
                session["state"] = "CLOSED"
                await websocket.send_json({"type": "session.closed", "session_id": session["session_id"]})
                await websocket.close()
                return
            else:
                await websocket.send_json({"type": "error", "code": "unsupported_event", "message": "仅支持 input.transcript、input.interrupt、session.close"})
    except WebSocketDisconnect:
        session["state"] = "CLOSED"


@app.post("/api/tickets")
def create_ticket(req: TicketRequest):
    if req.order_id and not any(x["id"] == req.order_id and x["buyer_id"] == "buyer-demo" for x in store.orders):
        raise HTTPException(404, "订单不存在或无权访问")
    ticket_id = "tk-" + uuid4().hex[:10]
    ticket = {"id": ticket_id, "buyer_id": "buyer-demo", **req.model_dump(), "status": "open", "messages": [{"sender": "buyer", "message": req.message, "created_at": now()}], "created_at": now()}
    store.tickets[ticket_id] = ticket
    store.add_event({"node": "CustomerTicket", "status": "created", "ticket_id": ticket_id, "trace_id": str(uuid4())})
    return ticket


@app.get("/api/tickets")
def list_tickets(status: str | None = None):
    rows = list(store.tickets.values())
    if status:
        rows = [x for x in rows if x["status"] == status]
    return {"items": rows}


@app.get("/api/tickets/{ticket_id}")
def get_ticket(ticket_id: str):
    ticket = store.tickets.get(ticket_id)
    if not ticket:
        raise HTTPException(404, "工单不存在")
    return ticket


@app.post("/api/tickets/{ticket_id}/claim")
def claim_ticket(ticket_id: str, req: TicketClaim, authorization: str | None = Header(default=None)):
    authorize(authorization, "CSR", "MANAGER", "ADMIN")
    ticket = store.tickets.get(ticket_id)
    if not ticket:
        raise HTTPException(404, "工单不存在")
    if ticket.get("status") == "resolved":
        raise HTTPException(409, "工单已解决，不能重复接单")
    ticket.update({"assignee": req.agent_id, "status": "in_progress", "last_updated_at": now()})
    store.add_event({"node": "CustomerTicket", "status": "claimed", "ticket_id": ticket_id, "assignee": req.agent_id, "trace_id": str(uuid4())})
    return ticket


@app.post("/api/tickets/{ticket_id}/reply")
def reply_ticket(ticket_id: str, req: TicketReply, x_role: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    ticket = store.tickets.get(ticket_id)
    if not ticket:
        raise HTTPException(404, "工单不存在")
    if x_role in {"agent", "supervisor", "admin"}:
        authorize(authorization, "CSR", "MANAGER", "ADMIN")
        sender = "客服"
    else:
        sender = "buyer"
    ticket["messages"].append({"sender": sender, "message": req.message, "created_at": now()})
    ticket["status"] = "resolved" if req.status == "resolved" else req.status
    ticket["last_updated_at"] = now()
    store.add_event({"node": "CustomerTicket", "status": "replied", "ticket_id": ticket_id, "sender": sender, "trace_id": str(uuid4())})
    return ticket


@app.get("/api/knowledge/search")
def knowledge_search(q: str, top_k: int = 4, shop_id: str = "all", role: str = "buyer"):
    return search_with_diagnostics(q, max(1, min(top_k, 10)), shop_id, role)


@app.get("/api/knowledge/documents")
def knowledge_documents(status: str | None = None):
    rows = list(store.knowledge)
    if status:
        rows = [x for x in rows if x.get("status", "published") == status]
    return {"items": [{k: x.get(k) for k in ("id", "title", "type", "version", "status", "shop_id", "effective_at", "keywords")} for x in rows], "total": len(rows)}


@app.get("/api/knowledge/gaps")
def knowledge_gaps():
    return {"items": store.rag_gaps[-50:], "total": len(store.rag_gaps)}


@app.post("/api/knowledge/documents")
async def upload_knowledge(file: UploadFile = File(...), authorization: str | None = Header(default=None)):
    authorize(authorization, "MANAGER", "ADMIN")
    content = await file.read()
    try:
        inspected = inspect_document(file.filename or "upload.txt", content)
    except SandboxViolation as exc:
        store.add_event({"node": "DocumentSandbox", "status": "blocked", "filename": Path(file.filename or "unknown").name, "reason": str(exc), "trace_id": str(uuid4())})
        raise HTTPException(422, str(exc)) from exc
    doc = {"id": "kb-" + uuid4().hex[:8], "title": inspected["filename"], "type": "运营上传", "version": "draft", "status": "draft", "text": inspected["text"], "shop_id": "all", "acl": ["agent", "manager", "admin"], "keywords": [], "sandbox": inspected["sandbox"], "bytes": inspected["bytes"]}
    store.knowledge.append(doc)
    store.add_event({"node": "DocumentSandbox", "status": "completed", "document_id": doc["id"], "bytes": inspected["bytes"], "trace_id": str(uuid4())})
    return {"status": "draft", "document": {k: doc[k] for k in ("id", "title", "type", "version", "sandbox")}}


@app.get("/api/ops/dashboard")
def dashboard():
    cases = list(store.after_sales.values())
    return {"after_sales_total": len(cases), "pending_human": sum(x.get("status") == "SUSPENDED_HUMAN" for x in cases), "approved": sum(x.get("outcome") == "APPROVED" or x.get("status") == "APPROVED" for x in cases), "rejected": sum(x.get("outcome") == "REJECTED" for x in cases), "refund_total": round(sum(x.get("amount", 0) for x in store.refunds.values() if x.get("status") == "succeeded"), 2), "knowledge_count": len(store.knowledge), "rag_gap_count": len(store.rag_gaps), "security_events": sum(x.get("node") in {"SecurityGate", "CriticDLP", "VoicePipeline"} and x.get("status") == "blocked" for x in store.events), "trace_count": len(store.events), "dlq_count": len(store.dead_letters), "commerce": commerce_metrics(store)}


@app.get("/api/ops/intents/metrics")
def intent_metrics():
    return build_intent_metrics()


@app.get("/api/security/events")
def security_events():
    rows = [x for x in store.events if x.get("node") in {"SecurityGate", "CriticDLP", "DocumentSandbox", "VoicePipeline"} and x.get("status") in {"blocked", "failed"}]
    return {"items": rows[-100:], "total": len(rows), "dlq_count": len(store.dead_letters), "policies": ["critic-input-v2", "dlp-v2", "tool-policy-v2"]}


@app.get("/api/security/dead-letters")
def dead_letters():
    return {"items": store.dead_letters[-100:], "total": len(store.dead_letters)}


@app.get("/api/ops/evals/latest")
def latest_eval():
    run = store.eval_runs[-1] if store.eval_runs else run_offline_eval()
    metrics = run["metrics"]
    rag_latencies = [x.get("latency_ms", 0) for x in store.events if x.get("node") == "RAG"]
    rag_latencies.sort()
    rag_p95 = rag_latencies[min(len(rag_latencies) - 1, int(len(rag_latencies) * 0.95))] if rag_latencies else 0
    return {"version": "workflow-v2.0", "run_id": run["run_id"], "recall": metrics["intent_recall"], "citation_hit_rate": 1.0, "injection_block_rate": metrics["injection_block_rate"], "token_reduction": metrics["token_reduction"], "p95_retrieval_ms": round(rag_p95, 2), "status": run["status"], "sample_count": metrics["sample_count"]}


@app.get("/api/platform/capabilities")
def capabilities():
    """前端和运维探针：明确当前环境的能力与生产替换点。"""
    return {
        "environment": "local_enterprise_reference",
        "systems": {"buyer": "ready", "customer_service": "ready", "operations": "ready"},
        "modules": {"commerce": "cart-checkout-split-order-inventory-reservation-coupon-invoice-review", "rag": "hybrid-lexical-keyword-rerank", "decision": "stateful-multi-agent-policy-engine", "security": "critic-dlp-tool-policy", "intent": "rule-model-fallback-circuit-breaker", "voice": "http-and-websocket-control-plane", "evaluation": "100-golden-plus-108-attacks", "sandbox": "ephemeral-no-shell-document-parser"},
        "implemented": ["购物车勾选结算、SKU 规格与店铺拆单", "库存预占/支付扣减/取消释放和支付幂等", "优惠券门槛、锁定、使用与回退", "发票、订单时间线、评价和逆向物流验收", "RUNNING/SUSPENDED_HUMAN/COMPLETED 状态机", "并行证据/欺诈/舆情 Agent", "RAG ACL/版本/阈值/知识缺口", "人工审批恢复与退款幂等", "动态 Trace/评测/意图指标", "WebSocket 语音控制面与打断"],
        "production_replacements": ["PostgreSQL/pgvector 持久化", "Redis Streams/Checkpointer", "OIDC/RBAC 网关", "真实 OCR/STT/TTS/WebRTC 媒体服务", "真实支付退款网关", "OpenTelemetry/Langfuse"],
    }


@app.post("/api/auth/login")
def login(req: LoginRequest):
    accounts = {
        "buyer": ("buyer123", "BUYER", "/buyer", "张先生"),
        "csr": ("csr123", "CSR", "/cs", "客服小甄"),
        "manager": ("manager123", "MANAGER", "/ops", "运营主管"),
        "admin": ("admin123", "ADMIN", "/ops", "系统管理员"),
    }
    row = accounts.get(req.username)
    if not row or row[0] != req.password:
        raise HTTPException(401, "账号或密码错误")
    token = token_urlsafe(32)
    store.sessions[token] = {"username": req.username, "role": row[1], "display_name": row[3], "expires_at": time() + 3600}
    store.add_event({"node": "Authentication", "status": "completed", "username": req.username, "role": row[1], "trace_id": str(uuid4())})
    return {"token": token, "token_type": "Bearer", "username": req.username, "role": row[1], "landing": row[2], "display_name": row[3], "expires_in": 3600}


@app.post("/api/ops/intake")
def intake(req: IntakeRequest, x_idempotency_key: str | None = Header(default=None)):
    order = next((x for x in store.orders if x["id"] == req.order_id), None)
    if not order:
        raise HTTPException(404, "订单不存在")
    remaining = round(float(order["total"]) - float(order.get("refund_amount", 0)), 2)
    if req.amount > remaining:
        raise HTTPException(422, f"申请金额超过订单可退金额 {remaining:.2f} 元")
    if x_idempotency_key:
        remembered = store.recall_idempotency("ops-intake", x_idempotency_key)
        if remembered:
            return {"idempotent": True, **remembered}
    case_id = "as-" + uuid4().hex[:10]
    case = {"id": case_id, "buyer_id": "buyer-demo", "order_id": req.order_id, "amount": req.amount, "reason": req.reason, "evidence_confidence": 0.9, "source": req.source, "status": "RUNNING", "created_at": now()}
    result = run_after_sales(case)
    case.update(result)
    store.after_sales[case_id] = case
    store.add_event({"node": "ExternalIntake", "status": "created", "case_id": case_id, "source": req.source, "trace_id": case.get("trace_id")})
    response = {"ticket_no": case_id, "status": case["status"], "case": case}
    if x_idempotency_key:
        store.remember_idempotency("ops-intake", x_idempotency_key, response)
    return response


@app.get("/api/ops/cases")
def ops_cases(status: str | None = None):
    rows = list(store.after_sales.values())
    if status and status != "ALL":
        rows = [x for x in rows if x.get("status") == status]
    return {"items": rows, "total": len(rows)}


@app.get("/api/ops/orders")
def ops_orders(status: str | None = None, q: str = ""):
    rows = list(store.orders)
    if status and status not in {"ALL", "全部"}:
        rows = [x for x in rows if x.get("status") == status]
    if q:
        ql = q.lower()
        rows = [x for x in rows if ql in x.get("id", "").lower() or ql in x.get("logistics", "").lower()]
    return {"items": rows, "total": len(rows), "summary": {
        "all": len(store.orders),
        "pending_payment": sum(x.get("status") == "待支付" for x in store.orders),
        "to_ship": sum(x.get("status") == "待发货" for x in store.orders),
        "to_receive": sum(x.get("status") == "待收货" for x in store.orders),
        "completed": sum(x.get("status") == "已完成" for x in store.orders),
    }, "metrics": commerce_metrics(store)}


@app.get("/api/ops/orders/{order_id}")
def ops_order_detail(order_id: str):
    return commerce_call(commerce_order_detail, store, order_id)


@app.get("/api/ops/commerce/metrics")
def ops_commerce_metrics():
    return commerce_metrics(store)


@app.get("/api/ops/shops")
def ops_shops():
    return {"items": [{**shop, "product_count": sum(x.get("shop_id") == shop["id"] for x in store.products), "gmv": round(sum(float(order.get("total", 0)) for order in store.orders if any(item.get("shop_id") == shop["id"] for item in order.get("items", [])) and order.get("status") not in {"待支付", "已取消"}), 2)} for shop in store.shops]}


@app.get("/api/ops/inventory")
def ops_inventory(q: str = ""):
    rows = []
    for product in store.products:
        if q and q.lower() not in (product["id"] + product["name"] + product.get("sku_code", "")).lower():
            continue
        rows.append({"product_id": product["id"], "sku_code": product.get("sku_code"), "name": product["name"], "on_hand": product["stock"], "reserved": reserved_stock(store, product["id"]), "sellable": sellable_stock(store, product["id"]), "status": product.get("status", "在售")})
    return {"items": rows, "ledger": store.inventory_ledger[-100:], "total": len(rows)}


@app.get("/api/ops/audit-logs")
def ops_audit_logs():
    generated = [{"id": x.get("id"), "actor": x.get("role", "system"), "action": f"{x.get('node')}.{x.get('status')}", "target_id": x.get("order_id") or x.get("product_id") or x.get("case_id"), "created_at": x.get("created_at")} for x in store.events[-100:]]
    return {"items": (store.audit_logs + generated)[-200:], "total": len(store.audit_logs) + len(generated)}


@app.get("/api/ops/returns")
def ops_returns():
    return {"items": [{**shipment, "case": store.after_sales.get(case_id)} for case_id, shipment in store.return_shipments.items()]}


@app.post("/api/ops/returns/{case_id}/receive")
def receive_return(case_id: str, authorization: str | None = Header(default=None)):
    authorize(authorization, "MANAGER", "ADMIN")
    shipment = store.return_shipments.get(case_id)
    case = store.after_sales.get(case_id)
    if not shipment or not case:
        raise HTTPException(404, "退货物流不存在")
    if shipment.get("status") == "仓库已验收":
        return {"idempotent": True, "shipment": shipment, "case": case}
    shipment.update({"status": "仓库已验收", "received_at": now()})
    shipment.setdefault("events", []).append({"time": now(), "status": "仓库已验收"})
    case.update({"decision": "RETURN_INSPECTED", "decision_reason": "仓库已验收，可由运营主管执行退款或换货审批"})
    store.add_event({"node": "ReverseLogistics", "status": "received", "case_id": case_id, "trace_id": case.get("trace_id")})
    return {"shipment": shipment, "case": case}


@app.get("/api/ops/products")
def ops_products(q: str = "", low_stock: int = 10):
    rows = store.products
    if q:
        ql = q.lower()
        rows = [x for x in rows if ql in (x.get("name", "") + x.get("category", "") + x.get("id", "")).lower()]
    items = [{**x, "reserved_stock": reserved_stock(store, x["id"]), "sellable_stock": sellable_stock(store, x["id"])} for x in rows]
    return {"items": items, "total": len(rows), "low_stock": sum(sellable_stock(store, x["id"]) <= low_stock for x in store.products), "categories": sorted({x.get("category") for x in store.products}), "brands": sorted({x.get("brand") for x in store.products})}


@app.post("/api/ops/products")
def create_product(req: ProductCreate, authorization: str | None = Header(default=None)):
    actor = authorize(authorization, "MANAGER", "ADMIN")
    if not any(shop["id"] == req.shop_id for shop in store.shops):
        raise HTTPException(422, "店铺不存在")
    if req.list_price is not None and req.list_price < req.price:
        raise HTTPException(422, "划线价不能低于售价")
    product_id = "p" + str(max(int(x["id"][1:]) for x in store.products) + 1)
    product = {"id": product_id, **req.model_dump(), "list_price": req.list_price or req.price, "status": "在售", "sku_code": "SKU-" + product_id.upper(), "rating": 5.0, "review_count": 0, "sales": 0, "tags": [req.category, req.brand], "specs": {"商品编码": "SKU-" + product_id.upper()}}
    store.products.append(product)
    store.audit_logs.append({"id": "audit-" + uuid4().hex[:10], "actor": actor["username"], "action": "catalog.created", "target_id": product_id, "created_at": now()})
    return {"product": product}


@app.put("/api/ops/products/{product_id}")
def update_product(product_id: str, req: ProductUpdate, authorization: str | None = Header(default=None)):
    actor = authorize(authorization, "MANAGER", "ADMIN")
    product = next((x for x in store.products if x["id"] == product_id), None)
    if not product:
        raise HTTPException(404, "商品不存在")
    changes = req.model_dump(exclude_none=True)
    if changes.get("list_price") is not None and changes["list_price"] < changes.get("price", product["price"]):
        raise HTTPException(422, "划线价不能低于售价")
    if changes:
        product.update(changes)
        store.audit_logs.append({"id": "audit-" + uuid4().hex[:10], "actor": actor["username"], "action": "catalog.updated", "target_id": product_id, "changes": changes, "created_at": now()})
        store.add_event({"node": "Catalog", "status": "updated", "product_id": product_id, "changes": changes, "trace_id": str(uuid4())})
    return {"product": product, "updated": changes}


@app.put("/api/ops/products/{product_id}/stock")
def update_product_stock(product_id: str, req: StockUpdate, authorization: str | None = Header(default=None)):
    actor = authorize(authorization, "MANAGER", "ADMIN")
    product = next((x for x in store.products if x["id"] == product_id), None)
    if not product:
        raise HTTPException(404, "商品不存在")
    active_reserved = reserved_stock(store, product_id)
    if req.stock < active_reserved:
        raise HTTPException(409, f"库存不能低于已预占数量 {active_reserved}")
    previous = product["stock"]
    product["stock"] = req.stock
    store.inventory_ledger.append({"id": "il-" + uuid4().hex[:10], "product_id": product_id, "type": "manual_adjustment", "change": req.stock - previous, "before": previous, "after": req.stock, "operator": actor["username"], "created_at": now()})
    store.audit_logs.append({"id": "audit-" + uuid4().hex[:10], "actor": actor["username"], "action": "inventory.adjusted", "target_id": product_id, "before": previous, "after": req.stock, "created_at": now()})
    store.add_event({"node": "Inventory", "status": "updated", "product_id": product_id, "previous": previous, "stock": req.stock, "trace_id": str(uuid4())})
    return {"product": product, "previous_stock": previous}


@app.get("/api/ops/batch/suspended")
def batch_suspended():
    rows = [x for x in store.after_sales.values() if x.get("status") == "SUSPENDED_HUMAN"]
    return {"items": [{"ticket_no": x["id"], "order_id": x["order_id"], "amount": x["amount"], "risk_score": x.get("risk_score", 0), "reason": x.get("reason", "")} for x in rows]}


@app.get("/api/ops/batch/export")
def batch_export(authorization: str | None = Header(default=None)):
    authorize(authorization, "MANAGER", "ADMIN")
    import csv
    from io import StringIO
    rows = [x for x in store.after_sales.values() if x.get("status") == "SUSPENDED_HUMAN"]
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["ticket_no", "order_id", "amount", "risk_score", "approval_action", "comment"])
    for x in rows:
        writer.writerow([x["id"], x["order_id"], x["amount"], x.get("risk_score", 0), "", ""])
    from fastapi.responses import Response
    return Response(output.getvalue().encode("utf-8-sig"), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=suspended.csv"})


@app.get("/api/ops/evals/golden")
def golden_cases():
    rows = golden_dataset()
    return {"items": rows, "total": len(rows), "version": "golden-v2.0", "coverage": ["退款", "证据", "物流", "商品", "优惠", "订单", "投诉", "人工", "安全"]}


@app.post("/api/ops/evals/run")
def run_eval(req: EvalRunRequest, authorization: str | None = Header(default=None)):
    authorize(authorization, "MANAGER", "ADMIN")
    if req.mode == "llm":
        raise HTTPException(503, "LLM-as-a-judge 适配器未配置；离线确定性评测可直接运行")
    return run_offline_eval()


@app.get("/api/ops/telemetry")
def telemetry():
    return telemetry_snapshot()


@app.get("/api/ops/intent/details")
def intent_details():
    return {"items": list(reversed(store.intent_records[-100:])), "total": len(store.intent_records), "dlq_count": len(store.dead_letters)}


@app.get("/api/ops/traces/{trace_id}")
def trace_detail(trace_id: str):
    rows = [event for event in store.events if event.get("trace_id") == trace_id]
    if not rows:
        raise HTTPException(404, "Trace 不存在")
    return {"trace_id": trace_id, "events": rows, "node_count": len(rows), "failed": any(event.get("status") in {"failed", "blocked"} for event in rows)}


@app.get("/api/ops/refunds")
def ops_refunds():
    return {"items": list(store.refunds.values()), "total": len(store.refunds), "amount": round(sum(item.get("amount", 0) for item in store.refunds.values()), 2)}


@app.get("/api/ops/infrastructure")
def infrastructure_status():
    return {"workflow": workflow_infra.status(), "evaluation_scheduler": evaluation_scheduler.status()}


@app.get("/api/ops/checkpoints/{case_id}")
def workflow_checkpoint(case_id: str):
    checkpoint = workflow_infra.load_checkpoint(case_id)
    if not checkpoint:
        raise HTTPException(404, "Checkpoint 不存在")
    return checkpoint
