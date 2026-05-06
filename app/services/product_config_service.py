from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Iterable

from sqlalchemy.orm import Session

from app.core.products import PRODUCTS, ALL_PRODUCTS, Product, get_product
from app.models.entities import ProductConfigSnapshot


def product_to_dict(product: Product) -> dict:
    return {
        "code": product.code,
        "category": product.category,
        "name": product.name,
        "price_cny": int(product.price_cny or 0),
        "amount_usd": float(product.amount_usd or 0),
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
            try:
                data["amount_usd"] = float(override.amount_usd)
            except Exception:
                data["amount_usd"] = override.amount_usd
        if override.period:
            data["period"] = override.period
        if override.inventory is not None:
            data["inventory"] = bool(int(override.inventory or 0))
        if override.is_active is not None:
            data["is_active"] = bool(int(override.is_active or 0))
        data["updated_by"] = override.updated_by
        data["updated_at"] = str(override.updated_at) if override.updated_at else None
    return data


def list_products_for_admin(db: Session, include_legacy: bool = True) -> list[dict]:
    overrides = latest_product_overrides(db)
    source = ALL_PRODUCTS if include_legacy else PRODUCTS
    return [merge_product_with_override(p, overrides.get(p.code.upper())) for p in source]


def list_products_for_public(db: Session) -> list[dict]:
    items = list_products_for_admin(db, include_legacy=False)
    return [i for i in items if i.get("is_active", True) and not i.get("legacy")]


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


def upsert_product_config(
    db: Session,
    *,
    product_code: str,
    product_name: str,
    category: str,
    price_cny: int,
    amount_usd: float,
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
