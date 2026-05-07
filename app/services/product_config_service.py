from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from urllib.request import urlopen, Request

from sqlalchemy.orm import Session

from app.core.products import (
    ALL_PRODUCTS,
    DEFAULT_USD_CNY_RATE,
    PRODUCTS,
    Product,
    cost_cny_from_usd,
    get_product,
    profit_cny_from_price_and_cost,
)
from app.models.entities import ProductConfigSnapshot


_RATE_CACHE: dict = {"rate": None, "source": "fallback", "updated_at": None, "expires_at": 0, "error": None}


def _manual_usd_cny_rate() -> float | None:
    """读取手动备用汇率。

    Render 环境变量可设置：
    - USD_CNY_RATE：手动固定汇率
    - USDT_CNY_RATE：兼容旧配置
    """
    raw = os.getenv("USD_CNY_RATE", "") or os.getenv("USDT_CNY_RATE", "")
    try:
        value = float(raw)
        if value > 0:
            return value
    except Exception:
        pass
    return None


def _fetch_json(url: str, timeout: int = 6) -> dict:
    req = Request(url, headers={"User-Agent": "membership-agent/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch_live_usd_cny_rate() -> tuple[float, str]:
    """从公开汇率接口获取实时 USD/CNY。

    使用多个免费接口做兜底，不影响订单、支付、发货主流程。
    接口失败时调用方会自动回退到环境变量或默认汇率。
    """
    sources = [
        ("open.er-api.com", "https://open.er-api.com/v6/latest/USD"),
        ("frankfurter.app", "https://api.frankfurter.app/latest?from=USD&to=CNY"),
        ("floatrates.com", "https://www.floatrates.com/daily/usd.json"),
    ]

    last_error = None
    for source, url in sources:
        try:
            data = _fetch_json(url)
            rate = None
            if source == "open.er-api.com":
                rate = (data.get("rates") or {}).get("CNY")
            elif source == "frankfurter.app":
                rate = (data.get("rates") or {}).get("CNY")
            elif source == "floatrates.com":
                rate = ((data.get("cny") or {}).get("rate"))

            rate = float(rate)
            if 5 <= rate <= 9:
                return round(rate, 4), source
        except Exception as e:
            last_error = str(e)
            continue

    raise RuntimeError(last_error or "实时汇率获取失败")


def get_exchange_rate_info(force_refresh: bool = False) -> dict:
    """返回汇率详情。

    默认每 30 分钟缓存一次实时汇率。
    如果实时接口失败，则使用环境变量 USD_CNY_RATE / USDT_CNY_RATE；
    如果环境变量也没有，则使用 DEFAULT_USD_CNY_RATE。
    """
    now = time.time()
    ttl = int(os.getenv("EXCHANGE_RATE_CACHE_SECONDS", "1800") or 1800)

    if not force_refresh and _RATE_CACHE.get("rate") and now < float(_RATE_CACHE.get("expires_at") or 0):
        return dict(_RATE_CACHE)

    mode = (os.getenv("EXCHANGE_RATE_MODE", "live") or "live").lower().strip()
    manual_rate = _manual_usd_cny_rate()

    if mode == "manual":
        rate = manual_rate or DEFAULT_USD_CNY_RATE
        info = {
            "rate": round(float(rate), 4),
            "source": "manual" if manual_rate else "fallback",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": now + ttl,
            "error": None,
        }
        _RATE_CACHE.update(info)
        return dict(_RATE_CACHE)

    try:
        rate, source = _fetch_live_usd_cny_rate()
        info = {
            "rate": rate,
            "source": source,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": now + ttl,
            "error": None,
        }
    except Exception as e:
        rate = manual_rate or DEFAULT_USD_CNY_RATE
        info = {
            "rate": round(float(rate), 4),
            "source": "manual_fallback" if manual_rate else "default_fallback",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": now + min(ttl, 300),
            "error": str(e),
        }

    _RATE_CACHE.update(info)
    return dict(_RATE_CACHE)


def get_usd_cny_rate(force_refresh: bool = False) -> float:
    """返回后台利润核算使用的美元兑人民币汇率。"""
    info = get_exchange_rate_info(force_refresh=force_refresh)
    try:
        return float(info.get("rate") or DEFAULT_USD_CNY_RATE)
    except Exception:
        return DEFAULT_USD_CNY_RATE


def product_to_dict(product: Product) -> dict:
    rate_info = get_exchange_rate_info()
    rate = float(rate_info.get("rate") or DEFAULT_USD_CNY_RATE)
    cost_usd = float(product.cost_usd or 0)
    price_cny = int(product.price_cny or 0)
    return {
        "code": product.code,
        "category": product.category,
        "name": product.name,
        "price_cny": price_cny,
        "amount_usd": float(product.amount_usd or 0),
        "cost_usd": cost_usd,
        "cost_cny": cost_cny_from_usd(cost_usd, rate),
        "profit_cny": profit_cny_from_price_and_cost(price_cny, cost_usd, rate),
        "exchange_rate": rate,
        "exchange_rate_source": rate_info.get("source"),
        "exchange_rate_updated_at": rate_info.get("updated_at"),
        "exchange_rate_error": rate_info.get("error"),
        "period": product.period,
        "period_days": int(product.period_days or 30),
        "inventory": bool(product.inventory),
        "badge": getattr(product, "badge", "") or "",
        "desc": getattr(product, "desc", "") or "",
        "legacy": bool(getattr(product, "legacy", False)),
        "is_active": True,
        "sort_order": 0,
    }


def latest_product_overrides(db: Session) -> dict[str, ProductConfigSnapshot]:
    """返回每个产品最新的一条后台配置。只读，不影响静态产品配置。"""
    rows = (
        db.query(ProductConfigSnapshot)
        .order_by(ProductConfigSnapshot.product_code.asc(), ProductConfigSnapshot.id.desc())
        .all()
    )
    result: dict[str, ProductConfigSnapshot] = {}
    for row in rows:
        code = str(row.product_code or "").upper()
        if code and code not in result:
            result[code] = row
    return result


def _float_or_default(value, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def merge_product_with_override(product: Product, override: ProductConfigSnapshot | None) -> dict:
    data = product_to_dict(product)
    if override:
        if override.product_name:
            data["name"] = override.product_name
        if override.category:
            data["category"] = override.category
        if override.price_cny is not None:
            data["price_cny"] = int(override.price_cny or 0)
        if override.amount_usd is not None and str(override.amount_usd) != "":
            data["amount_usd"] = _float_or_default(override.amount_usd, data.get("amount_usd", 0))
        if hasattr(override, "cost_usd") and override.cost_usd is not None and str(override.cost_usd) != "":
            data["cost_usd"] = _float_or_default(override.cost_usd, data.get("cost_usd", 0))
        if override.period:
            data["period"] = override.period
        if override.inventory is not None:
            data["inventory"] = bool(int(override.inventory or 0))
        if override.is_active is not None:
            data["is_active"] = bool(int(override.is_active or 0))
        data["updated_by"] = override.updated_by
        data["updated_at"] = str(override.updated_at) if override.updated_at else None

    rate_info = get_exchange_rate_info()
    rate = float(rate_info.get("rate") or DEFAULT_USD_CNY_RATE)
    data["exchange_rate"] = rate
    data["exchange_rate_source"] = rate_info.get("source")
    data["exchange_rate_updated_at"] = rate_info.get("updated_at")
    data["exchange_rate_error"] = rate_info.get("error")
    data["cost_cny"] = cost_cny_from_usd(data.get("cost_usd", 0), rate)
    data["profit_cny"] = profit_cny_from_price_and_cost(data.get("price_cny", 0), data.get("cost_usd", 0), rate)
    return data


def list_products_for_admin(db: Session, include_legacy: bool = True) -> list[dict]:
    overrides = latest_product_overrides(db)
    source = ALL_PRODUCTS if include_legacy else PRODUCTS
    return [merge_product_with_override(p, overrides.get(p.code.upper())) for p in source]


def list_products_for_public(db: Session) -> list[dict]:
    items = list_products_for_admin(db, include_legacy=False)
    public_items = []
    for item in items:
        if not item.get("is_active", True) or item.get("legacy"):
            continue
        safe = dict(item)
        # 成本和利润只允许后台查看，不返回给前台。
        safe.pop("cost_usd", None)
        safe.pop("cost_cny", None)
        safe.pop("profit_cny", None)
        safe.pop("exchange_rate", None)
        public_items.append(safe)
    return public_items


def get_product_config(db: Session, code: str | None) -> dict | None:
    product = get_product(code)
    if not product:
        return None
    override = latest_product_overrides(db).get(product.code.upper())
    return merge_product_with_override(product, override)


def product_name_db(db: Session, code: str | None) -> str:
    data = get_product_config(db, code)
    if not data:
        return str(code or "-") or "-"
    return f"{data.get('category') or '-'} - {data.get('name') or code}"


def product_price_cny_db(db: Session, code: str | None, default: int = 0) -> int:
    data = get_product_config(db, code)
    if not data:
        return default
    try:
        return int(data.get("price_cny") or 0)
    except Exception:
        return default


def product_amount_usd_db(db: Session, code: str | None, default: float = 20) -> float:
    data = get_product_config(db, code)
    if not data:
        return default
    try:
        return float(data.get("amount_usd") or 0)
    except Exception:
        return default


def product_cost_usd_db(db: Session, code: str | None, default: float = 0) -> float:
    data = get_product_config(db, code)
    if not data:
        return default
    try:
        return float(data.get("cost_usd") or 0)
    except Exception:
        return default


def upsert_product_config(
    db: Session,
    *,
    product_code: str,
    product_name: str,
    category: str,
    price_cny: int,
    amount_usd: float,
    cost_usd: float,
    period: str,
    inventory: bool,
    is_active: bool,
    updated_by: str,
) -> ProductConfigSnapshot:
    code = str(product_code or "").upper().strip()
    if not get_product(code):
        raise ValueError("产品代码不存在")
    item = ProductConfigSnapshot(
        product_code=code,
        product_name=str(product_name or "").strip(),
        category=str(category or "").strip(),
        price_cny=int(price_cny or 0),
        amount_usd=str(amount_usd or 0),
        cost_usd=str(cost_usd or 0),
        period=str(period or "").strip(),
        inventory=1 if inventory else 0,
        is_active=1 if is_active else 0,
        updated_by=updated_by,
        updated_at=datetime.utcnow(),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item
