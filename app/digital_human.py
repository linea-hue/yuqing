"""Digital human integration adapter.

The browser talks to our API only. Provider credentials never reach the
frontend. Supported providers are browser fallback, HeyGen, and D-ID.
"""
from __future__ import annotations

import json
import os
import base64
from pathlib import Path
from uuid import uuid4
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from .rag import grounded_answer
from .security import inspect_input
from .store import store


def _load_local_env() -> None:
    """Load simple KEY=VALUE pairs without requiring an extra dotenv package."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


_load_local_env()


def product_script(product: dict) -> str:
    specs = product.get("specs") or {}
    spec_text = "，".join(f"{k}{v}" for k, v in list(specs.items())[:4])
    tags = "、".join(product.get("tags") or [])
    parts = [f"大家好，今天为你介绍 {product.get('name', '这款商品')}。"]
    if product.get("brand"):
        parts.append(f"它来自 {product['brand']}。")
    if product.get("description"):
        parts.append(str(product["description"]).rstrip("。") + "。")
    if spec_text:
        parts.append(f"核心规格包括：{spec_text}。")
    if tags:
        parts.append(f"适合关注{tags}的用户。")
    if product.get("price") is not None:
        parts.append(f"当前售价为 {float(product['price']):.2f} 元。")
    parts.append("支持 7 天无理由退货，支付后通常 48 小时内发货。你可以继续问我规格、适用人群或售后问题。")
    return "".join(parts)


def _provider_configured() -> bool:
    provider = os.getenv("DIGITAL_HUMAN_PROVIDER", "generic").lower()
    if provider == "heygen":
        return bool(os.getenv("HEYGEN_API_KEY") and os.getenv("HEYGEN_AVATAR_ID"))
    if provider == "did":
        return bool(os.getenv("DID_API_KEY") and os.getenv("DID_SOURCE_URL"))
    return bool(os.getenv("DIGITAL_HUMAN_API_URL") and os.getenv("DIGITAL_HUMAN_API_KEY"))


def provider_configured() -> bool:
    """Expose provider availability without triggering a remote generation request."""
    return _provider_configured()


def speak(script: str, product: dict | None = None) -> dict:
    """Send text to the configured provider, or return local fallback metadata."""
    if not _provider_configured():
        return {
            "provider": "browser_fallback",
            "configured": False,
            "script": script,
            "message": "未配置数字人服务，当前使用浏览器语音播报。配置 D-ID 或其他数字人服务后可生成真人讲解视频。",
        }
    if os.getenv("DIGITAL_HUMAN_PROVIDER", "generic").lower() in {"heygen", "did"}:
        return render_video(script, product)
    payload = {
        "text": script,
        "avatar_id": os.getenv("DIGITAL_HUMAN_AVATAR_ID", "default"),
        "product_id": (product or {}).get("id"),
        "provider": os.getenv("DIGITAL_HUMAN_PROVIDER", "generic"),
    }
    request = Request(
        os.environ["DIGITAL_HUMAN_API_URL"],
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {os.environ['DIGITAL_HUMAN_API_KEY']}"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
        return {"provider": os.getenv("DIGITAL_HUMAN_PROVIDER", "generic"), "configured": True, "script": script, "result": result}
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        return {"provider": os.getenv("DIGITAL_HUMAN_PROVIDER", "generic"), "configured": True, "script": script, "error": str(exc), "fallback": True}


def render_video(script: str, product: dict | None = None) -> dict:
    """Create a generated avatar video through the configured provider."""
    provider = os.getenv("DIGITAL_HUMAN_PROVIDER", "generic").lower()
    if provider == "did":
        return _render_did_video(script, product)
    if provider != "heygen":
        return speak(script, product)
    if not _provider_configured():
        return {"provider": "heygen", "configured": False, "script": script, "message": "请配置 HEYGEN_API_KEY 和 HEYGEN_AVATAR_ID。"}
    payload = {
        "type": "avatar",
        "avatar_id": os.environ["HEYGEN_AVATAR_ID"],
        "title": f"商品讲解 - {(product or {}).get('name', '甄选商品')}",
        "aspect_ratio": os.getenv("HEYGEN_ASPECT_RATIO", "9:16"),
        "output_format": "mp4",
        "script": script,
    }
    if os.getenv("HEYGEN_VOICE_ID"):
        payload["voice_id"] = os.environ["HEYGEN_VOICE_ID"]
    if os.getenv("HEYGEN_CALLBACK_URL"):
        payload["callback_url"] = os.environ["HEYGEN_CALLBACK_URL"]
        payload["callback_id"] = (product or {}).get("id")
    request = Request(
        os.getenv("HEYGEN_API_URL", "https://api.heygen.com/v3/videos"),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": os.environ["HEYGEN_API_KEY"],
            "Idempotency-Key": f"product-{(product or {}).get('id', 'demo')}-{uuid4().hex}",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
        data = result.get("data", result)
        return {"provider": "heygen", "configured": True, "mode": "video", "script": script, "video_id": data.get("video_id"), "status": data.get("status", "waiting"), "result": result}
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        return {"provider": "heygen", "configured": True, "script": script, "error": str(exc), "fallback": True}


def _did_auth_header() -> str:
    """D-ID accepts Basic auth; support both raw user:password and pre-encoded keys."""
    key = os.environ["DID_API_KEY"].strip()
    if ":" in key:
        key = base64.b64encode(key.encode("utf-8")).decode("ascii")
    return f"Basic {key}"


def _http_error_message(exc: HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8", errors="replace")
        parsed = json.loads(body)
        return str(parsed.get("message") or parsed.get("error") or body[:500])
    except (ValueError, OSError):
        return str(exc)


def _render_did_video(script: str, product: dict | None = None) -> dict:
    """Create an asynchronous D-ID talk from the configured public avatar image."""
    if not _provider_configured():
        return {
            "provider": "did",
            "configured": False,
            "script": script,
            "message": "请配置 DID_API_KEY 和 DID_SOURCE_URL。DID_SOURCE_URL 必须是公网 HTTPS 图片地址。",
        }
    voice_id = os.getenv("DID_VOICE_ID", "zh-CN-XiaoxiaoNeural")
    payload = {
        "source_url": os.environ["DID_SOURCE_URL"],
        "script": {
            "type": "text",
            "input": script,
            "provider": {
                "type": os.getenv("DID_VOICE_PROVIDER", "microsoft"),
                "voice_id": voice_id,
            },
        },
        "config": {"fluent": True, "pad_audio": 0},
    }
    request = Request(
        os.getenv("DID_API_URL", "https://api.d-id.com/talks"),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": _did_auth_header(),
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
        return {
            "provider": "did",
            "configured": True,
            "mode": "video",
            "script": script,
            "video_id": result.get("id"),
            "status": result.get("status", "created"),
            "result": result,
        }
    except HTTPError as exc:
        return {"provider": "did", "configured": True, "script": script, "error": _http_error_message(exc), "fallback": True}
    except (URLError, TimeoutError, ValueError) as exc:
        return {"provider": "did", "configured": True, "script": script, "error": str(exc), "fallback": True}


def video_status(video_id: str) -> dict:
    provider = os.getenv("DIGITAL_HUMAN_PROVIDER", "generic").lower()
    if provider == "did":
        return _did_video_status(video_id)
    if provider != "heygen" or not os.getenv("HEYGEN_API_KEY"):
        return {"provider": "browser_fallback", "configured": False, "status": "unsupported"}
    request = Request(
        f"{os.getenv('HEYGEN_API_BASE_URL', 'https://api.heygen.com')}/v3/videos/{video_id}",
        headers={"x-api-key": os.environ["HEYGEN_API_KEY"]},
        method="GET",
    )
    try:
        with urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
        data = result.get("data", result)
        return {"provider": "heygen", "configured": True, "video_id": video_id, "status": data.get("status"), "video_url": data.get("video_url"), "thumbnail_url": data.get("thumbnail_url"), "result": result}
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        return {"provider": "heygen", "configured": True, "video_id": video_id, "error": str(exc)}


def _did_video_status(video_id: str) -> dict:
    if not os.getenv("DID_API_KEY"):
        return {"provider": "did", "configured": False, "video_id": video_id, "status": "unsupported"}
    request = Request(
        f"{os.getenv('DID_API_BASE_URL', 'https://api.d-id.com')}/talks/{video_id}",
        headers={"Accept": "application/json", "Authorization": _did_auth_header()},
        method="GET",
    )
    try:
        with urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
        return {
            "provider": "did",
            "configured": True,
            "video_id": video_id,
            "status": result.get("status"),
            "video_url": result.get("result_url"),
            "thumbnail_url": result.get("gif_url"),
            "result": result,
        }
    except HTTPError as exc:
        return {"provider": "did", "configured": True, "video_id": video_id, "error": _http_error_message(exc)}
    except (URLError, TimeoutError, ValueError) as exc:
        return {"provider": "did", "configured": True, "video_id": video_id, "error": str(exc)}


def answer_question(question: str, product: dict | None = None) -> dict:
    """Ground a product question in the existing RAG knowledge base."""
    safe = inspect_input(question)
    if safe.blocked:
        return {"blocked": True, "answer": "这个问题无法处理，我可以继续为你介绍商品规格、价格和售后规则。", "references": []}
    if product:
        text = safe.text.strip()
        specs = product.get("specs") or {}
        spec_text = "、".join(f"{key}{value}" for key, value in specs.items())
        tags = "、".join(product.get("tags") or [])
        if any(term in text for term in ("适合", "人群", "谁用", "用途", "场景")):
            answer = f"这款{product.get('name', '商品')}更适合关注{tags or product.get('category', '这类商品')}的用户。"
            if product.get("description"):
                answer += f"它的主要使用场景是：{str(product['description']).rstrip('。')}。"
            return {"blocked": False, "answer": answer, "references": [], "grounded": True}
        if any(term in text for term in ("规格", "参数", "配置", "尺寸", "容量", "续航")):
            return {
                "blocked": False,
                "answer": f"这款商品的核心参数是：{spec_text or product.get('description', '以详情页为准')}。",
                "references": [],
                "grounded": True,
            }
        if any(term in text for term in ("价格", "多少钱", "售价", "到手价")):
            return {"blocked": False, "answer": f"当前售价是 {float(product.get('price', 0)):.2f} 元。", "references": [], "grounded": True}
        if any(term in text for term in ("库存", "有货", "现货")):
            return {"blocked": False, "answer": f"当前可售库存约 {product.get('stock', 0)} 件。", "references": [], "grounded": True}
    context = f"当前商品：{product.get('name')}。商品信息：{product.get('description', '')}。用户问题：{safe.text}" if product else safe.text
    grounded = grounded_answer(context, role="buyer")
    answer = grounded.get("answer") or "我暂时没有找到相关信息，可以换个方式问我商品规格、库存或售后。"
    return {"blocked": False, "answer": answer, "references": grounded.get("references", []), "grounded": grounded.get("grounded", False)}


def recommend(question: str, product: dict | None = None) -> list[dict]:
    terms = set((question or "").lower())
    candidates = [x for x in store.products if x.get("status", "在售") == "在售"]
    if product:
        candidates = [x for x in candidates if x.get("id") != product.get("id")]
    scored = []
    for item in candidates:
        haystack = " ".join([str(item.get("name", "")), str(item.get("description", "")), " ".join(item.get("tags") or []), str(item.get("category", ""))]).lower()
        score = sum(1 for term in terms if len(term) > 1 and term in haystack)
        score += 0.01 * float(item.get("rating", 0))
        scored.append((score, item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored[:3]]
